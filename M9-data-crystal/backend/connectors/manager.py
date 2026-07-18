"""
云汐 M9 数据水晶 - 连接器管理器

P3 优化：数据采集管道 + 连接器生态
管理连接器的注册、实例创建、连接池、健康检查
"""

from __future__ import annotations

import time
import threading
import logging
from typing import Dict, List, Any, Optional, Iterator
from dataclasses import dataclass, field

from .base import (
    BaseConnector,
    ConnectorRegistry,
    ConnectorType,
    ConnectionStatus,
    HealthStatus,
    HealthCheckResult,
)

logger = logging.getLogger(__name__)


# ============================================================
# 连接池条目
# ============================================================

@dataclass
class PoolEntry:
    """连接池条目"""
    connector: BaseConnector
    connector_type: str
    config: Dict[str, Any]
    created_at: float
    last_used_at: float
    reference_count: int = 0
    in_use: bool = False


# ============================================================
# 连接器管理器
# ============================================================

class ConnectorManager:
    """
    连接器管理器

    功能：
    - 连接器注册/发现
    - 连接器实例管理（创建/销毁/复用）
    - 连接池管理
    - 健康检查调度
    - 连接器统计
    """

    def __init__(self, max_pool_size: int = 10, idle_timeout: int = 300,
                 health_check_interval: int = 60):
        """
        初始化连接器管理器

        Args:
            max_pool_size: 最大连接池大小
            idle_timeout: 空闲超时时间（秒）
            health_check_interval: 健康检查间隔（秒）
        """
        self._max_pool_size = max_pool_size
        self._idle_timeout = idle_timeout
        self._health_check_interval = health_check_interval

        # 连接器实例池：id -> connector
        self._instances: Dict[str, BaseConnector] = {}
        # 连接器配置存储：id -> config
        self._configs: Dict[str, Dict[str, Any]] = {}
        # 连接池：connector_type -> list[PoolEntry]
        self._pool: Dict[str, List[PoolEntry]] = {}
        # 健康状态缓存：id -> HealthCheckResult
        self._health_cache: Dict[str, HealthCheckResult] = {}
        # 统计信息
        self._stats: Dict[str, Any] = {
            "total_created": 0,
            "total_destroyed": 0,
            "total_health_checks": 0,
            "total_errors": 0,
        }

        self._lock = threading.RLock()
        self._health_check_thread: Optional[threading.Thread] = None
        self._health_check_running = False
        self._next_id = 1

        # 自动发现并注册内置连接器
        self._discover_builtin_connectors()

    def _discover_builtin_connectors(self) -> None:
        """自动发现并注册内置连接器"""
        try:
            from . import sqlite_connector
            from . import csv_connector
            from . import json_connector
            from . import excel_connector
            from . import mysql_connector
            from . import postgresql_connector
            from . import rest_api_connector
            from . import s3_connector

            # 确保所有内置连接器都已注册（防止注册表被清空后无法恢复）
            builtin_connectors = [
                sqlite_connector.SQLiteConnector,
                csv_connector.CSVConnector,
                json_connector.JSONConnector,
                excel_connector.ExcelConnector,
                mysql_connector.MySQLConnector,
                postgresql_connector.PostgreSQLConnector,
                rest_api_connector.RESTAPIConnector,
                s3_connector.S3Connector,
            ]
            for cls in builtin_connectors:
                if cls.__name__ not in ConnectorRegistry._connectors:
                    ConnectorRegistry.register(cls)
        except Exception as e:
            logger.warning(f"自动发现连接器时出错: {e}")

    # ============================================================
    # 连接器注册与发现
    # ============================================================

    def register_connector(self, connector_class: type, category: str = "other") -> None:
        """注册连接器类"""
        ConnectorRegistry.register(connector_class, category)
        logger.info(f"连接器已注册: {connector_class.__name__}")

    def list_connector_types(self) -> List[Dict[str, Any]]:
        """列出所有可用的连接器类型"""
        types = []
        for name in ConnectorRegistry.list_all():
            meta = ConnectorRegistry.get_meta(name)
            types.append({
                "name": name,
                "type": meta.connector_type if meta else "",
                "description": meta.description if meta else "",
                "version": meta.version if meta else "",
                "supported_operations": meta.supported_operations if meta else [],
            })
        return types

    def get_connector_categories(self) -> Dict[str, List[str]]:
        """获取连接器分类"""
        return ConnectorRegistry.get_categories()

    # ============================================================
    # 连接器实例管理
    # ============================================================

    def create_connector(self, connector_type: str, config: Dict[str, Any],
                         connector_id: Optional[str] = None) -> str:
        """
        创建连接器实例

        Args:
            connector_type: 连接器类型名称
            config: 连接器配置
            connector_id: 连接器 ID（可选，自动生成）

        Returns:
            str: 连接器 ID
        """
        with self._lock:
            # 生成 ID
            if connector_id is None:
                connector_id = f"conn_{self._next_id}"
                self._next_id += 1

            # 检查是否已存在
            if connector_id in self._instances:
                raise ValueError(f"连接器 ID 已存在: {connector_id}")

            # 创建实例
            connector_class = ConnectorRegistry.get(connector_type)
            if connector_class is None:
                raise ValueError(f"未知的连接器类型: {connector_type}")

            connector = connector_class(config=config)

            # 保存实例和配置
            self._instances[connector_id] = connector
            self._configs[connector_id] = {
                "connector_type": connector_type,
                "config": config,
                "created_at": time.time(),
            }
            self._stats["total_created"] += 1

            logger.info(f"连接器已创建: {connector_id} ({connector_type})")
            return connector_id

    def get_connector(self, connector_id: str) -> BaseConnector:
        """获取连接器实例"""
        with self._lock:
            if connector_id not in self._instances:
                raise KeyError(f"连接器不存在: {connector_id}")
            return self._instances[connector_id]

    def get_connector_config(self, connector_id: str) -> Dict[str, Any]:
        """获取连接器配置"""
        with self._lock:
            if connector_id not in self._configs:
                raise KeyError(f"连接器不存在: {connector_id}")
            return dict(self._configs[connector_id])

    def update_connector(self, connector_id: str, config: Dict[str, Any]) -> bool:
        """更新连接器配置"""
        with self._lock:
            if connector_id not in self._instances:
                raise KeyError(f"连接器不存在: {connector_id}")

            connector = self._instances[connector_id]
            # 断开旧连接
            try:
                connector.disconnect()
            except Exception:
                pass

            # 更新配置并重连
            old_config = self._configs[connector_id]
            new_config = dict(old_config.get("config", {}))
            new_config.update(config)

            connector._config = new_config
            self._configs[connector_id]["config"] = new_config
            self._configs[connector_id]["updated_at"] = time.time()

            # 清除健康状态缓存
            if connector_id in self._health_cache:
                del self._health_cache[connector_id]

            logger.info(f"连接器配置已更新: {connector_id}")
            return True

    def delete_connector(self, connector_id: str) -> bool:
        """删除连接器"""
        with self._lock:
            if connector_id not in self._instances:
                return False

            connector = self._instances[connector_id]
            try:
                connector.disconnect()
            except Exception:
                pass

            del self._instances[connector_id]
            del self._configs[connector_id]
            if connector_id in self._health_cache:
                del self._health_cache[connector_id]

            self._stats["total_destroyed"] += 1
            logger.info(f"连接器已删除: {connector_id}")
            return True

    def list_connectors(self) -> List[Dict[str, Any]]:
        """列出所有连接器"""
        with self._lock:
            result = []
            for conn_id, connector in self._instances.items():
                config_info = self._configs.get(conn_id, {})
                result.append({
                    "id": conn_id,
                    "name": connector.meta.name,
                    "connector_type": config_info.get("connector_type", ""),
                    "description": connector.meta.description,
                    "status": connector.status,
                    "is_connected": connector.is_connected(),
                    "config": connector.config,
                    "stats": connector.get_stats(),
                    "created_at": config_info.get("created_at"),
                    "updated_at": config_info.get("updated_at"),
                })
            return result

    def connect_connector(self, connector_id: str) -> bool:
        """连接指定连接器"""
        connector = self.get_connector(connector_id)
        result = connector.connect()
        # 清除健康缓存
        with self._lock:
            if connector_id in self._health_cache:
                del self._health_cache[connector_id]
        return result

    def disconnect_connector(self, connector_id: str) -> bool:
        """断开指定连接器"""
        connector = self.get_connector(connector_id)
        return connector.disconnect()

    def test_connection(self, connector_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """测试连接（不保存实例）"""
        try:
            connector_class = ConnectorRegistry.get(connector_type)
            if connector_class is None:
                return {
                    "success": False,
                    "error": f"未知的连接器类型: {connector_type}",
                    "response_time_ms": 0,
                }

            start = time.time()
            connector = connector_class(config=config)
            connected = connector.connect()
            elapsed = (time.time() - start) * 1000

            result = {
                "success": connected,
                "response_time_ms": round(elapsed, 2),
            }

            if not connected:
                result["error"] = connector._last_error or "连接失败"

            # 健康检查
            if connected:
                try:
                    health = connector.health_check()
                    result["health"] = health.to_dict()
                except Exception as e:
                    result["health_error"] = str(e)

                connector.disconnect()

            return result

        except Exception as e:
            self._stats["total_errors"] += 1
            return {
                "success": False,
                "error": str(e),
                "response_time_ms": 0,
            }

    # ============================================================
    # 健康检查
    # ============================================================

    def check_health(self, connector_id: str) -> HealthCheckResult:
        """检查指定连接器的健康状态"""
        connector = self.get_connector(connector_id)
        result = connector.health_check()

        with self._lock:
            self._health_cache[connector_id] = result
            self._stats["total_health_checks"] += 1

        return result

    def get_health_status(self, connector_id: str) -> Dict[str, Any]:
        """获取连接器健康状态（优先使用缓存）"""
        with self._lock:
            if connector_id in self._health_cache:
                return self._health_cache[connector_id].to_dict()

        # 缓存未命中，执行检查
        result = self.check_health(connector_id)
        return result.to_dict()

    def check_all_health(self) -> Dict[str, Dict[str, Any]]:
        """检查所有连接器的健康状态"""
        results = {}
        with self._lock:
            connector_ids = list(self._instances.keys())

        for conn_id in connector_ids:
            try:
                result = self.check_health(conn_id)
                results[conn_id] = result.to_dict()
            except Exception as e:
                results[conn_id] = {
                    "status": HealthStatus.UNKNOWN,
                    "error": str(e),
                }
        return results

    # ============================================================
    # 健康检查后台线程
    # ============================================================

    def start_health_check_scheduler(self) -> None:
        """启动健康检查调度器"""
        if self._health_check_running:
            return

        self._health_check_running = True
        self._health_check_thread = threading.Thread(
            target=self._health_check_loop,
            daemon=True,
            name="connector-health-checker",
        )
        self._health_check_thread.start()
        logger.info("连接器健康检查调度器已启动")

    def stop_health_check_scheduler(self) -> None:
        """停止健康检查调度器"""
        self._health_check_running = False
        if self._health_check_thread:
            self._health_check_thread.join(timeout=5)
            self._health_check_thread = None
        logger.info("连接器健康检查调度器已停止")

    def _health_check_loop(self) -> None:
        """健康检查循环"""
        while self._health_check_running:
            try:
                with self._lock:
                    connector_ids = list(self._instances.keys())

                for conn_id in connector_ids:
                    if not self._health_check_running:
                        break
                    try:
                        self.check_health(conn_id)
                    except Exception as e:
                        logger.warning(f"健康检查失败 [{conn_id}]: {e}")

            except Exception as e:
                logger.error(f"健康检查循环异常: {e}")

            # 等待下一轮检查
            for _ in range(self._health_check_interval):
                if not self._health_check_running:
                    break
                time.sleep(1)

    # ============================================================
    # Schema 查询
    # ============================================================

    def get_schema(self, connector_id: str, table: str) -> Dict[str, Any]:
        """获取连接器的 Schema"""
        connector = self.get_connector(connector_id)

        # 确保已连接
        if not connector.is_connected():
            connector.connect()

        return connector.get_schema(table)

    def list_tables(self, connector_id: str) -> List[str]:
        """列出连接器的表/文件"""
        connector = self.get_connector(connector_id)

        if not connector.is_connected():
            connector.connect()

        return connector.list_tables()

    # ============================================================
    # 统计信息
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取管理器统计信息"""
        with self._lock:
            return {
                "total_connectors": len(self._instances),
                "total_created": self._stats["total_created"],
                "total_destroyed": self._stats["total_destroyed"],
                "total_health_checks": self._stats["total_health_checks"],
                "total_errors": self._stats["total_errors"],
                "pool_size": sum(len(entries) for entries in self._pool.values()),
                "max_pool_size": self._max_pool_size,
                "health_check_interval": self._health_check_interval,
                "health_check_running": self._health_check_running,
            }

    # ============================================================
    # 连接池管理
    # ============================================================

    def acquire_from_pool(self, connector_type: str, config: Dict[str, Any]) -> BaseConnector:
        """
        从连接池获取连接器

        Args:
            connector_type: 连接器类型
            config: 配置（用于匹配）

        Returns:
            BaseConnector: 连接器实例
        """
        with self._lock:
            pool_key = connector_type
            if pool_key not in self._pool:
                self._pool[pool_key] = []

            # 查找可用的连接
            for entry in self._pool[pool_key]:
                if not entry.in_use:
                    entry.in_use = True
                    entry.reference_count += 1
                    entry.last_used_at = time.time()
                    logger.debug(f"从连接池获取连接器: {connector_type}")
                    return entry.connector

            # 池满了，清理空闲连接
            if len(self._pool[pool_key]) >= self._max_pool_size:
                self._cleanup_idle_locked(pool_key)

            # 创建新连接
            connector_class = ConnectorRegistry.get(connector_type)
            if connector_class is None:
                raise ValueError(f"未知的连接器类型: {connector_type}")

            connector = connector_class(config=config)
            connector.connect()

            entry = PoolEntry(
                connector=connector,
                connector_type=connector_type,
                config=config,
                created_at=time.time(),
                last_used_at=time.time(),
                reference_count=1,
                in_use=True,
            )
            self._pool[pool_key].append(entry)
            logger.debug(f"创建新连接加入池: {connector_type}")
            return connector

    def release_to_pool(self, connector: BaseConnector) -> None:
        """将连接器归还连接池"""
        with self._lock:
            for entries in self._pool.values():
                for entry in entries:
                    if entry.connector is connector:
                        entry.in_use = False
                        entry.last_used_at = time.time()
                        logger.debug(f"连接器归还连接池")
                        return

    def _cleanup_idle_locked(self, pool_key: str) -> None:
        """清理空闲连接（必须在锁内调用）"""
        now = time.time()
        entries = self._pool.get(pool_key, [])
        to_remove = []

        for entry in entries:
            if not entry.in_use and (now - entry.last_used_at) > self._idle_timeout:
                try:
                    entry.connector.disconnect()
                except Exception:
                    pass
                to_remove.append(entry)

        for entry in to_remove:
            entries.remove(entry)

    def cleanup_idle(self) -> int:
        """清理所有空闲超时的连接"""
        with self._lock:
            total_removed = 0
            for pool_key in list(self._pool.keys()):
                before = len(self._pool[pool_key])
                self._cleanup_idle_locked(pool_key)
                after = len(self._pool[pool_key])
                total_removed += before - after
            return total_removed

    # ============================================================
    # 清理
    # ============================================================

    def shutdown(self) -> None:
        """关闭管理器，清理所有资源"""
        self.stop_health_check_scheduler()

        with self._lock:
            # 断开所有连接器
            for conn_id, connector in self._instances.items():
                try:
                    connector.disconnect()
                except Exception:
                    pass

            # 清理连接池
            for entries in self._pool.values():
                for entry in entries:
                    try:
                        entry.connector.disconnect()
                    except Exception:
                        pass

            self._instances.clear()
            self._pool.clear()
            self._health_cache.clear()

        logger.info("连接器管理器已关闭")


# ============================================================
# 单例
# ============================================================

_connector_manager: Optional[ConnectorManager] = None


def get_connector_manager() -> ConnectorManager:
    """获取连接器管理器单例"""
    global _connector_manager
    if _connector_manager is None:
        from config import get_config
        settings = get_config()
        _connector_manager = ConnectorManager(
            max_pool_size=getattr(settings, 'connector_pool_size', 10),
            idle_timeout=getattr(settings, 'connector_idle_timeout', 300),
            health_check_interval=getattr(settings, 'connector_health_check_interval', 60),
        )
    return _connector_manager
