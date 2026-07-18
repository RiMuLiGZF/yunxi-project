"""M11 MCP Bus - Protocol 层测试.

测试 JSON-RPC 2.0 协议解析器的各项功能：
- 请求解析与验证
- 响应构建与解析
- 错误构建
- 批量请求支持
- 通知支持
- 标准错误码
"""

import json
import pytest

from src.protocol import (
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    JsonRpcErrorCode,
    build_error,
    build_response,
    handle_parse_error,
    is_notification,
    parse_request,
    parse_response,
)


# ============================================================
# JSONRPCRequest 模型测试
# ============================================================

class TestJSONRPCRequest:
    """测试 JSONRPCRequest 模型."""

    def test_create_basic_request(self):
        """创建基本请求."""
        req = JSONRPCRequest(method="tools/list", id=1)
        assert req.jsonrpc == "2.0"
        assert req.method == "tools/list"
        assert req.id == 1
        assert req.params is None
        assert req.is_notification is False

    def test_create_request_with_params(self):
        """创建带参数的请求."""
        req = JSONRPCRequest(
            method="tools/call",
            params={"name": "test_tool", "arguments": {"a": 1}},
            id="req-001",
        )
        assert req.method == "tools/call"
        assert req.params == {"name": "test_tool", "arguments": {"a": 1}}
        assert req.id == "req-001"

    def test_create_notification(self):
        """创建通知（无 id）."""
        req = JSONRPCRequest(method="notifications/initialized")
        assert req.method == "notifications/initialized"
        assert req.id is None
        assert req.is_notification is True

    def test_invalid_jsonrpc_version(self):
        """无效的 JSON-RPC 版本号."""
        with pytest.raises(ValueError):
            JSONRPCRequest(jsonrpc="1.0", method="test", id=1)

    def test_invalid_method_rpc_prefix(self):
        """方法名不能以 rpc. 开头."""
        with pytest.raises(ValueError):
            JSONRPCRequest(method="rpc.test", id=1)

    def test_empty_method_name(self):
        """空方法名."""
        with pytest.raises(ValueError):
            JSONRPCRequest(method="", id=1)

    def test_to_dict(self):
        """转换为字典."""
        req = JSONRPCRequest(method="test", params={"a": 1}, id=1)
        d = req.to_dict()
        assert d["jsonrpc"] == "2.0"
        assert d["method"] == "test"
        assert d["params"] == {"a": 1}
        assert d["id"] == 1

    def test_notification_to_dict_without_id(self):
        """通知的 to_dict 不包含 id."""
        req = JSONRPCRequest(method="test")
        d = req.to_dict()
        assert "id" not in d


# ============================================================
# JSONRPCResponse 模型测试
# ============================================================

class TestJSONRPCResponse:
    """测试 JSONRPCResponse 模型."""

    def test_create_success_response(self):
        """创建成功响应."""
        resp = JSONRPCResponse(result={"tools": []}, id=1)
        assert resp.jsonrpc == "2.0"
        assert resp.result == {"tools": []}
        assert resp.error is None
        assert resp.is_success is True
        assert resp.is_error is False

    def test_create_error_response(self):
        """创建错误响应."""
        error = JSONRPCError(code=-32601, message="Method not found")
        resp = JSONRPCResponse(error=error, id=1)
        assert resp.result is None
        assert resp.error is not None
        assert resp.error.code == -32601
        assert resp.is_success is False
        assert resp.is_error is True

    def test_to_dict_success(self):
        """成功响应转字典."""
        resp = JSONRPCResponse(result={"ok": True}, id="abc")
        d = resp.to_dict()
        assert d["jsonrpc"] == "2.0"
        assert d["result"] == {"ok": True}
        assert d["id"] == "abc"
        assert "error" not in d

    def test_to_dict_error(self):
        """错误响应转字典."""
        error = JSONRPCError(code=-32600, message="Invalid Request")
        resp = JSONRPCResponse(error=error, id=1)
        d = resp.to_dict()
        assert "error" in d
        assert d["error"]["code"] == -32600
        assert d["error"]["message"] == "Invalid Request"


# ============================================================
# JSONRPCError 模型测试
# ============================================================

class TestJSONRPCError:
    """测试 JSONRPCError 模型."""

    def test_create_parse_error(self):
        """Parse Error."""
        err = JSONRPCError.parse_error()
        assert err.code == -32700
        assert "Parse error" in err.message

    def test_create_invalid_request(self):
        """Invalid Request."""
        err = JSONRPCError.invalid_request()
        assert err.code == -32600
        assert "Invalid Request" in err.message

    def test_create_method_not_found(self):
        """Method not found."""
        err = JSONRPCError.method_not_found()
        assert err.code == -32601
        assert "Method not found" in err.message

    def test_create_invalid_params(self):
        """Invalid params."""
        err = JSONRPCError.invalid_params()
        assert err.code == -32602
        assert "Invalid params" in err.message

    def test_create_internal_error(self):
        """Internal error."""
        err = JSONRPCError.internal_error()
        assert err.code == -32603
        assert "Internal error" in err.message

    def test_error_with_data(self):
        """带 data 字段的错误."""
        err = JSONRPCError.invalid_params(data={"field": "name"})
        assert err.data == {"field": "name"}
        d = err.to_dict()
        assert d["data"] == {"field": "name"}

    def test_custom_message(self):
        """自定义错误消息."""
        err = JSONRPCError.from_code(-32601, message="Custom error message")
        assert err.message == "Custom error message"

    def test_to_dict_without_data(self):
        """不带 data 的 to_dict."""
        err = JSONRPCError(code=-32601, message="Method not found")
        d = err.to_dict()
        assert "data" not in d


# ============================================================
# parse_request 函数测试
# ============================================================

class TestParseRequest:
    """测试 parse_request 函数."""

    def test_parse_single_request(self):
        """解析单条请求."""
        raw = json.dumps({"jsonrpc": "2.0", "method": "test", "id": 1})
        result = parse_request(raw)
        assert isinstance(result, JSONRPCRequest)
        assert result.method == "test"
        assert result.id == 1

    def test_parse_batch_request(self):
        """解析批量请求."""
        raw = json.dumps([
            {"jsonrpc": "2.0", "method": "test1", "id": 1},
            {"jsonrpc": "2.0", "method": "test2", "id": 2},
        ])
        result = parse_request(raw)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].method == "test1"
        assert result[1].method == "test2"

    def test_parse_invalid_json(self):
        """无效 JSON."""
        with pytest.raises(ValueError, match="Parse error"):
            parse_request("not valid json")

    def test_parse_empty_batch(self):
        """空批量请求."""
        with pytest.raises(ValueError, match="Invalid Request"):
            parse_request("[]")

    def test_parse_missing_jsonrpc(self):
        """缺少 jsonrpc 字段."""
        with pytest.raises(ValueError, match="Invalid Request"):
            parse_request({"method": "test", "id": 1})

    def test_parse_missing_method(self):
        """缺少 method 字段."""
        with pytest.raises(ValueError, match="Invalid Request"):
            parse_request({"jsonrpc": "2.0", "id": 1})

    def test_parse_wrong_version(self):
        """错误的版本号."""
        with pytest.raises(ValueError, match="Invalid Request"):
            parse_request({"jsonrpc": "1.0", "method": "test", "id": 1})

    def test_parse_notification(self):
        """解析通知（无 id）."""
        result = parse_request({"jsonrpc": "2.0", "method": "test"})
        assert isinstance(result, JSONRPCRequest)
        assert result.is_notification is True

    def test_parse_with_array_params(self):
        """位置参数（数组）."""
        result = parse_request({
            "jsonrpc": "2.0",
            "method": "test",
            "params": [1, 2, 3],
            "id": 1,
        })
        assert result.params == [1, 2, 3]

    def test_parse_with_object_params(self):
        """命名参数（对象）."""
        result = parse_request({
            "jsonrpc": "2.0",
            "method": "test",
            "params": {"a": 1},
            "id": 1,
        })
        assert result.params == {"a": 1}

    def test_parse_dict_input(self):
        """字典输入（非字符串）."""
        result = parse_request({"jsonrpc": "2.0", "method": "test", "id": 1})
        assert isinstance(result, JSONRPCRequest)


# ============================================================
# parse_response 函数测试
# ============================================================

class TestParseResponse:
    """测试 parse_response 函数."""

    def test_parse_success_response(self):
        """解析成功响应."""
        raw = json.dumps({"jsonrpc": "2.0", "result": {"ok": True}, "id": 1})
        result = parse_response(raw)
        assert isinstance(result, JSONRPCResponse)
        assert result.result == {"ok": True}
        assert result.is_success

    def test_parse_error_response(self):
        """解析错误响应."""
        raw = json.dumps({
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": "Method not found"},
            "id": 1,
        })
        result = parse_response(raw)
        assert isinstance(result, JSONRPCResponse)
        assert result.is_error
        assert result.error.code == -32601

    def test_parse_batch_response(self):
        """解析批量响应."""
        raw = json.dumps([
            {"jsonrpc": "2.0", "result": 1, "id": 1},
            {"jsonrpc": "2.0", "result": 2, "id": 2},
        ])
        result = parse_response(raw)
        assert isinstance(result, list)
        assert len(result) == 2


# ============================================================
# 构建函数测试
# ============================================================

class TestBuildFunctions:
    """测试构建函数."""

    def test_build_response(self):
        """构建成功响应."""
        resp = build_response(request_id=1, result={"tools": []})
        assert resp["jsonrpc"] == "2.0"
        assert resp["result"] == {"tools": []}
        assert resp["id"] == 1

    def test_build_error(self):
        """构建错误响应."""
        resp = build_error(request_id=1, code=-32601)
        assert resp["jsonrpc"] == "2.0"
        assert resp["error"]["code"] == -32601
        assert resp["id"] == 1

    def test_build_error_custom_message(self):
        """构建自定义消息的错误响应."""
        resp = build_error(request_id=None, code=-32600, message="Custom msg")
        assert resp["error"]["message"] == "Custom msg"
        assert resp["id"] is None

    def test_handle_parse_error(self):
        """处理解析错误."""
        resp = handle_parse_error("bad json")
        assert resp["error"]["code"] == -32700
        assert resp["id"] is None


# ============================================================
# 工具函数测试
# ============================================================

class TestHelperFunctions:
    """测试工具函数."""

    def test_is_notification_true(self):
        """通知消息判断 - 是通知."""
        msg = {"jsonrpc": "2.0", "method": "test"}
        assert is_notification(msg) is True

    def test_is_notification_false(self):
        """通知消息判断 - 不是通知."""
        msg = {"jsonrpc": "2.0", "method": "test", "id": 1}
        assert is_notification(msg) is False

    def test_is_notification_null_id(self):
        """id 为 null 也算通知."""
        msg = {"jsonrpc": "2.0", "method": "test", "id": None}
        assert is_notification(msg) is True


# ============================================================
# JsonRpcErrorCode 枚举测试
# ============================================================

class TestJsonRpcErrorCode:
    """测试错误码枚举."""

    def test_parse_error_code(self):
        assert JsonRpcErrorCode.PARSE_ERROR == -32700

    def test_invalid_request_code(self):
        assert JsonRpcErrorCode.INVALID_REQUEST == -32600

    def test_method_not_found_code(self):
        assert JsonRpcErrorCode.METHOD_NOT_FOUND == -32601

    def test_invalid_params_code(self):
        assert JsonRpcErrorCode.INVALID_PARAMS == -32602

    def test_internal_error_code(self):
        assert JsonRpcErrorCode.INTERNAL_ERROR == -32603

    def test_server_error_code(self):
        assert JsonRpcErrorCode.SERVER_ERROR == -32000
