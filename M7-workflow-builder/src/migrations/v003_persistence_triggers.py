"""
迁移脚本 v003 - persistence_triggers

P2 级优化：持久化执行引擎 + 触发器系统 数据库表结构。

新增表：
- persistent_workflow_runs: 持久化工作流运行表（增强版，支持断点恢复）
- execution_contexts: 执行上下文快照表（用于断点恢复）
- triggers: 触发器定义表（Schedule/Webhook/Event）
- trigger_history: 触发历史表

新增索引：
- 针对查询模式优化的复合索引

注意：所有表使用 CREATE TABLE IF NOT EXISTS，保证幂等。
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "persistence_triggers"
__description__ = "P2 持久化执行引擎 + 触发器系统：persistent_workflow_runs, execution_contexts, triggers, trigger_history"


def up(conn):
    """
    升级迁移 - 创建持久化引擎和触发器相关表

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # 1. persistent_workflow_runs - 持久化工作流运行表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS persistent_workflow_runs (
            id VARCHAR(64) PRIMARY KEY,
            workflow_id VARCHAR(64) NOT NULL,
            workflow_name VARCHAR(200) DEFAULT '',
            status VARCHAR(20) DEFAULT 'pending',
            current_node_id VARCHAR(64) DEFAULT '',
            context_data JSON DEFAULT '{}',
            step_results JSON DEFAULT '{}',
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            created_by VARCHAR(50) DEFAULT '',
            priority INTEGER DEFAULT 5,
            result_summary JSON DEFAULT '{}',
            error_message TEXT DEFAULT '',
            retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 0,
            trigger_type VARCHAR(20) DEFAULT 'manual',
            trigger_id VARCHAR(64) DEFAULT '',
            input_data JSON DEFAULT '{}',
            timeout_seconds INTEGER DEFAULT 300,
            last_heartbeat TIMESTAMP,
            version INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_persist_workflow_id
        ON persistent_workflow_runs (workflow_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_persist_status
        ON persistent_workflow_runs (status)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_persist_priority
        ON persistent_workflow_runs (priority)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_persist_created_at
        ON persistent_workflow_runs (created_at)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_persist_last_heartbeat
        ON persistent_workflow_runs (last_heartbeat)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_persist_trigger_id
        ON persistent_workflow_runs (trigger_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_persist_wfid_status
        ON persistent_workflow_runs (workflow_id, status)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_persist_status_priority
        ON persistent_workflow_runs (status, priority)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_persist_trigger_type
        ON persistent_workflow_runs (trigger_type, status)
    """))

    # ============================================================
    # 2. execution_contexts - 执行上下文快照表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS execution_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id VARCHAR(64) NOT NULL,
            node_id VARCHAR(64) DEFAULT '',
            context_data JSON DEFAULT '{}',
            step_results JSON DEFAULT '{}',
            variables JSON DEFAULT '{}',
            snapshot_type VARCHAR(20) DEFAULT 'node_complete',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_ctx_run_id
        ON execution_contexts (run_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_ctx_snapshot_type
        ON execution_contexts (snapshot_type)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_ctx_created_at
        ON execution_contexts (created_at)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_ctx_runid_type
        ON execution_contexts (run_id, snapshot_type)
    """))

    # ============================================================
    # 3. triggers - 触发器定义表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS triggers (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(200) DEFAULT '',
            description TEXT DEFAULT '',
            workflow_id VARCHAR(64) NOT NULL,
            trigger_type VARCHAR(20) DEFAULT 'schedule',
            enabled INTEGER DEFAULT 0,
            config JSON DEFAULT '{}',
            input_mapping JSON DEFAULT '{}',
            filter_config JSON DEFAULT '{}',
            webhook_secret VARCHAR(100) DEFAULT '',
            webhook_path VARCHAR(200) DEFAULT '',
            timezone VARCHAR(50) DEFAULT 'Asia/Shanghai',
            last_triggered_at TIMESTAMP,
            trigger_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            created_by VARCHAR(50) DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_trigger_workflow_id
        ON triggers (workflow_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_trigger_type
        ON triggers (trigger_type)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_trigger_enabled
        ON triggers (enabled)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_trigger_webhook_path
        ON triggers (webhook_path)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_trigger_created_at
        ON triggers (created_at)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_trigger_wfid_type
        ON triggers (workflow_id, trigger_type)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_trigger_enabled_type
        ON triggers (enabled, trigger_type)
    """))

    # ============================================================
    # 4. trigger_history - 触发历史表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS trigger_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_id VARCHAR(64) NOT NULL,
            workflow_id VARCHAR(64) NOT NULL,
            run_id VARCHAR(64) DEFAULT '',
            trigger_type VARCHAR(20) DEFAULT 'schedule',
            status VARCHAR(20) DEFAULT 'success',
            payload JSON DEFAULT '{}',
            input_data JSON DEFAULT '{}',
            result_data JSON DEFAULT '{}',
            error_message TEXT DEFAULT '',
            triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_ms INTEGER DEFAULT 0,
            source_info JSON DEFAULT '{}'
        )
    """))

    # 索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_th_trigger_id
        ON trigger_history (trigger_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_th_workflow_id
        ON trigger_history (workflow_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_th_run_id
        ON trigger_history (run_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_th_status
        ON trigger_history (status)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_th_triggered_at
        ON trigger_history (triggered_at)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_th_triggerid_time
        ON trigger_history (trigger_id, triggered_at)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_th_wfid_status
        ON trigger_history (workflow_id, status)
    """))


def down(conn):
    """
    降级迁移（回滚） - 删除新增的表

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # 按创建逆序删除，避免外键约束问题
    conn.execute(text("DROP TABLE IF EXISTS trigger_history"))
    conn.execute(text("DROP TABLE IF EXISTS triggers"))
    conn.execute(text("DROP TABLE IF EXISTS execution_contexts"))
    conn.execute(text("DROP TABLE IF EXISTS persistent_workflow_runs"))
