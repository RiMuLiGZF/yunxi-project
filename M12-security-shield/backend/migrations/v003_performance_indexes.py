"""
迁移脚本 v003 - performance_indexes

为 M12 安全盾模块添加性能优化索引。

包含：
- security_events：target_path、method、rule_name、各复合索引
- api_keys：expires_at、last_used_at、owner+is_active 复合索引
- waf_rules：is_active、hit_count、updated_at、category+is_active 复合索引
- rate_limit_rules：path_pattern+method+is_active 复合索引
- ip_blacklist：banned_at、is_active+expires_at 复合索引

注意：所有索引使用 CREATE INDEX IF NOT EXISTS，保证幂等。
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "performance_indexes"
__description__ = "M12 性能优化索引：补充安全事件、API密钥、WAF规则等表的常用查询索引"


def up(conn):
    """
    升级迁移 - 添加性能优化索引

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # security_events 新增索引
    # ============================================================

    # 目标路径索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_se_target_path
        ON security_events (target_path)
    """))

    # 请求方法索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_se_method
        ON security_events (method)
    """))

    # 规则名索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_se_rule_name
        ON security_events (rule_name)
    """))

    # 事件类型+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_se_type_time
        ON security_events (event_type, created_at)
    """))

    # 来源IP+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_se_ip_time
        ON security_events (source_ip, created_at)
    """))

    # 状态+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_se_status_time
        ON security_events (status, created_at)
    """))

    # 严重级别+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_se_severity_time
        ON security_events (severity, created_at)
    """))

    # ============================================================
    # api_keys 新增索引
    # ============================================================

    # 过期时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ak_expires_at
        ON api_keys (expires_at)
    """))

    # 最后使用时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ak_last_used
        ON api_keys (last_used_at)
    """))

    # 创建时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ak_created_at
        ON api_keys (created_at)
    """))

    # 所有者+激活状态复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ak_owner_active
        ON api_keys (owner, is_active)
    """))

    # 调用次数索引（排序用）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ak_call_count
        ON api_keys (call_count)
    """))

    # ============================================================
    # ip_blacklist 新增索引
    # ============================================================

    # 封禁时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ib_banned_at
        ON ip_blacklist (banned_at)
    """))

    # 来源索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ib_source
        ON ip_blacklist (source)
    """))

    # 激活+过期复合索引（查询有效封禁）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ib_active_expires
        ON ip_blacklist (is_active, expires_at)
    """))

    # 命中次数索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ib_hit_count
        ON ip_blacklist (hit_count)
    """))

    # ============================================================
    # waf_rules 新增索引
    # ============================================================

    # 激活状态索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wr_active
        ON waf_rules (is_active)
    """))

    # 分类+激活复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wr_category_active
        ON waf_rules (category, is_active)
    """))

    # 命中次数索引（排序用）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wr_hit_count
        ON waf_rules (hit_count)
    """))

    # 最后命中时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wr_last_hit
        ON waf_rules (last_hit_at)
    """))

    # 更新时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_wr_updated_at
        ON waf_rules (updated_at)
    """))

    # ============================================================
    # token_blacklist 新增索引
    # ============================================================

    # 创建时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_tb_created_at
        ON token_blacklist (created_at)
    """))

    # ============================================================
    # rate_limit_rules 新增索引
    # ============================================================

    # 激活+优先级复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_rlr_active_priority
        ON rate_limit_rules (is_active, priority)
    """))

    # 路径+方法+激活复合索引（限流查询优化）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_rlr_path_method_active
        ON rate_limit_rules (path_pattern, method, is_active)
    """))

    # 创建时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_rlr_created_at
        ON rate_limit_rules (created_at)
    """))

    # 更新时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_rlr_updated_at
        ON rate_limit_rules (updated_at)
    """))

    # ============================================================
    # audit_logs 新增索引
    # ============================================================

    # 模块+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_al_module_time
        ON audit_logs (module, created_at)
    """))

    # 用户+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_al_user_time
        ON audit_logs (user_id, created_at)
    """))

    # 状态+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_al_status_time
        ON audit_logs (status, created_at)
    """))

    # 持续时间索引（慢操作分析）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_al_duration
        ON audit_logs (duration_ms)
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
        # audit_logs
        "idx_al_duration",
        "idx_al_status_time",
        "idx_al_user_time",
        "idx_al_module_time",
        # rate_limit_rules
        "idx_rlr_updated_at",
        "idx_rlr_created_at",
        "idx_rlr_path_method_active",
        "idx_rlr_active_priority",
        # token_blacklist
        "idx_tb_created_at",
        # waf_rules
        "idx_wr_updated_at",
        "idx_wr_last_hit",
        "idx_wr_hit_count",
        "idx_wr_category_active",
        "idx_wr_active",
        # ip_blacklist
        "idx_ib_hit_count",
        "idx_ib_active_expires",
        "idx_ib_source",
        "idx_ib_banned_at",
        # api_keys
        "idx_ak_call_count",
        "idx_ak_owner_active",
        "idx_ak_created_at",
        "idx_ak_last_used",
        "idx_ak_expires_at",
        # security_events
        "idx_se_severity_time",
        "idx_se_status_time",
        "idx_se_ip_time",
        "idx_se_type_time",
        "idx_se_rule_name",
        "idx_se_method",
        "idx_se_target_path",
    ]

    for idx_name in indexes_to_drop:
        conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
