"""
分身工厂 — CloneFactory

按需创建四种临时分身（勘探/规划/撰写/审查），
遵循最小信息下发原则：分身只获得完成任务所需的最少上下文。
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from shared_models import CloneIdentity, CloneType

logger = structlog.get_logger(__name__)


class CloneFactory:
    """分身工厂

    职责：
    - 创建四种类型的临时分身
    - 按分身类型裁剪上下文，实现最小信息下发
    - 为每种分身类型生成对应的能力列表与默认TTL
    """

    # ── 能力注册表：每种分身类型对应的能力集 ──
    _CAPABILITY_MAP: dict[CloneType, list[str]] = {
        CloneType.SCOUT: [
            "search",
            "scan",
            "probe",
            "read_only",
            "report",
        ],
        CloneType.PLANNER: [
            "decompose",
            "dependency_analysis",
            "resource_estimation",
            "scheduling",
            "critical_path",
        ],
        CloneType.WRITER: [
            "generate",
            "format",
            "compose",
            "reference_lookup",
            "template_apply",
        ],
        CloneType.REVIEWER: [
            "inspect",
            "validate",
            "compare",
            "score",
            "feedback",
        ],
    }

    # ── 默认TTL映射：每种分身类型的最大存活时间（秒） ──
    _TTL_MAP: dict[CloneType, int] = {
        CloneType.SCOUT: 120,       # 勘探分身：快速扫描，2分钟足够
        CloneType.PLANNER: 300,     # 规划分身：需要较长时间分析依赖
        CloneType.WRITER: 600,      # 撰写分身：生成内容耗时较长
        CloneType.REVIEWER: 180,    # 审查分身：审查比撰写快，3分钟
    }

    # ── 上下文裁剪保留字段映射：最小信息下发 ──
    _CONTEXT_FIELDS: dict[CloneType, list[str]] = {
        CloneType.SCOUT: [
            "task_description",
            "goal",
            "key_constraints",
            "scan_scope",
            "search_targets",
        ],
        CloneType.PLANNER: [
            "task_description",
            "dependencies",
            "resource_info",
            "team_composition",
            "time_constraints",
            "priority",
        ],
        CloneType.WRITER: [
            "task_description",
            "output_format",
            "reference_materials",
            "style_guide",
            "word_limit",
            "target_audience",
        ],
        CloneType.REVIEWER: [
            "check_criteria",
            "content_summary",
            "review_standards",
            "quality_threshold",
        ],
    }

    def __init__(self) -> None:
        self._logger = logger.bind(component="clone_factory")

    def create_clone(
        self,
        parent_agent_id: str,
        clone_type: CloneType,
        task_id: str,
        capabilities: list[str] | None = None,
        ttl: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> CloneIdentity:
        """创建一个临时分身

        Args:
            parent_agent_id: 创建该分身的父Agent ID
            clone_type:     分身类型（SCOUT/PLANNER/WRITER/REVIEWER）
            task_id:        分身要执行的任务ID
            capabilities:   自定义能力列表（None则按类型自动生成）
            ttl:            自定义存活时间秒数（None则按类型使用默认值）
            context:        完整上下文（工厂会自动裁剪为最小上下文）

        Returns:
            创建好的 CloneIdentity 实例
        """
        # 按类型生成默认能力列表（如果未自定义）
        resolved_capabilities = (
            capabilities
            if capabilities is not None
            else self._generate_capabilities(clone_type)
        )

        # 使用自定义TTL或按类型获取默认值
        resolved_ttl = ttl if ttl is not None else self._default_ttl(clone_type)

        # 最小信息下发：裁剪上下文
        minimized = self._minimize_context(clone_type, context or {})

        clone = CloneIdentity(
            parent_agent_id=parent_agent_id,
            clone_type=clone_type,
            task_id=task_id,
            capabilities=resolved_capabilities,
            ttl=resolved_ttl,
            minimized_context=minimized,
        )

        self._logger.info(
            "clone_created",
            clone_id=clone.clone_id,
            clone_type=clone_type.value,
            parent_agent_id=parent_agent_id,
            task_id=task_id,
            ttl=resolved_ttl,
            capabilities_count=len(resolved_capabilities),
            context_fields=list(minimized.keys()),
        )

        return clone

    def _minimize_context(
        self, clone_type: CloneType, full_context: dict[str, Any]
    ) -> dict[str, Any]:
        """按分身类型裁剪上下文，实现最小信息下发原则

        每种分身只获得完成任务所需的最少字段，防止信息过度暴露。

        裁剪规则：
        - SCOUT：    仅保留任务描述 + 目标 + 关键约束
        - PLANNER：  保留任务描述 + 依赖关系 + 资源信息
        - WRITER：   保留任务描述 + 输出格式 + 参考材料
        - REVIEWER： 仅保留检查标准 + 待审查内容摘要

        Args:
            clone_type:   分身类型
            full_context:  完整上下文字典

        Returns:
            裁剪后的最小上下文字典
        """
        allowed_fields = self._CONTEXT_FIELDS.get(
            clone_type, ["task_description"]
        )

        minimized: dict[str, Any] = {}
        for key in allowed_fields:
            if key in full_context:
                minimized[key] = full_context[key]

        # 记录裁剪信息：有多少字段被过滤掉
        filtered_count = len(full_context) - len(minimized)
        if filtered_count > 0:
            self._logger.debug(
                "context_minimized",
                clone_type=clone_type.value,
                original_fields=len(full_context),
                retained_fields=len(minimized),
                filtered_fields=filtered_count,
            )

        return minimized

    def _generate_capabilities(self, clone_type: CloneType) -> list[str]:
        """按分身类型生成能力列表

        Args:
            clone_type: 分身类型

        Returns:
            该类型分身的标准能力列表
        """
        return list(self._CAPABILITY_MAP.get(clone_type, []))

    def _default_ttl(self, clone_type: CloneType) -> int:
        """按分身类型返回默认TTL

        Args:
            clone_type: 分身类型

        Returns:
            默认存活时间（秒）
        """
        return self._TTL_MAP.get(clone_type, 300)
