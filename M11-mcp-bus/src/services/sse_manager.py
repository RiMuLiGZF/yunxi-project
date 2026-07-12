"""M11 MCP Bus - SSE 连接管理器.

管理 MCP SSE 传输协议的客户端连接会话，
负责连接建立、消息推送、心跳保活、连接清理。

MCP SSE 协议规范：
- 客户端通过 GET /mcp/sse 建立 SSE 连接
- 服务端通过 SSE 发送消息（JSON-RPC 响应和通知）
- 客户端通过 POST /mcp/sse/{session_id} 发送请求
- 每条 SSE 消息格式：event: message\ndata: <json>\n\n
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from asyncio import Queue
from typing import Any, Dict, Optional

from ..config import get_settings


class SseSession:
    """SSE 会话对象.

    表示一个客户端的 SSE 连接，包含消息队列和连接状态。
    """

    def __init__(self, session_id: str) -> None:
        """初始化 SSE 会话.

        Args:
            session_id: 会话唯一标识
        """
        self.session_id = session_id
        self.message_queue: Queue[str] = Queue(maxsize=1000)
        self.connected = True
        self.created_at = time.time()
        self.last_activity = time.time()
        self.client_info: Dict[str, Any] = {}

    async def put_message(self, message: str) -> bool:
        """向消息队列中放入一条消息.

        Args:
            message: 消息内容（JSON 字符串）

        Returns:
            是否成功放入（队列满则返回 False）
        """
        try:
            self.message_queue.put_nowait(message)
            self.last_activity = time.time()
            return True
        except asyncio.QueueFull:
            return False

    async def get_message(self, timeout: Optional[float] = None) -> Optional[str]:
        """从消息队列获取一条消息.

        Args:
            timeout: 超时时间（秒），None 则一直等待

        Returns:
            消息内容，超时返回 None
        """
        try:
            if timeout is None:
                message = await self.message_queue.get()
            else:
                message = await asyncio.wait_for(
                    self.message_queue.get(), timeout=timeout
                )
            self.last_activity = time.time()
            return message
        except asyncio.TimeoutError:
            return None

    def close(self) -> None:
        """关闭会话."""
        self.connected = False


class SseConnectionManager:
    """SSE 连接管理器.

    管理所有 SSE 客户端连接，负责：
    - 会话创建与销毁
    - 消息路由与推送
    - 心跳保活
    - 连接数限制
    """

    def __init__(self) -> None:
        """初始化连接管理器."""
        self._settings = get_settings()
        self._sessions: Dict[str, SseSession] = {}
        self._lock = asyncio.Lock()

    # --------------------------------------------------------
    # 会话管理
    # --------------------------------------------------------

    async def create_session(self) -> Optional[SseSession]:
        """创建新的 SSE 会话.

        Returns:
            新会话对象，超出连接数限制返回 None
        """
        async with self._lock:
            # 检查连接数限制
            if len(self._sessions) >= self._settings.sse_max_clients:
                return None

            session_id = "sse_" + secrets.token_hex(16)
            session = SseSession(session_id)
            self._sessions[session_id] = session
            return session

    async def get_session(self, session_id: str) -> Optional[SseSession]:
        """获取会话.

        Args:
            session_id: 会话 ID

        Returns:
            会话对象，不存在返回 None
        """
        async with self._lock:
            return self._sessions.get(session_id)

    async def remove_session(self, session_id: str) -> None:
        """移除会话.

        Args:
            session_id: 会话 ID
        """
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                session.close()

    async def get_session_count(self) -> int:
        """获取当前连接数.

        Returns:
            当前会话数量
        """
        async with self._lock:
            return len(self._sessions)

    # --------------------------------------------------------
    # 消息推送
    # --------------------------------------------------------

    async def send_to_session(
        self, session_id: str, message: Dict[str, Any]
    ) -> bool:
        """向指定会话发送消息.

        Args:
            session_id: 会话 ID
            message: 消息字典（会被序列化为 JSON）

        Returns:
            是否成功发送
        """
        session = await self.get_session(session_id)
        if not session or not session.connected:
            return False

        try:
            message_str = json.dumps(message, ensure_ascii=False)
        except (TypeError, ValueError):
            return False

        return await session.put_message(message_str)

    async def broadcast(self, message: Dict[str, Any]) -> int:
        """向所有会话广播消息.

        Args:
            message: 消息字典

        Returns:
            成功发送的会话数量
        """
        try:
            message_str = json.dumps(message, ensure_ascii=False)
        except (TypeError, ValueError):
            return 0

        count = 0
        async with self._lock:
            for session in self._sessions.values():
                if session.connected:
                    if await session.put_message(message_str):
                        count += 1
        return count

    # --------------------------------------------------------
    # 连接清理
    # --------------------------------------------------------

    async def cleanup_stale_sessions(self, max_idle: int = 300) -> int:
        """清理过期会话.

        Args:
            max_idle: 最大空闲时间（秒）

        Returns:
            清理的会话数量
        """
        now = time.time()
        stale_ids = []

        async with self._lock:
            for sid, session in self._sessions.items():
                if not session.connected or (now - session.last_activity) > max_idle:
                    stale_ids.append(sid)

            for sid in stale_ids:
                session = self._sessions.pop(sid, None)
                if session:
                    session.close()

        return len(stale_ids)

    # --------------------------------------------------------
    # SSE 消息格式化
    # --------------------------------------------------------

    @staticmethod
    def format_sse_message(data: str, event: str = "message") -> str:
        """格式化 SSE 消息.

        Args:
            data: 消息数据
            event: 事件类型

        Returns:
            符合 SSE 协议格式的字符串
        """
        lines = [f"event: {event}"]
        for line in data.split("\n"):
            lines.append(f"data: {line}")
        lines.append("")  # 空行分隔
        lines.append("")  # 额外空行
        return "\n".join(lines)

    @staticmethod
    def format_heartbeat() -> str:
        """格式化心跳消息（注释形式）.

        Returns:
            SSE 心跳注释
        """
        return ": ping\n\n"


# ============================================================
# 单例实例
# ============================================================

sse_manager = SseConnectionManager()
