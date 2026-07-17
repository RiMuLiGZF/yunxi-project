"""
三层模型架构调度器（增强版）—— ThreeTierModelRouter
=====================================================

## 概述

在云汐系统 M1 Agent 集群中落地"3B 调度 + 7B 按需 + 云端兜底"的三层模型架构。
根据任务复杂度自动路由到最优模型，兼顾响应速度、推理质量与运行成本。

## V12.0 增强能力

1. **显存感知增强**：三级探测（pynvml → nvidia-smi → 估算）+ 2s 缓存
2. **模型优先级队列**：P0(当前) / P1(常用) / P2(推荐) / P3(冷门)，低显存时从低到高卸载
3. **低显存自动降级**：auto_degrade() 方法，完整降级链与原因统计
4. **动态上下文调整**：simple 4k / medium 8k / complex 32k，显存紧张自动缩小
5. **预测性预热**：preload_for_task() 根据任务类型提前预热模型

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

## 环境变量配置（增强部分）

```bash
# 显存感知增强
MODEL_ROUTER_VRAM_CHECK_ENABLED=true     # 启用显存感知（默认 true）
MODEL_ROUTER_VRAM_CACHE_TTL=2            # 显存状态缓存 TTL（秒，默认 2）
MODEL_ROUTER_MIN_VRAM_GB=8               # 最低可用显存阈值（GB）

# 模型优先级队列
MODEL_ROUTER_PRIORITY_QUEUE_ENABLED=true # 启用优先级队列（默认 true）

# 自动降级
MODEL_ROUTER_DEGRADATION_ENABLED=true    # 启用自动降级（默认 true）
MODEL_ROUTER_MAX_DEGRADATIONS=3          # 单次请求最大降级次数

# 动态上下文
MODEL_ROUTER_DYNAMIC_CTX_ENABLED=true    # 启用动态上下文调整（默认 true）
MODEL_ROUTER_CTX_SIMPLE_K=4              # simple 任务 context k（默认 4）
MODEL_ROUTER_CTX_MEDIUM_K=8              # medium 任务 context k（默认 8）
MODEL_ROUTER_CTX_COMPLEX_K=32            # complex 任务 context k（默认 32）

# 预测性预热
MODEL_ROUTER_PRELOAD_ENABLED=false       # 启用预测性预热（默认 false）
MODEL_ROUTER_PRELOAD_LEAD_TIME=5         # 预热提前量（秒）
```
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────


class ModelPriority(IntEnum):
    """模型优先级枚举

    P0（最高）：当前正在使用的模型
    P1（高）：用户常用模型 / 近期使用过的模型
    P2（中）：系统推荐模型
    P3（低）：冷门模型
    """

    P0_CURRENT = 0    # 当前正在使用
    P1_FREQUENT = 1   # 常用 / 近期使用
    P2_RECOMMENDED = 2  # 系统推荐
    P3_RARE = 3       # 冷门


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
    # 预估显存占用（GB）
    vram_estimate_gb: float = 0.0
    # 默认 context window（k tokens）
    default_ctx_k: int = 8


@dataclass
class RouterConfig:
    """调度器全局配置"""

    tier0: TierConfig = field(default_factory=lambda: TierConfig(
        model="qwen2.5:3b",
        base_url="http://localhost:11434",
        timeout=30.0,
        provider="ollama",
        vram_estimate_gb=2.0,
        default_ctx_k=4,
    ))
    tier1: TierConfig = field(default_factory=lambda: TierConfig(
        model="qwen2.5:7b",
        base_url="http://localhost:11434",
        timeout=60.0,
        provider="ollama",
        idle_ttl=300.0,
        vram_estimate_gb=5.0,
        default_ctx_k=8,
    ))
    tier2: TierConfig = field(default_factory=lambda: TierConfig(
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key="",
        timeout=120.0,
        provider="deepseek",
        vram_estimate_gb=0.0,  # 云端不占显存
        default_ctx_k=32,
    ))

    # ── 全局开关（核心） ──
    degradation_enabled: bool = True   # 启用自动降级
    vram_check_enabled: bool = True    # 启用显存感知
    min_vram_gb: float = 8.0           # 最低可用显存（GB）

    # ── V12.0 增强功能开关 ──
    vram_cache_ttl: float = 2.0        # 显存状态缓存 TTL（秒）
    priority_queue_enabled: bool = True  # 启用优先级队列
    max_degradations: int = 3          # 单次请求最大降级次数
    dynamic_ctx_enabled: bool = True   # 启用动态上下文调整
    preload_enabled: bool = False      # 启用预测性预热（默认关闭）
    preload_lead_time: float = 5.0     # 预热提前量（秒）

    # ── 动态上下文配置（k tokens） ──
    ctx_simple_k: int = 4
    ctx_medium_k: int = 8
    ctx_complex_k: int = 32

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

    # 常用模型判定阈值（近 N 次使用中出现比例）
    frequent_model_threshold: float = 0.3  # 使用占比 >= 30% 视为常用


@dataclass
class RouteDecision:
    """路由决策结果"""

    model: str
    tier: int           # 0 / 1 / 2
    source: str         # "local" | "cloud"
    task_type: str      # "simple" | "medium" | "complex"
    degraded_from: Optional[int] = None  # 从哪一层降级而来
    context_window_k: Optional[int] = None  # 实际使用的 context window（k tokens）
    degradation_reason: Optional[str] = None  # 降级原因


@dataclass
class VramStatus:
    """显存状态信息"""

    total_gb: float = 0.0       # 总显存（GB）
    used_gb: float = 0.0        # 已使用（GB）
    free_gb: float = 0.0        # 可用（GB）
    source: str = "unknown"     # 数据来源：pynvml / nvidia-smi / estimated / unknown
    timestamp: float = 0.0      # 采样时间戳
    gpu_count: int = 0          # GPU 数量

    @property
    def usage_ratio(self) -> float:
        """显存使用率（0.0 ~ 1.0）"""
        if self.total_gb <= 0:
            return 0.0
        return self.used_gb / self.total_gb

    def is_available(self, required_gb: float) -> bool:
        """检查是否有足够可用显存"""
        return self.free_gb >= required_gb

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_gb": round(self.total_gb, 2),
            "used_gb": round(self.used_gb, 2),
            "free_gb": round(self.free_gb, 2),
            "usage_ratio": round(self.usage_ratio, 3),
            "source": self.source,
            "gpu_count": self.gpu_count,
        }


@dataclass
class DegradationRecord:
    """降级记录"""

    timestamp: float
    task_type: str
    from_tier: int
    to_tier: int
    reason: str  # "vram_insufficient" / "model_unavailable" / "invocation_failed" / "timeout"
    context_snapshot: dict[str, Any] = field(default_factory=dict)


# ── 模型优先级队列 ────────────────────────────────────────────


class ModelPriorityQueue:
    """模型优先级队列

    管理所有已知模型的优先级，显存不足时按优先级从低到高卸载。

    优先级定义：
    - P0（最高）：当前正在使用的模型
    - P1（高）：用户常用模型 / 近期使用过的模型
    - P2（中）：系统推荐模型
    - P3（低）：冷门模型
    """

    def __init__(self, frequent_threshold: float = 0.3) -> None:
        self._frequent_threshold = frequent_threshold
        # tier -> priority
        self._priorities: dict[int, ModelPriority] = {}
        # tier -> 最近使用次数（滑动窗口）
        self._usage_counts: dict[int, int] = {}
        # 总请求数（滑动窗口内）
        self._total_requests: int = 0
        # 使用历史（滑动窗口，最多 100 条）
        self._usage_history: deque[int] = deque(maxlen=100)
        # 当前活跃中的 tier 集合
        self._active_tiers: set[int] = set()
        # 系统推荐模型 tier 列表
        self._recommended_tiers: list[int] = [0, 1]
        self._logger = logger.bind(component="model_priority_queue")

    def set_active(self, tier: int) -> None:
        """标记某层模型为当前活跃（P0）"""
        self._active_tiers.add(tier)
        self._priorities[tier] = ModelPriority.P0_CURRENT
        self._record_usage(tier)
        self._recalculate_priorities()

    def set_inactive(self, tier: int) -> None:
        """标记某层模型不再活跃"""
        self._active_tiers.discard(tier)
        self._recalculate_priorities()

    def add_recommended(self, tier: int) -> None:
        """添加为系统推荐模型"""
        if tier not in self._recommended_tiers:
            self._recommended_tiers.append(tier)
        self._recalculate_priorities()

    def _record_usage(self, tier: int) -> None:
        """记录使用次数"""
        self._usage_counts[tier] = self._usage_counts.get(tier, 0) + 1
        self._usage_history.append(tier)
        self._total_requests = len(self._usage_history)

    def _recalculate_priorities(self) -> None:
        """重新计算所有 tier 的优先级"""
        for tier in range(3):  # 0, 1, 2
            if tier in self._active_tiers:
                self._priorities[tier] = ModelPriority.P0_CURRENT
            elif self._is_frequent(tier):
                self._priorities[tier] = ModelPriority.P1_FREQUENT
            elif tier in self._recommended_tiers:
                self._priorities[tier] = ModelPriority.P2_RECOMMENDED
            else:
                self._priorities[tier] = ModelPriority.P3_RARE

    def _is_frequent(self, tier: int) -> bool:
        """判断是否为常用模型"""
        if self._total_requests < 5:
            return False  # 样本不足，不判定为常用
        count = self._usage_counts.get(tier, 0)
        return (count / self._total_requests) >= self._frequent_threshold

    def get_priority(self, tier: int) -> ModelPriority:
        """获取指定层的优先级"""
        return self._priorities.get(tier, ModelPriority.P3_RARE)

    def get_unload_order(self) -> list[int]:
        """获取卸载顺序（优先级从低到高，即先卸载的排前面）

        返回按卸载优先级排序的 tier 列表。
        云端模型（tier2）不占显存，永远排在最后或不参与。
        """
        tiers = [t for t in range(3) if t != 2]  # 排除云端
        tiers.sort(key=lambda t: (self.get_priority(t).value, t), reverse=True)
        # reverse=True 意味着 P3_RARE (3) 排在前面，先卸载
        return tiers

    def get_eviction_candidates(self, loaded_tiers: list[int]) -> list[int]:
        """获取可卸载候选列表（仅包含已加载的本地模型）

        Args:
            loaded_tiers: 当前已加载的 tier 列表

        Returns:
            按卸载优先级排序的 tier 列表（先卸载的在前）
        """
        candidates = [t for t in loaded_tiers if t != 2 and t not in self._active_tiers]
        candidates.sort(key=lambda t: self.get_priority(t).value, reverse=True)
        return candidates

    def stats(self) -> dict[str, Any]:
        return {
            "priorities": {f"tier{t}": p.name for t, p in self._priorities.items()},
            "active_tiers": sorted(self._active_tiers),
            "recommended_tiers": self._recommended_tiers,
            "total_requests_window": self._total_requests,
            "usage_counts": {f"tier{t}": c for t, c in self._usage_counts.items()},
        }


# ── 调度器主类 ────────────────────────────────────────────────


class ThreeTierModelRouter:
    """三层模型架构规则版调度器（单例 · V12.0 增强版）

    实现 3B 调度 + 7B 按需 + 云端兜底 的智能路由。

    核心能力（V12.0 增强）：
    1. 任务分类：基于关键词 + 文本长度的规则分类器
    2. 路由决策：根据任务类型选择最优模型层
    3. 自动降级：上层不可用时自动降级到下一层
    4. 显存感知增强：三级探测 + 缓存，精准感知显存状态
    5. 模型优先级队列：P0-P3 四级，低显存按优先级卸载
    6. 低显存自动降级：auto_degrade() 智能降级链
    7. 动态上下文调整：根据任务类型和显存动态调整 context window
    8. 预测性预热：preload_for_task() 提前预热对应模型
    9. 模型预热/卸载：按需加载、空闲自动释放
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

        # ── V12.0 增强组件 ──

        # 显存状态缓存
        self._vram_cache: Optional[VramStatus] = None
        self._vram_cache_lock = asyncio.Lock()

        # 模型优先级队列
        self._priority_queue: Optional[ModelPriorityQueue] = None

        # 降级历史记录（最近 100 条）
        self._degradation_history: deque[DegradationRecord] = deque(maxlen=100)

        # 降级原因统计
        self._degradation_reason_stats: dict[str, int] = {}

        # 预热任务追踪
        self._preload_tasks: dict[str, asyncio.Task] = {}

        # 统计（增强）
        self._stats: dict[str, int] = {
            "total_requests": 0,
            "tier0_requests": 0,
            "tier1_requests": 0,
            "tier2_requests": 0,
            "degradation_count": 0,
            "vram_triggered_degradations": 0,  # 显存不足触发的降级
            "ctx_shrink_count": 0,  # context 缩小次数
            "preload_hit_count": 0,  # 预热命中次数
            "preload_miss_count": 0,  # 预热未命中次数
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

        # 全局基础配置
        cfg.degradation_enabled = os.getenv(
            "MODEL_ROUTER_DEGRADATION_ENABLED", "true"
        ).lower() == "true"
        cfg.vram_check_enabled = os.getenv(
            "MODEL_ROUTER_VRAM_CHECK_ENABLED", "true"
        ).lower() == "true"
        cfg.min_vram_gb = float(os.getenv("MODEL_ROUTER_MIN_VRAM_GB", str(cfg.min_vram_gb)))

        # ── V12.0 增强配置 ──
        cfg.vram_cache_ttl = float(os.getenv(
            "MODEL_ROUTER_VRAM_CACHE_TTL", str(cfg.vram_cache_ttl)
        ))
        cfg.priority_queue_enabled = os.getenv(
            "MODEL_ROUTER_PRIORITY_QUEUE_ENABLED", "true"
        ).lower() == "true"
        cfg.max_degradations = int(os.getenv(
            "MODEL_ROUTER_MAX_DEGRADATIONS", str(cfg.max_degradations)
        ))
        cfg.dynamic_ctx_enabled = os.getenv(
            "MODEL_ROUTER_DYNAMIC_CTX_ENABLED", "true"
        ).lower() == "true"
        cfg.preload_enabled = os.getenv(
            "MODEL_ROUTER_PRELOAD_ENABLED", "false"
        ).lower() == "true"
        cfg.preload_lead_time = float(os.getenv(
            "MODEL_ROUTER_PRELOAD_LEAD_TIME", str(cfg.preload_lead_time)
        ))

        # 动态 context 配置
        cfg.ctx_simple_k = int(os.getenv("MODEL_ROUTER_CTX_SIMPLE_K", str(cfg.ctx_simple_k)))
        cfg.ctx_medium_k = int(os.getenv("MODEL_ROUTER_CTX_MEDIUM_K", str(cfg.ctx_medium_k)))
        cfg.ctx_complex_k = int(os.getenv("MODEL_ROUTER_CTX_COMPLEX_K", str(cfg.ctx_complex_k)))

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

        # 初始化优先级队列
        if self.config.priority_queue_enabled:
            self._priority_queue = ModelPriorityQueue(
                frequent_threshold=self.config.frequent_model_threshold
            )
            # tier0 和 tier1 默认是推荐模型
            if self.config.tier0.enabled:
                self._priority_queue.add_recommended(0)
            if self.config.tier1.enabled:
                self._priority_queue.add_recommended(1)

        # 启动空闲清理任务（用于 tier1 自动卸载）
        self._cleanup_task = asyncio.create_task(self._idle_cleanup_loop())

        # 尝试预热 tier0 模型
        if self.config.tier0.enabled:
            asyncio.create_task(self._warmup_tier0())

        self._logger.info(
            "model_router_initialized_v12",
            tier0_enabled=self.config.tier0.enabled,
            tier1_enabled=self.config.tier1.enabled,
            tier2_enabled=self.config.tier2.enabled,
            tier0_model=self.config.tier0.model,
            tier1_model=self.config.tier1.model,
            tier2_model=self.config.tier2.model,
            vram_check_enabled=self.config.vram_check_enabled,
            priority_queue_enabled=self.config.priority_queue_enabled,
            dynamic_ctx_enabled=self.config.dynamic_ctx_enabled,
            preload_enabled=self.config.preload_enabled,
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

        # 取消所有预热任务
        for task in self._preload_tasks.values():
            task.cancel()
        self._preload_tasks.clear()

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
            return await self._route_simple(context)
        elif task_type == "medium":
            return await self._route_medium(context)
        elif task_type == "complex":
            return await self._route_complex(context)
        else:
            # 未知类型默认走 medium
            self._logger.warning("unknown_task_type", task_type=task_type)
            return await self._route_medium(context)

    async def _route_simple(self, context: dict[str, Any]) -> RouteDecision:
        """simple 任务路由 → tier0（3B）"""
        cfg = self.config.tier0
        if cfg.enabled and await self._check_tier_available(0):
            ctx_k = self._calculate_context_window("simple", 0)
            return RouteDecision(
                model=cfg.model,
                tier=0,
                source="local",
                task_type="simple",
                context_window_k=ctx_k,
            )

        # tier0 不可用，尝试 tier1
        if self.config.degradation_enabled:
            if self.config.tier1.enabled and await self._check_tier_available(1):
                if await self._vram_allows_tier(1):
                    self._stats["degradation_count"] += 1
                    self._record_degradation("simple", 0, 1, "model_unavailable", context)
                    self._logger.warning("degrade_simple_to_tier1")
                    ctx_k = self._calculate_context_window("simple", 1)
                    return RouteDecision(
                        model=self.config.tier1.model,
                        tier=1,
                        source="local",
                        task_type="simple",
                        degraded_from=0,
                        degradation_reason="model_unavailable",
                        context_window_k=ctx_k,
                    )
            # 再不行尝试 tier2
            if self.config.tier2.enabled and await self._check_tier_available(2):
                self._stats["degradation_count"] += 1
                self._record_degradation("simple", 0, 2, "model_unavailable", context)
                self._logger.warning("degrade_simple_to_tier2")
                ctx_k = self._calculate_context_window("simple", 2)
                return RouteDecision(
                    model=self.config.tier2.model,
                    tier=2,
                    source="cloud",
                    task_type="simple",
                    degraded_from=0,
                    degradation_reason="model_unavailable",
                    context_window_k=ctx_k,
                )

        raise RuntimeError("No available model tier for simple task")

    async def _route_medium(self, context: dict[str, Any]) -> RouteDecision:
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
                        self._stats["vram_triggered_degradations"] += 1
                        self._record_degradation("medium", 1, 0, "vram_insufficient", context)
                        ctx_k = self._calculate_context_window("medium", 0)
                        return RouteDecision(
                            model=self.config.tier0.model,
                            tier=0,
                            source="local",
                            task_type="medium",
                            degraded_from=1,
                            degradation_reason="vram_insufficient",
                            context_window_k=ctx_k,
                        )

            ctx_k = self._calculate_context_window("medium", 1)
            return RouteDecision(
                model=cfg.model,
                tier=1,
                source="local",
                task_type="medium",
                context_window_k=ctx_k,
            )

        # tier1 不可用，降级到 tier0
        if self.config.degradation_enabled:
            if self.config.tier0.enabled and await self._check_tier_available(0):
                self._stats["degradation_count"] += 1
                self._record_degradation("medium", 1, 0, "model_unavailable", context)
                self._logger.warning("degrade_medium_to_tier0")
                ctx_k = self._calculate_context_window("medium", 0)
                return RouteDecision(
                    model=self.config.tier0.model,
                    tier=0,
                    source="local",
                    task_type="medium",
                    degraded_from=1,
                    degradation_reason="model_unavailable",
                    context_window_k=ctx_k,
                )
            # 再不行尝试 tier2
            if self.config.tier2.enabled and await self._check_tier_available(2):
                self._stats["degradation_count"] += 1
                self._record_degradation("medium", 1, 2, "model_unavailable", context)
                self._logger.warning("degrade_medium_to_tier2")
                ctx_k = self._calculate_context_window("medium", 2)
                return RouteDecision(
                    model=self.config.tier2.model,
                    tier=2,
                    source="cloud",
                    task_type="medium",
                    degraded_from=1,
                    degradation_reason="model_unavailable",
                    context_window_k=ctx_k,
                )

        raise RuntimeError("No available model tier for medium task")

    async def _route_complex(self, context: dict[str, Any]) -> RouteDecision:
        """complex 任务路由 → tier2（云端），不可用降级到 tier1"""
        cfg = self.config.tier2
        if cfg.enabled and cfg.api_key and await self._check_tier_available(2):
            ctx_k = self._calculate_context_window("complex", 2)
            return RouteDecision(
                model=cfg.model,
                tier=2,
                source="cloud",
                task_type="complex",
                context_window_k=ctx_k,
            )

        # tier2 不可用，降级到 tier1
        if self.config.degradation_enabled:
            if self.config.tier1.enabled and await self._check_tier_available(1):
                # 检查显存
                if self.config.vram_check_enabled and not await self.check_vram_available(tier=1):
                    # 显存不足，继续降级到 tier0
                    if self.config.tier0.enabled and await self._check_tier_available(0):
                        self._stats["degradation_count"] += 1
                        self._stats["vram_triggered_degradations"] += 1
                        self._record_degradation("complex", 2, 0, "vram_insufficient", context)
                        self._logger.warning("degrade_complex_to_tier0")
                        ctx_k = self._calculate_context_window("complex", 0)
                        return RouteDecision(
                            model=self.config.tier0.model,
                            tier=0,
                            source="local",
                            task_type="complex",
                            degraded_from=2,
                            degradation_reason="vram_insufficient",
                            context_window_k=ctx_k,
                        )
                else:
                    self._stats["degradation_count"] += 1
                    self._record_degradation("complex", 2, 1, "model_unavailable", context)
                    self._logger.warning("degrade_complex_to_tier1")
                    ctx_k = self._calculate_context_window("complex", 1)
                    return RouteDecision(
                        model=self.config.tier1.model,
                        tier=1,
                        source="local",
                        task_type="complex",
                        degraded_from=2,
                        degradation_reason="model_unavailable",
                        context_window_k=ctx_k,
                    )

            # 再不行降级到 tier0
            if self.config.tier0.enabled and await self._check_tier_available(0):
                self._stats["degradation_count"] += 1
                self._record_degradation("complex", 2, 0, "model_unavailable", context)
                self._logger.warning("degrade_complex_to_tier0_direct")
                ctx_k = self._calculate_context_window("complex", 0)
                return RouteDecision(
                    model=self.config.tier0.model,
                    tier=0,
                    source="local",
                    task_type="complex",
                    degraded_from=2,
                    degradation_reason="model_unavailable",
                    context_window_k=ctx_k,
                )

        raise RuntimeError("No available model tier for complex task")

    # ── [V12.0] 显存感知增强 ──────────────────────────────

    async def get_vram_usage(self) -> VramStatus:
        """获取当前显存使用情况

        三级探测机制：
        1. pynvml 库（NVIDIA 官方 Python 绑定）
        2. nvidia-smi 命令行工具
        3. 估算（基于已加载模型的预估显存占用）

        结果带 2 秒缓存，避免频繁查询。

        Returns:
            VramStatus 显存状态信息
        """
        # 检查缓存
        now = time.time()
        if (
            self._vram_cache is not None
            and (now - self._vram_cache.timestamp) < self.config.vram_cache_ttl
        ):
            return self._vram_cache

        async with self._vram_cache_lock:
            # 双重检查（加锁后再查一次）
            now = time.time()
            if (
                self._vram_cache is not None
                and (now - self._vram_cache.timestamp) < self.config.vram_cache_ttl
            ):
                return self._vram_cache

            status = await self._probe_vram()
            status.timestamp = now
            self._vram_cache = status
            return status

    async def _probe_vram(self) -> VramStatus:
        """实际探测显存状态（三级探测）"""
        if not self.config.vram_check_enabled:
            return VramStatus(source="disabled")

        # 方法 1：pynvml
        status = await self._probe_vram_pynvml()
        if status is not None:
            return status

        # 方法 2：nvidia-smi
        status = await self._probe_vram_nvidia_smi()
        if status is not None:
            return status

        # 方法 3：基于已加载模型估算
        return self._estimate_vram()

    async def _probe_vram_pynvml(self) -> Optional[VramStatus]:
        """通过 pynvml 探测显存"""
        try:
            import pynvml  # type: ignore
            try:
                pynvml.nvmlInit()
                device_count = pynvml.nvmlDeviceGetCount()
                if device_count == 0:
                    pynvml.nvmlShutdown()
                    return None

                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                total_gb = info.total / (1024**3)
                used_gb = info.used / (1024**3)
                free_gb = info.free / (1024**3)

                pynvml.nvmlShutdown()
                return VramStatus(
                    total_gb=total_gb,
                    used_gb=used_gb,
                    free_gb=free_gb,
                    source="pynvml",
                    gpu_count=device_count,
                )
            except Exception:
                try:
                    pynvml.nvmlShutdown()
                except Exception:
                    pass
                return None
        except ImportError:
            return None

    async def _probe_vram_nvidia_smi(self) -> Optional[VramStatus]:
        """通过 nvidia-smi 命令行探测显存"""
        try:
            # 使用 asyncio 执行子进程，避免阻塞事件循环
            result = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    "nvidia-smi",
                    "--query-gpu=memory.total,memory.used,memory.free",
                    "--format=csv,noheader,nounits",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ),
                timeout=5.0,
            )
            stdout, _ = await result.communicate()
            if result.returncode == 0 and stdout:
                lines = stdout.decode().strip().split("\n")
                gpu_count = len(lines)
                if gpu_count > 0 and lines[0]:
                    parts = lines[0].split(",")
                    if len(parts) >= 3:
                        total_mb = float(parts[0].strip())
                        used_mb = float(parts[1].strip())
                        free_mb = float(parts[2].strip())
                        return VramStatus(
                            total_gb=total_mb / 1024.0,
                            used_gb=used_mb / 1024.0,
                            free_gb=free_mb / 1024.0,
                            source="nvidia-smi",
                            gpu_count=gpu_count,
                        )
        except Exception:
            pass
        return None

    def _estimate_vram(self) -> VramStatus:
        """基于已加载模型估算显存占用

        当无法直接探测显存时，根据已加载的模型进行粗略估算。
        总显存使用 min_vram_gb 作为基准估算值。
        """
        used_gb = 0.0
        for tier in (0, 1):
            if self._model_loaded.get(tier, False):
                cfg = self.config.tier0 if tier == 0 else self.config.tier1
                used_gb += cfg.vram_estimate_gb

        # 估算总显存 = 已用 + 剩余阈值（保守估计）
        free_gb = max(self.config.min_vram_gb - used_gb, 0.5)
        total_gb = used_gb + free_gb

        return VramStatus(
            total_gb=total_gb,
            used_gb=used_gb,
            free_gb=free_gb,
            source="estimated",
            gpu_count=0,
        )

    async def check_vram_available(self, tier: int = 1) -> bool:
        """检查当前显存是否足够加载目标模型

        优先级：
        1. 直接调用 get_vram_usage() 获取精确数据
        2. 与目标模型预估显存比较

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

        required_vram_gb = self.config.tier0.vram_estimate_gb if tier == 0 else self.config.tier1.vram_estimate_gb

        vram = await self.get_vram_usage()
        return vram.is_available(required_vram_gb)

    async def _vram_allows_tier(self, tier: int) -> bool:
        """快速检查某层模型是否能在当前显存下加载（内部用）"""
        if tier == 2:
            return True
        if not self.config.vram_check_enabled:
            return True
        return await self.check_vram_available(tier)

    async def _get_vram_from_m10(self) -> Optional[float]:
        """从 M10 系统卫士获取可用显存（GB）

        预留接口，待 M10 集成后实现。
        当前返回 None 表示不可用。
        """
        # TODO: 集成 M10 系统卫士的显存查询接口
        return None

    # ── [V12.0] 低显存自动降级 ────────────────────────────

    async def auto_degrade(
        self,
        task_type: str,
        context: Optional[dict[str, Any]] = None,
        reason: str = "vram_insufficient",
    ) -> RouteDecision:
        """低显存自动降级

        检测到显存不足时，自动降级到下一层模型。
        降级链：complex → 7B → 3B → 报错

        Args:
            task_type: 任务类型（simple/medium/complex）
            context: 上下文信息
            reason: 降级原因（vram_insufficient / model_unavailable / invocation_failed）

        Returns:
            降级后的 RouteDecision

        Raises:
            RuntimeError: 所有层级都不可用时抛出
        """
        context = context or {}

        # 先尝试正常路由（内部已包含降级逻辑）
        # 这里增加额外的降级原因追踪和次数限制
        decision = await self.route(task_type, context)

        # 如果发生了降级，记录原因
        if decision.degraded_from is not None and decision.degradation_reason is None:
            decision.degradation_reason = reason

        return decision

    def _record_degradation(
        self,
        task_type: str,
        from_tier: int,
        to_tier: int,
        reason: str,
        context: dict[str, Any],
    ) -> None:
        """记录降级事件"""
        record = DegradationRecord(
            timestamp=time.time(),
            task_type=task_type,
            from_tier=from_tier,
            to_tier=to_tier,
            reason=reason,
            context_snapshot={
                "text_len": context.get("text_len", 0),
                "has_system_prompt": bool(context.get("system_prompt")),
            },
        )
        self._degradation_history.append(record)
        self._degradation_reason_stats[reason] = (
            self._degradation_reason_stats.get(reason, 0) + 1
        )

    def get_degradation_stats(self) -> dict[str, Any]:
        """获取降级统计信息"""
        return {
            "total_degradations": self._stats.get("degradation_count", 0),
            "vram_triggered": self._stats.get("vram_triggered_degradations", 0),
            "reason_breakdown": dict(self._degradation_reason_stats),
            "recent_count": len(self._degradation_history),
        }

    # ── [V12.0] 动态上下文调整 ────────────────────────────

    def _calculate_context_window(self, task_type: str, tier: int) -> Optional[int]:
        """根据任务类型和显存情况动态计算 context window 大小

        策略：
        - simple 任务：4k context（省显存）
        - medium 任务：8k context（平衡）
        - complex 任务：32k context（质量优先，显存够才用）
        - 显存紧张时自动缩小 context

        Args:
            task_type: 任务类型
            tier: 目标层级

        Returns:
            context window 大小（k tokens），None 表示使用模型默认
        """
        if not self.config.dynamic_ctx_enabled:
            return None

        # 基础 context window（按任务类型）
        if task_type == "simple":
            base_k = self.config.ctx_simple_k
        elif task_type == "medium":
            base_k = self.config.ctx_medium_k
        elif task_type == "complex":
            base_k = self.config.ctx_complex_k
        else:
            base_k = self.config.ctx_medium_k

        # 云端模型不受显存限制，使用任务类型对应的值
        if tier == 2:
            return base_k

        # 本地模型：根据显存情况调整
        # 使用缓存的显存状态（同步访问，避免 await）
        vram = self._vram_cache
        if vram is not None and vram.source != "disabled":
            usage_ratio = vram.usage_ratio
            # 显存使用率 > 80%，缩小到 75%
            if usage_ratio > 0.8:
                shrunk_k = max(int(base_k * 0.5), 2)  # 最小 2k
                if shrunk_k < base_k:
                    self._stats["ctx_shrink_count"] += 1
                    self._logger.debug(
                        "ctx_window_shrunk",
                        task_type=task_type,
                        tier=tier,
                        original_k=base_k,
                        shrunk_k=shrunk_k,
                        vram_usage=round(usage_ratio, 3),
                    )
                    return shrunk_k
            # 显存使用率 > 60%，缩小到 75%
            elif usage_ratio > 0.6:
                shrunk_k = max(int(base_k * 0.75), 2)
                if shrunk_k < base_k:
                    self._stats["ctx_shrink_count"] += 1
                    return shrunk_k

        return base_k

    def get_context_window_for_task(self, task_type: str, tier: int) -> Optional[int]:
        """获取指定任务和层级的 context window 大小（公开接口）"""
        return self._calculate_context_window(task_type, tier)

    # ── [V12.0] 预测性预热 ────────────────────────────────

    async def preload_for_task(self, task_type: str) -> bool:
        """根据即将到来的任务类型，提前预热对应模型

        预测性预热：在用户开始任务前，提前加载对应模型，减少首次响应延迟。
        例如用户开始写代码前，提前预热 7B 模型。

        Args:
            task_type: 任务类型（simple/medium/complex）

        Returns:
            True 表示预热成功或已预热，False 表示预热失败
        """
        if not self.config.preload_enabled:
            self._logger.debug("preload_disabled", task_type=task_type)
            return False

        # 根据任务类型确定需要预热的 tier
        if task_type == "simple":
            target_tier = 0
        elif task_type == "medium":
            target_tier = 1
        elif task_type == "complex":
            target_tier = 2  # 云端不需要预热，但检查可用性
        else:
            target_tier = 1  # 默认预热 tier1

        task_key = f"task_{task_type}"

        # 如果已有预热任务在运行，等待或直接返回
        if task_key in self._preload_tasks and not self._preload_tasks[task_key].done():
            self._logger.debug("preload_already_running", task_type=task_type)
            return True

        # 如果模型已加载，算预热命中
        if target_tier == 2:
            self._stats["preload_hit_count"] += 1
            return await self._check_tier_available(2)

        if self._model_loaded.get(target_tier, False):
            self._stats["preload_hit_count"] += 1
            self._logger.debug("preload_hit", task_type=task_type, tier=target_tier)
            return True

        self._stats["preload_miss_count"] += 1
        self._logger.info("preload_starting", task_type=task_type, tier=target_tier)

        # 后台执行预热
        async def _do_preload():
            try:
                result = await self.preload_model(target_tier)
                self._logger.info(
                    "preload_complete",
                    task_type=task_type,
                    tier=target_tier,
                    success=result,
                )
                return result
            except Exception as exc:
                self._logger.warning(
                    "preload_failed",
                    task_type=task_type,
                    tier=target_tier,
                    error=str(exc),
                )
                return False

        task = asyncio.create_task(_do_preload())
        self._preload_tasks[task_key] = task

        # 不等完成，直接返回（预热是后台操作）
        return True

    def cancel_preload(self, task_type: str) -> None:
        """取消指定任务类型的预热"""
        task_key = f"task_{task_type}"
        if task_key in self._preload_tasks:
            task = self._preload_tasks.pop(task_key)
            if not task.done():
                task.cancel()
                self._logger.debug("preload_cancelled", task_type=task_type)

    # ── [V12.0] 模型优先级队列接口 ────────────────────────

    @property
    def priority_queue(self) -> Optional[ModelPriorityQueue]:
        """获取优先级队列实例"""
        return self._priority_queue

    def get_unload_candidates(self) -> list[int]:
        """获取当前可卸载的模型（按优先级从低到高排序）

        当显存不足时，按此顺序卸载模型。
        """
        if not self.config.priority_queue_enabled or self._priority_queue is None:
            # 没有优先级队列时，按 tier 从高到低卸载
            return [t for t in (1, 0) if self._model_loaded.get(t, False)]

        loaded = [t for t in (0, 1) if self._model_loaded.get(t, False)]
        return self._priority_queue.get_eviction_candidates(loaded)

    async def evict_low_priority_models(self, needed_gb: float) -> int:
        """卸载低优先级模型以释放显存

        Args:
            needed_gb: 需要释放的显存（GB）

        Returns:
            实际卸载的模型数量
        """
        if not self.config.priority_queue_enabled or self._priority_queue is None:
            return 0

        candidates = self.get_unload_candidates()
        evicted = 0
        freed_gb = 0.0

        for tier in candidates:
            if freed_gb >= needed_gb:
                break
            cfg = self.config.tier0 if tier == 0 else self.config.tier1
            if await self.unload_model(tier):
                evicted += 1
                freed_gb += cfg.vram_estimate_gb
                self._logger.info(
                    "evicted_low_priority_model",
                    tier=tier,
                    model=cfg.model,
                    freed_gb=cfg.vram_estimate_gb,
                    priority=self._priority_queue.get_priority(tier).name,
                )

        return evicted

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
                # 更新优先级队列
                if self._priority_queue is not None:
                    self._priority_queue.set_active(tier)
                return True

            cfg = self.config.tier0 if tier == 0 else self.config.tier1

            if not cfg.enabled:
                return False

            if not self._ollama_client:
                return False

            # 显存感知：加载前检查
            if self.config.vram_check_enabled and tier == 1:
                if not await self.check_vram_available(tier):
                    self._logger.warning(
                        "preload_skipped_vram_insufficient",
                        tier=tier,
                        model=cfg.model,
                    )
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
                    # 失效显存缓存（模型加载后显存状态变化）
                    self._vram_cache = None
                    # 更新优先级队列
                    if self._priority_queue is not None:
                        self._priority_queue.set_active(tier)
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

        # 更新优先级队列
        if self._priority_queue is not None:
            self._priority_queue.set_inactive(tier)

        # tier0 是常驻模型，通常不卸载
        # 但允许显式调用以释放资源
        cfg = self.config.tier0 if tier == 0 else self.config.tier1

        if not self._ollama_client:
            self._model_loaded[tier] = False
            self._vram_cache = None  # 失效显存缓存
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
                self._vram_cache = None  # 失效显存缓存
                self._logger.info("model_unloaded", tier=tier, model=cfg.model)
                return True
            return False
        except Exception as exc:
            self._logger.debug("model_unload_failed", tier=tier, error=str(exc))
            # 即使 API 调用失败，也标记为未加载
            self._model_loaded[tier] = False
            self._vram_cache = None
            return True

    async def _idle_cleanup_loop(self) -> None:
        """后台空闲清理循环

        定期检查 tier1 模型是否空闲超时，超时则自动卸载。
        优先级队列启用时，只卸载低优先级模型。
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
                # 优先级队列检查：只有非高优先级才卸载
                if self._priority_queue is not None:
                    priority = self._priority_queue.get_priority(tier)
                    if priority <= ModelPriority.P1_FREQUENT:
                        # P0 或 P1 级别的模型，延长 TTL，不立即卸载
                        self._logger.debug(
                            "skip_unload_high_priority",
                            tier=tier,
                            priority=priority.name,
                            idle_seconds=round(idle_time, 1),
                        )
                        return cleaned

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
        decision = await self.route(task_type, {"system_prompt": system_text, "text_len": len(user_text)})

        self._stats["total_requests"] += 1
        self._stats[f"tier{decision.tier}_requests"] += 1

        # 更新优先级队列
        if self._priority_queue is not None:
            self._priority_queue.set_active(decision.tier)

        self._logger.info(
            "routed_chat",
            task_type=task_type,
            tier=decision.tier,
            model=decision.model,
            source=decision.source,
            degraded_from=decision.degraded_from,
            degradation_reason=decision.degradation_reason,
            context_window_k=decision.context_window_k,
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
        decision = await self._route_simple({})
        self._stats["total_requests"] += 1
        self._stats[f"tier{decision.tier}_requests"] += 1
        if self._priority_queue is not None:
            self._priority_queue.set_active(decision.tier)
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
        decision = await self._route_medium({})
        self._stats["total_requests"] += 1
        self._stats[f"tier{decision.tier}_requests"] += 1
        if self._priority_queue is not None:
            self._priority_queue.set_active(decision.tier)
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
        decision = await self._route_complex({})
        self._stats["total_requests"] += 1
        self._stats[f"tier{decision.tier}_requests"] += 1
        if self._priority_queue is not None:
            self._priority_queue.set_active(decision.tier)
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
            return await self._invoke_cloud(messages, decision, **kwargs)
        else:
            return await self._invoke_ollama(tier, messages, decision, **kwargs)

    async def _invoke_ollama(
        self,
        tier: int,
        messages: list[dict[str, str]],
        decision: RouteDecision,
        **kwargs,
    ) -> str:
        """调用本地 Ollama 模型"""
        cfg = self.config.tier0 if tier == 0 else self.config.tier1

        if not self._ollama_client:
            raise RuntimeError("Ollama client not initialized")

        payload: dict[str, Any] = {
            "model": kwargs.get("model", cfg.model),
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
            },
        }

        # 动态 context window
        if decision.context_window_k and decision.context_window_k > 0:
            payload["options"]["num_ctx"] = decision.context_window_k * 1024

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
        decision: RouteDecision,
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

        payload: dict[str, Any] = {
            "model": kwargs.get("model", cfg.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "stream": False,
        }

        # 云端也支持动态 context（通过 max_tokens 间接控制）
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
        degradation_count = 0
        for next_tier in range(failed_tier - 1, -1, -1):
            if degradation_count >= self.config.max_degradations:
                self._logger.warning("max_degradations_reached", count=degradation_count)
                break

            try:
                cfg = (
                    self.config.tier0 if next_tier == 0
                    else self.config.tier1 if next_tier == 1
                    else self.config.tier2
                )
                if not cfg.enabled:
                    continue

                # 显存检查（本地模型）
                if next_tier in (0, 1) and self.config.vram_check_enabled:
                    if not await self.check_vram_available(next_tier):
                        self._logger.debug(
                            "skip_degrade_tier_vram_insufficient",
                            tier=next_tier,
                        )
                        continue

                self._logger.warning(
                    "degrading_to_lower_tier",
                    from_tier=failed_tier,
                    to_tier=next_tier,
                )
                self._stats["degradation_count"] += 1
                self._stats[f"tier{next_tier}_requests"] += 1
                degradation_count += 1

                # 更新优先级队列
                if self._priority_queue is not None:
                    self._priority_queue.set_active(next_tier)

                ctx_k = self._calculate_context_window("degraded", next_tier)
                decision = RouteDecision(
                    model=cfg.model,
                    tier=next_tier,
                    source="local" if next_tier < 2 else "cloud",
                    task_type="degraded",
                    degraded_from=failed_tier,
                    degradation_reason="invocation_failed",
                    context_window_k=ctx_k,
                )
                self._record_degradation("degraded", failed_tier, next_tier, "invocation_failed", {})
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
        """获取调度器统计信息（V12.0 增强版）"""
        result: dict[str, Any] = {
            **self._stats,
            "tier0_loaded": self._model_loaded.get(0, False),
            "tier1_loaded": self._model_loaded.get(1, False),
            "tier2_available": bool(self.config.tier2.enabled and self.config.tier2.api_key),
            "tier0_model": self.config.tier0.model,
            "tier1_model": self.config.tier1.model,
            "tier2_model": self.config.tier2.model,
            "degradation_enabled": self.config.degradation_enabled,
            "vram_check_enabled": self.config.vram_check_enabled,
            # V12.0 增强功能状态
            "priority_queue_enabled": self.config.priority_queue_enabled,
            "dynamic_ctx_enabled": self.config.dynamic_ctx_enabled,
            "preload_enabled": self.config.preload_enabled,
            # 降级统计
            "degradation_stats": self.get_degradation_stats(),
        }

        # 显存状态（如果有缓存）
        if self._vram_cache is not None:
            result["vram_status"] = self._vram_cache.to_dict()

        # 优先级队列状态
        if self._priority_queue is not None:
            result["priority_queue"] = self._priority_queue.stats()

        return result

    def reset_stats(self) -> None:
        """重置统计计数"""
        for key in self._stats:
            self._stats[key] = 0
        self._degradation_reason_stats.clear()
        self._degradation_history.clear()


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
