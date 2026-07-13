"""
M6 硬件外设 - 数据仓库

P1-5 改造：集中管理 sensor_data / device_status_history 表的 SQL 操作，
所有方法接受外部传入的 sqlite3.Connection，以支持事务。
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SensorDataRepository:
    """传感器数据仓库"""

    @staticmethod
    def insert_batch(
        device_id: str,
        readings: Dict[str, Dict[str, Any]],
        conn: sqlite3.Connection,
    ) -> None:
        """批量插入传感器读数

        Args:
            device_id: 设备 ID
            readings: 传感器读数字典，格式 {sensor_type: {"value": ..., "unit": ..., "quality": ...}}
            conn: 数据库连接（由调用方管理事务）
        """
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        for sensor_type, reading in readings.items():
            value = reading.get("value")
            value_text = None
            value_num = None

            if isinstance(value, (int, float)):
                value_num = float(value)
            elif isinstance(value, bool):
                value_num = 1.0 if value else 0.0
            else:
                value_text = str(value) if value is not None else None

            cursor.execute("""
                INSERT INTO sensor_data
                (device_id, sensor_type, value, value_text, unit, quality, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                device_id,
                sensor_type,
                value_num,
                value_text,
                reading.get("unit", ""),
                reading.get("quality", 100),
                now,
            ))

    @staticmethod
    def query_history(
        device_id: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        sensor_type: Optional[str] = None,
        limit: int = 1000,
        *,
        conn: sqlite3.Connection,
    ) -> List[Dict[str, Any]]:
        """查询传感器历史数据"""
        cursor = conn.cursor()

        query = (
            "SELECT device_id, sensor_type, value, value_text, unit, quality, timestamp "
            "FROM sensor_data WHERE device_id = ?"
        )
        params: List[Any] = [device_id]

        if sensor_type:
            query += " AND sensor_type = ?"
            params.append(sensor_type)

        if start:
            query += " AND timestamp >= ?"
            params.append(start.isoformat())

        if end:
            query += " AND timestamp <= ?"
            params.append(end.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        result = []
        for row in rows:
            result.append({
                "device_id": row[0],
                "sensor_type": row[1],
                "value": row[2] if row[2] is not None else row[3],
                "unit": row[4],
                "quality": row[5],
                "timestamp": row[6],
            })
        return result

    @staticmethod
    def query_latest(
        device_id: str,
        conn: sqlite3.Connection,
    ) -> List[Dict[str, Any]]:
        """查询某设备最新的所有传感器读数（按 sensor_type 各取最新一条）"""
        cursor = conn.cursor()
        cursor.execute("""
            SELECT device_id, sensor_type, value, value_text, unit, quality, timestamp
            FROM sensor_data
            WHERE device_id = ?
              AND timestamp = (
                  SELECT MAX(timestamp)
                  FROM sensor_data AS sub
                  WHERE sub.device_id = sensor_data.device_id
                    AND sub.sensor_type = sensor_data.sensor_type
              )
        """, (device_id,))
        rows = cursor.fetchall()
        return [
            {
                "device_id": row[0],
                "sensor_type": row[1],
                "value": row[2] if row[2] is not None else row[3],
                "unit": row[4],
                "quality": row[5],
                "timestamp": row[6],
            }
            for row in rows
        ]

    @staticmethod
    def cleanup_old(
        days: int,
        conn: sqlite3.Connection,
    ) -> int:
        """清理过期传感器数据

        Returns:
            删除的行数
        """
        cursor = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute("DELETE FROM sensor_data WHERE timestamp < ?", (cutoff,))
        return cursor.rowcount


class DeviceStatusRepository:
    """设备状态历史仓库"""

    @staticmethod
    def insert(
        device_id: str,
        status: str,
        battery: Optional[float],
        signal: Optional[int],
        conn: sqlite3.Connection,
    ) -> None:
        """插入设备状态记录"""
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO device_status_history
            (device_id, status, battery, signal_strength, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (device_id, status, battery, signal, now))

    @staticmethod
    def query_history(
        device_id: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 500,
        *,
        conn: sqlite3.Connection,
    ) -> List[Dict[str, Any]]:
        """查询设备状态历史"""
        cursor = conn.cursor()

        query = (
            "SELECT device_id, status, battery, signal_strength, timestamp "
            "FROM device_status_history WHERE device_id = ?"
        )
        params: List[Any] = [device_id]

        if start:
            query += " AND timestamp >= ?"
            params.append(start.isoformat())

        if end:
            query += " AND timestamp <= ?"
            params.append(end.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {
                "device_id": row[0],
                "status": row[1],
                "battery": row[2],
                "signal_strength": row[3],
                "timestamp": row[4],
            }
            for row in rows
        ]

    @staticmethod
    def query_latest(
        device_id: str,
        conn: sqlite3.Connection,
    ) -> Optional[Dict[str, Any]]:
        """查询某设备最新的一条状态记录"""
        cursor = conn.cursor()
        cursor.execute("""
            SELECT device_id, status, battery, signal_strength, timestamp
            FROM device_status_history
            WHERE device_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (device_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "device_id": row[0],
            "status": row[1],
            "battery": row[2],
            "signal_strength": row[3],
            "timestamp": row[4],
        }

    @staticmethod
    def cleanup_old(
        days: int,
        conn: sqlite3.Connection,
    ) -> int:
        """清理过期设备状态数据

        Returns:
            删除的行数
        """
        cursor = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute("DELETE FROM device_status_history WHERE timestamp < ?", (cutoff,))
        return cursor.rowcount
