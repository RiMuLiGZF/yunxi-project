"""
云汐内核 - 多 Agent 集群调度系统
总控调度 Agent 模块

作为调度中枢，负责：
1. 接收用户输入、意图识别、任务路由
2. 结果聚合与异常兜底
3. 多 Agent 串行/并行协作调度
4. 轻量级会话上下文管理
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import structlog
from src.tools.interfaces import (
    AgentTask,
    AgentResult,
    BusMessage,
    ClassifyResult,
    IAgentPlugin,
)
from src.core.intent_classifier import IntentClassifier
from src.core.task_dispatcher import TaskDispatcher

logger = structlog.get_logger(__name__)


class MasterScheduler(IAgentPlugin):
    """总控调度 Agent

    作为云汐内核的调度中枢，实现 IAgentPlugin 接口。
    """

    agent_id: str = "master_scheduler"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "general.fallback",
        "general.schedule",
        "general.system",
    ]

    def __init__(
        self,
        classifier: IntentClassifier,
        dispatcher: TaskDispatcher,
    ) -> None:
        self._classifier = classifier
        self._dispatcher = dispatcher
        self._session_context: dict[str, SessionContext] = {}
        """会话上下文，按 trace_id 索引"""
        self._context_lock: asyncio.Lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._message_bus: Any = None
        self._subscription_ids: list[str] = []
        self._logger = logger.bind(agent_id=self.agent_id)

    # ── IAgentPlugin 生命周期 ─────────────────────────────

    async def on_mount(self, registry: Any) -> None:
        """注册到注册中心时的初始化"""
        # 启动会话上下文清理任务
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._logger.info("master_scheduler_mounted")

    async def on_unmount(self) -> None:
        """注销时的清理"""
        self._running = False
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # 取消消息总线订阅
        for sub_id in self._subscription_ids:
            if self._message_bus:
                await self._message_bus.unsubscribe(sub_id)
        self._subscription_ids.clear()

        self._logger.info("master_scheduler_unmounted")

    # ── 消息总线订阅 ──────────────────────────────────────

    async def subscribe_to_bus(self, bus: Any) -> None:
        """订阅消息总线的 user.input 主题"""
        self._message_bus = bus
        sub_id = await bus.subscribe(
            "user.input",
            self._on_user_input,
            subscriber_id=self.agent_id,
        )
        self._subscription_ids.append(sub_id)
        self._logger.info("subscribed_to_user_input")

    async def _on_user_input(self, message: BusMessage) -> None:
        """处理来自消息总线的用户输入"""
        user_text = message.payload.get("text", "")
        trace_id = message.trace_id or uuid.uuid4().hex
        result = await self.process_input(user_text, trace_id=trace_id)
        # 发布结果回总线
        if self._message_bus:
            reply_msg = BusMessage(
                topic="system.events",
                sender=self.agent_id,
                recipient=message.sender,
                msg_type="scene.result",
                payload={"result": result},
                trace_id=trace_id,
            )
            await self._message_bus.publish(reply_msg)

    # ── 核心处理接口 ──────────────────────────────────────

    async def process_input(
        self,
        user_input: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """处理用户输入

        Args:
            user_input: 用户输入的文本
            trace_id: 链路追踪 ID（可选）

        Returns:
            处理结果字典，包含 reply, trace_id, agent_results 等
        """
        trace_id = trace_id or uuid.uuid4().hex

        # 初始化或获取会话上下文
        context = await self._get_or_create_context(trace_id)
        context.last_input = user_input

        self._logger.info(
            "processing_input",
            trace_id=trace_id,
            input_preview=user_input[:50],
        )

        # 1. 意图识别
        classify_result = self._classifier.classify(user_input)

        # 2. 根据置信度决策路由策略
        if classify_result.confidence >= 0.7:
            # 直接路由
            return await self._route_direct(
                user_input, classify_result, trace_id, context
            )
        elif classify_result.confidence >= 0.4:
            # 请求确认
            return self._route_confirm(classify_result, trace_id)
        else:
            # 通用回复（fallback）
            return self._route_fallback(trace_id)

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """实现 IAgentPlugin.handle_task

        当总控 Agent 自身作为一个目标 Agent 被调用时，
        例如处理系统命令或 fallback 任务。
        """
        trace_id = task.trace_id or task.task_id
        intent = task.intent

        if intent == "general.fallback":
            reply = self._generate_fallback_reply(task.payload)
            return AgentResult(
                task_id=task.task_id,
                trace_id=trace_id,
                agent_id=self.agent_id,
                status="success",
                output={"reply": reply},
            )
        elif intent == "general.system":
            return AgentResult(
                task_id=task.task_id,
                trace_id=trace_id,
                agent_id=self.agent_id,
                status="success",
                output={"reply": "系统状态正常。"},
            )
        else:
            return AgentResult(
                task_id=task.task_id,
                trace_id=trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=f"Unknown intent: {intent}",
            )

    # ── 路由策略 ──────────────────────────────────────────

    async def _route_direct(
        self,
        user_input: str,
        classify_result: ClassifyResult,
        trace_id: str,
        context: SessionContext,
    ) -> dict[str, Any]:
        """直接路由：构造任务并分发"""
        task = AgentTask(
            trace_id=trace_id,
            source="user",
            target=classify_result.target_agent,
            intent=classify_result.intent,
            payload={
                "user_input": user_input,
                "session_data": context.data,
            },
            priority=5,
        )

        # 保存到会话上下文
        context.last_task_id = task.task_id

        # 分发任务
        agent_result = await self._dispatcher.dispatch(task)

        # 如果失败，尝试降级
        if agent_result.status in ("failure", "timeout"):
            self._logger.warning(
                "agent_failed_fallback",
                trace_id=trace_id,
                target=classify_result.target_agent,
                status=agent_result.status,
            )

            # 尝试通用回复降级
            fallback_result = await self._try_fallback(
                user_input, trace_id
            )

            # 如果降级也失败，返回系统级错误
            if fallback_result.status == "failure":
                return {
                    "reply": "系统暂时无法处理，请稍后再试或转交人工。",
                    "trace_id": trace_id,
                    "status": "error",
                    "agent_results": [agent_result.model_dump()],
                }

            return {
                "reply": fallback_result.output.get("reply", ""),
                "trace_id": trace_id,
                "status": "degraded",
                "agent_results": [agent_result.model_dump(), fallback_result.model_dump()],
            }

        # 组装回复
        reply = self._assemble_reply(classify_result, agent_result)
        return {
            "reply": reply,
            "trace_id": trace_id,
            "status": "success",
            "agent_results": [agent_result.model_dump()],
        }

    def _route_confirm(
        self,
        classify_result: ClassifyResult,
        trace_id: str,
    ) -> dict[str, Any]:
        """请求确认：返回确认提示"""
        confirm_message = (
            f"我猜你想处理「{classify_result.intent}」相关的事情，"
            f"需要我帮你处理吗？"
        )
        return {
            "reply": confirm_message,
            "trace_id": trace_id,
            "status": "confirm",
            "classify_result": classify_result.model_dump(),
        }

    def _route_fallback(self, trace_id: str) -> dict[str, Any]:
        """通用回复：低置信度时的默认处理"""
        reply = self._generate_fallback_reply({})
        return {
            "reply": reply,
            "trace_id": trace_id,
            "status": "fallback",
        }

    # ── 结果聚合与回复生成 ────────────────────────────────

    def _assemble_reply(
        self,
        classify_result: ClassifyResult,
        agent_result: AgentResult,
    ) -> str:
        """将 Agent 执行结果组装为回复文本"""
        if agent_result.status == "success" and agent_result.output:
            output = agent_result.output
            # 尝试从 output 中提取 reply 字段
            reply = output.get("reply") or output.get("answer") or output.get("report")
            if reply:
                return str(reply)
            # 通用结构化输出
            return f"处理完成（{classify_result.intent}）"
        elif agent_result.status == "partial":
            return "部分处理完成，请查看详情。"
        elif agent_result.status == "handoff":
            return "已转交其他 Agent 处理。"
        elif agent_result.status == "timeout":
            return "处理超时，请稍后再试。"
        else:
            error_msg = agent_result.error or "未知错误"
            return f"处理失败：{error_msg}"

    async def _try_fallback(
        self, user_input: str, trace_id: str
    ) -> AgentResult:
        """尝试通用回复降级"""
        fallback_task = AgentTask(
            trace_id=trace_id,
            source="master_scheduler",
            target="master_scheduler",
            intent="general.fallback",
            payload={"user_input": user_input},
            priority=10,
        )
        try:
            return await self.handle_task(fallback_task)
        except Exception as exc:
            return AgentResult(
                task_id=fallback_task.task_id,
                trace_id=trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=str(exc),
            )

    def _generate_fallback_reply(self, payload: dict[str, Any]) -> str:
        """生成通用 fallback 回复"""
        return "我不太理解，可以再说详细一些吗？"

    # ── 会话上下文管理 ────────────────────────────────────

    async def _get_or_create_context(
        self, trace_id: str
    ) -> SessionContext:
        """获取或创建会话上下文"""
        async with self._context_lock:
            if trace_id not in self._session_context:
                self._session_context[trace_id] = SessionContext(
                    trace_id=trace_id
                )
            context = self._session_context[trace_id]
            context.last_access_time = time.time()
            return context

    async def _cleanup_loop(self) -> None:
        """定期清理过期的会话上下文（TTL: 5分钟）"""
        TTL_SECONDS = 300  # 5 分钟
        while self._running:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次
                now = time.time()
                expired_keys: list[str] = []
                async with self._context_lock:
                    for trace_id, ctx in self._session_context.items():
                        if now - ctx.last_access_time > TTL_SECONDS:
                            expired_keys.append(trace_id)
                    for key in expired_keys:
                        del self._session_context[key]

                if expired_keys:
                    self._logger.debug(
                        "session_context_cleaned",
                        expired_count=len(expired_keys),
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._logger.error("cleanup_loop_error", error=str(exc))

    # ── 工具方法 ──────────────────────────────────────────

    def get_session_context(self, trace_id: str) -> SessionContext | None:
        """获取指定 trace_id 的会话上下文"""
        return self._session_context.get(trace_id)

    async def clear_session_context(self, trace_id: str) -> None:
        """清除指定 trace_id 的会话上下文"""
        async with self._context_lock:
            self._session_context.pop(trace_id, None)


class SessionContext:
    """会话上下文

    按 trace_id 索引的轻量级会话状态。
    """

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self.created_at: float = time.time()
        self.last_access_time: float = time.time()
        self.last_input: str = ""
        self.last_task_id: str = ""
        self.data: dict[str, Any] = {}

    def __repr__(self) -> str:
        return (
            f"SessionContext(trace_id='{self.trace_id}', "
            f"created_at={self.created_at:.1f})"
        )