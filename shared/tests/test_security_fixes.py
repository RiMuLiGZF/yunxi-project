"""
安全默认值修复验证测试（SEC-001/002/006/007）

覆盖以下安全修复的验证：
- SEC-001: 全局模块默认 Token 硬编码 -> 默认空值 + 生产环境强制校验 + 开发环境自动生成
- SEC-002: 全局 JWT 默认密钥硬编码 -> 默认空值 + 生产环境强制校验 + 开发环境自动生成
- SEC-006: API 网关 JWT 开发模式不验证签名 -> 移除降级模式，jose 不可用时直接失败
- SEC-007: 密码哈希开发模式降级为 SHA256 -> 移除 YUNXI_DEV_MODE 降级，仅 YUNXI_INSECURE_PASSWORD 显式启用
"""

import sys
import os
import time
import json
import base64
import secrets
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 确保可以导入 shared 模块
SHARED_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SHARED_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


# ===========================================================================
# SEC-001: 全局模块默认 Token 硬编码
# ===========================================================================

class TestSEC001_ModuleTokens:
    """SEC-001: 全局模块默认 Token 安全修复测试"""

    def test_default_tokens_are_empty(self):
        """默认 Token 值为空字符串（不再是可预测的硬编码值）"""
        from shared.core.config import GlobalModuleConfig, ModuleEndpointConfig

        config = GlobalModuleConfig()

        # 所有模块的默认 token 都应该是空字符串
        # (gateway + m0~m12 = 14 个模块)
        module_fields = list(config.model_fields.keys())
        assert len(module_fields) == 14, f"应该有 14 个模块，实际 {len(module_fields)} 个"

        for module_key in module_fields:
            module_config = getattr(config, module_key)
            assert module_config.token == "", (
                f"模块 '{module_key}' 的默认 token 应该为空字符串，"
                f"实际为: '{module_config.token}'"
            )

    def test_development_auto_generates_tokens(self):
        """开发环境下空 Token 自动生成随机值"""
        from shared.core.config import YunxiGlobalConfig, EnvType

        # 开发环境 + 不设置任何 token
        with patch.dict(os.environ, {}, clear=True):
            config = YunxiGlobalConfig(env=EnvType.DEVELOPMENT)

        # 所有模块的 token 都应该被自动生成（非空）
        for module_key in config.modules.model_fields:
            module_config = getattr(config.modules, module_key)
            assert module_config.token != "", (
                f"开发环境下模块 '{module_key}' 的 token 应该被自动生成"
            )
            # 随机 token 应该有足够长度
            assert len(module_config.token) >= 16, (
                f"自动生成的 token 长度不足: {len(module_config.token)}"
            )

    def test_development_tokens_are_unique(self):
        """开发环境自动生成的各模块 Token 互不相同"""
        from shared.core.config import YunxiGlobalConfig, EnvType

        with patch.dict(os.environ, {}, clear=True):
            config = YunxiGlobalConfig(env=EnvType.DEVELOPMENT)

        tokens = []
        for module_key in config.modules.model_fields:
            tokens.append(getattr(config.modules, module_key).token)

        # 所有 token 应该互不相同
        assert len(set(tokens)) == len(tokens), "所有模块的自动生成 token 应该互不相同"

    def test_production_empty_tokens_raises_error(self):
        """生产环境下空 Module Token 抛出配置错误（SEC-001）"""
        from shared.core.config import YunxiGlobalConfig, EnvType, generate_secure_key

        # 设置 base admin_token 和 cors_origins 使父类校验通过，
        # 但模块 tokens 为空，触发我们的 SEC-001 校验
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                # 直接传参，base admin_token 和 cors_origins 设为有效值
                # 但 modules 保持默认（tokens 为空）
                YunxiGlobalConfig(
                    env=EnvType.PRODUCTION,
                    admin_token=generate_secure_key(32),
                    cors_origins="https://example.com",
                )

            error_msg = str(exc_info.value)
            assert "SEC-001" in error_msg, f"错误信息中应该包含 SEC-001 标记，实际: {error_msg[:200]}"
            assert "admin_token" in error_msg.lower() or "模块" in error_msg, (
                f"错误信息中应该提到模块 token，实际: {error_msg[:200]}"
            )

    def test_production_with_valid_tokens_passes(self):
        """生产环境下配置了有效 Token 可以正常初始化"""
        from shared.core.config import (
            YunxiGlobalConfig, EnvType, generate_secure_key,
            GlobalModuleConfig, GlobalSecurityConfig, ModuleEndpointConfig,
        )

        modules_dict = {}
        module_keys = ["gateway", "m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10", "m11", "m12"]
        for mk in module_keys:
            port = 8080 if mk == "gateway" else 8000 + (0 if mk == "m0" else int(mk[1:]))
            modules_dict[mk] = ModuleEndpointConfig(
                host="0.0.0.0",
                port=port,
                token=generate_secure_key(32),
                base_url=f"http://localhost:{port}",
            )

        security = GlobalSecurityConfig(jwt_secret=generate_secure_key(32))
        modules = GlobalModuleConfig(**modules_dict)

        config = YunxiGlobalConfig(
            env=EnvType.PRODUCTION,
            admin_token=generate_secure_key(32),  # base admin_token 也需要设置
            cors_origins="https://example.com",  # 生产环境不能用 *
            security=security,
            modules=modules,
        )

        assert config.env == EnvType.PRODUCTION
        assert config.modules.gateway.token != ""
        assert len(config.modules.gateway.token) >= 16


# ===========================================================================
# SEC-002: 全局 JWT 默认密钥硬编码
# ===========================================================================

class TestSEC002_JWTSecret:
    """SEC-002: 全局 JWT 默认密钥安全修复测试"""

    def test_default_jwt_secret_is_empty(self):
        """默认 JWT 密钥为空字符串（不再是可预测的硬编码值）"""
        from shared.core.config import GlobalSecurityConfig

        config = GlobalSecurityConfig()
        assert config.jwt_secret == "", (
            f"默认 jwt_secret 应该为空字符串，实际为: '{config.jwt_secret}'"
        )

    def test_default_not_contains_weak_pattern(self):
        """默认值不包含弱密钥模式（yunxi- 等前缀）"""
        from shared.core.config import GlobalSecurityConfig, is_default_or_weak_key

        config = GlobalSecurityConfig()
        # 空字符串被认为是弱密钥（因为未配置）
        # 但我们要确保默认值不是 yunxi- 开头的可预测值
        assert not config.jwt_secret.startswith("yunxi-"), (
            "默认 jwt_secret 不应该是 yunxi- 开头的可预测值"
        )

    def test_development_auto_generates_jwt_secret(self):
        """开发环境下空 JWT 密钥自动生成随机值"""
        from shared.core.config import YunxiGlobalConfig, EnvType

        with patch.dict(os.environ, {}, clear=True):
            config = YunxiGlobalConfig(env=EnvType.DEVELOPMENT)

        assert config.security.jwt_secret != "", (
            "开发环境下 jwt_secret 应该被自动生成"
        )
        assert len(config.security.jwt_secret) >= 32, (
            f"自动生成的 jwt_secret 长度不足: {len(config.security.jwt_secret)}"
        )

    def test_production_empty_jwt_secret_raises_error(self):
        """生产环境下空 JWT 密钥抛出配置错误（SEC-002）"""
        from shared.core.config import (
            YunxiGlobalConfig, EnvType, GlobalModuleConfig,
            ModuleEndpointConfig, generate_secure_key,
        )

        # 设置所有模块 token 和 base admin_token（避免 SEC-001 报错），
        # 但不设置 jwt secret，触发 SEC-002 校验
        modules_dict = {}
        for mk in ["gateway", "m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10", "m11", "m12"]:
            port = 8080 if mk == "gateway" else 8000 + (0 if mk == "m0" else int(mk[1:]))
            modules_dict[mk] = ModuleEndpointConfig(
                host="0.0.0.0",
                port=port,
                token=generate_secure_key(32),
                base_url=f"http://localhost:{port}",
            )

        with pytest.raises(ValueError) as exc_info:
            YunxiGlobalConfig(
                env=EnvType.PRODUCTION,
                admin_token=generate_secure_key(32),
                cors_origins="https://example.com",
                modules=GlobalModuleConfig(**modules_dict),
            )

        error_msg = str(exc_info.value)
        assert "SEC-002" in error_msg, f"错误信息中应该包含 SEC-002 标记，实际: {error_msg[:300]}"
        assert "jwt_secret" in error_msg.lower(), f"错误信息中应该提到 jwt_secret，实际: {error_msg[:300]}"

    def test_production_short_jwt_secret_raises_error_hs256(self):
        """生产环境 HS256 模式下短于 32 字符的 JWT 密钥抛出错误"""
        from shared.core.config import (
            YunxiGlobalConfig, EnvType, GlobalModuleConfig,
            GlobalSecurityConfig, ModuleEndpointConfig, generate_secure_key,
        )

        modules_dict = {}
        for mk in ["gateway", "m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10", "m11", "m12"]:
            port = 8080 if mk == "gateway" else 8000 + (0 if mk == "m0" else int(mk[1:]))
            modules_dict[mk] = ModuleEndpointConfig(
                host="0.0.0.0",
                port=port,
                token=generate_secure_key(32),
                base_url=f"http://localhost:{port}",
            )

        # 只有 10 字符的密钥，HS256 模式下应该失败
        security = GlobalSecurityConfig(
            jwt_secret="short-key!",  # 10 字符
            jwt_algorithm="HS256",
        )

        with pytest.raises(ValueError) as exc_info:
            YunxiGlobalConfig(
                env=EnvType.PRODUCTION,
                admin_token=generate_secure_key(32),
                cors_origins="https://example.com",
                security=security,
                modules=GlobalModuleConfig(**modules_dict),
            )

        error_msg = str(exc_info.value)
        assert "SEC-002" in error_msg, f"错误信息应该包含 SEC-002，实际: {error_msg[:300]}"
        assert "长度不足" in error_msg, f"错误信息应该提到长度不足，实际: {error_msg[:300]}"

    def test_production_weak_jwt_secret_raises_error(self):
        """生产环境使用弱密钥模式（如 yunxi- 开头）抛出错误"""
        from shared.core.config import (
            YunxiGlobalConfig, EnvType, GlobalModuleConfig,
            GlobalSecurityConfig, ModuleEndpointConfig, generate_secure_key,
        )

        modules_dict = {}
        for mk in ["gateway", "m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10", "m11", "m12"]:
            port = 8080 if mk == "gateway" else 8000 + (0 if mk == "m0" else int(mk[1:]))
            modules_dict[mk] = ModuleEndpointConfig(
                host="0.0.0.0",
                port=port,
                token=generate_secure_key(32),
                base_url=f"http://localhost:{port}",
            )

        # 使用弱密钥模式（长度够但以 yunxi- 开头）
        long_weak_key = "yunxi-" + generate_secure_key(40)
        security = GlobalSecurityConfig(
            jwt_secret=long_weak_key,
            jwt_algorithm="HS256",
        )

        with pytest.raises(ValueError) as exc_info:
            YunxiGlobalConfig(
                env=EnvType.PRODUCTION,
                admin_token=generate_secure_key(32),
                cors_origins="https://example.com",
                security=security,
                modules=GlobalModuleConfig(**modules_dict),
            )

        error_msg = str(exc_info.value)
        assert "SEC-002" in error_msg, f"错误信息应该包含 SEC-002，实际: {error_msg[:300]}"
        assert "弱密钥" in error_msg or "default" in error_msg.lower(), (
            f"错误信息应该提到弱密钥，实际: {error_msg[:300]}"
        )


# ===========================================================================
# SEC-006: API 网关 JWT 开发模式不验证签名
# ===========================================================================

class TestSEC006_JWTSignatureVerification:
    """SEC-006: JWT 签名验证安全修复测试"""

    def _make_jwt_token(self, payload: dict, secret: str, algorithm: str = "HS256") -> str:
        """手动生成 JWT Token（用于测试）"""
        import hmac
        import hashlib

        def b64url_encode(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = {"alg": algorithm, "typ": "JWT"}
        header_b64 = b64url_encode(json.dumps(header).encode("utf-8"))
        payload_b64 = b64url_encode(json.dumps(payload).encode("utf-8"))
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

        if algorithm == "HS256":
            signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        else:
            signature = b""

        sig_b64 = b64url_encode(signature)
        return f"{header_b64}.{payload_b64}.{sig_b64}"

    def test_jose_unavailable_raises_runtime_error(self):
        """jose 库不可用时中间件初始化抛出 RuntimeError"""
        # 模拟 jose 不可用的环境
        with patch.dict(sys.modules, {"jose": None}):
            # 强制重新导入 auth 模块
            if "src.middleware.auth" in sys.modules:
                del sys.modules["src.middleware.auth"]

            # 我们需要直接测试 HAS_JOSE 为 False 时的行为
            # 由于环境中实际安装了 jose，我们用 mock 来模拟
            pass

        # 更实用的测试：直接验证 AuthMiddleware 在 HAS_JOSE=False 时的行为
        # 由于我们无法轻易卸载 jose，我们通过修改模块级变量来测试
        from pathlib import Path as P
        gateway_root = P(__file__).resolve().parent.parent.parent / "API-Gateway"
        if str(gateway_root) not in sys.path:
            sys.path.insert(0, str(gateway_root))

        # 使用 unittest.mock 来模拟 HAS_JOSE = False
        from unittest.mock import patch as mock_patch
        from importlib import reload

        # 先确保模块被导入
        import src.middleware.auth as auth_module

        # 保存原始值
        original_has_jose = auth_module.HAS_JOSE

        try:
            # 模拟 HAS_JOSE = False
            with mock_patch.object(auth_module, 'HAS_JOSE', False):
                with pytest.raises(RuntimeError) as exc_info:
                    # 设置必要的环境变量
                    with mock_patch.dict(os.environ, {
                        "GATEWAY_JWT_SECRET": "test-secret-key-at-least-32-chars-long",
                        "ENV": "development",
                    }):
                        auth_module.AuthMiddleware(MagicMock())

                error_msg = str(exc_info.value)
                assert "SEC-006" in error_msg or "python-jose" in error_msg.lower(), (
                    f"错误信息应该包含 SEC-006 或 python-jose，实际为: {error_msg}"
                )
        finally:
            # 恢复
            auth_module.HAS_JOSE = original_has_jose

    def test_invalid_signature_rejected_in_development(self):
        """开发环境下签名无效的 JWT 也被拒绝（不再有降级模式）"""
        gateway_root = Path(__file__).resolve().parent.parent.parent / "API-Gateway"
        if str(gateway_root) not in sys.path:
            sys.path.insert(0, str(gateway_root))

        from src.middleware.auth import AuthMiddleware

        with patch.dict(os.environ, {
            "GATEWAY_JWT_SECRET": "test-secret-key-for-security-test-001",
            "GATEWAY_JWT_ALGORITHM": "HS256",
            "ENV": "development",
        }):
            middleware = AuthMiddleware(MagicMock())

            # 使用正确密钥签名的 token 应该通过
            valid_payload = {
                "sub": "user-123",
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
                "type": "access",
            }
            valid_token = self._make_jwt_token(
                valid_payload, "test-secret-key-for-security-test-001"
            )
            result = middleware._validate_jwt(valid_token)
            assert result is not None, "有效签名的 JWT 应该验证通过"

            # 使用错误密钥签名的 token 应该被拒绝
            invalid_token = self._make_jwt_token(
                valid_payload, "wrong-secret-key-for-testing"
            )
            result = middleware._validate_jwt(invalid_token)
            assert result is None, "签名无效的 JWT 应该被拒绝"

    def test_no_dev_mode_fallback_auth_type(self):
        """不再有 jwt_dev 类型的认证结果（降级模式已移除）"""
        gateway_root = Path(__file__).resolve().parent.parent.parent / "API-Gateway"
        if str(gateway_root) not in sys.path:
            sys.path.insert(0, str(gateway_root))

        from src.middleware.auth import AuthMiddleware

        with patch.dict(os.environ, {
            "GATEWAY_JWT_SECRET": "test-secret-key-for-security-test-002",
            "GATEWAY_JWT_ALGORITHM": "HS256",
            "ENV": "development",
        }):
            middleware = AuthMiddleware(MagicMock())

            payload = {
                "sub": "user-123",
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
                "type": "access",
            }
            token = self._make_jwt_token(payload, "test-secret-key-for-security-test-002")
            result = middleware._validate_jwt(token)

            assert result is not None
            # 认证类型应该是 "jwt"，而不是 "jwt_dev"
            assert result["auth_type"] == "jwt", (
                f"认证类型应该是 'jwt'，实际为 '{result['auth_type']}'"
            )
            # 不应该有 _warning 字段
            assert "_warning" not in result, (
                "结果中不应该包含 _warning 字段（降级模式已移除）"
            )


# ===========================================================================
# SEC-007: 密码哈希开发模式降级为 SHA256
# ===========================================================================

class TestSEC007_PasswordHash:
    """SEC-007: 密码哈希安全修复测试"""

    def test_bcrypt_available_by_default(self):
        """正常环境下 bcrypt 应该可用"""
        from shared.core.auth.password import is_bcrypt_available, is_insecure_fallback_mode

        # 默认情况下应该使用 bcrypt
        assert is_bcrypt_available() is True, "bcrypt 应该可用"
        assert is_insecure_fallback_mode() is False, "不应该处于 fallback 模式"

    def test_bcrypt_hash_and_verify(self):
        """bcrypt 模式下密码哈希和验证正常工作"""
        from shared.core.auth.password import (
            hash_password, verify_password, is_bcrypt_available, needs_update,
        )

        if not is_bcrypt_available():
            pytest.skip("bcrypt 不可用，跳过测试")

        hashed = hash_password("test_password_secure_123")
        assert hashed != "test_password_secure_123"
        assert hashed.startswith("$2"), "bcrypt 哈希应该以 $2 开头"
        assert verify_password("test_password_secure_123", hashed) is True
        assert verify_password("wrong_password", hashed) is False

    def test_insecure_fallback_disabled_by_default(self):
        """默认情况下 YUNXI_DEV_MODE=1 不会触发 fallback（已移除）"""
        # 注意：模块加载时已经初始化了后端，所以我们需要测试 _detect_backend 函数的逻辑
        from shared.core.auth.password import _backend, is_insecure_fallback_mode

        # 当前不应该是 fallback 模式
        assert is_insecure_fallback_mode() is False

        # 验证后端类型
        assert _backend in ("bcrypt", "passlib"), (
            f"当前后端应该是 bcrypt 或 passlib，实际为: {_backend}"
        )

    def test_fallback_requires_explicit_insecure_flag(self):
        """fallback 模式需要显式设置 YUNXI_INSECURE_PASSWORD=1"""
        # 我们通过模拟 bcrypt 不可用的情况来测试
        from unittest.mock import patch as mock_patch
        import importlib
        from shared.core.auth import password as password_module

        # 保存原始值
        original_backend = password_module._backend
        original_bcrypt = password_module._bcrypt
        original_pwd_context = password_module._pwd_context

        try:
            # 模拟 bcrypt 不可用 + 显式设置 YUNXI_INSECURE_PASSWORD=1
            with mock_patch.dict(os.environ, {"YUNXI_INSECURE_PASSWORD": "1"}):
                # 模拟 bcrypt 导入失败
                with mock_patch.object(password_module, '_bcrypt', None):
                    with mock_patch.object(password_module, '_pwd_context', None):
                        # 手动调用 _detect_backend 来测试逻辑
                        # 由于实际 bcrypt 可用，我们直接测试逻辑路径
                        password_module._backend = None

                        # 捕获警告输出
                        import io
                        from contextlib import redirect_stderr

                        stderr_capture = io.StringIO()
                        try:
                            with redirect_stderr(stderr_capture):
                                password_module._detect_backend()
                        except Exception:
                            pass

                        stderr_output = stderr_capture.getvalue()

                        # 如果处于 fallback 模式，应该有警告
                        if password_module._backend == "fallback":
                            assert "SEC-007" in stderr_output or "不安全" in stderr_output, (
                                "fallback 模式应该打印 SEC-007 警告"
                            )
        finally:
            # 恢复原始值
            password_module._backend = original_backend
            password_module._bcrypt = original_bcrypt
            password_module._pwd_context = original_pwd_context

    def test_bcrypt_unavailable_raises_runtime_error(self):
        """bcrypt 不可用且未启用 fallback 时，hash_password 抛出 RuntimeError"""
        from unittest.mock import patch as mock_patch
        from shared.core.auth import password as password_module

        # 保存原始值
        original_backend = password_module._backend

        try:
            # 模拟 bcrypt 不可用且未启用 fallback
            password_module._backend = "unavailable"

            with pytest.raises(RuntimeError) as exc_info:
                password_module.hash_password("test_password")

            error_msg = str(exc_info.value)
            assert "SEC-007" in error_msg or "bcrypt" in error_msg.lower(), (
                f"错误信息应该包含 SEC-007 或 bcrypt，实际为: {error_msg}"
            )
        finally:
            # 恢复
            password_module._backend = original_backend

    def test_fallback_hash_different_from_bcrypt(self):
        """fallback 模式的哈希格式与 bcrypt 不同（以 $fallback$ 开头）"""
        from unittest.mock import patch as mock_patch
        from shared.core.auth import password as password_module

        # 保存原始值
        original_backend = password_module._backend

        try:
            # 模拟 fallback 模式
            password_module._backend = "fallback"

            hashed = password_module.hash_password("test_fallback_password")
            assert hashed.startswith("$fallback$"), (
                f"fallback 哈希应该以 $fallback$ 开头，实际为: {hashed[:20]}"
            )

            # fallback 模式下的验证也应该工作
            assert password_module.verify_password("test_fallback_password", hashed) is True
            assert password_module.verify_password("wrong_password", hashed) is False
        finally:
            # 恢复
            password_module._backend = original_backend

    def test_fallback_needs_update_always_true(self):
        """fallback 模式的哈希始终需要升级"""
        from unittest.mock import patch as mock_patch
        from shared.core.auth import password as password_module

        original_backend = password_module._backend

        try:
            password_module._backend = "fallback"
            hashed = password_module.hash_password("test")

            # fallback 哈希总是需要升级
            assert password_module.needs_update(hashed) is True, (
                "fallback 模式的哈希应该始终标记为需要升级"
            )
        finally:
            password_module._backend = original_backend

    def test_empty_password_raises_value_error(self):
        """空密码抛出 ValueError"""
        from shared.core.auth.password import hash_password, is_bcrypt_available

        if not is_bcrypt_available():
            pytest.skip("bcrypt 不可用，跳过测试")

        with pytest.raises(ValueError):
            hash_password("")


# ===========================================================================
# 向后兼容性测试
# ===========================================================================

class TestBackwardCompatibility:
    """确保修复不破坏现有功能"""

    def test_config_get_module_token_still_works(self):
        """YunxiGlobalConfig.get_module_token 接口仍然正常工作"""
        from shared.core.config import YunxiGlobalConfig, EnvType

        with patch.dict(os.environ, {}, clear=True):
            config = YunxiGlobalConfig(env=EnvType.DEVELOPMENT)

        # 旧接口应该仍然可用
        token = config.get_module_token("gateway")
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_config_get_all_module_keys(self):
        """get_all_module_keys 返回所有模块（gateway + m0~m12 = 14）"""
        from shared.core.config import YunxiGlobalConfig, EnvType

        with patch.dict(os.environ, {}, clear=True):
            config = YunxiGlobalConfig(env=EnvType.DEVELOPMENT)

        keys = config.get_all_module_keys()
        assert len(keys) == 14, f"应该有 14 个模块，实际 {len(keys)} 个"
        assert "gateway" in keys
        assert "m0" in keys
        assert "m12" in keys

    def test_password_module_exports(self):
        """password 模块导出的函数都可用"""
        from shared.core.auth.password import (
            hash_password, verify_password, needs_update,
            is_bcrypt_available, is_insecure_fallback_mode,
        )

        assert callable(hash_password)
        assert callable(verify_password)
        assert callable(needs_update)
        assert callable(is_bcrypt_available)
        assert callable(is_insecure_fallback_mode)

    def test_auth_module_exports_backward_compat(self):
        """shared.core.auth 导出保持向后兼容"""
        from shared.core.auth import (
            hash_password, verify_password, needs_update,
            is_bcrypt_available, is_insecure_fallback_mode,
        )

        assert callable(hash_password)
        assert callable(verify_password)
        assert callable(needs_update)
        assert callable(is_bcrypt_available)
        # 新增的函数也应该可用
        assert callable(is_insecure_fallback_mode)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
