"""M7 积木平台 - 工作流错误处理增强.

提供高级错误处理功能：
- 节点级补偿/回滚机制
- 错误传播策略（终止/继续/跳过）
- 死路检测（节点执行后无后续）
- 错误聚合和报告
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .validator import build_adjacency_list

logger = logging.getLogger("m7.error_handling")


# ============================================================
# 错误传播策略
# ============================================================

class ErrorPropagationStrategy:
    """错误传播策略.

    定义节点失败时的行为：
    - FAIL_FAST (终止)：任何节点失败立即终止整个工作流
    - CONTINUE (继续)：节点失败后继续执行其他不依赖它的分支
    - SKIP_DEPENDENTS (跳过依赖)：节点失败后跳过所有依赖它的节点，但其他分支继续
    """

    FAIL_FAST = "fail_fast"
    CONTINUE = "continue"
    SKIP_DEPENDENTS = "skip_dependents"

    @classmethod
    def is_valid(cls, strategy: str) -> bool:
        """检查策略是否有效."""
        return strategy in {cls.FAIL_FAST, cls.CONTINUE, cls.SKIP_DEPENDENTS}

    @classmethod
    def default(cls) -> str:
        """默认策略."""
        return cls.FAIL_FAST


# ============================================================
# 补偿节点（回滚）
# ============================================================

class CompensationManager:
    """补偿/回滚管理器.

    管理节点的补偿操作：
    1. 每个节点可以配置补偿节点（失败时执行的回滚操作）
    2. 工作流失败时，按逆序执行已成功节点的补偿操作
    3. 支持部分回滚（仅回滚到某个检查点）
    """

    def __init__(self) -> None:
        self._compensations: List[Dict[str, Any]] = []

    def register_compensation(
        self,
        block_id: str,
        block_name: str,
        compensation_block: Dict[str, Any],
    ) -> None:
        """注册节点的补偿操作.

        Args:
            block_id: 节点 ID
            block_name: 节点名称
            compensation_block: 补偿节点配置
        """
        self._compensations.append({
            "block_id": block_id,
            "block_name": block_name,
            "compensation": compensation_block,
            "registered_at": time.time(),
        })

    def get_compensations(self) -> List[Dict[str, Any]]:
        """获取所有已注册的补偿操作（按执行顺序）."""
        return list(self._compensations)

    def get_compensations_reversed(self) -> List[Dict[str, Any]]:
        """获取逆序的补偿操作（用于回滚）."""
        return list(reversed(self._compensations))

    def clear(self) -> None:
        """清空所有补偿操作."""
        self._compensations.clear()


# ============================================================
# 死路检测
# ============================================================

def detect_dead_ends(
    blocks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """检测工作流中的死路节点.

    死路节点：执行后没有后继节点，且不是工作流的终点。
    或者：节点有条件分支，但所有分支都没有后继。

    Args:
        blocks: 积木块列表

    Returns:
        死路节点列表 [{block_id, reason, ...}, ...]
    """
    adjacency, in_degree = build_adjacency_list(blocks)

    if not blocks:
        return []

    # 找到所有终点（没有后继的节点）
    end_nodes = [bid for bid, nexts in adjacency.items() if not nexts]

    # 找到所有起点（入度为 0 的节点）
    start_nodes = [bid for bid, deg in in_degree.items() if deg == 0]

    # 如果只有一个终点且是合理的工作流结构，则不认为是死路
    dead_ends: List[Dict[str, Any]] = []

    # 检查每个节点
    block_map = {b["id"]: b for b in blocks}

    for block_id, next_nodes in adjacency.items():
        block = block_map.get(block_id, {})
        block_type = block.get("type", "")

        # 跳过终点节点（没有后继是正常的）
        if not next_nodes:
            # 检查是否有合理的理由没有后继
            # 条件节点需要有 true/false 分支
            if block_type == "logic.condition":
                config = block.get("config", {})
                true_branch = config.get("true_branch", [])
                false_branch = config.get("false_branch", [])
                if not true_branch and not false_branch:
                    dead_ends.append({
                        "block_id": block_id,
                        "block_name": block.get("name", ""),
                        "block_type": block_type,
                        "reason": "条件节点没有配置任何分支（true_branch 和 false_branch 均为空）",
                        "severity": "warning",
                    })
            continue

        # 检查是否存在无效的后继引用
        for next_id in next_nodes:
            if next_id not in block_map:
                dead_ends.append({
                    "block_id": block_id,
                    "block_name": block.get("name", ""),
                    "block_type": block_type,
                    "invalid_next": next_id,
                    "reason": f"引用了不存在的后继节点: {next_id}",
                    "severity": "error",
                })

    # 检查孤立节点（既没有前驱也没有后继的中间节点）
    for block_id in adjacency:
        has_predecessor = in_degree.get(block_id, 0) > 0
        has_successor = len(adjacency.get(block_id, [])) > 0

        if not has_predecessor and not has_successor and len(blocks) > 1:
            # 单个孤立节点
            block = block_map.get(block_id, {})
            dead_ends.append({
                "block_id": block_id,
                "block_name": block.get("name", ""),
                "block_type": block.get("type", ""),
                "reason": "孤立节点：既没有前驱也没有后继，不会被执行到",
                "severity": "warning",
            })

    return dead_ends


# ============================================================
# 错误聚合和报告
# ============================================================

class ErrorAggregator:
    """错误聚合器.

    收集工作流执行过程中的所有错误，生成统一的错误报告。
    """

    def __init__(self) -> None:
        self._errors: List[Dict[str, Any]] = []
        self._warnings: List[Dict[str, Any]] = []

    def add_error(
        self,
        block_id: str,
        error_message: str,
        error_type: str = "execution_error",
        retry_count: int = 0,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """添加错误.

        Args:
            block_id: 节点 ID
            error_message: 错误信息
            error_type: 错误类型
            retry_count: 重试次数
            details: 详细信息
        """
        self._errors.append({
            "block_id": block_id,
            "error_message": error_message,
            "error_type": error_type,
            "retry_count": retry_count,
            "timestamp": time.time(),
            "details": details or {},
        })

    def add_warning(
        self,
        block_id: str,
        warning_message: str,
        warning_type: str = "warning",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """添加警告.

        Args:
            block_id: 节点 ID
            warning_message: 警告信息
            warning_type: 警告类型
            details: 详细信息
        """
        self._warnings.append({
            "block_id": block_id,
            "warning_message": warning_message,
            "warning_type": warning_type,
            "timestamp": time.time(),
            "details": details or {},
        })

    @property
    def error_count(self) -> int:
        """错误数量."""
        return len(self._errors)

    @property
    def warning_count(self) -> int:
        """警告数量."""
        return len(self._warnings)

    @property
    def has_errors(self) -> bool:
        """是否有错误."""
        return len(self._errors) > 0

    def get_errors(self) -> List[Dict[str, Any]]:
        """获取所有错误."""
        return list(self._errors)

    def get_warnings(self) -> List[Dict[str, Any]]:
        """获取所有警告."""
        return list(self._warnings)

    def get_summary(self) -> Dict[str, Any]:
        """获取错误汇总报告."""
        error_by_type: Dict[str, int] = {}
        failed_blocks: List[str] = []

        for err in self._errors:
            err_type = err.get("error_type", "unknown")
            error_by_type[err_type] = error_by_type.get(err_type, 0) + 1
            if err["block_id"] not in failed_blocks:
                failed_blocks.append(err["block_id"])

        return {
            "total_errors": len(self._errors),
            "total_warnings": len(self._warnings),
            "failed_blocks": failed_blocks,
            "error_by_type": error_by_type,
            "errors": self._errors,
            "warnings": self._warnings,
        }

    def clear(self) -> None:
        """清空所有错误和警告."""
        self._errors.clear()
        self._warnings.clear()


# ============================================================
# 执行进度跟踪器
# ============================================================

class ProgressTracker:
    """工作流执行进度跟踪器.

    跟踪工作流的执行进度，计算百分比。
    支持实时进度更新和进度查询。
    """

    def __init__(self, total_blocks: int) -> None:
        """初始化进度跟踪器.

        Args:
            total_blocks: 总节点数
        """
        self.total_blocks = total_blocks
        self.completed_blocks: int = 0
        self.failed_blocks: int = 0
        self.skipped_blocks: int = 0
        self.current_block: Optional[str] = None
        self.start_time: float = time.time()
        self._status: str = "pending"
        self._step_progress: Dict[str, float] = {}  # 各节点内部进度

    def start(self) -> None:
        """标记执行开始."""
        self._status = "running"
        self.start_time = time.time()

    def start_block(self, block_id: str) -> None:
        """标记节点开始执行.

        Args:
            block_id: 节点 ID
        """
        self.current_block = block_id
        self._step_progress[block_id] = 0.0

    def update_block_progress(self, block_id: str, progress: float) -> None:
        """更新节点内部进度.

        Args:
            block_id: 节点 ID
            progress: 进度（0.0 - 1.0）
        """
        self._step_progress[block_id] = max(0.0, min(1.0, progress))

    def complete_block(self, block_id: str, success: bool) -> None:
        """标记节点完成.

        Args:
            block_id: 节点 ID
            success: 是否成功
        """
        if success:
            self.completed_blocks += 1
        else:
            self.failed_blocks += 1
        self._step_progress[block_id] = 1.0
        self.current_block = None

    def skip_block(self, block_id: str) -> None:
        """标记节点被跳过.

        Args:
            block_id: 节点 ID
        """
        self.skipped_blocks += 1
        self._step_progress[block_id] = 1.0

    def finish(self, status: str = "success") -> None:
        """标记执行结束.

        Args:
            status: 最终状态
        """
        self._status = status

    @property
    def progress_percent(self) -> float:
        """计算整体进度百分比（0-100）."""
        if self.total_blocks == 0:
            return 100.0

        # 已完成的节点按 100% 计算
        finished = self.completed_blocks + self.failed_blocks + self.skipped_blocks

        # 当前正在执行的节点按内部进度计算
        current_progress = 0.0
        if self.current_block and self.current_block in self._step_progress:
            current_progress = self._step_progress[self.current_block]

        total_progress = finished + current_progress
        return round((total_progress / self.total_blocks) * 100, 2)

    @property
    def status(self) -> str:
        """当前状态."""
        return self._status

    @property
    def elapsed_time(self) -> float:
        """已用时间（秒）."""
        return time.time() - self.start_time

    @property
    def estimated_remaining_time(self) -> Optional[float]:
        """预估剩余时间（秒）.

        基于已完成节点的平均耗时估算。
        """
        finished = self.completed_blocks + self.failed_blocks
        if finished == 0:
            return None

        avg_time_per_block = self.elapsed_time / finished
        remaining_blocks = self.total_blocks - finished - self.skipped_blocks
        return max(0, avg_time_per_block * remaining_blocks)

    def get_progress_info(self) -> Dict[str, Any]:
        """获取完整的进度信息."""
        return {
            "total_blocks": self.total_blocks,
            "completed_blocks": self.completed_blocks,
            "failed_blocks": self.failed_blocks,
            "skipped_blocks": self.skipped_blocks,
            "current_block": self.current_block,
            "progress_percent": self.progress_percent,
            "status": self._status,
            "elapsed_time": round(self.elapsed_time, 2),
            "estimated_remaining_time": round(self.estimated_remaining_time, 2)
                if self.estimated_remaining_time is not None else None,
            "step_progress": dict(self._step_progress),
        }


# ============================================================
# 执行日志收集器
# ============================================================

class ExecutionLogCollector:
    """执行日志收集器.

    收集工作流执行过程中的详细日志，支持流式输出。
    """

    LOG_LEVELS = {"debug", "info", "warning", "error"}

    def __init__(self) -> None:
        self._logs: List[Dict[str, Any]] = []
        self._start_time: float = time.time()

    def log(
        self,
        level: str,
        block_id: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """添加日志.

        Args:
            level: 日志级别（debug/info/warning/error）
            block_id: 相关节点 ID
            message: 日志消息
            details: 详细信息
        """
        if level not in self.LOG_LEVELS:
            level = "info"

        self._logs.append({
            "timestamp": time.time(),
            "relative_time": round(time.time() - self._start_time, 3),
            "level": level,
            "block_id": block_id,
            "message": message,
            "details": details or {},
        })

    def debug(self, block_id: str, message: str, **kwargs) -> None:
        """添加 debug 日志."""
        self.log("debug", block_id, message, kwargs)

    def info(self, block_id: str, message: str, **kwargs) -> None:
        """添加 info 日志."""
        self.log("info", block_id, message, kwargs)

    def warning(self, block_id: str, message: str, **kwargs) -> None:
        """添加 warning 日志."""
        self.log("warning", block_id, message, kwargs)

    def error(self, block_id: str, message: str, **kwargs) -> None:
        """添加 error 日志."""
        self.log("error", block_id, message, kwargs)

    def get_logs(
        self,
        level: Optional[str] = None,
        block_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """获取日志.

        Args:
            level: 按级别过滤
            block_id: 按节点过滤
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            日志列表
        """
        logs = self._logs

        if level:
            logs = [l for l in logs if l["level"] == level]

        if block_id:
            logs = [l for l in logs if l["block_id"] == block_id]

        if offset:
            logs = logs[offset:]

        if limit:
            logs = logs[:limit]

        return logs

    @property
    def log_count(self) -> int:
        """日志总数."""
        return len(self._logs)

    def get_log_summary(self) -> Dict[str, Any]:
        """获取日志汇总."""
        level_counts: Dict[str, int] = {lvl: 0 for lvl in self.LOG_LEVELS}
        block_log_counts: Dict[str, int] = {}

        for log in self._logs:
            lvl = log["level"]
            if lvl in level_counts:
                level_counts[lvl] += 1
            bid = log["block_id"]
            block_log_counts[bid] = block_log_counts.get(bid, 0) + 1

        return {
            "total_logs": len(self._logs),
            "level_counts": level_counts,
            "block_log_counts": block_log_counts,
            "start_time": self._start_time,
        }

    def clear(self) -> None:
        """清空日志."""
        self._logs.clear()
        self._start_time = time.time()


# ============================================================
# 失败节点高亮
# ============================================================

def highlight_failed_nodes(
    steps: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """高亮失败节点.

    分析执行步骤，标记失败节点及其影响的节点。

    Args:
        steps: 执行步骤列表

    Returns:
        高亮信息
    """
    failed_nodes: List[Dict[str, Any]] = []
    skipped_by_failure: List[Dict[str, Any]] = []
    successful_nodes: List[Dict[str, Any]] = []

    for step in steps:
        status = step.get("status", "")
        if status == "failed":
            failed_nodes.append({
                "block_id": step.get("block_id", ""),
                "block_name": step.get("block_name", ""),
                "error": step.get("error", ""),
                "retry_count": step.get("retry_count", 0),
                "duration_ms": step.get("duration_ms", 0),
            })
        elif status == "skipped" and step.get("error") == "前置依赖执行失败":
            skipped_by_failure.append({
                "block_id": step.get("block_id", ""),
                "block_name": step.get("block_name", ""),
                "reason": "前置依赖失败被跳过",
            })
        elif status == "success":
            successful_nodes.append({
                "block_id": step.get("block_id", ""),
                "block_name": step.get("block_name", ""),
            })

    return {
        "failed_nodes": failed_nodes,
        "skipped_by_failure": skipped_by_failure,
        "successful_nodes": successful_nodes,
        "total_failed": len(failed_nodes),
        "total_skipped": len(skipped_by_failure),
        "total_success": len(successful_nodes),
        "has_failures": len(failed_nodes) > 0,
    }
