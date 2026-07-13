from __future__ import annotations

"""Pipeline State Store - 流水线执行状态持久化与可观测.

将 Pipeline 执行上下文持久化到 SQLite，支持执行历史查询、
断点续执行、执行图可视化。

【重构说明】
本模块已迁移到 Repository 模式，内部委托给 PipelineRepository。
保留原有 API 以确保完全向后兼容。
"""

import json
import os
from typing import Any

from pydantic import BaseModel, Field

from skill_cluster.db.pipeline_repository import (
    PipelineRepository,
    PipelineRunRecord,
)
from skill_cluster.db.base import SQLiteDatabase
from skill_cluster.skill_pipeline import PipelineContext

__all__ = ["PipelineRunRecord", "PipelineStateStore"]


class PipelineStateStore:
    """流水线状态存储.

    【重构后】内部委托给 PipelineRepository，提供完全相同的 API。

    Args:
        db_path: 数据库文件路径，默认 ~/.yunxi/data/pipeline_runs.db
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.expanduser(
            "~/.yunxi/data/pipeline_runs.db"
        )
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        # 使用统一的 SQLiteDatabase + PipelineRepository
        self._db = SQLiteDatabase(self._db_path)
        self._repo = PipelineRepository(self._db)

    def save(self, ctx: PipelineContext) -> None:
        """保存执行上下文.

        Args:
            ctx: Pipeline 执行上下文
        """
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
        self._repo.save(record)

    def get(self, run_id: str) -> PipelineRunRecord | None:
        """按 run_id 查询执行记录.

        Args:
            run_id: 运行 ID

        Returns:
            PipelineRunRecord 或 None
        """
        return self._repo.get(run_id)

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
        return self._repo.list_runs(
            pipeline_id=pipeline_id,
            agent_id=agent_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    def get_stats(self, pipeline_id: str | None = None) -> dict[str, Any]:
        """获取执行统计.

        Args:
            pipeline_id: 按流水线 ID 筛选（None 表示全部）

        Returns:
            统计信息字典
        """
        return self._repo.get_stats(pipeline_id=pipeline_id)

    def delete_old_runs(self, before_timestamp: float) -> int:
        """删除旧记录.

        Args:
            before_timestamp: 删除此时间戳之前的记录

        Returns:
            删除的记录数
        """
        return self._repo.delete_old_runs(before_timestamp)

    # ------------------------------------------------------------------
    # 新增：底层 Repository 访问（供高级用户使用）
    # ------------------------------------------------------------------

    @property
    def repository(self) -> PipelineRepository:
        """获取底层 PipelineRepository 实例."""
        return self._repo

    @property
    def database(self) -> SQLiteDatabase:
        """获取底层 SQLiteDatabase 实例."""
        return self._db

    def close(self) -> None:
        """优雅关闭数据库连接."""
        self._db.close()

    def __enter__(self) -> "PipelineStateStore":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
