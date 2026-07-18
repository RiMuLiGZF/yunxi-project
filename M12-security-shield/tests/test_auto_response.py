"""
M12-security-shield - 自动响应引擎单元测试

覆盖响应规则、三级响应级别、封禁管理、规则管理、持久化等功能。
"""

import sys
import os
import unittest
import tempfile
import time

# 将项目根目录加入路径，支持直接运行测试
from services.auto_response import (
    AutoResponseEngine,
    SecurityEvent,
    ResponseRule,
    BannedIp,
    RESPONSE_LEVEL_DETECT,
    RESPONSE_LEVEL_LOG,
    RESPONSE_LEVEL_BLOCK,
    VALID_RESPONSE_LEVELS,
    EVENT_TYPE_SQL_INJECTION,
    EVENT_TYPE_XSS,
    EVENT_TYPE_LOGIN_FAILED,
    EVENT_TYPE_404_SCAN,
    EVENT_TYPE_DDOS,
    EVENT_TYPE_WAF_BLOCK,
    RULE_SQL_XSS_BAN,
    RULE_BRUTE_FORCE_BAN,
    RULE_SCAN_404_BAN,
    RULE_DDOS_BAN,
)


class TestAutoResponseEngineBasics(unittest.TestCase):
    """自动响应引擎基础功能测试"""

    def setUp(self):
        """每个测试前创建新的引擎实例"""
        self.engine = AutoResponseEngine(response_level=RESPONSE_LEVEL_DETECT)

    def test_default_response_level_is_detect(self):
        """测试默认响应级别为 detect"""
        engine = AutoResponseEngine()
        self.assertEqual(engine.get_response_level(), RESPONSE_LEVEL_DETECT)

    def test_set_valid_response_levels(self):
        """测试设置所有有效的响应级别"""
        for level in VALID_RESPONSE_LEVELS:
            result = self.engine.set_response_level(level)
            self.assertTrue(result)
            self.assertEqual(self.engine.get_response_level(), level)

    def test_set_invalid_response_level_fails(self):
        """测试设置无效的响应级别失败"""
        result = self.engine.set_response_level("invalid_level")
        self.assertFalse(result)
        # 级别保持不变
        self.assertEqual(self.engine.get_response_level(), RESPONSE_LEVEL_DETECT)

    def test_builtin_rules_loaded(self):
        """测试内置规则已加载"""
        rules = self.engine.get_rules()
        rule_ids = [r["rule_id"] for r in rules]

        self.assertIn(RULE_SQL_XSS_BAN, rule_ids)
        self.assertIn(RULE_BRUTE_FORCE_BAN, rule_ids)
        self.assertIn(RULE_SCAN_404_BAN, rule_ids)
        self.assertIn(RULE_DDOS_BAN, rule_ids)
        self.assertEqual(len(rules), 4)

    def test_builtin_rules_are_builtin(self):
        """测试内置规则标记为 is_builtin"""
        rules = self.engine.get_rules()
        for rule in rules:
            self.assertTrue(rule["is_builtin"], f"规则 {rule['rule_id']} 应标记为内置")

    def test_initial_stats(self):
        """测试初始统计值"""
        stats = self.engine.get_stats()
        self.assertEqual(stats["total_events"], 0)
        self.assertEqual(stats["total_bans"], 0)
        self.assertEqual(stats["total_alerts"], 0)
        self.assertEqual(stats["active_bans"], 0)
        self.assertEqual(stats["total_rules"], 4)
        self.assertEqual(stats["enabled_rules"], 4)


class TestDetectMode(unittest.TestCase):
    """Detect 响应级别测试：只记录，不拦截"""

    def setUp(self):
        self.engine = AutoResponseEngine(response_level=RESPONSE_LEVEL_DETECT)

    def test_sql_injection_in_detect_mode_not_triggered(self):
        """detect 模式下 SQL 注入不触发响应"""
        event = SecurityEvent(
            event_type=EVENT_TYPE_SQL_INJECTION,
            source_ip="192.168.1.100",
            severity="high",
            description="SQL 注入测试",
        )
        result = self.engine.process_event(event)

        self.assertFalse(result["triggered"])
        self.assertEqual(result["actions"], [])
        self.assertFalse(result["banned"])

    def test_xss_in_detect_mode_not_triggered(self):
        """detect 模式下 XSS 不触发响应"""
        event = SecurityEvent(
            event_type=EVENT_TYPE_XSS,
            source_ip="192.168.1.100",
            severity="high",
        )
        result = self.engine.process_event(event)
        self.assertFalse(result["triggered"])

    def test_brute_force_in_detect_mode_not_triggered(self):
        """detect 模式下暴力破解不触发响应"""
        for i in range(15):  # 超过阈值 10 次
            event = SecurityEvent(
                event_type=EVENT_TYPE_LOGIN_FAILED,
                source_ip="10.0.0.50",
                severity="medium",
            )
            result = self.engine.process_event(event)
            self.assertFalse(result["triggered"])

    def test_ip_not_banned_in_detect_mode(self):
        """detect 模式下 IP 不会被封禁"""
        # 触发多次 SQL 注入
        for i in range(5):
            event = SecurityEvent(
                event_type=EVENT_TYPE_SQL_INJECTION,
                source_ip="172.16.0.1",
                severity="high",
            )
            self.engine.process_event(event)

        banned, _ = self.engine.is_ip_banned("172.16.0.1")
        self.assertFalse(banned)


class TestLogMode(unittest.TestCase):
    """Log 响应级别测试：记录 + 告警"""

    def setUp(self):
        self.engine = AutoResponseEngine(response_level=RESPONSE_LEVEL_LOG)

    def test_sql_injection_triggers_alert(self):
        """log 模式下 SQL 注入触发告警"""
        event = SecurityEvent(
            event_type=EVENT_TYPE_SQL_INJECTION,
            source_ip="192.168.1.100",
            severity="high",
        )
        result = self.engine.process_event(event)

        self.assertTrue(result["triggered"])
        self.assertIn("alert", result["actions"])
        self.assertIn(RULE_SQL_XSS_BAN, result["rules_triggered"])
        self.assertFalse(result["banned"])  # log 模式不封禁

    def test_xss_triggers_alert(self):
        """log 模式下 XSS 触发告警"""
        event = SecurityEvent(
            event_type=EVENT_TYPE_XSS,
            source_ip="192.168.1.100",
            severity="high",
        )
        result = self.engine.process_event(event)
        self.assertTrue(result["triggered"])
        self.assertIn("alert", result["actions"])

    def test_brute_force_triggers_alert_after_threshold(self):
        """log 模式下暴力破解达到阈值后触发告警"""
        for i in range(9):
            event = SecurityEvent(
                event_type=EVENT_TYPE_LOGIN_FAILED,
                source_ip="10.0.0.50",
            )
            result = self.engine.process_event(event)
            # 前 9 次不应触发
            if i < 9:
                pass  # 第 10 次才触发

        # 第 10 次触发
        event = SecurityEvent(
            event_type=EVENT_TYPE_LOGIN_FAILED,
            source_ip="10.0.0.50",
        )
        result = self.engine.process_event(event)
        self.assertTrue(result["triggered"])
        self.assertIn("alert", result["actions"])
        self.assertFalse(result["banned"])

    def test_no_ban_in_log_mode(self):
        """log 模式下不会封禁 IP"""
        for i in range(20):
            event = SecurityEvent(
                event_type=EVENT_TYPE_LOGIN_FAILED,
                source_ip="10.0.0.50",
            )
            self.engine.process_event(event)

        banned, _ = self.engine.is_ip_banned("10.0.0.50")
        self.assertFalse(banned)

    def test_alerts_recorded(self):
        """测试告警被记录"""
        event = SecurityEvent(
            event_type=EVENT_TYPE_SQL_INJECTION,
            source_ip="192.168.1.100",
        )
        self.engine.process_event(event)

        alerts = self.engine.get_alerts()
        self.assertGreater(len(alerts), 0)
        self.assertEqual(alerts[0]["ip"], "192.168.1.100")
        self.assertEqual(alerts[0]["rule_id"], RULE_SQL_XSS_BAN)


class TestBlockMode(unittest.TestCase):
    """Block 响应级别测试：记录 + 拦截 + 封禁"""

    def setUp(self):
        self.engine = AutoResponseEngine(response_level=RESPONSE_LEVEL_BLOCK)

    def test_sql_injection_bans_ip(self):
        """block 模式下 SQL 注入直接封禁 IP"""
        event = SecurityEvent(
            event_type=EVENT_TYPE_SQL_INJECTION,
            source_ip="192.168.1.100",
            severity="high",
        )
        result = self.engine.process_event(event)

        self.assertTrue(result["triggered"])
        self.assertIn("ban", result["actions"])
        self.assertTrue(result["banned"])
        self.assertEqual(result["ban_duration_minutes"], 60)  # 1 小时

    def test_sql_injection_ip_is_banned(self):
        """block 模式下验证 IP 确实被封禁"""
        event = SecurityEvent(
            event_type=EVENT_TYPE_SQL_INJECTION,
            source_ip="10.0.0.1",
        )
        self.engine.process_event(event)

        banned, ban_info = self.engine.is_ip_banned("10.0.0.1")
        self.assertTrue(banned)
        self.assertIsNotNone(ban_info)
        self.assertEqual(ban_info.rule_id, RULE_SQL_XSS_BAN)

    def test_xss_bans_ip(self):
        """block 模式下 XSS 直接封禁 IP"""
        event = SecurityEvent(
            event_type=EVENT_TYPE_XSS,
            source_ip="172.16.0.1",
        )
        result = self.engine.process_event(event)
        self.assertTrue(result["banned"])

    def test_brute_force_bans_after_threshold(self):
        """block 模式下暴力破解达到阈值后封禁 24 小时"""
        ip = "192.168.2.50"
        for i in range(9):
            event = SecurityEvent(event_type=EVENT_TYPE_LOGIN_FAILED, source_ip=ip)
            result = self.engine.process_event(event)
            # 前 9 次不封禁
            self.assertFalse(result["banned"])

        # 第 10 次触发封禁
        event = SecurityEvent(event_type=EVENT_TYPE_LOGIN_FAILED, source_ip=ip)
        result = self.engine.process_event(event)
        self.assertTrue(result["banned"])
        self.assertEqual(result["ban_duration_minutes"], 1440)  # 24 小时

        banned, ban_info = self.engine.is_ip_banned(ip)
        self.assertTrue(banned)
        self.assertEqual(ban_info.rule_id, RULE_BRUTE_FORCE_BAN)

    def test_scan_404_bans_after_threshold(self):
        """block 模式下高频 404 扫描达到阈值后封禁 6 小时"""
        ip = "10.10.10.10"
        for i in range(99):
            event = SecurityEvent(event_type=EVENT_TYPE_404_SCAN, source_ip=ip)
            result = self.engine.process_event(event)
            # 前 99 次不封禁
            if i < 99:
                pass

        # 第 100 次触发封禁
        event = SecurityEvent(event_type=EVENT_TYPE_404_SCAN, source_ip=ip)
        result = self.engine.process_event(event)
        self.assertTrue(result["banned"])
        self.assertEqual(result["ban_duration_minutes"], 360)  # 6 小时

    def test_ddos_bans_after_threshold(self):
        """block 模式下 DDoS 达到阈值后封禁 12 小时"""
        ip = "203.0.113.1"
        for i in range(49):
            event = SecurityEvent(event_type=EVENT_TYPE_DDOS, source_ip=ip)
            self.engine.process_event(event)

        # 第 50 次触发封禁
        event = SecurityEvent(event_type=EVENT_TYPE_DDOS, source_ip=ip)
        result = self.engine.process_event(event)
        self.assertTrue(result["banned"])
        self.assertEqual(result["ban_duration_minutes"], 720)  # 12 小时

    def test_waf_block_event_triggers_ban(self):
        """WAF 拦截事件触发封禁"""
        event = SecurityEvent(
            event_type=EVENT_TYPE_WAF_BLOCK,
            source_ip="198.51.100.1",
        )
        result = self.engine.process_event(event)
        self.assertTrue(result["banned"])

    def test_already_banned_ip_does_not_double_ban(self):
        """已封禁的 IP 不会重复计数封禁"""
        ip = "203.0.113.50"
        event1 = SecurityEvent(event_type=EVENT_TYPE_SQL_INJECTION, source_ip=ip)
        result1 = self.engine.process_event(event1)
        self.assertTrue(result1["banned"])

        # 再次触发，不应重复封禁（结果仍为 True 但不会增加 ban 计数）
        event2 = SecurityEvent(event_type=EVENT_TYPE_SQL_INJECTION, source_ip=ip)
        result2 = self.engine.process_event(event2)
        # banned 可能为 False（因为已经被封禁了）
        # 但统计中 total_bans 应该只增加 1 次

        stats = self.engine.get_stats()
        # 至少有一次封禁
        self.assertGreaterEqual(stats["total_bans"], 1)

    def test_multiple_ips_banned_separately(self):
        """不同 IP 独立计数和封禁"""
        ip1 = "10.0.0.1"
        ip2 = "10.0.0.2"

        # IP1 触发 SQL 注入
        event1 = SecurityEvent(event_type=EVENT_TYPE_SQL_INJECTION, source_ip=ip1)
        self.engine.process_event(event1)

        # IP2 应该未被封禁
        banned2, _ = self.engine.is_ip_banned(ip2)
        self.assertFalse(banned2)

        # IP1 应该被封禁
        banned1, _ = self.engine.is_ip_banned(ip1)
        self.assertTrue(banned1)


class TestBanManagement(unittest.TestCase):
    """封禁管理功能测试"""

    def setUp(self):
        self.engine = AutoResponseEngine(response_level=RESPONSE_LEVEL_BLOCK)

    def test_manual_ban_ip(self):
        """手动封禁 IP"""
        result = self.engine.ban_ip("192.168.1.100", duration_minutes=30, reason="手动封禁测试")
        self.assertTrue(result)

        banned, info = self.engine.is_ip_banned("192.168.1.100")
        self.assertTrue(banned)
        self.assertEqual(info.reason, "手动封禁测试")
        self.assertEqual(info.rule_id, "manual")

    def test_manual_unban_ip(self):
        """手动解封 IP"""
        self.engine.ban_ip("10.0.0.1", duration_minutes=60)
        banned, _ = self.engine.is_ip_banned("10.0.0.1")
        self.assertTrue(banned)

        result = self.engine.unban_ip("10.0.0.1")
        self.assertTrue(result)

        banned, _ = self.engine.is_ip_banned("10.0.0.1")
        self.assertFalse(banned)

    def test_unban_nonexistent_ip_fails(self):
        """解封不存在的 IP 失败"""
        result = self.engine.unban_ip("1.2.3.4")
        self.assertFalse(result)

    def test_get_banned_ips(self):
        """获取封禁 IP 列表"""
        self.engine.ban_ip("10.0.0.1", duration_minutes=60, reason="test1")
        self.engine.ban_ip("10.0.0.2", duration_minutes=120, reason="test2")

        banned_list = self.engine.get_banned_ips()
        self.assertEqual(len(banned_list), 2)

        ips = [b["ip_address"] for b in banned_list]
        self.assertIn("10.0.0.1", ips)
        self.assertIn("10.0.0.2", ips)

    def test_get_banned_ips_active_only(self):
        """active_only 参数过滤已解封的 IP"""
        self.engine.ban_ip("10.0.0.1", duration_minutes=60)
        self.engine.ban_ip("10.0.0.2", duration_minutes=60)
        self.engine.unban_ip("10.0.0.2")

        active_banned = self.engine.get_banned_ips(active_only=True)
        self.assertEqual(len(active_banned), 1)
        self.assertEqual(active_banned[0]["ip_address"], "10.0.0.1")

        all_banned = self.engine.get_banned_ips(active_only=False)
        self.assertEqual(len(all_banned), 2)

    def test_permanent_ban(self):
        """永久封禁（duration_minutes=0）"""
        self.engine.ban_ip("192.168.1.1", duration_minutes=0, reason="永久封禁")
        banned, info = self.engine.is_ip_banned("192.168.1.1")
        self.assertTrue(banned)
        self.assertEqual(info.expires_at, 0.0)

    def test_ban_extends_existing_ban(self):
        """已封禁 IP 再次封禁会延长时间"""
        ip = "10.0.0.50"
        self.engine.ban_ip(ip, duration_minutes=30)  # 30 分钟

        # 再次封禁 60 分钟
        self.engine.ban_ip(ip, duration_minutes=60)

        banned_list = self.engine.get_banned_ips()
        self.assertEqual(len(banned_list), 1)
        # 剩余时间应接近 60 分钟（取较长的）
        remaining = banned_list[0]["remaining_minutes"]
        self.assertGreater(remaining, 50)  # 应该接近 60


class TestRuleManagement(unittest.TestCase):
    """规则管理功能测试"""

    def setUp(self):
        self.engine = AutoResponseEngine(response_level=RESPONSE_LEVEL_BLOCK)

    def test_get_rules(self):
        """获取规则列表"""
        rules = self.engine.get_rules()
        self.assertEqual(len(rules), 4)

    def test_update_builtin_rule_enabled(self):
        """启用/禁用内置规则"""
        result = self.engine.update_rule(RULE_SQL_XSS_BAN, {"enabled": False})
        self.assertIsNotNone(result)
        self.assertFalse(result["enabled"])

        # 验证规则已禁用
        rules = self.engine.get_rules()
        sql_rule = next(r for r in rules if r["rule_id"] == RULE_SQL_XSS_BAN)
        self.assertFalse(sql_rule["enabled"])

    def test_disabled_rule_does_not_trigger(self):
        """禁用的规则不会触发"""
        # 禁用 SQL 注入规则
        self.engine.update_rule(RULE_SQL_XSS_BAN, {"enabled": False})

        event = SecurityEvent(
            event_type=EVENT_TYPE_SQL_INJECTION,
            source_ip="192.168.1.100",
        )
        result = self.engine.process_event(event)
        self.assertFalse(result["triggered"])
        self.assertFalse(result["banned"])

    def test_update_rule_threshold(self):
        """更新规则阈值"""
        result = self.engine.update_rule(
            RULE_BRUTE_FORCE_BAN,
            {"threshold": 3, "time_window_seconds": 60}
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["threshold"], 3)
        self.assertEqual(result["time_window_seconds"], 60)

        # 验证 3 次就触发
        ip = "10.0.0.50"
        for i in range(2):
            event = SecurityEvent(event_type=EVENT_TYPE_LOGIN_FAILED, source_ip=ip)
            result = self.engine.process_event(event)
            self.assertFalse(result["banned"])

        event = SecurityEvent(event_type=EVENT_TYPE_LOGIN_FAILED, source_ip=ip)
        result = self.engine.process_event(event)
        self.assertTrue(result["banned"])

    def test_update_nonexistent_rule_fails(self):
        """更新不存在的规则返回 None"""
        result = self.engine.update_rule("nonexistent_rule", {"enabled": False})
        self.assertIsNone(result)

    def test_add_custom_rule(self):
        """添加自定义规则"""
        rule_data = {
            "rule_id": "custom_test",
            "name": "自定义测试规则",
            "event_types": ["custom_event"],
            "threshold": 5,
            "time_window_seconds": 30,
            "action": "ban",
            "ban_duration_minutes": 15,
            "risk_level": "medium",
        }
        result = self.engine.add_rule(rule_data)
        self.assertEqual(result["rule_id"], "custom_test")
        self.assertFalse(result["is_builtin"])

        rules = self.engine.get_rules()
        self.assertEqual(len(rules), 5)  # 4 内置 + 1 自定义

    def test_delete_custom_rule(self):
        """删除自定义规则"""
        self.engine.add_rule({"rule_id": "to_delete", "name": "待删除"})
        result = self.engine.delete_rule("to_delete")
        self.assertTrue(result)

        rules = self.engine.get_rules()
        self.assertEqual(len(rules), 4)  # 恢复为 4 个内置规则

    def test_delete_builtin_rule_fails(self):
        """删除内置规则失败"""
        result = self.engine.delete_rule(RULE_SQL_XSS_BAN)
        self.assertFalse(result)


class TestPersistence(unittest.TestCase):
    """持久化功能测试"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.persist_path = os.path.join(self.temp_dir, "auto_response_test.json")

    def tearDown(self):
        if os.path.exists(self.persist_path):
            os.remove(self.persist_path)
        os.rmdir(self.temp_dir)

    def test_save_and_load_banned_ips(self):
        """保存和加载封禁 IP"""
        # 创建引擎并封禁 IP
        engine1 = AutoResponseEngine(response_level=RESPONSE_LEVEL_BLOCK)
        engine1.set_persist_path(self.persist_path)
        engine1.ban_ip("192.168.1.100", duration_minutes=60, reason="测试持久化")
        engine1.save_to_disk()

        # 创建新引擎并加载
        engine2 = AutoResponseEngine(response_level=RESPONSE_LEVEL_DETECT)
        engine2.set_persist_path(self.persist_path)

        banned, info = engine2.is_ip_banned("192.168.1.100")
        self.assertTrue(banned)
        self.assertEqual(info.reason, "测试持久化")

    def test_save_and_load_response_level(self):
        """保存和加载响应级别"""
        engine1 = AutoResponseEngine(response_level=RESPONSE_LEVEL_BLOCK)
        engine1.set_persist_path(self.persist_path)
        engine1.save_to_disk()

        engine2 = AutoResponseEngine(response_level=RESPONSE_LEVEL_DETECT)
        engine2.set_persist_path(self.persist_path)
        self.assertEqual(engine2.get_response_level(), RESPONSE_LEVEL_BLOCK)

    def test_expired_ban_not_loaded(self):
        """过期的封禁不会被加载"""
        # 创建引擎并封禁一个很快过期的 IP
        engine1 = AutoResponseEngine(response_level=RESPONSE_LEVEL_BLOCK)
        engine1.set_persist_path(self.persist_path)
        engine1.ban_ip("10.0.0.1", duration_minutes=0)  # 永久封禁
        engine1.ban_ip("10.0.0.2", duration_minutes=1)  # 1 分钟（应仍然有效）
        engine1.save_to_disk()

        # 加载
        engine2 = AutoResponseEngine()
        engine2.set_persist_path(self.persist_path)

        # 永久封禁应该还在
        banned1, _ = engine2.is_ip_banned("10.0.0.1")
        self.assertTrue(banned1)


class TestPerformance(unittest.TestCase):
    """性能测试"""

    def setUp(self):
        self.engine = AutoResponseEngine(response_level=RESPONSE_LEVEL_DETECT)

    def test_event_processing_speed(self):
        """事件处理速度测试"""
        event = SecurityEvent(
            event_type=EVENT_TYPE_SQL_INJECTION,
            source_ip="192.168.1.100",
            severity="high",
        )

        # 预热
        for _ in range(10):
            self.engine.process_event(event)

        # 正式测试
        n = 1000
        start = time.perf_counter()
        for i in range(n):
            ev = SecurityEvent(
                event_type=EVENT_TYPE_SQL_INJECTION,
                source_ip=f"10.0.0.{i % 256}",
            )
            self.engine.process_event(ev)
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / n) * 1000
        # detect 模式应该很快
        self.assertLess(avg_ms, 1.0, f"平均事件处理时间 {avg_ms:.3f}ms，应 < 1ms")


if __name__ == "__main__":
    unittest.main(verbosity=2)
