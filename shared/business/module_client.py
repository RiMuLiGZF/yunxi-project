"""
云汐系统模块客户端
统一管理所有模块的注册、发现和通信
"""

import os
import sys
import time
import asyncio
import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from shared.config import get_config
from shared.cache import SimpleCache, get_path_ttl, get_cache_from_env

# 结构化日志：优先 structlog，缺失时回退到 stdlib logging
try:
    import structlog

    _slog = structlog.get_logger("yunxi.module")
    _HAS_STRUCTLOG = True
except Exception:  # pragma: no cover - structlog 为本项目硬依赖，此处仅为兜底
    import logging

    _slog = logging.getLogger("yunxi.module")
    _HAS_STRUCTLOG = False


def _log_event(level: str, event: str, **kwargs: Any) -> None:
    """统一日志调用，兼容 structlog 与 stdlib logging。"""
    if _HAS_STRUCTLOG:
        getattr(_slog, level)(event, **kwargs)
    else:
        getattr(_slog, level)(f"{event} {kwargs}")


def _is_dev_env() -> bool:
    """判断是否为开发环境（mock 仅在开发环境生效）。"""
    env = (
        os.getenv("YUNXI_ENV")
        or os.getenv("APP_ENV")
        or os.getenv("ENV")
        or "development"
    )
    return env.lower() != "production"


class ModuleKey(str, Enum):
    """模块键枚举，统一管理所有模块的 key"""

    M0 = "m0"  # 主理人管控台
    M1 = "m1"  # 代理集群
    M2 = "m2"  # 技能集群
    M3 = "m3"  # 边缘云端
    M4 = "m4"  # 场景引擎
    M5 = "m5"  # 潮汐记忆
    M6 = "m6"  # 硬件外设
    M7 = "m7"  # 工作流构建器
    M8 = "m8"  # 控制塔
    M10 = "m10"  # 系统卫士


class ModuleCategory(str, Enum):
    """模块分类枚举"""

    CONTROL = "control"  # 管控类
    CORE = "core"  # 核心能力类
    TOOL = "tool"  # 工具类
    INFRA = "infra"  # 基础设施类


class ModuleInfo:
    """模块信息类"""

    def __init__(
        self,
        key: str,
        name: str,
        version: str,
        port: int,
        base_url: str,
        description: str = "",
        health_endpoint: str = "/health",
        category: str = "core",
    ):
        self.key = key
        self.name = name
        self.version = version
        self.port = port
        self.base_url = base_url
        self.description = description
        self.health_endpoint = health_endpoint
        self.category = category
        self.status = "unknown"  # unknown / running / stopped / error

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "key": self.key,
            "name": self.name,
            "version": self.version,
            "port": self.port,
            "base_url": self.base_url,
            "description": self.description,
            "health_endpoint": self.health_endpoint,
            "category": self.category,
            "status": self.status,
        }


class ModuleClient:
    """模块 HTTP 客户端（httpx 异步）。

    通过 httpx 向目标模块发送真实请求。目标地址优先取自 shared/config
    （如 m8 默认 http://localhost:8008），可被对应 *_BASE_URL 环境变量覆盖。

    当目标不可达时：
      - 开发环境：记录 structlog 警告并返回 None，由调用方决定是否走 mock；
      - 生产环境：抛出异常，禁止静默 mock。
    """

    def __init__(self, module_key: str, config: Any = None, use_cache: bool = True):
        self.module_key = module_key.lower()
        self._config = config or get_config()
        self.base_url = (
            self._config.get_module_base_url(self.module_key) or ""
        ).rstrip("/")
        self.token = self._config.get_module_token(self.module_key) or ""
        self.timeout = float(os.getenv("MODULE_REQUEST_TIMEOUT", "10"))
        self.max_retry = max(1, int(os.getenv("MODULE_MAX_RETRY", "2")))
        self.retry_delay = float(os.getenv("MODULE_RETRY_DELAY", "0.5"))
        if not self.base_url:
            raise ValueError(f"未知模块或未配置 base_url: {module_key}")
        self._client: Optional[httpx.AsyncClient] = None

        # ---------- 缓存 ----------
        self.use_cache = use_cache
        self.cache: SimpleCache = get_cache_from_env()
        # 缓存 key 前缀（用于写操作后批量清理）
        self._cache_prefix = f"{self.module_key}:"

    def _headers(self, use_auth: bool = True) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if use_auth and self.token:
            headers["X-M8-Token"] = self.token
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or getattr(self._client, "is_closed", False):
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout
            )
        return self._client

    def _make_cache_key(
        self, method: str, path: str, params: Optional[Dict[str, Any]] = None
    ) -> str:
        """生成缓存 key

        格式：{module}:{method}:{path}:{params_hash}
        params 通过 JSON 序列化 + MD5 生成稳定哈希，保证相同参数得到相同 key。
        """
        params_str = ""
        if params:
            # sort_keys 保证参数顺序不影响哈希
            params_str = json.dumps(params, sort_keys=True, default=str)
        params_hash = hashlib.md5(params_str.encode("utf-8")).hexdigest()[:12]
        return f"{self.module_key}:{method.upper()}:{path}:{params_hash}"

    def _should_cache(self, method: str, use_cache_flag: bool) -> bool:
        """判断是否应该走缓存

        - 仅 GET 请求可缓存
        - 需 use_cache=True（实例级 + 请求级均为 True）
        """
        return self.use_cache and use_cache_flag and method.upper() == "GET"

    def _invalidate_write_cache(self, path: str) -> None:
        """写操作后清除相关缓存

        清除策略：清除该模块下所有 GET 缓存（保守策略，避免数据不一致）。
        也可以根据 path 做更细粒度的失效，这里先采用模块级失效。
        """
        if not self.use_cache:
            return
        # 清除该模块下所有 GET 缓存
        prefix = f"{self.module_key}:GET:"
        self.cache.delete_prefix(prefix)
        _log_event(
            "debug",
            "module_cache_invalidated",
            module=self.module_key,
            path=path,
            reason="write_operation",
        )

    async def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        use_auth: bool = True,
        use_cache: bool = True,
        cache_ttl: Optional[float] = None,
        **kwargs: Any,
    ) -> Optional[Any]:
        """发送 HTTP 请求，返回解析后的 JSON。不可达时按环境策略处理。

        缓存相关参数：
          use_cache: 是否使用缓存（仅 GET 请求生效），默认 True
          cache_ttl: 本次写入缓存的 TTL（秒），不传则根据路径匹配或使用默认值
        """
        method_upper = method.upper()
        can_cache = self._should_cache(method_upper, use_cache)

        # ---------- 缓存读取（仅 GET） ----------
        if can_cache:
            cache_key = self._make_cache_key(method_upper, path, params)
            cached = self.cache.get(cache_key)
            if cached is not None:
                _log_event(
                    "debug",
                    "module_cache_hit",
                    module=self.module_key,
                    method=method_upper,
                    path=path,
                )
                # 区分 None 值缓存 vs 未命中：用哨兵模式会更严谨，
                # 这里简单处理：若 cached 是 None 且接口真的返回 None，
                # 也会被当作缓存命中（开发环境下模块不可达时返回 None）。
                # 为避免把"不可达"的 None 误当缓存，仅缓存非 None 结果，
                # 所以 cached is not None 就一定是有效缓存。
                return cached

        merged_headers = self._headers(use_auth)
        if headers:
            merged_headers.update(headers)
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retry):
            try:
                client = await self._ensure_client()
                start = time.time()
                resp = await client.request(
                    method=method_upper,
                    url=path,
                    params=params,
                    json=json,
                    data=data,
                    headers=merged_headers,
                    **kwargs,
                )
                latency = (time.time() - start) * 1000
                resp.raise_for_status()
                _log_event(
                    "debug",
                    "module_request_ok",
                    module=self.module_key,
                    method=method_upper,
                    path=path,
                    status=resp.status_code,
                    latency_ms=round(latency, 1),
                )
                try:
                    result = resp.json()
                except Exception:
                    result = {"raw_text": resp.text, "status": resp.status_code}

                # ---------- 缓存写入（仅 GET 且成功） ----------
                if can_cache and result is not None:
                    cache_key = self._make_cache_key(method_upper, path, params)
                    ttl = cache_ttl
                    if ttl is None:
                        ttl = get_path_ttl(path, self.cache.default_ttl)
                    self.cache.set(cache_key, result, ttl=ttl)

                # ---------- 写操作后失效缓存 ----------
                if method_upper in ("POST", "PUT", "DELETE", "PATCH"):
                    self._invalidate_write_cache(path)

                return result
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code if exc.response is not None else None
                _log_event(
                    "warning",
                    "module_request_http_error",
                    module=self.module_key,
                    method=method_upper,
                    path=path,
                    status=status,
                    attempt=attempt + 1,
                )
                # 4xx 客户端错误不重试
                if status is not None and 400 <= status < 500:
                    if not _is_dev_env():
                        raise
                    return None
            except Exception as exc:  # 网络错误、连接超时等
                last_error = exc
                _log_event(
                    "warning",
                    "module_request_error",
                    module=self.module_key,
                    method=method_upper,
                    path=path,
                    error=str(exc),
                    attempt=attempt + 1,
                )
            if attempt < self.max_retry - 1:
                await asyncio.sleep(self.retry_delay)

        # 所有重试均失败
        if _is_dev_env():
            _log_event(
                "warning",
                "module_unreachable_mock_fallback",
                module=self.module_key,
                base_url=self.base_url,
                error=str(last_error),
            )
            return None
        # 生产环境：禁止静默 mock，向上抛出
        raise last_error  # type: ignore[misc]

    async def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
        cache_ttl: Optional[float] = None,
        **kwargs: Any,
    ) -> Optional[Any]:
        return await self.request(
            "GET", path, params=params, use_cache=use_cache, cache_ttl=cache_ttl, **kwargs
        )

    async def post(
        self,
        path: str,
        json: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Optional[Any]:
        return await self.request("POST", path, params=params, json=json, **kwargs)

    async def put(
        self,
        path: str,
        json: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Optional[Any]:
        return await self.request("PUT", path, params=params, json=json, **kwargs)

    async def delete(
        self, path: str, params: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> Optional[Any]:
        return await self.request("DELETE", path, params=params, **kwargs)

    async def health_check(self) -> bool:
        """健康检查，优先使用 M8 标准路径 /m8/health，失败时降级到 /health。

        调用策略：
        1. 先尝试 /m8/health（M8 标准接口）
        2. 若返回 404 或连接失败，降级尝试 /health
        3. 降级时记录 WARNING 日志

        结果可走缓存（TTL 2s）。
        """
        # 尝试从缓存读取
        if self.use_cache:
            cache_key = f"{self.module_key}:GET:/m8/health:d41d8cd98f00"
            cached = self.cache.get(cache_key)
            if cached is not None and isinstance(cached, dict):
                return cached.get("ok", False)

        try:
            client = await self._ensure_client()
            start = time.time()

            # 第一步：尝试 M8 标准路径
            try:
                resp = await client.get("/m8/health", headers=self._headers(False))
                latency = (time.time() - start) * 1000
                ok = resp.status_code == 200
                if ok:
                    _log_event(
                        "debug",
                        "module_health_check",
                        module=self.module_key,
                        base_url=self.base_url,
                        path="/m8/health",
                        status=resp.status_code,
                        latency_ms=round(latency, 1),
                    )
                    # 写入缓存（健康检查 TTL 2s）
                    if self.use_cache:
                        cache_key = f"{self.module_key}:GET:/m8/health:d41d8cd98f00"
                        self.cache.set(cache_key, {"ok": ok}, ttl=2.0)
                    return True
                elif resp.status_code == 404:
                    # 404 降级到 /health
                    _log_event(
                        "warning",
                        "module_health_fallback",
                        module=self.module_key,
                        reason="m8_health_404",
                        fallback_path="/health",
                    )
                else:
                    # 其他错误状态
                    _log_event(
                        "warning",
                        "module_health_check",
                        module=self.module_key,
                        base_url=self.base_url,
                        path="/m8/health",
                        status=resp.status_code,
                        latency_ms=round(latency, 1),
                    )
                    return False
            except Exception:
                # 连接异常，降级到 /health
                _log_event(
                    "warning",
                    "module_health_fallback",
                    module=self.module_key,
                    reason="m8_health_connection_error",
                    fallback_path="/health",
                )

            # 第二步：降级到 /health
            resp = await client.get("/health", headers=self._headers(False))
            latency = (time.time() - start) * 1000
            ok = resp.status_code == 200
            _log_event(
                "debug" if ok else "warning",
                "module_health_check",
                module=self.module_key,
                base_url=self.base_url,
                path="/health",
                status=resp.status_code,
                latency_ms=round(latency, 1),
                fallback=True,
            )
            # 写入缓存（健康检查 TTL 2s）
            if self.use_cache:
                cache_key = f"{self.module_key}:GET:/m8/health:d41d8cd98f00"
                self.cache.set(cache_key, {"ok": ok}, ttl=2.0)
            return ok
        except Exception as exc:
            _log_event(
                "warning",
                "module_health_check_failed",
                module=self.module_key,
                base_url=self.base_url,
                error=str(exc),
            )
            if not _is_dev_env():
                return False
            return False

    async def close(self) -> None:
        if self._client and not getattr(self._client, "is_closed", False):
            await self._client.aclose()
        self._client = None


class ModuleRegistry:
    """模块注册表 - 单例模式"""

    _instance: Optional["ModuleRegistry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config=None):
        if self._initialized:
            return
        self._initialized = True
        self._config = config or get_config()
        self._modules: Dict[str, ModuleInfo] = {}
        self._register_default_modules()

    def _register_default_modules(self):
        """注册默认模块（共10个）"""
        default_modules = [
            {
                "key": "m0",
                "name": "主理人管控台",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m0"),
                "base_url": self._config.get_module_base_url("m0"),
                "description": "云汐系统主理人专属管控平台，最高权限",
                "category": "control",
            },
            {
                "key": "m1",
                "name": "代理集群",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m1"),
                "base_url": self._config.get_module_base_url("m1"),
                "description": "多智能体协作、联邦调度、任务编排",
                "category": "core",
            },
            {
                "key": "m2",
                "name": "技能集群",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m2"),
                "base_url": self._config.get_module_base_url("m2"),
                "description": "技能库管理、技能发现、技能执行引擎",
                "category": "core",
            },
            {
                "key": "m3",
                "name": "边缘云端",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m3"),
                "base_url": self._config.get_module_base_url("m3"),
                "description": "边缘计算、云边协同、混合算力调度",
                "category": "infra",
            },
            {
                "key": "m4",
                "name": "场景引擎",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m4"),
                "base_url": self._config.get_module_base_url("m4"),
                "description": "场景模板、场景编排、交互引擎",
                "category": "core",
            },
            {
                "key": "m5",
                "name": "潮汐记忆",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m5"),
                "base_url": self._config.get_module_base_url("m5"),
                "description": "长期记忆、向量检索、知识图谱",
                "category": "core",
            },
            {
                "key": "m6",
                "name": "硬件外设",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m6"),
                "base_url": self._config.get_module_base_url("m6"),
                "description": "硬件驱动、外设管理、设备联动",
                "category": "infra",
            },
            {
                "key": "m7",
                "name": "工作流构建器",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m7"),
                "base_url": self._config.get_module_base_url("m7"),
                "description": "可视化流程编排、自动化任务、触发器",
                "category": "tool",
            },
            {
                "key": "m8",
                "name": "控制塔",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m8"),
                "base_url": self._config.get_module_base_url("m8"),
                "description": "算力调度、API网关、统一管控台",
                "category": "control",
            },
            {
                "key": "m10",
                "name": "系统卫士",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m10"),
                "base_url": self._config.get_module_base_url("m10"),
                "description": "系统资源监控、进程管理、阈值防护、审计日志",
                "category": "infra",
            },
        ]

        for module_data in default_modules:
            module = ModuleInfo(**module_data)
            self._modules[module.key] = module

    def register_module(self, module: ModuleInfo):
        """注册一个模块"""
        self._modules[module.key] = module

    def unregister_module(self, key: str):
        """注销一个模块"""
        if key in self._modules:
            del self._modules[key]

    def get_module(self, key: str) -> Optional[ModuleInfo]:
        """获取指定模块的信息"""
        return self._modules.get(key)

    def get_all_modules(self) -> List[ModuleInfo]:
        """获取所有已注册的模块"""
        return list(self._modules.values())

    def get_module_count(self) -> int:
        """获取已注册模块的数量"""
        return len(self._modules)

    def update_module_status(self, key: str, status: str):
        """更新模块状态"""
        if key in self._modules:
            self._modules[key].status = status

    def get_client(self, key: str) -> ModuleClient:
        """获取指定模块的 HTTP 客户端。

        返回基于 httpx 的真实客户端（base_url 取自 shared/config，
        如 m8 默认 http://localhost:8008）。客户端实例按模块 key 缓存复用。

        注意：调用方需通过 ``await client.get/post/...`` 发起真实请求；
        当目标不可达时，开发环境返回 None（供调用方走 mock），
        生产环境抛出异常。
        """
        key = key.lower()
        if not hasattr(self, "_clients"):
            object.__setattr__(self, "_clients", {})
        cache: Dict[str, ModuleClient] = getattr(self, "_clients", {})
        if key not in cache:
            if key not in self._modules:
                _log_event(
                    "warning",
                    "module_not_registered",
                    module=key,
                    action="create_client_anyway",
                )
            cache[key] = ModuleClient(key, config=self._config)
        return cache[key]

    async def check_all_health(self) -> Dict[str, bool]:
        """并发检查所有已注册模块的健康状态。"""
        results: Dict[str, bool] = {}
        for module in self.get_all_modules():
            try:
                results[module.key] = await self.get_client(module.key).health_check()
            except Exception as exc:
                _log_event(
                    "warning",
                    "check_all_health_error",
                    module=module.key,
                    error=str(exc),
                )
                results[module.key] = False
        return results

    def get_status_summary(self) -> Dict[str, Any]:
        """返回各模块状态摘要。"""
        modules = self.get_all_modules()
        total = len(modules)
        running = sum(1 for m in modules if m.status == "running")
        return {
            "total": total,
            "running": running,
            "stopped": sum(1 for m in modules if m.status == "stopped"),
            "unknown": sum(1 for m in modules if m.status not in ("running", "stopped")),
        }

    # ---------- 全局缓存管理 ----------

    def get_cache_stats(self) -> Dict[str, Any]:
        """返回所有已创建客户端的缓存统计信息。

        Returns:
            {
              "total": { hits, misses, hit_rate, size, ... },
              "by_module": {
                "m0": { hits, misses, ... },
                "m1": { ... },
              }
            }
        """
        if not hasattr(self, "_clients"):
            return {
                "total": self._empty_cache_stats(),
                "by_module": {},
            }
        clients: Dict[str, ModuleClient] = getattr(self, "_clients", {})
        by_module: Dict[str, Any] = {}
        total_hits = 0
        total_misses = 0
        total_evictions = 0
        total_sets = 0
        total_deletes = 0
        total_size = 0
        for key, client in clients.items():
            stats = client.cache.get_stats()
            by_module[key] = stats
            total_hits += stats.get("hits", 0)
            total_misses += stats.get("misses", 0)
            total_evictions += stats.get("evictions", 0)
            total_sets += stats.get("sets", 0)
            total_deletes += stats.get("deletes", 0)
            total_size += stats.get("size", 0)
        total_requests = total_hits + total_misses
        hit_rate = total_hits / total_requests if total_requests > 0 else 0.0
        return {
            "total": {
                "hits": total_hits,
                "misses": total_misses,
                "evictions": total_evictions,
                "sets": total_sets,
                "deletes": total_deletes,
                "total_requests": total_requests,
                "hit_rate": round(hit_rate, 4),
                "size": total_size,
                "module_count": len(clients),
            },
            "by_module": by_module,
        }

    def clear_all_cache(self) -> int:
        """清除所有已创建客户端的缓存。

        Returns:
            总共清除的缓存条目数
        """
        if not hasattr(self, "_clients"):
            return 0
        clients: Dict[str, ModuleClient] = getattr(self, "_clients", {})
        total_cleared = 0
        for key, client in clients.items():
            count = client.cache.clear()
            total_cleared += count
            _log_event(
                "debug",
                "module_cache_cleared",
                module=key,
                cleared=count,
            )
        _log_event(
            "info",
            "module_cache_clear_all",
            total_cleared=total_cleared,
            module_count=len(clients),
        )
        return total_cleared

    async def warm_cache(self, paths: Optional[List[str]] = None) -> Dict[str, int]:
        """预热常用接口的缓存（可选）。

        对所有已注册模块的指定路径发起 GET 请求，将结果写入缓存，
        从而减少首次实际请求的延迟。

        Args:
            paths: 要预热的路径列表，默认预热 /health

        Returns:
            { module_key: warmed_count } 每个模块成功预热的路径数
        """
        warm_paths = paths or ["/health"]
        results: Dict[str, int] = {}
        for module in self.get_all_modules():
            count = 0
            client = self.get_client(module.key)
            for path in warm_paths:
                try:
                    result = await client.get(path, use_cache=True)
                    if result is not None:
                        count += 1
                except Exception as exc:
                    _log_event(
                        "warning",
                        "module_cache_warm_failed",
                        module=module.key,
                        path=path,
                        error=str(exc),
                    )
            results[module.key] = count
        _log_event(
            "info",
            "module_cache_warm_complete",
            module_count=len(results),
            paths=warm_paths,
        )
        return results

    @staticmethod
    def _empty_cache_stats() -> Dict[str, Any]:
        return {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "sets": 0,
            "deletes": 0,
            "total_requests": 0,
            "hit_rate": 0.0,
            "size": 0,
            "module_count": 0,
        }


# ==================== 默认模块配置 ====================

DEFAULT_MODULE_CONFIGS: Dict[str, ModuleInfo] = {}
"""默认模块配置字典，以模块 key 为键"""


def _init_default_module_configs() -> None:
    """初始化 DEFAULT_MODULE_CONFIGS 字典"""
    global DEFAULT_MODULE_CONFIGS
    if DEFAULT_MODULE_CONFIGS:
        return
    # 使用 ModuleRegistry 中的默认模块定义
    registry = ModuleRegistry()
    for module in registry.get_all_modules():
        DEFAULT_MODULE_CONFIGS[module.key] = module


# 延迟初始化：首次访问时填充
_init_default_module_configs()


# 全局注册表单例
_registry: Optional[ModuleRegistry] = None


def get_registry() -> ModuleRegistry:
    """获取全局模块注册表实例"""
    global _registry
    if _registry is None:
        _registry = ModuleRegistry()
    return _registry


# ==================== 向后兼容别名 ====================

# 函数别名
get_module_registry = get_registry

# ModuleStatus 兼容（使用字符串状态）
class ModuleStatus:
    """模块状态常量（向后兼容）"""
    UNKNOWN = "unknown"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"

# 注意：ModuleClient 现已是独立的 httpx 客户端类（见上方定义），
# 不再作为 ModuleRegistry 的别名。需要模块注册信息请使用 ModuleRegistry，
# 需要发起 HTTP 请求请使用 ModuleClient / registry.get_client(key)。
