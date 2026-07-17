"""
API-Gateway 配置系统测试（CQ-007 + AR-002, P2级）

测试目标：
1. 新配置 GatewayModuleConfig 正常工作
2. 旧配置 GatewaySettings 兼容层正常工作（deprecated）
3. 两套配置数据完全一致
4. 路由表只有一份真源
5. 属性写入双向同步
6. 环境变量正确加载
"""

import os
import sys
import warnings
import unittest
from pathlib import Path

# 将项目根目录加入 path，以便导入 shared 模块
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 将 API-Gateway 目录加入 path，以便导入 src.config
_gateway_root = Path(__file__).resolve().parent.parent
if str(_gateway_root) not in sys.path:
    sys.path.insert(0, str(_gateway_root))


class TestConfigBasics(unittest.TestCase):
    """配置系统基础测试"""

    def test_imports(self):
        """测试所有导出符号均可正常导入"""
        from src.config import (
            GatewayModuleConfig,
            get_gateway_config,
            GatewaySettings,
            settings,
            ModuleRoute,
            build_default_routes,
        )
        self.assertIsNotNone(GatewayModuleConfig)
        self.assertIsNotNone(get_gateway_config)
        self.assertIsNotNone(GatewaySettings)
        self.assertIsNotNone(settings)
        self.assertIsNotNone(ModuleRoute)
        self.assertIsNotNone(build_default_routes)

    def test_unified_config_available(self):
        """测试统一配置框架是否可用"""
        from src.config import _USE_UNIFIED_CONFIG
        self.assertTrue(_USE_UNIFIED_CONFIG, "统一配置框架应该可用")


class TestGatewayModuleConfig(unittest.TestCase):
    """新配置 GatewayModuleConfig 测试"""

    def test_default_values(self):
        """测试新配置默认值"""
        from src.config import GatewayModuleConfig
        cfg = GatewayModuleConfig()

        self.assertEqual(cfg.module_name, "api-gateway")
        self.assertEqual(cfg.host, "0.0.0.0")
        self.assertEqual(cfg.port, 8080)
        self.assertEqual(cfg.log_level, "info")
        self.assertEqual(cfg.cors_origins, "*")
        self.assertEqual(cfg.api_key_header, "X-API-Key")
        self.assertEqual(cfg.jwt_header, "Authorization")
        self.assertEqual(cfg.rate_limit_per_minute, 600)
        self.assertEqual(cfg.rate_limit_per_ip, 100)
        self.assertEqual(cfg.circuit_breaker_threshold, 5)
        self.assertEqual(cfg.circuit_breaker_recovery_time, 30)

    def test_routes_count(self):
        """测试路由表包含12个模块"""
        from src.config import GatewayModuleConfig
        cfg = GatewayModuleConfig()
        self.assertEqual(len(cfg.routes), 12)

    def test_routes_modules(self):
        """测试所有12个模块都在路由表中"""
        from src.config import GatewayModuleConfig
        cfg = GatewayModuleConfig()
        expected_keys = [f"m{i}" for i in range(1, 13)]
        actual_keys = [r.key for r in cfg.routes]
        for key in expected_keys:
            self.assertIn(key, actual_keys, f"模块 {key} 应该在路由表中")

    def test_get_route(self):
        """测试 get_route 方法"""
        from src.config import GatewayModuleConfig
        cfg = GatewayModuleConfig()

        route = cfg.get_route("m1")
        self.assertIsNotNone(route)
        self.assertEqual(route.key, "m1")
        self.assertEqual(route.prefix, "/m1")

        # 不存在的路由返回 None
        self.assertIsNone(cfg.get_route("nonexistent"))

    def test_get_enabled_routes(self):
        """测试 get_enabled_routes 方法"""
        from src.config import GatewayModuleConfig
        cfg = GatewayModuleConfig()

        enabled = cfg.get_enabled_routes()
        # 默认所有路由都启用
        self.assertEqual(len(enabled), 12)

    def test_route_structure(self):
        """测试每个路由配置的结构完整性"""
        from src.config import GatewayModuleConfig
        cfg = GatewayModuleConfig()

        for route in cfg.routes:
            self.assertIsNotNone(route.key)
            self.assertIsNotNone(route.name)
            self.assertIsNotNone(route.target_url)
            self.assertIsNotNone(route.prefix)
            self.assertIsInstance(route.enabled, bool)
            self.assertIsInstance(route.timeout, float)
            self.assertIsInstance(route.health_path, str)
            self.assertIsInstance(route.health_timeout, float)
            self.assertIsInstance(route.auth_required, bool)
            self.assertIsInstance(route.public_paths, list)
            self.assertIsInstance(route.rate_limit_per_minute, int)
            self.assertIsInstance(route.rate_limit_per_ip, int)
            self.assertIsInstance(route.rate_limit_tier, str)
            self.assertIsInstance(route.supports_websocket, bool)
            self.assertIsInstance(route.supports_sse, bool)
            self.assertIsInstance(route.cb_failure_threshold, int)
            self.assertIsInstance(route.cb_recovery_time, int)

    def test_singleton(self):
        """测试 get_gateway_config 单例模式"""
        from src.config import get_gateway_config
        cfg1 = get_gateway_config()
        cfg2 = get_gateway_config()
        self.assertIs(cfg1, cfg2, "get_gateway_config 应该返回同一个实例")


class TestGatewaySettingsCompatibility(unittest.TestCase):
    """旧配置 GatewaySettings 兼容层测试"""

    def test_settings_singleton_exists(self):
        """测试 settings 单例存在且可访问"""
        from src.config import settings
        self.assertIsNotNone(settings)

    def test_settings_default_values(self):
        """测试兼容层默认值与新配置一致"""
        from src.config import settings, get_gateway_config
        cfg = get_gateway_config()

        self.assertEqual(settings.host, cfg.host)
        self.assertEqual(settings.port, cfg.port)
        self.assertEqual(settings.log_level, cfg.log_level)
        self.assertEqual(settings.env, cfg.env.value)
        self.assertEqual(settings.cors_origins, cfg.cors_origins)
        self.assertEqual(settings.api_key_header, cfg.api_key_header)
        self.assertEqual(settings.jwt_header, cfg.jwt_header)
        self.assertEqual(settings.rate_limit_per_minute, cfg.rate_limit_per_minute)
        self.assertEqual(settings.rate_limit_per_ip, cfg.rate_limit_per_ip)
        self.assertEqual(settings.circuit_breaker_threshold, cfg.circuit_breaker_threshold)
        self.assertEqual(
            settings.circuit_breaker_recovery_time,
            cfg.circuit_breaker_recovery_time
        )

    def test_settings_routes_consistency(self):
        """测试兼容层路由表与新配置一致"""
        from src.config import settings, get_gateway_config
        cfg = get_gateway_config()

        self.assertEqual(len(settings.routes), len(cfg.routes))
        for i in range(len(cfg.routes)):
            self.assertEqual(settings.routes[i].key, cfg.routes[i].key)
            self.assertEqual(settings.routes[i].name, cfg.routes[i].name)
            self.assertEqual(settings.routes[i].target_url, cfg.routes[i].target_url)
            self.assertEqual(settings.routes[i].prefix, cfg.routes[i].prefix)

    def test_settings_routes_same_objects(self):
        """测试兼容层路由表与新配置是同一份数据（引用相同）"""
        from src.config import settings, get_gateway_config
        cfg = get_gateway_config()

        # 路由表应该是同一份引用（指向同一个 list）
        self.assertIs(settings.routes, cfg.routes)

    def test_from_env_method(self):
        """测试 from_env() 类方法"""
        from src.config import GatewaySettings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            s = GatewaySettings.from_env()

            # 应该触发 DeprecationWarning
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            self.assertTrue(len(dep_warnings) > 0, "from_env() 应该触发 DeprecationWarning")

            self.assertIsNotNone(s)
            self.assertEqual(s.port, 8080)
            self.assertEqual(len(s.routes), 12)

    def test_direct_instantiation_warning(self):
        """测试直接实例化 GatewaySettings 触发警告"""
        from src.config import GatewaySettings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            s = GatewaySettings()

            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            self.assertTrue(
                len(dep_warnings) > 0,
                "直接实例化 GatewaySettings 应该触发 DeprecationWarning"
            )


class TestConfigSync(unittest.TestCase):
    """配置双向同步测试"""

    def test_write_old_syncs_to_new(self):
        """测试写入旧配置属性会同步到新配置"""
        from src.config import settings, get_gateway_config
        cfg = get_gateway_config()

        # 保存原值
        original_port = cfg.port

        try:
            # 修改旧配置
            settings.port = 9999
            # 新配置应该同步变化
            self.assertEqual(cfg.port, 9999)
        finally:
            # 恢复原值
            settings.port = original_port

    def test_write_new_syncs_to_old(self):
        """测试写入新配置属性会同步到旧配置"""
        from src.config import settings, get_gateway_config
        cfg = get_gateway_config()

        # 保存原值
        original_port = cfg.port

        try:
            # 修改新配置
            cfg.port = 7777
            # 旧配置应该同步变化（因为属性是 property，从新配置读取）
            self.assertEqual(settings.port, 7777)
        finally:
            # 恢复原值
            cfg.port = original_port

    def test_routes_write_sync(self):
        """测试路由表写入同步"""
        from src.config import settings, get_gateway_config, ModuleRoute
        cfg = get_gateway_config()

        # 保存原值
        original_routes = cfg.routes.copy()

        try:
            # 添加一个测试路由到旧配置
            test_route = ModuleRoute(
                key="test",
                name="Test Module",
                target_url="http://localhost:9999",
                prefix="/test",
            )
            settings.routes.append(test_route)

            # 新配置应该也能看到
            self.assertEqual(len(cfg.routes), len(original_routes) + 1)
            self.assertEqual(cfg.routes[-1].key, "test")
        finally:
            # 恢复
            cfg.routes = original_routes


class TestSingleSourceOfTruth(unittest.TestCase):
    """路由表单一真源测试"""

    def test_build_default_routes_is_same(self):
        """测试 build_default_routes() 返回的数据与配置中的一致"""
        from src.config import build_default_routes, get_gateway_config

        cfg = get_gateway_config()
        func_routes = build_default_routes()

        self.assertEqual(len(cfg.routes), len(func_routes))
        for i in range(len(func_routes)):
            # 结构和值应该相同
            self.assertEqual(cfg.routes[i].key, func_routes[i].key)
            self.assertEqual(cfg.routes[i].name, func_routes[i].name)
            self.assertEqual(cfg.routes[i].target_url, func_routes[i].target_url)

    def test_old_settings_routes_from_new_config(self):
        """测试旧配置路由表来自新配置（而不是自己重新构建）"""
        from src.config import settings, get_gateway_config

        cfg = get_gateway_config()
        # 旧配置的 routes 属性直接返回新配置的 routes
        self.assertIs(settings._unified, cfg)
        self.assertIs(settings.routes, cfg.routes)


class TestEnvVariables(unittest.TestCase):
    """环境变量加载测试"""

    def test_env_variable_override(self):
        """测试环境变量可以覆盖默认配置"""
        from src.config import GatewayModuleConfig

        # 保存原值
        original = os.environ.get("GATEWAY_PORT")

        try:
            os.environ["GATEWAY_PORT"] = "9090"
            # 创建新实例（非单例），验证环境变量覆盖
            cfg = GatewayModuleConfig()
            self.assertEqual(cfg.port, 9090)
        finally:
            # 恢复环境变量
            if original is not None:
                os.environ["GATEWAY_PORT"] = original
            elif "GATEWAY_PORT" in os.environ:
                del os.environ["GATEWAY_PORT"]

        # 恢复单例的端口值（不影响其他测试）
        from src.config import get_gateway_config
        get_gateway_config().port = 8080


class TestModuleRoute(unittest.TestCase):
    """ModuleRoute 模型测试"""

    def test_default_values(self):
        """测试 ModuleRoute 默认值"""
        from src.config import ModuleRoute

        route = ModuleRoute(
            key="test",
            name="Test",
            target_url="http://localhost:9000",
            prefix="/test",
        )

        self.assertTrue(route.enabled)
        self.assertEqual(route.timeout, 30.0)
        self.assertEqual(route.health_path, "/health")
        self.assertEqual(route.health_timeout, 5.0)
        self.assertTrue(route.auth_required)
        self.assertEqual(route.public_paths, [])
        self.assertEqual(route.rate_limit_per_minute, 60)
        self.assertEqual(route.rate_limit_per_ip, 30)
        self.assertEqual(route.rate_limit_tier, "public")
        self.assertFalse(route.supports_websocket)
        self.assertFalse(route.supports_sse)
        self.assertEqual(route.cb_failure_threshold, 5)
        self.assertEqual(route.cb_recovery_time, 30)
        self.assertEqual(route.description, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
