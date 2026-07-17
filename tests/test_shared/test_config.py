"""
shared.core.config 模块单元测试

测试内容：
- EnvType 枚举
- BaseConfig 基础配置类
- 配置加载与默认值
- 敏感字段脱敏
- 环境检测方法
- 配置热更新
- YunxiGlobalConfig 全局配置
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from shared.core.config import (
    EnvType,
    BaseConfig,
    is_sensitive_field,
    DEFAULT_SENSITIVE_KEYS,
    ModuleEndpointConfig,
    GlobalModuleConfig,
    GlobalSecurityConfig,
    YunxiGlobalConfig,
    get_global_config,
)


# ============================================================
# EnvType 枚举测试
# ============================================================

class TestEnvType:
    """环境类型枚举测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_env_type_has_four_values(self):
        """EnvType 包含 4 种环境类型"""
        assert EnvType.DEVELOPMENT.value == "development"
        assert EnvType.STAGING.value == "staging"
        assert EnvType.PRODUCTION.value == "production"
        assert EnvType.TESTING.value == "testing"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_is_production_property(self):
        """is_production 属性正确判断生产环境"""
        assert EnvType.PRODUCTION.is_production is True
        assert EnvType.DEVELOPMENT.is_production is False
        assert EnvType.STAGING.is_production is False
        assert EnvType.TESTING.is_production is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_is_development_property(self):
        """is_development 属性正确判断开发环境"""
        assert EnvType.DEVELOPMENT.is_development is True
        assert EnvType.PRODUCTION.is_development is False
        assert EnvType.STAGING.is_development is False
        assert EnvType.TESTING.is_development is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_is_staging_property(self):
        """is_staging 属性正确判断预发布环境"""
        assert EnvType.STAGING.is_staging is True
        assert EnvType.DEVELOPMENT.is_staging is False
        assert EnvType.PRODUCTION.is_staging is False


# ============================================================
# 敏感字段检测测试
# ============================================================

class TestSensitiveFieldDetection:
    """敏感字段检测函数测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_token_is_sensitive(self):
        """token 字段被识别为敏感字段"""
        assert is_sensitive_field("token") is True
        assert is_sensitive_field("access_token") is True
        assert is_sensitive_field("admin_token") is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_password_is_sensitive(self):
        """password 字段被识别为敏感字段"""
        assert is_sensitive_field("password") is True
        assert is_sensitive_field("db_password") is True
        assert is_sensitive_field("user_password") is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_api_key_is_sensitive(self):
        """api_key 字段被识别为敏感字段"""
        assert is_sensitive_field("api_key") is True
        assert is_sensitive_field("apikey") is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_secret_is_sensitive(self):
        """secret 字段被识别为敏感字段"""
        assert is_sensitive_field("secret") is True
        assert is_sensitive_field("jwt_secret") is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_normal_field_not_sensitive(self):
        """普通字段不被识别为敏感字段"""
        assert is_sensitive_field("host") is False
        assert is_sensitive_field("port") is False
        assert is_sensitive_field("module_name") is False
        assert is_sensitive_field("log_level") is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_case_insensitive(self):
        """字段名大小写不敏感"""
        assert is_sensitive_field("PASSWORD") is True
        assert is_sensitive_field("Token") is True
        assert is_sensitive_field("Api_Key") is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_default_sensitive_keys_not_empty(self):
        """默认敏感字段集合不为空"""
        assert len(DEFAULT_SENSITIVE_KEYS) > 0
        assert "token" in DEFAULT_SENSITIVE_KEYS
        assert "password" in DEFAULT_SENSITIVE_KEYS


# ============================================================
# BaseConfig 基础配置类测试
# ============================================================

class TestBaseConfig:
    """BaseConfig 基础配置类测试"""

    @pytest.fixture
    def test_config_class(self):
        """创建测试用配置类"""
        from pydantic_settings import SettingsConfigDict

        class TestConfig(BaseConfig):
            module_name: str = "test_module"
            custom_setting: str = "default_value"
            timeout: int = 30
            # 敏感字段
            admin_token: str = ""
            db_password: str = ""

            model_config = SettingsConfigDict(
                env_prefix="TESTCFG_",
                env_file=".env.test",
                extra="allow",
                validate_assignment=True,
            )

        return TestConfig

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_default_values(self, test_config_class):
        """配置类默认值正确"""
        config = test_config_class()
        assert config.module_name == "test_module"
        assert config.custom_setting == "default_value"
        assert config.timeout == 30

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_base_fields_exist(self, test_config_class):
        """基础配置字段存在且有默认值"""
        config = test_config_class()
        assert hasattr(config, "env")
        assert hasattr(config, "host")
        assert hasattr(config, "port")
        assert hasattr(config, "log_level")
        assert hasattr(config, "cors_origins")
        assert config.port > 0

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_env_default_development(self, test_config_class):
        """默认环境为 development"""
        # 清除环境变量影响
        with patch.dict(os.environ, {}, clear=True):
            config = test_config_class()
            assert config.env.value == "development"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_to_dict_returns_dict(self, test_config_class):
        """to_dict() 返回字典"""
        config = test_config_class()
        d = config.to_dict()
        assert isinstance(d, dict)
        assert "module_name" in d
        assert "custom_setting" in d
        assert "timeout" in d

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_to_dict_sanitize_sensitive(self, test_config_class):
        """to_dict(sanitize=True) 脱敏敏感字段"""
        config = test_config_class(admin_token="my-secret-token", db_password="db-pass-123")
        d = config.to_dict(sanitize=True)
        assert d["admin_token"] == "***MASKED***"
        assert d["db_password"] == "***MASKED***"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_to_dict_no_sanitize(self, test_config_class):
        """to_dict(sanitize=False) 保留原始值"""
        config = test_config_class(admin_token="my-secret-token")
        d = config.to_dict(sanitize=False)
        assert d["admin_token"] == "my-secret-token"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_repr_is_sanitized(self, test_config_class):
        """__repr__ 不泄露敏感信息"""
        config = test_config_class(admin_token="super-secret")
        r = repr(config)
        assert "super-secret" not in r

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_str_is_sanitized(self, test_config_class):
        """__str__ 不泄露敏感信息"""
        config = test_config_class(admin_token="super-secret")
        s = str(config)
        assert "super-secret" not in s

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_is_production_property(self, test_config_class):
        """is_production 属性正确"""
        import os
        os.environ["TESTCFG_ADMIN_TOKEN"] = "test-prod-token-1234567890"
        os.environ["TESTCFG_DB_PASSWORD"] = "test-db-password-123456"
        try:
            config = test_config_class(env=EnvType.PRODUCTION)
            assert config.is_production is True

            config_dev = test_config_class(env=EnvType.DEVELOPMENT)
            assert config_dev.is_production is False
        finally:
            del os.environ["TESTCFG_ADMIN_TOKEN"]
            del os.environ["TESTCFG_DB_PASSWORD"]

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_is_development_property(self, test_config_class):
        """is_development 属性正确"""
        config = test_config_class(env=EnvType.DEVELOPMENT)
        assert config.is_development is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_is_staging_property(self, test_config_class):
        """is_staging 属性正确"""
        config = test_config_class(env=EnvType.STAGING)
        assert config.is_staging is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_get_method_existing_key(self, test_config_class):
        """get() 方法获取已存在的配置"""
        config = test_config_class()
        assert config.get("module_name") == "test_module"
        assert config.get("timeout") == 30

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_get_method_missing_key(self, test_config_class):
        """get() 方法获取不存在的配置返回默认值"""
        config = test_config_class()
        assert config.get("nonexistent_key") is None
        assert config.get("nonexistent_key", "default") == "default"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_port_validation(self, test_config_class):
        """端口号范围校验"""
        # 合法端口
        config = test_config_class(port=8080)
        assert config.port == 8080

        # 非法端口应该报错
        with pytest.raises(Exception):
            test_config_class(port=0)

        with pytest.raises(Exception):
            test_config_class(port=70000)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_nested_sanitize(self, test_config_class):
        """嵌套字典中的敏感字段也被脱敏"""
        config = test_config_class()
        # 测试 _sanitize_dict 静态方法
        nested = {
            "user": {"password": "secret", "name": "alice"},
            "token": "abc123",
            "items": [{"api_key": "xyz"}, {"id": 1}],
        }
        BaseConfig._sanitize_dict(nested)
        assert nested["user"]["password"] == "***MASKED***"
        assert nested["user"]["name"] == "alice"
        assert nested["token"] == "***MASKED***"
        assert nested["items"][0]["api_key"] == "***MASKED***"
        assert nested["items"][1]["id"] == 1


# ============================================================
# ModuleEndpointConfig 测试
# ============================================================

class TestModuleEndpointConfig:
    """模块端点配置测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_default_values(self):
        """默认值正确"""
        ep = ModuleEndpointConfig()
        assert ep.host == "0.0.0.0"
        assert ep.port == 8000
        assert ep.token == ""
        assert ep.enabled is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_custom_values(self):
        """自定义值正确"""
        ep = ModuleEndpointConfig(
            host="127.0.0.1",
            port=9000,
            token="my-token",
            base_url="http://localhost:9000",
            enabled=False,
        )
        assert ep.host == "127.0.0.1"
        assert ep.port == 9000
        assert ep.token == "my-token"
        assert ep.enabled is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_health_check_path_default(self):
        """默认健康检查路径"""
        ep = ModuleEndpointConfig()
        assert ep.health_check_path == "/health"


# ============================================================
# GlobalModuleConfig 测试
# ============================================================

class TestGlobalModuleConfig:
    """全局模块配置测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_all_modules_exist(self):
        """所有模块配置都存在"""
        gmc = GlobalModuleConfig()
        modules = ["gateway", "m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10", "m11", "m12"]
        for m in modules:
            assert hasattr(gmc, m), f"缺少模块配置: {m}"
            ep = getattr(gmc, m)
            assert isinstance(ep, ModuleEndpointConfig)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_module_ports_unique(self):
        """各模块端口不重复"""
        gmc = GlobalModuleConfig()
        ports = []
        for field_name in gmc.model_fields:
            ep = getattr(gmc, field_name)
            if isinstance(ep, ModuleEndpointConfig):
                ports.append(ep.port)
        assert len(ports) == len(set(ports)), "存在重复的端口号"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_m8_port_is_8008(self):
        """M8 端口为 8008"""
        gmc = GlobalModuleConfig()
        assert gmc.m8.port == 8008

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_m11_port_is_8011(self):
        """M11 端口为 8011"""
        gmc = GlobalModuleConfig()
        assert gmc.m11.port == 8011


# ============================================================
# YunxiGlobalConfig 测试
# ============================================================

class TestYunxiGlobalConfig:
    """全局配置测试"""

    @pytest.fixture
    def global_config(self):
        """创建全局配置实例"""
        return YunxiGlobalConfig()

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_security_config_exists(self, global_config):
        """安全配置存在"""
        assert hasattr(global_config, "security")
        assert isinstance(global_config.security, GlobalSecurityConfig)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_modules_config_exists(self, global_config):
        """模块配置存在"""
        assert hasattr(global_config, "modules")
        assert isinstance(global_config.modules, GlobalModuleConfig)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_get_module_endpoint(self, global_config):
        """get_module_endpoint 方法"""
        ep = global_config.get_module_endpoint("m8")
        assert ep is not None
        assert ep.port == 8008

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_get_module_endpoint_invalid(self, global_config):
        """get_module_endpoint 对无效模块返回 None"""
        assert global_config.get_module_endpoint("nonexistent") is None

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_get_module_port(self, global_config):
        """get_module_port 方法"""
        assert global_config.get_module_port("m8") == 8008
        assert global_config.get_module_port("m11") == 8011

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_get_module_base_url(self, global_config):
        """get_module_base_url 方法"""
        url = global_config.get_module_base_url("m8")
        assert url is not None
        assert "8008" in url

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_get_all_module_keys(self, global_config):
        """get_all_module_keys 返回所有模块 key"""
        keys = global_config.get_all_module_keys()
        assert isinstance(keys, list)
        assert "m8" in keys
        assert "m11" in keys
        assert len(keys) >= 12

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_jwt_secret_default(self, global_config):
        """JWT 密钥有默认值"""
        assert global_config.security.jwt_secret != ""
        assert len(global_config.security.jwt_secret) > 10

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_access_token_expire_minutes(self, global_config):
        """访问令牌有效期配置"""
        assert global_config.security.access_token_expire_minutes > 0


# ============================================================
# 全局配置单例测试
# ============================================================

class TestGlobalConfigSingleton:
    """全局配置单例测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_get_global_config_returns_same_instance(self):
        """get_global_config 返回单例"""
        config1 = get_global_config()
        config2 = get_global_config()
        assert config1 is config2

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.config
    def test_get_global_config_type(self):
        """返回类型正确"""
        config = get_global_config()
        assert isinstance(config, YunxiGlobalConfig)
