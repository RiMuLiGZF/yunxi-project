"""
M7 单元测试 - 工作流版本管理测试

覆盖: 版本创建、版本列表、版本对比、版本回滚
运行: python -m pytest tests/test_version_manager.py -v
"""
import os
import sys
import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from services.version_manager import WorkflowVersionManager


@pytest.fixture
def temp_dir():
    """临时目录 fixture"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def version_manager(temp_dir):
    """版本管理器 fixture"""
    mgr = WorkflowVersionManager(data_dir=temp_dir)
    return mgr


@pytest.fixture
def sample_workflow():
    """示例工作流"""
    return {
        "id": "wf_test_001",
        "name": "测试工作流",
        "description": "这是一个测试工作流",
        "blocks": [
            {"id": "start", "type": "start", "name": "开始", "next": ["end"]},
            {"id": "end", "type": "end", "name": "结束", "next": []},
        ],
        "variables": {},
        "created_at": 1234567890,
    }


class TestWorkflowVersionManager:
    """工作流版本管理器测试"""

    def test_init(self, version_manager):
        """初始化测试"""
        assert version_manager is not None
        assert version_manager._versions_dir is not None

    def test_create_version_initial(self, version_manager, sample_workflow):
        """创建初始版本"""
        result = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="初始版本",
            bump_type="major",
            created_by="test_user",
        )

        assert result["success"] is True
        assert result["version"] == "1.0.0"
        assert result["version_note"] == "初始版本"
        assert result["created_by"] == "test_user"
        assert "version_id" in result
        assert "created_at" in result

    def test_create_version_minor_bump(self, version_manager, sample_workflow):
        """创建次版本号升级"""
        # 先创建初始版本
        version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="v1",
            bump_type="major",
            created_by="user1",
        )

        # 修改工作流
        sample_workflow["description"] = "更新后的描述"

        # 创建次版本
        result = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="添加新功能",
            bump_type="minor",
            created_by="user1",
        )

        assert result["success"] is True
        assert result["version"] == "1.1.0"
        assert result["version_note"] == "添加新功能"

    def test_create_version_patch_bump(self, version_manager, sample_workflow):
        """创建修订版本号升级"""
        version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="v1",
            bump_type="major",
            created_by="user1",
        )

        sample_workflow["description"] = "修复bug"
        result = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="修复 Bug",
            bump_type="patch",
            created_by="user2",
        )

        assert result["success"] is True
        assert result["version"] == "1.0.1"

    def test_list_versions_empty(self, version_manager):
        """空版本列表"""
        result = version_manager.list_versions("nonexistent")
        assert result["success"] is True
        assert result["total"] == 0
        assert result["versions"] == []

    def test_list_versions_multiple(self, version_manager, sample_workflow):
        """多版本列表"""
        for i in range(3):
            sample_workflow["description"] = f"版本{i}"
            version_manager.create_version(
                workflow_id="wf_test_001",
                workflow_data=sample_workflow,
                version_note=f"v{i}",
                bump_type="patch",
                created_by="user",
            )

        result = version_manager.list_versions("wf_test_001")
        assert result["success"] is True
        assert result["total"] == 3
        assert len(result["versions"]) == 3
        # 按创建时间倒序
        assert result["versions"][0]["version"] > result["versions"][2]["version"]

    def test_get_version(self, version_manager, sample_workflow):
        """获取单个版本"""
        create_result = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="测试版本",
            bump_type="major",
            created_by="user",
        )

        version_id = create_result["version_id"]
        result = version_manager.get_version("wf_test_001", version_id)

        assert result is not None
        assert result["version_id"] == version_id
        assert result["version"] == "1.0.0"
        assert "workflow_data" in result

    def test_get_version_not_found(self, version_manager):
        """获取不存在的版本"""
        result = version_manager.get_version("wf_test_001", "nonexistent")
        assert result is None

    def test_compare_versions(self, version_manager, sample_workflow):
        """版本对比"""
        # 创建第一个版本
        r1 = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="v1",
            bump_type="major",
            created_by="user",
        )

        # 修改工作流
        modified = dict(sample_workflow)
        modified["description"] = "更新后的描述"
        modified["blocks"].append({"id": "new_block", "type": "llm", "name": "新节点", "next": []})

        r2 = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=modified,
            version_note="v2",
            bump_type="minor",
            created_by="user",
        )

        result = version_manager.compare_versions(
            workflow_id="wf_test_001",
            version_a_id=r1["version_id"],
            version_b_id=r2["version_id"],
        )

        assert result["success"] is True
        assert "differences" in result
        assert result["version_a"] == r1["version"]
        assert result["version_b"] == r2["version"]
        assert len(result["differences"]) > 0

    def test_compare_versions_same(self, version_manager, sample_workflow):
        """相同版本对比"""
        r1 = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="v1",
            bump_type="major",
            created_by="user",
        )

        result = version_manager.compare_versions(
            workflow_id="wf_test_001",
            version_a_id=r1["version_id"],
            version_b_id=r1["version_id"],
        )

        assert result["success"] is True
        assert len(result["differences"]) == 0

    def test_compare_versions_not_found(self, version_manager):
        """对比不存在的版本"""
        result = version_manager.compare_versions(
            workflow_id="wf_test_001",
            version_a_id="v1",
            version_b_id="v2",
        )

        assert result["success"] is False
        assert "error" in result

    def test_rollback_to_version(self, version_manager, sample_workflow):
        """版本回滚"""
        # 创建 v1
        r1 = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="v1",
            bump_type="major",
            created_by="user",
        )

        # 创建 v2
        modified = dict(sample_workflow)
        modified["description"] = "v2 description"
        r2 = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=modified,
            version_note="v2",
            bump_type="minor",
            created_by="user",
        )

        # mock storage
        mock_storage = MagicMock()
        mock_storage.upsert_workflow = MagicMock()
        mock_storage.get_workflow = MagicMock(return_value=modified)

        # 回滚到 v1
        result = version_manager.rollback_to_version(
            workflow_id="wf_test_001",
            version_id=r1["version_id"],
            storage=mock_storage,
            rollback_note="回滚到v1",
        )

        assert result["success"] is True
        assert result["rolled_back"] is True
        assert "new_version_id" in result
        # 回滚后应该创建新版本
        versions = version_manager.list_versions("wf_test_001")
        assert versions["total"] == 3  # v1, v2, 回滚版本

    def test_delete_version(self, version_manager, sample_workflow):
        """删除版本"""
        r1 = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="v1",
            bump_type="major",
            created_by="user",
        )

        result = version_manager.delete_version("wf_test_001", r1["version_id"])
        assert result["success"] is True

        # 确认已删除
        versions = version_manager.list_versions("wf_test_001")
        assert versions["total"] == 0

    def test_delete_version_not_found(self, version_manager):
        """删除不存在的版本"""
        result = version_manager.delete_version("wf_test_001", "nonexistent")
        assert result["success"] is False

    def test_get_latest_version(self, version_manager, sample_workflow):
        """获取最新版本"""
        for i in range(3):
            sample_workflow["description"] = f"v{i}"
            version_manager.create_version(
                workflow_id="wf_test_001",
                workflow_data=sample_workflow,
                version_note=f"v{i}",
                bump_type="patch",
                created_by="user",
            )

        latest = version_manager.get_latest_version("wf_test_001")
        assert latest is not None
        assert latest["version"] == "0.0.2"  # patch 递增

    def test_get_latest_version_empty(self, version_manager):
        """获取最新版本 - 空"""
        latest = version_manager.get_latest_version("nonexistent")
        assert latest is None

    def test_version_semver_format(self, version_manager, sample_workflow):
        """版本号格式验证"""
        result = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="测试",
            bump_type="major",
            created_by="user",
        )

        version = result["version"]
        parts = version.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_multiple_workflows(self, version_manager, sample_workflow):
        """多个工作流版本互不干扰"""
        version_manager.create_version(
            workflow_id="wf_1",
            workflow_data=sample_workflow,
            version_note="v1",
            bump_type="major",
            created_by="user",
        )
        version_manager.create_version(
            workflow_id="wf_2",
            workflow_data=sample_workflow,
            version_note="v1",
            bump_type="major",
            created_by="user",
        )

        v1 = version_manager.list_versions("wf_1")
        v2 = version_manager.list_versions("wf_2")

        assert v1["total"] == 1
        assert v2["total"] == 1
        # 两个工作流的版本 ID 不同
        assert v1["versions"][0]["version_id"] != v2["versions"][0]["version_id"]


class TestVersionRecord:
    """版本记录数据结构测试"""

    def test_version_record_structure(self, version_manager, sample_workflow):
        """版本记录结构验证"""
        result = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="测试版本",
            bump_type="major",
            created_by="user",
        )

        assert "version_id" in result
        assert "version" in result
        assert "workflow_id" in result
        assert "version_note" in result
        assert "created_by" in result
        assert "created_at" in result
        assert "workflow_data" in result

    def test_version_record_to_dict(self, version_manager, sample_workflow):
        """版本记录转字典"""
        result = version_manager.create_version(
            workflow_id="wf_test_001",
            workflow_data=sample_workflow,
            version_note="测试",
            bump_type="major",
            created_by="user",
        )

        assert isinstance(result, dict)
        assert result["version"] == "1.0.0"
        assert "workflow_data" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
