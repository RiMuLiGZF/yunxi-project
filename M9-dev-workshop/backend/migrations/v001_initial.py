"""
迁移脚本 v001 - initial

M9 开发工坊模块初始表结构创建。
包含：workspace_projects、vscode_sessions、mcp_tools、dev_activities 四张核心表。

注意：此迁移脚本使用 SQLAlchemy Connection 对象执行 SQL 语句，
与 SQLAlchemyMigrationAdapter 适配层配合使用。
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "initial"
__description__ = "M9 开发工坊初始表结构：workspace_projects, vscode_sessions, mcp_tools, dev_activities"


def up(conn):
    """
    升级迁移 - 创建初始表结构

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # 1. workspace_projects - 工作区项目表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS workspace_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) NOT NULL,
            path VARCHAR(1024) NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            icon VARCHAR(255) DEFAULT 'folder',
            last_opened TIMESTAMP,
            tags JSON DEFAULT '[]',
            open_count INTEGER DEFAULT 0,
            total_dev_time FLOAT DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wp_path ON workspace_projects (path)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wp_name ON workspace_projects (name)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wp_last_opened ON workspace_projects (last_opened)
    """))

    # ============================================================
    # 2. vscode_sessions - VS Code 会话记录表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS vscode_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pid INTEGER NOT NULL,
            project_path VARCHAR(1024),
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP,
            status VARCHAR(50) DEFAULT 'running',
            window_title VARCHAR(255) DEFAULT ''
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_vs_status ON vscode_sessions (status)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_vs_project_path ON vscode_sessions (project_path)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_vs_start_time ON vscode_sessions (start_time)
    """))

    # ============================================================
    # 3. mcp_tools - MCP 工具注册表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS mcp_tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            endpoint VARCHAR(1024) DEFAULT '',
            category VARCHAR(100) DEFAULT 'general',
            enabled BOOLEAN DEFAULT 1,
            input_schema JSON DEFAULT '{}',
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_mt_category ON mcp_tools (category)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_mt_enabled ON mcp_tools (enabled)
    """))

    # ============================================================
    # 4. dev_activities - 开发活动日志表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS dev_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project VARCHAR(255) DEFAULT '',
            activity_type VARCHAR(100) NOT NULL,
            duration FLOAT DEFAULT 0.0,
            description TEXT DEFAULT '',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            meta_data JSON DEFAULT '{}'
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_da_project ON dev_activities (project)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_da_timestamp ON dev_activities (timestamp)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_da_activity_type ON dev_activities (activity_type)
    """))


def down(conn):
    """
    降级迁移（回滚） - 删除初始表结构

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # 按创建逆序删除，避免外键约束问题
    conn.execute(text("DROP TABLE IF EXISTS dev_activities"))
    conn.execute(text("DROP TABLE IF EXISTS mcp_tools"))
    conn.execute(text("DROP TABLE IF EXISTS vscode_sessions"))
    conn.execute(text("DROP TABLE IF EXISTS workspace_projects"))
