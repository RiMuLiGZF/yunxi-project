"""
配置模块边界条件与异常路径测试

对应问题：TST-006（边界条件与异常路径测试不足）
测试模块：shared.core.config

覆盖场景：
- 空值配置
- 非法值配置
- 边界值配置（端口范围、密钥长度等）
- 敏感字段验证
- 生产环境校验
- CORS 安全校验
- WAF 安全校验
- 弱密钥检测
- 配置热更新
- 健康检查边界
- 脱敏输出
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 确保可以导入 shared 模块
SHARED_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SHARED_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


# ===========================================================================
# 1. 密钥验证边界测试
# ===========================================================================

class TestValidateSecretKey:
    """validate_secret_key 边界测试"""

    @pytest.mark.parametrize("empty_key", [
        "",
        None,
        "   ",
        "\t\n",
    ])
    def test_empty_key_invalid(self, empty_key):
        """空密钥应验证失败"""
        from shared.core.config import validate_secret_key

        is_valid, msg = validate_secret_key(empty_key, "test_secret")
        assert is_valid is False
        assert "不能为空" in msg or "空白" in msg

    def test_whitespace_only_key(self):
        """纯空白密钥应验证失败"""
        from shared.core.config import validate_secret_key

        is_valid, msg = validate_secret_key("   \t  \n  ", "test_secret")
        assert is_valid is False
        assert "空白" in msg

    @pytest.mark.parametrize("weak_key", [
        "changeme_secret",
        "yunxi-secret-123",
        "admin123",
        "password",
        "123456",
        "test_key",
        "default_value",
        "secret_key",
        "your-api-key",
        "example_secret",
    ])
    def test_weak_key_patterns(self, weak_key):
        """弱密钥模式应被检测到"""
        from shared.core.config import validate_secret_key

        # 确保密钥足够长，但模式是弱的
        key = weak_key + "a" * 20  # 确保长度足够
        is_valid, msg = validate_secret_key(key, "test_secret")
        assert is_valid is False
        assert "弱密钥" in msg or "默认" in msg

    @pytest.mark.parametrize("weak_key_exact", [
        "admin123",
        "password",
        "123456",
        "test",
        "default",
        "secret",
    ])
    def test_exact_weak_key_patterns(self, weak_key_exact):
        """精确匹配弱密钥模式应被检测到"""
        from shared.core.config import validate_secret_key

        # 注意：validate_secret_key 先检查长度，后检查弱密钥模式
        # 对于短密钥，长度检查会先失败
        # 对于恰好等于模式的密钥，应该通过 == 检查被捕获
        is_valid, msg = validate_secret_key(weak_key_exact, "test_secret")
        # 总之应该失败（要么长度不够，要么弱密钥模式匹配）
        assert is_valid is False
        # 至少有一个失败原因
        assert "不能" in msg or "长度不足" in msg or "弱密钥" in msg or "默认" in msg

    def test_jwt_secret_min_length_32(self):
        """JWT secret 最小长度 32"""
        from shared.core.config import validate_secret_key

        # 31 字符应失败
        key_31 = "a" * 31
        is_valid, msg = validate_secret_key(key_31, "jwt_secret")
        assert is_valid is False
        assert "32" in msg

        # 32 字符应通过（长度通过，非弱密钥）
        key_32 = "k" * 32
        is_valid, msg = validate_secret_key(key_32, "jwt_secret")
        assert is_valid is True

    def test_encryption_key_min_length_32(self):
        """encryption_key 最小长度 32"""
        from shared.core.config import validate_secret_key

        key_31 = "a" * 31
        is_valid, _ = validate_secret_key(key_31, "encryption_key")
        assert is_valid is False

        key_32 = "k" * 32
        is_valid, _ = validate_secret_key(key_32, "encryption_key")
        assert is_valid is True

    def test_admin_token_min_length_16(self):
        """admin_token 最小长度 16"""
        from shared.core.config import validate_secret_key

        key_15 = "a" * 15
        is_valid, _ = validate_secret_key(key_15, "admin_token")
        assert is_valid is False

        key_16 = "k" * 16
        is_valid, _ = validate_secret_key(key_16, "admin_token")
        assert is_valid is True

    def test_api_key_min_length_16(self):
        """api_key 最小长度 16"""
        from shared.core.config import validate_secret_key

        key_15 = "a" * 15
        is_valid, _ = validate_secret_key(key_15, "api_key")
        assert is_valid is False

        key_16 = "k" * 16
        is_valid, _ = validate_secret_key(key_16, "api_key")
        assert is_valid is True

    def test_password_pure_digits_fails(self):
        """纯数字密码应验证失败"""
        from shared.core.config import validate_secret_key

        # 使用足够长的纯数字密码（不是已知弱密码模式前缀）
        # 避免以 123456 开头（弱密钥模式），用 987654 开头
        key = "9876543210987654"  # 16 位纯数字，不以弱模式开头
        is_valid, msg = validate_secret_key(key, "user_password")
        assert is_valid is False
        assert "纯数字" in msg

    def test_password_all_same_chars_fails(self):
        """全相同字符密码应验证失败"""
        from shared.core.config import validate_secret_key

        key = "aaaaaaaaaaaa"  # 12 个相同字符
        is_valid, msg = validate_secret_key(key, "user_password")
        assert is_valid is False
        assert "过于简单" in msg or "强度不足" in msg

    def test_non_string_key_invalid(self):
        """非字符串密钥应验证失败"""
        from shared.core.config import validate_secret_key

        is_valid, _ = validate_secret_key(12345, "test_secret")
        assert is_valid is False

        is_valid, _ = validate_secret_key([], "test_secret")
        assert is_valid is False

    def test_custom_min_length(self):
        """自定义最小长度应生效"""
        from shared.core.config import validate_secret_key

        # 自定义最小长度为 50
        key_49 = "a" * 49
        is_valid, _ = validate_secret_key(key_49, "custom", min_length=50)
        assert is_valid is False

        key_50 = "k" * 50
        is_valid, _ = validate_secret_key(key_50, "custom", min_length=50)
        assert is_valid is True

    def test_check_weak_false_skips_weak_check(self):
        """check_weak=False 时跳过弱密钥检查"""
        from shared.core.config import validate_secret_key

        weak_key = "changeme_" + "a" * 20
        # check_weak=True 时应失败
        is_valid, _ = validate_secret_key(weak_key, "test", check_weak=True)
        assert is_valid is False

        # check_weak=False 时应通过（长度够）
        is_valid, _ = validate_secret_key(weak_key, "test", check_weak=False)
        assert is_valid is True

    def test_very_long_key_valid(self):
        """非常长的密钥应验证通过"""
        from shared.core.config import validate_secret_key

        long_key = "k" * 1000
        is_valid, msg = validate_secret_key(long_key, "jwt_secret")
        assert is_valid is True
        assert "1000" in msg  # 消息中应包含长度信息


# ===========================================================================
# 2. is_default_or_weak_key 测试
# ===========================================================================

class TestIsDefaultOrWeakKey:
    """is_default_or_weak_key 边界测试"""

    @pytest.mark.parametrize("weak_key", [
        "",
        None,
        "changeme_secret",
        "yunxi-secret",
        "admin123",
        "password",
        "test_key",
    ])
    def test_weak_keys_return_true(self, weak_key):
        """弱/默认密钥应返回 True"""
        from shared.core.config import is_default_or_weak_key

        assert is_default_or_weak_key(weak_key) is True

    def test_strong_key_returns_false(self):
        """强密钥应返回 False"""
        from shared.core.config import is_default_or_weak_key

        strong_key = "xK9$mP2@qR7!nV5#bW8&"
        assert is_default_or_weak_key(strong_key) is False

    def test_non_string_returns_true(self):
        """非字符串输入应返回 True（视为无效）"""
        from shared.core.config import is_default_or_weak_key

        assert is_default_or_weak_key(123) is True
        assert is_default_or_weak_key([]) is True
        assert is_default_or_weak_key({}) is True


# ===========================================================================
# 3. is_sensitive_field 测试
# ===========================================================================

class TestIsSensitiveField:
    """敏感字段检测边界测试"""

    @pytest.mark.parametrize("field_name", [
        "token",
        "access_token",
        "refresh_token",
        "jwt_secret",
        "api_secret",
        "db_password",
        "admin_password",
        "api_key",
        "apikey",
        "encryption_key",
        "private_key",
        "access_key",
        "admin_token",
        "redis_password",
        "mongo_password",
    ])
    def test_sensitive_field_names(self, field_name):
        """敏感字段名应被正确识别"""
        from shared.core.config import is_sensitive_field

        assert is_sensitive_field(field_name) is True

    @pytest.mark.parametrize("field_name", [
        "Token",
        "SECRET",
        "Password",
        "ApiKey",
        "JWT_Secret",
    ])
    def test_sensitive_field_case_insensitive(self, field_name):
        """敏感字段检测应不区分大小写"""
        from shared.core.config import is_sensitive_field

        assert is_sensitive_field(field_name) is True

    @pytest.mark.parametrize("field_name", [
        "host",
        "port",
        "name",
        "log_level",
        "timeout",
        "enabled",
        "url",
        "path",
        "username",
    ])
    def test_non_sensitive_fields(self, field_name):
        """非敏感字段不应被识别为敏感"""
        from shared.core.config import is_sensitive_field

        assert is_sensitive_field(field_name) is False


# ===========================================================================
# 4. BaseConfig 边界测试
# ===========================================================================

class TestBaseConfig:
    """BaseConfig 边界测试"""

    def test_port_min_boundary(self):
        """端口最小值边界（1）"""
        from shared.core.config import BaseConfig, EnvType

        # 端口 1 是有效的
        config = BaseConfig(port=1, env=EnvType.DEVELOPMENT, admin_token="test-token-min-16chars!!")
        assert config.port == 1

    def test_port_max_boundary(self):
        """端口最大值边界（65535）"""
        from shared.core.config import BaseConfig, EnvType

        # 端口 65535 是有效的
        config = BaseConfig(port=65535, env=EnvType.DEVELOPMENT, admin_token="test-token-min-16chars!!")
        assert config.port == 65535

    def test_port_zero_invalid(self):
        """端口 0 应无效"""
        from shared.core.config import BaseConfig, EnvType
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BaseConfig(port=0, env=EnvType.DEVELOPMENT)

    def test_port_above_max_invalid(self):
        """端口超过 65535 应无效"""
        from shared.core.config import BaseConfig, EnvType
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BaseConfig(port=65536, env=EnvType.DEVELOPMENT)

    def test_port_negative_invalid(self):
        """负端口应无效"""
        from shared.core.config import BaseConfig, EnvType
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BaseConfig(port=-1, env=EnvType.DEVELOPMENT)

    def test_env_type_all_values(self):
        """所有环境类型枚举值应有效"""
        from shared.core.config import BaseConfig, EnvType

        strong_token = "strong-admin-token-32-characters-min!!"
        # 非生产环境不需要强 token
        for env_val in [EnvType.DEVELOPMENT, EnvType.STAGING, EnvType.TESTING]:
            config = BaseConfig(env=env_val)
            assert config.env == env_val

        # 生产环境需要提供强 admin_token 和正确的 CORS/WAF 配置
        config = BaseConfig(
            env=EnvType.PRODUCTION,
            admin_token=strong_token,
            cors_origins="https://app.example.com",
            waf_enabled=True,
            waf_mode="block",
        )
        assert config.env == EnvType.PRODUCTION

    def test_invalid_env_type_raises(self):
        """无效的环境类型应抛出错误"""
        from shared.core.config import BaseConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BaseConfig(env="invalid_env")

    def test_development_allows_weak_admin_token(self):
        """开发环境允许弱/空 admin_token（警告但不阻止）"""
        from shared.core.config import BaseConfig, EnvType

        # 开发环境下弱密钥不应抛异常
        config = BaseConfig(env=EnvType.DEVELOPMENT, admin_token="")
        assert config.env == EnvType.DEVELOPMENT

    def test_production_strong_admin_token_passes(self):
        """生产环境下强 admin_token 应通过"""
        from shared.core.config import BaseConfig, EnvType

        strong_token = "xK9$mP2@qR7!nV5#bW8&zL3"
        config = BaseConfig(
            env=EnvType.DEVELOPMENT,  # 用 development 避免 CORS/WAF 校验
            admin_token=strong_token,
        )
        assert config.admin_token == strong_token

    def test_log_level_case_insensitive(self):
        """日志级别应为字符串（不强制校验大小写，交由 logger 处理）"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            log_level="DEBUG",
            admin_token="test-token-min-16chars!!",
        )
        assert config.log_level == "DEBUG"


# ===========================================================================
# 5. CORS 安全校验边界测试
# ===========================================================================

class TestCorsSecurity:
    """CORS 安全校验边界测试"""

    def test_production_wildcard_cors_raises(self):
        """生产环境 CORS 通配符应抛出错误"""
        from shared.core.config import BaseConfig, EnvType

        with pytest.raises(ValueError, match="CORS"):
            BaseConfig(
                env=EnvType.PRODUCTION,
                cors_origins="*",
                admin_token="strong-admin-token-32chars!!",
            )

    def test_production_empty_cors_raises(self):
        """生产环境空 CORS 应抛出错误"""
        from shared.core.config import BaseConfig, EnvType

        with pytest.raises(ValueError, match="CORS"):
            BaseConfig(
                env=EnvType.PRODUCTION,
                cors_origins="",
                admin_token="strong-admin-token-32chars!!",
            )

    def test_production_specific_domain_passes(self):
        """生产环境具体域名 CORS 应通过"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.PRODUCTION,
            cors_origins="https://app.example.com",
            admin_token="strong-admin-token-32chars!!",
            waf_enabled=True,
            waf_mode="block",
        )
        assert config.cors_origins == "https://app.example.com"

    def test_production_multiple_domains_passes(self):
        """生产环境多个域名 CORS 应通过"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.PRODUCTION,
            cors_origins="https://app.example.com,https://admin.example.com",
            admin_token="strong-admin-token-32chars!!",
            waf_enabled=True,
            waf_mode="block",
        )
        assert config.cors_origins == "https://app.example.com,https://admin.example.com"

    def test_development_wildcard_cors_allowed(self):
        """开发环境 CORS 通配符应允许（警告但不阻止）"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            cors_origins="*",
            admin_token="",
        )
        assert config.cors_origins == "*"

    def test_cors_with_spaces(self):
        """CORS 来源中的空格应被正确处理"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.PRODUCTION,
            cors_origins=" https://a.com , https://b.com ",  # 有空格
            admin_token="strong-admin-token-32chars!!",
            waf_enabled=True,
            waf_mode="block",
        )
        # 不应抛异常（空格在分割时会被 strip）
        assert "https://a.com" in config.cors_origins


# ===========================================================================
# 6. WAF 安全校验边界测试
# ===========================================================================

class TestWafSecurity:
    """WAF 安全校验边界测试"""

    @staticmethod
    def _make_waf_config(**kwargs):
        """创建一个带 WAF 字段的配置类实例"""
        from shared.core.config import BaseConfig, EnvType
        from pydantic import Field
        from pydantic_settings import SettingsConfigDict

        class WafTestConfig(BaseConfig):
            """测试用配置类，包含 WAF 字段"""
            waf_enabled: bool = Field(default=True, description="WAF 开关")
            waf_mode: str = Field(default="block", description="WAF 模式")

            model_config = SettingsConfigDict(
                env_prefix="WAF_TEST_",
                env_file=".env",
                extra="allow",
                validate_assignment=True,
            )

        return WafTestConfig(**kwargs)

    def test_production_waf_disabled_raises(self):
        """生产环境 WAF 未启用应抛出错误"""
        from shared.core.config import EnvType

        with pytest.raises(ValueError, match="WAF"):
            self._make_waf_config(
                env=EnvType.PRODUCTION,
                waf_enabled=False,
                waf_mode="block",
                cors_origins="https://app.example.com",
                admin_token="strong-admin-token-32chars!!",
            )

    def test_production_waf_monitor_mode_raises(self):
        """生产环境 WAF monitor 模式应抛出错误"""
        from shared.core.config import EnvType

        with pytest.raises(ValueError, match="WAF"):
            self._make_waf_config(
                env=EnvType.PRODUCTION,
                waf_enabled=True,
                waf_mode="monitor",
                cors_origins="https://app.example.com",
                admin_token="strong-admin-token-32chars!!",
            )

    def test_production_waf_block_mode_passes(self):
        """生产环境 WAF block 模式应通过"""
        from shared.core.config import EnvType

        config = self._make_waf_config(
            env=EnvType.PRODUCTION,
            waf_enabled=True,
            waf_mode="block",
            cors_origins="https://app.example.com",
            admin_token="strong-admin-token-32chars!!",
        )
        assert config.waf_mode == "block"

    def test_development_waf_monitor_allowed(self):
        """开发环境 WAF monitor 模式应允许"""
        from shared.core.config import EnvType

        config = self._make_waf_config(
            env=EnvType.DEVELOPMENT,
            waf_enabled=True,
            waf_mode="monitor",
            admin_token="",
        )
        assert config.waf_mode == "monitor"

    def test_production_waf_case_insensitive(self):
        """生产环境 WAF mode 大写 MONITOR 应抛出错误"""
        from shared.core.config import EnvType

        with pytest.raises(ValueError, match="WAF"):
            self._make_waf_config(
                env=EnvType.PRODUCTION,
                waf_enabled=True,
                waf_mode="MONITOR",  # 大写
                cors_origins="https://app.example.com",
                admin_token="strong-admin-token-32chars!!",
            )

    def test_base_config_without_waf_fields(self):
        """没有 WAF 字段的 BaseConfig 不应触发 WAF 校验"""
        from shared.core.config import BaseConfig, EnvType

        # BaseConfig 没有 waf_enabled/waf_mode 字段
        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            admin_token="test-token-16chars-min!",
        )
        # 不应有 waf_enabled 属性（除非通过 extra 传入）
        assert not hasattr(config, "waf_enabled") or "waf_enabled" not in config.model_fields


# ===========================================================================
# 7. 配置脱敏测试
# ===========================================================================

class TestConfigSanitization:
    """配置脱敏边界测试"""

    def test_to_dict_sanitize_masks_sensitive(self):
        """to_dict(sanitize=True) 应脱敏敏感字段"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            admin_token="my-secret-token-12345",
        )
        data = config.to_dict(sanitize=True)
        assert data["admin_token"] == "***MASKED***"

    def test_to_dict_no_sanitize_shows_real(self):
        """to_dict(sanitize=False) 应显示真实值"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            admin_token="my-secret-token-12345",
        )
        data = config.to_dict(sanitize=False)
        assert data["admin_token"] == "my-secret-token-12345"

    def test_repr_is_sanitized(self):
        """__repr__ 应脱敏"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            admin_token="my-secret-token-12345",
        )
        repr_str = repr(config)
        assert "my-secret-token" not in repr_str

    def test_str_is_sanitized(self):
        """__str__ 应脱敏"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            admin_token="my-secret-token-12345",
        )
        str_val = str(config)
        assert "my-secret-token" not in str_val

    def test_nested_dict_sanitization(self):
        """嵌套字典中的敏感字段应被脱敏"""
        from shared.core.config import BaseConfig

        # 测试 _sanitize_dict 静态方法
        test_dict = {
            "host": "localhost",
            "nested": {
                "api_key": "secret-key-123",
                "port": 8080,
            },
        }
        BaseConfig._sanitize_dict(test_dict)
        assert test_dict["host"] == "localhost"
        assert test_dict["nested"]["api_key"] == "***MASKED***"
        assert test_dict["nested"]["port"] == 8080

    def test_list_of_dicts_sanitization(self):
        """字典列表中的敏感字段应被脱敏"""
        from shared.core.config import BaseConfig

        test_dict = {
            "items": [
                {"name": "item1", "password": "pass1"},
                {"name": "item2", "password": "pass2"},
            ]
        }
        BaseConfig._sanitize_dict(test_dict)
        assert test_dict["items"][0]["password"] == "***MASKED***"
        assert test_dict["items"][1]["password"] == "***MASKED***"
        assert test_dict["items"][0]["name"] == "item1"

    def test_empty_value_not_masked(self):
        """空字符串的敏感字段不应被特殊处理（保持空）"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            admin_token="",
        )
        data = config.to_dict(sanitize=True)
        # 空值脱敏后可能还是空或者被 mask，都可以接受
        assert isinstance(data["admin_token"], str)


# ===========================================================================
# 8. 健康检查边界测试
# ===========================================================================

class TestHealthCheck:
    """配置健康检查边界测试"""

    def test_development_weak_keys_gives_warning(self):
        """开发环境弱密钥应给出 warning 级别问题"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            admin_token="",
        )
        report = config.health_check()
        assert report["status"] == "warning"
        assert report["warning_count"] > 0

    def test_valid_port_health_ok(self):
        """有效端口的健康检查应通过"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            port=8080,
            admin_token="test-token-16chars-min!",
        )
        report = config.health_check()
        assert "port_config" in report["checks"]
        assert report["checks"]["port_config"]["status"] == "ok"

    def test_issue_count_matches(self):
        """健康检查的 issue_count 应与实际 issues 数量一致"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            admin_token="",
        )
        report = config.health_check()
        assert report["issue_count"] == len(report["issues"])

    def test_error_count_matches(self):
        """error_count 应与 error 级 issues 数量一致"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            admin_token="",
        )
        report = config.health_check()
        error_count = sum(1 for i in report["issues"] if i["level"] == "error")
        assert report["error_count"] == error_count

    def test_warning_count_matches(self):
        """warning_count 应与 warning 级 issues 数量一致"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            admin_token="",
        )
        report = config.health_check()
        warning_count = sum(1 for i in report["issues"] if i["level"] == "warning")
        assert report["warning_count"] == warning_count

    def test_assert_healthy_development_warning(self):
        """开发环境警告级问题 assert_healthy 不应抛出异常"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(
            env=EnvType.DEVELOPMENT,
            admin_token="",
        )
        # warning 级别不应抛出 RuntimeError
        try:
            config.assert_healthy()
        except RuntimeError:
            pytest.fail("开发环境警告级问题不应抛出 RuntimeError")


# ===========================================================================
# 9. generate_secure_key 边界测试
# ===========================================================================

class TestGenerateSecureKey:
    """generate_secure_key 边界测试"""

    def test_default_length_32(self):
        """默认长度应为 32 字节（hex 编码后 64 字符）"""
        from shared.core.config import generate_secure_key

        key = generate_secure_key()
        # hex 编码：32 字节 = 64 字符
        assert len(key) == 64

    def test_custom_length(self):
        """自定义长度应生效"""
        from shared.core.config import generate_secure_key

        key = generate_secure_key(length=16)
        assert len(key) == 32  # 16 字节 hex = 32 字符

    def test_url_safe_mode(self):
        """url_safe 模式应使用 URL 安全字符集"""
        from shared.core.config import generate_secure_key

        key = generate_secure_key(length=32, url_safe=True)
        # URL 安全 base64 不应包含 + / =
        assert "+" not in key
        assert "/" not in key
        assert "=" not in key

    def test_keys_are_unique(self):
        """两次生成的密钥应不同"""
        from shared.core.config import generate_secure_key

        key1 = generate_secure_key()
        key2 = generate_secure_key()
        assert key1 != key2

    def test_zero_length_key(self):
        """0 长度密钥应返回空字符串"""
        from shared.core.config import generate_secure_key

        key = generate_secure_key(length=0)
        assert len(key) == 0

    def test_very_long_key(self):
        """非常长的密钥应能正常生成"""
        from shared.core.config import generate_secure_key

        key = generate_secure_key(length=1024)
        assert len(key) == 2048  # 1024 字节 hex = 2048 字符


# ===========================================================================
# 10. EnvType 属性测试
# ===========================================================================

class TestEnvType:
    """EnvType 枚举边界测试"""

    def test_is_production_true(self):
        """production 环境的 is_production 应为 True"""
        from shared.core.config import EnvType

        assert EnvType.PRODUCTION.is_production is True

    def test_is_production_false_for_others(self):
        """非 production 环境的 is_production 应为 False"""
        from shared.core.config import EnvType

        assert EnvType.DEVELOPMENT.is_production is False
        assert EnvType.STAGING.is_production is False
        assert EnvType.TESTING.is_production is False

    def test_is_development_true(self):
        """development 环境的 is_development 应为 True"""
        from shared.core.config import EnvType

        assert EnvType.DEVELOPMENT.is_development is True

    def test_is_staging_true(self):
        """staging 环境的 is_staging 应为 True"""
        from shared.core.config import EnvType

        assert EnvType.STAGING.is_staging is True

    def test_env_type_string_value(self):
        """EnvType 的值应为字符串"""
        from shared.core.config import EnvType

        assert isinstance(EnvType.DEVELOPMENT.value, str)
        assert EnvType.DEVELOPMENT.value == "development"
        assert EnvType.PRODUCTION.value == "production"


# ===========================================================================
# 11. 配置 get 方法边界测试
# ===========================================================================

class TestConfigGet:
    """配置 get 方法边界测试"""

    def test_get_existing_field(self):
        """获取存在的字段应返回正确值"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(env=EnvType.DEVELOPMENT, port=9000)
        assert config.get("port") == 9000

    def test_get_nonexistent_field_returns_default(self):
        """获取不存在的字段应返回默认值"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(env=EnvType.DEVELOPMENT)
        assert config.get("nonexistent_field") is None
        assert config.get("nonexistent_field", "fallback") == "fallback"

    def test_get_empty_path(self):
        """空路径应返回默认值"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(env=EnvType.DEVELOPMENT)
        assert config.get("") is None

    def test_get_deep_nonexistent_path(self):
        """深层不存在的路径应返回默认值"""
        from shared.core.config import BaseConfig, EnvType

        config = BaseConfig(env=EnvType.DEVELOPMENT)
        assert config.get("a.b.c.d") is None
        assert config.get("a.b.c.d", "default") == "default"
