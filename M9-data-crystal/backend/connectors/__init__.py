"""
云汐 M9 数据水晶 - 连接器包

P3 优化：数据采集管道 + 连接器生态
统一导出所有连接器
"""

from .base import (
    BaseConnector,
    ConnectorMeta,
    ConnectorRegistry,
    ConnectorType,
    ConnectionStatus,
    HealthStatus,
    HealthCheckResult,
    ConnectorStats,
)

# 导入所有连接器以触发注册
from .sqlite_connector import SQLiteConnector
from .csv_connector import CSVConnector
from .json_connector import JSONConnector
from .excel_connector import ExcelConnector
from .mysql_connector import MySQLConnector
from .postgresql_connector import PostgreSQLConnector
from .rest_api_connector import RESTAPIConnector
from .s3_connector import S3Connector

from .manager import ConnectorManager, get_connector_manager

__all__ = [
    # 基类和常量
    "BaseConnector",
    "ConnectorMeta",
    "ConnectorRegistry",
    "ConnectorType",
    "ConnectionStatus",
    "HealthStatus",
    "HealthCheckResult",
    "ConnectorStats",
    # 连接器
    "SQLiteConnector",
    "CSVConnector",
    "JSONConnector",
    "ExcelConnector",
    "MySQLConnector",
    "PostgreSQLConnector",
    "RESTAPIConnector",
    "S3Connector",
    # 管理器
    "ConnectorManager",
    "get_connector_manager",
]
