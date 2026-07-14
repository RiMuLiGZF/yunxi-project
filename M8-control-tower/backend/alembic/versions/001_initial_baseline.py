"""初始基线迁移 - 创建所有 34 张表

Revision ID: 001_initial_baseline
Revises: 
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import sys
from pathlib import Path

# 将项目根目录加入 sys.path，以便作为包导入
project_dir = str(Path(__file__).parent.parent.parent.parent)
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from backend.models import Base  # noqa: E402


# revision identifiers, used by Alembic.
revision: str = '001_initial_baseline'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建所有 34 张初始表"""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """删除所有表"""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
