"""
API-Gateway 熔断器测试（TS-005, P1级）

测试目标：
1. 熔断器三态转换（Closed -> Open -> Half-Open -> Closed）
2. 正常状态下请求通过
3. 失败率达到阈值后熔断
4. 熔断状态下直接拒绝请求
5. 半开状态探测
6. 恢复后关闭熔断器
7. 不同路由独立熔断器
8. 手动重置熔断器
9. 降级响应
10. 统计信息
"""

import sys
import time
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 将项目根目录加入 path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 将 API-Gateway 目录加入 path
_gateway_root = Path(__file__).resolve().parent.parent
if str(_gateway_root) not in sys.path:
    sys.path.insert(0, str(_gateway_root))

# 使用自定义模块名进行测试，避免与路由配置中的模块混淆
TEST_MOD = "test_module"
TEST_MOD_2 = "test_module_2"


class TestCircuitStateEnum(unittest.TestCase):
    """熔断器状态枚举测试"""

    def test_states_exist(self):
        """测试三种状态都存在"""
        from src.services.circuit_breaker import CircuitState
        self.assertEqual(CircuitState.CLOSED.value, "closed")
        self.assertEqual(CircuitState.OPEN.value, "open")
        self.assertEqual(CircuitState.HALF_OPEN.value, "half_open")


class TestCircuitBreakerClosed(unittest.TestCase):
    """熔断器关闭状态测试"""

    def setUp(self):
        from src.services.circuit_breaker import CircuitBreaker
        # 创建一个独立的熔断器实例
        self.cb = CircuitBreaker(failure_threshold=5, recovery_time=30)

    def test_initial_state_is_closed(self):
        """测试初始状态为关闭"""
        self.assertEqual(self.cb.get_state(TEST_MOD).value, "closed")

    def test_closed_state_allows_requests(self):
        """测试关闭状态下允许请求"""
        async def test():
            for i in range(10):
                allowed = await self.cb.can_execute(TEST_MOD)
                self.assertTrue(allowed, f"第 {i+1} 次请求应该被允许")

        asyncio.get_event_loop().run_until_complete(test())

    def test_success_resets_failure_count(self):
        """测试成功请求重置失败计数"""
        async def test():
            # 先调用 can_execute 以初始化状态
            await self.cb.can_execute(TEST_MOD)
            # 记录几次失败
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            # 记录一次成功
            await self.cb.record_success(TEST_MOD)

            # 失败计数应该被重置
            stats = self.cb.get_stats()
            self.assertEqual(stats[TEST_MOD]["failure_count"], 0)

        asyncio.get_event_loop().run_until_complete(test())

    def test_request_count_increments(self):
        """测试请求计数递增"""
        async def test():
            for i in range(5):
                await self.cb.can_execute(TEST_MOD)

            stats = self.cb.get_stats()
            self.assertEqual(stats[TEST_MOD]["total_requests"], 5)

        asyncio.get_event_loop().run_until_complete(test())


class TestCircuitBreakerOpen(unittest.TestCase):
    """熔断器打开状态测试"""

    def setUp(self):
        from src.services.circuit_breaker import CircuitBreaker
        # 使用较小的阈值便于测试（用自定义模块名，不受路由配置影响）
        self.cb = CircuitBreaker(failure_threshold=3, recovery_time=30)

    def test_failure_threshold_triggers_open(self):
        """测试达到失败阈值后熔断"""
        async def test():
            # 先允许请求（初始化状态）
            for i in range(3):
                allowed = await self.cb.can_execute(TEST_MOD)
                self.assertTrue(allowed)

            # 记录3次失败
            for i in range(3):
                await self.cb.record_failure(TEST_MOD)

            # 状态应该变为 open
            self.assertEqual(self.cb.get_state(TEST_MOD).value, "open")

        asyncio.get_event_loop().run_until_complete(test())

    def test_open_state_blocks_requests(self):
        """测试熔断状态下阻止请求"""
        async def test():
            # 触发熔断
            await self.cb.can_execute(TEST_MOD)
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            self.assertEqual(self.cb.get_state(TEST_MOD).value, "open")

            # 熔断状态下请求应该被拒绝
            allowed = await self.cb.can_execute(TEST_MOD)
            self.assertFalse(allowed)

        asyncio.get_event_loop().run_until_complete(test())

    def test_open_state_rejected_count(self):
        """测试熔断状态下拒绝计数"""
        async def test():
            # 触发熔断
            await self.cb.can_execute(TEST_MOD)
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            # 尝试3次请求，都应该被拒绝
            for _ in range(3):
                await self.cb.can_execute(TEST_MOD)

            stats = self.cb.get_stats()
            self.assertEqual(stats[TEST_MOD]["rejected_count"], 3)

        asyncio.get_event_loop().run_until_complete(test())

    def test_last_failure_time_updated(self):
        """测试最后失败时间被更新"""
        async def test():
            await self.cb.can_execute(TEST_MOD)
            before = time.time()
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)
            after = time.time()

            stats = self.cb.get_stats()
            last_failure = stats[TEST_MOD]["last_failure_time"]
            self.assertGreaterEqual(last_failure, before)
            self.assertLessEqual(last_failure, after)

        asyncio.get_event_loop().run_until_complete(test())


class TestCircuitBreakerHalfOpen(unittest.TestCase):
    """熔断器半开状态测试"""

    def setUp(self):
        from src.services.circuit_breaker import CircuitBreaker
        self.cb = CircuitBreaker(failure_threshold=3, recovery_time=1)  # 恢复时间1秒便于测试

    def test_recovery_time_transitions_to_half_open(self):
        """测试恢复时间过后进入半开状态"""
        async def test():
            # 触发熔断
            await self.cb.can_execute(TEST_MOD)
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            self.assertEqual(self.cb.get_state(TEST_MOD).value, "open")

            # 手动设置最后失败时间为过去的时间
            self.cb._last_failure_time[TEST_MOD] = time.time() - 2  # 2秒前，超过恢复时间

            # 下一次请求应该进入半开状态
            allowed = await self.cb.can_execute(TEST_MOD)
            self.assertTrue(allowed)
            self.assertEqual(self.cb.get_state(TEST_MOD).value, "half_open")

        asyncio.get_event_loop().run_until_complete(test())

    def test_half_open_limited_requests(self):
        """测试半开状态下只允许有限数量的探测请求"""
        async def test():
            # 触发熔断
            await self.cb.can_execute(TEST_MOD)
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            # 设置为已过恢复时间
            self.cb._last_failure_time[TEST_MOD] = time.time() - 2

            # 第一次调用触发 OPEN->HALF_OPEN 转换并放行（状态转换请求）
            # 之后默认有3个探测请求，所以总共4次通过，第5次被拒绝
            for i in range(4):
                allowed = await self.cb.can_execute(TEST_MOD)
                self.assertTrue(allowed, f"第 {i+1} 个请求应该被允许")

            # 第5个请求应该被拒绝
            allowed = await self.cb.can_execute(TEST_MOD)
            self.assertFalse(allowed)

        asyncio.get_event_loop().run_until_complete(test())

    def test_half_open_success_closes_circuit(self):
        """测试半开状态下成功请求恢复到关闭状态"""
        async def test():
            # 触发熔断
            await self.cb.can_execute(TEST_MOD)
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            # 设置为已过恢复时间
            self.cb._last_failure_time[TEST_MOD] = time.time() - 2

            # 半开状态下全部成功（默认half_open_max_requests=3）
            for _ in range(3):
                await self.cb.can_execute(TEST_MOD)
                await self.cb.record_success(TEST_MOD)

            # 应该恢复到关闭状态
            self.assertEqual(self.cb.get_state(TEST_MOD).value, "closed")

            # 失败计数应该被重置
            stats = self.cb.get_stats()
            self.assertEqual(stats[TEST_MOD]["failure_count"], 0)

        asyncio.get_event_loop().run_until_complete(test())

    def test_half_open_failure_reopens_circuit(self):
        """测试半开状态下失败立即回到熔断状态"""
        async def test():
            # 触发熔断
            await self.cb.can_execute(TEST_MOD)
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            # 设置为已过恢复时间
            self.cb._last_failure_time[TEST_MOD] = time.time() - 2

            # 第一个探测请求失败
            await self.cb.can_execute(TEST_MOD)
            await self.cb.record_failure(TEST_MOD)

            # 应该立即回到熔断状态
            self.assertEqual(self.cb.get_state(TEST_MOD).value, "open")

        asyncio.get_event_loop().run_until_complete(test())


class TestIndependentCircuits(unittest.TestCase):
    """独立熔断器测试（不同路由独立熔断）"""

    def setUp(self):
        from src.services.circuit_breaker import CircuitBreaker
        self.cb = CircuitBreaker(failure_threshold=3, recovery_time=30)

    def test_modules_independent(self):
        """测试不同模块的熔断器独立"""
        async def test():
            # TEST_MOD 熔断
            await self.cb.can_execute(TEST_MOD)
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            self.assertEqual(self.cb.get_state(TEST_MOD).value, "open")

            # TEST_MOD_2 应该仍然正常
            self.assertEqual(self.cb.get_state(TEST_MOD_2).value, "closed")
            allowed = await self.cb.can_execute(TEST_MOD_2)
            self.assertTrue(allowed)

        asyncio.get_event_loop().run_until_complete(test())

    def test_all_12_modules_have_config(self):
        """测试所有12个模块都有熔断器配置"""
        stats = self.cb.get_stats()
        for i in range(1, 13):
            key = f"m{i}"
            self.assertIn(key, stats, f"模块 {key} 应该有熔断器配置")

    def test_different_failure_thresholds(self):
        """测试不同模块可以有不同的熔断阈值"""
        stats = self.cb.get_stats()
        # m8 和 m12 的熔断阈值是10，m1 是5，m3 是3
        self.assertEqual(stats["m8"]["failure_threshold"], 10)
        self.assertEqual(stats["m12"]["failure_threshold"], 10)
        self.assertEqual(stats["m1"]["failure_threshold"], 5)
        self.assertEqual(stats["m3"]["failure_threshold"], 3)

    def test_m3_triggers_faster(self):
        """测试 m3 模块（阈值为3）比 m1（阈值为5）更快熔断"""
        async def test():
            # m1 失败3次，应该还没熔断
            await self.cb.can_execute("m1")
            for _ in range(3):
                await self.cb.record_failure("m1")
            self.assertEqual(self.cb.get_state("m1").value, "closed")

            # m3 失败3次，应该熔断了
            await self.cb.can_execute("m3")
            for _ in range(3):
                await self.cb.record_failure("m3")
            self.assertEqual(self.cb.get_state("m3").value, "open")

        asyncio.get_event_loop().run_until_complete(test())


class TestCircuitBreakerReset(unittest.TestCase):
    """熔断器重置测试"""

    def setUp(self):
        from src.services.circuit_breaker import CircuitBreaker
        self.cb = CircuitBreaker(failure_threshold=3, recovery_time=30)

    def test_reset_single_circuit(self):
        """测试重置单个熔断器"""
        async def test():
            # 触发熔断
            await self.cb.can_execute(TEST_MOD)
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            self.assertEqual(self.cb.get_state(TEST_MOD).value, "open")

            # 重置
            result = await self.cb.reset(TEST_MOD)
            self.assertTrue(result)

            self.assertEqual(self.cb.get_state(TEST_MOD).value, "closed")
            stats = self.cb.get_stats()
            self.assertEqual(stats[TEST_MOD]["failure_count"], 0)

        asyncio.get_event_loop().run_until_complete(test())

    def test_reset_existing_route_circuit(self):
        """测试重置路由配置中存在的模块熔断器"""
        async def test():
            # 先触发 m1 熔断（需要5次失败）
            await self.cb.can_execute("m1")
            for _ in range(5):
                await self.cb.record_failure("m1")

            self.assertEqual(self.cb.get_state("m1").value, "open")

            # 重置
            result = await self.cb.reset("m1")
            self.assertTrue(result)
            self.assertEqual(self.cb.get_state("m1").value, "closed")

        asyncio.get_event_loop().run_until_complete(test())

    def test_reset_nonexistent_circuit(self):
        """测试重置不存在的熔断器返回 False"""
        async def test():
            # 使用一个从未访问过的 key
            result = await self.cb.reset("completely_new_key")
            # 因为 _states 是 defaultdict，get_state 会创建条目
            # 但 reset 检查的是 key in self._states，如果从未访问过则返回 False
            self.assertFalse(result)

        asyncio.get_event_loop().run_until_complete(test())

    def test_reset_all(self):
        """测试重置所有熔断器"""
        async def test():
            # 熔断多个模块
            for module in [TEST_MOD, TEST_MOD_2]:
                await self.cb.can_execute(module)
                for _ in range(3):
                    await self.cb.record_failure(module)

            # 确认都已熔断
            for module in [TEST_MOD, TEST_MOD_2]:
                self.assertEqual(self.cb.get_state(module).value, "open")

            # 重置所有
            await self.cb.reset_all()

            # 确认都已恢复
            for module in [TEST_MOD, TEST_MOD_2]:
                self.assertEqual(self.cb.get_state(module).value, "closed")

        asyncio.get_event_loop().run_until_complete(test())


class TestCircuitBreakerStats(unittest.TestCase):
    """熔断器统计测试"""

    def setUp(self):
        from src.services.circuit_breaker import CircuitBreaker
        self.cb = CircuitBreaker(failure_threshold=5, recovery_time=30)

    def test_stats_structure(self):
        """测试统计信息结构"""
        stats = self.cb.get_stats()
        # 至少有一个模块的统计（因为 _init_from_routes 会初始化配置）
        self.assertGreater(len(stats), 0)

        module_key = list(stats.keys())[0]
        module_stats = stats[module_key]

        self.assertIn("state", module_stats)
        self.assertIn("failure_count", module_stats)
        self.assertIn("failure_threshold", module_stats)
        self.assertIn("recovery_time_seconds", module_stats)
        self.assertIn("last_failure_time", module_stats)
        self.assertIn("last_state_change", module_stats)
        self.assertIn("time_since_state_change", module_stats)
        self.assertIn("time_until_recovery", module_stats)
        self.assertIn("total_requests", module_stats)
        self.assertIn("success_count", module_stats)
        self.assertIn("failure_count_total", module_stats)
        self.assertIn("rejected_count", module_stats)
        self.assertIn("state_changes", module_stats)

    def test_success_count(self):
        """测试成功计数"""
        async def test():
            for _ in range(5):
                await self.cb.can_execute(TEST_MOD)
                await self.cb.record_success(TEST_MOD)

            stats = self.cb.get_stats()
            self.assertEqual(stats[TEST_MOD]["success_count"], 5)
            self.assertEqual(stats[TEST_MOD]["total_requests"], 5)

        asyncio.get_event_loop().run_until_complete(test())

    def test_failure_count_total(self):
        """测试总失败计数"""
        async def test():
            await self.cb.can_execute(TEST_MOD)
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            stats = self.cb.get_stats()
            self.assertEqual(stats[TEST_MOD]["failure_count_total"], 3)

        asyncio.get_event_loop().run_until_complete(test())

    def test_state_changes_count(self):
        """测试状态变化计数"""
        async def test():
            # 先访问一次以初始化统计
            await self.cb.can_execute(TEST_MOD)
            stats_before = self.cb.get_stats()
            initial_changes = stats_before[TEST_MOD]["state_changes"]

            # 触发熔断（状态变化 1 次）
            for _ in range(5):
                await self.cb.record_failure(TEST_MOD)

            stats_after = self.cb.get_stats()
            self.assertEqual(
                stats_after[TEST_MOD]["state_changes"],
                initial_changes + 1
            )

        asyncio.get_event_loop().run_until_complete(test())

    def test_time_until_recovery_in_open_state(self):
        """测试熔断状态下的恢复剩余时间"""
        async def test():
            await self.cb.can_execute(TEST_MOD)
            for _ in range(5):
                await self.cb.record_failure(TEST_MOD)

            stats = self.cb.get_stats()
            self.assertGreater(stats[TEST_MOD]["time_until_recovery"], 0)
            self.assertLessEqual(stats[TEST_MOD]["time_until_recovery"], 30)

        asyncio.get_event_loop().run_until_complete(test())


class TestFallbackResponse(unittest.TestCase):
    """降级响应测试"""

    def setUp(self):
        from src.services.circuit_breaker import CircuitBreaker
        self.cb = CircuitBreaker(failure_threshold=5, recovery_time=30)

    def test_fallback_response_structure(self):
        """测试降级响应结构"""
        response = self.cb.get_fallback_response(TEST_MOD)
        self.assertEqual(response["code"], 503)
        self.assertIn("message", response)
        self.assertIn("data", response)
        self.assertIn("module", response["data"])
        self.assertIn("reason", response["data"])
        self.assertIn("retry_after", response["data"])
        self.assertEqual(response["data"]["reason"], "circuit_breaker_open")

    def test_fallback_includes_module_name(self):
        """测试降级响应包含模块名称"""
        response = self.cb.get_fallback_response("m8")
        self.assertEqual(response["data"]["module"], "m8")
        self.assertIn("M8", response["data"]["module_name"])

    def test_fallback_retry_after_matches_config(self):
        """测试降级响应的重试时间与配置恢复时间一致"""
        # 对于自定义模块，使用默认配置的恢复时间
        response = self.cb.get_fallback_response(TEST_MOD)
        self.assertEqual(response["data"]["retry_after"], 30)

    def test_fallback_for_m1_module(self):
        """测试 m1 模块的降级响应（验证路由配置读取）"""
        response = self.cb.get_fallback_response("m1")
        # m1 的 cb_recovery_time 是 30 秒
        self.assertEqual(response["data"]["retry_after"], 30)
        self.assertIn("M1", response["data"]["module_name"])

    def test_fallback_for_unknown_module(self):
        """测试未知模块的降级响应"""
        response = self.cb.get_fallback_response("nonexistent_xyz")
        self.assertEqual(response["code"], 503)
        self.assertEqual(response["data"]["module"], "nonexistent_xyz")
        # 未知模块使用默认恢复时间
        self.assertEqual(response["data"]["retry_after"], 30)


class TestCircuitBreakerConfig(unittest.TestCase):
    """熔断器配置测试"""

    def test_default_config_for_new_module(self):
        """测试新模块使用默认配置"""
        from src.services.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=10, recovery_time=60)

        config = cb._get_config("brand_new_module")
        self.assertEqual(config.failure_threshold, 10)
        self.assertEqual(config.recovery_time, 60)

    def test_route_config_overrides_default(self):
        """测试路由配置覆盖默认配置"""
        from src.services.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=5, recovery_time=30)

        # m8 的熔断阈值应该是10，恢复时间15（从路由配置读取）
        stats = cb.get_stats()
        self.assertEqual(stats["m8"]["failure_threshold"], 10)
        self.assertEqual(stats["m8"]["recovery_time_seconds"], 15)

    def test_m3_strict_config(self):
        """测试 m3 模块的严格熔断配置"""
        from src.services.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=5, recovery_time=30)

        stats = cb.get_stats()
        # m3 的失败阈值是 3，恢复时间是 60 秒
        self.assertEqual(stats["m3"]["failure_threshold"], 3)
        self.assertEqual(stats["m3"]["recovery_time_seconds"], 60)


class TestCircuitBreakerSingleton(unittest.TestCase):
    """熔断器单例测试"""

    def test_get_circuit_breaker_returns_instance(self):
        """测试 get_circuit_breaker 返回实例"""
        from src.services.circuit_breaker import get_circuit_breaker, CircuitBreaker
        cb = get_circuit_breaker()
        self.assertIsInstance(cb, CircuitBreaker)

    def test_get_circuit_breaker_singleton(self):
        """测试 get_circuit_breaker 是单例"""
        from src.services.circuit_breaker import get_circuit_breaker
        cb1 = get_circuit_breaker()
        cb2 = get_circuit_breaker()
        self.assertIs(cb1, cb2)


class TestCircuitBreakerStateTransitions(unittest.TestCase):
    """完整状态转换测试"""

    def setUp(self):
        from src.services.circuit_breaker import CircuitBreaker
        self.cb = CircuitBreaker(failure_threshold=3, recovery_time=1)

    def test_full_lifecycle(self):
        """测试完整生命周期：Closed -> Open -> Half-Open -> Closed"""
        async def test():
            # 1. Closed 状态
            self.assertEqual(self.cb.get_state(TEST_MOD).value, "closed")

            # 2. 失败触发 Open
            await self.cb.can_execute(TEST_MOD)
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)
            self.assertEqual(self.cb.get_state(TEST_MOD).value, "open")

            # 3. 等待恢复时间，进入 Half-Open
            self.cb._last_failure_time[TEST_MOD] = time.time() - 2
            allowed = await self.cb.can_execute(TEST_MOD)
            self.assertTrue(allowed)
            self.assertEqual(self.cb.get_state(TEST_MOD).value, "half_open")

            # 4. 半开状态全部成功，回到 Closed
            for _ in range(3):
                await self.cb.can_execute(TEST_MOD)
                await self.cb.record_success(TEST_MOD)
            self.assertEqual(self.cb.get_state(TEST_MOD).value, "closed")

        asyncio.get_event_loop().run_until_complete(test())

    def test_full_lifecycle_with_half_open_failure(self):
        """测试完整生命周期：Closed -> Open -> Half-Open -> Open"""
        async def test():
            # 1. Closed -> Open
            await self.cb.can_execute(TEST_MOD)
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)
            self.assertEqual(self.cb.get_state(TEST_MOD).value, "open")

            # 2. Open -> Half-Open
            self.cb._last_failure_time[TEST_MOD] = time.time() - 2
            await self.cb.can_execute(TEST_MOD)
            self.assertEqual(self.cb.get_state(TEST_MOD).value, "half_open")

            # 3. Half-Open -> Open（失败）
            await self.cb.record_failure(TEST_MOD)
            self.assertEqual(self.cb.get_state(TEST_MOD).value, "open")

        asyncio.get_event_loop().run_until_complete(test())

    def test_multiple_state_transitions(self):
        """测试多次状态转换"""
        async def test():
            # 先访问一次以初始化统计
            await self.cb.can_execute(TEST_MOD)
            stats_before = self.cb.get_stats()
            changes_before = stats_before[TEST_MOD]["state_changes"]

            # 第一次熔断
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            # 重置
            await self.cb.reset(TEST_MOD)

            # 第二次熔断
            for _ in range(3):
                await self.cb.record_failure(TEST_MOD)

            stats_after = self.cb.get_stats()
            # 至少有3次状态变化：2次熔断 + 1次重置
            self.assertGreaterEqual(
                stats_after[TEST_MOD]["state_changes"] - changes_before, 3
            )

        asyncio.get_event_loop().run_until_complete(test())


if __name__ == "__main__":
    unittest.main(verbosity=2)
