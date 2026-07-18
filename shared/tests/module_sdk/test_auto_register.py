"""
模块自动注册启动器测试
"""

import sys
import time
from pathlib import Path

import pytest

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from shared.module_sdk.auto_register import (
    ModuleAutoRegister,
    auto_register_module,
)
from shared.module_sdk.registry import (
    InMemoryRegistry,
    ServiceRegistryClient,
    reset_registry_client,
)


# ============================================================
# ModuleAutoRegister 测试
# ============================================================

class TestModuleAutoRegister:
    """ModuleAutoRegister 测试"""

    def setup_method(self):
        reset_registry_client()
        self.registry = InMemoryRegistry()

    def teardown_method(self):
        self.registry.clear()
        self.registry.stop_auto_cleanup()
        reset_registry_client()

    def test_initialization(self):
        """测试基本初始化"""
        registrar = ModuleAutoRegister(
            module_name="m1",
            instance_id="m1-test",
            address="127.0.0.1",
            port=8001,
            registry=self.registry,
        )
        assert registrar.module_name == "m1"
        assert registrar.instance_id == "m1-test"
        assert registrar.port == 8001
        assert registrar.is_registered is False
        assert registrar.is_running is False

    def test_auto_instance_id(self):
        """测试自动生成实例 ID"""
        registrar = ModuleAutoRegister(
            module_name="m1",
            port=8001,
            registry=self.registry,
        )
        assert registrar.instance_id.startswith("m1-")
        assert len(registrar.instance_id) > len("m1-")

    def test_start_registers_service(self):
        """测试 start 会注册服务"""
        registrar = ModuleAutoRegister(
            module_name="m1",
            instance_id="m1-1",
            address="127.0.0.1",
            port=8001,
            registry=self.registry,
            heartbeat_interval=0,  # 不启动心跳
        )
        result = registrar.start()
        assert result is True
        assert registrar.is_registered is True
        assert registrar.is_running is True

        # 检查注册中心中存在
        instances = self.registry.discover("m1")
        assert len(instances) == 1
        assert instances[0].instance_id == "m1-1"

    def test_stop_deregisters_service(self):
        """测试 stop 会注销服务"""
        registrar = ModuleAutoRegister(
            module_name="m1",
            instance_id="m1-1",
            address="127.0.0.1",
            port=8001,
            registry=self.registry,
            heartbeat_interval=0,
        )
        registrar.start()
        assert len(self.registry.discover("m1")) == 1

        registrar.stop()
        assert registrar.is_registered is False
        assert registrar.is_running is False
        assert len(self.registry.discover("m1")) == 0

    def test_heartbeat(self):
        """测试心跳发送"""
        registrar = ModuleAutoRegister(
            module_name="m1",
            instance_id="m1-1",
            address="127.0.0.1",
            port=8001,
            registry=self.registry,
            heartbeat_interval=0.01,  # 很快的心跳
        )
        registrar.start()

        # 等待几次心跳
        time.sleep(0.05)

        # 检查心跳是否更新
        inst = self.registry.get_instance("m1", "m1-1")
        assert inst is not None
        assert inst.last_heartbeat > 0

        registrar.stop()

    def test_callbacks(self):
        """测试回调函数"""
        success_called = []
        deregister_called = []

        def on_success():
            success_called.append(True)

        def on_deregister():
            deregister_called.append(True)

        registrar = ModuleAutoRegister(
            module_name="m1",
            instance_id="m1-1",
            address="127.0.0.1",
            port=8001,
            registry=self.registry,
            heartbeat_interval=0,
            on_register_success=on_success,
            on_deregister=on_deregister,
        )

        registrar.start()
        assert len(success_called) == 1

        registrar.stop()
        assert len(deregister_called) == 1

    def test_register_failed_callback(self):
        """测试注册失败回调"""
        # 使用一个会抛出异常的 registry
        class BadRegistry:
            def register(self, *args, **kwargs):
                raise ValueError("test error")

            def heartbeat(self, *args, **kwargs):
                return False

        failed_called = []

        def on_failed(exc):
            failed_called.append(exc)

        registrar = ModuleAutoRegister(
            module_name="m1",
            instance_id="m1-1",
            address="127.0.0.1",
            port=8001,
            registry=BadRegistry(),
            heartbeat_interval=0,
            on_register_failed=on_failed,
        )

        result = registrar.start()
        assert result is False
        assert len(failed_called) == 1
        assert isinstance(failed_called[0], ValueError)

    def test_double_start(self):
        """测试重复 start 不会重复注册"""
        registrar = ModuleAutoRegister(
            module_name="m1",
            instance_id="m1-1",
            address="127.0.0.1",
            port=8001,
            registry=self.registry,
            heartbeat_interval=0,
        )

        r1 = registrar.start()
        r2 = registrar.start()
        assert r1 is True
        assert r2 is True  # 第二次直接返回 True

        # 只有一个实例
        instances = self.registry.discover("m1")
        assert len(instances) == 1

        registrar.stop()

    def test_stop_before_start(self):
        """测试在 start 之前调用 stop"""
        registrar = ModuleAutoRegister(
            module_name="m1",
            port=8001,
            registry=self.registry,
            heartbeat_interval=0,
        )
        # 不应抛出异常
        registrar.stop()
        assert registrar.is_running is False

    def test_module_name_lowercase(self):
        """测试模块名转为小写"""
        registrar = ModuleAutoRegister(
            module_name="M1",
            port=8001,
            registry=self.registry,
            heartbeat_interval=0,
        )
        assert registrar.module_name == "m1"

    def test_metadata(self):
        """测试元数据"""
        registrar = ModuleAutoRegister(
            module_name="m1",
            instance_id="m1-1",
            address="127.0.0.1",
            port=8001,
            registry=self.registry,
            heartbeat_interval=0,
            metadata={"env": "test", "zone": "east"},
            version="2.0.0",
            weight=3,
        )
        registrar.start()

        inst = self.registry.get_instance("m1", "m1-1")
        assert inst is not None
        assert inst.version == "2.0.0"
        assert inst.weight == 3
        assert inst.metadata == {"env": "test", "zone": "east"}

        registrar.stop()


# ============================================================
# 便捷函数测试
# ============================================================

class TestConvenienceFunctions:
    """便捷函数测试"""

    def setup_method(self):
        reset_registry_client()
        self.registry = InMemoryRegistry()

    def teardown_method(self):
        self.registry.clear()
        self.registry.stop_auto_cleanup()
        reset_registry_client()

    def test_auto_register_module(self):
        """测试 auto_register_module 便捷函数"""
        registrar = auto_register_module(
            module_name="test_mod",
            port=9999,
            address="127.0.0.1",
            heartbeat_interval=0,
        )
        # 使用全局注册中心
        assert registrar.is_registered is True
        assert registrar.module_name == "test_mod"

        registrar.stop()
