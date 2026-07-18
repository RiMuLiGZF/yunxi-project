"""
测试：V9 语义意图分类 + GroupChat + OTLP 导出 + V9 编排器
"""

import pytest
import sys
from unittest.mock import AsyncMock, MagicMock
from semantic_intent_v3 import SemanticIntentClassifierV3
from group_chat import (
    GroupChatEngine, GroupChatAgent, ChatMessage,
    RoundRobinSelector, DescriptionSelector, RandomSelector,
    MaxRoundTermination, KeywordTermination, CompositeTermination,
    CustomSelector,
)
from otlp_exporter import OTLPExporter, OTLPSpan
from orchestrator_v9 import OrchestratorV9


# ═════════════ SemanticIntentClassifierV3 ═════════════


def test_train_and_classify():
    clf = SemanticIntentClassifierV3(min_confidence=0.2)
    samples = {
        "weather": ["今天天气怎么样", "明天会下雨吗", "气温多少度"],
        "greeting": ["你好", "早上好", "晚上好", "hello"],
        "code": ["写个Python函数", "帮我debug这段代码", "如何实现排序"],
    }
    clf.train(samples)

    result = clf.classify("今天天气如何")
    assert result["intent"] == "weather"
    assert result["confidence"] > 0.2
    assert result["latency_ms"] < 100  # 本地TF-IDF应该很快

    result = clf.classify("你好啊")
    assert result["intent"] == "greeting"

    result = clf.classify("写个Python排序函数")
    assert result["intent"] == "code"


def test_classify_fallback():
    clf = SemanticIntentClassifierV3(min_confidence=0.9)  # 高阈值
    samples = {"weather": ["今天天气怎么样"]}
    clf.train(samples)
    result = clf.classify("完全不相关的内容")
    assert result["intent"] == "fallback"


def test_incremental_learning():
    clf = SemanticIntentClassifierV3()
    clf.train({"weather": ["今天天气怎么样"]})
    clf.add_sample("weather", "明天会下雨吗")
    stats = clf.stats()
    assert stats["intents"]["weather"]["samples"] == 2


def test_batch_classify():
    clf = SemanticIntentClassifierV3()
    clf.train({"a": ["test a"], "b": ["test b"]})
    results = clf.batch_classify(["test a", "test b"])
    assert len(results) == 2
    assert results[0]["intent"] == "a"
    assert results[1]["intent"] == "b"


def test_tokenize_chinese():
    clf = SemanticIntentClassifierV3()
    tokens = clf._tokenize("今天天气怎么样？Hello world!")
    assert "今" in tokens
    assert "天" in tokens
    assert "hello" in tokens
    assert "world" in tokens


def test_cosine_similarity():
    clf = SemanticIntentClassifierV3()
    a = {"x": 1.0, "y": 0.0}
    b = {"x": 1.0, "y": 0.0}
    assert clf._cosine_similarity(a, b) == 1.0

    c = {"x": 0.0, "y": 1.0}
    assert abs(clf._cosine_similarity(a, c)) < 0.01


# ═════════════ GroupChat ═════════════


class FakeChatAgent(GroupChatAgent):
    def __init__(self, agent_id: str, prefix: str = ""):
        super().__init__(agent_id, description=f"{agent_id} agent")
        self.prefix = prefix

    async def respond(self, context: list[ChatMessage], task: str = "") -> str:
        return f"{self.prefix}reply from {self.agent_id}"


@pytest.mark.asyncio
async def test_group_chat_round_robin():
    agents = [FakeChatAgent("a1"), FakeChatAgent("a2"), FakeChatAgent("a3")]
    engine = GroupChatEngine(
        agents=agents,
        selector=RoundRobinSelector(),
        termination=MaxRoundTermination(5),
    )
    result = await engine.run(task="hello", max_round=5)
    assert result["rounds"] == 5
    assert len(result["messages"]) == 6  # 1 user + 5 agent
    assert result["participants"] == ["a1", "a2", "a3"]


@pytest.mark.asyncio
async def test_group_chat_keyword_termination():
    class TerminateAgent(GroupChatAgent):
        def __init__(self):
            super().__init__("terminator")
        async def respond(self, context, task="") -> str:
            return "TERMINATE"

    engine = GroupChatEngine(
        agents=[TerminateAgent()],
        selector=RoundRobinSelector(),
        termination=CompositeTermination([
            MaxRoundTermination(20),
            KeywordTermination("TERMINATE"),
        ]),
    )
    result = await engine.run(task="go")
    assert result["rounds"] == 1
    assert "TERMINATE" in result["final_answer"]


@pytest.mark.asyncio
async def test_group_chat_no_repeat_speaker():
    agents = [FakeChatAgent("a1"), FakeChatAgent("a2")]
    engine = GroupChatEngine(
        agents=agents,
        selector=RoundRobinSelector(),
        termination=MaxRoundTermination(4),
        allow_repeat_speaker=False,
    )
    result = await engine.run(max_round=4)
    # a1, a2, a1, a2
    agent_sequence = [m["agent_id"] for m in result["messages"]]
    assert agent_sequence == ["a1", "a2", "a1", "a2"]


@pytest.mark.asyncio
async def test_group_chat_description_selector():
    class CodeAgent(GroupChatAgent):
        def __init__(self):
            super().__init__("coder", description="write code python javascript")
        async def respond(self, context, task="") -> str:
            return "coding..."

    class ChatAgent(GroupChatAgent):
        def __init__(self):
            super().__init__("chatter", description="chat conversation talk")
        async def respond(self, context, task="") -> str:
            return "chatting..."

    engine = GroupChatEngine(
        agents=[CodeAgent(), ChatAgent()],
        selector=DescriptionSelector(),
        termination=MaxRoundTermination(3),
    )
    result = await engine.run(task="write python code")
    # 第一条 agent 消息应选 coder（task 匹配 description）
    agent_msgs = [m for m in result["messages"] if m["agent_id"] != "user"]
    assert agent_msgs[0]["agent_id"] == "coder"


@pytest.mark.asyncio
async def test_group_chat_custom_selector():
    agents = [FakeChatAgent("a1"), FakeChatAgent("a2")]

    def always_pick_a2(agents_list, messages, last):
        return agents_list[1]

    engine = GroupChatEngine(
        agents=agents,
        selector=CustomSelector(always_pick_a2),
        termination=MaxRoundTermination(3),
    )
    result = await engine.run(max_round=3)
    for m in result["messages"]:
        assert m["agent_id"] == "a2"


def test_group_chat_stats():
    engine = GroupChatEngine(agents=[FakeChatAgent("a1")])
    stats = engine.stats()
    assert stats["participants"] == 1
    assert stats["selector_type"] == "RoundRobinSelector"


# ═════════════ OTLP Exporter ═════════════


def test_otlp_span_to_dict():
    span = OTLPSpan(
        trace_id="abc123",
        span_id="span1",
        name="test_span",
        start_time_ns=1000000000,
        end_time_ns=2000000000,
        attributes={"key": "value"},
    )
    d = span.to_otlp_dict()
    assert d["traceId"] == "abc123"
    assert d["name"] == "test_span"
    assert d["startTimeUnixNano"] == "1000000000"


def test_otlp_exporter_local_cache():
    exporter = OTLPExporter(endpoint="", batch_size=2)
    exporter.export_span(OTLPSpan(trace_id="t1", span_id="s1"))
    exporter.export_span(OTLPSpan(trace_id="t1", span_id="s2"))
    stats = exporter.stats()
    assert stats["local_cache_size"] == 2
    assert stats["endpoint"] == "none (local cache mode)"


def test_otlp_exporter_batch_flush():
    exporter = OTLPExporter(endpoint="", batch_size=3)
    for i in range(5):
        exporter.export_span(OTLPSpan(trace_id="t", span_id=f"s{i}"))
    stats = exporter.stats()
    assert stats["local_cache_size"] == 3  # 前3个触发 flush
    assert stats["buffer_size"] == 2  # 后2个在 buffer


# ═════════════ OrchestratorV9 ═════════════


def test_v9_classify_intent():
    v8_mock = MagicMock()
    v9 = OrchestratorV9(v8_mock)
    v9.train_intent({"test": ["sample text"]})
    result = v9.classify_intent("sample text")
    assert result["intent"] == "test"


def test_v9_diagnose():
    v8_mock = MagicMock()
    v8_mock.diagnose = MagicMock(return_value={"v8": {"ok": True}})
    v9 = OrchestratorV9(v8_mock)
    diag = v9.diagnose()
    assert "v8" in diag
    assert "v9" in diag
    assert diag["v9"]["otlp_exporter"] is None


def test_v9_with_otlp():
    v8_mock = MagicMock()
    otlp = OTLPExporter(endpoint="")
    v9 = OrchestratorV9(v8_mock, otlp_exporter=otlp)
    diag = v9.diagnose()
    assert diag["v9"]["otlp_exporter"]["endpoint"] == "none (local cache mode)"


@pytest.mark.asyncio
async def test_v9_group_chat():
    v8_mock = MagicMock()
    v9 = OrchestratorV9(v8_mock)

    result = await v9.run_group_chat(
        agents=[FakeChatAgent("a1"), FakeChatAgent("a2")],
        task="test",
        max_round=3,
    )
    assert result["rounds"] == 3
    assert len(result["messages"]) == 4  # user + 3 agent


@pytest.mark.asyncio
async def test_v9_process_delegation():
    v8_mock = MagicMock()
    v8_mock.process = AsyncMock(return_value={"reply": "ok"})
    v9 = OrchestratorV9(v8_mock)
    # 使用非简单查询输入，确保走完整 V3 意图分类链路
    result = await v9.process("请帮我写一段Python代码实现快速排序")
    assert result["reply"] == "ok"
    # [P2-003] V9.process() 现在注入 override_intent 到 V8
    v8_mock.process.assert_called_once()
    call_kwargs = v8_mock.process.call_args[1]
    assert call_kwargs["override_intent"] is not None
    assert "intent" in call_kwargs["override_intent"]


@pytest.mark.asyncio
async def test_v9_process_simple_query():
    """[P3-005] 简单查询应跳过 V3 意图分类和 Ledger，直接委托 V8"""
    v8_mock = MagicMock()
    v8_mock.process = AsyncMock(return_value={"reply": "hi"})
    v9 = OrchestratorV9(v8_mock)
    result = await v9.process("hello")
    assert result["reply"] == "hi"
    v8_mock.process.assert_called_once()
    call_kwargs = v8_mock.process.call_args[1]
    # 简单查询不注入 override_intent
    assert "override_intent" not in call_kwargs
