"""
迁移脚本 v002 - rate_limit_rules

新增速率限制规则表 rate_limit_rules，用于精细化的 API 限流配置。
同时为 api_keys 表增加自定义限流配置字段。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 迁移元数据
__migration_name__ = "rate_limit_rules"
__description__ = "新增速率限制规则表 rate_limit_rules，扩展限流配置能力"


def up(conn):
    """
    升级迁移 - 新增速率限制规则表

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # 1. rate_limit_rules - 速率限制规则表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS rate_limit_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_name VARCHAR(200) UNIQUE NOT NULL,
            path_pattern VARCHAR(500) DEFAULT '',
            method VARCHAR(10) DEFAULT '',
            limit_per_minute INTEGER DEFAULT 60,
            limit_per_hour INTEGER DEFAULT 1000,
            limit_per_day INTEGER DEFAULT 10000,
            scope VARCHAR(50) DEFAULT 'ip',
            burst_size INTEGER DEFAULT 10,
            is_active BOOLEAN DEFAULT 1,
            priority INTEGER DEFAULT 0,
            description TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_rlr_path_pattern ON rate_limit_rules (path_pattern)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_rlr_active ON rate_limit_rules (is_active)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_rlr_scope ON rate_limit_rules (scope)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_rlr_priority ON rate_limit_rules (priority)
    """))

    # ============================================================
    # 2. 为 api_keys 增加自定义限流配置字段
    # ============================================================
    try:
        conn.execute(text("""
            ALTER TABLE api_keys ADD COLUMN custom_rate_limit_json TEXT DEFAULT '{}'
        """))
    except Exception as e:
        # 列已存在，跳过
        logger.debug("列 custom_rate_limit_json 已存在，跳过: %s", e)

    try:
        conn.execute(text("""
            ALTER TABLE api_keys ADD COLUMN rate_limit_override BOOLEAN DEFAULT 0
        """))
    except Exception as e:
        # 列已存在，跳过
        logger.debug("列 rate_limit_override 已存在，跳过: %s", e)

    # ============================================================
    # 3. 插入默认限流规则
    # ============================================================
    default_rules = [
        ("global_default", "", "", 60, 1000, 10000, "ip", 20, 1, 0,
         "全局默认限流规则"),
        ("auth_endpoints", "/auth/*", "POST", 10, 100, 500, "ip", 5, 1, 100,
         "认证接口限流，防止暴力破解"),
        ("api_general", "/api/*", "", 120, 2000, 20000, "api_key", 30, 1, 50,
         "API 通用限流"),
    ]

    for rule in default_rules:
        conn.execute(text("""
            INSERT OR IGNORE INTO rate_limit_rules
            (rule_name, path_pattern, method, limit_per_minute, limit_per_hour,
             limit_per_day, scope, burst_size, is_active, priority, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), rule)


def down(conn):
    """
    降级迁移（回滚） - 删除速率限制规则表

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # 删除新增的表
    conn.execute(text("DROP TABLE IF EXISTS rate_limit_rules"))

    # 注意：SQLite 不支持 DROP COLUMN，回滚时新增字段保留
    # 实际回滚建议通过备份恢复
