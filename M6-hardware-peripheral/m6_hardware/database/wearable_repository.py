"""
可穿戴设备仓储层
==============

基于 Repository 模式，所有方法接受外部传入的 sqlite3.Connection，
以支持事务和连接复用。

包含 4 个仓储类：
- WearableDeviceRepository: 可穿戴设备管理
- WearableHealthRepository: 健康数据管理
- WearableNotificationRepository: 通知推送管理
- WearableSettingsRepository: 设备配置管理

P0 批次迁移：手表/可穿戴数据从 M8 迁到 M6
"""

from __future__ import annotations

import json
import sqlite3
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# 可穿戴设备仓储
# ============================================================================

class WearableDeviceRepository:
    """可穿戴设备仓储"""

    @staticmethod
    def create(
        device_id: str,
        user_id: str,
        name: str,
        device_type: str,
        brand: str,
        model: str,
        mac_address: str,
        status: str,
        battery_level: Optional[float],
        firmware_version: str,
        *,
        conn: sqlite3.Connection,
    ) -> int:
        """创建设备，返回自增 ID"""
        now = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO wearable_devices (
                device_id, user_id, name, device_type, brand, model,
                mac_address, status, battery_level, firmware_version,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id, user_id, name, device_type, brand, model,
                mac_address, status, battery_level, firmware_version,
                now, now,
            ),
        )
        conn.commit()
        return cursor.lastrowid

    @staticmethod
    def get_by_device_id(device_id: str, *, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        """根据 device_id 获取设备"""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM wearable_devices WHERE device_id = ?",
            (device_id,),
        )
        row = cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None

    @staticmethod
    def get_by_id(device_db_id: int, *, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        """根据自增 ID 获取设备"""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM wearable_devices WHERE id = ?",
            (device_db_id,),
        )
        row = cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None

    @staticmethod
    def list_devices(
        user_id: Optional[str] = None,
        device_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        *,
        conn: sqlite3.Connection,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        查询设备列表，支持过滤

        Returns:
            (设备列表, 总数)
        """
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
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM wearable_devices {where_clause}", params)
        total = cursor.fetchone()[0]

        # 查询分页数据
        query = f"""
            SELECT * FROM wearable_devices {where_clause}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        cursor.execute(query, params)
        rows = cursor.fetchall()
        devices = [_row_to_dict(cursor, row) for row in rows]

        return devices, total

    @staticmethod
    def update(
        device_id: str,
        updates: Dict[str, Any],
        *,
        conn: sqlite3.Connection,
    ) -> bool:
        """更新设备信息，返回是否成功"""
        if not updates:
            return False

        updates["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        params = list(updates.values()) + [device_id]

        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE wearable_devices SET {set_clause} WHERE device_id = ?",
            params,
        )
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def delete(device_id: str, *, conn: sqlite3.Connection) -> bool:
        """删除设备，返回是否成功"""
        cursor = conn.cursor()
        cursor.execute("DELETE FROM wearable_devices WHERE device_id = ?", (device_id,))
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def count(*, conn: sqlite3.Connection) -> int:
        """统计设备总数"""
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM wearable_devices")
        return cursor.fetchone()[0]


# ============================================================================
# 健康数据仓储
# ============================================================================

class WearableHealthRepository:
    """健康数据仓储"""

    @staticmethod
    def insert(
        device_id: str,
        user_id: str,
        data_type: str,
        value: float,
        unit: str,
        recorded_at: str,
        source: str,
        quality: str,
        *,
        conn: sqlite3.Connection,
    ) -> int:
        """插入一条健康数据，返回自增 ID"""
        now = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO wearable_health_data (
                device_id, user_id, data_type, value, unit,
                recorded_at, source, quality, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (device_id, user_id, data_type, value, unit, recorded_at, source, quality, now),
        )
        conn.commit()
        return cursor.lastrowid

    @staticmethod
    def insert_batch(
        records: List[Dict[str, Any]],
        *,
        conn: sqlite3.Connection,
    ) -> int:
        """
        批量插入健康数据

        Args:
            records: 每条记录包含 device_id, user_id, data_type, value, unit, recorded_at, source, quality
        """
        if not records:
            return 0

        now = datetime.now().isoformat()
        cursor = conn.cursor()
        rows = [
            (
                r["device_id"], r.get("user_id", "default"), r["data_type"],
                r["value"], r.get("unit", ""), r.get("recorded_at", now),
                r.get("source", "device"), r.get("quality", "good"), now,
            )
            for r in records
        ]
        cursor.executemany(
            """
            INSERT INTO wearable_health_data (
                device_id, user_id, data_type, value, unit,
                recorded_at, source, quality, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        return cursor.rowcount

    @staticmethod
    def query(
        device_id: Optional[str] = None,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        *,
        conn: sqlite3.Connection,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        查询健康数据

        Returns:
            (数据列表, 总数)
        """
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

        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM wearable_health_data {where_clause}", params)
        total = cursor.fetchone()[0]

        query = f"""
            SELECT * FROM wearable_health_data {where_clause}
            ORDER BY recorded_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [_row_to_dict(cursor, row) for row in rows], total

    @staticmethod
    def get_latest(
        device_id: str,
        data_type: Optional[str] = None,
        *,
        conn: sqlite3.Connection,
    ) -> List[Dict[str, Any]]:
        """获取设备最新的健康数据（每类一条）"""
        cursor = conn.cursor()
        if data_type:
            cursor.execute(
                """
                SELECT * FROM wearable_health_data
                WHERE device_id = ? AND data_type = ?
                ORDER BY recorded_at DESC LIMIT 1
                """,
                (device_id, data_type),
            )
        else:
            cursor.execute(
                """
                SELECT t1.* FROM wearable_health_data t1
                INNER JOIN (
                    SELECT data_type, MAX(recorded_at) as max_time
                    FROM wearable_health_data
                    WHERE device_id = ?
                    GROUP BY data_type
                ) t2 ON t1.data_type = t2.data_type AND t1.recorded_at = t2.max_time
                WHERE t1.device_id = ?
                """,
                (device_id, device_id),
            )
        rows = cursor.fetchall()
        return [_row_to_dict(cursor, row) for row in rows]

    @staticmethod
    def cleanup_old(days: int, *, conn: sqlite3.Connection) -> int:
        """清理过期数据，返回删除行数"""
        cursor = conn.cursor()
        cursor.execute(
            f"""
            DELETE FROM wearable_health_data
            WHERE recorded_at < datetime('now', '-{days} days')
            """
        )
        conn.commit()
        return cursor.rowcount


# ============================================================================
# 通知推送仓储
# ============================================================================

class WearableNotificationRepository:
    """通知推送仓储"""

    @staticmethod
    def create(
        notification_id: str,
        device_id: str,
        user_id: str,
        title: str,
        content: str,
        type_: str,
        status: str,
        source: str,
        *,
        conn: sqlite3.Connection,
    ) -> int:
        """创建通知，返回自增 ID"""
        now = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO wearable_notifications (
                notification_id, device_id, user_id, title, content,
                type, status, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (notification_id, device_id, user_id, title, content, type_, status, source, now),
        )
        conn.commit()
        return cursor.lastrowid

    @staticmethod
    def get_by_id(notify_id: int, *, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        """根据 ID 获取通知"""
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM wearable_notifications WHERE id = ?", (notify_id,))
        row = cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None

    @staticmethod
    def get_by_notification_id(notification_id: str, *, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        """根据通知唯一 ID 获取"""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM wearable_notifications WHERE notification_id = ?",
            (notification_id,),
        )
        row = cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None

    @staticmethod
    def list_notifications(
        device_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        type_: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        *,
        conn: sqlite3.Connection,
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

        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM wearable_notifications {where_clause}", params)
        total = cursor.fetchone()[0]

        query = f"""
            SELECT * FROM wearable_notifications {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [_row_to_dict(cursor, row) for row in rows], total

    @staticmethod
    def update_status(
        notification_id: str,
        status: str,
        *,
        delivered_at: Optional[str] = None,
        conn: sqlite3.Connection,
    ) -> bool:
        """更新通知状态"""
        updates: Dict[str, Any] = {"status": status}
        if delivered_at is not None:
            updates["delivered_at"] = delivered_at

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        params = list(updates.values()) + [notification_id]

        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE wearable_notifications SET {set_clause} WHERE notification_id = ?",
            params,
        )
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def cleanup_old(days: int, *, conn: sqlite3.Connection) -> int:
        """清理过期通知"""
        cursor = conn.cursor()
        cursor.execute(
            f"""
            DELETE FROM wearable_notifications
            WHERE created_at < datetime('now', '-{days} days')
            """
        )
        conn.commit()
        return cursor.rowcount


# ============================================================================
# 设备配置仓储
# ============================================================================

class WearableSettingsRepository:
    """设备配置仓储"""

    @staticmethod
    def get_by_device_id(device_id: str, *, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        """获取设备配置"""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM wearable_settings WHERE device_id = ?",
            (device_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        result = _row_to_dict(cursor, row)
        # settings_json 字段从字符串解析为 dict
        if isinstance(result.get("settings_json"), str):
            try:
                result["settings_json"] = json.loads(result["settings_json"])
            except (json.JSONDecodeError, TypeError):
                result["settings_json"] = {}
        return result

    @staticmethod
    def upsert(
        device_id: str,
        user_id: str,
        settings_json: Dict[str, Any],
        *,
        conn: sqlite3.Connection,
    ) -> int:
        """
        插入或更新设备配置（Upsert）
        返回记录 ID
        """
        now = datetime.now().isoformat()
        settings_str = json.dumps(settings_json, ensure_ascii=False)

        cursor = conn.cursor()
        # 先查是否存在
        cursor.execute("SELECT id FROM wearable_settings WHERE device_id = ?", (device_id,))
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "UPDATE wearable_settings SET settings_json = ?, updated_at = ? WHERE device_id = ?",
                (settings_str, now, device_id),
            )
            conn.commit()
            return existing[0]
        else:
            cursor.execute(
                """
                INSERT INTO wearable_settings (device_id, user_id, settings_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (device_id, user_id, settings_str, now),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def delete(device_id: str, *, conn: sqlite3.Connection) -> bool:
        """删除设备配置"""
        cursor = conn.cursor()
        cursor.execute("DELETE FROM wearable_settings WHERE device_id = ?", (device_id,))
        conn.commit()
        return cursor.rowcount > 0


# ============================================================================
# 工具函数
# ============================================================================

def _row_to_dict(cursor: sqlite3.Cursor, row: sqlite3.Row | tuple) -> Dict[str, Any]:
    """将数据库行转换为字典"""
    if isinstance(row, dict):
        return row
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))
