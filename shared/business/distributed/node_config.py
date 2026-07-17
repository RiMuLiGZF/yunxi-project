"""分布式节点配置"""

import os
from dataclasses import dataclass, field, asdict
from typing import Optional
import json
import uuid
import socket


@dataclass
class NodeConfig:
    """节点配置

    Attributes:
        node_id:        节点唯一标识
        node_role:      节点角色 — primary（主节点）/ edge（边缘节点）
        node_name:      节点显示名称
        cluster_id:     所属集群 ID
        bind_host:      对外绑定地址
        advertise_host: 对外广播地址（空则自动检测）
        api_port:       节点管理 API 端口
        peer_nodes:     已知对等节点 [{"id": "x", "host": "x", "port": 8080}]
        modules:        本节点运行的模块 ["M0","M1","M4"...]
    """

    node_id: str = ""
    node_role: str = "primary"  # primary / edge
    node_name: str = "云汐主节点"
    cluster_id: str = "yunxi-default"
    bind_host: str = "0.0.0.0"  # 对外绑定地址
    advertise_host: str = ""  # 对外广播地址（空则自动检测）
    api_port: int = 8080  # 节点管理 API 端口
    peer_nodes: list = field(default_factory=list)  # 已知对等节点
    modules: list = field(default_factory=list)  # 本节点运行的模块

    @classmethod
    def from_env(cls) -> "NodeConfig":
        """从环境变量加载配置"""
        return cls(
            node_id=os.getenv("YUNXI_NODE_ID", str(uuid.uuid4())[:8]),
            node_role=os.getenv("YUNXI_NODE_ROLE", "primary"),
            node_name=os.getenv("YUNXI_NODE_NAME", "云汐主节点"),
            cluster_id=os.getenv("YUNXI_CLUSTER_ID", "yunxi-default"),
            bind_host=os.getenv("YUNXI_BIND_HOST", "0.0.0.0"),
            advertise_host=os.getenv("YUNXI_ADVERTISE_HOST", ""),
            api_port=int(os.getenv("YUNXI_NODE_API_PORT", "8080")),
            peer_nodes=json.loads(os.getenv("YUNXI_PEER_NODES", "[]")),
            modules=json.loads(os.getenv("YUNXI_NODE_MODULES", "[]")),
        )

    def get_advertise_host(self) -> str:
        """获取对外广播地址，如果未配置则自动检测"""
        if self.advertise_host:
            return self.advertise_host
        try:
            # 尝试通过 UDP 连接获取本机对外 IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            host = s.getsockname()[0]
            s.close()
            return host
        except Exception:
            return "127.0.0.1"

    def save_to_env_file(self, path: str):
        """保存到 .env 文件"""
        lines = [
            f"YUNXI_NODE_ID={self.node_id}",
            f"YUNXI_NODE_ROLE={self.node_role}",
            f"YUNXI_NODE_NAME={self.node_name}",
            f"YUNXI_CLUSTER_ID={self.cluster_id}",
            f"YUNXI_BIND_HOST={self.bind_host}",
            f"YUNXI_ADVERTISE_HOST={self.advertise_host}",
            f"YUNXI_NODE_API_PORT={self.api_port}",
            f'YUNXI_PEER_NODES={json.dumps(self.peer_nodes, ensure_ascii=False)}',
            f'YUNXI_NODE_MODULES={json.dumps(self.modules, ensure_ascii=False)}',
        ]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def to_dict(self) -> dict:
        """转换为字典"""
        return asdict(self)

    def __repr__(self) -> str:
        return (
            f"NodeConfig(id={self.node_id!r}, role={self.node_role!r}, "
            f"name={self.node_name!r}, host={self.get_advertise_host()}, "
            f"port={self.api_port}, modules={self.modules})"
        )
