# -*- coding: utf-8 -*-
"""
SEC-004 测试：M8 控制塔 JWT 统一认证体系

验证 M8 auth.py 迁移到统一 JWTHandler 后的功能正确性：
1. Token 签发和验证
2. Token 黑名单机制
3. 密钥轮换接口
4. JTI 唯一标识
5. 向后兼容（旧格式 Token 验证）
6. 使用 datetime.now(tz=timezone.utc) 替代 datetime.utcnow()
"""

import sys
import os
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

# 将 M8-control-tower 目录加入 path（backend 的父目录）
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_parent_dir = os.path.dirname(_backend_dir)
# 设置测试用 JWT 密钥（确保统一 JWTHandler 可用）
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-unit-testing-only-1234567890"
# 设置为测试环境
os.environ["ENV"] = "test"


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(scope="module")
def jwt_handler():
    """获取统一 JWTHandler，如果不可用则跳过整个测试模块."""
    from backend.auth import _get_jwt_handler
    handler = _get_jwt_handler()
    if handler is None:
        pytest.skip("统一 JWTHandler 不可用，跳过 JWT 迁移测试")
    return handler


@pytest.fixture(scope="module")
def token_blacklist():
    """获取 Token 黑名单，如果不可用则跳过."""
    from backend.auth import _get_token_blacklist
    bl = _get_token_blacklist()
    if bl is None:
        pytest.skip("Token 黑名单不可用，跳过测试")
    return bl


# ===========================================================================
# 集成测试：统一 JWTHandler 可用时的完整功能验证
# ===========================================================================

class TestJWTMigration:
    """JWT 迁移到统一认证体系测试（集成测试）"""

    def test_create_access_token_contains_jti(self, jwt_handler):
        """测试新签发的 Token 包含 JTI 唯一标识"""
        from backend.auth import create_access_token

        token = create_access_token(data={"sub": "testuser", "role": "admin"})
        assert token is not None
        assert isinstance(token, str)

        # 验证 Token 包含 JTI
        jti = jwt_handler.get_jti(token)
        assert jti is not None
        assert len(jti) > 0  # JTI 是 uuid4.hex，32 字符

    def test_create_access_token_contains_type(self, jwt_handler):
        """测试新签发的 Token 包含 type=access 字段"""
        from backend.auth import create_access_token

        token = create_access_token(data={"sub": "testuser", "role": "admin"})
        payload = jwt_handler.decode_token(token, token_type="access")
        assert payload is not None
        assert payload.get("type") == "access"
        assert payload.get("sub") == "testuser"
        assert payload.get("role") == "admin"

    def test_token_uses_utc_timezone(self, jwt_handler):
        """测试 Token 使用 UTC 时区（datetime.now(tz=timezone.utc)）"""
        from backend.auth import create_access_token

        before = datetime.now(tz=timezone.utc)
        token = create_access_token(data={"sub": "testuser"})
        after = datetime.now(tz=timezone.utc)

        payload = jwt_handler.decode_token(token)
        assert payload is not None

        # iat 应该在 before 和 after 之间（允许 1 秒误差，因为 JWT 的 iat 是整数秒）
        iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        # iat 是整秒，所以 before 可能比 iat 多不到 1 秒
        assert (before - timedelta(seconds=1)) <= iat <= (after + timedelta(seconds=1))

        # exp 应该在 iat + expire 时间范围内
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert exp > iat

    def test_token_blacklist_add_and_check(self, jwt_handler, token_blacklist):
        """测试 Token 黑名单功能：加入黑名单后验证失败"""
        from backend.auth import create_access_token, blacklist_token

        # 签发 Token
        token = create_access_token(data={"sub": "testuser", "role": "user"})
        assert jwt_handler.is_access_token_valid(token)

        # 加入黑名单
        result = blacklist_token(token)
        assert result is True

        # 黑名单验证应该返回 True
        jti = jwt_handler.get_jti(token)
        assert token_blacklist.is_blacklisted(jti) is True

    def test_blacklist_clean_expired(self, token_blacklist):
        """测试清理已过期的黑名单 Token"""
        from backend.auth import clean_expired_blacklist

        # 添加多个已过期的 Token 到黑名单
        # 注意：InMemoryTokenBlacklist.is_blacklisted 在检查时会自动清理过期项，
        # 所以直接操作内部字典来添加过期项
        expired_jtis = [
            "expired-jti-001",
            "expired-jti-002",
            "expired-jti-003",
        ]
        for jti in expired_jtis:
            token_blacklist._blacklist[jti] = datetime.now(tz=timezone.utc) - timedelta(hours=1)

        # 添加一个未过期的
        valid_jti = "valid-jti-001"
        token_blacklist._blacklist[valid_jti] = datetime.now(tz=timezone.utc) + timedelta(hours=1)

        # 确认数量
        initial_count = len(token_blacklist._blacklist)
        assert initial_count >= 4  # 3 个过期 + 1 个未过期

        # 清理过期的
        cleaned = clean_expired_blacklist()
        assert cleaned >= 3  # 至少清理了 3 个过期项

        # 未过期的应该保留
        assert token_blacklist.is_blacklisted(valid_jti) is True

        # 过期的应该被清理了
        for jti in expired_jtis:
            assert token_blacklist.is_blacklisted(jti) is False

    def test_rotate_jwt_secret(self, jwt_handler):
        """测试密钥轮换接口"""
        from backend.auth import create_access_token, rotate_jwt_secret, _get_jwt_handler
        from backend.config import settings

        handler_before = jwt_handler

        # 用旧密钥签发 Token
        old_token = create_access_token(data={"sub": "testuser"})
        assert handler_before.is_access_token_valid(old_token)

        # 轮换密钥
        new_secret = "new-test-secret-key-for-rotation-1234567890"
        result = rotate_jwt_secret(new_secret)
        assert result is True

        # 新 handler 应该无法验证旧 Token
        handler_after = _get_jwt_handler()
        assert handler_after is not None
        assert handler_after.is_access_token_valid(old_token) is False

        # 用新密钥签发的 Token 应该能验证
        new_token = create_access_token(data={"sub": "testuser"})
        assert handler_after.is_access_token_valid(new_token)

        # 恢复旧密钥（避免影响其他测试）
        rotate_jwt_secret(settings.jwt_secret)

    def test_backward_compatibility_legacy_token(self, jwt_handler):
        """测试向后兼容：旧格式 Token（不含 type/jti）仍能验证通过"""
        from backend.auth import _decode_token_legacy
        from jose import jwt as jose_jwt
        from backend.config import settings

        # 构造一个旧格式的 Token（不含 type 和 jti 字段）
        legacy_payload = {
            "sub": "legacyuser",
            "role": "viewer",
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=30),
        }
        legacy_token = jose_jwt.encode(
            legacy_payload,
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        # 新格式验证（带 type=access）应该失败
        assert jwt_handler.decode_token(legacy_token, token_type="access") is None

        # 旧格式验证应该成功
        legacy_payload_decoded = _decode_token_legacy(legacy_token)
        assert legacy_payload_decoded is not None
        assert legacy_payload_decoded.get("sub") == "legacyuser"
        assert legacy_payload_decoded.get("role") == "viewer"


# ===========================================================================
# 单元测试：M8 特有功能（不依赖统一 JWTHandler）
# ===========================================================================

class TestM8AuthFeatures:
    """M8 认证模块特有功能测试（单元测试，不依赖 JWTHandler）"""

    def test_password_hash_and_verify(self):
        """测试密码哈希和验证功能（M8 特有功能保留）"""
        from backend.auth import get_password_hash, verify_password

        password = "TestPassword123!@#"
        hashed = get_password_hash(password)

        assert hashed != password
        assert verify_password(password, hashed) is True
        assert verify_password("wrongpassword", hashed) is False

    def test_password_hash_empty_password(self):
        """测试空密码哈希"""
        from backend.auth import get_password_hash, verify_password

        hashed = get_password_hash("")
        assert verify_password("", hashed) is True
        assert verify_password("notempty", hashed) is False

    def test_password_hash_consistency(self):
        """测试同一密码每次哈希结果不同（加盐）"""
        from backend.auth import get_password_hash

        password = "SamePassword123!"
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        # 由于加盐，两次哈希结果应该不同
        assert hash1 != hash2

    def test_role_hierarchy(self):
        """测试角色层级权限判断（M8 特有功能保留）"""
        from backend.auth import has_role, ROLE_LEVELS, VALID_ROLES

        # 角色层级定义正确
        assert "owner" in ROLE_LEVELS
        assert "admin" in ROLE_LEVELS
        assert "auditor" in ROLE_LEVELS
        assert "user" in ROLE_LEVELS
        assert "viewer" in ROLE_LEVELS

        # 层级正确：owner > admin > auditor > user > viewer
        assert has_role("owner", "admin") is True
        assert has_role("admin", "user") is True
        assert has_role("auditor", "viewer") is True
        assert has_role("user", "viewer") is True

        # 反向不成立
        assert has_role("viewer", "admin") is False
        assert has_role("user", "owner") is False
        assert has_role("auditor", "admin") is False

        # 同级成立
        assert has_role("admin", "admin") is True
        assert has_role("viewer", "viewer") is True

        # 未知角色返回 0 级
        assert has_role("unknown_role", "viewer") is False

    def test_role_levels_order(self):
        """测试角色层级的数值顺序"""
        from backend.auth import ROLE_LEVELS

        # owner 级别最高
        assert ROLE_LEVELS["owner"] > ROLE_LEVELS["admin"]
        assert ROLE_LEVELS["admin"] > ROLE_LEVELS["auditor"]
        assert ROLE_LEVELS["auditor"] > ROLE_LEVELS["user"]
        assert ROLE_LEVELS["user"] > ROLE_LEVELS["viewer"]

    def test_verify_m8_token(self):
        """测试 M8 内部 Token 验证（M8 特有功能保留）"""
        from backend.auth import verify_m8_token
        from backend.config import settings

        assert verify_m8_token(settings.m8_admin_token) is True
        assert verify_m8_token("wrong-token") is False
        assert verify_m8_token("") is False

    def test_verify_m8_token_none(self):
        """测试 None Token 验证"""
        from backend.auth import verify_m8_token

        assert verify_m8_token(None) is False


# ===========================================================================
# 单元测试：JWTHandler 不可用时的回退行为（使用 mock）
# ===========================================================================

class TestJWTFallbackBehavior:
    """测试 JWTHandler 不可用时的回退行为（使用 mock 隔离依赖）"""

    def test_decode_token_legacy_format(self):
        """测试旧格式 Token 的解码函数 _decode_token_legacy.

        验证向后兼容的旧格式解码功能正常工作。
        """
        from backend.auth import _decode_token_legacy
        from jose import jwt as jose_jwt
        from backend.config import settings

        # 构造旧格式 Token（不含 type/jti）
        legacy_payload = {
            "sub": "testuser",
            "role": "admin",
            "exp": datetime.now(tz=timezone.utc) + timedelta(hours=1),
        }
        legacy_token = jose_jwt.encode(
            legacy_payload,
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        # 旧格式解码应该成功
        decoded = _decode_token_legacy(legacy_token)
        assert decoded is not None
        assert decoded.get("sub") == "testuser"
        assert decoded.get("role") == "admin"

    def test_decode_token_legacy_expired(self):
        """测试过期的旧格式 Token 解码返回 None"""
        from backend.auth import _decode_token_legacy
        from jose import jwt as jose_jwt
        from backend.config import settings

        # 构造已过期的旧格式 Token
        expired_payload = {
            "sub": "testuser",
            "exp": datetime.now(tz=timezone.utc) - timedelta(hours=1),
        }
        expired_token = jose_jwt.encode(
            expired_payload,
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        # 过期 Token 应该返回 None
        decoded = _decode_token_legacy(expired_token)
        assert decoded is None

    def test_decode_token_legacy_invalid_signature(self):
        """测试签名错误的旧格式 Token 解码返回 None"""
        from backend.auth import _decode_token_legacy
        from jose import jwt as jose_jwt

        # 用错误的密钥签名
        invalid_payload = {
            "sub": "testuser",
            "exp": datetime.now(tz=timezone.utc) + timedelta(hours=1),
        }
        invalid_token = jose_jwt.encode(
            invalid_payload,
            "wrong-secret-key-for-testing",
            algorithm="HS256",
        )

        # 签名错误应该返回 None
        decoded = _decode_token_legacy(invalid_token)
        assert decoded is None

    def test_get_jwt_handler_returns_none_when_unavailable(self):
        """测试 _get_jwt_handler 在不可用时返回 None"""
        import backend.auth as auth_mod

        orig_handler = auth_mod._jwt_handler
        orig_init_failed = auth_mod._jwt_init_failed
        orig_has_unified = auth_mod._HAS_UNIFIED_JWT

        try:
            auth_mod._jwt_handler = None
            auth_mod._jwt_init_failed = True
            auth_mod._HAS_UNIFIED_JWT = False

            result = auth_mod._get_jwt_handler()
            assert result is None
        finally:
            auth_mod._jwt_handler = orig_handler
            auth_mod._jwt_init_failed = orig_init_failed
            auth_mod._HAS_UNIFIED_JWT = orig_has_unified

    def test_get_token_blacklist_works_independently(self):
        """测试 _get_token_blacklist 不依赖 JWTHandler"""
        from backend.auth import _get_token_blacklist

        bl = _get_token_blacklist()
        # 黑名单应该可用（不依赖 JWTHandler）
        assert bl is not None
        assert hasattr(bl, "is_blacklisted")
        assert hasattr(bl, "add")

    def test_blacklist_add_and_check_unit(self):
        """单元测试黑名单的 add 和 is_blacklisted 方法"""
        from backend.auth import _get_token_blacklist

        bl = _get_token_blacklist()
        assert bl is not None

        # 添加一个 jti 到黑名单（需要 token_hash 和 expired_at）
        test_jti = "test-unit-jti-12345"
        test_hash = "sha256_hash_of_token"
        expired_at = datetime.now(tz=timezone.utc) + timedelta(hours=1)

        bl.add(test_jti, test_hash, expired_at)

        # 检查是否在黑名单中
        assert bl.is_blacklisted(test_jti) is True

        # 未添加的应该不在黑名单中
        assert bl.is_blacklisted("non-existent-jti") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
