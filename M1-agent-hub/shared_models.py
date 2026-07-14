"""
云汐内核 V10.0 — 子Agent核心数据模型与共享类型（兼容层）

此文件现已重定向至 models/ 子包，所有符号从 models 重新导出。
原有 `from shared_models import XXX` 语句无需修改，继续正常工作。

拆分结构：
  - models/enums.py        — 枚举类与映射常量
  - models/task.py          — 任务相关模型（DAG）
  - models/agent.py         — Agent 身份与分身模型
  - models/team.py          — 组队与仲裁模型
  - models/federation.py    — 联邦调度核心模型
"""

from __future__ import annotations

from models import *  # noqa: F401, F403