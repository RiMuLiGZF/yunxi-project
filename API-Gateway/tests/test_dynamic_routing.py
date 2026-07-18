"""
动态路由配置与热加载测试

测试目标：
1. RouteConfig 模型验证
2. RouteConfigLoader 文件加载
3. RouteConfigLoader 配置校验
4. 路由匹配（最长前缀匹配）
5. 运行时增删改路由
6. 热加载（失败回滚）
7. RouterManager 初始化
8. 路由统计
9. 配置文件变更检测
10. M12 认证模式配置
11. 向后兼容（硬编码路由 fallback）
"""

import os
import sys
import time
import unittest
import tempfile
import json
from pathlib import Path

# 测试路径注入由 conftest.py 统一处理


class TestRouteConfigModel(unittest.TestCase):
    """RouteConfig 模型测试"""

    def test_route_config_default_values(self):
        """测试 RouteConfig 默认值"""
        from src.services.route_config_loader import RouteConfig

        route = RouteConfig(
            id="test-route",
            path="/test",
            url="http://localhost:9000",
        )

        self.assertEqual(route.id, "test-route")
        self.assertEqual(route.path, "/test")
        self.assertEqual(route.url, "http://localhost:9000")
        self.assertEqual(route.name, "")
        self.assertEqual(route.weight, 100)
        self.assertEqual(route.timeout, 30.0)
        self.assertEqual(route.retry, 2)
        self.assertTrue(route.strip_prefix)
        self.assertTrue(route.enabled)
        self.assertTrue(route.auth_required)
        self.assertEqual(route.health_path, "/health")
        self.assertEqual(route.health_timeout, 5.0)
        self.assertEqual(route.public_paths, [])
        self.assertFalse(route.supports_websocket)
        self.assertFalse(route.supports_sse)
        self.assertEqual(route.plugins, [])

    def test_route_config_path_validation(self):
        """测试路径验证（必须以 / 开头）"""
        from src.services.route_config_loader import RouteConfig
        from pydantic import ValidationError

        # 正常路径
        route = RouteConfig(id="test", path="/api", url="http://localhost:9000")
        self.assertEqual(route.path, "/api")

        # 无效路径
        with self.assertRaises(ValidationError):
            RouteConfig(id="test", path="invalid", url="http://localhost:9000")

    def test_route_config_weight_validation(self):
        """测试权重验证（0-100）"""
        from src.services.route_config_loader import RouteConfig
        from pydantic import ValidationError

        # 正常权重
        route = RouteConfig(id="test", path="/api", url="http://localhost:9000", weight=50)
        self.assertEqual(route.weight, 50)

        # 超出范围
        with self.assertRaises(ValidationError):
            RouteConfig(id="test", path="/api", url="http://localhost:9000", weight=101)

        with self.assertRaises(ValidationError):
            RouteConfig(id="test", path="/api", url="http://localhost:9000", weight=-1)

    def test_route_config_timeout_validation(self):
        """测试超时验证（必须为正）"""
        from src.services.route_config_loader import RouteConfig
        from pydantic import ValidationError

        # 正常超时
        route = RouteConfig(id="test", path="/api", url="http://localhost:9000", timeout=60.0)
        self.assertEqual(route.timeout, 60.0)

        # 无效超时
        with self.assertRaises(ValidationError):
            RouteConfig(id="test", path="/api", url="http://localhost:9000", timeout=0)

        with self.assertRaises(ValidationError):
            RouteConfig(id="test", path="/api", url="http://localhost:9000", timeout=-1.0)

    def test_route_config_nested_models(self):
        """测试嵌套配置模型（rate_limit, circuit_breaker）"""
        from src.services.route_config_loader import RouteConfig, RateLimitConfig, CircuitBreakerConfig

        route = RouteConfig(
            id="test",
            path="/api",
            url="http://localhost:9000",
            rate_limit={"per_minute": 120, "per_ip": 60, "tier": "admin"},
            circuit_breaker={"failure_threshold": 10, "recovery_time": 15},
        )

        self.assertIsInstance(route.rate_limit, RateLimitConfig)
        self.assertEqual(route.rate_limit.per_minute, 120)
        self.assertEqual(route.rate_limit.per_ip, 60)
        self.assertEqual(route.rate_limit.tier, "admin")

        self.assertIsInstance(route.circuit_breaker, CircuitBreakerConfig)
        self.assertEqual(route.circuit_breaker.failure_threshold, 10)
        self.assertEqual(route.circuit_breaker.recovery_time, 15)


class TestRouteConfigLoader(unittest.TestCase):
    """RouteConfigLoader 测试"""

    def setUp(self):
        """每个测试前创建临时配置文件"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, "routes.yaml")
        self._write_sample_config()

    def tearDown(self):
        """每个测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_sample_config(self):
        """写入示例配置"""
        content = """
version: "1.0.0"
defaults:
  timeout: 30.0

routes:
  - id: m1
    name: "M1 Service"
    path: /m1
    target: m1-service
    url: "http://localhost:8001"
    weight: 100
    timeout: 60.0
    enabled: true
    auth_required: true

  - id: m2
    name: "M2 Service"
    path: /m2
    target: m2-service
    url: "http://localhost:8002"
    weight: 100
    enabled: true
    auth_required: false

  - id: m3
    name: "M3 Service"
    path: /m3/api
    target: m3-service
    url: "http://localhost:8003"
    enabled: false
"""
        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write(content)

    def test_load_from_yaml_file(self):
        """测试从 YAML 文件加载配置"""
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader(config_path=self.config_file)
        success = loader.load_from_file()

        self.assertTrue(success)
        self.assertEqual(len(loader.get_all_routes()), 3)

        # 验证各路由
        routes = loader.get_all_routes()
        route_ids = [r.id for r in routes]
        self.assertIn("m1", route_ids)
        self.assertIn("m2", route_ids)
        self.assertIn("m3", route_ids)

    def test_load_from_file_nonexistent(self):
        """测试加载不存在的文件"""
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader(config_path="/nonexistent/routes.yaml")
        success = loader.load_from_file()

        self.assertFalse(success)
        self.assertEqual(len(loader.get_all_routes()), 0)

    def test_load_from_dict(self):
        """测试从字典加载配置"""
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader()
        data = {
            "version": "1.0.0",
            "routes": [
                {
                    "id": "test1",
                    "path": "/test1",
                    "url": "http://localhost:9001",
                },
                {
                    "id": "test2",
                    "path": "/test2",
                    "url": "http://localhost:9002",
                },
            ],
        }

        success = loader.load_from_dict(data)
        self.assertTrue(success)
        self.assertEqual(len(loader.get_all_routes()), 2)

    def test_get_routes_only_enabled(self):
        """测试 get_routes() 只返回启用的路由"""
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader(config_path=self.config_file)
        loader.load_from_file()

        enabled_routes = loader.get_routes()
        all_routes = loader.get_all_routes()

        self.assertEqual(len(all_routes), 3)
        self.assertEqual(len(enabled_routes), 2)  # m3 是 disabled

        # 验证 m3 不在启用列表中
        enabled_ids = [r.id for r in enabled_routes]
        self.assertNotIn("m3", enabled_ids)

    def test_get_route_by_id(self):
        """测试根据 ID 获取路由"""
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader(config_path=self.config_file)
        loader.load_from_file()

        route = loader.get_route("m1")
        self.assertIsNotNone(route)
        self.assertEqual(route.id, "m1")
        self.assertEqual(route.name, "M1 Service")

        # 不存在的路由
        self.assertIsNone(loader.get_route("nonexistent"))

    def test_validate_duplicate_ids(self):
        """测试校验：重复 ID"""
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader()
        data = {
            "routes": [
                {"id": "dup", "path": "/a", "url": "http://localhost:9001"},
                {"id": "dup", "path": "/b", "url": "http://localhost:9002"},
            ],
        }

        success = loader.load_from_dict(data)
        self.assertFalse(success)
        self.assertIn("Duplicate route id", loader.get_stats().get("last_error", ""))

    def test_validate_invalid_url(self):
        """测试校验：无效 URL"""
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader()
        data = {
            "routes": [
                {"id": "test", "path": "/test", "url": "ftp://localhost:9000"},
            ],
        }

        success = loader.load_from_dict(data)
        self.assertFalse(success)
        self.assertIn("invalid url scheme", loader.get_stats().get("last_error", ""))


class TestRouteMatching(unittest.TestCase):
    """路由匹配测试"""

    def setUp(self):
        """设置测试路由"""
        from src.services.route_config_loader import RouteConfigLoader

        self.loader = RouteConfigLoader()
        data = {
            "routes": [
                {"id": "api", "path": "/api", "url": "http://localhost:9001"},
                {"id": "api-v2", "path": "/api/v2", "url": "http://localhost:9002"},
                {"id": "api-v2-users", "path": "/api/v2/users", "url": "http://localhost:9003"},
                {"id": "admin", "path": "/admin", "url": "http://localhost:9004"},
                {"id": "disabled", "path": "/disabled", "url": "http://localhost:9005", "enabled": False},
            ],
        }
        self.loader.load_from_dict(data)

    def test_longest_prefix_match(self):
        """测试最长前缀匹配"""
        # 应该匹配最长的前缀
        route = self.loader.match_route("/api/v2/users/123")
        self.assertIsNotNone(route)
        self.assertEqual(route.id, "api-v2-users")

        route = self.loader.match_route("/api/v2/other")
        self.assertIsNotNone(route)
        self.assertEqual(route.id, "api-v2")

        route = self.loader.match_route("/api/v1/test")
        self.assertIsNotNone(route)
        self.assertEqual(route.id, "api")

    def test_exact_path_match(self):
        """测试精确路径匹配"""
        route = self.loader.match_route("/api")
        self.assertIsNotNone(route)
        self.assertEqual(route.id, "api")

        route = self.loader.match_route("/admin")
        self.assertIsNotNone(route)
        self.assertEqual(route.id, "admin")

    def test_disabled_route_not_matched(self):
        """测试禁用的路由不匹配"""
        route = self.loader.match_route("/disabled/test")
        self.assertIsNone(route)

    def test_no_match(self):
        """测试无匹配路径"""
        route = self.loader.match_route("/nonexistent/path")
        self.assertIsNone(route)

    def test_method_filtering(self):
        """测试 HTTP 方法过滤"""
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader()
        data = {
            "routes": [
                {
                    "id": "get-only",
                    "path": "/read-only",
                    "url": "http://localhost:9000",
                    "methods": ["GET"],
                },
            ],
        }
        loader.load_from_dict(data)

        # GET 应该匹配
        route = loader.match_route("/read-only/data", method="GET")
        self.assertIsNotNone(route)

        # POST 不应该匹配
        route = loader.match_route("/read-only/data", method="POST")
        self.assertIsNone(route)


class TestRuntimeRouteModification(unittest.TestCase):
    """运行时路由增删改测试"""

    def setUp(self):
        """设置初始路由"""
        from src.services.route_config_loader import RouteConfigLoader

        self.loader = RouteConfigLoader()
        data = {
            "routes": [
                {"id": "m1", "path": "/m1", "url": "http://localhost:8001"},
                {"id": "m2", "path": "/m2", "url": "http://localhost:8002"},
            ],
        }
        self.loader.load_from_dict(data)

    def test_add_route(self):
        """测试添加路由"""
        from src.services.route_config_loader import RouteConfig

        self.assertEqual(len(self.loader.get_all_routes()), 2)

        new_route = RouteConfig(
            id="m3",
            path="/m3",
            url="http://localhost:8003",
        )

        success = self.loader.add_route(new_route)
        self.assertTrue(success)
        self.assertEqual(len(self.loader.get_all_routes()), 3)
        self.assertIsNotNone(self.loader.get_route("m3"))

    def test_add_duplicate_route(self):
        """测试添加重复路由"""
        from src.services.route_config_loader import RouteConfig

        new_route = RouteConfig(
            id="m1",  # 已存在
            path="/m1-new",
            url="http://localhost:9999",
        )

        success = self.loader.add_route(new_route)
        self.assertFalse(success)
        self.assertEqual(len(self.loader.get_all_routes()), 2)

    def test_update_route(self):
        """测试更新路由"""
        route = self.loader.get_route("m1")
        self.assertEqual(route.url, "http://localhost:8001")

        success = self.loader.update_route("m1", {"url": "http://localhost:9999"})
        self.assertTrue(success)

        updated = self.loader.get_route("m1")
        self.assertEqual(updated.url, "http://localhost:9999")

    def test_update_nonexistent_route(self):
        """测试更新不存在的路由"""
        success = self.loader.update_route("nonexistent", {"url": "http://localhost:9999"})
        self.assertFalse(success)

    def test_delete_route(self):
        """测试删除路由"""
        self.assertEqual(len(self.loader.get_all_routes()), 2)

        success = self.loader.delete_route("m1")
        self.assertTrue(success)
        self.assertEqual(len(self.loader.get_all_routes()), 1)
        self.assertIsNone(self.loader.get_route("m1"))

    def test_delete_nonexistent_route(self):
        """测试删除不存在的路由"""
        success = self.loader.delete_route("nonexistent")
        self.assertFalse(success)
        self.assertEqual(len(self.loader.get_all_routes()), 2)


class TestHotReload(unittest.TestCase):
    """热加载测试"""

    def setUp(self):
        """每个测试前创建临时配置文件"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, "routes.yaml")
        self._write_config_v1()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_config_v1(self):
        content = """
version: "1.0.0"
routes:
  - id: m1
    name: "M1 v1"
    path: /m1
    url: "http://localhost:8001"
    weight: 100
"""
        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write(content)

    def _write_config_v2(self):
        content = """
version: "2.0.0"
routes:
  - id: m1
    name: "M1 v2"
    path: /m1
    url: "http://localhost:9001"
    weight: 100

  - id: m2
    name: "M2 v2"
    path: /m2
    url: "http://localhost:9002"
    weight: 100
"""
        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write(content)

    def _write_invalid_config(self):
        content = """
version: "bad"
routes:
  - id: bad-route
    path: missing-slash
    url: "http://localhost:9000"
"""
        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write(content)

    def test_reload_success(self):
        """测试成功热加载"""
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader(config_path=self.config_file)
        loader.load_from_file()

        self.assertEqual(len(loader.get_all_routes()), 1)
        self.assertEqual(loader.get_route("m1").name, "M1 v1")

        # 修改配置文件
        self._write_config_v2()
        # 确保修改时间不同
        time.sleep(0.1)

        # 重新加载
        success = loader.reload()
        self.assertTrue(success)
        self.assertEqual(len(loader.get_all_routes()), 2)
        self.assertEqual(loader.get_route("m1").name, "M1 v2")
        self.assertIsNotNone(loader.get_route("m2"))

    def test_reload_fallback_on_failure(self):
        """测试热加载失败时保留旧配置"""
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader(config_path=self.config_file)
        loader.load_from_file()

        old_routes = loader.get_all_routes()
        self.assertEqual(len(old_routes), 1)

        # 写入无效配置
        self._write_invalid_config()
        time.sleep(0.1)

        # 重新加载应该失败，但保留旧配置
        success = loader.reload()
        self.assertFalse(success)

        # 旧配置应该还在
        current_routes = loader.get_all_routes()
        self.assertEqual(len(current_routes), 1)
        self.assertEqual(current_routes[0].id, "m1")

    def test_check_for_changes(self):
        """测试文件变更检测"""
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader(config_path=self.config_file)
        loader.load_from_file()

        # 刚加载完，应该没有变更
        self.assertFalse(loader.check_for_changes())

        # 修改文件
        time.sleep(0.1)
        self._write_config_v2()

        # 应该检测到变更
        self.assertTrue(loader.check_for_changes())


class TestRouterManager(unittest.TestCase):
    """RouterManager 测试"""

    def test_initialization_with_config_file(self):
        """测试使用配置文件初始化"""
        from src.services.router_manager import RouterManager
        from src.services.route_config_loader import RouteConfigLoader

        # 创建临时配置文件
        temp_dir = tempfile.mkdtemp()
        config_file = os.path.join(temp_dir, "routes.yaml")
        content = """
routes:
  - id: test1
    path: /test1
    url: "http://localhost:9001"
  - id: test2
    path: /test2
    url: "http://localhost:9002"
"""
        with open(config_file, "w", encoding="utf-8") as f:
            f.write(content)

        try:
            loader = RouteConfigLoader(config_path=config_file)
            manager = RouterManager(config_loader=loader, auto_reload=False)
            manager.initialize()

            self.assertEqual(len(manager.get_all_routes()), 2)
            self.assertIsNotNone(manager.get_route("test1"))
            self.assertIsNotNone(manager.get_route("test2"))
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_route_matching(self):
        """测试路由管理器的路由匹配"""
        from src.services.router_manager import RouterManager
        from src.services.route_config_loader import RouteConfigLoader, RouteConfig

        loader = RouteConfigLoader()
        manager = RouterManager(config_loader=loader, auto_reload=False)

        # 手动添加路由
        loader.add_route(RouteConfig(id="api", path="/api", url="http://localhost:9000"))
        loader.add_route(RouteConfig(id="api-v2", path="/api/v2", url="http://localhost:9001"))

        route = manager.match_route("/api/v2/test")
        self.assertIsNotNone(route)
        self.assertEqual(route.id, "api-v2")

    def test_route_stats(self):
        """测试路由统计"""
        from src.services.router_manager import RouterManager
        from src.services.route_config_loader import RouteConfigLoader, RouteConfig

        loader = RouteConfigLoader()
        manager = RouterManager(config_loader=loader, auto_reload=False)
        loader.add_route(RouteConfig(id="test", path="/test", url="http://localhost:9000"))

        # 记录命中
        manager.record_hit("test", 50.0, True)
        manager.record_hit("test", 100.0, True)
        manager.record_hit("test", 200.0, False)

        stats = manager.get_route_stats("test")
        self.assertIsNotNone(stats)
        self.assertEqual(stats["total_hits"], 3)
        self.assertEqual(stats["success_hits"], 2)
        self.assertEqual(stats["failed_hits"], 1)
        self.assertEqual(stats["avg_latency_ms"], round(350.0 / 3, 2))

    def test_reload_callback(self):
        """测试重新加载回调"""
        from src.services.router_manager import RouterManager
        from src.services.route_config_loader import RouteConfigLoader

        temp_dir = tempfile.mkdtemp()
        config_file = os.path.join(temp_dir, "routes.yaml")

        # 写初始配置
        with open(config_file, "w", encoding="utf-8") as f:
            f.write('routes:\n  - id: m1\n    path: /m1\n    url: "http://localhost:8001"\n')

        try:
            loader = RouteConfigLoader(config_path=config_file)
            manager = RouterManager(config_loader=loader, auto_reload=False)
            manager.initialize()

            # 注册回调
            callback_results = []

            def on_reload(success):
                callback_results.append(success)

            manager.register_reload_callback(on_reload)

            # 修改配置
            with open(config_file, "w", encoding="utf-8") as f:
                f.write('routes:\n  - id: m1\n    path: /m1\n    url: "http://localhost:9999"\n')

            time.sleep(0.1)
            manager.reload_config()

            self.assertEqual(len(callback_results), 1)
            self.assertTrue(callback_results[0])
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestConfigOptions(unittest.TestCase):
    """配置项测试"""

    def test_auth_mode_config(self):
        """测试 auth_mode 配置项"""
        from src.config import get_gateway_config

        cfg = get_gateway_config()
        self.assertTrue(hasattr(cfg, "auth_mode"))
        self.assertIn(cfg.auth_mode, ("local", "m12"))

    def test_m12_url_config(self):
        """测试 m12_url 配置项"""
        from src.config import get_gateway_config

        cfg = get_gateway_config()
        self.assertTrue(hasattr(cfg, "m12_url"))
        self.assertTrue(cfg.m12_url.startswith("http"))

    def test_m12_verify_endpoint_config(self):
        """测试 m12_verify_endpoint 配置项"""
        from src.config import get_gateway_config

        cfg = get_gateway_config()
        self.assertTrue(hasattr(cfg, "m12_verify_endpoint"))
        self.assertTrue(cfg.m12_verify_endpoint.startswith("/"))

    def test_route_config_file_config(self):
        """测试 route_config_file 配置项"""
        from src.config import get_gateway_config

        cfg = get_gateway_config()
        self.assertTrue(hasattr(cfg, "route_config_file"))

    def test_route_auto_reload_config(self):
        """测试 route_auto_reload 配置项"""
        from src.config import get_gateway_config

        cfg = get_gateway_config()
        self.assertTrue(hasattr(cfg, "route_auto_reload"))
        self.assertIsInstance(cfg.route_auto_reload, bool)

    def test_settings_compatibility(self):
        """测试 GatewaySettings 兼容层的新配置项"""
        from src.config import settings

        self.assertTrue(hasattr(settings, "auth_mode"))
        self.assertTrue(hasattr(settings, "m12_url"))
        self.assertTrue(hasattr(settings, "m12_verify_endpoint"))
        self.assertTrue(hasattr(settings, "m12_auth_cache_ttl"))
        self.assertTrue(hasattr(settings, "route_config_file"))
        self.assertTrue(hasattr(settings, "route_auto_reload"))
        self.assertTrue(hasattr(settings, "route_reload_interval"))


class TestBackwardCompatibility(unittest.TestCase):
    """向后兼容测试"""

    def test_hardcoded_routes_fallback(self):
        """测试配置文件不存在时回退到硬编码路由"""
        from src.services.router_manager import RouterManager
        from src.services.route_config_loader import RouteConfigLoader

        loader = RouteConfigLoader(config_path="/nonexistent/routes.yaml")
        manager = RouterManager(config_loader=loader, auto_reload=False)
        manager.initialize()

        # 应该加载了硬编码的默认路由（12个模块）
        routes = manager.get_all_routes()
        self.assertGreater(len(routes), 0)

        # 验证有 m1 到 m12 的路由
        route_ids = [r.id for r in routes]
        for i in range(1, 13):
            self.assertIn(f"m{i}", route_ids, f"Module m{i} should be in fallback routes")

    def test_old_settings_routes_still_work(self):
        """测试旧的 settings.routes 方式仍然可用"""
        from src.config import settings

        routes = settings.routes
        self.assertIsNotNone(routes)
        self.assertEqual(len(routes), 12)

    def test_module_route_structure(self):
        """测试 ModuleRoute 结构仍然完整"""
        from src.config import ModuleRoute

        route = ModuleRoute(
            key="test",
            name="Test",
            target_url="http://localhost:9000",
            prefix="/test",
        )

        self.assertEqual(route.key, "test")
        self.assertEqual(route.target_url, "http://localhost:9000")
        self.assertEqual(route.prefix, "/test")
        self.assertTrue(route.enabled)
        self.assertTrue(route.auth_required)


class TestLoadFromJson(unittest.TestCase):
    """JSON 格式配置文件测试"""

    def test_load_from_json_file(self):
        """测试从 JSON 文件加载配置"""
        from src.services.route_config_loader import RouteConfigLoader

        temp_dir = tempfile.mkdtemp()
        config_file = os.path.join(temp_dir, "routes.json")

        data = {
            "version": "1.0.0",
            "routes": [
                {"id": "json-test", "path": "/json-test", "url": "http://localhost:9000"},
            ],
        }

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        try:
            loader = RouteConfigLoader(config_path=config_file)
            success = loader.load_from_file()

            self.assertTrue(success)
            self.assertEqual(len(loader.get_all_routes()), 1)
            self.assertEqual(loader.get_route("json-test").id, "json-test")
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
