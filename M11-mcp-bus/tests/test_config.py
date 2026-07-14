"""M11 MCP Bus - 配置模块单元测试.

测试 Settings 类的默认值、环境变量读取、属性计算等功能。
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# 确保项目根目录在 Python 路径中，使 src 作为包导入
# 这样源码中的相对导入（from ..config import ...）才能正确解析
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import Settings, get_settings, reload_settings


class TestSettingsDefaults(unittest.TestCase):
    """测试配置默认值."""

    def setUp(self) -> None:
        """每个测试前清除设置缓存."""
        # 清除 lru_cache，确保每次测试都是全新的实例
        reload_settings()

    def test_default_host(self) -> None:
        """测试 host 默认值为 0.0.0.0."""
        settings = Settings()
        self.assertEqual(settings.host, "0.0.0.0")

    def test_default_port(self) -> None:
        """测试 port 默认值为 8011."""
        settings = Settings()
        self.assertEqual(settings.port, 8011)

    def test_default_env(self) -> None:
        """测试 env 默认值为 development."""
        settings = Settings()
        self.assertEqual(settings.env, "development")

    def test_default_log_level(self) -> None:
        """测试 log_level 默认值为 info."""
        settings = Settings()
        self.assertEqual(settings.log_level, "info")

    def test_default_db_path(self) -> None:
        """测试 db_path 默认值."""
        settings = Settings()
        self.assertEqual(settings.db_path, "~/.yunxi/m11_bus.db")

    def test_default_admin_token(self) -> None:
        """测试 admin_token 默认值为空字符串."""
        settings = Settings()
        self.assertEqual(settings.admin_token, "")


class TestSettingsEnvironment(unittest.TestCase):
    """测试环境变量读取."""

    def setUp(self) -> None:
        """每个测试前清除设置缓存."""
        reload_settings()

    def test_env_variable_read_host(self) -> None:
        """测试通过环境变量 M11_HOST 设置 host."""
        with patch.dict(os.environ, {"M11_HOST": "127.0.0.1"}):
            settings = Settings()
            self.assertEqual(settings.host, "127.0.0.1")

    def test_env_variable_read_port(self) -> None:
        """测试通过环境变量 M11_PORT 设置 port."""
        with patch.dict(os.environ, {"M11_PORT": "9090"}):
            settings = Settings()
            self.assertEqual(settings.port, 9090)

    def test_env_variable_read_env(self) -> None:
        """测试通过环境变量 M11_ENV 设置 env."""
        with patch.dict(os.environ, {"M11_ENV": "production"}):
            settings = Settings()
            self.assertEqual(settings.env, "production")

    def test_env_variable_read_admin_token(self) -> None:
        """测试通过环境变量 M11_ADMIN_TOKEN 设置 admin_token."""
        with patch.dict(os.environ, {"M11_ADMIN_TOKEN": "test-token-123"}):
            settings = Settings()
            self.assertEqual(settings.admin_token, "test-token-123")


class TestSettingsProperties(unittest.TestCase):
    """测试配置计算属性."""

    def setUp(self) -> None:
        """每个测试前清除设置缓存."""
        reload_settings()

    def test_db_file_path_expands_user(self) -> None:
        """测试 db_file_path 属性正确展开 ~ 为用户目录."""
        settings = Settings(db_path="~/test_db.db")
        path = settings.db_file_path
        # 展开后不应该包含 ~
        self.assertNotIn("~", str(path))
        self.assertIsInstance(path, Path)
        self.assertTrue(path.is_absolute())

    def test_db_url_format(self) -> None:
        """测试 db_url 属性格式为 sqlite:///..."""
        settings = Settings(db_path="/tmp/test.db")
        url = settings.db_url
        self.assertTrue(url.startswith("sqlite:///"))
        self.assertIn("test.db", url)

    def test_is_development_true(self) -> None:
        """测试 env=development 时 is_development 为 True."""
        settings = Settings(env="development")
        self.assertTrue(settings.is_development)
        self.assertFalse(settings.is_production)

    def test_is_production_true(self) -> None:
        """测试 env=production 时 is_production 为 True."""
        settings = Settings(env="production")
        self.assertTrue(settings.is_production)
        self.assertFalse(settings.is_development)

    def test_is_development_false_for_other_env(self) -> None:
        """测试其他环境值时 is_development 和 is_production 均为 False."""
        settings = Settings(env="staging")
        self.assertFalse(settings.is_development)
        self.assertFalse(settings.is_production)


class TestCorsOriginList(unittest.TestCase):
    """测试 CORS 来源列表解析."""

    def setUp(self) -> None:
        """每个测试前清除设置缓存."""
        reload_settings()

    def test_default_cors_origins_is_wildcard(self) -> None:
        """测试默认 cors_origins 包含通配符或开发地址."""
        settings = Settings()
        origins = settings.cors_origins
        # 兼容默认 "*" 和开发环境多源列表
        self.assertTrue(
            origins == "*" or "localhost" in origins or "127.0.0.1" in origins,
            f"Unexpected cors_origins: {origins}",
        )

    def test_cors_origin_list_with_wildcard(self) -> None:
        """测试 cors_origins='*' 时返回 ['*']."""
        settings = Settings(cors_origins="*")
        result = settings.cors_origin_list
        self.assertEqual(result, ["*"])

    def test_cors_origin_list_single_origin(self) -> None:
        """测试单个来源解析."""
        settings = Settings(cors_origins="http://localhost:3000")
        result = settings.cors_origin_list
        self.assertEqual(result, ["http://localhost:3000"])

    def test_cors_origin_list_multiple_origins(self) -> None:
        """测试多个逗号分隔来源解析."""
        settings = Settings(
            cors_origins="http://localhost:3000,http://example.com,https://api.test.com"
        )
        result = settings.cors_origin_list
        self.assertEqual(
            result,
            ["http://localhost:3000", "http://example.com", "https://api.test.com"],
        )

    def test_cors_origin_list_strips_whitespace(self) -> None:
        """测试来源解析时去除空格."""
        settings = Settings(
            cors_origins=" http://a.com ,  http://b.com  "
        )
        result = settings.cors_origin_list
        self.assertEqual(result, ["http://a.com", "http://b.com"])

    def test_cors_origin_list_empty_string(self) -> None:
        """测试空字符串时返回 ['*']."""
        settings = Settings(cors_origins="")
        result = settings.cors_origin_list
        self.assertEqual(result, ["*"])


class TestSettingsSingleton(unittest.TestCase):
    """测试配置单例模式."""

    def setUp(self) -> None:
        """每个测试前清除设置缓存."""
        reload_settings()

    def test_get_settings_returns_same_instance(self) -> None:
        """测试 get_settings() 多次调用返回同一实例."""
        s1 = get_settings()
        s2 = get_settings()
        self.assertIs(s1, s2)

    def test_reload_settings_creates_new_instance(self) -> None:
        """测试 reload_settings() 返回新的实例."""
        s1 = get_settings()
        s2 = reload_settings()
        # 重新加载后应该是新的实例
        self.assertIsNot(s1, s2)
        # 但后续调用应返回同一实例
        s3 = get_settings()
        self.assertIs(s2, s3)


if __name__ == "__main__":
    unittest.main()
