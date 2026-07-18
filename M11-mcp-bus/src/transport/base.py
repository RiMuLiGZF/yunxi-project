"""M11 MCP Bus - 传输层基类.

定义统一的传输层抽象接口 BaseTransport，所有具体传输实现
（HTTP、SSE、stdio 等）都必须继承自此基类，提供一致的
连接、发送、接收接口。

设计原则:
- 统一的异步接口
- 事件驱动（回调模式）
- 传输无关：上层业务逻辑不依赖具体传输类型
- 向后兼容：现有代码可以逐步迁移
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, List, Optional


# ============================================================
# 事件回调类型别名
# ============================================================

# 消息回调：(message_dict) -> None
MessageCallback = Callable[[Dict[str, Any]], Awaitable[None]]

# 连接回调：(transport) -> None
ConnectCallback = Callable[["BaseTransport"], Awaitable[None]]

# 断开回调：(transport, reason) -> None
DisconnectCallback = Callable[["BaseTransport", str], Awaitable[None]]

# 错误回调：(transport, error) -> None
ErrorCallback = Callable[["BaseTransport", Exception], Awaitable[None]]


# ============================================================
# 传输层状态枚举
# ============================================================

class TransportState:
    """传输层连接状态."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    ERROR = "error"


# ============================================================
# 传输层基类
# ============================================================

class BaseTransport(ABC):
    """传输层抽象基类.

    定义了所有传输实现必须实现的核心接口，包括连接管理、
    消息收发和事件回调。

    所有方法默认是异步的，以支持 HTTP/SSE/stdio 等不同传输方式。

    属性:
        transport_type: 传输类型标识（如 "http", "sse", "stdio"）
        state: 当前连接状态
        endpoint: 连接端点地址（不同传输含义不同）
    """

    def __init__(self, transport_type: str, endpoint: str = "") -> None:
        """初始化传输层.

        Args:
            transport_type: 传输类型标识
            endpoint: 连接端点地址
        """
        self._transport_type = transport_type
        self._endpoint = endpoint
        self._state: str = TransportState.DISCONNECTED

        # 事件回调列表
        self._on_message_callbacks: List[MessageCallback] = []
        self._on_connect_callbacks: List[ConnectCallback] = []
        self._on_disconnect_callbacks: List[DisconnectCallback] = []
        self._on_error_callbacks: List[ErrorCallback] = []

        # 传输锁（防止并发连接/断开）
        self._lock = asyncio.Lock()

    # ============================================================
    # 属性
    # ============================================================

    @property
    def transport_type(self) -> str:
        """传输类型标识."""
        return self._transport_type

    @property
    def endpoint(self) -> str:
        """连接端点地址."""
        return self._endpoint

    @property
    def state(self) -> str:
        """当前连接状态."""
        return self._state

    def is_connected(self) -> bool:
        """检查是否已连接.

        Returns:
            True 表示已连接
        """
        return self._state == TransportState.CONNECTED

    # ============================================================
    # 抽象方法 - 子类必须实现
    # ============================================================

    @abstractmethod
    async def connect(self) -> None:
        """建立连接.

        子类应实现具体的连接逻辑，连接成功后将状态设为 CONNECTED，
        并触发 on_connect 事件。

        Raises:
            ConnectionError: 连接失败
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接.

        子类应实现具体的断开逻辑，断开后将状态设为 DISCONNECTED，
        并触发 on_disconnect 事件。
        """
        ...

    @abstractmethod
    async def send(self, message: Dict[str, Any]) -> None:
        """发送消息.

        Args:
            message: 要发送的消息字典（JSON-RPC 格式）

        Raises:
            ConnectionError: 连接未建立
            RuntimeError: 发送失败
        """
        ...

    @abstractmethod
    async def receive(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """接收一条消息.

        对于请求-响应模式的传输（如 HTTP），此方法可能不适用
        （HTTP 是同步的请求-响应）。
        对于长连接模式（如 SSE、stdio），此方法从消息队列中读取一条。

        Args:
            timeout: 超时时间（秒），None 表示一直等待

        Returns:
            消息字典，超时时返回 None
        """
        ...

    # ============================================================
    # 请求-响应模式（可选实现）
    # ============================================================

    async def request(
        self,
        message: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """发送请求并等待响应（请求-响应模式）.

        默认实现是 send + receive，子类可以根据传输特点优化。
        对于 HTTP 传输，这是主要的通信方式。

        Args:
            message: 请求消息字典
            timeout: 超时时间（秒）

        Returns:
            响应消息字典

        Raises:
            ConnectionError: 连接未建立
            TimeoutError: 请求超时
            RuntimeError: 请求失败
        """
        if not self.is_connected():
            raise ConnectionError("Transport not connected")

        await self.send(message)
        response = await self.receive(timeout=timeout)
        if response is None:
            raise TimeoutError("Request timed out")
        return response

    # ============================================================
    # 事件回调注册
    # ============================================================

    def on_message(self, callback: MessageCallback) -> None:
        """注册消息接收回调.

        Args:
            callback: 回调函数，接收消息字典参数
        """
        self._on_message_callbacks.append(callback)

    def on_connect(self, callback: ConnectCallback) -> None:
        """注册连接建立回调.

        Args:
            callback: 回调函数，接收传输实例参数
        """
        self._on_connect_callbacks.append(callback)

    def on_disconnect(self, callback: DisconnectCallback) -> None:
        """注册连接断开回调.

        Args:
            callback: 回调函数，接收传输实例和断开原因
        """
        self._on_disconnect_callbacks.append(callback)

    def on_error(self, callback: ErrorCallback) -> None:
        """注册错误回调.

        Args:
            callback: 回调函数，接收传输实例和异常对象
        """
        self._on_error_callbacks.append(callback)

    # ============================================================
    # 事件触发（供子类调用）
    # ============================================================

    async def _emit_message(self, message: Dict[str, Any]) -> None:
        """触发消息接收事件.

        Args:
            message: 收到的消息字典
        """
        for callback in self._on_message_callbacks:
            try:
                await callback(message)
            except Exception:
                # 回调异常不应影响传输层
                pass

    async def _emit_connect(self) -> None:
        """触发连接建立事件."""
        for callback in self._on_connect_callbacks:
            try:
                await callback(self)
            except Exception:
                pass

    async def _emit_disconnect(self, reason: str = "") -> None:
        """触发连接断开事件.

        Args:
            reason: 断开原因
        """
        for callback in self._on_disconnect_callbacks:
            try:
                await callback(self, reason)
            except Exception:
                pass

    async def _emit_error(self, error: Exception) -> None:
        """触发错误事件.

        Args:
            error: 异常对象
        """
        for callback in self._on_error_callbacks:
            try:
                await callback(self, error)
            except Exception:
                pass

    # ============================================================
    # 状态管理（供子类调用）
    # ============================================================

    def _set_state(self, state: str) -> None:
        """设置连接状态.

        Args:
            state: 新的状态值
        """
        self._state = state

    # ============================================================
    # 上下文管理器支持
    # ============================================================

    async def __aenter__(self) -> "BaseTransport":
        """异步上下文管理器入口."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器退出."""
        await self.disconnect()

    # ============================================================
    # 字符串表示
    # ============================================================

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} type={self._transport_type} state={self._state}>"

    def __str__(self) -> str:
        return f"{self._transport_type} transport ({self._state})"


__all__ = [
    "BaseTransport",
    "TransportState",
    "MessageCallback",
    "ConnectCallback",
    "DisconnectCallback",
    "ErrorCallback",
]
