# -*- coding: utf-8 -*-
"""
Brain Agent 代理路由测试（M8 控制塔）

测试 M8 端的 Brain Agent 代理路由，验证：
1. 工具接口代理转发（请求正确转发到 M1）
2. Agent 接口代理转发
3. 多 Agent 接口代理转发
4. trace_id 透传（X-Trace-Id 头正确传递）
5. 错误处理（M1 不可用时返回友好错误）

所有测试使用 mock，不依赖真实外部服务。
测试直接用 importlib 加载 brain.py 文件，避免通过 backend.routers 包的链式导入问题。
"""

import os
import sys
import types
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from typing import Optional, Dict, Any

# 路径设置
M8_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = M8_ROOT.parent
BRAIN_PY = M8_ROOT / "backend" / "routers" / "business" / "brain.py"

for _p in (str(PROJECT_ROOT), str(M8_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ============================================================================
# 加载 brain 模块（用 importlib 直接加载，绕开有问题的包导入链）
# ============================================================================

def _setup_package_hierarchy():
    """设置正确的包层次，让相对导入能工作，同时 mock 掉有问题的模块"""
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

    # 设置 backend.routers 包
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

    # Mock 掉有问题的模块
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
            m.__path__ = []
            sys.modules[mod_name] = m

    return backups


def _load_brain_module():
    """加载 brain.py 模块，正确处理相对导入"""
    backups = _setup_package_hierarchy()

    # Mock schemas 模块中的 ApiResponse
    mock_schemas = types.ModuleType('backend.schemas')
    mock_schemas.__path__ = [str(M8_ROOT / 'backend' / 'schemas')]
    backups['backend.schemas'] = sys.modules.get('backend.schemas')

    # 创建一个简单的 ApiResponse 类
    class _ApiResponse(BaseModel):
        code: int = 0
        message: str = "ok"
        data: Optional[Any] = None
        trace_id: Optional[str] = None
        timestamp: float = 0.0

        @classmethod
        def success(cls, data=None, message="ok", trace_id=None):
            import time
            return cls(code=0, message=message, data=data, trace_id=trace_id, timestamp=time.time())

        @classmethod
        def error(cls, code, message, data=None, trace_id=None):
            import time
            return cls(code=code, message=message, data=data, trace_id=trace_id, timestamp=time.time())

    mock_schemas.ApiResponse = _ApiResponse
    sys.modules['backend.schemas'] = mock_schemas

    # Mock auth 模块中的 get_current_user
    mock_auth = types.ModuleType('backend.auth')
    mock_auth.__path__ = [str(M8_ROOT / 'backend')]
    backups['backend.auth'] = sys.modules.get('backend.auth')

    async def _mock_get_current_user():
        return {"user_id": "test_user", "username": "testuser"}

    mock_auth.get_current_user = _mock_get_current_user
    sys.modules['backend.auth'] = mock_auth

    # Mock shared.core.observability
    mock_observability = types.ModuleType('shared.core.observability')
    mock_observability.__path__ = []
    backups['shared.core.observability'] = sys.modules.get('shared.core.observability')

    def _mock_get_logger(name):
        import logging
        return logging.getLogger(name)

    mock_observability.get_logger = _mock_get_logger
    sys.modules['shared.core.observability'] = mock_observability

    # Mock shared.core 包
    if 'shared.core' not in sys.modules:
        mock_shared_core = types.ModuleType('shared.core')
        mock_shared_core.__path__ = []
        sys.modules['shared.core'] = mock_shared_core
        backups['shared.core'] = None

    # Mock shared 包
    if 'shared' not in sys.modules:
        mock_shared = types.ModuleType('shared')
        mock_shared.__path__ = [str(PROJECT_ROOT / 'shared')]
        sys.modules['shared'] = mock_shared
        backups['shared'] = None

    # Mock shared.business 包中的模块（brain.py 顶部导入的）
    for mod_name in [
        'shared.business',
        'shared.business.rag_knowledge',
        'shared.business.long_term_memory',
        'shared.business.autonomous_learning',
        'shared.business.personality_engine',
        'shared.business.skill_evolution',
        'shared.business.tool_system',
        'shared.business.agent_engine',
    ]:
        backups[mod_name] = sys.modules.get(mod_name)
        if mod_name not in sys.modules:
            m = MagicMock()
            if '.' in mod_name.rsplit('.', 1)[0]:
                m.__path__ = []
            sys.modules[mod_name] = m

    # 设置代理模式环境变量
    os.environ['BRAIN_AGENT_PROXY_MODE'] = 'proxy'

    # 加载 brain 模块
    spec = importlib.util.spec_from_file_location(
        "backend.routers.business.brain",
        BRAIN_PY,
    )
    brain_mod = importlib.util.module_from_spec(spec)
    sys.modules['backend.routers.business.brain'] = brain_mod
    spec.loader.exec_module(brain_mod)

    return brain_mod, backups


@pytest.fixture(scope="module")
def brain_module():
    """加载 brain 模块（模块级 fixture，只加载一次）"""
    mod, backups = _load_brain_module()
    yield mod
    # 清理
    for mod_name, original in reversed(backups.items()):
        if original is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = original


@pytest.fixture
def app(brain_module):
    """创建 FastAPI 测试应用，注册 brain 路由"""
    app = FastAPI()
    app.include_router(brain_module.router, prefix="/api/brain")
    return app


@pytest.fixture
def client(app):
    """创建测试客户端"""
    with TestClient(app) as test_client:
        yield test_client


# ============================================================================
# Mock httpx 客户端
# ============================================================================

@pytest.fixture
def mock_httpx_client(brain_module):
    """Mock httpx 客户端，捕获所有请求"""
    mock_client = MagicMock()
    # 重置全局客户端
    brain_module._brain_agent_client = None

    original_get_client = brain_module._get_brain_agent_client

    def _mock_get_client():
        return mock_client

    with patch.object(brain_module, '_get_brain_agent_client', _mock_get_client):
        yield mock_client

    # 恢复
    brain_module._brain_agent_client = None


def _make_mock_response(json_data, status_code=200):
    """创建 mock httpx 响应"""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def _make_mock_error_response(status_code=500, detail="Internal Server Error"):
    """创建 mock 错误响应"""
    import httpx
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {"detail": detail}
    error = httpx.HTTPStatusError(
        "Error",
        request=MagicMock(),
        response=mock_resp,
    )
    return error


# ============================================================================
# 工具接口代理测试
# ============================================================================

class TestToolProxy:
    """测试工具接口代理转发"""

    def test_tools_list_proxy(self, client, mock_httpx_client):
        """工具列表接口正确转发到 M1"""
        mock_data = {
            "code": 0,
            "message": "ok",
            "data": {
                "tools": [{"name": "calculator", "description": "Calc"}],
                "total": 1,
                "categories": ["calculation"],
            },
        }
        mock_httpx_client.request = AsyncMock(return_value=_make_mock_response(mock_data))

        response = client.get("/api/brain/tools/list")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] == 1

        # 验证请求被正确转发
        mock_httpx_client.request.assert_called_once()
        call_kwargs = mock_httpx_client.request.call_args
        assert call_kwargs[1]["method"] == "GET"
        assert "/api/brain/tools/list" in call_kwargs[1]["url"]

    def test_tools_call_proxy(self, client, mock_httpx_client):
        """工具调用接口正确转发到 M1"""
        mock_data = {
            "code": 0,
            "message": "ok",
            "data": {"success": True, "output": "42", "tool_name": "calculator"},
        }
        mock_httpx_client.request = AsyncMock(return_value=_make_mock_response(mock_data))

        response = client.post(
            "/api/brain/tools/call/calculator",
            json={"expression": "6 * 7"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["success"] is True

        # 验证请求被正确转发
        mock_httpx_client.request.assert_called_once()
        call_kwargs = mock_httpx_client.request.call_args
        assert call_kwargs[1]["method"] == "POST"
        assert "calculator" in call_kwargs[1]["url"]
        assert call_kwargs[1]["json"] == {"expression": "6 * 7"}


# ============================================================================
# Agent 接口代理测试
# ============================================================================

class TestAgentProxy:
    """测试 Agent 接口代理转发"""

    def test_agent_run_proxy(self, client, mock_httpx_client):
        """Agent 运行接口正确转发到 M1"""
        mock_data = {
            "code": 0,
            "message": "ok",
            "data": {
                "success": True,
                "answer": "The answer is 42",
                "total_steps": 3,
                "tools_used": ["calculator"],
            },
        }
        mock_httpx_client.request = AsyncMock(return_value=_make_mock_response(mock_data))

        response = client.post(
            "/api/brain/agent/run",
            json={"query": "What is the answer?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["success"] is True

        # 验证请求被正确转发
        mock_httpx_client.request.assert_called_once()
        call_kwargs = mock_httpx_client.request.call_args
        assert call_kwargs[1]["method"] == "POST"
        assert "/api/brain/agent/run" in call_kwargs[1]["url"]

    def test_agent_stats_proxy(self, client, mock_httpx_client):
        """Agent 统计接口正确转发到 M1"""
        mock_data = {
            "code": 0,
            "message": "ok",
            "data": {
                "stats": {"total_executions": 25},
                "recent_executions": [],
            },
        }
        mock_httpx_client.request = AsyncMock(return_value=_make_mock_response(mock_data))

        response = client.get("/api/brain/agent/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["stats"]["total_executions"] == 25


# ============================================================================
# 多 Agent 团队接口代理测试
# ============================================================================

class TestTeamProxy:
    """测试多 Agent 团队接口代理转发"""

    def test_team_query_proxy(self, client, mock_httpx_client):
        """团队查询接口正确转发到 M1"""
        mock_data = {
            "code": 0,
            "message": "ok",
            "data": {
                "success": True,
                "final_answer": "Based on research...",
                "agents_involved": ["研究员·知微"],
            },
        }
        mock_httpx_client.request = AsyncMock(return_value=_make_mock_response(mock_data))

        response = client.post(
            "/api/brain/team/query",
            json={"query": "Research AI"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["success"] is True

        # 验证请求被正确转发
        mock_httpx_client.request.assert_called_once()
        call_kwargs = mock_httpx_client.request.call_args
        assert call_kwargs[1]["method"] == "POST"
        assert "/api/brain/team/query" in call_kwargs[1]["url"]

    def test_team_profile_proxy(self, client, mock_httpx_client):
        """团队简介接口正确转发到 M1"""
        mock_data = {
            "code": 0,
            "message": "ok",
            "data": {"team_name": "云汐智囊团", "team_size": 5},
        }
        mock_httpx_client.request = AsyncMock(return_value=_make_mock_response(mock_data))

        response = client.get("/api/brain/team/profile")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["team_name"] == "云汐智囊团"


# ============================================================================
# trace_id 透传测试
# ============================================================================

class TestTraceIdPassthrough:
    """测试 trace_id 透传"""

    def test_trace_id_is_passed_to_m1(self, client, mock_httpx_client):
        """X-Trace-Id 头正确透传到 M1"""
        mock_data = {"code": 0, "message": "ok", "data": {}}
        mock_httpx_client.request = AsyncMock(return_value=_make_mock_response(mock_data))

        trace_id = "test-trace-id-12345"
        response = client.get(
            "/api/brain/tools/list",
            headers={"X-Trace-Id": trace_id},
        )
        assert response.status_code == 200

        # 验证 trace_id 被正确传递
        mock_httpx_client.request.assert_called_once()
        call_kwargs = mock_httpx_client.request.call_args
        headers = call_kwargs[1].get("headers", {})
        assert headers.get("X-Trace-Id") == trace_id

    def test_lowercase_trace_id_header(self, client, mock_httpx_client):
        """小写 x-trace-id 头也能正确透传"""
        mock_data = {"code": 0, "message": "ok", "data": {}}
        mock_httpx_client.request = AsyncMock(return_value=_make_mock_response(mock_data))

        trace_id = "lowercase-trace-id"
        response = client.get(
            "/api/brain/tools/list",
            headers={"x-trace-id": trace_id},
        )
        assert response.status_code == 200

        mock_httpx_client.request.assert_called_once()
        call_kwargs = mock_httpx_client.request.call_args
        headers = call_kwargs[1].get("headers", {})
        assert headers.get("X-Trace-Id") == trace_id

    def test_no_trace_id_when_not_provided(self, client, mock_httpx_client):
        """未提供 trace_id 时不添加该头"""
        mock_data = {"code": 0, "message": "ok", "data": {}}
        mock_httpx_client.request = AsyncMock(return_value=_make_mock_response(mock_data))

        response = client.get("/api/brain/tools/list")
        assert response.status_code == 200

        mock_httpx_client.request.assert_called_once()
        call_kwargs = mock_httpx_client.request.call_args
        headers = call_kwargs[1].get("headers")
        # 没有提供 trace_id 时，headers 为 None 或不含 X-Trace-Id
        if headers is not None:
            assert "X-Trace-Id" not in headers


# ============================================================================
# 错误处理测试
# ============================================================================

class TestErrorHandling:
    """测试代理层错误处理"""

    def test_m1_connection_error(self, client, mock_httpx_client):
        """M1 连接失败时返回友好错误（502）"""
        import httpx
        mock_httpx_client.request = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        response = client.get("/api/brain/tools/list")
        # 连接错误应返回 502
        assert response.status_code == 502
        data = response.json()
        assert "M1" in data.get("detail", "") or "连接失败" in data.get("detail", "")

    def test_m1_server_error(self, client, mock_httpx_client):
        """M1 返回 500 错误时返回友好错误（502）"""
        mock_httpx_client.request = AsyncMock(
            side_effect=_make_mock_error_response(500, "Internal Server Error")
        )

        response = client.get("/api/brain/tools/stats")
        assert response.status_code == 502
        data = response.json()
        assert "M1" in data.get("detail", "")

    def test_m1_not_found(self, client, mock_httpx_client):
        """M1 返回 404 时返回友好错误（502）"""
        mock_httpx_client.request = AsyncMock(
            side_effect=_make_mock_error_response(404, "Not Found")
        )

        response = client.post(
            "/api/brain/tools/call/nonexistent_tool",
            json={},
        )
        assert response.status_code == 502
        data = response.json()
        assert "M1" in data.get("detail", "")

    def test_timeout_error(self, client, mock_httpx_client):
        """M1 超时返回友好错误（502）"""
        import httpx
        mock_httpx_client.request = AsyncMock(
            side_effect=httpx.TimeoutException("Request timed out")
        )

        response = client.post(
            "/api/brain/agent/run",
            json={"query": "test"},
        )
        assert response.status_code == 502
        data = response.json()
        assert "连接失败" in data.get("detail", "") or "M1" in data.get("detail", "")


# ============================================================================
# 代理模式开关测试
# ============================================================================

class TestProxyModeConfig:
    """测试代理模式配置"""

    def test_default_mode_is_proxy(self, brain_module):
        """默认代理模式为 proxy"""
        assert brain_module.BRAIN_AGENT_PROXY_MODE == "proxy"

    def test_m1_base_url_default(self, brain_module):
        """默认 M1 地址正确"""
        assert brain_module.M1_BASE_URL == "http://localhost:8001"

    def test_proxy_timeout_default(self, brain_module):
        """默认超时时间正确"""
        assert brain_module.BRAIN_AGENT_PROXY_TIMEOUT == 30.0
