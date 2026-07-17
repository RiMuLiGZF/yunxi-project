"""
【兼容存根】shared_models 模块已迁移至 models/

新位置: src.models.* (原 shared_models.py 的内容已拆分到 models/ 目录)
本文件仅保留向后兼容的 re-export，避免破坏既有 import 路径。

请更新为:
  from models.task import ...
  from models.agent import ...
  from models.team import ...
  from models.federation import ...
  from models.enums import ...
"""

from __future__ import annotations

import warnings

warnings.warn(
    "shared_models 已迁移至 models/ 子目录，请使用 from models.xxx import ...",
    DeprecationWarning,
    stacklevel=2,
)

# 从 models 子包重新导出所有符号
from models.base import *  # noqa: F401,F403
from models.enums import *  # noqa: F401,F403
from models.task import *  # noqa: F401,F403
from models.agent import *  # noqa: F401,F403
from models.team import *  # noqa: F401,F403
from models.federation import *  # noqa: F401,F403
from models.message import *  # noqa: F401,F403
from models.common import *  # noqa: F401,F403
from models.config import *  # noqa: F401,F403
