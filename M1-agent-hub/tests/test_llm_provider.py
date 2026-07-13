"""
测试：LLM Provider 抽象层
"""

import pytest
import sys
import asyncio

sys.path.insert(0, "/workspace/agent_cluster")

from llm_provider import (
    MockLLMProvider,
    LLMProviderFactory,
    LLMMessage,
    LLMStreamChunk,
)


@pytest.mark.asyncio
async def test_mock_chat():
    provider = MockLLMProvider(model="mock-test")
    messages = [LLMMessage(role="user", content="hello")]
    response = await provider.chat(messages)

    assert len(response.choices) == 1
    assert "hello" in response.choices[0].message.content
    assert response.usage.prompt_tokens == 5


@pytest.mark.asyncio
async def test_mock_chat_stream():
    provider = MockLLMProvider(model="mock-test")
    messages = [LLMMessage(role="user", content="hi")]

    chunks = []
    async for chunk in provider.chat_stream(messages):
        chunks.append(chunk)

    assert len(chunks) > 0
    full_text = "".join(c.delta_content for c in chunks if c.delta_content)
    assert len(full_text) > 0
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_mock_embed():
    provider = MockLLMProvider()
    embeddings = await provider.embed(["text1", "text2"])

    assert len(embeddings) == 2
    assert len(embeddings[0]) == 128


@pytest.mark.asyncio
async def test_factory_mock():
    provider = LLMProviderFactory.create("mock", model="test-model")
    assert isinstance(provider, MockLLMProvider)
    assert provider.model == "test-model"


def test_factory_unknown():
    with pytest.raises(ValueError):
        LLMProviderFactory.create("unknown")
