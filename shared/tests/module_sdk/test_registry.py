"""
服务注册中心测试 - 注册/发现/心跳/健康检查
"""

import sys
import time
from pathlib import Path

import pytest

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from shared.module_sdk.registry import (
    InMemoryRegistry,
    ServiceRegistryClient,
    get_registry_client,
    reset_registry_client,
)
from shared.module_sdk.models import ServiceStatus, ServiceInstance


# ============================================================
# InMemoryRegistry 测试
# ============================================================

class TestInMemoryRegistry:
    """内存注册中心测试"""

    def setup_method(self):
        """每个测试前创建新实例"""
        self.registry = InMemoryRegistry()

    def teardown_method(self):
        """每个测试后清理"""
        self.registry.clear()
        self.registry.stop_auto_cleanup()

    def test_register_single_instance(self):
        """测试注册单个实例"""
        result = self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        assert result is True

        instances = self.registry.discover("m1")
        assert len(instances) == 1
        assert instances[0].service_name == "m1"
        assert instances[0].instance_id == "m1-1"
        assert instances[0].address == "127.0.0.1"
        assert instances[0].port == 8001

    def test_register_multiple_instances(self):
        """测试注册多个实例"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        self.registry.register("m1", "m1-2", "127.0.0.1", 8002)
        self.registry.register("m2", "m2-1", "127.0.0.1", 8003)

        m1_instances = self.registry.discover("m1")
        assert len(m1_instances) == 2

        m2_instances = self.registry.discover("m2")
        assert len(m2_instances) == 1

    def test_register_duplicate_updates(self):
        """测试重复注册会更新"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001, version="1.0.0")
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001, version="2.0.0")

        instances = self.registry.discover("m1")
        assert len(instances) == 1
        assert instances[0].version == "2.0.0"

    def test_deregister(self):
        """测试注销"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        assert len(self.registry.discover("m1")) == 1

        result = self.registry.deregister("m1", "m1-1")
        assert result is True
        assert len(self.registry.discover("m1")) == 0

    def test_deregister_nonexistent(self):
        """测试注销不存在的实例"""
        result = self.registry.deregister("m1", "m1-999")
        assert result is False

    def test_heartbeat(self):
        """测试心跳"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)

        # 先让时间前进一点
        time.sleep(0.01)

        before = time.time()
        result = self.registry.heartbeat("m1", "m1-1")
        assert result is True

        instance = self.registry.get_instance("m1", "m1-1")
        assert instance is not None
        assert instance.last_heartbeat >= before

    def test_heartbeat_nonexistent(self):
        """测试不存在实例的心跳"""
        result = self.registry.heartbeat("m1", "m1-999")
        assert result is False

    def test_discover_returns_healthy_only(self):
        """测试 discover 只返回健康实例"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        self.registry.register("m1", "m1-2", "127.0.0.1", 8002)

        # 将 m1-2 标记为不健康
        inst = self.registry.get_instance("m1", "m1-2")
        inst.status = ServiceStatus.UNHEALTHY

        instances = self.registry.discover("m1")
        assert len(instances) == 1
        assert instances[0].instance_id == "m1-1"

    def test_discover_nonexistent_service(self):
        """测试发现不存在的服务"""
        instances = self.registry.discover("nonexistent")
        assert instances == []

    def test_get_all_services(self):
        """测试获取所有服务"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        self.registry.register("m2", "m2-1", "127.0.0.1", 8002)

        all_services = self.registry.get_all_services()
        assert "m1" in all_services
        assert "m2" in all_services
        assert len(all_services["m1"]) == 1
        assert len(all_services["m2"]) == 1

    def test_get_service_names(self):
        """测试获取服务名称列表"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        self.registry.register("m2", "m2-1", "127.0.0.1", 8002)

        names = self.registry.get_service_names()
        assert "m1" in names
        assert "m2" in names
        assert len(names) == 2

    def test_has_service(self):
        """测试 has_service"""
        assert self.registry.has_service("m1") is False
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        assert self.registry.has_service("m1") is True

    def test_get_instance(self):
        """测试获取单个实例"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001, metadata={"env": "test"})

        inst = self.registry.get_instance("m1", "m1-1")
        assert inst is not None
        assert inst.instance_id == "m1-1"
        assert inst.metadata == {"env": "test"}

        assert self.registry.get_instance("m1", "nonexistent") is None
        assert self.registry.get_instance("nonexistent", "m1-1") is None

    def test_get_all_instances(self):
        """测试获取所有实例（含不健康的）"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        self.registry.register("m1", "m1-2", "127.0.0.1", 8002)

        inst = self.registry.get_instance("m1", "m1-2")
        inst.status = ServiceStatus.UNHEALTHY

        all_instances = self.registry.get_all_instances("m1")
        assert len(all_instances) == 2

        healthy = self.registry.discover("m1")
        assert len(healthy) == 1

    def test_service_name_case_insensitive(self):
        """测试服务名不区分大小写"""
        self.registry.register("M1", "m1-1", "127.0.0.1", 8001)
        instances = self.registry.discover("m1")
        assert len(instances) == 1
        assert instances[0].service_name == "m1"

    def test_get_stats(self):
        """测试统计信息"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        self.registry.register("m1", "m1-2", "127.0.0.1", 8002)
        self.registry.register("m2", "m2-1", "127.0.0.1", 8003)

        stats = self.registry.get_stats()
        assert stats["service_count"] == 2
        assert stats["total_instances"] == 3
        assert stats["healthy_instances"] == 3

    def test_register_with_metadata(self):
        """测试带元数据注册"""
        self.registry.register(
            "m1", "m1-1", "127.0.0.1", 8001,
            metadata={"zone": "east", "rack": "r1"},
        )
        inst = self.registry.get_instance("m1", "m1-1")
        assert inst.metadata["zone"] == "east"
        assert inst.metadata["rack"] == "r1"

    def test_weight(self):
        """测试权重"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001, weight=3)
        inst = self.registry.get_instance("m1", "m1-1")
        assert inst.weight == 3


# ============================================================
# ServiceRegistryClient 测试
# ============================================================

class TestServiceRegistryClient:
    """统一注册中心客户端测试"""

    def setup_method(self):
        reset_registry_client()

    def teardown_method(self):
        reset_registry_client()

    def test_memory_mode(self):
        """测试内存模式"""
        client = ServiceRegistryClient(mode="memory")
        assert client.mode == "memory"

        client.register("m1", "m1-1", "127.0.0.1", 8001)
        instances = client.discover("m1")
        assert len(instances) == 1
        client.close()

    def test_invalid_mode(self):
        """测试无效模式"""
        with pytest.raises(ValueError, match="Unsupported registry mode"):
            ServiceRegistryClient(mode="invalid")

    def test_get_registry_client_singleton(self):
        """测试全局单例"""
        client1 = get_registry_client()
        client2 = get_registry_client()
        assert client1 is client2

    def test_reset_registry_client(self):
        """测试重置单例"""
        client1 = get_registry_client()
        reset_registry_client()
        client2 = get_registry_client()
        assert client1 is not client2

    def test_register_and_discover(self):
        """测试注册发现流程"""
        client = ServiceRegistryClient(mode="memory")

        # 注册
        result = client.register("test", "test-1", "127.0.0.1", 9001)
        assert result is True

        # 发现
        instances = client.discover("test")
        assert len(instances) == 1
        assert instances[0].instance_id == "test-1"

        # 注销
        result = client.deregister("test", "test-1")
        assert result is True

        # 再次发现
        instances = client.discover("test")
        assert len(instances) == 0

        client.close()

    def test_heartbeat(self):
        """测试心跳"""
        client = ServiceRegistryClient(mode="memory")
        client.register("test", "test-1", "127.0.0.1", 9001)

        result = client.heartbeat("test", "test-1")
        assert result is True

        result = client.heartbeat("test", "nonexistent")
        assert result is False

        client.close()

    def test_get_all_services(self):
        """测试获取所有服务"""
        client = ServiceRegistryClient(mode="memory")
        client.register("s1", "s1-1", "127.0.0.1", 9001)
        client.register("s2", "s2-1", "127.0.0.1", 9002)

        services = client.get_all_services()
        assert "s1" in services
        assert "s2" in services

        client.close()

    def test_has_service(self):
        """测试 has_service"""
        client = ServiceRegistryClient(mode="memory")
        assert client.has_service("s1") is False
        client.register("s1", "s1-1", "127.0.0.1", 9001)
        assert client.has_service("s1") is True
        client.close()

    def test_get_instance(self):
        """测试获取实例"""
        client = ServiceRegistryClient(mode="memory")
        client.register("s1", "s1-1", "127.0.0.1", 9001, version="1.0")

        inst = client.get_instance("s1", "s1-1")
        assert inst is not None
        assert inst.version == "1.0"

        assert client.get_instance("s1", "nonexistent") is None
        client.close()

    def test_get_stats(self):
        """测试统计"""
        client = ServiceRegistryClient(mode="memory")
        client.register("s1", "s1-1", "127.0.0.1", 9001)
        stats = client.get_stats()
        assert stats["service_count"] == 1
        client.close()
