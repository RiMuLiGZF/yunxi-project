"""
V9.5 第一轮增量优化测试

覆盖修复：
- N-012 [P0]: Ledger replan 死循环
- N-001 [P1]: __getattr__ 白名单透传
- N-003 [P1]: TaskDispatcher Budget 预检
- N-005 [P1]: MessageAdapter outbound 路径修复
- N-006 [P1]: HTTPTransport.subscribe() 轮询实现
- N-008 [P1]: BudgetManager rolling aggregation
- N-009 [P1]: GroupChat guest 三层可见性
"""

import asyncio
import time
from collections import deque
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from ledger_engine import (
    LedgerEngine, LedgerStatus, REPLAN_MAX_PER_PLAN, REPLAN_MAX_PER_TASK,
    TaskLedger, TaskPlan,
)
from orchestrator_v9 import OrchestratorV9
from orchestrator_v8 import OrchestratorV8
from budget_manager import BudgetManager, BudgetLevel
from group_chat import (
    GroupChatEngine, GroupChatAgent, ChatMessage,
    RoundRobinSelector, MaxRoundTermination,
)
from message_adapter import MessageAdapter
from http_transport import HTTPTransport
from a2a_protocol import MemoryTransport, Task, TaskStatus


# ── N-012 [P0]: Ledger replan 死循环 ─────────────────────


class TestLedgerReplanDeadLoop:
    """验证 Ledger 不会进入 replan 死循环"""

    def test_skipped_status_exists(self):
        assert LedgerStatus.SKIPPED == "skipped"

    def test_constants_defined(self):
        assert REPLAN_MAX_PER_PLAN == 5
        assert REPLAN_MAX_PER_TASK == 20

    def test_detect_blockers_excludes_exhausted(self):
        """耗尽 replan_count 的 plan 不再被 detect_blockers 返回"""
        ledger = TaskLedger(task_id="t1", goal="test")
        plan = ledger.add_plan("p1", "do something", assigned_agent="a1")
        plan.status = LedgerStatus.FAILED
        plan.retry_count = plan.max_retries  # retry已达上限
        plan.replan_count = REPLAN_MAX_PER_PLAN  # replan也已达上限

        blockers = ledger.detect_blockers()
        assert len(blockers) == 0  # 不应再返回

    def test_detect_blockers_returns_active(self):
        """未耗尽 replan_count 的 plan 仍被返回"""
        ledger = TaskLedger(task_id="t1", goal="test")
        plan = ledger.add_plan("p1", "do something", assigned_agent="a1")
        plan.status = LedgerStatus.FAILED
        plan.retry_count = plan.max_retries
        plan.replan_count = 0  # 还有 replan 机会

        blockers = ledger.detect_blockers()
        assert len(blockers) == 1

    def test_max_replans_exceeded(self):
        """任务级 replan 总次数保护"""
        engine = LedgerEngine(max_replan_rounds=3)
        engine.create_task("t1", "test goal")
        task_ledger, _ = engine.get_ledgers("t1")
        plan = task_ledger.add_plan("p1", "step1", assigned_agent="a1")
        plan.status = LedgerStatus.FAILED
        plan.retry_count = plan.max_retries  # 确保 retry 达上限

        # 模拟连续 replan（每次都触发 blockers_detected）
        for i in range(3):
            result = engine.evaluate_and_replan("t1")
            assert result is not None, f"第{i+1}次 replan 应返回结果"
            assert result["action"] == "replan_required"

        # 第 4 次应该返回 terminate
        result = engine.evaluate_and_replan("t1")
        assert result is not None
        assert result["action"] == "terminate"
        assert result["reason"] == "max_replans_exceeded"

    def test_all_plans_exhausted(self):
        """所有 plan 都被 SKIPPED 后终止"""
        engine = LedgerEngine()
        engine.create_task("t1", "test")
        task_ledger, _ = engine.get_ledgers("t1")
        plan = task_ledger.add_plan("p1", "step1", assigned_agent="a1")
        plan.status = LedgerStatus.FAILED
        plan.retry_count = plan.max_retries
        # 让 replan_count 达到上限减 1，下次 replan 会被 SKIPPED
        plan.replan_count = REPLAN_MAX_PER_PLAN - 1

        result = engine.evaluate_and_replan("t1")
        assert result is not None
        # 计划应该被 SKIPPED 而非无限循环
        assert task_ledger._plan_index["p1"].status == LedgerStatus.SKIPPED
        assert result["action"] == "terminate"
        assert result["reason"] == "all_plans_exhausted"

    def test_replan_count_increments(self):
        """replan_count 正确递增"""
        engine = LedgerEngine()
        engine.create_task("t1", "test")
        task_ledger, _ = engine.get_ledgers("t1")
        plan = task_ledger.add_plan("p1", "step1", assigned_agent="a1")
        plan.status = LedgerStatus.FAILED
        plan.retry_count = plan.max_retries

        engine.evaluate_and_replan("t1")
        assert plan.replan_count == 1

        engine.evaluate_and_replan("t1")
        assert plan.replan_count == 2

    def test_skipped_plans_in_result(self):
        """replan 结果中包含 skipped_plans 列表"""
        engine = LedgerEngine()
        engine.create_task("t1", "test")
        task_ledger, _ = engine.get_ledgers("t1")
        # 两个 plan，一个即将被 SKIPPED
        plan_a = task_ledger.add_plan("pa", "step_a", assigned_agent="a1")
        plan_b = task_ledger.add_plan("pb", "step_b", assigned_agent="b1")
        plan_a.status = LedgerStatus.FAILED
        plan_a.retry_count = plan_a.max_retries
        plan_a.replan_count = REPLAN_MAX_PER_PLAN - 1  # 即将被 SKIPPED
        plan_b.status = LedgerStatus.FAILED
        plan_b.retry_count = plan_b.max_retries
        plan_b.replan_count = 0  # 仍然活跃

        result = engine.evaluate_and_replan("t1")
        assert result is not None
        assert "skipped_plans" in result
        assert "pa" in result["skipped_plans"]
        assert len(result["blockers"]) == 1  # 只有 plan_b 仍在 blockers 中
        assert plan_a.status == LedgerStatus.SKIPPED


# ── N-001 [P1]: __getattr__ 白名单透传 ──────────────────


class TestGetattrWhitelist:
    """验证 __getattr__ 不再暴露所有内部属性"""

    def _make_v8_mock(self):
        mock_v8 = MagicMock()
        mock_v8.load_plugins = AsyncMock()
        mock_v8.get_config = MagicMock(return_value="mock")
        mock_v8.list_agents = MagicMock(return_value=[])
        mock_v8.process = AsyncMock(return_value={"status": "success"})
        return mock_v8

    def test_v9_whitelist_allowed(self):
        """V9 白名单方法可正常透传"""
        mock_v8 = self._make_v8_mock()
        v9 = OrchestratorV9(orchestrator_v8=mock_v8, guardrails=None, ledger=None)
        v9.load_plugins  # 不应抛异常

    def test_v9_whitelist_blocked(self):
        """V9 非白名单属性抛 AttributeError"""
        mock_v8 = self._make_v8_mock()
        v9 = OrchestratorV9(orchestrator_v8=mock_v8, guardrails=None, ledger=None)
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = v9._v7  # 内部属性不应透传

    def test_v9_internal_tracer_blocked(self):
        """V9 的深层穿透属性 _tracer 被拦截"""
        mock_v8 = self._make_v8_mock()
        v9 = OrchestratorV9(orchestrator_v8=mock_v8, guardrails=None, ledger=None)
        with pytest.raises(AttributeError):
            _ = v9._tracer

    def test_v9_pass_through_set_is_extensible(self):
        """白名单是可扩展 set 类型"""
        assert isinstance(OrchestratorV9._V8_PASS_THROUGH, set)
        # 测试 register_passthrough
        OrchestratorV9.register_passthrough("test_method")
        assert "test_method" in OrchestratorV9._V8_PASS_THROUGH
        OrchestratorV9._V8_PASS_THROUGH.discard("test_method")  # 清理

    def test_v9_all_whitelist_methods_callable(self):
        """V9 白名单中的方法都可以访问"""
        mock_v8 = self._make_v8_mock()
        v9 = OrchestratorV9(orchestrator_v8=mock_v8, guardrails=None, ledger=None)
        for method_name in OrchestratorV9._V8_PASS_THROUGH:
            assert hasattr(v9, method_name), f"V9 缺少白名单方法: {method_name}"

    def test_v8_whitelist_allowed(self):
        """V8 白名单方法可正常透传"""
        mock_v7 = MagicMock()
        mock_v7.load_plugins = AsyncMock()
        mock_v7.get_config = MagicMock(return_value="mock")
        v8 = OrchestratorV8(orchestrator_v7=mock_v7, budget_manager=None)
        v8.get_config("key")

    def test_v8_whitelist_blocked(self):
        """V8 非白名单属性抛 AttributeError"""
        mock_v7 = MagicMock()
        v8 = OrchestratorV8(orchestrator_v7=mock_v7, budget_manager=None)
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = v8._v5  # 内部属性不应透传


# ── N-003 [P1]: TaskDispatcher Budget 预检 ────────────────


class TestDispatcherBudgetPrecheck:
    """验证 TaskDispatcher 分发前检查预算"""

    @pytest.mark.asyncio
    async def test_budget_exceeded_returns_failure(self):
        """预算不足时分发返回 failure"""
        from task_dispatcher import TaskDispatcher
        from agent_registry import AgentRegistry
        from interfaces import AgentTask

        budget = BudgetManager(request_budget_usd=0.001, daily_budget_usd=0.001)
        # 用尽预算：设置一个有成本的定价
        budget.set_pricing("expensive-model", 100.0, 100.0)
        budget.record_usage("expensive-model", 100, 100)  # 花费20美元

        registry = AgentRegistry()
        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock()

        dispatcher = TaskDispatcher(registry, mock_bus, budget_manager=budget)
        task = AgentTask(
            task_id="t1", target="agent1", intent="test",
            payload={"model": "expensive-model", "query": "x" * 100},
        )
        result = await dispatcher.dispatch(task)
        assert result.status == "failure"
        assert "Budget" in result.error

    @pytest.mark.asyncio
    async def test_budget_available_dispatches_normally(self):
        """预算充足时正常分发"""
        from task_dispatcher import TaskDispatcher
        from agent_registry import AgentRegistry
        from interfaces import AgentTask, IAgentPlugin

        budget = BudgetManager(daily_budget_usd=1000)
        registry = AgentRegistry()

        # 注册一个 mock agent (register 是 async)
        mock_agent = MagicMock(spec=IAgentPlugin)
        mock_agent.agent_id = "agent1"
        mock_agent.handle_task = AsyncMock(
            return_value=MagicMock(
                task_id="t1", trace_id="t1", agent_id="agent1",
                status="success", latency_ms=10, error=None,
            )
        )
        await registry.register(mock_agent)

        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock()

        dispatcher = TaskDispatcher(registry, mock_bus, budget_manager=budget)
        task = AgentTask(task_id="t1", target="agent1", intent="test")
        result = await dispatcher.dispatch(task)
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_no_budget_manager_passes_through(self):
        """无 budget_manager 时正常放行"""
        from task_dispatcher import TaskDispatcher
        from agent_registry import AgentRegistry
        from interfaces import AgentTask

        registry = AgentRegistry()
        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock()

        dispatcher = TaskDispatcher(registry, mock_bus)
        task = AgentTask(task_id="t1", target="nonexistent", intent="test")
        result = await dispatcher.dispatch(task)
        assert result.status == "failure"  # Agent not found, not budget


# ── N-008 [P1]: BudgetManager rolling aggregation ────────


class TestBudgetRollingAggregation:
    """验证 BudgetManager O(1) rolling aggregation"""

    def test_deque_maxlen(self):
        """_records 使用 deque，有 maxlen 限制"""
        bm = BudgetManager()
        assert hasattr(bm._records, 'maxlen')
        assert bm._records.maxlen == 100000

    def test_daily_rolling_cache(self):
        """日预算缓存字段存在"""
        bm = BudgetManager()
        assert hasattr(bm, '_daily_total')
        assert hasattr(bm, '_daily_window_start')

    def test_monthly_rolling_cache(self):
        """月预算缓存字段存在"""
        bm = BudgetManager()
        assert hasattr(bm, '_monthly_total')
        assert hasattr(bm, '_monthly_window_start')

    def test_record_usage_increments_daily_with_cost(self):
        """record_usage 增量更新日缓存（有成本的模型）"""
        bm = BudgetManager(daily_budget_usd=1000)
        # 设置一个有成本的定价
        bm.set_pricing("paid-model", 1.0, 2.0)
        # 初始化窗口
        bm.check_budget(BudgetLevel.DAILY)
        initial = bm._daily_total

        bm.record_usage("paid-model", 100, 100)
        # paid-model: 100/1000*1.0 + 100/1000*2.0 = 0.1 + 0.2 = 0.3
        assert bm._daily_total > initial
        assert abs(bm._daily_total - initial - 0.3) < 0.001

    def test_budget_check_consistency(self):
        """rolling aggregation 和全量计算结果一致"""
        bm = BudgetManager(daily_budget_usd=1000)
        bm.set_pricing("paid-model", 1.0, 2.0)

        # 初始化窗口
        ok1, used1, _ = bm.check_budget(BudgetLevel.DAILY)
        assert ok1

        # 记录多笔使用
        bm.record_usage("paid-model", 500, 500)
        bm.record_usage("paid-model", 300, 200)

        # 检查 rolling 结果
        ok2, used2, _ = bm.check_budget(BudgetLevel.DAILY)

        # 验证：全量计算
        expected = sum(r.estimated_cost for r in bm._records if r.timestamp >= bm._daily_window_start)
        assert abs(used2 - expected) < 0.001, f"Rolling {used2} != Full {expected}"

    def test_refresh_daily_window_method(self):
        """_refresh_daily_window 方法存在"""
        bm = BudgetManager()
        assert hasattr(bm, '_refresh_daily_window')

    def test_refresh_monthly_window_method(self):
        """_refresh_monthly_window 方法存在"""
        bm = BudgetManager()
        assert hasattr(bm, '_refresh_monthly_window')

    def test_deque_auto_eviction(self):
        """超过 maxlen 时自动淘汰旧记录"""
        bm = BudgetManager.__new__(BudgetManager)
        bm.daily_budget = 1000
        bm.monthly_budget = 10000
        bm.request_budget = 1.0
        bm.enable_routing = True
        bm._pricing = dict(BudgetManager.DEFAULT_PRICING)
        bm._records = deque(maxlen=5)  # 极小 maxlen 测试
        bm._daily_total = 0.0
        bm._monthly_total = 0.0
        bm._daily_window_start = 0.0
        bm._monthly_window_start = 0.0
        bm._logger = MagicMock()

        for i in range(7):
            bm.record_usage("mock-model", 10, 10)

        assert len(bm._records) <= 5


# ── N-009 [P1]: GroupChat guest 三层可见性 ────────────────


class TestGroupChatGuestVisibility:
    """验证 guest 角色的三层可见性模型"""

    @pytest.mark.asyncio
    async def test_guest_sees_user_messages(self):
        """guest 能看到所有 user 消息"""
        responses = []

        class GuestAgent(GroupChatAgent):
            async def respond(self, context, task=""):
                responses.append([m.agent_id for m in context])
                return "ok"

        agent = GuestAgent(agent_id="guest1", role="guest")
        engine = GroupChatEngine(
            agents=[agent],
            rbac_guard=MagicMock(),
        )
        await engine.run(task="hello")
        assert "user" in responses[0]

    @pytest.mark.asyncio
    async def test_guest_sees_agent_summary_after_agent_speaks(self):
        """当 agent 先发言后，guest 能看到 agent 消息摘要"""
        responses = {}

        class MemberAgent(GroupChatAgent):
            async def respond(self, context, task=""):
                responses["member"] = list(context)
                return "this is a detailed agent analysis response about the task"

        class GuestAgent(GroupChatAgent):
            async def respond(self, context, task=""):
                responses["guest"] = list(context)
                return "guest reply"

        # Agent 排列顺序：member 先发言
        member = MemberAgent(agent_id="member1", role="member")
        guest = GuestAgent(agent_id="guest1", role="guest")
        engine = GroupChatEngine(
            agents=[member, guest],
            selector=RoundRobinSelector(),
            rbac_guard=MagicMock(),
            termination=MaxRoundTermination(4),
        )
        await engine.run(task="test task")

        # guest 应该收到 _system 摘要消息
        if "guest" in responses:
            ctx = responses["guest"]
            system_msgs = [m for m in ctx if m.agent_id == "_system"]
            # 因为 member 先发言，guest 应该能看到摘要
            agent_msgs_in_history = [
                m for m in engine.get_history() if m.agent_id not in ("user", "guest1", "_system")
            ]
            if agent_msgs_in_history:
                assert len(system_msgs) > 0, "guest should see agent summary via _system messages"
                assert "Agent讨论摘要" in system_msgs[0].content

    @pytest.mark.asyncio
    async def test_non_guest_gets_full_context(self):
        """非 guest 角色获取完整上下文"""
        responses = []

        class MemberAgent(GroupChatAgent):
            async def respond(self, context, task=""):
                responses.append(list(context))
                return "ok"

        agent = MemberAgent(agent_id="member1", role="member")
        engine = GroupChatEngine(
            agents=[agent],
            rbac_guard=MagicMock(),
        )
        await engine.run(task="hello")
        # member 应该看到完整消息列表
        assert len(responses[0]) == 1  # 只有 user 消息


# ── N-005 [P1]: MessageAdapter outbound 路径 ─────────────


class TestMessageAdapterOutbound:
    """验证 MessageAdapter outbound 路径修复"""

    def test_bus_to_a2a_conversion(self):
        """BusMessage 到 A2A Task 转换正确"""
        from interfaces import BusMessage

        adapter = MessageAdapter()
        msg = BusMessage(
            msg_id="msg_1",
            topic="agent.target1",
            sender="orchestrator",
            recipient="target1",
            msg_type="agent.handoff",
            payload={"key": "value"},
            trace_id="trace_1",
        )
        task = adapter.bus_to_a2a(msg)
        assert task.task_id == "msg_1"
        assert task.sender == "orchestrator"
        assert task.recipient == "target1"

    def test_a2a_to_bus_conversion(self):
        """A2A Task 到 BusMessage 转换正确"""
        task = Task(
            task_id="task_1",
            status=TaskStatus.COMPLETED,
            sender="agent1",
            recipient="user",
            description="done",
            payload={"result": "ok"},
            trace_id="trace_1",
        )
        adapter = MessageAdapter()
        bus_msg = adapter.a2a_to_bus(task)
        assert bus_msg.msg_id == "task_1"
        assert bus_msg.sender == "agent1"

    def test_register_with_bus_memory_transport_distinction(self):
        """register_with_bus 正确区分 MemoryTransport 和 HTTPTransport"""
        adapter = MessageAdapter()

        # 无 transport 时注册 bus 应 warning 但不崩溃
        import asyncio
        async def _test():
            from message_bus import MessageBus
            bus = await MessageBus.get_instance()
            await adapter.register_with_bus(bus)
            assert adapter._bus is not None
        asyncio.run(_test())

    def test_memory_transport_get_handlers(self):
        """MemoryTransport.get_handlers() 返回已注册的 handlers"""
        transport = MemoryTransport()
        handler_called = []
        async def my_handler(task):
            handler_called.append(task.task_id)
            return MagicMock(is_final=True)

        transport.register_handler("h1", my_handler)
        transport.register_handler("h2", my_handler)

        handlers = transport.get_handlers()
        assert "h1" in handlers
        assert "h2" in handlers


# ── N-006 [P1]: HTTPTransport.subscribe 轮询 ─────────────


class TestHTTPTransportSubscribe:
    """验证 HTTPTransport.subscribe() 轮询实现"""

    @pytest.mark.asyncio
    async def test_subscribe_yields_timeout_sentinel(self):
        """subscribe 超时后返回终止哨兵"""
        transport = HTTPTransport(base_url="http://localhost:99999", timeout=1.0)
        # 由于无服务器，最终应 yield timeout sentinel
        updates = []
        async for update in transport.subscribe("agent1"):
            updates.append(update)
            if update.is_final:
                break
        assert len(updates) >= 1
        assert updates[-1].is_final
