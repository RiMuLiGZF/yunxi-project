"""
三层模型架构调度器（规则版）—— ThreeTierModelRouter
=====================================================

## 概述

在云汐系统 M1 Agent 集群中落地"3B 调度 + 7B 按需 + 云端兜底"的三层模型架构。
根据任务复杂度自动路由到最优模型，兼顾响应速度、推理质量与运行成本。

## 架构图

```
                    ┌─────────────────────┐
                    │  ThreeTierModelRouter  │
                    │   (单例 · 规则调度)    │
                    └──────────┬──────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
    ┌──────────┐         ┌──────────┐         ┌──────────┐
    │  Tier 0  │         │  Tier 1  │         │  Tier 2  │
    │  3B 模型  │         │  7B 模型  │         │ 云端 API  │
    │ (常驻显存)│         │ (按需加载)│         │ (兜底调用)│
    └──────────┘         └──────────┘         └──────────┘
     qwen2.5:3b          qwen2.5:7b           deepseek /
     闲聊·问答·           代码·分析·            gpt-4o-mini
     状态查询              长文本推理             专业·创意·多模态
```

## 三层模型定位

| 层级 | 模型规模 | 定位 | 典型场景 | 显存占用 | 响应速度 |
|------|---------|------|---------|---------|---------|
| Tier 0 | 3B | 调度/轻量对话 | 闲聊、确认、状态查询、简单指令 | ~2GB | 极快 |
| Tier 1 | 7B | 主力推理 | 代码生成、分析总结、多步推理 | ~5GB | 中等 |
| Tier 2 | 云端 | 兜底/复杂任务 | 专业领域、创意写作、多模态 | 0 | 依赖网络 |

## 降级链

```
complex → tier2(云端) → tier1(7B) → tier0(3B) → 报错
medium  → tier1(7B)   → tier0(3B) → 报错
simple  → tier0(3B)   → 报错
```

## 与现有系统的集成方式

### 方式一：替换 shared/llm_client.py 的 LLMClient（推荐）

在 `shared/clients/llm_client.py` 中，将 `LLMClient` 的底层调用替换为 `ThreeTierModelRouter`：

```python
from shared.model_router import get_model_router

class LLMClient:
    def __init__(self):
        self._router = get_model_router()

    async def chat(self, messages, **kwargs):
        return await self._router.chat(messages, **kwargs)
```

### 方式二：M1 内部直接使用（快速集成）

在 `M1-agent-hub/llm_provider.py` 的 `InferenceRouter` 中替换路由逻辑：

```python
from shared.model_router import get_model_router

class InferenceRouter:
    def __init__(self, ...):
        self._router = get_model_router()

    async def route_inference(self, messages, ...):
        return await self._router.chat(messages)
```

### 方式三：作为独立组件调用

```python
from shared.model_router import get_model_router

router = get_model_router()

# 自动路由
result = await router.chat([{"role": "user", "content": "你好"}])

# 强制使用 3B
result = await router.chat_simple([{"role": "user", "content": "现在几点了？"}])

# 强制使用 7B
result = await router.chat_heavy([{"role": "user", "content": "写一个快速排序函数"}])

# 强制使用云端
result = await router.chat_cloud([{"role": "user", "content": "写一份深度分析报告"}])
```

## 环境变量配置

```bash
# Tier 0（3B 调度模型）
MODEL_ROUTER_TIER0_ENABLED=true
MODEL_ROUTER_TIER0_MODEL=qwen2.5:3b
MODEL_ROUTER_TIER0_BASE_URL=http://localhost:11434
MODEL_ROUTER_TIER0_TIMEOUT=30

# Tier 1（7B 主力模型）
MODEL_ROUTER_TIER1_ENABLED=true
MODEL_ROUTER_TIER1_MODEL=qwen2.5:7b
MODEL_ROUTER_TIER1_BASE_URL=http://localhost:11434
MODEL_ROUTER_TIER1_TIMEOUT=60
MODEL_ROUTER_TIER1_IDLE_TTL=300  # 空闲5分钟自动卸载

# Tier 2（云端 API）
MODEL_ROUTER_TIER2_ENABLED=true
MODEL_ROUTER_TIER2_PROVIDER=deepseek
MODEL_ROUTER_TIER2_MODEL=deepseek-chat
MODEL_ROUTER_TIER2_BASE_URL=https://api.deepseek.com/v1
MODEL_ROUTER_TIER2_API_KEY=your-api-key
MODEL_ROUTER_TIER2_TIMEOUT=120

# 全局配置
MODEL_ROUTER_DEGRADATION_ENABLED=true   # 启用自动降级
MODEL_ROUTER_VRAM_CHECK_ENABLED=true    # 启用显存感知
MODEL_ROUTER_MIN_VRAM_GB=8              # 最低可用显存阈值（GB）
```

## 显存感知机制

- 优先通过 M10 系统卫士获取显存状态（如不可用则尝试 pynvml / nvidia-smi）
- 加载 7B 模型前检查显存是否充足
- 显存不足时自动降级到下一层模型
- 7B 模型空闲超过 TTL 后自动卸载，释放显存

## 线程安全

- 单例模式，全局共享一个实例
- 模型加载使用 asyncio.Lock 防止并发加载
- 状态更新操作均为原子操作
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────


@dataclass
class TierConfig:
    """单层模型配置"""

    enabled: bool = True
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    timeout: float = 60.0
    provider: str = "ollama"  # ollama | openai | deepseek
    idle_ttl: float = 300.0   # 空闲超时自动卸载（秒），仅 tier1 有效


@dataclass
class RouterConfig:
    """调度器全局配置"""

    tier0: TierConfig = field(default_factory=lambda: TierConfig(
        model="qwen2.5:3b",
        base_url="http://localhost:11434",
        timeout=30.0,
        provider="ollama",
    ))
    tier1: TierConfig = field(default_factory=lambda: TierConfig(
        model="qwen2.5:7b",
        base_url="http://localhost:11434",
        timeout=60.0,
        provider="ollama",
        idle_ttl=300.0,
    ))
    tier2: TierConfig = field(default_factory=lambda: TierConfig(
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key="",
        timeout=120.0,
        provider="deepseek",
    ))

    # 全局开关
    degradation_enabled: bool = True   # 启用自动降级
    vram_check_enabled: bool = True    # 启用显存感知
    min_vram_gb: float = 8.0           # 最低可用显存（GB）

    # 关键词配置（可扩展）
    simple_keywords: list[str] = field(default_factory=lambda: [
        "你好", "在吗", "几点了", "天气", "查询", "状态",
        "帮我查", "确认", "好的", "收到", "hi", "hello",
        "谢谢", "再见", "拜拜", "嗯", "哦", "啊",
    ])
    medium_keywords: list[str] = field(default_factory=lambda: [
        "写代码", "分析", "解释", "总结", "写一篇", "代码",
        "函数", "脚本", "优化", "重构", "实现", "设计",
        "方案", "对比", "评估", "翻译",
    ])
    complex_keywords: list[str] = field(default_factory=lambda: [
        "深度分析", "专业报告", "法律", "医疗", "金融",
        "多模态", "图片", "视频", "论文", "研究", "战略",
        "架构设计", "系统设计", "创意写作", "小说", "诗歌",
        "写诗", "创作", "学术", "博士", "硕士", "专利",
        "一首诗", "写一首", "剧本", "作曲", "编曲",
    ])

    # 字数阈值
    simple_max_chars: int = 100        # 短文本上限
    medium_max_chars: int = 2000       # 中等文本上限


@dataclass
class RouteDecision:
    """路由决策结果"""

    model: str
    tier: int           # 0 / 1 / 2
    source: str         # "local" | "cloud"
    task_type: str      # "simple" | "medium" | "complex"
    degraded_from: Optional[int] = None  # 从哪一层降级而来


# ── 调度器主类 ────────────────────────────────────────────────


class ThreeTierModelRouter:
    """三层模型架构规则版调度器（单例）

    实现 3B 调度 + 7B 按需 + 云端兜底 的智能路由。

    核心能力：
    1. 任务分类：基于关键词 + 文本长度的规则分类器
    2. 路由决策：根据任务类型选择最优模型层
    3. 自动降级：上层不可用时自动降级到下一层
    4. 显存感知：加载前检查显存，不足时自动降级
    5. 模型预热/卸载：按需加载、空闲自动释放
    """

    _instance: Optional["ThreeTierModelRouter"] = None
    _instance_lock = asyncio.Lock()

    @classmethod
    async def get_instance(cls) -> "ThreeTierModelRouter":
        """获取单例（异步安全）"""
        if cls._instance is None:
            async with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
                    await cls._instance._initialize()
        return cls._instance

    @classmethod
    def get_instance_sync(cls) -> "ThreeTierModelRouter":
        """获取单例（同步版本，用于非 async 上下文）

        注意：同步版本不会自动初始化，需手动调用 initialize()。
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, config: Optional[RouterConfig] = None) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = False

        # 加载配置
        self.config = config or self._load_config_from_env()

        # HTTP 客户端（惰性初始化）
        self._ollama_client: Any = None  # httpx.AsyncClient for tier0/tier1
        self._cloud_client: Any = None   # httpx.AsyncClient for tier2

        # 模型状态
        self._model_loaded: dict[int, bool] = {0: False, 1: False, 2: False}
        self._model_last_used: dict[int, float] = {0: 0.0, 1: 0.0, 2: 0.0}
        self._model_load_locks: dict[int, asyncio.Lock] = {
            0: asyncio.Lock(),
            1: asyncio.Lock(),
            2: asyncio.Lock(),
        }

        # 健康状态缓存
        self._health_cache: dict[int, tuple[bool, float]] = {}  # tier -> (healthy, timestamp)
        self._health_cache_ttl = 30.0  # 健康状态缓存 30 秒

        # 统计
        self._stats: dict[str, int] = {
            "total_requests": 0,
            "tier0_requests": 0,
            "tier1_requests": 0,
            "tier2_requests": 0,
            "degradation_count": 0,
        }

        # 后台任务
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        self._logger = logger.bind(component="three_tier_router")

    # ── 初始化与配置 ──────────────────────────────────────

    def _load_config_from_env(self) -> RouterConfig:
        """从环境变量加载配置"""
        cfg = RouterConfig()

        # Tier 0
        cfg.tier0.enabled = os.getenv("MODEL_ROUTER_TIER0_ENABLED", "true").lower() == "true"
        cfg.tier0.model = os.getenv("MODEL_ROUTER_TIER0_MODEL", cfg.tier0.model)
        cfg.tier0.base_url = os.getenv("MODEL_ROUTER_TIER0_BASE_URL", cfg.tier0.base_url)
        cfg.tier0.timeout = float(os.getenv("MODEL_ROUTER_TIER0_TIMEOUT", str(cfg.tier0.timeout)))

        # Tier 1
        cfg.tier1.enabled = os.getenv("MODEL_ROUTER_TIER1_ENABLED", "true").lower() == "true"
        cfg.tier1.model = os.getenv("MODEL_ROUTER_TIER1_MODEL", cfg.tier1.model)
        cfg.tier1.base_url = os.getenv("MODEL_ROUTER_TIER1_BASE_URL", cfg.tier1.base_url)
        cfg.tier1.timeout = float(os.getenv("MODEL_ROUTER_TIER1_TIMEOUT", str(cfg.tier1.timeout)))
        cfg.tier1.idle_ttl = float(os.getenv("MODEL_ROUTER_TIER1_IDLE_TTL", str(cfg.tier1.idle_ttl)))

        # Tier 2
        cfg.tier2.enabled = os.getenv("MODEL_ROUTER_TIER2_ENABLED", "true").lower() == "true"
        cfg.tier2.provider = os.getenv("MODEL_ROUTER_TIER2_PROVIDER", cfg.tier2.provider)
        cfg.tier2.model = os.getenv("MODEL_ROUTER_TIER2_MODEL", cfg.tier2.model)
        cfg.tier2.base_url = os.getenv("MODEL_ROUTER_TIER2_BASE_URL", cfg.tier2.base_url)
        cfg.tier2.api_key = os.getenv("MODEL_ROUTER_TIER2_API_KEY", cfg.tier2.api_key)
        cfg.tier2.timeout = float(os.getenv("MODEL_ROUTER_TIER2_TIMEOUT", str(cfg.tier2.timeout)))

        # 全局
        cfg.degradation_enabled = os.getenv(
            "MODEL_ROUTER_DEGRADATION_ENABLED", "true"
        ).lower() == "true"
        cfg.vram_check_enabled = os.getenv(
            "MODEL_ROUTER_VRAM_CHECK_ENABLED", "true"
        ).lower() == "true"
        cfg.min_vram_gb = float(os.getenv("MODEL_ROUTER_MIN_VRAM_GB", str(cfg.min_vram_gb)))

        return cfg

    async def _initialize(self) -> None:
        """异步初始化"""
        if self._initialized:
            return
        self._initialized = True
        self._running = True

        # 惰性创建 HTTP 客户端
        try:
            import httpx
            self._ollama_client = httpx.AsyncClient(timeout=120.0)
            self._cloud_client = httpx.AsyncClient(timeout=120.0)
        except ImportError:
            self._logger.warning("httpx not available, router will work in degraded mode")

        # 启动空闲清理任务（用于 tier1 自动卸载）
        self._cleanup_task = asyncio.create_task(self._idle_cleanup_loop())

        # 尝试预热 tier0 模型
        if self.config.tier0.enabled:
            asyncio.create_task(self._warmup_tier0())

        self._logger.info(
            "model_router_initialized",
            tier0_enabled=self.config.tier0.enabled,
            tier1_enabled=self.config.tier1.enabled,
            tier2_enabled=self.config.tier2.enabled,
            tier0_model=self.config.tier0.model,
            tier1_model=self.config.tier1.model,
            tier2_model=self.config.tier2.model,
        )

    async def _warmup_tier0(self) -> None:
        """预热 tier0 模型（后台执行）"""
        try:
            await self.preload_model(0)
            self._logger.info("tier0_warmup_complete", model=self.config.tier0.model)
        except Exception as exc:
            self._logger.warning("tier0_warmup_failed", error=str(exc))

    async def shutdown(self) -> None:
        """关闭调度器，释放资源"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        if self._ollama_client:
            await self._ollama_client.aclose()
            self._ollama_client = None
        if self._cloud_client:
            await self._cloud_client.aclose()
            self._cloud_client = None

        self._logger.info("model_router_shutdown")

    # ── 任务分类器 ────────────────────────────────────────

    def classify_task(self, text: str, context: Optional[dict[str, Any]] = None) -> str:
        """任务分类器（规则版）

        根据文本内容和长度，将任务分为三类：
        - simple: 短文本、闲聊、问答、确认、状态查询、简单指令
        - medium: 代码生成、分析类、写作类、长文本、多步推理
        - complex: 超长文本、专业领域、创意写作、复杂代码、多模态

        Args:
            text: 用户输入文本
            context: 上下文信息（可选），如 system_prompt, history 等

        Returns:
            "simple" | "medium" | "complex"
        """
        text = text.strip()
        text_len = len(text)
        context = context or {}

        # 1. 先检查 complex 关键词（优先级最高，避免被 medium 误判）
        for kw in self.config.complex_keywords:
            if kw in text:
                return "complex"

        # 2. 检查 medium 关键词
        for kw in self.config.medium_keywords:
            if kw in text:
                # 如果文本很长，升级为 complex
                if text_len > self.config.medium_max_chars:
                    return "complex"
                return "medium"

        # 3. 检查 simple 关键词
        for kw in self.config.simple_keywords:
            if kw in text:
                return "simple"

        # 4. 基于文本长度判断
        if text_len <= self.config.simple_max_chars:
            # 短文本默认 simple（除非上下文暗示更复杂）
            system_prompt = context.get("system_prompt", "")
            if any(kw in system_prompt for kw in self.config.complex_keywords):
                return "complex"
            if any(kw in system_prompt for kw in self.config.medium_keywords):
                return "medium"
            return "simple"

        elif text_len <= self.config.medium_max_chars:
            return "medium"

        else:
            return "complex"

    # ── 路由决策 ──────────────────────────────────────────

    async def route(self, task_type: str, context: Optional[dict[str, Any]] = None) -> RouteDecision:
        """路由决策：根据任务类型选择最优模型层

        路由逻辑：
        1. simple → tier0 3B 模型
        2. medium → tier1 7B 模型（显存不足则降级到 3B）
        3. complex → tier2 云端 API（不可用则降级到 7B）

        降级链：complex → 7B → 3B → 报错

        Args:
            task_type: "simple" | "medium" | "complex"
            context: 上下文信息

        Returns:
            RouteDecision 路由决策
        """
        context = context or {}

        if task_type == "simple":
            return await self._route_simple()
        elif task_type == "medium":
            return await self._route_medium()
        elif task_type == "complex":
            return await self._route_complex()
        else:
            # 未知类型默认走 medium
            self._logger.warning("unknown_task_type", task_type=task_type)
            return await self._route_medium()

    async def _route_simple(self) -> RouteDecision:
        """simple 任务路由 → tier0（3B）"""
        cfg = self.config.tier0
        if cfg.enabled and await self._check_tier_available(0):
            return RouteDecision(
                model=cfg.model,
                tier=0,
                source="local",
                task_type="simple",
            )

        # tier0 不可用，尝试 tier1
        if self.config.degradation_enabled:
            if self.config.tier1.enabled and await self._check_tier_available(1):
                self._stats["degradation_count"] += 1
                self._logger.warning("degrade_simple_to_tier1")
                return RouteDecision(
                    model=self.config.tier1.model,
                    tier=1,
                    source="local",
                    task_type="simple",
                    degraded_from=0,
                )
            # 再不行尝试 tier2
            if self.config.tier2.enabled and await self._check_tier_available(2):
                self._stats["degradation_count"] += 1
                self._logger.warning("degrade_simple_to_tier2")
                return RouteDecision(
                    model=self.config.tier2.model,
                    tier=2,
                    source="cloud",
                    task_type="simple",
                    degraded_from=0,
                )

        raise RuntimeError("No available model tier for simple task")

    async def _route_medium(self) -> RouteDecision:
        """medium 任务路由 → tier1（7B），显存不足降级到 tier0"""
        cfg = self.config.tier1
        if cfg.enabled and await self._check_tier_available(1):
            # 检查显存是否足够加载 7B
            if self.config.vram_check_enabled:
                if not await self.check_vram_available(tier=1):
                    self._logger.warning("insufficient_vram_for_tier1")
                    # 显存不足，降级到 tier0
                    if self.config.tier0.enabled and await self._check_tier_available(0):
                        self._stats["degradation_count"] += 1
                        return RouteDecision(
                            model=self.config.tier0.model,
                            tier=0,
                            source="local",
                            task_type="medium",
                            degraded_from=1,
                        )

            return RouteDecision(
                model=cfg.model,
                tier=1,
                source="local",
                task_type="medium",
            )

        # tier1 不可用，降级到 tier0
        if self.config.degradation_enabled:
            if self.config.tier0.enabled and await self._check_tier_available(0):
                self._stats["degradation_count"] += 1
                self._logger.warning("degrade_medium_to_tier0")
                return RouteDecision(
                    model=self.config.tier0.model,
                    tier=0,
                    source="local",
                    task_type="medium",
                    degraded_from=1,
                )
            # 再不行尝试 tier2
            if self.config.tier2.enabled and await self._check_tier_available(2):
                self._stats["degradation_count"] += 1
                self._logger.warning("degrade_medium_to_tier2")
                return RouteDecision(
                    model=self.config.tier2.model,
                    tier=2,
                    source="cloud",
                    task_type="medium",
                    degraded_from=1,
                )

        raise RuntimeError("No available model tier for medium task")

    async def _route_complex(self) -> RouteDecision:
        """complex 任务路由 → tier2（云端），不可用降级到 tier1"""
        cfg = self.config.tier2
        if cfg.enabled and cfg.api_key and await self._check_tier_available(2):
            return RouteDecision(
                model=cfg.model,
                tier=2,
                source="cloud",
                task_type="complex",
            )

        # tier2 不可用，降级到 tier1
        if self.config.degradation_enabled:
            if self.config.tier1.enabled and await self._check_tier_available(1):
                # 检查显存
                if self.config.vram_check_enabled and not await self.check_vram_available(tier=1):
                    # 显存不足，继续降级到 tier0
                    if self.config.tier0.enabled and await self._check_tier_available(0):
                        self._stats["degradation_count"] += 1
                        self._logger.warning("degrade_complex_to_tier0")
                        return RouteDecision(
                            model=self.config.tier0.model,
                            tier=0,
                            source="local",
                            task_type="complex",
                            degraded_from=2,
                        )
                else:
                    self._stats["degradation_count"] += 1
                    self._logger.warning("degrade_complex_to_tier1")
                    return RouteDecision(
                        model=self.config.tier1.model,
                        tier=1,
                        source="local",
                        task_type="complex",
                        degraded_from=2,
                    )

            # 再不行降级到 tier0
            if self.config.tier0.enabled and await self._check_tier_available(0):
                self._stats["degradation_count"] += 1
                self._logger.warning("degrade_complex_to_tier0_direct")
                return RouteDecision(
                    model=self.config.tier0.model,
                    tier=0,
                    source="local",
                    task_type="complex",
                    degraded_from=2,
                )

        raise RuntimeError("No available model tier for complex task")

    # ── 显存感知 ──────────────────────────────────────────

    async def check_vram_available(self, tier: int = 1) -> bool:
        """检查当前显存是否足够加载目标模型

        优先级：
        1. M10 系统卫士 API（如果可用）
        2. pynvml 库（NVIDIA GPU）
        3. nvidia-smi 命令行
        4. 不可检测时默认返回 True（假设足够）

        Args:
            tier: 目标层级（0/1/2）

        Returns:
            True 表示显存足够，False 表示不足
        """
        if not self.config.vram_check_enabled:
            return True

        # tier2 是云端，不需要检查显存
        if tier == 2:
            return True

        # 估算所需显存（粗略）
        # 3B 模型约 2GB，7B 模型约 5GB
        required_vram_gb = 2.0 if tier == 0 else 5.0

        # 方法1：尝试通过 M10 系统卫士获取（如果有集成）
        m10_vram = await self._get_vram_from_m10()
        if m10_vram is not None:
            return m10_vram >= required_vram_gb

        # 方法2：尝试 pynvml
        try:
            import pynvml  # type: ignore
            try:
                pynvml.nvmlInit()
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                free_gb = info.free / (1024**3)
                pynvml.nvmlShutdown()
                return free_gb >= required_vram_gb
            except Exception:
                try:
                    pynvml.nvmlShutdown()
                except Exception:
                    pass
        except ImportError:
            pass

        # 方法3：尝试 nvidia-smi
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5.0,
            )
            if result.returncode == 0:
                free_mb = float(result.stdout.strip().split("\n")[0])
                free_gb = free_mb / 1024.0
                return free_gb >= required_vram_gb
        except Exception:
            pass

        # 无法检测，默认认为足够
        self._logger.debug("vram_check_unavailable_assuming_sufficient")
        return True

    async def _get_vram_from_m10(self) -> Optional[float]:
        """从 M10 系统卫士获取可用显存（GB）

        预留接口，待 M10 集成后实现。
        当前返回 None 表示不可用。
        """
        # TODO: 集成 M10 系统卫士的显存查询接口
        return None

    # ── 模型预热/卸载 ─────────────────────────────────────

    async def preload_model(self, tier: int) -> bool:
        """预加载指定层的模型到显存

        Args:
            tier: 层级（0/1/2）

        Returns:
            True 表示加载成功/已加载，False 表示失败
        """
        if tier not in (0, 1, 2):
            raise ValueError(f"Invalid tier: {tier}")

        if tier == 2:
            # 云端模型不需要预热，检查可用性即可
            return await self._check_tier_available(2)

        async with self._model_load_locks[tier]:
            # 双重检查
            if self._model_loaded.get(tier, False):
                self._model_last_used[tier] = time.time()
                return True

            cfg = self.config.tier0 if tier == 0 else self.config.tier1

            if not cfg.enabled:
                return False

            if not self._ollama_client:
                return False

            try:
                # 通过 Ollama API 加载模型（空 generate 请求）
                resp = await self._ollama_client.post(
                    f"{cfg.base_url}/api/generate",
                    json={
                        "model": cfg.model,
                        "prompt": "",
                        "stream": False,
                        "options": {"num_predict": 1},
                    },
                    timeout=cfg.timeout + 60,  # 加载可能需要额外时间
                )
                if resp.status_code == 200:
                    self._model_loaded[tier] = True
                    self._model_last_used[tier] = time.time()
                    self._logger.info("model_preloaded", tier=tier, model=cfg.model)
                    return True
                return False
            except Exception as exc:
                self._logger.warning("model_preload_failed", tier=tier, error=str(exc))
                return False

    async def unload_model(self, tier: int) -> bool:
        """卸载指定层的模型，释放显存

        Args:
            tier: 层级（0/1/2）

        Returns:
            True 表示卸载成功，False 表示失败
        """
        if tier not in (0, 1, 2):
            raise ValueError(f"Invalid tier: {tier}")

        if tier == 2:
            self._model_loaded[2] = False
            return True  # 云端模型不需要卸载

        # tier0 是常驻模型，通常不卸载
        # 但允许显式调用以释放资源
        cfg = self.config.tier0 if tier == 0 else self.config.tier1

        if not self._ollama_client:
            self._model_loaded[tier] = False
            return True

        try:
            # 用 keep_alive=0s 让 Ollama 立即卸载
            resp = await self._ollama_client.post(
                f"{cfg.base_url}/api/generate",
                json={
                    "model": cfg.model,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": "0s",
                    "options": {"num_predict": 1},
                },
                timeout=30.0,
            )
            if resp.status_code == 200:
                self._model_loaded[tier] = False
                self._logger.info("model_unloaded", tier=tier, model=cfg.model)
                return True
            return False
        except Exception as exc:
            self._logger.debug("model_unload_failed", tier=tier, error=str(exc))
            # 即使 API 调用失败，也标记为未加载
            self._model_loaded[tier] = False
            return True

    async def _idle_cleanup_loop(self) -> None:
        """后台空闲清理循环

        定期检查 tier1 模型是否空闲超时，超时则自动卸载。
        """
        check_interval = 30.0  # 每 30 秒检查一次

        while self._running:
            try:
                await asyncio.sleep(check_interval)
                await self._cleanup_idle_models()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._logger.error("idle_cleanup_error", error=str(exc))

    async def _cleanup_idle_models(self) -> int:
        """清理空闲超时的模型，返回清理数量"""
        cleaned = 0
        now = time.time()

        # 只清理 tier1（7B 按需加载）
        # tier0 是常驻模型，不自动卸载
        tier = 1
        if self._model_loaded.get(tier, False):
            idle_time = now - self._model_last_used.get(tier, 0)
            if idle_time > self.config.tier1.idle_ttl:
                self._logger.info(
                    "tier1_idle_timeout_unloading",
                    idle_seconds=round(idle_time, 1),
                    model=self.config.tier1.model,
                )
                if await self.unload_model(tier):
                    cleaned += 1

        return cleaned

    # ── 健康检查 ──────────────────────────────────────────

    async def _check_tier_available(self, tier: int) -> bool:
        """检查指定层是否可用（带缓存）"""
        now = time.time()
        cached = self._health_cache.get(tier)
        if cached and (now - cached[1]) < self._health_cache_ttl:
            return cached[0]

        healthy = await self._do_health_check(tier)
        self._health_cache[tier] = (healthy, now)
        return healthy

    async def _do_health_check(self, tier: int) -> bool:
        """实际执行健康检查"""
        if tier == 2:
            # 云端：检查是否配置了 API Key
            cfg = self.config.tier2
            return bool(cfg.enabled and cfg.api_key)

        # 本地 Ollama 模型
        cfg = self.config.tier0 if tier == 0 else self.config.tier1
        if not cfg.enabled or not self._ollama_client:
            return False

        try:
            resp = await self._ollama_client.get(
                f"{cfg.base_url}/api/tags",
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                model_names = [m.get("name", "") for m in models]
                # 检查目标模型是否存在
                for name in model_names:
                    if name == cfg.model or name.startswith(cfg.model.split(":")[0]):
                        return True
                return False
        except Exception:
            return False

        return False

    # ── 核心 API ──────────────────────────────────────────

    async def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """自动路由 + 调用对应模型

        根据消息内容自动分类，路由到最优模型层执行。
        支持自动降级。

        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}]
            **kwargs: 其他参数（temperature, max_tokens 等）

        Returns:
            模型回复文本
        """
        # 提取用户消息文本用于分类
        user_text = self._extract_user_text(messages)
        system_text = self._extract_system_text(messages)

        # 任务分类
        task_type = self.classify_task(user_text, context={"system_prompt": system_text})

        # 路由决策
        decision = await self.route(task_type)

        self._stats["total_requests"] += 1
        self._stats[f"tier{decision.tier}_requests"] += 1

        self._logger.info(
            "routed_chat",
            task_type=task_type,
            tier=decision.tier,
            model=decision.model,
            source=decision.source,
            degraded_from=decision.degraded_from,
            text_len=len(user_text),
        )

        # 执行调用（带降级重试）
        try:
            return await self._invoke_model(decision, messages, **kwargs)
        except Exception as exc:
            self._logger.warning(
                "model_invocation_failed",
                tier=decision.tier,
                error=str(exc),
            )
            # 失败时尝试降级
            if self.config.degradation_enabled:
                return await self._chat_with_degradation(decision.tier, messages, **kwargs)
            raise

    async def chat_simple(self, messages: list[dict[str, str]], **kwargs) -> str:
        """强制使用 tier0（3B）模型

        适用于已知简单的任务，跳过分类器。
        """
        decision = await self._route_simple()
        self._stats["total_requests"] += 1
        self._stats[f"tier{decision.tier}_requests"] += 1
        try:
            return await self._invoke_model(decision, messages, **kwargs)
        except Exception as exc:
            if self.config.degradation_enabled:
                return await self._chat_with_degradation(decision.tier, messages, **kwargs)
            raise

    async def chat_heavy(self, messages: list[dict[str, str]], **kwargs) -> str:
        """强制使用 tier1（7B）模型

        适用于需要较强推理能力的任务。
        """
        decision = await self._route_medium()
        self._stats["total_requests"] += 1
        self._stats[f"tier{decision.tier}_requests"] += 1
        try:
            return await self._invoke_model(decision, messages, **kwargs)
        except Exception as exc:
            if self.config.degradation_enabled:
                return await self._chat_with_degradation(decision.tier, messages, **kwargs)
            raise

    async def chat_cloud(self, messages: list[dict[str, str]], **kwargs) -> str:
        """强制使用 tier2（云端 API）模型

        适用于复杂专业任务。
        """
        decision = await self._route_complex()
        self._stats["total_requests"] += 1
        self._stats[f"tier{decision.tier}_requests"] += 1
        try:
            return await self._invoke_model(decision, messages, **kwargs)
        except Exception as exc:
            if self.config.degradation_enabled:
                return await self._chat_with_degradation(decision.tier, messages, **kwargs)
            raise

    # ── 内部方法 ──────────────────────────────────────────

    def _extract_user_text(self, messages: list[dict[str, str]]) -> str:
        """从消息列表中提取最后一条用户消息"""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    def _extract_system_text(self, messages: list[dict[str, str]]) -> str:
        """从消息列表中提取系统提示词"""
        for msg in messages:
            if msg.get("role") == "system":
                return msg.get("content", "")
        return ""

    async def _invoke_model(
        self,
        decision: RouteDecision,
        messages: list[dict[str, str]],
        **kwargs,
    ) -> str:
        """调用指定层的模型"""
        tier = decision.tier

        # 确保模型已加载（本地模型）
        if tier in (0, 1):
            await self.preload_model(tier)

        # 更新最后使用时间
        self._model_last_used[tier] = time.time()

        if tier == 2:
            return await self._invoke_cloud(messages, **kwargs)
        else:
            return await self._invoke_ollama(tier, messages, **kwargs)

    async def _invoke_ollama(
        self,
        tier: int,
        messages: list[dict[str, str]],
        **kwargs,
    ) -> str:
        """调用本地 Ollama 模型"""
        cfg = self.config.tier0 if tier == 0 else self.config.tier1

        if not self._ollama_client:
            raise RuntimeError("Ollama client not initialized")

        payload = {
            "model": kwargs.get("model", cfg.model),
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
            },
        }

        if kwargs.get("max_tokens"):
            payload["options"]["num_predict"] = kwargs["max_tokens"]

        resp = await self._ollama_client.post(
            f"{cfg.base_url}/api/chat",
            json=payload,
            timeout=cfg.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")

    async def _invoke_cloud(
        self,
        messages: list[dict[str, str]],
        **kwargs,
    ) -> str:
        """调用云端 API（OpenAI 兼容格式）"""
        cfg = self.config.tier2

        if not self._cloud_client:
            raise RuntimeError("Cloud client not initialized")

        if not cfg.api_key:
            raise RuntimeError("Cloud API key not configured")

        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": kwargs.get("model", cfg.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "stream": False,
        }

        if kwargs.get("max_tokens"):
            payload["max_tokens"] = kwargs["max_tokens"]

        resp = await self._cloud_client.post(
            f"{cfg.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=cfg.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def _chat_with_degradation(
        self,
        failed_tier: int,
        messages: list[dict[str, str]],
        **kwargs,
    ) -> str:
        """降级重试：从失败层级往下尝试"""
        # 降级顺序：2 → 1 → 0
        for next_tier in range(failed_tier - 1, -1, -1):
            try:
                cfg = (
                    self.config.tier0 if next_tier == 0
                    else self.config.tier1 if next_tier == 1
                    else self.config.tier2
                )
                if not cfg.enabled:
                    continue

                self._logger.warning(
                    "degrading_to_lower_tier",
                    from_tier=failed_tier,
                    to_tier=next_tier,
                )
                self._stats["degradation_count"] += 1
                self._stats[f"tier{next_tier}_requests"] += 1

                decision = RouteDecision(
                    model=cfg.model,
                    tier=next_tier,
                    source="local" if next_tier < 2 else "cloud",
                    task_type="degraded",
                    degraded_from=failed_tier,
                )
                return await self._invoke_model(decision, messages, **kwargs)
            except Exception as exc:
                self._logger.warning(
                    "degraded_tier_also_failed",
                    tier=next_tier,
                    error=str(exc),
                )
                continue

        raise RuntimeError(f"All tiers failed (started from tier {failed_tier})")

    # ── 统计信息 ──────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """获取调度器统计信息"""
        return {
            **self._stats,
            "tier0_loaded": self._model_loaded.get(0, False),
            "tier1_loaded": self._model_loaded.get(1, False),
            "tier2_available": bool(self.config.tier2.enabled and self.config.tier2.api_key),
            "tier0_model": self.config.tier0.model,
            "tier1_model": self.config.tier1.model,
            "tier2_model": self.config.tier2.model,
            "degradation_enabled": self.config.degradation_enabled,
            "vram_check_enabled": self.config.vram_check_enabled,
        }

    def reset_stats(self) -> None:
        """重置统计计数"""
        for key in self._stats:
            self._stats[key] = 0


# ── 便捷函数 ──────────────────────────────────────────────────


def get_model_router() -> ThreeTierModelRouter:
    """获取模型调度器单例（同步版本）

    注意：首次获取后，需要在 async 上下文中调用一次初始化。
    推荐使用 `await get_model_router_async()`。

    Returns:
        ThreeTierModelRouter 实例
    """
    return ThreeTierModelRouter.get_instance_sync()


async def get_model_router_async() -> ThreeTierModelRouter:
    """获取模型调度器单例（异步版本，自动初始化）

    Returns:
        ThreeTierModelRouter 实例
    """
    return await ThreeTierModelRouter.get_instance()
