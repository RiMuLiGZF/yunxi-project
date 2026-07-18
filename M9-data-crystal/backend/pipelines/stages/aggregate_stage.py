"""
云汐 M9 数据水晶 - 数据聚合阶段

P3 优化：数据采集管道 + 连接器生态
支持分组统计、求和/计数/平均值/最大最小、时间窗口聚合
"""

from __future__ import annotations

import logging
from typing import Iterator, Dict, Any, Optional, List
from collections import defaultdict
from datetime import datetime, timedelta

from ..base import PipelineStage, StageRegistry

logger = logging.getLogger(__name__)


@StageRegistry.register
class AggregateStage(PipelineStage):
    """
    数据聚合阶段

    功能：
    - 分组统计
    - 求和/计数/平均值/最大最小
    - 时间窗口聚合
    """

    name = "aggregate"
    description = "数据聚合阶段，支持分组统计、聚合函数、时间窗口"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    def process(self, data: Iterator[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        """执行数据聚合"""
        # 聚合需要收集所有数据
        all_data = list(data)
        records_in = len(all_data)

        try:
            result = self._aggregate(all_data)
            records_out = len(result)

            self._record_in(records_in)
            self._record_out(records_out)

            yield from result

        except Exception as e:
            self._record_error()
            logger.error(f"数据聚合出错: {e}")
            raise

    def _aggregate(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """执行聚合"""
        group_by = self._config.get("group_by", [])
        aggregations = self._config.get("aggregations", [])
        time_window = self._config.get("time_window", {})

        if not aggregations:
            return data

        # 时间窗口处理
        if time_window and time_window.get("enabled", False):
            data = self._add_time_window(data, time_window)
            # 添加时间窗口到分组字段
            window_field = time_window.get("window_field", "_time_window")
            if window_field not in group_by:
                group_by = list(group_by) + [window_field]

        # 分组
        groups = defaultdict(list)
        for record in data:
            if group_by:
                key = tuple(str(record.get(f, "")) for f in group_by)
            else:
                key = ("__all__",)
            groups[key].append(record)

        # 聚合
        results = []
        for key, group_data in groups.items():
            result_record = {}

            # 添加分组字段
            if group_by:
                for i, field in enumerate(group_by):
                    result_record[field] = group_data[0].get(field, key[i]) if group_data else key[i]

            # 执行聚合函数
            for agg in aggregations:
                field = agg.get("field", "")
                function = agg.get("function", "count")
                alias = agg.get("alias", f"{function}_{field}")

                values = [r.get(field) for r in group_data if r.get(field) is not None]

                result_record[alias] = self._apply_aggregation(function, values, group_data)

            results.append(result_record)

        return results

    def _apply_aggregation(self, function: str, values: List[Any],
                           group_data: List[Dict[str, Any]]) -> Any:
        """应用聚合函数"""
        func = function.lower()

        if func == "count":
            return len(group_data)

        if func == "count_distinct":
            return len(set(str(v) for v in values))

        if not values:
            return None

        numeric_values = []
        for v in values:
            try:
                numeric_values.append(float(v))
            except (ValueError, TypeError):
                pass

        if func == "sum":
            return sum(numeric_values) if numeric_values else 0

        if func == "avg" or func == "average":
            return sum(numeric_values) / len(numeric_values) if numeric_values else 0

        if func == "min":
            return min(numeric_values) if numeric_values else None

        if func == "max":
            return max(numeric_values) if numeric_values else None

        if func == "first":
            return values[0] if values else None

        if func == "last":
            return values[-1] if values else None

        if func == "concat":
            separator = self._config.get("concat_separator", ", ")
            return separator.join(str(v) for v in values)

        if func == "median":
            if not numeric_values:
                return None
            sorted_vals = sorted(numeric_values)
            n = len(sorted_vals)
            if n % 2 == 0:
                return (sorted_vals[n//2 - 1] + sorted_vals[n//2]) / 2
            else:
                return sorted_vals[n//2]

        return None

    def _add_time_window(self, data: List[Dict[str, Any]],
                         time_window: Dict[str, Any]) -> List[Dict[str, Any]]:
        """添加时间窗口字段"""
        time_field = time_window.get("time_field", "timestamp")
        window_size = time_window.get("window_size", "1h")  # 1h, 1d, 1w
        window_field = time_window.get("window_field", "_time_window")

        # 解析窗口大小
        window_seconds = self._parse_window_size(window_size)

        result = []
        for record in data:
            record = dict(record)
            time_val = record.get(time_field)

            if time_val:
                try:
                    if isinstance(time_val, str):
                        dt = datetime.fromisoformat(time_val)
                    elif isinstance(time_val, datetime):
                        dt = time_val
                    else:
                        dt = datetime.fromtimestamp(float(time_val))

                    # 计算时间窗口
                    epoch = datetime(1970, 1, 1)
                    delta = dt - epoch
                    window_start = epoch + timedelta(
                        seconds=(delta.total_seconds() // window_seconds) * window_seconds
                    )
                    record[window_field] = window_start.isoformat()
                except (ValueError, TypeError):
                    record[window_field] = str(time_val)
            else:
                record[window_field] = "unknown"

            result.append(record)

        return result

    def _parse_window_size(self, window_size: str) -> int:
        """解析窗口大小为秒数"""
        import re
        match = re.match(r'(\d+)([smhdw])', window_size.lower())
        if not match:
            return 3600  # 默认 1 小时

        value = int(match.group(1))
        unit = match.group(2)

        multipliers = {
            's': 1,
            'm': 60,
            'h': 3600,
            'd': 86400,
            'w': 604800,
        }
        return value * multipliers.get(unit, 3600)

    def validate_config(self) -> bool:
        """验证配置"""
        if "aggregations" in self._config:
            if not isinstance(self._config["aggregations"], list):
                return False

            valid_funcs = {
                "count", "count_distinct", "sum", "avg", "average",
                "min", "max", "first", "last", "concat", "median",
            }
            for agg in self._config["aggregations"]:
                if not isinstance(agg, dict):
                    return False
                if agg.get("function", "").lower() not in valid_funcs:
                    return False

        if "group_by" in self._config:
            if not isinstance(self._config["group_by"], list):
                return False

        return True
