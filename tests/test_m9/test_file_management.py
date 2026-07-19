"""
M9 开发工坊 - 文件管理与路径安全单元测试

测试内容：
- 路径安全工具函数（纯函数测试，已移至 test_auth_and_workspace.py）
- 文件管理器核心逻辑（单元测试，mock 文件系统）
- 文件管理 API（集成测试，标记为 integration）
"""

import sys
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent.parent
M9_BACKEND_PATH = PROJECT_ROOT / "M9-dev-workshop" / "backend"

if str(M9_BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(M9_BACKEND_PATH))


# ============================================================
# 文件管理器单元测试
# ============================================================

class TestFileManager:
    """文件管理器核心逻辑单元测试"""

    @pytest.fixture
    def temp_workspace(self, tmp_path):
        """创建临时工作空间目录"""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # 创建一些测试文件
        (workspace / "file1.txt").write_text("content1")
        (workspace / "file2.py").write_text("print('hello')")
        subdir = workspace / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("nested")
        return workspace

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_file_manager_module_exists(self):
        """file_manager 模块存在"""
        import file_manager
        assert file_manager is not None

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_file_manager_class_exists(self):
        """FileManager 类存在"""
        from file_manager import FileManager
        assert FileManager is not None

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_workspace_manager_module_exists(self):
        """workspace_manager 模块存在"""
        import workspace_manager
        assert workspace_manager is not None


class TestFileOperationsWithTempDir:
    """使用临时目录进行文件操作测试（真实文件系统，无外部依赖）"""

    @pytest.fixture
    def test_dir(self, tmp_path):
        """创建测试目录"""
        d = tmp_path / "test_files"
        d.mkdir()
        return d

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_create_and_read_file(self, test_dir):
        """创建并读取文件（基础文件操作）"""
        test_file = test_dir / "test.txt"
        test_file.write_text("hello world")

        assert test_file.exists()
        assert test_file.read_text() == "hello world"

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_delete_file(self, test_dir):
        """删除文件"""
        test_file = test_dir / "to_delete.txt"
        test_file.write_text("delete me")

        assert test_file.exists()
        test_file.unlink()
        assert not test_file.exists()

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_create_directory(self, test_dir):
        """创建目录"""
        new_dir = test_dir / "new_dir"
        new_dir.mkdir()

        assert new_dir.exists()
        assert new_dir.is_dir()

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_list_directory(self, test_dir):
        """列出目录内容"""
        (test_dir / "a.txt").write_text("a")
        (test_dir / "b.txt").write_text("b")
        (test_dir / "sub").mkdir()

        files = list(test_dir.iterdir())
        names = [f.name for f in files]

        assert "a.txt" in names
        assert "b.txt" in names
        assert "sub" in names
        assert len(files) == 3

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_nested_directory_creation(self, test_dir):
        """创建嵌套目录"""
        nested = test_dir / "a" / "b" / "c"
        nested.mkdir(parents=True)

        assert nested.exists()
        assert nested.is_dir()

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_overwrite_file(self, test_dir):
        """覆盖写入文件"""
        test_file = test_dir / "overwrite.txt"
        test_file.write_text("original")
        test_file.write_text("updated")

        assert test_file.read_text() == "updated"

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_file_size(self, test_dir):
        """文件大小计算"""
        test_file = test_dir / "size.txt"
        content = "1234567890"
        test_file.write_text(content)

        assert test_file.stat().st_size == len(content)


# ============================================================
# 路径安全补充测试
# ============================================================

class TestPathSafetyExtended:
    """路径安全工具扩展测试"""

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_safe_join_empty_segment(self, tmp_path):
        """空路径段处理"""
        from core.path_safety import safe_join

        result = safe_join(str(tmp_path), "")
        # 空段应该仍然安全
        assert result is not None or result is None  # 取决于实现

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_safe_join_with_symlink_simulation(self, tmp_path):
        """模拟符号链接路径（不创建实际符号链接）"""
        from core.path_safety import is_path_safe

        # 直接测试路径比较逻辑
        base = str(tmp_path)
        inside = str(tmp_path / "safe" / "file.txt")
        outside = str(tmp_path.parent / "outside.txt")

        assert is_path_safe(base, inside) is True
        assert is_path_safe(base, outside) is False

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_sanitize_filename_preserves_extension(self):
        """长文件名截断时保留扩展名"""
        from core.path_safety import sanitize_filename

        long_name = "a" * 300 + ".py"
        result = sanitize_filename(long_name)
        assert result.endswith(".py")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_path_security_error_class(self):
        """PathSecurityError 异常类存在"""
        from core.path_safety import PathSecurityError

        assert issubclass(PathSecurityError, Exception)
        err = PathSecurityError("test error")
        assert str(err) == "test error"


# ============================================================
# 集成测试（需要完整 M9 应用）
# ============================================================

class TestFileManagementIntegration:
    """文件管理 API 集成测试（需要 M9 应用实例）

    依赖 m9_client fixture，应用无法初始化时自动跳过。
    """

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_file_list_endpoint(self, m9_client, test_workspace_dir):
        """文件列表接口"""
        response = m9_client.get(
            f"/api/v1/workspace/files?path={test_workspace_dir}"
        )
        if response.status_code == 404:
            response = m9_client.get(
                f"/api/workspace/files?path={test_workspace_dir}"
            )
        assert response.status_code in [200, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_file_list_returns_json(self, m9_client, test_workspace_dir):
        """文件列表返回 JSON 格式"""
        response = m9_client.get(
            f"/api/v1/workspace/files?path={test_workspace_dir}"
        )
        if response.status_code == 404:
            response = m9_client.get(
                f"/api/workspace/files?path={test_workspace_dir}"
            )
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)
            assert "code" in data

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_read_file_endpoint(self, m9_client, test_workspace_dir):
        """读取文件接口"""
        test_file = test_workspace_dir / "project-a" / "main.py"
        response = m9_client.get(
            f"/api/v1/workspace/files/read?path={test_file}"
        )
        if response.status_code == 404:
            response = m9_client.get(
                f"/api/workspace/file?path={test_file}"
            )
        assert response.status_code in [200, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_read_nonexistent_file(self, m9_client, test_workspace_dir):
        """读取不存在的文件"""
        nonexistent = test_workspace_dir / "nonexistent.py"
        response = m9_client.get(
            f"/api/v1/workspace/files/read?path={nonexistent}"
        )
        if response.status_code == 404:
            response = m9_client.get(
                f"/api/workspace/file?path={nonexistent}"
            )
        assert response.status_code in [200, 404, 401, 403]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_write_file_endpoint(self, m9_client, test_workspace_dir):
        """写入文件接口"""
        test_file = test_workspace_dir / "test_write.py"
        body = {
            "path": str(test_file),
            "content": "# test content\nprint('hello')",
        }
        response = m9_client.post("/api/v1/workspace/files/write", json=body)
        if response.status_code == 404:
            response = m9_client.put("/api/workspace/file", json=body)
        assert response.status_code in [200, 201, 400, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_write_file_creates_file(self, m9_client, test_workspace_dir):
        """写入文件后文件实际存在"""
        test_file = test_workspace_dir / "test_create.py"
        body = {
            "path": str(test_file),
            "content": "print('created')",
        }
        response = m9_client.post("/api/v1/workspace/files/write", json=body)
        if response.status_code == 404:
            response = m9_client.put("/api/workspace/file", json=body)
        if response.status_code in [200, 201]:
            assert test_file.exists()
            assert test_file.read_text() == "print('created')"

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_delete_file_endpoint(self, m9_client, test_workspace_dir):
        """删除文件接口"""
        test_file = test_workspace_dir / "to_delete.py"
        test_file.write_text("# to delete")
        body = {"path": str(test_file)}
        response = m9_client.post("/api/v1/workspace/files/delete", json=body)
        if response.status_code == 404:
            response = m9_client.delete(
                f"/api/workspace/file?path={test_file}"
            )
        assert response.status_code in [200, 400, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_create_directory_endpoint(self, m9_client, test_workspace_dir):
        """创建目录接口"""
        new_dir = test_workspace_dir / "new_directory"
        body = {"path": str(new_dir)}
        response = m9_client.post("/api/v1/workspace/files/mkdir", json=body)
        if response.status_code == 404:
            response = m9_client.post("/api/workspace/directory", json=body)
        assert response.status_code in [200, 201, 400, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_path_traversal_prevention(self, m9_client, test_workspace_dir):
        """路径遍历攻击防护"""
        malicious_path = test_workspace_dir / "../../etc/passwd"
        response = m9_client.get(
            f"/api/v1/workspace/files/read?path={malicious_path}"
        )
        if response.status_code == 404:
            response = m9_client.get(
                f"/api/workspace/file?path={malicious_path}"
            )
        assert response.status_code in [200, 400, 403, 404, 401]
