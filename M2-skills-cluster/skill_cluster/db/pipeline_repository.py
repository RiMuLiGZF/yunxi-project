from __future__ import annotations

"""Pipeline Repository - 流水线状态持久化 Repository.

将 pipeline_store.py 的数据库操作迁移到 Repository 模式，
pipeline_store.py 保留向后兼容，内部委托给 PipelineRepository。
"""

import json
from typing import Any

import structlog
from pydantic import BaseModel, Field

from skill_cluster.db.base import BaseRepository, SQLiteDatabase

logger = structlog.get_logger()


class PipelineRunRecord(BaseModel):
    """流水线执行记录."""

    run_id: str = Field(..., description="运行 ID")
    pipeline_id: str = Field(..., description="流水线 ID")
    agent_id: str = Field(..., description="Agent 标识")
    trace_id: str = Field(..., description="追踪 ID")
    status: str = Field(..., description="状态")
    started_at: float = Field(..., description="开始时间")
    finished_at: float | None = Field(default=None, description="结束时间")
    duration_ms: float = Field(default=0.0, description="耗时")
    step_count: int = Field(default=0, description="步骤数")
    step_results_json: str = Field(default="{}", description="步骤结果 JSON")
    variables_json: str = Field(default="{}", description="变量 JSON")


class PipelineRepository(BaseRepository):
    """流水线状态 Repository.

    封装 pipeline_runs 表的所有数据库操作，提供类型安全的 API。

    Args:
        db: SQLiteDatabase 实例
    """

    table_name = "pipeline_runs"
    primary_key = "run_id"

    def _create_tables(self) -> None:
        """创建 pipeline_runs 表."""
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id TEXT PRIMARY KEY,
                pipeline_id TEXT,
                agent_id TEXT,
                trace_id TEXT,
                status TEXT,
                started_at REAL,
                finished_at REAL,
                duration_ms REAL,
                step_count INTEGER,
                step_results_json TEXT,
                variables_json TEXT
            )
            """
        )

    def _create_indexes(self) -> None:
        """创建索引."""
        self._ensure_index("pipeline_id")
        self._ensure_index("agent_id")
        self._ensure_index("status")
        self._ensure_index("trace_id")

    # ------------------------------------------------------------------
    # 写入操作
    # ------------------------------------------------------------------

    def save(self, record: PipelineRunRecord) -> None:
        """保存（插入或替换）一条流水线执行记录.

        Args:
            record: 流水线执行记录
        """
        self._db.execute(
            """
            INSERT OR REPLACE INTO pipeline_runs
            (run_id, pipeline_id, agent_id, trace_id, status,
             started_at, finished_at, duration_ms, step_count,
             step_results_json, variables_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.run_id,
                record.pipeline_id,
                record.agent_id,
                record.trace_id,
                record.status,
                record.started_at,
                record.finished_at,
                record.duration_ms,
                record.step_count,
                record.step_results_json,
                record.variables_json,
            ),
        )
        logger.debug("pipeline_run_saved", run_id=record.run_id, status=record.status)

    # ------------------------------------------------------------------
    # 查询操作
    # ------------------------------------------------------------------

    def get(self, run_id: str) -> PipelineRunRecord | None:
        """按 run_id 查询执行记录.

        Args:
            run_id: 运行 ID

        Returns:
            PipelineRunRecord 或 None
        """
        row = self.get_by_id(run_id)
        if row is None:
            return None
        return self._row_to_record(row)

    def list_runs(
        self,
        pipeline_id: str | None = None,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PipelineRunRecord]:
        """查询执行记录列表.

        Args:
            pipeline_id: 按流水线 ID 筛选
            agent_id: 按 Agent ID 筛选
            status: 按状态筛选
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            PipelineRunRecord 列表
        """
        conditions: list[str] = []
        params: list[Any] = []

        if pipeline_id is not None:
            conditions.append("pipeline_id = ?")
            params.append(pipeline_id)
        if agent_id is not None:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.extend([limit, offset])

        rows = self._db.fetchall(
            f"""
            SELECT * FROM pipeline_runs{where_clause}
            ORDER BY started_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        )
        return [self._row_to_record(r) for r in rows]

    def get_stats(self, pipeline_id: str | None = None) -> dict[str, Any]:
        """获取执行统计.

        Args:
            pipeline_id: 按流水线 ID 筛选（None 表示全部）

        Returns:
            统计信息字典
        """
        where_clause = " WHERE pipeline_id = ?" if pipeline_id else ""
        params: list[Any] = [pipeline_id] if pipeline_id else []

        total_row = self._db.fetchone(
            f"SELECT COUNT(*) FROM pipeline_runs{where_clause}", params
        )
        total = total_row[0] if total_row else 0

        success_where = (
            f"{where_clause} AND status = 'success'"
            if where_clause
            else " WHERE status = 'success'"
        )
        failure_where = (
            f"{where_clause} AND status = 'failure'"
            if where_clause
            else " WHERE status = 'failure'"
        )

        success_row = self._db.fetchone(
            f"SELECT COUNT(*) FROM pipeline_runs{success_where}", params
        )
        success = success_row[0] if success_row else 0

        failure_row = self._db.fetchone(
            f"SELECT COUNT(*) FROM pipeline_runs{failure_where}", params
        )
        failure = failure_row[0] if failure_row else 0

        avg_row = self._db.fetchone(
            f"SELECT AVG(duration_ms) FROM pipeline_runs{where_clause}", params
        )
        avg_duration = avg_row[0] if avg_row and avg_row[0] is not None else 0.0

        return {
            "total": total,
            "success": success,
            "failure": failure,
            "success_rate": success / total if total > 0 else 0.0,
            "avg_duration_ms": avg_duration,
        }

    # ------------------------------------------------------------------
    # 删除操作
    # ------------------------------------------------------------------

    def delete_old_runs(self, before_timestamp: float) -> int:
        """删除旧记录.

        Args:
            before_timestamp: 删除此时间戳之前的记录

        Returns:
            删除的记录数
        """
        cursor = self._db.execute(
            "DELETE FROM pipeline_runs WHERE started_at < ?",
            (before_timestamp,),
        )
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info("pipeline_runs_deleted", count=deleted, before=before_timestamp)
        return deleted

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_record(row: Any) -> PipelineRunRecord:
        """将数据库行转换为 PipelineRunRecord."""
        return PipelineRunRecord(
            run_id=row["run_id"],
            pipeline_id=row["pipeline_id"],
            agent_id=row["agent_id"],
            trace_id=row["trace_id"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            duration_ms=row["duration_ms"] if row["duration_ms"] is not None else 0.0,
            step_count=row["step_count"] if row["step_count"] is not None else 0,
            step_results_json=row["step_results_json"] or "{}",
            variables_json=row["variables_json"] or "{}",
        )


def get_pipeline_repository(db_path: str | None = None) -> PipelineRepository:
    """便捷函数：创建 PipelineRepository 实例.

    Args:
        db_path: 数据库文件路径，默认 ~/.yunxi/data/pipeline_runs.db

    Returns:
        PipelineRepository 实例
    """
    import os

    path = db_path or os.path.expanduser("~/.yunxi/data/pipeline_runs.db")
    db = SQLiteDatabase(path)
    return PipelineRepository(db)
