"""服务模块.

包含场景识别、切换管理、上下文存储、VS Code 启动、MCP 客户端、技能系统等核心服务。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


__all__ = [
    "SceneRecognizer",
    "SceneSwitchManager",
    "ContextStore",
    "VSCodeLauncher",
    "McpClient",
    "BaseSkill",
    "SkillExecutor",
    "VSCodeControlSkill",
    "FileOperationSkill",
    "TerminalCommandSkill",
    "GitToolSkill",
    "get_skill_executor",
]
