from __future__ import annotations

"""Skill 技能路由器."""

import asyncio
import time
from typing import Any

import structlog

from skill_cluster.resilience.circuit_breaker import ErrorClassifier
from skill_cluster.config import IdempotencyConfig, RateLimitConfig
from skill_cluster.interfaces import ISkill, SkillInvokeRequest, SkillInvokeResult
from skill_cluster.middleware import MiddlewarePipeline
from skill_cluster.permissions import SkillPermissionManager
from skill_cluster.resilience.rate_limiter import rate_limit_middleware
from skill_cluster.skill_registry import SkillRegistry

logger = structlog.get_logger()

# 【向后兼容】ErrorClassifier 已迁移至 circuit_breaker.py
# 此处保留导入别名，旧代码无需修改即可继续使用
__all__ = ["ErrorClassifier"]


class SkillRouter:
    """技能路由器（单例模式）.

    提供技能的挂载、卸载、调用与健康检查.
    invoke 方法已拆分为权限检查、技能解析、依赖验证、
    执行调用四个独立阶段，便于单元测试和中间件拦截。

    【P0-2 修复】已接入 MiddlewarePipeline 中间件管道，
    支持缓存、事件、弹性、指标、日志等横切关注点。
    """

    _instance: "SkillRouter | None" = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "SkillRouter":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        permission_manager: SkillPermissionManager | None = None,
        middleware: MiddlewarePipeline | None = None,
        rate_limit_config: RateLimitConfig | None = None,
        idempotency_config: IdempotencyConfig | None = None,
    ) -> None:
        if hasattr(self, "_initialized"):
            return
        self._registry = registry or SkillRegistry()
        self._permission_manager = permission_manager or SkillPermissionManager()
        # 【P0-2 修复】初始化中间件管道
        self.middleware = middleware or MiddlewarePipeline()
        # 【限流中间件】默认启用，可通过配置关闭
        self._rate_limit_config = rate_limit_config or RateLimitConfig()
        if self._rate_limit_config.enabled:
            self.middleware.use(
                rate_limit_middleware(self._rate_limit_config)
            )
            logger.info(
                "rate_limit_middleware_enabled",
                global_rate=self._rate_limit_config.global_rate,
                per_skill_rate=self._rate_limit_config.per_skill_rate,
                per_ip_rate=self._rate_limit_config.per_ip_rate,
            )
        # 【幂等中间件】默认关闭，可通过配置启用
        self._idempotency_config = idempotency_config or IdempotencyConfig()
        self._idempotency_manager: "IdempotencyManager | None" = None
        if self._idempotency_config.enabled:
            from skill_cluster.resilience.idempotency import IdempotencyManager
            from skill_cluster.middleware import idempotent_middleware
            self._idempotency_manager = IdempotencyManager(
                ttl=self._idempotency_config.ttl,
                max_entries=self._idempotency_config.max_entries,
            )
            self.middleware.use(
                idempotent_middleware(
                    self._idempotency_manager,
                    key_source=self._idempotency_config.key_source,
                    header_name=self._idempotency_config.header_name,
                )
            )
            logger.info(
                "idempotency_middleware_enabled",
                ttl=self._idempotency_config.ttl,
                max_entries=self._idempotency_config.max_entries,
                key_source=self._idempotency_config.key_source,
                header_name=self._idempotency_config.header_name,
            )
        self._initialized = True

    @classmethod
    def _reset_instance(cls) -> None:
        """重置单例实例（仅用于测试）."""
        cls._instance = None

    @classmethod
    async def get_instance(
        cls,
        registry: SkillRegistry | None = None,
        permission_manager: SkillPermissionManager | None = None,
    ) -> "SkillRouter":
        """获取路由器实例（异步安全单例）."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(registry, permission_manager)
            return cls._instance

    def use(self, middleware: Any) -> "SkillRouter":
        """【P0-2 修复】注册中间件.

        便捷方法，等价于 router.middleware.use(mw)。

        Args:
            middleware: 中间件函数.

        Returns:
            self，支持链式调用.
        """
        self.middleware.use(middleware)
        return self

    @property
    def idempotency_manager(self) -> "IdempotencyManager | None":
        """获取幂等性管理器实例.

        Returns:
            IdempotencyManager 实例，若未启用则返回 None.
        """
        return self._idempotency_manager

    def mount(self, skill: ISkill, trace_id: str = "") -> None:
        """挂载技能.

        Args:
            skill: 技能实例.
            trace_id: 调用链路追踪 ID.
        """
        self._registry.register(skill, trace_id=trace_id)
        logger.info(
            "skill_mounted",
            skill_id=skill.manifest.skill_id,
            trace_id=trace_id,
        )

    def unmount(self, skill_id: str, trace_id: str = "") -> None:
        """卸载技能.

        Args:
            skill_id: 技能 ID.
            trace_id: 调用链路追踪 ID.
        """
        self._registry.unregister(skill_id, trace_id=trace_id)
        logger.info(
            "skill_unmounted",
            skill_id=skill_id,
            trace_id=trace_id,
        )

    # ---- invoke 拆分阶段 ----

    def _check_permission(
        self, agent_id: str, sid: str, action: str, trace_id: str
    ) -> SkillInvokeResult | None:
        """阶段1: 权限检查.

        Returns:
            无权限时返回错误结果，有权限返回 None.
        """
        if not self._permission_manager.check(
            agent_id, sid, "read", action=action
        ):
            logger.warning(
                "invoke_unauthorized",
                skill_id=sid,
                agent_id=agent_id,
                trace_id=trace_id,
            )
            return SkillInvokeResult(
                skill_id=sid,
                action=action,
                status="unauthorized",
                error="Permission denied",
                latency_ms=0.0,
                trace_id=trace_id,
            )
        return None

    def _resolve_skill(
        self, sid: str, action: str, trace_id: str
    ) -> SkillInvokeResult | ISkill:
        """阶段2: 技能解析.

        Returns:
            技能实例或错误结果.
        """
        skill = self._registry.get_skill(sid)
        if skill is None:
            logger.warning(
                "invoke_not_found",
                skill_id=sid,
                trace_id=trace_id,
            )
            return SkillInvokeResult(
                skill_id=sid,
                action=action,
                status="not_found",
                error=f"Skill {sid} not found",
                latency_ms=0.0,
                trace_id=trace_id,
            )
        return skill

    def _check_dependencies(
        self,
        skill: ISkill,
        sid: str,
        action: str,
        trace_id: str,
    ) -> SkillInvokeResult | None:
        """阶段3: 依赖验证.

        Returns:
            依赖缺失时返回错误结果，否则返回 None.
        """
        manifest = skill.manifest
        for dep in manifest.dependencies:
            if self._registry.get_skill(dep) is None:
                return SkillInvokeResult(
                    skill_id=sid,
                    action=action,
                    status="failure",
                    error=f"Dependency {dep} not satisfied",
                    latency_ms=0.0,
                    trace_id=trace_id,
                )
        return None

    async def _execute_skill(
        self,
        skill: ISkill,
        request: SkillInvokeRequest,
        timeout: int,
    ) -> SkillInvokeResult:
        """阶段4: 带超时的技能执行.

        区分可重试错误与不可重试错误。
        """
        try:
            return await asyncio.wait_for(
                skill.invoke(request), timeout=timeout
            )
        except asyncio.TimeoutError:
            return SkillInvokeResult(
                skill_id=request.skill_id,
                action=request.action,
                status="timeout",
                error=f"Timeout after {timeout}s",
                latency_ms=0.0,
                trace_id=request.trace_id,
            )
        except Exception as e:
            error_type, retryable = ErrorClassifier.classify(e)
            status = "failure"
            error_msg = str(e)
            if retryable:
                error_msg = f"[RETRYABLE:{error_type}] {error_msg}"
            logger.error(
                "invoke_error",
                skill_id=request.skill_id,
                action=request.action,
                trace_id=request.trace_id,
                error_type=error_type,
                retryable=retryable,
                error=error_msg,
            )
            return SkillInvokeResult(
                skill_id=request.skill_id,
                action=request.action,
                status=status,
                error=error_msg,
                latency_ms=0.0,
                trace_id=request.trace_id,
            )

    async def invoke(
        self, request: SkillInvokeRequest, agent_id: str
    ) -> SkillInvokeResult:
        """调用技能.

        【P0-2 修复】已接入中间件管道（洋葱模型）。
        中间件在四阶段调用逻辑的最外层包裹，
        所有内置中间件（缓存/事件/弹性/指标/日志）均可正常工作。

        已拆分为四个独立阶段，便于测试和中间件拦截。

        Args:
            request: 调用请求.
            agent_id: Agent 标识.

        Returns:
            调用结果.
        """
        # 【P0-2 修复】通过中间件管道执行四阶段调用
        async def _handler() -> SkillInvokeResult:
            return await self._invoke_core(request, agent_id)

        return await self.middleware.execute(request, agent_id, _handler)

    async def _invoke_core(
        self, request: SkillInvokeRequest, agent_id: str
    ) -> SkillInvokeResult:
        """invoke 核心四阶段逻辑（不含中间件）."""
        start = time.perf_counter()
        sid = request.skill_id

        # 阶段1: 权限检查
        result = self._check_permission(
            agent_id, sid, request.action, request.trace_id
        )
        if result is not None:
            result.latency_ms = (time.perf_counter() - start) * 1000
            return result

        # 阶段2: 技能解析
        skill_or_error = self._resolve_skill(
            sid, request.action, request.trace_id
        )
        if isinstance(skill_or_error, SkillInvokeResult):
            skill_or_error.latency_ms = (
                time.perf_counter() - start
            ) * 1000
            return skill_or_error
        skill = skill_or_error

        # 阶段3: 依赖验证
        result = self._check_dependencies(
            skill, sid, request.action, request.trace_id
        )
        if result is not None:
            result.latency_ms = (time.perf_counter() - start) * 1000
            return result

        # 阶段4: 执行调用
        timeout = request.timeout or 30
        result = await self._execute_skill(skill, request, timeout)

        latency = (time.perf_counter() - start) * 1000
        result.latency_ms = latency
        if result.status == "success":
            logger.info(
                "invoke_completed",
                skill_id=sid,
                action=request.action,
                agent_id=agent_id,
                trace_id=request.trace_id,
                latency_ms=latency,
            )
        return result

    async def invoke_batch(
        self, requests: list[SkillInvokeRequest], agent_id: str
    ) -> list[SkillInvokeResult]:
        """批量调用技能（带并发控制）.

        Args:
            requests: 调用请求列表.
            agent_id: Agent 标识.

        Returns:
            调用结果列表.
        """
        semaphore = asyncio.Semaphore(10)  # 默认最大并发10

        async def _invoke_with_limit(req: SkillInvokeRequest) -> SkillInvokeResult:
            async with semaphore:
                return await self.invoke(req, agent_id)

        tasks = [_invoke_with_limit(req) for req in requests]
        return await asyncio.gather(*tasks)

    async def health_check_all(self) -> dict[str, dict]:
        """健康检查所有已挂载技能（并行执行）.

        Returns:
            技能健康状态字典.
        """
        async def _check(sid: str) -> tuple[str, dict]:
            skill = self._registry.get_skill(sid)
            if skill is None:
                return sid, {"healthy": False, "error": "Skill not found"}
            try:
                return sid, await skill.health()
            except Exception as e:
                return sid, {"healthy": False, "error": str(e)}

        sids = self._registry.list_skills()
        results_list = await asyncio.gather(*[_check(sid) for sid in sids])
        return dict(results_list)
