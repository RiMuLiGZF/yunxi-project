"""
JWT 模块边界条件与异常路径测试

对应问题：TST-006（边界条件与异常路径测试不足）
测试模块：shared.core.auth.jwt

覆盖场景：
- 空 Token / None Token
- 过期 Token
- 篡改签名的 Token
- 算法不匹配
- 超长 Token
- 非法格式 Token
- 空 payload
- 超大 payload
- Token 类型不匹配
- 黑名单边界
- issuer/audience 不匹配
- 密钥轮换边界
"""

import sys
import time
import base64
import json
from pathlib import Path
from datetime import timedelta, datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

# 确保可以导入 shared 模块
SHARED_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SHARED_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


# 检查 python-jose 是否可用
try:
    from jose import JWTError, jwt as _jose_jwt
    _jose_available = True
except ImportError:
    _jose_available = False

pytestmark = pytest.mark.skipif(
    not _jose_available,
    reason="python-jose 不可用，跳过 JWT 测试"
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def hs256_handler():
    """创建一个 HS256 算法的 JWTHandler（用于测试）"""
    from shared.core.auth.jwt import JWTHandler, JWTConfig

    config = JWTConfig(
        secret="test-secret-key-32-characters-minimum!!",
        algorithm="HS256",
        access_token_expire_minutes=30,
        refresh_token_expire_days=7,
        issuer="test-issuer",
        require_secure_secret=False,  # 测试用，跳过安全检查
    )
    return JWTHandler(config)


@pytest.fixture
def hs256_handler_no_issuer():
    """创建一个不设置 issuer 的 JWTHandler"""
    from shared.core.auth.jwt import JWTHandler, JWTConfig

    config = JWTConfig(
        secret="test-secret-key-32-characters-minimum!!",
        algorithm="HS256",
        access_token_expire_minutes=30,
        require_secure_secret=False,
    )
    return JWTHandler(config)


@pytest.fixture
def rsa_keys():
    """生成 RSA 密钥对用于 RS256 测试"""
    from shared.core.auth.jwt import JWTHandler, JWTConfig
    from jose.backends import RSAKey

    try:
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode("utf-8")

        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("utf-8")

        return {"private_key": private_pem, "public_key": public_pem}
    except ImportError:
        pytest.skip("cryptography 库不可用，跳过 RSA 测试")


# ===========================================================================
# 1. 空 Token / None Token 测试
# ===========================================================================

class TestEmptyToken:
    """空 Token 边界测试"""

    @pytest.mark.parametrize("empty_token", [
        "",           # 空字符串
        None,         # None
        "   ",        # 空白字符串
        "\t\n",       # 制表符换行
    ])
    def test_decode_empty_token_returns_none(self, hs256_handler, empty_token):
        """空 Token 解码应返回 None"""
        result = hs256_handler.decode_token(empty_token)
        assert result is None

    @pytest.mark.parametrize("empty_token", [
        "",
        None,
        "   ",
    ])
    def test_is_access_token_valid_empty(self, hs256_handler, empty_token):
        """空 Token 的有效性检查应返回 False"""
        result = hs256_handler.is_access_token_valid(empty_token)
        assert result is False

    @pytest.mark.parametrize("empty_token", [
        "",
        None,
        "   ",
    ])
    def test_is_refresh_token_valid_empty(self, hs256_handler, empty_token):
        """空 Token 的刷新令牌检查应返回 False"""
        result = hs256_handler.is_refresh_token_valid(empty_token)
        assert result is False

    def test_get_jti_empty_token(self, hs256_handler):
        """空 Token 提取 JTI 应返回 None"""
        result = hs256_handler.get_jti("")
        assert result is None

    def test_get_kid_empty_token(self, hs256_handler):
        """空 Token 提取 kid 应返回 None"""
        result = hs256_handler.get_kid("")
        assert result is None

    def test_hash_token_empty(self, hs256_handler):
        """空 Token 哈希应正常返回（空字符串的哈希）"""
        result = hs256_handler.hash_token("")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA256 hex 长度

    def test_refresh_access_token_empty(self, hs256_handler):
        """使用空 Token 刷新应返回 None"""
        result = hs256_handler.refresh_access_token("")
        assert result is None


# ===========================================================================
# 2. 过期 Token 测试
# ===========================================================================

class TestExpiredToken:
    """过期 Token 边界测试"""

    def test_expired_access_token_decode_fails(self, hs256_handler):
        """已过期的 Token 解码应返回 None"""
        # 创建一个已过期的 Token（过期时间在过去）
        from shared.core.auth.jwt import JWTHandler, JWTConfig

        # 使用非常短的过期时间
        config = JWTConfig(
            secret="test-secret-key-32-characters-minimum!!",
            algorithm="HS256",
            access_token_expire_minutes=0,  # 0 分钟
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        # 创建一个 Token，让它立即过期
        token = handler.create_access_token(
            {"sub": "test-user"},
            expires_delta=timedelta(seconds=-1)  # 已过期 1 秒
        )
        result = handler.decode_token(token)
        assert result is None

    def test_negative_expiry_token_fails(self, hs256_handler):
        """负过期时间的 Token 应验证失败"""
        token = hs256_handler.create_access_token(
            {"sub": "test-user"},
            expires_delta=timedelta(seconds=-10)  # 已过期 10 秒
        )
        result = hs256_handler.decode_token(token)
        assert result is None

    def test_expired_refresh_token_fails(self, hs256_handler):
        """过期的 Refresh Token 刷新应失败"""
        token = hs256_handler.create_refresh_token(
            {"sub": "test-user"},
            expires_delta=timedelta(seconds=-1)
        )
        result = hs256_handler.refresh_access_token(token)
        assert result is None

    def test_far_future_token_valid(self, hs256_handler):
        """远未来过期的 Token 应有效"""
        token = hs256_handler.create_access_token(
            {"sub": "test-user"},
            expires_delta=timedelta(days=365)  # 一年后过期
        )
        result = hs256_handler.decode_token(token)
        assert result is not None
        assert result["sub"] == "test-user"

    def test_zero_second_expiry_token(self, hs256_handler):
        """0 秒过期的 Token 应立即失效"""
        token = hs256_handler.create_access_token(
            {"sub": "test-user"},
            expires_delta=timedelta(seconds=0)
        )
        # 0 秒过期，可能刚好有效也可能已过期，取决于执行时间
        # 但至少不应该抛出异常
        try:
            result = hs256_handler.decode_token(token)
            # 结果可以是 None 或有效 payload，但不能抛异常
            assert result is None or isinstance(result, dict)
        except Exception as e:
            pytest.fail(f"0 秒过期 Token 解码不应抛出异常: {e}")


# ===========================================================================
# 3. 篡改签名的 Token 测试
# ===========================================================================

class TestTamperedToken:
    """篡改签名 Token 测试"""

    def test_modified_payload_fails(self, hs256_handler):
        """修改 payload 后的 Token 应验证失败"""
        # 创建有效 Token
        original_token = hs256_handler.create_access_token(
            {"sub": "user", "role": "user"}
        )

        # 拆分 Token
        parts = original_token.split(".")
        assert len(parts) == 3

        # 修改 payload（将 role 改为 admin）
        payload_bytes = base64.urlsafe_b64decode(parts[1] + "==")
        payload = json.loads(payload_bytes)
        payload["role"] = "admin"
        new_payload = base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).rstrip(b"=").decode()

        # 重新组装 Token（签名不变）
        tampered_token = f"{parts[0]}.{new_payload}.{parts[2]}"

        # 验证应失败
        result = hs256_handler.decode_token(tampered_token)
        assert result is None

    def test_modified_header_fails(self, hs256_handler):
        """修改 header 后的 Token 应验证失败"""
        original_token = hs256_handler.create_access_token({"sub": "user"})

        parts = original_token.split(".")

        # 修改 header 中的算法
        header_bytes = base64.urlsafe_b64decode(parts[0] + "==")
        header = json.loads(header_bytes)
        header["alg"] = "none"
        new_header = base64.urlsafe_b64encode(
            json.dumps(header).encode()
        ).rstrip(b"=").decode()

        tampered_token = f"{new_header}.{parts[1]}.{parts[2]}"
        result = hs256_handler.decode_token(tampered_token)
        assert result is None

    def test_completely_fake_token(self, hs256_handler):
        """完全伪造的 Token 应验证失败"""
        fake_header = base64.urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        fake_payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "admin", "role": "admin"}).encode()
        ).rstrip(b"=").decode()
        fake_signature = base64.urlsafe_b64encode(b"fake_signature").rstrip(b"=").decode()

        fake_token = f"{fake_header}.{fake_payload}.{fake_signature}"
        result = hs256_handler.decode_token(fake_token)
        assert result is None

    def test_signature_truncated(self, hs256_handler):
        """签名被截断的 Token 应验证失败"""
        original_token = hs256_handler.create_access_token({"sub": "user"})
        parts = original_token.split(".")

        # 截断签名
        truncated_sig = parts[2][:10]
        truncated_token = f"{parts[0]}.{parts[1]}.{truncated_sig}"

        result = hs256_handler.decode_token(truncated_token)
        assert result is None

    def test_empty_signature(self, hs256_handler):
        """空签名的 Token 应验证失败"""
        original_token = hs256_handler.create_access_token({"sub": "user"})
        parts = original_token.split(".")

        no_sig_token = f"{parts[0]}.{parts[1]}."
        result = hs256_handler.decode_token(no_sig_token)
        assert result is None


# ===========================================================================
# 4. 算法不匹配测试
# ===========================================================================

class TestAlgorithmMismatch:
    """算法不匹配测试"""

    def test_hs256_signed_token_verified_with_rs256_fails(self, hs256_handler, rsa_keys):
        """HS256 签名的 Token 用 RS256 验证应失败"""
        from shared.core.auth.jwt import JWTHandler, JWTConfig

        # 用 HS256 签名
        hs256_token = hs256_handler.create_access_token({"sub": "user"})

        # 用 RS256 handler 验证
        rs256_config = JWTConfig(
            algorithm="RS256",
            private_key=rsa_keys["private_key"],
            public_key=rsa_keys["public_key"],
            require_secure_secret=False,
        )
        rs256_handler = JWTHandler(rs256_config)

        result = rs256_handler.decode_token(hs256_token)
        assert result is None

    def test_rs256_signed_token_verified_with_hs256_fails(self, hs256_handler, rsa_keys):
        """RS256 签名的 Token 用 HS256 验证应失败"""
        from shared.core.auth.jwt import JWTHandler, JWTConfig

        rs256_config = JWTConfig(
            algorithm="RS256",
            private_key=rsa_keys["private_key"],
            public_key=rsa_keys["public_key"],
            require_secure_secret=False,
        )
        rs256_handler = JWTHandler(rs256_config)
        rs256_token = rs256_handler.create_access_token({"sub": "user"})

        result = hs256_handler.decode_token(rs256_token)
        assert result is None

    def test_alg_none_attack_rejected(self, hs256_handler):
        """alg=none 攻击应被拒绝"""
        # 手动构造 alg=none 的 Token
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "admin", "exp": int(time.time()) + 3600}).encode()
        ).rstrip(b"=").decode()

        # alg=none 不需要签名
        none_token = f"{header}.{payload}."

        result = hs256_handler.decode_token(none_token)
        assert result is None


# ===========================================================================
# 5. 非法格式 Token 测试
# ===========================================================================

class TestInvalidFormatToken:
    """非法格式 Token 测试"""

    @pytest.mark.parametrize("bad_token", [
        "not-a-jwt",                    # 不是 JWT 格式
        "only.one.part",                # 只有两部分
        "too.many.parts.here",          # 四部分
        "...",                          # 只有分隔符
        "a.b.",                         # 空签名
        ".b.c",                         # 空 header
        "a..c",                         # 空 payload
        "你好世界",                       # 中文字符
        "token with spaces",            # 含空格
        "token\ttab",                   # 含制表符
        "token\nnewline",               # 含换行
    ])
    def test_invalid_format_tokens(self, hs256_handler, bad_token):
        """各种非法格式 Token 应返回 None 且不抛异常"""
        try:
            result = hs256_handler.decode_token(bad_token)
            assert result is None
        except Exception as e:
            pytest.fail(f"非法格式 Token '{bad_token}' 不应抛出异常: {e}")

    @pytest.mark.parametrize("bad_token", [
        "not-a-jwt",
        "only.two",
        "...",
    ])
    def test_get_jti_invalid_format(self, hs256_handler, bad_token):
        """非法格式 Token 提取 JTI 应返回 None"""
        result = hs256_handler.get_jti(bad_token)
        assert result is None

    @pytest.mark.parametrize("bad_token", [
        "not-a-jwt",
        "only.two",
    ])
    def test_get_kid_invalid_format(self, hs256_handler, bad_token):
        """非法格式 Token 提取 kid 应返回 None"""
        result = hs256_handler.get_kid(bad_token)
        assert result is None


# ===========================================================================
# 6. 超长 Token 测试
# ===========================================================================

class TestOversizedToken:
    """超大 Token 边界测试"""

    def test_very_large_payload(self, hs256_handler):
        """超大 payload 的 Token 应能正确处理"""
        # 构造一个很大的 payload
        large_data = "x" * 10000  # 10KB 的数据
        token = hs256_handler.create_access_token(
            {"sub": "user", "large_data": large_data}
        )

        # 应能正确解码
        result = hs256_handler.decode_token(token)
        assert result is not None
        assert result["sub"] == "user"
        assert len(result["large_data"]) == 10000

    def test_extremely_long_token_string(self, hs256_handler):
        """极长的 Token 字符串（非 JWT 格式）应安全处理"""
        very_long = "a" * 100000  # 100K 字符
        try:
            result = hs256_handler.decode_token(very_long)
            assert result is None
        except Exception as e:
            pytest.fail(f"超长 Token 不应抛出异常: {e}")

    def test_hash_very_long_token(self, hs256_handler):
        """超长 Token 的哈希应正常计算"""
        very_long = "a" * 100000
        result = hs256_handler.hash_token(very_long)
        assert isinstance(result, str)
        assert len(result) == 64


# ===========================================================================
# 7. Token 类型不匹配测试
# ===========================================================================

class TestTokenTypeMismatch:
    """Token 类型不匹配测试"""

    def test_access_token_used_as_refresh_fails(self, hs256_handler):
        """Access Token 不能当 Refresh Token 用"""
        access_token = hs256_handler.create_access_token({"sub": "user"})
        result = hs256_handler.decode_token(access_token, token_type="refresh")
        assert result is None

    def test_refresh_token_used_as_access_fails(self, hs256_handler):
        """Refresh Token 不能当 Access Token 用"""
        refresh_token = hs256_handler.create_refresh_token({"sub": "user"})
        result = hs256_handler.decode_token(refresh_token, token_type="access")
        assert result is None

    def test_is_access_token_valid_with_refresh(self, hs256_handler):
        """is_access_token_valid 对 Refresh Token 应返回 False"""
        refresh_token = hs256_handler.create_refresh_token({"sub": "user"})
        result = hs256_handler.is_access_token_valid(refresh_token)
        assert result is False

    def test_is_refresh_token_valid_with_access(self, hs256_handler):
        """is_refresh_token_valid 对 Access Token 应返回 False"""
        access_token = hs256_handler.create_access_token({"sub": "user"})
        result = hs256_handler.is_refresh_token_valid(access_token)
        assert result is False

    def test_no_type_check_accepts_both(self, hs256_handler):
        """不指定 token_type 时两种 Token 都能通过"""
        access_token = hs256_handler.create_access_token({"sub": "user"})
        refresh_token = hs256_handler.create_refresh_token({"sub": "user"})

        result1 = hs256_handler.decode_token(access_token)  # 不指定类型
        result2 = hs256_handler.decode_token(refresh_token)  # 不指定类型

        assert result1 is not None
        assert result2 is not None


# ===========================================================================
# 8. Issuer / Audience 不匹配测试
# ===========================================================================

class TestIssuerAudienceMismatch:
    """Issuer 和 Audience 不匹配测试"""

    def test_issuer_mismatch_fails(self, hs256_handler):
        """issuer 不匹配应验证失败"""
        # hs256_handler 的 issuer 是 "test-issuer"
        token = hs256_handler.create_access_token({"sub": "user"})

        # 创建一个期望不同 issuer 的 handler
        from shared.core.auth.jwt import JWTHandler, JWTConfig
        config = JWTConfig(
            secret="test-secret-key-32-characters-minimum!!",
            algorithm="HS256",
            issuer="different-issuer",
            require_secure_secret=False,
        )
        other_handler = JWTHandler(config)

        result = other_handler.decode_token(token)
        assert result is None

    def test_token_without_issuer_field(self, hs256_handler_no_issuer):
        """不设置 issuer 的 handler 签发的 Token 应正常工作"""
        token = hs256_handler_no_issuer.create_access_token({"sub": "user"})
        result = hs256_handler_no_issuer.decode_token(token)
        assert result is not None
        assert "iss" not in result

    def test_audience_mismatch_fails(self):
        """audience 不匹配应验证失败"""
        from shared.core.auth.jwt import JWTHandler, JWTConfig
        from jose import jwt as _jose_jwt
        from datetime import datetime, timedelta, timezone

        # 手动构造带 aud claim 的 token
        secret = "test-secret-key-32-characters-minimum!!"
        payload = {
            "sub": "user",
            "aud": "app1",
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=30),
            "iat": datetime.now(tz=timezone.utc),
            "type": "access",
        }
        token = _jose_jwt.encode(payload, secret, algorithm="HS256")

        # 用不同 audience 的 handler 验证
        config = JWTConfig(
            secret=secret,
            algorithm="HS256",
            audience="app2",  # 不同的 audience
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        result = handler.decode_token(token)
        assert result is None

    def test_audience_match_passes(self):
        """audience 匹配应验证通过"""
        from shared.core.auth.jwt import JWTHandler, JWTConfig
        from jose import jwt as _jose_jwt
        from datetime import datetime, timedelta, timezone

        secret = "test-secret-key-32-characters-minimum!!"
        payload = {
            "sub": "user",
            "aud": "myapp",
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=30),
            "iat": datetime.now(tz=timezone.utc),
            "type": "access",
        }
        token = _jose_jwt.encode(payload, secret, algorithm="HS256")

        config = JWTConfig(
            secret=secret,
            algorithm="HS256",
            audience="myapp",
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        result = handler.decode_token(token)
        assert result is not None
        assert result["sub"] == "user"


# ===========================================================================
# 9. 空 payload / 最小 payload 测试
# ===========================================================================

class TestEmptyPayload:
    """空 payload / 最小 payload 测试"""

    def test_minimal_payload(self, hs256_handler):
        """只有 sub 的最小 payload 应正常工作"""
        token = hs256_handler.create_access_token({"sub": "user"})
        result = hs256_handler.decode_token(token)
        assert result is not None
        assert result["sub"] == "user"
        assert "exp" in result
        assert "iat" in result
        assert "jti" in result

    def test_empty_dict_payload(self, hs256_handler):
        """空字典 payload 应正常创建和验证"""
        token = hs256_handler.create_access_token({})
        result = hs256_handler.decode_token(token)
        assert result is not None
        assert "exp" in result
        assert "iat" in result
        assert "jti" in result

    def test_payload_with_null_values(self, hs256_handler):
        """含 None 值的 payload 应正常处理"""
        token = hs256_handler.create_access_token(
            {"sub": "user", "optional": None, "empty_list": []}
        )
        result = hs256_handler.decode_token(token)
        assert result is not None
        assert result["sub"] == "user"
        assert result["optional"] is None
        assert result["empty_list"] == []

    def test_payload_with_special_characters(self, hs256_handler):
        """含特殊字符的 payload 应正常处理"""
        special_str = '!@#$%^&*()_+-=[]{}|;:\'",.<>?/`~'
        token = hs256_handler.create_access_token(
            {"sub": "user", "special": special_str, "unicode": "中文测试"}
        )
        result = hs256_handler.decode_token(token)
        assert result is not None
        assert result["special"] == special_str
        assert result["unicode"] == "中文测试"


# ===========================================================================
# 10. JWTConfig 安全验证边界测试
# ===========================================================================

class TestJWTConfigValidation:
    """JWTConfig 配置验证边界测试"""

    def test_empty_secret_raises_with_secure_check(self):
        """空 secret + require_secure_secret=True 应抛出 ValueError"""
        from shared.core.auth.jwt import JWTConfig

        config = JWTConfig(
            secret="",
            algorithm="HS256",
            require_secure_secret=True,
        )
        with pytest.raises(ValueError, match="secret 不能为空"):
            config.validate()

    def test_short_secret_raises_with_secure_check(self):
        """短 secret + require_secure_secret=True 应抛出 ValueError"""
        from shared.core.auth.jwt import JWTConfig

        config = JWTConfig(
            secret="short",  # 小于 32 字符
            algorithm="HS256",
            require_secure_secret=True,
        )
        with pytest.raises(ValueError, match="长度仅"):
            config.validate()

    def test_exactly_32_char_secret_passes(self):
        """恰好 32 字符的 secret 应通过验证"""
        from shared.core.auth.jwt import JWTConfig

        secret_32 = "a" * 32
        config = JWTConfig(
            secret=secret_32,
            algorithm="HS256",
            require_secure_secret=True,
        )
        # 不应抛出异常
        config.validate()

    def test_rs256_without_keys_raises(self):
        """RS256 算法但不提供密钥应抛出 ValueError"""
        from shared.core.auth.jwt import JWTConfig

        config = JWTConfig(
            algorithm="RS256",
            private_key=None,
            public_key=None,
            require_secure_secret=True,
        )
        with pytest.raises(ValueError, match="必须配置 private_key 和 public_key"):
            config.validate()

    def test_skip_security_check_allows_empty(self):
        """require_secure_secret=False 时允许空 secret"""
        from shared.core.auth.jwt import JWTConfig

        config = JWTConfig(
            secret="",
            algorithm="HS256",
            require_secure_secret=False,
        )
        # 不应抛出异常
        config.validate()

    def test_is_default_secret_empty_hs256(self):
        """空 HS256 secret 应被识别为默认密钥"""
        from shared.core.auth.jwt import JWTConfig

        config = JWTConfig(
            secret="",
            algorithm="HS256",
            require_secure_secret=False,
        )
        assert config.is_default_secret is True

    def test_is_default_secret_short_hs256(self):
        """短 HS256 secret 应被识别为默认密钥"""
        from shared.core.auth.jwt import JWTConfig

        config = JWTConfig(
            secret="short",
            algorithm="HS256",
            require_secure_secret=False,
        )
        assert config.is_default_secret is True

    def test_is_default_secret_strong_hs256(self):
        """强 HS256 secret 不应被识别为默认密钥"""
        from shared.core.auth.jwt import JWTConfig

        config = JWTConfig(
            secret="a" * 32,
            algorithm="HS256",
            require_secure_secret=False,
        )
        assert config.is_default_secret is False


# ===========================================================================
# 11. 黑名单边界测试
# ===========================================================================

class TestTokenBlacklist:
    """Token 黑名单边界测试"""

    def test_blacklist_empty_jti_not_blacklisted(self):
        """空 JTI 不应在黑名单中"""
        from shared.core.auth.jwt import InMemoryTokenBlacklist

        bl = InMemoryTokenBlacklist()
        assert bl.is_blacklisted("") is False

    def test_blacklist_none_jti_not_blacklisted(self):
        """None JTI 不应在黑名单中"""
        from shared.core.auth.jwt import InMemoryTokenBlacklist

        bl = InMemoryTokenBlacklist()
        assert bl.is_blacklisted(None) is False

    def test_blacklist_expired_token_cleaned(self):
        """已过期的黑名单 Token 应被清理"""
        from shared.core.auth.jwt import InMemoryTokenBlacklist
        from datetime import datetime, timezone, timedelta

        bl = InMemoryTokenBlacklist()

        # 添加一个已过期的 Token
        past_time = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        bl.add("expired-jti", "hash123", past_time)

        # 检查时应自动清理并返回 False
        assert bl.is_blacklisted("expired-jti") is False

    def test_blacklist_future_token_remains(self):
        """未过期的黑名单 Token 应保持在黑名单中"""
        from shared.core.auth.jwt import InMemoryTokenBlacklist
        from datetime import datetime, timezone, timedelta

        bl = InMemoryTokenBlacklist()

        future_time = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        bl.add("valid-jti", "hash456", future_time)

        assert bl.is_blacklisted("valid-jti") is True

    def test_clean_expired_removes_only_expired(self):
        """clean_expired 应只移除已过期的条目"""
        from shared.core.auth.jwt import InMemoryTokenBlacklist
        from datetime import datetime, timezone, timedelta

        bl = InMemoryTokenBlacklist()

        now = datetime.now(tz=timezone.utc)
        # 添加 3 个过期的
        for i in range(3):
            bl.add(f"expired-{i}", f"hash-{i}", now - timedelta(hours=i + 1))
        # 添加 2 个未过期的
        for i in range(2):
            bl.add(f"valid-{i}", f"hash-v{i}", now + timedelta(hours=i + 1))

        removed = bl.clean_expired()
        assert removed == 3

        # 验证未过期的还在
        assert bl.is_blacklisted("valid-0") is True
        assert bl.is_blacklisted("valid-1") is True

    def test_add_empty_jti_noop(self):
        """添加空 JTI 应为空操作"""
        from shared.core.auth.jwt import InMemoryTokenBlacklist
        from datetime import datetime, timezone, timedelta

        bl = InMemoryTokenBlacklist()
        future = datetime.now(tz=timezone.utc) + timedelta(hours=1)

        bl.add("", "hash", future)
        # 不应有任何条目
        assert bl.is_blacklisted("") is False
        assert bl.clean_expired() == 0


# ===========================================================================
# 12. 密钥轮换边界测试
# ===========================================================================

class TestKeyRotation:
    """密钥轮换边界测试"""

    def test_token_signed_with_old_key_can_verify(self, rsa_keys):
        """使用旧密钥签发的 Token 应能通过 verification_keys 验证"""
        from shared.core.auth.jwt import JWTHandler, JWTConfig
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend

        # 生成旧密钥对
        old_private = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        old_private_pem = old_private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode("utf-8")
        old_public_pem = old_private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("utf-8")

        # 用旧密钥签发 Token
        old_config = JWTConfig(
            algorithm="RS256",
            private_key=old_private_pem,
            public_key=old_public_pem,
            kid="old-key",
            require_secure_secret=False,
        )
        old_handler = JWTHandler(old_config)
        old_token = old_handler.create_access_token({"sub": "user"})

        # 用新密钥的 handler，但添加旧密钥到 verification_keys
        new_config = JWTConfig(
            algorithm="RS256",
            private_key=rsa_keys["private_key"],
            public_key=rsa_keys["public_key"],
            kid="new-key",
            verification_keys={"old-key": old_public_pem},
            require_secure_secret=False,
        )
        new_handler = JWTHandler(new_config)

        # 旧 Token 应能通过新 handler 验证
        result = new_handler.decode_token(old_token)
        assert result is not None
        assert result["sub"] == "user"

    def test_unknown_kid_falls_back_to_default_key(self, rsa_keys):
        """未知 kid 的 Token 应回退到默认密钥验证"""
        from shared.core.auth.jwt import JWTHandler, JWTConfig

        # 用默认密钥签发（不带 kid）
        config = JWTConfig(
            algorithm="RS256",
            private_key=rsa_keys["private_key"],
            public_key=rsa_keys["public_key"],
            verification_keys={"other-key": "not-valid-pem"},
            require_secure_secret=False,
        )
        handler = JWTHandler(config)

        # 不带 kid 的 Token
        token = handler.create_access_token({"sub": "user"})

        # 应能通过默认密钥验证
        result = handler.decode_token(token)
        assert result is not None

    def test_add_remove_verification_key(self, hs256_handler):
        """添加和移除验证密钥应正常工作"""
        # HS256 也可以测试添加/移除逻辑
        hs256_handler.add_verification_key("key1", "secret-1-32-characters-min!!")
        assert "key1" in hs256_handler.config.verification_keys

        hs256_handler.remove_verification_key("key1")
        assert "key1" not in hs256_handler.config.verification_keys

    def test_remove_nonexistent_key_no_error(self, hs256_handler):
        """移除不存在的密钥不应抛异常"""
        try:
            hs256_handler.remove_verification_key("nonexistent-key")
        except Exception as e:
            pytest.fail(f"移除不存在的密钥不应抛出异常: {e}")
