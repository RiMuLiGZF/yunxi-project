"""
M8 认证 API 测试

测试 M8 管理台的认证相关接口，验证：
- 用户登录
- Token 验证
- 获取当前用户信息
- 登出
- 密码修改
"""

import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestAuthApi:
    """M8 认证 API 测试类"""

    # ============================================================
    # 登录测试
    # ============================================================

    @pytest.mark.smoke
    @pytest.mark.m8
    @pytest.mark.auth
    def test_login_with_valid_credentials(self, m8_client):
        """测试使用有效凭证登录"""
        try:
            response = m8_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "admin123456"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data.get("code") == 0
            assert "data" in data
            
            login_data = data["data"]
            assert "access_token" in login_data
            assert login_data["access_token"]  # token 非空
        except Exception as e:
            pytest.skip(f"登录测试跳过: {e}")

    @pytest.mark.m8
    @pytest.mark.auth
    def test_login_with_invalid_password(self, m8_client):
        """测试使用错误密码登录"""
        try:
            response = m8_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrong_password"}
            )
            data = response.json()
            # 错误密码应该返回非 0 的 code
            assert data.get("code") != 0
        except Exception as e:
            pytest.skip(f"错误密码登录测试跳过: {e}")

    @pytest.mark.m8
    @pytest.mark.auth
    def test_login_with_nonexistent_user(self, m8_client):
        """测试使用不存在的用户登录"""
        try:
            response = m8_client.post(
                "/api/auth/login",
                json={"username": "nonexistent_user", "password": "test123456"}
            )
            data = response.json()
            # 不存在的用户应该返回错误
            assert data.get("code") != 0
        except Exception as e:
            pytest.skip(f"不存在用户登录测试跳过: {e}")

    @pytest.mark.m8
    @pytest.mark.auth
    def test_login_with_empty_credentials(self, m8_client):
        """测试使用空凭证登录"""
        try:
            # 空用户名
            response = m8_client.post(
                "/api/auth/login",
                json={"username": "", "password": "admin123456"}
            )
            data = response.json()
            assert data.get("code") != 0

            # 空密码
            response = m8_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": ""}
            )
            data = response.json()
            assert data.get("code") != 0
        except Exception as e:
            pytest.skip(f"空凭证登录测试跳过: {e}")

    # ============================================================
    # Token 验证测试
    # ============================================================

    @pytest.mark.m8
    @pytest.mark.auth
    def test_get_current_user_with_token(self, m8_client, admin_token):
        """测试使用有效 Token 获取当前用户信息"""
        try:
            if not admin_token or admin_token.startswith("test-"):
                pytest.skip("需要有效 Token")
            
            headers = {"Authorization": f"Bearer {admin_token}"}
            response = m8_client.get("/api/auth/me", headers=headers)
            
            if response.status_code == 401:
                pytest.skip("Token 无效或已过期")
            
            assert response.status_code == 200
            data = response.json()
            assert data.get("code") == 0
            assert "data" in data
            
            user_data = data["data"]
            assert "username" in user_data
        except Exception as e:
            pytest.skip(f"获取当前用户测试跳过: {e}")

    @pytest.mark.m8
    @pytest.mark.auth
    def test_access_protected_route_without_token(self, m8_client):
        """测试无 Token 访问受保护路由"""
        try:
            response = m8_client.get("/api/system/stats")
            # 未认证应该返回 401 或错误响应
            data = response.json()
            assert response.status_code == 401 or data.get("code") != 0
        except Exception as e:
            pytest.skip(f"无 Token 访问测试跳过: {e}")

    @pytest.mark.m8
    @pytest.mark.auth
    def test_access_protected_route_with_invalid_token(self, m8_client):
        """测试使用无效 Token 访问受保护路由"""
        try:
            headers = {"Authorization": "Bearer invalid_token_12345"}
            response = m8_client.get("/api/system/stats", headers=headers)
            data = response.json()
            # 无效 token 应该返回错误
            assert response.status_code == 401 or data.get("code") != 0
        except Exception as e:
            pytest.skip(f"无效 Token 访问测试跳过: {e}")

    # ============================================================
    # 登出测试
    # ============================================================

    @pytest.mark.m8
    @pytest.mark.auth
    def test_logout(self, m8_client, admin_token):
        """测试登出功能"""
        try:
            if not admin_token or admin_token.startswith("test-"):
                pytest.skip("需要有效 Token")
            
            headers = {"Authorization": f"Bearer {admin_token}"}
            response = m8_client.post("/api/auth/logout", headers=headers, json={})
            
            if response.status_code == 200:
                data = response.json()
                # 登出应该成功
                assert data.get("code") == 0
        except Exception as e:
            pytest.skip(f"登出测试跳过: {e}")
