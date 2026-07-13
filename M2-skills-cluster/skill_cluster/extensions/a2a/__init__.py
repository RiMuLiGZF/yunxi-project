"""M2 技能集群 - A2A 扩展.

Agent-to-Agent 通信协议与消息总线。
"""

from __future__ import annotations

from skill_cluster.extensions.a2a.bus import A2ABus
# 数据模型在 models.a2a 中
from skill_cluster.models.a2a import (
    A2AAgentCard,
    A2AArtifact,
    A2AMessage,
    A2APart,
    A2ATask,
)

__all__ = [
    "A2ABus",
    "A2AAgentCard",
    "A2AArtifact",
    "A2AMessage",
    "A2APart",
    "A2ATask",
]
