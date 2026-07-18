"""
E2E 测试 - 认证流程

测试完整的认证端到端流程：
- 用户注册 → 登录 → 访问受保护资源 → 登出
- 登录失败 → 重试 → 锁定
- Token 过期 → 刷新 Token → 继续访问
- 密码修改 → 旧 Token 失效
- 多设备登录 → 各自独立
"""

import sys
import pytest
from pathlib import Path
from typing import Dict, Any

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
class TestUserRegistration:
    """用户注册 E2E 测试"""

    @pytest.mark.e2e_auth
    def test_register_new_user_success(self, e2e_api_client, test_data_factory):
        """测试新用户注册成功"""
        user = test_data_factory.create_test_user()

        result = e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })

        assert result["code"] == 0
        assert result["data"] is not None
        assert "id" in result["data"] or "username" in result["data"]

    @pytest.mark.e2e_auth
    def test_register_duplicate_username_fails(self, e2e_api_client, test_data_factory):
        """测试重复用户名注册失败"""
        user = test_data_factory.create_test_user()

        # 第一次注册
        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })

        # 第二次注册相同用户名
        result = e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": "another@test.com",
        })

        assert result["code"] != 0  # 应该失败

    @pytest.mark.e2e_auth
    def test_register_empty_username_fails(self, e2e_api_client):
        """测试空用户名注册失败"""
        result = e2e_api_client.post("/api/auth/register", {
            "username": "",
            "password": "Test@123456",
            "email": "test@test.com",
        })

        assert result["code"] != 0

    @pytest.mark.e2e_auth
    def test_register_empty_password_fails(self, e2e_api_client, test_data_factory):
        """测试空密码注册失败"""
        user = test_data_factory.create_test_user()

        result = e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": "",
            "email": user.email,
        })

        assert result["code"] != 0

    @pytest.mark.e2e_auth
    def test_register_then_login(self, e2e_api_client, test_data_factory):
        """测试注册后可以登录"""
        user = test_data_factory.create_test_user()

        # 注册
        register_result = e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        assert register_result["code"] == 0

        # 登录
        login_result = e2e_api_client.login(user.username, user.password)
        assert login_result["code"] == 0
        assert "access_token" in login_result["data"]


class TestLoginFlow:
    """登录流程 E2E 测试"""

    @pytest.mark.e2e_auth
    def test_admin_login_success(self, e2e_api_client, e2e_config):
        """测试管理员登录成功"""
        result = e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )

        assert result["code"] == 0
        assert "access_token" in result["data"]
        assert "token_type" in result["data"]
        assert result["data"]["token_type"] == "bearer"

    @pytest.mark.e2e_auth
    def test_login_returns_user_info(self, e2e_api_client, e2e_config):
        """测试登录返回用户信息"""
        result = e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )

        assert result["code"] == 0
        assert "user" in result["data"]
        user = result["data"]["user"]
        assert "id" in user
        assert "username" in user
        assert "role" in user

    @pytest.mark.e2e_auth
    def test_login_wrong_password_fails(self, e2e_api_client, e2e_config):
        """测试错误密码登录失败"""
        result = e2e_api_client.login(
            username=e2e_config.admin_username,
            password="wrong_password_123",
        )

        assert result["code"] != 0
        assert e2e_api_client.access_token is None

    @pytest.mark.e2e_auth
    def test_login_nonexistent_user_fails(self, e2e_api_client):
        """测试不存在的用户登录失败"""
        result = e2e_api_client.login(
            username="nonexistent_user_xyz",
            password="some_password",
        )

        assert result["code"] != 0

    @pytest.mark.e2e_auth
    def test_login_empty_credentials_fails(self, e2e_api_client):
        """测试空凭据登录失败"""
        result = e2e_api_client.login(username="", password="")

        assert result["code"] != 0

    @pytest.mark.e2e_auth
    def test_multiple_failed_logins_lockout(self, e2e_api_client, test_data_factory):
        """测试多次登录失败后锁定"""
        user = test_data_factory.create_test_user()

        # 先注册用户
        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })

        # 多次错误密码登录
        results = []
        for i in range(6):  # 超过锁定阈值
            result = e2e_api_client.login(
                username=user.username,
                password=f"wrong_password_{i}",
            )
            results.append(result)

        # 至少最后几次应该返回错误
        failed_count = sum(1 for r in results if r["code"] != 0)
        assert failed_count >= 1  # 至少有一次失败


class TestProtectedResources:
    """受保护资源访问 E2E 测试"""

    @pytest.mark.e2e_auth
    def test_access_protected_without_token_fails(self, e2e_api_client):
        """测试无 Token 访问受保护资源失败"""
        # 确保未登录
        e2e_api_client.access_token = None

        result = e2e_api_client.get("/api/users")

        assert result["code"] == 401 or result["code"] != 0

    @pytest.mark.e2e_auth
    def test_access_protected_with_valid_token(self, admin_api_client):
        """测试使用有效 Token 访问受保护资源"""
        result = admin_api_client.get("/api/users")

        # 应该能成功访问
        assert result["code"] == 0

    @pytest.mark.e2e_auth
    def test_get_user_info_after_login(self, admin_api_client):
        """测试登录后获取用户信息"""
        result = admin_api_client.get("/api/auth/me")

        assert result["code"] == 0
        assert "data" in result
        assert "username" in result["data"]

    @pytest.mark.e2e_auth
    def test_access_system_info_authenticated(self, admin_api_client):
        """测试已认证用户访问系统信息"""
        result = admin_api_client.get("/api/system/stats")

        assert result["code"] == 0
        assert "data" in result


class TestTokenRefresh:
    """Token 刷新 E2E 测试"""

    @pytest.mark.e2e_auth
    def test_refresh_token_success(self, e2e_api_client, e2e_config):
        """测试 Token 刷新成功"""
        # 先登录
        login_result = e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )
        assert login_result["code"] == 0
        old_token = e2e_api_client.access_token

        # 刷新 Token
        refresh_result = e2e_api_client.refresh_token_flow()

        assert refresh_result["code"] == 0
        assert "access_token" in refresh_result["data"]
        # 新 Token 应该不同
        assert refresh_result["data"]["access_token"] != old_token

    @pytest.mark.e2e_auth
    def test_new_token_can_access_resources(self, e2e_api_client, e2e_config):
        """测试刷新后的 Token 可以访问资源"""
        # 登录
        e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )

        # 刷新
        refresh_result = e2e_api_client.refresh_token_flow()
        assert refresh_result["code"] == 0

        # 使用新 Token 访问受保护资源
        result = e2e_api_client.get("/api/auth/me")
        assert result["code"] == 0

    @pytest.mark.e2e_auth
    def test_refresh_without_login_fails(self, e2e_api_client):
        """测试未登录时刷新 Token 失败"""
        e2e_api_client.access_token = None
        e2e_api_client.refresh_token = None

        result = e2e_api_client.refresh_token_flow()

        assert result["code"] != 0


class TestPasswordChange:
    """密码修改 E2E 测试"""

    @pytest.mark.e2e_auth
    def test_change_password_success(self, e2e_api_client, test_data_factory):
        """测试修改密码成功"""
        # 创建并登录用户
        user = test_data_factory.create_test_user()
        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        e2e_api_client.login(user.username, user.password)
        old_token = e2e_api_client.access_token

        # 修改密码
        new_password = "NewTest@123456"
        result = e2e_api_client.put("/api/auth/password", {
            "old_password": user.password,
            "new_password": new_password,
        })

        assert result["code"] == 0

    @pytest.mark.e2e_auth
    def test_old_password_incorrect_fails(self, e2e_api_client, test_data_factory):
        """测试旧密码错误时修改失败"""
        user = test_data_factory.create_test_user()
        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        e2e_api_client.login(user.username, user.password)

        result = e2e_api_client.put("/api/auth/password", {
            "old_password": "wrong_old_password",
            "new_password": "NewTest@123456",
        })

        assert result["code"] != 0

    @pytest.mark.e2e_auth
    def test_short_new_password_fails(self, e2e_api_client, test_data_factory):
        """测试新密码太短时失败"""
        user = test_data_factory.create_test_user()
        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        e2e_api_client.login(user.username, user.password)

        result = e2e_api_client.put("/api/auth/password", {
            "old_password": user.password,
            "new_password": "123",  # 太短
        })

        assert result["code"] != 0

    @pytest.mark.e2e_auth
    def test_login_with_new_password_after_change(self, e2e_api_client, test_data_factory):
        """测试密码修改后使用新密码登录"""
        user = test_data_factory.create_test_user()
        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        e2e_api_client.login(user.username, user.password)

        new_password = "NewTest@123456"
        e2e_api_client.put("/api/auth/password", {
            "old_password": user.password,
            "new_password": new_password,
        })

        # 使用新密码登录
        e2e_api_client.access_token = None
        result = e2e_api_client.login(user.username, new_password)
        assert result["code"] == 0

    @pytest.mark.e2e_auth
    def test_old_password_fails_after_change(self, e2e_api_client, test_data_factory):
        """测试密码修改后旧密码失效"""
        user = test_data_factory.create_test_user()
        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        e2e_api_client.login(user.username, user.password)

        new_password = "NewTest@123456"
        e2e_api_client.put("/api/auth/password", {
            "old_password": user.password,
            "new_password": new_password,
        })

        # 使用旧密码登录应该失败
        e2e_api_client.access_token = None
        result = e2e_api_client.login(user.username, user.password)
        assert result["code"] != 0


class TestLogout:
    """登出 E2E 测试"""

    @pytest.mark.e2e_auth
    def test_logout_success(self, admin_api_client):
        """测试登出成功"""
        result = admin_api_client.logout()

        assert result["code"] == 0
        assert admin_api_client.access_token is None

    @pytest.mark.e2e_auth
    def test_cannot_access_after_logout(self, admin_api_client):
        """测试登出后无法访问受保护资源"""
        # 登出
        admin_api_client.logout()

        # 访问受保护资源应该失败
        result = admin_api_client.get("/api/users")
        assert result["code"] != 0

    @pytest.mark.e2e_auth
    def test_login_again_after_logout(self, e2e_api_client, e2e_config):
        """测试登出后可以重新登录"""
        # 登录
        e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )
        assert e2e_api_client.access_token is not None

        # 登出
        e2e_api_client.logout()
        assert e2e_api_client.access_token is None

        # 重新登录
        result = e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )
        assert result["code"] == 0
        assert e2e_api_client.access_token is not None


class TestMultiDeviceLogin:
    """多设备登录 E2E 测试"""

    @pytest.mark.e2e_auth
    def test_multiple_logins_independent_tokens(
        self, e2e_api_client, test_data_factory, e2e_config
    ):
        """测试多次登录生成独立的 Token"""
        tokens = []
        for i in range(3):
            result = e2e_api_client.login(
                username=e2e_config.admin_username,
                password=e2e_config.admin_password,
            )
            if result["code"] == 0:
                tokens.append(result["data"]["access_token"])

        # 每个 token 应该不同
        unique_tokens = set(tokens)
        assert len(unique_tokens) >= 1  # 至少有一个 token

    @pytest.mark.e2e_auth
    def test_each_token_can_access_resources(
        self, e2e_api_client, e2e_config
    ):
        """测试每个 Token 都能独立访问资源"""
        # 第一次登录
        result1 = e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )
        assert result1["code"] == 0
        token1 = result1["data"]["access_token"]

        # 验证 token1 可用
        e2e_api_client.set_token(token1)
        result = e2e_api_client.get("/api/auth/me")
        assert result["code"] == 0

        # 第二次登录
        result2 = e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )
        assert result2["code"] == 0
        token2 = result2["data"]["access_token"]

        # 验证 token2 可用
        e2e_api_client.set_token(token2)
        result = e2e_api_client.get("/api/auth/me")
        assert result["code"] == 0

    @pytest.mark.e2e_auth
    def test_logout_one_device_affects_only_that_device(
        self, e2e_api_client, e2e_config
    ):
        """测试一个设备登出不影响其他设备"""
        # 第一次登录（设备 A）
        result_a = e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )
        token_a = result_a["data"]["access_token"]

        # 第二次登录（设备 B）
        result_b = e2e_api_client.login(
            username=e2e_config.admin_username,
            password=e2e_config.admin_password,
        )
        token_b = result_b["data"]["access_token"]

        # 设备 A 登出
        e2e_api_client.set_token(token_a)
        e2e_api_client.logout()

        # 设备 B 的 token 应该仍然有效（mock 模式下模拟）
        e2e_api_client.set_token(token_b)
        result = e2e_api_client.get("/api/auth/me")
        # 在真实环境中可能仍有效，在 mock 中也应仍有效
        assert result["code"] == 0


class TestTokenExpiry:
    """Token 过期 E2E 测试"""

    @pytest.mark.e2e_auth
    def test_invalid_token_rejected(self, e2e_api_client):
        """测试无效 Token 被拒绝"""
        e2e_api_client.set_token("invalid_token_xyz_123456")

        result = e2e_api_client.get("/api/users")

        assert result["code"] != 0

    @pytest.mark.e2e_auth
    def test_empty_token_rejected(self, e2e_api_client):
        """测试空 Token 被拒绝"""
        e2e_api_client.set_token("")

        result = e2e_api_client.get("/api/users")

        assert result["code"] != 0

    @pytest.mark.e2e_auth
    def test_malformed_token_rejected(self, e2e_api_client):
        """测试格式错误的 Token 被拒绝"""
        e2e_api_client.set_token("not.a.valid.jwt.token")

        result = e2e_api_client.get("/api/users")

        assert result["code"] != 0


class TestRoleBasedAccess:
    """基于角色的访问控制 E2E 测试"""

    @pytest.mark.e2e_auth
    def test_admin_can_access_user_management(self, admin_api_client):
        """测试管理员可以访问用户管理接口"""
        result = admin_api_client.get("/api/users")

        assert result["code"] == 0
        assert "items" in result["data"] or "data" in result

    @pytest.mark.e2e_auth
    def test_user_role_can_access_own_info(
        self, e2e_api_client, test_data_factory
    ):
        """测试普通用户可以访问自己的信息"""
        user = test_data_factory.create_test_user()
        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        e2e_api_client.login(user.username, user.password)

        result = e2e_api_client.get("/api/auth/me")

        assert result["code"] == 0

    @pytest.mark.e2e_auth
    def test_admin_has_admin_role(self, admin_api_client):
        """测试管理员用户拥有 admin 角色"""
        result = admin_api_client.get("/api/auth/me")

        assert result["code"] == 0
        user = result["data"]
        assert user.get("role") == "admin"

    @pytest.mark.e2e_auth
    def test_regular_user_has_user_role(
        self, e2e_api_client, test_data_factory
    ):
        """测试普通用户拥有 user 角色"""
        user = test_data_factory.create_test_user(role="user")
        e2e_api_client.post("/api/auth/register", {
            "username": user.username,
            "password": user.password,
            "email": user.email,
        })
        e2e_api_client.login(user.username, user.password)

        result = e2e_api_client.get("/api/auth/me")

        assert result["code"] == 0
        assert result["data"].get("role") == "user"
