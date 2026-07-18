"""
云汐 M9 数据水晶 - 连接器基类

P3 优化：数据采集管道 + 连接器生态
定义统一的连接器接口规范，所有连接器必须继承此类
"""

from __future__ import annotations

import time
import logging
from abc import ABC, abstractmethod
from typing import Iterator, List, Dict, Any, Optional
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


# ============================================================
# 连接器类型枚举
# ============================================================

class ConnectorType:
    """连接器类型常量"""
    DATABASE = "database"
    FILE = "file"
    API = "api"
    STREAM = "stream"
    CLOUD = "cloud"


# ============================================================
# 连接状态
# ============================================================

class ConnectionStatus:
    """连接状态常量"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# ============================================================
# 健康状态
# ============================================================

class HealthStatus:
    """健康状态常量"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# ============================================================
# 连接器元数据
# ============================================================

@dataclass
class ConnectorMeta:
    """连接器元数据"""
    name: str = ""
    connector_type: str = ""  # database / file / api / stream / cloud
    description: str = ""
    version: str = "1.0.0"
    supported_operations: List[str] = field(default_factory=list)
    # 支持的操作：read, write, batch_read, batch_write, stream_read, stream_write, schema, list_tables


# ============================================================
# 健康检查结果
# ============================================================

@dataclass
class HealthCheckResult:
    """健康检查结果"""
    status: str = HealthStatus.UNKNOWN
    response_time_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "response_time_ms": round(self.response_time_ms, 2),
            "details": self.details,
            "error": self.error,
        }


# ============================================================
# 连接器统计信息
# ============================================================

@dataclass
class ConnectorStats:
    """连接器统计信息"""
    total_reads: int = 0
    total_writes: int = 0
    total_bytes_read: int = 0
    total_bytes_written: int = 0
    total_errors: int = 0
    last_read_at: Optional[float] = None
    last_write_at: Optional[float] = None
    connection_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_reads": self.total_reads,
            "total_writes": self.total_writes,
            "total_bytes_read": self.total_bytes_read,
            "total_bytes_written": self.total_bytes_written,
            "total_errors": self.total_errors,
            "last_read_at": self.last_read_at,
            "last_write_at": self.last_write_at,
            "connection_count": self.connection_count,
        }


# ============================================================
# 连接器基类
# ============================================================

class BaseConnector(ABC):
    """
    连接器基类 - 定义统一的连接器接口

    所有数据源连接器必须继承此类并实现抽象方法。
    提供生命周期管理、数据读写、元数据查询、健康检查等能力。
    """

    # 元数据（子类应覆盖）
    meta: ConnectorMeta = ConnectorMeta()

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化连接器

        Args:
            config: 连接配置字典
        """
        self._config: Dict[str, Any] = config or {}
        self._status: str = ConnectionStatus.DISCONNECTED
        self._stats: ConnectorStats = ConnectorStats()
        self._connected_at: Optional[float] = None
        self._last_error: Optional[str] = None

    # ============================================================
    # 生命周期方法
    # ============================================================

    @abstractmethod
    def connect(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        建立连接

        Args:
            config: 连接配置（可选，若提供则覆盖当前配置）

        Returns:
            bool: 连接是否成功
        """
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        """
        断开连接

        Returns:
            bool: 断开是否成功
        """
        pass

    def is_connected(self) -> bool:
        """
        检查是否已连接

        Returns:
            bool: 是否已连接
        """
        return self._status == ConnectionStatus.CONNECTED

    @property
    def status(self) -> str:
        """获取连接状态"""
        return self._status

    @property
    def config(self) -> Dict[str, Any]:
        """获取当前配置（敏感字段已脱敏）"""
        return self._sanitize_config(self._config)

    def _sanitize_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """脱敏配置中的敏感字段"""
        sensitive_keys = {'password', 'token', 'secret', 'api_key', 'access_key', 'secret_key'}
        result = {}
        for key, value in config.items():
            if isinstance(value, dict):
                result[key] = self._sanitize_config(value)
            elif key.lower() in sensitive_keys and value:
                result[key] = "***"
            else:
                result[key] = value
        return result

    # ============================================================
    # 数据读取方法
    # ============================================================

    @abstractmethod
    def read(self, query: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        """
        流式读取数据

        Args:
            query: 查询参数（SQL语句、过滤条件、文件路径等）

        Yields:
            dict: 数据记录
        """
        pass

    def read_batch(self, batch_size: int = 100, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        批量读取数据

        Args:
            batch_size: 批量大小
            query: 查询参数

        Returns:
            list[dict]: 数据记录列表
        """
        results = []
        for i, record in enumerate(self.read(query)):
            results.append(record)
            if i + 1 >= batch_size:
                break
        self._stats.total_reads += 1
        self._stats.last_read_at = time.time()
        return results

    def read_all(self, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        读取所有数据（注意：大数据量时可能内存溢出）

        Args:
            query: 查询参数

        Returns:
            list[dict]: 所有数据记录
        """
        return list(self.read(query))

    # ============================================================
    # 数据写入方法（可选）
    # ============================================================

    def write(self, data: List[Dict[str, Any]]) -> int:
        """
        批量写入数据

        Args:
            data: 数据记录列表

        Returns:
            int: 实际写入条数
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持写入操作")

    def write_stream(self, data: Iterator[Dict[str, Any]]) -> int:
        """
        流式写入数据

        Args:
            data: 数据记录迭代器

        Returns:
            int: 实际写入条数
        """
        # 默认实现：收集所有数据后批量写入
        records = list(data)
        count = self.write(records)
        self._stats.total_writes += 1
        self._stats.last_write_at = time.time()
        return count

    # ============================================================
    # 元数据方法
    # ============================================================

    def list_tables(self) -> List[str]:
        """
        列出可用的表/文件/端点

        Returns:
            list[str]: 表名/文件名/端点列表
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持 list_tables")

    def get_schema(self, table: str) -> Dict[str, Any]:
        """
        获取指定表/集合的 Schema

        Args:
            table: 表名/文件名/端点

        Returns:
            dict: Schema 定义，包含字段名、类型等
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持 get_schema")

    # ============================================================
    # 健康检查
    # ============================================================

    def health_check(self) -> HealthCheckResult:
        """
        健康检查

        Returns:
            HealthCheckResult: 健康检查结果
        """
        start = time.time()
        try:
            if not self.is_connected():
                # 尝试重新连接
                if not self.connect():
                    return HealthCheckResult(
                        status=HealthStatus.UNHEALTHY,
                        response_time_ms=(time.time() - start) * 1000,
                        error="连接失败",
                    )

            # 执行一个轻量操作验证连接
            self._health_probe()

            elapsed = (time.time() - start) * 1000
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                response_time_ms=elapsed,
                details={"latency_ms": round(elapsed, 2)},
            )
        except Exception as e:
            self._stats.total_errors += 1
            self._last_error = str(e)
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=(time.time() - start) * 1000,
                error=str(e),
            )

    def _health_probe(self) -> None:
        """
        健康探针 - 子类可重写此方法执行具体的连通性验证
        默认实现：尝试读取一条数据
        """
        try:
            next(self.read({"limit": 1}), None)
        except NotImplementedError:
            # 不支持读取的连接器跳过
            pass

    # ============================================================
    # 统计信息
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取连接器统计信息"""
        return self._stats.to_dict()

    def reset_stats(self) -> None:
        """重置统计信息"""
        self._stats = ConnectorStats()

    # ============================================================
    # 上下文管理器支持
    # ============================================================

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    # ============================================================
    # 工具方法
    # ============================================================

    def _ensure_connected(self) -> None:
        """确保已连接，否则抛出异常"""
        if not self.is_connected():
            raise ConnectionError(f"连接器 {self.meta.name} 未连接")

    def _record_read(self, count: int = 1, bytes_read: int = 0) -> None:
        """记录读取操作"""
        self._stats.total_reads += count
        self._stats.total_bytes_read += bytes_read
        self._stats.last_read_at = time.time()

    def _record_write(self, count: int = 1, bytes_written: int = 0) -> None:
        """记录写入操作"""
        self._stats.total_writes += count
        self._stats.total_bytes_written += bytes_written
        self._stats.last_write_at = time.time()

    def _record_error(self) -> None:
        """记录错误"""
        self._stats.total_errors += 1


# ============================================================
# 连接器注册表
# ============================================================

class ConnectorRegistry:
    """
    连接器注册表 - 管理所有可用的连接器类型

    支持注册、发现、创建连接器实例
    """

    _connectors: Dict[str, type] = {}
    _categories: Dict[str, List[str]] = {}

    @classmethod
    def register(cls, connector_class: type, category: str = None) -> type:
        """
        注册连接器类（可作为装饰器使用）

        Args:
            connector_class: 连接器类（必须继承 BaseConnector）
            category: 连接器分类（默认从 meta.connector_type 自动推断）

        Returns:
            type: 连接器类（支持装饰器语法）
        """
        if not issubclass(connector_class, BaseConnector):
            raise TypeError(f"{connector_class.__name__} 必须继承 BaseConnector")

        name = connector_class.__name__
        cls._connectors[name] = connector_class

        # 自动推断分类
        if category is None:
            meta = getattr(connector_class, "meta", None)
            if meta and hasattr(meta, "connector_type"):
                category = meta.connector_type
            else:
                category = "other"

        if category not in cls._categories:
            cls._categories[category] = []
        if name not in cls._categories[category]:
            cls._categories[category].append(name)

        logger.debug(f"连接器已注册: {name} (分类: {category})")
        return connector_class

    @classmethod
    def unregister(cls, name: str) -> bool:
        """注销连接器"""
        if name in cls._connectors:
            del cls._connectors[name]
            for cat_list in cls._categories.values():
                if name in cat_list:
                    cat_list.remove(name)
            return True
        return False

    @classmethod
    def get(cls, name: str) -> Optional[type]:
        """获取连接器类"""
        return cls._connectors.get(name)

    @classmethod
    def create(cls, name: str, config: Optional[Dict[str, Any]] = None) -> BaseConnector:
        """创建连接器实例"""
        connector_class = cls.get(name)
        if connector_class is None:
            raise ValueError(f"未知的连接器类型: {name}")
        return connector_class(config=config)

    @classmethod
    def list_all(cls) -> List[str]:
        """列出所有连接器名称"""
        return list(cls._connectors.keys())

    @classmethod
    def list_by_category(cls, category: str) -> List[str]:
        """按分类列出连接器"""
        return cls._categories.get(category, [])

    @classmethod
    def get_categories(cls) -> Dict[str, List[str]]:
        """获取所有分类及其中的连接器"""
        return dict(cls._categories)

    @classmethod
    def get_meta(cls, name: str) -> Optional[ConnectorMeta]:
        """获取连接器元数据"""
        connector_class = cls.get(name)
        if connector_class:
            return connector_class.meta
        return None

    @classmethod
    def clear(cls) -> None:
        """清空注册表（测试用）"""
        cls._connectors.clear()
        cls._categories.clear()
