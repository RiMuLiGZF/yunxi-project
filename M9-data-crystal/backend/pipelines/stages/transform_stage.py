"""
云汐 M9 数据水晶 - 字段转换阶段

P3 优化：数据采集管道 + 连接器生态
支持字段重命名、类型转换、计算字段、字段删除/保留
"""

from __future__ import annotations

import re
import logging
from typing import Iterator, List, Dict, Any, Optional
from datetime import datetime

from ..base import PipelineStage, StageRegistry

logger = logging.getLogger(__name__)


@StageRegistry.register
class TransformStage(PipelineStage):
    """
    字段转换阶段

    功能：
    - 字段重命名
    - 类型转换
    - 计算字段
    - 字段删除/保留
    """

    name = "transform"
    description = "字段转换阶段，支持重命名、类型转换、计算字段"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    def process(self, data: Iterator[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        """执行字段转换"""
        records_in = 0
        records_out = 0

        for record in data:
            records_in += 1
            try:
                result = self._transform_record(record)
                records_out += 1
                yield result
            except Exception as e:
                self._record_error()
                logger.warning(f"字段转换出错: {e}")
                continue

        self._record_in(records_in)
        self._record_out(records_out)

    def _transform_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """转换单条记录"""
        result = dict(record)

        # 1. 字段重命名
        rename_map = self._config.get("rename", {})
        if rename_map:
            for old_name, new_name in rename_map.items():
                if old_name in result:
                    result[new_name] = result.pop(old_name)

        # 2. 类型转换
        type_map = self._config.get("type_map", {})
        if type_map:
            for field, target_type in type_map.items():
                if field in result:
                    result[field] = self._convert_type(result[field], target_type)

        # 3. 计算字段
        computed_fields = self._config.get("computed_fields", {})
        if computed_fields:
            for field_name, expression in computed_fields.items():
                result[field_name] = self._compute_field(result, expression)

        # 4. 字段保留（白名单）
        keep_fields = self._config.get("keep_fields", [])
        if keep_fields:
            result = {k: v for k, v in result.items() if k in keep_fields}

        # 5. 字段删除（黑名单）
        drop_fields = self._config.get("drop_fields", [])
        if drop_fields:
            for field in drop_fields:
                result.pop(field, None)

        # 6. 字段默认值
        default_values = self._config.get("default_values", {})
        if default_values:
            for field, default_val in default_values.items():
                if field not in result or result[field] is None or result[field] == "":
                    result[field] = default_val

        return result

    def _convert_type(self, value: Any, target_type: str) -> Any:
        """类型转换"""
        if value is None or value == "":
            return None

        type_map = {
            "str": str,
            "string": str,
            "int": int,
            "integer": int,
            "float": float,
            "double": float,
            "bool": lambda v: str(v).lower() in ("true", "1", "yes", "on"),
            "boolean": lambda v: str(v).lower() in ("true", "1", "yes", "on"),
            "date": lambda v: datetime.fromisoformat(str(v)).date() if isinstance(v, str) else v,
            "datetime": lambda v: datetime.fromisoformat(str(v)) if isinstance(v, str) else v,
            "list": lambda v: v if isinstance(v, list) else [v],
        }

        converter = type_map.get(target_type.lower())
        if converter:
            try:
                return converter(value)
            except (ValueError, TypeError):
                return value

        return value

    def _compute_field(self, record: Dict[str, Any], expression: Any) -> Any:
        """计算字段值

        expression 支持：
        - 字符串模板："Hello {name}"
        - 数学运算：{"operation": "add", "fields": ["a", "b"]}
        - 直接引用字段："field_name"
        - 常量值：任意非字符串/字典值
        """
        if isinstance(expression, str):
            # 检查是否是模板字符串
            if "{" in expression and "}" in expression:
                try:
                    return expression.format(**record)
                except (KeyError, ValueError):
                    return expression
            # 检查是否是字段引用
            if expression in record:
                return record[expression]
            return expression

        if isinstance(expression, dict) and "operation" in expression:
            op = expression["operation"]
            fields = expression.get("fields", [])
            values = [record.get(f, 0) for f in fields]

            operations = {
                "add": lambda vs: sum(v for v in vs if v is not None),
                "subtract": lambda vs: vs[0] - vs[1] if len(vs) >= 2 else vs[0] if vs else 0,
                "multiply": lambda vs: (lambda r=1: [r := r * v for v in vs if v is not None][-1])(),
                "divide": lambda vs: vs[0] / vs[1] if len(vs) >= 2 and vs[1] not in (0, None) else 0,
                "concat": lambda vs: "".join(str(v) for v in vs if v is not None),
                "upper": lambda vs: str(vs[0]).upper() if vs else "",
                "lower": lambda vs: str(vs[0]).lower() if vs else "",
                "length": lambda vs: len(str(vs[0])) if vs else 0,
                "trim": lambda vs: str(vs[0]).strip() if vs else "",
            }

            op_func = operations.get(op)
            if op_func:
                try:
                    return op_func(values)
                except Exception:
                    return None

        # 常量值
        return expression

    def validate_config(self) -> bool:
        """验证配置"""
        valid_keys = {
            "rename", "type_map", "computed_fields",
            "keep_fields", "drop_fields", "default_values",
        }
        config_keys = set(self._config.keys())
        if not config_keys.issubset(valid_keys) and config_keys:
            # 允许有额外配置（忽略）
            pass

        if "rename" in self._config and not isinstance(self._config["rename"], dict):
            return False

        if "type_map" in self._config and not isinstance(self._config["type_map"], dict):
            return False

        if "keep_fields" in self._config and not isinstance(self._config["keep_fields"], list):
            return False

        if "drop_fields" in self._config and not isinstance(self._config["drop_fields"], list):
            return False

        return True
