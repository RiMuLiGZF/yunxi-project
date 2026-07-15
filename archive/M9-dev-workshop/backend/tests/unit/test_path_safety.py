"""路径安全工具单元测试 (>=30 用例)"""
import sys
import os
import tempfile
from pathlib import Path

# 确保可以导入 backend 模块
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest
from core.path_safety import (
    safe_join,
    is_path_safe,
    sanitize_filename,
    assert_path_safe,
    PathSecurityError,
)


class TestSafeJoin:
    """safe_join 函数测试"""

    def test_normal_path_join(self, tmp_path):
        """正常路径拼接"""
        result = safe_join(str(tmp_path), "subdir", "file.txt")
        assert result is not None
        assert result.endswith(os.path.join("subdir", "file.txt"))

    def test_single_segment(self, tmp_path):
        """单级路径拼接"""
        result = safe_join(str(tmp_path), "file.txt")
        assert result is not None
        assert os.path.basename(result) == "file.txt"

    def test_root_dir_self(self, tmp_path):
        """根目录自身（空路径段时返回根目录本身）"""
        result = safe_join(str(tmp_path))
        assert result is not None
        assert result == os.path.realpath(str(tmp_path))

    def test_path_traversal_dotdot(self, tmp_path):
        """路径遍历攻击 - .. 返回 None"""
        result = safe_join(str(tmp_path), "..", "etc", "passwd")
        assert result is None

    def test_deep_path_traversal(self, tmp_path):
        """深层路径遍历"""
        result = safe_join(str(tmp_path), "a", "..", "..", "..", "etc")
        assert result is None

    def test_empty_paths(self, tmp_path):
        """空路径段"""
        result = safe_join(str(tmp_path))
        assert result is not None
        assert result == os.path.realpath(str(tmp_path))

    def test_hidden_directory(self, tmp_path):
        """隐藏目录"""
        result = safe_join(str(tmp_path), ".hidden", "file.txt")
        assert result is not None
        assert ".hidden" in result

    def test_unicode_filename(self, tmp_path):
        """Unicode 文件名"""
        result = safe_join(str(tmp_path), "中文文件.txt")
        assert result is not None
        assert "中文文件.txt" in result

    def test_spaces_in_path(self, tmp_path):
        """路径含空格"""
        result = safe_join(str(tmp_path), "my folder", "my file.txt")
        assert result is not None

    def test_dot_segments_only(self, tmp_path):
        """仅点段"""
        result = safe_join(str(tmp_path), ".", "file.txt")
        assert result is not None

    def test_relative_subdirectory(self, tmp_path):
        """相对子目录"""
        subdir = os.path.join(str(tmp_path), "a", "b", "c")
        os.makedirs(subdir, exist_ok=True)
        result = safe_join(str(tmp_path), "a", "b", "c", "file.txt")
        assert result is not None

    def test_traversal_beyond_root(self, tmp_path):
        """遍历超过根目录"""
        result = safe_join(str(tmp_path), "subdir", "..", "..", "..", "tmp")
        assert result is None

    def test_mixed_normal_and_traversal(self, tmp_path):
        """正常路径和遍历混合 - a/.. 归约后仍安全"""
        result = safe_join(str(tmp_path), "a", "..", "b")
        assert result is not None
        assert result.endswith(os.path.join("b"))

    def test_trailing_separator(self, tmp_path):
        """尾部有分隔符"""
        result = safe_join(str(tmp_path), "subdir", "")
        assert result is not None

    def test_path_with_forward_slash(self, tmp_path):
        """路径含正斜杠"""
        result = safe_join(str(tmp_path), "subdir/file.txt")
        assert result is not None


class TestIsPathSafe:
    """is_path_safe 函数测试"""

    def test_safe_path(self, tmp_path):
        """安全路径返回 True"""
        target = os.path.join(str(tmp_path), "file.txt")
        assert is_path_safe(str(tmp_path), target) is True

    def test_path_equals_root(self, tmp_path):
        """路径等于根目录"""
        assert is_path_safe(str(tmp_path), str(tmp_path)) is True

    def test_traversal_path(self, tmp_path):
        """遍历路径返回 False"""
        target = os.path.join(str(tmp_path), "..", "etc")
        assert is_path_safe(str(tmp_path), target) is False

    def test_sibling_directory(self, tmp_path):
        """兄弟目录返回 False"""
        parent = os.path.dirname(str(tmp_path))
        target = os.path.join(parent, "sibling")
        assert is_path_safe(str(tmp_path), target) is False

    def test_nested_safe_path(self, tmp_path):
        """深层嵌套安全路径"""
        target = os.path.join(str(tmp_path), "a", "b", "c", "d")
        assert is_path_safe(str(tmp_path), target) is True

    def test_case_sensitivity(self, tmp_path):
        """大小写检查"""
        target = os.path.join(str(tmp_path), "FILE.TXT")
        result = is_path_safe(str(tmp_path), target)
        assert isinstance(result, bool)

    def test_empty_root(self):
        """根目录为当前工作目录"""
        target = os.path.join(os.getcwd(), "somefile")
        assert is_path_safe(os.getcwd(), target) is True

    def test_symlink_target_outside(self, tmp_path):
        """符号链接指向外部"""
        link_path = os.path.join(str(tmp_path), "link_outside")
        outside_dir = os.path.join(str(tmp_path), "..")
        try:
            os.symlink(outside_dir, link_path)
            assert is_path_safe(str(tmp_path), link_path) is False
        except (OSError, NotImplementedError):
            pass


class TestSanitizeFilename:
    """sanitize_filename 函数测试"""

    def test_normal_filename(self):
        """正常文件名"""
        assert sanitize_filename("document.txt") == "document.txt"

    def test_slash_replacement(self):
        """斜杠替换为下划线"""
        assert sanitize_filename("path/to/file.txt") == "path_to_file.txt"

    def test_backslash_replacement(self):
        """反斜杠替换为下划线"""
        assert sanitize_filename("path\\to\\file.txt") == "path_to_file.txt"

    def test_mixed_separators(self):
        """混合路径分隔符"""
        result = sanitize_filename("a/b\\c/d.txt")
        assert "/" not in result
        assert "\\" not in result

    def test_empty_filename(self):
        """空文件名返回 unnamed"""
        assert sanitize_filename("") == "unnamed"

    def test_only_dots(self):
        """仅有点的文件名"""
        assert sanitize_filename("...") == "unnamed"

    def test_hidden_file(self):
        """隐藏文件（以 . 开头）"""
        result = sanitize_filename(".gitignore")
        assert not result.startswith(".")

    def test_long_filename(self):
        """超长文件名截断"""
        long_name = "a" * 300 + ".txt"
        result = sanitize_filename(long_name)
        assert len(result) <= 255

    def test_long_extension(self):
        """长文件名保留扩展名"""
        name = "a" * 300 + ".txt"
        result = sanitize_filename(name)
        assert result.endswith(".txt")

    def test_special_characters(self):
        """特殊字符保留"""
        result = sanitize_filename("file@#$%.txt")
        assert "/" not in result
        assert "\\" not in result

    def test_null_byte_handling(self):
        """空字节不崩溃"""
        result = sanitize_filename("file\x00name.txt")
        assert isinstance(result, str)


class TestAssertPathSafe:
    """assert_path_safe 函数测试"""

    def test_safe_path_no_exception(self, tmp_path):
        """安全路径不抛异常"""
        target = os.path.join(str(tmp_path), "file.txt")
        assert_path_safe(str(tmp_path), target)

    def test_unsafe_path_raises(self, tmp_path):
        """越界路径抛出 PathSecurityError"""
        target = os.path.join(str(tmp_path), "..", "etc")
        with pytest.raises(PathSecurityError):
            assert_path_safe(str(tmp_path), target, "test_operation")

    def test_error_message_contains_operation(self, tmp_path):
        """错误消息包含操作名称"""
        target = os.path.join(str(tmp_path), "..")
        with pytest.raises(PathSecurityError) as exc_info:
            assert_path_safe(str(tmp_path), target, "delete_project")
        assert "delete_project" in str(exc_info.value)

    def test_root_path_no_exception(self, tmp_path):
        """根目录自身不抛异常"""
        assert_path_safe(str(tmp_path), str(tmp_path))

    def test_deep_traversal_raises(self, tmp_path):
        """深层遍历抛异常"""
        target = os.path.join(str(tmp_path), "a", "b", "..", "..", "..", "..", "etc")
        with pytest.raises(PathSecurityError):
            assert_path_safe(str(tmp_path), target)


class TestBypassAttempts:
    """各种绕过手法测试"""

    def test_double_dotdot(self, tmp_path):
        """双重 .. 拼接"""
        result = safe_join(str(tmp_path), "..", "..", "etc")
        assert result is None

    def test_dotdot_in_middle(self, tmp_path):
        """中间的 .."""
        result = safe_join(str(tmp_path), "a", "..", "..", "b")
        assert result is None

    def test_encoded_slash(self, tmp_path):
        """编码斜杠不被解释为路径分隔符"""
        result = safe_join(str(tmp_path), "dir%2F..%2Fetc")
        assert result is not None
        realpath = os.path.realpath(result)
        assert realpath.startswith(os.path.realpath(str(tmp_path)))

    def test_mixed_slash_types(self, tmp_path):
        """混合正斜杠和反斜杠 - a/../b 归约后为 b，再 .. 回到 root，etc 在 root 内"""
        result = safe_join(str(tmp_path), "a/../b", "..", "etc")
        # a/.. 归约 -> root, b -> root/b, .. -> root, etc -> root/etc (安全)
        assert result is not None
        assert os.path.realpath(result).startswith(os.path.realpath(str(tmp_path)))

    def test_dotdot_with_slash_variants(self, tmp_path):
        """不同分隔符的 .."""
        result = safe_join(str(tmp_path), "..\\..\\etc")
        assert result is None

    def test_current_directory_dot(self, tmp_path):
        """当前目录 . 不影响安全性"""
        result = safe_join(str(tmp_path), ".", ".", "file.txt")
        assert result is not None

    def test_dotdot_at_start(self, tmp_path):
        """开头的 .."""
        result = safe_join(str(tmp_path), "..")
        assert result is None
