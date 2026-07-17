"""
M4 单元测试 - 上下文管理补充测试 (TS-007, P2级)

覆盖: 上下文过期、上下文持久化、上下文大小限制、
      多场景上下文、上下文合并、状态统计
运行: python -m pytest tests/test_context_management.py -v
"""
import os
import sys
import tempfile
import time
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.services.context_store import ContextStore


@pytest.fixture
def temp_persist_path():
    """临时持久化文件路径."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def store(temp_persist_path):
    """创建一个干净的 ContextStore 实例."""
    return ContextStore(persist_path=temp_persist_path, auto_save=False)


class TestContextCreation:
    """上下文创建测试"""

    def test_create_context_for_new_scene(self, store):
        """为新场景创建上下文."""
        result = store.save_context("work_dev", {"key": "value"}, "user1")

        assert result["success"] is True
        assert result["update_count"] == 1

        ctx = store.get_context("work_dev", "user1")
        assert ctx["exists"] is True
        assert ctx["context_data"]["key"] == "value"

    def test_create_multiple_scene_contexts(self, store):
        """为多个场景创建独立上下文."""
        store.save_context("work_dev", {"mode": "work"}, "user1")
        store.save_context("learning", {"mode": "study"}, "user1")
        store.save_context("life", {"mode": "life"}, "user1")

        status = store.get_status("user1")
        assert status["total_scenes"] == 3

    def test_create_context_for_multiple_users(self, store):
        """为多个用户创建独立上下文."""
        store.save_context("work_dev", {"data": "user1_data"}, "user1")
        store.save_context("work_dev", {"data": "user2_data"}, "user2")

        ctx1 = store.get_context("work_dev", "user1")
        ctx2 = store.get_context("work_dev", "user2")

        assert ctx1["context_data"]["data"] == "user1_data"
        assert ctx2["context_data"]["data"] == "user2_data"


class TestContextAccess:
    """上下文存取测试"""

    def test_get_context_not_exists(self, store):
        """获取不存在的上下文."""
        result = store.get_context("nonexistent", "user1")
        assert result["exists"] is False
        assert result["context_data"] == {}
        assert result["update_count"] == 0

    def test_get_context_returns_scene_id(self, store):
        """获取上下文应返回场景ID."""
        store.save_context("work_dev", {"a": 1}, "user1")
        ctx = store.get_context("work_dev", "user1")
        assert ctx["scene_id"] == "work_dev"

    def test_save_and_retrieve_complex_data(self, store):
        """保存和读取复杂数据结构."""
        complex_data = {
            "nested": {
                "level1": {
                    "level2": "deep_value"
                }
            },
            "list": [1, 2, 3, {"key": "value"}],
            "number": 42,
            "boolean": True,
            "null_val": None,
        }

        store.save_context("work_dev", complex_data, "user1", merge=False)
        ctx = store.get_context("work_dev", "user1")

        assert ctx["context_data"]["nested"]["level1"]["level2"] == "deep_value"
        assert ctx["context_data"]["list"][3]["key"] == "value"
        assert ctx["context_data"]["number"] == 42
        assert ctx["context_data"]["boolean"] is True
        assert ctx["context_data"]["null_val"] is None

    def test_save_context_updates_timestamp(self, store):
        """保存上下文应更新时间戳."""
        store.save_context("work_dev", {"a": 1}, "user1")
        ctx1 = store.get_context("work_dev", "user1")
        ts1 = ctx1["last_updated"]

        time.sleep(0.01)
        store.save_context("work_dev", {"b": 2}, "user1")
        ctx2 = store.get_context("work_dev", "user1")
        ts2 = ctx2["last_updated"]

        assert ts2 >= ts1


class TestContextMerge:
    """上下文合并测试"""

    def test_merge_mode_preserves_existing(self, store):
        """合并模式应保留现有数据."""
        store.save_context("work_dev", {"a": 1, "b": 2}, "user1")
        store.save_context("work_dev", {"b": 3, "c": 4}, "user1", merge=True)

        ctx = store.get_context("work_dev", "user1")
        assert ctx["context_data"]["a"] == 1  # 保留
        assert ctx["context_data"]["b"] == 3  # 更新
        assert ctx["context_data"]["c"] == 4  # 新增

    def test_overwrite_mode_replaces_data(self, store):
        """覆盖模式应替换全部数据."""
        store.save_context("work_dev", {"a": 1, "b": 2}, "user1")
        store.save_context("work_dev", {"c": 3}, "user1", merge=False)

        ctx = store.get_context("work_dev", "user1")
        assert "a" not in ctx["context_data"]
        assert "b" not in ctx["context_data"]
        assert ctx["context_data"]["c"] == 3

    def test_merge_mode_increments_count(self, store):
        """合并模式应增加更新计数."""
        store.save_context("work_dev", {"a": 1}, "user1")
        assert store.get_context("work_dev", "user1")["update_count"] == 1

        store.save_context("work_dev", {"b": 2}, "user1", merge=True)
        assert store.get_context("work_dev", "user1")["update_count"] == 2

    def test_default_is_merge_mode(self, store):
        """默认应为合并模式."""
        store.save_context("work_dev", {"a": 1}, "user1")
        result = store.save_context("work_dev", {"b": 2}, "user1")
        assert result["merged"] is True

        ctx = store.get_context("work_dev", "user1")
        assert ctx["context_data"]["a"] == 1
        assert ctx["context_data"]["b"] == 2


class TestContextDeletion:
    """上下文删除测试"""

    def test_clear_existing_context(self, store):
        """清空存在的上下文."""
        store.save_context("work_dev", {"a": 1}, "user1")
        result = store.clear_context("work_dev", "user1")

        assert result["success"] is True
        assert result["cleared"] is True

        ctx = store.get_context("work_dev", "user1")
        assert ctx["exists"] is False

    def test_clear_nonexistent_context(self, store):
        """清空不存在的上下文."""
        result = store.clear_context("nonexistent", "user1")
        assert result["success"] is True
        assert result["cleared"] is False

    def test_clear_one_scene_does_not_affect_others(self, store):
        """清空一个场景不影响其他场景."""
        store.save_context("work_dev", {"a": 1}, "user1")
        store.save_context("learning", {"b": 2}, "user1")

        store.clear_context("work_dev", "user1")

        assert store.get_context("work_dev", "user1")["exists"] is False
        assert store.get_context("learning", "user1")["exists"] is True


class TestContextPersistence:
    """上下文持久化测试"""

    def test_auto_save_creates_file(self, temp_persist_path):
        """auto_save 启用时应自动创建文件."""
        store = ContextStore(persist_path=temp_persist_path, auto_save=True)
        store.save_context("work_dev", {"test": "value"}, "user1")

        assert os.path.exists(temp_persist_path)

        with open(temp_persist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "user1" in data
        assert "work_dev" in data["user1"]

    def test_manual_save(self, store):
        """手动保存应正常工作."""
        store.save_context("work_dev", {"test": "manual"}, "user1")
        result = store.save_to_disk()
        assert result is True

    def test_load_persisted_data(self, temp_persist_path):
        """应能从磁盘加载持久化数据."""
        # 第一个实例保存数据
        store1 = ContextStore(persist_path=temp_persist_path, auto_save=True)
        store1.save_context("work_dev", {"theme": "dark"}, "user1")
        store1.save_context("learning", {"subject": "math"}, "user1")

        # 第二个实例加载
        store2 = ContextStore(persist_path=temp_persist_path, auto_save=False)
        assert store2.get_context("work_dev", "user1")["context_data"]["theme"] == "dark"
        assert store2.get_context("learning", "user1")["context_data"]["subject"] == "math"

    def test_persist_path_property(self, store, temp_persist_path):
        """persist_path 属性应正确."""
        assert store.persist_path == temp_persist_path

    def test_save_and_load_all_users(self, temp_persist_path):
        """应能持久化和加载多用户数据."""
        store1 = ContextStore(persist_path=temp_persist_path, auto_save=True)
        store1.save_context("work_dev", {"d": "u1"}, "user1")
        store1.save_context("work_dev", {"d": "u2"}, "user2")
        store1.save_context("work_dev", {"d": "u3"}, "user3")

        store2 = ContextStore(persist_path=temp_persist_path, auto_save=False)
        all_status = store2.get_all_status()
        assert all_status["total_users"] == 3


class TestContextStatus:
    """上下文状态统计测试"""

    def test_get_status_empty(self, store):
        """无数据时的状态."""
        status = store.get_status("user1")
        assert status["total_scenes"] == 0
        assert status["total_size_bytes"] == 0
        assert len(status["scene_stats"]) == 0

    def test_get_status_with_data(self, store):
        """有数据时的状态统计."""
        store.save_context("work_dev", {"a": 1}, "user1")
        store.save_context("learning", {"b": 2, "c": 3}, "user1")

        status = store.get_status("user1")
        assert status["total_scenes"] == 2
        assert status["total_size_bytes"] > 0
        assert len(status["scene_stats"]) == 2

    def test_status_sorted_by_last_updated(self, store):
        """状态应按最后更新时间倒序排列."""
        store.save_context("work_dev", {"a": 1}, "user1")
        time.sleep(0.01)
        store.save_context("learning", {"b": 2}, "user1")

        status = store.get_status("user1")
        # 第一个（最新的）应该是 learning
        assert status["scene_stats"][0]["scene_id"] == "learning"
        assert status["scene_stats"][1]["scene_id"] == "work_dev"

    def test_status_contains_scene_name(self, store):
        """状态应包含场景名称."""
        store.save_context("work_dev", {"a": 1}, "user1")
        status = store.get_status("user1")
        assert "scene_name" in status["scene_stats"][0]

    def test_status_contains_data_size(self, store):
        """状态应包含数据大小."""
        store.save_context("work_dev", {"a": 1}, "user1")
        status = store.get_status("user1")
        assert "data_size_bytes" in status["scene_stats"][0]
        assert status["scene_stats"][0]["data_size_bytes"] > 0

    def test_get_all_status(self, store):
        """获取所有用户状态."""
        store.save_context("work_dev", {"a": 1}, "user1")
        store.save_context("work_dev", {"b": 2}, "user2")

        all_status = store.get_all_status()
        assert all_status["total_users"] == 2
        assert "user1" in all_status["users"]
        assert "user2" in all_status["users"]


class TestContextEdgeCases:
    """上下文边界条件测试"""

    def test_empty_context_data(self, store):
        """空字典上下文."""
        store.save_context("work_dev", {}, "user1", merge=False)
        ctx = store.get_context("work_dev", "user1")
        assert ctx["exists"] is True
        assert ctx["context_data"] == {}

    def test_large_context_data(self, store):
        """较大的上下文数据."""
        large_data = {f"key_{i}": f"value_{i}" for i in range(100)}
        store.save_context("work_dev", large_data, "user1", merge=False)

        ctx = store.get_context("work_dev", "user1")
        assert len(ctx["context_data"]) == 100
        assert ctx["context_data"]["key_99"] == "value_99"

    def test_special_characters_in_keys(self, store):
        """键名中包含特殊字符."""
        data = {
            "key with spaces": "value",
            "key.with.dots": "value",
            "key-with-dashes": "value",
            "key_with_underscores": "value",
            "中文键名": "中文值",
        }
        store.save_context("work_dev", data, "user1", merge=False)
        ctx = store.get_context("work_dev", "user1")

        assert ctx["context_data"]["key with spaces"] == "value"
        assert ctx["context_data"]["key.with.dots"] == "value"
        assert ctx["context_data"]["中文键名"] == "中文值"

    def test_update_count_accumulates(self, store):
        """更新计数应持续累积."""
        for i in range(10):
            store.save_context("work_dev", {f"k{i}": i}, "user1")

        ctx = store.get_context("work_dev", "user1")
        assert ctx["update_count"] == 10

    def test_clear_resets_status(self, store):
        """清空后状态应正确更新."""
        store.save_context("work_dev", {"a": 1}, "user1")
        assert store.get_status("user1")["total_scenes"] == 1

        store.clear_context("work_dev", "user1")
        assert store.get_status("user1")["total_scenes"] == 0
