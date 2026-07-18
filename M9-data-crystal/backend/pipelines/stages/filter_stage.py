"""
云汐 M9 数据水晶 - 数据过滤阶段

P3 优化：数据采集管道 + 连接器生态
支持条件表达式过滤、空值过滤、去重
"""

from __future__ import annotations

import re
import logging
from typing import Iterator, List, Dict, Any, Optional, Callable

from ..base import PipelineStage, StageRegistry

logger = logging.getLogger(__name__)


@StageRegistry.register
class FilterStage(PipelineStage):
    """
    数据过滤阶段

    功能：
    - 条件表达式过滤
    - 空值过滤
    - 去重
    - 自定义过滤函数
    """

    name = "filter"
    description = "数据过滤阶段，支持条件过滤、空值过滤、去重"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._filter_func: Optional[Callable[[Dict[str, Any]], bool]] = None
        self._seen_keys: set = set()
        self._build_filter()

    def _build_filter(self) -> None:
        """构建过滤函数"""
        filter_type = self._config.get("type", "condition")  # condition / null / duplicate / custom

        if filter_type == "custom":
            self._filter_func = self._config.get("filter_func")
            return

        if filter_type == "null":
            null_fields = self._config.get("fields", [])
            filter_mode = self._config.get("mode", "exclude")  # exclude / include

            def null_filter(record: Dict[str, Any]) -> bool:
                if null_fields:
                    for field in null_fields:
                        val = record.get(field)
                        is_null = val is None or val == ""
                        if filter_mode == "exclude" and is_null:
                            return False
                        if filter_mode == "include" and not is_null:
                            return False
                    return True
                else:
                    # 检查所有字段
                    all_null = all(v is None or v == "" for v in record.values())
                    return not all_null if filter_mode == "exclude" else all_null

            self._filter_func = null_filter
            return

        if filter_type == "duplicate":
            dedupe_fields = self._config.get("fields", [])
            self._seen_keys = set()

            def dedupe_filter(record: Dict[str, Any]) -> bool:
                if dedupe_fields:
                    key = tuple(str(record.get(f, "")) for f in dedupe_fields)
                else:
                    # 使用所有字段的哈希
                    key = hash(frozenset(
                        (k, str(v)) for k, v in sorted(record.items())
                    ))
                if key in self._seen_keys:
                    return False
                self._seen_keys.add(key)
                return True

            self._filter_func = dedupe_filter
            return

        # 默认：条件过滤
        conditions = self._config.get("conditions", [])
        logic = self._config.get("logic", "and")  # and / or

        if not conditions:
            # 无过滤条件，全部通过
            self._filter_func = lambda r: True
            return

        def condition_filter(record: Dict[str, Any]) -> bool:
            results = []
            for cond in conditions:
                field = cond.get("field", "")
                operator = cond.get("operator", "eq")
                value = cond.get("value")
                results.append(self._evaluate_condition(record, field, operator, value))

            if logic == "and":
                return all(results)
            else:
                return any(results)

        self._filter_func = condition_filter

    def _evaluate_condition(self, record: Dict[str, Any], field: str,
                            operator: str, value: Any) -> bool:
        """评估单个条件"""
        record_value = record.get(field)

        operators = {
            "eq": lambda a, b: a == b,
            "neq": lambda a, b: a != b,
            "gt": lambda a, b: a is not None and b is not None and a > b,
            "gte": lambda a, b: a is not None and b is not None and a >= b,
            "lt": lambda a, b: a is not None and b is not None and a < b,
            "lte": lambda a, b: a is not None and b is not None and a <= b,
            "contains": lambda a, b: b in str(a) if a is not None else False,
            "not_contains": lambda a, b: b not in str(a) if a is not None else True,
            "startswith": lambda a, b: str(a).startswith(str(b)) if a is not None else False,
            "endswith": lambda a, b: str(a).endswith(str(b)) if a is not None else False,
            "in": lambda a, b: a in b if isinstance(b, (list, tuple, set)) else False,
            "not_in": lambda a, b: a not in b if isinstance(b, (list, tuple, set)) else True,
            "is_null": lambda a, b: a is None or a == "",
            "not_null": lambda a, b: a is not None and a != "",
            "regex": lambda a, b: bool(re.search(str(b), str(a))) if a is not None else False,
            "empty": lambda a, b: a is None or a == "" or a == [] or a == {},
            "not_empty": lambda a, b: a is not None and a != "" and a != [] and a != {},
        }

        func = operators.get(operator)
        if func is None:
            return True

        try:
            return func(record_value, value)
        except Exception:
            return False

    def process(self, data: Iterator[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        """执行过滤"""
        if self._filter_func is None:
            yield from data
            return

        records_in = 0
        records_out = 0

        for record in data:
            records_in += 1
            try:
                if self._filter_func(record):
                    records_out += 1
                    yield record
            except Exception as e:
                self._record_error()
                logger.warning(f"过滤出错: {e}")
                continue

        self._record_in(records_in)
        self._record_out(records_out)

    def validate_config(self) -> bool:
        """验证配置"""
        filter_type = self._config.get("type", "condition")
        valid_types = {"condition", "null", "duplicate", "custom"}

        if filter_type not in valid_types:
            return False

        if filter_type == "custom":
            if not callable(self._config.get("filter_func")):
                return False

        if filter_type == "condition":
            conditions = self._config.get("conditions", [])
            if not isinstance(conditions, list):
                return False
            valid_ops = {
                "eq", "neq", "gt", "gte", "lt", "lte",
                "contains", "not_contains", "startswith", "endswith",
                "in", "not_in", "is_null", "not_null",
                "regex", "empty", "not_empty",
            }
            for cond in conditions:
                if "field" not in cond or "operator" not in cond:
                    return False
                if cond["operator"] not in valid_ops:
                    return False

        return True
