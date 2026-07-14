"""M9 项目管理器单元测试"""

import pytest
import os
import json
import tempfile
from unittest.mock import patch
from m9_programming_dev.project_manager import ProjectManager
from m9_programming_dev.models import ProjectInfo


class TestProjectManager:
    """项目管理器测试"""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="m9_test_")
        with patch("m9_programming_dev.project_manager.settings") as mock_settings:
            mock_settings.projects_root_dir = self.tmp_dir
            self.manager = ProjectManager()

    def test_list_empty(self):
        """测试空项目列表"""
        projects = self.manager.list_projects()
        assert isinstance(projects, list)
        assert len(projects) == 0

    def test_create_project(self):
        """测试创建项目"""
        project = self.manager.create_project("Test Project", "A test project", "python")
        assert project.name == "Test Project"
        assert project.description == "A test project"
        assert project.language == "python"
        assert project.id
        assert os.path.isdir(os.path.join(self.tmp_dir, project.id))

    def test_get_project(self):
        """测试获取项目"""
        created = self.manager.create_project("Get Test")
        fetched = self.manager.get_project(created.id)
        assert fetched is not None
        assert fetched.name == "Get Test"
        assert fetched.id == created.id

    def test_get_nonexistent_project(self):
        """测试获取不存在的项目"""
        project = self.manager.get_project("nonexistent")
        assert project is None

    def test_delete_project(self):
        """测试删除项目"""
        created = self.manager.create_project("Delete Test")
        result = self.manager.delete_project(created.id)
        assert result is True
        assert self.manager.get_project(created.id) is None
        assert not os.path.exists(os.path.join(self.tmp_dir, created.id))

    def test_delete_nonexistent_project(self):
        """测试删除不存在的项目"""
        result = self.manager.delete_project("nonexistent")
        assert result is False

    def test_project_meta_persistence(self):
        """测试项目元数据持久化"""
        created = self.manager.create_project("Persistent")
        meta_path = os.path.join(self.tmp_dir, created.id, ".project.json")
        assert os.path.exists(meta_path)
        with open(meta_path, 'r') as f:
            data = json.load(f)
        assert data["name"] == "Persistent"

    def test_get_project_files(self):
        """测试获取项目文件列表"""
        project = self.manager.create_project("Files Test")
        # 创建一个测试文件
        test_file = os.path.join(self.tmp_dir, project.id, "main.py")
        with open(test_file, 'w') as f:
            f.write("print('hello')")
        files = self.manager.get_project_files(project.id)
        assert len(files) >= 1
        assert any(f["name"] == "main.py" for f in files)

    def test_get_project_files_nonexistent(self):
        """测试获取不存在项目的文件列表"""
        files = self.manager.get_project_files("nonexistent")
        assert files == []

    def teardown_method(self):
        import shutil
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)
