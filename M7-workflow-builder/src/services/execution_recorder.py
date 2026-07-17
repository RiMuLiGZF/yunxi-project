"""M7 积木平台 - 执行记录器.

提供工作流执行过程的详细记录：
- 节点级执行记录（输入输出、耗时、状态）
- 工作流级执行记录
- 执行日志流式输出
- 执行进度百分比
- 失败节点高亮
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NodeExecutionRecord:
    """节点执行记录."""

    node_id: str
    node_name: str = ""
    node_type: str = ""
    status: str = "pending"  # pending, running, completed, failed, retrying, skipped
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_type: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_ms: int = 0
    retry_count: int = 0
    logs: List[Dict[str, Any]] = field(default_factory=list)

    def start(self, input_data: Optional[Dict[str, Any]] = None) -> None:
        """记录节点开始执行."""
        self.status = "running"
        self.started_at = time.time()
        if input_data is not None:
            self.input_data = input_data
        self._add_log("info", f"节点开始执行: {self.node_name}")

    def complete(self, output: Optional[Dict[str, Any]] = None) -> None:
        """记录节点执行完成."""
        self.status = "completed"
        self.completed_at = time.time()
        if self.started_at:
            self.duration_ms = int((self.completed_at - self.started_at) * 1000)
        if output is not None:
            self.output_data = output
        self._add_log("info", f"节点执行完成，耗时 {self.duration_ms}ms")

    def fail(self, error: str, error_type: str = "UnknownError") -> None:
        """记录节点执行失败."""
        self.status = "failed"
        self.completed_at = time.time()
        if self.started_at:
            self.duration_ms = int((self.completed_at - self.started_at) * 1000)
        self.error = error
        self.error_type = error_type
        self._add_log("error", f"节点执行失败: {error}")

    def retry(self) -> None:
        """记录节点重试."""
        self.retry_count += 1
        self.status = "retrying"
        self._add_log("warning", f"节点第 {self.retry_count} 次重试")

    def skip(self, reason: str = "") -> None:
        """记录节点跳过."""
        self.status = "skipped"
        self.completed_at = time.time()
        self._add_log("info", f"节点跳过: {reason}")

    def _add_log(self, level: str, message: str) -> None:
        """添加日志."""
        self.logs.append({
            "timestamp": time.time(),
            "level": level,
            "message": message,
            "node_id": self.node_id,
        })

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "status": self.status,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error": self.error,
            "error_type": self.error_type,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "log_count": len(self.logs),
        }


@dataclass
class WorkflowExecutionRecord:
    """工作流执行记录."""

    execution_id: str
    workflow_id: str
    workflow_name: str = ""
    status: str = "pending"  # pending, running, completed, failed, cancelled
    total_nodes: int = 0
    completed_nodes: int = 0
    failed_nodes: int = 0
    running_nodes: int = 0
    skipped_nodes: int = 0
    progress_percent: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    total_duration_ms: int = 0
    error: Optional[str] = None
    node_records: Dict[str, NodeExecutionRecord] = field(default_factory=dict)
    logs: List[Dict[str, Any]] = field(default_factory=list)

    def start(self) -> None:
        """记录工作流开始执行."""
        self.status = "running"
        self.started_at = time.time()
        self._add_log("info", f"工作流开始执行: {self.workflow_name}")

    def node_start(self, node_id: str) -> None:
        """记录节点开始."""
        record = self._get_or_create_node(node_id)
        record.start()
        self.running_nodes += 1
        self._update_progress()

    def node_complete(self, node_id: str, output: Optional[Dict[str, Any]] = None) -> None:
        """记录节点完成."""
        record = self._get_or_create_node(node_id)
        record.complete(output)
        self.completed_nodes += 1
        self.running_nodes = max(0, self.running_nodes - 1)
        self._update_progress()

    def node_fail(self, node_id: str, error: str, error_type: str = "UnknownError") -> None:
        """记录节点失败."""
        record = self._get_or_create_node(node_id)
        record.fail(error, error_type)
        self.failed_nodes += 1
        self.running_nodes = max(0, self.running_nodes - 1)
        self._update_progress()

    def node_retry(self, node_id: str) -> None:
        """记录节点重试."""
        record = self._get_or_create_node(node_id)
        record.retry()

    def node_skip(self, node_id: str, reason: str = "") -> None:
        """记录节点跳过."""
        record = self._get_or_create_node(node_id)
        record.skip(reason)
        self.skipped_nodes += 1
        self._update_progress()

    def complete(self) -> None:
        """记录工作流完成."""
        self.status = "completed"
        self.completed_at = time.time()
        if self.started_at:
            self.total_duration_ms = int((self.completed_at - self.started_at) * 1000)
        self.progress_percent = 100.0
        self._add_log("info", f"工作流执行完成，总耗时 {self.total_duration_ms}ms")

    def fail(self, error: str) -> None:
        """记录工作流失败."""
        self.status = "failed"
        self.completed_at = time.time()
        if self.started_at:
            self.total_duration_ms = int((self.completed_at - self.started_at) * 1000)
        self.error = error
        self._add_log("error", f"工作流执行失败: {error}")

    def cancel(self, reason: str = "用户取消") -> None:
        """取消工作流执行."""
        self.status = "cancelled"
        self.completed_at = time.time()
        if self.started_at:
            self.total_duration_ms = int((self.completed_at - self.started_at) * 1000)
        self._add_log("warning", f"工作流已取消: {reason}")

    def _get_or_create_node(self, node_id: str) -> NodeExecutionRecord:
        """获取或创建节点记录."""
        if node_id not in self.node_records:
            self.node_records[node_id] = NodeExecutionRecord(node_id=node_id)
        return self.node_records[node_id]

    def get_node_record(self, node_id: str) -> Optional[NodeExecutionRecord]:
        """获取节点记录."""
        return self.node_records.get(node_id)

    def get_failed_nodes(self) -> List[NodeExecutionRecord]:
        """获取所有失败的节点."""
        return [r for r in self.node_records.values() if r.status == "failed"]

    def get_completed_nodes(self) -> List[NodeExecutionRecord]:
        """获取所有完成的节点."""
        return [r for r in self.node_records.values() if r.status == "completed"]

    def _update_progress(self) -> None:
        """更新执行进度."""
        if self.total_nodes > 0:
            done = self.completed_nodes + self.failed_nodes + self.skipped_nodes
            self.progress_percent = round(done / self.total_nodes * 100, 1)

    def _add_log(self, level: str, message: str) -> None:
        """添加工作流级别日志."""
        self.logs.append({
            "timestamp": time.time(),
            "level": level,
            "message": message,
            "execution_id": self.execution_id,
        })

    def get_logs(self, level: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取执行日志.

        Args:
            level: 日志级别过滤

        Returns:
            日志列表
        """
        all_logs = list(self.logs)
        # 合并节点日志
        for node_record in self.node_records.values():
            all_logs.extend(node_record.logs)

        # 按时间排序
        all_logs.sort(key=lambda x: x.get("timestamp", 0))

        if level:
            all_logs = [l for l in all_logs if l.get("level") == level]

        return all_logs

    def to_dict(self, include_node_details: bool = True) -> Dict[str, Any]:
        """转换为字典."""
        result = {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "total_nodes": self.total_nodes,
            "completed_nodes": self.completed_nodes,
            "failed_nodes": self.failed_nodes,
            "running_nodes": self.running_nodes,
            "skipped_nodes": self.skipped_nodes,
            "progress_percent": self.progress_percent,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_ms": self.total_duration_ms,
            "error": self.error,
            "log_count": len(self.logs),
        }

        if include_node_details:
            result["node_records"] = {
                nid: rec.to_dict() for nid, rec in self.node_records.items()
            }
            # 失败节点高亮
            result["failed_nodes_detail"] = [
                rec.to_dict() for rec in self.get_failed_nodes()
            ]

        return result


class ExecutionRecorder:
    """执行记录器 - 管理所有工作流执行记录."""

    def __init__(self, max_records: int = 1000) -> None:
        self._records: Dict[str, WorkflowExecutionRecord] = {}
        self._max_records = max_records

    def create_execution(
        self,
        workflow_id: str,
        workflow_name: str,
        blocks: List[Dict[str, Any]],
    ) -> str:
        """创建新的执行记录.

        Args:
            workflow_id: 工作流 ID
            workflow_name: 工作流名称
            blocks: 工作流节点列表

        Returns:
            执行 ID
        """
        execution_id = f"exec_{uuid.uuid4().hex[:12]}"

        record = WorkflowExecutionRecord(
            execution_id=execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            total_nodes=len(blocks),
        )

        # 初始化节点记录
        for block in blocks:
            node_id = block.get("id", "")
            if node_id:
                record.node_records[node_id] = NodeExecutionRecord(
                    node_id=node_id,
                    node_name=block.get("name", ""),
                    node_type=block.get("type", ""),
                )

        self._records[execution_id] = record
        self._cleanup_old_records()

        return execution_id

    def get_execution(self, execution_id: str) -> Optional[WorkflowExecutionRecord]:
        """获取执行记录."""
        return self._records.get(execution_id)

    def list_executions(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WorkflowExecutionRecord]:
        """列出执行记录.

        Args:
            workflow_id: 按工作流筛选
            status: 按状态筛选
            limit: 数量限制
            offset: 偏移量

        Returns:
            执行记录列表（按时间倒序）
        """
        records = list(self._records.values())

        if workflow_id:
            records = [r for r in records if r.workflow_id == workflow_id]

        if status:
            records = [r for r in records if r.status == status]

        # 按开始时间倒序
        records.sort(key=lambda r: r.started_at or 0, reverse=True)

        return records[offset : offset + limit]

    def start_execution(self, execution_id: str) -> bool:
        """开始执行."""
        record = self._records.get(execution_id)
        if not record:
            return False
        record.start()
        return True

    def complete_execution(self, execution_id: str) -> bool:
        """完成执行."""
        record = self._records.get(execution_id)
        if not record:
            return False
        record.complete()
        return True

    def fail_execution(self, execution_id: str, error: str) -> bool:
        """执行失败."""
        record = self._records.get(execution_id)
        if not record:
            return False
        record.fail(error)
        return True

    def cancel_execution(self, execution_id: str, reason: str = "") -> bool:
        """取消执行."""
        record = self._records.get(execution_id)
        if not record:
            return False
        record.cancel(reason)
        return True

    def node_start(self, execution_id: str, node_id: str, input_data: Optional[Dict[str, Any]] = None) -> bool:
        """节点开始."""
        record = self._records.get(execution_id)
        if not record:
            return False
        record.node_start(node_id)
        if input_data and node_id in record.node_records:
            record.node_records[node_id].input_data = input_data
        return True

    def node_complete(self, execution_id: str, node_id: str, output: Optional[Dict[str, Any]] = None) -> bool:
        """节点完成."""
        record = self._records.get(execution_id)
        if not record:
            return False
        record.node_complete(node_id, output)
        return True

    def node_fail(self, execution_id: str, node_id: str, error: str, error_type: str = "UnknownError") -> bool:
        """节点失败."""
        record = self._records.get(execution_id)
        if not record:
            return False
        record.node_fail(node_id, error, error_type)
        return True

    def node_retry(self, execution_id: str, node_id: str) -> bool:
        """节点重试."""
        record = self._records.get(execution_id)
        if not record:
            return False
        record.node_retry(node_id)
        return True

    def node_skip(self, execution_id: str, node_id: str, reason: str = "") -> bool:
        """节点跳过."""
        record = self._records.get(execution_id)
        if not record:
            return False
        record.node_skip(node_id, reason)
        return True

    def get_progress(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """获取执行进度."""
        record = self._records.get(execution_id)
        if not record:
            return None
        return {
            "execution_id": execution_id,
            "status": record.status,
            "progress_percent": record.progress_percent,
            "total_nodes": record.total_nodes,
            "completed_nodes": record.completed_nodes,
            "failed_nodes": record.failed_nodes,
            "running_nodes": record.running_nodes,
            "started_at": record.started_at,
        }

    def get_logs(self, execution_id: str, level: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取执行日志."""
        record = self._records.get(execution_id)
        if not record:
            return []
        return record.get_logs(level=level)

    def get_stats(self, workflow_id: Optional[str] = None) -> Dict[str, Any]:
        """获取执行统计.

        Args:
            workflow_id: 按工作流统计

        Returns:
            统计信息
        """
        records = list(self._records.values())
        if workflow_id:
            records = [r for r in records if r.workflow_id == workflow_id]

        total = len(records)
        completed = sum(1 for r in records if r.status == "completed")
        failed = sum(1 for r in records if r.status == "failed")
        running = sum(1 for r in records if r.status == "running")
        cancelled = sum(1 for r in records if r.status == "cancelled")

        success_rate = round(completed / max(total, 1) * 100, 2)

        # 平均执行时间
        durations = [r.total_duration_ms for r in records if r.completed_at and r.started_at]
        avg_duration = round(sum(durations) / max(len(durations), 1), 2) if durations else 0

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "cancelled": cancelled,
            "success_rate": success_rate,
            "avg_duration_ms": avg_duration,
        }

    def _cleanup_old_records(self) -> None:
        """清理旧记录，保持在 max_records 以内."""
        if len(self._records) <= self._max_records:
            return

        # 按开始时间排序，删除最旧的
        sorted_records = sorted(
            self._records.values(),
            key=lambda r: r.started_at or 0,
        )
        to_delete = sorted_records[: len(self._records) - self._max_records]
        for record in to_delete:
            del self._records[record.execution_id]


# 全局单例
_execution_recorder: Optional[ExecutionRecorder] = None


def get_execution_recorder() -> ExecutionRecorder:
    """获取执行记录器单例."""
    global _execution_recorder
    if _execution_recorder is None:
        _execution_recorder = ExecutionRecorder()
    return _execution_recorder
