"""
测试：StreamingEngine 流式响应引擎
"""

import pytest
import sys
import asyncio
from streaming_engine import StreamingEngine, StreamChunk, StreamChunkType
from llm_provider import LLMStreamChunk


@pytest.fixture
def engine():
    return StreamingEngine()


@pytest.mark.asyncio
async def test_stream_agent_response(engine):
    async def agent_call():
        return {"reply": "你好，这是回复", "status": "success"}

    chunks = []
    async for chunk in engine.stream_agent_response(
        agent_call, trace_id="t1", agent_id="agent.note", chunk_delay_ms=0
    ):
        chunks.append(chunk)

    text = "".join(c.content for c in chunks if c.chunk_type == StreamChunkType.TEXT)
    assert text == "你好，这是回复"
    assert any(c.chunk_type == StreamChunkType.DONE for c in chunks)
    assert chunks[0].chunk_type == StreamChunkType.STATUS


@pytest.mark.asyncio
async def test_stream_agent_empty_reply(engine):
    async def agent_call():
        return {"reply": "", "status": "success"}

    chunks = []
    async for chunk in engine.stream_agent_response(agent_call, trace_id="t1"):
        chunks.append(chunk)

    assert any(c.chunk_type == StreamChunkType.DONE for c in chunks)


@pytest.mark.asyncio
async def test_stream_agent_error(engine):
    async def agent_call():
        raise ValueError("boom")

    chunks = []
    async for chunk in engine.stream_agent_response(agent_call, trace_id="t1"):
        chunks.append(chunk)

    assert any(c.chunk_type == StreamChunkType.ERROR for c in chunks)
    assert any(c.chunk_type == StreamChunkType.DONE for c in chunks)


@pytest.mark.asyncio
async def test_stream_llm_response(engine):
    async def mock_llm_stream():
        yield LLMStreamChunk(delta_content="Hel", finish_reason=None)
        yield LLMStreamChunk(delta_content="lo", finish_reason=None)
        yield LLMStreamChunk(delta_content="", finish_reason="stop")

    chunks = []
    async for chunk in engine.stream_llm_response(mock_llm_stream(), trace_id="t1"):
        chunks.append(chunk)

    text = "".join(c.content for c in chunks if c.chunk_type == StreamChunkType.TEXT)
    assert text == "Hello"
    assert any(c.chunk_type == StreamChunkType.DONE for c in chunks)


@pytest.mark.asyncio
async def test_stream_with_guardrails(engine):
    async def source():
        yield StreamChunk(chunk_type=StreamChunkType.TEXT, content="正常内容")
        yield StreamChunk(chunk_type=StreamChunkType.DONE)

    async def guardrail_check(text):
        if "违规" in text:
            return False, "包含违规内容"
        return True, ""

    chunks = []
    async for chunk in engine.stream_with_guardrails(source(), guardrail_check, trace_id="t1"):
        chunks.append(chunk)

    assert any(c.chunk_type == StreamChunkType.TEXT for c in chunks)
    assert any(c.chunk_type == StreamChunkType.DONE for c in chunks)


@pytest.mark.asyncio
async def test_stream_with_guardrails_block(engine):
    async def source():
        # 第一个 chunk 长度超过 20，触发即时检查
        yield StreamChunk(chunk_type=StreamChunkType.TEXT, content="这是一段很长的违规内容文本，足够触发检查")
        yield StreamChunk(chunk_type=StreamChunkType.TEXT, content="后续")
        yield StreamChunk(chunk_type=StreamChunkType.DONE)

    async def guardrail_check(text):
        if "违规" in text:
            return False, "包含违规内容"
        return True, ""

    chunks = []
    async for chunk in engine.stream_with_guardrails(source(), guardrail_check, trace_id="t1"):
        chunks.append(chunk)

    assert any(c.chunk_type == StreamChunkType.GUARDRAIL for c in chunks)
    # 第一个 chunk 在输出前就被拦截，因此没有任何 TEXT 被实际输出
    text_chunks = [c for c in chunks if c.chunk_type == StreamChunkType.TEXT]
    assert len(text_chunks) == 0


@pytest.mark.asyncio
async def test_collect_stream(engine):
    async def source():
        yield StreamChunk(chunk_type=StreamChunkType.TEXT, content="He")
        yield StreamChunk(chunk_type=StreamChunkType.TEXT, content="llo")
        yield StreamChunk(chunk_type=StreamChunkType.DONE)

    text, chunks = await engine.collect_stream(source())
    assert text == "Hello"
    assert len(chunks) == 3
