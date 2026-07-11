"""文件操作技能.

提供文件读取、写入、目录列出、创建目录、删除文件/目录、文件存在检查等功能。
包含路径安全限制，防止越权访问工作目录以外的文件。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

try:
    from src.services.skills.base import BaseSkill
except ImportError:
    from services.skills.base import BaseSkill  # type: ignore


class FileOperationSkill(BaseSkill):
    """文件操作技能.

    支持的操作（通过 action 参数区分）:
        - read_file: 读取文件内容
        - write_file: 写入文件
        - list_dir: 列出目录内容
        - create_dir: 创建目录
        - delete_file: 删除文件或目录
        - file_exists: 检查文件是否存在

    安全特性:
        - 所有路径会被规范化，禁止通过 ../ 跳出工作目录
        - 默认工作目录可通过 context 中的 workspace 参数设置
    """

    name = "file_operation"
    display_name = "文件操作"
    description = "对工作目录内的文件和目录进行读写、列表、创建、删除等操作，包含路径安全限制"
    category = "productivity"
    icon = "📁"
    version = "1.0.0"

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：read_file(读取文件) / write_file(写入文件) / list_dir(列出目录) / create_dir(创建目录) / delete_file(删除文件) / file_exists(检查存在)",
                "enum": ["read_file", "write_file", "list_dir", "create_dir", "delete_file", "file_exists"],
            },
            "path": {
                "type": "string",
                "description": "文件或目录路径（相对于工作目录的相对路径，或绝对路径但必须在工作目录内）",
            },
            "content": {
                "type": "string",
                "description": "文件内容（用于 write_file 操作）",
            },
            "encoding": {
                "type": "string",
                "description": "文件编码，默认 utf-8",
                "default": "utf-8",
            },
            "recursive": {
                "type": "boolean",
                "description": "是否递归（用于 create_dir / delete_file 操作）",
                "default": True,
            },
            "show_hidden": {
                "type": "boolean",
                "description": "是否显示隐藏文件（用于 list_dir 操作）",
                "default": False,
            },
        },
        "required": ["action", "path"],
    }

    # 支持的操作列表
    _SUPPORTED_ACTIONS = {
        "read_file", "write_file", "list_dir",
        "create_dir", "delete_file", "file_exists",
    }

    # 默认工作目录（可被 context 中的 workspace 覆盖）
    _default_workspace: str = ""

    def _get_workspace(self, context: dict[str, Any]) -> str:
        """获取工作目录.

        优先级: context["workspace"] > context["project_path"] > 默认工作目录 > 当前目录

        Args:
            context: 执行上下文

        Returns:
            工作目录绝对路径
        """
        workspace = (
            context.get("workspace")
            or context.get("project_path")
            or self._default_workspace
            or os.getcwd()
        )
        return os.path.abspath(workspace)

    def _resolve_safe_path(
        self,
        target_path: str,
        workspace: str,
    ) -> tuple[bool, str, str]:
        """解析并验证路径安全性.

        确保目标路径在工作目录范围内，防止路径遍历攻击。

        Args:
            target_path: 目标路径（相对或绝对）
            workspace: 工作目录

        Returns:
            (是否安全, 解析后的绝对路径, 错误信息)
        """
        if not target_path:
            return False, "", "路径不能为空"

        # 规范化工作目录
        workspace = os.path.abspath(workspace)

        # 如果是相对路径，拼接工作目录
        if os.path.isabs(target_path):
            abs_path = os.path.abspath(target_path)
        else:
            abs_path = os.path.abspath(os.path.join(workspace, target_path))

        # 检查是否在工作目录内（使用 Path 的 is_relative_to 兼容方案）
        try:
            Path(abs_path).resolve().relative_to(Path(workspace).resolve())
        except ValueError:
            return False, abs_path, f"路径越界：{target_path} 不在工作目录 {workspace} 内"

        return True, abs_path, ""

    def execute(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行文件操作.

        Args:
            params: 参数字典，必须包含 action 和 path
            context: 执行上下文

        Returns:
            执行结果字典
        """
        ctx = context or {}
        action = params.get("action", "")
        target_path = params.get("path", "")

        if not action:
            return {
                "success": False,
                "message": "缺少 action 参数",
                "data": {"supported_actions": sorted(self._SUPPORTED_ACTIONS)},
            }

        if action not in self._SUPPORTED_ACTIONS:
            return {
                "success": False,
                "message": f"不支持的操作: {action}",
                "data": {"supported_actions": sorted(self._SUPPORTED_ACTIONS)},
            }

        if not target_path and action != "list_dir":
            return {
                "success": False,
                "message": "缺少 path 参数",
                "data": {"action": action},
            }

        # 获取工作目录并验证路径安全
        workspace = self._get_workspace(ctx)
        safe, abs_path, error_msg = self._resolve_safe_path(target_path, workspace)

        # list_dir 空路径表示工作目录本身
        if action == "list_dir" and not target_path:
            safe = True
            abs_path = os.path.abspath(workspace)
            error_msg = ""

        if not safe:
            return {
                "success": False,
                "message": error_msg,
                "data": {
                    "action": action,
                    "requested_path": target_path,
                    "workspace": workspace,
                },
            }

        # 根据 action 分发到具体方法
        handler = getattr(self, f"_handle_{action}", None)
        if handler is None:
            return {
                "success": False,
                "message": f"操作 {action} 暂无处理方法",
                "data": {"action": action},
            }

        try:
            result = handler(abs_path, params, ctx, workspace)
            return result
        except Exception as e:
            return {
                "success": False,
                "message": f"执行 {action} 时发生异常: {e}",
                "data": {
                    "action": action,
                    "path": target_path,
                    "error": str(e),
                },
            }

    def _handle_read_file(
        self,
        abs_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
        workspace: str,
    ) -> dict[str, Any]:
        """处理读取文件操作."""
        if not os.path.isfile(abs_path):
            return {
                "success": False,
                "message": f"文件不存在: {abs_path}",
                "data": {"path": abs_path},
            }

        encoding = params.get("encoding", "utf-8")
        try:
            with open(abs_path, "r", encoding=encoding) as f:
                content = f.read()
            return {
                "success": True,
                "message": "文件读取成功",
                "data": {
                    "path": abs_path,
                    "content": content,
                    "size": len(content),
                    "encoding": encoding,
                },
            }
        except UnicodeDecodeError:
            return {
                "success": False,
                "message": f"文件编码错误，无法使用 {encoding} 解码",
                "data": {"path": abs_path, "encoding": encoding},
            }

    def _handle_write_file(
        self,
        abs_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
        workspace: str,
    ) -> dict[str, Any]:
        """处理写入文件操作."""
        content = params.get("content", "")
        encoding = params.get("encoding", "utf-8")

        # 确保父目录存在
        parent_dir = os.path.dirname(abs_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        with open(abs_path, "w", encoding=encoding) as f:
            f.write(content)

        return {
            "success": True,
            "message": "文件写入成功",
            "data": {
                "path": abs_path,
                "size": len(content),
                "encoding": encoding,
            },
        }

    def _handle_list_dir(
        self,
        abs_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
        workspace: str,
    ) -> dict[str, Any]:
        """处理列出目录操作."""
        if not os.path.isdir(abs_path):
            return {
                "success": False,
                "message": f"目录不存在: {abs_path}",
                "data": {"path": abs_path},
            }

        show_hidden = params.get("show_hidden", False)
        entries = []

        for item in os.listdir(abs_path):
            # 跳过隐藏文件（以 . 开头）
            if not show_hidden and item.startswith("."):
                continue

            item_path = os.path.join(abs_path, item)
            is_dir = os.path.isdir(item_path)
            try:
                size = 0 if is_dir else os.path.getsize(item_path)
            except OSError:
                size = 0

            entries.append({
                "name": item,
                "is_dir": is_dir,
                "size": size,
                "path": os.path.relpath(item_path, workspace),
            })

        # 排序：目录在前，文件在后，按名称排序
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        return {
            "success": True,
            "message": "目录列表获取成功",
            "data": {
                "path": abs_path,
                "entries": entries,
                "count": len(entries),
                "show_hidden": show_hidden,
            },
        }

    def _handle_create_dir(
        self,
        abs_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
        workspace: str,
    ) -> dict[str, Any]:
        """处理创建目录操作."""
        recursive = params.get("recursive", True)

        if os.path.exists(abs_path):
            return {
                "success": True,
                "message": "目录已存在",
                "data": {"path": abs_path, "already_exists": True},
            }

        if recursive:
            os.makedirs(abs_path, exist_ok=True)
        else:
            os.mkdir(abs_path)

        return {
            "success": True,
            "message": "目录创建成功",
            "data": {"path": abs_path, "recursive": recursive},
        }

    def _handle_delete_file(
        self,
        abs_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
        workspace: str,
    ) -> dict[str, Any]:
        """处理删除文件/目录操作."""
        if not os.path.exists(abs_path):
            return {
                "success": False,
                "message": f"路径不存在: {abs_path}",
                "data": {"path": abs_path},
            }

        recursive = params.get("recursive", True)

        if os.path.isfile(abs_path):
            os.remove(abs_path)
            return {
                "success": True,
                "message": "文件删除成功",
                "data": {"path": abs_path, "type": "file"},
            }
        elif os.path.isdir(abs_path):
            if recursive:
                shutil.rmtree(abs_path)
            else:
                # 非递归删除只能删除空目录
                try:
                    os.rmdir(abs_path)
                except OSError as e:
                    return {
                        "success": False,
                        "message": f"目录删除失败（可能非空）: {e}",
                        "data": {"path": abs_path, "type": "dir"},
                    }
            return {
                "success": True,
                "message": "目录删除成功",
                "data": {"path": abs_path, "type": "dir", "recursive": recursive},
            }
        else:
            return {
                "success": False,
                "message": "未知路径类型",
                "data": {"path": abs_path},
            }

    def _handle_file_exists(
        self,
        abs_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
        workspace: str,
    ) -> dict[str, Any]:
        """处理文件存在检查操作."""
        exists = os.path.exists(abs_path)
        is_file = os.path.isfile(abs_path) if exists else False
        is_dir = os.path.isdir(abs_path) if exists else False

        return {
            "success": True,
            "message": "检查完成",
            "data": {
                "path": abs_path,
                "exists": exists,
                "is_file": is_file,
                "is_dir": is_dir,
            },
        }

    def health_check(self) -> bool:
        """文件操作技能始终可用（只要文件系统正常）."""
        return True
