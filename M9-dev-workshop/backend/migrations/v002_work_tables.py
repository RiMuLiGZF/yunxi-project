"""
迁移脚本 v002 - work_tables

M9 开发工坊工作开发相关表（从 M8 迁移而来）。
包含：work_projects、work_tasks、work_commits、work_dev_code_usage 四张表。

注意：此迁移脚本使用 SQLAlchemy Connection 对象执行 SQL 语句，
与 SQLAlchemyMigrationAdapter 适配层配合使用。
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "work_tables"
__description__ = "工作开发表：work_projects, work_tasks, work_commits, work_dev_code_usage（M8 迁移）"


def up(conn):
    """
    升级迁移 - 创建工作开发相关表

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # 1. work_projects - 工作项目表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS work_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            name VARCHAR(200) DEFAULT '',
            description TEXT DEFAULT '',
            status VARCHAR(20) DEFAULT 'active',
            progress INTEGER DEFAULT 0,
            repo_url VARCHAR(500) DEFAULT '',
            language VARCHAR(50) DEFAULT '',
            file_count INTEGER DEFAULT 0,
            line_count INTEGER DEFAULT 0,
            commit_count INTEGER DEFAULT 0,
            user_id VARCHAR(128),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wp_user_id ON work_projects (user_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wp_status ON work_projects (status)
    """))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wp_project_id ON work_projects (project_id)
    """))

    # ============================================================
    # 2. work_tasks - 工作任务表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS work_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            title VARCHAR(255) DEFAULT '',
            description TEXT DEFAULT '',
            status VARCHAR(20) DEFAULT 'todo',
            priority VARCHAR(20) DEFAULT 'medium',
            project_id INTEGER,
            assignee VARCHAR(100) DEFAULT '',
            due_date VARCHAR(20),
            user_id VARCHAR(128),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_user_id ON work_tasks (user_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_status ON work_tasks (status)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wt_project_id ON work_tasks (project_id)
    """))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wt_task_id ON work_tasks (task_id)
    """))

    # ============================================================
    # 3. work_commits - 代码提交记录表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS work_commits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_id INTEGER,
            hash VARCHAR(64) DEFAULT '',
            message TEXT DEFAULT '',
            author VARCHAR(100) DEFAULT '',
            branch VARCHAR(100) DEFAULT '',
            project_id INTEGER,
            additions INTEGER DEFAULT 0,
            deletions INTEGER DEFAULT 0,
            files_changed INTEGER DEFAULT 0,
            committed_at TIMESTAMP,
            user_id VARCHAR(128)
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wc_user_id ON work_commits (user_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wc_project_id ON work_commits (project_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wc_committed_at ON work_commits (committed_at)
    """))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wc_commit_id ON work_commits (commit_id)
    """))

    # ============================================================
    # 4. work_dev_code_usage - 代码开发用量表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS work_dev_code_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usage_id INTEGER,
            action_type VARCHAR(20) DEFAULT '',
            operation_type VARCHAR(20) DEFAULT '',
            language VARCHAR(50) DEFAULT '',
            tokens_used INTEGER DEFAULT 0,
            project_id INTEGER,
            is_fallback BOOLEAN DEFAULT 0,
            user_id VARCHAR(128),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wdcu_user_id ON work_dev_code_usage (user_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wdcu_project_id ON work_dev_code_usage (project_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wdcu_created_at ON work_dev_code_usage (created_at)
    """))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wdcu_usage_id ON work_dev_code_usage (usage_id)
    """))


def down(conn):
    """
    降级迁移（回滚） - 删除工作开发相关表

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # 按创建逆序删除，避免外键约束问题
    conn.execute(text("DROP TABLE IF EXISTS work_dev_code_usage"))
    conn.execute(text("DROP TABLE IF EXISTS work_commits"))
    conn.execute(text("DROP TABLE IF EXISTS work_tasks"))
    conn.execute(text("DROP TABLE IF EXISTS work_projects"))
