"""工作区管理器单元测试 (>=20 用例)"""
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# 确保可以导入 backend 模块
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, WorkspaceProject, DevActivity


@pytest.fixture
def db_engine(tmp_path):
    """创建临时内存 SQLite 引擎"""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """创建数据库会话"""
    Session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def workspace_root(tmp_path):
    """临时工作区根目录"""
    root = tmp_path / "workspace"
    root.mkdir()
    return str(root)


@pytest.fixture
def mock_settings(workspace_root):
    """模拟配置"""
    settings = MagicMock()
    settings.workspace_root = workspace_root
    settings.scan_dirs = [workspace_root]
    settings.debug = False
    return settings


@pytest.fixture
def manager(db_session, mock_settings):
    """创建工作区管理器"""
    from workspace_manager import WorkspaceManager
    mgr = WorkspaceManager.__new__(WorkspaceManager)
    mgr.settings = mock_settings
    mgr._db = db_session
    mgr._lock = __import__("threading").RLock()
    return mgr


class TestCreateProject:
    """创建项目测试"""

    def test_create_normal_project(self, manager, workspace_root):
        """正常创建项目"""
        path = os.path.join(workspace_root, "my_project")
        result = manager.create_project(
            name="My Project",
            path=path,
            description="A test project"
        )
        assert result["success"] is True
        assert result["project"]["name"] == "My Project"
        assert result["project"]["path"] == path

    def test_create_project_with_tags(self, manager, workspace_root):
        """创建带标签的项目"""
        path = os.path.join(workspace_root, "tagged_project")
        result = manager.create_project(
            name="Tagged Project",
            path=path,
            tags=["python", "web"]
        )
        assert result["success"] is True
        assert "python" in result["project"]["tags"]

    def test_create_project_duplicate_path(self, manager, workspace_root):
        """重复路径"""
        path = os.path.join(workspace_root, "dup_project")
        manager.create_project(name="First", path=path)
        result = manager.create_project(name="Second", path=path)
        assert result["success"] is False
        assert "已存在" in result["message"]

    def test_create_project_path_traversal(self, manager, workspace_root):
        """路径遍历被拒绝"""
        result = manager.create_project(
            name="Hacked",
            path=os.path.join(workspace_root, "..", "etc", "passwd")
        )
        assert result["success"] is False
        assert "路径安全" in result["message"]

    def test_create_project_default_icon(self, manager, workspace_root):
        """默认图标"""
        path = os.path.join(workspace_root, "default_icon")
        result = manager.create_project(name="Test", path=path)
        assert result["project"]["icon"] == "folder"


class TestGetProject:
    """获取项目测试"""

    def test_get_existing_project(self, manager, workspace_root):
        """获取存在的项目"""
        path = os.path.join(workspace_root, "existing")
        created = manager.create_project(name="Exists", path=path)
        project_id = created["project"]["id"]
        result = manager.get_project(project_id)
        assert result is not None
        assert result["name"] == "Exists"

    def test_get_nonexistent_project(self, manager):
        """获取不存在的项目"""
        result = manager.get_project(99999)
        assert result is None

    def test_get_project_by_path(self, manager, workspace_root):
        """根据路径获取项目"""
        path = os.path.join(workspace_root, "by_path")
        manager.create_project(name="ByPath", path=path)
        result = manager.get_project_by_path(path)
        assert result is not None
        assert result["name"] == "ByPath"

    def test_get_project_by_path_nonexistent(self, manager):
        """根据路径获取不存在的项目"""
        result = manager.get_project_by_path("/nonexistent/path")
        assert result is None


class TestListProjects:
    """列出项目测试"""

    def test_list_all_projects(self, manager, workspace_root):
        """列出所有项目"""
        for i in range(3):
            path = os.path.join(workspace_root, f"project_{i}")
            manager.create_project(name=f"Project {i}", path=path)
        result = manager.list_projects()
        assert len(result) == 3

    def test_list_with_keyword(self, manager, workspace_root):
        """关键词搜索"""
        path1 = os.path.join(workspace_root, "alpha")
        path2 = os.path.join(workspace_root, "beta")
        manager.create_project(name="Alpha Project", path=path1)
        manager.create_project(name="Beta Project", path=path2)
        result = manager.list_projects(keyword="Alpha")
        assert len(result) == 1
        assert "Alpha" in result[0]["name"]

    def test_list_with_tag_filter(self, manager, workspace_root):
        """标签过滤"""
        path1 = os.path.join(workspace_root, "tagged_a")
        path2 = os.path.join(workspace_root, "tagged_b")
        manager.create_project(name="A", path=path1, tags=["python"])
        manager.create_project(name="B", path=path2, tags=["web"])
        result = manager.list_projects(tag="python")
        assert len(result) == 1
        assert result[0]["name"] == "A"


class TestUpdateProject:
    """更新项目测试"""

    def test_update_project_name(self, manager, workspace_root):
        """更新项目名称"""
        path = os.path.join(workspace_root, "update_me")
        created = manager.create_project(name="Original", path=path)
        project_id = created["project"]["id"]
        result = manager.update_project(project_id, name="Updated")
        assert result["success"] is True
        assert result["project"]["name"] == "Updated"

    def test_update_project_description(self, manager, workspace_root):
        """更新项目描述"""
        path = os.path.join(workspace_root, "desc_update")
        created = manager.create_project(name="Test", path=path)
        project_id = created["project"]["id"]
        result = manager.update_project(project_id, description="New description")
        assert result["success"] is True
        assert result["project"]["description"] == "New description"

    def test_update_nonexistent_project(self, manager):
        """更新不存在的项目"""
        result = manager.update_project(99999, name="Nope")
        assert result["success"] is False
        assert "不存在" in result["message"]


class TestDeleteProject:
    """删除项目测试"""

    def test_delete_existing_project(self, manager, workspace_root):
        """正常删除"""
        path = os.path.join(workspace_root, "delete_me")
        created = manager.create_project(name="Delete", path=path)
        project_id = created["project"]["id"]
        result = manager.delete_project(project_id)
        assert result["success"] is True

    def test_delete_nonexistent_project(self, manager):
        """删除不存在的项目"""
        result = manager.delete_project(99999)
        assert result["success"] is False
        assert "不存在" in result["message"]

    def test_delete_then_get(self, manager, workspace_root):
        """删除后获取返回 None"""
        path = os.path.join(workspace_root, "del_get")
        created = manager.create_project(name="DelGet", path=path)
        project_id = created["project"]["id"]
        manager.delete_project(project_id)
        assert manager.get_project(project_id) is None


class TestTagManagement:
    """标签管理测试"""

    def test_add_tag(self, manager, workspace_root):
        """添加标签"""
        path = os.path.join(workspace_root, "tag_add")
        created = manager.create_project(name="TagAdd", path=path)
        project_id = created["project"]["id"]
        result = manager.add_tag(project_id, "new_tag")
        assert result["success"] is True
        assert "new_tag" in result["tags"]

    def test_add_duplicate_tag(self, manager, workspace_root):
        """添加重复标签不重复"""
        path = os.path.join(workspace_root, "dup_tag")
        created = manager.create_project(name="DupTag", path=path, tags=["existing"])
        project_id = created["project"]["id"]
        result = manager.add_tag(project_id, "existing")
        assert result["success"] is True
        assert result["tags"].count("existing") == 1

    def test_remove_tag(self, manager, workspace_root):
        """移除标签"""
        path = os.path.join(workspace_root, "rem_tag")
        created = manager.create_project(name="RemTag", path=path, tags=["to_remove"])
        project_id = created["project"]["id"]
        result = manager.remove_tag(project_id, "to_remove")
        assert result["success"] is True
        assert "to_remove" not in result["tags"]

    def test_get_all_tags(self, manager, workspace_root):
        """获取所有标签"""
        path1 = os.path.join(workspace_root, "tags_a")
        path2 = os.path.join(workspace_root, "tags_b")
        manager.create_project(name="A", path=path1, tags=["python", "web"])
        manager.create_project(name="B", path=path2, tags=["python", "mobile"])
        tags = manager.get_all_tags()
        assert "python" in tags
        assert "web" in tags
        assert "mobile" in tags

    def test_add_tag_nonexistent_project(self, manager):
        """为不存在的项目添加标签"""
        result = manager.add_tag(99999, "tag")
        assert result["success"] is False


class TestStatistics:
    """统计测试"""

    def test_get_statistics(self, manager, workspace_root):
        """获取统计信息"""
        path = os.path.join(workspace_root, "stats")
        manager.create_project(name="Stats", path=path)
        stats = manager.get_statistics()
        assert stats["total_projects"] == 1
        assert "tag_distribution" in stats
        assert "total_opens" in stats

    def test_statistics_empty(self, manager):
        """空工作区统计"""
        stats = manager.get_statistics()
        assert stats["total_projects"] == 0
        assert stats["total_opens"] == 0


class TestActivityLog:
    """活动记录测试"""

    def test_log_activity(self, manager):
        """记录活动"""
        result = manager.log_activity(
            project="TestProject",
            activity_type="coding",
            duration=30.5,
            description="Wrote unit tests"
        )
        assert result["success"] is True
        assert result["activity"]["project"] == "TestProject"

    def test_get_activities(self, manager):
        """获取活动"""
        manager.log_activity(project="P1", activity_type="coding")
        manager.log_activity(project="P1", activity_type="debugging")
        activities = manager.get_activities(project="P1")
        assert len(activities) == 2

    def test_get_activities_filter_by_type(self, manager):
        """按类型过滤活动"""
        manager.log_activity(project="P1", activity_type="coding")
        manager.log_activity(project="P1", activity_type="meeting")
        activities = manager.get_activities(activity_type="coding")
        assert len(activities) == 1
        assert activities[0]["activity_type"] == "coding"


class TestOpenProject:
    """打开项目测试"""

    def test_open_project(self, manager, workspace_root):
        """打开项目"""
        path = os.path.join(workspace_root, "open_me")
        created = manager.create_project(name="OpenMe", path=path)
        project_id = created["project"]["id"]
        result = manager.open_project(project_id)
        assert result["success"] is True
        assert result["project"]["open_count"] == 1
        assert result["project"]["last_opened"] is not None

    def test_open_nonexistent_project(self, manager):
        """打开不存在的项目"""
        result = manager.open_project(99999)
        assert result["success"] is False
