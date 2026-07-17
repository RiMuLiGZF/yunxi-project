"""
API-Gateway 速率限制测试（TS-005, P1级）

测试目标：
1. 令牌桶全局/单IP限速
2. 分级限速（public/sensitive/strict/admin/mcp）
3. 不同 IP 独立计数
4. 滑动窗口计数器
5. 渐进式封禁
6. 登录失败限流
7. API Key 限速
8. 统计信息
9. 白名单 IP 不限流（通过封禁机制测试）
10. 同步/异步版本
"""

import sys
import time
import asyncio
import unittest
from pathlib import Path

# 将项目根目录加入 path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 将 API-Gateway 目录加入 path
_gateway_root = Path(__file__).resolve().parent.parent
if str(_gateway_root) not in sys.path:
    sys.path.insert(0, str(_gateway_root))


class TestSlidingWindowCounter(unittest.TestCase):
    """滑动窗口计数器测试"""

    def test_initial_allows_requests(self):
        """测试初始状态允许请求"""
        from src.services.rate_limiter import SlidingWindowCounter
        counter = SlidingWindowCounter(window_seconds=60, max_requests=10)

        allowed, remaining = counter.add_and_check()
        self.assertTrue(allowed)
        self.assertEqual(remaining, 9)

    def test_blocks_after_limit(self):
        """测试达到限制后阻止请求"""
        from src.services.rate_limiter import SlidingWindowCounter
        counter = SlidingWindowCounter(window_seconds=60, max_requests=5)

        for i in range(5):
            allowed, _ = counter.add_and_check()
            self.assertTrue(allowed, f"第 {i+1} 次请求应该通过")

        # 第6次应该被阻止
        allowed, remaining = counter.add_and_check()
        self.assertFalse(allowed)
        self.assertEqual(remaining, 0)

    def test_request_count_correct(self):
        """测试请求计数正确"""
        from src.services.rate_limiter import SlidingWindowCounter
        counter = SlidingWindowCounter(window_seconds=60, max_requests=100)

        for i in range(10):
            counter.add_and_check()

        self.assertEqual(len(counter.requests), 10)

    def test_expired_requests_cleaned(self):
        """测试过期请求被清理"""
        from src.services.rate_limiter import SlidingWindowCounter
        counter = SlidingWindowCounter(window_seconds=1, max_requests=10)

        # 添加一些"过期"的请求
        old_time = time.time() - 2  # 2秒前，超过1秒窗口
        for _ in range(5):
            counter.requests.append(old_time)

        # 新的请求应该通过（旧的已过期）
        allowed, remaining = counter.add_and_check()
        self.assertTrue(allowed)
        # 清理后应该只剩1个新请求
        self.assertEqual(len(counter.requests), 1)
        self.assertEqual(remaining, 9)


class TestRateLimitTiers(unittest.TestCase):
    """限速级别配置测试"""

    def test_tiers_exist(self):
        """测试所有预定义限速级别存在"""
        from src.services.rate_limiter import RATE_LIMIT_TIERS
        self.assertIn("public", RATE_LIMIT_TIERS)
        self.assertIn("sensitive", RATE_LIMIT_TIERS)
        self.assertIn("strict", RATE_LIMIT_TIERS)
        self.assertIn("admin", RATE_LIMIT_TIERS)
        self.assertIn("mcp", RATE_LIMIT_TIERS)

    def test_public_tier_config(self):
        """测试 public 级别配置"""
        from src.services.rate_limiter import RATE_LIMIT_TIERS
        tier = RATE_LIMIT_TIERS["public"]
        self.assertEqual(tier.name, "public")
        self.assertEqual(tier.requests_per_minute, 100)
        self.assertGreater(tier.requests_per_hour, 0)

    def test_sensitive_tier_stricter(self):
        """测试 sensitive 级别比 public 更严格"""
        from src.services.rate_limiter import RATE_LIMIT_TIERS
        public = RATE_LIMIT_TIERS["public"]
        sensitive = RATE_LIMIT_TIERS["sensitive"]
        self.assertLess(sensitive.requests_per_minute, public.requests_per_minute)

    def test_strict_tier_strictest(self):
        """测试 strict 级别最严格"""
        from src.services.rate_limiter import RATE_LIMIT_TIERS
        strict = RATE_LIMIT_TIERS["strict"]
        sensitive = RATE_LIMIT_TIERS["sensitive"]
        self.assertLess(strict.requests_per_minute, sensitive.requests_per_minute)
        self.assertEqual(strict.requests_per_minute, 5)

    def test_admin_tier_config(self):
        """测试 admin 级别配置"""
        from src.services.rate_limiter import RATE_LIMIT_TIERS
        admin = RATE_LIMIT_TIERS["admin"]
        self.assertEqual(admin.requests_per_minute, 30)

    def test_mcp_tier_config(self):
        """测试 mcp 级别配置"""
        from src.services.rate_limiter import RATE_LIMIT_TIERS
        mcp = RATE_LIMIT_TIERS["mcp"]
        self.assertEqual(mcp.requests_per_minute, 60)


class TestRateLimiterBasic(unittest.TestCase):
    """速率限制器基础测试"""

    def setUp(self):
        from src.services.rate_limiter import RateLimiter
        # 使用小阈值便于测试
        self.rl = RateLimiter(total_limit=100, per_ip_limit=10)

    def test_initial_stats(self):
        """测试初始统计"""
        stats = self.rl.get_stats()
        self.assertEqual(stats["total_requests"], 0)
        self.assertEqual(stats["blocked_total"], 0)
        self.assertEqual(stats["total_limit"], 100)
        self.assertEqual(stats["per_ip_limit"], 10)

    def test_single_request_allowed(self):
        """测试单个请求被允许"""
        async def test():
            allowed, reason, headers = await self.rl.check_rate_limit(ip="127.0.0.1")
            self.assertTrue(allowed)
            self.assertEqual(reason, "")

        asyncio.get_event_loop().run_until_complete(test())

    def test_rate_limit_headers_present(self):
        """测试限流信息头存在"""
        async def test():
            allowed, _, headers = await self.rl.check_rate_limit(ip="127.0.0.1")
            self.assertTrue(allowed)
            self.assertIn("X-RateLimit-Limit", headers)
            self.assertIn("X-RateLimit-Remaining", headers)
            self.assertIn("X-RateLimit-Tier", headers)

        asyncio.get_event_loop().run_until_complete(test())

    def test_ip_limit_exceeded(self):
        """测试单 IP 达到限制后被阻止"""
        # 使用一个独立的限流器，阈值为5
        from src.services.rate_limiter import RateLimiter
        rl = RateLimiter(total_limit=100, per_ip_limit=5)

        async def test():
            for i in range(5):
                allowed, _, _ = await rl.check_rate_limit(ip="192.168.1.1")
                self.assertTrue(allowed, f"第 {i+1} 次请求应该通过")

            # 第6次应该被阻止
            allowed, reason, headers = await rl.check_rate_limit(ip="192.168.1.1")
            self.assertFalse(allowed)
            self.assertEqual(reason, "ip_rate_limit_exceeded")
            self.assertIn("Retry-After", headers)

        asyncio.get_event_loop().run_until_complete(test())

    def test_different_ips_independent(self):
        """测试不同 IP 独立计数"""
        from src.services.rate_limiter import RateLimiter
        rl = RateLimiter(total_limit=1000, per_ip_limit=3)

        async def test():
            # IP1 用完全部配额
            for i in range(3):
                allowed, _, _ = await rl.check_rate_limit(ip="10.0.0.1")
                self.assertTrue(allowed)

            # IP1 被阻止
            allowed, _, _ = await rl.check_rate_limit(ip="10.0.0.1")
            self.assertFalse(allowed)

            # IP2 仍然可以请求
            allowed, _, _ = await rl.check_rate_limit(ip="10.0.0.2")
            self.assertTrue(allowed)

            # IP3 也可以
            allowed, _, _ = await rl.check_rate_limit(ip="10.0.0.3")
            self.assertTrue(allowed)

        asyncio.get_event_loop().run_until_complete(test())

    def test_stats_updated(self):
        """测试统计信息更新"""
        async def test():
            for i in range(5):
                await self.rl.check_rate_limit(ip="127.0.0.1")

            stats = self.rl.get_stats()
            self.assertEqual(stats["total_requests"], 5)
            self.assertEqual(stats["blocked_total"], 0)
            self.assertEqual(stats["active_ips"], 1)

        asyncio.get_event_loop().run_until_complete(test())


class TestTierRateLimit(unittest.TestCase):
    """分级限速测试"""

    def setUp(self):
        from src.services.rate_limiter import RateLimiter
        self.rl = RateLimiter(total_limit=1000, per_ip_limit=100)

    def test_public_tier_allows_more(self):
        """测试 public 级别允许更多请求"""
        from src.services.rate_limiter import RATE_LIMIT_TIERS
        limit = RATE_LIMIT_TIERS["public"].requests_per_minute

        async def test():
            ip = "172.16.0.1"
            for i in range(min(limit, 20)):  # 只测前20个，避免太慢
                allowed, _, _ = await self.rl.check_rate_limit(ip=ip, tier="public")
                self.assertTrue(allowed, f"public tier 第 {i+1} 次请求应该通过")

        asyncio.get_event_loop().run_until_complete(test())

    def test_sensitive_tier_strict(self):
        """测试 sensitive 级别更严格"""
        # sensitive 每分钟10次
        async def test():
            ip = "172.16.0.2"
            for i in range(10):
                allowed, _, _ = await self.rl.check_rate_limit(ip=ip, tier="sensitive")
                self.assertTrue(allowed, f"sensitive tier 第 {i+1} 次请求应该通过")

            # 第11次应该被阻止
            allowed, reason, _ = await self.rl.check_rate_limit(ip=ip, tier="sensitive")
            self.assertFalse(allowed)
            self.assertEqual(reason, "tier_rate_limit_exceeded")

        asyncio.get_event_loop().run_until_complete(test())

    def test_strict_tier_most_strict(self):
        """测试 strict 级别最严格（每分钟5次）"""
        async def test():
            ip = "172.16.0.3"
            for i in range(5):
                allowed, _, _ = await self.rl.check_rate_limit(ip=ip, tier="strict")
                self.assertTrue(allowed, f"strict tier 第 {i+1} 次请求应该通过")

            # 第6次应该被阻止
            allowed, reason, _ = await self.rl.check_rate_limit(ip=ip, tier="strict")
            self.assertFalse(allowed)
            self.assertEqual(reason, "tier_rate_limit_exceeded")

        asyncio.get_event_loop().run_until_complete(test())

    def test_admin_tier(self):
        """测试 admin 级别（每分钟30次）"""
        async def test():
            ip = "172.16.0.4"
            for i in range(30):
                allowed, _, _ = await self.rl.check_rate_limit(ip=ip, tier="admin")
                self.assertTrue(allowed, f"admin tier 第 {i+1} 次请求应该通过")

            # 第31次应该被阻止
            allowed, reason, _ = await self.rl.check_rate_limit(ip=ip, tier="admin")
            self.assertFalse(allowed)
            self.assertEqual(reason, "tier_rate_limit_exceeded")

        asyncio.get_event_loop().run_until_complete(test())

    def test_mcp_tier(self):
        """测试 mcp 级别（每分钟60次）"""
        async def test():
            ip = "172.16.0.5"
            for i in range(60):
                allowed, _, _ = await self.rl.check_rate_limit(ip=ip, tier="mcp")
                self.assertTrue(allowed, f"mcp tier 第 {i+1} 次请求应该通过")

            # 第61次应该被阻止
            allowed, reason, _ = await self.rl.check_rate_limit(ip=ip, tier="mcp")
            self.assertFalse(allowed)
            self.assertEqual(reason, "tier_rate_limit_exceeded")

        asyncio.get_event_loop().run_until_complete(test())

    def test_unknown_tier_passes(self):
        """测试未知级别直接放行"""
        async def test():
            allowed, reason, _ = await self.rl.check_rate_limit(ip="127.0.0.1", tier="nonexistent")
            self.assertTrue(allowed)
            self.assertEqual(reason, "")

        asyncio.get_event_loop().run_until_complete(test())

    def test_tier_headers_include_tier_name(self):
        """测试响应头包含限速级别名称"""
        async def test():
            allowed, _, headers = await self.rl.check_rate_limit(ip="127.0.0.1", tier="public")
            self.assertTrue(allowed)
            self.assertEqual(headers.get("X-RateLimit-Tier"), "public")

        asyncio.get_event_loop().run_until_complete(test())


class TestSyncRateLimit(unittest.TestCase):
    """同步版本速率限制测试"""

    def setUp(self):
        from src.services.rate_limiter import RateLimiter
        self.rl = RateLimiter(total_limit=1000, per_ip_limit=100)

    def test_sync_allows_requests(self):
        """测试同步版本允许请求"""
        allowed, reason = self.rl.check_rate_limit_sync(ip="127.0.0.1", tier="public")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_sync_ip_limit(self):
        """测试同步版本 IP 限速"""
        from src.services.rate_limiter import RateLimiter
        rl = RateLimiter(total_limit=1000, per_ip_limit=5)

        for i in range(5):
            allowed, _ = rl.check_rate_limit_sync(ip="10.0.0.1", tier="public")
            self.assertTrue(allowed, f"第 {i+1} 次请求应该通过")

        allowed, reason = rl.check_rate_limit_sync(ip="10.0.0.1", tier="public")
        self.assertFalse(allowed)
        self.assertEqual(reason, "ip_rate_limit_exceeded")

    def test_sync_tier_limit(self):
        """测试同步版本分级限速"""
        # strict 级别 5次/分钟
        for i in range(5):
            allowed, _ = self.rl.check_rate_limit_sync(ip="10.0.0.2", tier="strict")
            self.assertTrue(allowed)

        allowed, reason = self.rl.check_rate_limit_sync(ip="10.0.0.2", tier="strict")
        self.assertFalse(allowed)
        self.assertEqual(reason, "tier_rate_limit_exceeded")


class TestBanMechanism(unittest.TestCase):
    """封禁机制测试"""

    def setUp(self):
        from src.services.rate_limiter import RateLimiter
        self.rl = RateLimiter(total_limit=1000, per_ip_limit=100)

    def test_initial_no_ban(self):
        """测试初始状态没有封禁"""
        self.assertFalse(self.rl._check_ban("127.0.0.1"))

    def test_unban_ip(self):
        """测试手动解封 IP"""
        # 先手动添加一个封禁记录
        from src.services.rate_limiter import BanEntry
        self.rl._ban_entries["192.168.1.100"] = BanEntry(
            ip="192.168.1.100",
            until=time.time() + 3600,
            reason="test_ban",
            count=5,
        )
        self.assertTrue(self.rl._check_ban("192.168.1.100"))

        # 解封
        result = self.rl.unban_ip("192.168.1.100")
        self.assertTrue(result)
        self.assertFalse(self.rl._check_ban("192.168.1.100"))

    def test_unban_nonexistent_ip(self):
        """测试解封不存在的 IP 返回 False"""
        result = self.rl.unban_ip("192.0.2.1")
        self.assertFalse(result)

    def test_ban_expires(self):
        """测试封禁到期自动解除"""
        from src.services.rate_limiter import BanEntry
        # 添加一个已过期的封禁
        self.rl._ban_entries["10.0.0.1"] = BanEntry(
            ip="10.0.0.1",
            until=time.time() - 1,  # 已过期
            reason="expired_ban",
            count=1,
        )
        # 检查时应该自动移除
        self.assertFalse(self.rl._check_ban("10.0.0.1"))
        self.assertNotIn("10.0.0.1", self.rl._ban_entries)

    def test_violation_registration(self):
        """测试超限记录与渐进式封禁"""
        # 第1-3次超限：不封禁
        for i in range(3):
            self.rl._register_violation("192.168.1.50", "test")
            self.assertFalse(self.rl._check_ban("192.168.1.50"))

        # 第4次超限：封禁5分钟
        self.rl._register_violation("192.168.1.50", "test")
        self.assertTrue(self.rl._check_ban("192.168.1.50"))

    def test_banned_ip_blocked_in_check(self):
        """测试被封禁 IP 在 check_rate_limit 中被阻止"""
        from src.services.rate_limiter import BanEntry
        self.rl._ban_entries["192.168.1.200"] = BanEntry(
            ip="192.168.1.200",
            until=time.time() + 300,
            reason="rate_limit",
            count=5,
        )

        async def test():
            allowed, reason, headers = await self.rl.check_rate_limit(ip="192.168.1.200")
            self.assertFalse(allowed)
            self.assertEqual(reason, "ip_banned")
            self.assertIn("X-RateLimit-Banned", headers)

        asyncio.get_event_loop().run_until_complete(test())

    def test_ban_list(self):
        """测试获取封禁列表"""
        from src.services.rate_limiter import BanEntry
        self.rl._ban_entries["10.0.0.1"] = BanEntry(
            ip="10.0.0.1", until=time.time() + 100, reason="test", count=4
        )

        ban_list = self.rl.get_ban_list()
        self.assertEqual(len(ban_list), 1)
        self.assertEqual(ban_list[0]["ip"], "10.0.0.1")
        self.assertGreater(ban_list[0]["remaining_seconds"], 0)


class TestLoginFailureRateLimit(unittest.TestCase):
    """登录失败限流测试"""

    def setUp(self):
        from src.services.rate_limiter import RateLimiter
        self.rl = RateLimiter(total_limit=1000, per_ip_limit=100)

    def test_initial_login_allowed(self):
        """测试初始状态登录被允许"""
        allowed, info = self.rl.check_login_allowed("user@example.com", "192.168.1.1")
        self.assertTrue(allowed)
        self.assertEqual(info["failures"], 0)
        self.assertEqual(info["remaining_attempts"], 5)

    def test_login_failure_recorded(self):
        """测试登录失败被记录"""
        result = self.rl.record_login_failure("user@example.com", "192.168.1.1")
        self.assertEqual(result["failure_count"], 1)
        self.assertFalse(result.get("locked", False))

        info = self.rl.get_login_lock_info("user@example.com", "192.168.1.1")
        self.assertEqual(info["failures"], 1)
        self.assertEqual(info["remaining_attempts"], 4)

    def test_login_lock_after_max_failures(self):
        """测试达到最大失败次数后锁定账号"""
        username = "lockeduser@example.com"
        ip = "192.168.1.2"

        # 连续失败5次
        for i in range(5):
            result = self.rl.record_login_failure(username, ip)

        # 第5次失败后应该被锁定
        self.assertTrue(result["locked"])
        self.assertGreater(result["lock_duration"], 0)

        # 检查登录应该被拒绝
        allowed, info = self.rl.check_login_allowed(username, ip)
        self.assertFalse(allowed)
        self.assertEqual(info["reason"], "account_locked")

    def test_login_success_clears_failures(self):
        """测试登录成功清除失败记录"""
        username = "successuser@example.com"
        ip = "192.168.1.3"

        # 先记录几次失败
        for _ in range(3):
            self.rl.record_login_failure(username, ip)

        # 登录成功
        self.rl.record_login_success(username, ip)

        # 失败记录应该被清除
        info = self.rl.get_login_lock_info(username, ip)
        self.assertEqual(info["failures"], 0)
        self.assertFalse(info["locked"])

    def test_login_lock_info(self):
        """测试获取登录锁定信息"""
        username = "infouser@example.com"
        ip = "192.168.1.4"

        # 无记录时
        info = self.rl.get_login_lock_info(username, ip)
        self.assertEqual(info["failures"], 0)
        self.assertFalse(info["locked"])
        self.assertEqual(info["remaining_attempts"], 5)

        # 有失败记录时
        self.rl.record_login_failure(username, ip)
        info = self.rl.get_login_lock_info(username, ip)
        self.assertEqual(info["failures"], 1)
        self.assertEqual(info["remaining_attempts"], 4)

    def test_ip_level_login_lock(self):
        """测试 IP 级别的登录失败锁定（暴力破解防护）"""
        ip = "192.168.1.50"

        # 用不同用户名失败20次（IP级阈值是 5*4=20）
        for i in range(20):
            self.rl.record_login_failure(f"user{i}@test.com", ip)

        # 再用新用户尝试应该被 IP 级锁定
        allowed, info = self.rl.check_login_allowed("newuser@test.com", ip)
        self.assertFalse(allowed)
        self.assertEqual(info["reason"], "ip_login_locked")


class TestAPIKeyRateLimit(unittest.TestCase):
    """API Key 速率限制测试"""

    def setUp(self):
        from src.services.rate_limiter import RateLimiter
        self.rl = RateLimiter(total_limit=1000, per_ip_limit=100)

    def test_default_api_key_limit(self):
        """测试默认 API Key 限速（100次/分钟）"""
        api_key = "test-api-key-001"

        # 前100次应该通过
        for i in range(100):
            allowed, info = self.rl.check_api_key_rate_limit(api_key)
            self.assertTrue(allowed, f"第 {i+1} 次请求应该通过")

        # 第101次应该被阻止
        allowed, info = self.rl.check_api_key_rate_limit(api_key)
        self.assertFalse(allowed)
        self.assertEqual(info["reason"], "api_key_rate_limit_exceeded")
        self.assertIn("Retry-After", info)

    def test_custom_api_key_limit(self):
        """测试自定义 API Key 限速"""
        api_key = "custom-limit-key"
        self.rl.set_api_key_limit(api_key, requests_per_minute=10)

        for i in range(10):
            allowed, _ = self.rl.check_api_key_rate_limit(api_key)
            self.assertTrue(allowed)

        allowed, info = self.rl.check_api_key_rate_limit(api_key)
        self.assertFalse(allowed)
        self.assertEqual(info["X-RateLimit-Limit"], "10")

    def test_disabled_api_key_no_limit(self):
        """测试禁用限速的 API Key 不受限制"""
        api_key = "disabled-limit-key"
        self.rl.set_api_key_limit(api_key, requests_per_minute=1, enabled=False)

        # 即使超过限制也应该通过
        for i in range(10):
            allowed, _ = self.rl.check_api_key_rate_limit(api_key)
            self.assertTrue(allowed)

    def test_different_api_keys_independent(self):
        """测试不同 API Key 独立计数"""
        key1 = "key-one"
        key2 = "key-two"
        self.rl.set_api_key_limit(key1, requests_per_minute=5)
        self.rl.set_api_key_limit(key2, requests_per_minute=5)

        # key1 用完配额
        for i in range(5):
            self.rl.check_api_key_rate_limit(key1)
        allowed, _ = self.rl.check_api_key_rate_limit(key1)
        self.assertFalse(allowed)

        # key2 仍然可以请求
        allowed, _ = self.rl.check_api_key_rate_limit(key2)
        self.assertTrue(allowed)


class TestRateLimiterStats(unittest.TestCase):
    """速率限制统计测试"""

    def setUp(self):
        from src.services.rate_limiter import RateLimiter
        self.rl = RateLimiter(total_limit=100, per_ip_limit=10)

    def test_stats_structure(self):
        """测试统计信息结构"""
        stats = self.rl.get_stats()
        self.assertIn("total_limit", stats)
        self.assertIn("total_remaining", stats)
        self.assertIn("per_ip_limit", stats)
        self.assertIn("total_requests", stats)
        self.assertIn("blocked_total", stats)
        self.assertIn("blocked_by_ip", stats)
        self.assertIn("blocked_by_tier", stats)
        self.assertIn("blocked_by_login", stats)
        self.assertIn("blocked_by_api_key", stats)
        self.assertIn("banned_ips", stats)
        self.assertIn("locked_accounts", stats)
        self.assertIn("active_ips", stats)
        self.assertIn("active_api_keys", stats)

    def test_blocked_by_ip_counter(self):
        """测试 IP 限流阻塞计数"""
        from src.services.rate_limiter import RateLimiter
        rl = RateLimiter(total_limit=1000, per_ip_limit=3)

        async def test():
            ip = "172.16.1.1"
            for i in range(3):
                await rl.check_rate_limit(ip=ip)
            # 第4次被阻止
            await rl.check_rate_limit(ip=ip)

            stats = rl.get_stats()
            self.assertEqual(stats["blocked_by_ip"], 1)
            self.assertEqual(stats["blocked_total"], 1)

        asyncio.get_event_loop().run_until_complete(test())

    def test_blocked_by_tier_counter(self):
        """测试分级限流阻塞计数"""
        async def test():
            ip = "172.16.1.2"
            for i in range(5):
                await self.rl.check_rate_limit(ip=ip, tier="strict")
            # 第6次被阻止
            await self.rl.check_rate_limit(ip=ip, tier="strict")

            stats = self.rl.get_stats()
            self.assertEqual(stats["blocked_by_tier"], 1)

        asyncio.get_event_loop().run_until_complete(test())

    def test_active_ips_count(self):
        """测试活跃 IP 计数"""
        async def test():
            await self.rl.check_rate_limit(ip="10.0.0.1")
            await self.rl.check_rate_limit(ip="10.0.0.2")
            await self.rl.check_rate_limit(ip="10.0.0.3")

            stats = self.rl.get_stats()
            self.assertGreaterEqual(stats["active_ips"], 3)

        asyncio.get_event_loop().run_until_complete(test())


class TestRateLimiterCleanup(unittest.TestCase):
    """清理功能测试"""

    def setUp(self):
        from src.services.rate_limiter import RateLimiter
        self.rl = RateLimiter(total_limit=1000, per_ip_limit=100)

    def test_cleanup_expired_bans(self):
        """测试清理过期封禁"""
        from src.services.rate_limiter import BanEntry

        # 添加过期封禁
        self.rl._ban_entries["expired-ip"] = BanEntry(
            ip="expired-ip",
            until=time.time() - 100,
            reason="test",
            count=1,
        )
        # 添加未过期封禁
        self.rl._ban_entries["active-ip"] = BanEntry(
            ip="active-ip",
            until=time.time() + 100,
            reason="test",
            count=1,
        )

        self.assertEqual(len(self.rl._ban_entries), 2)

        self.rl.cleanup()

        # 过期的应该被清理
        self.assertEqual(len(self.rl._ban_entries), 1)
        self.assertIn("active-ip", self.rl._ban_entries)
        self.assertNotIn("expired-ip", self.rl._ban_entries)

    def test_cleanup_inactive_ips(self):
        """测试清理长时间不活动的 IP"""
        # 手动设置一个旧的 IP 令牌桶
        old_time = time.time() - 7200  # 2小时前
        self.rl._ip_tokens["old-ip"] = 5.0
        self.rl._ip_last_refill["old-ip"] = old_time

        self.assertIn("old-ip", self.rl._ip_tokens)

        self.rl.cleanup()

        # 长时间不活动的 IP 应该被清理
        self.assertNotIn("old-ip", self.rl._ip_tokens)


class TestGlobalRateLimit(unittest.TestCase):
    """全局限速测试"""

    def test_global_limit(self):
        """测试全局限速"""
        from src.services.rate_limiter import RateLimiter
        # 全局限制为10，单IP限制为100（确保IP限制不会先触发）
        rl = RateLimiter(total_limit=10, per_ip_limit=100)

        async def test():
            # 使用不同IP避免触发IP限制
            for i in range(10):
                ip = f"10.0.{i}.1"
                allowed, _, _ = await rl.check_rate_limit(ip=ip)
                self.assertTrue(allowed, f"第 {i+1} 次全局请求应该通过")

            # 第11次应该触发全局限速
            allowed, reason, _ = await rl.check_rate_limit(ip="10.0.99.1")
            self.assertFalse(allowed)
            self.assertEqual(reason, "global_rate_limit_exceeded")

        asyncio.get_event_loop().run_until_complete(test())


class TestRateLimiterSingleton(unittest.TestCase):
    """限流器单例测试"""

    def test_get_rate_limiter_returns_instance(self):
        """测试 get_rate_limiter 返回实例"""
        from src.services.rate_limiter import get_rate_limiter, RateLimiter
        rl = get_rate_limiter()
        self.assertIsInstance(rl, RateLimiter)

    def test_get_rate_limiter_singleton(self):
        """测试 get_rate_limiter 是单例"""
        from src.services.rate_limiter import get_rate_limiter
        rl1 = get_rate_limiter()
        rl2 = get_rate_limiter()
        self.assertIs(rl1, rl2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
