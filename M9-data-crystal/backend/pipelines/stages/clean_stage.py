"""
云汐 M9 数据水晶 - 数据清洗阶段

P3 优化：数据采集管道 + 连接器生态
支持去除空白、统一日期格式、统一编码、异常值处理
"""

from __future__ import annotations

import re
import logging
from typing import Iterator, Dict, Any, Optional
from datetime import datetime, date

from ..base import PipelineStage, StageRegistry

logger = logging.getLogger(__name__)


@StageRegistry.register
class CleanStage(PipelineStage):
    """
    数据清洗阶段

    功能：
    - 去除空白字符
    - 统一日期格式
    - 统一编码
    - 异常值处理
    - HTML 标签清除
    - 特殊字符过滤
    """

    name = "clean"
    description = "数据清洗阶段，支持去空白、统一日期格式、异常值处理"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    def process(self, data: Iterator[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        """执行数据清洗"""
        records_in = 0
        records_out = 0

        for record in data:
            records_in += 1
            try:
                result = self._clean_record(record)
                records_out += 1
                yield result
            except Exception as e:
                self._record_error()
                logger.warning(f"数据清洗出错: {e}")
                continue

        self._record_in(records_in)
        self._record_out(records_out)

    def _clean_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """清洗单条记录"""
        result = {}

        for key, value in record.items():
            # 字段名清洗
            clean_key = self._clean_field_name(key)

            # 字段值清洗
            clean_value = self._clean_value(clean_key, value)

            result[clean_key] = clean_value

        return result

    def _clean_field_name(self, name: str) -> str:
        """清洗字段名"""
        if not isinstance(name, str):
            return name

        # 去除首尾空白
        name = name.strip()

        # 转换命名风格
        naming_style = self._config.get("naming_style", "")
        if naming_style == "snake_case":
            name = self._to_snake_case(name)
        elif naming_style == "camel_case":
            name = self._to_camel_case(name)
        elif naming_style == "pascal_case":
            name = self._to_pascal_case(name)

        return name

    def _to_snake_case(self, name: str) -> str:
        """转换为 snake_case"""
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower().replace(' ', '_')

    def _to_camel_case(self, name: str) -> str:
        """转换为 camelCase"""
        words = re.split(r'[_\s-]', name.lower())
        return words[0] + ''.join(w.capitalize() for w in words[1:])

    def _to_pascal_case(self, name: str) -> str:
        """转换为 PascalCase"""
        words = re.split(r'[_\s-]', name.lower())
        return ''.join(w.capitalize() for w in words)

    def _clean_value(self, field: str, value: Any) -> Any:
        """清洗字段值"""
        if value is None:
            return None

        # 字符串处理
        if isinstance(value, str):
            return self._clean_string(field, value)

        # 数字处理
        if isinstance(value, (int, float)):
            return self._clean_number(field, value)

        # 日期处理
        if isinstance(value, (datetime, date)):
            return self._clean_date(field, value)

        return value

    def _clean_string(self, field: str, value: str) -> str:
        """清洗字符串"""
        # 去除首尾空白
        if self._config.get("strip_whitespace", True):
            value = value.strip()

        # 去除多余空白字符
        if self._config.get("collapse_whitespace", False):
            value = re.sub(r'\s+', ' ', value)

        # 去除不可见字符
        if self._config.get("remove_invisible_chars", False):
            value = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)

        # 去除 HTML 标签
        if self._config.get("strip_html", False):
            value = re.sub(r'<[^>]+>', '', value)

        # 大小写统一
        case_mode = self._config.get("case_mode", "")
        if case_mode == "lower":
            value = value.lower()
        elif case_mode == "upper":
            value = value.upper()
        elif case_mode == "title":
            value = value.title()

        # 空字符串转 None
        if self._config.get("empty_to_null", True) and value == "":
            return None

        return value

    def _clean_number(self, field: str, value: Any) -> Any:
        """清洗数字"""
        # 异常值处理
        outlier_mode = self._config.get("outlier_mode", "keep")  # keep / replace / remove
        outlier_config = self._config.get("outlier_fields", {})

        if field in outlier_config:
            config = outlier_config[field]
            min_val = config.get("min")
            max_val = config.get("max")

            if min_val is not None and value < min_val:
                if outlier_mode == "replace":
                    return config.get("replace_value", min_val)
                elif outlier_mode == "remove":
                    return None
            if max_val is not None and value > max_val:
                if outlier_mode == "replace":
                    return config.get("replace_value", max_val)
                elif outlier_mode == "remove":
                    return None

        return value

    def _clean_date(self, field: str, value: Any) -> Any:
        """清洗日期"""
        date_format = self._config.get("date_format", "")
        if date_format and isinstance(value, (datetime, date)):
            if isinstance(value, datetime):
                return value.strftime(date_format)
            else:
                return value.strftime(date_format)

        return value

    def validate_config(self) -> bool:
        """验证配置"""
        valid_keys = {
            "strip_whitespace", "collapse_whitespace", "remove_invisible_chars",
            "strip_html", "case_mode", "empty_to_null",
            "naming_style", "date_format",
            "outlier_mode", "outlier_fields",
        }

        case_modes = {"", "lower", "upper", "title"}
        if self._config.get("case_mode", "") not in case_modes:
            return False

        naming_styles = {"", "snake_case", "camel_case", "pascal_case"}
        if self._config.get("naming_style", "") not in naming_styles:
            return False

        outlier_modes = {"keep", "replace", "remove"}
        if self._config.get("outlier_mode", "keep") not in outlier_modes:
            return False

        return True
