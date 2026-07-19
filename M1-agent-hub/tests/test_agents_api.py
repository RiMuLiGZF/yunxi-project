"""
Agent 管理 API 路由测试（M1 Agent Hub）

测试迁移到 M1 的 Agent 管理和密钥管理 API 路由。
所有测试使用 mock，不依赖真实外部服务，不依赖 shared_models 真实导入。

测试用例（至少 8 个）：
1. Agent 列表
2. Agent 注册
3. Agent 删除
4. Agent 健康检查
5. 密钥列表
6. 密钥保存
7. 密钥删除
8. 服务商列表
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from fastapi import FastAPI, APIRouter
from fastapi.testclient import TestClient

# 路径设置
_MODULE_SRC = Path(__file__).resolve().parents[1] / "src"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_MODULE_SRC), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ============================================================================
# Mock shared_models（项目遗留问题：models/ 目录不存在）
# ============================================================================

@pytest.fixture(autouse=True)
def mock_shared_models():
    """Mock shared_models 模块，避免导入不存在的 models.base"""
    mock_mod = MagicMock()

    class MockEnum:
        def __init__(self, value):
            self.value = value

        def __eq__(self, other):
            if isinstance(other, MockEnum):
                return self.value == other.value
            return self.value == other

        def __hash__(self):
            return hash(self.value)

        def __str__(self):
            return self.value

    class ExternalAgentType:
        LLM = MockEnum("llm")
        CODE = MockEnum("code")
        VOICE = MockEnum("voice")

        def __new__(cls, val):
            if val == "llm":
                return cls.LLM
            if val == "code":
                return cls.CODE
            if val == "voice":
                return cls.VOICE
            raise ValueError(f"Invalid agent type: {val}")

    class AgentPrivacyLevel:
        STANDARD = MockEnum("standard")
        ENHANCED = MockEnum("enhanced")
        LOCAL_ONLY = MockEnum("local_only")

        def __new__(cls, val):
            if val == "standard":
                return cls.STANDARD
            if val == "enhanced":
                return cls.ENHANCED
            if val == "local_only":
                return cls.LOCAL_ONLY
            raise ValueError(f"Invalid privacy level: {val}")

    class ConnectionType:
        API_KEY = MockEnum("api_key")
        LOCAL = MockEnum("local")
        OAUTH = MockEnum("oauth")

        def __new__(cls, val):
            if val == "api_key":
                return cls.API_KEY
            if val == "local":
                return cls.LOCAL
            if val == "oauth":
                return cls.OAUTH
            raise ValueError(f"Invalid connection type: {val}")

    class LicenseType:
        MIT = MockEnum("MIT")
        APACHE = MockEnum("Apache-2.0")
        OTHER = MockEnum("other")

        def __new__(cls, val):
            val_lower = val.lower() if isinstance(val, str) else str(val).lower()
            if "mit" in val_lower:
                return cls.MIT
            if "apache" in val_lower:
                return cls.APACHE
            return cls.OTHER

    class ExternalAgentProfile:
        def __init__(self, **kwargs):
            self.agent_id = kwargs.get("agent_id", "")
            self.display_name = kwargs.get("display_name", "")
            self.provider = kwargs.get("provider", "")
            self.agent_type = kwargs.get("agent_type", ExternalAgentType.LLM)
            self.capabilities = kwargs.get("capabilities", [])
            self.description = kwargs.get("description", "")
            self.status = kwargs.get("status", "active")
            self.privacy_level = kwargs.get("privacy_level", AgentPrivacyLevel.STANDARD)
            self.connection_type = kwargs.get("connection_type", ConnectionType.API_KEY)
            self.config = kwargs.get("config", {})
            self.license = kwargs.get("license", LicenseType.MIT)
            self.created_at = kwargs.get("created_at", 0)
            self.updated_at = kwargs.get("updated_at", 0)
            self.last_health_check = kwargs.get("last_health_check", 0)
            self.cost_model = kwargs.get("cost_model", None)

    mock_mod.ExternalAgentProfile = ExternalAgentProfile
    mock_mod.ExternalAgentType = ExternalAgentType
    mock_mod.AgentPrivacyLevel = AgentPrivacyLevel
    mock_mod.ConnectionType = ConnectionType
    mock_mod.LicenseType = LicenseType

    with patch.dict(sys.modules, {
        'shared_models': mock_mod,
        'models': MagicMock(),
        'models.base': MagicMock(),
        'models.enums': MagicMock(),
        'models.task': MagicMock(),
        'models.agent': MagicMock(),
        'models.team': MagicMock(),
        'models.federation': MagicMock(),
        'models.message': MagicMock(),
        'models.common': MagicMock(),
        'models.config': MagicMock(),
        'models.error_codes': MagicMock(),
    }):
        yield mock_mod


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_registry():
    """Mock ExternalAgentRegistry（用于注入到 agents 模块）"""
    reg = MagicMock()

    # list_agents
    reg.list_agents.return_value = []

    # register_agent
    from shared_models import ExternalAgentProfile, ExternalAgentType, AgentPrivacyLevel, ConnectionType, LicenseType
    mock_profile = ExternalAgentProfile(
        agent_id="test-agent-001",
        display_name="Test Agent",
        provider="test-provider",
        agent_type=ExternalAgentType.LLM,
        capabilities=["text_generation"],
        description="Test agent",
        status="active",
        privacy_level=AgentPrivacyLevel.STANDARD,
        connection_type=ConnectionType.API_KEY,
        config={"mode": "api"},
        license=LicenseType.MIT,
    )
    reg.register_agent.return_value = mock_profile

    # delete_agent
    reg.delete_agent.return_value = True

    # check_health
    reg.check_health = AsyncMock(return_value={
        "healthy": True,
        "latency_ms": 120,
        "status": "active",
    })

    # get_agent
    reg.get_agent.return_value = mock_profile

    # update_agent
    reg.update_agent.return_value = True

    # stats
    reg.stats.return_value = {
        "total": 5,
        "by_type": {"llm": 3, "code": 2},
        "by_status": {"active": 4, "inactive": 1},
        "by_provider": {"openai": 2, "anthropic": 3},
    }

    return reg


@pytest.fixture
def mock_key_mgr():
    """Mock APIKeyManager（用于注入到 agents 模块）"""
    km = MagicMock()

    km.list_keys.return_value = [
        {"provider": "openai", "display_name": "OpenAI", "key_preview": "sk-***...abcd",
         "base_url": "https://api.openai.com/v1", "model": "gpt-4o", "updated_at": 1234567890},
        {"provider": "deepseek", "display_name": "DeepSeek", "key_preview": "sk-***...wxyz",
         "base_url": "https://api.deepseek.com/v1", "model": "deepseek-coder", "updated_at": 1234567891},
    ]

    km.add_key.return_value = {
        "success": True, "provider": "openai", "display_name": "OpenAI",
        "key_preview": "sk-***...abcd", "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o", "action": "added",
    }

    km.remove_key.return_value = {"success": True, "provider": "openai"}

    km.health_check = AsyncMock(return_value={
        "provider": "openai", "healthy": True, "latency_ms": 150,
        "models": ["gpt-4o", "gpt-4"],
    })

    km.health_check_all = AsyncMock(return_value={
        "total": 2, "healthy": 2, "unhealthy": 0,
        "results": {
            "openai": {"healthy": True, "latency_ms": 150},
            "deepseek": {"healthy": True, "latency_ms": 200},
        },
    })

    km.list_supported_providers.return_value = [
        {"provider": "openai", "display_name": "OpenAI",
         "default_base_url": "https://api.openai.com/v1", "default_model": "gpt-4o"},
        {"provider": "anthropic", "display_name": "Anthropic",
         "default_base_url": "https://api.anthropic.com", "default_model": "claude-3-5-sonnet-20240620"},
        {"provider": "deepseek", "display_name": "DeepSeek",
         "default_base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-coder"},
    ]

    km.stats.return_value = {"total_keys": 2, "providers": ["openai", "deepseek"]}

    return km


@pytest.fixture
def agents_app(mock_registry, mock_key_mgr):
    """创建挂载 agents 路由的 FastAPI 应用，mock 掉核心依赖"""
    # 导入模块并直接设置模块级变量
    import src.api.agents as agents_mod

    # 保存原始值
    orig_registry = agents_mod._external_registry
    orig_key_manager = agents_mod._key_manager

    # 设置 mock 值
    agents_mod._external_registry = mock_registry
    agents_mod._key_manager = mock_key_mgr

    try:
        from src.api.agents import (
            list_agents, register_agent, delete_agent,
            agent_health_check, toggle_agent, agent_stats,
            list_keys, save_key, delete_key,
            key_health_check, key_health_check_all,
            list_supported_providers,
        )

        app = FastAPI()
        r = APIRouter()
        r.add_api_route("", list_agents, methods=["GET"])
        r.add_api_route("/register", register_agent, methods=["POST"])
        r.add_api_route("/{agent_id}", delete_agent, methods=["DELETE"])
        r.add_api_route("/{agent_id}/health-check", agent_health_check, methods=["POST"])
        r.add_api_route("/{agent_id}/toggle", toggle_agent, methods=["POST"])
        r.add_api_route("/stats", agent_stats, methods=["GET"])
        r.add_api_route("/keys", list_keys, methods=["GET"])
        r.add_api_route("/keys", save_key, methods=["POST"])
        r.add_api_route("/keys/{provider}", delete_key, methods=["DELETE"])
        r.add_api_route("/keys/{provider}/health-check", key_health_check, methods=["POST"])
        r.add_api_route("/keys/health-check-all", key_health_check_all, methods=["POST"])
        r.add_api_route("/keys/providers", list_supported_providers, methods=["GET"])
        app.include_router(r, prefix="/api/agents")

        yield app
    finally:
        # 恢复原始值
        agents_mod._external_registry = orig_registry
        agents_mod._key_manager = orig_key_manager


@pytest.fixture
def client(agents_app):
    """测试客户端"""
    with TestClient(agents_app) as c:
        yield c


# ============================================================================
# 测试用例
# ============================================================================

class TestAgentList:
    """Agent 列表接口测试"""

    def test_list_agents_empty(self, client, mock_registry):
        """测试获取空 Agent 列表"""
        response = client.get("/api/agents")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] == 0
        assert data["data"]["items"] == []
        mock_registry.list_agents.assert_called_once()

    def test_list_agents_with_status_filter(self, client, mock_registry):
        """测试带状态筛选的 Agent 列表"""
        response = client.get("/api/agents", params={"status": "active"})
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        call_kwargs = mock_registry.list_agents.call_args
        assert call_kwargs.kwargs.get("status") == "active"


class TestAgentRegister:
    """Agent 注册接口测试"""

    def test_register_agent_success(self, client, mock_registry):
        """测试成功注册 Agent"""
        payload = {
            "display_name": "Test Agent",
            "provider": "test-provider",
            "agent_type": "llm",
            "capabilities": ["text_generation"],
            "mode": "api",
            "api_provider": "openai",
            "model_name": "gpt-4o",
            "description": "Test agent",
            "privacy_level": "standard",
            "connection_type": "api_key",
            "license": "MIT",
        }
        response = client.post("/api/agents/register", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["message"] == "Agent 注册成功"
        assert data["data"]["agent_id"] == "test-agent-001"
        assert data["data"]["display_name"] == "Test Agent"
        mock_registry.register_agent.assert_called_once()

    def test_register_agent_missing_required(self, client):
        """测试缺少必填字段时返回 422"""
        response = client.post("/api/agents/register", json={"provider": "test"})
        assert response.status_code == 422


class TestAgentDelete:
    """Agent 删除接口测试"""

    def test_delete_agent_success(self, client, mock_registry):
        """测试成功删除 Agent"""
        response = client.delete("/api/agents/test-agent-001")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "删除成功" in data["message"]
        mock_registry.delete_agent.assert_called_once_with("test-agent-001")

    def test_delete_agent_not_found(self, client, mock_registry):
        """测试删除不存在的 Agent 返回 404"""
        mock_registry.delete_agent.return_value = False
        response = client.delete("/api/agents/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 404
        assert "未找到" in data["message"]


class TestAgentHealthCheck:
    """Agent 健康检查接口测试"""

    def test_agent_health_check_success(self, client, mock_registry):
        """测试 Agent 健康检查成功"""
        response = client.post("/api/agents/test-agent-001/health-check")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["healthy"] is True
        assert data["data"]["latency_ms"] == 120
        mock_registry.check_health.assert_called_once_with("test-agent-001")


class TestKeyList:
    """密钥列表接口测试"""

    def test_list_keys(self, client, mock_key_mgr):
        """测试获取密钥列表"""
        response = client.get("/api/agents/keys")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] == 2
        assert len(data["data"]["items"]) == 2
        assert data["data"]["items"][0]["provider"] == "openai"
        # 验证不返回明文密钥
        assert "api_key" not in data["data"]["items"][0]
        mock_key_mgr.list_keys.assert_called_once()


class TestKeySave:
    """密钥保存接口测试"""

    def test_save_key_success(self, client, mock_key_mgr):
        """测试成功保存密钥"""
        payload = {
            "provider": "openai",
            "api_key": "sk-test-1234567890abcdef",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
        }
        response = client.post("/api/agents/keys", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "成功" in data["message"]
        assert data["data"]["provider"] == "openai"
        mock_key_mgr.add_key.assert_called_once_with(
            provider="openai",
            api_key="sk-test-1234567890abcdef",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
        )

    def test_save_key_missing_provider(self, client):
        """测试缺少 provider 时返回 422"""
        response = client.post("/api/agents/keys", json={"api_key": "sk-test"})
        assert response.status_code == 422


class TestKeyDelete:
    """密钥删除接口测试"""

    def test_delete_key_success(self, client, mock_key_mgr):
        """测试成功删除密钥"""
        response = client.delete("/api/agents/keys/openai")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "已删除" in data["message"]
        mock_key_mgr.remove_key.assert_called_once_with("openai")

    def test_delete_key_not_found(self, client, mock_key_mgr):
        """测试删除不存在的密钥返回 404"""
        mock_key_mgr.remove_key.return_value = {"success": False, "error": "密钥不存在"}
        response = client.delete("/api/agents/keys/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 404


class TestProvidersList:
    """服务商列表接口测试"""

    def test_list_supported_providers(self, client, mock_key_mgr):
        """测试获取支持的服务商列表"""
        response = client.get("/api/agents/keys/providers")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] == 3
        providers = [p["provider"] for p in data["data"]["items"]]
        assert "openai" in providers
        assert "anthropic" in providers
        assert "deepseek" in providers
        mock_key_mgr.list_supported_providers.assert_called_once()


class TestAgentStats:
    """Agent 统计接口测试"""

    def test_agent_stats(self, client, mock_registry, mock_key_mgr):
        """测试获取 Agent 统计信息"""
        response = client.get("/api/agents/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] == 5
        assert "by_type" in data["data"]
        assert "keys_total" in data["data"]
        assert data["data"]["keys_total"] == 2
        mock_registry.stats.assert_called_once()
        mock_key_mgr.stats.assert_called_once()


class TestAgentToggle:
    """Agent 启用/禁用接口测试"""

    def test_toggle_agent_enable(self, client, mock_registry):
        """测试启用 Agent"""
        response = client.post("/api/agents/test-agent-001/toggle", json={"enabled": True})
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["enabled"] is True
        assert data["data"]["status"] == "active"
        mock_registry.update_agent.assert_called_once_with("test-agent-001", status="active")

    def test_toggle_agent_disable(self, client, mock_registry):
        """测试禁用 Agent"""
        response = client.post("/api/agents/test-agent-001/toggle", json={"enabled": False})
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["enabled"] is False
        assert data["data"]["status"] == "inactive"


class TestKeyHealthCheck:
    """密钥健康检查接口测试"""

    def test_key_health_check_single(self, client, mock_key_mgr):
        """测试单密钥健康检查"""
        response = client.post("/api/agents/keys/openai/health-check")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["provider"] == "openai"
        assert data["data"]["healthy"] is True

    def test_key_health_check_all(self, client, mock_key_mgr):
        """测试批量密钥健康检查"""
        response = client.post("/api/agents/keys/health-check-all")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] == 2
        assert data["data"]["healthy"] == 2


class TestM8Auth:
    """M8 Token 鉴权测试"""

    def test_auth_verify_correct_token(self, mock_shared_models):
        """测试正确 Token 通过验证"""
        with patch.dict(os.environ, {"M1_ADMIN_TOKEN": "test-secret-token"}):
            from src.api.agents import _verify_m8_token
            assert _verify_m8_token("test-secret-token") is True
            assert _verify_m8_token("wrong-token") is False
            assert _verify_m8_token("") is False

    def test_auth_bypassed_in_dev_mode(self, mock_shared_models):
        """测试未配置 Token 时开发模式免鉴权"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("M1_ADMIN_TOKEN", None)
            from src.api.agents import _verify_m8_token
            assert _verify_m8_token("") is True
            assert _verify_m8_token("anything") is True
