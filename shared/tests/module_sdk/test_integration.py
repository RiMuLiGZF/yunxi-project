"""
SDK 集成测试 - 端到端调用、向后兼容
"""

import sys
import time
from pathlib import Path

import pytest

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from shared.module_sdk import (
    ModuleClient,
    ServiceRegistryClient,
    EventBus,
    ModuleAutoRegister,
    ApiResponse,
    ServiceInstance,
    ServiceStatus,
    Event,
    SdkErrorCode,
    get_registry_client,
    get_event_bus,
    reset_registry_client,
    reset_event_bus,
)


# ============================================================
# 集成测试：注册 + 发现 + 调用
# ============================================================

class TestIntegrationRegistryDiscovery:
    """注册与发现集成测试"""

    def setup_method(self):
        reset_registry_client()
        self.registry = ServiceRegistryClient(mode="memory")

    def teardown_method(self):
        self.registry.close()
        reset_registry_client()

    def test_register_and_discover(self):
        """测试注册后能发现"""
        # 注册
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        self.registry.register("m1", "m1-2", "127.0.0.1", 8002)

        # 发现
        instances = self.registry.discover("m1")
        assert len(instances) == 2
        assert all(isinstance(i, ServiceInstance) for i in instances)

    def test_deregister_and_discover(self):
        """测试注销后不再被发现"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        self.registry.register("m1", "m1-2", "127.0.0.1", 8002)

        assert len(self.registry.discover("m1")) == 2

        self.registry.deregister("m1", "m1-1")
        instances = self.registry.discover("m1")
        assert len(instances) == 1
        assert instances[0].instance_id == "m1-2"

    def test_heartbeat_maintains_health(self):
        """测试心跳维持健康状态"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)

        # 心跳
        for _ in range(5):
            ok = self.registry.heartbeat("m1", "m1-1")
            assert ok is True

        # 仍然健康
        instances = self.registry.discover("m1")
        assert len(instances) == 1
        assert instances[0].status == ServiceStatus.HEALTHY

    def test_multiple_services_isolated(self):
        """测试多个服务互相隔离"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        self.registry.register("m2", "m2-1", "127.0.0.1", 8002)
        self.registry.register("m2", "m2-2", "127.0.0.1", 8003)

        assert len(self.registry.discover("m1")) == 1
        assert len(self.registry.discover("m2")) == 2
        assert len(self.registry.discover("m3")) == 0

    def test_get_all_services(self):
        """测试获取所有服务"""
        self.registry.register("m1", "m1-1", "127.0.0.1", 8001)
        self.registry.register("m2", "m2-1", "127.0.0.1", 8002)

        all_services = self.registry.get_all_services()
        assert "m1" in all_services
        assert "m2" in all_services
        assert len(all_services) == 2


# ============================================================
# 集成测试：事件总线 + 注册中心联动
# ============================================================

class TestIntegrationEventBus:
    """事件总线集成测试"""

    def setup_method(self):
        reset_event_bus()

    def teardown_method(self):
        reset_event_bus()

    def test_publish_subscribe_flow(self):
        """完整的发布订阅流程"""
        bus = get_event_bus()

        results = []

        def handler(event):
            results.append({
                "type": event.event_type,
                "data": event.data,
                "source": event.source,
            })

        # 订阅
        sub_id = bus.subscribe("module.*", handler)
        assert isinstance(sub_id, str)

        # 发布
        bus.publish("module.started", {"module": "m1"}, source="m8")
        bus.publish("module.stopped", {"module": "m2"}, source="m8")
        bus.publish("other.event", {"x": 1}, source="m1")  # 不匹配

        # 验证
        assert len(results) == 2
        assert results[0]["type"] == "module.started"
        assert results[0]["data"] == {"module": "m1"}
        assert results[0]["source"] == "m8"
        assert results[1]["type"] == "module.stopped"

        # 取消订阅
        assert bus.unsubscribe(sub_id) is True

        # 再次发布，不再收到
        results.clear()
        bus.publish("module.started", {"module": "m3"}, source="m8")
        assert len(results) == 0

    def test_event_history_and_replay(self):
        """事件历史和重放集成测试"""
        bus = get_event_bus()

        # 发布一些事件
        for i in range(5):
            bus.publish(f"order.{i}", {"id": i}, source="m4")

        # 查询历史
        history = bus.get_history(event_type="order.*", limit=10)
        assert len(history) == 5

        # 重放
        replayed = []
        count = bus.replay("order.*", handler=lambda e: replayed.append(e))
        assert count == 5
        assert len(replayed) == 5
        # 按时间顺序
        assert replayed[0].event_type == "order.0"
        assert replayed[-1].event_type == "order.4"

    def test_wildcard_patterns(self):
        """通配符模式集成测试"""
        bus = EventBus(backend="memory")

        received = {
            "exact": [],
            "single": [],
            "multi": [],
            "all": [],
        }

        bus.subscribe("a.b.c", lambda e: received["exact"].append(e))
        bus.subscribe("a.*.c", lambda e: received["single"].append(e))
        bus.subscribe("a.#", lambda e: received["multi"].append(e))
        bus.subscribe("#", lambda e: received["all"].append(e))

        bus.publish("a.b.c", {})
        bus.publish("a.x.c", {})
        bus.publish("a.b.c.d", {})

        assert len(received["exact"]) == 1  # 只匹配 a.b.c
        assert len(received["single"]) == 2  # a.b.c 和 a.x.c
        assert len(received["multi"]) == 3  # 所有 a. 开头的
        assert len(received["all"]) == 3  # 所有


# ============================================================
# 集成测试：自动注册器 + 注册中心
# ============================================================

class TestIntegrationAutoRegister:
    """自动注册器集成测试"""

    def setup_method(self):
        reset_registry_client()
        self.registry = ServiceRegistryClient(mode="memory")

    def teardown_method(self):
        self.registry.close()
        reset_registry_client()

    def test_full_lifecycle(self):
        """完整生命周期：注册 -> 心跳 -> 注销"""
        registrar = ModuleAutoRegister(
            module_name="m1",
            instance_id="m1-test",
            address="127.0.0.1",
            port=8001,
            registry=self.registry,
            heartbeat_interval=0.01,
        )

        # 启动
        assert registrar.start() is True
        assert registrar.is_registered is True
        assert len(self.registry.discover("m1")) == 1

        # 等待心跳
        time.sleep(0.05)

        # 仍然健康
        instances = self.registry.discover("m1")
        assert len(instances) == 1
        assert instances[0].status == ServiceStatus.HEALTHY

        # 停止
        registrar.stop()
        assert registrar.is_registered is False
        assert len(self.registry.discover("m1")) == 0

    def test_multiple_modules(self):
        """多个模块同时注册"""
        regs = []
        for i in range(3):
            r = ModuleAutoRegister(
                module_name=f"m{i+1}",
                instance_id=f"m{i+1}-1",
                address="127.0.0.1",
                port=8001 + i,
                registry=self.registry,
                heartbeat_interval=0,
            )
            r.start()
            regs.append(r)

        # 所有服务都注册了
        assert len(self.registry.get_service_names()) == 3
        for i in range(3):
            assert len(self.registry.discover(f"m{i+1}")) == 1

        # 逐个注销
        for r in regs:
            r.stop()

        assert len(self.registry.get_service_names()) == 0


# ============================================================
# 向后兼容性测试
# ============================================================

class TestBackwardCompatibility:
    """向后兼容性测试"""

    def test_module_client_does_not_affect_existing(self):
        """新 SDK 的 ModuleClient 不影响现有 ModuleClient"""
        # 新 SDK 的 ModuleClient
        from shared.module_sdk import ModuleClient as NewClient
        # 旧的 ModuleClient
        from shared.business.module_client import ModuleClient as OldClient

        # 两者都存在且不同
        assert NewClient is not OldClient

    def test_new_sdk_is_additive(self):
        """新 SDK 是纯增量功能，不修改现有代码"""
        # 现有模块仍然可以导入
        from shared.business.module_client import (
            ModuleClient,
            ModuleRegistry,
            ModuleInfo,
        )
        assert ModuleClient is not None
        assert ModuleRegistry is not None
        assert ModuleInfo is not None

        # 新 SDK 也可以导入
        from shared.module_sdk import (
            ModuleClient as NewModuleClient,
            ServiceRegistryClient,
            EventBus,
        )
        assert NewModuleClient is not None
        assert ServiceRegistryClient is not None
        assert EventBus is not None

    def test_existing_registry_still_works(self):
        """现有的 core.ha.service_registry 仍然可用"""
        from shared.core.ha.service_registry import (
            ServiceRegistry as HaServiceRegistry,
            ServiceInstanceInfo,
            ServiceStatus,
        )
        assert HaServiceRegistry is not None
        assert ServiceInstanceInfo is not None
        assert ServiceStatus is not None

    def test_config_backward_compatible(self):
        """配置仍然向后兼容"""
        from shared.core.config import get_config

        config = get_config()
        # 旧的属性仍然可用
        assert hasattr(config, "module_base_urls")
        assert hasattr(config, "module_ports")
        # 新的 SDK 配置属性也可用
        assert hasattr(config, "service_registry_url")
        assert hasattr(config, "service_discovery_enabled")
        assert hasattr(config, "module_client_timeout")
        assert hasattr(config, "event_bus_backend")


# ============================================================
# SDK 入口测试
# ============================================================

class TestSdkEntryPoints:
    """SDK 入口点测试"""

    def test_import_from_package(self):
        """从包顶层导入"""
        from shared.module_sdk import (
            ApiResponse,
            ServiceInstance,
            ServiceStatus,
            Event,
            SdkErrorCode,
            LoadBalanceStrategy,
            CircuitState,
            ServiceRegistryClient,
            InMemoryRegistry,
            get_registry_client,
            reset_registry_client,
            EventBus,
            InMemoryEventBus,
            get_event_bus,
            reset_event_bus,
            ModuleClient,
            CircuitBreaker,
            LoadBalancer,
            ModuleAutoRegister,
            setup_module_registration,
            setup_module_registration_lifespan,
            auto_register_module,
        )
        # 全部能导入就通过
        assert True

    def test_version(self):
        """测试版本号"""
        import shared.module_sdk as sdk
        assert hasattr(sdk, "__version__")
        assert sdk.__version__ == "1.0.0"

    def test_api_response_success(self):
        """ApiResponse 成功响应"""
        resp = ApiResponse.success(data={"foo": "bar"})
        assert resp.is_success is True
        assert resp.code == 0
        assert resp.data == {"foo": "bar"}

    def test_api_response_error(self):
        """ApiResponse 错误响应"""
        resp = ApiResponse.error(code=SdkErrorCode.CALL_FAILED, message="call failed")
        assert resp.is_success is False
        assert resp.code == SdkErrorCode.CALL_FAILED
        assert resp.message == "call failed"

    def test_event_model(self):
        """Event 模型完整性"""
        event = Event(
            event_type="test.event",
            data={"key": "value"},
            source="m1",
            trace_id="trace-123",
        )
        assert event.event_id is not None
        assert event.timestamp > 0
        assert event.matches("test.*") is True
        assert event.matches("other.*") is False

    def test_service_instance_model(self):
        """ServiceInstance 模型完整性"""
        inst = ServiceInstance(
            service_name="m1",
            instance_id="m1-1",
            address="127.0.0.1",
            port=8001,
            weight=2,
            metadata={"env": "test"},
        )
        assert inst.base_url == "http://127.0.0.1:8001"
        assert inst.is_healthy is True
        assert inst.to_dict()["base_url"] == "http://127.0.0.1:8001"
