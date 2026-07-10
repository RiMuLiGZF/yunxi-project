"""
M9 开发者工坊 - 工作区管理测试
测试内容：
1. 项目 CRUD 操作
2. 项目扫描
3. 标签管理
4. 活动记录
5. 项目统计

使用方式：
    cd M9-dev-workshop/backend
    python -m pytest tests/test_workspace.py -v
    或
    python tests/test_workspace.py
"""

import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime

# 添加项目路径
backend_dir = Path(__file__).parent.parent.resolve()
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 导入模型和管理器
from models import Base, WorkspaceProject, DevActivity, SessionLocal
from workspace_manager import WorkspaceManager, get_workspace_manager


# ==================== Fixtures ====================

@pytest.fixture
def test_db():
    """创建内存数据库用于测试"""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # 替换 SessionLocal 为测试数据库
    original_session = SessionLocal
    from models import SessionLocal as SL
    # 注意：这里我们直接使用独立的session进行测试

    db = TestingSession()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def workspace_manager(test_db):
    """创建 WorkspaceManager 实例"""
    manager = WorkspaceManager()
    # 替换 manager 使用的数据库会话
    manager.db = test_db
    return manager


# ==================== 项目 CRUD 测试 ====================

class TestProjectCRUD:
    """项目增删改查测试"""

    def test_add_project(self, workspace_manager):
        """测试添加项目"""
        result = workspace_manager.add_project(
            path="/test/path/project1",
            name="测试项目",
            icon="📁",
            tags=["python", "test"],
        )
        assert result["success"] is True
        assert result["project"]["name"] == "测试项目"
        assert result["project"]["path"] == "/test/path/project1"

    def test_add_duplicate_project(self, workspace_manager):
        """测试添加重复路径的项目"""
        workspace_manager.add_project(path="/test/dup", name="项目1")
        result = workspace_manager.add_project(path="/test/dup", name="项目2")
        assert result["success"] is False
        assert "已存在" in result["message"]

    def test_get_project_by_path(self, workspace_manager):
        """测试按路径获取项目"""
        workspace_manager.add_project(path="/test/find", name="查找测试")
        project = workspace_manager.get_project_by_path("/test/find")
        assert project is not None
        assert project.name == "查找测试"

    def test_get_nonexistent_project(self, workspace_manager):
        """测试获取不存在的项目"""
        project = workspace_manager.get_project_by_path("/nonexistent")
        assert project is None

    def test_list_projects(self, workspace_manager):
        """测试项目列表"""
        for i in range(5):
            workspace_manager.add_project(
                path=f"/test/p{i}",
                name=f"项目{i}",
                tags=["tag1"] if i % 2 == 0 else ["tag2"],
            )
        projects = workspace_manager.list_projects()
        assert len(projects) == 5

    def test_list_projects_with_tag_filter(self, workspace_manager):
        """测试按标签筛选项目"""
        for i in range(5):
            workspace_manager.add_project(
                path=f"/test/p{i}",
                name=f"项目{i}",
                tags=["python"] if i % 2 == 0 else ["js"],
            )
        python_projects = workspace_manager.list_projects(tag="python")
        assert len(python_projects) == 3  # 0, 2, 4

    def test_list_projects_with_keyword(self, workspace_manager):
        """测试关键词搜索项目"""
        workspace_manager.add_project(path="/test/foo", name="FooProject")
        workspace_manager.add_project(path="/test/bar", name="BarProject")
        results = workspace_manager.list_projects(keyword="Foo")
        assert len(results) == 1
        assert results[0]["name"] == "FooProject"

    def test_delete_project(self, workspace_manager):
        """测试删除项目"""
        workspace_manager.add_project(path="/test/del", name="待删除")
        result = workspace_manager.delete_project(path="/test/del")
        assert result["success"] is True

        project = workspace_manager.get_project_by_path("/test/del")
        assert project is None

    def test_delete_nonexistent_project(self, workspace_manager):
        """测试删除不存在的项目"""
        result = workspace_manager.delete_project(path="/nonexistent")
        assert result["success"] is False


# ==================== 项目扫描测试 ====================

class TestProjectScan:
    """项目扫描功能测试"""

    def test_scan_with_invalid_dir(self, workspace_manager):
        """测试扫描不存在的目录"""
        result = workspace_manager.scan_projects(scan_dirs=["/nonexistent/path"])
        assert result["success"] is True  # 扫描失败不影响整体成功
        assert result["new_count"] >= 0

    def test_scan_with_empty_dirs(self, workspace_manager):
        """测试空目录列表扫描"""
        result = workspace_manager.scan_projects(scan_dirs=[])
        assert result["success"] is True


# ==================== 标签管理测试 ====================

class TestTagManagement:
    """标签管理测试"""

    def test_get_all_tags(self, workspace_manager):
        """测试获取所有标签"""
        workspace_manager.add_project(path="/test/t1", name="T1", tags=["python", "web"])
        workspace_manager.add_project(path="/test/t2", name="T2", tags=["python", "data"])
        workspace_manager.add_project(path="/test/t3", name="T3", tags=["js"])

        tags = workspace_manager.get_all_tags()
        assert "python" in tags
        assert "web" in tags
        assert "data" in tags
        assert "js" in tags
        assert len(tags) == 4

    def test_update_project_tags(self, workspace_manager):
        """测试更新项目标签"""
        workspace_manager.add_project(path="/test/upd", name="Upd", tags=["old"])
        result = workspace_manager.update_project_tags(
            path="/test/upd",
            tags=["new1", "new2"],
        )
        assert result["success"] is True

        project = workspace_manager.get_project_by_path("/test/upd")
        assert "new1" in project.tags
        assert "new2" in project.tags
        assert "old" not in project.tags


# ==================== 活动记录测试 ====================

class TestActivityRecord:
    """活动记录测试"""

    def test_record_activity(self, workspace_manager):
        """测试记录活动"""
        workspace_manager.add_project(path="/test/act", name="活动测试")
        result = workspace_manager.record_activity(
            project_path="/test/act",
            activity_type="coding",
            duration=30.5,
        )
        assert result["success"] is True

    def test_record_activity_nonexistent_project(self, workspace_manager):
        """测试记录不存在项目的活动（应自动创建）"""
        result = workspace_manager.record_activity(
            project_path="/test/newproj",
            activity_type="coding",
            duration=10,
        )
        assert result["success"] is True
        # 项目应该被自动创建
        project = workspace_manager.get_project_by_path("/test/newproj")
        assert project is not None

    def test_get_activities(self, workspace_manager):
        """测试获取活动列表"""
        workspace_manager.add_project(path="/test/act2", name="活动测试2")
        for i in range(3):
            workspace_manager.record_activity(
                project_path="/test/act2",
                activity_type="coding",
                duration=10,
            )
        activities = workspace_manager.get_activities(project="/test/act2")
        assert len(activities) == 3

    def test_get_recent_projects(self, workspace_manager):
        """测试获取最近项目"""
        for i in range(5):
            workspace_manager.add_project(path=f"/test/recent{i}", name=f"最近{i}")
            workspace_manager.record_activity(
                project_path=f"/test/recent{i}",
                activity_type="coding",
                duration=10,
            )
        recent = workspace_manager.get_recent_projects(limit=3)
        assert len(recent) == 3


# ==================== 统计测试 ====================

class TestStatistics:
    """统计功能测试"""

    def test_get_dashboard_stats(self, workspace_manager):
        """测试仪表盘统计"""
        workspace_manager.add_project(path="/test/stat1", name="统计1")
        workspace_manager.add_project(path="/test/stat2", name="统计2")
        workspace_manager.record_activity(
            project_path="/test/stat1",
            activity_type="coding",
            duration=60,
        )
        stats = workspace_manager.get_dashboard_stats()
        assert stats["success"] is True
        assert stats["total_projects"] >= 2
        assert stats["today_dev_time_minutes"] >= 60


# ==================== 直接运行入口 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("M9 工作区管理测试")
    print("=" * 60)

    # 使用 pytest 运行
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    sys.exit(exit_code)
