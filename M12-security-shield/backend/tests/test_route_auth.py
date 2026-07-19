"""
M12 安全盾 - 路由鉴权测试
验证 WAF、IP 控制、状态等模块的路由鉴权是否正常工作。

测试策略：
- 无 token 访问受保护路由应返回 401
- 有有效 token 访问应正常返回
- 健康检查等公共端点无需鉴权
- 低权限角色访问高权限接口应返回 403
"""

import os
import sys
import tempfile
from pathlib import Path
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

# ===========================================================================
# 测试环境初始化（必须在任何业务模块导入前完成）
# ===========================================================================

# 将 backend 目录加入 path
_current_dir = Path(__file__).resolve().parent
_backend_dir = _current_dir.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# 创建临时测试数据库文件（模块级别共享）
_fd, _test_db_path = tempfile.mkstemp(suffix=".db", prefix="m12_test_auth_")
os.close(_fd)

# 在导入任何业务模块前设置环境变量
os.environ["M12_JWT_SECRET"] = "test-secret-key-for-auth-testing-123456"
os.environ["M12_REQUIRE_SECURE_SECRET"] = "false"
os.environ["M12_ENV"] = "testing"
os.environ["M12_DB_PATH"] = _test_db_path


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(scope="module")
def client():
    """创建测试用的 FastAPI 客户端，数据库表已初始化"""
    # 现在才导入业务模块（确保环境变量已生效）
    from main import create_app
    from database import init_db, engine, Base

    # 确保所有模型都被加载（触发表创建）
    import models  # noqa: F401

    # 手动创建所有表
    Base.metadata.create_all(bind=engine)

    # 创建 app
    app = create_app()
    test_client = TestClient(app)

    yield test_client

    # 清理：关闭 engine
    engine.dispose()
    try:
        os.unlink(_test_db_path)
    except OSError:
        pass


@pytest.fixture(scope="module")
def admin_token():
    """生成管理员角色的有效 JWT Token"""
    from auth import create_access_token, ROLE_ADMIN

    token = create_access_token(
        data={
            "sub": "user_test_admin",
            "username": "test_admin",
            "roles": [ROLE_ADMIN],
            "scopes": ["*"],
        },
    )
    return token


@pytest.fixture(scope="module")
def viewer_token():
    """生成只读角色的有效 JWT Token"""
    from auth import create_access_token, ROLE_VIEWER

    token = create_access_token(
        data={
            "sub": "user_test_viewer",
            "username": "test_viewer",
            "roles": [ROLE_VIEWER],
            "scopes": ["waf:read", "ip:read", "audit:read", "dashboard:read"],
        },
    )
    return token


@pytest.fixture(scope="module")
def api_role_token():
    """生成 API 角色的低权限 Token（低于 viewer）"""
    from auth import create_access_token, ROLE_API

    token = create_access_token(
        data={
            "sub": "user_test_api",
            "username": "test_api",
            "roles": [ROLE_API],
            "scopes": [],
        },
    )
    return token


def auth_headers(token: str) -> dict:
    """生成带 Bearer Token 的请求头"""
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# 1. 健康检查 - 无需鉴权（3 个测试）
# ===========================================================================

class TestHealthCheckNoAuth:
    """健康检查端点无需鉴权"""

    def test_health_check_without_token(self, client):
        """健康检查无 token 也能访问"""
        response = client.get("/api/m12/status/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("code") == 0 or data.get("status") == "healthy" or "data" in data

    def test_health_check_with_token(self, client, viewer_token):
        """健康检查带 token 也正常返回"""
        response = client.get("/api/m12/status/health", headers=auth_headers(viewer_token))
        assert response.status_code == 200

    def test_health_deep_check_without_token(self, client):
        """深度健康检查无 token 也能访问"""
        response = client.get("/api/m12/status/health?deep=true")
        assert response.status_code == 200


# ===========================================================================
# 2. WAF 路由 - 无 token 返回 401（4 个测试）
# ===========================================================================

class TestWafRoutesNoAuth:
    """WAF 路由无 token 访问应返回 401"""

    def test_waf_status_without_token(self, client):
        """WAF 状态无 token 返回 401"""
        response = client.get("/api/m12/waf/status")
        assert response.status_code == 401

    def test_waf_rules_without_token(self, client):
        """WAF 规则列表无 token 返回 401"""
        response = client.get("/api/m12/waf/rules")
        assert response.status_code == 401

    def test_waf_stats_without_token(self, client):
        """WAF 统计无 token 返回 401"""
        response = client.get("/api/m12/waf/stats")
        assert response.status_code == 401

    def test_waf_toggle_without_token(self, client):
        """WAF 开关无 token 返回 401"""
        response = client.post("/api/m12/waf/toggle")
        assert response.status_code == 401


# ===========================================================================
# 3. WAF 路由 - 有 token 正常访问（3 个测试）
# ===========================================================================

class TestWafRoutesWithAuth:
    """WAF 路由有有效 token 正常访问"""

    def test_waf_status_with_viewer_token(self, client, viewer_token):
        """WAF 状态带 viewer token 正常返回"""
        response = client.get("/api/m12/waf/status", headers=auth_headers(viewer_token))
        assert response.status_code == 200
        data = response.json()
        assert "data" in data

    def test_waf_rules_with_viewer_token(self, client, viewer_token):
        """WAF 规则列表带 viewer token 正常返回"""
        response = client.get("/api/m12/waf/rules", headers=auth_headers(viewer_token))
        assert response.status_code == 200
        data = response.json()
        assert "data" in data

    def test_waf_stats_with_viewer_token(self, client, viewer_token):
        """WAF 统计带 viewer token 正常返回"""
        response = client.get("/api/m12/waf/stats", headers=auth_headers(viewer_token))
        assert response.status_code == 200
        data = response.json()
        assert "data" in data


# ===========================================================================
# 4. IP 控制路由 - 无 token 返回 401（3 个测试）
# ===========================================================================

class TestIpControlRoutesNoAuth:
    """IP 控制路由无 token 访问应返回 401"""

    def test_ip_check_without_token(self, client):
        """IP 检测无 token 返回 401"""
        response = client.get("/api/m12/ip/check", params={"ip_address": "127.0.0.1"})
        assert response.status_code == 401

    def test_ip_blacklist_without_token(self, client):
        """IP 黑名单无 token 返回 401"""
        response = client.get("/api/m12/ip/blacklist")
        assert response.status_code == 401

    def test_ip_stats_without_token(self, client):
        """IP 统计无 token 返回 401"""
        response = client.get("/api/m12/ip/stats")
        assert response.status_code == 401


# ===========================================================================
# 5. IP 控制路由 - 有 token 正常访问（3 个测试）
# ===========================================================================

class TestIpControlRoutesWithAuth:
    """IP 控制路由有有效 token 正常访问"""

    def test_ip_check_with_viewer_token(self, client, viewer_token):
        """IP 检测带 viewer token 正常返回"""
        response = client.get(
            "/api/m12/ip/check",
            params={"ip_address": "127.0.0.1"},
            headers=auth_headers(viewer_token),
        )
        assert response.status_code == 200
        data = response.json()
        assert "data" in data

    def test_ip_blacklist_with_viewer_token(self, client, viewer_token):
        """IP 黑名单带 viewer token 正常返回"""
        response = client.get(
            "/api/m12/ip/blacklist",
            headers=auth_headers(viewer_token),
        )
        assert response.status_code == 200
        data = response.json()
        assert "data" in data

    def test_ip_stats_with_viewer_token(self, client, viewer_token):
        """IP 统计带 viewer token 正常返回"""
        response = client.get(
            "/api/m12/ip/stats",
            headers=auth_headers(viewer_token),
        )
        assert response.status_code == 200
        data = response.json()
        assert "data" in data


# ===========================================================================
# 6. status.py 路由鉴权（3 个测试）
# ===========================================================================

class TestStatusRoutesAuth:
    """status.py 各路由鉴权验证"""

    def test_status_info_without_token(self, client):
        """模块信息无 token 可访问（公开端点）"""
        response = client.get("/api/m12/status/info")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data

    def test_status_overview_without_token(self, client):
        """服务概览无 token 返回 401（需鉴权）"""
        response = client.get("/api/m12/status/overview")
        assert response.status_code == 401

    def test_status_overview_with_viewer_token(self, client, viewer_token):
        """服务概览带 viewer token 正常返回"""
        response = client.get(
            "/api/m12/status/overview",
            headers=auth_headers(viewer_token),
        )
        assert response.status_code == 200
        data = response.json()
        assert "data" in data


# ===========================================================================
# 7. 角色权限验证 - 低权限访问高权限接口返回 403（2 个测试）
# ===========================================================================

class TestRoleBasedAccessControl:
    """基于角色的访问控制验证"""

    def test_waf_toggle_api_role_forbidden(self, client, api_role_token):
        """WAF 开关需要 admin，api 角色访问返回 403"""
        response = client.post(
            "/api/m12/waf/toggle",
            headers=auth_headers(api_role_token),
        )
        assert response.status_code == 403

    def test_status_config_viewer_forbidden(self, client, viewer_token):
        """系统配置需要 admin，viewer 角色访问返回 403"""
        response = client.get(
            "/api/m12/status/config",
            headers=auth_headers(viewer_token),
        )
        assert response.status_code == 403


# ===========================================================================
# 8. Token 有效性验证（2 个测试）
# ===========================================================================

class TestTokenValidity:
    """Token 有效性验证"""

    def test_invalid_token_returns_401(self, client):
        """无效 token 返回 401"""
        response = client.get(
            "/api/m12/waf/status",
            headers=auth_headers("invalid-token-string"),
        )
        assert response.status_code == 401

    def test_expired_token_returns_401(self, client):
        """过期 token 返回 401"""
        from auth import create_access_token, ROLE_VIEWER

        # 创建已过期的 token（过期时间设为过去时间）
        token = create_access_token(
            data={
                "sub": "user_expired",
                "username": "expired_user",
                "roles": [ROLE_VIEWER],
                "scopes": [],
            },
            expires_delta=timedelta(seconds=-10),
        )
        response = client.get(
            "/api/m12/waf/status",
            headers=auth_headers(token),
        )
        assert response.status_code == 401
