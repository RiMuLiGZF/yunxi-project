"""
任务分发器 (TaskDispatcher) 单元测试

覆盖功能：
1. test_dispatch_success           -- 正常分发到已注册 Agent 返回 success
2. test_dispatch_agent_not_found   -- 分发到未注册 Agent 返回 failure + "not found" 错误
3. test_dispatch_timeout           -- 执行超时返回 timeout 状态
4. test_dispatch_parallel          -- 多任务并行分发返回正确结果
5. test_retry_mechanism            -- 失败任务（非 "not found"）自动重试 1 次
6. test_collaborators              -- 协作 Agent 分发
7. test_dispatch_latency           -- 结果包含 latency_ms > 0
8. test_handoff_event_published    -- handoff 事件在分发前发布到消息总线
9. test_complete_event_published   -- complete 事件在分发后发布到消息总线
"""

from __future__ import annotations

import asyncio
import sys
import time

# ---------------------------------------------------------------------------
# 路径处理：task_dispatcher.py 内部使用 from interfaces import ... 等裸导入，
# 需要把 agent_cluster 目录和 workspace 目录加入 sys.path。
# ---------------------------------------------------------------------------
PACKAGE_DIR = "/workspace/agent_cluster"
WORKSPACE_DIR = "/workspace"

for p in [PACKAGE_DIR, WORKSPACE_DIR]:
    if p not in sys.path:
# ---------------------------------------------------------------------------
# 被测试模块导入
# ---------------------------------------------------------------------------
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from agent_cluster.core.task_dispatcher import TaskDispatcher  # noqa: E402
from agent_cluster.core.message_bus import MessageBus  # noqa: E402
from agent_cluster.agents.agent_registry import AgentRegistry  # noqa: E402
from interfaces import (  # noqa: E402
    AgentTask,
    AgentResult,
    BusMessage,
    IAgentPlugin,
)


# ===================================================================
# MockAgent: 实现 IAgentPlugin 接口的测试替身
# ===================================================================


class MockAgent(IAgentPlugin):
    """可配置行为的 Mock Agent，用于 TaskDispatcher 单元测试。

    Attributes:
        agent_id: Agent 标识
        call_count: 累计被调用的次数（便于外部断言）
        _delay: handle_task 模拟耗时（秒）
        _fail_first_n: 前 N 次调用抛出异常（用于测试重试）
        _return_failure: 直接返回 failure 状态的结果而非抛出异常
    """

    def __init__(
        self,
        agent_id: str,
        delay: float = 0.0,
        fail_first_n: int = 0,
        return_failure: bool = False,
    ) -> None:
        self.agent_id = agent_id
        self.call_count = 0
        self._delay = delay
        self._fail_first_n = fail_first_n
        self._return_failure = return_failure

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """实现 IAgentPlugin.handle_task，支持延迟模拟和条件失败。"""
        self.call_count += 1

        # 模拟耗时
        if self._delay > 0:
            await asyncio.sleep(self._delay)

        # 前 N 次调用抛出异常（用于测试重试）
        if self.call_count <= self._fail_first_n:
            raise RuntimeError(f"simulated failure (call #{self.call_count})")

        # 返回 failure 状态（非异常路径）
        if self._return_failure:
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error="business error",
            )

        # 默认：成功
        return AgentResult(
            task_id=task.task_id,
            trace_id=task.trace_id,
            agent_id=self.agent_id,
            status="success",
            output={"result": "ok"},
        )


# ===================================================================
# Fixtures
# ===================================================================


@pytest_asyncio.fixture
async def bus():
    """创建并返回一个干净的 MessageBus 实例，测试结束后销毁。"""
    await MessageBus.reset_instance()
    instance = await MessageBus.get_instance()
    yield instance
    await MessageBus.reset_instance()


@pytest_asyncio.fixture
async def registry():
    """返回一个空的 AgentRegistry 实例。"""
    return AgentRegistry()


@pytest_asyncio.fixture
async def dispatcher(registry: AgentRegistry, bus: MessageBus):
    """返回一个绑定 registry 和 bus 的 TaskDispatcher 实例。"""
    from retry_coordinator import RetryCoordinator
    return TaskDispatcher(
        registry=registry,
        message_bus=bus,
        retry_coordinator=RetryCoordinator(),
    )


@pytest_asyncio.fixture
def sample_task():
    """返回一个基本的 AgentTask 工厂函数。"""
    def _make(target: str = "test_agent", ttl: int = 300, **kwargs):
        return AgentTask(target=target, ttl=ttl, **kwargs)
    return _make


# ===================================================================
# 辅助：清空消息总线队列
# ===================================================================


async def _drain_bus(bus: MessageBus, timeout: float = 3.0) -> None:
    """等待消息总线消费完队列中的所有消息。"""
    deadline = time.time() + timeout
    while bus.queue_size() > 0 and time.time() < deadline:
        await asyncio.sleep(0.02)


# ===================================================================
# 1. test_dispatch_success
# ===================================================================


class TestDispatchSuccess:
    """正常分发到已注册 Agent 应返回 success。"""

    @pytest.mark.asyncio
    async def test_dispatch_success(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        agent = MockAgent(agent_id="worker_a")
        await registry.register(agent)

        task = sample_task(target="worker_a")
        result = await dispatcher.dispatch(task)

        assert result.status == "success"
        assert result.task_id == task.task_id
        assert result.agent_id == "worker_a"
        assert result.output == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_dispatch_with_custom_payload(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """带自定义 payload 的分发仍正常进行。"""
        agent = MockAgent(agent_id="worker_b")
        await registry.register(agent)

        task = sample_task(target="worker_b", payload={"key": "value", "num": 42})
        result = await dispatcher.dispatch(task)

        assert result.status == "success"
        assert result.agent_id == "worker_b"

    @pytest.mark.asyncio
    async def test_dispatch_uses_trace_id(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """trace_id 应透传到结果。"""
        agent = MockAgent(agent_id="worker_c")
        await registry.register(agent)

        task = sample_task(target="worker_c", trace_id="my-trace-001")
        result = await dispatcher.dispatch(task)

        assert result.trace_id == "my-trace-001"


# ===================================================================
# 2. test_dispatch_agent_not_found
# ===================================================================


class TestDispatchAgentNotFound:
    """分发到未注册 Agent 返回 failure + "not found" 错误。"""

    @pytest.mark.asyncio
    async def test_dispatch_agent_not_found(
        self, dispatcher: TaskDispatcher, sample_task
    ) -> None:
        """registry 中没有任何 Agent，分发到 "ghost" 应得到 failure。"""
        task = sample_task(target="ghost")
        result = await dispatcher.dispatch(task)

        assert result.status == "failure"
        assert result.error is not None
        assert "not found" in result.error.lower()
        assert "ghost" in result.error

    @pytest.mark.asyncio
    async def test_agent_not_found_no_retry(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """"not found" 错误不应触发重试，dispatch 只应执行一次即返回。"""
        # 不注册任何 Agent
        task = sample_task(target="nonexistent")
        result = await dispatcher.dispatch(task)

        assert result.status == "failure"
        assert result.error is not None and "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_not_found_error_latency(
        self, dispatcher: TaskDispatcher, sample_task
    ) -> None:
        """即使 Agent 未找到，latency_ms 仍应被记录。"""
        task = sample_task(target="missing")
        result = await dispatcher.dispatch(task)

        assert result.latency_ms >= 0


# ===================================================================
# 3. test_dispatch_timeout
# ===================================================================


class TestDispatchTimeout:
    """Agent 执行超时应返回 timeout 状态。"""

    @pytest.mark.asyncio
    async def test_dispatch_timeout(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """Agent 耗时超过 task.ttl * 0.8 时应触发 timeout。"""
        # Agent 耗时 5 秒，但 task.ttl=1 -> timeout = 0.8 秒 < 5 秒
        agent = MockAgent(agent_id="slow_agent", delay=5.0)
        await registry.register(agent)

        task = sample_task(target="slow_agent", ttl=1)
        result = await dispatcher.dispatch(task)

        assert result.status == "timeout"
        assert result.agent_id == "slow_agent"
        assert result.task_id == task.task_id
        assert result.error is not None
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_timeout_result_has_trace_id(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """超时结果也应携带 trace_id。"""
        agent = MockAgent(agent_id="slow_agent_2", delay=5.0)
        await registry.register(agent)

        task = sample_task(target="slow_agent_2", ttl=1, trace_id="timeout-trace")
        result = await dispatcher.dispatch(task)

        assert result.status == "timeout"
        assert result.trace_id == "timeout-trace"

    @pytest.mark.asyncio
    async def test_fast_agent_no_timeout(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """快速 Agent 即使 ttl 很小也不会触发 timeout。"""
        agent = MockAgent(agent_id="fast_agent", delay=0.01)
        await registry.register(agent)

        task = sample_task(target="fast_agent", ttl=1)
        result = await dispatcher.dispatch(task)

        assert result.status == "success"


# ===================================================================
# 4. test_dispatch_parallel
# ===================================================================


class TestDispatchParallel:
    """并行分发多个任务。"""

    @pytest.mark.asyncio
    async def test_dispatch_parallel(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry
    ) -> None:
        agent_a = MockAgent(agent_id="para_a")
        agent_b = MockAgent(agent_id="para_b")
        await registry.register(agent_a)
        await registry.register(agent_b)

        tasks = [
            AgentTask(target="para_a", task_id="t1"),
            AgentTask(target="para_b", task_id="t2"),
        ]
        results = await dispatcher.dispatch_parallel(tasks)

        assert len(results) == 2
        assert results[0].status == "success"
        assert results[0].task_id == "t1"
        assert results[0].agent_id == "para_a"
        assert results[1].status == "success"
        assert results[1].task_id == "t2"
        assert results[1].agent_id == "para_b"

    @pytest.mark.asyncio
    async def test_parallel_executes_concurrently(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry
    ) -> None:
        """并行分发应并发执行，总耗时小于各任务耗时之和。"""
        agent_a = MockAgent(agent_id="slow_a", delay=0.3)
        agent_b = MockAgent(agent_id="slow_b", delay=0.3)
        await registry.register(agent_a)
        await registry.register(agent_b)

        tasks = [
            AgentTask(target="slow_a", ttl=60),
            AgentTask(target="slow_b", ttl=60),
        ]

        start = time.time()
        results = await dispatcher.dispatch_parallel(tasks)
        elapsed = time.time() - start

        # 两个 0.3s 的任务串行需 0.6s，并发应 < 0.5s
        assert elapsed < 0.5, (
            f"并行分发应并发执行，耗时 {elapsed:.3f}s 应明显小于 0.6s"
        )
        assert all(r.status == "success" for r in results)

    @pytest.mark.asyncio
    async def test_parallel_with_not_found(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry
    ) -> None:
        """并行分发中部分 Agent 不存在不应影响其他任务。"""
        agent = MockAgent(agent_id="exists")
        await registry.register(agent)

        tasks = [
            AgentTask(target="exists", task_id="ok"),
            AgentTask(target="missing", task_id="fail"),
        ]
        results = await dispatcher.dispatch_parallel(tasks)

        assert len(results) == 2
        assert results[0].status == "success"
        assert results[0].task_id == "ok"
        assert results[1].status == "failure"
        assert results[1].task_id == "fail"
        assert results[1].error is not None
        assert "not found" in results[1].error.lower()

    @pytest.mark.asyncio
    async def test_parallel_empty_tasks(
        self, dispatcher: TaskDispatcher
    ) -> None:
        """空任务列表应返回空结果列表。"""
        results = await dispatcher.dispatch_parallel([])
        assert results == []


# ===================================================================
# 5. test_retry_mechanism
# ===================================================================


class TestRetryMechanism:
    """失败任务（非 "not found"）应自动重试 1 次。"""

    @pytest.mark.asyncio
    async def test_retry_mechanism(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """Agent 第一次调用抛出异常，第二次成功，最终返回 success。"""
        agent = MockAgent(agent_id="retry_agent", fail_first_n=1)
        await registry.register(agent)

        task = sample_task(target="retry_agent", ttl=30)
        result = await dispatcher.dispatch(task)

        assert result.status == "success"
        assert agent.call_count == 2, "应恰好调用 2 次（首次失败 + 重试）"

    @pytest.mark.asyncio
    async def test_retry_still_fails_after_retry(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """重试后仍然失败，最终返回 failure。"""
        agent = MockAgent(agent_id="always_fail", fail_first_n=999)
        await registry.register(agent)

        task = sample_task(target="always_fail", ttl=30)
        result = await dispatcher.dispatch(task)

        assert result.status == "failure"
        assert agent.call_count == 2, "应恰好调用 2 次后放弃"

    @pytest.mark.asyncio
    async def test_no_retry_on_success(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """首次成功不应触发重试。"""
        agent = MockAgent(agent_id="fast_retry", fail_first_n=0)
        await registry.register(agent)

        task = sample_task(target="fast_retry", ttl=30)
        result = await dispatcher.dispatch(task)

        assert result.status == "success"
        assert agent.call_count == 1, "首次成功不应触发重试"

    @pytest.mark.asyncio
    async def test_retry_not_triggered_for_not_found_error(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """通过 MockAgent 返回 failure（非异常）且错误包含特定"not found"不应重试。

        注意：_execute_with_retry 判断 retry 的条件是
        `result.error != f"Agent '{task.target}' not found"`。
        如果 MockAgent 直接返回一个 error 恰好等于该字符串，也不应重试。
        """
        class NotFoundMockAgent(IAgentPlugin):
            def __init__(self):
                self.agent_id = "not_found_mock"
                self.call_count = 0

            async def handle_task(self, task: AgentTask) -> AgentResult:
                self.call_count += 1
                return AgentResult(
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    status="failure",
                    error=f"Agent '{task.target}' not found",
                )

        agent = NotFoundMockAgent()
        await registry.register(agent)

        task = sample_task(target="not_found_mock", ttl=30)
        result = await dispatcher.dispatch(task)

        # _execute_with_retry 中判断：
        # result.error == f"Agent '{task.target}' not found" -> 不重试
        assert result.status == "failure"
        assert agent.call_count == 1, '"not found" 错误不应触发重试'


# ===================================================================
# 6. test_collaborators
# ===================================================================


class TestCollaborators:
    """任务携带 collaborators 时应分发到所有协作 Agent。"""

    @pytest.mark.asyncio
    async def test_collaborators(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        primary = MockAgent(agent_id="primary")
        collab_a = MockAgent(agent_id="collab_a")
        collab_b = MockAgent(agent_id="collab_b")
        await registry.register(primary)
        await registry.register(collab_a)
        await registry.register(collab_b)

        task = sample_task(
            target="primary",
            collaborators=["collab_a", "collab_b"],
            ttl=30,
        )
        result = await dispatcher.dispatch(task)

        assert result.status == "success"
        assert primary.call_count == 1, "主 Agent 应被调用 1 次"
        assert collab_a.call_count == 1, "协作 Agent A 应被调用 1 次"
        assert collab_b.call_count == 1, "协作 Agent B 应被调用 1 次"

    @pytest.mark.asyncio
    async def test_collaborator_not_found_falls_back(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """所有协作 Agent 均不存在时退化为单 Agent 执行。"""
        primary = MockAgent(agent_id="primary_alone")
        await registry.register(primary)

        task = sample_task(
            target="primary_alone",
            collaborators=["nonexistent_a", "nonexistent_b"],
            ttl=30,
        )
        result = await dispatcher.dispatch(task)

        assert result.status == "success"
        assert primary.call_count >= 1

    @pytest.mark.asyncio
    async def test_collaborators_parallel_execution(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry
    ) -> None:
        """协作 Agent 并行执行，总耗时小于串行之和。"""
        primary = MockAgent(agent_id="primary_p", delay=0.05)
        collab_a = MockAgent(agent_id="collab_p_a", delay=0.3)
        collab_b = MockAgent(agent_id="collab_p_b", delay=0.3)
        await registry.register(primary)
        await registry.register(collab_a)
        await registry.register(collab_b)

        task = AgentTask(
            target="primary_p",
            collaborators=["collab_p_a", "collab_p_b"],
            ttl=60,
        )

        start = time.time()
        result = await dispatcher.dispatch(task)
        elapsed = time.time() - start

        # 协作 Agent (0.3s) 和主 Agent (0.05s + 协作) 并行执行
        # 如果串行 -> 0.3 + 0.3 + (0.05 + extra) > 0.65s
        # 并发 -> 0.3 + 0.05 + extra < 0.5s
        assert result.status == "success"
        assert elapsed < 0.65, (
            f"协作 Agent 应并发执行，耗时 {elapsed:.3f}s "
            f"应明显小于 0.65s"
        )

    @pytest.mark.asyncio
    async def test_collaborator_payload_injection(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """协作结果应注入主任务的 payload.collaborator_results。"""
        collab = MockAgent(agent_id="collab_inject")
        await registry.register(collab)

        # 主 Agent 需要返回 payload 中的 collaborator_results
        class InjectCheckAgent(IAgentPlugin):
            def __init__(self):
                self.agent_id = "primary_inject"
                self.has_collab_results = False

            async def handle_task(self, task: AgentTask) -> AgentResult:
                self.has_collab_results = (
                    "collaborator_results" in task.payload
                )
                return AgentResult(
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    status="success",
                    output={"injected": self.has_collab_results},
                )

        inject_agent = InjectCheckAgent()
        await registry.register(inject_agent)

        task = sample_task(
            target="primary_inject",
            collaborators=["collab_inject"],
            ttl=30,
        )
        result = await dispatcher.dispatch(task)

        assert result.status == "success"
        assert inject_agent.has_collab_results, (
            "主 Agent 收到的 payload 应包含 collaborator_results"
        )


# ===================================================================
# 7. test_dispatch_latency
# ===================================================================


class TestDispatchLatency:
    """结果应包含正数的延迟指标。"""

    @pytest.mark.asyncio
    async def test_dispatch_latency_positive(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        agent = MockAgent(agent_id="latency_agent")
        await registry.register(agent)

        task = sample_task(target="latency_agent", ttl=30)
        result = await dispatcher.dispatch(task)

        assert result.latency_ms > 0, "成功任务应记录正数延迟"

    @pytest.mark.asyncio
    async def test_latency_increases_with_delay(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """Agent 处理耗时越长，latency_ms 越大。"""
        agent = MockAgent(agent_id="slow_latency", delay=0.1)
        await registry.register(agent)

        task = sample_task(target="slow_latency", ttl=30)
        result = await dispatcher.dispatch(task)

        # 0.1s = 100ms，加上一些开销，至少 > 50ms
        assert result.latency_ms > 50, (
            f"延迟应反映实际耗时，得到 {result.latency_ms}ms"
        )


# ===================================================================
# 8. test_handoff_event_published
# ===================================================================


class TestHandoffEventPublished:
    """handoff 事件应在分发前发布到消息总线。"""

    @pytest.mark.asyncio
    async def test_handoff_event_published(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, bus: MessageBus,
        sample_task,
    ) -> None:
        agent = MockAgent(agent_id="handoff_target")
        await registry.register(agent)

        # 订阅 handoff topic，subscriber_id 必须匹配 handoff 消息的 recipient
        handoff_received: list[BusMessage] = []
        handoff_event = asyncio.Event()

        async def handoff_handler(msg: BusMessage) -> None:
            handoff_received.append(msg)
            handoff_event.set()

        await bus.subscribe(
            "agent.handoff_target",
            handoff_handler,
            subscriber_id="handoff_target",
        )

        # 执行分发
        task = sample_task(target="handoff_target", ttl=30, intent="test.intent")
        result = await dispatcher.dispatch(task)

        # 等待消息被消费
        await _drain_bus(bus)

        assert result.status == "success"
        await asyncio.wait_for(handoff_event.wait(), timeout=2.0)
        assert len(handoff_received) == 1

        msg = handoff_received[0]
        assert msg.topic == "agent.handoff_target"
        assert msg.sender == "task_dispatcher"
        assert msg.recipient == "handoff_target"
        assert msg.msg_type == "agent.handoff"
        assert msg.payload.get("task_id") == task.task_id
        assert msg.payload.get("intent") == "test.intent"

    @pytest.mark.asyncio
    async def test_handoff_not_published_for_missing_agent(
        self, dispatcher: TaskDispatcher, bus: MessageBus, sample_task
    ) -> None:
        """未找到 Agent 时不应发布 handoff 事件（dispatch 中提前返回）。"""
        handoff_received: list[BusMessage] = []
        handoff_event = asyncio.Event()

        async def handler(msg: BusMessage) -> None:
            handoff_received.append(msg)
            handoff_event.set()

        await bus.subscribe("agent.missing", handler)

        task = sample_task(target="missing")
        result = await dispatcher.dispatch(task)

        await _drain_bus(bus)

        assert result.status == "failure"
        # handoff 不应发布
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(handoff_event.wait(), timeout=0.5)
        assert len(handoff_received) == 0


# ===================================================================
# 9. test_complete_event_published
# ===================================================================


class TestCompleteEventPublished:
    """complete 事件应在分发后发布到消息总线。"""

    @pytest.mark.asyncio
    async def test_complete_event_published(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, bus: MessageBus,
        sample_task,
    ) -> None:
        agent = MockAgent(agent_id="complete_target")
        await registry.register(agent)

        # 订阅 system.events topic
        complete_received: list[BusMessage] = []
        complete_event = asyncio.Event()

        async def complete_handler(msg: BusMessage) -> None:
            if msg.msg_type == "agent.task_complete":
                complete_received.append(msg)
                complete_event.set()

        await bus.subscribe("system.events", complete_handler)

        # 执行分发
        task = sample_task(target="complete_target", ttl=30)
        result = await dispatcher.dispatch(task)

        # 等待消息被消费
        await _drain_bus(bus)

        assert result.status == "success"
        await asyncio.wait_for(complete_event.wait(), timeout=2.0)
        assert len(complete_received) == 1

        msg = complete_received[0]
        assert msg.topic == "system.events"
        assert msg.sender == "complete_target"
        assert msg.recipient is None  # 广播
        assert msg.msg_type == "agent.task_complete"
        assert msg.payload.get("task_id") == task.task_id
        assert msg.payload.get("status") == "success"
        assert msg.payload.get("latency_ms") is not None

    @pytest.mark.asyncio
    async def test_complete_published_on_failure(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, bus: MessageBus,
        sample_task,
    ) -> None:
        """Agent 不存在时仍应发布 complete 事件。"""
        complete_received: list[BusMessage] = []
        complete_event = asyncio.Event()

        async def handler(msg: BusMessage) -> None:
            if msg.msg_type == "agent.task_complete":
                complete_received.append(msg)
                complete_event.set()

        await bus.subscribe("system.events", handler)

        task = sample_task(target="ghost")
        result = await dispatcher.dispatch(task)

        await _drain_bus(bus)

        assert result.status == "failure"
        await asyncio.wait_for(complete_event.wait(), timeout=2.0)
        assert len(complete_received) == 1

        msg = complete_received[0]
        assert msg.msg_type == "agent.task_complete"
        assert msg.payload.get("status") == "failure"

    @pytest.mark.asyncio
    async def test_complete_published_on_timeout(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, bus: MessageBus,
        sample_task,
    ) -> None:
        """超时场景也应发布 complete 事件。"""
        agent = MockAgent(agent_id="timeout_complete", delay=5.0)
        await registry.register(agent)

        complete_received: list[BusMessage] = []
        complete_event = asyncio.Event()

        async def handler(msg: BusMessage) -> None:
            if msg.msg_type == "agent.task_complete":
                complete_received.append(msg)
                complete_event.set()

        await bus.subscribe("system.events", handler)

        task = sample_task(target="timeout_complete", ttl=1)
        result = await dispatcher.dispatch(task)

        await _drain_bus(bus)

        assert result.status == "timeout"
        await asyncio.wait_for(complete_event.wait(), timeout=2.0)
        assert len(complete_received) == 1
        assert complete_received[0].payload.get("status") == "timeout"


# ===================================================================
# 边界场景与健壮性测试
# ===================================================================


class TestDispatcherEdgeCases:

    @pytest.mark.asyncio
    async def test_dispatch_after_agent_unregistered(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry, sample_task
    ) -> None:
        """注册后注销 Agent，再分发应返回 not found。"""
        agent = MockAgent(agent_id="ephemeral")
        await registry.register(agent)
        await registry.unregister("ephemeral")

        task = sample_task(target="ephemeral")
        result = await dispatcher.dispatch(task)

        assert result.status == "failure"
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_dispatch_zero_ttl(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry
    ) -> None:
        """ttl = 0 的任务应能正常分发（timeout = 0，极快超时）。"""
        agent = MockAgent(agent_id="zero_ttl", delay=0.01)
        await registry.register(agent)

        task = AgentTask(target="zero_ttl", ttl=0)
        result = await dispatcher.dispatch(task)

        # ttl=0, timeout=0, 快速 Agent 也可能在超时前完成
        assert result.status in ("success", "timeout")

    @pytest.mark.asyncio
    async def test_dispatch_negative_ttl(
        self, dispatcher: TaskDispatcher, registry: AgentRegistry
    ) -> None:
        """ttl 为负值应仍能调用（timeout 为负数，必然超时）。"""
        agent = MockAgent(agent_id="neg_ttl", delay=0.01)
        await registry.register(agent)

        task = AgentTask(target="neg_ttl", ttl=-1)
        result = await dispatcher.dispatch(task)

        # timeout = -0.8, asyncio.wait_for 会立即超时
        assert result.status == "timeout"
