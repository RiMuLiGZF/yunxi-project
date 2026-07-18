"""
数据聚合查询服务（Query Service）
================================

提供跨模块数据查询、联表、聚合计算、分页查询、数据导出等能力。

核心能力：
- 跨模块数据查询
- 数据联表（JOIN）
- 聚合计算（count/sum/avg/group by）
- 分页查询
- 数据导出（JSON/CSV）
"""

from __future__ import annotations

import csv
import io
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..base import BaseRepository, PaginationResult, QueryFilter, OrderBy


# ============================================================
# 枚举定义
# ============================================================

class AggregateFunc(str, Enum):
    """聚合函数类型"""
    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


class JoinType(str, Enum):
    """连接类型"""
    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    FULL = "full"


class ExportFormat(str, Enum):
    """导出格式"""
    JSON = "json"
    CSV = "csv"


# ============================================================
# 数据类
# ============================================================

@dataclass
class AggregationQuery:
    """
    聚合查询定义。

    Attributes:
        model_name: 模型名称
        group_by: 分组字段列表
        aggregations: 聚合定义 {别名: (函数, 字段)}
        filters: 过滤条件
        having: HAVING 过滤（聚合后过滤）
        order_by: 排序
        limit: 限制条数
    """
    model_name: str
    group_by: List[str] = field(default_factory=list)
    aggregations: Dict[str, Tuple[AggregateFunc, str]] = field(default_factory=dict)
    filters: List[QueryFilter] = field(default_factory=list)
    having: List[Tuple[str, str, Any]] = field(default_factory=list)
    order_by: List[OrderBy] = field(default_factory=list)
    limit: Optional[int] = None


@dataclass
class AggregationResult:
    """聚合查询结果"""
    rows: List[Dict[str, Any]]
    total_groups: int
    execution_time_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rows": self.rows,
            "total_groups": self.total_groups,
            "execution_time_ms": round(self.execution_time_ms, 2),
        }


@dataclass
class JoinQuery:
    """
    联表查询定义。

    Attributes:
        primary_model: 主模型名称
        joins: 连接定义 [(join_type, target_model, left_key, right_key)]
        select_fields: 选择的字段列表 [(model, field, alias)]
        filters: 过滤条件 [(model, field, operator, value)]
        order_by: 排序 [(model, field, ascending)]
        page: 页码
        page_size: 每页大小
    """
    primary_model: str
    joins: List[Tuple[JoinType, str, str, str]] = field(default_factory=list)
    select_fields: List[Tuple[str, str, str]] = field(default_factory=list)
    filters: List[Tuple[str, str, str, Any]] = field(default_factory=list)
    order_by: List[Tuple[str, str, bool]] = field(default_factory=list)
    page: int = 1
    page_size: int = 20


# ============================================================
# 查询服务
# ============================================================

class QueryService:
    """
    数据聚合查询服务。

    提供跨模型查询、聚合计算、联表查询等高级查询能力。
    基于内存实现，适合中小规模数据。
    """

    def __init__(self, repositories: Optional[Dict[str, BaseRepository]] = None):
        """
        Args:
            repositories: {model_name: repository} 字典
        """
        self._repositories: Dict[str, BaseRepository] = repositories or {}

    def register_repository(self, name: str, repo: BaseRepository) -> None:
        """注册仓库"""
        self._repositories[name] = repo

    def get_repository(self, name: str) -> Optional[BaseRepository]:
        """获取仓库"""
        return self._repositories.get(name)

    # ---- 基础查询 ----

    def query(
        self,
        model_name: str,
        filters: Optional[List[QueryFilter]] = None,
        order_by: Optional[List[OrderBy]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PaginationResult:
        """
        分页查询。

        Args:
            model_name: 模型名称
            filters: 过滤条件
            order_by: 排序
            page: 页码
            page_size: 每页大小

        Returns:
            分页结果
        """
        repo = self._get_repo_or_raise(model_name)
        return repo._execute_paginated_query(
            filters=filters or [],
            order_by=order_by or [],
            page=page,
            page_size=page_size,
        )

    def find_one(
        self,
        model_name: str,
        filters: Optional[List[QueryFilter]] = None,
    ) -> Optional[Any]:
        """查询单条记录"""
        repo = self._get_repo_or_raise(model_name)
        results = repo._execute_query(
            filters=filters or [],
            order_by=[],
            limit=1,
            offset=0,
        )
        return results[0] if results else None

    # ---- 聚合查询 ----

    def aggregate(self, query: AggregationQuery) -> AggregationResult:
        """
        执行聚合查询。

        支持 count/sum/avg/min/max 聚合函数，
        支持 group by 分组和 having 过滤。
        """
        start_time = time.time()
        repo = self._get_repo_or_raise(query.model_name)

        # 获取所有数据
        all_data = repo._execute_query(
            filters=query.filters,
            order_by=[],
            limit=None,
            offset=None,
        )

        # 转换为字典
        rows = [
            item.to_dict() if hasattr(item, "to_dict") else item
            for item in all_data
        ]

        # 分组
        groups: Dict[Tuple, List[Dict[str, Any]]] = {}
        if query.group_by:
            for row in rows:
                key = tuple(row.get(f) for f in query.group_by)
                if key not in groups:
                    groups[key] = []
                groups[key].append(row)
        else:
            groups[()] = rows

        # 计算聚合
        result_rows = []
        for group_key, group_rows in groups.items():
            result_row: Dict[str, Any] = {}

            # 分组字段
            for i, field_name in enumerate(query.group_by):
                result_row[field_name] = group_key[i]

            # 聚合计算
            for alias, (func, field_name) in query.aggregations.items():
                values = [
                    r.get(field_name) for r in group_rows
                    if r.get(field_name) is not None
                ]

                if func == AggregateFunc.COUNT:
                    result_row[alias] = len(group_rows)
                elif func == AggregateFunc.SUM:
                    result_row[alias] = sum(v for v in values if isinstance(v, (int, float)))
                elif func == AggregateFunc.AVG:
                    nums = [v for v in values if isinstance(v, (int, float))]
                    result_row[alias] = sum(nums) / len(nums) if nums else 0
                elif func == AggregateFunc.MIN:
                    nums = [v for v in values if isinstance(v, (int, float))]
                    result_row[alias] = min(nums) if nums else None
                elif func == AggregateFunc.MAX:
                    nums = [v for v in values if isinstance(v, (int, float))]
                    result_row[alias] = max(nums) if nums else None

            result_rows.append(result_row)

        # HAVING 过滤
        if query.having:
            filtered = []
            for row in result_rows:
                match = True
                for field, op, value in query.having:
                    f = QueryFilter(field=field, operator=op, value=value)
                    if not f.matches(row):
                        match = False
                        break
                if match:
                    filtered.append(row)
            result_rows = filtered

        # 排序
        if query.order_by:
            for ob in reversed(query.order_by):
                result_rows.sort(
                    key=lambda x: (x.get(ob.field) is None, x.get(ob.field)),
                    reverse=not ob.ascending,
                )

        # LIMIT
        if query.limit:
            result_rows = result_rows[: query.limit]

        execution_time = (time.time() - start_time) * 1000

        return AggregationResult(
            rows=result_rows,
            total_groups=len(result_rows),
            execution_time_ms=execution_time,
        )

    # ---- 联表查询 ----

    def join_query(self, query: JoinQuery) -> Dict[str, Any]:
        """
        执行联表查询（内存实现）。

        支持 inner/left/right/full 连接，
        基于内存的嵌套循环实现。
        """
        start_time = time.time()

        primary_repo = self._get_repo_or_raise(query.primary_model)
        primary_data = [
            item.to_dict() if hasattr(item, "to_dict") else item
            for item in primary_repo.list_all()
        ]

        # 逐步连接
        result_data = [
            {f"{query.primary_model}.{k}": v for k, v in row.items()}
            for row in primary_data
        ]

        for join_type, target_model, left_key, right_key in query.joins:
            target_repo = self._get_repo_or_raise(target_model)
            target_data = [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in target_repo.list_all()
            ]

            # 构建目标数据索引
            target_index: Dict[Any, List[Dict[str, Any]]] = {}
            for row in target_data:
                key = row.get(right_key)
                if key not in target_index:
                    target_index[key] = []
                target_index[key].append(row)

            left_full_key = f"{query.primary_model}.{left_key}"

            new_result = []
            for left_row in result_data:
                left_val = left_row.get(left_full_key)
                matches = target_index.get(left_val, [])

                if matches:
                    for right_row in matches:
                        merged = dict(left_row)
                        for k, v in right_row.items():
                            merged[f"{target_model}.{k}"] = v
                        new_result.append(merged)
                elif join_type in (JoinType.LEFT, JoinType.FULL):
                    # 左连接：保留左表
                    merged = dict(left_row)
                    for row in target_data[:1]:  # 取字段名
                        for k in row.keys():
                            merged[f"{target_model}.{k}"] = None
                    new_result.append(merged)

            # RIGHT JOIN 和 FULL JOIN 还需要处理右表中未匹配的行
            if join_type in (JoinType.RIGHT, JoinType.FULL):
                matched_right_keys = set()
                for row in new_result:
                    key = row.get(f"{target_model}.{right_key}")
                    if key is not None:
                        matched_right_keys.add(key)

                for right_row in target_data:
                    key = right_row.get(right_key)
                    if key not in matched_right_keys:
                        merged = {}
                        # 左表字段设为 None
                        if primary_data:
                            for k in primary_data[0].keys():
                                merged[f"{query.primary_model}.{k}"] = None
                        # 右表字段
                        for k, v in right_row.items():
                            merged[f"{target_model}.{k}"] = v
                        new_result.append(merged)

            result_data = new_result

        # 过滤
        if query.filters:
            for model_name, field_name, op, value in query.filters:
                full_field = f"{model_name}.{field_name}"
                f = QueryFilter(field=full_field, operator=op, value=value)
                result_data = [row for row in result_data if f.matches(row)]

        # 排序
        if query.order_by:
            for model_name, field_name, ascending in reversed(query.order_by):
                full_field = f"{model_name}.{field_name}"
                result_data.sort(
                    key=lambda x: (x.get(full_field) is None, x.get(full_field)),
                    reverse=not ascending,
                )

        # 分页
        total = len(result_data)
        start = (query.page - 1) * query.page_size
        end = start + query.page_size
        page_items = result_data[start:end]

        # 选择字段
        if query.select_fields:
            selected_items = []
            for row in page_items:
                selected = {}
                for model_name, field_name, alias in query.select_fields:
                    full_field = f"{model_name}.{field_name}"
                    selected[alias or field_name] = row.get(full_field)
                selected_items.append(selected)
            page_items = selected_items

        execution_time = (time.time() - start_time) * 1000

        return {
            "items": page_items,
            "total": total,
            "page": query.page,
            "page_size": query.page_size,
            "total_pages": (total + query.page_size - 1) // query.page_size if query.page_size > 0 else 0,
            "execution_time_ms": round(execution_time, 2),
        }

    # ---- 数据导出 ----

    def export(
        self,
        model_name: str,
        fmt: ExportFormat = ExportFormat.JSON,
        filters: Optional[List[QueryFilter]] = None,
    ) -> Tuple[str, bytes]:
        """
        导出数据。

        Args:
            model_name: 模型名称
            fmt: 导出格式
            filters: 过滤条件

        Returns:
            (文件名, 文件内容字节)
        """
        repo = self._get_repo_or_raise(model_name)
        all_data = repo._execute_query(
            filters=filters or [],
            order_by=[],
            limit=None,
            offset=None,
        )

        rows = [
            item.to_dict() if hasattr(item, "to_dict") else item
            for item in all_data
        ]

        if fmt == ExportFormat.JSON:
            content = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
            filename = f"{model_name}_export.json"
        elif fmt == ExportFormat.CSV:
            output = io.StringIO()
            if rows:
                writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            content = output.getvalue().encode("utf-8-sig")
            filename = f"{model_name}_export.csv"
        else:
            raise ValueError(f"Unsupported export format: {fmt}")

        return filename, content

    # ---- 跨模块统计 ----

    def cross_module_stats(self, model_names: List[str]) -> Dict[str, Any]:
        """
        获取多个模块的统计信息。

        Args:
            model_names: 模型名称列表

        Returns:
            统计信息字典
        """
        stats: Dict[str, Any] = {}
        for model_name in model_names:
            repo = self._repositories.get(model_name)
            if repo:
                stats[model_name] = {
                    "count": repo._count_query([]),
                    "available": True,
                }
            else:
                stats[model_name] = {
                    "count": 0,
                    "available": False,
                }
        return stats

    def _get_repo_or_raise(self, model_name: str) -> BaseRepository:
        repo = self._repositories.get(model_name)
        if not repo:
            raise ValueError(f"Repository not found for model: {model_name}")
        return repo
