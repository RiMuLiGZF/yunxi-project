"""
云汐内核 — 临时分身池管理模块

提供临时分身的完整生命周期管理：
  - CloneFactory：按需创建四种分身（勘探/规划/撰写/审查），实现最小信息下发
  - ClonePool：管理所有分身的获取、释放、配额控制与过期清理
  - CloneAgentAdapter：将分身适配为 IAgentPlugin 接口，支持审计日志与最小权限
"""

from src.pool.clone_pool import ClonePool
from shared_models import CloneIdentity

__all__ = [
    "ClonePool",
    "CloneIdentity",
]
