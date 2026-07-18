"""
数据治理（Data Governance）
==========================

提供数据分类分级、生命周期管理、血缘追踪和质量报告能力。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from datetime import datetime

from .quality_checker import QualityCheckResult, QualitySeverity


# ============================================================
# 数据分类分级
# ============================================================

class DataClassification(str, Enum):
    """数据分类"""
    PUBLIC = "public"           # 公开数据
    INTERNAL = "internal"       # 内部数据
    CONFIDENTIAL = "confidential"  # 机密数据
    RESTRICTED = "restricted"   # 受限数据（最高级别）


class DataLifecycleStage(str, Enum):
    """数据生命周期阶段"""
    CREATED = "created"         # 创建
    ACTIVE = "active"           # 活跃使用
    ARCHIVED = "archived"       # 归档
    DELETED = "deleted"         # 已删除（可恢复）
    PURGED = "purged"           # 已清除（不可恢复）


# ============================================================
# 数据血缘
# ============================================================

@dataclass
class DataLineage:
    """
    数据血缘记录。

    追踪数据的来源、转换和流向。
    """
    lineage_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_model: str = ""
    source_field: str = ""
    target_model: str = ""
    target_field: str = ""
    transform_type: str = ""     # 转换类型：copy/aggregate/join/compute
    transform_logic: str = ""    # 转换逻辑描述
    created_at: float = field(default_factory=time.time)
    created_by: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lineage_id": self.lineage_id,
            "source_model": self.source_model,
            "source_field": self.source_field,
            "target_model": self.target_model,
            "target_field": self.target_field,
            "transform_type": self.transform_type,
            "transform_logic": self.transform_logic,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }


# ============================================================
# 数据质量报告
# ============================================================

@dataclass
class QualityReport:
    """
    数据质量报告。

    汇总多个模型的质量检查结果，生成综合报告。
    """
    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: float = field(default_factory=time.time)
    model_results: Dict[str, QualityCheckResult] = field(default_factory=dict)
    overall_score: float = 0.0
    summary: Dict[str, Any] = field(default_factory=dict)

    def calculate(self) -> None:
        """计算综合评分和摘要"""
        if not self.model_results:
            self.overall_score = 0.0
            self.summary = {}
            return

        total_records = 0
        total_issues = 0
        total_errors = 0
        total_warnings = 0
        scores = []

        for model_name, result in self.model_results.items():
            total_records += result.total_records
            total_issues += result.issue_count
            total_errors += result.error_count
            total_warnings += result.warning_count
            scores.append(result.score)

        self.overall_score = round(sum(scores) / len(scores), 2) if scores else 0.0

        self.summary = {
            "models_checked": len(self.model_results),
            "total_records": total_records,
            "total_issues": total_issues,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "overall_score": self.overall_score,
            "passed_models": sum(1 for r in self.model_results.values() if r.passed),
            "failed_models": sum(1 for r in self.model_results.values() if not r.passed),
            "grade": self._get_grade(self.overall_score),
        }

    def _get_grade(self, score: float) -> str:
        """根据评分获取等级"""
        if score >= 95:
            return "A+"
        elif score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"

    def to_dict(self) -> Dict[str, Any]:
        if not self.summary:
            self.calculate()
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "overall_score": self.overall_score,
            "models": {
                name: result.to_dict()
                for name, result in self.model_results.items()
            },
        }


# ============================================================
# 数据治理管理器
# ============================================================

class DataGovernance:
    """
    数据治理管理器。

    提供数据分类分级、生命周期管理、血缘追踪和质量报告能力。
    """

    def __init__(self):
        # 数据分类配置
        self._classifications: Dict[str, DataClassification] = {}

        # 生命周期策略
        self._lifecycle_policies: Dict[str, Dict[str, Any]] = {}

        # 数据血缘
        self._lineages: List[DataLineage] = []

        # 质量报告历史
        self._report_history: List[QualityReport] = []

    # ---- 数据分类分级 ----

    def set_classification(self, model_name: str, classification: DataClassification) -> None:
        """设置模型的数据分类等级"""
        self._classifications[model_name] = classification

    def get_classification(self, model_name: str) -> DataClassification:
        """获取模型的数据分类等级"""
        return self._classifications.get(model_name, DataClassification.INTERNAL)

    def list_classifications(self) -> Dict[str, str]:
        """列出所有模型的分类"""
        return {k: v.value for k, v in self._classifications.items()}

    def get_models_by_classification(
        self, classification: DataClassification
    ) -> List[str]:
        """获取指定分类的所有模型"""
        return [
            name for name, cls in self._classifications.items()
            if cls == classification
        ]

    # ---- 生命周期管理 ----

    def set_lifecycle_policy(
        self,
        model_name: str,
        active_days: int = 90,
        archive_days: int = 365,
        delete_days: int = 365 * 3,
        purge_days: int = 365 * 7,
    ) -> None:
        """
        设置数据生命周期策略。

        Args:
            model_name: 模型名称
            active_days: 活跃期天数
            archive_days: 归档前天数
            delete_days: 删除前天数
            purge_days: 清除前天数
        """
        self._lifecycle_policies[model_name] = {
            "active_days": active_days,
            "archive_days": archive_days,
            "delete_days": delete_days,
            "purge_days": purge_days,
        }

    def get_lifecycle_policy(self, model_name: str) -> Optional[Dict[str, Any]]:
        """获取生命周期策略"""
        return self._lifecycle_policies.get(model_name)

    def get_lifecycle_stage(
        self,
        model_name: str,
        record_timestamp: float,
    ) -> DataLifecycleStage:
        """
        根据时间戳判断数据所处的生命周期阶段。

        Args:
            model_name: 模型名称
            record_timestamp: 记录创建/更新时间戳

        Returns:
            生命周期阶段
        """
        policy = self._lifecycle_policies.get(model_name)
        if not policy:
            return DataLifecycleStage.ACTIVE

        age_days = (time.time() - record_timestamp) / 86400

        if age_days < policy["active_days"]:
            return DataLifecycleStage.ACTIVE
        elif age_days < policy["archive_days"]:
            return DataLifecycleStage.ARCHIVED
        elif age_days < policy["delete_days"]:
            return DataLifecycleStage.DELETED
        else:
            return DataLifecycleStage.PURGED

    # ---- 数据血缘 ----

    def add_lineage(self, lineage: DataLineage) -> None:
        """添加数据血缘记录"""
        self._lineages.append(lineage)

    def get_lineage_by_target(self, model_name: str) -> List[DataLineage]:
        """获取指定模型作为目标的血缘关系"""
        return [l for l in self._lineages if l.target_model == model_name]

    def get_lineage_by_source(self, model_name: str) -> List[DataLineage]:
        """获取指定模型作为源的血缘关系"""
        return [l for l in self._lineages if l.source_model == model_name]

    def get_lineage(self, model_name: str) -> List[DataLineage]:
        """获取指定模型的所有血缘关系"""
        return [
            l for l in self._lineages
            if l.source_model == model_name or l.target_model == model_name
        ]

    def trace_upstream(self, model_name: str, depth: int = 3) -> List[Dict[str, Any]]:
        """
        向上追溯数据来源（找所有上游）。

        Args:
            model_name: 起始模型
            depth: 追溯深度

        Returns:
            上游数据血缘列表
        """
        visited: Set[str] = set()
        result: List[DataLineage] = []
        current = {model_name}

        for _ in range(depth):
            next_level: Set[str] = set()
            for model in current:
                lineages = self.get_lineage_by_target(model)
                for lineage in lineages:
                    if lineage.source_model not in visited:
                        result.append(lineage)
                        next_level.add(lineage.source_model)
            visited.update(next_level)
            current = next_level
            if not current:
                break

        return [l.to_dict() for l in result]

    def trace_downstream(self, model_name: str, depth: int = 3) -> List[Dict[str, Any]]:
        """
        向下追踪数据流向（找所有下游）。

        Args:
            model_name: 起始模型
            depth: 追溯深度

        Returns:
            下游数据血缘列表
        """
        visited: Set[str] = set()
        result: List[DataLineage] = []
        current = {model_name}

        for _ in range(depth):
            next_level: Set[str] = set()
            for model in current:
                lineages = self.get_lineage_by_source(model)
                for lineage in lineages:
                    if lineage.target_model not in visited:
                        result.append(lineage)
                        next_level.add(lineage.target_model)
            visited.update(next_level)
            current = next_level
            if not current:
                break

        return [l.to_dict() for l in result]

    # ---- 质量报告 ----

    def generate_report(
        self,
        model_results: Dict[str, QualityCheckResult],
    ) -> QualityReport:
        """
        生成数据质量报告。

        Args:
            model_results: 各模型的质量检查结果

        Returns:
            质量报告
        """
        report = QualityReport(model_results=model_results)
        report.calculate()
        self._report_history.append(report)

        # 保留最近 100 份报告
        if len(self._report_history) > 100:
            self._report_history = self._report_history[-100:]

        return report

    def get_report_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取历史报告列表"""
        reports = self._report_history[-limit:]
        return [
            {
                "report_id": r.report_id,
                "generated_at": r.generated_at,
                "overall_score": r.overall_score,
                "models_checked": len(r.model_results),
                "summary": r.summary,
            }
            for r in reversed(reports)
        ]

    def get_latest_report(self) -> Optional[QualityReport]:
        """获取最新报告"""
        if not self._report_history:
            return None
        return self._report_history[-1]

    # ---- 统计信息 ----

    def get_stats(self) -> Dict[str, Any]:
        """获取治理统计信息"""
        classification_counts = {}
        for cls in self._classifications.values():
            classification_counts[cls.value] = classification_counts.get(cls.value, 0) + 1

        return {
            "classified_models": len(self._classifications),
            "classification_counts": classification_counts,
            "lifecycle_policies": len(self._lifecycle_policies),
            "lineage_records": len(self._lineages),
            "quality_reports": len(self._report_history),
        }


# ============================================================
# 全局单例
# ============================================================

_governance: Optional[DataGovernance] = None


def get_data_governance() -> DataGovernance:
    """获取数据治理管理器单例"""
    global _governance
    if _governance is None:
        _governance = DataGovernance()
    return _governance


def reset_data_governance() -> None:
    """重置数据治理管理器（测试用）"""
    global _governance
    _governance = None
