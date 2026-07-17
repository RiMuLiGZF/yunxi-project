"""
M7 单元测试 - 执行记录增强测试

覆盖: 执行进度、执行日志、失败节点高亮、流式输出
运行: python -m pytest tests/test_execution_records.py -v
"""
import os
import sys
import pytest
import asyncio
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from services.execution_recorder import (
    ExecutionRecorder,
    NodeExecutionRecord,
    WorkflowExecutionRecord,
)


@pytest.fixture
def recorder():
    """执行记录器 fixture"""
    return ExecutionRecorder()


@pytest.fixture
def sample_workflow():
    """示例工作流"""
    return {
        "id": "wf_test_001",
        "name": "测试工作流",
        "blocks": [
            {"id": "node1", "name": "节点1", "type": "start"},
            {"id": "node2", "name": "节点2", "type": "llm"},
            {"id": "node3", "name": "节点3", "type": "end"},
        ],
    }


class TestNodeExecutionRecord:
    """节点执行记录测试"""

    def test_create_record(self):
        """创建节点记录"""
        record = NodeExecutionRecord(
            node_id="node1",
            node_name="测试节点",
            node_type="llm",
        )

        assert record.node_id == "node1"
        assert record.node_name == "测试节点"
        assert record.node_type == "llm"
        assert record.status == "pending"
        assert record.retry_count == 0

    def test_record_start(self):
        """记录开始"""
        record = NodeExecutionRecord(node_id="n1", node_name="n", node_type="t")
        record.start()

        assert record.status == "running"
        assert record.started_at is not None
        assert record.started_at > 0

    def test_record_complete(self):
        """记录完成"""
        record = NodeExecutionRecord(node_id="n1", node_name="n", node_type="t")
        record.start()
        record.complete(output={"result": "success"})

        assert record.status == "completed"
        assert record.completed_at is not None
        assert record.output == {"result": "success"}
        assert record.duration_ms > 0

    def test_record_fail(self):
        """记录失败"""
        record = NodeExecutionRecord(node_id="n1", node_name="n", node_type="t")
        record.start()
        record.fail(error="测试错误", error_type="ValueError")

        assert record.status == "failed"
        assert record.error == "测试错误"
        assert record.error_type == "ValueError"
        assert record.completed_at is not None

    def test_record_retry(self):
        """记录重试"""
        record = NodeExecutionRecord(node_id="n1", node_name="n", node_type="t")
        record.start()
        record.fail(error="临时错误")
        record.retry()

        assert record.retry_count == 1
        assert record.status == "retrying"

    def test_to_dict(self):
        """转字典"""
        record = NodeExecutionRecord(node_id="n1", node_name="测试", node_type="llm")
        record.start()
        record.complete(output={"data": "test"})

        d = record.to_dict()
        assert d["node_id"] == "n1"
        assert d["node_name"] == "测试"
        assert d["status"] == "completed"
        assert "duration_ms" in d
        assert "output" in d


class TestWorkflowExecutionRecord:
    """工作流执行记录测试"""

    def test_create_record(self, sample_workflow):
        """创建工作流执行记录"""
        record = WorkflowExecutionRecord(
            workflow_id=sample_workflow["id"],
            workflow_name=sample_workflow["name"],
            blocks=sample_workflow["blocks"],
        )

        assert record.workflow_id == "wf_test_001"
        assert record.status == "pending"
        assert record.total_nodes == 3
        assert record.completed_nodes == 0
        assert record.failed_nodes == 0

    def test_start_execution(self, sample_workflow):
        """开始执行"""
        record = WorkflowExecutionRecord(
            workflow_id="wf1",
            workflow_name="test",
            blocks=sample_workflow["blocks"],
        )
        record.start()

        assert record.status == "running"
        assert record.started_at is not None

    def test_node_start(self, sample_workflow):
        """节点开始执行"""
        record = WorkflowExecutionRecord(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )
        record.start()
        record.node_start("node1")

        assert record.get_node_record("node1").status == "running"
        assert record.running_nodes == 1

    def test_node_complete(self, sample_workflow):
        """节点完成"""
        record = WorkflowExecutionRecord(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )
        record.start()
        record.node_start("node1")
        record.node_complete("node1", output={"result": "ok"})

        node = record.get_node_record("node1")
        assert node.status == "completed"
        assert record.completed_nodes == 1
        assert record.progress_percent > 0

    def test_node_fail(self, sample_workflow):
        """节点失败"""
        record = WorkflowExecutionRecord(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )
        record.start()
        record.node_start("node2")
        record.node_fail("node2", error="测试错误")

        node = record.get_node_record("node2")
        assert node.status == "failed"
        assert record.failed_nodes == 1

    def test_progress_percentage(self, sample_workflow):
        """进度百分比计算"""
        record = WorkflowExecutionRecord(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )
        record.start()

        # 0% 进度
        assert record.progress_percent == 0

        # 完成一个节点
        record.node_start("node1")
        record.node_complete("node1", output={})
        assert record.progress_percent == round(1 / 3 * 100, 1)

        # 完成所有节点
        record.node_start("node2")
        record.node_complete("node2", output={})
        record.node_start("node3")
        record.node_complete("node3", output={})
        assert record.progress_percent == 100

    def test_complete_workflow(self, sample_workflow):
        """完成工作流"""
        record = WorkflowExecutionRecord(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )
        record.start()

        # 完成所有节点
        for block in sample_workflow["blocks"]:
            record.node_start(block["id"])
            record.node_complete(block["id"], output={})

        record.complete()

        assert record.status == "completed"
        assert record.completed_at is not None
        assert record.progress_percent == 100

    def test_fail_workflow(self, sample_workflow):
        """工作流失败"""
        record = WorkflowExecutionRecord(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )
        record.start()
        record.node_start("node1")
        record.node_fail("node1", error="致命错误")
        record.fail(error="节点失败导致工作流终止")

        assert record.status == "failed"
        assert record.error == "节点失败导致工作流终止"

    def test_get_failed_nodes(self, sample_workflow):
        """获取失败节点列表"""
        record = WorkflowExecutionRecord(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )
        record.start()
        record.node_start("node2")
        record.node_fail("node2", error="错误1")

        failed = record.get_failed_nodes()
        assert len(failed) == 1
        assert failed[0].node_id == "node2"

    def test_get_logs(self, sample_workflow):
        """获取执行日志"""
        record = WorkflowExecutionRecord(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )
        record.start()
        record.node_start("node1")
        record.node_complete("node1", output={})

        logs = record.get_logs()
        assert isinstance(logs, list)
        assert len(logs) > 0

    def test_to_dict(self, sample_workflow):
        """转字典"""
        record = WorkflowExecutionRecord(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )
        record.start()
        record.node_start("node1")
        record.node_complete("node1", output={"data": "test"})

        d = record.to_dict()
        assert d["workflow_id"] == "wf1"
        assert d["status"] == "running"
        assert d["total_nodes"] == 3
        assert d["completed_nodes"] == 1
        assert "progress_percent" in d
        assert "node_records" in d


class TestExecutionRecorder:
    """执行记录器测试"""

    def test_create_execution(self, recorder, sample_workflow):
        """创建执行记录"""
        exec_id = recorder.create_execution(
            workflow_id="wf1",
            workflow_name="test",
            blocks=sample_workflow["blocks"],
        )

        assert exec_id is not None
        assert len(exec_id) > 0

        record = recorder.get_execution(exec_id)
        assert record is not None
        assert record.workflow_id == "wf1"

    def test_get_execution_not_found(self, recorder):
        """获取不存在的执行记录"""
        record = recorder.get_execution("nonexistent")
        assert record is None

    def test_list_executions(self, recorder, sample_workflow):
        """列出执行记录"""
        for i in range(5):
            recorder.create_execution(
                workflow_id=f"wf_{i}",
                workflow_name=f"工作流{i}",
                blocks=sample_workflow["blocks"],
            )

        executions = recorder.list_executions(limit=10)
        assert len(executions) == 5

    def test_list_executions_pagination(self, recorder, sample_workflow):
        """执行记录分页"""
        for i in range(10):
            recorder.create_execution(
                workflow_id=f"wf_{i}",
                workflow_name=f"工作流{i}",
                blocks=sample_workflow["blocks"],
            )

        page1 = recorder.list_executions(limit=3, offset=0)
        page2 = recorder.list_executions(limit=3, offset=3)

        assert len(page1) == 3
        assert len(page2) == 3
        # 按时间倒序，第一页应该是最新的
        assert page1[0].workflow_id == "wf_9"

    def test_list_executions_by_workflow(self, recorder, sample_workflow):
        """按工作流筛选执行记录"""
        recorder.create_execution(
            workflow_id="wf_a", workflow_name="A", blocks=sample_workflow["blocks"]
        )
        recorder.create_execution(
            workflow_id="wf_a", workflow_name="A", blocks=sample_workflow["blocks"]
        )
        recorder.create_execution(
            workflow_id="wf_b", workflow_name="B", blocks=sample_workflow["blocks"]
        )

        executions = recorder.list_executions(workflow_id="wf_a")
        assert len(executions) == 2

    def test_update_node_status(self, recorder, sample_workflow):
        """更新节点状态"""
        exec_id = recorder.create_execution(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )

        recorder.start_execution(exec_id)
        recorder.node_start(exec_id, "node1")
        recorder.node_complete(exec_id, "node1", output={})

        record = recorder.get_execution(exec_id)
        assert record.completed_nodes == 1

    def test_execution_stats(self, recorder, sample_workflow):
        """执行统计"""
        # 创建一些执行记录
        for i in range(5):
            exec_id = recorder.create_execution(
                workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
            )
            if i < 3:
                recorder.start_execution(exec_id)
                for block in sample_workflow["blocks"]:
                    recorder.node_start(exec_id, block["id"])
                    recorder.node_complete(exec_id, block["id"], output={})
                recorder.complete_execution(exec_id)
            else:
                recorder.start_execution(exec_id)
                recorder.node_start(exec_id, "node1")
                recorder.node_fail(exec_id, "node1", error="错误")
                recorder.fail_execution(exec_id, error="失败")

        stats = recorder.get_stats(workflow_id="wf1")
        assert stats["total"] == 5
        assert stats["completed"] == 3
        assert stats["failed"] == 2
        assert stats["success_rate"] == 60.0

    def test_stream_logs(self, recorder, sample_workflow):
        """流式日志获取"""
        exec_id = recorder.create_execution(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )
        recorder.start_execution(exec_id)
        recorder.node_start(exec_id, "node1")
        recorder.node_complete(exec_id, "node1", output={})

        logs = recorder.get_logs(exec_id)
        assert isinstance(logs, list)
        assert len(logs) > 0

    def test_cancel_execution(self, recorder, sample_workflow):
        """取消执行"""
        exec_id = recorder.create_execution(
            workflow_id="wf1", workflow_name="test", blocks=sample_workflow["blocks"]
        )
        recorder.start_execution(exec_id)

        result = recorder.cancel_execution(exec_id, reason="用户取消")
        assert result is True

        record = recorder.get_execution(exec_id)
        assert record.status == "cancelled"

    def test_max_records_limit(self, sample_workflow):
        """最大记录数限制"""
        recorder = ExecutionRecorder(max_records=10)
        for i in range(20):
            recorder.create_execution(
                workflow_id=f"wf_{i}",
                workflow_name=f"工作流{i}",
                blocks=sample_workflow["blocks"],
            )

        executions = recorder.list_executions(limit=100)
        assert len(executions) == 10  # 受 max_records 限制


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
