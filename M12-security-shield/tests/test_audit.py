"""
M12 安全盾 - 审计日志单元测试
覆盖：审计日志记录、查询过滤、分页、安全事件、统计功能
"""

import sys
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# 将项目根目录加入路径
from backend.services.audit_service import AuditService, get_audit_service


class TestAuditLogRecord(unittest.TestCase):
    """审计日志记录功能测试"""

    def setUp(self):
        """测试前准备：创建新的审计服务实例"""
        self.audit = AuditService()

    def test_log_audit_success(self):
        """测试：记录审计事件成功"""
        log = self.audit.log_audit(
            user_id="user_001",
            username="admin",
            role="admin",
            module="auth",
            action="login",
            resource_type="session",
            description="用户登录",
            source_ip="192.168.1.100",
            user_agent="Mozilla/5.0",
            request_method="POST",
            request_path="/api/login",
            response_status=200,
            status="success",
            duration_ms=45,
        )
        self.assertIsNotNone(log)
        self.assertIn("id", log)
        self.assertGreater(log["id"], 0)

    def test_log_audit_contains_correct_fields(self):
        """测试：事件包含正确的字段（时间、用户、动作、资源、IP 等）"""
        log = self.audit.log_audit(
            user_id="user_002",
            username="operator",
            role="operator",
            module="waf",
            action="create_rule",
            resource_type="waf_rule",
            resource_id="rule_123",
            description="创建 WAF 规则",
            source_ip="10.0.0.50",
            user_agent="curl/7.0",
            request_method="POST",
            request_path="/api/waf/rules",
            response_status=201,
            status="success",
            error_message="",
            duration_ms=120,
            extra_data={"rule_type": "sql_injection"},
        )
        # 验证核心字段
        self.assertEqual(log["user_id"], "user_002")
        self.assertEqual(log["username"], "operator")
        self.assertEqual(log["role"], "operator")
        self.assertEqual(log["module"], "waf")
        self.assertEqual(log["action"], "create_rule")
        self.assertEqual(log["resource_type"], "waf_rule")
        self.assertEqual(log["resource_id"], "rule_123")
        self.assertEqual(log["description"], "创建 WAF 规则")
        self.assertEqual(log["source_ip"], "10.0.0.50")
        self.assertEqual(log["user_agent"], "curl/7.0")
        self.assertEqual(log["request_method"], "POST")
        self.assertEqual(log["request_path"], "/api/waf/rules")
        self.assertEqual(log["response_status"], 201)
        self.assertEqual(log["status"], "success")
        self.assertEqual(log["duration_ms"], 120)
        self.assertEqual(log["extra_data"], {"rule_type": "sql_injection"})
        # 创建时间存在
        self.assertIn("created_at", log)
        self.assertTrue(len(log["created_at"]) > 0)

    def test_log_audit_incremental_ids(self):
        """测试：日志 ID 递增"""
        log1 = self.audit.log_audit(action="action1", module="test")
        log2 = self.audit.log_audit(action="action2", module="test")
        log3 = self.audit.log_audit(action="action3", module="test")
        self.assertEqual(log2["id"], log1["id"] + 1)
        self.assertEqual(log3["id"], log2["id"] + 1)

    def test_log_audit_different_event_types(self):
        """测试：不同事件类型正确记录"""
        types = ["login", "logout", "create", "update", "delete", "read"]
        for action in types:
            self.audit.log_audit(action=action, module="test")

        result = self.audit.get_audit_logs(page=1, page_size=20)
        actions_found = {log["action"] for log in result["items"]}
        for t in types:
            self.assertIn(t, actions_found)

    def test_log_audit_default_values(self):
        """测试：不传参数时使用合理的默认值"""
        log = self.audit.log_audit()
        self.assertEqual(log["user_id"], "")
        self.assertEqual(log["username"], "")
        self.assertEqual(log["module"], "")
        self.assertEqual(log["action"], "")
        self.assertEqual(log["status"], "success")
        self.assertEqual(log["duration_ms"], 0)
        self.assertEqual(log["request_params"], {})
        self.assertEqual(log["extra_data"], {})

    def test_log_audit_total_count_increases(self):
        """测试：每次记录后总计数增加"""
        initial = self.audit._stats["total_logs"]
        self.audit.log_audit(action="test1")
        self.audit.log_audit(action="test2")
        self.assertEqual(self.audit._stats["total_logs"], initial + 2)

    def test_log_audit_failed_status(self):
        """测试：记录失败状态的审计日志"""
        log = self.audit.log_audit(
            action="login",
            status="failed",
            error_message="密码错误",
        )
        self.assertEqual(log["status"], "failed")
        self.assertEqual(log["error_message"], "密码错误")

    def test_log_audit_denied_status(self):
        """测试：记录权限被拒的审计日志"""
        log = self.audit.log_audit(
            action="delete_rule",
            status="denied",
            error_message="权限不足",
        )
        self.assertEqual(log["status"], "denied")
        self.assertEqual(log["error_message"], "权限不足")


class TestAuditLogQuery(unittest.TestCase):
    """审计日志查询功能测试"""

    def setUp(self):
        """测试前准备：填充测试数据"""
        self.audit = AuditService()
        # 插入测试数据
        self.audit.log_audit(
            user_id="user_001", username="alice", module="auth", action="login",
            source_ip="192.168.1.10", status="success",
        )
        self.audit.log_audit(
            user_id="user_001", username="alice", module="waf", action="create_rule",
            source_ip="192.168.1.10", status="success",
        )
        self.audit.log_audit(
            user_id="user_002", username="bob", module="auth", action="login",
            source_ip="10.0.0.20", status="failed",
        )
        self.audit.log_audit(
            user_id="user_002", username="bob", module="ip", action="ban_ip",
            source_ip="10.0.0.20", status="success",
        )
        self.audit.log_audit(
            user_id="user_003", username="charlie", module="audit", action="view_logs",
            source_ip="172.16.0.30", status="denied",
        )

    def test_filter_by_module(self):
        """测试：按模块过滤"""
        result = self.audit.get_audit_logs(module="auth", page=1, page_size=20)
        self.assertEqual(result["total"], 2)
        for log in result["items"]:
            self.assertEqual(log["module"], "auth")

    def test_filter_by_user_id(self):
        """测试：按用户过滤"""
        result = self.audit.get_audit_logs(user_id="user_001", page=1, page_size=20)
        self.assertEqual(result["total"], 2)
        for log in result["items"]:
            self.assertEqual(log["user_id"], "user_001")

    def test_filter_by_action(self):
        """测试：按操作类型过滤"""
        result = self.audit.get_audit_logs(action="login", page=1, page_size=20)
        self.assertEqual(result["total"], 2)
        for log in result["items"]:
            self.assertEqual(log["action"], "login")

    def test_filter_by_status(self):
        """测试：按状态过滤"""
        result = self.audit.get_audit_logs(status="success", page=1, page_size=20)
        self.assertEqual(result["total"], 3)
        for log in result["items"]:
            self.assertEqual(log["status"], "success")

    def test_filter_by_source_ip(self):
        """测试：按来源 IP 过滤"""
        result = self.audit.get_audit_logs(source_ip="10.0.0.20", page=1, page_size=20)
        self.assertEqual(result["total"], 2)
        for log in result["items"]:
            self.assertEqual(log["source_ip"], "10.0.0.20")

    def test_filter_combined_conditions(self):
        """测试：多条件组合过滤"""
        result = self.audit.get_audit_logs(
            user_id="user_002",
            module="auth",
            status="failed",
            page=1, page_size=20,
        )
        self.assertEqual(result["total"], 1)
        log = result["items"][0]
        self.assertEqual(log["user_id"], "user_002")
        self.assertEqual(log["module"], "auth")
        self.assertEqual(log["status"], "failed")

    def test_pagination_first_page(self):
        """测试：分页功能 - 第一页"""
        result = self.audit.get_audit_logs(page=1, page_size=2)
        self.assertEqual(result["total"], 5)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["page_size"], 2)
        self.assertEqual(result["total_pages"], 3)

    def test_pagination_last_page(self):
        """测试：分页功能 - 最后一页"""
        result = self.audit.get_audit_logs(page=3, page_size=2)
        self.assertEqual(len(result["items"]), 1)  # 第 3 页只有 1 条
        self.assertEqual(result["page"], 3)

    def test_pagination_out_of_range(self):
        """测试：分页 - 超出范围返回空列表"""
        result = self.audit.get_audit_logs(page=10, page_size=2)
        self.assertEqual(len(result["items"]), 0)
        self.assertEqual(result["total"], 5)

    def test_pagination_total_pages_calculation(self):
        """测试：总页数计算正确"""
        # 5 条，每页 2 条 -> 3 页
        result = self.audit.get_audit_logs(page=1, page_size=2)
        self.assertEqual(result["total_pages"], 3)
        # 5 条，每页 5 条 -> 1 页
        result = self.audit.get_audit_logs(page=1, page_size=5)
        self.assertEqual(result["total_pages"], 1)
        # 5 条，每页 10 条 -> 1 页
        result = self.audit.get_audit_logs(page=1, page_size=10)
        self.assertEqual(result["total_pages"], 1)

    def test_keyword_search(self):
        """测试：关键词搜索"""
        result = self.audit.get_audit_logs(keyword="alice", page=1, page_size=20)
        self.assertEqual(result["total"], 2)

    def test_query_empty_result(self):
        """测试：查询不存在的条件返回空"""
        result = self.audit.get_audit_logs(user_id="nonexistent", page=1, page_size=20)
        self.assertEqual(result["total"], 0)
        self.assertEqual(len(result["items"]), 0)


class TestSecurityEvents(unittest.TestCase):
    """安全事件记录和查询测试"""

    def setUp(self):
        """测试前准备"""
        self.audit = AuditService()

    def test_log_security_event_success(self):
        """测试：记录安全事件成功"""
        event = self.audit.log_security_event(
            event_type="waf_block",
            severity="high",
            source_ip="192.168.1.100",
            target_path="/api/v1/users",
            method="GET",
            description="SQL injection attempt detected",
            rule_name="sql_injection_keyword",
            user_agent="sqlmap/1.0",
        )
        self.assertIsNotNone(event)
        self.assertGreater(event["id"], 0)
        self.assertEqual(event["event_type"], "waf_block")
        self.assertEqual(event["severity"], "high")
        self.assertEqual(event["status"], "active")

    def test_security_event_fields(self):
        """测试：安全事件包含完整字段"""
        details = {"payload": "1' OR '1'='1", "param": "id"}
        event = self.audit.log_security_event(
            event_type="xss_attack",
            severity="medium",
            source_ip="10.0.0.1",
            target_path="/search",
            method="POST",
            description="XSS attack in search query",
            rule_name="xss_script_tag",
            user_agent="Mozilla/5.0",
            details=details,
        )
        self.assertEqual(event["event_type"], "xss_attack")
        self.assertEqual(event["severity"], "medium")
        self.assertEqual(event["source_ip"], "10.0.0.1")
        self.assertEqual(event["target_path"], "/search")
        self.assertEqual(event["method"], "POST")
        self.assertEqual(event["description"], "XSS attack in search query")
        self.assertEqual(event["rule_name"], "xss_script_tag")
        self.assertEqual(event["user_agent"], "Mozilla/5.0")
        self.assertEqual(event["extra_data"], details)
        self.assertIn("created_at", event)

    def test_get_event_by_id(self):
        """测试：按 ID 查询安全事件"""
        event = self.audit.log_security_event(event_type="test", severity="low")
        event_id = event["id"]

        found = self.audit.get_event_by_id(event_id)
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], event_id)

    def test_get_event_by_id_not_found(self):
        """测试：查询不存在的事件返回 None"""
        result = self.audit.get_event_by_id(99999)
        self.assertIsNone(result)

    def test_resolve_event(self):
        """测试：处理安全事件"""
        event = self.audit.log_security_event(event_type="waf_block", severity="high")
        event_id = event["id"]

        resolved = self.audit.resolve_event(
            event_id=event_id,
            resolution_note="已确认并封禁 IP",
            resolved_by="admin",
            status="resolved",
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["resolved_by"], "admin")
        self.assertEqual(resolved["resolution_note"], "已确认并封禁 IP")
        self.assertIsNotNone(resolved["resolved_at"])

    def test_resolve_nonexistent_event(self):
        """测试：处理不存在的事件返回 None"""
        result = self.audit.resolve_event(event_id=99999, resolution_note="test")
        self.assertIsNone(result)


class TestAuditStats(unittest.TestCase):
    """审计统计功能测试"""

    def setUp(self):
        """测试前准备：填充数据"""
        self.audit = AuditService()
        self.audit.log_security_event(event_type="waf_block", severity="high")
        self.audit.log_security_event(event_type="waf_block", severity="medium")
        self.audit.log_security_event(event_type="auth_fail", severity="low")
        self.audit.log_security_event(event_type="ip_ban", severity="critical")
        self.audit.log_audit(action="login", module="auth")
        self.audit.log_audit(action="create_rule", module="waf")

    def test_total_events_count(self):
        """测试：总事件数统计正确"""
        stats = self.audit.get_stats()
        self.assertEqual(stats["total_events"], 4)

    def test_events_by_type(self):
        """测试：按类型统计正确"""
        stats = self.audit.get_stats()
        self.assertEqual(stats["events_by_type"]["waf_block"], 2)
        self.assertEqual(stats["events_by_type"]["auth_fail"], 1)
        self.assertEqual(stats["events_by_type"]["ip_ban"], 1)

    def test_events_by_severity(self):
        """测试：按严重级别统计正确"""
        stats = self.audit.get_stats()
        self.assertEqual(stats["events_by_severity"]["high"], 1)
        self.assertEqual(stats["events_by_severity"]["medium"], 1)
        self.assertEqual(stats["events_by_severity"]["low"], 1)
        self.assertEqual(stats["events_by_severity"]["critical"], 1)

    def test_total_audit_logs(self):
        """测试：审计日志总数正确"""
        stats = self.audit.get_stats()
        self.assertEqual(stats["total_audit_logs"], 2)

    def test_active_high_severity_count(self):
        """测试：未处理的高危事件统计"""
        stats = self.audit.get_stats()
        # high + critical
        self.assertEqual(stats["high_severity_count"], 2)

    def test_dashboard_data(self):
        """测试：仪表盘数据结构完整"""
        data = self.audit.get_dashboard_data()
        self.assertIn("summary", data)
        self.assertIn("attack_distribution", data)
        self.assertIn("severity_distribution", data)
        self.assertIn("top_source_ips", data)
        self.assertIn("trend_data", data)
        self.assertEqual(data["summary"]["total_events"], 4)

    def test_recent_stats(self):
        """测试：快速统计接口"""
        stats = self.audit.get_recent_stats()
        self.assertIn("events_today", stats)
        self.assertIn("waf_blocks_today", stats)
        self.assertIn("total_events", stats)
        self.assertEqual(stats["total_events"], 4)


class TestAuditIntegrity(unittest.TestCase):
    """日志完整性测试"""

    def setUp(self):
        self.audit = AuditService()

    def test_audit_log_created_at_immutable(self):
        """测试：日志创建时间字段在创建后存在且为字符串格式"""
        log = self.audit.log_audit(action="test", module="test")
        created_at = log["created_at"]
        self.assertIsInstance(created_at, str)
        # ISO 格式包含 T 或日期时间格式
        self.assertTrue(len(created_at) > 10)

    def test_security_event_id_unique(self):
        """测试：所有事件 ID 唯一"""
        ids = set()
        for i in range(20):
            event = self.audit.log_security_event(
                event_type=f"type_{i % 3}",
                severity="info",
            )
            ids.add(event["id"])
        self.assertEqual(len(ids), 20)

    def test_audit_log_id_unique(self):
        """测试：所有审计日志 ID 唯一"""
        ids = set()
        for i in range(20):
            log = self.audit.log_audit(action=f"action_{i}")
            ids.add(log["id"])
        self.assertEqual(len(ids), 20)

    def test_event_status_default_active(self):
        """测试：新创建的安全事件默认状态为 active"""
        event = self.audit.log_security_event(event_type="test", severity="low")
        self.assertEqual(event["status"], "active")
        self.assertEqual(event["resolved_by"], "")
        self.assertIsNone(event["resolved_at"])

    def test_thread_safety_basic(self):
        """测试：并发写入不丢数据（基础测试）"""
        import threading

        def writer(n):
            for i in range(n):
                self.audit.log_audit(action=f"thread_write_{i}")

        threads = []
        for _ in range(5):
            t = threading.Thread(target=writer, args=(10,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # 5 线程 x 10 条 = 50 条
        result = self.audit.get_audit_logs(page=1, page_size=100)
        self.assertEqual(result["total"], 50)


class TestAuditServiceSingleton(unittest.TestCase):
    """审计服务单例模式测试"""

    def test_get_audit_service_returns_same_instance(self):
        """测试：get_audit_service 返回同一实例"""
        # 注意：单例是模块级的，多次调用返回同一对象
        from backend.services.audit_service import _audit_service
        # 先重置单例
        import backend.services.audit_service as audit_mod
        audit_mod._audit_service = None

        s1 = get_audit_service()
        s2 = get_audit_service()
        self.assertIs(s1, s2)

    def tearDown(self):
        """测试后重置单例，避免影响其他测试"""
        import backend.services.audit_service as audit_mod
        audit_mod._audit_service = None


if __name__ == "__main__":
    unittest.main()
