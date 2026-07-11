"""设备注册表（抽象 + 内存 + SQLite 持久化实现）.

提供设备注册、注销、查询、状态更新等功能。
- DeviceRegistry: 抽象基类
- InMemoryDeviceRegistry: 内存实现（默认，轻量）
- SqliteDeviceRegistry: SQLite 持久化实现（生产环境）
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Optional

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class DeviceInfo:
    """设备信息.

    Attributes:
        device_id: 设备唯一标识.
        name: 设备名称.
        device_type: 设备类型（desktop/laptop/smartwatch/drone/ring）.
        status: 设备状态（online/offline/unknown）.
        last_seen: 最后活跃时间戳.
        metadata: 附加元数据（JSON）.
        created_at: 注册时间戳.
        updated_at: 最后更新时间戳.
    """
    device_id: str
    name: str = ""
    device_type: str = "unknown"
    status: str = "online"
    last_seen: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class DeviceRegistry(ABC):
    """设备注册表抽象基类."""

    @abstractmethod
    async def register_device(self, device: DeviceInfo) -> bool:
        """注册设备.

        Args:
            device: 设备信息.

        Returns:
            True 表示注册成功.
        """
        ...

    @abstractmethod
    async def unregister_device(self, device_id: str) -> bool:
        """注销设备.

        Args:
            device_id: 设备ID.

        Returns:
            True 表示注销成功.
        """
        ...

    @abstractmethod
    async def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """获取设备信息.

        Args:
            device_id: 设备ID.

        Returns:
            设备信息，不存在返回 None.
        """
        ...

    @abstractmethod
    async def list_devices(self, status: Optional[str] = None) -> list[DeviceInfo]:
        """列出设备.

        Args:
            status: 按状态过滤，None 表示全部.

        Returns:
            设备信息列表.
        """
        ...

    @abstractmethod
    async def update_device_status(self, device_id: str, status: str) -> bool:
        """更新设备状态.

        Args:
            device_id: 设备ID.
            status: 新状态.

        Returns:
            True 表示更新成功.
        """
        ...

    @abstractmethod
    async def clear_all(self) -> int:
        """清空所有设备.

        Returns:
            清除的设备数量.
        """
        ...


class InMemoryDeviceRegistry(DeviceRegistry):
    """内存设备注册表.

    轻量实现，服务重启后数据丢失。
    适用于开发测试和单实例场景。
    """

    def __init__(self) -> None:
        """初始化内存注册表."""
        self._devices: dict[str, DeviceInfo] = {}
        logger.info("in_memory_device_registry.initialized")

    async def register_device(self, device: DeviceInfo) -> bool:
        """注册设备."""
        if device.device_id in self._devices:
            # 更新
            existing = self._devices[device.device_id]
            device.created_at = existing.created_at
            device.updated_at = time.time()
        self._devices[device.device_id] = device
        logger.debug(
            "in_memory_device_registry.registered",
            device_id=device.device_id,
            device_type=device.device_type,
        )
        return True

    async def unregister_device(self, device_id: str) -> bool:
        """注销设备."""
        if device_id in self._devices:
            del self._devices[device_id]
            logger.debug("in_memory_device_registry.unregistered", device_id=device_id)
            return True
        return False

    async def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """获取设备信息."""
        return self._devices.get(device_id)

    async def list_devices(self, status: Optional[str] = None) -> list[DeviceInfo]:
        """列出设备."""
        devices = list(self._devices.values())
        if status:
            devices = [d for d in devices if d.status == status]
        return devices

    async def update_device_status(self, device_id: str, status: str) -> bool:
        """更新设备状态."""
        device = self._devices.get(device_id)
        if not device:
            return False
        device.status = status
        device.last_seen = time.time()
        device.updated_at = time.time()
        return True

    async def clear_all(self) -> int:
        """清空所有设备."""
        count = len(self._devices)
        self._devices.clear()
        logger.info("in_memory_device_registry.cleared", count=count)
        return count


class SqliteDeviceRegistry(DeviceRegistry):
    """基于 SQLite 的设备注册表.

    持久化存储，服务重启后数据不丢失。
    适用于生产环境和多实例场景。
    """

    def __init__(self, db_path: str) -> None:
        """初始化 SQLite 注册表.

        Args:
            db_path: SQLite 数据库文件路径.
        """
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        # 内存缓存，加速读操作
        self._cache: dict[str, DeviceInfo] = {}
        logger.info("sqlite_device_registry.initialized", db_path=db_path)

    async def initialize(self) -> None:
        """初始化数据库连接和表结构."""
        # 确保目录存在
        db_dir = os.path.dirname(self._db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                device_type TEXT DEFAULT 'unknown',
                status TEXT DEFAULT 'online',
                last_seen REAL,
                metadata TEXT DEFAULT '{}',
                created_at REAL,
                updated_at REAL
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status)"
        )
        await self._db.commit()

        # 加载到内存缓存
        await self._load_to_cache()
        logger.info("sqlite_device_registry.ready", cached_count=len(self._cache))

    async def _load_to_cache(self) -> None:
        """从数据库加载所有设备到内存缓存."""
        assert self._db is not None
        cursor = await self._db.execute("SELECT * FROM devices")
        rows = await cursor.fetchall()
        for row in rows:
            device = self._row_to_device(row)
            self._cache[device.device_id] = device
        logger.debug("sqlite_device_registry.cache_loaded", count=len(self._cache))

    def _row_to_device(self, row: tuple) -> DeviceInfo:
        """将数据库行转换为 DeviceInfo."""
        (
            device_id, name, device_type, status,
            last_seen, metadata_json, created_at, updated_at,
        ) = row
        try:
            metadata = json.loads(metadata_json) if metadata_json else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        return DeviceInfo(
            device_id=device_id,
            name=name or "",
            device_type=device_type or "unknown",
            status=status or "unknown",
            last_seen=last_seen or 0.0,
            metadata=metadata,
            created_at=created_at or 0.0,
            updated_at=updated_at or 0.0,
        )

    async def _ensure_db(self) -> None:
        """确保数据库已初始化."""
        if self._db is None:
            await self.initialize()

    async def register_device(self, device: DeviceInfo) -> bool:
        """注册设备."""
        await self._ensure_db()
        assert self._db is not None

        now = time.time()
        device.updated_at = now

        if device.device_id in self._cache:
            # 更新
            existing = self._cache[device.device_id]
            device.created_at = existing.created_at
            await self._db.execute(
                """
                UPDATE devices SET
                    name=?, device_type=?, status=?, last_seen=?,
                    metadata=?, updated_at=?
                WHERE device_id=?
                """,
                (
                    device.name, device.device_type, device.status,
                    device.last_seen, json.dumps(device.metadata, ensure_ascii=False),
                    now, device.device_id,
                ),
            )
        else:
            # 新注册
            device.created_at = now
            await self._db.execute(
                """
                INSERT INTO devices
                    (device_id, name, device_type, status, last_seen,
                     metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device.device_id, device.name, device.device_type,
                    device.status, device.last_seen,
                    json.dumps(device.metadata, ensure_ascii=False),
                    now, now,
                ),
            )

        await self._db.commit()
        self._cache[device.device_id] = device
        logger.debug("sqlite_device_registry.registered", device_id=device.device_id)
        return True

    async def unregister_device(self, device_id: str) -> bool:
        """注销设备."""
        await self._ensure_db()
        assert self._db is not None

        if device_id not in self._cache:
            return False

        await self._db.execute(
            "DELETE FROM devices WHERE device_id=?",
            (device_id,),
        )
        await self._db.commit()
        del self._cache[device_id]
        logger.debug("sqlite_device_registry.unregistered", device_id=device_id)
        return True

    async def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """获取设备信息（从缓存读取）."""
        await self._ensure_db()
        return self._cache.get(device_id)

    async def list_devices(self, status: Optional[str] = None) -> list[DeviceInfo]:
        """列出设备（从缓存读取）."""
        await self._ensure_db()
        devices = list(self._cache.values())
        if status:
            devices = [d for d in devices if d.status == status]
        return devices

    async def update_device_status(self, device_id: str, status: str) -> bool:
        """更新设备状态."""
        await self._ensure_db()
        assert self._db is not None

        device = self._cache.get(device_id)
        if not device:
            return False

        now = time.time()
        device.status = status
        device.last_seen = now
        device.updated_at = now

        await self._db.execute(
            "UPDATE devices SET status=?, last_seen=?, updated_at=? WHERE device_id=?",
            (status, now, now, device_id),
        )
        await self._db.commit()
        return True

    async def clear_all(self) -> int:
        """清空所有设备."""
        await self._ensure_db()
        assert self._db is not None

        count = len(self._cache)
        await self._db.execute("DELETE FROM devices")
        await self._db.commit()
        self._cache.clear()
        logger.info("sqlite_device_registry.cleared", count=count)
        return count

    async def close(self) -> None:
        """关闭数据库连接."""
        if self._db:
            await self._db.close()
            self._db = None
            self._cache.clear()
            logger.info("sqlite_device_registry.closed")


def create_device_registry(
    registry_type: str = "memory",
    db_path: str = "",
) -> DeviceRegistry:
    """工厂函数：创建设备注册表.

    Args:
        registry_type: 类型（memory / sqlite）.
        db_path: SQLite 数据库路径（sqlite 类型时必填）.

    Returns:
        DeviceRegistry 实例.
    """
    if registry_type == "sqlite":
        if not db_path:
            raise ValueError("SqliteDeviceRegistry requires db_path")
        return SqliteDeviceRegistry(db_path)
    else:
        return InMemoryDeviceRegistry()
