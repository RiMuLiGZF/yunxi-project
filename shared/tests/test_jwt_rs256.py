"""
统一认证体系 - JWT RS256 非对称加密测试

测试 RS256 签名和验证、密钥生成和加载、密钥轮换、kid 头验证、
HS256 到 RS256 的兼容迁移、错误处理等功能。
"""

import sys
import os
import tempfile
import shutil
from pathlib import Path
from datetime import timedelta

import pytest

# 确保可以导入 shared 模块
SHARED_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SHARED_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


# ===========================================================================
# RS256 基本功能测试
# ===========================================================================

class TestRS256Basic:
    """RS256 签名和验证基本测试"""

    def test_rs256_create_and_decode_access_token(self):
        """RS256 Access Token 签发与验证"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        # 生成密钥对
        private_pem, public_pem = RSAKeyManager.generate_keypair(2048)

        config = JWTConfig(
            algorithm="RS256",
            private_key=private_pem,
            public_key=public_pem,
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
        # JWT 格式：header.payload.signature
        assert token.count(".") == 2

        # 验证 Token
        payload = handler.decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user_123"
        assert payload["username"] == "testuser"
        assert payload["roles"] == ["admin"]
        assert payload["type"] == "access"
        assert "jti" in payload
        assert "exp" in payload
        assert "iat" in payload

    def test_rs256_create_and_decode_refresh_token(self):
        """RS256 Refresh Token 签发与验证"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        private_pem, public_pem = RSAKeyManager.generate_keypair(2048)

        config = JWTConfig(
            algorithm="RS256",
            private_key=private_pem,
            public_key=public_pem,
            refresh_token_expire_days=7,
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        token = handler.create_refresh_token({"sub": "user_123"})
        assert isinstance(token, str)

        # 验证 refresh token
        payload = handler.decode_token(token, token_type="refresh")
        assert payload is not None
        assert payload["sub"] == "user_123"
        assert payload["type"] == "refresh"

        # 验证 access token 类型不匹配
        payload = handler.decode_token(token, token_type="access")
        assert payload is None

    def test_rs256_invalid_token_returns_none(self):
        """RS256 无效 Token 返回 None"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        private_pem, public_pem = RSAKeyManager.generate_keypair(2048)

        config = JWTConfig(
            algorithm="RS256",
            private_key=private_pem,
            public_key=public_pem,
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        # 完全无效的字符串
        assert handler.decode_token("invalid.token.here") is None
        assert handler.decode_token("") is None
        assert handler.decode_token("not-a-jwt") is None

    def test_rs256_wrong_public_key_fails_verification(self):
        """RS256 使用错误的公钥验证失败"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        # 生成两对密钥
        priv1, pub1 = RSAKeyManager.generate_keypair(2048)
        priv2, pub2 = RSAKeyManager.generate_keypair(2048)

        # 用密钥对1签名
        config1 = JWTConfig(
            algorithm="RS256",
            private_key=priv1,
            public_key=pub1,
            require_secure_secret=False,
        )
        handler1 = JWTHandler(config1)
        token = handler1.create_access_token({"sub": "user1"})

        # 用密钥对2的公钥验证，应该失败
        config2 = JWTConfig(
            algorithm="RS256",
            private_key=priv2,
            public_key=pub2,
            require_secure_secret=False,
        )
        handler2 = JWTHandler(config2)
        payload = handler2.decode_token(token)
        assert payload is None

    def test_rs256_token_expiration(self):
        """RS256 过期 Token 验证失败"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        private_pem, public_pem = RSAKeyManager.generate_keypair(2048)

        config = JWTConfig(
            algorithm="RS256",
            private_key=private_pem,
            public_key=public_pem,
            access_token_expire_minutes=1,  # 1 分钟过期
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        # 生成一个已过期的 Token（通过设置负的过期时间）
        token = handler.create_access_token(
            {"sub": "user1"},
            expires_delta=timedelta(minutes=-1),
        )
        assert handler.decode_token(token) is None


# ===========================================================================
# kid 和密钥轮换测试
# ===========================================================================

class TestKidAndKeyRotation:
    """kid 头和密钥轮换测试"""

    def test_kid_header_in_token(self):
        """JWT Token 中包含 kid 头"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        private_pem, public_pem = RSAKeyManager.generate_keypair(2048)

        config = JWTConfig(
            algorithm="RS256",
            private_key=private_pem,
            public_key=public_pem,
            kid="test-key-001",
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        token = handler.create_access_token({"sub": "user1"})

        # 提取 kid
        kid = handler.get_kid(token)
        assert kid == "test-key-001"

    def test_no_kid_when_not_configured(self):
        """未配置 kid 时 Token 不包含 kid 头"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        private_pem, public_pem = RSAKeyManager.generate_keypair(2048)

        config = JWTConfig(
            algorithm="RS256",
            private_key=private_pem,
            public_key=public_pem,
            kid=None,  # 不设置 kid
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        token = handler.create_access_token({"sub": "user1"})
        kid = handler.get_kid(token)
        assert kid is None

    def test_verification_with_multiple_keys(self):
        """使用多密钥验证（密钥轮换场景）"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        # 生成两对密钥
        priv1, pub1 = RSAKeyManager.generate_keypair(2048)
        priv2, pub2 = RSAKeyManager.generate_keypair(2048)

        # 用旧密钥签发 Token
        old_config = JWTConfig(
            algorithm="RS256",
            private_key=priv1,
            public_key=pub1,
            kid="old-key",
            require_secure_secret=False,
        )
        old_handler = JWTHandler(old_config)
        old_token = old_handler.create_access_token({"sub": "user1"})

        # 新密钥的 handler 配置了旧公钥作为验证密钥
        new_config = JWTConfig(
            algorithm="RS256",
            private_key=priv2,
            public_key=pub2,
            kid="new-key",
            verification_keys={
                "old-key": pub1,
                "new-key": pub2,
            },
            require_secure_secret=False,
        )
        new_handler = JWTHandler(new_config)

        # 新 handler 应该能验证旧 Token
        payload = new_handler.decode_token(old_token)
        assert payload is not None
        assert payload["sub"] == "user1"

        # 新 handler 签发的新 Token 也能验证
        new_token = new_handler.create_access_token({"sub": "user2"})
        payload = new_handler.decode_token(new_token)
        assert payload is not None
        assert payload["sub"] == "user2"

    def test_verification_fails_with_unknown_kid(self):
        """未知 kid 的 Token 验证失败（不在 verification_keys 中）"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        priv1, pub1 = RSAKeyManager.generate_keypair(2048)
        priv2, pub2 = RSAKeyManager.generate_keypair(2048)

        # 用密钥1签发，kid 是 unknown
        config1 = JWTConfig(
            algorithm="RS256",
            private_key=priv1,
            public_key=pub1,
            kid="unknown-key",
            require_secure_secret=False,
        )
        handler1 = JWTHandler(config1)
        token = handler1.create_access_token({"sub": "user1"})

        # 密钥2的 handler，verification_keys 中没有 unknown-key
        config2 = JWTConfig(
            algorithm="RS256",
            private_key=priv2,
            public_key=pub2,
            kid="key2",
            verification_keys={"key2": pub2},
            require_secure_secret=False,
        )
        handler2 = JWTHandler(config2)

        # 应该验证失败（使用默认公钥 key2，不匹配）
        assert handler2.decode_token(token) is None

    def test_add_and_remove_verification_key(self):
        """动态添加和移除验证密钥"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        priv1, pub1 = RSAKeyManager.generate_keypair(2048)
        priv2, pub2 = RSAKeyManager.generate_keypair(2048)

        # 用密钥1签发
        config1 = JWTConfig(
            algorithm="RS256",
            private_key=priv1,
            public_key=pub1,
            kid="key1",
            require_secure_secret=False,
        )
        handler1 = JWTHandler(config1)
        token = handler1.create_access_token({"sub": "user1"})

        # 密钥2的 handler，初始没有 key1
        config2 = JWTConfig(
            algorithm="RS256",
            private_key=priv2,
            public_key=pub2,
            kid="key2",
            require_secure_secret=False,
        )
        handler2 = JWTHandler(config2)

        # 初始验证失败
        assert handler2.decode_token(token) is None

        # 添加 key1 的公钥
        handler2.add_verification_key("key1", pub1)
        # 现在应该能验证
        payload = handler2.decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user1"

        # 移除 key1
        handler2.remove_verification_key("key1")
        # 再次验证失败
        assert handler2.decode_token(token) is None


# ===========================================================================
# RSAKeyManager 测试
# ===========================================================================

class TestRSAKeyManager:
    """RSA 密钥管理器测试"""

    def setup_method(self):
        """每个测试前创建临时目录"""
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """每个测试后清理临时目录"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generate_keypair(self):
        """生成 RSA 密钥对"""
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        private_pem, public_pem = RSAKeyManager.generate_keypair(2048)

        assert isinstance(private_pem, str)
        assert isinstance(public_pem, str)
        assert "BEGIN PRIVATE KEY" in private_pem
        assert "END PRIVATE KEY" in private_pem
        assert "BEGIN PUBLIC KEY" in public_pem
        assert "END PUBLIC KEY" in public_pem

    def test_generate_keypair_4096(self):
        """生成 4096 位 RSA 密钥对"""
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        private_pem, public_pem = RSAKeyManager.generate_keypair(4096)
        assert "BEGIN PRIVATE KEY" in private_pem
        assert "BEGIN PUBLIC KEY" in public_pem

    def test_ensure_keys_creates_keys(self):
        """ensure_keys 在没有密钥时自动生成"""
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        key_dir = os.path.join(self.temp_dir, "keys")
        manager = RSAKeyManager(key_dir=key_dir)

        assert manager.ensure_keys() is True
        assert manager.key_count > 0
        assert manager.get_active_key() is not None
        assert manager.active_kid is not None

        # 检查文件是否存在
        active_key = manager.get_active_key()
        priv_file = os.path.join(key_dir, f"{active_key.kid}_private.pem")
        pub_file = os.path.join(key_dir, f"{active_key.kid}_public.pem")
        assert os.path.exists(priv_file)
        assert os.path.exists(pub_file)
        assert os.path.exists(os.path.join(key_dir, "jwt_private.pem"))
        assert os.path.exists(os.path.join(key_dir, "jwt_public.pem"))
        assert os.path.exists(os.path.join(key_dir, "keys_metadata.json"))

    def test_ensure_keys_persists(self):
        """ensure_keys 多次调用不重新生成密钥"""
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        key_dir = os.path.join(self.temp_dir, "keys")
        manager1 = RSAKeyManager(key_dir=key_dir)
        manager1.ensure_keys()
        kid1 = manager1.active_kid
        priv1 = manager1.get_active_key().private_key

        # 创建新的 manager 实例，加载相同目录
        manager2 = RSAKeyManager(key_dir=key_dir)
        manager2.ensure_keys()
        kid2 = manager2.active_kid
        priv2 = manager2.get_active_key().private_key

        # 应该是同一个密钥
        assert kid1 == kid2
        assert priv1 == priv2

    def test_rotate_keys(self):
        """密钥轮换功能"""
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        key_dir = os.path.join(self.temp_dir, "keys")
        manager = RSAKeyManager(key_dir=key_dir, old_key_retention_days=30)
        manager.ensure_keys()

        old_kid = manager.active_kid
        old_priv = manager.get_active_key().private_key

        # 执行轮换
        new_kid = manager.rotate_keys()

        assert new_kid is not None
        assert new_kid != old_kid
        assert manager.active_kid == new_kid
        assert manager.key_count == 2  # 新旧两个密钥

        # 旧密钥还在，但不是活跃的
        old_key = manager.get_key_by_kid(old_kid)
        assert old_key is not None
        assert old_key.is_active is False

        # 新密钥是活跃的
        new_key = manager.get_active_key()
        assert new_key.is_active is True
        assert new_key.private_key != old_priv

    def test_get_all_verification_keys(self):
        """获取所有验证公钥"""
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        key_dir = os.path.join(self.temp_dir, "keys")
        manager = RSAKeyManager(key_dir=key_dir, old_key_retention_days=30)
        manager.ensure_keys()
        manager.rotate_keys()

        verification_keys = manager.get_all_verification_keys()
        assert len(verification_keys) == 2
        assert manager.active_kid in verification_keys

        for kid, pub_key in verification_keys.items():
            assert "BEGIN PUBLIC KEY" in pub_key

    def test_get_key_by_kid(self):
        """根据 kid 查找密钥"""
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        key_dir = os.path.join(self.temp_dir, "keys")
        manager = RSAKeyManager(key_dir=key_dir)
        manager.ensure_keys()

        active_kid = manager.active_kid
        key = manager.get_key_by_kid(active_kid)
        assert key is not None
        assert key.kid == active_kid
        assert key.is_active is True

        # 不存在的 kid 返回 None
        assert manager.get_key_by_kid("nonexistent") is None

    def test_get_jwt_handler(self):
        """从密钥管理器创建 JWTHandler"""
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available
        from shared.core.auth import is_jwt_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")
        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        key_dir = os.path.join(self.temp_dir, "keys")
        manager = RSAKeyManager(key_dir=key_dir)
        manager.ensure_keys()

        handler = manager.get_jwt_handler()
        assert handler is not None

        token = handler.create_access_token({"sub": "testuser"})
        payload = handler.decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"

    def test_get_all_keys_info(self):
        """获取所有密钥信息（不含密钥内容）"""
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        key_dir = os.path.join(self.temp_dir, "keys")
        manager = RSAKeyManager(key_dir=key_dir)
        manager.ensure_keys()
        manager.rotate_keys()

        keys_info = manager.get_all_keys_info()
        assert len(keys_info) == 2

        for info in keys_info:
            assert "kid" in info
            assert "is_active" in info
            assert "created_at" in info
            assert "expires_at" in info
            # 不包含密钥内容
            assert "private_key" not in info
            assert "public_key" not in info

    def test_invalid_key_size(self):
        """无效的密钥大小抛出异常"""
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        with pytest.raises(ValueError):
            RSAKeyManager(key_dir=self.temp_dir, key_size=1024)


# ===========================================================================
# 从文件加载密钥测试
# ===========================================================================

class TestLoadKeysFromFile:
    """从文件加载 RSA 密钥测试"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_jwt_config_load_keys_from_path(self):
        """JWTConfig 从文件路径加载密钥"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        # 生成并保存密钥
        priv_pem, pub_pem = RSAKeyManager.generate_keypair(2048)
        priv_path = os.path.join(self.temp_dir, "private.pem")
        pub_path = os.path.join(self.temp_dir, "public.pem")

        with open(priv_path, "w") as f:
            f.write(priv_pem)
        with open(pub_path, "w") as f:
            f.write(pub_pem)

        # 通过路径加载
        config = JWTConfig(
            algorithm="RS256",
            private_key_path=priv_path,
            public_key_path=pub_path,
            require_secure_secret=False,
        )

        assert config.private_key == priv_pem
        assert config.public_key == pub_pem

        handler = JWTHandler(config)
        token = handler.create_access_token({"sub": "user1"})
        payload = handler.decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user1"

    def test_jwt_config_nonexistent_path(self):
        """密钥文件不存在时不加载"""
        from shared.core.auth import JWTConfig

        config = JWTConfig(
            algorithm="RS256",
            private_key_path="/nonexistent/private.pem",
            public_key_path="/nonexistent/public.pem",
            require_secure_secret=False,
        )

        assert config.private_key is None
        assert config.public_key is None


# ===========================================================================
# HS256 到 RS256 兼容迁移测试
# ===========================================================================

class TestHS256ToRS256Migration:
    """HS256 到 RS256 兼容迁移测试"""

    def test_hs256_still_works(self):
        """HS256 算法仍然可用（向后兼容）"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        config = JWTConfig(
            secret="test-secret-key-at-least-32-chars-long-for-hs256",
            algorithm="HS256",
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        token = handler.create_access_token({"sub": "user1"})
        payload = handler.decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user1"

    def test_default_algorithm_is_rs256(self):
        """默认算法已更改为 RS256"""
        from shared.core.auth import JWTConfig

        config = JWTConfig(require_secure_secret=False)
        assert config.algorithm == "RS256"

    def test_rs256_fallback_to_hs256_when_secret_only(self):
        """只配置了 JWT_SECRET 时，HS256 仍然可以工作"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        # 模拟旧配置：只有 secret，算法用 HS256
        config = JWTConfig(
            secret="old-secret-key-for-backward-compatibility-32ch",
            algorithm="HS256",
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        token = handler.create_access_token({"sub": "legacy_user"})
        payload = handler.decode_token(token)
        assert payload is not None
        assert payload["sub"] == "legacy_user"

    def test_create_jwt_handler_from_key_manager(self):
        """从密钥管理器创建 JWT Handler（便捷函数）"""
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available
        from shared.core.auth import create_jwt_handler_from_key_manager, is_jwt_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")
        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        key_dir = os.path.join(self.temp_dir if hasattr(self, 'temp_dir') else tempfile.mkdtemp(), "keys")
        manager = RSAKeyManager(key_dir=key_dir)
        manager.ensure_keys()

        handler = create_jwt_handler_from_key_manager(manager)
        assert handler is not None
        assert handler.config.algorithm == "RS256"
        assert handler.config.kid == manager.active_kid

        token = handler.create_access_token({"sub": "test"})
        payload = handler.decode_token(token)
        assert payload is not None


# ===========================================================================
# 错误处理测试
# ===========================================================================

class TestErrorHandling:
    """错误处理测试"""

    def test_invalid_private_key_format(self):
        """无效的私钥格式"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        config = JWTConfig(
            algorithm="RS256",
            private_key="not-a-valid-pem-key",
            public_key="not-a-valid-pem-key",
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        # 签名时应该失败
        with pytest.raises(Exception):
            handler.create_access_token({"sub": "user1"})

    def test_corrupted_token(self):
        """损坏的 Token"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        private_pem, public_pem = RSAKeyManager.generate_keypair(2048)
        config = JWTConfig(
            algorithm="RS256",
            private_key=private_pem,
            public_key=public_pem,
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        token = handler.create_access_token({"sub": "user1"})
        # 篡改 Token
        corrupted = token[:-5] + "XXXXX"
        assert handler.decode_token(corrupted) is None

    def test_empty_token(self):
        """空 Token"""
        from shared.core.auth import JWTHandler, JWTConfig, is_jwt_available
        from shared.core.auth.key_manager import RSAKeyManager, is_crypto_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")
        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        private_pem, public_pem = RSAKeyManager.generate_keypair(2048)
        config = JWTConfig(
            algorithm="RS256",
            private_key=private_pem,
            public_key=public_pem,
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        assert handler.decode_token("") is None
        assert handler.decode_token(None) is None

    def test_get_kid_invalid_token(self):
        """从无效 Token 提取 kid 返回 None"""
        from shared.core.auth import JWTHandler, is_jwt_available

        if not is_jwt_available():
            pytest.skip("python-jose 不可用，跳过测试")

        assert JWTHandler.get_kid("not.a.jwt") is None
        assert JWTHandler.get_kid("") is None

    def test_config_validate_rs256_no_keys(self):
        """RS256 配置验证：没有密钥时抛出异常"""
        from shared.core.auth import JWTConfig

        config = JWTConfig(
            algorithm="RS256",
            require_secure_secret=True,
        )

        with pytest.raises(ValueError, match="RS256"):
            config.validate()

    def test_config_validate_hs256_weak_secret(self):
        """HS256 配置验证：弱密钥时抛出异常"""
        from shared.core.auth import JWTConfig

        config = JWTConfig(
            secret="short",
            algorithm="HS256",
            require_secure_secret=True,
        )

        with pytest.raises(ValueError, match="长度仅"):
            config.validate()


# ===========================================================================
# 便捷函数测试
# ===========================================================================

class TestConvenienceFunctions:
    """便捷函数测试"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generate_rsa_keys_function(self):
        """generate_rsa_keys 便捷函数"""
        from shared.core.auth.key_manager import generate_rsa_keys, is_crypto_available

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        key_dir = os.path.join(self.temp_dir, "keys")
        priv_path, pub_path = generate_rsa_keys(
            key_size=2048,
            output_dir=key_dir,
        )

        assert os.path.exists(priv_path)
        assert os.path.exists(pub_path)

        with open(priv_path, "r") as f:
            assert "BEGIN PRIVATE KEY" in f.read()
        with open(pub_path, "r") as f:
            assert "BEGIN PUBLIC KEY" in f.read()

    def test_rotate_jwt_keys_function(self):
        """rotate_jwt_keys 便捷函数"""
        from shared.core.auth.key_manager import (
            rotate_jwt_keys, RSAKeyManager, is_crypto_available
        )

        if not is_crypto_available():
            pytest.skip("cryptography 不可用，跳过测试")

        key_dir = os.path.join(self.temp_dir, "keys")
        # 先生成初始密钥
        manager = RSAKeyManager(key_dir=key_dir)
        manager.ensure_keys()
        old_kid = manager.active_kid

        # 执行轮换
        new_kid = rotate_jwt_keys(key_dir=key_dir)
        assert new_kid is not None
        assert new_kid != old_kid
