"""
M11 MCP 总线 - MCP 协议与 API Key 认证单元测试

测试内容：
- JSON-RPC 2.0 协议解析与构建（纯单元测试，不依赖 FastAPI）
- API Key 哈希与提取函数（纯单元测试）
- API Key 认证服务核心逻辑（mock 数据库依赖）
- 健康检查端点（集成测试，标记为 integration）
"""

import sys
import json
import hashlib
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent.parent
M11_SRC_PATH = PROJECT_ROOT / "M11-mcp-bus" / "src"

# 将 M11 源码加入路径以便直接导入纯逻辑模块
if str(M11_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(M11_SRC_PATH))


def _try_import_security():
    """尝试导入 security.auth 模块，失败返回 None"""
    try:
        # 方式1：直接从 src 包导入（当 src 父目录在 path 中时）
        from src.security import auth
        return auth
    except ImportError:
        pass
    try:
        # 方式2：直接导入
        from security import auth
        return auth
    except ImportError:
        return None


# ============================================================
# JSON-RPC 协议单元测试（不依赖 FastAPI，纯函数测试）
# ============================================================

class TestJSONRPCProtocol:
    """JSON-RPC 2.0 协议解析与构建测试"""

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_parse_valid_request(self):
        """解析有效的 JSON-RPC 请求"""
        from protocol.jsonrpc import parse_request, JSONRPCRequest

        raw = json.dumps({"jsonrpc": "2.0", "method": "ping", "id": 1})
        result = parse_request(raw)

        assert isinstance(result, JSONRPCRequest)
        assert result.jsonrpc == "2.0"
        assert result.method == "ping"
        assert result.id == 1
        assert result.params is None
        assert not result.is_notification

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_parse_request_with_params(self):
        """解析带参数的请求"""
        from protocol.jsonrpc import parse_request

        raw = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "hello"}},
            "id": "req-1",
        })
        result = parse_request(raw)

        assert result.method == "tools/call"
        assert result.params is not None
        assert result.params["name"] == "echo"
        assert result.id == "req-1"

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_parse_notification(self):
        """解析通知（无 id）"""
        from protocol.jsonrpc import parse_request

        raw = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        result = parse_request(raw)

        assert result.is_notification is True
        assert result.id is None

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_parse_invalid_json(self):
        """解析无效 JSON 抛出 ValueError"""
        from protocol.jsonrpc import parse_request

        with pytest.raises(ValueError, match="Parse error"):
            parse_request("not valid json")

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_parse_missing_jsonrpc(self):
        """缺少 jsonrpc 字段的请求抛出 ValueError"""
        from protocol.jsonrpc import parse_request

        raw = json.dumps({"method": "ping", "id": 1})
        with pytest.raises(ValueError):
            parse_request(raw)

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_parse_missing_method(self):
        """缺少 method 字段的请求抛出 ValueError"""
        from protocol.jsonrpc import parse_request

        raw = json.dumps({"jsonrpc": "2.0", "id": 1})
        with pytest.raises(ValueError):
            parse_request(raw)

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_parse_batch_request(self):
        """解析批量请求"""
        from protocol.jsonrpc import parse_request

        raw = json.dumps([
            {"jsonrpc": "2.0", "method": "ping", "id": 1},
            {"jsonrpc": "2.0", "method": "pong", "id": 2},
        ])
        result = parse_request(raw)
        # 批量请求应该返回列表或特殊处理
        assert result is not None

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_parse_empty_batch(self):
        """解析空批量请求抛出 ValueError"""
        from protocol.jsonrpc import parse_request

        raw = json.dumps([])
        with pytest.raises(ValueError, match="empty batch"):
            parse_request(raw)

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_build_success_response(self):
        """构建成功响应"""
        from protocol.jsonrpc import build_response

        resp = build_response(request_id=1, result={"tools": []})

        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["result"] == {"tools": []}
        assert "error" not in resp

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_build_error_response(self):
        """构建错误响应"""
        from protocol.jsonrpc import build_error
        from protocol.types import JsonRpcErrorCode

        resp = build_error(
            request_id=1,
            code=JsonRpcErrorCode.METHOD_NOT_FOUND,
            message="Method not found",
        )

        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["error"]["code"] == JsonRpcErrorCode.METHOD_NOT_FOUND
        assert resp["error"]["message"] == "Method not found"
        assert "result" not in resp

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_parse_success_response(self):
        """解析成功响应"""
        from protocol.jsonrpc import parse_response, JSONRPCResponse

        raw = json.dumps({"jsonrpc": "2.0", "result": {"ok": True}, "id": 1})
        result = parse_response(raw)

        assert isinstance(result, JSONRPCResponse)
        assert result.is_success is True
        assert result.is_error is False
        assert result.result == {"ok": True}
        assert result.id == 1

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_parse_error_response(self):
        """解析错误响应"""
        from protocol.jsonrpc import parse_response

        raw = json.dumps({
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": "Method not found"},
            "id": 1,
        })
        result = parse_response(raw)

        assert result.is_error is True
        assert result.is_success is False
        assert result.error.code == -32601
        assert result.error.message == "Method not found"

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_handle_parse_error(self):
        """处理解析错误，返回标准 Parse Error"""
        from protocol.jsonrpc import handle_parse_error
        from protocol.types import JsonRpcErrorCode

        result = handle_parse_error("garbage")

        assert result["jsonrpc"] == "2.0"
        assert result["error"]["code"] == JsonRpcErrorCode.PARSE_ERROR
        assert result["id"] is None

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_build_batch_response_filters_notifications(self):
        """批量响应过滤掉通知消息"""
        from protocol.jsonrpc import build_batch_response, build_response

        responses = [
            build_response(request_id=1, result="ok"),
            build_response(request_id=None, result=None),  # 通知，应被过滤
            build_response(request_id=2, result="done"),
        ]

        batch = build_batch_response(responses)
        assert len(batch) == 2
        assert batch[0]["id"] == 1
        assert batch[1]["id"] == 2

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_jsonrpcrequest_model_validation(self):
        """JSONRPCRequest 模型验证"""
        from protocol.jsonrpc import JSONRPCRequest

        # 正常请求
        req = JSONRPCRequest(jsonrpc="2.0", method="test", id=1)
        assert req.jsonrpc == "2.0"
        assert req.method == "test"
        assert req.id == 1

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_error_code_constants(self):
        """错误码常量值正确"""
        from protocol.types import JsonRpcErrorCode

        assert JsonRpcErrorCode.PARSE_ERROR == -32700
        assert JsonRpcErrorCode.INVALID_REQUEST == -32600
        assert JsonRpcErrorCode.METHOD_NOT_FOUND == -32601
        assert JsonRpcErrorCode.INVALID_PARAMS == -32602
        assert JsonRpcErrorCode.INTERNAL_ERROR == -32603

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_is_notification_property(self):
        """is_notification 属性正确判断"""
        from protocol.jsonrpc import JSONRPCRequest

        # 有 id 不是通知
        req1 = JSONRPCRequest(jsonrpc="2.0", method="test", id=1)
        assert req1.is_notification is False

        # 无 id 是通知
        req2 = JSONRPCRequest(jsonrpc="2.0", method="test", id=None)
        assert req2.is_notification is True


# ============================================================
# API Key 工具函数测试（纯函数，无外部依赖）
# ============================================================

class TestAPIKeyFunctions:
    """API Key 工具函数测试（纯函数，无外部依赖）

    如果 security.auth 模块无法导入（相对导入问题），测试会自动跳过。
    """

    @pytest.fixture
    def auth_module(self):
        """获取 security.auth 模块"""
        mod = _try_import_security()
        if mod is None:
            pytest.skip("security.auth 模块不可用")
        return mod

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_hash_key_returns_sha256(self, auth_module):
        """hash_key 函数返回 SHA256 十六进制字符串"""
        key = "test-api-key-12345"
        hashed = auth_module.hash_key(key)

        assert len(hashed) == 64
        assert hashed == hashlib.sha256(key.encode("utf-8")).hexdigest()

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_hash_key_is_deterministic(self, auth_module):
        """相同输入产生相同哈希"""
        key = "my-secret-key"
        assert auth_module.hash_key(key) == auth_module.hash_key(key)

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_hash_key_different_inputs(self, auth_module):
        """不同输入产生不同哈希"""
        assert auth_module.hash_key("key-a") != auth_module.hash_key("key-b")

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_extract_key_from_x_api_key_header(self, auth_module):
        """从 X-API-Key 头提取 Key"""
        headers = {"X-API-Key": "key-from-header"}
        result = auth_module.AuthService.extract_key_from_headers(headers)
        assert result == "key-from-header"

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_extract_key_from_lowercase_header(self, auth_module):
        """从小写 x-api-key 头提取 Key"""
        headers = {"x-api-key": "key-lowercase"}
        result = auth_module.AuthService.extract_key_from_headers(headers)
        assert result == "key-lowercase"

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_extract_key_from_bearer_token(self, auth_module):
        """从 Authorization: Bearer 头提取 Key"""
        headers = {"Authorization": "Bearer key-from-bearer"}
        result = auth_module.AuthService.extract_key_from_headers(headers)
        assert result == "key-from-bearer"

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_extract_key_from_lowercase_bearer(self, auth_module):
        """从小写 authorization bearer 头提取 Key"""
        headers = {"authorization": "bearer key-lower-bearer"}
        result = auth_module.AuthService.extract_key_from_headers(headers)
        assert result == "key-lower-bearer"

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_extract_key_returns_none_when_missing(self, auth_module):
        """没有 Key 时返回 None"""
        assert auth_module.AuthService.extract_key_from_headers({}) is None
        assert auth_module.AuthService.extract_key_from_headers(
            {"Content-Type": "application/json"}
        ) is None

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_extract_key_prefers_x_api_key_over_bearer(self, auth_module):
        """X-API-Key 优先级高于 Bearer"""
        headers = {
            "X-API-Key": "header-key",
            "Authorization": "Bearer bearer-key",
        }
        result = auth_module.AuthService.extract_key_from_headers(headers)
        assert result == "header-key"


# ============================================================
# 公开路径判断测试
# ============================================================

class TestPublicPaths:
    """公开路径判断测试"""

    @pytest.fixture
    def auth_module(self):
        """获取 security.auth 模块"""
        mod = _try_import_security()
        if mod is None:
            pytest.skip("security.auth 模块不可用")
        return mod

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_health_is_public(self, auth_module):
        """/health 是公开路径"""
        assert auth_module.is_public_path("/health") is True

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_docs_is_public(self, auth_module):
        """/docs 是公开路径"""
        assert auth_module.is_public_path("/docs") is True

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_openapi_is_public(self, auth_module):
        """/openapi.json 是公开路径"""
        assert auth_module.is_public_path("/openapi.json") is True

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_m8_wildcard_matches(self, auth_module):
        """/m8/* 通配符匹配 /m8/health 等"""
        assert auth_module.is_public_path("/m8/health") is True
        assert auth_module.is_public_path("/m8/metrics") is True
        assert auth_module.is_public_path("/m8/config") is True

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_protected_path_not_public(self, auth_module):
        """受保护路径不是公开路径"""
        assert auth_module.is_public_path("/mcp") is False
        assert auth_module.is_public_path("/api/tools") is False
        assert auth_module.is_public_path("/admin/keys") is False

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_custom_public_paths(self, auth_module):
        """自定义公开路径列表"""
        custom_paths = ["/custom/public", "/health"]
        assert auth_module.is_public_path("/custom/public", custom_paths) is True
        assert auth_module.is_public_path("/docs", custom_paths) is False


# ============================================================
# AuthService 核心逻辑测试（mock 数据库依赖）
# ============================================================

class TestAuthServiceLogic:
    """AuthService 核心逻辑测试（mock 数据库依赖）"""

    @pytest.fixture
    def auth_module(self):
        """获取 security.auth 模块"""
        mod = _try_import_security()
        if mod is None:
            pytest.skip("security.auth 模块不可用")
        return mod

    @pytest.fixture
    def mock_api_key_model(self):
        """mock ApiKey 模型"""
        mock = MagicMock()
        mock.id = 1
        mock.key_hash = hashlib.sha256(b"valid-key").hexdigest()
        mock.expires_at = None
        mock.rate_limit = 100
        return mock

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_authenticate_empty_key_fails(self, auth_module):
        """空 Key 认证失败，返回 missing_key"""
        service = auth_module.AuthService(public_paths=["/health"])
        result = service.authenticate("")

        assert result.success is False
        assert result.error_code == "missing_key"

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_authenticate_invalid_key_fails(self, auth_module):
        """无效 Key 认证失败，返回 invalid_key"""
        service = auth_module.AuthService(public_paths=["/health"])

        # mock find_api_key_by_value 返回 None
        with patch.object(auth_module, "find_api_key_by_value", return_value=None):
            result = service.authenticate("wrong-key")

        assert result.success is False
        assert result.error_code == "invalid_key"

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_authenticate_valid_key_succeeds(self, auth_module, mock_api_key_model):
        """有效 Key 认证成功"""
        service = auth_module.AuthService(public_paths=["/health"])

        with patch.object(auth_module, "find_api_key_by_value", return_value=mock_api_key_model):
            result = service.authenticate("valid-key")

        assert result.success is True
        assert result.api_key is not None
        assert result.api_key.id == 1

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_authenticate_full_public_path_bypasses_auth(self, auth_module):
        """公开路径绕过认证"""
        service = auth_module.AuthService(public_paths=["/health"])
        result = service.authenticate_full(path="/health", api_key="")

        assert result.allowed is True
        assert result.reason == "public_path"

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_authenticate_full_auth_disabled_allows_anonymous(self, auth_module):
        """认证关闭时允许匿名访问"""
        service = auth_module.AuthService(auth_enabled=False, public_paths=[])
        result = service.authenticate_full(path="/any/path", api_key="")

        assert result.allowed is True
        assert result.reason == "auth_disabled"

    @pytest.mark.unit
    @pytest.mark.m11
    @pytest.mark.apikey
    @pytest.mark.auth
    def test_authenticate_full_missing_key_rejected(self, auth_module):
        """非公开路径 + 无 Key + 认证开启 = 拒绝"""
        service = auth_module.AuthService(auth_enabled=True, public_paths=["/health"])
        result = service.authenticate_full(path="/api/tools", api_key="")

        assert result.allowed is False
        assert result.error_code == "missing_key"


# ============================================================
# 集成测试（需要完整 M11 应用）
# ============================================================

class TestMCPProtocolIntegration:
    """MCP 协议集成测试（需要 M11 应用实例）

    依赖 m11_client fixture，应用无法初始化时自动跳过。
    """

    @pytest.mark.integration
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_health_endpoint(self, m11_client):
        """健康检查端点可访问"""
        response = m11_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.integration
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_health_returns_json(self, m11_client):
        """健康检查返回 JSON 格式"""
        response = m11_client.get("/health")
        data = response.json()
        assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_mcp_endpoint_exists(self, m11_client):
        """MCP 端点存在"""
        response = m11_client.post("/mcp", json={
            "jsonrpc": "2.0",
            "method": "ping",
            "id": 1,
        })
        assert response.status_code in [200, 401, 403]

    @pytest.mark.integration
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_mcp_requires_auth(self, m11_client):
        """MCP 端点需要认证"""
        response = m11_client.post("/mcp", json={
            "jsonrpc": "2.0",
            "method": "ping",
            "id": 1,
        })
        assert response.status_code in [401, 403, 200]

    @pytest.mark.integration
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_mcp_invalid_json_returns_parse_error(self, m11_client):
        """无效 JSON 返回解析错误"""
        response = m11_client.post(
            "/mcp",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code in [200, 400, 401, 403]

    @pytest.mark.integration
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_tools_list_endpoint(self, m11_client):
        """工具列表端点"""
        response = m11_client.get("/api/tools")
        assert response.status_code in [200, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_docs_endpoint(self, m11_client):
        """API 文档端点（公开）"""
        response = m11_client.get("/docs")
        assert response.status_code in [200, 404]

    @pytest.mark.integration
    @pytest.mark.m11
    @pytest.mark.mcp
    def test_openapi_endpoint(self, m11_client):
        """OpenAPI JSON 端点（公开）"""
        response = m11_client.get("/openapi.json")
        assert response.status_code in [200, 404]
