"""
云汐 M9 数据水晶 - 数据校验阶段

P3 优化：数据采集管道 + 连接器生态
支持 Schema 校验、必填字段检查、范围检查、正则匹配
"""

from __future__ import annotations

import re
import logging
from typing import Iterator, Dict, Any, Optional, List

from ..base import PipelineStage, StageRegistry

logger = logging.getLogger(__name__)


@StageRegistry.register
class ValidateStage(PipelineStage):
    """
    数据校验阶段

    功能：
    - Schema 校验
    - 必填字段检查
    - 范围检查
    - 正则匹配
    - 数据类型校验
    """

    name = "validate"
    description = "数据校验阶段，支持 Schema 校验、必填检查、正则匹配"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._validation_errors: List[Dict[str, Any]] = []
        self._error_output = self._config.get("error_output", "skip")  # skip / flag / abort / collect

    @property
    def validation_errors(self) -> List[Dict[str, Any]]:
        """获取校验错误列表"""
        return self._validation_errors

    def process(self, data: Iterator[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        """执行数据校验"""
        self._validation_errors = []

        records_in = 0
        records_out = 0

        schema = self._config.get("schema", {})
        required_fields = self._config.get("required_fields", [])
        field_rules = self._config.get("field_rules", {})

        for record in data:
            records_in += 1
            errors = []

            # 1. 必填字段检查
            if required_fields:
                for field in required_fields:
                    if field not in record or record[field] is None or record[field] == "":
                        errors.append({
                            "field": field,
                            "rule": "required",
                            "message": f"字段 '{field}' 是必填项",
                        })

            # 2. Schema 校验
            if schema:
                schema_errors = self._validate_schema(record, schema)
                errors.extend(schema_errors)

            # 3. 字段规则校验
            if field_rules:
                rule_errors = self._validate_field_rules(record, field_rules)
                errors.extend(rule_errors)

            if errors:
                self._record_error()

                if self._error_output == "skip":
                    # 跳过无效记录
                    continue
                elif self._error_output == "flag":
                    # 标记错误但继续传递
                    record["_validation_errors"] = errors
                    record["_is_valid"] = False
                    records_out += 1
                    yield record
                elif self._error_output == "abort":
                    # 中止执行
                    self._validation_errors.append({"record": record, "errors": errors})
                    raise ValueError(f"数据校验失败: {errors[0]['message']}")
                elif self._error_output == "collect":
                    # 收集错误但继续
                    self._validation_errors.append({"record": record, "errors": errors})
                    continue
            else:
                if self._error_output == "flag":
                    record["_is_valid"] = True
                    record["_validation_errors"] = []
                records_out += 1
                yield record

        self._record_in(records_in)
        self._record_out(records_out)

    def _validate_schema(self, record: Dict[str, Any], schema: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Schema 校验"""
        errors = []
        fields_schema = schema.get("fields", {})

        for field_name, field_schema in fields_schema.items():
            value = record.get(field_name)

            # 类型校验
            expected_type = field_schema.get("type")
            if expected_type and value is not None and value != "":
                if not self._check_type(value, expected_type):
                    errors.append({
                        "field": field_name,
                        "rule": "type",
                        "message": f"字段 '{field_name}' 类型错误，期望 {expected_type}",
                        "expected": expected_type,
                        "actual": type(value).__name__,
                    })

            # 枚举校验
            enum_values = field_schema.get("enum")
            if enum_values and value is not None and value != "":
                if value not in enum_values:
                    errors.append({
                        "field": field_name,
                        "rule": "enum",
                        "message": f"字段 '{field_name}' 值不在允许范围内",
                        "allowed": enum_values,
                        "actual": value,
                    })

        return errors

    def _validate_field_rules(self, record: Dict[str, Any],
                              field_rules: Dict[str, Any]) -> List[Dict[str, Any]]:
        """字段规则校验"""
        errors = []

        for field_name, rules in field_rules.items():
            value = record.get(field_name)

            if value is None or value == "":
                # 空值不做规则校验（由 required 控制）
                continue

            # 范围检查
            if "min" in rules:
                try:
                    if float(value) < float(rules["min"]):
                        errors.append({
                            "field": field_name,
                            "rule": "min",
                            "message": f"字段 '{field_name}' 值小于最小值 {rules['min']}",
                        })
                except (ValueError, TypeError):
                    pass

            if "max" in rules:
                try:
                    if float(value) > float(rules["max"]):
                        errors.append({
                            "field": field_name,
                            "rule": "max",
                            "message": f"字段 '{field_name}' 值大于最大值 {rules['max']}",
                        })
                except (ValueError, TypeError):
                    pass

            # 长度检查
            if "min_length" in rules:
                if len(str(value)) < rules["min_length"]:
                    errors.append({
                        "field": field_name,
                        "rule": "min_length",
                        "message": f"字段 '{field_name}' 长度小于最小值 {rules['min_length']}",
                    })

            if "max_length" in rules:
                if len(str(value)) > rules["max_length"]:
                    errors.append({
                        "field": field_name,
                        "rule": "max_length",
                        "message": f"字段 '{field_name}' 长度大于最大值 {rules['max_length']}",
                    })

            # 正则匹配
            if "pattern" in rules:
                if not re.match(rules["pattern"], str(value)):
                    errors.append({
                        "field": field_name,
                        "rule": "pattern",
                        "message": f"字段 '{field_name}' 不匹配正则表达式",
                        "pattern": rules["pattern"],
                    })

            # 自定义校验函数
            if "validator" in rules and callable(rules["validator"]):
                try:
                    if not rules["validator"](value):
                        errors.append({
                            "field": field_name,
                            "rule": "custom",
                            "message": f"字段 '{field_name}' 自定义校验失败",
                        })
                except Exception:
                    errors.append({
                        "field": field_name,
                        "rule": "custom",
                        "message": f"字段 '{field_name}' 自定义校验异常",
                    })

        return errors

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """检查值的类型"""
        type_map = {
            "string": str,
            "str": str,
            "integer": int,
            "int": int,
            "float": float,
            "number": (int, float),
            "boolean": bool,
            "bool": bool,
            "list": list,
            "array": list,
            "dict": dict,
            "object": dict,
        }

        expected = type_map.get(expected_type.lower())
        if expected is None:
            return True

        return isinstance(value, expected)

    def validate_config(self) -> bool:
        """验证配置"""
        valid_keys = {
            "schema", "required_fields", "field_rules", "error_output",
        }

        error_outputs = {"skip", "flag", "abort", "collect"}
        if self._config.get("error_output", "skip") not in error_outputs:
            return False

        if "required_fields" in self._config:
            if not isinstance(self._config["required_fields"], list):
                return False

        if "schema" in self._config:
            if not isinstance(self._config["schema"], dict):
                return False

        if "field_rules" in self._config:
            if not isinstance(self._config["field_rules"], dict):
                return False

        return True
