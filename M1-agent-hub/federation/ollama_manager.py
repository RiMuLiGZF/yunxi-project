"""
Ollama 模型管理器 — OllamaModelManager
=========================================

管理本地 Ollama 模型的热加载/热卸载，实现：
  - 按需加载：首次调用时才加载模型到显存
  - 空闲卸载：超过 TTL 未使用则卸载释放显存
  - 状态查询：当前已加载模型、显存占用
  - 并发控制：同时加载的模型数不超过上限

设计目标：在 8GB 显存的笔记本上，让多个 Agent 分时复用模型。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class OllamaModelManager:
    """Ollama 模型热加载管理器

    原理：
      - Ollama 模型加载到显存后，空闲 5 分钟会自动卸载（Ollama 内置）
      - 我们在此基础上增加更精细的控制：主动卸载、并发限制、优先级管理

    使用场景：
      - 多个 Agent 共享同一个 Ollama 实例
      - 显存有限，需要分时复用不同模型
      - Agent 空闲时自动释放模型资源
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        max_concurrent_models: int = 2,        # 同时加载的最大模型数
        idle_ttl: float = 180.0,               # 空闲超时（秒），默认3分钟
        check_interval: float = 30.0,          # 空闲检测间隔（秒）
        warmup_models: list[str] | None = None, # 启动时预热的模型
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._max_concurrent = max_concurrent_models
        self._idle_ttl = idle_ttl
        self._check_interval = check_interval

        # 模型状态追踪
        self._model_last_used: dict[str, float] = {}   # model_name -> last_used_ts
        self._model_load_count: dict[str, int] = {}    # model_name -> 引用计数
        self._loading_locks: dict[str, asyncio.Lock] = {}

        # 后台任务
        self._cleanup_task: asyncio.Task | None = None
        self._running = False

        # HTTP 客户端
        self._client: httpx.AsyncClient | None = None

        self._logger = logger.bind(component="ollama_model_manager")

    # ── 生命周期 ──────────────────────────────────────────

    async def start(self) -> None:
        """启动管理器（初始化客户端+启动空闲检测）"""
        if self._running:
            return

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=30.0,
        )
        self._running = True

        # 启动空闲清理任务
        self._cleanup_task = asyncio.create_task(self._idle_cleanup_loop())
        self._logger.info(
            "ollama_manager_started",
            max_concurrent=self._max_concurrent,
            idle_ttl=self._idle_ttl,
        )

    async def stop(self) -> None:
        """停止管理器"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        if self._client:
            await self._client.aclose()
            self._client = None

        self._logger.info("ollama_manager_stopped")

    # ── 核心 API ──────────────────────────────────────────

    async def ensure_model(self, model_name: str) -> bool:
        """确保模型已加载（按需加载）

        Returns:
            True 表示模型可用，False 表示加载失败
        """
        if not self._running or not self._client:
            # 管理器未启动，假设模型可用（降级）
            return True

        # 检查模型是否已经可用
        if await self._is_model_loaded(model_name):
            self._model_last_used[model_name] = time.time()
            return True

        # 需要加载，用锁防止并发加载同一个模型
        lock = self._loading_locks.setdefault(model_name, asyncio.Lock())
        async with lock:
            # 双重检查
            if await self._is_model_loaded(model_name):
                self._model_last_used[model_name] = time.time()
                return True

            # 检查并发限制，如果超限先卸载最久不用的
            await self._evict_if_needed()

            # 加载模型
            success = await self._load_model(model_name)
            if success:
                self._model_last_used[model_name] = time.time()
                self._logger.info("model_loaded", model=model_name)

            return success

    async def release_model(self, model_name: str) -> None:
        """主动释放模型（减少引用计数，归零则可卸载）"""
        if model_name in self._model_last_used:
            self._model_last_used[model_name] = time.time()  # 更新时间，由 idle 清理

    async def list_loaded_models(self) -> list[dict[str, Any]]:
        """列出当前已加载的模型"""
        if not self._client:
            return []

        try:
            resp = await self._client.get("/api/ps")
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                return [
                    {
                        "name": m.get("name", ""),
                        "size_vram": m.get("size_vram", 0),
                        "size": m.get("size", 0),
                        "digest": m.get("digest", ""),
                    }
                    for m in models
                ]
        except Exception as exc:
            self._logger.debug("list_models_failed", error=str(exc))

        return []

    async def get_vram_usage(self) -> dict[str, Any]:
        """获取 VRAM 使用情况"""
        models = await self.list_loaded_models()
        total_vram = sum(m.get("size_vram", 0) for m in models)
        return {
            "loaded_models": len(models),
            "total_vram_bytes": total_vram,
            "total_vram_gb": round(total_vram / (1024**3), 2),
            "models": [m["name"] for m in models],
        }

    # ── 内部方法 ──────────────────────────────────────────

    async def _is_model_loaded(self, model_name: str) -> bool:
        """检查模型是否已加载"""
        models = await self.list_loaded_models()
        for m in models:
            # Ollama 模型名可能带 tag，做前缀匹配
            if m["name"].startswith(model_name) or model_name.startswith(m["name"].split(":")[0]):
                return True
        return False

    async def _load_model(self, model_name: str) -> bool:
        """加载模型到显存（通过 /api/generate 空请求触发）"""
        if not self._client:
            return False

        try:
            # Ollama 有个技巧：发一个空的 generate 请求可以触发模型加载
            resp = await self._client.post(
                "/api/generate",
                json={
                    "model": model_name,
                    "prompt": "",
                    "stream": False,
                    "options": {"num_predict": 1},
                },
                timeout=120.0,  # 加载模型可能需要时间
            )
            return resp.status_code == 200
        except Exception as exc:
            self._logger.warning("model_load_failed", model=model_name, error=str(exc))
            return False

    async def _unload_model(self, model_name: str) -> bool:
        """卸载模型（Ollama 没有直接的卸载 API，靠空闲超时）

        我们通过设置一个极短的 keep_alive 来触发立即卸载。
        """
        if not self._client:
            return False

        try:
            # 用 keep_alive=0s 让 Ollama 立即卸载模型
            resp = await self._client.post(
                "/api/generate",
                json={
                    "model": model_name,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": "0s",
                    "options": {"num_predict": 1},
                },
                timeout=30.0,
            )
            if resp.status_code == 200:
                self._model_last_used.pop(model_name, None)
                self._logger.info("model_unloaded", model=model_name)
                return True
            return False
        except Exception as exc:
            self._logger.debug("model_unload_failed", model=model_name, error=str(exc))
            return False

    async def _evict_if_needed(self) -> None:
        """如果已加载模型数超限，卸载最久未使用的"""
        loaded = await self.list_loaded_models()
        if len(loaded) < self._max_concurrent:
            return

        # 按最后使用时间排序，卸载最久的
        sorted_models = sorted(
            self._model_last_used.keys(),
            key=lambda m: self._model_last_used.get(m, 0)
        )

        while len(loaded) >= self._max_concurrent and sorted_models:
            oldest = sorted_models.pop(0)
            await self._unload_model(oldest)
            loaded = await self.list_loaded_models()

    async def _idle_cleanup_loop(self) -> None:
        """后台空闲清理循环"""
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)
                await self._cleanup_idle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._logger.error("idle_cleanup_error", error=str(exc))

    async def _cleanup_idle(self) -> int:
        """清理空闲超时的模型，返回清理数量"""
        now = time.time()
        cleaned = 0

        for model_name in list(self._model_last_used.keys()):
            last_used = self._model_last_used[model_name]
            if now - last_used > self._idle_ttl:
                if await self._unload_model(model_name):
                    cleaned += 1

        if cleaned > 0:
            self._logger.info("idle_models_cleaned", count=cleaned)

        return cleaned

    # ── 统计信息 ──────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "tracked_models": len(self._model_last_used),
            "max_concurrent": self._max_concurrent,
            "idle_ttl": self._idle_ttl,
            "check_interval": self._check_interval,
        }
