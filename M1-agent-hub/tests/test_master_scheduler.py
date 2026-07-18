"""
Tests for MasterScheduler（总控调度 Agent）

覆盖路由策略、会话管理、总线订阅、故障降级等核心功能。
"""

import sys
import os
from typing import Any

# ── 确保能找到相邻模块（interfaces, intent_classifier 等）──
import pytest
from unittest.mock import AsyncMock, MagicMock

from interfaces import AgentTask, AgentResult
from master_scheduler import MasterScheduler
from intent_classifier import IntentClassifier


# ═══════════════════════════════════════════════════════════
# 辅助工厂函数
# ═══════════════════════════════════════════════════════════


def _make_agent_result(
    agent_id: str = "agent.note",
    status: str = "success",
    reply: str = "",
    error: str | None = None,
    **extra_output: Any,
) -> AgentResult:
    """创建 AgentResult 的便捷工厂函数"""
    output: dict[str, Any] | None = None
    if reply or extra_output:
        output = {"reply": reply, **extra_output}
    return AgentResult(
        task_id="test-task",
        trace_id="test-trace",
        agent_id=agent_id,
        status=status,
        output=output,
        error=error,
    )


def _make_dispatcher(
    return_value: AgentResult | None = None,
) -> MagicMock:
    """创建带 mock dispatch 方法的 TaskDispatcher"""
    dispatcher = MagicMock(spec=["dispatch"])
    dispatcher.dispatch = AsyncMock(return_value=return_value)
    return dispatcher


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def classifier() -> IntentClassifier:
    """真实的 IntentClassifier 实例"""
    return IntentClassifier()


@pytest.fixture
def mock_dispatcher() -> MagicMock:
    """Mock TaskDispatcher"""
    return _make_dispatcher()


@pytest.fixture
def scheduler(
    classifier: IntentClassifier,
    mock_dispatcher: MagicMock,
) -> MasterScheduler:
    """MasterScheduler 实例"""
    return MasterScheduler(classifier=classifier, dispatcher=mock_dispatcher)


# ═══════════════════════════════════════════════════════════
# 1. test_direct_route
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_direct_route(
    scheduler: MasterScheduler,
    mock_dispatcher: MagicMock,
) -> None:
    """高置信度输入（confidence >= 0.7）直接路由到目标 Agent

    验证要点：
    - 返回 status == "success"
    - reply 与 mock Agent 的输出一致
    - dispatch 被调用一次
    - 构造的 AgentTask 包含正确的 target / intent / source
    """
    mock_dispatcher.dispatch.return_value = _make_agent_result(
        agent_id="agent.note",
        reply="笔记已成功记录",
    )

    # "记笔记" 是 note.create 的精确匹配关键词 → confidence 1.0 → 直接路由
    result = await scheduler.process_input("记笔记")

    assert result["status"] == "success"
    assert result["reply"] == "笔记已成功记录"
    assert "trace_id" in result

    # 验证 dispatch 调用细节
    mock_dispatcher.dispatch.assert_awaited_once()
    task: AgentTask = mock_dispatcher.dispatch.await_args[0][0]  # type: ignore[union-attr]
    assert task.target == "agent.note"
    assert task.intent == "note.create"
    assert task.source == "user"
    assert task.trace_id == result["trace_id"]


# ═══════════════════════════════════════════════════════════
# 2. test_confirm_route
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_confirm_route(
    scheduler: MasterScheduler,
    mock_dispatcher: MagicMock,
) -> None:
    """中等置信度（0.4 <= confidence < 0.7）返回 confirm 状态

    验证要点：
    - 返回 status == "confirm"
    - reply 包含确认提示文案
    - classify_result 嵌入在返回字典中
    - dispatch 不会被调用
    """
    # "请帮我记录一下" 包含关键词 "记录"（非前后缀）→ confidence 0.6
    result = await scheduler.process_input("请帮我记录一下")

    assert result["status"] == "confirm"
    assert "我猜你想处理" in result["reply"]
    assert "classify_result" in result

    cr = result["classify_result"]
    assert cr["target_agent"] == "agent.note"
    assert cr["intent"] == "note.create"
    assert cr["confidence"] == 0.6
    assert cr["requires_confirmation"] is True

    # confirm 路由不应派发任务
    mock_dispatcher.dispatch.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 3. test_fallback_route
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fallback_route(
    scheduler: MasterScheduler,
    mock_dispatcher: MagicMock,
) -> None:
    """低置信度（confidence < 0.4）返回 fallback 状态

    验证要点：
    - 返回 status == "fallback"
    - reply 为通用不理解回复
    - dispatch 不会被调用
    """
    # "今天天气怎么样" 不匹配任何关键词 → confidence 0.0 → fallback
    result = await scheduler.process_input("今天天气怎么样")

    assert result["status"] == "fallback"
    assert "不太理解" in result["reply"]
    assert "trace_id" in result

    # fallback 路由不应派发任务
    mock_dispatcher.dispatch.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 4. test_agent_failure_degradation
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_agent_failure_degradation(
    scheduler: MasterScheduler,
    mock_dispatcher: MagicMock,
) -> None:
    """目标 Agent 执行失败时降级到通用回复

    验证要点：
    - dispatch 调用后目标 Agent 返回 failure
    - MasterScheduler 应调用 _try_fallback 生成降级回复
    - 返回 status == "degraded"
    - agent_results 包含原始失败结果 + 降级结果
    """
    mock_dispatcher.dispatch.return_value = _make_agent_result(
        agent_id="agent.note",
        status="failure",
        error="Service unavailable",
    )

    result = await scheduler.process_input("记笔记")

    assert result["status"] == "degraded"
    assert "不太理解" in result["reply"]
    assert len(result["agent_results"]) == 2

    # 第一个是原始 Agent 失败结果
    assert result["agent_results"][0]["agent_id"] == "agent.note"
    assert result["agent_results"][0]["status"] == "failure"

    # 第二个是 MasterScheduler 自身的降级结果
    assert result["agent_results"][1]["agent_id"] == "master_scheduler"
    assert result["agent_results"][1]["status"] == "success"


# ═══════════════════════════════════════════════════════════
# 5. test_serial_collaboration
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_serial_collaboration(
    scheduler: MasterScheduler,
    mock_dispatcher: MagicMock,
) -> None:
    """多个 Agent 串行协作：先后路由到不同 Agent

    验证要点：
    - 第一次输入路由到 agent.note
    - 第二次输入路由到 agent.emotion
    - dispatch 被调用两次，每次 target 不同
    - 两次结果均正确返回
    """
    # ── 第一次：路由到 agent.note ──
    mock_dispatcher.dispatch.return_value = _make_agent_result(
        agent_id="agent.note",
        reply="笔记已成功记录",
    )
    result1 = await scheduler.process_input("记笔记")
    assert result1["status"] == "success"
    assert result1["reply"] == "笔记已成功记录"

    # ── 第二次：路由到 agent.emotion ──
    mock_dispatcher.dispatch.return_value = _make_agent_result(
        agent_id="agent.emotion",
        reply="我感受到你的心情了",
    )
    result2 = await scheduler.process_input("聊聊心情")
    assert result2["status"] == "success"
    assert result2["reply"] == "我感受到你的心情了"

    # 验证两次 dispatch 的目标不同
    assert mock_dispatcher.dispatch.await_count == 2
    calls = mock_dispatcher.dispatch.await_args_list
    assert calls[0].args[0].target == "agent.note"
    assert calls[0].args[0].intent == "note.create"
    assert calls[1].args[0].target == "agent.emotion"
    assert calls[1].args[0].intent == "emotion.chat"


# ═══════════════════════════════════════════════════════════
# 6. test_session_context
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_session_context(
    scheduler: MasterScheduler,
    mock_dispatcher: MagicMock,
) -> None:
    """会话上下文被创建且可访问

    验证要点：
    - get_session_context 返回非 None 的 SessionContext
    - trace_id / last_input / created_at / last_access_time 字段正确
    - last_task_id 被正确记录
    """
    mock_dispatcher.dispatch.return_value = _make_agent_result(
        agent_id="agent.note",
        reply="笔记已记录",
    )

    trace_id = "my-test-trace"
    result = await scheduler.process_input("记笔记", trace_id=trace_id)

    context = scheduler.get_session_context(trace_id)
    assert context is not None
    assert context.trace_id == trace_id
    assert context.last_input == "记笔记"
    assert context.created_at > 0
    assert context.last_access_time > 0
    # last_task_id 应为 AgentTask 自动生成的 UUID（非空）
    assert context.last_task_id != ""
    # result 中返回的 task_id 来自 Mock AgentResult 的硬编码值
    assert result["agent_results"][0]["task_id"] == "test-task"

    # data 字段初始为空字典
    assert context.data == {}


# ═══════════════════════════════════════════════════════════
# 7. test_session_context_ttl
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_session_context_ttl(
    scheduler: MasterScheduler,
    mock_dispatcher: MagicMock,
) -> None:
    """会话上下文在手动清理后不可访问（模拟 TTL 过期）

    验证要点：
    - process_input 后上下文可访问
    - clear_session_context 后上下文返回 None
    - 多次清除幂等
    """
    mock_dispatcher.dispatch.return_value = _make_agent_result(
        agent_id="agent.note",
        reply="笔记已记录",
    )

    trace_id = "ttl-test-trace"
    await scheduler.process_input("记笔记", trace_id=trace_id)

    # process_input 后上下文可访问
    assert scheduler.get_session_context(trace_id) is not None

    # 手动清除（模拟 TTL 过期清理）
    await scheduler.clear_session_context(trace_id)
    assert scheduler.get_session_context(trace_id) is None

    # 重复清除幂等
    await scheduler.clear_session_context(trace_id)
    assert scheduler.get_session_context(trace_id) is None


# ═══════════════════════════════════════════════════════════
# 8. test_handle_task_as_agent
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_handle_task_as_agent(scheduler: MasterScheduler) -> None:
    """MasterScheduler.handle_task 处理 fallback / system / 未知 intent

    验证要点：
    - "general.fallback" intent → status == "success", 回复包含不理解文案
    - "general.system" intent → status == "success", 回复包含 "系统状态正常"
    - 未知 intent → status == "failure", error 包含 "Unknown intent"
    """
    # ── fallback intent ──
    task = AgentTask(
        trace_id="t1",
        source="test",
        target="master_scheduler",
        intent="general.fallback",
        payload={"user_input": "随便说说"},
    )
    result = await scheduler.handle_task(task)
    assert result.status == "success"
    assert result.agent_id == "master_scheduler"
    assert result.task_id == task.task_id
    assert result.trace_id == "t1"
    assert result.output is not None
    assert "不太理解" in result.output["reply"]

    # ── system intent ──
    task = AgentTask(
        trace_id="t2",
        source="test",
        target="master_scheduler",
        intent="general.system",
        payload={},
    )
    result = await scheduler.handle_task(task)
    assert result.status == "success"
    assert result.output is not None
    assert "系统状态正常" in result.output["reply"]

    # ── unknown intent（应失败）──
    task = AgentTask(
        trace_id="t3",
        source="test",
        target="master_scheduler",
        intent="some.random.intent",
        payload={},
    )
    result = await scheduler.handle_task(task)
    assert result.status == "failure"
    assert "Unknown intent" in result.error


# ═══════════════════════════════════════════════════════════
# 9. test_subscribe_to_bus
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_subscribe_to_bus(scheduler: MasterScheduler) -> None:
    """订阅消息总线应注册 listener

    验证要点：
    - bus.subscribe 被以正确的 topic 和 subscriber_id 调用
    - subscription_ids 列表包含返回的 sub_id
    """
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub-id-1")

    await scheduler.subscribe_to_bus(bus)

    bus.subscribe.assert_awaited_once_with(
        "user.input",
        scheduler._on_user_input,
        subscriber_id="master_scheduler",
    )
    assert "sub-id-1" in scheduler._subscription_ids


# ═══════════════════════════════════════════════════════════
# 10. test_emotion_crisis_detection
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_emotion_crisis_detection(
    scheduler: MasterScheduler,
    mock_dispatcher: MagicMock,
) -> None:
    """危机关键词应路由到情绪 Agent 并返回高风险等级（risk_level="high"）

    验证要点：
    - "不想活" 是 emotion.support 的精确匹配关键词 → confidence 1.0 → 直接路由
    - dispatch 目标为 agent.emotion，intent 为 emotion.support
    - 返回结果中包含 risk_level="high"
    """
    mock_dispatcher.dispatch.return_value = _make_agent_result(
        agent_id="agent.emotion",
        reply="我在这里陪伴你，请告诉我更多。",
        risk_level="high",
    )

    result = await scheduler.process_input("不想活")

    # 直接路由成功
    assert result["status"] == "success"
    assert result["reply"] == "我在这里陪伴你，请告诉我更多。"

    # 验证 dispatch 到情绪 Agent
    mock_dispatcher.dispatch.assert_awaited_once()
    task: AgentTask = mock_dispatcher.dispatch.await_args[0][0]  # type: ignore[union-attr]
    assert task.target == "agent.emotion"
    assert task.intent == "emotion.support"

    # 验证返回的风险等级
    agent_result = result["agent_results"][0]
    assert agent_result["output"]["risk_level"] == "high"
