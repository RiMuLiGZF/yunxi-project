"""
数据质量检查器（Quality Checker）
================================

提供数据质量检查能力，包括：
- 完整性检查（必填字段）
- 一致性检查（引用完整性）
- 准确性检查（格式/范围）
- 唯一性检查
- 时效性检查
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..base import BaseModel


# ============================================================
# 枚举定义
# ============================================================

class QualityRuleType(str, Enum):
    """质量检查规则类型"""
    COMPLETENESS = "completeness"     # 完整性
    CONSISTENCY = "consistency"       # 一致性
    ACCURACY = "accuracy"             # 准确性
    UNIQUENESS = "uniqueness"         # 唯一性
    TIMELINESS = "timeliness"         # 时效性
    CUSTOM = "custom"                 # 自定义


class QualitySeverity(str, Enum):
    """问题严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ============================================================
# 数据类
# ============================================================

@dataclass
class QualityIssue:
    """质量问题"""
    rule_type: QualityRuleType
    severity: QualitySeverity
    model_name: str
    field: str = ""
    record_id: Any = None
    message: str = ""
    details: Dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_type": self.rule_type.value,
            "severity": self.severity.value,
            "model_name": self.model_name,
            "field": self.field,
            "record_id": str(self.record_id) if self.record_id is not None else None,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class QualityRule:
    """
    质量检查规则。

    Attributes:
        name: 规则名称
        rule_type: 规则类型
        severity: 严重程度
        model_name: 目标模型名
        field: 目标字段名
        check_func: 检查函数（接收数据字典，返回问题列表）
        description: 规则描述
    """
    name: str
    rule_type: QualityRuleType
    severity: QualitySeverity
    model_name: str = ""
    field: str = ""
    check_func: Optional[Callable[[Dict[str, Any]], List[QualityIssue]]] = None
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "rule_type": self.rule_type.value,
            "severity": self.severity.value,
            "model_name": self.model_name,
            "field": self.field,
            "description": self.description,
        }


@dataclass
class QualityCheckResult:
    """质量检查结果"""
    model_name: str
    total_records: int = 0
    issues: List[QualityIssue] = dc_field(default_factory=list)
    execution_time_ms: float = 0.0
    rules_checked: int = 0

    @property
    def issue_count(self) -> int:
        """问题总数"""
        return len(self.issues)

    @property
    def error_count(self) -> int:
        """错误级别问题数"""
        return sum(1 for i in self.issues if i.severity in (QualitySeverity.ERROR, QualitySeverity.CRITICAL))

    @property
    def warning_count(self) -> int:
        """警告级别问题数"""
        return sum(1 for i in self.issues if i.severity == QualitySeverity.WARNING)

    @property
    def passed(self) -> bool:
        """是否通过检查（无错误级问题）"""
        return self.error_count == 0

    @property
    def score(self) -> float:
        """
        质量评分（0-100）。

        基于问题数量和严重程度计算。
        """
        if self.total_records == 0:
            return 100.0

        score = 100.0
        for issue in self.issues:
            if issue.severity == QualitySeverity.CRITICAL:
                score -= 10
            elif issue.severity == QualitySeverity.ERROR:
                score -= 5
            elif issue.severity == QualitySeverity.WARNING:
                score -= 1
            elif issue.severity == QualitySeverity.INFO:
                score -= 0.1

        return max(0.0, round(score, 2))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "total_records": self.total_records,
            "issue_count": self.issue_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "passed": self.passed,
            "score": self.score,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "rules_checked": self.rules_checked,
            "issues": [i.to_dict() for i in self.issues[:100]],  # 最多返回100条
            "has_more_issues": len(self.issues) > 100,
        }


# ============================================================
# 质量检查器
# ============================================================

class QualityChecker:
    """
    数据质量检查器。

    支持多种质量检查规则，可以对模型数据进行全面的质量评估。
    """

    def __init__(self):
        self._rules: List[QualityRule] = []
        self._builtin_checks: Dict[str, Callable] = {}
        self._register_builtin_checks()

    def _register_builtin_checks(self) -> None:
        """注册内置检查"""
        self._builtin_checks = {
            "required": self._check_required,
            "unique": self._check_unique,
            "format": self._check_format,
            "range": self._check_range,
            "referential": self._check_referential,
            "timeliness": self._check_timeliness,
        }

    # ---- 规则管理 ----

    def add_rule(self, rule: QualityRule) -> None:
        """添加检查规则"""
        self._rules.append(rule)

    def add_rules(self, rules: List[QualityRule]) -> None:
        """批量添加规则"""
        self._rules.extend(rules)

    def clear_rules(self) -> None:
        """清除所有规则"""
        self._rules.clear()

    def get_rules(self, model_name: Optional[str] = None) -> List[QualityRule]:
        """获取规则列表"""
        if model_name:
            return [r for r in self._rules if r.model_name == model_name]
        return list(self._rules)

    # ---- 基于模型字段定义的自动检查 ----

    def auto_generate_rules(self, model_class: type) -> List[QualityRule]:
        """
        根据模型字段定义自动生成检查规则。

        解析 __fields__ 中的 required/unique/format 等属性，
        生成对应的质量检查规则。
        """
        model_name = model_class.__name__
        rules: List[QualityRule] = []

        if not hasattr(model_class, "__fields__"):
            return rules

        fields = model_class.__fields__

        for field_name, field_def in fields.items():
            # 必填字段
            if field_def.get("required"):
                rules.append(QualityRule(
                    name=f"{model_name}.{field_name}.required",
                    rule_type=QualityRuleType.COMPLETENESS,
                    severity=QualitySeverity.ERROR,
                    model_name=model_name,
                    field=field_name,
                    description=f"字段 {field_name} 必填",
                ))

            # 唯一字段
            if field_def.get("unique"):
                rules.append(QualityRule(
                    name=f"{model_name}.{field_name}.unique",
                    rule_type=QualityRuleType.UNIQUENESS,
                    severity=QualitySeverity.ERROR,
                    model_name=model_name,
                    field=field_name,
                    description=f"字段 {field_name} 必须唯一",
                ))

            # 格式校验
            fmt = field_def.get("format")
            if fmt:
                rules.append(QualityRule(
                    name=f"{model_name}.{field_name}.format",
                    rule_type=QualityRuleType.ACCURACY,
                    severity=QualitySeverity.WARNING,
                    model_name=model_name,
                    field=field_name,
                    description=f"字段 {field_name} 格式校验 ({fmt})",
                ))

            # 范围校验
            if "min" in field_def or "max" in field_def:
                rules.append(QualityRule(
                    name=f"{model_name}.{field_name}.range",
                    rule_type=QualityRuleType.ACCURACY,
                    severity=QualitySeverity.WARNING,
                    model_name=model_name,
                    field=field_name,
                    description=f"字段 {field_name} 范围校验",
                ))

        return rules

    # ---- 执行检查 ----

    def check_model(
        self,
        model_name: str,
        records: List[Dict[str, Any]],
        model_class: Optional[type] = None,
        custom_rules: Optional[List[QualityRule]] = None,
    ) -> QualityCheckResult:
        """
        对模型数据执行质量检查。

        Args:
            model_name: 模型名称
            records: 数据记录列表
            model_class: 模型类（用于自动生成规则）
            custom_rules: 自定义规则

        Returns:
            检查结果
        """
        start_time = time.time()
        result = QualityCheckResult(
            model_name=model_name,
            total_records=len(records),
        )

        # 收集所有规则
        all_rules = list(custom_rules or [])

        # 从已注册的规则中筛选
        all_rules.extend(r for r in self._rules if r.model_name == model_name)

        # 自动生成规则
        if model_class:
            auto_rules = self.auto_generate_rules(model_class)
            all_rules.extend(auto_rules)

        result.rules_checked = len(all_rules)

        # 执行检查
        for rule in all_rules:
            issues = self._execute_rule(rule, records)
            result.issues.extend(issues)

        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    def _execute_rule(
        self,
        rule: QualityRule,
        records: List[Dict[str, Any]],
    ) -> List[QualityIssue]:
        """执行单条规则"""
        issues: List[QualityIssue] = []

        # 自定义检查函数
        if rule.check_func:
            for record in records:
                try:
                    record_issues = rule.check_func(record)
                    for issue in record_issues:
                        issue.model_name = rule.model_name
                        if not issue.severity:
                            issue.severity = rule.severity
                    issues.extend(record_issues)
                except Exception as e:
                    issues.append(QualityIssue(
                        rule_type=rule.rule_type,
                        severity=QualitySeverity.ERROR,
                        model_name=rule.model_name,
                        field=rule.field,
                        message=f"检查规则 {rule.name} 执行失败: {e}",
                    ))
            return issues

        # 内置检查
        if rule.rule_type == QualityRuleType.COMPLETENESS:
            issues.extend(self._check_required(rule, records))
        elif rule.rule_type == QualityRuleType.UNIQUENESS:
            issues.extend(self._check_unique(rule, records))
        elif rule.rule_type == QualityRuleType.ACCURACY:
            issues.extend(self._check_format(rule, records))
            issues.extend(self._check_range(rule, records))

        return issues

    # ---- 内置检查实现 ----

    def _check_required(
        self,
        rule: QualityRule,
        records: List[Dict[str, Any]],
    ) -> List[QualityIssue]:
        """完整性检查：必填字段"""
        issues = []
        field = rule.field
        if not field:
            return issues

        for i, record in enumerate(records):
            value = record.get(field)
            if value is None or value == "" or (isinstance(value, list) and len(value) == 0):
                pk = record.get("id", i)
                issues.append(QualityIssue(
                    rule_type=QualityRuleType.COMPLETENESS,
                    severity=rule.severity,
                    model_name=rule.model_name,
                    field=field,
                    record_id=pk,
                    message=f"必填字段 '{field}' 为空",
                ))
        return issues

    def _check_unique(
        self,
        rule: QualityRule,
        records: List[Dict[str, Any]],
    ) -> List[QualityIssue]:
        """唯一性检查"""
        issues = []
        field = rule.field
        if not field:
            return issues

        seen: Dict[Any, List[Any]] = {}
        for record in records:
            value = record.get(field)
            if value is not None:
                pk = record.get("id")
                if value not in seen:
                    seen[value] = []
                seen[value].append(pk)

        for value, pks in seen.items():
            if len(pks) > 1:
                issues.append(QualityIssue(
                    rule_type=QualityRuleType.UNIQUENESS,
                    severity=rule.severity,
                    model_name=rule.model_name,
                    field=field,
                    record_id=pks[0],
                    message=f"字段 '{field}' 值 '{value}' 重复（{len(pks)}条记录）",
                    details={"duplicate_count": len(pks), "record_ids": [str(p) for p in pks]},
                ))
        return issues

    def _check_format(
        self,
        rule: QualityRule,
        records: List[Dict[str, Any]],
    ) -> List[QualityIssue]:
        """准确性检查：格式校验"""
        issues = []
        field = rule.field
        if not field:
            return issues

        # 检查是否有 format 定义（通过 details 或 description 推断）
        fmt_pattern = None
        if "format" in rule.description:
            # 从描述中提取格式（简化实现）
            if "email" in rule.description.lower():
                fmt_pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
            elif "phone" in rule.description.lower() or "phone" in rule.name.lower():
                fmt_pattern = r"^1[3-9]\d{9}$"
            elif "url" in rule.description.lower():
                fmt_pattern = r"^https?://.+"

        if not fmt_pattern:
            return issues

        for i, record in enumerate(records):
            value = record.get(field)
            if value is not None and value != "":
                if not re.match(fmt_pattern, str(value)):
                    pk = record.get("id", i)
                    issues.append(QualityIssue(
                        rule_type=QualityRuleType.ACCURACY,
                        severity=rule.severity,
                        model_name=rule.model_name,
                        field=field,
                        record_id=pk,
                        message=f"字段 '{field}' 格式不正确: '{value}'",
                    ))
        return issues

    def _check_range(
        self,
        rule: QualityRule,
        records: List[Dict[str, Any]],
    ) -> List[QualityIssue]:
        """准确性检查：范围校验"""
        # 简化实现：此处不做通用范围检查
        return []

    def _check_referential(
        self,
        rule: QualityRule,
        records: List[Dict[str, Any]],
        ref_records: Optional[List[Dict[str, Any]]] = None,
        ref_field: str = "id",
    ) -> List[QualityIssue]:
        """一致性检查：引用完整性"""
        issues = []
        field = rule.field
        if not field or ref_records is None:
            return issues

        ref_values = set(r.get(ref_field) for r in ref_records if r.get(ref_field) is not None)

        for i, record in enumerate(records):
            value = record.get(field)
            if value is not None and value not in ref_values:
                pk = record.get("id", i)
                issues.append(QualityIssue(
                    rule_type=QualityRuleType.CONSISTENCY,
                    severity=rule.severity,
                    model_name=rule.model_name,
                    field=field,
                    record_id=pk,
                    message=f"引用 '{field}'={value} 不存在于引用表中",
                ))
        return issues

    def _check_timeliness(
        self,
        rule: QualityRule,
        records: List[Dict[str, Any]],
        max_age_seconds: float = 86400,
    ) -> List[QualityIssue]:
        """时效性检查"""
        issues = []
        field = rule.field or "updated_at"
        now = time.time()

        for i, record in enumerate(records):
            ts = record.get(field)
            if ts and isinstance(ts, (int, float)):
                age = now - ts
                if age > max_age_seconds:
                    pk = record.get("id", i)
                    issues.append(QualityIssue(
                        rule_type=QualityRuleType.TIMELINESS,
                        severity=rule.severity,
                        model_name=rule.model_name,
                        field=field,
                        record_id=pk,
                        message=f"数据已过期（{age/3600:.1f}小时未更新）",
                        details={"age_hours": round(age / 3600, 2)},
                    ))
        return issues

    # ---- 批量检查 ----

    def check_all(
        self,
        models_data: Dict[str, List[Dict[str, Any]]],
        model_classes: Optional[Dict[str, type]] = None,
    ) -> Dict[str, QualityCheckResult]:
        """
        批量检查多个模型。

        Args:
            models_data: {model_name: records} 字典
            model_classes: {model_name: model_class} 字典

        Returns:
            {model_name: check_result} 字典
        """
        results = {}
        for model_name, records in models_data.items():
            model_class = model_classes.get(model_name) if model_classes else None
            results[model_name] = self.check_model(
                model_name=model_name,
                records=records,
                model_class=model_class,
            )
        return results
