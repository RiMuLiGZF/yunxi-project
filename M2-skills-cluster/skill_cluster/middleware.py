from __future__ import annotations

"""Middleware 中间件管道机制.

为 SkillRouter.invoke() 提供可插拔的中间件管道，支持缓存、熔断、
事件、指标、日志等横切关注点的声明式注入。
"""

import time
from typing import Any, Awaitable, Callable

import structlog

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult
from skill_cluster.event_bus import EventBus, SkillEvent
from skill_cluster.skill_cache import SkillCache
from skill_cluster.circuit_breaker import ResilientSkillInvoker

logger = structlog.get_logger()

# 中间件签名: (request, agent_id, next_handler) -> result
Middleware = Callable[
    [SkillInvokeRequest, str, Callable[[], Awaitable[SkillInvokeResult]]],
    Awaitable[SkillInvokeResult],
]


class MiddlewarePipeline:
    """中间件管道.

    使用洋葱模型（Onion Model）构建调用链，每个中间件可在调用前后执行逻辑。
    """

    def __init__(self) -> None:
        self._middlewares: list[Middleware] = []

    def use(self, mw: Middleware) -> "MiddlewarePipeline":
        """注册中间件（后注册的先执行，类似 Koa）."""
        self._middlewares.append(mw)
        return self

    async def execute(
        self,
        request: SkillInvokeRequest,
        agent_id: str,
        handler: Callable[[], Awaitable[SkillInvokeResult]],
    ) -> SkillInvokeResult:
        """执行中间件管道."""
        # 构建洋葱调用链
        current = handler
        for mw in reversed(self._middlewares):
            _mw = mw
            _next = current

            async def _wrapper(
                req: SkillInvokeRequest = request,
                aid: str = agent_id,
                nxt: Callable[[], Awaitable[SkillInvokeResult]] = _next,
                middleware: Middleware = _mw,
            ) -> SkillInvokeResult:
                return await middleware(req, aid, nxt)

            current = _wrapper

        return await current()


# ---------- 内置中间件 ----------


def cache_middleware(skill_cache: SkillCache) -> Middleware:
    """缓存中间件.

    命中缓存时直接返回，未命中时写入缓存。
    """
    async def _mw(
        request: SkillInvokeRequest,
        agent_id: str,
        next_handler: Callable[[], Awaitable[SkillInvokeResult]],
    ) -> SkillInvokeResult:
        cached = skill_cache.get(request.skill_id, request.action, request.params)
        if cached is not None:
            logger.debug("middleware_cache_hit", skill_id=request.skill_id)
            return SkillInvokeResult(
                skill_id=request.skill_id,
                action=request.action,
                status="success",
                data=cached,
                latency_ms=0.0,
                trace_id=request.trace_id,
            )

        result = await next_handler()
        if result.status == "success" and result.data is not None:
            # 【第六轮优化】透传 MCP cache_scope/ttl_ms 到缓存层
            cache_scope = getattr(request, "cache_scope", "public")
            ttl = None
            ttl_ms = getattr(request, "ttl_ms", None)
            if ttl_ms is not None:
                ttl = ttl_ms / 1000.0
            skill_cache.set(
                request.skill_id,
                request.action,
                request.params,
                result.data,
                ttl=ttl,
                cache_scope=cache_scope,
            )
        return result

    return _mw


def event_middleware(event_bus: EventBus) -> Middleware:
    """事件中间件.

    调用前后自动发布事件。
    """
    async def _mw(
        request: SkillInvokeRequest,
        agent_id: str,
        next_handler: Callable[[], Awaitable[SkillInvokeResult]],
    ) -> SkillInvokeResult:
        await event_bus.publish(
            SkillEvent(
                event_type=f"{request.skill_id}.{request.action}.invoking",
                payload={"agent_id": agent_id, "params": request.params},
                source_skill_id=request.skill_id,
                trace_id=request.trace_id,
            )
        )

        result = await next_handler()

        await event_bus.publish(
            SkillEvent(
                event_type=f"{request.skill_id}.{request.action}.completed",
                payload={
                    "agent_id": agent_id,
                    "status": result.status,
                    "latency_ms": result.latency_ms,
                },
                source_skill_id=request.skill_id,
                trace_id=request.trace_id,
            )
        )
        return result

    return _mw


def resilient_middleware(invoker: ResilientSkillInvoker) -> Middleware:
    """弹性中间件（熔断 + 重试）."""
    async def _mw(
        request: SkillInvokeRequest,
        agent_id: str,
        next_handler: Callable[[], Awaitable[SkillInvokeResult]],
    ) -> SkillInvokeResult:
        try:
            return await invoker.invoke(
                request.skill_id, next_handler
            )
        except Exception as e:
            return SkillInvokeResult(
                skill_id=request.skill_id,
                action=request.action,
                status="failure",
                error=str(e),
                latency_ms=0.0,
                trace_id=request.trace_id,
            )

    return _mw


def metrics_middleware(collector: "MetricsCollector") -> Middleware:
    """指标收集中间件."""
    async def _mw(
        request: SkillInvokeRequest,
        agent_id: str,
        next_handler: Callable[[], Awaitable[SkillInvokeResult]],
    ) -> SkillInvokeResult:
        start = time.perf_counter()
        result = await next_handler()
        latency = (time.perf_counter() - start) * 1000

        collector.record(
            skill_id=request.skill_id,
            action=request.action,
            agent_id=agent_id,
            status=result.status,
            latency_ms=latency,
        )
        return result

    return _mw


def logging_middleware() -> Middleware:
    """日志中间件.

    记录详细的调用前后信息。
    """
    async def _mw(
        request: SkillInvokeRequest,
        agent_id: str,
        next_handler: Callable[[], Awaitable[SkillInvokeResult]],
    ) -> SkillInvokeResult:
        logger.info(
            "middleware_invoke_start",
            skill_id=request.skill_id,
            action=request.action,
            agent_id=agent_id,
            trace_id=request.trace_id,
        )
        result = await next_handler()
        logger.info(
            "middleware_invoke_end",
            skill_id=request.skill_id,
            action=request.action,
            status=result.status,
            latency_ms=result.latency_ms,
            trace_id=request.trace_id,
        )
        return result

    return _mw


def idempotent_middleware(
    manager: "IdempotencyManager",
    key_source: str = "metadata",
    header_name: str = "X-Idempotency-Key",
) -> Middleware:
    """幂等中间件（便捷入口，委托给 idempotency 模块）.

    从请求中提取幂等键，命中缓存则直接返回结果，
    未命中则执行调用并缓存结果。

    Args:
        manager: IdempotencyManager 实例.
        key_source: 幂等键来源策略.
        header_name: 幂等键请求头名称.

    Returns:
        符合 Middleware 签名的中间件函数.
    """
    from skill_cluster.idempotency import idempotent_middleware as _idempotent_mw
    return _idempotent_mw(manager, key_source, header_name)


# 延迟导入避免循环依赖
from skill_cluster.metrics import MetricsCollector
from skill_cluster.idempotency import IdempotencyManager  # noqa: F401
