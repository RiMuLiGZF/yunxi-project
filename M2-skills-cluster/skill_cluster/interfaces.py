"""Skill 技能集群系统 - 核心接口与数据模型.

【模型迁移说明】
Pydantic 模型已迁移至 ``skill_cluster.models.skill``，
本文件保留 import 别名以保持向后兼容。

所有 ``from skill_cluster.interfaces import Xxx`` 的导入方式继续有效。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

# ---- 从 models.skill 导入所有 Pydantic 模型（向后兼容） ----
from skill_cluster.models.skill import (
    SkillConfig,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
    SkillQuery,
)

# 保持 field_validator / model_validator 的可访问性（如有外部代码依赖）
from pydantic import field_validator, model_validator  # noqa: F401


__all__ = [
    "ISkill",
    "SkillConfig",
    "SkillInvokeRequest",
    "SkillInvokeResult",
    "SkillManifest",
    "SkillQuery",
    "field_validator",
    "model_validator",
]


class ISkill(ABC):
    """技能抽象基类."""

    def __init__(self, manifest: SkillManifest) -> None:
        self._manifest = manifest

    @property
    def manifest(self) -> SkillManifest:
        """返回技能清单."""
        return self._manifest

    @abstractmethod
    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """执行技能调用.

        Args:
            request: 调用请求.

        Returns:
            调用结果.
        """
        ...

    @abstractmethod
    async def health(self) -> dict:
        """返回健康状态.

        Returns:
            健康状态字典.
        """
        ...

    @abstractmethod
    async def configure(self, config: dict) -> None:
        """配置技能.

        Args:
            config: 配置字典.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self._manifest.skill_id}@{self._manifest.version}>"
