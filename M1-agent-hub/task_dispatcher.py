"""
云汐内核 - 多 Agent 集群调度系统
任务分发器模块

负责将 AgentTask 分发到目标 Agent 执行，
支持超时控制、重试机制、多 Agent 并行协作、
延迟指标记录与消息总线集成。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

import structlog
from interfaces import (
    AgentTask,
    AgentResult,
    BusMessage,
    IAgentPlugin,
    DispatchError,
)
from agent_registry import AgentRegistry
from budget_manager import BudgetManager
from idempotency import IdempotencyManager, generate_task_key

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class TaskDispatcher:
    """任务分发器

    负责将 AgentTask 分发到已注册的 Agent 执行。
    与 AgentRegistry 和 MessageBus 集成。

    [P2-009] 支持可选的 CircuitBreakerRegistry 集成，
    在 _execute_single() 中对每个 Agent 调用提供熔断保护。

    [V10.0-R06] 支持硬件健康探测：根据硬件在线状态调整调度策略，
    离线时任务缓存/降级。
    """

    def __init__(
        self,
        registry: AgentRegistry,
        message_bus: Any,  # MessageBus
        circuit_breaker: Any | None = None,  # [P2-009] CircuitBreakerRegistry
        retry_coordinator: Any | None = None,  # [P3-002] RetryCoordinator
        budget_manager: BudgetManager | None = None,
    ) -> None:
        self._registry: AgentRegistry = registry
        self._bus: Any = message_bus
        self._circuit_breaker: Any | None = circuit_breaker  # [P2-009] 可选熔断器
        self._retry_coordinator: Any | None = retry_coordinator  # [P3-002] 可选重试协调器
        self._budget_manager: BudgetManager | None = budget_manager
        self._logger: structlog.stdlib.BoundLogger = logger.bind(service="task_dispatcher")
        # [V11.2] 幂等性管理器
        self._idempotency: IdempotencyManager = IdempotencyManager(ttl=3600, max_entries=10000)
        from interfaces import CancelToken
        self._cancel_tokens: dict[str, CancelToken] = {}  # [V9.8] 取消令牌映射
        # [V10.0-R06] 硬件状态映射：device_id -> HardwareStatus
        self._hardware_status: dict[str, Any] = {}
        # [V10.0-R06] 断连任务缓存：device_id -> list[AgentTask]
        self._offline_cache: dict[str, list[AgentTask]] = {}
        # [V10.0-R06] 硬件健康回调注册表
        self._hardware_callbacks: list[Callable[[str, bool], Awaitable[None]]] = []

    # ── 单任务分发 ────────────────────────────────────────

    # [V10.0-R06] dispatch方法已移至文件底部，集成硬件状态感知

    def _check_budget(self, task: AgentTask) -> bool:
        """[V9.5] 预算预检：分发前检查预算是否充足"""
        if self._budget_manager is None:
            return True
        estimated_input = len(task.payload.get("query", task.payload.get("input", "")))
        if not self._budget_manager.is_budget_available(
            model=task.payload.get("model", ""),
            input_tokens=estimated_input,
            output_tokens=estimated_input,  # 保守估计输出与输入等量
        ):
            self._logger.warning(
                "budget_exceeded_before_dispatch",
                task_id=task.task_id,
                target=task.target,
            )
            return False
        return True

    def cancel_task(self, task_id: str, reason: str = "") -> bool:
        """[V9.8] 取消正在执行的任务

        Returns:
            True if cancellation was signaled, False if task not found.
        """
        token = self._cancel_tokens.get(task_id)
        if token is None:
            return False
        token.cancel(reason)
        self._logger.info("task_cancelled", task_id=task_id, reason=reason)
        return True

    async def _execute_with_retry(
        self, task: AgentTask, agent: IAgentPlugin, trace_id: str
    ) -> AgentResult:
        """执行任务并支持自动重试

        [P3-002] 接入 RetryCoordinator，废弃硬编码的 1 次重试。
        """
        timeout = task.ttl * 0.8  # 超时取 TTL 的 80%

        # 发送 handoff 事件
        await self._publish_handoff(task)

        # 首次执行
        result = await self._execute_single(agent, task, timeout, trace_id)

        # 接入 RetryCoordinator
        should_retry = (
            result.status in ("failure", "timeout")
            and result.error != f"Agent '{task.target}' not found"
        )
        if should_retry and self._retry_coordinator is not None:
            decision = self._retry_coordinator.check_can_retry(
                task.task_id, agent_id=agent.agent_id
            )
            if decision.allowed:
                self._logger.info(
                    "retrying_task",
                    trace_id=trace_id,
                    task_id=task.task_id,
                    original_error=result.error,
                    delay_seconds=decision.delay_seconds,
                )
                if decision.delay_seconds > 0:
                    await asyncio.sleep(decision.delay_seconds)
                result = await self._execute_single(agent, task, timeout, trace_id)
                if result.status == "success":
                    self._retry_coordinator.record_success(task.task_id)

        return result

    async def _execute_single(
        self, agent: IAgentPlugin, task: AgentTask, timeout: float, trace_id: str
    ) -> AgentResult:
        """执行单个 Agent 调用

        [P2-009] 如果配置了 circuit_breaker，统一使用 breaker.call()
        内部状态机处理 OPEN/HALF_OPEN/CLOSED，不再前置预检。
        """
        # [V9.8] 尝试传递取消令牌
        cancel_token = self._cancel_tokens.get(task.task_id)
        handle_kwargs = {}
        if cancel_token is not None:
            try:
                import inspect
                sig = inspect.signature(agent.handle_task)
                if "cancel_token" in sig.parameters:
                    handle_kwargs["cancel_token"] = cancel_token
            except (ValueError, TypeError):
                # Mock对象或C扩展函数无法inspect，跳过
                pass

        try:
            if self._circuit_breaker is not None:
                # [P2-009] 通过熔断器保护执行
                breaker = self._circuit_breaker.get(agent.agent_id)

                async def _protected_call():
                    return await asyncio.wait_for(
                        agent.handle_task(task, **handle_kwargs), timeout=timeout
                    )

                try:
                    result = await breaker.call(_protected_call)
                    return result
                except Exception as exc:
                    # 区分熔断器拦截和执行异常
                    error_str = str(exc)
                    if "circuit breaker" in error_str.lower():
                        self._logger.warning(
                            "task_blocked_by_circuit_breaker",
                            trace_id=trace_id,
                            task_id=task.task_id,
                            agent_id=agent.agent_id,
                        )
                        return AgentResult(
                            task_id=task.task_id,
                            trace_id=trace_id,
                            agent_id=agent.agent_id,
                            status="failure",
                            error=error_str,
                        )
                    # 其他异常由下方统一处理
                    raise

            result = await asyncio.wait_for(
                agent.handle_task(task, **handle_kwargs), timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            self._logger.warning(
                "task_timeout",
                trace_id=trace_id,
                task_id=task.task_id,
                agent_id=agent.agent_id,
                timeout=timeout,
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=trace_id,
                agent_id=agent.agent_id,
                status="timeout",
                error=f"Task timed out after {timeout:.1f}s",
            )
        except Exception as exc:
            self._logger.error(
                "task_failed",
                trace_id=trace_id,
                task_id=task.task_id,
                agent_id=agent.agent_id,
                error=str(exc),
                exc_info=True,
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=trace_id,
                agent_id=agent.agent_id,
                status="failure",
                error=str(exc),
            )

    # ── 多 Agent 协作 ─────────────────────────────────────

    async def _dispatch_with_collaborators(
        self, task: AgentTask, primary_agent: IAgentPlugin
    ) -> AgentResult:
        """多 Agent 协作分发

        1. 并行分发给所有协作 Agent
        2. 主 Agent 做最终聚合
        """
        collaborator_agents: list[IAgentPlugin] = []
        for collab_id in task.collaborators:
            agent = self._registry.get(collab_id)
            if agent is not None:
                collaborator_agents.append(agent)

        if not collaborator_agents:
            # 没有有效的协作 Agent，退化为单 Agent 执行
            return await self._execute_with_retry(task, primary_agent, task.trace_id)

        # 全局超时保护
        global_timeout = task.ttl * 0.9

        async def _run_collaboration() -> AgentResult:
            # 为协作 Agent 创建子任务
            collab_tasks_list: list[asyncio.Task[AgentResult]] = []
            for agent in collaborator_agents:
                collab_task = asyncio.create_task(
                    self._execute_single(
                        agent, task, task.ttl * 0.4, task.trace_id
                    )
                )
                collab_tasks_list.append(collab_task)

            # 并行执行协作 Agent
            collab_results = await asyncio.gather(
                *collab_tasks_list, return_exceptions=True
            )

            # 处理协作结果
            processed_results: list[AgentResult] = []
            for agent, collab_result in zip(collaborator_agents, collab_results):
                if isinstance(collab_result, Exception):
                    processed_results.append(
                        AgentResult(
                            task_id=task.task_id,
                            trace_id=task.trace_id,
                            agent_id=agent.agent_id,
                            status="failure",
                            error=str(collab_result),
                        )
                    )
                else:
                    processed_results.append(collab_result)

            # 将协作结果注入主任务的副本 payload（不修改原始 task）
            collab_payload = {**task.payload}
            collab_payload["collaborator_results"] = [
                r.model_dump() for r in processed_results
            ]
            collab_task_copy = AgentTask(**task.model_dump())
            collab_task_copy.payload = collab_payload

            # 主 Agent 执行聚合
            primary_result = await self._execute_with_retry(
                collab_task_copy, primary_agent, task.trace_id
            )
            return primary_result

        try:
            return await asyncio.wait_for(_run_collaboration(), timeout=global_timeout)
        except asyncio.TimeoutError:
            self._logger.error(
                "collaboration_timeout",
                trace_id=task.trace_id,
                global_timeout=global_timeout,
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=primary_agent.agent_id,
                status="timeout",
                error=f"Collaboration timed out after {global_timeout:.1f}s",
            )

    # ── 并行分发 ──────────────────────────────────────────

    async def dispatch_parallel(
        self, tasks: list[AgentTask]
    ) -> list[AgentResult]:
        """并行分发多个任务

        [V9.5] 预算预检：过滤超预算任务
        """
        # [V9.5] 批量预算预检
        if self._budget_manager is not None:
            affordable_tasks = []
            for task in tasks:
                if self._check_budget(task):
                    affordable_tasks.append(task)
                else:
                    self._logger.warning(
                        "task_skipped_budget",
                        task_id=task.task_id,
                    )
            tasks = affordable_tasks

        coros = [self.dispatch(task) for task in tasks]
        results = await asyncio.gather(*coros, return_exceptions=True)

        final_results: list[AgentResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    AgentResult(
                        task_id=tasks[i].task_id,
                        trace_id=tasks[i].trace_id,
                        agent_id=tasks[i].target,
                        status="failure",
                        error=str(result),
                    )
                )
            else:
                final_results.append(result)

        return final_results

    # ── 消息总线集成 ──────────────────────────────────────

    async def _publish_handoff(self, task: AgentTask) -> None:
        """发布任务转交事件"""
        msg = BusMessage(
            topic=f"agent.{task.target}",
            sender="task_dispatcher",
            recipient=task.target,
            msg_type="agent.handoff",
            payload={"task_id": task.task_id, "intent": task.intent},
            priority=task.priority,
            trace_id=task.trace_id or task.task_id,
        )
        await self._bus.publish(msg)

    async def _publish_task_complete(
        self, task: AgentTask, result: AgentResult
    ) -> None:
        """发布任务完成事件"""
        msg = BusMessage(
            topic="system.events",
            sender=task.target or "task_dispatcher",
            recipient=None,  # 广播
            msg_type="agent.task_complete",
            payload={
                "task_id": task.task_id,
                "status": result.status,
                "latency_ms": result.latency_ms,
            },
            trace_id=task.trace_id or task.task_id,
        )
        await self._bus.publish(msg)

    # ── [V10.0-R06] 硬件健康探测与断连重连 ────────────────

    def update_hardware_status(self, status: Any) -> None:
        """更新硬件状态（由模块6通过消息总线触发）

        Args:
            status: HardwareStatus 实例
        """
        device_id = getattr(status, "device_id", "")
        if not device_id:
            return

        prev = self._hardware_status.get(device_id)
        was_online = getattr(prev, "online", True) if prev is not None else True
        self._hardware_status[device_id] = status
        is_online = getattr(status, "online", True)

        # 检测断连 -> 重连转换
        if was_online and not is_online:
            self._logger.warning(
                "hardware_disconnected",
                device_id=device_id,
                device_type=getattr(status, "device_type", ""),
            )
        elif not was_online and is_online:
            self._logger.info(
                "hardware_reconnected",
                device_id=device_id,
                cached_tasks=len(self._offline_cache.get(device_id, [])),
            )
            # 触发断连缓存补发
            asyncio.create_task(self._flush_offline_cache(device_id))

    def is_hardware_online(self, device_id: str) -> bool:
        """检查指定硬件是否在线"""
        status = self._hardware_status.get(device_id)
        if status is None:
            return True  # 未知设备默认在线
        return getattr(status, "online", True)

    def should_degrade_for_hardware(self, task: AgentTask) -> bool:
        """判断任务是否需要因硬件状态降级

        降级策略：
        - 手表/戒指离线：降级为纯文本回复（短TTL）
        - 无人机离线：标记为失败，不入缓存（无人机任务通常有实时性要求）
        - 桌面屏离线：正常缓存，重连后补发
        """
        device_id = task.metadata.get("device_id", "")
        if not device_id:
            return False
        if self.is_hardware_online(device_id):
            return False

        device_type = getattr(
            self._hardware_status.get(device_id), "device_type", ""
        )
        if device_type in ("watch", "ring"):
            return True  # 降级为纯文本
        return False

    async def _flush_offline_cache(self, device_id: str) -> None:
        """硬件重连后，批量补发缓存的任务"""
        cached = self._offline_cache.pop(device_id, [])
        if not cached:
            return

        self._logger.info(
            "flushing_offline_cache",
            device_id=device_id,
            count=len(cached),
        )
        for task in cached:
            # 补发前检查硬件是否仍然在线
            if not self.is_hardware_online(device_id):
                self._logger.warning(
                    "hardware_offline_again",
                    device_id=device_id,
                    task_id=task.task_id,
                )
                # 回存缓存
                self._offline_cache.setdefault(device_id, []).append(task)
                break
            await self.dispatch(task)

    async def dispatch(self, task: AgentTask) -> AgentResult:
        """分发单个任务到目标 Agent

        [V10.0-R06] 增加硬件状态感知：
        - 离线设备任务入缓存
        - 手表/戒指离线降级为纯文本

        [V11.2] 增加幂等性保证：
        - 基于 task_id 的幂等键，重复提交相同任务直接返回缓存结果
        - 返回结果中 metrics.is_idempotent_hit 标识是否命中缓存
        """
        start_time = time.time()
        trace_id = task.trace_id or task.task_id

        # [V11.2] 幂等性检查：相同 task_id 的重复提交直接返回缓存结果
        idem_key = generate_task_key(task.task_id)
        exists, cached_result = await self._idempotency.check(idem_key)
        if exists and isinstance(cached_result, AgentResult):
            # 标记幂等命中
            if "is_idempotent_hit" not in cached_result.metrics:
                cached_result.metrics["is_idempotent_hit"] = True
            self._logger.info(
                "dispatch_idempotent_hit",
                task_id=task.task_id,
                trace_id=trace_id,
                target=task.target,
            )
            return cached_result

        # [V10.0-R06] 硬件状态检查
        device_id = task.metadata.get("device_id", "")
        if device_id and not self.is_hardware_online(device_id):
            device_type = getattr(
                self._hardware_status.get(device_id), "device_type", ""
            )
            if device_type == "drone":
                # 无人机任务实时性强，直接失败
                return AgentResult(
                    task_id=task.task_id,
                    trace_id=trace_id,
                    agent_id=task.target,
                    status="failure",
                    error=f"Drone '{device_id}' offline",
                    latency_ms=0.0,
                )
            # 其他设备缓存待重连
            self._offline_cache.setdefault(device_id, []).append(task)
            self._logger.info(
                "task_cached_offline",
                task_id=task.task_id,
                device_id=device_id,
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=trace_id,
                agent_id=task.target,
                status="partial",
                error=f"Device '{device_id}' offline, task cached",
                latency_ms=0.0,
            )

        # [V10.0-R06] 硬件降级检测
        if self.should_degrade_for_hardware(task):
            # 手表/戒指离线：缩短TTL，降级为文本
            task.ttl = 15  # 短TTL
            self._logger.info(
                "task_degraded_for_hardware",
                task_id=task.task_id,
                device_id=device_id,
            )

        self._logger.info(
            "dispatch_started",
            trace_id=trace_id,
            task_id=task.task_id,
            target=task.target,
            intent=task.intent,
        )

        # [V9.5] 预算预检
        if not self._check_budget(task):
            latency_ms = (time.time() - start_time) * 1000
            result = AgentResult(
                task_id=task.task_id,
                trace_id=trace_id,
                agent_id=task.target,
                status="failure",
                error="Budget exceeded before dispatch",
                latency_ms=latency_ms,
            )
            await self._publish_task_complete(task, result)
            return result

        # 1. 查找目标 Agent
        agent = self._registry.get(task.target)
        if agent is None:
            latency_ms = (time.time() - start_time) * 1000
            result = AgentResult(
                task_id=task.task_id,
                trace_id=trace_id,
                agent_id=task.target,
                status="failure",
                error=f"Agent '{task.target}' not found",
                latency_ms=latency_ms,
            )
            await self._publish_task_complete(task, result)
            return result

        # [V9.8] 注册取消令牌
        from interfaces import CancelToken
        cancel_token = CancelToken()
        self._cancel_tokens[task.task_id] = cancel_token

        # 2. 处理多 Agent 协作
        if task.collaborators:
            result = await self._dispatch_with_collaborators(task, agent)
        else:
            # 3. 单 Agent 执行（带重试）
            result = await self._execute_with_retry(task, agent, trace_id)

        # 4. 记录延迟
        latency_ms = (time.time() - start_time) * 1000
        result.latency_ms = latency_ms

        # 5. 发布完成事件
        await self._publish_task_complete(task, result)

        self._logger.info(
            "dispatch_completed",
            trace_id=trace_id,
            task_id=task.task_id,
            status=result.status,
            latency_ms=round(latency_ms, 2),
        )

        # [V9.8] 清理取消令牌
        self._cancel_tokens.pop(task.task_id, None)

        # [V11.2] 存储结果到幂等缓存
        result.metrics["is_idempotent_hit"] = False
        await self._idempotency.store(idem_key, result, is_error=(result.status == "failure"))

        return result