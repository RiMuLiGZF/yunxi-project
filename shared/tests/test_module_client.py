"""
shared 共享库 - 模块通信测试
测试内容：
1. ModuleInfo 类
2. ModuleRegistry 注册/发现
3. 模块状态管理
4. 单例模式

使用方式：
    cd shared/tests
    python test_module_client.py
    或
    python -m pytest test_module_client.py -v
"""

import sys
from pathlib import Path

# 添加项目路径
shared_dir = Path(__file__).parent.parent.resolve()
if str(shared_dir) not in sys.path:
    sys.path.insert(0, str(shared_dir))

import pytest

from module_client import ModuleInfo, ModuleRegistry, get_module_registry


# ==================== Fixtures ====================

@pytest.fixture
def sample_module():
    """创建示例模块信息"""
    return ModuleInfo(
        key="test_mod",
        name="测试模块",
        version="1.0.0",
        port=8099,
        base_url="http://localhost:8099",
        description="这是一个测试模块",
    )


# ==================== ModuleInfo 测试 ====================

class TestModuleInfo:
    """模块信息类测试"""

    def test_module_info_creation(self, sample_module):
        """测试创建模块信息"""
        assert sample_module.key == "test_mod"
        assert sample_module.name == "测试模块"
        assert sample_module.version == "1.0.0"
        assert sample_module.port == 8099
        assert sample_module.base_url == "http://localhost:8099"
        assert sample_module.description == "这是一个测试模块"

    def test_module_info_default_status(self, sample_module):
        """测试默认状态"""
        assert sample_module.status == "unknown"

    def test_module_info_to_dict(self, sample_module):
        """测试序列化"""
        d = sample_module.to_dict()
        assert d["key"] == "test_mod"
        assert d["name"] == "测试模块"
        assert d["version"] == "1.0.0"
        assert d["port"] == 8099
        assert d["base_url"] == "http://localhost:8099"
        assert d["description"] == "这是一个测试模块"
        assert d["status"] == "unknown"

    def test_module_info_status_change(self, sample_module):
        """测试状态变更"""
        sample_module.status = "running"
        assert sample_module.status == "running"
        d = sample_module.to_dict()
        assert d["status"] == "running"

    def test_module_info_all_statuses(self, sample_module):
        """测试所有状态值"""
        for status in ["unknown", "running", "stopped", "error"]:
            sample_module.status = status
            assert sample_module.status == status


# ==================== ModuleRegistry 测试 ====================

class TestModuleRegistry:
    """模块注册中心测试"""

    def test_registry_creation(self):
        """测试创建注册中心"""
        # 注意：ModuleRegistry 是单例，每次 new 都返回同一个实例
        registry = ModuleRegistry()
        assert registry is not None
        assert hasattr(registry, '_modules')

    def test_default_modules_count(self):
        """测试默认模块数量"""
        registry = ModuleRegistry()
        modules = registry.get_all_modules()
        # 默认注册了9个模块（M1-M8, M10）
        assert len(modules) == 9

    def test_default_module_keys(self):
        """测试默认模块的 key"""
        registry = ModuleRegistry()
        modules = registry.get_all_modules()
        keys = [m.key for m in modules]
        assert "m1" in keys
        assert "m2" in keys
        assert "m8" in keys
        assert "m10" in keys
        # M9 不在默认列表里
        assert "m9" not in keys

    def test_register_module(self, sample_module):
        """测试注册模块"""
        registry = ModuleRegistry()
        initial_count = registry.get_module_count()
        registry.register_module(sample_module)
        assert registry.get_module("test_mod") is not None
        assert registry.get_module("test_mod").name == "测试模块"
        assert registry.get_module_count() == initial_count + 1
        # 清理
        registry.unregister_module("test_mod")

    def test_register_duplicate_module(self, sample_module):
        """测试注册重复模块（会覆盖）"""
        registry = ModuleRegistry()
        registry.register_module(sample_module)
        # 重复注册应该覆盖旧的
        mod2 = ModuleInfo(
            key="test_mod",
            name="更新后的模块",
            version="2.0.0",
            port=8099,
            base_url="http://localhost:8099",
        )
        registry.register_module(mod2)
        assert registry.get_module("test_mod").name == "更新后的模块"
        assert registry.get_module("test_mod").version == "2.0.0"
        # 清理
        registry.unregister_module("test_mod")

    def test_unregister_module(self, sample_module):
        """测试注销模块"""
        registry = ModuleRegistry()
        registry.register_module(sample_module)
        assert registry.get_module("test_mod") is not None
        registry.unregister_module("test_mod")
        assert registry.get_module("test_mod") is None

    def test_unregister_nonexistent_module(self):
        """测试注销不存在的模块（不报错）"""
        registry = ModuleRegistry()
        # 注销不存在的模块应该不抛异常
        registry.unregister_module("nonexistent_key_12345")

    def test_get_module(self):
        """测试获取模块"""
        registry = ModuleRegistry()
        m1 = registry.get_module("m1")
        assert m1 is not None
        assert m1.key == "m1"

    def test_get_nonexistent_module(self):
        """测试获取不存在的模块"""
        registry = ModuleRegistry()
        result = registry.get_module("nonexistent_module")
        assert result is None

    def test_get_all_modules(self):
        """测试获取所有模块"""
        registry = ModuleRegistry()
        modules = registry.get_all_modules()
        assert isinstance(modules, list)
        assert len(modules) >= 9
        # 所有元素都是 ModuleInfo 实例
        for mod in modules:
            assert isinstance(mod, ModuleInfo)

    def test_get_module_count(self):
        """测试获取模块数量"""
        registry = ModuleRegistry()
        count = registry.get_module_count()
        assert isinstance(count, int)
        assert count >= 9

    def test_update_module_status(self):
        """测试更新模块状态"""
        registry = ModuleRegistry()
        registry.update_module_status("m1", "running")
        m1 = registry.get_module("m1")
        assert m1.status == "running"

    def test_update_module_status_stopped(self):
        """测试更新为停止状态"""
        registry = ModuleRegistry()
        registry.update_module_status("m2", "stopped")
        m2 = registry.get_module("m2")
        assert m2.status == "stopped"

    def test_update_module_status_error(self):
        """测试更新为错误状态"""
        registry = ModuleRegistry()
        registry.update_module_status("m3", "error")
        m3 = registry.get_module("m3")
        assert m3.status == "error"

    def test_update_nonexistent_module_status(self):
        """测试更新不存在模块的状态（不报错）"""
        registry = ModuleRegistry()
        # 更新不存在的模块应该不抛异常
        registry.update_module_status("nonexistent_12345", "running")


# ==================== 单例模式测试 ====================

class TestSingleton:
    """单例模式测试"""

    def test_same_instance(self):
        """测试单例模式返回同一实例"""
        r1 = ModuleRegistry()
        r2 = ModuleRegistry()
        assert r1 is r2

    def test_get_module_registry_singleton(self):
        """测试 get_module_registry 返回单例"""
        r1 = get_module_registry()
        r2 = get_module_registry()
        assert r1 is r2

    def test_get_module_registry_returns_registry(self):
        """测试 get_module_registry 返回 ModuleRegistry 实例"""
        r = get_module_registry()
        assert isinstance(r, ModuleRegistry)


# ==================== 模块配置测试 ====================

class TestModuleConfig:
    """模块配置测试"""

    def test_module_has_port(self):
        """测试每个模块都有端口"""
        registry = ModuleRegistry()
        for mod in registry.get_all_modules():
            assert isinstance(mod.port, int)
            assert mod.port > 0

    def test_module_has_base_url(self):
        """测试每个模块都有 base_url"""
        registry = ModuleRegistry()
        for mod in registry.get_all_modules():
            assert mod.base_url.startswith("http")

    def test_module_has_version(self):
        """测试每个模块都有版本号"""
        registry = ModuleRegistry()
        for mod in registry.get_all_modules():
            assert mod.version is not None
            assert len(mod.version) > 0


# ==================== 直接运行入口 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("shared 模块通信测试")
    print("=" * 60)

    # 使用 pytest 运行
    exit_code = pytest.main([__file__, "-v", "--tb=short", "-c", "pytest.ini"])
    sys.exit(exit_code)
