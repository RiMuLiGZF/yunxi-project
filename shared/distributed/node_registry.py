"""轻量级节点注册与发现 — 不依赖外部服务（Consul / etcd）"""

import httpx
import time
import threading
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("shared.distributed.registry")

# 节点心跳超时（秒）— 超过此时间未收到心跳视为离线
HEARTBEAT_TIMEOUT = 60


@dataclass
class NodeInfo:
    """节点信息"""

    node_id: str
    node_role: str  # primary / edge
    node_name: str
    host: str
    port: int
    modules: list = field(default_factory=list)
    last_heartbeat: float = 0.0
    status: str = "unknown"  # healthy / degraded / offline

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NodeInfo":
        return cls(
            node_id=data["node_id"],
            node_role=data.get("node_role", "edge"),
            node_name=data.get("node_name", ""),
            host=data.get("host", ""),
            port=data.get("port", 8080),
            modules=data.get("modules", []),
            last_heartbeat=data.get("last_heartbeat", 0.0),
            status=data.get("status", "unknown"),
        )


class NodeRegistry:
    """节点注册中心 — 主节点运行

    维护所有已注册节点的状态信息，提供注册、注销、心跳上报和查询功能。
    内部使用线程锁保证并发安全。
    """

    def __init__(self):
        self._nodes: dict[str, NodeInfo] = {}
        self._lock = threading.Lock()

    def register(self, node: NodeInfo) -> None:
        """注册新节点或更新已有节点信息"""
        with self._lock:
            node.last_heartbeat = time.time()
            node.status = "healthy"
            self._nodes[node.node_id] = node
            logger.info(
                f"节点注册: {node.node_id} ({node.node_name}) "
                f"@ {node.host}:{node.port}, 模块={node.modules}"
            )

    def deregister(self, node_id: str) -> None:
        """注销节点"""
        with self._lock:
            removed = self._nodes.pop(node_id, None)
            if removed:
                logger.info(f"节点注销: {node_id} ({removed.node_name})")

    def heartbeat(self, node_id: str, **kwargs) -> bool:
        """处理节点心跳

        Args:
            node_id: 节点 ID
            **kwargs: 可选更新字段（modules, status 等）

        Returns:
            True 表示心跳成功更新，False 表示节点未注册
        """
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                logger.warning(f"心跳来自未注册节点: {node_id}")
                return False

            node.last_heartbeat = time.time()
            node.status = kwargs.get("status", "healthy")

            if "modules" in kwargs:
                node.modules = kwargs["modules"]
            if "host" in kwargs:
                node.host = kwargs["host"]
            if "port" in kwargs:
                node.port = kwargs["port"]

            logger.debug(f"心跳更新: {node_id}")
            return True

    def get_healthy_nodes(self) -> list[NodeInfo]:
        """获取所有健康的节点（排除超时节点）"""
        now = time.time()
        healthy = []
        with self._lock:
            for node in self._nodes.values():
                if now - node.last_heartbeat <= HEARTBEAT_TIMEOUT:
                    node.status = "healthy"
                    healthy.append(node)
                else:
                    node.status = "offline"
                    logger.warning(
                        f"节点超时离线: {node.node_id} ({node.node_name}), "
                        f"最后心跳: {now - node.last_heartbeat:.1f}s 前"
                    )
        return healthy

    def get_node(self, node_id: str) -> Optional[NodeInfo]:
        """获取单个节点信息"""
        with self._lock:
            return self._nodes.get(node_id)

    def get_nodes_by_module(self, module: str) -> list[NodeInfo]:
        """获取运行指定模块的所有节点"""
        with self._lock:
            return [
                node
                for node in self._nodes.values()
                if module in node.modules
                and time.time() - node.last_heartbeat <= HEARTBEAT_TIMEOUT
            ]

    def get_all_nodes(self) -> list[NodeInfo]:
        """获取所有已注册节点（包含离线节点）"""
        with self._lock:
            return list(self._nodes.values())

    def get_cluster_summary(self) -> dict:
        """获取集群摘要信息"""
        now = time.time()
        with self._lock:
            total = len(self._nodes)
            healthy = sum(
                1
                for n in self._nodes.values()
                if now - n.last_heartbeat <= HEARTBEAT_TIMEOUT
            )
            offline = total - healthy
            primary_count = sum(
                1 for n in self._nodes.values() if n.node_role == "primary"
            )
            edge_count = total - primary_count
            all_modules = set()
            for n in self._nodes.values():
                all_modules.update(n.modules)

        return {
            "total_nodes": total,
            "healthy_nodes": healthy,
            "offline_nodes": offline,
            "primary_count": primary_count,
            "edge_count": edge_count,
            "modules": sorted(all_modules),
            "status": "healthy" if offline == 0 else ("degraded" if healthy > 0 else "offline"),
        }


class NodeClient:
    """节点客户端 — 边缘节点使用，向主节点注册并维持心跳

    自动完成注册、心跳维持和节点发现功能。
    """

    def __init__(
        self,
        primary_host: str,
        primary_port: int,
        node_info: NodeInfo,
    ):
        self._primary_host = primary_host
        self._primary_port = primary_port
        self._node_info = node_info
        self._base_url = f"http://{primary_host}:{primary_port}"
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def register(self) -> bool:
        """向主节点注册本节点"""
        try:
            payload = self._node_info.to_dict()
            resp = httpx.post(
                f"{self._base_url}/api/v1/cluster/nodes/register",
                json=payload,
                timeout=10.0,
            )
            resp.raise_for_status()
            logger.info(
                f"节点 {self._node_info.node_id} 注册成功 → 主节点 "
                f"{self._primary_host}:{self._primary_port}"
            )
            return True
        except Exception as e:
            logger.error(f"节点注册失败: {e}")
            return False

    def heartbeat_loop(self, interval: int = 15) -> None:
        """启动心跳循环（阻塞方法，通常在后台线程中运行）

        Args:
            interval: 心跳间隔（秒），默认 15 秒
        """
        logger.info(
            f"心跳循环启动, 间隔={interval}s, "
            f"目标={self._base_url}"
        )
        while not self._stop_event.wait(timeout=interval):
            try:
                resp = httpx.post(
                    f"{self._base_url}/api/v1/cluster/nodes/{self._node_info.node_id}/heartbeat",
                    json={
                        "status": "healthy",
                        "modules": self._node_info.modules,
                    },
                    timeout=5.0,
                )
                resp.raise_for_status()
                logger.debug(
                    f"心跳发送成功: {self._node_info.node_id}"
                )
            except Exception as e:
                logger.warning(f"心跳发送失败: {e}")

    def start_heartbeat_thread(self, interval: int = 15) -> None:
        """在后台线程中启动心跳循环"""
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self.heartbeat_loop,
            args=(interval,),
            daemon=True,
            name=f"heartbeat-{self._node_info.node_id}",
        )
        self._heartbeat_thread.start()

    def stop_heartbeat_thread(self) -> None:
        """停止心跳循环"""
        self._stop_event.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5.0)
        logger.info(f"心跳循环已停止: {self._node_info.node_id}")

    def discover_nodes(self) -> list[NodeInfo]:
        """从主节点发现所有已注册节点"""
        try:
            resp = httpx.get(
                f"{self._base_url}/api/v1/cluster/nodes",
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {}).get("nodes", [])
            return [NodeInfo.from_dict(item) for item in data]
        except Exception as e:
            logger.error(f"节点发现失败: {e}")
            return []
