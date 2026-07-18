"""
M9 单元测试 - 文件管理器测试

覆盖: 文件树、文件读写、文件搜索、批量操作
运行: python -m pytest tests/unit/test_file_manager.py -v
"""
import os
import sys
import pytest
import tempfile
import shutil
from file_manager import FileManager


@pytest.fixture
def temp_workspace():
    """临时工作区 fixture"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def file_manager(temp_workspace):
    """文件管理器 fixture"""
    import config
    original_root = config.get_settings().workspace_root
    config.get_settings().workspace_root = temp_workspace

    fm = FileManager()
    yield fm

    config.get_settings().workspace_root = original_root


@pytest.fixture
def sample_project(temp_workspace):
    """示例项目目录"""
    project_path = os.path.join(temp_workspace, "test_project")
    os.makedirs(project_path)

    # 创建一些文件
    files = {
        "main.py": "print('hello world')\n",
        "utils.py": "def add(a, b):\n    return a + b\n",
        "README.md": "# Test Project\nThis is a test.\n",
        "config.json": '{"name": "test", "version": "1.0"}\n',
    }

    # 创建子目录
    os.makedirs(os.path.join(project_path, "src"))
    os.makedirs(os.path.join(project_path, "tests"))

    for path, content in files.items():
        with open(os.path.join(project_path, path), "w", encoding="utf-8") as f:
            f.write(content)

    # 子目录中的文件
    with open(os.path.join(project_path, "src", "module.py"), "w", encoding="utf-8") as f:
        f.write("class Module:\n    pass\n")

    with open(os.path.join(project_path, "tests", "test_main.py"), "w", encoding="utf-8") as f:
        f.write("def test_example():\n    assert True\n")

    return project_path


class TestFileManager:
    """文件管理器测试"""

    def test_init(self, file_manager):
        """初始化测试"""
        assert file_manager is not None

    def test_get_file_tree(self, file_manager, sample_project):
        """获取文件树"""
        result = file_manager.get_file_tree(sample_project)
        assert result["success"] is True
        assert result["project_path"] == sample_project
        tree = result["tree"]
        assert tree["type"] == "directory"
        assert len(tree["children"]) > 0

    def test_get_file_tree_max_depth(self, file_manager, sample_project):
        """文件树深度限制"""
        result = file_manager.get_file_tree(sample_project, max_depth=1)
        assert result["success"] is True
        # 深度为 1 时应该只显示根目录下的直接子项
        tree = result["tree"]
        for child in tree["children"]:
            if child["type"] == "directory":
                assert child.get("truncated", False) or len(child.get("children", [])) == 0

    def test_get_file_tree_hidden(self, file_manager, sample_project):
        """隐藏文件显示"""
        # 创建一个隐藏文件
        hidden_file = os.path.join(sample_project, ".hidden")
        with open(hidden_file, "w") as f:
            f.write("hidden")

        # 不显示隐藏文件
        result = file_manager.get_file_tree(sample_project, show_hidden=False)
        tree = result["tree"]
        has_hidden = any(c["name"].startswith(".") for c in tree["children"])
        assert not has_hidden

        # 显示隐藏文件
        result2 = file_manager.get_file_tree(sample_project, show_hidden=True)
        tree2 = result2["tree"]
        has_hidden2 = any(c["name"].startswith(".") for c in tree2["children"])
        assert has_hidden2

    def test_read_file(self, file_manager, sample_project):
        """读取文件"""
        result = file_manager.read_file(sample_project, "main.py")
        assert result["success"] is True
        assert "hello world" in result["content"]
        assert result["path"] == "main.py"

    def test_read_file_not_found(self, file_manager, sample_project):
        """读取不存在的文件"""
        result = file_manager.read_file(sample_project, "nonexistent.py")
        assert result["success"] is False
        assert "不存在" in result.get("error", "")

    def test_read_file_subdirectory(self, file_manager, sample_project):
        """读取子目录中的文件"""
        result = file_manager.read_file(sample_project, "src/module.py")
        assert result["success"] is True
        assert "Module" in result["content"]

    def test_write_file(self, file_manager, sample_project):
        """写入文件"""
        result = file_manager.write_file(
            sample_project,
            "new_file.py",
            "print('new file')\n",
        )
        assert result["success"] is True
        assert result["path"] == "new_file.py"

        # 验证文件内容
        full_path = os.path.join(sample_project, "new_file.py")
        with open(full_path, "r", encoding="utf-8") as f:
            assert "new file" in f.read()

    def test_write_file_create_parents(self, file_manager, sample_project):
        """写入文件时自动创建父目录"""
        result = file_manager.write_file(
            sample_project,
            "deep/nested/file.py",
            "print('nested')\n",
            create_parents=True,
        )
        assert result["success"] is True
        assert os.path.exists(os.path.join(sample_project, "deep", "nested", "file.py"))

    def test_write_file_overwrite(self, file_manager, sample_project):
        """覆盖写入文件"""
        result = file_manager.write_file(sample_project, "main.py", "new content")
        assert result["success"] is True

        # 验证内容已更新
        read_result = file_manager.read_file(sample_project, "main.py")
        assert read_result["content"] == "new content"

    def test_search_files_by_name(self, file_manager, sample_project):
        """按文件名搜索"""
        result = file_manager.search_files(sample_project, query="main")
        assert result["success"] is True
        assert result["total"] > 0
        for item in result["results"]:
            assert "main" in item["name"].lower()

    def test_search_files_by_content(self, file_manager, sample_project):
        """按内容搜索"""
        result = file_manager.search_files(sample_project, query="hello", search_content=True)
        assert result["success"] is True
        assert result["total"] > 0

    def test_search_files_pattern(self, file_manager, sample_project):
        """按文件模式过滤搜索"""
        result = file_manager.search_files(sample_project, query="test", file_pattern="*.py")
        assert result["success"] is True
        for item in result["results"]:
            assert item["name"].endswith(".py")

    def test_search_files_max_results(self, file_manager, sample_project):
        """搜索结果数量限制"""
        result = file_manager.search_files(sample_project, query=".", max_results=2)
        assert result["success"] is True
        assert len(result["results"]) <= 2

    def test_batch_delete(self, file_manager, sample_project):
        """批量删除文件"""
        # 创建一些临时文件
        file_manager.write_file(sample_project, "del1.py", "delete me")
        file_manager.write_file(sample_project, "del2.py", "delete me too")

        result = file_manager.batch_operation(
            sample_project,
            operation="delete",
            files=["del1.py", "del2.py"],
        )

        assert result["success"] is True
        assert result["success_count"] == 2
        assert result["failed_count"] == 0

        # 验证文件已删除
        assert not os.path.exists(os.path.join(sample_project, "del1.py"))
        assert not os.path.exists(os.path.join(sample_project, "del2.py"))

    def test_batch_delete_mixed(self, file_manager, sample_project):
        """批量删除 - 部分成功部分失败"""
        file_manager.write_file(sample_project, "exists.py", "exists")

        result = file_manager.batch_operation(
            sample_project,
            operation="delete",
            files=["exists.py", "nonexistent.py"],
        )

        assert result["success"] is True
        assert result["success_count"] == 1
        assert result["failed_count"] == 1

    def test_get_file_info(self, file_manager, sample_project):
        """获取文件信息"""
        result = file_manager.get_file_info(sample_project, "main.py")
        assert result["success"] is True
        assert result["name"] == "main.py"
        assert result["type"] == "file"
        assert result["size"] > 0
        assert "modified_at" in result

    def test_get_file_info_directory(self, file_manager, sample_project):
        """获取目录信息"""
        result = file_manager.get_file_info(sample_project, "src")
        assert result["success"] is True
        assert result["type"] == "directory"

    def test_get_file_info_not_found(self, file_manager, sample_project):
        """获取不存在的文件信息"""
        result = file_manager.get_file_info(sample_project, "nonexistent")
        assert result["success"] is False

    def test_create_directory(self, file_manager, sample_project):
        """创建目录"""
        result = file_manager.create_directory(sample_project, "new_dir")
        assert result["success"] is True
        assert os.path.isdir(os.path.join(sample_project, "new_dir"))

    def test_create_nested_directory(self, file_manager, sample_project):
        """创建嵌套目录"""
        result = file_manager.create_directory(sample_project, "a/b/c")
        assert result["success"] is True
        assert os.path.isdir(os.path.join(sample_project, "a", "b", "c"))

    def test_create_directory_exists(self, file_manager, sample_project):
        """创建已存在的目录"""
        result = file_manager.create_directory(sample_project, "src")
        assert result["success"] is True  # 已存在也算成功


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
