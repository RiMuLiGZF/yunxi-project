"""
数据聚合服务（Data Aggregation）
=============================

提供跨模块数据查询和聚合能力。
"""

from .query_service import (
    QueryService,
    AggregationQuery,
    AggregationResult,
    AggregateFunc,
    JoinQuery,
    JoinType,
)
from .views import (
    DataView,
    ViewManager,
    ViewCache,
    get_view_manager,
)

__all__ = [
    # 查询服务
    "QueryService",
    "AggregationQuery",
    "AggregationResult",
    "AggregateFunc",
    "JoinQuery",
    "JoinType",
    # 数据视图
    "DataView",
    "ViewManager",
    "ViewCache",
    "get_view_manager",
]
