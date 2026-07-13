from __future__ import annotations

import pytest

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult
from skill_cluster.infrastructure.streaming import (
    StreamChunk,
    StreamInvokeResult,
    StreamingInvoker,
    StreamableSkillMixin,
)


def test_stream_chunk_model() -> None:
    chunk = StreamChunk(data="hello", is_done=False, metadata={"token": 1})
    assert chunk.data == "hello"
    assert chunk.is_done is False
    assert chunk.metadata["token"] == 1


def test_stream_invoke_result_model() -> None:
    result = StreamInvokeResult(
        skill_id="skill.test",
        action="echo",
        status="success",
        data=["a", "b"],
        latency_ms=12.5,
        trace_id="t1",
        chunk_count=2,
    )
    assert result.chunk_count == 2
    assert result.data == ["a", "b"]


@pytest.mark.asyncio
async def test_streaming_invoker_not_found() -> None:
    invoker = StreamingInvoker()
    request = SkillInvokeRequest(
        skill_id="skill.not_exist", action="test", trace_id="t1"
    )
    chunks = []
    async for chunk in invoker.invoke_stream(request, "agent1"):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0].is_done is True
    assert chunks[0].metadata["status"] == "not_found"


@pytest.mark.asyncio
async def test_streaming_invoker_fallback_to_invoke() -> None:
    """技能未实现 invoke_stream 时，退化为 invoke + 单块."""
    from skill_cluster.skill_router import SkillRouter
    from skill_cluster.tests.test_router import DummySkill

    router = SkillRouter()
    skill = DummySkill("skill.dummy1")
    router.mount(skill)

    invoker = StreamingInvoker(router)
    request = SkillInvokeRequest(
        skill_id="skill.dummy1", action="echo", trace_id="t1"
    )
    chunks = []
    async for chunk in invoker.invoke_stream(request, "agent1"):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0].is_done is True
    assert chunks[0].metadata["status"] == "success"


@pytest.mark.asyncio
async def test_streaming_invoker_collect() -> None:
    from skill_cluster.skill_router import SkillRouter
    from skill_cluster.tests.test_router import DummySkill

    router = SkillRouter()
    skill = DummySkill("skill.dummy2")
    router.mount(skill)

    invoker = StreamingInvoker(router)
    request = SkillInvokeRequest(
        skill_id="skill.dummy2", action="echo", trace_id="t1"
    )
    result = await invoker.collect(request, "agent1")

    assert isinstance(result, StreamInvokeResult)
    assert result.status == "success"
    assert result.skill_id == "skill.dummy2"


@pytest.mark.asyncio
async def test_streaming_invoker_on_chunk_callback() -> None:
    from skill_cluster.skill_router import SkillRouter
    from skill_cluster.tests.test_router import DummySkill

    router = SkillRouter()
    skill = DummySkill("skill.dummy3")
    router.mount(skill)

    invoker = StreamingInvoker(router)
    request = SkillInvokeRequest(
        skill_id="skill.dummy3", action="echo", trace_id="t1"
    )
    called = []

    def callback(chunk: StreamChunk) -> None:
        called.append(chunk)

    async for _ in invoker.invoke_stream(request, "agent1", on_chunk=callback):
        pass

    assert len(called) == 1


@pytest.mark.asyncio
async def test_streamable_skill_mixin() -> None:
    from skill_cluster.interfaces import SkillManifest

    class MyStreamSkill(StreamableSkillMixin):
        def __init__(self) -> None:
            self._manifest = SkillManifest(
                skill_id="skill.stream",
                name="stream",
                version="1.0.0",
                description="test",
                author="test",
                entrypoint="MyStreamSkill",
            )

        async def stream(self, request):
            yield StreamChunk(data="hello", is_done=False)
            yield StreamChunk(data="world", is_done=True)

        async def health(self):
            return {"healthy": True}

        async def configure(self, config):
            pass

    skill = MyStreamSkill()
    request = SkillInvokeRequest(
        skill_id="skill.stream", action="test", trace_id="t1"
    )
    chunks = []
    async for chunk in skill.invoke_stream(request):
        chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[0].data == "hello"
    assert chunks[1].is_done is True
