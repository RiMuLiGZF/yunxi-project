"""令牌桶限流器.

在网关层实现经典令牌桶（Token Bucket）算法，为端云协同调度内核
提供请求速率控制能力。支持全局桶和 per-agent 独立桶的双重限流，
确保单个 Agent 不会耗尽全局配额，也不会因高频请求压垮云端推理服务。

Usage::

    limiter = TokenBucketRateLimiter(max_tokens=50, refill_rate=10)

    # 启动后台令牌补充任务
    await limiter.start()

    # 尝试获取令牌（带超时）
    if await limiter.acquire(tokens=1, timeout=5.0):
        await handle_request(request)

    # 阻塞等待直到获取令牌
    await limiter.wait_for_permit(tokens=1)

    # 关闭限流器
    await limiter.stop()
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 单个令牌桶
# ---------------------------------------------------------------------------

class _TokenBucket:
    """单个令牌桶实例.

    使用 asyncio.Lock 保证在异步环境下的线程安全性。

    Attributes:
        max_tokens: 桶的最大令牌容量.
        tokens: 当前可用令牌数.
        refill_rate: 每秒补充的令牌数.
        last_refill_at: 上次补充令牌的时间戳.
        rejection_count: 被拒绝（令牌不足）的累计次数.
    """

    __slots__ = (
        "max_tokens", "tokens", "refill_rate",
        "last_refill_at", "rejection_count", "_lock",
    )

    def __init__(
        self,
        max_tokens: float,
        refill_rate: float,
        initial_tokens: float | None = None,
    ) -> None:
        self.max_tokens: float = max_tokens
        self.tokens: float = initial_tokens if initial_tokens is not None else max_tokens
        self.refill_rate: float = refill_rate
        self.last_refill_at: float = time.monotonic()
        self.rejection_count: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

    def _refill(self) -> None:
        """根据流逝时间补充令牌（不获取锁，调用方需持锁）."""
        now = time.monotonic()
        elapsed = now - self.last_refill_at
        if elapsed > 0:
            added = elapsed * self.refill_rate
            self.tokens = min(self.max_tokens, self.tokens + added)
            self.last_refill_at = now

    async def try_acquire(self, tokens: float = 1.0) -> bool:
        """尝试获取指定数量的令牌.

        Args:
            tokens: 需要获取的令牌数量.

        Returns:
            True 表示获取成功，False 表示令牌不足.
        """
        async with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            self.rejection_count += 1
            return False

    async def get_available(self) -> float:
        """获取当前可用令牌数（含补充）.

        Returns:
            补充后的当前可用令牌数.
        """
        async with self._lock:
            self._refill()
            return self.tokens


# ---------------------------------------------------------------------------
# 限流器统计快照
# ---------------------------------------------------------------------------

class RateLimiterStats(BaseModel):
    """限流器统计快照.

    用于 Prometheus 指标暴露和运维监控面板。

    Attributes:
        global_tokens: 全局桶当前可用令牌数.
        global_max_tokens: 全局桶最大容量.
        global_refill_rate: 全局桶每秒补充速率.
        global_rejection_count: 全局桶累计拒绝次数.
        agent_count: 已注册的 agent 桶数量.
        agent_buckets: 各 agent 桶的详细状态.
    """
    global_tokens: float = Field(description="全局桶当前可用令牌数")
    global_max_tokens: float = Field(description="全局桶最大容量")
    global_refill_rate: float = Field(description="全局桶每秒补充速率")
    global_rejection_count: int = Field(description="全局桶累计拒绝次数")
    agent_count: int = Field(description="已注册的 agent 桶数量")
    agent_buckets: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="各 agent 桶详细状态"
    )


# ---------------------------------------------------------------------------
# TokenBucketRateLimiter 主类
# ---------------------------------------------------------------------------

class TokenBucketRateLimiter:
    """令牌桶限流器.

    实现全局令牌桶 + per-agent 令牌桶的双重限流策略。
    请求必须同时通过全局桶和对应 agent 桶的令牌检查才能被放行。

    后台 asyncio 任务定期为所有桶补充令牌，默认每 100ms 执行一次。

    Attributes:
        max_tokens: 全局桶最大令牌容量.
        refill_rate: 全局桶每秒补充令牌数.
        refill_interval_ms: 令牌补充间隔（毫秒）.
        agent_max_tokens: per-agent 桶最大令牌容量.
        agent_refill_rate: per-agent 桶每秒补充令牌数.
    """

    def __init__(
        self,
        max_tokens: float = 50.0,
        refill_rate: float = 10.0,
        refill_interval_ms: float = 100.0,
        agent_max_tokens: float | None = None,
        agent_refill_rate: float | None = None,
    ) -> None:
        """初始化限流器.

        Args:
            max_tokens: 全局桶最大令牌容量，默认 50.
            refill_rate: 全局桶每秒补充令牌数，默认 10.
            refill_interval_ms: 后台令牌补充间隔（毫秒），默认 100.
            agent_max_tokens: per-agent 桶最大容量，默认为全局容量的 20%.
            agent_refill_rate: per-agent 桶每秒补充速率，默认为全局速率的 20%.
        """
        self.max_tokens: float = max_tokens
        self.refill_rate: float = refill_rate
        self.refill_interval_ms: float = refill_interval_ms

        # per-agent 桶配置：默认为全局配额的 20%，保证公平性
        self.agent_max_tokens: float = (
            agent_max_tokens if agent_max_tokens is not None else max_tokens * 0.2
        )
        self.agent_refill_rate: float = (
            agent_refill_rate if agent_refill_rate is not None else refill_rate * 0.2
        )

        # 全局令牌桶
        self._global_bucket: _TokenBucket = _TokenBucket(
            max_tokens=max_tokens, refill_rate=refill_rate
        )

        # per-agent 令牌桶集合
        self._agent_buckets: dict[str, _TokenBucket] = {}

        # 用于 agent 桶创建时的并发控制
        self._agent_registry_lock: asyncio.Lock = asyncio.Lock()

        # 后台补充任务句柄
        self._refill_task: asyncio.Task[None] | None = None
        self._running: bool = False

        logger.info(
            "rate_limiter.init",
            max_tokens=max_tokens,
            refill_rate=refill_rate,
            refill_interval_ms=refill_interval_ms,
            agent_max_tokens=self.agent_max_tokens,
            agent_refill_rate=self.agent_refill_rate,
        )

    # ---- 生命周期管理 ----

    async def start(self) -> None:
        """启动后台令牌补充任务.

        应在事件循环启动后、开始接收请求前调用。
        """
        if self._running:
            logger.warning("rate_limiter.already_running")
            return
        self._running = True
        self._refill_task = asyncio.create_task(self._refill_loop())
        logger.info("rate_limiter.started")

    async def stop(self) -> None:
        """停止限流器，取消后台补充任务.

        应在应用关闭时调用，确保资源正确释放。
        """
        self._running = False
        if self._refill_task is not None:
            self._refill_task.cancel()
            try:
                await self._refill_task
            except asyncio.CancelledError:
                pass
            self._refill_task = None
        logger.info(
            "rate_limiter.stopped",
            global_rejections=self._global_bucket.rejection_count,
        )

    # ---- 后台补充循环 ----

    async def _refill_loop(self) -> None:
        """后台令牌补充循环.

        每隔 refill_interval_ms 毫秒为全局桶和所有 agent 桶补充令牌。
        """
        interval_sec = self.refill_interval_ms / 1000.0
        logger.debug(
            "rate_limiter.refill_loop.start",
            interval_ms=self.refill_interval_ms,
        )
        try:
            while self._running:
                await asyncio.sleep(interval_sec)
                # 补充全局桶
                await self._global_bucket.get_available()
                # 补充所有 agent 桶
                async with self._agent_registry_lock:
                    for bucket in self._agent_buckets.values():
                        await bucket.get_available()
        except asyncio.CancelledError:
            logger.debug("rate_limiter.refill_loop.cancelled")

    # ---- 获取 agent 桶 ----

    def get_agent_bucket(self, agent_name: str) -> _TokenBucket:
        """获取指定 Agent 的令牌桶，不存在则自动创建.

        Args:
            agent_name: Agent 名称，用作桶标识.

        Returns:
            该 Agent 对应的 _TokenBucket 实例.
        """
        if agent_name not in self._agent_buckets:
            bucket = _TokenBucket(
                max_tokens=self.agent_max_tokens,
                refill_rate=self.agent_refill_rate,
            )
            self._agent_buckets[agent_name] = bucket
            logger.debug(
                "rate_limiter.agent_bucket.created",
                agent_name=agent_name,
                max_tokens=self.agent_max_tokens,
                refill_rate=self.agent_refill_rate,
            )
        return self._agent_buckets[agent_name]

    # ---- 核心限流接口 ----

    async def acquire(self, tokens: float = 1.0, timeout: float = 5.0) -> bool:
        """尝试在超时内获取令牌（全局桶 + agent 桶双重检查）.

        如果指定了 agent_name，则需同时通过全局桶和对应 agent 桶的令牌检查。
        若未指定 agent_name，仅检查全局桶。

        Args:
            tokens: 需要获取的令牌数量.
            timeout: 最大等待时间（秒），0 表示不等待直接返回.

        Returns:
            True 表示成功获取令牌，False 表示超时未获取到.
        """
        return await self._acquire_impl(tokens=tokens, timeout=timeout)

    async def acquire_for_agent(
        self,
        agent_name: str,
        tokens: float = 1.0,
        timeout: float = 5.0,
    ) -> bool:
        """尝试在超时内为指定 Agent 获取令牌.

        需同时通过全局桶和 agent 桶的令牌检查。两个桶独立消耗令牌。

        Args:
            agent_name: Agent 名称.
            tokens: 需要获取的令牌数量.
            timeout: 最大等待时间（秒）.

        Returns:
            True 表示成功获取令牌，False 表示超时未获取到.
        """
        return await self._acquire_impl(
            tokens=tokens, timeout=timeout, agent_name=agent_name
        )

    async def _acquire_impl(
        self,
        tokens: float = 1.0,
        timeout: float = 5.0,
        agent_name: str | None = None,
    ) -> bool:
        """令牌获取的内部实现，支持带超时的轮询重试.

        Args:
            tokens: 令牌数量.
            timeout: 超时秒数.
            agent_name: 可选的 agent 名称.

        Returns:
            是否获取成功.
        """
        deadline = time.monotonic() + timeout
        while True:
            # 检查全局桶
            global_ok = await self._global_bucket.try_acquire(tokens)
            if not global_ok:
                if timeout <= 0 or time.monotonic() >= deadline:
                    logger.debug(
                        "rate_limiter.acquire.rejected.global",
                        agent_name=agent_name,
                        tokens=tokens,
                        available=await self._global_bucket.get_available(),
                    )
                    return False
                await asyncio.sleep(min(0.05, deadline - time.monotonic()))
                continue

            # 若指定了 agent，还需检查 agent 桶
            if agent_name is not None:
                agent_bucket = self.get_agent_bucket(agent_name)
                agent_ok = await agent_bucket.try_acquire(tokens)
                if not agent_ok:
                    # agent 桶不足，需退还全局桶令牌
                    async with self._global_bucket._lock:
                        self._global_bucket._refill()
                        self._global_bucket.tokens = min(
                            self._global_bucket.max_tokens,
                            self._global_bucket.tokens + tokens,
                        )
                    if timeout <= 0 or time.monotonic() >= deadline:
                        logger.debug(
                            "rate_limiter.acquire.rejected.agent",
                            agent_name=agent_name,
                            tokens=tokens,
                            available=await agent_bucket.get_available(),
                        )
                        return False
                    await asyncio.sleep(min(0.05, deadline - time.monotonic()))
                    continue

            return True

    async def wait_for_permit(
        self,
        tokens: float = 1.0,
        agent_name: str | None = None,
    ) -> None:
        """阻塞等待直到获取到足够的令牌.

        无超时限制，会一直等待直到令牌可用。适用于对延迟不敏感
        但必须执行的关键任务。

        Args:
            tokens: 需要获取的令牌数量.
            agent_name: 可选的 agent 名称.
        """
        while True:
            acquired = await self._acquire_impl(
                tokens=tokens, timeout=1.0, agent_name=agent_name
            )
            if acquired:
                return
            logger.debug(
                "rate_limiter.wait_for_permit.retry",
                agent_name=agent_name,
                tokens=tokens,
            )

    async def wait_for_agent_permit(self, agent_name: str, tokens: float = 1.0) -> None:
        """阻塞等待直到为指定 Agent 获取到令牌.

        Args:
            agent_name: Agent 名称.
            tokens: 需要获取的令牌数量.
        """
        await self.wait_for_permit(tokens=tokens, agent_name=agent_name)

    # ---- 统计信息 ----

    async def get_stats(self) -> RateLimiterStats:
        """获取限流器当前统计快照.

        Returns:
            包含全局桶和所有 agent 桶状态的 RateLimiterStats 实例.
        """
        global_tokens = await self._global_bucket.get_available()
        agent_buckets_state: dict[str, dict[str, Any]] = {}
        async with self._agent_registry_lock:
            for name, bucket in self._agent_buckets.items():
                available = await bucket.get_available()
                agent_buckets_state[name] = {
                    "tokens": round(available, 2),
                    "max_tokens": bucket.max_tokens,
                    "refill_rate": bucket.refill_rate,
                    "rejection_count": bucket.rejection_count,
                }
        return RateLimiterStats(
            global_tokens=round(global_tokens, 2),
            global_max_tokens=self.max_tokens,
            global_refill_rate=self.refill_rate,
            global_rejection_count=self._global_bucket.rejection_count,
            agent_count=len(self._agent_buckets),
            agent_buckets=agent_buckets_state,
        )

    def get_stats_sync(self) -> dict[str, Any]:
        """同步获取限流器统计（不含 agent 桶的精确值，仅供快速查询）.

        Returns:
            包含全局桶基本状态的字典.
        """
        return {
            "global_max_tokens": self.max_tokens,
            "global_refill_rate": self.refill_rate,
            "global_rejection_count": self._global_bucket.rejection_count,
            "agent_count": len(self._agent_buckets),
            "agent_max_tokens": self.agent_max_tokens,
            "agent_refill_rate": self.agent_refill_rate,
        }

    # ---- 管理接口 ----

    async def reset_agent_bucket(self, agent_name: str) -> None:
        """重置指定 Agent 的令牌桶至满状态.

        用于测试或运维场景下重置某个 Agent 的配额。

        Args:
            agent_name: Agent 名称.
        """
        async with self._agent_registry_lock:
            if agent_name in self._agent_buckets:
                bucket = self._agent_buckets[agent_name]
                async with bucket._lock:
                    bucket.tokens = bucket.max_tokens
                    bucket.rejection_count = 0
                logger.info(
                    "rate_limiter.agent_bucket.reset",
                    agent_name=agent_name,
                )

    async def reset_all(self) -> None:
        """重置全局桶和所有 agent 桶至满状态.

        用于测试场景下完全重置限流器状态。
        """
        async with self._global_bucket._lock:
            self._global_bucket.tokens = self._global_bucket.max_tokens
            self._global_bucket.rejection_count = 0
        async with self._agent_registry_lock:
            for name, bucket in self._agent_buckets.items():
                async with bucket._lock:
                    bucket.tokens = bucket.max_tokens
                    bucket.rejection_count = 0
        logger.info("rate_limiter.reset_all")

    @property
    def is_running(self) -> bool:
        """限流器后台任务是否运行中."""
        return self._running
