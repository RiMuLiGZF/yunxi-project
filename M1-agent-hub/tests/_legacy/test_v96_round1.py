"""
V9.6 第一轮增量优化测试

覆盖修复：
- V6-011 [P1]: V8.process() hardcoded deep attribute penetration
- LedgerLifecycle: close_task() 行为
- AdaptiveRetry: 自适应退避配置
- RegistryInvertedIndex: O(1) 能力查询
"""

import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from orchestrator_v8 import OrchestratorV8
from ledger_engine import (
    LedgerEngine, LedgerStatus, TaskLedger, ProgressLedger,
)
from retry_coordinator import RetryCoordinator
from enhanced_registry import EnhancedRegistry


# ── TestLedgerLifecycle ───────────────────────────────


class TestLedgerLifecycle:
    """验证 LedgerEngine.close_task() 生命周期行为"""

    def test_close_task_marks_all_plans_final(self):
        """close_task 将所有未完成的计划标记为 FINAL"""
        engine = LedgerEngine()
        engine.create_task("t1", "test goal")
        task_ledger, _ = engine.get_ledgers("t1")
        task_ledger.add_plan("p1", "step1", assigned_agent="a1")
        task_ledger.add_plan("p2", "step2", assigned_agent="a2")
        task_ledger.update_plan_status("p2", LedgerStatus.COMPLETED)

        assert engine.close_task("t1") is True

        # p1 应被标记为 FINAL（因为原本不是 COMPLETED/SKIPPED/FINAL）
        # p2 应保持 COMPLETED
        # task_ledger 已从 active_task_ledgers 中移除，需要通过返回值验证
        # 但 task_ledger 对象本身仍在内存中（被局部变量引用）
        assert task_ledger._plan_index["p1"].status == LedgerStatus.FINAL
        assert task_ledger._plan_index["p2"].status == LedgerStatus.COMPLETED

    def test_close_task_removes_from_active_task_ledgers(self):
        """close_task 将任务从 active_task_ledgers 中移除"""
        engine = LedgerEngine()
        engine.create_task("t1", "test goal")
        assert "t1" in engine.active_task_ledgers

        engine.close_task("t1")
        assert "t1" not in engine.active_task_ledgers
        assert len(engine.active_task_ledgers) == 0

    def test_close_task_keeps_progress_ledger_as_archive(self):
        """close_task 保留 progress_ledger 作为存档"""
        engine = LedgerEngine()
        engine.create_task("t1", "test goal")
        _, progress_ledger_before = engine.get_ledgers("t1")
        progress_ledger_before.record_progress("a1", LedgerStatus.IN_PROGRESS)

        engine.close_task("t1")

        # task_ledger 被移除
        assert engine.get_ledgers("t1") == (None, progress_ledger_before)
        # progress_ledger 仍可通过 get_ledgers 获取（作为存档）
        _, progress_ledger_after = engine.get_ledgers("t1")
        assert progress_ledger_after is not None
        assert "a1" in progress_ledger_after.progress_records


# ── TestAdaptiveRetry ─────────────────────────────────


class TestAdaptiveRetry:
    """验证 RetryCoordinator 自适应退避配置"""

    def test_classify_error_timeout(self):
        """包含 timeout 关键字的错误被分类为 timeout"""
        assert RetryCoordinator.classify_error("Request timeout") == "timeout"
        assert RetryCoordinator.classify_error("Connection timed out") == "timeout"

    def test_classify_error_oom(self):
        """包含 oom/out of memory 关键字的错误被分类为 oom"""
        assert RetryCoordinator.classify_error("OOM error") == "oom"
        assert RetryCoordinator.classify_error("CUDA out of memory") == "oom"

    def test_classify_error_network(self):
        """包含 network/connection 关键字的错误被分类为 network"""
        assert RetryCoordinator.classify_error("Network unreachable") == "network"
        assert RetryCoordinator.classify_error("Connection refused") == "network"

    def test_classify_error_unknown(self):
        """无匹配关键字的错误被分类为 unknown"""
        assert RetryCoordinator.classify_error("Something went wrong") == "unknown"
        assert RetryCoordinator.classify_error("") == "unknown"

    def test_adaptive_delay_uses_profile(self):
        """timeout 错误使用比 oom 更短的基础延迟"""
        timeout_delay = RetryCoordinator.adaptive_delay("timeout", retry_count=0)
        oom_delay = RetryCoordinator.adaptive_delay("oom", retry_count=0)
        network_delay = RetryCoordinator.adaptive_delay("network", retry_count=0)

        assert timeout_delay < oom_delay
        assert network_delay < oom_delay
        assert timeout_delay == 0.5
        assert oom_delay == 5.0
        assert network_delay == 1.0


# ── TestRegistryInvertedIndex ─────────────────────────


class TestRegistryInvertedIndex:
    """验证 EnhancedRegistry 能力反向索引"""

    @pytest.mark.asyncio
    async def test_capability_index_populated_on_register(self):
        """注册 Agent 时能力反向索引被填充"""
        reg = EnhancedRegistry()

        class FakeAgent:
            agent_id = "a1"
            version = "1.0"
            capabilities = ["chat", "code"]

        await reg.register(FakeAgent())
        assert "chat" in reg._capability_index
        assert "code" in reg._capability_index
        assert "a1" in reg._capability_index["chat"]
        assert "a1" in reg._capability_index["code"]

    @pytest.mark.asyncio
    async def test_capability_index_cleaned_on_unregister(self):
        """注销 Agent 时能力反向索引被清理"""
        reg = EnhancedRegistry()

        class FakeAgent:
            agent_id = "a1"
            version = "1.0"
            capabilities = ["chat"]

        await reg.register(FakeAgent())
        await reg.unregister("a1")

        assert "a1" not in reg._capability_index.get("chat", set())

    @pytest.mark.asyncio
    async def test_find_by_capability_uses_index(self):
        """find_by_capability 使用反向索引快速查找"""
        reg = EnhancedRegistry()

        class ChatAgent:
            agent_id = "chat_a"
            version = "1.0"
            capabilities = ["chat"]

        class CodeAgent:
            agent_id = "code_a"
            version = "1.0"
            capabilities = ["code"]

        await reg.register(ChatAgent())
        await reg.register(CodeAgent())

        chat_agents = reg.find_by_capability("chat")
        assert len(chat_agents) == 1
        assert chat_agents[0].agent_id == "chat_a"

        code_agents = reg.find_by_capability("code")
        assert len(code_agents) == 1
        assert code_agents[0].agent_id == "code_a"

        empty = reg.find_by_capability("nonexistent")
        assert empty == []


# ── TestV8TracerExtraction ────────────────────────────


class TestV8TracerExtraction:
    """验证 V8 不再深层穿透获取 tracer"""

    def test_v8_stores_tracer_at_init(self):
        """V8 在 __init__ 中将 tracer 提取到 self._tracer"""
        mock_tracer = MagicMock()
        mock_v2 = MagicMock()
        mock_v2._tracer = mock_tracer
        mock_v3 = MagicMock()
        mock_v3._v2 = mock_v2
        mock_v4 = MagicMock()
        mock_v4._v3 = mock_v3
        mock_v5 = MagicMock()
        mock_v5._v4 = mock_v4
        mock_v7 = MagicMock()
        mock_v7._v5 = mock_v5

        v8 = OrchestratorV8(orchestrator_v7=mock_v7)
        assert v8._tracer is mock_tracer

    def test_v8_stores_none_when_no_tracer(self):
        """当 V7 链中无 tracer 时，self._tracer 为 None"""
        mock_v7 = MagicMock()
        mock_v7._v5 = None

        v8 = OrchestratorV8(orchestrator_v7=mock_v7)
        assert v8._tracer is None

    def test_v8_uses_explicit_tracer_parameter(self):
        """当传入 tracer 参数时，优先使用显式参数"""
        explicit_tracer = MagicMock()
        mock_v7 = MagicMock()

        v8 = OrchestratorV8(orchestrator_v7=mock_v7, tracer=explicit_tracer)
        assert v8._tracer is explicit_tracer

    @pytest.mark.asyncio
    async def test_v8_process_uses_local_tracer(self):
        """V8.process() 使用 self._tracer 而非深层穿透"""
        mock_tracer = MagicMock()
        mock_trace = MagicMock()
        mock_trace.to_dict.return_value = {"spans": []}
        mock_tracer.get_trace.return_value = mock_trace

        mock_v7 = MagicMock()
        mock_v7.process = AsyncMock(return_value={"status": "success"})
        # 确保 V7 链中没有 _tracer，以证明 V8 使用的是 self._tracer
        del mock_v7._v5

        v8 = OrchestratorV8(orchestrator_v7=mock_v7, tracer=mock_tracer)
        # 确保 _tracer 来自显式传入
        assert v8._tracer is mock_tracer

        result = await v8.process("hello", trace_id="t1")

        # 验证 tracer.get_trace 被调用
        mock_tracer.get_trace.assert_called_once_with("t1")
        assert result["status"] == "success"
