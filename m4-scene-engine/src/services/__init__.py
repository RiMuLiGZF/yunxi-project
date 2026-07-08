"""服务模块.

包含场景识别、切换管理、上下文存储、VS Code 启动、MCP 客户端、技能系统等核心服务。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# 服务类导出（懒加载方式，避免循环导入）
try:
    from .recognizer import SceneRecognizer
except ImportError:
    from recognizer import SceneRecognizer  # type: ignore

try:
    from .switcher import SceneSwitchManager
except ImportError:
    from switcher import SceneSwitchManager  # type: ignore

try:
    from .context_store import ContextStore
except ImportError:
    from context_store import ContextStore  # type: ignore

try:
    from .vscode_launcher import VSCodeLauncher, get_vscode_launcher
except ImportError:
    from vscode_launcher import VSCodeLauncher, get_vscode_launcher  # type: ignore

try:
    from .mcp_client import McpClient, get_mcp_client
except ImportError:
    from mcp_client import McpClient, get_mcp_client  # type: ignore

# 技能系统导出
try:
    from .skills.base import BaseSkill
    from .skills.vscode_control_skill import VSCodeControlSkill
    from .skills.file_operation_skill import FileOperationSkill
    from .skills.terminal_command_skill import TerminalCommandSkill
    from .skills.git_tool_skill import GitToolSkill
    from .skill_executor import SkillExecutor, get_skill_executor
except ImportError:
    try:
        from skills.base import BaseSkill  # type: ignore
        from skills.vscode_control_skill import VSCodeControlSkill  # type: ignore
        from skills.file_operation_skill import FileOperationSkill  # type: ignore
        from skills.terminal_command_skill import TerminalCommandSkill  # type: ignore
        from skills.git_tool_skill import GitToolSkill  # type: ignore
        from skill_executor import SkillExecutor, get_skill_executor  # type: ignore
    except ImportError:
        pass


__all__ = [
    "SceneRecognizer",
    "SceneSwitchManager",
    "ContextStore",
    "VSCodeLauncher",
    "get_vscode_launcher",
    "McpClient",
    "get_mcp_client",
    "BaseSkill",
    "SkillExecutor",
    "get_skill_executor",
    "VSCodeControlSkill",
    "FileOperationSkill",
    "TerminalCommandSkill",
    "GitToolSkill",
]
