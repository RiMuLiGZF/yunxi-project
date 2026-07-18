"""
统一认证体系 - 综合测试

测试 shared.core.auth 各模块的功能：
- password: 密码哈希与验证
- jwt: JWT Token 签发与验证
- api_key: API Key 生成、哈希、验证
- rbac: 角色权限检查
- middleware: 统一认证中间件
- dependencies: FastAPI Depends 依赖
- 向后兼容：旧 shared.auth 模块
"""

import sys
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 确保可以导入 shared 模块
SHARED_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SHARED_DIR.parent
if str(PROJECT_DIR) not in sys.path:
# ===========================================================================
# password 模块测试
# ===========================================================================

class TestPassword:
    """密码哈希与验证测试"""

    def test_hash_and_verify_password(self):
        """正常密码哈希与验证"""
        from shared.core.auth import hash_password, verify_password, is_bcrypt_available

        if not is_bcrypt_available():
            pytest.skip("bcrypt 不可用，跳过测试")

        hashed = hash_password("test_password_123")
        assert hashed != "test_password_123"
        assert len(hashed) > 0
        assert verify_password("test_password_123", hashed) is True
        assert verify_password("wrong_password", hashed) is False

    def test_empty_password(self):
        """空密码处理"""
        from shared.core.auth import verify_password, is_bcrypt_available

        if not is_bcrypt_available():
            pytest.skip("bcrypt 不可用，跳过测试")

        assert verify_password("", "some_hash") is False
        assert verify_password("password", "") is False

    def test_needs_update(self):
        """密码哈希升级检查"""
        from shared.core.auth import hash_password, needs_update, is_bcrypt_available

        if not is_bcrypt_available():
            pytest.skip("bcrypt 不可用，跳过测试")

        hashed = hash_password("test")
        # bcrypt 生成的哈希通常不需要升级
        assert isinstance(needs_update(hashed), bool)


# ===========================================================================
# JWT 模块测试
# ===========================================================================

class TestJWT:
    """JWT Token 签发与验证测试"""

    def test_create_and_decode_access_token(self):
        """Access Token 签发与验证"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        config = JWTConfig(
            secret="test-secret-key-at-least-32-chars-long",
            algorithm="HS256",
            access_token_expire_minutes=30,
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        token = handler.create_access_token({
            "sub": "user_123",
            "username": "testuser",
            "roles": ["admin"],
            "scopes": ["read", "write"],
        })

        assert isinstance(token, str)
        assert len(token) > 0

        payload = handler.decode_token(token, token_type="access")
        assert payload is not None
        assert payload["sub"] == "user_123"
        assert payload["username"] == "testuser"
        assert payload["roles"] == ["admin"]
        assert payload["scopes"] == ["read", "write"]
        assert payload["type"] == "access"
        assert "jti" in payload
        assert "exp" in payload
        assert "iat" in payload

    def test_create_and_decode_refresh_token(self):
        """Refresh Token 签发与验证"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        config = JWTConfig(
            secret="test-secret-key-at-least-32-chars-long",
            algorithm="HS256",
            refresh_token_expire_days=7,
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        token = handler.create_refresh_token({"sub": "user_123"})
        payload = handler.decode_token(token, token_type="refresh")
        assert payload is not None
        assert payload["sub"] == "user_123"
        assert payload["type"] == "refresh"

    def test_invalid_token(self):
        """无效 Token 验证失败"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        config = JWTConfig(
            secret="test-secret-key-at-least-32-chars-long",
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        assert handler.decode_token("invalid.token.here") is None
        assert handler.decode_token("") is None

    def test_wrong_token_type(self):
        """Token 类型不匹配"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        config = JWTConfig(
            secret="test-secret-key-at-least-32-chars-long",
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        access_token = handler.create_access_token({"sub": "user1"})
        # 用 access token 当 refresh 用，应该失败
        assert handler.decode_token(access_token, token_type="refresh") is None

    def test_token_hash(self):
        """Token 哈希计算"""
        from shared.core.auth import JWTHandler, is_jwt_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        token = "test-jwt-token"
        hashed = JWTHandler.hash_token(token)
        assert isinstance(hashed, str)
        assert len(hashed) == 64  # SHA256 hex

    def test_refresh_access_token(self):
        """使用 Refresh Token 刷新 Access Token"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        config = JWTConfig(
            secret="test-secret-key-at-least-32-chars-long",
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        refresh_token = handler.create_refresh_token({"sub": "user1"})
        result = handler.refresh_access_token(
            refresh_token,
            additional_data={"roles": ["admin"], "scopes": ["*"]},
        )

        assert result is not None
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["token_type"] == "bearer"

        new_payload = handler.decode_token(result["access_token"], token_type="access")
        assert new_payload is not None
        assert new_payload["sub"] == "user1"
        assert new_payload["roles"] == ["admin"]

    def test_in_memory_blacklist(self):
        """内存版 Token 黑名单"""
        from shared.core.auth import InMemoryTokenBlacklist
        from datetime import datetime, timedelta, timezone

        blacklist = InMemoryTokenBlacklist()
        jti = "test-jti-123"

        assert blacklist.is_blacklisted(jti) is False

        expired_at = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        blacklist.add(jti, "hash-value", expired_at)

        assert blacklist.is_blacklisted(jti) is True
        assert blacklist.is_blacklisted("other-jti") is False

        # 测试过期自动清理
        expired_jti = "expired-jti"
        blacklist.add(expired_jti, "hash2", datetime.now(tz=timezone.utc) - timedelta(hours=1))
        assert blacklist.is_blacklisted(expired_jti) is False

        # 测试清理
        count = blacklist.clean_expired()
        assert isinstance(count, int)

    def test_jwt_config_validation(self):
        """JWT 配置安全校验"""
        from shared.core.auth import JWTConfig

        # 不安全的密钥
        unsafe_config = JWTConfig(secret="short", require_secure_secret=True)
        with pytest.raises(ValueError):
            unsafe_config.validate()

        # 安全的密钥
        safe_config = JWTConfig(
            secret="this-is-a-very-long-secret-key-for-testing",
            require_secure_secret=True,
        )
        safe_config.validate()  # 不应抛出异常

        # 跳过检查
        skip_config = JWTConfig(secret="short", require_secure_secret=False)
        skip_config.validate()  # 不应抛出异常


# ===========================================================================
# API Key 模块测试
# ===========================================================================

class TestApiKey:
    """API Key 管理测试"""

    def test_generate_api_key(self):
        """生成 API Key"""
        from shared.core.auth import generate_api_key

        key = generate_api_key(prefix="test-", length=32)
        assert key.startswith("test-")
        assert len(key) == len("test-") + 32

        key2 = generate_api_key(prefix="m12-", length=48)
        assert key2.startswith("m12-")
        assert len(key2) == len("m12-") + 48

        # 两次生成的 key 不同
        assert key != generate_api_key(prefix="test-", length=32)

    def test_hash_and_verify_sha256(self):
        """SHA256 哈希与验证"""
        from shared.core.auth import hash_api_key_sha256, verify_api_key_hash

        key = "test-api-key-12345"
        hashed = hash_api_key_sha256(key)

        assert isinstance(hashed, str)
        assert len(hashed) == 64
        assert verify_api_key_hash(key, hashed, use_bcrypt=False) is True
        assert verify_api_key_hash("wrong-key", hashed, use_bcrypt=False) is False

    def test_mask_api_key(self):
        """API Key 脱敏"""
        from shared.core.auth import mask_api_key

        key = "abcdefghijklmnopqrstuvwxyz"
        masked = mask_api_key(key, show_first=4, show_last=4)
        assert masked.startswith("abcd")
        assert masked.endswith("wxyz")
        assert "*" in masked
        assert len(masked) == len(key)

        # 短密钥
        short = mask_api_key("abc", show_first=4, show_last=4)
        assert short == "***"

    def test_api_key_info(self):
        """ApiKeyInfo 数据类"""
        from shared.core.auth import ApiKeyInfo

        info = ApiKeyInfo(
            key_hash="hash_value",
            key_name="test-key",
            roles=["admin"],
            scopes=["read", "write"],
        )

        assert info.key_name == "test-key"
        assert info.roles == ["admin"]
        assert info.is_active is True
        assert info.is_expired() is False

        d = info.to_dict()
        assert "key_hash" not in d
        assert d["key_name"] == "test-key"

        d_with_hash = info.to_dict(include_hash=True)
        assert d_with_hash["key_hash"] == "hash_value"

    def test_in_memory_store_and_validator_sha256(self):
        """内存存储与验证器（SHA256 模式）"""
        from shared.core.auth import (
            InMemoryApiKeyStore, ApiKeyValidator, ApiKeyInfo,
            hash_api_key_sha256, generate_api_key,
        )

        store = InMemoryApiKeyStore()
        api_key = generate_api_key(prefix="test-")
        key_hash = hash_api_key_sha256(api_key)

        store.add_key(ApiKeyInfo(
            key_hash=key_hash,
            key_name="test-key",
            roles=["viewer"],
            scopes=["read"],
        ))

        validator = ApiKeyValidator(store, use_bcrypt=False)

        # 正确的 key
        result = validator.validate_sha256_fast(api_key)
        assert result is not None
        assert result.key_name == "test-key"
        assert result.roles == ["viewer"]

        # 错误的 key
        assert validator.validate_sha256_fast("wrong-key") is None

        # 空 key
        assert validator.validate_sha256_fast("") is None

    def test_validator_with_expired_key(self):
        """过期 Key 验证失败"""
        from shared.core.auth import (
            InMemoryApiKeyStore, ApiKeyValidator, ApiKeyInfo,
            hash_api_key_sha256, generate_api_key,
        )
        from datetime import datetime, timedelta, timezone

        store = InMemoryApiKeyStore()
        api_key = generate_api_key()
        key_hash = hash_api_key_sha256(api_key)

        store.add_key(ApiKeyInfo(
            key_hash=key_hash,
            key_name="expired-key",
            expires_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        ))

        validator = ApiKeyValidator(store, use_bcrypt=False)
        assert validator.validate_sha256_fast(api_key) is None

    def test_validator_with_inactive_key(self):
        """禁用的 Key 验证失败"""
        from shared.core.auth import (
            InMemoryApiKeyStore, ApiKeyValidator, ApiKeyInfo,
            hash_api_key_sha256, generate_api_key,
        )

        store = InMemoryApiKeyStore()
        api_key = generate_api_key()
        key_hash = hash_api_key_sha256(api_key)

        store.add_key(ApiKeyInfo(
            key_hash=key_hash,
            key_name="inactive-key",
            is_active=False,
        ))

        validator = ApiKeyValidator(store, use_bcrypt=False)
        assert validator.validate_sha256_fast(api_key) is None


# ===========================================================================
# RBAC 模块测试
# ===========================================================================

class TestRBAC:
    """角色权限控制测试"""

    def test_role_hierarchy(self):
        """角色层级检查"""
        from shared.core.auth import has_role, ROLE_ADMIN, ROLE_VIEWER, ROLE_SUPER_ADMIN

        assert has_role([ROLE_SUPER_ADMIN], ROLE_ADMIN) is True
        assert has_role([ROLE_ADMIN], ROLE_VIEWER) is True
        assert has_role([ROLE_VIEWER], ROLE_ADMIN) is False
        assert has_role([], ROLE_ADMIN) is False

    def test_has_any_role(self):
        """任意角色检查"""
        from shared.core.auth import has_any_role, ROLE_ADMIN, ROLE_VIEWER, ROLE_API

        assert has_any_role([ROLE_ADMIN], [ROLE_VIEWER, ROLE_API]) is True
        assert has_any_role([ROLE_API], [ROLE_ADMIN, ROLE_VIEWER]) is False
        assert has_any_role([], [ROLE_ADMIN]) is False

    def test_has_all_roles(self):
        """所有角色检查"""
        from shared.core.auth import has_all_roles, ROLE_ADMIN, ROLE_VIEWER, ROLE_SUPER_ADMIN

        assert has_all_roles([ROLE_SUPER_ADMIN], [ROLE_ADMIN, ROLE_VIEWER]) is True
        assert has_all_roles([ROLE_VIEWER], [ROLE_ADMIN, ROLE_VIEWER]) is False

    def test_scope_check(self):
        """权限范围检查"""
        from shared.core.auth import has_scope, has_any_scope, has_all_scopes, SCOPE_ALL

        assert has_scope(["read", "write"], "read") is True
        assert has_scope(["read"], "write") is False
        assert has_scope([SCOPE_ALL], "anything") is True
        assert has_scope([], "read") is False

        assert has_any_scope(["read"], ["read", "write"]) is True
        assert has_any_scope(["read"], ["write", "delete"]) is False

        assert has_all_scopes(["read", "write"], ["read", "write"]) is True
        assert has_all_scopes(["read"], ["read", "write"]) is False

    def test_require_role_decorator(self):
        """角色依赖装饰器"""
        from shared.core.auth import require_role, ROLE_ADMIN, ROLE_VIEWER

        checker = require_role(ROLE_ADMIN)
        # 有 admin 角色的用户应该通过
        user = {"roles": ["admin"], "username": "test"}
        result = checker(user)
        assert result == user

        # 只有 viewer 角色的用户应该抛出异常
        viewer_user = {"roles": ["viewer"], "username": "test2"}
        with pytest.raises(Exception):
            checker(viewer_user)

    def test_require_scope_decorator(self):
        """权限依赖装饰器"""
        from shared.core.auth import require_scope

        checker = require_scope("data:read")
        user = {"scopes": ["data:read", "data:write"], "username": "test"}
        result = checker(user)
        assert result == user

        no_scope_user = {"scopes": ["other:read"], "username": "test2"}
        with pytest.raises(Exception):
            checker(no_scope_user)


# ===========================================================================
# 中间件辅助函数测试
# ===========================================================================

class TestMiddlewareHelpers:
    """中间件辅助函数测试"""

    def test_is_public_path(self):
        """公开路径判断"""
        from shared.core.auth import is_public_path, DEFAULT_PUBLIC_PATHS

        assert is_public_path("/", DEFAULT_PUBLIC_PATHS) is True
        assert is_public_path("/health", DEFAULT_PUBLIC_PATHS) is True
        assert is_public_path("/docs", DEFAULT_PUBLIC_PATHS) is True
        assert is_public_path("/openapi.json", DEFAULT_PUBLIC_PATHS) is True
        assert is_public_path("/api/users", DEFAULT_PUBLIC_PATHS) is False

        # 通配符匹配
        assert is_public_path("/m8/health", ["/m8/*"]) is True
        assert is_public_path("/m8/status", ["/m8/*"]) is True

        # 前缀匹配
        assert is_public_path("/docs/something", ["/docs"]) is True

    def test_simple_memory_rate_limiter(self):
        """内存版速率限制器"""
        from shared.core.auth import SimpleMemoryRateLimiter

        limiter = SimpleMemoryRateLimiter(default_limit=5, window_seconds=60)

        # 限额内请求允许
        for i in range(5):
            allowed, remaining, window = limiter.check("test_key")
            assert allowed is True

        # 超限被拒绝
        allowed, remaining, window = limiter.check("test_key")
        assert allowed is False
        assert remaining == 0

        # 不同 key 独立计数
        allowed2, _, _ = limiter.check("other_key")
        assert allowed2 is True

        # reset 功能
        limiter.reset("test_key")
        allowed3, _, _ = limiter.check("test_key")
        assert allowed3 is True

    def test_default_public_paths(self):
        """默认公开路径"""
        from shared.core.auth import DEFAULT_PUBLIC_PATHS

        assert isinstance(DEFAULT_PUBLIC_PATHS, list)
        assert len(DEFAULT_PUBLIC_PATHS) > 0
        assert "/" in DEFAULT_PUBLIC_PATHS
        assert "/health" in DEFAULT_PUBLIC_PATHS


# ===========================================================================
# 向后兼容测试：旧 shared.auth 模块
# ===========================================================================

class TestBackwardCompatibility:
    """旧 shared.auth 模块向后兼容测试"""

    def test_hash_api_key_compat(self):
        """旧版 hash_api_key 兼容"""
        from shared.auth import hash_api_key as old_hash
        from shared.core.auth import hash_api_key_sha256

        key = "test-api-key-compat"
        # 旧版使用 SHA256
        assert old_hash(key) == hash_api_key_sha256(key)

    def test_verify_api_key_compat(self):
        """旧版 verify_api_key 兼容"""
        from shared.auth import verify_api_key, hash_api_key

        key = "test-verify-key"
        key_hash = hash_api_key(key)

        # 字符串格式
        assert verify_api_key(key, [key]) == {}

        # 元组格式
        result = verify_api_key(key, [(key_hash, {"name": "test", "permissions": ["*"]})])
        assert result is not None
        assert result["name"] == "test"
        assert result["permissions"] == ["*"]

        # 验证失败
        assert verify_api_key("wrong", [key_hash]) is None

    def test_is_public_path_compat(self):
        """旧版 is_public_path 兼容"""
        from shared.auth import is_public_path, DEFAULT_PUBLIC_PATHS

        assert is_public_path("/health", DEFAULT_PUBLIC_PATHS) is True
        assert is_public_path("/api/users", DEFAULT_PUBLIC_PATHS) is False
        assert is_public_path("/m8/health", ["/m8/*"]) is True

    def test_simple_rate_limiter_compat(self):
        """旧版 SimpleRateLimiter 兼容"""
        from shared.auth import SimpleRateLimiter

        limiter = SimpleRateLimiter(default_limit=3, window_seconds=60)
        for i in range(3):
            allowed, remaining, window = limiter.check("key")
            assert allowed is True

        allowed, remaining, window = limiter.check("key")
        assert allowed is False

    def test_generate_api_key_compat(self):
        """旧版 generate_api_key 兼容"""
        from shared.auth import generate_api_key

        key = generate_api_key(prefix="yx_", length=32)
        assert key.startswith("yx_")
        assert len(key) == len("yx_") + 32

    def test_mask_api_key_compat(self):
        """旧版 mask_api_key 兼容"""
        from shared.auth import mask_api_key

        key = "abcdefghijklmnop"
        masked = mask_api_key(key, show_first=4, show_last=4)
        assert masked.startswith("abcd")
        assert masked.endswith("mnop")

    def test_create_api_key_dependency_compat(self):
        """旧版 create_api_key_dependency 兼容（仅验证函数存在）"""
        from shared.auth import create_api_key_dependency

        dep = create_api_key_dependency(valid_keys=["test-key"])
        assert callable(dep)


# ===========================================================================
# FastAPI 中间件集成测试
# ===========================================================================

class TestFastAPIIntegration:
    """FastAPI 集成测试"""

    @pytest.fixture
    def app_with_auth(self):
        """创建带统一认证的 FastAPI 应用"""
        from fastapi import FastAPI, Request
        from shared.core.auth import (
            UnifiedAuthMiddleware,
            JWTHandler, JWTConfig,
            ApiKeyValidator, InMemoryApiKeyStore, ApiKeyInfo,
            hash_api_key_sha256, generate_api_key,
            is_jwt_available,
        )

        app = FastAPI()

        # API Key 认证
        store = InMemoryApiKeyStore()
        test_api_key = generate_api_key(prefix="test-")
        store.add_key(ApiKeyInfo(
            key_hash=hash_api_key_sha256(test_api_key),
            key_name="test-key",
            roles=["admin"],
            scopes=["*"],
        ))
        validator = ApiKeyValidator(store, use_bcrypt=False)

        # JWT 认证
        jwt_handler = None
        test_jwt_token = None
        if is_jwt_available():
            config = JWTConfig(
                secret="test-secret-key-at-least-32-chars-long-for-jwt",
                require_secure_secret=False,
            )
            jwt_handler = JWTHandler(config)
            test_jwt_token = jwt_handler.create_access_token({
                "sub": "user1",
                "username": "testuser",
                "roles": ["admin"],
                "scopes": ["*"],
            })

        app.add_middleware(
            UnifiedAuthMiddleware,
            jwt_handler=jwt_handler,
            api_key_validator=validator,
            api_key_header_names=["X-API-Key", "X-Test-Token"],
            public_paths=["/health", "/docs", "/openapi.json"],
        )

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        @app.get("/api/protected")
        async def protected(request: Request):
            user = getattr(request.state, "user", None)
            return {"user": user}

        return {
            "app": app,
            "api_key": test_api_key,
            "jwt_token": test_jwt_token,
        }

    def test_public_path_accessible(self, app_with_auth):
        """公开路径可以直接访问"""
        from fastapi.testclient import TestClient

        client = TestClient(app_with_auth["app"])
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_protected_without_auth(self, app_with_auth):
        """受保护路径无认证返回 401"""
        from fastapi.testclient import TestClient

        client = TestClient(app_with_auth["app"])
        response = client.get("/api/protected")
        assert response.status_code == 401

    def test_protected_with_api_key(self, app_with_auth):
        """使用 API Key 访问受保护路径"""
        from fastapi.testclient import TestClient

        client = TestClient(app_with_auth["app"])
        response = client.get(
            "/api/protected",
            headers={"X-API-Key": app_with_auth["api_key"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["auth_type"] == "api_key"
        assert data["user"]["username"] == "test-key"

    def test_protected_with_jwt(self, app_with_auth):
        """使用 JWT Token 访问受保护路径"""
        if not app_with_auth["jwt_token"]:
            pytest.skip("JWT 不可用，跳过测试")

        from fastapi.testclient import TestClient

        client = TestClient(app_with_auth["app"])
        response = client.get(
            "/api/protected",
            headers={"Authorization": f"Bearer {app_with_auth['jwt_token']}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["auth_type"] == "jwt"
        assert data["user"]["username"] == "testuser"

    def test_protected_with_wrong_api_key(self, app_with_auth):
        """错误的 API Key 返回 401"""
        from fastapi.testclient import TestClient

        client = TestClient(app_with_auth["app"])
        response = client.get(
            "/api/protected",
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    def test_protected_with_custom_header(self, app_with_auth):
        """使用自定义 Header 名称的 API Key"""
        from fastapi.testclient import TestClient

        client = TestClient(app_with_auth["app"])
        response = client.get(
            "/api/protected",
            headers={"X-Test-Token": app_with_auth["api_key"]},
        )
        assert response.status_code == 200

    def test_protected_with_query_param(self, app_with_auth):
        """使用 Query 参数传递 API Key"""
        from fastapi.testclient import TestClient

        client = TestClient(app_with_auth["app"])
        response = client.get(
            f"/api/protected?api_key={app_with_auth['api_key']}",
        )
        assert response.status_code == 200


# ===========================================================================
# dependencies 模块测试
# ===========================================================================

class TestDependencies:
    """FastAPI Depends 依赖测试"""

    def test_create_auth_dependency(self):
        """创建统一认证依赖"""
        from shared.core.auth import (
            create_auth_dependency,
            ApiKeyValidator, InMemoryApiKeyStore, ApiKeyInfo,
            hash_api_key_sha256, generate_api_key,
        )

        store = InMemoryApiKeyStore()
        api_key = generate_api_key()
        store.add_key(ApiKeyInfo(
            key_hash=hash_api_key_sha256(api_key),
            key_name="test-dep-key",
            roles=["viewer"],
        ))
        validator = ApiKeyValidator(store, use_bcrypt=False)

        dep_func = create_auth_dependency(api_key_validator=validator)
        assert callable(dep_func)

    def test_create_token_header_dependency(self):
        """创建简单 Token Header 依赖"""
        from shared.core.auth import create_token_header_dependency

        dep_func = create_token_header_dependency(
            token_getter=lambda: "test-token-123",
            header_names=["X-Custom-Token"],
        )
        assert callable(dep_func)
