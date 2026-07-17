"""
Pytest 根级 conftest（v11.2 重构版 - src/ 结构）。

背景：
- 本模块原始包名为 ``agent_cluster``。
- 当前工程目录名为 ``M1-agent-hub``（含连字符，非合法 Python 包名）。
- 核心代码已迁移至 src/ 子目录，遵循标准包结构。
- 根目录保留入口点、配置文件与文档。

修复策略：
1. 将 src/ 加入 sys.path，使 ``from core.xxx import ...`` 等导入可用；
2. 在 sys.modules 中注册 ``agent_cluster`` 为指向 src/ 的命名空间包，
   使 ``from agent_cluster.xxx import ...`` 能解析到 src/ 下的模块；
3. 根目录也加入 sys.path，便于入口点导入。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

# 根目录（M1-agent-hub/）
ROOT_DIR = Path(__file__).resolve().parent
ROOT_STR = str(ROOT_DIR)

# src/ 目录（核心代码位置）
SRC_DIR = ROOT_DIR / "src"
SRC_STR = str(SRC_DIR)

# 1) 将 src/ 加入 sys.path（主代码路径）
#    这样 ``from core.task_dispatcher import TaskDispatcher`` 可以直接工作
if SRC_STR not in sys.path:
    sys.path.insert(0, SRC_STR)

# 2) 将根目录加入 sys.path（入口点和顶层配置）
if ROOT_STR not in sys.path:
    sys.path.insert(0, ROOT_STR)

# 3) 注册 agent_cluster 命名空间包（指向 src/）
#    这样 ``from agent_cluster.core.task_dispatcher import TaskDispatcher`` 也能工作
if "agent_cluster" not in sys.modules:
    _pkg = types.ModuleType("agent_cluster")
    _pkg.__path__ = [SRC_STR]  # type: ignore[attr-defined]
    _pkg.__package__ = "agent_cluster"
    # 注入版本号
    try:
        from src import __version__
        _pkg.__version__ = __version__
    except ImportError:
        _pkg.__version__ = "11.2.0"
    sys.modules["agent_cluster"] = _pkg
