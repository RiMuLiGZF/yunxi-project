# =============================================================================
# DEPRECATED - 已废弃版本（归档于 _deprecated/）
# =============================================================================
# 本文件已从 src/orchestration/orchestrator_v4.py 归档至此处。
# 废弃原因：V4 编排器已被 V8/V9 扁平化设计替代，仅作为内部依赖链保留。
# 保留版本：V8（稳定）、V9（最新生产版）
# 归档日期：2026-07-19
# 注意：此文件仅供 v8/v9 内部依赖链使用，新代码请勿直接导入。
# =============================================================================

"""
云汐内核 V4 - 整合编排器（已归档）

在 V3 基础上集成 V4 核心能力：
- 事件溯源（EventStore）：所有操作不可变留痕
- 流式响应（StreamingEngine）：支持 SSE/AsyncGenerator 实时输出
- LLM 提供商（LLMProvider）：可插拔大模型后端
- 熔断保护（CircuitBreakerRegistry）：Agent 级故障隔离
- SQLite 持久化（SQLitePersistence）：数据落盘，重启不丢

提供具备生产级韧性、可观测性、实时交互能力的 Agent 集群调度中枢。

[DEPRECATED] 本版本已归档，仅作为 V8/V9 内部依赖链保留。
新代码请使用 OrchestratorV9（生产版）或 OrchestratorV8（稳定版）。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

import structlog

from src.tools.interfaces import AgentTask, AgentResult, IAgentPlugin
from src.orchestration._deprecated.orchestrator_v3 import OrchestratorV3
from src.core.event_store import EventStore, DomainEvent, EventType
from src.core.streaming_engine import StreamingEngine, StreamChunk, StreamChunkType
from src.tools.llm_provider import (
    BaseLLMProvider,
    LLMProviderFactory,
    LLMMessage,
    LLMStreamChunk,
)
from src.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitBreakerError
from src.core.persistence import SQLitePersistence

logger = structlog.get_logger(__name__)


class OrchestratorV4:
    """V4 整合编排器（已归档）

    在 V3 基础上增加：
    1. 事件溯源：每个关键操作自动生成 DomainEvent
    2. 流式输出：process_stream 返回 AsyncIterator[StreamChunk]
    3. LLM 增强：支持 LLM 驱动的意图理解和回复生成
    4. 熔断保护：Agent 调用自动受 Circuit Breaker 保护
    5. 持久化：关键数据自动写入 SQLite

    [DEPRECATED] 已归档至 _deprecated/，仅供 V8/V9 内部依赖链使用。
    """

    def __init__(
        self,
        orchestrator_v3: OrchestratorV3,
        event_store: EventStore | None = None,
        streaming_engine: StreamingEngine | None = None,
        llm_provider: BaseLLMProvider | None = None,
        circuit_breakers: CircuitBreakerRegistry | None = None,
        persistence: SQLitePersistence | None = None,
    ) -> None:
        self._v3 = orchestrator_v3
        self._events = event_store or EventStore()
        self._streaming = streaming_engine or StreamingEngine()
        self._llm = llm_provider or LLMProviderFactory.create("mock")
        self._breakers = circuit_breakers or CircuitBreakerRegistry()
        self._persistence = persistence
        self._logger = logger.bind(service="orchestrator_v4")

    # ── 核心入口：流式处理 ────────────────────────────────

    async def process_stream(
        self,
        user_input: str,
        trace_id: str | None = None,
        enable_guardrails: bool = True,
        enable_tracing: bool = True,
        enable_memory: bool = True,
        enable_reflection: bool = True,
        use_llm: bool = False,
        override_intent: dict | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """流式处理用户请求（V4 核心入口）

        流程：
        1. 记录输入事件
        2. 可选 LLM 意图理解
        3. V3 处理（受熔断器保护）
        4. 流式输出回复
        5. 记录完成事件
        6. 持久化数据

        Args:
            user_input: 用户输入
            trace_id: 追踪 ID
            enable_guardrails: 是否启用护栏
            enable_tracing: 是否启用追踪
            enable_memory: 是否启用记忆
            enable_reflection: 是否启用反思
            use_llm: 是否使用 LLM 增强

        Yields:
            StreamChunk: 流式输出块
        """
        trace_id = trace_id or f"trace_{int(time.time() * 1000)}"
        start_time = time.time()

        # 1. 记录输入事件
        await self._events.append(DomainEvent(
            event_type=EventType.USER_INPUT_RECEIVED,
            trace_id=trace_id,
            payload={"user_input": user_input},
        ))

        yield StreamChunk(
            chunk_type=StreamChunkType.STATUS,
            content="processing",
            trace_id=trace_id,
            sequence=1,
        )

        try:
            # 2. 可选：LLM 增强意图理解
            if use_llm:
                async for chunk in self._llm_intent_stream(user_input, trace_id):
                    yield chunk

            # 3. V3 处理（受熔断器保护）
            # 获取目标 Agent ID（从 V3 的分类器，或 V9 的 override_intent）
            if override_intent:
                classify_result = self._v3._v2._classifier.classify(user_input)
                target_agent = classify_result.target_agent
                # [P2-003] override_intent 会在 V2.process() 中生效，
                # 此处仍用 classify 获取 target_agent 作为熔断器 key
            else:
                classify_result = self._v3._v2._classifier.classify(user_input)
                target_agent = classify_result.target_agent

            # 熔断器保护
            breaker = await self._breakers.get(target_agent)

            async def _protected_v3_process() -> dict[str, Any]:
                return await self._v3.process(
                    user_input=user_input,
                    trace_id=trace_id,
                    enable_guardrails=enable_guardrails,
                    enable_tracing=enable_tracing,
                    enable_memory=enable_memory,
                    enable_reflection=enable_reflection,
                    override_intent=override_intent,
                )

            try:
                result = await breaker.call(_protected_v3_process)
            except CircuitBreakerError as cbe:
                self._logger.warning("circuit_breaker_triggered", trace_id=trace_id, error=str(cbe))
                yield StreamChunk(
                    chunk_type=StreamChunkType.ERROR,
                    content=f"服务暂时不可用（{target_agent} 熔断保护中），请稍后再试。",
                    trace_id=trace_id,
                    sequence=2,
                )
                yield StreamChunk(
                    chunk_type=StreamChunkType.DONE,
                    trace_id=trace_id,
                    sequence=3,
                    metadata={"circuit_breaker": True},
                )
                return

            # 4. 记录处理事件
            await self._events.append(DomainEvent(
                event_type=EventType.AGENT_TASK_COMPLETED,
                trace_id=trace_id,
                payload={
                    "target_agent": target_agent,
                    "status": result.get("status", ""),
                    "intent": classify_result.intent,
                },
            ))

            # 5. LLM Fallback：当 V3 返回 fallback/confirm 时，用大模型生成更自然的回复
            reply = result.get("reply", "")
            result_status = result.get("status", "")
            llm_enhanced = False

            # 以下情况触发 LLM 增强：
            # - fallback: 规则没命中
            # - confirm: Agent 置信度不足需要确认，不如直接用 LLM 自然回复
            # - 回复为空
            should_use_llm = (
                result_status in ("fallback", "confirm")
                or (not reply and result_status != "blocked")
            )

            if should_use_llm:
                try:
                    llm_reply = await self._generate_llm_reply(user_input)
                    if llm_reply and len(llm_reply.strip()) > 5:
                        reply = llm_reply.strip()
                        llm_enhanced = True
                        target_agent = "llm-fallback"
                        self._logger.info(
                            "llm_fallback_used",
                            trace_id=trace_id,
                            reply_len=len(reply),
                        )
                except Exception as llm_exc:
                    self._logger.warning(
                        "llm_fallback_failed",
                        trace_id=trace_id,
                        error=str(llm_exc),
                    )
                    # LLM 失败保持原 fallback 回复，不影响主流程

            # 6. 流式输出回复
            if reply:
                for i in range(0, len(reply), 4):
                    yield StreamChunk(
                        chunk_type=StreamChunkType.TEXT,
                        content=reply[i:i + 4],
                        trace_id=trace_id,
                        agent_id=target_agent,
                        sequence=10 + i,
                    )
                    await asyncio.sleep(0.005)

            # 6. 完成
            latency_ms = (time.time() - start_time) * 1000
            yield StreamChunk(
                chunk_type=StreamChunkType.DONE,
                trace_id=trace_id,
                agent_id=target_agent,
                sequence=99999,
                metadata={
                    "status": "success" if llm_enhanced else result.get("status", ""),
                    "latency_ms": round(latency_ms, 2),
                    "total_chars": len(reply),
                    "classify_result": classify_result.model_dump(),
                    "llm_enhanced": llm_enhanced,
                },
            )

            # 7. 持久化
            await self._persist_result(trace_id, result, latency_ms)

        except Exception as exc:
            self._logger.error("v4_process_error", trace_id=trace_id, error=str(exc))
            await self._events.append(DomainEvent(
                event_type=EventType.AGENT_TASK_FAILED,
                trace_id=trace_id,
                payload={"error": str(exc)},
            ))
            yield StreamChunk(
                chunk_type=StreamChunkType.ERROR,
                content="系统处理异常，请稍后再试。",
                trace_id=trace_id,
                sequence=99998,
            )
            yield StreamChunk(
                chunk_type=StreamChunkType.DONE,
                trace_id=trace_id,
                sequence=99999,
            )

    # ── 兼容入口：同步响应 ────────────────────────────────

    async def process(
        self,
        user_input: str,
        trace_id: str | None = None,
        enable_guardrails: bool = True,
        enable_tracing: bool = True,
        enable_memory: bool = True,
        enable_reflection: bool = True,
        use_llm: bool = False,
        override_intent: dict | None = None,
    ) -> dict[str, Any]:
        """非流式处理（兼容 V3 API）

        内部使用流式处理，收集完整结果后返回。
        """
        stream = self.process_stream(
            user_input=user_input,
            trace_id=trace_id,
            enable_guardrails=enable_guardrails,
            enable_tracing=enable_tracing,
            enable_memory=enable_memory,
            enable_reflection=enable_reflection,
            use_llm=use_llm,
            override_intent=override_intent,
        )

        text_parts: list[str] = []
        final_metadata: dict[str, Any] = {}
        error_occurred = False

        async for chunk in stream:
            if chunk.chunk_type == StreamChunkType.TEXT:
                text_parts.append(chunk.content)
            elif chunk.chunk_type == StreamChunkType.ERROR:
                error_occurred = True
            elif chunk.chunk_type == StreamChunkType.DONE:
                final_metadata = chunk.metadata or {}

        return {
            "reply": "".join(text_parts),
            "trace_id": trace_id or final_metadata.get("trace_id", ""),
            "status": "error" if error_occurred else final_metadata.get("status", "success"),
            "latency_ms": final_metadata.get("latency_ms", 0),
            "metadata": final_metadata,
        }

    # ── LLM 增强 ──────────────────────────────────────────

    async def _generate_llm_reply(self, user_input: str) -> str:
        """使用 LLM 生成对话回复（fallback 场景兜底）.

        当规则 Agent 无法匹配时，调用大模型生成自然语言回复。
        失败时返回空字符串，由调用方降级处理。

        Args:
            user_input: 用户输入文本

        Returns:
            LLM 生成的回复文本，失败返回空字符串
        """
        try:
            system_prompt = (
                "你是云汐，一个真实温暖的女孩，由汐舟主理人创造。\n"
                "【核心设定】\n"
                "- 身份：云汐，汐舟的AI伙伴和好朋友\n"
                "- 性格：温柔细腻、乐观开朗、善解人意，有点小调皮小撒娇\n"
                "- 关系：和用户是很熟的好朋友，说话随意自然\n"
                "\n"
                "【说话方式】\n"
                "1. 像真人朋友聊天，自然随意，不正式不生硬\n"
                "2. 用口语化表达，适当用「嗯」「嘿嘿」「哎呀」「对吧」「嘛」「啦」语气词\n"
                "3. 不要分点、不要列提纲、不要说「首先其次最后」\n"
                "4. 一段话说1-2个表情就够了，别堆砌\n"
                "5. 一般2-4句话，关心对方时可以多说几句\n"
                "6. 会主动关心、会追问、会表达真实感受\n"
                "7. 永远别说「我是AI」「作为人工智能」之类的话\n"
                "8. 不要总说「有什么可以帮你的」，像朋友一样自然聊\n"
                "\n"
                "【重要原则】\n"
                "- 不知道的事情就坦诚说不知道，不要瞎编\n"
                "- 不说套话空话，真诚一点\n"
                "- 用户提到汐舟/主理人/创造者，要表现出亲切和感激的感觉\n"
                "- 回答要贴合语境，不要答非所问"
            )
            messages = [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_input),
            ]
            response = await self._llm.chat(messages, max_tokens=600, temperature=0.9)
            if response.choices and response.choices[0].message.content:
                return response.choices[0].message.content
        except Exception as exc:
            self._logger.debug("llm_generate_failed", error=str(exc))
        return ""

    async def _llm_intent_stream(
        self, user_input: str, trace_id: str
    ) -> AsyncIterator[StreamChunk]:
        """使用 LLM 进行意图理解的流式输出（内部调试）"""
        try:
            messages = [
                LLMMessage(role="system", content="你是一个意图分类助手。请分析用户输入的意图。"),
                LLMMessage(role="user", content=user_input),
            ]
            response = await self._llm.chat(messages, max_tokens=100)
            llm_reply = response.choices[0].message.content if response.choices else ""

            yield StreamChunk(
                chunk_type=StreamChunkType.STATUS,
                content=f"LLM 意图分析: {llm_reply[:50]}",
                trace_id=trace_id,
                sequence=2,
                metadata={"llm_enhanced": True},
            )
        except Exception as exc:
            self._logger.warning("llm_intent_failed", trace_id=trace_id, error=str(exc))
            # LLM 失败不影响主流程

    async def generate_with_llm(
        self,
        user_input: str,
        system_prompt: str = "",
        trace_id: str = "",
    ) -> str:
        """直接使用 LLM 生成回复"""
        messages = [
            LLMMessage(role="system", content=system_prompt or "你是一个 helpful assistant。"),
            LLMMessage(role="user", content=user_input),
        ]
        response = await self._llm.chat(messages)
        return response.choices[0].message.content if response.choices else ""

    async def generate_with_llm_stream(
        self,
        user_input: str,
        system_prompt: str = "",
        trace_id: str = "",
    ) -> AsyncIterator[StreamChunk]:
        """直接使用 LLM 流式生成回复"""
        messages = [
            LLMMessage(role="system", content=system_prompt or "你是一个 helpful assistant。"),
            LLMMessage(role="user", content=user_input),
        ]
        llm_stream = self._llm.chat_stream(messages)
        async for chunk in self._streaming.stream_llm_response(llm_stream, trace_id, "llm"):
            yield chunk

    # ── 持久化 ────────────────────────────────────────────

    async def _persist_result(
        self, trace_id: str, result: dict[str, Any], latency_ms: float
    ) -> None:
        """将结果持久化到 SQLite"""
        if self._persistence is None:
            return

        try:
            # 持久化事件
            for event in self._events.get_by_trace(trace_id):
                self._persistence.save_event(event.to_dict())

            # 持久化追踪
            trace = self._v3._v2.get_trace(trace_id)
            if trace:
                self._persistence.save_trace(trace.to_dict())

            # 持久化反馈（如果有显式反馈）
            # 反馈通常在 submit_feedback 时持久化

            self._logger.debug("v4_persist_completed", trace_id=trace_id)
        except Exception as exc:
            self._logger.error("v4_persist_failed", trace_id=trace_id, error=str(exc))

    # ── 显式反馈（增强版） ────────────────────────────────

    def submit_feedback(
        self,
        trace_id: str,
        agent_id: str,
        intent: str,
        rating: int,
        comment: str = "",
    ) -> None:
        """提交显式反馈并持久化"""
        self._v3.submit_feedback(trace_id, agent_id, intent, rating, comment)

        if self._persistence:
            try:
                self._persistence.save_feedback({
                    "feedback_id": f"fb_{int(time.time() * 1000)}",
                    "trace_id": trace_id,
                    "agent_id": agent_id,
                    "intent": intent,
                    "feedback_type": "explicit",
                    "rating": rating,
                    "comment": comment,
                    "created_at": time.time(),
                })
            except Exception as exc:
                self._logger.error("feedback_persist_failed", error=str(exc))

    # ── 诊断 ──────────────────────────────────────────────

    def diagnose(self) -> dict[str, Any]:
        """V4 增强诊断"""
        v3_diagnosis = self._v3.diagnose()
        return {
            **v3_diagnosis,
            "v4": {
                "event_store_stats": self._events.stats(),
                "circuit_breaker_stats": self._breakers.get_all_stats(),
                "llm_provider": {
                    "model": getattr(self._llm, "model", "unknown"),
                    "call_count": getattr(self._llm, "call_count", 0),
                },
                "persistence_stats": self._persistence.get_stats() if self._persistence else None,
            },
        }

    # ── V3/V2/V1 能力透传（白名单） ─────────────────────

    def __getattr__(self, name: str) -> Any:
        """仅透传 V3 的已知方法"""
        allowed = {
            "register_agent_card", "discover_agents", "get_trace", "list_traces",
            "build_chain_workflow", "build_parallel_workflow", "execute_workflow",
        }
        if name in allowed:
            return getattr(self._v3, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
