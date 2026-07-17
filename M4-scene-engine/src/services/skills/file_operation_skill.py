"""文件操作技能.

提供文件读取、写入、目录列出、创建目录、删除文件/目录、文件存在检查等功能。
包含路径安全限制，防止越权访问工作目录以外的文件。

安全修复记录：
- SEC-012 (2026-07-18): 加固路径遍历防护，使用 os.path.realpath()
  解析最终路径后与基础目录比较，增加符号链接检测，
  所有文件操作前都经过路径安全检查。
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from src.services.skills.base import BaseSkill

# 审计日志记录器
_audit_logger = logging.getLogger("yunxi.security.audit.file_operation")


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
        - 所有路径使用 os.path.realpath() 解析后与 workspace 比较
        - 符号链接检测：禁止跟随链接跳出 workspace
        - 空字节注入检测
        - 默认工作目录可通过 context 中的 workspace 参数设置
        - 所有文件操作记录审计日志
    """

    name = "file_operation"
    display_name = "文件操作"
    description = "对工作目录内的文件和目录进行读写、列表、创建、删除等操作，包含严格的路径安全限制"
    category = "productivity"
    icon = "📁"
    version = "1.1.0"

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

    # 最大文件大小（读取）：10MB
    _MAX_READ_SIZE = 10 * 1024 * 1024

    # 最大文件大小（写入）：50MB
    _MAX_WRITE_SIZE = 50 * 1024 * 1024

    # ------------------------------------------------------------------
    # 工作目录
    # ------------------------------------------------------------------

    def _get_workspace(self, context: dict[str, Any]) -> str:
        """获取工作目录.

        优先级: context["workspace"] > context["project_path"] > 默认工作目录 > 当前目录

        Args:
            context: 执行上下文

        Returns:
            工作目录绝对路径（已规范化）
        """
        workspace = (
            context.get("workspace")
            or context.get("project_path")
            or self._default_workspace
            or os.getcwd()
        )
        return os.path.abspath(workspace)

    # ------------------------------------------------------------------
    # 路径安全检查
    # ------------------------------------------------------------------

    def _resolve_safe_path(
        self,
        target_path: str,
        workspace: str,
    ) -> tuple[bool, str, str]:
        """解析并验证路径安全性（SEC-012 加固版）.

        确保目标路径在工作目录范围内，防止路径遍历攻击。
        使用 os.path.realpath() 解析符号链接后的真实路径进行比较。

        安全检查步骤：
        1. 空值检查
        2. 空字节注入检测
        3. 路径规范化
        4. realpath 解析符号链接
        5. 与 workspace 的 realpath 比较

        Args:
            target_path: 目标路径（相对或绝对）
            workspace: 工作目录

        Returns:
            (是否安全, 解析后的绝对路径, 错误信息)
        """
        # 1. 空值检查
        if not target_path:
            return False, "", "路径不能为空"

        # 2. 空字节注入检测
        if "\x00" in target_path:
            self._audit_log("path_check", target_path, workspace, False, "空字节注入检测")
            return False, "", "路径包含非法字符"

        # 3. 规范化工作目录（解析符号链接）
        try:
            real_workspace = os.path.realpath(workspace)
        except OSError as e:
            return False, "", f"工作目录解析失败: {e}"

        # 4. 解析目标路径
        try:
            if os.path.isabs(target_path):
                # 绝对路径：直接规范化
                abs_path = os.path.abspath(target_path)
            else:
                # 相对路径：拼接工作目录后规范化
                abs_path = os.path.abspath(os.path.join(workspace, target_path))

            # 解析符号链接后的真实路径
            # 注意：对于不存在的路径，realpath 会返回规范化后的路径
            # 对于存在的路径，会跟随所有符号链接
            real_path = os.path.realpath(abs_path)
        except OSError as e:
            return False, "", f"路径解析失败: {e}"

        # 5. 检查是否在工作目录内
        # 使用 realpath 比较，防止符号链接绕过
        if not (real_path == real_workspace or real_path.startswith(real_workspace + os.sep)):
            self._audit_log(
                "path_check", target_path, workspace, False,
                f"路径越界: real_path={real_path}, workspace={real_workspace}",
            )
            return False, real_path, f"路径越界：目标路径不在工作目录范围内"

        # 6. 符号链接检测（对于已存在的路径）
        # 如果路径存在且是符号链接，检查链接目标是否在 workspace 内
        # （realpath 已经处理了这个，但我们额外记录日志）
        if os.path.exists(abs_path) and os.path.islink(abs_path):
            link_target = os.readlink(abs_path)
            _audit_logger.debug(
                "Symlink detected: %s -> %s (resolved: %s)",
                abs_path, link_target, real_path,
            )
            # realpath 已经确保了目标在 workspace 内，所以这里只记录

        # 7. 检查路径中的每个组件是否包含危险模式
        # （如 Windows 上的 \\.\ 或 Unix 上的 /proc/self/fd 等）
        if self._is_dangerous_path_pattern(real_path, real_workspace):
            self._audit_log("path_check", target_path, workspace, False, "危险路径模式")
            return False, real_path, "路径包含危险模式，已拒绝"

        return True, real_path, ""

    def _is_dangerous_path_pattern(self, real_path: str, real_workspace: str) -> bool:
        """检测路径是否包含危险模式.

        Args:
            real_path: 已解析的真实路径
            real_workspace: 工作目录的真实路径

        Returns:
            True 表示危险，False 表示安全
        """
        # 规范化路径分隔符
        path_norm = real_path.replace("\\", "/").lower()
        ws_norm = real_workspace.replace("\\", "/").lower()

        # 获取相对路径部分
        if path_norm.startswith(ws_norm + "/"):
            relative_part = path_norm[len(ws_norm) + 1:]
        elif path_norm == ws_norm:
            return False  # workspace 本身是安全的
        else:
            return True  # 不在 workspace 内，由上层检查处理

        # Windows 危险设备路径
        dangerous_patterns = [
            # Windows 设备名
            "con", "prn", "aux", "nul",
            "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
            "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
            # Unix 危险目录（即使在 workspace 内也不应该访问）
            # 注意：这些只有在路径直接以这些名称开头时才会匹配
            # 正常情况下 workspace 内不会有这些目录
        ]

        # 检查第一个路径组件是否是危险名称
        first_component = relative_part.split("/")[0]
        if first_component.lower() in {p.lower() for p in dangerous_patterns}:
            return True

        return False

    # ------------------------------------------------------------------
    # 审计日志
    # ------------------------------------------------------------------

    def _audit_log(
        self,
        action: str,
        target_path: str,
        workspace: str,
        allowed: bool,
        reason: str = "",
    ) -> None:
        """记录文件操作审计日志.

        Args:
            action: 操作类型
            target_path: 目标路径
            workspace: 工作目录
            allowed: 是否被允许
            reason: 拒绝原因
        """
        try:
            _audit_logger.info(
                "File operation %s | action=%s | path=%s | workspace=%s | allowed=%s | reason=%s",
                "ALLOWED" if allowed else "BLOCKED",
                action,
                target_path,
                workspace,
                allowed,
                reason,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 主执行入口
    # ------------------------------------------------------------------

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

        # 获取工作目录
        workspace = self._get_workspace(ctx)

        # list_dir 空路径表示工作目录本身
        if action == "list_dir" and not target_path:
            abs_path = os.path.realpath(workspace)
            safe = True
            error_msg = ""
        else:
            # 路径安全检查
            safe, abs_path, error_msg = self._resolve_safe_path(target_path, workspace)

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

        # 记录审计日志
        self._audit_log(action, target_path, workspace, True)

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

    # ------------------------------------------------------------------
    # 读取文件
    # ------------------------------------------------------------------

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

        # 文件大小限制
        try:
            file_size = os.path.getsize(abs_path)
            if file_size > self._MAX_READ_SIZE:
                return {
                    "success": False,
                    "message": f"文件过大（{file_size} 字节），超过最大读取限制 {self._MAX_READ_SIZE} 字节",
                    "data": {"path": abs_path, "size": file_size, "max_size": self._MAX_READ_SIZE},
                }
        except OSError as e:
            return {
                "success": False,
                "message": f"无法获取文件大小: {e}",
                "data": {"path": abs_path, "error": str(e)},
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

    # ------------------------------------------------------------------
    # 写入文件
    # ------------------------------------------------------------------

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

        # 写入大小限制
        if len(content.encode(encoding, errors="replace")) > self._MAX_WRITE_SIZE:
            return {
                "success": False,
                "message": f"写入内容过大，超过最大写入限制 {self._MAX_WRITE_SIZE} 字节",
                "data": {"path": abs_path, "max_size": self._MAX_WRITE_SIZE},
            }

        # 确保父目录存在且在 workspace 内
        parent_dir = os.path.dirname(abs_path)
        if parent_dir:
            # 再次验证父目录的安全性
            parent_safe, parent_real, parent_error = self._resolve_safe_path(
                parent_dir, workspace
            )
            if not parent_safe:
                return {
                    "success": False,
                    "message": f"父目录不安全: {parent_error}",
                    "data": {"path": abs_path, "parent_dir": parent_dir},
                }
            os.makedirs(parent_real, exist_ok=True)

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

    # ------------------------------------------------------------------
    # 列出目录
    # ------------------------------------------------------------------

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

            # 检查每个条目是否通过符号链接跳出了 workspace
            # 使用 realpath 确保安全
            try:
                real_item = os.path.realpath(item_path)
                real_ws = os.path.realpath(workspace)
                # 确保在 workspace 内
                if not (real_item == real_ws or real_item.startswith(real_ws + os.sep)):
                    # 符号链接指向 workspace 外，跳过
                    continue
            except OSError:
                continue

            is_dir = os.path.isdir(item_path)
            try:
                size = 0 if is_dir else os.path.getsize(item_path)
            except OSError:
                size = 0

            entries.append({
                "name": item,
                "is_dir": is_dir,
                "is_symlink": os.path.islink(item_path),
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

    # ------------------------------------------------------------------
    # 创建目录
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 删除文件/目录
    # ------------------------------------------------------------------

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

        # 额外安全检查：禁止删除 workspace 根目录本身
        real_path = os.path.realpath(abs_path)
        real_workspace = os.path.realpath(workspace)
        if real_path == real_workspace:
            return {
                "success": False,
                "message": "禁止删除工作目录根目录",
                "data": {"path": abs_path, "workspace": workspace},
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

    # ------------------------------------------------------------------
    # 文件存在检查
    # ------------------------------------------------------------------

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
        is_symlink = os.path.islink(abs_path) if exists else False

        return {
            "success": True,
            "message": "检查完成",
            "data": {
                "path": abs_path,
                "exists": exists,
                "is_file": is_file,
                "is_dir": is_dir,
                "is_symlink": is_symlink,
            },
        }

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """文件操作技能始终可用（只要文件系统正常）."""
        return True
