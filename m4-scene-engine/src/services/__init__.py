"""服务模块.

包含场景识别、切换管理、上下文存储、VS Code 启动、MCP 客户端、技能系统等核心服务。

使用懒加载机制（__getattr__）避免循环导入，运行时按需加载各服务类。
类型注解通过 TYPE_CHECKING 导入，不产生运行时开销。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 类型注解专用导入，仅在静态分析时生效
    from src.services.recognizer import SceneRecognizer
    from src.services.switcher import SceneSwitchManager
    from src.services.context_store import ContextStore
    from src.services.vscode_launcher import VSCodeLauncher
    from src.services.mcp_client import McpClient
    from src.services.skill_executor import SkillExecutor
    from src.services.skills.base import BaseSkill
    from src.services.skills.vscode_control_skill import VSCodeControlSkill
    from src.services.skills.file_operation_skill import FileOperationSkill
    from src.services.skills.terminal_command_skill import TerminalCommandSkill
    from src.services.skills.git_tool_skill import GitToolSkill


# ---------------------------------------------------------------------------
# 懒加载模块映射
# ---------------------------------------------------------------------------
# 格式: 导出名称 -> (模块路径, 类/函数名)
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # 核心服务
    "SceneRecognizer": ("src.services.recognizer", "SceneRecognizer"),
    "SceneSwitchManager": ("src.services.switcher", "SceneSwitchManager"),
    "ContextStore": ("src.services.context_store", "ContextStore"),
    "VSCodeLauncher": ("src.services.vscode_launcher", "VSCodeLauncher"),
    "get_vscode_launcher": ("src.services.vscode_launcher", "get_vscode_launcher"),
    "McpClient": ("src.services.mcp_client", "McpClient"),
    "get_mcp_client": ("src.services.mcp_client", "get_mcp_client"),
    # 技能系统
    "BaseSkill": ("src.services.skills.base", "BaseSkill"),
    "VSCodeControlSkill": ("src.services.skills.vscode_control_skill", "VSCodeControlSkill"),
    "FileOperationSkill": ("src.services.skills.file_operation_skill", "FileOperationSkill"),
    "TerminalCommandSkill": ("src.services.skills.terminal_command_skill", "TerminalCommandSkill"),
    "GitToolSkill": ("src.services.skills.git_tool_skill", "GitToolSkill"),
    "SkillExecutor": ("src.services.skill_executor", "SkillExecutor"),
    "get_skill_executor": ("src.services.skill_executor", "get_skill_executor"),
}


def __getattr__(name: str):
    """懒加载钩子 - 首次访问时才实际导入模块.

    Args:
        name: 要获取的属性名

    Returns:
        对应的类或函数实例

    Raises:
        AttributeError: 名称不在导出列表中
    """
    if name in _LAZY_EXPORTS:
        import importlib
        module_path, attr_name = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_path)
        attr = getattr(module, attr_name)
        # 缓存到模块全局，避免重复导入
        globals()[name] = attr
        return attr
    raise AttributeError(f"module 'src.services' has no attribute {name!r}")


def __dir__() -> list[str]:
    """返回所有可用的导出名称（用于 IDE 补全和 dir() 调用）."""
    return sorted(set(list(globals().keys()) + list(_LAZY_EXPORTS.keys())))


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
