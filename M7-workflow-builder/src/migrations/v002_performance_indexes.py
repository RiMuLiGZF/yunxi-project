"""
迁移脚本 v002 - performance_indexes

为 M7 工作流模块添加性能优化索引。

包含：
- workflow_definitions：updated_at、run_count、created_by 等常用字段索引
- workflow_runs：finished_at、triggered_by、duration_ms 等索引
- custom_blocks：updated_at 索引
- 复合索引优化

注意：所有索引使用 CREATE INDEX IF NOT EXISTS，保证幂等。
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "performance_indexes"
__description__ = "M7 性能优化索引：补充常用查询字段和复合索引"


def up(conn):
    """
    升级迁移 - 添加性能优化索引

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # workflow_definitions 新增索引
    # ============================================================

    # 更新时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_wf_updated_at
        ON workflow_definitions (updated_at)
    """))

    # 运行次数索引（热门工作流排序）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_wf_run_count
        ON workflow_definitions (run_count)
    """))

    # 创建者索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_wf_created_by
        ON workflow_definitions (created_by)
    """))

    # 状态+分类复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_wf_status_category
        ON workflow_definitions (status, category)
    """))

    # 创建者+状态复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_wf_creator_status
        ON workflow_definitions (created_by, status)
    """))

    # ============================================================
    # workflow_runs 新增索引
    # ============================================================

    # 完成时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_run_finished_at
        ON workflow_runs (finished_at)
    """))

    # 触发者索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_run_triggered_by
        ON workflow_runs (triggered_by)
    """))

    # 耗时索引（慢运行分析）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_run_duration
        ON workflow_runs (duration_ms)
    """))

    # 工作流ID+开始时间复合索引（运行历史查询）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_run_wfid_started
        ON workflow_runs (workflow_id, started_at)
    """))

    # 状态+开始时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_run_status_started
        ON workflow_runs (status, started_at)
    """))

    # 触发者+状态复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_run_trigger_status
        ON workflow_runs (triggered_by, status)
    """))

    # ============================================================
    # custom_blocks 新增索引
    # ============================================================

    # 更新时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_cb_updated_at
        ON custom_blocks (updated_at)
    """))

    # 用户+更新时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_cb_user_updated
        ON custom_blocks (user_id, updated_at)
    """))


def down(conn):
    """
    降级迁移（回滚） - 删除新增的索引

    只删除本迁移新增的索引，保留原有索引。

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # 按创建逆序删除
    indexes_to_drop = [
        # custom_blocks
        "ix_cb_user_updated",
        "ix_cb_updated_at",
        # workflow_runs
        "ix_run_trigger_status",
        "ix_run_status_started",
        "ix_run_wfid_started",
        "ix_run_duration",
        "ix_run_triggered_by",
        "ix_run_finished_at",
        # workflow_definitions
        "ix_wf_creator_status",
        "ix_wf_status_category",
        "ix_wf_created_by",
        "ix_wf_run_count",
        "ix_wf_updated_at",
    ]

    for idx_name in indexes_to_drop:
        conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
