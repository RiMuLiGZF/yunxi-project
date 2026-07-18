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


class TestJWTMigration:
    """JWT 迁移到统一认证体系测试"""

    def test_create_access_token_contains_jti(self):
        """测试新签发的 Token 包含 JTI 唯一标识"""
        from backend.auth import create_access_token, _get_jwt_handler

        handler = _get_jwt_handler()
        if handler is None:
            pytest.skip("统一 JWTHandler 不可用，跳过测试")

        token = create_access_token(data={"sub": "testuser", "role": "admin"})
        assert token is not None
        assert isinstance(token, str)

        # 验证 Token 包含 JTI
        jti = handler.get_jti(token)
        assert jti is not None
        assert len(jti) > 0  # JTI 是 uuid4.hex，32 字符

    def test_create_access_token_contains_type(self):
        """测试新签发的 Token 包含 type=access 字段"""
        from backend.auth import create_access_token, _get_jwt_handler

        handler = _get_jwt_handler()
        if handler is None:
            pytest.skip("统一 JWTHandler 不可用，跳过测试")

        token = create_access_token(data={"sub": "testuser", "role": "admin"})
        payload = handler.decode_token(token, token_type="access")
        assert payload is not None
        assert payload.get("type") == "access"
        assert payload.get("sub") == "testuser"
        assert payload.get("role") == "admin"

    def test_token_uses_utc_timezone(self):
        """测试 Token 使用 UTC 时区（datetime.now(tz=timezone.utc)）"""
        from backend.auth import create_access_token, _get_jwt_handler

        handler = _get_jwt_handler()
        if handler is None:
            pytest.skip("统一 JWTHandler 不可用，跳过测试")

        before = datetime.now(tz=timezone.utc)
        token = create_access_token(data={"sub": "testuser"})
        after = datetime.now(tz=timezone.utc)

        payload = handler.decode_token(token)
        assert payload is not None

        # iat 应该在 before 和 after 之间（允许 1 秒误差，因为 JWT 的 iat 是整数秒）
        iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        # iat 是整秒，所以 before 可能比 iat 多不到 1 秒
        assert (before - timedelta(seconds=1)) <= iat <= (after + timedelta(seconds=1))

        # exp 应该在 iat + expire 时间范围内
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert exp > iat

    def test_token_blacklist_add_and_check(self):
        """测试 Token 黑名单功能：加入黑名单后验证失败"""
        from backend.auth import (
            create_access_token,
            blacklist_token,
            _get_jwt_handler,
            _get_token_blacklist,
            clean_expired_blacklist,
        )

        handler = _get_jwt_handler()
        bl = _get_token_blacklist()
        if handler is None or bl is None:
            pytest.skip("统一 JWTHandler 或黑名单不可用，跳过测试")

        # 签发 Token
        token = create_access_token(data={"sub": "testuser", "role": "user"})
        assert handler.is_access_token_valid(token)

        # 加入黑名单
        result = blacklist_token(token)
        assert result is True

        # 黑名单验证应该返回 True
        jti = handler.get_jti(token)
        assert bl.is_blacklisted(jti) is True

    def test_blacklist_clean_expired(self):
        """测试清理已过期的黑名单 Token"""
        from backend.auth import _get_token_blacklist, clean_expired_blacklist

        bl = _get_token_blacklist()
        if bl is None:
            pytest.skip("黑名单不可用，跳过测试")

        # 添加多个已过期的 Token 到黑名单
        # 注意：InMemoryTokenBlacklist.is_blacklisted 在检查时会自动清理过期项，
        # 所以直接操作内部字典来添加过期项
        from datetime import timezone
        expired_jtis = [
            "expired-jti-001",
            "expired-jti-002",
            "expired-jti-003",
        ]
        for jti in expired_jtis:
            bl._blacklist[jti] = datetime.now(tz=timezone.utc) - timedelta(hours=1)

        # 添加一个未过期的
        valid_jti = "valid-jti-001"
        bl._blacklist[valid_jti] = datetime.now(tz=timezone.utc) + timedelta(hours=1)

        # 确认数量
        initial_count = len(bl._blacklist)
        assert initial_count >= 4  # 3 个过期 + 1 个未过期

        # 清理过期的
        cleaned = clean_expired_blacklist()
        assert cleaned >= 3  # 至少清理了 3 个过期项

        # 未过期的应该保留
        assert bl.is_blacklisted(valid_jti) is True

        # 过期的应该被清理了
        for jti in expired_jtis:
            assert bl.is_blacklisted(jti) is False

    def test_rotate_jwt_secret(self):
        """测试密钥轮换接口"""
        from backend.auth import create_access_token, rotate_jwt_secret, _get_jwt_handler

        handler_before = _get_jwt_handler()
        if handler_before is None:
            pytest.skip("统一 JWTHandler 不可用，跳过测试")

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
        from backend.config import settings
        rotate_jwt_secret(settings.jwt_secret)

    def test_backward_compatibility_legacy_token(self):
        """测试向后兼容：旧格式 Token（不含 type/jti）仍能验证通过"""
        from backend.auth import _get_jwt_handler, _decode_token_legacy

        handler = _get_jwt_handler()
        if handler is None:
            pytest.skip("统一 JWTHandler 不可用，跳过测试")

        # 构造一个旧格式的 Token（不含 type 和 jti 字段）
        from jose import jwt as jose_jwt
        from backend.config import settings

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
        assert handler.decode_token(legacy_token, token_type="access") is None

        # 旧格式验证应该成功
        legacy_payload_decoded = _decode_token_legacy(legacy_token)
        assert legacy_payload_decoded is not None
        assert legacy_payload_decoded.get("sub") == "legacyuser"
        assert legacy_payload_decoded.get("role") == "viewer"

    def test_password_hash_and_verify(self):
        """测试密码哈希和验证功能（M8 特有功能保留）"""
        from backend.auth import get_password_hash, verify_password

        password = "TestPassword123!@#"
        hashed = get_password_hash(password)

        assert hashed != password
        assert verify_password(password, hashed) is True
        assert verify_password("wrongpassword", hashed) is False

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

    def test_verify_m8_token(self):
        """测试 M8 内部 Token 验证（M8 特有功能保留）"""
        from backend.auth import verify_m8_token
        from backend.config import settings

        assert verify_m8_token(settings.m8_admin_token) is True
        assert verify_m8_token("wrong-token") is False
        assert verify_m8_token("") is False
