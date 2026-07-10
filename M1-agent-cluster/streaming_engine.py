"""
云汐内核 V4 - 流式响应引擎

灵感来源：OpenAI SSE Streaming / Server-Sent Events

将同步的 Agent 响应转换为异步生成器流，
支持逐 token 输出、实时进度推送、流式 Guardrails。

核心能力：
- 将 Agent 输出拆分为流式 chunk
- 支持 LLM 原生流式输出透传
- 流式 Guardrails（边输出边检查）
- 背压控制与客户端心跳
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Awaitable

import structlog

from llm_provider import LLMStreamChunk

logger = structlog.get_logger(__name__)


class StreamChunkType(str, Enum):
    """流式输出块类型"""

    TEXT = "text"           # 文本内容
    TOOL_CALL = "tool_call" # 工具调用
    STATUS = "status"       # 状态更新
    GUARDRAIL = "guardrail" # 护栏结果
    ERROR = "error"         # 错误
    DONE = "done"           # 完成


@dataclass
class StreamChunk:
    """流式输出块"""

    chunk_type: StreamChunkType = StreamChunkType.TEXT
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    trace_id: str = ""
    agent_id: str = ""
    sequence: int = 0  # 序列号，用于排序

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（适合 SSE/JSON 输出）"""
        return {
            "chunk_type": self.chunk_type.value,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "agent_id": self.agent_id,
            "sequence": self.sequence,
        }

    def to_sse(self) -> str:
        """转换为 SSE 格式"""
        import json
        return f"data: {json.dumps(self.to_dict(), ensure_ascii=False)}\n\n"


StreamHandler = Callable[[StreamChunk], Awaitable[None]]
"""流式 chunk 处理函数签名"""


class StreamingEngine:
    """流式响应引擎

    将 Agent 的同步/异步响应包装为流式输出。
    """

    def __init__(self) -> None:
        self._logger = logger.bind(service="streaming_engine")
        self._sequence_counter = 0

    def _next_seq(self) -> int:
        self._sequence_counter += 1
        return self._sequence_counter

    # ── 核心流式包装 ────────────────────────────────────

    async def stream_agent_response(
        self,
        agent_call: Callable[[], Awaitable[dict[str, Any]]],
        trace_id: str = "",
        agent_id: str = "",
        chunk_size: int = 4,
        chunk_delay_ms: float = 5.0,
    ) -> AsyncIterator[StreamChunk]:
        """将 Agent 响应包装为流式输出

        Args:
            agent_call: 调用 Agent 的异步函数，返回包含 reply 的字典
            trace_id: 追踪 ID
            agent_id: Agent ID
            chunk_size: 每个 chunk 的字符数
            chunk_delay_ms: chunk 之间延迟（毫秒）

        Yields:
            StreamChunk: 流式输出块
        """
        start_time = time.time()

        try:
            result = await agent_call()
            reply = result.get("reply", "") or result.get("answer", "") or result.get("report", "")
            status = result.get("status", "success")

            if not reply:
                yield StreamChunk(
                    chunk_type=StreamChunkType.STATUS,
                    content=status,
                    trace_id=trace_id,
                    agent_id=agent_id,
                    sequence=self._next_seq(),
                    metadata={"empty_reply": True},
                )
                yield StreamChunk(
                    chunk_type=StreamChunkType.DONE,
                    trace_id=trace_id,
                    agent_id=agent_id,
                    sequence=self._next_seq(),
                )
                return

            # 发送状态
            yield StreamChunk(
                chunk_type=StreamChunkType.STATUS,
                content="streaming",
                trace_id=trace_id,
                agent_id=agent_id,
                sequence=self._next_seq(),
            )

            # 流式发送文本
            for i in range(0, len(reply), chunk_size):
                chunk_text = reply[i:i + chunk_size]
                yield StreamChunk(
                    chunk_type=StreamChunkType.TEXT,
                    content=chunk_text,
                    trace_id=trace_id,
                    agent_id=agent_id,
                    sequence=self._next_seq(),
                )
                if chunk_delay_ms > 0:
                    await asyncio.sleep(chunk_delay_ms / 1000)

            # 发送完成
            latency_ms = (time.time() - start_time) * 1000
            yield StreamChunk(
                chunk_type=StreamChunkType.DONE,
                trace_id=trace_id,
                agent_id=agent_id,
                sequence=self._next_seq(),
                metadata={
                    "status": status,
                    "latency_ms": round(latency_ms, 2),
                    "total_chars": len(reply),
                },
            )

        except Exception as exc:
            self._logger.error("stream_agent_error", trace_id=trace_id, error=str(exc))
            yield StreamChunk(
                chunk_type=StreamChunkType.ERROR,
                content=f"流式输出异常: {exc}",
                trace_id=trace_id,
                agent_id=agent_id,
                sequence=self._next_seq(),
            )
            yield StreamChunk(
                chunk_type=StreamChunkType.DONE,
                trace_id=trace_id,
                agent_id=agent_id,
                sequence=self._next_seq(),
            )

    # ── LLM 原生流式透传 ─────────────────────────────────

    async def stream_llm_response(
        self,
        llm_stream: AsyncIterator[LLMStreamChunk],
        trace_id: str = "",
        agent_id: str = "",
    ) -> AsyncIterator[StreamChunk]:
        """透传 LLM 原生流式输出

        将 LLM 的流式输出转换为统一的 StreamChunk 格式。
        """
        try:
            async for chunk in llm_stream:
                if chunk.delta_content:
                    yield StreamChunk(
                        chunk_type=StreamChunkType.TEXT,
                        content=chunk.delta_content,
                        trace_id=trace_id,
                        agent_id=agent_id,
                        sequence=self._next_seq(),
                        metadata={"model": chunk.model},
                    )

                if chunk.finish_reason:
                    yield StreamChunk(
                        chunk_type=StreamChunkType.DONE,
                        trace_id=trace_id,
                        agent_id=agent_id,
                        sequence=self._next_seq(),
                        metadata={
                            "finish_reason": chunk.finish_reason,
                            "model": chunk.model,
                        },
                    )
        except Exception as exc:
            self._logger.error("stream_llm_error", trace_id=trace_id, error=str(exc))
            yield StreamChunk(
                chunk_type=StreamChunkType.ERROR,
                content=f"LLM 流式输出异常: {exc}",
                trace_id=trace_id,
                agent_id=agent_id,
                sequence=self._next_seq(),
            )
            yield StreamChunk(
                chunk_type=StreamChunkType.DONE,
                trace_id=trace_id,
                agent_id=agent_id,
                sequence=self._next_seq(),
            )

    # ── 流式 Guardrails ─────────────────────────────────

    async def stream_with_guardrails(
        self,
        source_stream: AsyncIterator[StreamChunk],
        guardrail_check: Callable[[str], Awaitable[tuple[bool, str]]],
        trace_id: str = "",
    ) -> AsyncIterator[StreamChunk]:
        """流式 Guardrails 检查

        边输出边检查，发现违规时立即截断。
        """
        buffer = ""
        blocked = False

        async for chunk in source_stream:
            if blocked:
                continue

            if chunk.chunk_type == StreamChunkType.TEXT:
                buffer += chunk.content

                # 每累积一定长度检查一次
                if len(buffer) >= 20:
                    passed, reason = await guardrail_check(buffer)
                    if not passed:
                        blocked = True
                        yield StreamChunk(
                            chunk_type=StreamChunkType.GUARDRAIL,
                            content="输出被安全策略截断",
                            trace_id=trace_id,
                            sequence=self._next_seq(),
                            metadata={"reason": reason, "truncated": True},
                        )
                        yield StreamChunk(
                            chunk_type=StreamChunkType.DONE,
                            trace_id=trace_id,
                            sequence=self._next_seq(),
                            metadata={"truncated": True},
                        )
                        continue

                yield chunk
            elif chunk.chunk_type == StreamChunkType.DONE:
                # 最终检查
                if not blocked and buffer:
                    passed, reason = await guardrail_check(buffer)
                    if not passed:
                        blocked = True
                        yield StreamChunk(
                            chunk_type=StreamChunkType.GUARDRAIL,
                            content="输出被安全策略拦截",
                            trace_id=trace_id,
                            sequence=self._next_seq(),
                            metadata={"reason": reason},
                        )
                if not blocked:
                    yield chunk
            else:
                yield chunk

    # ── 工具方法 ────────────────────────────────────────

    async def collect_stream(
        self, stream: AsyncIterator[StreamChunk]
    ) -> tuple[str, list[StreamChunk]]:
        """收集流式输出为完整字符串

        Returns:
            (完整内容, 所有 chunk 列表)
        """
        chunks: list[StreamChunk] = []
        text_parts: list[str] = []

        async for chunk in stream:
            chunks.append(chunk)
            if chunk.chunk_type == StreamChunkType.TEXT:
                text_parts.append(chunk.content)

        return "".join(text_parts), chunks
