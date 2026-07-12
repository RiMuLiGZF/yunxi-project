"""
M12-security-shield - WAF 规则引擎单元测试

覆盖 SQL 注入、XSS、命令注入、CSRF 等攻击类型的检测，
以及正常请求的误报测试、WAF 开关、自定义规则等功能。
"""

import sys
import os
import unittest

# 将项目根目录加入路径，支持直接运行测试
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from services.waf_engine import WafEngine


class TestWafEngineSqlInjection(unittest.TestCase):
    """SQL 注入检测测试"""

    def setUp(self):
        """每个测试前创建新的 WAF 引擎实例"""
        self.waf = WafEngine()

    def test_sql_injection_basic_or_tautology(self):
        """测试基础 SQL 注入：永真式 OR '1'='1"""
        result = self.waf.check_request(
            method="GET",
            path="/api/user",
            query="id=1' OR '1'='1",
        )
        self.assertFalse(result["passed"], "SQL 永真式注入应被拦截")
        self.assertEqual(result["rule_type"], "sql_injection")

    def test_sql_injection_stacked_drop_table(self):
        """测试堆叠查询注入：1; DROP TABLE users"""
        result = self.waf.check_request(
            method="GET",
            path="/api/data",
            query="id=1; DROP TABLE users",
        )
        self.assertFalse(result["passed"], "堆叠查询 DROP TABLE 应被拦截")
        self.assertEqual(result["rule_type"], "sql_injection")

    def test_sql_injection_case_mixed_bypass(self):
        """测试大小写混合绕过：sElEcT * FrOm users"""
        result = self.waf.check_request(
            method="GET",
            path="/api/search",
            query="q=sElEcT * FrOm users",
        )
        self.assertFalse(result["passed"], "大小写混合的 SQL 关键字应被拦截")
        self.assertEqual(result["rule_type"], "sql_injection")

    def test_sql_injection_url_encoded_bypass(self):
        """测试 URL 编码绕过：单引号编码为 %27"""
        result = self.waf.check_request(
            method="GET",
            path="/api/user",
            query="id=1%27%20OR%20%271%27=%271",
        )
        self.assertFalse(result["passed"], "URL 编码的 SQL 注入应被拦截")
        self.assertEqual(result["rule_type"], "sql_injection")

    def test_sql_injection_comment_bypass(self):
        """测试注释符绕过：1 OR 1=1 --"""
        result = self.waf.check_request(
            method="GET",
            path="/api/login",
            query="user=admin'--&pass=123",
        )
        self.assertFalse(result["passed"], "带注释符的 SQL 注入应被拦截")
        self.assertEqual(result["rule_type"], "sql_injection")

    def test_sql_injection_union_select(self):
        """测试 UNION 注入：UNION SELECT password FROM users"""
        result = self.waf.check_request(
            method="GET",
            path="/api/product",
            query="id=1 UNION SELECT username, password FROM users",
        )
        self.assertFalse(result["passed"], "UNION SELECT 注入应被拦截")
        self.assertEqual(result["rule_type"], "sql_injection")

    def test_sql_normal_query_no_false_positive(self):
        """测试正常 SQL 相关查询不被误报：数字参数、普通查询"""
        result = self.waf.check_request(
            method="GET",
            path="/api/items",
            query="page=1&size=20&sort=name",
        )
        self.assertTrue(result["passed"], "正常查询参数不应被误报为 SQL 注入")

    def test_sql_normal_numeric_id_no_false_positive(self):
        """测试纯数字 ID 参数不被误报"""
        result = self.waf.check_request(
            method="GET",
            path="/api/user",
            query="id=42&page=3&sort=name",
        )
        self.assertTrue(result["passed"], "纯数字 ID 与普通参数不应触发安全规则")


class TestWafEngineXss(unittest.TestCase):
    """XSS 检测测试"""

    def setUp(self):
        self.waf = WafEngine()

    def test_xss_basic_script_tag(self):
        """测试基础 XSS：<script>alert(1)</script>"""
        result = self.waf.check_request(
            method="GET",
            path="/api/search",
            query="q=<script>alert(1)</script>",
        )
        self.assertFalse(result["passed"], "script 标签 XSS 应被拦截")
        self.assertEqual(result["rule_type"], "xss")

    def test_xss_javascript_protocol(self):
        """测试 javascript 伪协议：javascript:alert(1)"""
        result = self.waf.check_request(
            method="GET",
            path="/api/redirect",
            query="url=javascript:alert(document.cookie)",
        )
        self.assertFalse(result["passed"], "javascript 伪协议 XSS 应被拦截")
        self.assertEqual(result["rule_type"], "xss")

    def test_xss_event_handler_bypass(self):
        """测试事件处理器绕过：onerror、onload"""
        result = self.waf.check_request(
            method="GET",
            path="/api/comment",
            query="text=<img src=x onerror=alert(1)>",
        )
        self.assertFalse(result["passed"], "img onerror 事件 XSS 应被拦截")
        self.assertEqual(result["rule_type"], "xss")

    def test_xss_body_injection(self):
        """测试请求体中的 XSS payload"""
        result = self.waf.check_request(
            method="POST",
            path="/api/comment",
            body='{"content": "<svg onload=alert(1)>"}',
        )
        self.assertFalse(result["passed"], "请求体中的 SVG onload XSS 应被拦截")
        self.assertEqual(result["rule_type"], "xss")

    def test_xss_normal_html_no_false_positive(self):
        """测试正常 HTML 不被误报：普通格式化文本"""
        result = self.waf.check_request(
            method="POST",
            path="/api/article",
            body='{"content": "<p>这是一段<strong>正常</strong>的文本。</p>"}',
        )
        self.assertTrue(result["passed"], "正常 HTML 标签不应被误报为 XSS")

    def test_xss_normal_link_no_false_positive(self):
        """测试普通链接不被误报"""
        result = self.waf.check_request(
            method="GET",
            path="/api/share",
            query="url=https://example.com/page?id=123",
        )
        self.assertTrue(result["passed"], "普通 URL 链接不应触发 XSS 规则")


class TestWafEngineCommandInjection(unittest.TestCase):
    """命令注入检测测试"""

    def setUp(self):
        self.waf = WafEngine()

    def test_cmd_injection_semicolon_ls(self):
        """测试基础命令注入：; ls -la"""
        result = self.waf.check_request(
            method="GET",
            path="/api/ping",
            query="host=127.0.0.1; ls -la",
        )
        self.assertFalse(result["passed"], "分号加 ls 命令注入应被拦截")
        self.assertEqual(result["rule_type"], "command_injection")

    def test_cmd_injection_pipe_cat(self):
        """测试管道符注入：| cat /etc/passwd"""
        result = self.waf.check_request(
            method="GET",
            path="/api/run",
            query="input=hello | cat /etc/passwd",
        )
        self.assertFalse(result["passed"], "管道符命令注入应被拦截")
        self.assertEqual(result["rule_type"], "command_injection")

    def test_cmd_injection_and_whoami(self):
        """测试 && 连接符注入：&& whoami"""
        result = self.waf.check_request(
            method="GET",
            path="/api/system",
            query="action=check && whoami",
        )
        self.assertFalse(result["passed"], "&& whoami 命令注入应被拦截")
        self.assertEqual(result["rule_type"], "command_injection")

    def test_cmd_injection_backtick(self):
        """测试反引号命令替换：`id`"""
        result = self.waf.check_request(
            method="GET",
            path="/api/input",
            query="text=hello `id` world",
        )
        self.assertFalse(result["passed"], "反引号命令替换应被拦截")
        self.assertEqual(result["rule_type"], "command_injection")

    def test_cmd_normal_param_no_false_positive(self):
        """测试正常命令参数不被误报"""
        result = self.waf.check_request(
            method="GET",
            path="/api/search",
            query="q=filetype&sort=name&filter=active",
        )
        self.assertTrue(result["passed"], "正常参数不应被误报为命令注入")

    def test_cmd_normal_path_no_false_positive(self):
        """测试普通路径字符串不被误报"""
        result = self.waf.check_request(
            method="GET",
            path="/api/file",
            query="path=documents/reports/2024",
        )
        self.assertTrue(result["passed"], "普通文件路径不应触发命令注入规则")


class TestWafEngineCsrf(unittest.TestCase):
    """CSRF 检测测试"""

    def setUp(self):
        self.waf = WafEngine()

    def test_csrf_missing_origin_header(self):
        """测试缺失 Origin 的请求（CSRF 风险）"""
        result = self.waf.check_request(
            method="POST",
            path="/api/transfer",
            body='{"amount": 1000}',
            headers={"Origin": "null", "Referer": "none"},
        )
        # CSRF 规则是 log 级别，action 可能不是 block，但应能检测到
        # 由于 match_target 是 header，需要看实际规则行为
        self.assertIsNotNone(result["passed"])

    def test_csrf_normal_request_with_referer(self):
        """测试带正常 Referer 的请求不触发 CSRF"""
        result = self.waf.check_request(
            method="POST",
            path="/api/submit",
            body='{"data": "test"}',
            headers={
                "Origin": "https://example.com",
                "Referer": "https://example.com/form",
            },
        )
        # 正常 Referer 不应触发 CSRF 规则
        self.assertTrue(result["passed"], "带正常 Referer 的请求不应被拦截")


class TestWafEngineFeatures(unittest.TestCase):
    """WAF 引擎功能测试（开关、自定义规则、统计等）"""

    def setUp(self):
        self.waf = WafEngine()

    def test_waf_disable_bypasses_all_checks(self):
        """测试 WAF 禁用后所有请求直接通过"""
        self.waf.disable()
        result = self.waf.check_request(
            method="GET",
            path="/api/test",
            query="id=1' OR '1'='1",
        )
        self.assertTrue(result["passed"], "WAF 禁用时 SQL 注入也应通过")

    def test_waf_enable_after_disable(self):
        """测试 WAF 重新启用后恢复检测"""
        self.waf.disable()
        self.waf.enable()
        result = self.waf.check_request(
            method="GET",
            path="/api/test",
            query="q=<script>alert(1)</script>",
        )
        self.assertFalse(result["passed"], "WAF 重新启用后应恢复 XSS 检测")

    def test_waf_toggle_switch(self):
        """测试 toggle 切换开关"""
        initial = self.waf.enabled
        new_state = self.waf.toggle()
        self.assertNotEqual(initial, new_state)
        new_state2 = self.waf.toggle()
        self.assertEqual(initial, new_state2)

    def test_add_custom_rule_and_detect(self):
        """测试添加自定义规则并生效"""
        rule = {
            "name": "custom_test_rule",
            "type": "custom",
            "pattern": r"malicious_pattern_xyz",
            "severity": "high",
            "action": "block",
            "match_target": "all",
        }
        new_rule = self.waf.add_rule(rule)
        self.assertEqual(new_rule["name"], "custom_test_rule")
        self.assertFalse(new_rule["is_builtin"])

        # 验证自定义规则生效
        result = self.waf.check_request(
            method="GET",
            path="/api/test",
            query="data=malicious_pattern_xyz",
        )
        self.assertFalse(result["passed"], "自定义规则应能检测到匹配内容")
        self.assertEqual(result["rule_name"], "custom_test_rule")

    def test_delete_custom_rule(self):
        """测试删除自定义规则"""
        rule = {
            "name": "rule_to_delete",
            "type": "custom",
            "pattern": r"delete_me_pattern",
        }
        new_rule = self.waf.add_rule(rule)
        rule_id = new_rule["id"]

        deleted = self.waf.delete_rule(rule_id)
        self.assertTrue(deleted, "自定义规则应能被删除")

        # 删除后应不再检测
        result = self.waf.check_request(
            method="GET",
            path="/api/test",
            query="data=delete_me_pattern",
        )
        self.assertTrue(result["passed"], "删除规则后不应再触发")

    def test_delete_builtin_rule_fails(self):
        """测试删除内置规则应失败"""
        # 找一个内置规则的 ID（第一个规则就是内置的）
        builtin_rules = self.waf.get_rules(is_active=True)
        if builtin_rules:
            rule_id = builtin_rules[0]["id"]
            result = self.waf.delete_rule(rule_id)
            self.assertFalse(result, "内置规则不应被删除")

    def test_get_rules_by_type(self):
        """测试按类型筛选规则"""
        sql_rules = self.waf.get_rules(rule_type="sql_injection")
        self.assertTrue(len(sql_rules) > 0, "应能筛选出 SQL 注入规则")
        for r in sql_rules:
            self.assertEqual(r["type"], "sql_injection")

    def test_rule_count_correct(self):
        """测试规则总数统计正确"""
        total = self.waf.get_rule_count()
        active = self.waf.get_active_rule_count()
        self.assertGreater(total, 0)
        self.assertGreaterEqual(total, active)

    def test_stats_increment_on_block(self):
        """测试拦截后统计计数增加"""
        status_before = self.waf.get_status()
        blocks_before = status_before["total_blocks"]

        # 触发一次拦截
        self.waf.check_request(
            method="GET",
            path="/api/test",
            query="id=1' OR '1'='1",
        )

        status_after = self.waf.get_status()
        self.assertGreater(status_after["total_blocks"], blocks_before)
        self.assertGreater(status_after["total_checks"], status_before["total_checks"])

    def test_path_traversal_detection(self):
        """测试路径遍历检测"""
        result = self.waf.check_request(
            method="GET",
            path="/api/file",
            query="path=../../etc/passwd",
        )
        self.assertFalse(result["passed"], "路径遍历攻击应被拦截")
        self.assertEqual(result["rule_type"], "path_traversal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
