"""
ModuleClient 测试 - 调用/重试/熔断/超时/负载均衡
"""

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from shared.module_sdk.module_client import (
    ModuleClient,
    CircuitBreaker,
    LoadBalancer,
)
from shared.module_sdk.models import (
    ServiceInstance,
    ServiceStatus,
    LoadBalanceStrategy,
    CircuitState,
    SdkErrorCode,
    ApiResponse,
)
from shared.module_sdk.registry import (
    InMemoryRegistry,
    reset_registry_client,
)


# ============================================================
# CircuitBreaker 测试
# ============================================================

class TestCircuitBreaker:
    """熔断器测试"""

    def test_initial_state_closed(self):
        """测试初始状态为关闭"""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_opens_after_failures(self):
        """测试失败次数达到阈值后打开"""
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=10)

        assert cb.allow_request() is True
        cb.record_failure()
        assert cb.allow_request() is True
        cb.record_failure()
        assert cb.allow_request() is True
        cb.record_failure()
        # 第 3 次失败后打开
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_recovery_timeout(self):
        """测试冷却时间过后进入半开状态"""
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout=0.01)

        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

        # 等待冷却
        time.sleep(0.02)

        # 进入半开状态
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_recovers(self):
        """测试半开状态成功后恢复关闭"""
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout=0.01)

        # 打开
        cb.record_failure()
        cb.record_failure()

        # 等待冷却
        time.sleep(0.02)

        # 半开 + 成功
        assert cb.allow_request() is True
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_half_open_failure_reopens(self):
        """测试半开状态失败后重新打开"""
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout=0.01)

        # 打开
        cb.record_failure()
        cb.record_failure()

        # 等待冷却
        time.sleep(0.02)

        # 半开 + 失败
        assert cb.allow_request() is True
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_half_open_limited_calls(self):
        """测试半开状态限制调用次数"""
        cb = CircuitBreaker(
            name="test", failure_threshold=2,
            recovery_timeout=0.01, half_open_max_calls=2,
        )

        # 打开
        cb.record_failure()
        cb.record_failure()

        # 等待冷却
        time.sleep(0.02)

        # 半开状态最多允许 half_open_max_calls 个请求
        assert cb.allow_request() is True
        assert cb.allow_request() is True
        assert cb.allow_request() is False  # 第 3 个被拒绝

    def test_reset(self):
        """测试重置熔断器"""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_get_stats(self):
        """测试获取统计信息"""
        cb = CircuitBreaker(name="test", failure_threshold=5, recovery_timeout=30)
        stats = cb.get_stats()
        assert stats["state"] == "closed"
        assert stats["failure_threshold"] == 5
        assert stats["recovery_timeout"] == 30
        assert stats["failure_count"] == 0


# ============================================================
# LoadBalancer 测试
# ============================================================

class TestLoadBalancer:
    """负载均衡器测试"""

    def _make_instance(self, iid, weight=1):
        return ServiceInstance(
            service_name="test",
            instance_id=iid,
            address="127.0.0.1",
            port=8000,
            weight=weight,
        )

    def test_round_robin(self):
        """测试轮询策略"""
        lb = LoadBalancer(strategy=LoadBalanceStrategy.ROUND_ROBIN)
        instances = [self._make_instance("a"), self._make_instance("b"), self._make_instance("c")]
        lb.update_instances(instances)

        results = [lb.select_instance().instance_id for _ in range(6)]
        assert results == ["a", "b", "c", "a", "b", "c"]

    def test_random(self):
        """测试随机策略"""
        lb = LoadBalancer(strategy=LoadBalanceStrategy.RANDOM)
        instances = [self._make_instance("a"), self._make_instance("b")]
        lb.update_instances(instances)

        # 多次选择应该都是 a 或 b
        for _ in range(20):
            inst = lb.select_instance()
            assert inst.instance_id in ("a", "b")

    def test_weighted_round_robin(self):
        """测试加权轮询"""
        lb = LoadBalancer(strategy=LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN)
        instances = [
            self._make_instance("a", weight=3),
            self._make_instance("b", weight=1),
        ]
        lb.update_instances(instances)

        # 4 次调用应该覆盖一个完整周期（3个a + 1个b）
        results = [lb.select_instance().instance_id for _ in range(4)]
        assert "a" in results
        assert "b" in results
        assert results.count("a") >= results.count("b")

    def test_consistent_hash(self):
        """测试一致性哈希"""
        lb = LoadBalancer(strategy=LoadBalanceStrategy.CONSISTENT_HASH)
        instances = [self._make_instance("a"), self._make_instance("b"), self._make_instance("c")]
        lb.update_instances(instances)

        # 相同 key 应该返回相同实例
        r1 = lb.select_instance(hash_key="user-123")
        r2 = lb.select_instance(hash_key="user-123")
        assert r1.instance_id == r2.instance_id

    def test_no_instances(self):
        """测试无实例时返回 None"""
        lb = LoadBalancer()
        assert lb.select_instance() is None

    def test_update_instances(self):
        """测试更新实例列表"""
        lb = LoadBalancer(strategy=LoadBalanceStrategy.ROUND_ROBIN)
        assert lb.instance_count == 0

        instances = [self._make_instance("a")]
        lb.update_instances(instances)
        assert lb.instance_count == 1

        instances2 = [self._make_instance("a"), self._make_instance("b")]
        lb.update_instances(instances2)
        assert lb.instance_count == 2


# ============================================================
# ModuleClient 测试
# ============================================================

class TestModuleClient:
    """ModuleClient 测试"""

    def setup_method(self):
        reset_registry_client()

    def teardown_method(self):
        reset_registry_client()

    def test_initialization(self):
        """测试基本初始化"""
        client = ModuleClient("m1")
        assert client.module_name == "m1"
        assert client.timeout == 10.0
        assert client.max_retries == 2

    def test_custom_config(self):
        """测试自定义配置"""
        config = {
            "timeout": 5.0,
            "max_retries": 3,
            "retry_backoff": 0.1,
            "circuit_breaker_enabled": False,
        }
        client = ModuleClient("m1", config=config)
        assert client.timeout == 5.0
        assert client.max_retries == 3
        assert client.retry_backoff == 0.1
        assert client.circuit_breaker_enabled is False

    def test_module_name_lowercase(self):
        """测试模块名转为小写"""
        client = ModuleClient("M1")
        assert client.module_name == "m1"

    def test_no_healthy_instances(self):
        """测试无健康实例时返回错误"""
        client = ModuleClient(
            "nonexistent_module",
            config={"service_discovery_enabled": True},
        )
        # 使用内存注册中心，没有注册任何实例
        import asyncio
        result = asyncio.run(client.get("/test"))
        assert result.is_success is False
        assert result.code == SdkErrorCode.NO_HEALTHY_INSTANCE

    def test_call_with_default_base_url(self):
        """测试使用默认 base_url（无服务发现时）"""
        import asyncio

        client = ModuleClient(
            "m1",
            config={
                "service_discovery_enabled": False,
                "default_base_url": "http://127.0.0.1:9999",
                "max_retries": 0,
                "timeout": 0.5,
                "circuit_breaker_enabled": False,
            },
        )

        # 没有真实服务，应该调用失败并耗尽重试
        result = asyncio.run(client.get("/health"))
        assert result.is_success is False
        # 因为没有服务发现，走默认 base_url，连接失败后重试耗尽
        assert result.code == SdkErrorCode.CALL_RETRY_EXHAUSTED

    def test_service_discovery_integration(self):
        """测试与注册中心的集成"""
        from shared.module_sdk.registry import ServiceRegistryClient

        registry = ServiceRegistryClient(mode="memory")
        registry.register("m1", "m1-1", "127.0.0.1", 9999)

        client = ModuleClient(
            "m1",
            config={
                "service_discovery_enabled": True,
                "max_retries": 0,
                "timeout": 0.5,
                "circuit_breaker_enabled": False,
            },
            registry=registry,
        )

        # 强制发现
        instances = client.force_discover()
        assert len(instances) == 1
        assert instances[0].instance_id == "m1-1"

        registry.close()

    def test_reset_circuit_breakers(self):
        """测试重置熔断器"""
        client = ModuleClient("m1", config={"circuit_breaker_enabled": True})
        client.reset_circuit_breakers()
        stats = client.get_circuit_breaker_stats()
        assert isinstance(stats, dict)

    def test_clear_blacklist(self):
        """测试清空黑名单"""
        client = ModuleClient("m1")
        client._blacklist_instance("test-instance")
        assert len(client._blacklisted_instances) == 1
        client.clear_blacklist()
        assert len(client._blacklisted_instances) == 0

    def test_blacklist_expiry(self):
        """测试黑名单过期"""
        client = ModuleClient("m1", config={"blacklist_timeout": 0.01})
        client._blacklist_instance("test-1")
        assert "test-1" in client._blacklisted_instances

        time.sleep(0.02)
        client._clean_blacklist()
        assert "test-1" not in client._blacklisted_instances


# ============================================================
# 熔断器与客户端集成测试
# ============================================================

class TestCircuitBreakerIntegration:
    """熔断器与客户端集成测试"""

    def test_circuit_breaker_per_instance(self):
        """测试每个实例独立的熔断器"""
        client = ModuleClient("m1", config={"circuit_failure_threshold": 3})

        # 获取不同实例的熔断器
        cb1 = client._get_circuit_breaker("inst-1")
        cb2 = client._get_circuit_breaker("inst-2")

        assert cb1 is not cb2
        assert cb1.name == "m1/inst-1"
        assert cb2.name == "m1/inst-2"

    def test_circuit_breaker_disabled(self):
        """测试禁用熔断器"""
        client = ModuleClient("m1", config={"circuit_breaker_enabled": False})
        # 禁用时仍可获取熔断器，但不会使用
        cb = client._get_circuit_breaker("test")
        assert cb is not None


# ============================================================
# 便捷方法测试
# ============================================================

class TestConvenienceMethods:
    """便捷方法测试"""

    def setup_method(self):
        reset_registry_client()

    def teardown_method(self):
        reset_registry_client()

    def test_get_method_exists(self):
        """测试 get 方法存在"""
        client = ModuleClient("m1")
        assert callable(client.get)

    def test_post_method_exists(self):
        """测试 post 方法存在"""
        client = ModuleClient("m1")
        assert callable(client.post)

    def test_put_method_exists(self):
        """测试 put 方法存在"""
        client = ModuleClient("m1")
        assert callable(client.put)

    def test_delete_method_exists(self):
        """测试 delete 方法存在"""
        client = ModuleClient("m1")
        assert callable(client.delete)

    def test_call_method_exists(self):
        """测试 call 方法存在"""
        client = ModuleClient("m1")
        assert callable(client.call)


# ============================================================
# 负载均衡多实例测试
# ============================================================

class TestLoadBalancerMultiInstance:
    """多实例负载均衡测试"""

    def _make_instances(self, n):
        return [
            ServiceInstance(
                service_name="test",
                instance_id=f"inst-{i}",
                address="127.0.0.1",
                port=8000 + i,
            )
            for i in range(n)
        ]

    def test_round_robin_distribution(self):
        """测试轮询分布均匀"""
        lb = LoadBalancer(strategy=LoadBalanceStrategy.ROUND_ROBIN)
        lb.update_instances(self._make_instances(3))

        counts = {}
        for _ in range(30):
            inst = lb.select_instance()
            counts[inst.instance_id] = counts.get(inst.instance_id, 0) + 1

        # 30次请求，3个实例，每个应该10次
        for iid, count in counts.items():
            assert count == 10, f"{iid}: {count}"

    def test_instance_update_resets_round_robin(self):
        """测试更新实例后重置轮询索引"""
        lb = LoadBalancer(strategy=LoadBalanceStrategy.ROUND_ROBIN)
        lb.update_instances(self._make_instances(2))

        # 先选 1 次
        lb.select_instance()

        # 更新实例
        lb.update_instances(self._make_instances(3))

        # 应该从第一个开始
        inst = lb.select_instance()
        assert inst.instance_id == "inst-0"
