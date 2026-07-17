"""
云汐内核 V10.0 — 状态快照与断点续跑子Agent模块

导出：
- SnapshotAgent：快照管理子Agent（继承 IAgentPlugin）
- SnapshotChain：快照链便捷操作类
- SnapshotEntry：快照条目数据结构
- SnapshotStore：快照存储核心类
"""

from src.snapshot.agent import SnapshotAgent
from src.snapshot.snapshot_store import SnapshotChain, SnapshotEntry, SnapshotStore

__all__ = [
    "SnapshotAgent",
    "SnapshotChain",
    "SnapshotEntry",
    "SnapshotStore",
]
