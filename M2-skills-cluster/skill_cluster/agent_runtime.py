from __future__ import annotations
"""[DEPRECATED] 已迁移至 skill_cluster.agent.runtime.

本文件为向后兼容存根，将从新路径导入并发出废弃警告。
请更新为: from skill_cluster.agent.runtime import ...
"""

import warnings

warnings.warn(
    "skill_cluster.agent_runtime 已废弃，请使用 skill_cluster.agent.runtime",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.agent.runtime import (  # noqa: F401
    AgentRegistry,
    AgentRuntime,
    AgentState,
)
