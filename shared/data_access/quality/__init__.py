"""
数据质量（Data Quality）
=======================

提供数据质量检查和数据治理能力。
"""

from .quality_checker import (
    QualityChecker,
    QualityCheckResult,
    QualityIssue,
    QualityRule,
    QualityRuleType,
    QualitySeverity,
)
from .governance import (
    DataGovernance,
    DataClassification,
    DataLifecycleStage,
    DataLineage,
    QualityReport,
    get_data_governance,
)

__all__ = [
    # 质量检查
    "QualityChecker",
    "QualityCheckResult",
    "QualityIssue",
    "QualityRule",
    "QualityRuleType",
    "QualitySeverity",
    # 数据治理
    "DataGovernance",
    "DataClassification",
    "DataLifecycleStage",
    "DataLineage",
    "QualityReport",
    "get_data_governance",
]
