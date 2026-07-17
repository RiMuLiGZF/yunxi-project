"""
迁移脚本 v001 - initial

M7 工作流模块初始表结构创建。
包含：workflow_definitions、workflow_runs、custom_blocks 三张核心表。

注意：此迁移脚本使用 SQLAlchemy Connection 对象执行 SQL 语句，
与 SQLAlchemyMigrationAdapter 适配层配合使用。
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "initial"
__description__ = "M7 工作流模块初始表结构：workflow_definitions, workflow_runs, custom_blocks"


def up(conn):
    """
    升级迁移 - 创建初始表结构

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # 1. workflow_definitions - 工作流定义表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS workflow_definitions (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(200) DEFAULT '',
            description TEXT DEFAULT '',
            category VARCHAR(50) DEFAULT '',
            status VARCHAR(20) DEFAULT 'draft',
            blocks JSON DEFAULT '[]',
            connections JSON DEFAULT '[]',
            variables JSON DEFAULT '[]',
            "trigger" JSON DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            run_count INTEGER DEFAULT 0,
            created_by VARCHAR(50) DEFAULT '',
            tags JSON DEFAULT '[]'
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_wf_name ON workflow_definitions (name)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_wf_category ON workflow_definitions (category)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_wf_status ON workflow_definitions (status)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_wf_created_at ON workflow_definitions (created_at)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_wf_name_category
        ON workflow_definitions (name, category)
    """))

    # ============================================================
    # 2. workflow_runs - 工作流运行记录表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id VARCHAR(64) PRIMARY KEY,
            workflow_id VARCHAR(64) NOT NULL,
            workflow_name VARCHAR(200) DEFAULT '',
            status VARCHAR(20) DEFAULT 'pending',
            steps JSON DEFAULT '[]',
            inputs JSON DEFAULT '{}',
            outputs JSON DEFAULT '{}',
            error TEXT DEFAULT '',
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            duration_ms INTEGER DEFAULT 0,
            triggered_by VARCHAR(50) DEFAULT ''
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_run_workflow_id ON workflow_runs (workflow_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_run_status ON workflow_runs (status)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_run_started_at ON workflow_runs (started_at)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_run_wfid_status
        ON workflow_runs (workflow_id, status)
    """))

    # ============================================================
    # 3. custom_blocks - 自定义积木表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS custom_blocks (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(200) DEFAULT '',
            category VARCHAR(50) DEFAULT '工具块',
            description TEXT DEFAULT '',
            code TEXT DEFAULT '',
            icon VARCHAR(50) DEFAULT 'puzzle',
            ports JSON DEFAULT '{}',
            user_id VARCHAR(50) DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_cb_name ON custom_blocks (name)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_cb_category ON custom_blocks (category)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_cb_user_id ON custom_blocks (user_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_cb_created_at ON custom_blocks (created_at)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_cb_user_category
        ON custom_blocks (user_id, category)
    """))


def down(conn):
    """
    降级迁移（回滚） - 删除初始表结构

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # 按创建逆序删除，避免外键约束问题
    conn.execute(text("DROP TABLE IF EXISTS custom_blocks"))
    conn.execute(text("DROP TABLE IF EXISTS workflow_runs"))
    conn.execute(text("DROP TABLE IF EXISTS workflow_definitions"))
