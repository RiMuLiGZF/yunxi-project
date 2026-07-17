"""分布式基础设施模块

提供轻量级的分布式节点管理能力，无需依赖 Consul / etcd 等外部服务。

导出:
    NodeConfig   — 节点配置（环境变量加载）
    NodeInfo     — 节点信息数据结构
    NodeRegistry — 节点注册中心（主节点运行）
    NodeClient   — 节点客户端（边缘节点使用）
    MessageBus   — 跨节点消息总线
"""

from .node_config import NodeConfig
from .node_registry import NodeRegistry, NodeInfo, NodeClient
from .cluster_bus import MessageBus

__all__ = [
    "NodeConfig",
    "NodeInfo",
    "NodeRegistry",
    "NodeClient",
    "MessageBus",
]
