"""
数据治理模块
==========

提供数据主权管理、去重规划、数据质量监控等功能。

子模块：
- sovereignty: 数据主权清单与查询工具
"""

from .sovereignty import (
    load_sovereignty,
    get_module_sovereignty,
    check_data_owner,
    list_overlapping_domains,
    get_deduplication_progress,
)

__all__ = [
    "load_sovereignty",
    "get_module_sovereignty",
    "check_data_owner",
    "list_overlapping_domains",
    "get_deduplication_progress",
]
