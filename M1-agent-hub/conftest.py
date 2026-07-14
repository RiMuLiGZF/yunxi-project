"""
Pytest 根级 conftest。

背景：
- 本模块原始包名为 ``agent_cluster``（见 README「M1 多Agent集群调度 (Agent Cluster)」）。
- 当前工程目录已更名为 ``M1-agent-hub``（含连字符，不是合法的 Python 包名），
  且源码模块（task_dispatcher.py、message_bus.py、agent_card.py 等）直接平铺在
  本目录下，不再存在名为 ``agent_cluster`` 的子目录。
- tests/ 下仍有 13 个测试文件使用 ``from agent_cluster.xxx import ...`` 旧包名导入。

修复策略（对应「包名仍为 agent_cluster，仅目录名变更」场景）：
1. 将本目录加入 sys.path，保证 ``from interfaces import ...`` 等裸导入可用；
2. 在 sys.modules 中注册 ``agent_cluster`` 为指向本目录的命名空间包，
   使 ``from agent_cluster.xxx import ...`` 能解析到本目录下的同名模块。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

# 本目录（M1-agent-hub 根目录），即原 agent_cluster 包的实际位置
ROOT_DIR = Path(__file__).resolve().parent
ROOT_STR = str(ROOT_DIR)

# 1) 保证本目录在 sys.path 中，便于裸导入（from interfaces import ... 等）
if ROOT_STR not in sys.path:
    sys.path.insert(0, ROOT_STR)

# 2) 将 agent_cluster 注册为指向本目录的命名空间包，
#    使 `from agent_cluster.<module> import ...` 解析到本目录下的 <module>.py
if "agent_cluster" not in sys.modules:
    _pkg = types.ModuleType("agent_cluster")
    _pkg.__path__ = [ROOT_STR]  # type: ignore[attr-defined]
    _pkg.__package__ = "agent_cluster"
    sys.modules["agent_cluster"] = _pkg
