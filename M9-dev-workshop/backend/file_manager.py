"""M9 开发者工坊 - 文件管理器.

提供项目文件的管理功能：
- 文件树 API
- 文件读写 API
- 文件搜索
- 批量操作
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .core.path_safety import safe_join, assert_path_safe, PathSecurityError, sanitize_filename
except ImportError:
    from core.path_safety import safe_join, assert_path_safe, PathSecurityError, sanitize_filename

try:
    from .config import get_settings
except ImportError:
    from config import get_settings


class FileManager:
    """项目文件管理器."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._workspace_root = Path(self.settings.workspace_root)

    # ------------------------------------------------------------------
    # 文件树
    # ------------------------------------------------------------------

    def get_file_tree(
        self,
        project_path: str,
        max_depth: int = 5,
        show_hidden: bool = False,
    ) -> Dict[str, Any]:
        """获取项目文件树.

        Args:
            project_path: 项目路径
            max_depth: 最大深度
            show_hidden: 是否显示隐藏文件

        Returns:
            文件树结构
        """
        # 路径安全校验
        try:
            assert_path_safe(str(self._workspace_root), project_path, "get_file_tree")
        except PathSecurityError as e:
            return {
                "success": False,
                "error": f"路径不安全: {str(e)}",
            }

        if not os.path.isdir(project_path):
            return {
                "success": False,
                "error": f"路径不存在或不是目录: {project_path}",
            }

        tree = self._build_tree(
            project_path,
            project_path,
            max_depth=max_depth,
            show_hidden=show_hidden,
            current_depth=0,
        )

        return {
            "success": True,
            "project_path": project_path,
            "tree": tree,
            "max_depth": max_depth,
        }

    def _build_tree(
        self,
        root_path: str,
        current_path: str,
        max_depth: int,
        show_hidden: bool,
        current_depth: int,
    ) -> Dict[str, Any]:
        """递归构建文件树."""
        if current_depth >= max_depth:
            return {
                "name": os.path.basename(current_path),
                "path": os.path.relpath(current_path, root_path),
                "type": "directory",
                "truncated": True,
            }

        name = os.path.basename(current_path)
        rel_path = os.path.relpath(current_path, root_path)

        if os.path.isfile(current_path):
            stat = os.stat(current_path)
            return {
                "name": name,
                "path": rel_path if rel_path != "." else name,
                "type": "file",
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            }

        # 目录
        children = []
        try:
            entries = sorted(os.listdir(current_path))
        except PermissionError:
            return {
                "name": name,
                "path": rel_path if rel_path != "." else name,
                "type": "directory",
                "error": "permission_denied",
                "children": [],
            }

        for entry in entries:
            if not show_hidden and entry.startswith("."):
                continue

            full_path = os.path.join(current_path, entry)
            child_rel = os.path.relpath(full_path, root_path)

            if os.path.isdir(full_path):
                # 跳过一些大目录
                if entry in {"node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build"}:
                    children.append({
                        "name": entry,
                        "path": child_rel,
                        "type": "directory",
                        "skipped": True,
                        "children": [],
                    })
                    continue

                child_tree = self._build_tree(
                    root_path, full_path, max_depth, show_hidden, current_depth + 1
                )
                children.append(child_tree)
            else:
                stat = os.stat(full_path)
                children.append({
                    "name": entry,
                    "path": child_rel,
                    "type": "file",
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                })

        # 统计
        file_count = sum(1 for c in children if c.get("type") == "file")
        dir_count = sum(1 for c in children if c.get("type") == "directory")

        return {
            "name": name,
            "path": rel_path if rel_path != "." else name,
            "type": "directory",
            "children": children,
            "file_count": file_count,
            "directory_count": dir_count,
        }

    # ------------------------------------------------------------------
    # 文件读写
    # ------------------------------------------------------------------

    def read_file(
        self,
        project_path: str,
        file_path: str,
        max_size_kb: int = 1024,
    ) -> Dict[str, Any]:
        """读取文件内容.

        Args:
            project_path: 项目路径
            file_path: 文件相对路径
            max_size_kb: 最大读取大小（KB）

        Returns:
            文件内容
        """
        full_path = os.path.join(project_path, file_path)

        # 路径安全校验
        try:
            assert_path_safe(str(self._workspace_root), full_path, "read_file")
        except PathSecurityError as e:
            return {
                "success": False,
                "error": f"路径不安全: {str(e)}",
            }

        if not os.path.isfile(full_path):
            return {
                "success": False,
                "error": f"文件不存在: {file_path}",
            }

        # 检查文件大小
        file_size = os.path.getsize(full_path)
        max_size = max_size_kb * 1024
        if file_size > max_size:
            return {
                "success": False,
                "error": f"文件过大（{file_size} bytes），超过限制 {max_size} bytes",
                "file_size": file_size,
                "max_size": max_size,
            }

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            # 尝试其他编码
            try:
                with open(full_path, "r", encoding="gbk") as f:
                    content = f.read()
            except Exception:
                return {
                    "success": False,
                    "error": "无法解码文件（可能是二进制文件）",
                    "file_size": file_size,
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"读取文件失败: {str(e)}",
            }

        stat = os.stat(full_path)
        return {
            "success": True,
            "path": file_path,
            "content": content,
            "size": file_size,
            "modified_at": stat.st_mtime,
            "encoding": "utf-8",
        }

    def write_file(
        self,
        project_path: str,
        file_path: str,
        content: str,
        create_parents: bool = True,
    ) -> Dict[str, Any]:
        """写入文件内容.

        Args:
            project_path: 项目路径
            file_path: 文件相对路径
            content: 文件内容
            create_parents: 是否自动创建父目录

        Returns:
            写入结果
        """
        full_path = os.path.join(project_path, file_path)

        # 路径安全校验
        try:
            assert_path_safe(str(self._workspace_root), full_path, "write_file")
        except PathSecurityError as e:
            return {
                "success": False,
                "error": f"路径不安全: {str(e)}",
            }

        # 安全化文件名
        safe_name = sanitize_filename(os.path.basename(file_path))
        if safe_name != os.path.basename(file_path):
            return {
                "success": False,
                "error": f"文件名不安全: {os.path.basename(file_path)}",
            }

        try:
            if create_parents:
                os.makedirs(os.path.dirname(full_path), exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            stat = os.stat(full_path)
            return {
                "success": True,
                "path": file_path,
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
                "created": not os.path.exists(full_path) or stat.st_size == len(content.encode("utf-8")),
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"写入文件失败: {str(e)}",
            }

    # ------------------------------------------------------------------
    # 文件搜索
    # ------------------------------------------------------------------

    def search_files(
        self,
        project_path: str,
        query: str,
        search_content: bool = False,
        file_pattern: Optional[str] = None,
        max_results: int = 50,
    ) -> Dict[str, Any]:
        """搜索文件.

        Args:
            project_path: 项目路径
            query: 搜索关键词
            search_content: 是否搜索文件内容
            file_pattern: 文件模式过滤（如 *.py）
            max_results: 最大结果数

        Returns:
            搜索结果
        """
        # 路径安全校验
        try:
            assert_path_safe(str(self._workspace_root), project_path, "search_files")
        except PathSecurityError as e:
            return {
                "success": False,
                "error": f"路径不安全: {str(e)}",
            }

        if not os.path.isdir(project_path):
            return {
                "success": False,
                "error": f"路径不存在: {project_path}",
            }

        results = []
        query_lower = query.lower()
        skip_dirs = {"node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build"}

        for root, dirs, files in os.walk(project_path):
            # 跳过忽略目录
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

            for filename in files:
                if len(results) >= max_results:
                    break

                # 文件模式过滤
                if file_pattern:
                    import fnmatch
                    if not fnmatch.fnmatch(filename, file_pattern):
                        continue

                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, project_path)

                # 文件名匹配
                name_match = query_lower in filename.lower()

                # 内容匹配
                content_match = False
                content_preview = ""
                if search_content and not name_match:
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            file_content = f.read()
                            if query_lower in file_content.lower():
                                content_match = True
                                # 找到匹配位置，提取前后上下文
                                idx = file_content.lower().find(query_lower)
                                start = max(0, idx - 50)
                                end = min(len(file_content), idx + len(query) + 50)
                                content_preview = file_content[start:end].strip()
                    except (OSError, UnicodeDecodeError):
                        pass

                if name_match or content_match:
                    stat = os.stat(file_path)
                    results.append({
                        "path": rel_path,
                        "name": filename,
                        "type": "file",
                        "size": stat.st_size,
                        "modified_at": stat.st_mtime,
                        "match_type": "name" if name_match else "content",
                        "content_preview": content_preview,
                    })

            if len(results) >= max_results:
                break

        return {
            "success": True,
            "query": query,
            "results": results,
            "total": len(results),
            "max_results": max_results,
            "search_content": search_content,
        }

    # ------------------------------------------------------------------
    # 批量操作
    # ------------------------------------------------------------------

    def batch_operation(
        self,
        project_path: str,
        operation: str,
        files: List[str],
        **kwargs,
    ) -> Dict[str, Any]:
        """批量文件操作.

        Args:
            project_path: 项目路径
            operation: 操作类型（delete/copy/move/rename）
            files: 文件路径列表
            **kwargs: 操作参数

        Returns:
            操作结果
        """
        # 路径安全校验
        try:
            assert_path_safe(str(self._workspace_root), project_path, "batch_operation")
        except PathSecurityError as e:
            return {
                "success": False,
                "error": f"路径不安全: {str(e)}",
            }

        results = []
        success_count = 0
        failed_count = 0

        for file_path in files:
            full_path = os.path.join(project_path, file_path)

            # 路径安全校验
            try:
                assert_path_safe(str(self._workspace_root), full_path, "batch_operation_file")
            except PathSecurityError:
                results.append({
                    "path": file_path,
                    "success": False,
                    "error": "路径不安全",
                })
                failed_count += 1
                continue

            try:
                if operation == "delete":
                    if os.path.isfile(full_path):
                        os.remove(full_path)
                    elif os.path.isdir(full_path):
                        shutil.rmtree(full_path)
                    else:
                        raise FileNotFoundError(f"文件不存在: {file_path}")

                elif operation == "copy":
                    dest = kwargs.get("destination", "")
                    dest_path = os.path.join(project_path, dest)
                    assert_path_safe(str(self._workspace_root), dest_path, "batch_copy_dest")
                    if os.path.isdir(full_path):
                        shutil.copytree(full_path, dest_path)
                    else:
                        shutil.copy2(full_path, dest_path)

                elif operation == "move":
                    dest = kwargs.get("destination", "")
                    dest_path = os.path.join(project_path, dest)
                    assert_path_safe(str(self._workspace_root), dest_path, "batch_move_dest")
                    shutil.move(full_path, dest_path)

                else:
                    results.append({
                        "path": file_path,
                        "success": False,
                        "error": f"不支持的操作: {operation}",
                    })
                    failed_count += 1
                    continue

                results.append({
                    "path": file_path,
                    "success": True,
                })
                success_count += 1

            except Exception as e:
                results.append({
                    "path": file_path,
                    "success": False,
                    "error": str(e),
                })
                failed_count += 1

        return {
            "success": True,
            "operation": operation,
            "total": len(files),
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results,
        }

    # ------------------------------------------------------------------
    # 文件信息
    # ------------------------------------------------------------------

    def get_file_info(
        self,
        project_path: str,
        file_path: str,
    ) -> Dict[str, Any]:
        """获取文件信息.

        Args:
            project_path: 项目路径
            file_path: 文件相对路径

        Returns:
            文件信息
        """
        full_path = os.path.join(project_path, file_path)

        try:
            assert_path_safe(str(self._workspace_root), full_path, "get_file_info")
        except PathSecurityError as e:
            return {
                "success": False,
                "error": f"路径不安全: {str(e)}",
            }

        if not os.path.exists(full_path):
            return {
                "success": False,
                "error": f"路径不存在: {file_path}",
            }

        stat = os.stat(full_path)
        is_dir = os.path.isdir(full_path)

        return {
            "success": True,
            "path": file_path,
            "name": os.path.basename(file_path),
            "type": "directory" if is_dir else "file",
            "size": stat.st_size if not is_dir else None,
            "created_at": stat.st_ctime,
            "modified_at": stat.st_mtime,
            "accessed_at": stat.st_atime,
            "extension": os.path.splitext(file_path)[1] if not is_dir else None,
        }

    def create_directory(
        self,
        project_path: str,
        dir_path: str,
    ) -> Dict[str, Any]:
        """创建目录.

        Args:
            project_path: 项目路径
            dir_path: 目录相对路径

        Returns:
            创建结果
        """
        full_path = os.path.join(project_path, dir_path)

        try:
            assert_path_safe(str(self._workspace_root), full_path, "create_directory")
        except PathSecurityError as e:
            return {
                "success": False,
                "error": f"路径不安全: {str(e)}",
            }

        try:
            os.makedirs(full_path, exist_ok=True)
            return {
                "success": True,
                "path": dir_path,
                "created": not os.path.exists(full_path),
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"创建目录失败: {str(e)}",
            }


# 全局单例
_file_manager: Optional[FileManager] = None


def get_file_manager() -> FileManager:
    """获取文件管理器单例."""
    global _file_manager
    if _file_manager is None:
        _file_manager = FileManager()
    return _file_manager
