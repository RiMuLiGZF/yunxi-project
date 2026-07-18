"""SceneSwitchManager 单元测试.

测试 SceneSwitchManager 的核心功能：
- 当前场景查询
- 场景切换（成功/相同/无效）
- 切换历史记录与分页
- 切换计数
- 多用户隔离
- 最大历史记录限制
- 重置用户
- 全局状态查询
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


class TestSceneSwitchManager:
    """SceneSwitchManager 测试类."""

    # ------------------------------------------------------------------
    # 当前场景测试
    # ------------------------------------------------------------------

    def test_default_scene(self, manager):
        """新用户的当前场景应为默认场景."""
        assert manager.get_current_scene("new_user") == DEFAULT_SCENE

    def test_default_user(self, manager):
        """不传 user_id 应使用 default 用户."""
        scene1 = manager.get_current_scene()
        scene2 = manager.get_current_scene("default")
        assert scene1 == scene2

    def test_custom_default_scene(self):
        """支持自定义默认场景."""
        mgr = SceneSwitchManager(default_scene="work_dev", max_history=50)
        assert mgr.get_current_scene("user1") == "work_dev"

    # ------------------------------------------------------------------
    # 场景切换测试
    # ------------------------------------------------------------------

    def test_switch_scene_success(self, manager):
        """切换到有效场景应成功."""
        result = manager.switch_scene("work_dev", user_id="user1", reason="测试切换")
        assert result["success"] is True
        assert result["switched"] is True
        assert result["from_scene"] == DEFAULT_SCENE
        assert result["to_scene"] == "work_dev"
        assert "record_id" in result
        assert "timestamp" in result

        # 验证当前场景已更新
        assert manager.get_current_scene("user1") == "work_dev"

    def test_switch_same_scene(self, manager):
        """切换到当前场景应返回 switched=False."""
        manager.switch_scene("work_dev", user_id="user1")
        result = manager.switch_scene("work_dev", user_id="user1")

        assert result["success"] is True
        assert result["switched"] is False
        assert result["reason"] == "已在目标场景"

    def test_switch_invalid_scene(self, manager):
        """切换到无效场景应返回失败."""
        result = manager.switch_scene("invalid_scene", user_id="user1")
        assert result["success"] is False
        assert "无效的场景ID" in result["reason"]

        # 当前场景不应改变
        assert manager.get_current_scene("user1") == DEFAULT_SCENE

    def test_switch_unknown_scene_allowed(self, manager):
        """切换到 unknown 是允许的（但不更新当前场景）."""
        manager.switch_scene("work_dev", user_id="user1")
        result = manager.switch_scene("unknown", user_id="user1", trigger_type="recognize")

        # 切换 unknown 是成功的（有记录）
        assert result["success"] is True
        assert result["switched"] is True
        assert result["to_scene"] == "unknown"

        # 但当前场景不应该变成 unknown（保持上次有效场景）
        assert manager.get_current_scene("user1") == "work_dev"

    def test_switch_with_from_scene(self, manager):
        """指定 from_scene 应使用指定值而非当前场景."""
        manager.switch_scene("work_dev", user_id="user1")

        result = manager.switch_scene(
            "life_manage",
            from_scene="study_plan",  # 不是当前的 work_dev
            user_id="user1",
            reason="手动指定源场景",
        )

        assert result["success"] is True
        assert result["from_scene"] == "study_plan"
        assert result["to_scene"] == "life_manage"

    def test_switch_trigger_types(self, manager):
        """不同触发类型都应正常记录."""
        triggers = ["manual", "auto", "recognize"]
        for t in triggers:
            result = manager.switch_scene("work_dev", trigger_type=t, user_id=f"user_{t}")
            assert result["trigger_type"] == t

    # ------------------------------------------------------------------
    # 切换计数测试
    # ------------------------------------------------------------------

    def test_switch_count_increments(self, manager):
        """每次切换计数应增加."""
        assert manager.get_switch_count("user1") == 0

        manager.switch_scene("work_dev", user_id="user1")
        assert manager.get_switch_count("user1") == 1

        manager.switch_scene("life_manage", user_id="user1")
        assert manager.get_switch_count("user1") == 2

    def test_switch_count_same_scene_no_increment(self, manager):
        """切换到相同场景（switched=False）也会计数（因为有记录）.

        注意：实际实现中只要调用 switch_scene 且成功创建记录，计数就会+1
        但 same scene 的情况实际是 switched=False 但仍记录吗？
        看代码：相同场景直接 return，没有记录历史和计数
        """
        manager.switch_scene("work_dev", user_id="user1")
        count_before = manager.get_switch_count("user1")

        # 切换到相同场景
        manager.switch_scene("work_dev", user_id="user1")
        count_after = manager.get_switch_count("user1")

        # 相同场景不应增加计数
        assert count_after == count_before

    # ------------------------------------------------------------------
    # 切换历史测试
    # ------------------------------------------------------------------

    def test_history_empty(self, manager):
        """无切换时历史应为空."""
        history = manager.get_history("user1")
        assert history["total"] == 0
        assert history["records"] == []

    def test_history_records_order(self, manager):
        """历史记录应按时间倒序排列（最新在前）."""
        manager.switch_scene("work_dev", user_id="user1")
        time.sleep(0.01)
        manager.switch_scene("life_manage", user_id="user1")
        time.sleep(0.01)
        manager.switch_scene("study_plan", user_id="user1")

        history = manager.get_history("user1")
        assert history["total"] == 3
        assert len(history["records"]) == 3

        # 最新的应该是 study_plan
        assert history["records"][0]["to_scene"] == "study_plan"
        assert history["records"][1]["to_scene"] == "life_manage"
        assert history["records"][2]["to_scene"] == "work_dev"

    def test_history_limit(self, manager):
        """历史记录应支持 limit 参数."""
        for i in range(10):
            manager.switch_scene("work_dev" if i % 2 == 0 else "life_manage", user_id="user1")
            time.sleep(0.005)

        history = manager.get_history("user1", limit=3)
        assert history["total"] == 10
        assert len(history["records"]) == 3
        assert history["limit"] == 3

    def test_history_offset(self, manager):
        """历史记录应支持 offset 参数."""
        for i in range(10):
            manager.switch_scene("work_dev" if i % 2 == 0 else "life_manage", user_id="user1")
            time.sleep(0.005)

        history1 = manager.get_history("user1", limit=5, offset=0)
        history2 = manager.get_history("user1", limit=5, offset=5)

        assert len(history1["records"]) == 5
        assert len(history2["records"]) == 5
        # 第一页的最后一条应该比第二页的第一条更新
        assert history1["records"][-1]["timestamp"] >= history2["records"][0]["timestamp"]

    def test_history_record_structure(self, manager):
        """历史记录应包含完整字段."""
        manager.switch_scene(
            "work_dev",
            user_id="user1",
            trigger_type="manual",
            reason="测试记录结构",
        )

        history = manager.get_history("user1")
        record = history["records"][0]

        assert "id" in record
        assert "from_scene" in record
        assert "to_scene" in record
        assert "trigger_type" in record
        assert "user_id" in record
        assert "timestamp" in record
        assert "reason" in record
        assert isinstance(record["id"], str)
        assert len(record["id"]) > 0

    # ------------------------------------------------------------------
    # 多用户隔离测试
    # ------------------------------------------------------------------

    def test_multi_user_isolation(self, manager):
        """不同用户的场景状态应隔离."""
        manager.switch_scene("work_dev", user_id="user1")
        manager.switch_scene("life_manage", user_id="user2")

        assert manager.get_current_scene("user1") == "work_dev"
        assert manager.get_current_scene("user2") == "life_manage"
        assert manager.get_switch_count("user1") == 1
        assert manager.get_switch_count("user2") == 1

    def test_get_all_users(self, manager):
        """获取所有用户列表."""
        manager.switch_scene("work_dev", user_id="user1")
        manager.switch_scene("work_dev", user_id="user2")
        manager.switch_scene("work_dev", user_id="user3")

        users = manager.get_all_users()
        assert len(users) == 3
        assert "user1" in users
        assert "user2" in users
        assert "user3" in users

    # ------------------------------------------------------------------
    # 最大历史记录限制测试
    # ------------------------------------------------------------------

    def test_max_history_limit(self):
        """超过 max_history 时旧记录应被丢弃."""
        mgr = SceneSwitchManager(max_history=5)

        scenes = ["work_dev", "study_plan", "review_summary", "interpersonal", "life_manage"]
        for i in range(10):
            scene = scenes[i % len(scenes)]
            mgr.switch_scene(scene, user_id="user1")
            time.sleep(0.005)

        history = mgr.get_history("user1")
        # 只保留最近 5 条
        assert history["total"] == 5
        assert len(history["records"]) == 5

        # 5个场景循环切换，保留的是最近 5 条
        result_scenes = [r["to_scene"] for r in history["records"]]
        assert len(set(result_scenes)) == 5  # 5 个不同场景

    # ------------------------------------------------------------------
    # 重置用户测试
    # ------------------------------------------------------------------

    def test_reset_user(self, manager):
        """重置用户应清空历史并恢复默认场景."""
        manager.switch_scene("work_dev", user_id="user1")
        manager.switch_scene("life_manage", user_id="user1")

        assert manager.get_switch_count("user1") == 2
        assert manager.get_current_scene("user1") == "life_manage"

        manager.reset_user("user1")

        assert manager.get_current_scene("user1") == DEFAULT_SCENE
        assert manager.get_switch_count("user1") == 0
        history = manager.get_history("user1")
        assert history["total"] == 0

    def test_reset_user_does_not_affect_others(self, manager):
        """重置一个用户不应影响其他用户."""
        manager.switch_scene("work_dev", user_id="user1")
        manager.switch_scene("life_manage", user_id="user2")

        manager.reset_user("user1")

        # user1 被重置
        assert manager.get_current_scene("user1") == DEFAULT_SCENE
        # user2 不受影响
        assert manager.get_current_scene("user2") == "life_manage"
        assert manager.get_switch_count("user2") == 1

    # ------------------------------------------------------------------
    # 全局状态测试
    # ------------------------------------------------------------------

    def test_get_all_scene_status(self, manager):
        """获取所有用户场景状态."""
        manager.switch_scene("work_dev", user_id="user1")
        manager.switch_scene("life_manage", user_id="user2")

        status = manager.get_all_scene_status()
        assert "user1" in status
        assert "user2" in status

        assert status["user1"]["scene_id"] == "work_dev"
        assert status["user2"]["scene_id"] == "life_manage"
        assert "scene_name" in status["user1"]
        assert "switch_count" in status["user1"]

    def test_get_all_scene_status_empty(self, manager):
        """无用户时状态应为空字典."""
        status = manager.get_all_scene_status()
        assert status == {}

    # ------------------------------------------------------------------
    # 场景定义测试
    # ------------------------------------------------------------------

    def test_all_scenes_switchable(self, manager):
        """所有预定义场景都应能切换."""
        for scene_id in SCENE_DEFINITIONS:
            result = manager.switch_scene(scene_id, user_id="test_user")
            assert result["success"] is True, f"切换到 {scene_id} 失败"
            assert manager.get_current_scene("test_user") == scene_id
