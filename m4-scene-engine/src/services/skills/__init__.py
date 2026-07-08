"""技能模块.

提供技能系统的核心组件，包括技能基类和所有内置技能。

使用方式:
    from src.services.skills import BaseSkill
    from src.services.skills import VSCodeControlSkill, FileOperationSkill
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------

try:
    from src.services.skills.base import BaseSkill
except ImportError:
    from services.skills.base import BaseSkill  # type: ignore


# ---------------------------------------------------------------------------
# 内置技能
# ---------------------------------------------------------------------------

try:
    from src.services.skills.vscode_control_skill import VSCodeControlSkill
    from src.services.skills.file_operation_skill import FileOperationSkill
    from src.services.skills.terminal_command_skill import TerminalCommandSkill
    from src.services.skills.git_tool_skill import GitToolSkill
except ImportError:
    from services.skills.vscode_control_skill import VSCodeControlSkill  # type: ignore
    from services.skills.file_operation_skill import FileOperationSkill  # type: ignore
    from services.skills.terminal_command_skill import TerminalCommandSkill  # type: ignore
    from services.skills.git_tool_skill import GitToolSkill  # type: ignore


__all__ = [
    # 基类
    "BaseSkill",
    # 内置技能
    "VSCodeControlSkill",
    "FileOperationSkill",
    "TerminalCommandSkill",
    "GitToolSkill",
]
