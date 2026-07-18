"""add_config_center_tables

新增配置中心 4 张核心表：
- config_items      配置项（当前值）
- config_versions   配置版本历史
- config_audit_logs 配置变更审计日志
- config_schemas    配置 Schema 定义

Revision ID: 004_config_center
Revises: 1783573384_audit
Create Date: 2026-07-18 10:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "004_config_center"
down_revision = "1783573384_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级：创建配置中心 4 张表"""

    # 1. 配置项表
    op.create_table(
        "config_items",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("config_key", sa.String(255), nullable=False, index=True),
        sa.Column("config_value", sa.JSON, nullable=True),
        sa.Column("config_type", sa.String(20), nullable=False, default="string"),
        sa.Column("scope", sa.String(20), nullable=False, default="global", index=True),
        sa.Column("module_name", sa.String(50), nullable=True, index=True),
        sa.Column("env_name", sa.String(30), nullable=True, index=True),
        sa.Column("instance_id", sa.String(100), nullable=True, index=True),
        sa.Column("description", sa.String(500), nullable=True, default=""),
        sa.Column("is_secret", sa.Boolean, nullable=False, default=False, index=True),
        sa.Column("version", sa.Integer, nullable=False, default=1),
        sa.Column("is_canary", sa.Boolean, nullable=False, default=False, index=True),
        sa.Column("canary_percent", sa.Integer, nullable=True),
        sa.Column("canary_instances", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime, nullable=False, index=True),
        sa.Column("updated_by", sa.String(100), nullable=True, default="system"),
        sa.UniqueConstraint(
            "config_key", "scope", "module_name", "env_name", "instance_id",
            name="uq_config_key_scope",
        ),
    )
    op.create_index("ix_config_scope_module", "config_items", ["scope", "module_name"])
    op.create_index("ix_config_scope_env", "config_items", ["scope", "env_name"])
    op.create_index("ix_config_scope_instance", "config_items", ["scope", "instance_id"])

    # 2. 配置版本历史表
    op.create_table(
        "config_versions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("config_key", sa.String(255), nullable=False, index=True),
        sa.Column("scope", sa.String(20), nullable=False, index=True),
        sa.Column("module_name", sa.String(50), nullable=True, index=True),
        sa.Column("env_name", sa.String(30), nullable=True, index=True),
        sa.Column("instance_id", sa.String(100), nullable=True, index=True),
        sa.Column("version", sa.Integer, nullable=False, default=1, index=True),
        sa.Column("config_value", sa.JSON, nullable=True),
        sa.Column("config_type", sa.String(20), nullable=False, default="string"),
        sa.Column("description", sa.String(500), nullable=True, default=""),
        sa.Column("is_secret", sa.Boolean, nullable=False, default=False),
        sa.Column("change_reason", sa.String(500), nullable=True, default=""),
        sa.Column("changed_by", sa.String(100), nullable=True, default="system"),
        sa.Column("changed_at", sa.DateTime, nullable=False, index=True),
        sa.Column("is_canary", sa.Boolean, nullable=False, default=False),
        sa.Column("canary_percent", sa.Integer, nullable=True),
        sa.Column("canary_instances", sa.JSON, nullable=True),
        sa.UniqueConstraint(
            "config_key", "scope", "module_name", "env_name", "instance_id", "version",
            name="uq_config_version",
        ),
    )
    op.create_index("ix_config_version_key_scope", "config_versions", ["config_key", "scope"])

    # 3. 配置审计日志表
    op.create_table(
        "config_audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(30), nullable=False, index=True),
        sa.Column("config_key", sa.String(255), nullable=False, index=True),
        sa.Column("scope", sa.String(20), nullable=False, index=True),
        sa.Column("module_name", sa.String(50), nullable=True, index=True),
        sa.Column("env_name", sa.String(30), nullable=True, index=True),
        sa.Column("instance_id", sa.String(100), nullable=True, index=True),
        sa.Column("old_value", sa.JSON, nullable=True),
        sa.Column("new_value", sa.JSON, nullable=True),
        sa.Column("old_version", sa.Integer, nullable=True),
        sa.Column("new_version", sa.Integer, nullable=True),
        sa.Column("operator", sa.String(100), nullable=True, default="system", index=True),
        sa.Column("operator_ip", sa.String(50), nullable=True, default=""),
        sa.Column("operator_role", sa.String(50), nullable=True, default=""),
        sa.Column("reason", sa.String(500), nullable=True, default=""),
        sa.Column("created_at", sa.DateTime, nullable=False, index=True),
        sa.Column("extra", sa.JSON, nullable=True),
    )
    op.create_index("ix_config_audit_action", "config_audit_logs", ["action"])
    op.create_index("ix_config_audit_key_scope", "config_audit_logs", ["config_key", "scope"])
    op.create_index("ix_config_audit_operator", "config_audit_logs", ["operator"])
    op.create_index("ix_config_audit_created_at", "config_audit_logs", ["created_at"])

    # 4. 配置 Schema 表
    op.create_table(
        "config_schemas",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("schema_name", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("module_name", sa.String(50), nullable=True, index=True),
        sa.Column("description", sa.String(500), nullable=True, default=""),
        sa.Column("schema_json", sa.JSON, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True, index=True),
        sa.Column("version", sa.Integer, nullable=False, default=1),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("created_by", sa.String(100), nullable=True, default="system"),
    )
    op.create_index("ix_config_schema_module", "config_schemas", ["module_name"])


def downgrade() -> None:
    """降级：删除配置中心 4 张表"""
    op.drop_table("config_schemas")
    op.drop_table("config_audit_logs")
    op.drop_table("config_versions")
    op.drop_table("config_items")
