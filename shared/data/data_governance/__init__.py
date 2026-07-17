"""
数据治理模块
==========

提供数据主权管理、去重规划、数据质量监控、数据分类分级等功能。

子模块：
- sovereignty: 数据主权清单与查询工具
"""

from .sovereignty import (
    load_sovereignty,
    get_module_sovereignty,
    check_data_owner,
    list_overlapping_domains,
    get_deduplication_progress,
    # 数据分类分级
    get_classification_rules,
    get_table_metadata,
    list_tables_by_category,
    list_tables_by_sensitivity,
    get_retention_policy,
    get_classification_summary,
    get_highest_risk_tables,
    get_encrypted_tables,
)

__all__ = [
    "load_sovereignty",
    "get_module_sovereignty",
    "check_data_owner",
    "list_overlapping_domains",
    "get_deduplication_progress",
    # 数据分类分级
    "get_classification_rules",
    "get_table_metadata",
    "list_tables_by_category",
    "list_tables_by_sensitivity",
    "get_retention_policy",
    "get_classification_summary",
    "get_highest_risk_tables",
    "get_encrypted_tables",
]
