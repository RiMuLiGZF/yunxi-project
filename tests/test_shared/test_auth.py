"""
shared.core.auth 模块单元测试

测试内容：
- JWT Token 签发与验证
- JWT Config 安全性检查
- Token 黑名单
- API Key 生成与验证
- API Key 存储
- 密码哈希与验证
"""

import pytest
import hashlib
from datetime import datetime, timedelta, timezone


# ============================================================
# JWT 测试
# ============================================================

class TestJWTConfig:
    """JWT 配置类测试"""

    @pytest.fixture
    def make_config(self):
        """创建 JWTConfig 的工厂函数"""
        def _factory(**kwargs):
            from shared.core.auth.jwt import JWTConfig
            defaults = {
                "secret": "test-secret-key-very-long-for-security-123456",
                "algorithm": "HS256",
                "require_secure_secret": False,
            }
            defaults.update(kwargs)
            return JWTConfig(**defaults)
        return _factory

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_default_values(self, make_config):
        """默认配置值正确"""
        config = make_config()
        assert config.algorithm == "HS256"
        assert config.access_token_expire_minutes == 1440
        assert config.refresh_token_expire_days == 7

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_short_secret_is_default(self, make_config):
        """短密钥被识别为默认/不安全密钥"""
        config = make_config(secret="short")
        assert config.is_default_secret is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_long_secret_is_safe(self, make_config):
        """长密钥被识别为安全密钥"""
        config = make_config(secret="a" * 40)
        assert config.is_default_secret is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_empty_secret_is_default(self, make_config):
        """空密钥被识别为默认密钥"""
        config = make_config(secret="")
        assert config.is_default_secret is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_validate_secure_secret_pass(self, make_config):
        """安全密钥通过验证"""
        config = make_config(
            secret="a" * 40,
            require_secure_secret=True,
        )
        # 不抛出异常即为通过
        config.validate()

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_validate_short_secret_fails(self, make_config):
        """短密钥验证失败"""
        config = make_config(
            secret="short",
            require_secure_secret=True,
        )
        with pytest.raises(ValueError):
            config.validate()

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_validate_skip_when_not_required(self, make_config):
        """require_secure_secret=False 时跳过验证"""
        config = make_config(
            secret="short",
            require_secure_secret=False,
        )
        # 不抛出异常即为通过
        config.validate()


class TestJWTHandler:
    """JWT 处理器测试"""

    @pytest.fixture
    def handler(self):
        """创建 JWT 处理器"""
        try:
            from shared.core.auth.jwt import JWTHandler, JWTConfig
            config = JWTConfig(
                secret="test-secret-key-for-unit-tests-only-1234567890",
                algorithm="HS256",
                access_token_expire_minutes=60,
                refresh_token_expire_days=7,
                require_secure_secret=False,
            )
            return JWTHandler(config)
        except ImportError:
            pytest.skip("JWT 模块不可用")

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_create_access_token(self, handler):
        """创建 Access Token"""
        token = handler.create_access_token({"sub": "user1", "role": "admin"})
        assert isinstance(token, str)
        assert len(token) > 0
        # JWT 格式：header.payload.signature
        parts = token.split(".")
        assert len(parts) == 3

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_decode_valid_token(self, handler):
        """解码有效 Token"""
        token = handler.create_access_token({"sub": "user1", "role": "admin"})
        payload = handler.decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user1"
        assert payload["role"] == "admin"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_decode_invalid_token_returns_none(self, handler):
        """解码无效 Token 返回 None"""
        result = handler.decode_token("invalid.token.here")
        assert result is None

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_decode_empty_token_returns_none(self, handler):
        """解码空 Token 返回 None"""
        result = handler.decode_token("")
        assert result is None

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_access_token_has_type(self, handler):
        """Access Token 包含 type=access"""
        token = handler.create_access_token({"sub": "user1"})
        payload = handler.decode_token(token)
        assert payload["type"] == "access"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_refresh_token_has_type(self, handler):
        """Refresh Token 包含 type=refresh"""
        token = handler.create_refresh_token({"sub": "user1"})
        payload = handler.decode_token(token)
        assert payload["type"] == "refresh"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_is_access_token_valid(self, handler):
        """is_access_token_valid 正确判断"""
        token = handler.create_access_token({"sub": "user1"})
        assert handler.is_access_token_valid(token) is True

        refresh = handler.create_refresh_token({"sub": "user1"})
        assert handler.is_access_token_valid(refresh) is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_is_refresh_token_valid(self, handler):
        """is_refresh_token_valid 正确判断"""
        token = handler.create_refresh_token({"sub": "user1"})
        assert handler.is_refresh_token_valid(token) is True

        access = handler.create_access_token({"sub": "user1"})
        assert handler.is_refresh_token_valid(access) is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_token_contains_jti(self, handler):
        """Token 包含 JTI"""
        token = handler.create_access_token({"sub": "user1"})
        payload = handler.decode_token(token)
        assert "jti" in payload
        assert len(payload["jti"]) > 0

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_token_contains_iat(self, handler):
        """Token 包含签发时间"""
        token = handler.create_access_token({"sub": "user1"})
        payload = handler.decode_token(token)
        assert "iat" in payload

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_token_contains_exp(self, handler):
        """Token 包含过期时间"""
        token = handler.create_access_token({"sub": "user1"})
        payload = handler.decode_token(token)
        assert "exp" in payload
        assert payload["exp"] > payload["iat"]

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_custom_expires_delta(self, handler):
        """自定义过期时间"""
        custom_expire = timedelta(minutes=5)
        token = handler.create_access_token({"sub": "user1"}, expires_delta=custom_expire)
        payload = handler.decode_token(token)
        # 5 分钟 = 300 秒
        ttl = payload["exp"] - payload["iat"]
        assert 290 < ttl < 310  # 允许 10 秒误差

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_hash_token(self, handler):
        """hash_token 返回 SHA256 哈希"""
        token = handler.create_access_token({"sub": "user1"})
        hashed = handler.hash_token(token)
        assert isinstance(hashed, str)
        assert len(hashed) == 64  # SHA256 hex
        # 验证哈希正确
        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert hashed == expected

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_get_jti(self, handler):
        """get_jti 提取 JTI"""
        token = handler.create_access_token({"sub": "user1"})
        jti = handler.get_jti(token)
        assert jti is not None
        assert len(jti) > 0

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_get_jti_invalid_token(self, handler):
        """无效 Token 的 JTI 返回 None"""
        jti = handler.get_jti("not-a-valid-jwt")
        assert jti is None

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_refresh_access_token(self, handler):
        """使用 Refresh Token 刷新 Access Token"""
        refresh_token = handler.create_refresh_token({"sub": "user1"})
        result = handler.refresh_access_token(refresh_token)
        assert result is not None
        assert "access_token" in result
        assert "refresh_token" in result
        assert "token_type" in result
        assert "expires_in" in result
        assert result["token_type"] == "bearer"
        assert result["expires_in"] == 3600  # 60 * 60

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_refresh_with_invalid_token(self, handler):
        """无效 Refresh Token 刷新失败"""
        result = handler.refresh_access_token("invalid-token")
        assert result is None

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_token_with_issuer(self):
        """带签发者的 Token"""
        from shared.core.auth.jwt import JWTHandler, JWTConfig
        config = JWTConfig(
            secret="test-secret-key-for-unit-tests-only-1234567890",
            algorithm="HS256",
            issuer="yunxi-test",
            require_secure_secret=False,
        )
        handler = JWTHandler(config)
        token = handler.create_access_token({"sub": "user1"})
        payload = handler.decode_token(token)
        assert payload["iss"] == "yunxi-test"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_is_jwt_available_function(self):
        """is_jwt_available 函数"""
        from shared.core.auth.jwt import is_jwt_available
        result = is_jwt_available()
        assert isinstance(result, bool)


# ============================================================
# Token 黑名单测试
# ============================================================

class TestTokenBlacklist:
    """Token 黑名单测试"""

    @pytest.fixture
    def blacklist(self):
        """创建内存版黑名单"""
        from shared.core.auth.jwt import InMemoryTokenBlacklist
        return InMemoryTokenBlacklist()

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_empty_blacklist_returns_false(self, blacklist):
        """空黑名单检查返回 False"""
        assert blacklist.is_blacklisted("any-jti") is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_add_and_check(self, blacklist):
        """添加后检查返回 True"""
        future = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        blacklist.add("jti-123", "hash-abc", future)
        assert blacklist.is_blacklisted("jti-123") is True
        assert blacklist.is_blacklisted("jti-456") is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_expired_token_not_blacklisted(self, blacklist):
        """已过期的 Token 不计入黑名单"""
        past = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        blacklist.add("jti-expired", "hash-xyz", past)
        assert blacklist.is_blacklisted("jti-expired") is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_empty_jti_not_blacklisted(self, blacklist):
        """空 JTI 不被视为黑名单"""
        assert blacklist.is_blacklisted("") is False
        assert blacklist.is_blacklisted(None) is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.jwt
    def test_clean_expired(self, blacklist):
        """清理过期 Token"""
        future = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        past = datetime.now(tz=timezone.utc) - timedelta(hours=1)

        blacklist.add("jti-valid", "hash-1", future)
        blacklist.add("jti-expired-1", "hash-2", past)
        blacklist.add("jti-expired-2", "hash-3", past)

        cleaned = blacklist.clean_expired()
        assert cleaned == 2
        assert blacklist.is_blacklisted("jti-valid") is True


# ============================================================
# API Key 测试
# ============================================================

class TestApiKeyGeneration:
    """API Key 生成测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_generate_api_key_default(self):
        """生成默认 API Key"""
        from shared.core.auth.api_key import generate_api_key
        key = generate_api_key()
        assert isinstance(key, str)
        assert key.startswith("yx-")
        assert len(key) > 10

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_generate_api_key_custom_prefix(self):
        """自定义前缀"""
        from shared.core.auth.api_key import generate_api_key
        key = generate_api_key(prefix="m11-")
        assert key.startswith("m11-")

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_generate_api_key_custom_length(self):
        """自定义长度"""
        from shared.core.auth.api_key import generate_api_key
        key = generate_api_key(length=50)
        # 前缀 3 字符 + 50 字符随机部分
        assert len(key) == 3 + 50

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_generate_api_key_invalid_length(self):
        """无效长度抛出异常"""
        from shared.core.auth.api_key import generate_api_key
        with pytest.raises(ValueError):
            generate_api_key(length=0)
        with pytest.raises(ValueError):
            generate_api_key(length=-1)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_generate_keys_unique(self):
        """生成的密钥唯一"""
        from shared.core.auth.api_key import generate_api_key
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100  # 100 个都是唯一的


class TestApiKeyHashing:
    """API Key 哈希测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_sha256_hash(self):
        """SHA256 哈希"""
        from shared.core.auth.api_key import hash_api_key_sha256
        key = "test-api-key-12345"
        hashed = hash_api_key_sha256(key)
        assert len(hashed) == 64
        # 验证哈希一致性
        assert hashed == hashlib.sha256(key.encode("utf-8")).hexdigest()

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_hash_consistency(self):
        """相同输入产生相同哈希"""
        from shared.core.auth.api_key import hash_api_key_sha256
        key = "consistent-key"
        assert hash_api_key_sha256(key) == hash_api_key_sha256(key)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_verify_sha256_hash(self):
        """SHA256 哈希验证"""
        from shared.core.auth.api_key import hash_api_key_sha256, verify_api_key_hash
        key = "test-verify-key"
        hashed = hash_api_key_sha256(key)
        assert verify_api_key_hash(key, hashed, use_bcrypt=False) is True
        assert verify_api_key_hash("wrong-key", hashed, use_bcrypt=False) is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_verify_empty_key(self):
        """空密钥验证返回 False"""
        from shared.core.auth.api_key import verify_api_key_hash
        assert verify_api_key_hash("", "some-hash") is False
        assert verify_api_key_hash("key", "") is False


class TestApiKeyMasking:
    """API Key 脱敏测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_mask_default(self):
        """默认脱敏方式"""
        from shared.core.auth.api_key import mask_api_key
        key = "yx-abcdefghijklmnopqrstuvwxyz123456"
        masked = mask_api_key(key)
        assert masked.startswith("yx-abc")
        assert masked.endswith("3456")
        assert "*" in masked

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_mask_custom_show(self):
        """自定义显示位数"""
        from shared.core.auth.api_key import mask_api_key
        key = "abcdefghijklmnop"
        masked = mask_api_key(key, show_first=3, show_last=2)
        assert masked.startswith("abc")
        assert masked.endswith("op")

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_mask_short_key(self):
        """短密钥全部隐藏"""
        from shared.core.auth.api_key import mask_api_key
        key = "ab"
        masked = mask_api_key(key)
        assert masked == "**"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_mask_empty_key(self):
        """空密钥返回空"""
        from shared.core.auth.api_key import mask_api_key
        assert mask_api_key("") == ""
        assert mask_api_key(None) == ""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_get_api_key_prefix(self):
        """获取密钥前缀"""
        from shared.core.auth.api_key import get_api_key_prefix
        key = "m11-abcdefghijklmnop"
        prefix = get_api_key_prefix(key)
        assert prefix == key[:8]

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_get_api_key_prefix_short(self):
        """短密钥返回完整内容"""
        from shared.core.auth.api_key import get_api_key_prefix
        key = "abc"
        assert get_api_key_prefix(key) == "abc"


class TestInMemoryApiKeyStore:
    """内存版 API Key 存储测试"""

    @pytest.fixture
    def store(self):
        """创建内存存储"""
        from shared.core.auth.api_key import InMemoryApiKeyStore, ApiKeyInfo, hash_api_key_sha256
        store = InMemoryApiKeyStore()
        # 添加测试密钥
        key_hash = hash_api_key_sha256("test-key-12345")
        store.add_key(ApiKeyInfo(
            key_hash=key_hash,
            key_name="test-key",
            key_prefix="test-key",
            roles=["admin"],
            scopes=["*"],
        ))
        return store

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_get_all_active(self, store):
        """获取所有活跃密钥"""
        keys = store.get_all_active()
        assert len(keys) == 1
        assert keys[0].key_name == "test-key"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_find_by_hash(self, store):
        """按哈希查找"""
        from shared.core.auth.api_key import hash_api_key_sha256
        key_hash = hash_api_key_sha256("test-key-12345")
        found = store.find_by_hash(key_hash)
        assert found is not None
        assert found.key_name == "test-key"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_find_by_hash_not_found(self, store):
        """未找到返回 None"""
        found = store.find_by_hash("nonexistent-hash")
        assert found is None

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_remove_key(self, store):
        """移除密钥"""
        from shared.core.auth.api_key import hash_api_key_sha256
        key_hash = hash_api_key_sha256("test-key-12345")
        assert store.remove_key(key_hash) is True
        assert store.get_all_active() == []
        # 再次移除返回 False
        assert store.remove_key(key_hash) is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_increment_usage(self, store):
        """增加使用统计"""
        key = store.get_all_active()[0]
        initial_count = key.call_count
        store.increment_usage(key)
        assert key.call_count == initial_count + 1
        assert key.last_used_at is not None


class TestApiKeyValidator:
    """API Key 验证器测试"""

    @pytest.fixture
    def validator_and_key(self):
        """创建验证器和测试密钥"""
        from shared.core.auth.api_key import (
            InMemoryApiKeyStore, ApiKeyInfo, ApiKeyValidator, hash_api_key_sha256,
        )
        store = InMemoryApiKeyStore()
        api_key = "test-validator-key-1234567890"
        key_hash = hash_api_key_sha256(api_key)
        store.add_key(ApiKeyInfo(
            key_hash=key_hash,
            key_name="validator-test",
            roles=["user"],
            scopes=["read"],
        ))
        validator = ApiKeyValidator(store, use_bcrypt=False)
        return validator, api_key

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_validate_valid_key(self, validator_and_key):
        """验证有效密钥"""
        validator, api_key = validator_and_key
        result = validator.validate(api_key)
        assert result is not None
        assert result.key_name == "validator-test"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_validate_invalid_key(self, validator_and_key):
        """验证无效密钥"""
        validator, _ = validator_and_key
        result = validator.validate("wrong-key")
        assert result is None

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_validate_empty_key(self, validator_and_key):
        """验证空密钥"""
        validator, _ = validator_and_key
        assert validator.validate("") is None
        assert validator.validate(None) is None

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_validate_increments_usage(self, validator_and_key):
        """验证成功增加使用次数"""
        validator, api_key = validator_and_key
        result1 = validator.validate(api_key)
        count1 = result1.call_count
        result2 = validator.validate(api_key)
        assert result2.call_count == count1 + 1

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_validate_sha256_fast(self, validator_and_key):
        """快速 SHA256 验证"""
        validator, api_key = validator_and_key
        result = validator.validate_sha256_fast(api_key)
        assert result is not None
        assert result.key_name == "validator-test"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_is_bcrypt_available_function(self):
        """is_bcrypt_available 函数"""
        from shared.core.auth.api_key import is_bcrypt_available
        result = is_bcrypt_available()
        assert isinstance(result, bool)


# ============================================================
# ApiKeyInfo 测试
# ============================================================

class TestApiKeyInfo:
    """API Key 信息类测试"""

    @pytest.fixture
    def key_info(self):
        """创建测试用 ApiKeyInfo"""
        from shared.core.auth.api_key import ApiKeyInfo
        return ApiKeyInfo(
            key_hash="test-hash-123",
            key_name="my-key",
            key_prefix="my-key-p",
            owner="user1",
            roles=["admin", "user"],
            scopes=["read", "write"],
        )

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_to_dict_excludes_hash_by_default(self, key_info):
        """to_dict 默认不包含哈希"""
        d = key_info.to_dict()
        assert "key_hash" not in d
        assert "key_name" in d
        assert "roles" in d

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_to_dict_include_hash(self, key_info):
        """to_dict 可以选择包含哈希"""
        d = key_info.to_dict(include_hash=True)
        assert "key_hash" in d
        assert d["key_hash"] == "test-hash-123"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_is_active_default_true(self, key_info):
        """默认激活状态为 True"""
        assert key_info.is_active is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_is_expired_no_expiry(self, key_info):
        """无过期时间则永不过期"""
        assert key_info.is_expired() is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_is_expired_past(self):
        """已过期的密钥"""
        from shared.core.auth.api_key import ApiKeyInfo
        info = ApiKeyInfo(
            key_hash="test",
            expires_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        )
        assert info.is_expired() is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.apikey
    def test_is_expired_future(self):
        """未过期的密钥"""
        from shared.core.auth.api_key import ApiKeyInfo
        info = ApiKeyInfo(
            key_hash="test",
            expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        )
        assert info.is_expired() is False
