"""
可穿戴设备服务层
================

基于 shared.data_layer.DatabaseManager 封装的可穿戴设备业务服务。
提供比 Repository 层更高层的业务逻辑，包括：
- 数据校验与业务规则
- 批量操作封装
- 事件触发与通知

P0 批次迁移：手表/可穿戴数据从 M8 迁到 M6
数据主权：可穿戴设备数据归属 M6 硬件外设模块
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class WearableService:
    """可穿戴设备业务服务

    基于 shared.data_layer.DatabaseManager 实现统一数据访问。
    所有方法均接受外部传入的 db_manager 实例，支持依赖注入。
    """

    def __init__(self, db_manager=None, db_name: str = "m6_wearable"):
        """
        初始化可穿戴设备服务

        Args:
            db_manager: DatabaseManager 实例，None 则自动导入 shared 单例
            db_name: 数据库名称（在 data_root 下的文件名）
        """
        if db_manager is None:
            try:
                import sys
                from pathlib import Path
                # 尝试找到项目根目录并加入 sys.path
                current = Path(__file__).resolve().parent
                for _ in range(5):
                    if (current / "shared" / "data_layer").exists():
                        if str(current) not in sys.path:
                            sys.path.insert(0, str(current))
                        break
                    current = current.parent
                from shared.data_layer import get_db_manager
                db_manager = get_db_manager()
            except ImportError:
                logger.warning("shared.data_layer 不可用，将降级使用本地数据库连接")
                db_manager = None

        self._db_manager = db_manager
        self.db_name = db_name
        self._fallback_conn = None  # 降级模式的本地连接

    # ========================================================================
    # 内部工具：数据库访问适配
    # ========================================================================

    def _has_shared_layer(self) -> bool:
        """是否使用 shared data layer"""
        return self._db_manager is not None

    def _get_db_path(self) -> str:
        """获取本地数据库路径（降级模式使用）"""
        from pathlib import Path
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir / f"{self.db_name}.db")

    def _execute_query(
        self,
        sql: str,
        params: Optional[tuple] = None,
        *,
        write: bool = False,
    ) -> Any:
        """
        执行 SQL 查询（自动适配 shared layer 或本地连接）

        Args:
            sql: SQL 语句
            params: 参数元组
            write: 是否为写操作

        Returns:
            查询结果（读操作返回行列表，写操作返回受影响行数）
        """
        if self._has_shared_layer():
            if write:
                return self._db_manager.execute(self.db_name, sql, params)
            else:
                return self._db_manager.query_all(self.db_name, sql, params)
        else:
            # 降级模式：使用本地 sqlite3 连接
            import sqlite3
            if self._fallback_conn is None:
                self._fallback_conn = sqlite3.connect(
                    self._get_db_path(), check_same_thread=False
                )
                self._fallback_conn.row_factory = sqlite3.Row
                self._init_tables_local(self._fallback_conn)

            cursor = self._fallback_conn.execute(sql, params or ())
            if write:
                self._fallback_conn.commit()
                return cursor.rowcount
            else:
                return [dict(row) for row in cursor.fetchall()]

    def _init_tables_local(self, conn) -> None:
        """初始化本地数据库表（降级模式使用）"""
        cursor = conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS wearable_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL DEFAULT 'default',
                name TEXT NOT NULL DEFAULT '',
                device_type TEXT NOT NULL DEFAULT 'watch',
                brand TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                mac_address TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'offline',
                battery_level REAL,
                firmware_version TEXT NOT NULL DEFAULT '',
                last_sync_at DATETIME,
                paired_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wearable_health_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'default',
                data_type TEXT NOT NULL,
                value REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT '',
                recorded_at DATETIME NOT NULL,
                source TEXT NOT NULL DEFAULT 'device',
                quality TEXT NOT NULL DEFAULT 'good',
                created_at DATETIME NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wearable_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_id TEXT NOT NULL UNIQUE,
                device_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'default',
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT 'system',
                status TEXT NOT NULL DEFAULT 'pending',
                source TEXT NOT NULL DEFAULT 'system',
                delivered_at DATETIME,
                created_at DATETIME NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wearable_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL DEFAULT 'default',
                settings_json TEXT NOT NULL DEFAULT '{}',
                updated_at DATETIME NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_wearable_device_user
            ON wearable_devices(user_id);
            CREATE INDEX IF NOT EXISTS idx_wearable_device_type
            ON wearable_devices(device_type);
            CREATE INDEX IF NOT EXISTS idx_wearable_device_status
            ON wearable_devices(status);

            CREATE INDEX IF NOT EXISTS idx_wearable_health_device_type_time
            ON wearable_health_data(device_id, data_type, recorded_at);
            CREATE INDEX IF NOT EXISTS idx_wearable_health_user
            ON wearable_health_data(user_id);

            CREATE INDEX IF NOT EXISTS idx_wearable_notify_device
            ON wearable_notifications(device_id);
            CREATE INDEX IF NOT EXISTS idx_wearable_notify_status
            ON wearable_notifications(status);

            CREATE INDEX IF NOT EXISTS idx_wearable_settings_user
            ON wearable_settings(user_id);
        """)
        conn.commit()

    # ========================================================================
    # 可穿戴设备管理
    # ========================================================================

    def list_devices(
        self,
        user_id: Optional[str] = None,
        device_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """查询设备列表，返回 (设备列表, 总数)"""
        conditions = []
        params: List[Any] = []

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if device_type:
            conditions.append("device_type = ?")
            params.append(device_type)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        # 查询总数
        count_sql = f"SELECT COUNT(*) as cnt FROM wearable_devices {where_clause}"
        count_result = self._execute_query(count_sql, tuple(params))
        total = count_result[0]["cnt"] if count_result else 0

        # 查询分页数据
        query_sql = f"""
            SELECT * FROM wearable_devices {where_clause}
            ORDER BY updated_at DESC
            LIMIT {int(limit)} OFFSET {int(offset)}
        """
        devices = self._execute_query(query_sql, tuple(params))

        return devices, total

    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """根据 device_id 获取设备"""
        sql = "SELECT * FROM wearable_devices WHERE device_id = ?"
        result = self._execute_query(sql, (device_id,))
        return result[0] if result else None

    def create_device(self, device_data: Dict[str, Any]) -> Dict[str, Any]:
        """创建设备，返回创建后的设备数据"""
        now = datetime.now().isoformat()
        data = {
            "device_id": device_data["device_id"],
            "user_id": device_data.get("user_id", "default"),
            "name": device_data.get("name", ""),
            "device_type": device_data.get("device_type", "watch"),
            "brand": device_data.get("brand", ""),
            "model": device_data.get("model", ""),
            "mac_address": device_data.get("mac_address", ""),
            "status": device_data.get("status", "offline"),
            "battery_level": device_data.get("battery_level"),
            "firmware_version": device_data.get("firmware_version", ""),
            "paired_at": device_data.get("paired_at"),
            "last_sync_at": device_data.get("last_sync_at"),
            "created_at": now,
            "updated_at": now,
        }

        if self._has_shared_layer():
            row_id = self._db_manager.insert(self.db_name, "wearable_devices", data)
            return self._db_manager.query_one(
                self.db_name,
                "SELECT * FROM wearable_devices WHERE id = ?",
                (row_id,),
            )
        else:
            # 降级模式
            columns = list(data.keys())
            placeholders = ", ".join("?" for _ in columns)
            values = tuple(data[col] for col in columns)
            sql = f"INSERT INTO wearable_devices ({', '.join(columns)}) VALUES ({placeholders})"
            self._execute_query(sql, values, write=True)
            return self.get_device(data["device_id"])

    def update_device(self, device_id: str, updates: Dict[str, Any]) -> bool:
        """更新设备信息"""
        if not updates:
            return False
        updates["updated_at"] = datetime.now().isoformat()

        if self._has_shared_layer():
            rows = self._db_manager.update(
                self.db_name,
                "wearable_devices",
                updates,
                "device_id = ?",
                (device_id,),
            )
            return rows > 0
        else:
            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            params = list(updates.values()) + [device_id]
            sql = f"UPDATE wearable_devices SET {set_clause} WHERE device_id = ?"
            rows = self._execute_query(sql, tuple(params), write=True)
            return rows > 0

    def delete_device(self, device_id: str) -> bool:
        """删除设备"""
        if self._has_shared_layer():
            rows = self._db_manager.delete(
                self.db_name,
                "wearable_devices",
                "device_id = ?",
                (device_id,),
            )
            return rows > 0
        else:
            sql = "DELETE FROM wearable_devices WHERE device_id = ?"
            rows = self._execute_query(sql, (device_id,), write=True)
            return rows > 0

    # ========================================================================
    # 健康数据管理
    # ========================================================================

    def query_health_data(
        self,
        device_id: Optional[str] = None,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """查询健康数据，返回 (数据列表, 总数)"""
        conditions = []
        params: List[Any] = []

        if device_id:
            conditions.append("device_id = ?")
            params.append(device_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if data_type:
            conditions.append("data_type = ?")
            params.append(data_type)
        if start_time:
            conditions.append("recorded_at >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("recorded_at <= ?")
            params.append(end_time)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        count_sql = f"SELECT COUNT(*) as cnt FROM wearable_health_data {where_clause}"
        count_result = self._execute_query(count_sql, tuple(params))
        total = count_result[0]["cnt"] if count_result else 0

        query_sql = f"""
            SELECT * FROM wearable_health_data {where_clause}
            ORDER BY recorded_at DESC
            LIMIT {int(limit)} OFFSET {int(offset)}
        """
        data = self._execute_query(query_sql, tuple(params))

        return data, total

    def insert_health_data(self, health_data: Dict[str, Any]) -> int:
        """插入一条健康数据，返回自增 ID"""
        now = datetime.now().isoformat()
        data = {
            "device_id": health_data["device_id"],
            "user_id": health_data.get("user_id", "default"),
            "data_type": health_data["data_type"],
            "value": health_data.get("value", 0),
            "unit": health_data.get("unit", ""),
            "recorded_at": health_data.get("recorded_at", now),
            "source": health_data.get("source", "device"),
            "quality": health_data.get("quality", "good"),
            "created_at": now,
        }

        if self._has_shared_layer():
            return self._db_manager.insert(self.db_name, "wearable_health_data", data)
        else:
            columns = list(data.keys())
            placeholders = ", ".join("?" for _ in columns)
            values = tuple(data[col] for col in columns)
            sql = f"INSERT INTO wearable_health_data ({', '.join(columns)}) VALUES ({placeholders})"
            self._execute_query(sql, values, write=True)
            return 0  # 降级模式不返回 rowid

    def batch_insert_health_data(self, records: List[Dict[str, Any]]) -> int:
        """批量插入健康数据，返回插入行数"""
        if not records:
            return 0

        now = datetime.now().isoformat()
        rows = [
            (
                r["device_id"],
                r.get("user_id", "default"),
                r["data_type"],
                r.get("value", 0),
                r.get("unit", ""),
                r.get("recorded_at", now),
                r.get("source", "device"),
                r.get("quality", "good"),
                now,
            )
            for r in records
        ]

        if self._has_shared_layer():
            sql = """
                INSERT INTO wearable_health_data
                (device_id, user_id, data_type, value, unit, recorded_at, source, quality, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            return self._db_manager.execute_many(self.db_name, sql, rows)
        else:
            sql = """
                INSERT INTO wearable_health_data
                (device_id, user_id, data_type, value, unit, recorded_at, source, quality, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            total = 0
            for row in rows:
                self._execute_query(sql, row, write=True)
                total += 1
            return total

    # ========================================================================
    # 通知管理
    # ========================================================================

    def list_notifications(
        self,
        device_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        type_: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """查询通知列表"""
        conditions = []
        params: List[Any] = []

        if device_id:
            conditions.append("device_id = ?")
            params.append(device_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if type_:
            conditions.append("type = ?")
            params.append(type_)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        count_sql = f"SELECT COUNT(*) as cnt FROM wearable_notifications {where_clause}"
        count_result = self._execute_query(count_sql, tuple(params))
        total = count_result[0]["cnt"] if count_result else 0

        query_sql = f"""
            SELECT * FROM wearable_notifications {where_clause}
            ORDER BY created_at DESC
            LIMIT {int(limit)} OFFSET {int(offset)}
        """
        notifications = self._execute_query(query_sql, tuple(params))

        return notifications, total

    def create_notification(self, notif_data: Dict[str, Any]) -> Dict[str, Any]:
        """创建通知"""
        import uuid
        now = datetime.now().isoformat()
        data = {
            "notification_id": notif_data.get("notification_id", uuid.uuid4().hex),
            "device_id": notif_data["device_id"],
            "user_id": notif_data.get("user_id", "default"),
            "title": notif_data.get("title", ""),
            "content": notif_data.get("content", ""),
            "type": notif_data.get("type", "system"),
            "status": notif_data.get("status", "pending"),
            "source": notif_data.get("source", "api"),
            "delivered_at": notif_data.get("delivered_at"),
            "created_at": now,
        }

        if self._has_shared_layer():
            row_id = self._db_manager.insert(self.db_name, "wearable_notifications", data)
            return self._db_manager.query_one(
                self.db_name,
                "SELECT * FROM wearable_notifications WHERE id = ?",
                (row_id,),
            )
        else:
            columns = list(data.keys())
            placeholders = ", ".join("?" for _ in columns)
            values = tuple(data[col] for col in columns)
            sql = f"INSERT INTO wearable_notifications ({', '.join(columns)}) VALUES ({placeholders})"
            self._execute_query(sql, values, write=True)
            return data

    def update_notification_status(
        self,
        notification_id: str,
        status: str,
        delivered_at: Optional[str] = None,
    ) -> bool:
        """更新通知状态"""
        updates: Dict[str, Any] = {"status": status}
        if delivered_at is not None:
            updates["delivered_at"] = delivered_at

        if self._has_shared_layer():
            rows = self._db_manager.update(
                self.db_name,
                "wearable_notifications",
                updates,
                "notification_id = ?",
                (notification_id,),
            )
            return rows > 0
        else:
            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            params = list(updates.values()) + [notification_id]
            sql = f"UPDATE wearable_notifications SET {set_clause} WHERE notification_id = ?"
            rows = self._execute_query(sql, tuple(params), write=True)
            return rows > 0

    # ========================================================================
    # 设备配置管理
    # ========================================================================

    def get_settings(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备配置"""
        sql = "SELECT * FROM wearable_settings WHERE device_id = ?"
        result = self._execute_query(sql, (device_id,))
        if not result:
            return None
        settings = result[0]
        # 解析 settings_json
        if isinstance(settings.get("settings_json"), str):
            try:
                settings["settings_json"] = json.loads(settings["settings_json"])
            except (json.JSONDecodeError, TypeError):
                settings["settings_json"] = {}
        return settings

    def upsert_settings(self, device_id: str, user_id: str, settings_json: Dict[str, Any]) -> int:
        """插入或更新设备配置，返回记录 ID"""
        now = datetime.now().isoformat()
        settings_str = json.dumps(settings_json, ensure_ascii=False)

        existing = self.get_settings(device_id)
        if existing:
            if self._has_shared_layer():
                self._db_manager.update(
                    self.db_name,
                    "wearable_settings",
                    {"settings_json": settings_str, "updated_at": now},
                    "device_id = ?",
                    (device_id,),
                )
                return existing["id"]
            else:
                sql = "UPDATE wearable_settings SET settings_json = ?, updated_at = ? WHERE device_id = ?"
                self._execute_query(sql, (settings_str, now, device_id), write=True)
                return existing["id"]
        else:
            data = {
                "device_id": device_id,
                "user_id": user_id,
                "settings_json": settings_str,
                "updated_at": now,
            }
            if self._has_shared_layer():
                return self._db_manager.insert(self.db_name, "wearable_settings", data)
            else:
                columns = list(data.keys())
                placeholders = ", ".join("?" for _ in columns)
                values = tuple(data[col] for col in columns)
                sql = f"INSERT INTO wearable_settings ({', '.join(columns)}) VALUES ({placeholders})"
                self._execute_query(sql, values, write=True)
                return 0

    # ========================================================================
    # 统计与健康检查
    # ========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取可穿戴设备统计概览"""
        device_count_sql = "SELECT COUNT(*) as cnt FROM wearable_devices"
        health_count_sql = "SELECT COUNT(*) as cnt FROM wearable_health_data"
        notif_count_sql = "SELECT COUNT(*) as cnt FROM wearable_notifications"

        device_result = self._execute_query(device_count_sql)
        health_result = self._execute_query(health_count_sql)
        notif_result = self._execute_query(notif_count_sql)

        return {
            "device_count": device_result[0]["cnt"] if device_result else 0,
            "health_data_count": health_result[0]["cnt"] if health_result else 0,
            "notification_count": notif_result[0]["cnt"] if notif_result else 0,
        }

    def health_check(self) -> Dict[str, Any]:
        """服务健康检查"""
        try:
            if self._has_shared_layer():
                return self._db_manager.health_check(self.db_name)
            else:
                # 降级模式健康检查
                self._execute_query("SELECT 1")
                tables = self._execute_query(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
                return {
                    "status": "healthy",
                    "tables": len(tables),
                    "table_names": [t["name"] for t in tables],
                    "mode": "fallback_local",
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }


# 全局单例
_instance: Optional[WearableService] = None


def get_wearable_service() -> WearableService:
    """获取可穿戴设备服务单例"""
    global _instance
    if _instance is None:
        _instance = WearableService()
    return _instance
