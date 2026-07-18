"""M11 MCP Bus - Transport 抽象层测试.

测试传输层抽象基类、工厂模式、以及各传输实现的基本功能。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.transport import (
    BaseTransport,
    HttpTransport,
    SseTransport,
    StdioTransport,
    TransportFactory,
    TransportState,
    create_transport,
    get_transport_factory,
)
from src.transport.base import BaseTransport as BaseTransportClass


# ============================================================
# BaseTransport 抽象基类测试
# ============================================================

class TestBaseTransport:
    """测试 BaseTransport 抽象基类."""

    def test_cannot_instantiate_abstract_class(self):
        """不能直接实例化抽象基类."""
        with pytest.raises(TypeError):
            BaseTransport("test")  # type: ignore

    def test_concrete_subclass_must_implement_methods(self):
        """具体子类必须实现所有抽象方法."""
        class IncompleteTransport(BaseTransport):
            pass  # 未实现抽象方法

        with pytest.raises(TypeError):
            IncompleteTransport("test")

    def test_initial_state(self):
        """初始状态为 disconnected."""
        transport = _create_mock_transport()
        assert transport.state == TransportState.DISCONNECTED
        assert transport.is_connected() is False

    def test_transport_type_property(self):
        """传输类型属性."""
        transport = _create_mock_transport("http")
        assert transport.transport_type == "http"

    def test_endpoint_property(self):
        """端点属性."""
        transport = _create_mock_transport(endpoint="http://test")
        assert transport.endpoint == "http://test"

    def test_event_callbacks(self):
        """事件回调注册与触发."""
        transport = _create_mock_transport()
        received_messages = []
        received_connects = []
        received_disconnects = []
        received_errors = []

        async def on_msg(msg):
            received_messages.append(msg)

        async def on_connect(t):
            received_connects.append(t)

        async def on_disconnect(t, reason):
            received_disconnects.append((t, reason))

        async def on_error(t, err):
            received_errors.append((t, err))

        transport.on_message(on_msg)
        transport.on_connect(on_connect)
        transport.on_disconnect(on_disconnect)
        transport.on_error(on_error)

        # 手动触发事件（模拟内部调用）
        import asyncio
        asyncio.get_event_loop().run_until_complete(transport._emit_message({"test": 1}))
        asyncio.get_event_loop().run_until_complete(transport._emit_connect())
        asyncio.get_event_loop().run_until_complete(transport._emit_disconnect("test"))
        asyncio.get_event_loop().run_until_complete(transport._emit_error(RuntimeError("test")))

        assert len(received_messages) == 1
        assert len(received_connects) == 1
        assert len(received_disconnects) == 1
        assert len(received_errors) == 1

    def test_repr(self):
        """字符串表示."""
        transport = _create_mock_transport("http")
        repr_str = repr(transport)
        assert "http" in repr_str
        assert "disconnected" in repr_str


# ============================================================
# TransportFactory 工厂测试
# ============================================================

class TestTransportFactory:
    """测试传输工厂."""

    def test_factory_supports_http(self):
        """工厂支持 HTTP 传输."""
        factory = TransportFactory()
        assert factory.is_supported("http")
        assert "http" in factory.get_supported_types()

    def test_factory_supports_sse(self):
        """工厂支持 SSE 传输."""
        factory = TransportFactory()
        assert factory.is_supported("sse")
        assert "sse" in factory.get_supported_types()

    def test_factory_supports_stdio(self):
        """工厂支持 stdio 传输."""
        factory = TransportFactory()
        assert factory.is_supported("stdio")
        assert "stdio" in factory.get_supported_types()

    def test_create_http_transport(self):
        """创建 HTTP 传输实例."""
        factory = TransportFactory()
        transport = factory.create_transport(
            "http",
            {"endpoint": "http://localhost:8000/mcp"},
        )
        assert isinstance(transport, HttpTransport)
        assert transport.endpoint == "http://localhost:8000/mcp"

    def test_create_sse_transport(self):
        """创建 SSE 传输实例."""
        factory = TransportFactory()
        transport = factory.create_transport(
            "sse",
            {"sse_endpoint": "http://localhost:8000/mcp/sse"},
        )
        assert isinstance(transport, SseTransport)

    def test_create_stdio_transport(self):
        """创建 stdio 传输实例."""
        factory = TransportFactory()
        transport = factory.create_transport(
            "stdio",
            {"command": "python", "args": ["-c", "print('hello')"]},
        )
        assert isinstance(transport, StdioTransport)

    def test_unsupported_transport_type(self):
        """不支持的传输类型."""
        factory = TransportFactory()
        with pytest.raises(ValueError, match="Unsupported transport type"):
            factory.create_transport("unknown_type", {})

    def test_register_custom_transport(self):
        """注册自定义传输类型."""
        factory = TransportFactory()

        class CustomTransport(_create_mock_transport_class()):
            def __init__(self, custom_param=""):
                super().__init__(transport_type="custom", endpoint=custom_param)

        # 注册自定义传输类型
        factory.register_transport("custom", CustomTransport)
        assert factory.is_supported("custom")

    def test_global_singleton_factory(self):
        """全局单例工厂."""
        factory1 = get_transport_factory()
        factory2 = get_transport_factory()
        assert factory1 is factory2

    def test_create_transport_helper_function(self):
        """便捷函数 create_transport."""
        transport = create_transport(
            "http",
            {"endpoint": "http://localhost:8000/mcp"},
        )
        assert isinstance(transport, HttpTransport)


# ============================================================
# HttpTransport 测试
# ============================================================

class TestHttpTransport:
    """测试 HTTP 传输实现."""

    def test_create_http_transport(self):
        """创建 HTTP 传输实例."""
        transport = HttpTransport(
            endpoint="http://localhost:8000/mcp",
            api_key="test-key",
            timeout=30.0,
        )
        assert transport.transport_type == "http"
        assert transport.endpoint == "http://localhost:8000/mcp"
        assert transport.is_connected() is False

    def test_http_transport_with_extra_headers(self):
        """带额外请求头的 HTTP 传输."""
        transport = HttpTransport(
            endpoint="http://localhost:8000/mcp",
            extra_headers={"X-Custom": "value"},
        )
        assert transport is not None

    @pytest.mark.asyncio
    async def test_http_connect(self):
        """HTTP 连接（创建客户端）."""
        transport = HttpTransport(endpoint="http://localhost:8000/mcp")
        await transport.connect()
        assert transport.is_connected() is True
        await transport.disconnect()
        assert transport.is_connected() is False

    @pytest.mark.asyncio
    async def test_http_double_connect(self):
        """重复 connect 不报错."""
        transport = HttpTransport(endpoint="http://localhost:8000/mcp")
        await transport.connect()
        await transport.connect()  # 第二次应直接返回
        assert transport.is_connected() is True
        await transport.disconnect()

    @pytest.mark.asyncio
    async def test_http_double_disconnect(self):
        """重复 disconnect 不报错."""
        transport = HttpTransport(endpoint="http://localhost:8000/mcp")
        await transport.connect()
        await transport.disconnect()
        await transport.disconnect()  # 第二次应直接返回
        assert transport.is_connected() is False

    @pytest.mark.asyncio
    async def test_http_request_without_connection(self):
        """未连接时调用 request 应报错."""
        transport = HttpTransport(endpoint="http://localhost:8000/mcp")
        with pytest.raises(ConnectionError):
            await transport.request({"jsonrpc": "2.0", "method": "test", "id": 1})

    @pytest.mark.asyncio
    async def test_http_request(self):
        """HTTP 请求-响应（使用 mock）."""
        transport = HttpTransport(endpoint="http://localhost:8000/mcp")
        await transport.connect()

        # Mock httpx 客户端
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "result": {"ok": True},
            "id": 1,
        }
        mock_response.raise_for_status = MagicMock()

        transport._client = MagicMock()
        transport._client.post = AsyncMock(return_value=mock_response)

        response = await transport.request({
            "jsonrpc": "2.0",
            "method": "test",
            "id": 1,
        })
        assert response["result"] == {"ok": True}
        assert response["id"] == 1

        await transport.disconnect()


# ============================================================
# StdioTransport 测试（基本功能，不实际启动进程）
# ============================================================

class TestStdioTransport:
    """测试 stdio 传输实现（基本功能）."""

    def test_create_stdio_transport(self):
        """创建 stdio 传输实例."""
        transport = StdioTransport(
            command="python",
            args=["-c", "print('hello')"],
        )
        assert transport.transport_type == "stdio"
        assert transport.is_connected() is False
        assert transport.pid is None

    def test_stdio_transport_initial_state(self):
        """初始状态检查."""
        transport = StdioTransport(command="echo", args=["hello"])
        assert transport.state == TransportState.DISCONNECTED
        assert transport.exit_code is None
        assert transport.error_message == ""

    def test_get_stderr_logs_empty(self):
        """空的 stderr 日志."""
        transport = StdioTransport(command="echo")
        logs = transport.get_stderr_logs()
        assert isinstance(logs, list)
        assert len(logs) == 0


# ============================================================
# SseTransport 测试（基本功能）
# ============================================================

class TestSseTransport:
    """测试 SSE 传输实现（基本功能）."""

    def test_create_sse_transport(self):
        """创建 SSE 传输实例."""
        transport = SseTransport(
            sse_endpoint="http://localhost:8000/mcp/sse",
            post_endpoint="http://localhost:8000/mcp/sse/{session_id}",
        )
        assert transport.transport_type == "sse"
        assert transport.is_connected() is False

    def test_sse_with_api_key(self):
        """带 API Key 的 SSE 传输."""
        transport = SseTransport(
            sse_endpoint="http://localhost:8000/mcp/sse",
            api_key="test-key",
        )
        assert transport is not None


# ============================================================
# 辅助函数
# ============================================================

def _create_mock_transport_class():
    """创建一个实现了所有抽象方法的 mock 传输类."""
    class MockTransport(BaseTransport):
        async def connect(self):
            self._set_state(TransportState.CONNECTED)
            await self._emit_connect()

        async def disconnect(self):
            self._set_state(TransportState.DISCONNECTED)
            await self._emit_disconnect("normal")

        async def send(self, message):
            if not self.is_connected():
                raise ConnectionError("Not connected")

        async def receive(self, timeout=None):
            if not self.is_connected():
                raise ConnectionError("Not connected")
            return None

    return MockTransport


def _create_mock_transport(transport_type="mock", endpoint=""):
    """创建 mock 传输实例."""
    cls = _create_mock_transport_class()
    return cls(transport_type=transport_type, endpoint=endpoint)
