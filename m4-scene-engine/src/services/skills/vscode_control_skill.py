"""VS Code 控制技能.

提供 VS Code 的启动、关闭、打开项目/文件、扩展管理、状态查询等功能。
底层调用 vscode_launcher 服务。
"""

from __future__ import annotations

from typing import Any

try:
    from src.services.skills.base import BaseSkill
except ImportError:
    from services.skills.base import BaseSkill  # type: ignore


class VSCodeControlSkill(BaseSkill):
    """VS Code 控制技能.

    支持的操作（通过 action 参数区分）:
        - launch: 启动 VS Code
        - close: 关闭 VS Code
        - open_project: 打开项目目录
        - open_file: 打开文件（支持行号）
        - install_extension: 安装扩展
        - list_extensions: 列出已安装扩展
        - get_status: 获取 VS Code 状态
    """

    name = "vscode_control"
    display_name = "VS Code 控制"
    description = "控制 VS Code 编辑器，支持启动、关闭、打开项目/文件、安装扩展、查询状态等操作"
    category = "development"
    icon = "💻"
    version = "1.0.0"

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：launch(启动) / close(关闭) / open_project(打开项目) / open_file(打开文件) / install_extension(安装扩展) / list_extensions(列出扩展) / get_status(获取状态)",
                "enum": ["launch", "close", "open_project", "open_file", "install_extension", "list_extensions", "get_status"],
            },
            "project_path": {
                "type": "string",
                "description": "项目路径（用于 open_project / launch 操作）",
            },
            "file_path": {
                "type": "string",
                "description": "文件路径（用于 open_file 操作）",
            },
            "line": {
                "type": "integer",
                "description": "行号（用于 open_file 操作，从 1 开始）",
                "minimum": 1,
            },
            "extension_id": {
                "type": "string",
                "description": "扩展 ID（用于 install_extension 操作，如 ms-python.python）",
            },
            "new_window": {
                "type": "boolean",
                "description": "是否在新窗口打开（用于 launch / open_project 操作）",
                "default": True,
            },
        },
        "required": ["action"],
    }

    # 支持的操作列表
    _SUPPORTED_ACTIONS = {
        "launch", "close", "open_project", "open_file",
        "install_extension", "list_extensions", "get_status",
    }

    def _get_launcher(self) -> Any:
        """获取 VS Code 启动器实例.

        Returns:
            VSCodeLauncher 实例

        Raises:
            ImportError: 无法导入 VS Code 启动器
        """
        try:
            from src.services.vscode_launcher import get_vscode_launcher
        except ImportError:
            from services.vscode_launcher import get_vscode_launcher  # type: ignore
        return get_vscode_launcher()

    def execute(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行 VS Code 控制操作.

        Args:
            params: 参数字典，必须包含 action
            context: 执行上下文

        Returns:
            执行结果字典
        """
        action = params.get("action", "")
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

        try:
            launcher = self._get_launcher()
        except Exception as e:
            return {
                "success": False,
                "message": f"VS Code 启动器不可用: {e}",
                "data": {"action": action},
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
            result = handler(launcher, params, context or {})
            return result
        except Exception as e:
            return {
                "success": False,
                "message": f"执行 {action} 时发生异常: {e}",
                "data": {"action": action, "error": str(e)},
            }

    def _handle_launch(
        self,
        launcher: Any,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理启动 VS Code 操作."""
        project_path = params.get("project_path") or context.get("project_path")
        new_window = params.get("new_window", True)
        result = launcher.launch_vscode(
            project_path=project_path if project_path else None,
            new_window=new_window,
        )
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "data": result,
        }

    def _handle_close(
        self,
        launcher: Any,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理关闭 VS Code 操作."""
        success = launcher.close_vscode()
        return {
            "success": success,
            "message": "VS Code 已关闭" if success else "VS Code 关闭失败或未运行",
            "data": {"closed": success},
        }

    def _handle_open_project(
        self,
        launcher: Any,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理打开项目操作."""
        project_path = params.get("project_path") or context.get("project_path", "")
        if not project_path:
            return {
                "success": False,
                "message": "项目路径不能为空",
                "data": {"action": "open_project"},
            }
        new_window = params.get("new_window", True)
        result = launcher.launch_vscode(
            project_path=project_path,
            new_window=new_window,
        )
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "data": result,
        }

    def _handle_open_file(
        self,
        launcher: Any,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理打开文件操作."""
        file_path = params.get("file_path", "")
        if not file_path:
            return {
                "success": False,
                "message": "文件路径不能为空",
                "data": {"action": "open_file"},
            }
        line = params.get("line")
        result = launcher.open_file(file_path, line=line)
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "data": result.get("data", {}),
        }

    def _handle_install_extension(
        self,
        launcher: Any,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理安装扩展操作."""
        extension_id = params.get("extension_id", "")
        if not extension_id:
            return {
                "success": False,
                "message": "扩展 ID 不能为空",
                "data": {"action": "install_extension"},
            }
        result = launcher.install_extension(extension_id)
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "data": result.get("data", {}),
        }

    def _handle_list_extensions(
        self,
        launcher: Any,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理列出扩展操作."""
        result = launcher.list_extensions()
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "data": result.get("data", {}),
        }

    def _handle_get_status(
        self,
        launcher: Any,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理获取状态操作."""
        result = launcher.get_status()
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "data": result.get("data", {}),
        }

    def health_check(self) -> bool:
        """检查 VS Code 服务是否可用."""
        try:
            launcher = self._get_launcher()
            detect_result = launcher.detect_vscode()
            return detect_result.get("installed", False)
        except Exception:
            return False
