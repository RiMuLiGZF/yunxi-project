"""
M12-security-shield - IP 控制单元测试

覆盖 IP 黑白名单管理、CIDR 段匹配、自动封禁、自动解封、
综合 IP 状态检查等功能测试。
"""

import sys
import os
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from services.ip_filter import IpFilter, IpEntry


class TestIpFilterBlacklist(unittest.TestCase):
    """IP 黑名单管理测试"""

    def setUp(self):
        self.ipf = IpFilter()

    def test_add_single_ip_to_blacklist(self):
        """测试添加单个 IP 到黑名单"""
        entry = self.ipf.add_to_blacklist("192.168.1.100", reason="恶意攻击", severity="high")
        self.assertEqual(entry.ip_address, "192.168.1.100")
        self.assertEqual(entry.ip_type, "single")
        self.assertEqual(entry.reason, "恶意攻击")
        self.assertEqual(entry.severity, "high")

    def test_blacklisted_ip_is_blocked(self):
        """测试黑名单 IP 被拦截"""
        self.ipf.add_to_blacklist("10.0.0.1", reason="测试封禁")
        is_black, entry = self.ipf.is_blacklisted("10.0.0.1")
        self.assertTrue(is_black, "黑名单 IP 应被识别")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.ip_address, "10.0.0.1")

    def test_normal_ip_not_blacklisted(self):
        """测试普通 IP 不在黑名单中"""
        is_black, entry = self.ipf.is_blacklisted("8.8.8.8")
        self.assertFalse(is_black, "普通 IP 不应在黑名单中")
        self.assertIsNone(entry)

    def test_remove_from_blacklist(self):
        """测试从黑名单移除 IP"""
        self.ipf.add_to_blacklist("172.16.0.1", reason="临时封禁")
        # 确认在黑名单中
        is_black, _ = self.ipf.is_blacklisted("172.16.0.1")
        self.assertTrue(is_black)

        # 移除
        result = self.ipf.remove_from_blacklist("172.16.0.1")
        self.assertTrue(result, "移除应成功")

        # 确认已移除
        is_black, _ = self.ipf.is_blacklisted("172.16.0.1")
        self.assertFalse(is_black, "移除后不应在黑名单中")

    def test_remove_nonexistent_blacklist_ip(self):
        """测试移除不存在的黑名单 IP 返回 False"""
        result = self.ipf.remove_from_blacklist("1.2.3.4")
        self.assertFalse(result, "移除不存在的 IP 应返回 False")

    def test_blacklist_hit_count_increments(self):
        """测试黑名单命中次数增加"""
        self.ipf.add_to_blacklist("203.0.113.1", reason="测试")
        is_black, entry = self.ipf.is_blacklisted("203.0.113.1")
        initial_hits = entry.hit_count

        is_black2, entry2 = self.ipf.is_blacklisted("203.0.113.1")
        self.assertGreater(entry2.hit_count, initial_hits, "命中后 hit_count 应增加")


class TestIpFilterWhitelist(unittest.TestCase):
    """IP 白名单管理测试"""

    def setUp(self):
        self.ipf = IpFilter()

    def test_add_single_ip_to_whitelist(self):
        """测试添加单个 IP 到白名单"""
        entry = self.ipf.add_to_whitelist("127.0.0.1", reason="本地回环")
        self.assertEqual(entry.ip_address, "127.0.0.1")
        self.assertEqual(entry.ip_type, "single")

    def test_whitelisted_ip_is_allowed(self):
        """测试白名单 IP 被放行"""
        self.ipf.add_to_whitelist("10.0.0.5", reason="内部服务")
        is_white, entry = self.ipf.is_whitelisted("10.0.0.5")
        self.assertTrue(is_white, "白名单 IP 应被识别")
        self.assertIsNotNone(entry)

    def test_normal_ip_not_whitelisted(self):
        """测试普通 IP 不在白名单中"""
        is_white, entry = self.ipf.is_whitelisted("8.8.4.4")
        self.assertFalse(is_white)
        self.assertIsNone(entry)

    def test_remove_from_whitelist(self):
        """测试从白名单移除 IP"""
        self.ipf.add_to_whitelist("192.168.1.1", reason="网关")
        is_white, _ = self.ipf.is_whitelisted("192.168.1.1")
        self.assertTrue(is_white)

        result = self.ipf.remove_from_whitelist("192.168.1.1")
        self.assertTrue(result)

        is_white, _ = self.ipf.is_whitelisted("192.168.1.1")
        self.assertFalse(is_white)

    def test_whitelist_priority_over_blacklist(self):
        """测试白名单优先级高于黑名单（check_ip 中白名单优先）"""
        self.ipf.add_to_blacklist("192.168.1.50", reason="可疑")
        self.ipf.add_to_whitelist("192.168.1.50", reason="信任")

        result = self.ipf.check_ip("192.168.1.50")
        self.assertTrue(result["is_whitelisted"])
        self.assertEqual(result["recommendation"], "allow")
        self.assertEqual(result["risk_level"], "low")


class TestIpFilterCidr(unittest.TestCase):
    """CIDR 段匹配测试"""

    def setUp(self):
        self.ipf = IpFilter()

    def test_cidr_blacklist_match(self):
        """测试 CIDR 段黑名单匹配"""
        self.ipf.add_to_blacklist("192.168.1.0/24", reason="网段封禁")
        # 网段内的 IP 应被拦截
        is_black, entry = self.ipf.is_blacklisted("192.168.1.100")
        self.assertTrue(is_black, "CIDR 网段内的 IP 应被识别为黑名单")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.ip_address, "192.168.1.0/24")

    def test_cidr_blacklist_boundary(self):
        """测试 CIDR 边界 IP 匹配"""
        self.ipf.add_to_blacklist("10.0.0.0/24", reason="测试网段")
        # 第一个可用地址
        is_black1, _ = self.ipf.is_blacklisted("10.0.0.1")
        self.assertTrue(is_black1, "网段内起始 IP 应匹配")
        # 最后一个可用地址
        is_black2, _ = self.ipf.is_blacklisted("10.0.0.254")
        self.assertTrue(is_black2, "网段内末尾 IP 应匹配")

    def test_cidr_blacklist_outside(self):
        """测试 CIDR 网段外的 IP 不匹配"""
        self.ipf.add_to_blacklist("172.16.0.0/16", reason="测试")
        is_black, _ = self.ipf.is_blacklisted("172.17.0.1")
        self.assertFalse(is_black, "网段外的 IP 不应匹配")

    def test_cidr_whitelist_match(self):
        """测试 CIDR 段白名单匹配"""
        self.ipf.add_to_whitelist("192.168.0.0/16", reason="内网全部")
        is_white, entry = self.ipf.is_whitelisted("192.168.50.200")
        self.assertTrue(is_white, "CIDR 白名单网段内 IP 应被识别")
        self.assertIsNotNone(entry)

    def test_cidr_remove_from_blacklist(self):
        """测试移除 CIDR 黑名单段"""
        self.ipf.add_to_blacklist("10.10.0.0/16", reason="测试")
        # 确认匹配
        self.assertTrue(self.ipf.is_blacklisted("10.10.1.1")[0])

        # 移除
        result = self.ipf.remove_from_blacklist("10.10.0.0/16")
        self.assertTrue(result)

        # 确认不再匹配
        self.assertFalse(self.ipf.is_blacklisted("10.10.1.1")[0])


class TestIpFilterAutoBan(unittest.TestCase):
    """自动封禁与自动解封测试"""

    def setUp(self):
        self.ipf = IpFilter()

    def test_auto_ban_after_threshold(self):
        """测试达到失败阈值后自动封禁"""
        test_ip = "203.0.113.50"
        # 9 次失败，不应触发封禁
        for i in range(9):
            banned = self.ipf.record_failure(test_ip, threshold=10, ban_minutes=60)
            self.assertFalse(banned, f"第 {i+1} 次失败不应触发封禁")

        # 第 10 次失败，应触发自动封禁
        banned = self.ipf.record_failure(test_ip, threshold=10, ban_minutes=60)
        self.assertTrue(banned, "达到阈值后应触发自动封禁")

        # 验证 IP 已在黑名单中
        is_black, entry = self.ipf.is_blacklisted(test_ip)
        self.assertTrue(is_black, "自动封禁后 IP 应在黑名单中")
        self.assertEqual(entry.source, "auto")
        self.assertEqual(entry.severity, "high")

    def test_reset_failure_count(self):
        """测试重置失败计数"""
        test_ip = "198.51.100.10"
        # 记录 5 次失败
        for _ in range(5):
            self.ipf.record_failure(test_ip, threshold=10, ban_minutes=60)

        # 重置计数
        self.ipf.reset_failure_count(test_ip)

        # 再记录 9 次，不应触发封禁（因为已重置）
        for i in range(9):
            banned = self.ipf.record_failure(test_ip, threshold=10, ban_minutes=60)
            self.assertFalse(banned, f"重置后第 {i+1} 次失败不应触发封禁")

    def test_auto_ban_expiry(self):
        """测试自动封禁到期后自动解封（通过 mock 时间）"""
        test_ip = "192.0.2.10"
        # 触发自动封禁，封禁 1 分钟
        for _ in range(10):
            banned = self.ipf.record_failure(test_ip, threshold=10, ban_minutes=1)
        self.assertTrue(banned)

        # 确认在黑名单中
        is_black, _ = self.ipf.is_blacklisted(test_ip)
        self.assertTrue(is_black)

        # 获取当前时间作为基准
        base_time = time.time()
        future_time = base_time + 120  # 2 分钟后

        # 强制让 _last_cleanup 变旧，以便触发清理逻辑
        self.ipf._last_cleanup = base_time - 400

        # mock 时间前进 2 分钟（超过封禁时长）
        with patch("services.ip_filter.time.time", return_value=future_time):
            is_black_after, _ = self.ipf.is_blacklisted(test_ip)
            self.assertFalse(is_black_after, "封禁到期后应自动解封")

    def test_failure_count_resets_after_window(self):
        """测试失败计数在时间窗口后重置"""
        test_ip = "198.51.100.20"
        # 记录 5 次失败
        for _ in range(5):
            self.ipf.record_failure(test_ip, threshold=10, ban_minutes=60)

        # 获取当前时间作为基准，mock 时间前进 11 分钟（超过 10 分钟窗口）
        base_time = time.time()
        future_time = base_time + 660  # 11 分钟

        with patch("services.ip_filter.time.time", return_value=future_time):
            # 再记录 9 次失败，不应触发封禁（因为计数已重置）
            for i in range(9):
                banned = self.ipf.record_failure(test_ip, threshold=10, ban_minutes=60)
                self.assertFalse(banned, f"窗口重置后第 {i+1} 次失败不应触发封禁")


class TestIpFilterCheckIp(unittest.TestCase):
    """综合 IP 状态检查测试"""

    def setUp(self):
        self.ipf = IpFilter()

    def test_check_ip_normal(self):
        """测试普通 IP 的综合检查结果"""
        result = self.ipf.check_ip("8.8.8.8")
        self.assertEqual(result["ip_address"], "8.8.8.8")
        self.assertFalse(result["is_blacklisted"])
        self.assertFalse(result["is_whitelisted"])
        self.assertEqual(result["recommendation"], "allow")
        self.assertEqual(result["risk_level"], "low")

    def test_check_ip_blacklisted(self):
        """测试黑名单 IP 的综合检查"""
        self.ipf.add_to_blacklist("1.2.3.4", reason="恶意", severity="critical")
        result = self.ipf.check_ip("1.2.3.4")
        self.assertTrue(result["is_blacklisted"])
        self.assertFalse(result["is_whitelisted"])
        self.assertEqual(result["recommendation"], "block")
        self.assertEqual(result["risk_level"], "critical")
        self.assertIsNotNone(result["blacklist_info"])

    def test_check_ip_whitelisted(self):
        """测试白名单 IP 的综合检查"""
        self.ipf.add_to_whitelist("5.6.7.8", reason="信任")
        result = self.ipf.check_ip("5.6.7.8")
        self.assertTrue(result["is_whitelisted"])
        self.assertEqual(result["recommendation"], "allow")
        self.assertEqual(result["risk_level"], "low")
        self.assertIsNotNone(result["whitelist_info"])


class TestIpFilterStats(unittest.TestCase):
    """IP 过滤器统计信息测试"""

    def setUp(self):
        self.ipf = IpFilter()

    def test_get_counts(self):
        """测试获取黑白名单数量"""
        bl_count, wl_count = self.ipf.get_counts()
        self.assertEqual(bl_count, 0)
        self.assertEqual(wl_count, 0)

        self.ipf.add_to_blacklist("1.1.1.1")
        self.ipf.add_to_blacklist("2.2.2.2")
        self.ipf.add_to_whitelist("3.3.3.3")

        bl_count, wl_count = self.ipf.get_counts()
        self.assertEqual(bl_count, 2)
        self.assertEqual(wl_count, 1)

    def test_get_stats(self):
        """测试获取详细统计信息"""
        self.ipf.add_to_blacklist("10.0.0.1", severity="high")
        self.ipf.add_to_blacklist("10.0.0.2", severity="medium")
        self.ipf.add_to_whitelist("192.168.1.1")

        stats = self.ipf.get_stats()
        self.assertEqual(stats["blacklist_count"], 2)
        self.assertEqual(stats["whitelist_count"], 1)
        self.assertEqual(stats["active_blacklist"], 2)
        self.assertEqual(stats["active_whitelist"], 1)
        self.assertIn("high", stats["by_severity"])
        self.assertIn("medium", stats["by_severity"])

    def test_blacklist_filter_by_severity(self):
        """测试按严重级别筛选黑名单"""
        self.ipf.add_to_blacklist("1.1.1.1", severity="high")
        self.ipf.add_to_blacklist("2.2.2.2", severity="low")
        self.ipf.add_to_blacklist("3.3.3.3", severity="high")

        high_severity = self.ipf.get_blacklist(severity="high")
        self.assertEqual(len(high_severity), 2)
        for entry in high_severity:
            self.assertEqual(entry.severity, "high")


class TestIpEntry(unittest.TestCase):
    """IpEntry 数据类测试"""

    def test_ip_entry_single_ip(self):
        """测试单 IP 条目的创建和解析"""
        entry = IpEntry(ip_address="192.168.1.1", ip_type="single")
        self.assertIsNotNone(entry._network)
        self.assertEqual(entry.ip_type, "single")

    def test_ip_entry_cidr(self):
        """测试 CIDR 条目的创建和解析"""
        entry = IpEntry(ip_address="10.0.0.0/8", ip_type="cidr")
        self.assertIsNotNone(entry._network)
        self.assertEqual(entry.ip_type, "cidr")

    def test_ip_entry_invalid_ip(self):
        """测试无效 IP 的处理"""
        entry = IpEntry(ip_address="not_an_ip", ip_type="single")
        self.assertIsNone(entry._network)

    def test_ip_entry_default_values(self):
        """测试 IpEntry 默认值"""
        entry = IpEntry(ip_address="127.0.0.1")
        self.assertEqual(entry.ip_type, "single")
        self.assertEqual(entry.severity, "medium")
        self.assertEqual(entry.source, "manual")
        self.assertTrue(entry.is_active)
        self.assertEqual(entry.hit_count, 0)
        self.assertIsNone(entry.expires_at)


if __name__ == "__main__":
    unittest.main(verbosity=2)
