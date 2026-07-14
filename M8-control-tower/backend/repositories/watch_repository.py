# -*- coding: utf-8 -*-
"""
M8 管理工作台 - 手表交互数据仓库

封装手表设备、健康数据、通知历史、设置的数据库 CRUD。
迁移过渡期：优先读 DB，DB 为空时自动初始化默认数据。
"""

import random
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from ..models import WatchDevice, WatchHealthData, WatchNotification, WatchSetting


# ==================== 默认数据初始化 ====================

def _get_default_devices(user_id: int = 1) -> List[WatchDevice]:
    """生成默认设备数据"""
    now = datetime.utcnow()
    return [
        WatchDevice(
            device_id="watch_001",
            name="云汐智能手表 Pro",
            device_type="watch",
            brand="Yunxi",
            model="Watch Pro 2",
            firmware_version="v2.3.1",
            status="online",
            battery=78,
            paired=True,
            paired_at=now - timedelta(days=30),
            last_sync=now - timedelta(minutes=5),
            mac_address="AA:BB:CC:DD:EE:01",
            features=["heart_rate", "steps", "sleep", "spo2", "notification", "find_device"],
            user_id=user_id,
        ),
        WatchDevice(
            device_id="watch_002",
            name="云汐智能戒指",
            device_type="ring",
            brand="Yunxi",
            model="Ring Lite",
            firmware_version="v1.5.0",
            status="online",
            battery=92,
            paired=True,
            paired_at=now - timedelta(days=15),
            last_sync=now - timedelta(minutes=2),
            mac_address="AA:BB:CC:DD:EE:02",
            features=["heart_rate", "sleep", "temperature", "spo2", "hrv"],
            user_id=user_id,
        ),
    ]


def _get_default_notifications(user_id: int = 1) -> List[WatchNotification]:
    """生成默认通知数据"""
    now = datetime.utcnow()
    return [
        WatchNotification(
            notification_id="notif_001",
            device_id="watch_001",
            title="日程提醒",
            content="10分钟后有团队会议",
            notification_type="reminder",
            status="delivered",
            delivered_at=now - timedelta(minutes=10),
            read_at=None,
            action_type="open_calendar",
            action_data={"event_id": "evt_001"},
            source="calendar",
            user_id=user_id,
            created_at=now - timedelta(minutes=12),
        ),
        WatchNotification(
            notification_id="notif_002",
            device_id="watch_001",
            title="久坐提醒",
            content="您已坐了1小时，建议起身活动一下",
            notification_type="info",
            status="read",
            delivered_at=now - timedelta(hours=1),
            read_at=now - timedelta(minutes=55),
            action_type="dismiss",
            action_data={},
            source="system",
            user_id=user_id,
            created_at=now - timedelta(hours=1, minutes=2),
        ),
        WatchNotification(
            notification_id="notif_003",
            device_id="watch_001",
            title="心率异常",
            content="检测到静息心率偏高，请注意休息",
            notification_type="warning",
            status="delivered",
            delivered_at=now - timedelta(hours=2),
            read_at=None,
            action_type="view_health",
            action_data={"data_type": "heart_rate"},
            source="health",
            user_id=user_id,
            created_at=now - timedelta(hours=2, minutes=1),
        ),
    ]


def _generate_health_history_records(device_id: str, data_type: str,
                                      days: int = 7, user_id: int = 1) -> List[WatchHealthData]:
    """生成健康历史数据（用于初始化）"""
    records = []
    now = datetime.utcnow()

    if data_type == "heart_rate":
        for i in range(days * 24):
            ts = now - timedelta(hours=i)
            records.append(WatchHealthData(
                device_id=device_id,
                data_type="heart_rate",
                value=random.randint(55, 95),
                unit="bpm",
                timestamp=ts,
                source="watch",
                quality="good",
                extra={"status": "normal"},
                user_id=user_id,
            ))
    elif data_type == "steps":
        for i in range(days):
            ts = now - timedelta(days=i)
            steps_val = random.randint(3000, 15000)
            records.append(WatchHealthData(
                device_id=device_id,
                data_type="steps",
                value=steps_val,
                unit="steps",
                timestamp=ts.replace(hour=23, minute=59, second=59),
                source="watch",
                quality="good",
                extra={"goal": 10000},
                user_id=user_id,
            ))
    elif data_type == "spo2":
        for i in range(days * 24):
            ts = now - timedelta(hours=i)
            records.append(WatchHealthData(
                device_id=device_id,
                data_type="spo2",
                value=round(random.uniform(94, 99), 1),
                unit="%",
                timestamp=ts,
                source="watch",
                quality="good",
                extra={"status": "normal"},
                user_id=user_id,
            ))
    elif data_type == "sleep":
        for i in range(days):
            ts = now - timedelta(days=i)
            total = round(random.uniform(5.5, 9), 1)
            records.append(WatchHealthData(
                device_id=device_id,
                data_type="sleep",
                value=total,
                unit="hours",
                timestamp=ts.replace(hour=7, minute=0, second=0),
                source="watch",
                quality="good",
                extra={
                    "total_hours": total,
                    "deep_sleep": round(total * 0.25, 1),
                    "light_sleep": round(total * 0.55, 1),
                    "rem_sleep": round(total * 0.2, 1),
                    "score": random.randint(60, 95),
                },
                user_id=user_id,
            ))

    return records


def init_watch_default_data(db: Session, user_id: int = 1) -> bool:
    """初始化手表默认数据（幂等）

    当 watch_devices 表为空时，插入示例设备、健康数据和通知。

    Args:
        db: 数据库 session
        user_id: 用户ID

    Returns:
        是否执行了初始化
    """
    device_count = db.query(WatchDevice).filter(WatchDevice.user_id == user_id).count()
    if device_count > 0:
        return False

    # 插入默认设备
    devices = _get_default_devices(user_id)
    db.add_all(devices)
    db.flush()

    # 插入默认通知
    notifications = _get_default_notifications(user_id)
    db.add_all(notifications)

    # 为第一个设备插入健康历史数据
    for data_type in ["heart_rate", "steps", "spo2", "sleep"]:
        health_records = _generate_health_history_records("watch_001", data_type, days=7, user_id=user_id)
        db.add_all(health_records)

    db.commit()
    print(f"[Migration] 手表默认数据初始化完成: {len(devices)} 个设备, {len(notifications)} 条通知")
    return True


# ==================== 设备 Repository ====================

class WatchDeviceRepository:
    """手表设备数据仓库"""

    def __init__(self, db: Session, user_id: int = 1):
        self.db = db
        self.user_id = user_id
        self._ensure_initialized()

    def _ensure_initialized(self):
        """确保默认数据已初始化"""
        try:
            init_watch_default_data(self.db, self.user_id)
        except Exception as e:
            print(f"[Migration] 手表数据初始化跳过: {e}")

    def list_devices(self, status: Optional[str] = None,
                     device_type: Optional[str] = None,
                     page: int = 1, page_size: int = 10) -> Tuple[List[WatchDevice], int]:
        """获取设备列表（支持筛选和分页）"""
        query = self.db.query(WatchDevice).filter(WatchDevice.user_id == self.user_id)

        if status:
            query = query.filter(WatchDevice.status == status)
        if device_type:
            query = query.filter(WatchDevice.device_type == device_type)

        total = query.count()
        devices = (
            query.order_by(desc(WatchDevice.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return devices, total

    def get_by_device_id(self, device_id: str) -> Optional[WatchDevice]:
        """根据 device_id 获取设备"""
        return (
            self.db.query(WatchDevice)
            .filter(
                WatchDevice.device_id == device_id,
                WatchDevice.user_id == self.user_id,
            )
            .first()
        )

    def bind_device(self, device_id: str, name: str, device_type: str = "watch",
                    mac_address: str = "") -> WatchDevice:
        """绑定新设备"""
        device = WatchDevice(
            device_id=device_id,
            name=name,
            device_type=device_type,
            brand="Unknown",
            model="Unknown",
            firmware_version="v1.0.0",
            status="online",
            battery=100,
            paired=True,
            paired_at=datetime.utcnow(),
            last_sync=datetime.utcnow(),
            mac_address=mac_address,
            features=["heart_rate", "steps", "notification"],
            user_id=self.user_id,
        )
        self.db.add(device)
        self.db.commit()
        self.db.refresh(device)
        return device

    def unbind_device(self, device_id: str) -> bool:
        """解绑设备"""
        device = self.get_by_device_id(device_id)
        if not device:
            return False
        self.db.delete(device)
        self.db.commit()
        return True

    def update_last_sync(self, device_id: str):
        """更新设备最后同步时间"""
        device = self.get_by_device_id(device_id)
        if device:
            device.last_sync = datetime.utcnow()
            self.db.commit()

    def count(self) -> int:
        """设备总数"""
        return (
            self.db.query(WatchDevice)
            .filter(WatchDevice.user_id == self.user_id)
            .count()
        )


# ==================== 健康数据 Repository ====================

class WatchHealthRepository:
    """手表健康数据仓库"""

    def __init__(self, db: Session, user_id: int = 1):
        self.db = db
        self.user_id = user_id
        self._ensure_initialized()

    def _ensure_initialized(self):
        """确保默认数据已初始化"""
        try:
            init_watch_default_data(self.db, self.user_id)
        except Exception as e:
            print(f"[Migration] 手表健康数据初始化跳过: {e}")

    def get_latest(self, device_id: str, data_type: str) -> Optional[WatchHealthData]:
        """获取最新的一条健康数据"""
        return (
            self.db.query(WatchHealthData)
            .filter(
                WatchHealthData.device_id == device_id,
                WatchHealthData.data_type == data_type,
                WatchHealthData.user_id == self.user_id,
            )
            .order_by(desc(WatchHealthData.timestamp))
            .first()
        )

    def get_history(self, device_id: str, data_type: str,
                    start_time: Optional[datetime] = None,
                    end_time: Optional[datetime] = None,
                    page: int = 1, page_size: int = 100) -> Tuple[List[WatchHealthData], int]:
        """获取健康历史数据（支持时间范围和分页）"""
        query = self.db.query(WatchHealthData).filter(
            WatchHealthData.device_id == device_id,
            WatchHealthData.data_type == data_type,
            WatchHealthData.user_id == self.user_id,
        )

        if start_time:
            query = query.filter(WatchHealthData.timestamp >= start_time)
        if end_time:
            query = query.filter(WatchHealthData.timestamp <= end_time)

        total = query.count()
        records = (
            query.order_by(desc(WatchHealthData.timestamp))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return records, total

    def add_record(self, device_id: str, data_type: str, value: float,
                   unit: str = "", timestamp: Optional[datetime] = None,
                   extra: Optional[Dict[str, Any]] = None,
                   source: str = "watch", quality: str = "good") -> WatchHealthData:
        """添加一条健康数据"""
        record = WatchHealthData(
            device_id=device_id,
            data_type=data_type,
            value=value,
            unit=unit,
            timestamp=timestamp or datetime.utcnow(),
            source=source,
            quality=quality,
            extra=extra or {},
            user_id=self.user_id,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def add_batch(self, records: List[Dict[str, Any]], device_id: str = "") -> int:
        """批量添加健康数据

        Args:
            records: 记录列表，每项包含 data_type, value, unit, timestamp 等
            device_id: 可选，统一的设备ID

        Returns:
            插入的记录数
        """
        db_records = []
        for r in records:
            db_records.append(WatchHealthData(
                device_id=r.get("device_id", device_id),
                data_type=r.get("data_type", ""),
                value=r.get("value", 0),
                unit=r.get("unit", ""),
                timestamp=r.get("timestamp", datetime.utcnow()),
                source=r.get("source", "watch"),
                quality=r.get("quality", "good"),
                extra=r.get("extra", {}),
                user_id=self.user_id,
            ))
        if db_records:
            self.db.add_all(db_records)
            self.db.commit()
        return len(db_records)

    def sync_data(self, device_id: str, data_types: List[str], days: int = 7) -> int:
        """模拟同步健康数据（生成模拟数据并入库）

        返回同步的记录数。
        """
        total = 0
        for dt in data_types:
            records = _generate_health_history_records(device_id, dt, days=days, user_id=self.user_id)
            self.db.add_all(records)
            total += len(records)
        self.db.commit()
        return total


# ==================== 通知 Repository ====================

class WatchNotificationRepository:
    """手表通知数据仓库"""

    def __init__(self, db: Session, user_id: int = 1):
        self.db = db
        self.user_id = user_id
        self._ensure_initialized()

    def _ensure_initialized(self):
        """确保默认数据已初始化"""
        try:
            init_watch_default_data(self.db, self.user_id)
        except Exception as e:
            print(f"[Migration] 手表通知数据初始化跳过: {e}")

    def list_notifications(self, device_id: Optional[str] = None,
                           notification_type: Optional[str] = None,
                           status: Optional[str] = None,
                           page: int = 1, page_size: int = 20) -> Tuple[List[WatchNotification], int]:
        """获取通知历史（支持筛选和分页）"""
        query = self.db.query(WatchNotification).filter(WatchNotification.user_id == self.user_id)

        if device_id:
            query = query.filter(WatchNotification.device_id == device_id)
        if notification_type:
            query = query.filter(WatchNotification.notification_type == notification_type)
        if status:
            query = query.filter(WatchNotification.status == status)

        total = query.count()
        notifications = (
            query.order_by(desc(WatchNotification.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return notifications, total

    def get_by_notification_id(self, notification_id: str) -> Optional[WatchNotification]:
        """根据 notification_id 获取通知"""
        return (
            self.db.query(WatchNotification)
            .filter(
                WatchNotification.notification_id == notification_id,
                WatchNotification.user_id == self.user_id,
            )
            .first()
        )

    def send_notification(self, device_id: str, title: str, content: str,
                          notification_type: str = "info",
                          action_type: str = "",
                          action_data: Optional[Dict[str, Any]] = None,
                          source: str = "system") -> WatchNotification:
        """发送通知（创建通知记录）"""
        now = datetime.utcnow()
        notif_id = f"notif_{uuid.uuid4().hex[:8]}"
        notification = WatchNotification(
            notification_id=notif_id,
            device_id=device_id,
            title=title,
            content=content,
            notification_type=notification_type,
            status="delivered",
            delivered_at=now,
            read_at=None,
            action_type=action_type,
            action_data=action_data or {},
            source=source,
            user_id=self.user_id,
            created_at=now,
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        return notification

    def mark_read(self, notification_id: str) -> bool:
        """标记通知为已读"""
        notification = self.get_by_notification_id(notification_id)
        if not notification:
            return False
        notification.status = "read"
        notification.read_at = datetime.utcnow()
        self.db.commit()
        return True

    def count(self) -> int:
        """通知总数"""
        return (
            self.db.query(WatchNotification)
            .filter(WatchNotification.user_id == self.user_id)
            .count()
        )


# ==================== 设置 Repository ====================

class WatchSettingRepository:
    """手表设置数据仓库"""

    def __init__(self, db: Session, user_id: int = 1):
        self.db = db
        self.user_id = user_id

    def get_by_device_id(self, device_id: str) -> Optional[WatchSetting]:
        """获取设备设置"""
        return (
            self.db.query(WatchSetting)
            .filter(
                WatchSetting.device_id == device_id,
                WatchSetting.user_id == self.user_id,
            )
            .first()
        )

    def get_or_create(self, device_id: str,
                      default_settings: Optional[Dict[str, Any]] = None) -> WatchSetting:
        """获取或创建设备设置"""
        setting = self.get_by_device_id(device_id)
        if setting:
            return setting

        setting = WatchSetting(
            device_id=device_id,
            settings_json=default_settings or {},
            user_id=self.user_id,
        )
        self.db.add(setting)
        self.db.commit()
        self.db.refresh(setting)
        return setting

    def update_settings(self, device_id: str,
                        settings: Dict[str, Any]) -> WatchSetting:
        """更新设备设置（合并更新）"""
        setting = self.get_or_create(device_id)
        merged = {**(setting.settings_json or {}), **settings}
        setting.settings_json = merged
        setting.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(setting)
        return setting

    def replace_settings(self, device_id: str,
                         settings: Dict[str, Any]) -> WatchSetting:
        """替换设备设置（全量替换）"""
        setting = self.get_or_create(device_id)
        setting.settings_json = settings
        setting.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(setting)
        return setting
