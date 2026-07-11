"""
M6 硬件外设 - 数据采集服务
后台定时任务，采集所有在线设备的传感器数据并存入 SQLite
"""

import asyncio
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..config import get_config
from .device_manager import get_device_manager


class DataCollector:
    """数据采集服务

    定期采集所有在线设备的传感器数据，存储到 SQLite 数据库，
    支持历史数据查询。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._config = get_config()
        self._device_manager = get_device_manager()
        self._db_path = self._config.database_path
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._initialized = True
        self._init_database()

    def _init_database(self):
        """初始化数据库表结构"""
        db_dir = Path(self._db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()

            # 传感器数据表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sensor_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    sensor_type TEXT NOT NULL,
                    value REAL,
                    value_text TEXT,
                    unit TEXT,
                    quality INTEGER,
                    timestamp DATETIME NOT NULL
                )
            """)

            # 设备状态历史表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    battery REAL,
                    signal_strength INTEGER,
                    timestamp DATETIME NOT NULL
                )
            """)

            # 索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sensor_device_time
                ON sensor_data(device_id, timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sensor_type_time
                ON sensor_data(sensor_type, timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_status_device_time
                ON device_status_history(device_id, timestamp)
            """)

            conn.commit()
        finally:
            conn.close()

    async def start(self):
        """启动数据采集服务"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._collection_loop())

    async def stop(self):
        """停止数据采集服务"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _collection_loop(self):
        """采集循环"""
        interval = self._config.collection_interval
        while self._running:
            try:
                self._collect_once()
            except Exception as e:
                print(f"[DataCollector] 采集异常: {e}")
            await asyncio.sleep(interval)

    def _collect_once(self):
        """执行一次数据采集"""
        # 驱动所有设备步进
        self._device_manager.tick_all()

        # 采集并存储传感器数据
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            devices = self._device_manager.list_devices()
            for dev_data in devices:
                device_id = dev_data["device_id"]

                # 存储设备状态
                cursor.execute("""
                    INSERT INTO device_status_history
                    (device_id, status, battery, signal_strength, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    device_id,
                    dev_data["status"],
                    dev_data.get("battery"),
                    dev_data.get("signal_strength"),
                    now,
                ))

                # 存储传感器数据
                sensors = dev_data.get("sensors", {})
                for sensor_type, reading in sensors.items():
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

            conn.commit()

            # 清理过期数据
            self._cleanup_old_data(cursor)
            conn.commit()
        finally:
            conn.close()

    def _cleanup_old_data(self, cursor):
        """清理过期历史数据"""
        retention_days = self._config.history_retention_days
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

        cursor.execute("DELETE FROM sensor_data WHERE timestamp < ?", (cutoff,))
        cursor.execute("DELETE FROM device_status_history WHERE timestamp < ?", (cutoff,))

    def get_sensor_history(
        self,
        device_id: str,
        sensor_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """查询传感器历史数据

        Args:
            device_id: 设备ID
            sensor_type: 传感器类型（可选）
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）
            limit: 最大返回条数

        Returns:
            历史数据列表
        """
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()

            query = "SELECT device_id, sensor_type, value, value_text, unit, quality, timestamp FROM sensor_data WHERE device_id = ?"
            params: List[Any] = [device_id]

            if sensor_type:
                query += " AND sensor_type = ?"
                params.append(sensor_type)

            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time.isoformat())

            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time.isoformat())

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
        finally:
            conn.close()

    def get_latest_sensor_data(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备最新传感器数据

        Args:
            device_id: 设备ID

        Returns:
            最新传感器数据集合
        """
        # 直接从设备管理器获取（内存中的最新数据）
        dev = self._device_manager.get_device(device_id)
        if not dev:
            return None
        return {
            "device_id": device_id,
            "sensors": dev.get("sensors", {}),
            "collected_at": datetime.now().isoformat(),
        }

    def get_status_history(
        self,
        device_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """查询设备状态历史

        Args:
            device_id: 设备ID
            start_time: 开始时间
            end_time: 结束时间
            limit: 最大条数

        Returns:
            状态历史列表
        """
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()

            query = "SELECT device_id, status, battery, signal_strength, timestamp FROM device_status_history WHERE device_id = ?"
            params: List[Any] = [device_id]

            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time.isoformat())

            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time.isoformat())

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            result = []
            for row in rows:
                result.append({
                    "device_id": row[0],
                    "status": row[1],
                    "battery": row[2],
                    "signal_strength": row[3],
                    "timestamp": row[4],
                })

            return result
        finally:
            conn.close()


def get_data_collector() -> DataCollector:
    """获取数据采集服务单例"""
    return DataCollector()
