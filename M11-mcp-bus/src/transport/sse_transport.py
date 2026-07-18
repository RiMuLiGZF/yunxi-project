"""M11 MCP Bus - SSE 传输实现.

基于 Server-Sent Events 的长连接传输实现，继承 BaseTransport。
适用于与支持 SSE 传输协议的 MCP 服务通信。

特点:
- 双向通信（SSE 下行 + POST 上行）
- 长连接，支持服务器推送
- 请求-响应匹配（基于 id）
- 支持通知消息
"""

from __future__ import annotations

import asyncio
import json
import secrets
from asyncio import Queue
from typing import Any, Dict, Optional

import httpx

from .base import BaseTransport, TransportState


class SseTransport(BaseTransport):
    """SSE 传输实现.

    使用 SSE（Server-Sent Events）作为下行通道，
    HTTP POST 作为上行通道，实现双向通信。

    请求通过 POST 发送到消息端点，响应通过 SSE 流接收。
    使用 JSON-RPC 的 id 字段进行请求-响应匹配。

    使用方式:
        transport = SseTransport(
            sse_endpoint="http://localhost:8000/mcp/sse",
            post_endpoint="http://localhost:8000/mcp/sse/{session_id}"
        )
        await transport.connect()
        response = await transport.request({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
        await transport.disconnect()
    """

    def __init__(
        self,
        sse_endpoint: str,
        post_endpoint: str = "",
        api_key: str = "",
        timeout: float = 30.0,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """初始化 SSE 传输.

        Args:
            sse_endpoint: SSE 连接端点（GET）
            post_endpoint: 消息发送端点（POST），支持 {session_id} 占位符
            api_key: API Key
            timeout: 请求超时时间（秒）
            extra_headers: 额外的请求头
        """
        super().__init__(transport_type="sse", endpoint=sse_endpoint)
        self._sse_endpoint = sse_endpoint
        self._post_endpoint_template = post_endpoint or sse_endpoint
        self._api_key = api_key
        self._timeout = timeout
        self._extra_headers = extra_headers or {}

        # 会话 ID（连接后由服务端分配）
        self._session_id: Optional[str] = None

        # 消息队列（接收到的消息）
        self._message_queue: Queue[Dict[str, Any]] = Queue(maxsize=1000)

        # 待处理请求（id -> Future）
        self._pending_requests: Dict[Any, asyncio.Future] = {}

        # 后台任务
        self._reader_task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None

    # ============================================================
    # 连接管理
    # ============================================================

    async def connect(self) -> None:
        """建立 SSE 连接."""
        async with self._lock:
            if self._state == TransportState.CONNECTED:
                return

            self._set_state(TransportState.CONNECTING)

            # 构建请求头
            headers = {
                "Accept": "text/event-stream",
                **self._extra_headers,
            }
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=headers,
            )

            try:
                # 启动 SSE 读取任务
                self._reader_task = asyncio.create_task(self._read_sse_stream())
                # 等待会话建立（等待 endpoint 事件）
                await self._wait_for_session(timeout=10.0)

                self._set_state(TransportState.CONNECTED)
                await self._emit_connect()
            except Exception as e:
                # 连接失败，清理
                if self._client:
                    await self._client.aclose()
                    self._client = None
                self._set_state(TransportState.ERROR)
                await self._emit_error(e)
                raise ConnectionError(f"SSE connection failed: {e}") from e

    async def disconnect(self) -> None:
        """断开 SSE 连接."""
        async with self._lock:
            if self._state == TransportState.DISCONNECTED:
                return

            self._set_state(TransportState.DISCONNECTING)

            # 取消读取任务
            if self._reader_task and not self._reader_task.done():
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._reader_task = None

            # 关闭客户端
            if self._client:
                try:
                    await self._client.aclose()
                except Exception:
                    pass
                self._client = None

            # 清理 pending requests
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(ConnectionError("SSE connection closed"))
            self._pending_requests.clear()

            self._session_id = None
            self._set_state(TransportState.DISCONNECTED)
            await self._emit_disconnect("normal")

    # ============================================================
    # 消息收发
    # ============================================================

    async def send(self, message: Dict[str, Any]) -> None:
        """发送消息（通过 POST 端点）.

        Args:
            message: 消息字典

        Raises:
            ConnectionError: 连接未建立
            RuntimeError: 发送失败
        """
        if not self.is_connected() or self._client is None:
            raise ConnectionError("SSE transport not connected")

        if not self._session_id:
            raise ConnectionError("SSE session not established")

        post_url = self._post_endpoint_template.format(session_id=self._session_id)

        try:
            response = await self._client.post(
                post_url,
                json=message,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            await self._emit_error(e)
            raise RuntimeError(f"SSE send failed: {e}") from e

    async def receive(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """从消息队列接收一条消息.

        Args:
            timeout: 超时时间（秒），None 表示一直等待

        Returns:
            消息字典，超时返回 None
        """
        try:
            if timeout is None:
                return await self._message_queue.get()
            else:
                return await asyncio.wait_for(
                    self._message_queue.get(), timeout=timeout
                )
        except asyncio.TimeoutError:
            return None

    async def request(
        self,
        message: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """发送请求并等待匹配的响应.

        使用消息中的 id 字段进行请求-响应匹配。

        Args:
            message: 请求消息字典（必须包含 id）
            timeout: 超时时间（秒）

        Returns:
            响应消息字典

        Raises:
            ConnectionError: 连接未建立
            ValueError: 请求消息缺少 id
            TimeoutError: 请求超时
        """
        if not self.is_connected():
            raise ConnectionError("SSE transport not connected")

        request_id = message.get("id")
        if request_id is None:
            # 通知消息，直接发送不等待响应
            await self.send(message)
            return {}

        # 创建 Future 等待响应
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests[request_id] = future

        try:
            await self.send(message)
            response = await asyncio.wait_for(
                future, timeout=timeout or self._timeout
            )
            return response
        except asyncio.TimeoutError as e:
            raise TimeoutError(f"SSE request timed out (id={request_id})") from e
        finally:
            self._pending_requests.pop(request_id, None)

    # ============================================================
    # 内部方法：SSE 流读取
    # ============================================================

    async def _read_sse_stream(self) -> None:
        """后台读取 SSE 流的任务."""
        try:
            async with self._client.stream("GET", self._sse_endpoint) as response:
                response.raise_for_status()

                current_event = "message"
                current_data_lines: list[str] = []

                async for line in response.aiter_lines():
                    if not line:
                        # 空行表示事件结束
                        if current_data_lines:
                            data = "\n".join(current_data_lines)
                            await self._handle_sse_event(current_event, data)
                            current_data_lines = []
                        current_event = "message"
                        continue

                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        current_data_lines.append(line[5:].strip())
                    # 忽略其他类型（id:, retry:, 注释等）

        except asyncio.CancelledError:
            # 正常取消
            raise
        except Exception as e:
            # 连接异常
            if self._state == TransportState.CONNECTED:
                self._set_state(TransportState.ERROR)
                await self._emit_error(e)
                await self._emit_disconnect(f"error: {e}")

    async def _handle_sse_event(self, event: str, data: str) -> None:
        """处理 SSE 事件.

        Args:
            event: 事件类型
            data: 事件数据
        """
        if event == "endpoint":
            # endpoint 事件：包含会话 ID
            try:
                endpoint_data = json.loads(data)
                endpoint_url = endpoint_data.get("endpoint", "")
                # 从 endpoint URL 中提取 session_id
                # 格式通常是 /mcp/sse/{session_id}
                parts = endpoint_url.rstrip("/").split("/")
                if parts:
                    self._session_id = parts[-1]
            except (json.JSONDecodeError, IndexError):
                pass
            return

        if event == "message":
            # 消息事件：JSON-RPC 响应或通知
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                return

            if not isinstance(message, dict):
                return

            # 放入消息队列
            try:
                self._message_queue.put_nowait(message)
            except asyncio.QueueFull:
                # 队列满，丢弃最旧的消息
                try:
                    self._message_queue.get_nowait()
                    self._message_queue.put_nowait(message)
                except asyncio.QueueFull:
                    pass

            # 匹配 pending request
            msg_id = message.get("id")
            if msg_id is not None and msg_id in self._pending_requests:
                future = self._pending_requests[msg_id]
                if not future.done():
                    future.set_result(message)

            # 触发消息回调
            await self._emit_message(message)

    async def _wait_for_session(self, timeout: float) -> None:
        """等待会话建立（等待 session_id 被设置）.

        Args:
            timeout: 超时时间（秒）

        Raises:
            TimeoutError: 等待超时
        """
        start = asyncio.get_event_loop().time()
        while self._session_id is None:
            if asyncio.get_event_loop().time() - start > timeout:
                raise TimeoutError("SSE session establishment timed out")
            await asyncio.sleep(0.1)
            # 检查读取任务是否已失败
            if self._reader_task and self._reader_task.done():
                try:
                    self._reader_task.result()
                except Exception as e:
                    raise ConnectionError(f"SSE reader task failed: {e}") from e


__all__ = ["SseTransport"]
