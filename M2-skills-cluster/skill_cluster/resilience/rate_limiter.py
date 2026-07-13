from __future__ import annotations

"""令牌桶限流中间件.

为 M2 技能集群提供多维度限流能力，支持全局、按技能ID、按用户ID、按IP
等维度的令牌桶限流。作为中间件接入 MiddlewarePipeline 洋葱模型管道。

核心组件：
- TokenBucket: 令牌桶算法实现
- RateLimiterRegistry: 多维度限流注册中心
- rate_limit_middleware: 限流中间件工厂函数
- RateLimitError: 限流异常
"""

import asyncio
import time
from typing import Any

import structlog

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult

logger = structlog.get_logger()


class RateLimitError(Exception):
    """限流异常.

    Attributes:
        key: 触发限流的 key
        retry_after: 建议重试等待时间（秒）
        limit: 限流上限
        remaining: 剩余令牌数
    """

    def __init__(
        self,
        key: str,
        retry_after: float = 1.0,
        limit: float = 0.0,
        remaining: float = 0.0,
    ) -> None:
        self.key = key
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining
        super().__init__(f"Rate limit exceeded for key: {key}")


class TokenBucket:
    """令牌桶限流器.

    基于令牌桶算法实现的单机限流器，支持异步安全访问。

    Attributes:
        rate: 每秒生成的令牌数
        capacity: 桶的最大容量（令牌数）
        tokens: 当前令牌数
        last_refill_time: 上次补充令牌的时间戳
        rejected_count: 累计拒绝次数
    """

    def __init__(self, rate: float, capacity: float) -> None:
        """初始化令牌桶.

        Args:
            rate: 每秒令牌生成速率（tokens/second）
            capacity: 桶的最大容量
        """
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")

        self.rate: float = rate
        self.capacity: float = capacity
        self.tokens: float = capacity  # 初始满桶
        self.last_refill_time: float = time.monotonic()
        self.rejected_count: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

    def _refill(self) -> None:
        """补充令牌（非线程安全，需外部加锁）."""
        now = time.monotonic()
        elapsed = now - self.last_refill_time
        if elapsed > 0:
            new_tokens = elapsed * self.rate
            self.tokens = min(self.capacity, self.tokens + new_tokens)
            self.last_refill_time = now

    async def acquire(self, tokens: float = 1.0) -> bool:
        """尝试获取指定数量的令牌.

        Args:
            tokens: 需要获取的令牌数，默认 1.0

        Returns:
            是否成功获取令牌
        """
        async with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            self.rejected_count += 1
            return False

    async def acquire_or_wait(
        self, tokens: float = 1.0, timeout: float = 1.0
    ) -> bool:
        """带等待超时的令牌获取.

        如果当前令牌不足，会等待直到有足够令牌或超时。

        Args:
            tokens: 需要获取的令牌数
            timeout: 最大等待时间（秒）

        Returns:
            是否在超时前成功获取令牌
        """
        deadline = time.monotonic() + timeout
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True

                # 计算需要等待的时间
                deficit = tokens - self.tokens
                wait_time = deficit / self.rate
                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    self.rejected_count += 1
                    return False

                # 实际等待时间取较小值
                actual_wait = min(wait_time, remaining)

            # 在锁外等待
            await asyncio.sleep(actual_wait)

    def get_stats(self) -> dict[str, Any]:
        """获取限流器统计信息.

        Returns:
            包含当前令牌数、速率、容量、拒绝数等统计的字典
        """
        # 先补充一次令牌以获得准确的当前值
        self._refill()
        return {
            "rate": self.rate,
            "capacity": self.capacity,
            "tokens": round(self.tokens, 2),
            "rejected_count": self.rejected_count,
            "last_refill_time": self.last_refill_time,
        }

    def reset(self) -> None:
        """重置令牌桶到满桶状态，清零拒绝计数."""
        self.tokens = self.capacity
        self.last_refill_time = time.monotonic()
        self.rejected_count = 0


class RateLimiterRegistry:
    """多维度限流注册中心.

    管理多个令牌桶实例，支持按不同维度（全局、技能ID、用户ID、IP等）
    创建和查询限流器。

    维度 key 命名约定：
    - "global"          : 全局限流
    - "skill:{id}"      : 按技能ID限流
    - "user:{id}"       : 按用户ID限流
    - "ip:{address}"    : 按IP限流
    """

    def __init__(self) -> None:
        """初始化注册中心."""
        self._limiters: dict[str, TokenBucket] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def get_limiter(
        self, key: str, rate: float, capacity: float
    ) -> TokenBucket:
        """获取或创建限流器.

        如果 key 对应的限流器不存在，则使用指定的 rate 和 capacity 创建。
        已存在的限流器不会修改其配置。

        Args:
            key: 限流器标识
            rate: 每秒令牌生成速率（仅新建时生效）
            capacity: 桶容量（仅新建时生效）

        Returns:
            TokenBucket 实例
        """
        async with self._lock:
            if key not in self._limiters:
                self._limiters[key] = TokenBucket(rate, capacity)
                logger.debug(
                    "rate_limiter_created",
                    key=key,
                    rate=rate,
                    capacity=capacity,
                )
            return self._limiters[key]

    async def check(
        self, key: str, tokens: float = 1.0
    ) -> tuple[bool, dict[str, Any]]:
        """检查是否允许通过限流.

        Args:
            key: 限流器标识
            tokens: 需要消耗的令牌数

        Returns:
            (是否允许通过, 限流统计信息)
            统计信息包含: allowed, key, tokens_remaining, limit, retry_after
        """
        limiter = self._limiters.get(key)
        if limiter is None:
            # 未创建的限流器默认放行
            return True, {
                "allowed": True,
                "key": key,
                "tokens_remaining": float("inf"),
                "limit": 0,
                "retry_after": 0.0,
            }

        allowed = await limiter.acquire(tokens)
        stats = limiter.get_stats()
        retry_after = 0.0 if allowed else (tokens - stats["tokens"]) / limiter.rate

        result = {
            "allowed": allowed,
            "key": key,
            "tokens_remaining": stats["tokens"],
            "limit": stats["capacity"],
            "retry_after": round(retry_after, 2),
        }

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                key=key,
                rate=stats["rate"],
                capacity=stats["capacity"],
                tokens_remaining=stats["tokens"],
                rejected_count=stats["rejected_count"],
            )

        return allowed, result

    async def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """获取所有限流器的统计信息.

        Returns:
            所有限流器的统计字典，key 为限流器标识
        """
        async with self._lock:
            return {key: limiter.get_stats() for key, limiter in self._limiters.items()}

    async def reset(self, key: str) -> None:
        """重置指定的限流器.

        Args:
            key: 限流器标识
        """
        async with self._lock:
            if key in self._limiters:
                self._limiters[key].reset()
                logger.debug("rate_limiter_reset", key=key)

    async def reset_all(self) -> None:
        """重置所有限流器."""
        async with self._lock:
            for limiter in self._limiters.values():
                limiter.reset()
            logger.debug("rate_limiter_reset_all", count=len(self._limiters))


# ---- 中间件工厂 ----

# 全局注册中心单例
_registry: RateLimiterRegistry | None = None


def _get_registry() -> RateLimiterRegistry:
    """获取全局限流注册中心单例."""
    global _registry
    if _registry is None:
        _registry = RateLimiterRegistry()
    return _registry


class RateLimitConfig:
    """限流中间件配置.

    Attributes:
        enabled: 是否启用限流
        global_rate: 全局限流速率（tokens/秒）
        global_capacity: 全局限流容量
        per_skill_rate: 按技能限流速率（tokens/秒），0 表示不限制
        per_skill_capacity: 按技能限流容量
        per_ip_rate: 按IP限流速率（tokens/秒），0 表示不限制
        per_ip_capacity: 按IP限流容量
        per_user_rate: 按用户限流速率（tokens/秒），0 表示不限制
        per_user_capacity: 按用户限流容量
        cost_per_request: 每次请求消耗的令牌数
    """

    def __init__(
        self,
        enabled: bool = True,
        global_rate: float = 100.0,
        global_capacity: float = 200.0,
        per_skill_rate: float = 20.0,
        per_skill_capacity: float = 50.0,
        per_ip_rate: float = 10.0,
        per_ip_capacity: float = 30.0,
        per_user_rate: float = 0.0,
        per_user_capacity: float = 0.0,
        cost_per_request: float = 1.0,
    ) -> None:
        self.enabled = enabled
        self.global_rate = global_rate
        self.global_capacity = global_capacity
        self.per_skill_rate = per_skill_rate
        self.per_skill_capacity = per_skill_capacity
        self.per_ip_rate = per_ip_rate
        self.per_ip_capacity = per_ip_capacity
        self.per_user_rate = per_user_rate
        self.per_user_capacity = per_user_capacity
        self.cost_per_request = cost_per_request


def _extract_ip(request: SkillInvokeRequest) -> str | None:
    """从请求中提取客户端 IP.

    优先从 metadata 中获取 client_ip 字段。

    Args:
        request: 技能调用请求

    Returns:
        客户端IP，无法获取则返回 None
    """
    metadata = getattr(request, "metadata", {}) or {}
    return metadata.get("client_ip") or metadata.get("ip")


def _extract_user_id(request: SkillInvokeRequest, agent_id: str) -> str | None:
    """从请求中提取用户ID.

    优先从 metadata 中获取 user_id，其次使用 agent_id。

    Args:
        request: 技能调用请求
        agent_id: Agent 标识

    Returns:
        用户ID，无法获取则返回 None
    """
    metadata = getattr(request, "metadata", {}) or {}
    return metadata.get("user_id") or agent_id


def rate_limit_middleware(
    config: RateLimitConfig | None = None,
    registry: RateLimiterRegistry | None = None,
) -> Any:
    """限流中间件工厂函数.

    创建一个符合 MiddlewarePipeline 规范的限流中间件，
    支持多维度（全局/技能/IP/用户）限流检查。

    限流检查顺序：全局 -> 技能 -> IP -> 用户
    任一维度触发限流即返回限流结果，不再继续后续检查。

    限流响应头信息通过 result.data 中的 _rate_limit 字段传递。

    Args:
        config: 限流配置，为 None 时使用默认配置
        registry: 限流注册中心，为 None 时使用全局单例

    Returns:
        中间件函数，签名符合 Middleware 类型
    """
    cfg = config or RateLimitConfig()
    reg = registry or _get_registry()

    async def _mw(
        request: SkillInvokeRequest,
        agent_id: str,
        next_handler: Any,
    ) -> SkillInvokeResult:
        if not cfg.enabled:
            return await next_handler()

        cost = cfg.cost_per_request
        rate_limit_info: dict[str, Any] = {}

        # ---- 1. 全局限流 ----
        if cfg.global_rate > 0:
            await reg.get_limiter(
                "global", cfg.global_rate, cfg.global_capacity
            )
            allowed, info = await reg.check("global", cost)
            rate_limit_info["global"] = info
            if not allowed:
                return _make_rate_limit_result(
                    request=request,
                    key="global",
                    info=info,
                    detail="Global rate limit exceeded",
                )

        # ---- 2. 按技能限流 ----
        if cfg.per_skill_rate > 0:
            skill_key = f"skill:{request.skill_id}"
            await reg.get_limiter(
                skill_key, cfg.per_skill_rate, cfg.per_skill_capacity
            )
            allowed, info = await reg.check(skill_key, cost)
            rate_limit_info["skill"] = info
            if not allowed:
                return _make_rate_limit_result(
                    request=request,
                    key=skill_key,
                    info=info,
                    detail=f"Skill rate limit exceeded: {request.skill_id}",
                )

        # ---- 3. 按IP限流 ----
        if cfg.per_ip_rate > 0:
            client_ip = _extract_ip(request)
            if client_ip:
                ip_key = f"ip:{client_ip}"
                await reg.get_limiter(
                    ip_key, cfg.per_ip_rate, cfg.per_ip_capacity
                )
                allowed, info = await reg.check(ip_key, cost)
                rate_limit_info["ip"] = info
                if not allowed:
                    return _make_rate_limit_result(
                        request=request,
                        key=ip_key,
                        info=info,
                        detail=f"IP rate limit exceeded: {client_ip}",
                    )

        # ---- 4. 按用户限流 ----
        if cfg.per_user_rate > 0:
            user_id = _extract_user_id(request, agent_id)
            if user_id:
                user_key = f"user:{user_id}"
                await reg.get_limiter(
                    user_key, cfg.per_user_rate, cfg.per_user_capacity
                )
                allowed, info = await reg.check(user_key, cost)
                rate_limit_info["user"] = info
                if not allowed:
                    return _make_rate_limit_result(
                        request=request,
                        key=user_key,
                        info=info,
                        detail=f"User rate limit exceeded: {user_id}",
                    )

        # ---- 所有限流检查通过，执行后续逻辑 ----
        result = await next_handler()

        # 将限流信息附加到结果 data 中（作为 _rate_limit 字段）
        if rate_limit_info and result.data is not None:
            if isinstance(result.data, dict):
                result.data["_rate_limit"] = rate_limit_info
            # 非 dict 类型的 data 不附加限流信息

        return result

    return _mw


def _make_rate_limit_result(
    request: SkillInvokeRequest,
    key: str,
    info: dict[str, Any],
    detail: str,
) -> SkillInvokeResult:
    """构造限流响应结果.

    Args:
        request: 原始请求
        key: 触发限流的 key
        info: 限流统计信息
        detail: 详细错误描述

    Returns:
        SkillInvokeResult，status 为 "failure"，包含限流信息
    """
    return SkillInvokeResult(
        skill_id=request.skill_id,
        action=request.action,
        status="failure",
        data={
            "error_code": "RATE_LIMITED",
            "rate_limit_key": key,
            "retry_after": info.get("retry_after", 1.0),
            "limit": info.get("limit", 0),
            "remaining": info.get("tokens_remaining", 0),
        },
        error=detail,
        latency_ms=0.0,
        trace_id=request.trace_id,
    )


# ---- 便捷 API ----

def get_global_registry() -> RateLimiterRegistry:
    """获取全局限流注册中心.

    Returns:
        全局 RateLimiterRegistry 单例
    """
    return _get_registry()


async def check_rate_limit(
    key: str,
    rate: float,
    capacity: float,
    tokens: float = 1.0,
) -> tuple[bool, dict[str, Any]]:
    """便捷函数：检查指定 key 的限流.

    Args:
        key: 限流器标识
        rate: 速率（仅首次创建时生效）
        capacity: 容量（仅首次创建时生效）
        tokens: 消耗令牌数

    Returns:
        (是否允许, 统计信息)
    """
    reg = _get_registry()
    await reg.get_limiter(key, rate, capacity)
    return await reg.check(key, tokens)
