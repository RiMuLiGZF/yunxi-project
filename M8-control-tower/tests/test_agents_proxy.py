# -*- coding: utf-8 -*-
"""
Agent 管理代理路由测试（M8 控制塔）

测试 M8 端的 Agent 管理代理路由，验证：
1. 代理转发正确（请求正确转发到 M1）
2. trace_id 透传（X-Trace-Id 头正确传递）
3. 错误处理（M1 不可用时返回友好错误）

所有测试使用 mock，不依赖真实外部服务。
测试直接用 importlib 加载 agents.py 文件，避免通过 backend.routers 包的链式导入问题。
"""

import os
import sys
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, APIRouter, Request, Query, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from typing import Optional

# 路径设置
M8_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = M8_ROOT.parent
AGENTS_PY = M8_ROOT / "backend" / "routers" / "business" / "agents.py"

for _p in (str(PROJECT_ROOT), str(M8_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ============================================================================
# 加载 agents 模块（用 importlib 直接加载，绕开有问题的包导入链）
# ============================================================================

def _setup_package_hierarchy():
    """设置正确的包层次，让相对导入能工作，同时 mock 掉有问题的模块"""
    import types

    # 保存原始模块
    backups = {}

    def _ensure_package(name, path_list):
        """确保 sys.modules 中有一个包模块"""
        if name not in sys.modules:
            pkg = types.ModuleType(name)
            pkg.__path__ = path_list
            pkg.__package__ = name.rsplit('.', 1)[0] if '.' in name else ''
            sys.modules[name] = pkg
            backups[name] = None  # 标记为新增的

    # 设置 backend 包
    _ensure_package('backend', [str(M8_ROOT / 'backend')])

    # 设置 backend.routers 包（但 mock 掉其 __init__.py 的内容）
    routers_pkg = types.ModuleType('backend.routers')
    routers_pkg.__path__ = [str(M8_ROOT / 'backend' / 'routers')]
    routers_pkg.__package__ = 'backend'
    sys.modules['backend.routers'] = routers_pkg
    backups['backend.routers'] = None

    # 设置 backend.routers.business 包
    business_pkg = types.ModuleType('backend.routers.business')
    business_pkg.__path__ = [str(M8_ROOT / 'backend' / 'routers' / 'business')]
    business_pkg.__package__ = 'backend.routers'
    sys.modules['backend.routers.business'] = business_pkg
    backups['backend.routers.business'] = None

    # Mock 掉有问题的模块（在相对导入链之外的）
    for mod_name in [
        'backend.models',
        'backend.models.base',
        'backend.services',
        'backend.routers.core',
        'backend.routers.core.registry',
        'backend.services.service_registry',
        'backend.services.backup_scheduler',
        'backend.models.backup_scheduler',
    ]:
        backups[mod_name] = sys.modules.get(mod_name)
        if mod_name not in sys.modules:
            m = MagicMock()
            m.__path__ = []  # 假装是包
            sys.modules[mod_name] = m

    return backups


def _load_agents_module():
    """加载 agents.py 模块，正确处理相对导入"""
    backups = _setup_package_hierarchy()

    # 正常导入 agents 模块（通过包路径）
    import backend.routers.business.agents as agents_mod

    return agents_mod, backups


@pytest.fixture(scope="session")
def agents_mod():
    """会话级 agents 模块"""
    module, mock_backups = _load_agents_module()
    yield module
    # 清理
    sys.modules.pop("agents_module", None)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_httpx_client():
    """Mock httpx.AsyncClient"""
    client = MagicMock()
    client.request = AsyncMock()

    # 默认成功响应
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "code": 0,
        "message": "ok",
        "data": {"total": 0, "items": []},
    }
    mock_response.raise_for_status = MagicMock()
    client.request.return_value = mock_response

    return client


@pytest.fixture
def proxy_test_app(agents_mod, mock_httpx_client):
    """创建仅包含代理路由的测试应用"""
    with patch.dict(os.environ, {
        "AGENTS_PROXY_MODE": "proxy",
        "M1_BASE_URL": "http://localhost:8001",
        "M1_ADMIN_TOKEN": "test-m1-token",
    }):
        # 重新加载配置（因为环境变量变了）
        agents_mod.M1_BASE_URL = os.getenv("M1_BASE_URL", "http://localhost:8001")
        agents_mod.M1_ADMIN_TOKEN = os.getenv("M1_ADMIN_TOKEN", "")
        agents_mod.AGENTS_PROXY_MODE = os.getenv("AGENTS_PROXY_MODE", "proxy")

        # 注入 mock httpx client
        agents_mod._client = mock_httpx_client

        AgentRegisterRequest = agents_mod.AgentRegisterRequest
        KeySaveRequest = agents_mod.KeySaveRequest
        _proxy_to_m1 = agents_mod._proxy_to_m1
        _get_trace_id = agents_mod._get_trace_id

        app = FastAPI()
        r = APIRouter()

        @r.get("")
        async def list_agents(
            request: Request,
            agent_type: Optional[str] = Query(None),
            status: Optional[str] = Query(None),
        ):
            params = {}
            if agent_type:
                params["agent_type"] = agent_type
            if status:
                params["status"] = status
            return await _proxy_to_m1(
                method="GET",
                path="/api/agents",
                params=params if params else None,
                trace_id=_get_trace_id(request),
            )

        @r.post("/register")
        async def register_agent(request: Request, req: AgentRegisterRequest):
            return await _proxy_to_m1(
                method="POST",
                path="/api/agents/register",
                json_data=req.model_dump(),
                trace_id=_get_trace_id(request),
            )

        @r.delete("/{agent_id}")
        async def delete_agent(request: Request, agent_id: str):
            return await _proxy_to_m1(
                method="DELETE",
                path=f"/api/agents/{agent_id}",
                trace_id=_get_trace_id(request),
            )

        @r.get("/keys")
        async def list_keys(request: Request):
            return await _proxy_to_m1(
                method="GET",
                path="/api/agents/keys",
                trace_id=_get_trace_id(request),
            )

        @r.post("/keys")
        async def save_key(request: Request, req: KeySaveRequest):
            return await _proxy_to_m1(
                method="POST",
                path="/api/agents/keys",
                json_data=req.model_dump(),
                trace_id=_get_trace_id(request),
            )

        @r.delete("/keys/{provider}")
        async def delete_key(request: Request, provider: str):
            return await _proxy_to_m1(
                method="DELETE",
                path=f"/api/agents/keys/{provider}",
                trace_id=_get_trace_id(request),
            )

        @r.get("/keys/providers")
        async def list_providers(request: Request):
            return await _proxy_to_m1(
                method="GET",
                path="/api/agents/keys/providers",
                trace_id=_get_trace_id(request),
            )

        app.include_router(r, prefix="/api/agents")

        yield app, mock_httpx_client


@pytest.fixture
def client(proxy_test_app):
    """测试客户端"""
    app, mock_http = proxy_test_app
    with TestClient(app) as c:
        yield c, mock_http


# ============================================================================
# 测试用例
# ============================================================================

class TestProxyForwarding:
    """代理转发正确性测试（3个核心用例）"""

    def test_list_agents_proxies_to_m1(self, client):
        """测试 Agent 列表请求正确转发到 M1"""
        c, mock_http = client

        mock_http.request.return_value.json.return_value = {
            "code": 0,
            "message": "ok",
            "data": {
                "total": 3,
                "items": [
                    {"agent_id": "a1", "display_name": "Agent 1"},
                    {"agent_id": "a2", "display_name": "Agent 2"},
                    {"agent_id": "a3", "display_name": "Agent 3"},
                ],
            },
        }

        response = c.get("/api/agents")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] == 3

        mock_http.request.assert_called_once()
        call_kwargs = mock_http.request.call_args
        assert call_kwargs.kwargs["method"] == "GET"
        assert call_kwargs.kwargs["url"] == "/api/agents"

    def test_register_agent_proxies_payload(self, client):
        """测试 Agent 注册请求正确转发 payload 到 M1"""
        c, mock_http = client

        mock_http.request.return_value.json.return_value = {
            "code": 0,
            "message": "Agent 注册成功",
            "data": {"agent_id": "new-agent-001", "display_name": "My Agent"},
        }

        payload = {
            "display_name": "My Agent",
            "provider": "custom",
            "agent_type": "llm",
        }
        response = c.post("/api/agents/register", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

        call_kwargs = mock_http.request.call_args
        assert call_kwargs.kwargs["method"] == "POST"
        assert call_kwargs.kwargs["url"] == "/api/agents/register"
        assert call_kwargs.kwargs["json"]["display_name"] == "My Agent"
        assert call_kwargs.kwargs["json"]["provider"] == "custom"

    def test_delete_agent_proxies_with_id(self, client):
        """测试 Agent 删除请求正确携带 agent_id"""
        c, mock_http = client

        mock_http.request.return_value.json.return_value = {
            "code": 0,
            "message": "Agent 删除成功",
            "data": None,
        }

        response = c.delete("/api/agents/test-agent-123")
        assert response.status_code == 200

        call_kwargs = mock_http.request.call_args
        assert call_kwargs.kwargs["method"] == "DELETE"
        assert call_kwargs.kwargs["url"] == "/api/agents/test-agent-123"


class TestTraceIdPassthrough:
    """trace_id 透传测试（2个用例）"""

    def test_trace_id_header_passed(self, client):
        """测试 X-Trace-Id 请求头正确透传到 M1"""
        c, mock_http = client

        mock_http.request.return_value.json.return_value = {
            "code": 0,
            "message": "ok",
            "data": {"total": 0, "items": []},
        }

        trace_id = "trace-abc123-test"
        response = c.get(
            "/api/agents",
            headers={"X-Trace-Id": trace_id},
        )
        assert response.status_code == 200

        call_kwargs = mock_http.request.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("X-Trace-Id") == trace_id

    def test_no_trace_id_when_not_provided(self, client):
        """测试未提供 trace_id 时不添加该头"""
        c, mock_http = client

        mock_http.request.return_value.json.return_value = {
            "code": 0,
            "message": "ok",
            "data": {"total": 0, "items": []},
        }

        response = c.get("/api/agents")
        assert response.status_code == 200

        call_kwargs = mock_http.request.call_args
        headers = call_kwargs.kwargs.get("headers")
        if headers is not None:
            assert "X-Trace-Id" not in headers


class TestErrorHandling:
    """错误处理测试（4个用例）"""

    def test_connection_error_returns_502(self, client):
        """测试 M1 连接失败时返回 502 友好错误"""
        c, mock_http = client

        import httpx
        mock_http.request.side_effect = httpx.ConnectError("Connection refused")

        response = c.get("/api/agents")
        assert response.status_code == 502
        body = response.json()
        assert "M1 Agent Hub" in body["detail"]

    def test_timeout_error_returns_502(self, client):
        """测试 M1 超时时返回 502 错误"""
        c, mock_http = client

        import httpx
        mock_http.request.side_effect = httpx.TimeoutException("Request timed out")

        response = c.get("/api/agents")
        assert response.status_code == 502
        body = response.json()
        assert "M1 Agent Hub" in body["detail"]

    def test_m1_returns_404_proxies_correctly(self, client):
        """测试 M1 返回 404 时正确处理为 502"""
        c, mock_http = client

        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Not found"}
        mock_http.request.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=MagicMock(),
            response=mock_response,
        )

        response = c.delete("/api/agents/nonexistent")
        assert response.status_code == 502
        body = response.json()
        assert "M1 Agent Hub 返回错误" in body["detail"]
        assert "404" in body["detail"]

    def test_invalid_payload_returns_422(self, client):
        """测试无效请求体时 FastAPI 返回 422（代理层验证）"""
        c, mock_http = client

        # 缺少必填字段 provider
        payload = {"api_key": "sk-test"}
        response = c.post("/api/agents/keys", json=payload)
        assert response.status_code == 422
        mock_http.request.assert_not_called()


class TestProxyConfiguration:
    """代理配置测试（3个用例）"""

    def test_default_proxy_mode(self, agents_mod):
        """测试默认代理模式配置"""
        assert agents_mod.AGENTS_PROXY_MODE in ("proxy", "local")

    def test_m1_base_url_default(self, agents_mod):
        """测试 M1 默认地址配置"""
        assert agents_mod.M1_BASE_URL
        assert agents_mod.M1_BASE_URL.startswith("http")

    def test_proxy_timeout_config(self, agents_mod):
        """测试代理超时配置有效"""
        assert agents_mod.PROXY_TIMEOUT > 0
        assert agents_mod.PROXY_TIMEOUT <= 120
