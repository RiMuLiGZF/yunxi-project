from __future__ import annotations

"""Pipeline State Store - 流水线执行状态持久化与可观测.

将 Pipeline 执行上下文持久化到 SQLite，支持执行历史查询、
断点续执行、执行图可视化。
"""

import json
import os
import sqlite3
import time
from typing import Any

from pydantic import BaseModel, Field

from skill_cluster.skill_pipeline import PipelineContext


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


class PipelineStateStore:
    """流水线状态存储."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.expanduser(
            "~/.yunxi/data/pipeline_runs.db"
        )
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
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
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pipeline_id ON pipeline_runs(pipeline_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_id ON pipeline_runs(agent_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_status ON pipeline_runs(status)
                """
            )
            conn.commit()

    def save(self, ctx: PipelineContext) -> None:
        """保存执行上下文."""
        duration = (
            (ctx.finished_at - ctx.started_at) * 1000
            if ctx.finished_at else 0.0
        )
        record = PipelineRunRecord(
            run_id=ctx.run_id,
            pipeline_id=ctx.pipeline_id,
            agent_id=ctx.agent_id,
            trace_id=ctx.trace_id,
            status=ctx.status,
            started_at=ctx.started_at,
            finished_at=ctx.finished_at,
            duration_ms=duration,
            step_count=len(ctx.step_results),
            step_results_json=json.dumps(
                {
                    sid: {
                        "status": r.status,
                        "action": r.action,
                        "latency_ms": r.latency_ms,
                        "error": r.error,
                    }
                    for sid, r in ctx.step_results.items()
                },
                ensure_ascii=False,
            ),
            variables_json=json.dumps(ctx.variables, ensure_ascii=False),
        )

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
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
            conn.commit()

    def get(self, run_id: str) -> PipelineRunRecord | None:
        """按 run_id 查询执行记录."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
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
        """查询执行记录列表."""
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

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM pipeline_runs {where} ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._row_to_record(r) for r in rows]

    def get_stats(self, pipeline_id: str | None = None) -> dict[str, Any]:
        """获取执行统计."""
        where = "WHERE pipeline_id = ?" if pipeline_id else ""
        params = [pipeline_id] if pipeline_id else []

        with sqlite3.connect(self._db_path) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM pipeline_runs {where}", params
            ).fetchone()[0]
            success = conn.execute(
                f"SELECT COUNT(*) FROM pipeline_runs {where} {'AND' if where else 'WHERE'} status = 'success'",
                params,
            ).fetchone()[0]
            failure = conn.execute(
                f"SELECT COUNT(*) FROM pipeline_runs {where} {'AND' if where else 'WHERE'} status = 'failure'",
                params,
            ).fetchone()[0]
            avg_duration = conn.execute(
                f"SELECT AVG(duration_ms) FROM pipeline_runs {where}", params
            ).fetchone()[0]

        return {
            "total": total,
            "success": success,
            "failure": failure,
            "success_rate": success / total if total > 0 else 0.0,
            "avg_duration_ms": avg_duration or 0.0,
        }

    def delete_old_runs(self, before_timestamp: float) -> int:
        """删除旧记录."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM pipeline_runs WHERE started_at < ?",
                (before_timestamp,),
            )
            conn.commit()
            return cursor.rowcount

    def _row_to_record(self, row: sqlite3.Row) -> PipelineRunRecord:
        return PipelineRunRecord(
            run_id=row[0],
            pipeline_id=row[1],
            agent_id=row[2],
            trace_id=row[3],
            status=row[4],
            started_at=row[5],
            finished_at=row[6],
            duration_ms=row[7],
            step_count=row[8],
            step_results_json=row[9],
            variables_json=row[10],
        )
