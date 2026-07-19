"""
迁移脚本 v004 - market_indexes

为 M7 市场模块添加性能优化索引。

包含：
- market_templates：status、category、author、created_at 索引
- market_blocks：status、category、author、created_at 索引
- market_ratings：item_type、item_id 索引
- 复合索引：status+category、status+created_at

注意：所有索引使用 CREATE INDEX IF NOT EXISTS，保证幂等。
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "market_indexes"
__description__ = "M7 市场模块性能索引：模板表、积木表、评分表的查询优化索引"


def up(conn):
    """
    升级迁移 - 添加市场模块性能优化索引

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # market_templates 新增索引
    # ============================================================

    # 状态索引（列表过滤）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_templates_status
        ON market_templates (status)
    """))

    # 分类索引（分类过滤）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_templates_category
        ON market_templates (category)
    """))

    # 作者索引（作者过滤）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_templates_author
        ON market_templates (author)
    """))

    # 创建时间索引（时间排序）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_templates_created_at
        ON market_templates (created_at)
    """))

    # 状态+分类复合索引（列表页常用过滤）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_templates_status_category
        ON market_templates (status, category)
    """))

    # 状态+创建时间复合索引（列表页排序）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_templates_status_created
        ON market_templates (status, created_at)
    """))

    # ============================================================
    # market_blocks 新增索引
    # ============================================================

    # 状态索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_blocks_status
        ON market_blocks (status)
    """))

    # 分类索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_blocks_category
        ON market_blocks (category)
    """))

    # 作者索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_blocks_author
        ON market_blocks (author)
    """))

    # 创建时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_blocks_created_at
        ON market_blocks (created_at)
    """))

    # 状态+分类复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_blocks_status_category
        ON market_blocks (status, category)
    """))

    # 状态+创建时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_blocks_status_created
        ON market_blocks (status, created_at)
    """))

    # ============================================================
    # market_ratings 新增索引
    # ============================================================

    # 条目类型索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_ratings_item_type
        ON market_ratings (item_type)
    """))

    # 条目ID索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_ratings_item_id
        ON market_ratings (item_id)
    """))

    # 条目类型+条目ID复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_market_ratings_item_type_id
        ON market_ratings (item_type, item_id)
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
        # market_ratings
        "ix_market_ratings_item_type_id",
        "ix_market_ratings_item_id",
        "ix_market_ratings_item_type",
        # market_blocks
        "ix_market_blocks_status_created",
        "ix_market_blocks_status_category",
        "ix_market_blocks_created_at",
        "ix_market_blocks_author",
        "ix_market_blocks_category",
        "ix_market_blocks_status",
        # market_templates
        "ix_market_templates_status_created",
        "ix_market_templates_status_category",
        "ix_market_templates_created_at",
        "ix_market_templates_author",
        "ix_market_templates_category",
        "ix_market_templates_status",
    ]

    for idx_name in indexes_to_drop:
        conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
