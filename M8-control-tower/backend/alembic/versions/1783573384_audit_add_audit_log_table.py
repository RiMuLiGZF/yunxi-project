"""add_audit_log_table_and_user_fields

Revision ID: 1783573384_audit
Revises: 001_initial_baseline
Create Date: 2026-07-09 13:03:04

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "1783573384_audit"
down_revision = "001_initial_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级：添加审计日志表，扩展用户表字段"""
    # 1. 扩展 users 表
    op.add_column("users", sa.Column("nickname", sa.String(100), nullable=False, server_default=""))
    op.add_column("users", sa.Column("email", sa.String(255), nullable=False, server_default=""))
    op.add_column("users", sa.Column("status", sa.String(20), nullable=False, server_default="active"))
    op.create_index(op.f("ix_users_status"), "users", ["status"])

    # 2. 创建审计日志表
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("user_id", sa.Integer, index=True, nullable=True),
        sa.Column("username", sa.String(50), index=True, default=""),
        sa.Column("action", sa.String(50), index=True, default=""),
        sa.Column("module", sa.String(30), index=True, default="system"),
        sa.Column("result", sa.String(20), index=True, default="success"),
        sa.Column("ip", sa.String(50), default=""),
        sa.Column("user_agent", sa.String(500), default=""),
        sa.Column("details", sa.JSON, default=dict),
        sa.Column("created_at", sa.DateTime, index=True),
        sa.Column("user_id_meta", sa.Integer, default=1, index=True),
    )


def downgrade() -> None:
    """降级"""
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_users_status"), table_name="users")
    op.drop_column("users", "status")
    op.drop_column("users", "email")
    op.drop_column("users", "nickname")
