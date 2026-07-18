"""
API-Gateway 插件系统测试（CQ-008, P1级）

测试目标：
1. 插件基类和上下文
2. 插件管理器（注册、启用、禁用、注销）
3. 插件执行顺序（优先级）
4. 洋葱模型（pre_request 正序，post_response 倒序）
5. 日志增强插件
6. 指标采集插件
7. 请求 ID 插件
8. CORS 插件
9. 安全头插件
"""

import sys
import asyncio
import unittest
from pathlib import Path

# 将 API-Gateway 目录加入 path
_gateway_root = Path(__file__).resolve().parent.parent
if str(_gateway_root) not in sys.path:
class TestPluginBase(unittest.TestCase):
    """插件基类测试"""

    def setUp(self):
        from src.plugins.plugin_base import BasePlugin, PluginContext
        self.BasePlugin = BasePlugin
        self.PluginContext = PluginContext

    def test_plugin_defaults(self):
        """测试插件默认属性"""
        plugin = self.BasePlugin()
        self.assertEqual(plugin.name, "base_plugin")
        self.assertEqual(plugin.version, "1.0.0")
        self.assertTrue(plugin.enabled)
        self.assertEqual(plugin.priority, 100)

    def test_plugin_custom_name(self):
        """测试自定义插件名称"""
        plugin = self.BasePlugin(name="custom", priority=50, enabled=False)
        self.assertEqual(plugin.name, "custom")
        self.assertEqual(plugin.priority, 50)
        self.assertFalse(plugin.enabled)

    def test_pre_request_returns_ctx(self):
        """测试 pre_request 默认返回 ctx"""
        plugin = self.BasePlugin()
        ctx = self.PluginContext(request_path="/test")

        async def test():
            return await plugin.pre_request(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertIsNotNone(result)
        self.assertEqual(result.request_path, "/test")

    def test_post_response_returns_ctx(self):
        """测试 post_response 默认返回 ctx"""
        plugin = self.BasePlugin()
        ctx = self.PluginContext(response_status=200)

        async def test():
            return await plugin.post_response(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(result.response_status, 200)

    def test_on_error_returns_ctx(self):
        """测试 on_error 默认返回 ctx"""
        plugin = self.BasePlugin()
        ctx = self.PluginContext(error_message="test error")

        async def test():
            return await plugin.on_error(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(result.error_message, "test error")

    def test_get_stats(self):
        """测试获取插件统计"""
        plugin = self.BasePlugin(name="test-plugin")
        stats = plugin.get_stats()
        self.assertEqual(stats["name"], "test-plugin")
        self.assertIn("pre_request_calls", stats)
        self.assertIn("post_response_calls", stats)
        self.assertIn("on_error_calls", stats)

    def test_reset_stats(self):
        """测试重置统计"""
        plugin = self.BasePlugin()
        ctx = self.PluginContext()

        async def test():
            await plugin.pre_request(ctx)
            await plugin.post_response(ctx)

        asyncio.get_event_loop().run_until_complete(test())

        plugin.reset_stats()
        stats = plugin.get_stats()
        self.assertEqual(stats["pre_request_calls"], 0)
        self.assertEqual(stats["post_response_calls"], 0)

    def test_plugin_context_defaults(self):
        """测试插件上下文默认值"""
        ctx = self.PluginContext()
        self.assertEqual(ctx.request_method, "")
        self.assertEqual(ctx.request_path, "")
        self.assertEqual(ctx.response_status, 0)
        self.assertEqual(ctx.extra, {})

    def test_plugin_context_extra(self):
        """测试插件上下文 extra 字段"""
        ctx = self.PluginContext()
        ctx.extra["custom_key"] = "custom_value"
        self.assertEqual(ctx.extra["custom_key"], "custom_value")

    def test_plugin_repr(self):
        """测试插件字符串表示"""
        plugin = self.BasePlugin(name="my-plugin")
        repr_str = repr(plugin)
        self.assertIn("my-plugin", repr_str)


class TestPluginManager(unittest.TestCase):
    """插件管理器测试"""

    def setUp(self):
        from src.plugins.plugin_manager import PluginManager
        from src.plugins.plugin_base import BasePlugin, PluginContext
        self.PluginManager = PluginManager
        self.BasePlugin = BasePlugin
        self.PluginContext = PluginContext

    def test_register_plugin(self):
        """测试注册插件"""
        manager = self.PluginManager()
        plugin = self.BasePlugin(name="test-plugin")

        async def test():
            return await manager.register(plugin)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertTrue(result)
        self.assertTrue(manager.has_plugin("test-plugin"))

    def test_unregister_plugin(self):
        """测试注销插件"""
        manager = self.PluginManager()
        plugin = self.BasePlugin(name="test-plugin")

        async def test():
            await manager.register(plugin)
            return await manager.unregister("test-plugin")

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertTrue(result)
        self.assertFalse(manager.has_plugin("test-plugin"))

    def test_unregister_nonexistent(self):
        """测试注销不存在的插件"""
        manager = self.PluginManager()

        async def test():
            return await manager.unregister("nonexistent")

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertFalse(result)

    def test_enable_disable_plugin(self):
        """测试启用/禁用插件"""
        manager = self.PluginManager()
        plugin = self.BasePlugin(name="test-plugin", enabled=False)

        async def test():
            await manager.register(plugin)
            enabled = await manager.enable("test-plugin")
            disabled = await manager.disable("test-plugin")
            return enabled, disabled

        enabled, disabled = asyncio.get_event_loop().run_until_complete(test())
        self.assertTrue(enabled)
        self.assertTrue(disabled)

    def test_enable_nonexistent(self):
        """测试启用不存在的插件"""
        manager = self.PluginManager()

        async def test():
            return await manager.enable("nonexistent")

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertFalse(result)

    def test_get_plugin(self):
        """测试获取插件"""
        manager = self.PluginManager()
        plugin = self.BasePlugin(name="test-plugin")

        async def test():
            await manager.register(plugin)
            return manager.get_plugin("test-plugin")

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "test-plugin")

    def test_execute_pre_request(self):
        """测试执行 pre_request 钩子"""
        manager = self.PluginManager()

        call_order = []

        class TestPlugin(self.BasePlugin):
            def __init__(self, name, priority):
                super().__init__(name=name, priority=priority)

            async def pre_request(self, ctx):
                call_order.append(self.name)
                return ctx

        plugin1 = TestPlugin("first", 10)
        plugin2 = TestPlugin("second", 20)
        plugin3 = TestPlugin("third", 30)

        async def test():
            await manager.register(plugin1)
            await manager.register(plugin3)
            await manager.register(plugin2)
            ctx = self.PluginContext(request_path="/test")
            return await manager.execute_pre_request(ctx)

        asyncio.get_event_loop().run_until_complete(test())

        # 应该按优先级顺序执行
        self.assertEqual(call_order, ["first", "second", "third"])

    def test_execute_post_response_onion_model(self):
        """测试 post_response 洋葱模型（倒序执行）"""
        manager = self.PluginManager()

        call_order = []

        class TestPlugin(self.BasePlugin):
            def __init__(self, name, priority):
                super().__init__(name=name, priority=priority)

            async def post_response(self, ctx):
                call_order.append(self.name)
                return ctx

        plugin1 = TestPlugin("first", 10)
        plugin2 = TestPlugin("second", 20)
        plugin3 = TestPlugin("third", 30)

        async def test():
            await manager.register(plugin1)
            await manager.register(plugin2)
            await manager.register(plugin3)
            ctx = self.PluginContext(response_status=200)
            return await manager.execute_post_response(ctx)

        asyncio.get_event_loop().run_until_complete(test())

        # post_response 应该按优先级倒序执行（洋葱模型）
        self.assertEqual(call_order, ["third", "second", "first"])

    def test_disabled_plugin_not_executed(self):
        """测试禁用的插件不执行"""
        manager = self.PluginManager()

        executed = []

        class TestPlugin(self.BasePlugin):
            def __init__(self, name, enabled):
                super().__init__(name=name, enabled=enabled)

            async def pre_request(self, ctx):
                executed.append(self.name)
                return ctx

        plugin_enabled = TestPlugin("enabled", True)
        plugin_disabled = TestPlugin("disabled", False)

        async def test():
            await manager.register(plugin_enabled)
            await manager.register(plugin_disabled)
            ctx = self.PluginContext()
            return await manager.execute_pre_request(ctx)

        asyncio.get_event_loop().run_until_complete(test())

        self.assertEqual(executed, ["enabled"])

    def test_plugin_error_does_not_break(self):
        """测试插件错误不影响主流程"""
        manager = self.PluginManager()

        class BadPlugin(self.BasePlugin):
            def __init__(self):
                super().__init__(name="bad", priority=10)

            async def pre_request(self, ctx):
                raise ValueError("plugin error")

        class GoodPlugin(self.BasePlugin):
            def __init__(self):
                super().__init__(name="good", priority=20)

            async def pre_request(self, ctx):
                ctx.extra["good_executed"] = True
                return ctx

        async def test():
            await manager.register(BadPlugin())
            await manager.register(GoodPlugin())
            ctx = self.PluginContext()
            return await manager.execute_pre_request(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        # 好插件仍然应该执行
        self.assertTrue(result.extra.get("good_executed"))

    def test_list_plugins(self):
        """测试列出插件"""
        manager = self.PluginManager()

        async def test():
            await manager.register(self.BasePlugin(name="p1", priority=10))
            await manager.register(self.BasePlugin(name="p2", priority=20))
            return manager.list_plugins()

        plugins = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(len(plugins), 2)
        self.assertEqual(plugins[0]["name"], "p1")  # 按优先级排序

    def test_get_stats(self):
        """测试获取统计信息"""
        manager = self.PluginManager()

        async def test():
            await manager.register(self.BasePlugin(name="p1"))
            await manager.register(self.BasePlugin(name="p2"))
            return manager.get_stats()

        stats = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(stats["total_plugins"], 2)
        self.assertEqual(stats["enabled_plugins"], 2)
        self.assertIn("plugins", stats)

    def test_reset_all_stats(self):
        """测试重置所有插件统计"""
        manager = self.PluginManager()

        async def test():
            await manager.register(self.BasePlugin(name="p1"))
            ctx = self.PluginContext()
            await manager.execute_pre_request(ctx)
            manager.reset_all_stats()
            return manager.get_stats()

        stats = asyncio.get_event_loop().run_until_complete(test())
        # 重置后所有插件的调用次数应为 0
        for plugin_stats in stats["plugins"].values():
            self.assertEqual(plugin_stats["pre_request_calls"], 0)

    def test_execute_on_error(self):
        """测试执行 on_error 钩子"""
        manager = self.PluginManager()

        errors_handled = []

        class TestPlugin(self.BasePlugin):
            def __init__(self, name):
                super().__init__(name=name)

            async def on_error(self, ctx):
                errors_handled.append(self.name)
                return ctx

        async def test():
            await manager.register(TestPlugin("p1"))
            ctx = self.PluginContext(error_message="test error")
            return await manager.execute_on_error(ctx)

        asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(len(errors_handled), 1)


class TestRequestIdPlugin(unittest.TestCase):
    """请求 ID 插件测试"""

    def setUp(self):
        from src.plugins.builtin_plugins import RequestIdPlugin
        from src.plugins.plugin_base import PluginContext
        self.RequestIdPlugin = RequestIdPlugin
        self.PluginContext = PluginContext

    def test_generates_request_id(self):
        """测试生成请求 ID"""
        plugin = self.RequestIdPlugin()
        ctx = self.PluginContext(
            request_method="GET",
            request_path="/test",
            request_headers={},
        )

        async def test():
            return await plugin.pre_request(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertTrue(result.request_id)
        self.assertEqual(len(result.request_id), 32)  # UUID hex 长度

    def test_inherits_request_id(self):
        """测试从请求头继承请求 ID"""
        plugin = self.RequestIdPlugin(header_name="X-Request-Id")
        ctx = self.PluginContext(
            request_headers={"X-Request-Id": "existing-id-123"},
        )

        async def test():
            return await plugin.pre_request(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(result.request_id, "existing-id-123")

    def test_inherits_trace_id(self):
        """测试从 X-Trace-Id 继承"""
        plugin = self.RequestIdPlugin()
        ctx = self.PluginContext(
            request_headers={"X-Trace-Id": "trace-abc"},
        )

        async def test():
            return await plugin.pre_request(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(result.request_id, "trace-abc")

    def test_adds_to_response(self):
        """测试响应头中添加请求 ID"""
        plugin = self.RequestIdPlugin(header_name="X-Request-Id")
        ctx = self.PluginContext(
            request_id="test-id-123",
            response_headers={},
        )

        async def test():
            return await plugin.post_response(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(result.response_headers["X-Request-Id"], "test-id-123")
        self.assertEqual(result.response_headers["X-Trace-Id"], "test-id-123")

    def test_stats(self):
        """测试统计信息"""
        plugin = self.RequestIdPlugin()
        stats = plugin.get_stats()
        self.assertIn("generated_count", stats)
        self.assertIn("inherited_count", stats)


class TestCorsPlugin(unittest.TestCase):
    """CORS 插件测试"""

    def setUp(self):
        from src.plugins.builtin_plugins import CorsPlugin
        from src.plugins.plugin_base import PluginContext
        self.CorsPlugin = CorsPlugin
        self.PluginContext = PluginContext

    def test_adds_cors_headers(self):
        """测试添加 CORS 响应头"""
        plugin = self.CorsPlugin(allow_origins=["*"])
        ctx = self.PluginContext(
            request_headers={"Origin": "http://example.com"},
            response_headers={},
        )

        async def test():
            return await plugin.post_response(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertIn("Access-Control-Allow-Origin", result.response_headers)

    def test_preflight_request(self):
        """测试预检请求处理"""
        plugin = self.CorsPlugin(allow_origins=["http://example.com"])
        ctx = self.PluginContext(
            request_method="OPTIONS",
            request_headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )

        async def test():
            return await plugin.pre_request(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertTrue(result.extra.get("cors_preflight_handled"))

    def test_allow_specific_origin(self):
        """测试允许特定来源"""
        plugin = self.CorsPlugin(
            allow_origins=["http://example.com"],
            allow_credentials=True,
        )
        ctx = self.PluginContext(
            request_headers={"Origin": "http://example.com"},
            response_headers={},
        )

        async def test():
            return await plugin.post_response(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(
            result.response_headers["Access-Control-Allow-Origin"],
            "http://example.com",
        )
        self.assertEqual(
            result.response_headers["Access-Control-Allow-Credentials"],
            "true",
        )

    def test_origin_not_allowed(self):
        """测试不允许的来源"""
        plugin = self.CorsPlugin(allow_origins=["http://allowed.com"])
        ctx = self.PluginContext(
            request_headers={"Origin": "http://forbidden.com"},
            response_headers={},
        )

        async def test():
            return await plugin.post_response(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        # 不在允许列表中，不添加 CORS 头
        self.assertNotIn("Access-Control-Allow-Origin", result.response_headers)


class TestSecurityHeadersPlugin(unittest.TestCase):
    """安全头插件测试"""

    def setUp(self):
        from src.plugins.builtin_plugins import SecurityHeadersPlugin
        from src.plugins.plugin_base import PluginContext
        self.SecurityHeadersPlugin = SecurityHeadersPlugin
        self.PluginContext = PluginContext

    def test_adds_security_headers(self):
        """测试添加安全响应头"""
        plugin = self.SecurityHeadersPlugin(env="development")
        ctx = self.PluginContext(response_headers={})

        async def test():
            return await plugin.post_response(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertIn("X-Content-Type-Options", result.response_headers)
        self.assertEqual(result.response_headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("X-Frame-Options", result.response_headers)
        self.assertIn("Content-Security-Policy", result.response_headers)
        self.assertIn("Referrer-Policy", result.response_headers)
        self.assertIn("Permissions-Policy", result.response_headers)

    def test_hsts_in_production(self):
        """测试生产环境添加 HSTS"""
        plugin = self.SecurityHeadersPlugin(env="production")
        ctx = self.PluginContext(response_headers={})

        async def test():
            return await plugin.post_response(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertIn("Strict-Transport-Security", result.response_headers)

    def test_no_hsts_in_development(self):
        """测试开发环境不添加 HSTS"""
        plugin = self.SecurityHeadersPlugin(env="development")
        ctx = self.PluginContext(response_headers={})

        async def test():
            return await plugin.post_response(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertNotIn("Strict-Transport-Security", result.response_headers)

    def test_does_not_override_existing(self):
        """测试不覆盖已有的安全头"""
        plugin = self.SecurityHeadersPlugin(env="development")
        ctx = self.PluginContext(
            response_headers={"X-Frame-Options": "SAMEORIGIN"},
        )

        async def test():
            return await plugin.post_response(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        # 保持原有的值
        self.assertEqual(result.response_headers["X-Frame-Options"], "SAMEORIGIN")

    def test_custom_headers(self):
        """测试自定义头"""
        plugin = self.SecurityHeadersPlugin(
            env="development",
            custom_headers={"X-Custom-Security": "custom-value"},
        )
        ctx = self.PluginContext(response_headers={})

        async def test():
            return await plugin.post_response(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(result.response_headers["X-Custom-Security"], "custom-value")

    def test_stats(self):
        """测试统计信息"""
        plugin = self.SecurityHeadersPlugin()
        stats = plugin.get_stats()
        self.assertIn("headers_count", stats)


class TestMetricsPlugin(unittest.TestCase):
    """指标采集插件测试"""

    def setUp(self):
        from src.plugins.builtin_plugins import MetricsPlugin
        from src.plugins.plugin_base import PluginContext
        self.MetricsPlugin = MetricsPlugin
        self.PluginContext = PluginContext

    def test_records_request(self):
        """测试记录请求"""
        plugin = self.MetricsPlugin()
        ctx = self.PluginContext(
            request_method="GET",
            request_path="/test",
            route_key="m1",
            response_status=200,
            latency_ms=50.0,
        )

        async def test():
            await plugin.pre_request(ctx)
            return await plugin.post_response(ctx)

        asyncio.get_event_loop().run_until_complete(test())

        stats = plugin.get_stats()
        self.assertEqual(stats["total_requests"], 1)
        self.assertEqual(stats["method_counts"]["GET"], 1)

    def test_active_requests(self):
        """测试活跃请求数"""
        plugin = self.MetricsPlugin()
        ctx = self.PluginContext(
            request_method="GET",
            response_status=200,
        )

        async def test():
            await plugin.pre_request(ctx)
            stats = plugin.get_stats()
            active_before = stats["active_requests"]
            await plugin.post_response(ctx)
            stats = plugin.get_stats()
            active_after = stats["active_requests"]
            return active_before, active_after

        active_before, active_after = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(active_before, 1)
        self.assertEqual(active_after, 0)

    def test_error_counting(self):
        """测试错误计数"""
        plugin = self.MetricsPlugin()
        ctx = self.PluginContext(
            request_method="GET",
            response_status=500,
        )

        async def test():
            await plugin.pre_request(ctx)
            return await plugin.post_response(ctx)

        asyncio.get_event_loop().run_until_complete(test())

        stats = plugin.get_stats()
        self.assertEqual(stats["error_count"], 1)

    def test_latency_tracking(self):
        """测试延迟跟踪"""
        plugin = self.MetricsPlugin()
        ctx = self.PluginContext(
            request_method="GET",
            response_status=200,
            latency_ms=100.0,
        )

        async def test():
            await plugin.pre_request(ctx)
            return await plugin.post_response(ctx)

        asyncio.get_event_loop().run_until_complete(test())

        stats = plugin.get_stats()
        self.assertEqual(stats["avg_latency_ms"], 100.0)
        self.assertEqual(stats["max_latency_ms"], 100.0)
        self.assertEqual(stats["min_latency_ms"], 100.0)

    def test_prometheus_metrics(self):
        """测试 Prometheus 格式指标"""
        plugin = self.MetricsPlugin()
        ctx = self.PluginContext(
            request_method="GET",
            response_status=200,
            latency_ms=50.0,
        )

        async def test():
            await plugin.pre_request(ctx)
            await plugin.post_response(ctx)
            return plugin.get_prometheus_metrics()

        metrics = asyncio.get_event_loop().run_until_complete(test())
        self.assertIn("gateway_requests_total", metrics)
        self.assertIn("gateway_active_requests", metrics)
        self.assertIn("gateway_request_duration_seconds", metrics)


class TestLoggingPlugin(unittest.TestCase):
    """日志增强插件测试"""

    def setUp(self):
        from src.plugins.builtin_plugins import LoggingPlugin
        from src.plugins.plugin_base import PluginContext
        self.LoggingPlugin = LoggingPlugin
        self.PluginContext = PluginContext

    def test_pre_request_logs(self):
        """测试 pre_request 不报错"""
        plugin = self.LoggingPlugin()
        ctx = self.PluginContext(
            request_method="GET",
            request_path="/test",
            client_ip="127.0.0.1",
            request_id="test-id",
        )

        async def test():
            return await plugin.pre_request(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertIsNotNone(result)

    def test_post_response_logs(self):
        """测试 post_response 不报错"""
        plugin = self.LoggingPlugin()
        ctx = self.PluginContext(
            request_method="GET",
            request_path="/test",
            request_id="test-id",
            response_status=200,
            response_body=b"ok",
            latency_ms=50.0,
        )

        async def test():
            return await plugin.post_response(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertIsNotNone(result)

    def test_slow_request_detection(self):
        """测试慢请求检测"""
        plugin = self.LoggingPlugin(slow_request_threshold_ms=100)
        ctx = self.PluginContext(
            request_method="GET",
            request_path="/test",
            request_id="test-id",
            response_status=200,
            latency_ms=200.0,  # 超过阈值
        )

        async def test():
            return await plugin.post_response(ctx)

        asyncio.get_event_loop().run_until_complete(test())

        stats = plugin.get_stats()
        self.assertIn("slow_request_count", stats)

    def test_on_error_logs(self):
        """测试 on_error 不报错"""
        plugin = self.LoggingPlugin()
        ctx = self.PluginContext(
            request_method="GET",
            request_path="/test",
            request_id="test-id",
            error_message="test error",
        )

        async def test():
            return await plugin.on_error(ctx)

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
