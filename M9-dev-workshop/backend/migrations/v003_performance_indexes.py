"""
迁移脚本 v003 - performance_indexes

为 M9 开发工坊模块添加性能优化索引。

包含：
- work_projects：created_at、updated_at、language 等索引
- work_tasks：priority、due_date、updated_at、assignee 等索引
- work_commits：hash、author、branch 等索引
- dev_activities：project+timestamp 复合索引
- 各表复合索引优化

注意：所有索引使用 CREATE INDEX IF NOT EXISTS，保证幂等。
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "performance_indexes"
__description__ = "M9 性能优化索引：补充工作项目、任务、提交等表的常用查询索引"


def up(conn):
    """
    升级迁移 - 添加性能优化索引

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # work_projects 新增索引
    # ============================================================

    # 创建时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wp_created_at
        ON work_projects (created_at)
    """))

    # 更新时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wp_updated_at
        ON work_projects (updated_at)
    """))

    # 语言索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wp_language
        ON work_projects (language)
    """))

    # 用户+状态复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wp_user_status
        ON work_projects (user_id, status)
    """))

    # 状态+更新时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wp_status_updated
        ON work_projects (status, updated_at)
    """))

    # ============================================================
    # work_tasks 新增索引
    # ============================================================

    # 优先级索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_priority
        ON work_tasks (priority)
    """))

    # 截止日期索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_due_date
        ON work_tasks (due_date)
    """))

    # 创建时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_created_at
        ON work_tasks (created_at)
    """))

    # 更新时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_updated_at
        ON work_tasks (updated_at)
    """))

    # 负责人索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_assignee
        ON work_tasks (assignee)
    """))

    # 项目+状态复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_project_status
        ON work_tasks (project_id, status)
    """))

    # 用户+状态复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_user_status
        ON work_tasks (user_id, status)
    """))

    # 状态+优先级复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_status_priority
        ON work_tasks (status, priority)
    """))

    # 负责人+状态复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_assignee_status
        ON work_tasks (assignee, status)
    """))

    # ============================================================
    # work_commits 新增索引
    # ============================================================

    # 提交哈希索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wc_hash
        ON work_commits (hash)
    """))

    # 作者索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wc_author
        ON work_commits (author)
    """))

    # 分支索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wc_branch
        ON work_commits (branch)
    """))

    # 项目+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wc_project_time
        ON work_commits (project_id, committed_at)
    """))

    # 作者+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wc_author_time
        ON work_commits (author, committed_at)
    """))

    # ============================================================
    # work_dev_code_usage 新增索引
    # ============================================================

    # 动作类型索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wdcu_action_type
        ON work_dev_code_usage (action_type)
    """))

    # 语言索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wdcu_language
        ON work_dev_code_usage (language)
    """))

    # 项目+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wdcu_project_time
        ON work_dev_code_usage (project_id, created_at)
    """))

    # 用户+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wdcu_user_time
        ON work_dev_code_usage (user_id, created_at)
    """))

    # ============================================================
    # dev_activities 新增索引
    # ============================================================

    # 项目+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_da_project_time
        ON dev_activities (project, timestamp)
    """))

    # 活动类型+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_da_type_time
        ON dev_activities (activity_type, timestamp)
    """))

    # ============================================================
    # workspace_projects 新增索引
    # ============================================================

    # 创建时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ws_created_at
        ON workspace_projects (created_at)
    """))

    # 更新时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ws_updated_at
        ON workspace_projects (updated_at)
    """))

    # 打开次数索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ws_open_count
        ON workspace_projects (open_count)
    """))

    # ============================================================
    # vscode_sessions 新增索引
    # ============================================================

    # 进程ID索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_vs_pid
        ON vscode_sessions (pid)
    """))

    # ============================================================
    # mcp_tools 新增索引
    # ============================================================

    # 分类+启用状态复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_mt_category_enabled
        ON mcp_tools (category, enabled)
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
        # mcp_tools
        "idx_mt_category_enabled",
        # vscode_sessions
        "idx_vs_pid",
        # workspace_projects
        "idx_ws_open_count",
        "idx_ws_updated_at",
        "idx_ws_created_at",
        # dev_activities
        "idx_da_type_time",
        "idx_da_project_time",
        # work_dev_code_usage
        "idx_wdcu_user_time",
        "idx_wdcu_project_time",
        "idx_wdcu_language",
        "idx_wdcu_action_type",
        # work_commits
        "idx_wc_author_time",
        "idx_wc_project_time",
        "idx_wc_branch",
        "idx_wc_author",
        "idx_wc_hash",
        # work_tasks
        "idx_wt_assignee_status",
        "idx_wt_status_priority",
        "idx_wt_user_status",
        "idx_wt_project_status",
        "idx_wt_assignee",
        "idx_wt_updated_at",
        "idx_wt_created_at",
        "idx_wt_due_date",
        "idx_wt_priority",
        # work_projects
        "idx_wp_status_updated",
        "idx_wp_user_status",
        "idx_wp_language",
        "idx_wp_updated_at",
        "idx_wp_created_at",
    ]

    for idx_name in indexes_to_drop:
        conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
