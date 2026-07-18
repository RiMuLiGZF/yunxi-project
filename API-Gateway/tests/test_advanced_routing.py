"""
API-Gateway 高级路由测试（CQ-008, P1级）

测试目标：
1. 权重路由 - 按权重分配流量
2. 一致性哈希路由 - 同一用户始终打到同一后端
3. 灰度发布场景 - 新旧版本流量分配
4. 路径重写 - 正则表达式
5. 路径重写 - 前缀剥离
6. 路径重写 - 添加前缀
7. 请求头转换 - add/set/remove/append
8. 响应头转换
9. 条件头操作
"""

import sys
import unittest
from pathlib import Path

# 将 API-Gateway 目录加入 path
_gateway_root = Path(__file__).resolve().parent.parent
if str(_gateway_root) not in sys.path:
class TestWeightedRouter(unittest.TestCase):
    """权重路由器测试"""

    def setUp(self):
        from src.routing.weighted_router import WeightedRouter, RouteTarget
        self.WeightedRouter = WeightedRouter
        self.RouteTarget = RouteTarget

    def test_initial_no_targets(self):
        """测试初始无目标时返回 None"""
        router = self.WeightedRouter()
        self.assertIsNone(router.select_target())

    def test_single_target(self):
        """测试单个目标始终返回该目标"""
        target = self.RouteTarget(url="http://backend1:8080", weight=100, name="v1")
        router = self.WeightedRouter([target])
        result = router.select_target()
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "v1")
        self.assertEqual(result.url, "http://backend1:8080")

    def test_weight_distribution_two_targets(self):
        """测试两个目标的权重分布（统计意义上）"""
        targets = [
            self.RouteTarget(url="http://v1:8080", weight=90, name="v1"),
            self.RouteTarget(url="http://v2:8080", weight=10, name="v2"),
        ]
        router = self.WeightedRouter(targets)

        v1_count = 0
        v2_count = 0
        total = 1000

        for _ in range(total):
            target = router.select_target()
            if target.name == "v1":
                v1_count += 1
            elif target.name == "v2":
                v2_count += 1

        # 检查大致比例（允许 15% 误差）
        v1_ratio = v1_count / total
        v2_ratio = v2_count / total
        self.assertAlmostEqual(v1_ratio, 0.9, delta=0.15)
        self.assertAlmostEqual(v2_ratio, 0.1, delta=0.15)
        self.assertEqual(v1_count + v2_count, total)

    def test_canary_release_scenario(self):
        """测试灰度发布场景：新版本 10%，旧版本 90%"""
        targets = [
            self.RouteTarget(url="http://old:8080", weight=90, name="stable"),
            self.RouteTarget(url="http://new:8080", weight=10, name="canary"),
        ]
        router = self.WeightedRouter(targets)
        stats = router.get_stats()
        self.assertEqual(stats["total_targets"], 2)
        self.assertEqual(stats["healthy_targets"], 2)

    def test_consistent_hash_same_user(self):
        """测试一致性哈希：同一用户始终打到同一后端"""
        targets = [
            self.RouteTarget(url="http://v1:8080", weight=50, name="v1"),
            self.RouteTarget(url="http://v2:8080", weight=50, name="v2"),
            self.RouteTarget(url="http://v3:8080", weight=50, name="v3"),
        ]
        router = self.WeightedRouter(targets)

        user_id = "user_12345"
        first_result = router.select_target(user_id=user_id)
        self.assertIsNotNone(first_result)

        # 多次调用同一用户，结果应该一致
        for _ in range(100):
            result = router.select_target(user_id=user_id)
            self.assertEqual(result.name, first_result.name)

    def test_consistent_hash_different_users(self):
        """测试一致性哈希：不同用户可能分布到不同后端"""
        targets = [
            self.RouteTarget(url="http://v1:8080", weight=50, name="v1"),
            self.RouteTarget(url="http://v2:8080", weight=50, name="v2"),
        ]
        router = self.WeightedRouter(targets)

        # 多个用户应该分布到不同后端
        backend_users = {}
        for i in range(100):
            user_id = f"user_{i}"
            result = router.select_target(user_id=user_id)
            backend_users.setdefault(result.name, []).append(user_id)

        # 至少两个后端都有用户
        self.assertGreaterEqual(len(backend_users), 1)

    def test_unhealthy_target_skipped(self):
        """测试不健康的目标会被跳过"""
        targets = [
            self.RouteTarget(url="http://v1:8080", weight=50, name="v1", healthy=False),
            self.RouteTarget(url="http://v2:8080", weight=50, name="v2", healthy=True),
        ]
        router = self.WeightedRouter(targets)

        for _ in range(100):
            result = router.select_target()
            self.assertEqual(result.name, "v2")

    def test_add_target(self):
        """测试添加目标"""
        router = self.WeightedRouter()
        target = self.RouteTarget(url="http://v1:8080", weight=100, name="v1")
        router.add_target(target)

        result = router.select_target()
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "v1")

    def test_remove_target(self):
        """测试移除目标"""
        targets = [
            self.RouteTarget(url="http://v1:8080", weight=50, name="v1"),
            self.RouteTarget(url="http://v2:8080", weight=50, name="v2"),
        ]
        router = self.WeightedRouter(targets)

        success = router.remove_target("v1")
        self.assertTrue(success)

        for _ in range(100):
            result = router.select_target()
            self.assertEqual(result.name, "v2")

    def test_remove_nonexistent_target(self):
        """测试移除不存在的目标返回 False"""
        router = self.WeightedRouter()
        self.assertFalse(router.remove_target("nonexistent"))

    def test_update_target_health(self):
        """测试更新目标健康状态"""
        targets = [
            self.RouteTarget(url="http://v1:8080", weight=100, name="v1"),
        ]
        router = self.WeightedRouter(targets)

        router.update_target_health("v1", False)
        result = router.select_target()
        self.assertIsNone(result)

        router.update_target_health("v1", True)
        result = router.select_target()
        self.assertIsNotNone(result)

    def test_validate_with_targets(self):
        """测试有效配置验证"""
        targets = [
            self.RouteTarget(url="http://v1:8080", weight=50, name="v1"),
        ]
        router = self.WeightedRouter(targets)
        self.assertTrue(router.validate())

    def test_validate_empty(self):
        """测试空配置验证失败"""
        router = self.WeightedRouter()
        self.assertFalse(router.validate())

    def test_get_stats(self):
        """测试获取统计信息"""
        targets = [
            self.RouteTarget(url="http://v1:8080", weight=90, name="v1"),
            self.RouteTarget(url="http://v2:8080", weight=10, name="v2"),
        ]
        router = self.WeightedRouter(targets)
        stats = router.get_stats()
        self.assertEqual(stats["total_targets"], 2)
        self.assertEqual(stats["healthy_targets"], 2)
        self.assertEqual(len(stats["targets"]), 2)
        # 权重百分比之和应该接近 100
        total_pct = sum(t["weight_percent"] for t in stats["targets"])
        self.assertAlmostEqual(total_pct, 100, delta=1)

    def test_set_targets(self):
        """测试设置目标列表"""
        router = self.WeightedRouter()
        targets = [
            self.RouteTarget(url="http://v1:8080", weight=100, name="v1"),
        ]
        router.set_targets(targets)
        result = router.select_target()
        self.assertEqual(result.name, "v1")

    def test_get_targets(self):
        """测试获取目标列表"""
        targets = [
            self.RouteTarget(url="http://v1:8080", weight=50, name="v1"),
        ]
        router = self.WeightedRouter(targets)
        target_list = router.get_targets()
        self.assertEqual(len(target_list), 1)
        self.assertEqual(target_list[0]["name"], "v1")


class TestPathRewriter(unittest.TestCase):
    """路径重写器测试"""

    def setUp(self):
        from src.routing.path_rewriter import PathRewriter, RewriteRule
        self.PathRewriter = PathRewriter
        self.RewriteRule = RewriteRule

    def test_no_rules_passthrough(self):
        """测试无规则时路径不变"""
        rewriter = self.PathRewriter()
        result = rewriter.rewrite("/api/v1/users")
        self.assertEqual(result, "/api/v1/users")

    def test_regex_rewrite_simple(self):
        """测试简单正则重写"""
        rule = self.RewriteRule(
            pattern=r"/old/(.*)",
            replacement=r"/new/\1",
            type="regex",
        )
        rewriter = self.PathRewriter([rule])
        result = rewriter.rewrite("/old/api/users")
        self.assertEqual(result, "/new/api/users")

    def test_regex_rewrite_no_match(self):
        """测试正则不匹配时路径不变"""
        rule = self.RewriteRule(
            pattern=r"/old/(.*)",
            replacement=r"/new/\1",
            type="regex",
        )
        rewriter = self.PathRewriter([rule])
        result = rewriter.rewrite("/other/path")
        self.assertEqual(result, "/other/path")

    def test_regex_multiple_groups(self):
        """测试多分组正则重写"""
        rule = self.RewriteRule(
            pattern=r"/api/v(\d+)/(.+)",
            replacement=r"/v\1/api/\2",
            type="regex",
        )
        rewriter = self.PathRewriter([rule])
        result = rewriter.rewrite("/api/v2/users/123")
        self.assertEqual(result, "/v2/api/users/123")

    def test_strip_prefix(self):
        """测试前缀剥离"""
        rule = self.RewriteRule(
            pattern="/api",
            type="strip_prefix",
        )
        rewriter = self.PathRewriter([rule])
        result = rewriter.rewrite("/api/v1/users")
        self.assertEqual(result, "/v1/users")

    def test_strip_prefix_no_match(self):
        """测试前缀不匹配时路径不变"""
        rule = self.RewriteRule(
            pattern="/api",
            type="strip_prefix",
        )
        rewriter = self.PathRewriter([rule])
        result = rewriter.rewrite("/other/path")
        self.assertEqual(result, "/other/path")

    def test_strip_prefix_root(self):
        """测试剥离前缀后根路径"""
        rule = self.RewriteRule(
            pattern="/api",
            type="strip_prefix",
        )
        rewriter = self.PathRewriter([rule])
        result = rewriter.rewrite("/api")
        self.assertEqual(result, "/")

    def test_add_prefix(self):
        """测试添加前缀"""
        rule = self.RewriteRule(
            pattern="",
            replacement="/api",
            type="add_prefix",
        )
        rewriter = self.PathRewriter([rule])
        result = rewriter.rewrite("/v1/users")
        self.assertEqual(result, "/api/v1/users")

    def test_add_prefix_already_exists(self):
        """测试前缀已存在时不重复添加"""
        rule = self.RewriteRule(
            pattern="",
            replacement="/api",
            type="add_prefix",
        )
        rewriter = self.PathRewriter([rule])
        result = rewriter.rewrite("/api/v1/users")
        self.assertEqual(result, "/api/v1/users")

    def test_multiple_rules_ordered(self):
        """测试多条规则按顺序执行"""
        rules = [
            self.RewriteRule(
                pattern="/api",
                type="strip_prefix",
                order=1,
            ),
            self.RewriteRule(
                pattern=r"/v(\d+)",
                replacement=r"/version/\1",
                type="regex",
                order=2,
            ),
        ]
        rewriter = self.PathRewriter(rules)
        result = rewriter.rewrite("/api/v2/users")
        self.assertEqual(result, "/version/2/users")

    def test_disabled_rule_skipped(self):
        """测试禁用的规则被跳过"""
        rules = [
            self.RewriteRule(
                pattern="/api",
                type="strip_prefix",
                enabled=False,
            ),
        ]
        rewriter = self.PathRewriter(rules)
        result = rewriter.rewrite("/api/v1/users")
        self.assertEqual(result, "/api/v1/users")

    def test_get_rules(self):
        """测试获取规则列表"""
        rules = [
            self.RewriteRule(pattern="/test", type="strip_prefix"),
        ]
        rewriter = self.PathRewriter(rules)
        rule_list = rewriter.get_rules()
        self.assertEqual(len(rule_list), 1)
        self.assertEqual(rule_list[0]["pattern"], "/test")

    def test_get_stats(self):
        """测试获取统计信息"""
        rewriter = self.PathRewriter()
        rewriter.rewrite("/test")
        stats = rewriter.get_stats()
        self.assertIn("total_rewrites", stats)
        self.assertEqual(stats["total_rewrites"], 1)

    def test_reset_stats(self):
        """测试重置统计"""
        rewriter = self.PathRewriter()
        rewriter.rewrite("/test")
        rewriter.reset_stats()
        stats = rewriter.get_stats()
        self.assertEqual(stats["total_rewrites"], 0)

    def test_add_rule(self):
        """测试添加规则"""
        rewriter = self.PathRewriter()
        rule = self.RewriteRule(pattern="/old", replacement="/new", type="regex")
        rewriter.add_rule(rule)
        result = rewriter.rewrite("/old/path")
        self.assertEqual(result, "/new/path")

    def test_remove_rule(self):
        """测试移除规则"""
        rules = [
            self.RewriteRule(pattern="/old", replacement="/new", type="regex"),
        ]
        rewriter = self.PathRewriter(rules)
        success = rewriter.remove_rule("/old", "regex")
        self.assertTrue(success)
        result = rewriter.rewrite("/old/path")
        self.assertEqual(result, "/old/path")

    def test_set_rules(self):
        """测试设置规则列表"""
        rewriter = self.PathRewriter()
        rules = [
            self.RewriteRule(pattern="/a", replacement="/b", type="regex"),
        ]
        rewriter.set_rules(rules)
        result = rewriter.rewrite("/a")
        self.assertEqual(result, "/b")


class TestHeaderTransformer(unittest.TestCase):
    """头转换器测试"""

    def setUp(self):
        from src.routing.header_transformer import HeaderTransformer, HeaderRule, HeaderCondition
        self.HeaderTransformer = HeaderTransformer
        self.HeaderRule = HeaderRule
        self.HeaderCondition = HeaderCondition

    def test_add_header_request(self):
        """测试添加请求头"""
        rule = self.HeaderRule(
            action="add",
            header="X-Custom",
            value="test-value",
            direction="request",
        )
        transformer = self.HeaderTransformer([rule])
        headers = {"Content-Type": "application/json"}
        result = transformer.transform_request(headers)
        self.assertEqual(result["X-Custom"], "test-value")
        self.assertEqual(result["Content-Type"], "application/json")

    def test_add_header_exists_not_overwritten(self):
        """测试 add 操作：头已存在时不覆盖"""
        rule = self.HeaderRule(
            action="add",
            header="X-Custom",
            value="new-value",
            direction="request",
        )
        transformer = self.HeaderTransformer([rule])
        headers = {"X-Custom": "existing-value"}
        result = transformer.transform_request(headers)
        self.assertEqual(result["X-Custom"], "existing-value")

    def test_set_header(self):
        """测试 set 操作：覆盖或添加"""
        rule = self.HeaderRule(
            action="set",
            header="X-Custom",
            value="new-value",
            direction="request",
        )
        transformer = self.HeaderTransformer([rule])
        headers = {"X-Custom": "old-value"}
        result = transformer.transform_request(headers)
        self.assertEqual(result["X-Custom"], "new-value")

    def test_remove_header(self):
        """测试 remove 操作"""
        rule = self.HeaderRule(
            action="remove",
            header="X-Custom",
            direction="request",
        )
        transformer = self.HeaderTransformer([rule])
        headers = {"X-Custom": "value", "Content-Type": "json"}
        result = transformer.transform_request(headers)
        self.assertNotIn("X-Custom", result)
        self.assertIn("Content-Type", result)

    def test_append_header(self):
        """测试 append 操作"""
        rule = self.HeaderRule(
            action="append",
            header="X-Custom",
            value="second",
            direction="request",
        )
        transformer = self.HeaderTransformer([rule])
        headers = {"X-Custom": "first"}
        result = transformer.transform_request(headers)
        self.assertEqual(result["X-Custom"], "first, second")

    def test_append_header_new(self):
        """测试 append 操作：头不存在时创建"""
        rule = self.HeaderRule(
            action="append",
            header="X-New",
            value="value",
            direction="request",
        )
        transformer = self.HeaderTransformer([rule])
        headers = {}
        result = transformer.transform_request(headers)
        self.assertEqual(result["X-New"], "value")

    def test_response_header_transform(self):
        """测试响应头转换"""
        rule = self.HeaderRule(
            action="set",
            header="X-Server",
            value="yunxi-gateway",
            direction="response",
        )
        transformer = self.HeaderTransformer([rule])
        headers = {"Content-Type": "application/json"}
        result = transformer.transform_response(headers)
        self.assertEqual(result["X-Server"], "yunxi-gateway")

    def test_both_direction(self):
        """测试 both 方向：请求和响应都生效"""
        rule = self.HeaderRule(
            action="set",
            header="X-Trace-Id",
            value="trace-123",
            direction="both",
        )
        transformer = self.HeaderTransformer([rule])

        req_headers = {}
        req_result = transformer.transform_request(req_headers)
        self.assertEqual(req_result["X-Trace-Id"], "trace-123")

        resp_headers = {}
        resp_result = transformer.transform_response(resp_headers)
        self.assertEqual(resp_result["X-Trace-Id"], "trace-123")

    def test_condition_exists_passes(self):
        """测试条件：头存在时执行操作"""
        condition = self.HeaderCondition(header="X-User-Id", operator="exists")
        rule = self.HeaderRule(
            action="set",
            header="X-Auth-Type",
            value="user",
            direction="request",
            conditions=[condition],
        )
        transformer = self.HeaderTransformer([rule])

        # 有 X-User-Id 头，应该执行
        headers = {"X-User-Id": "123"}
        result = transformer.transform_request(headers)
        self.assertEqual(result["X-Auth-Type"], "user")

    def test_condition_exists_skipped(self):
        """测试条件：头不存在时跳过操作"""
        condition = self.HeaderCondition(header="X-User-Id", operator="exists")
        rule = self.HeaderRule(
            action="set",
            header="X-Auth-Type",
            value="user",
            direction="request",
            conditions=[condition],
        )
        transformer = self.HeaderTransformer([rule])

        # 没有 X-User-Id 头，应该跳过
        headers = {"Content-Type": "json"}
        result = transformer.transform_request(headers)
        self.assertNotIn("X-Auth-Type", result)

    def test_condition_equals(self):
        """测试条件：等于操作符"""
        condition = self.HeaderCondition(
            header="X-Env",
            operator="equals",
            value="production",
        )
        rule = self.HeaderRule(
            action="set",
            header="X-Security",
            value="strict",
            direction="response",
            conditions=[condition],
        )
        transformer = self.HeaderTransformer([rule])

        headers = {"X-Env": "production"}
        result = transformer.transform_response(headers)
        self.assertEqual(result["X-Security"], "strict")

    def test_condition_contains(self):
        """测试条件：包含操作符"""
        condition = self.HeaderCondition(
            header="Content-Type",
            operator="contains",
            value="json",
        )
        rule = self.HeaderRule(
            action="set",
            header="X-Format",
            value="json",
            direction="request",
            conditions=[condition],
        )
        transformer = self.HeaderTransformer([rule])

        headers = {"Content-Type": "application/json"}
        result = transformer.transform_request(headers)
        self.assertEqual(result["X-Format"], "json")

    def test_condition_not_exists(self):
        """测试条件：不存在操作符"""
        condition = self.HeaderCondition(header="X-Cache", operator="not_exists")
        rule = self.HeaderRule(
            action="set",
            header="X-Cache",
            value="miss",
            direction="response",
            conditions=[condition],
        )
        transformer = self.HeaderTransformer([rule])

        headers = {"Content-Type": "json"}
        result = transformer.transform_response(headers)
        self.assertEqual(result["X-Cache"], "miss")

    def test_condition_regex(self):
        """测试条件：正则操作符"""
        condition = self.HeaderCondition(
            header="Accept",
            operator="regex",
            value="text/html",
        )
        rule = self.HeaderRule(
            action="set",
            header="X-Content-Type",
            value="html",
            direction="response",
            conditions=[condition],
        )
        transformer = self.HeaderTransformer([rule])

        headers = {"Accept": "text/html,application/xhtml+xml"}
        result = transformer.transform_response(headers)
        self.assertEqual(result["X-Content-Type"], "html")

    def test_multiple_conditions_all_required(self):
        """测试多条件：全部满足才执行"""
        conditions = [
            self.HeaderCondition(header="X-User-Id", operator="exists"),
            self.HeaderCondition(header="X-Env", operator="equals", value="prod"),
        ]
        rule = self.HeaderRule(
            action="set",
            header="X-Auth",
            value="verified",
            direction="request",
            conditions=conditions,
        )
        transformer = self.HeaderTransformer([rule])

        # 两个条件都满足
        headers = {"X-User-Id": "123", "X-Env": "prod"}
        result = transformer.transform_request(headers)
        self.assertEqual(result["X-Auth"], "verified")

        # 只满足一个
        headers = {"X-User-Id": "123", "X-Env": "dev"}
        result = transformer.transform_request(headers)
        self.assertNotIn("X-Auth", result)

    def test_case_insensitive_header_names(self):
        """测试头名称大小写不敏感"""
        rule = self.HeaderRule(
            action="remove",
            header="x-custom",
            direction="request",
        )
        transformer = self.HeaderTransformer([rule])
        headers = {"X-Custom": "value"}
        result = transformer.transform_request(headers)
        self.assertNotIn("X-Custom", result)

    def test_get_rules(self):
        """测试获取规则列表"""
        rules = [
            self.HeaderRule(action="add", header="X-Test", value="v", direction="request"),
        ]
        transformer = self.HeaderTransformer(rules)
        rule_dict = transformer.get_rules()
        self.assertIn("request", rule_dict)
        self.assertEqual(len(rule_dict["request"]), 1)

    def test_get_stats(self):
        """测试获取统计信息"""
        transformer = self.HeaderTransformer()
        transformer.transform_request({})
        stats = transformer.get_stats()
        self.assertIn("request_transforms", stats)
        self.assertEqual(stats["request_transforms"], 1)

    def test_add_rule(self):
        """测试添加规则"""
        transformer = self.HeaderTransformer()
        rule = self.HeaderRule(action="add", header="X-New", value="v", direction="request")
        transformer.add_rule(rule)
        result = transformer.transform_request({})
        self.assertEqual(result["X-New"], "v")

    def test_remove_rule(self):
        """测试移除规则"""
        rules = [
            self.HeaderRule(action="add", header="X-Test", value="v", direction="request"),
        ]
        transformer = self.HeaderTransformer(rules)
        success = transformer.remove_rule("X-Test", "add", "request")
        self.assertTrue(success)
        result = transformer.transform_request({})
        self.assertNotIn("X-Test", result)

    def test_reset_stats(self):
        """测试重置统计"""
        transformer = self.HeaderTransformer()
        transformer.transform_request({})
        transformer.reset_stats()
        stats = transformer.get_stats()
        self.assertEqual(stats["request_transforms"], 0)

    def test_original_headers_not_modified(self):
        """测试原始头字典不被修改"""
        rule = self.HeaderRule(
            action="set",
            header="X-New",
            value="value",
            direction="request",
        )
        transformer = self.HeaderTransformer([rule])
        original = {"Content-Type": "json"}
        result = transformer.transform_request(original)
        self.assertNotIn("X-New", original)
        self.assertIn("X-New", result)


if __name__ == "__main__":
    unittest.main()
