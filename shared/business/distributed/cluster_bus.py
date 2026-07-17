"""跨节点消息总线 — 基于 HTTP 的轻量级实现

支持 Pub/Sub 模式的跨节点消息传递，用于节点间协调、事件通知和 RPC 调用。
"""

import httpx
import json
import logging
from typing import Callable, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("shared.distributed.bus")


class MessageType(str, Enum):
    """消息类型"""

    BROADCAST = "broadcast"  # 广播消息
    REQUEST = "request"  # 请求-响应（RPC）
    EVENT = "event"  # 事件通知


@dataclass
class BusMessage:
    """消息结构"""

    topic: str
    payload: dict
    source_node: str = ""
    target_node: str = "all"  # "all" 表示广播，否则为节点 ID
    message_type: str = MessageType.BROADCAST.value
    message_id: str = ""  # 消息唯一 ID
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "payload": self.payload,
            "source_node": self.source_node,
            "target_node": self.target_node,
            "message_type": self.message_type,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
        }


class MessageBus:
    """跨节点消息总线

    提供节点间的消息传递能力：
    - subscribe():   订阅主题
    - publish():     发布广播消息
    - request():     发送请求并等待响应（RPC）
    """

    def __init__(self, node_config):
        """
        Args:
            node_config: NodeConfig 实例，用于获取本节点信息和对等节点列表
        """
        self._config = node_config
        self._handlers: dict[str, list[Callable]] = {}
        self._request_handlers: dict[str, Callable] = {}

    def subscribe(self, topic: str, handler: Callable) -> None:
        """订阅主题

        Args:
            topic:   主题名称
            handler: 回调函数，签名: handler(topic: str, message: dict) -> None
        """
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)
        logger.debug(f"订阅主题: {topic} (当前 {len(self._handlers[topic])} 个处理器)")

    def subscribe_request(self, topic: str, handler: Callable) -> None:
        """订阅请求-响应主题（用于 RPC 服务端）

        Args:
            topic:   主题名称
            handler: 回调函数，签名: handler(topic: str, message: dict) -> dict
        """
        self._request_handlers[topic] = handler
        logger.debug(f"注册 RPC 处理器: {topic}")

    def publish(self, topic: str, message: dict, target_node: str = "all") -> None:
        """发布消息

        Args:
            topic:        主题名称
            message:      消息内容（字典）
            target_node:  目标节点 ID，"all" 表示广播给所有节点
        """
        # 先在本地分发
        self._send_to_local(topic, message, source_node=self._config.node_id)

        if target_node == "all":
            # 广播给所有对等节点
            self._broadcast_to_peers(topic, message)
        else:
            # 发送给指定节点
            self._send_to_remote(topic, message, target_node)

    def request(
        self,
        topic: str,
        message: dict,
        target_node: str,
        timeout: float = 30.0,
    ) -> dict:
        """发送 RPC 请求并等待响应

        Args:
            topic:        请求主题
            message:      请求数据
            target_node:  目标节点 ID
            timeout:      超时时间（秒）

        Returns:
            目标节点返回的响应数据
        """
        # 如果目标是本节点，直接本地调用
        if target_node == self._config.node_id:
            handler = self._request_handlers.get(topic)
            if handler:
                return handler(topic, message)
            raise RuntimeError(f"本节点无 RPC 处理器: {topic}")

        # 发送到远程节点
        target_info = self._find_peer_node(target_node)
        if not target_info:
            raise RuntimeError(f"未找到目标节点: {target_node}")

        url = (
            f"http://{target_info['host']}:{target_info['port']}"
            f"/api/v1/cluster/message"
        )
        payload = {
            "topic": topic,
            "payload": message,
            "source_node": self._config.node_id,
            "target_node": target_node,
            "message_type": MessageType.REQUEST.value,
        }

        try:
            resp = httpx.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json().get("data", {})
        except httpx.TimeoutException:
            logger.error(f"RPC 超时: {topic} → {target_node} ({timeout}s)")
            return {"error": "timeout", "message": f"请求超时 ({timeout}s)"}
        except Exception as e:
            logger.error(f"RPC 失败: {topic} → {target_node}: {e}")
            return {"error": "failed", "message": str(e)}

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _send_to_local(
        self,
        topic: str,
        message: dict,
        source_node: str = "",
    ) -> None:
        """在本地分发消息给所有订阅者"""
        handlers = self._handlers.get(topic, [])
        if not handlers:
            logger.debug(f"本地无订阅者: {topic}")
            return

        for handler in handlers:
            try:
                handler(topic, message)
            except Exception as e:
                logger.error(f"本地消息处理异常: {topic}: {e}")

    def _send_to_remote(
        self,
        topic: str,
        message: dict,
        target_node: str,
    ) -> None:
        """向指定远程节点发送消息"""
        target_info = self._find_peer_node(target_node)
        if not target_info:
            logger.warning(f"未找到目标节点，跳过发送: {target_node}")
            return

        url = (
            f"http://{target_info['host']}:{target_info['port']}"
            f"/api/v1/cluster/message"
        )
        payload = {
            "topic": topic,
            "payload": message,
            "source_node": self._config.node_id,
            "target_node": target_node,
            "message_type": MessageType.BROADCAST.value,
        }

        try:
            resp = httpx.post(url, json=payload, timeout=10.0)
            resp.raise_for_status()
            logger.debug(f"远程消息已发送: {topic} → {target_node}")
        except Exception as e:
            logger.error(f"远程消息发送失败: {topic} → {target_node}: {e}")

    def _broadcast_to_peers(self, topic: str, message: dict) -> None:
        """广播消息给所有对等节点"""
        for peer in self._config.peer_nodes:
            peer_id = peer.get("id", "")
            if peer_id and peer_id != self._config.node_id:
                self._send_to_remote(topic, message, peer_id)

    def _find_peer_node(self, node_id: str) -> Optional[dict]:
        """根据节点 ID 查找对等节点信息"""
        for peer in self._config.peer_nodes:
            if peer.get("id") == node_id:
                return peer
        return None
