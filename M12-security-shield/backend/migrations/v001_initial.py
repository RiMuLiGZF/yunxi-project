"""
迁移脚本 v001 - initial

M12 安全盾初始表结构创建。
包含 6 张核心表：
- security_events: 安全事件表
- api_keys: API 密钥表
- ip_blacklist: IP 黑名单表
- waf_rules: WAF 规则表
- token_blacklist: Token 黑名单表
- audit_logs: 审计日志表

注意：此迁移脚本使用 SQLAlchemy Connection 对象执行 SQL 语句，
与 SQLAlchemyMigrationAdapter 适配层配合使用。
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "initial"
__description__ = "M12 安全盾初始表结构：security_events, api_keys, ip_blacklist, waf_rules, token_blacklist, audit_logs"


def up(conn):
    """
    升级迁移 - 创建初始表结构

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # 1. security_events - 安全事件表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type VARCHAR(100) DEFAULT '',
            severity VARCHAR(20) DEFAULT 'info',
            source_ip VARCHAR(50) DEFAULT '',
            target_path VARCHAR(500) DEFAULT '',
            method VARCHAR(10) DEFAULT '',
            description TEXT DEFAULT '',
            rule_name VARCHAR(200) DEFAULT '',
            user_agent VARCHAR(500) DEFAULT '',
            status VARCHAR(20) DEFAULT 'active',
            resolved_by VARCHAR(100) DEFAULT '',
            resolved_at DATETIME,
            resolution_note TEXT DEFAULT '',
            extra_data TEXT DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_se_created_at ON security_events (created_at)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_se_type_severity
        ON security_events (event_type, severity)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_se_source_ip ON security_events (source_ip)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_se_status ON security_events (status)
    """))

    # ============================================================
    # 2. api_keys - API 密钥表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_name VARCHAR(200) DEFAULT '',
            key_hash VARCHAR(255) UNIQUE NOT NULL,
            key_prefix VARCHAR(50) DEFAULT '',
            owner VARCHAR(200) DEFAULT '',
            roles TEXT DEFAULT '[]',
            scopes TEXT DEFAULT '[]',
            rate_limit INTEGER DEFAULT 0,
            call_count INTEGER DEFAULT 0,
            last_used_at DATETIME,
            expires_at DATETIME,
            is_active BOOLEAN DEFAULT 1,
            created_by VARCHAR(100) DEFAULT 'system',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            description TEXT DEFAULT ''
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ak_active ON api_keys (is_active)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ak_key_prefix ON api_keys (key_prefix)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ak_owner ON api_keys (owner)
    """))

    # ============================================================
    # 3. ip_blacklist - IP 黑名单表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS ip_blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address VARCHAR(50) UNIQUE NOT NULL,
            ip_type VARCHAR(20) DEFAULT 'single',
            reason TEXT DEFAULT '',
            severity VARCHAR(20) DEFAULT 'medium',
            source VARCHAR(100) DEFAULT 'manual',
            banned_by VARCHAR(100) DEFAULT 'system',
            banned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME,
            is_active BOOLEAN DEFAULT 1,
            hit_count INTEGER DEFAULT 0,
            last_hit_at DATETIME,
            extra_data TEXT DEFAULT '{}'
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ib_active ON ip_blacklist (is_active)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ib_expires ON ip_blacklist (expires_at)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ib_severity ON ip_blacklist (severity)
    """))

    # ============================================================
    # 4. waf_rules - WAF 规则表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS waf_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_name VARCHAR(200) UNIQUE NOT NULL,
            rule_type VARCHAR(50) DEFAULT 'custom',
            category VARCHAR(50) DEFAULT '',
            pattern TEXT NOT NULL,
            match_target VARCHAR(50) DEFAULT 'query',
            severity VARCHAR(20) DEFAULT 'medium',
            action VARCHAR(20) DEFAULT 'block',
            description TEXT DEFAULT '',
            is_builtin BOOLEAN DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            hit_count INTEGER DEFAULT 0,
            last_hit_at DATETIME,
            created_by VARCHAR(100) DEFAULT 'system',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wr_type_active
        ON waf_rules (rule_type, is_active)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wr_severity ON waf_rules (severity)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wr_category ON waf_rules (category)
    """))

    # ============================================================
    # 5. token_blacklist - Token 黑名单表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS token_blacklist (
            token_jti VARCHAR(255) PRIMARY KEY,
            token_hash VARCHAR(255) NOT NULL,
            expired_at DATETIME NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_tb_expired_at ON token_blacklist (expired_at)
    """))

    # ============================================================
    # 6. audit_logs - 审计日志表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id VARCHAR(100) DEFAULT '',
            username VARCHAR(200) DEFAULT '',
            role VARCHAR(50) DEFAULT '',
            module VARCHAR(100) DEFAULT '',
            action VARCHAR(100) DEFAULT '',
            resource_type VARCHAR(100) DEFAULT '',
            resource_id VARCHAR(100) DEFAULT '',
            description TEXT DEFAULT '',
            source_ip VARCHAR(50) DEFAULT '',
            user_agent VARCHAR(500) DEFAULT '',
            request_method VARCHAR(10) DEFAULT '',
            request_path VARCHAR(500) DEFAULT '',
            request_params TEXT DEFAULT '{}',
            response_status INTEGER DEFAULT 0,
            response_data TEXT DEFAULT '{}',
            status VARCHAR(20) DEFAULT 'success',
            error_message TEXT DEFAULT '',
            duration_ms INTEGER DEFAULT 0,
            extra_data TEXT DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_al_created_at ON audit_logs (created_at)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_al_user_module
        ON audit_logs (user_id, module)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_al_action ON audit_logs (action)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_al_status ON audit_logs (status)
    """))


def down(conn):
    """
    降级迁移（回滚） - 删除初始表结构

    警告：此操作会删除所有数据！仅在回滚时使用。

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # 按创建逆序删除，避免外键约束问题
    tables = [
        "audit_logs",
        "token_blacklist",
        "waf_rules",
        "ip_blacklist",
        "api_keys",
        "security_events",
    ]

    for table in tables:
        conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
