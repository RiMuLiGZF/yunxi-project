"""ContextStore 单元测试.

测试 ContextStore 的核心功能：
- 上下文 CRUD（获取/保存/清空）
- 多用户隔离
- 合并 vs 覆盖模式
- JSON 文件持久化
- 状态概览
"""

import os
import sys
import tempfile
import time

import pytest

# 添加 src 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.services.context_store import ContextStore


@pytest.fixture
def temp_persist_path():
    """临时持久化文件路径."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    yield path
    # 清理
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def store(temp_persist_path):
    """创建一个干净的 ContextStore 实例."""
    return ContextStore(persist_path=temp_persist_path, auto_save=False)


class TestContextStore:
    """ContextStore 测试类."""

    # ------------------------------------------------------------------
    # 基础 CRUD 测试
    # ------------------------------------------------------------------

    def test_get_context_not_exists(self, store):
        """获取不存在的上下文应返回默认结构."""
        result = store.get_context("work_dev", "user1")
        assert result["scene_id"] == "work_dev"
        assert result["context_data"] == {}
        assert result["exists"] is False
        assert result["update_count"] == 0

    def test_save_context_new(self, store):
        """保存新上下文应成功."""
        data = {"theme": "dark", "font_size": 14}
        result = store.save_context("work_dev", data, "user1")
        assert result["success"] is True
        assert result["scene_id"] == "work_dev"
        assert result["update_count"] == 1
        assert result["merged"] is True

        # 验证保存成功
        ctx = store.get_context("work_dev", "user1")
        assert ctx["exists"] is True
        assert ctx["context_data"]["theme"] == "dark"
        assert ctx["context_data"]["font_size"] == 14
        assert ctx["update_count"] == 1

    def test_save_context_merge(self, store):
        """合并模式应保留旧字段并更新/新增字段."""
        store.save_context("work_dev", {"a": 1, "b": 2}, "user1")
        result = store.save_context("work_dev", {"b": 3, "c": 4}, "user1", merge=True)

        assert result["merged"] is True
        ctx = store.get_context("work_dev", "user1")
        assert ctx["context_data"]["a"] == 1  # 保留
        assert ctx["context_data"]["b"] == 3  # 更新
        assert ctx["context_data"]["c"] == 4  # 新增
        assert ctx["update_count"] == 2

    def test_save_context_overwrite(self, store):
        """覆盖模式应替换全部数据."""
        store.save_context("work_dev", {"a": 1, "b": 2}, "user1")
        result = store.save_context("work_dev", {"c": 3}, "user1", merge=False)

        assert result["merged"] is False
        ctx = store.get_context("work_dev", "user1")
        assert "a" not in ctx["context_data"]
        assert ctx["context_data"]["c"] == 3
        assert ctx["update_count"] == 1  # 覆盖模式 reset 计数

    def test_clear_context_exists(self, store):
        """清空存在的上下文应成功."""
        store.save_context("work_dev", {"a": 1}, "user1")
        result = store.clear_context("work_dev", "user1")

        assert result["success"] is True
        assert result["cleared"] is True

        ctx = store.get_context("work_dev", "user1")
        assert ctx["exists"] is False

    def test_clear_context_not_exists(self, store):
        """清空不存在的上下文应返回 cleared=False."""
        result = store.clear_context("nonexistent", "user1")
        assert result["success"] is True
        assert result["cleared"] is False

    # ------------------------------------------------------------------
    # 多用户隔离测试
    # ------------------------------------------------------------------

    def test_multi_user_isolation(self, store):
        """不同用户的上下文应完全隔离."""
        store.save_context("work_dev", {"data": "user1_data"}, "user1")
        store.save_context("work_dev", {"data": "user2_data"}, "user2")

        ctx1 = store.get_context("work_dev", "user1")
        ctx2 = store.get_context("work_dev", "user2")

        assert ctx1["context_data"]["data"] == "user1_data"
        assert ctx2["context_data"]["data"] == "user2_data"

    def test_default_user(self, store):
        """不传 user_id 应使用 default 用户."""
        store.save_context("work_dev", {"data": "default_user"})
        ctx1 = store.get_context("work_dev")
        ctx2 = store.get_context("work_dev", "default")
        assert ctx1["context_data"] == ctx2["context_data"]

    # ------------------------------------------------------------------
    # 状态概览测试
    # ------------------------------------------------------------------

    def test_get_status_empty(self, store):
        """无数据时状态概览应有默认值."""
        status = store.get_status("user1")
        assert status["user_id"] == "user1"
        assert status["total_scenes"] == 0
        assert status["total_size_bytes"] == 0
        assert len(status["scene_stats"]) == 0
        assert "all_scenes" in status

    def test_get_status_with_data(self, store):
        """有数据时状态概览应正确统计."""
        store.save_context("work_dev", {"a": 1}, "user1")
        store.save_context("life_manage", {"b": 2}, "user1")

        status = store.get_status("user1")
        assert status["total_scenes"] == 2
        assert status["total_size_bytes"] > 0
        assert len(status["scene_stats"]) == 2
        # 按最后更新时间倒序
        assert status["scene_stats"][0]["last_updated"] >= status["scene_stats"][1]["last_updated"]

    def test_get_all_status(self, store):
        """获取所有用户状态."""
        store.save_context("work_dev", {"a": 1}, "user1")
        store.save_context("work_dev", {"b": 2}, "user2")
        store.save_context("life_manage", {"c": 3}, "user2")

        all_status = store.get_all_status()
        assert all_status["total_users"] == 2
        assert all_status["users"]["user1"]["scene_count"] == 1
        assert all_status["users"]["user2"]["scene_count"] == 2

    # ------------------------------------------------------------------
    # 持久化测试
    # ------------------------------------------------------------------

    def test_persist_path_property(self, store, temp_persist_path):
        """persist_path 属性应返回正确路径."""
        assert store.persist_path == temp_persist_path

    def test_save_and_load_persistence(self, temp_persist_path):
        """数据应能持久化到磁盘并重新加载."""
        # 第一个实例保存数据
        store1 = ContextStore(persist_path=temp_persist_path, auto_save=True)
        store1.save_context("work_dev", {"theme": "light"}, "user1")

        # 第二个实例加载数据
        store2 = ContextStore(persist_path=temp_persist_path, auto_save=False)
        ctx = store2.get_context("work_dev", "user1")
        assert ctx["exists"] is True
        assert ctx["context_data"]["theme"] == "light"

    def test_manual_save_load(self, store):
        """手动保存和加载应正常工作."""
        store.save_context("work_dev", {"test": "value"}, "user1")
        assert store.save_to_disk() is True

        # 修改内存数据
        store.save_context("work_dev", {"modified": True}, "user1", merge=False)

        # 重新加载，应该恢复到磁盘上的数据
        assert store.load_from_disk() is True
        ctx = store.get_context("work_dev", "user1")
        assert ctx["context_data"]["test"] == "value"

    def test_auto_save_enabled(self, temp_persist_path):
        """auto_save=True 时每次保存应自动落盘."""
        store = ContextStore(persist_path=temp_persist_path, auto_save=True)
        store.save_context("work_dev", {"auto": "save"}, "user1")

        # 直接读文件验证
        import json
        with open(temp_persist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "user1" in data
        assert data["user1"]["work_dev"]["context_data"]["auto"] == "save"

    def test_load_from_nonexistent_file(self, temp_persist_path):
        """加载不存在的文件应返回 False 且不报错."""
        nonexistent = temp_persist_path + ".nonexistent"
        store = ContextStore(persist_path=nonexistent, auto_save=False)
        assert store.load_from_disk() is False
        # 不应该有任何数据
        status = store.get_status("default")
        assert status["total_scenes"] == 0

    # ------------------------------------------------------------------
    # 多场景测试
    # ------------------------------------------------------------------

    def test_multiple_scenes(self, store):
        """同一用户多个场景应独立存储."""
        scenes = ["work_dev", "life_manage", "study_plan", "review_summary"]
        for i, scene in enumerate(scenes):
            store.save_context(scene, {"index": i}, "user1")

        for i, scene in enumerate(scenes):
            ctx = store.get_context(scene, "user1")
            assert ctx["exists"] is True
            assert ctx["context_data"]["index"] == i
