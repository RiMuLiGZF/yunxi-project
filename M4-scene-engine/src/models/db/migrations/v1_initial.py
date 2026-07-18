"""v1 初始迁移 - 创建所有数据库表.

版本 1: initial_schema
使用 Base.metadata.create_all() 创建所有已注册模型的表。
"""

from __future__ import annotations

from typing import Any

from ..base import Base
from ..migration import Migration

# 导入所有模型以确保它们被注册到 Base.metadata
from ..scene import *  # noqa: F401, F403
from ..appearance import *  # noqa: F401, F403
from ..emotion import *  # noqa: F401, F403
from ..social import *  # noqa: F401, F403
from ..review import *  # noqa: F401, F403
from ..life import *  # noqa: F401, F403
from ..study import *  # noqa: F401, F403
from ..work import *  # noqa: F401, F403
from ..chat import *  # noqa: F401, F403
from ..voice import *  # noqa: F401, F403
from ..watch import *  # noqa: F401, F403


def up_func(conn: Any) -> None:
    """执行初始 schema 创建.

    使用 Base.metadata.create_all() 创建所有已注册模型的表。

    Args:
        conn: SQLAlchemy Connection 对象.
    """
    Base.metadata.create_all(bind=conn)


migration_v1 = Migration(
    version=1,
    name="initial_schema",
    up_func=up_func,
)
