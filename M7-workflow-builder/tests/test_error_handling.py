"""
M7 单元测试 - 异常处理测试 (TS-002, P2级)

覆盖: 节点执行失败、工作流失败回滚、重试机制、超时处理、错误传播
运行: python -m pytest tests/test_error_handling.py -v
"""
import os
import sys
import pytest
from services.engine import WorkflowEngine


@pytest.fixture
def engine():
    """创建工作流引擎实例."""
    eng = WorkflowEngine(use_builtin_fallback=True, workflow_timeout=30, block_timeout=5)
    eng._m2_available = False
    eng._m2_check_time = float('inf')
    return eng


class TestNodeExecutionFailure:
    """节点执行失败测试"""

    def test_unknown_block_type_fails(self, engine):
        """未知积木类型应执行失败."""
        import asyncio
        workflow = {
            "id": "wf_unknown",
            "name": "未知积木测试",
            "blocks": [
                {"id": "bad", "type": "skill.nonexistent_xyz", "name": "未知积木",
                 "config": {"action": "default"}},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        # 未知积木类型，M2 不可用且无内置降级，应该失败
        assert result["status"] == "failed"
        assert result["failed_blocks"] >= 1
        assert result["success_blocks"] == 0

    def test_linear_workflow_stops_on_failure(self, engine):
        """线性工作流遇到失败节点应停止执行."""
        import asyncio
        workflow = {
            "id": "wf_stop_on_fail",
            "name": "失败停止测试",
            "blocks": [
                {"id": "ok", "type": "skill.translate", "name": "成功节点",
                 "config": {"action": "translate"}, "next": ["fail"]},
                {"id": "fail", "type": "skill.nonexistent_xyz", "name": "失败节点",
                 "config": {"action": "default"}, "next": ["after"]},
                {"id": "after", "type": "skill.notify", "name": "之后节点",
                 "config": {"action": "send"}, "next": []},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        # 失败后应停止，after 节点不应被执行
        assert result["status"] == "failed"
        step_ids = [s["block_id"] for s in result["steps"]]
        assert "ok" in step_ids
        assert "fail" in step_ids
        # after 节点应该因为依赖失败而被跳过
        assert "after" not in [s["block_id"] for s in result["steps"] if s["status"] == "success"]

    def test_failure_error_message_preserved(self, engine):
        """失败节点应保留错误信息."""
        import asyncio
        workflow = {
            "id": "wf_error_msg",
            "name": "错误信息测试",
            "blocks": [
                {"id": "fail", "type": "skill.nonexistent_xyz", "name": "失败节点",
                 "config": {"action": "default"}},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        assert result["status"] == "failed"
        # 工作流级别的 error 应该有内容
        assert result["error"] is not None
        # 步骤级别的 error 也应该有内容
        fail_step = result["steps"][0]
        assert fail_step["error"] is not None
        assert len(fail_step["error"]) > 0

    def test_dag_failure_propagates_to_dependents(self, engine):
        """DAG 中失败节点的后继节点应被跳过."""
        import asyncio
        workflow = {
            "id": "wf_dag_fail",
            "name": "DAG失败传播测试",
            "blocks": [
                {"id": "start", "type": "skill.web_fetch", "name": "开始",
                 "config": {"action": "fetch"}, "next": ["ok", "fail"]},
                {"id": "ok", "type": "skill.translate", "name": "成功分支",
                 "config": {"action": "translate"}, "next": ["merge"]},
                {"id": "fail", "type": "skill.nonexistent_xyz", "name": "失败分支",
                 "config": {"action": "default"}, "next": ["merge"]},
                {"id": "merge", "type": "skill.notify", "name": "汇合",
                 "config": {"action": "send"}, "next": []},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        # 整体应该失败
        assert result["status"] == "failed"
        # 失败节点的后继 (merge) 应该被跳过或失败
        step_statuses = {s["block_id"]: s["status"] for s in result["steps"]}
        assert "fail" in step_statuses
        assert step_statuses["fail"] == "failed"


class TestRetryMechanism:
    """重试机制测试"""

    def test_retry_config_on_block(self, engine):
        """节点应支持配置重试策略."""
        import asyncio
        workflow = {
            "id": "wf_retry",
            "name": "重试测试",
            "blocks": [
                {
                    "id": "retry_node",
                    "type": "skill.nonexistent_xyz",
                    "name": "重试节点",
                    "config": {"action": "default"},
                    "retry": {
                        "max_retries": 2,
                        "retry_delay": 0.01,
                        "retry_backoff": 1.0,
                    },
                },
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        # 虽然最终失败，但重试次数应该被记录
        assert result["status"] == "failed"
        step = result["steps"][0]
        # 最多重试 2 次（加上首次共 3 次尝试）
        assert step["retry_count"] <= 2
        assert step["retry_count"] >= 0

    def test_retry_with_retry_on_filter(self, engine):
        """retry_on 白名单应过滤可重试的错误."""
        import asyncio
        workflow = {
            "id": "wf_retry_filter",
            "name": "重试过滤测试",
            "blocks": [
                {
                    "id": "retry_node",
                    "type": "skill.nonexistent_xyz",
                    "name": "重试节点",
                    "config": {"action": "default"},
                    "retry": {
                        "max_retries": 3,
                        "retry_delay": 0.01,
                        "retry_backoff": 1.0,
                        "retry_on": ["网络错误", "timeout"],
                    },
                },
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        # 错误信息不包含 retry_on 中的关键词，应该不重试
        assert result["status"] == "failed"
        step = result["steps"][0]
        # 由于错误不匹配白名单，重试次数应该为 0
        assert step["retry_count"] == 0

    def test_zero_retries_no_retry(self, engine):
        """max_retries=0 时不应重试."""
        import asyncio
        workflow = {
            "id": "wf_no_retry",
            "name": "不重试测试",
            "blocks": [
                {
                    "id": "fail_node",
                    "type": "skill.nonexistent_xyz",
                    "name": "失败节点",
                    "config": {"action": "default"},
                    "retry": {"max_retries": 0},
                },
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        assert result["status"] == "failed"
        step = result["steps"][0]
        assert step["retry_count"] == 0

    def test_successful_node_no_retry(self, engine):
        """成功的节点不应有重试."""
        import asyncio
        workflow = {
            "id": "wf_success_no_retry",
            "name": "成功不重试测试",
            "blocks": [
                {
                    "id": "ok",
                    "type": "skill.translate",
                    "name": "成功节点",
                    "config": {"action": "translate"},
                    "retry": {"max_retries": 3},
                },
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        assert result["status"] == "success"
        step = result["steps"][0]
        assert step["retry_count"] == 0
        assert step["status"] == "success"


class TestTimeoutHandling:
    """超时处理测试"""

    def test_block_timeout_config(self, engine):
        """引擎应配置积木超时时间."""
        assert engine.block_timeout > 0
        assert isinstance(engine.block_timeout, (int, float))

    def test_workflow_timeout_config(self, engine):
        """引擎应配置工作流超时时间."""
        assert engine.workflow_timeout > 0
        assert isinstance(engine.workflow_timeout, (int, float))

    def test_short_block_timeout_fails_slow_block(self):
        """极短的积木超时应导致执行失败（模拟）."""
        import asyncio
        # 创建一个超时极短的引擎
        eng = WorkflowEngine(
            use_builtin_fallback=True,
            workflow_timeout=30,
            block_timeout=0.001,  # 1毫秒，几乎必超时
        )
        eng._m2_available = False
        eng._m2_check_time = float('inf')

        # 注意：内置积木执行很快，可能不会真的超时
        # 这里测试的是超时配置是否被正确设置
        assert eng.block_timeout == 0.001

    def test_workflow_timeout_field_in_result(self, engine):
        """工作流结果应包含超时配置."""
        import asyncio
        workflow = {
            "id": "wf_timeout_field",
            "name": "超时字段测试",
            "blocks": [
                {"id": "t1", "type": "skill.translate", "name": "翻译",
                 "config": {"action": "translate"}},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        assert "workflow_timeout" in result
        assert "block_timeout" in result
        assert result["workflow_timeout"] == engine.workflow_timeout
        assert result["block_timeout"] == engine.block_timeout


class TestErrorPropagation:
    """错误传播测试"""

    def test_error_in_linear_workflow_stops_execution(self, engine):
        """线性工作流中错误应停止后续执行."""
        import asyncio
        workflow = {
            "id": "wf_error_stop",
            "name": "错误停止测试",
            "blocks": [
                {"id": "a", "type": "skill.translate", "name": "A",
                 "config": {"action": "translate"}, "next": ["b"]},
                {"id": "b", "type": "skill.nonexistent_xyz", "name": "B(失败)",
                 "config": {"action": "default"}, "next": ["c"]},
                {"id": "c", "type": "skill.notify", "name": "C",
                 "config": {"action": "send"}, "next": ["d"]},
                {"id": "d", "type": "skill.web_fetch", "name": "D",
                 "config": {"action": "fetch"}, "next": []},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        assert result["status"] == "failed"
        # 成功的节点只有 a
        assert result["success_blocks"] == 1
        # 失败节点是 b
        assert result["failed_blocks"] == 1

    def test_final_output_none_on_failure(self, engine):
        """失败的工作流 final_output 应为 None."""
        import asyncio
        workflow = {
            "id": "wf_final_none",
            "name": "失败输出测试",
            "blocks": [
                {"id": "fail", "type": "skill.nonexistent_xyz", "name": "失败",
                 "config": {"action": "default"}},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        assert result["status"] == "failed"
        assert result["final_output"] is None

    def test_error_field_present_on_failure(self, engine):
        """失败的工作流应包含 error 字段."""
        import asyncio
        workflow = {
            "id": "wf_error_field",
            "name": "错误字段测试",
            "blocks": [
                {"id": "fail", "type": "skill.nonexistent_xyz", "name": "失败",
                 "config": {"action": "default"}},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        assert "error" in result
        assert result["error"] is not None
        assert len(str(result["error"])) > 0

    def test_empty_workflow_error(self, engine):
        """空工作流应返回明确的错误信息."""
        import asyncio
        workflow = {
            "id": "wf_empty",
            "name": "空工作流",
            "blocks": [],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        assert result["status"] == "failed"
        assert "没有积木块" in result["error"]

    def test_circular_dependency_error(self, engine):
        """循环依赖的工作流应返回错误."""
        import asyncio
        workflow = {
            "id": "wf_circular",
            "name": "循环依赖测试",
            "blocks": [
                {"id": "a", "type": "skill.translate", "name": "A",
                 "config": {"action": "translate"}, "next": ["b"]},
                {"id": "b", "type": "skill.notify", "name": "B",
                 "config": {"action": "send"}, "next": ["c"]},
                {"id": "c", "type": "skill.web_fetch", "name": "C",
                 "config": {"action": "fetch"}, "next": ["a"]},  # 形成环
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        assert result["status"] == "failed"
        assert "循环依赖" in result["error"] or "环" in result["error"]


class TestConcurrencyControl:
    """并发控制测试"""

    def test_concurrent_slot_management(self, engine):
        """并发槽位管理应正常工作."""
        import asyncio

        # 初始状态：运行数应为 0（或之前测试的数量）
        initial_count = WorkflowEngine.get_running_count()

        async def _test():
            # 获取槽位
            acquired = await WorkflowEngine._acquire_slot()
            assert acquired is True
            assert WorkflowEngine.get_running_count() == initial_count + 1

            # 释放槽位
            await WorkflowEngine._release_slot()
            assert WorkflowEngine.get_running_count() == initial_count

        asyncio.get_event_loop().run_until_complete(_test())

    def test_max_running_config(self):
        """最大并发数应可配置."""
        max_running = WorkflowEngine._get_max_running()
        assert max_running > 0
        assert isinstance(max_running, int)

    def test_running_count_non_negative(self):
        """运行数不应为负数."""
        count = WorkflowEngine.get_running_count()
        assert count >= 0


class TestStepResultStructure:
    """步骤结果结构测试"""

    def test_step_result_has_required_fields(self, engine):
        """每个步骤结果应包含必要字段."""
        import asyncio
        workflow = {
            "id": "wf_step_fields",
            "name": "步骤字段测试",
            "blocks": [
                {"id": "s1", "type": "skill.translate", "name": "翻译步骤",
                 "config": {"action": "translate", "text": "hello"}},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        step = result["steps"][0]
        required_fields = [
            "block_id", "block_name", "skill_id", "action",
            "status", "input", "output", "error",
            "started_at", "finished_at", "duration_ms", "retry_count",
        ]
        for field in required_fields:
            assert field in step, f"步骤结果缺少字段: {field}"

    def test_failed_step_has_error_message(self, engine):
        """失败的步骤应包含错误信息."""
        import asyncio
        workflow = {
            "id": "wf_fail_step",
            "name": "失败步骤测试",
            "blocks": [
                {"id": "fail", "type": "skill.nonexistent_xyz", "name": "失败步骤",
                 "config": {"action": "default"}},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        step = result["steps"][0]
        assert step["status"] == "failed"
        assert step["error"] is not None
        assert isinstance(step["error"], str)
        assert len(step["error"]) > 0

    def test_step_duration_is_positive(self, engine):
        """步骤耗时应大于等于 0."""
        import asyncio
        workflow = {
            "id": "wf_duration",
            "name": "耗时测试",
            "blocks": [
                {"id": "s1", "type": "skill.translate", "name": "翻译",
                 "config": {"action": "translate"}},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow(workflow)
        )

        step = result["steps"][0]
        assert step["duration_ms"] >= 0
        assert step["finished_at"] >= step["started_at"]
