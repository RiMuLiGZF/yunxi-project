"""M11 MCP Bus - HTTP 传输实现.

基于 httpx 的 HTTP JSON-RPC 传输实现，继承 BaseTransport。
适用于与支持 HTTP POST 的 MCP 服务通信。

特点:
- 请求-响应模式
- 支持自定义请求头（如鉴权）
- 超时控制
- 连接池复用
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .base import BaseTransport, TransportState


class HttpTransport(BaseTransport):
    """HTTP 传输实现.

    通过 HTTP POST 方式发送 JSON-RPC 请求，支持：
    - 自定义请求头
    - Bearer Token 鉴权
    - 超时控制
    - 连接池

    使用方式:
        transport = HttpTransport(endpoint="http://localhost:8000/mcp")
        await transport.connect()
        response = await transport.request({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
        await transport.disconnect()
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str = "",
        timeout: float = 30.0,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """初始化 HTTP 传输.

        Args:
            endpoint: MCP 服务端点 URL
            api_key: API Key（用于 Authorization: Bearer 头）
            timeout: 请求超时时间（秒）
            extra_headers: 额外的请求头
        """
        super().__init__(transport_type="http", endpoint=endpoint)
        self._api_key = api_key
        self._timeout = timeout
        self._extra_headers = extra_headers or {}
        self._client: Optional[httpx.AsyncClient] = None

    # ============================================================
    # 连接管理
    # ============================================================

    async def connect(self) -> None:
        """建立 HTTP 连接（创建 httpx 客户端）.

        HTTP 是无状态协议，connect 主要是初始化客户端和
        验证端点可用性。
        """
        async with self._lock:
            if self._state == TransportState.CONNECTED:
                return

            self._set_state(TransportState.CONNECTING)

            # 构建请求头
            headers = {
                "Content-Type": "application/json",
                **self._extra_headers,
            }
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            # 创建 httpx 异步客户端
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=headers,
            )

            self._set_state(TransportState.CONNECTED)
            await self._emit_connect()

    async def disconnect(self) -> None:
        """断开 HTTP 连接（关闭 httpx 客户端）."""
        async with self._lock:
            if self._state == TransportState.DISCONNECTED:
                return

            self._set_state(TransportState.DISCONNECTING)

            if self._client is not None:
                try:
                    await self._client.aclose()
                except Exception:
                    pass
                self._client = None

            self._set_state(TransportState.DISCONNECTED)
            await self._emit_disconnect("normal")

    # ============================================================
    # 消息收发
    # ============================================================

    async def send(self, message: Dict[str, Any]) -> None:
        """发送消息（HTTP 下不适用，使用 request 方法）.

        HTTP 是请求-响应模式，send 方法不直接使用。
        请使用 request() 方法发送请求并获取响应。

        Args:
            message: 消息字典

        Raises:
            ConnectionError: 连接未建立
            NotImplementedError: HTTP 传输不支持单独发送
        """
        if not self.is_connected():
            raise ConnectionError("HTTP transport not connected")

        # HTTP 传输不支持纯发送（必须等待响应）
        # 这里为了兼容接口，内部调用 request 但忽略响应
        # 实际使用中应该直接用 request 方法
        await self.request(message)

    async def receive(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """接收消息（HTTP 下不适用）.

        HTTP 是请求-响应模式，没有主动接收消息的能力。
        此方法始终返回 None。

        Args:
            timeout: 超时时间（忽略）

        Returns:
            None - HTTP 传输不支持主动接收
        """
        # HTTP 传输是同步的请求-响应模式，没有消息队列
        return None

    async def request(
        self,
        message: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """发送 HTTP 请求并等待响应.

        Args:
            message: JSON-RPC 请求字典
            timeout: 超时时间（秒），为 None 则使用默认值

        Returns:
            JSON-RPC 响应字典

        Raises:
            ConnectionError: 连接未建立
            RuntimeError: 请求失败或响应解析失败
            TimeoutError: 请求超时
        """
        if not self.is_connected() or self._client is None:
            raise ConnectionError("HTTP transport not connected")

        try:
            response = await self._client.post(
                self._endpoint,
                json=message,
                timeout=timeout or self._timeout,
            )
            response.raise_for_status()

            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError("Response is not a JSON object")

            await self._emit_message(data)
            return data

        except httpx.TimeoutException as e:
            await self._emit_error(e)
            raise TimeoutError(f"HTTP request timed out: {e}") from e
        except httpx.HTTPError as e:
            await self._emit_error(e)
            raise RuntimeError(f"HTTP request failed: {e}") from e
        except Exception as e:
            await self._emit_error(e)
            raise RuntimeError(f"Request failed: {e}") from e

    # ============================================================
    # 便捷方法：批量请求
    # ============================================================

    async def batch_request(
        self,
        messages: list[Dict[str, Any]],
        timeout: Optional[float] = None,
    ) -> list[Dict[str, Any]]:
        """发送批量 JSON-RPC 请求.

        Args:
            messages: JSON-RPC 请求列表
            timeout: 超时时间（秒）

        Returns:
            JSON-RPC 响应列表

        Raises:
            ConnectionError: 连接未建立
            RuntimeError: 请求失败
        """
        if not self.is_connected() or self._client is None:
            raise ConnectionError("HTTP transport not connected")

        try:
            response = await self._client.post(
                self._endpoint,
                json=messages,
                timeout=timeout or self._timeout,
            )
            response.raise_for_status()

            data = response.json()
            if not isinstance(data, list):
                raise RuntimeError("Batch response is not a JSON array")

            return data

        except httpx.HTTPError as e:
            await self._emit_error(e)
            raise RuntimeError(f"Batch request failed: {e}") from e


__all__ = ["HttpTransport"]
