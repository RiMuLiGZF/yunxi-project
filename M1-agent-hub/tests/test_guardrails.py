"""Guardrails 护栏系统单元测试"""
import sys
import pytest

from agent_cluster.guardrails import (
    ContentLengthGuardrail,
    SensitiveInfoGuardrail,
    KeywordBlockGuardrail,
    EmotionalRiskGuardrail,
    RateLimitGuardrail,
    GuardrailPipeline,
    create_default_pipeline,
)


@pytest.mark.asyncio
async def test_content_length_pass():
    gr = ContentLengthGuardrail(max_length=100)
    result = await gr.check("hello")
    assert result.passed


@pytest.mark.asyncio
async def test_content_length_block():
    gr = ContentLengthGuardrail(max_length=5)
    result = await gr.check("hello world")
    assert not result.passed
    assert result.action == "block"
    assert "超过限制" in result.message


@pytest.mark.asyncio
async def test_sensitive_info_detect_only():
    gr = SensitiveInfoGuardrail(detect_only=True)
    result = await gr.check("我的邮箱是 test@example.com")
    assert result.passed  # detect_only 只警告不阻断
    assert result.action == "warn"
    assert "email" in result.message


@pytest.mark.asyncio
async def test_sensitive_info_sanitize():
    gr = SensitiveInfoGuardrail(detect_only=False)
    result = await gr.check("我的邮箱是 test@example.com")
    assert not result.passed
    assert result.action == "sanitize"
    assert "REDACTED" in result.sanitized_value


@pytest.mark.asyncio
async def test_keyword_block():
    gr = KeywordBlockGuardrail(blocklist=["赌博", "毒品"])
    result = await gr.check("我们来赌博吧")
    assert not result.passed
    assert "赌博" in result.message


@pytest.mark.asyncio
async def test_keyword_pass():
    gr = KeywordBlockGuardrail(blocklist=["赌博"])
    result = await gr.check("正常聊天内容")
    assert result.passed


@pytest.mark.asyncio
async def test_emotional_risk_detect():
    gr = EmotionalRiskGuardrail()
    result = await gr.check("我不想活了")
    assert not result.passed
    assert result.violation_type == "crisis_signal"
    assert result.action == "block"


@pytest.mark.asyncio
async def test_emotional_risk_pass():
    gr = EmotionalRiskGuardrail()
    result = await gr.check("今天天气不错")
    assert result.passed


@pytest.mark.asyncio
async def test_rate_limit():
    gr = RateLimitGuardrail(max_calls=2, window_seconds=60)
    r1 = await gr.check("test1")
    r2 = await gr.check("test2")
    r3 = await gr.check("test3")
    assert r1.passed
    assert r2.passed
    assert not r3.passed
    assert "频率超限" in r3.message


@pytest.mark.asyncio
async def test_pipeline_input_chain():
    pipeline = GuardrailPipeline("test")
    pipeline.add_input_guardrail(ContentLengthGuardrail(max_length=10))
    pipeline.add_input_guardrail(KeywordBlockGuardrail(blocklist=["bad"]))

    passed, value, results = await pipeline.check_input("good text")
    assert passed
    assert len(results) == 2


@pytest.mark.asyncio
async def test_pipeline_blocks_on_first_failure():
    pipeline = GuardrailPipeline("test")
    pipeline.add_input_guardrail(KeywordBlockGuardrail(blocklist=["bad"]))
    pipeline.add_input_guardrail(ContentLengthGuardrail(max_length=5))

    passed, value, results = await pipeline.check_input("bad content that is very long")
    assert not passed
    # 第一个护栏 block 后，第二个不应执行
    assert len(results) == 1


@pytest.mark.asyncio
async def test_default_pipeline_creation():
    pipeline = create_default_pipeline()
    assert len(pipeline.input_guardrails) > 0
    assert len(pipeline.output_guardrails) > 0
