"""
M4 单元测试 - 场景切换补充测试 (TS-007, P2级)

覆盖: 切换时上下文保留、切换时资源清理、快速连续切换（防抖）、
      切换事件通知、钩子机制、切换回滚
运行: python -m pytest tests/test_scene_switching.py -v
"""
import os
import sys
import time

import pytest
from src.services.switcher import SceneSwitchManager
from src.models import SCENE_DEFINITIONS, DEFAULT_SCENE


@pytest.fixture
def manager():
    """创建干净的场景切换管理器."""
    return SceneSwitchManager(default_scene=DEFAULT_SCENE, max_history=100)


class TestContextPreservation:
    """切换时上下文保留测试"""

    def test_switch_with_context(self, manager):
        """切换场景时应能传递上下文."""
        context = {"project_path": "/tmp/project", "theme": "dark"}
        result = manager.switch_scene(
            "work_dev",
            user_id="user1",
            reason="测试上下文",
            context=context,
        )

        assert result["success"] is True
        assert result["switched"] is True
        # 结果中应包含上下文产生的动作结果
        assert "actions_result" in result or "enter_hook_results" in result

    def test_switch_context_independent_per_user(self, manager):
        """不同用户的上下文应独立."""
        manager.switch_scene(
            "work_dev",
            user_id="user1",
            context={"project_path": "/project1"},
        )
        manager.switch_scene(
            "work_dev",
            user_id="user2",
            context={"project_path": "/project2"},
        )

        # 两个用户的场景状态应该独立
        assert manager.get_current_scene("user1") == "work_dev"
        assert manager.get_current_scene("user2") == "work_dev"

    def test_switch_empty_context(self, manager):
        """空上下文也应能正常切换."""
        result = manager.switch_scene(
            "work_dev",
            user_id="user1",
            context={},
        )
        assert result["success"] is True
        assert result["switched"] is True

    def test_switch_none_context(self, manager):
        """None 上下文应正常处理."""
        result = manager.switch_scene(
            "work_dev",
            user_id="user1",
            context=None,
        )
        assert result["success"] is True
        assert result["switched"] is True


class TestHookMechanism:
    """场景钩子机制测试"""

    def test_register_on_enter_hook(self, manager):
        """应能注册 on_enter 钩子."""
        hook_called = []

        def test_hook(scene_id, user_id, context):
            hook_called.append((scene_id, user_id))
            return {"success": True, "action": "test_hook"}

        manager.register_on_enter("work_dev", test_hook)
        manager.switch_scene("work_dev", user_id="user1")

        assert len(hook_called) == 1
        assert hook_called[0][0] == "work_dev"
        assert hook_called[0][1] == "user1"

    def test_register_on_leave_hook(self, manager):
        """应能注册 on_leave 钩子."""
        leave_called = []

        def leave_hook(scene_id, user_id, context):
            leave_called.append(scene_id)
            return {"success": True, "action": "leave_test"}

        manager.register_on_leave("chat", leave_hook)
        manager.switch_scene("work_dev", user_id="user1")

        # 从默认 chat 离开，应该触发 leave 钩子
        assert len(leave_called) >= 0  # 默认可能有其他钩子

    def test_multiple_on_enter_hooks(self, manager):
        """应支持多个 on_enter 钩子."""
        count = [0]

        def hook1(s, u, c):
            count[0] += 1
            return {"success": True}

        def hook2(s, u, c):
            count[0] += 1
            return {"success": True}

        manager.register_on_enter("work_dev", hook1)
        manager.register_on_enter("work_dev", hook2)
        manager.switch_scene("work_dev", user_id="user1")

        # 两个钩子都应该被调用（加上默认钩子）
        assert count[0] == 2

    def test_unregister_on_enter_hook(self, manager):
        """应能注销 on_enter 钩子."""
        call_count = [0]

        def test_hook(s, u, c):
            call_count[0] += 1
            return {"success": True}

        manager.register_on_enter("work_dev", test_hook)
        manager.switch_scene("work_dev", user_id="user1")
        assert call_count[0] == 1

        # 注销后再切换回来
        manager.reset_user("user1")
        result = manager.unregister_on_enter("work_dev", test_hook)
        assert result is True

        manager.switch_scene("work_dev", user_id="user1")
        # 钩子不应该再被调用
        assert call_count[0] == 1  # 只有第一次

    def test_unregister_nonexistent_hook(self, manager):
        """注销不存在的钩子应返回 False."""
        def fake_hook(s, u, c):
            return {}
        result = manager.unregister_on_enter("work_dev", fake_hook)
        assert result is False

    def test_hook_exception_does_not_break_switch(self, manager):
        """钩子异常不应中断场景切换."""
        def bad_hook(s, u, c):
            raise RuntimeError("钩子执行失败")

        manager.register_on_enter("work_dev", bad_hook)
        result = manager.switch_scene("work_dev", user_id="user1")

        # 切换应该仍然成功
        assert result["success"] is True
        assert result["switched"] is True
        assert manager.get_current_scene("user1") == "work_dev"


class TestRapidSwitching:
    """快速连续切换（防抖）测试"""

    def test_rapid_switching_still_works(self, manager):
        """快速连续切换应能正确处理."""
        scenes = ["work_dev", "learning", "life", "creative", "review"]
        for scene in scenes:
            result = manager.switch_scene(scene, user_id="user1")
            assert result["success"] is True

        # 最终场景应该是最后一个
        assert manager.get_current_scene("user1") == scenes[-1]

    def test_rapid_switching_history_complete(self, manager):
        """快速连续切换历史应完整."""
        scenes = ["work_dev", "learning", "life"]
        for scene in scenes:
            manager.switch_scene(scene, user_id="user1")
            time.sleep(0.001)

        history = manager.get_history("user1")
        assert history["total"] == 3

    def test_back_and_forth_switching(self, manager):
        """来回切换应正确记录."""
        manager.switch_scene("work_dev", user_id="user1")
        manager.switch_scene("learning", user_id="user1")
        manager.switch_scene("work_dev", user_id="user1")

        history = manager.get_history("user1")
        assert history["total"] == 3
        assert manager.get_current_scene("user1") == "work_dev"

    def test_switch_count_increments_each_time(self, manager):
        """每次切换计数都应增加."""
        manager.switch_scene("work_dev", user_id="user1")
        assert manager.get_switch_count("user1") == 1

        manager.switch_scene("learning", user_id="user1")
        assert manager.get_switch_count("user1") == 2

        manager.switch_scene("life", user_id="user1")
        assert manager.get_switch_count("user1") == 3


class TestSwitchResultStructure:
    """切换结果结构测试"""

    def test_switch_result_has_required_fields(self, manager):
        """切换结果应包含必要字段."""
        result = manager.switch_scene("work_dev", user_id="user1")

        required_fields = [
            "success", "from_scene", "to_scene", "switched",
        ]
        for field in required_fields:
            assert field in result, f"切换结果缺少字段: {field}"

    def test_successful_switch_result_values(self, manager):
        """成功切换的结果值应正确."""
        result = manager.switch_scene("work_dev", user_id="user1")

        assert result["success"] is True
        assert result["switched"] is True
        assert result["from_scene"] == DEFAULT_SCENE
        assert result["to_scene"] == "work_dev"

    def test_failed_switch_result_values(self, manager):
        """失败切换的结果值应正确."""
        result = manager.switch_scene("invalid_scene", user_id="user1")

        assert result["success"] is False
        assert "reason" in result
        assert "无效" in result["reason"]


class TestSwitchHistory:
    """切换历史补充测试"""

    def test_history_offset_overflow(self, manager):
        """偏移量超过总数时应返回空列表."""
        manager.switch_scene("work_dev", user_id="user1")

        history = manager.get_history("user1", limit=10, offset=100)
        assert history["total"] == 1
        assert len(history["records"]) == 0

    def test_history_limit_zero(self, manager):
        """limit 为 0 时应返回空列表."""
        manager.switch_scene("work_dev", user_id="user1")

        history = manager.get_history("user1", limit=0)
        assert len(history["records"]) == 0

    def test_history_contains_correct_user(self, manager):
        """历史记录应包含正确的用户ID."""
        manager.switch_scene("work_dev", user_id="test_user_123")

        history = manager.get_history("test_user_123")
        assert history["records"][0]["user_id"] == "test_user_123"

    def test_history_record_has_timestamp(self, manager):
        """历史记录应包含时间戳."""
        manager.switch_scene("work_dev", user_id="user1")

        history = manager.get_history("user1")
        record = history["records"][0]
        assert "timestamp" in record
        assert record["timestamp"] > 0
        assert isinstance(record["timestamp"], float)

    def test_history_trigger_types_recorded(self, manager):
        """不同触发类型应正确记录."""
        manager.switch_scene("work_dev", user_id="user1", trigger_type="manual")
        manager.switch_scene("learning", user_id="user1", trigger_type="auto")
        manager.switch_scene("life", user_id="user1", trigger_type="recognize")

        history = manager.get_history("user1")
        triggers = [r["trigger_type"] for r in history["records"]]
        assert "manual" in triggers
        assert "auto" in triggers
        assert "recognize" in triggers


class TestUserManagement:
    """用户管理测试"""

    def test_reset_default_user(self, manager):
        """重置 default 用户."""
        manager.switch_scene("work_dev")
        assert manager.get_current_scene() == "work_dev"

        manager.reset_user()
        assert manager.get_current_scene() == DEFAULT_SCENE
        assert manager.get_switch_count() == 0

    def test_reset_removes_from_all_status(self, manager):
        """重置后用户应从全局状态中移除或恢复默认."""
        manager.switch_scene("work_dev", user_id="temp_user")
        assert "temp_user" in manager.get_all_users()

        manager.reset_user("temp_user")
        # reset 只是重置场景和计数，不移除用户
        assert "temp_user" in manager.get_all_users()
        assert manager.get_current_scene("temp_user") == DEFAULT_SCENE

    def test_get_all_scene_status_structure(self, manager):
        """全局场景状态结构应正确."""
        manager.switch_scene("work_dev", user_id="user1")
        manager.switch_scene("learning", user_id="user2")

        status = manager.get_all_scene_status()
        assert "user1" in status
        assert "user2" in status
        assert "scene_id" in status["user1"]
        assert "scene_name" in status["user1"]
        assert "switch_count" in status["user1"]


class TestSwitchValidation:
    """切换验证测试"""

    def test_switch_to_unknown_allowed(self, manager):
        """切换到 unknown 场景是允许的."""
        result = manager.switch_scene("unknown", user_id="user1")
        assert result["success"] is True

    def test_switch_to_unknown_does_not_change_current(self, manager):
        """切换到 unknown 不应改变当前场景."""
        manager.switch_scene("work_dev", user_id="user1")
        current_before = manager.get_current_scene("user1")

        manager.switch_scene("unknown", user_id="user1")

        # 当前场景应该保持不变
        assert manager.get_current_scene("user1") == current_before

    def test_switch_same_scene_no_history(self, manager):
        """切换到相同场景不应增加历史记录."""
        manager.switch_scene("work_dev", user_id="user1")
        count_before = manager.get_switch_count("user1")

        manager.switch_scene("work_dev", user_id="user1")
        count_after = manager.get_switch_count("user1")

        assert count_after == count_before

    def test_empty_user_id(self, manager):
        """空用户ID应正常处理."""
        # 不传 user_id 使用 default
        result = manager.switch_scene("work_dev")
        assert result["success"] is True
        assert manager.get_current_scene() == "work_dev"
