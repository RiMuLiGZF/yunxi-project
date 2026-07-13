"""M3 主数据库迁移定义.

将 LocalDataManager 的数据库表结构通过版本化迁移管理。
当前版本：v1（初始 Schema，与原有 CREATE TABLE IF NOT EXISTS 等效）

迁移版本历史：
    v1 - 初始 Schema：call_logs, sync_items, sessions, audit_trail, config_kv, cache_items
"""

from __future__ import annotations

from edge_cloud_kernel.common.db_migration import DatabaseMigrator, Migration


# ---------------------------------------------------------------------------
# v1: 初始 Schema
# ---------------------------------------------------------------------------

V1_UP_SQL = [
    # call_logs: 调用日志
    """
    CREATE TABLE IF NOT EXISTS call_logs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id        TEXT,
        model           TEXT,
        prompt_tokens   INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        total_tokens    INTEGER DEFAULT 0,
        latency_ms      INTEGER DEFAULT 0,
        status          TEXT,
        error           TEXT,
        route           TEXT,
        created_at      REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_call_logs_agent_id ON call_logs(agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_call_logs_created_at ON call_logs(created_at)",

    # sync_items: 同步条目
    """
    CREATE TABLE IF NOT EXISTS sync_items (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        item_type       TEXT NOT NULL,
        item_id         TEXT NOT NULL,
        version         INTEGER DEFAULT 1,
        data_hash       TEXT,
        operation       TEXT,
        status          TEXT,
        created_at      REAL,
        updated_at      REAL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sync_items_type_id ON sync_items(item_type, item_id)",
    "CREATE INDEX IF NOT EXISTS idx_sync_items_status ON sync_items(status)",

    # sessions: 会话状态
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id      TEXT PRIMARY KEY,
        agent_id        TEXT,
        data            TEXT,
        expires_at      REAL,
        created_at      REAL,
        updated_at      REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)",

    # audit_trail: 审计记录
    """
    CREATE TABLE IF NOT EXISTS audit_trail (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id        TEXT,
        action          TEXT NOT NULL,
        resource        TEXT,
        detail          TEXT,
        ip_address      TEXT,
        created_at      REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_agent_id ON audit_trail(agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_trail(created_at)",

    # config_kv: 配置键值
    """
    CREATE TABLE IF NOT EXISTS config_kv (
        key             TEXT PRIMARY KEY,
        value           TEXT,
        updated_at      REAL
    )
    """,

    # cache_items: 通用缓存
    """
    CREATE TABLE IF NOT EXISTS cache_items (
        cache_key       TEXT PRIMARY KEY,
        value           TEXT,
        expires_at      REAL,
        created_at      REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cache_expires_at ON cache_items(expires_at)",
]


# ---------------------------------------------------------------------------
# 迁移列表
# ---------------------------------------------------------------------------

MIGRATIONS = [
    Migration(
        version=1,
        name="initial_schema",
        up_sql=V1_UP_SQL,
    ),
]


def create_migrator(db_path: str) -> DatabaseMigrator:
    """创建 M3 主数据库迁移器（预注册所有迁移）.

    Args:
        db_path: 数据库文件路径.

    Returns:
        预注册迁移的 DatabaseMigrator 实例.
    """
    return DatabaseMigrator(db_path=db_path, migrations=list(MIGRATIONS))
