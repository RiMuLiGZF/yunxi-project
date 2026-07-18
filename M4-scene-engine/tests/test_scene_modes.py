"""
M4 单元测试 - 场景模式测试 (TS-007, P2级)

覆盖: 模式基类、模式注册表、各业务模式（工作/学习/生活/情绪/成长）、
      模式注册/注销/查询、默认模式
运行: python -m pytest tests/test_scene_modes.py -v
"""
import os
import sys

import pytest
from src.modes.base_mode import BaseMode
from src.modes.mode_registry import ModeRegistry


# ============================================================================
# 测试用自定义模式
# ============================================================================

class TestMode(BaseMode):
    """测试用模式."""
    mode_id = "test_mode"
    mode_name = "测试模式"
    mode_description = "用于单元测试的模式"
    icon = "🧪"
    category = "test"
    priority = 10
    is_enabled = True


class DisabledMode(BaseMode):
    """被禁用的模式."""
    mode_id = "disabled_mode"
    mode_name = "禁用模式"
    mode_description = "被禁用的测试模式"
    icon = "🚫"
    category = "test"
    priority = 20
    is_enabled = False


class WorkMode(BaseMode):
    """工作模式."""
    mode_id = "work"
    mode_name = "工作模式"
    mode_description = "专注工作的模式"
    icon = "💼"
    category = "work"
    priority = 1
    is_enabled = True


class StudyMode(BaseMode):
    """学习模式."""
    mode_id = "study"
    mode_name = "学习模式"
    mode_description = "专注学习的模式"
    icon = "📖"
    category = "study"
    priority = 2
    is_enabled = True


class LifeMode(BaseMode):
    """生活模式."""
    mode_id = "life"
    mode_name = "生活模式"
    mode_description = "日常生活模式"
    icon = "🏠"
    category = "life"
    priority = 3
    is_enabled = True


# ============================================================================
# 模式基类测试
# ============================================================================

class TestBaseMode:
    """模式基类测试"""

    def test_base_mode_default_values(self):
        """基类应具有默认属性值."""
        mode = BaseMode()
        assert mode.mode_id == ""
        assert mode.mode_name == ""
        assert mode.mode_description == ""
        assert mode.icon == "📦"
        assert mode.category == "general"
        assert mode.priority == 100
        assert mode.is_enabled is True

    def test_subclass_overrides_attributes(self):
        """子类应能覆盖属性."""
        mode = TestMode()
        assert mode.mode_id == "test_mode"
        assert mode.mode_name == "测试模式"
        assert mode.icon == "🧪"
        assert mode.category == "test"
        assert mode.priority == 10
        assert mode.is_enabled is True

    def test_get_info_returns_dict(self):
        """get_info 应返回完整信息字典."""
        mode = TestMode()
        info = mode.get_info()

        assert isinstance(info, dict)
        assert info["mode_id"] == "test_mode"
        assert info["mode_name"] == "测试模式"
        assert info["mode_description"] == "用于单元测试的模式"
        assert info["icon"] == "🧪"
        assert info["category"] == "test"
        assert info["priority"] == 10
        assert info["is_enabled"] is True

    def test_repr_contains_mode_info(self):
        """__repr__ 应包含模式信息."""
        mode = TestMode()
        repr_str = repr(mode)
        assert "TestMode" in repr_str
        assert "test_mode" in repr_str
        assert "测试模式" in repr_str

    def test_on_enter_returns_dict(self):
        """on_enter 应返回字典."""
        mode = TestMode()
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            mode.on_enter({"user_id": "test"})
        )

        assert isinstance(result, dict)
        assert "success" in result
        assert "message" in result
        assert "data" in result
        assert "context_updates" in result
        assert result["success"] is True
        assert "测试模式" in result["message"]

    def test_on_leave_returns_dict(self):
        """on_leave 应返回字典."""
        mode = TestMode()
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            mode.on_leave({"user_id": "test"})
        )

        assert isinstance(result, dict)
        assert "success" in result
        assert result["success"] is True

    def test_handle_message_returns_dict(self):
        """handle_message 应返回字典."""
        mode = TestMode()
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            mode.handle_message("你好", {"user_id": "test"})
        )

        assert isinstance(result, dict)
        assert "success" in result
        assert "reply" in result
        assert result["success"] is True
        assert "测试模式" in result["reply"]

    def test_get_config_returns_dict(self):
        """get_config 应返回字典（默认空）."""
        mode = TestMode()
        import asyncio
        config = asyncio.get_event_loop().run_until_complete(mode.get_config())
        assert isinstance(config, dict)


# ============================================================================
# 模式注册表测试
# ============================================================================

class TestModeRegistry:
    """模式注册表测试"""

    def setup_method(self):
        """每个测试前创建新的注册表实例."""
        self.registry = ModeRegistry()

    def test_registry_starts_empty(self):
        """新注册表应为空."""
        assert self.registry.count() == 0
        assert len(self.registry) == 0
        assert self.registry.get_default() is None

    def test_register_mode(self):
        """注册模式."""
        mode = TestMode()
        self.registry.register(mode)

        assert self.registry.count() == 1
        assert self.registry.has("test_mode") is True
        assert "test_mode" in self.registry

    def test_register_sets_default(self):
        """第一个注册的启用模式应成为默认模式."""
        mode = TestMode()
        self.registry.register(mode)

        default = self.registry.get_default()
        assert default is not None
        assert default.mode_id == "test_mode"

    def test_register_duplicate_raises(self):
        """注册重复 ID 的模式应抛出异常."""
        self.registry.register(TestMode())

        with pytest.raises(ValueError, match="已注册"):
            self.registry.register(TestMode())

    def test_register_empty_id_raises(self):
        """注册空 ID 的模式应抛出异常."""
        class EmptyIdMode(BaseMode):
            mode_id = ""

        with pytest.raises(ValueError, match="不能为空"):
            self.registry.register(EmptyIdMode())

    def test_unregister_existing_mode(self):
        """注销已注册的模式."""
        self.registry.register(TestMode())
        assert self.registry.count() == 1

        result = self.registry.unregister("test_mode")
        assert result is True
        assert self.registry.count() == 0
        assert self.registry.has("test_mode") is False

    def test_unregister_nonexistent_mode(self):
        """注销不存在的模式应返回 False."""
        result = self.registry.unregister("nonexistent")
        assert result is False

    def test_unregister_default_mode_reselects(self):
        """注销默认模式后应重新选择默认模式."""
        self.registry.register(WorkMode())
        self.registry.register(StudyMode())
        assert self.registry.get_default().mode_id == "work"

        self.registry.unregister("work")
        assert self.registry.get_default().mode_id == "study"

    def test_get_mode(self):
        """获取模式."""
        mode = TestMode()
        self.registry.register(mode)

        retrieved = self.registry.get("test_mode")
        assert retrieved is not None
        assert retrieved.mode_id == "test_mode"

    def test_get_nonexistent_mode(self):
        """获取不存在的模式应返回 None."""
        assert self.registry.get("nonexistent") is None

    def test_list_all_modes(self):
        """列出所有模式."""
        self.registry.register(WorkMode())
        self.registry.register(StudyMode())
        self.registry.register(DisabledMode())

        all_modes = self.registry.list_all()
        assert len(all_modes) == 3

    def test_list_all_sorted_by_priority(self):
        """列出所有模式应按优先级排序."""
        self.registry.register(StudyMode())  # priority 2
        self.registry.register(LifeMode())   # priority 3
        self.registry.register(WorkMode())   # priority 1

        all_modes = self.registry.list_all()
        assert all_modes[0].mode_id == "work"   # priority 1
        assert all_modes[1].mode_id == "study"  # priority 2
        assert all_modes[2].mode_id == "life"   # priority 3

    def test_list_enabled_modes(self):
        """列出已启用的模式."""
        self.registry.register(WorkMode())
        self.registry.register(DisabledMode())
        self.registry.register(StudyMode())

        enabled = self.registry.list_enabled()
        assert len(enabled) == 2
        assert all(m.is_enabled for m in enabled)

    def test_count_enabled(self):
        """已启用模式计数."""
        self.registry.register(WorkMode())
        self.registry.register(DisabledMode())

        assert self.registry.count() == 2
        assert self.registry.count_enabled() == 1

    def test_get_by_category(self):
        """按分类获取模式."""
        self.registry.register(WorkMode())
        self.registry.register(StudyMode())
        self.registry.register(LifeMode())

        work_modes = self.registry.get_by_category("work")
        assert len(work_modes) == 1
        assert work_modes[0].mode_id == "work"

        study_modes = self.registry.get_by_category("study")
        assert len(study_modes) == 1

    def test_get_by_category_empty(self):
        """获取不存在分类的模式应返回空列表."""
        result = self.registry.get_by_category("nonexistent")
        assert result == []

    def test_set_default(self):
        """设置默认模式."""
        self.registry.register(WorkMode())
        self.registry.register(StudyMode())

        result = self.registry.set_default("study")
        assert result is True
        assert self.registry.get_default().mode_id == "study"

    def test_set_default_nonexistent(self):
        """设置不存在的模式为默认应返回 False."""
        result = self.registry.set_default("nonexistent")
        assert result is False

    def test_set_default_disabled(self):
        """设置禁用的模式为默认应返回 False."""
        self.registry.register(DisabledMode())
        result = self.registry.set_default("disabled_mode")
        assert result is False

    def test_clear_registry(self):
        """清空注册表."""
        self.registry.register(WorkMode())
        self.registry.register(StudyMode())
        assert self.registry.count() == 2

        self.registry.clear()
        assert self.registry.count() == 0
        assert self.registry.get_default() is None

    def test_disabled_mode_not_default(self):
        """禁用的模式不应成为默认模式."""
        self.registry.register(DisabledMode())
        assert self.registry.get_default() is None

    def test_contains_operator(self):
        """in 运算符应能检查模式是否存在."""
        self.registry.register(TestMode())
        assert "test_mode" in self.registry
        assert "nonexistent" not in self.registry

    def test_len_operator(self):
        """len() 应返回模式数量."""
        assert len(self.registry) == 0
        self.registry.register(TestMode())
        assert len(self.registry) == 1

    def test_repr_contains_counts(self):
        """__repr__ 应包含计数信息."""
        self.registry.register(WorkMode())
        repr_str = repr(self.registry)
        assert "total=1" in repr_str
        assert "enabled=1" in repr_str


# ============================================================================
# 模式注册表单例测试
# ============================================================================

class TestModeRegistrySingleton:
    """模式注册表单例测试"""

    def test_get_instance_returns_same_object(self):
        """get_instance 应返回同一个实例."""
        inst1 = ModeRegistry.get_instance()
        inst2 = ModeRegistry.get_instance()
        assert inst1 is inst2

    def test_singleton_persists_state(self):
        """单例应保持状态."""
        inst1 = ModeRegistry.get_instance()
        # 注意：这里可能已经被其他测试注册了模式
        # 所以只测试单例属性，不测试空状态
        inst2 = ModeRegistry.get_instance()
        assert inst1.count() == inst2.count()


# ============================================================================
# 业务模式特定行为测试
# ============================================================================

class TestModeCategories:
    """模式分类测试"""

    def setup_method(self):
        """每个测试前创建新的注册表并注册测试模式."""
        self.registry = ModeRegistry()
        self.registry.register(WorkMode())
        self.registry.register(StudyMode())
        self.registry.register(LifeMode())
        self.registry.register(TestMode())
        self.registry.register(DisabledMode())

    def test_work_category_exists(self):
        """工作分类应存在."""
        work_modes = self.registry.get_by_category("work")
        assert len(work_modes) > 0
        assert all(m.category == "work" for m in work_modes)

    def test_study_category_exists(self):
        """学习分类应存在."""
        study_modes = self.registry.get_by_category("study")
        assert len(study_modes) > 0

    def test_life_category_exists(self):
        """生活分类应存在."""
        life_modes = self.registry.get_by_category("life")
        assert len(life_modes) > 0

    def test_disabled_modes_not_in_category_list(self):
        """禁用模式不应出现在分类列表中."""
        test_modes = self.registry.get_by_category("test")
        # TestMode 是启用的，应该出现
        assert any(m.mode_id == "test_mode" for m in test_modes)
        # DisabledMode 是禁用的，不应该出现
        assert not any(m.mode_id == "disabled_mode" for m in test_modes)

    def test_priority_order_in_category(self):
        """同一分类内的模式应按优先级排序."""
        modes = self.registry.list_enabled()
        priorities = [m.priority for m in modes]
        # 检查是否升序排列
        assert priorities == sorted(priorities)


class TestModeLifecycle:
    """模式生命周期测试"""

    def test_on_enter_message_contains_mode_name(self):
        """进入模式的消息应包含模式名称."""
        import asyncio
        mode = TestMode()
        result = asyncio.get_event_loop().run_until_complete(
            mode.on_enter({"user_id": "user1"})
        )
        assert mode.mode_name in result["message"]

    def test_on_leave_message_contains_mode_name(self):
        """离开模式的消息应包含模式名称."""
        import asyncio
        mode = TestMode()
        result = asyncio.get_event_loop().run_until_complete(
            mode.on_leave({"user_id": "user1"})
        )
        assert mode.mode_name in result["message"]

    def test_handle_message_echoes_content(self):
        """消息处理应包含模式标识."""
        import asyncio
        mode = TestMode()
        result = asyncio.get_event_loop().run_until_complete(
            mode.handle_message("测试消息", {"user_id": "user1"})
        )
        assert "测试消息" in result["reply"]
        assert mode.mode_name in result["reply"]
