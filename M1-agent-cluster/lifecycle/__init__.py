"""
云汐内核 V10.0 — 生命周期管理子Agent模块

提供 Agent 实例池与 Lifecycle-Agent，管理 Agent 实例的完整生命周期：
  CREATED -> ACTIVATING -> ACTIVE -> SUSPENDED -> DRAINING -> TERMINATED -> ARCHIVED
"""

from lifecycle.agent import LifecycleAgent
from lifecycle.instance_pool import AgentInstance, AgentInstancePool

__all__ = [
    "LifecycleAgent",
    "AgentInstance",
    "AgentInstancePool",
]
