"""performance_indexes

为 M8 控制塔添加性能优化索引。

包含：
- backup_modules：enabled、schedule_type、last_backup_at 等索引
- backup_history：status、backup_type、trigger_type、各复合索引
- audit_logs：user+module、module+created_at 等复合索引
- users：补充常用查询索引

Revision ID: 003_performance_indexes
Revises: 1783573384_audit
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "003_performance_indexes"
down_revision = "1783573384_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级：添加性能优化索引"""

    # ============================================================
    # backup_modules 新增索引
    # ============================================================

    # 启用状态索引
    op.create_index(
        "ix_backup_modules_enabled",
        "backup_modules",
        ["enabled"],
    )

    # 调度类型索引
    op.create_index(
        "ix_backup_modules_schedule_type",
        "backup_modules",
        ["schedule_type"],
    )

    # 上次备份时间索引
    op.create_index(
        "ix_backup_modules_last_backup_at",
        "backup_modules",
        ["last_backup_at"],
    )

    # 创建时间索引
    op.create_index(
        "ix_backup_modules_created_at",
        "backup_modules",
        ["created_at"],
    )

    # 更新时间索引
    op.create_index(
        "ix_backup_modules_updated_at",
        "backup_modules",
        ["updated_at"],
    )

    # ============================================================
    # backup_history 新增索引
    # ============================================================

    # 备份类型索引
    op.create_index(
        "ix_backup_history_backup_type",
        "backup_history",
        ["backup_type"],
    )

    # 触发方式索引
    op.create_index(
        "ix_backup_history_trigger_type",
        "backup_history",
        ["trigger_type"],
    )

    # 创建时间索引
    op.create_index(
        "ix_backup_history_created_at",
        "backup_history",
        ["created_at"],
    )

    # 模块+状态复合索引
    op.create_index(
        "ix_backup_history_module_status",
        "backup_history",
        ["module_id", "status"],
    )

    # 模块+时间复合索引
    op.create_index(
        "ix_backup_history_module_time",
        "backup_history",
        ["module_id", "created_at"],
    )

    # 耗时索引（慢备份分析）
    op.create_index(
        "ix_backup_history_duration",
        "backup_history",
        ["duration_seconds"],
    )

    # 大小索引
    op.create_index(
        "ix_backup_history_size",
        "backup_history",
        ["backup_size_bytes"],
    )

    # ============================================================
    # audit_logs 新增索引
    # ============================================================

    # 用户+模块复合索引
    op.create_index(
        "ix_audit_logs_user_module",
        "audit_logs",
        ["user_id", "module"],
    )

    # 模块+时间复合索引
    op.create_index(
        "ix_audit_logs_module_time",
        "audit_logs",
        ["module", "created_at"],
    )

    # 状态+时间复合索引
    op.create_index(
        "ix_audit_logs_status_time",
        "audit_logs",
        ["status", "created_at"],
    )

    # ============================================================
    # users 新增索引
    # ============================================================

    # 角色索引
    op.create_index(
        "ix_users_role",
        "users",
        ["role"],
    )

    # 最后登录时间索引
    try:
        op.create_index(
            "ix_users_last_login",
            "users",
            ["last_login_at"],
        )
    except Exception:
        # 列可能不存在，跳过
        pass


def downgrade() -> None:
    """降级：删除新增的索引"""

    # users
    try:
        op.drop_index("ix_users_last_login", table_name="users")
    except Exception:
        pass
    op.drop_index("ix_users_role", table_name="users")

    # audit_logs
    op.drop_index("ix_audit_logs_status_time", table_name="audit_logs")
    op.drop_index("ix_audit_logs_module_time", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_module", table_name="audit_logs")

    # backup_history
    op.drop_index("ix_backup_history_size", table_name="backup_history")
    op.drop_index("ix_backup_history_duration", table_name="backup_history")
    op.drop_index("ix_backup_history_module_time", table_name="backup_history")
    op.drop_index("ix_backup_history_module_status", table_name="backup_history")
    op.drop_index("ix_backup_history_created_at", table_name="backup_history")
    op.drop_index("ix_backup_history_trigger_type", table_name="backup_history")
    op.drop_index("ix_backup_history_backup_type", table_name="backup_history")

    # backup_modules
    op.drop_index("ix_backup_modules_updated_at", table_name="backup_modules")
    op.drop_index("ix_backup_modules_created_at", table_name="backup_modules")
    op.drop_index("ix_backup_modules_last_backup_at", table_name="backup_modules")
    op.drop_index("ix_backup_modules_schedule_type", table_name="backup_modules")
    op.drop_index("ix_backup_modules_enabled", table_name="backup_modules")
