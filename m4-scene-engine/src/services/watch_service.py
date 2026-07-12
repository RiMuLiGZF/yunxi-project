"""手表交互服务 - 业务逻辑层.

封装手表交互的业务逻辑，包括设备管理、健康数据同步、
通知推送、手表端配置等功能。

手表交互作为一个独立的服务模块，提供智能穿戴设备的
数据管理与交互能力。
"""

from __future__ import annotations

import uuid
import random
from typing import Any, Optional, List
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src.database import WatchDeviceDB, WatchHealthDataDB, WatchNotificationDB


# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------

#: 默认设备特性
DEFAULT_FEATURES = ["heart_rate", "steps", "sleep", "notification"]
#: 设备类型
DEVICE_TYPES = ["watch", "ring", "band"]
#: 健康数据类型
HEALTH_DATA_TYPES = ["heart_rate", "steps", "spo2", "sleep", "calories"]


# ---------------------------------------------------------------------------
# WatchService 主类
# ---------------------------------------------------------------------------


class WatchService:
    """手表交互服务.

    封装手表相关的所有业务逻辑，包括设备管理、健康数据、
    通知推送、配置管理等。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化手表服务.

        Args:
            db: 数据库会话
            user_id: 用户ID
        """
        self.db = db
        self.user_id = user_id

    # ------------------------------------------------------------------
    # 设备管理
    # ------------------------------------------------------------------

    def list_devices(
        self,
        status: Optional[str] = None,
        device_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """获取设备列表.

        Args:
            status: 按状态过滤（online/offline）
            device_type: 按类型过滤（watch/ring/band）
            page: 页码
            page_size: 每页数量

        Returns:
            分页设备列表
        """
        query = self.db.query(WatchDeviceDB).filter(
            WatchDeviceDB.user_id == self.user_id,
        )

        if status:
            query = query.filter(WatchDeviceDB.status == status)
        if device_type:
            query = query.filter(WatchDeviceDB.device_type == device_type)

        total = query.count()
        devices = (
            query.order_by(WatchDeviceDB.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "devices": [d.to_dict() for d in devices],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_device(self, device_id: str) -> Optional[dict[str, Any]]:
        """获取单个设备详情.

        Args:
            device_id: 设备ID

        Returns:
            设备信息字典，不存在返回 None
        """
        device = (
            self.db.query(WatchDeviceDB)
            .filter(
                WatchDeviceDB.device_id == device_id,
                WatchDeviceDB.user_id == self.user_id,
            )
            .first()
        )
        if device is None:
            return None
        return device.to_dict()

    def bind_device(
        self,
        device_id: str,
        name: str,
        device_type: str = "watch",
        mac_address: str = "",
    ) -> dict[str, Any]:
        """绑定设备.

        Args:
            device_id: 设备ID
            name: 设备名称
            device_type: 设备类型
            mac_address: MAC 地址

        Returns:
            新绑定的设备信息

        Raises:
            ValueError: 设备已绑定
        """
        existing = (
            self.db.query(WatchDeviceDB)
            .filter(
                WatchDeviceDB.device_id == device_id,
                WatchDeviceDB.user_id == self.user_id,
            )
            .first()
        )
        if existing:
            raise ValueError("设备已绑定")

        now = datetime.utcnow()
        device = WatchDeviceDB(
            device_id=device_id,
            user_id=self.user_id,
            name=name,
            device_type=device_type,
            brand="Yunxi",
            model="Unknown",
            firmware_version="v1.0.0",
            status="online",
            battery=100,
            paired=True,
            paired_at=now,
            last_sync=now,
            mac_address=mac_address,
            features=list(DEFAULT_FEATURES),
            settings={},
        )
        self.db.add(device)
        self.db.commit()
        self.db.refresh(device)

        return device.to_dict()

    def unbind_device(self, device_id: str) -> bool:
        """解绑设备.

        Args:
            device_id: 设备ID

        Returns:
            是否解绑成功
        """
        device = (
            self.db.query(WatchDeviceDB)
            .filter(
                WatchDeviceDB.device_id == device_id,
                WatchDeviceDB.user_id == self.user_id,
            )
            .first()
        )
        if device is None:
            return False

        # 级联删除健康数据和通知
        self.db.query(WatchHealthDataDB).filter(
            WatchHealthDataDB.device_id == device_id,
            WatchHealthDataDB.user_id == self.user_id,
        ).delete()

        self.db.query(WatchNotificationDB).filter(
            WatchNotificationDB.device_id == device_id,
            WatchNotificationDB.user_id == self.user_id,
        ).delete()

        self.db.delete(device)
        self.db.commit()
        return True

    def update_device(self, device_id: str, update_data: dict[str, Any]) -> Optional[dict[str, Any]]:
        """更新设备信息.

        Args:
            device_id: 设备ID
            update_data: 要更新的字段字典

        Returns:
            更新后的设备信息，不存在返回 None
        """
        device = (
            self.db.query(WatchDeviceDB)
            .filter(
                WatchDeviceDB.device_id == device_id,
                WatchDeviceDB.user_id == self.user_id,
            )
            .first()
        )
        if device is None:
            return None

        allowed_fields = [
            "name", "device_type", "status", "battery",
            "firmware_version", "features", "settings",
        ]
        for field in allowed_fields:
            if field in update_data and update_data[field] is not None:
                setattr(device, field, update_data[field])

        device.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(device)

        return device.to_dict()

    # ------------------------------------------------------------------
    # 健康数据
    # ------------------------------------------------------------------

    def get_realtime_health(self, device_id: str) -> dict[str, Any]:
        """获取实时健康数据（mock 生成）.

        Args:
            device_id: 设备ID

        Returns:
            实时健康数据字典

        Raises:
            ValueError: 设备不存在或离线
        """
        device = (
            self.db.query(WatchDeviceDB)
            .filter(
                WatchDeviceDB.device_id == device_id,
                WatchDeviceDB.user_id == self.user_id,
            )
            .first()
        )
        if device is None:
            raise ValueError("设备不存在")
        if device.status == "offline":
            raise ValueError("设备离线，无法获取实时数据")

        features = device.features or []
        now = datetime.utcnow().isoformat()
        data: dict[str, Any] = {
            "device_id": device_id,
            "timestamp": now,
        }

        # 从数据库读取最新数据，如果没有则生成 mock 数据
        if "heart_rate" in features:
            latest_hr = self._get_latest_health_data(device_id, "heart_rate")
            if latest_hr:
                hr_val = int(latest_hr.value)
            else:
                hr_val = random.randint(60, 90)
            data["heart_rate"] = {
                "value": hr_val,
                "unit": "bpm",
                "status": "normal" if 60 <= hr_val <= 100 else "warning",
            }

        if "steps" in features:
            latest_steps = self._get_latest_health_data(device_id, "steps")
            if latest_steps:
                steps_val = int(latest_steps.value)
                goal = (latest_steps.extra or {}).get("goal", 10000)
            else:
                steps_val = random.randint(1000, 12000)
                goal = 10000
            data["steps"] = {
                "value": steps_val,
                "unit": "steps",
                "goal": goal,
            }

        if "spo2" in features:
            latest_spo2 = self._get_latest_health_data(device_id, "spo2")
            if latest_spo2:
                spo2_val = latest_spo2.value
            else:
                spo2_val = round(random.uniform(95, 99), 1)
            data["spo2"] = {
                "value": spo2_val,
                "unit": "%",
                "status": "normal" if spo2_val >= 95 else "warning",
            }

        if "sleep" in features:
            latest_sleep = self._get_latest_health_data(device_id, "sleep")
            if latest_sleep and latest_sleep.extra:
                extra = latest_sleep.extra
                data["sleep"] = {
                    "total_hours": extra.get("total_hours", latest_sleep.value),
                    "deep_sleep": extra.get("deep_sleep", 0),
                    "light_sleep": extra.get("light_sleep", 0),
                    "rem_sleep": extra.get("rem_sleep", 0),
                }
            else:
                total = round(random.uniform(6, 9), 1)
                data["sleep"] = {
                    "total_hours": total,
                    "deep_sleep": round(total * 0.25, 1),
                    "light_sleep": round(total * 0.55, 1),
                    "rem_sleep": round(total * 0.2, 1),
                }

        if "calories" in features or "steps" in features:
            if "steps" in data:
                cal = int(data["steps"]["value"] * 0.04)
                data["calories"] = {
                    "value": cal,
                    "unit": "kcal",
                }

        return {
            "device_id": device_id,
            "device_name": device.name,
            "data": data,
        }

    def sync_health_data(
        self,
        device_id: str,
        data_type: Optional[str] = None,
        days: int = 7,
    ) -> dict[str, Any]:
        """同步健康数据（生成 mock 历史数据并存入数据库）.

        Args:
            device_id: 设备ID
            data_type: 数据类型（不传则同步全部）
            days: 同步天数

        Returns:
            同步结果字典

        Raises:
            ValueError: 设备不存在
        """
        device = (
            self.db.query(WatchDeviceDB)
            .filter(
                WatchDeviceDB.device_id == device_id,
                WatchDeviceDB.user_id == self.user_id,
            )
            .first()
        )
        if device is None:
            raise ValueError("设备不存在")

        data_types = [data_type] if data_type else ["heart_rate", "steps", "spo2", "sleep"]
        synced_count = 0

        for dt in data_types:
            history = self._generate_mock_health_history(device_id, dt, days)
            for item in history:
                record = WatchHealthDataDB(
                    device_id=device_id,
                    user_id=self.user_id,
                    data_type=dt,
                    value=item.get("value", 0),
                    unit=item.get("unit", ""),
                    extra=item.get("extra", {}),
                    recorded_at=item.get("recorded_at", datetime.utcnow()),
                )
                self.db.add(record)
                synced_count += 1

        # 更新设备最后同步时间
        device.last_sync = datetime.utcnow()
        self.db.commit()

        return {
            "device_id": device_id,
            "data_types": data_types,
            "synced_count": synced_count,
            "sync_time": datetime.utcnow().isoformat(),
        }

    def get_health_history(
        self,
        device_id: str,
        data_type: str = "heart_rate",
        days: int = 7,
        page: int = 1,
        page_size: int = 100,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> dict[str, Any]:
        """获取健康数据历史.

        Args:
            device_id: 设备ID
            data_type: 数据类型
            days: 天数（未指定时间范围时使用）
            page: 页码
            page_size: 每页数量
            start_time: 开始时间（ISO格式）
            end_time: 结束时间（ISO格式）

        Returns:
            分页健康数据历史
        """
        device = (
            self.db.query(WatchDeviceDB)
            .filter(
                WatchDeviceDB.device_id == device_id,
                WatchDeviceDB.user_id == self.user_id,
            )
            .first()
        )
        if device is None:
            raise ValueError("设备不存在")

        query = self.db.query(WatchHealthDataDB).filter(
            WatchHealthDataDB.device_id == device_id,
            WatchHealthDataDB.user_id == self.user_id,
            WatchHealthDataDB.data_type == data_type,
        )

        # 解析时间范围
        end_dt = None
        start_dt = None
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        if not start_dt and not end_dt:
            end_dt = datetime.utcnow()
            start_dt = end_dt - timedelta(days=days)

        if start_dt:
            query = query.filter(WatchHealthDataDB.recorded_at >= start_dt)
        if end_dt:
            query = query.filter(WatchHealthDataDB.recorded_at <= end_dt)

        total = query.count()
        records = (
            query.order_by(WatchHealthDataDB.recorded_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        # 转换格式
        history_data = []
        values_for_stats: list[float] = []

        for r in records:
            extra = r.extra or {}
            if data_type == "steps":
                item = {
                    "timestamp": r.recorded_at.date().isoformat() if r.recorded_at else "",
                    "value": int(r.value),
                    "unit": r.unit or "steps",
                    "goal": extra.get("goal", 10000),
                }
                values_for_stats.append(r.value)
            elif data_type == "sleep":
                item = {
                    "timestamp": r.recorded_at.date().isoformat() if r.recorded_at else "",
                    "total_hours": extra.get("total_hours", r.value),
                    "deep_sleep": extra.get("deep_sleep", 0),
                    "light_sleep": extra.get("light_sleep", 0),
                    "rem_sleep": extra.get("rem_sleep", 0),
                    "score": extra.get("score", 0),
                }
                values_for_stats.append(extra.get("score", r.value))
            else:
                item = {
                    "timestamp": r.recorded_at.isoformat() if r.recorded_at else "",
                    "value": r.value,
                    "unit": r.unit or "",
                }
                values_for_stats.append(r.value)
            history_data.append(item)

        # 统计数据
        if values_for_stats:
            avg_value = sum(values_for_stats) / len(values_for_stats)
            max_value = max(values_for_stats)
            min_value = min(values_for_stats)
        else:
            avg_value = max_value = min_value = 0

        return {
            "device_id": device_id,
            "data_type": data_type,
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": history_data,
            "statistics": {
                "avg": round(avg_value, 2),
                "max": max_value,
                "min": min_value,
                "days": days,
            },
        }

    # ------------------------------------------------------------------
    # 通知推送
    # ------------------------------------------------------------------

    def send_notification(
        self,
        device_id: str,
        title: str,
        content: str,
        notification_type: str = "info",
        action_type: str = "",
        action_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """发送通知到手表.

        Args:
            device_id: 设备ID
            title: 通知标题
            content: 通知内容
            notification_type: 通知类型
            action_type: 动作类型
            action_data: 动作数据

        Returns:
            通知发送结果

        Raises:
            ValueError: 设备不存在
        """
        device = (
            self.db.query(WatchDeviceDB)
            .filter(
                WatchDeviceDB.device_id == device_id,
                WatchDeviceDB.user_id == self.user_id,
            )
            .first()
        )
        if device is None:
            raise ValueError("设备不存在")

        if device.status == "offline":
            # 设备离线，通知状态设为 pending
            status = "pending"
            delivered_at = None
        else:
            status = "delivered"
            delivered_at = datetime.utcnow()

        notification_id = f"notif_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        notification = WatchNotificationDB(
            notification_id=notification_id,
            device_id=device_id,
            user_id=self.user_id,
            title=title,
            content=content,
            notification_type=notification_type,
            status=status,
            action_type=action_type,
            action_data=action_data or {},
            source="api",
            delivered_at=delivered_at,
            created_at=now,
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)

        return {
            "notification_id": notification_id,
            "device_id": device_id,
            "status": status,
            "delivered_at": delivered_at.isoformat() if delivered_at else None,
        }

    def list_notifications(
        self,
        device_id: Optional[str] = None,
        notification_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """获取通知历史.

        Args:
            device_id: 按设备过滤（可选）
            notification_type: 按类型过滤（可选）
            status: 按状态过滤（可选）
            page: 页码
            page_size: 每页数量

        Returns:
            分页通知列表
        """
        query = self.db.query(WatchNotificationDB).filter(
            WatchNotificationDB.user_id == self.user_id,
        )

        if device_id:
            query = query.filter(WatchNotificationDB.device_id == device_id)
        if notification_type:
            query = query.filter(WatchNotificationDB.notification_type == notification_type)
        if status:
            query = query.filter(WatchNotificationDB.status == status)

        total = query.count()
        notifications = (
            query.order_by(WatchNotificationDB.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "notifications": [n.to_dict() for n in notifications],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def mark_notification_read(self, notification_id: str) -> bool:
        """标记通知为已读.

        Args:
            notification_id: 通知ID

        Returns:
            是否成功
        """
        notification = (
            self.db.query(WatchNotificationDB)
            .filter(
                WatchNotificationDB.notification_id == notification_id,
                WatchNotificationDB.user_id == self.user_id,
            )
            .first()
        )
        if notification is None:
            return False

        notification.status = "read"
        notification.read_at = datetime.utcnow()
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # 手表端配置
    # ------------------------------------------------------------------

    def get_watch_settings(self, device_id: str) -> dict[str, Any]:
        """获取手表端配置.

        Args:
            device_id: 设备ID

        Returns:
            配置字典
        """
        device = (
            self.db.query(WatchDeviceDB)
            .filter(
                WatchDeviceDB.device_id == device_id,
                WatchDeviceDB.user_id == self.user_id,
            )
            .first()
        )
        if device is None:
            raise ValueError("设备不存在")

        default_settings = {
            "screen_brightness": 80,
            "vibration_enabled": True,
            "screen_timeout": 15,
            "theme": "auto",
            "notifications_enabled": True,
            "dnd_mode": False,
            "dnd_start_time": "22:00",
            "dnd_end_time": "07:00",
            "heart_rate_monitor": True,
            "sleep_monitor": True,
            "sedentary_reminder": True,
            "water_reminder": True,
        }

        # 合并用户自定义配置
        user_settings = device.settings or {}
        default_settings.update(user_settings)

        return {
            "device_id": device_id,
            "settings": default_settings,
        }

    def update_watch_settings(self, device_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        """更新手表端配置.

        Args:
            device_id: 设备ID
            settings: 配置字典

        Returns:
            更新后的配置
        """
        device = (
            self.db.query(WatchDeviceDB)
            .filter(
                WatchDeviceDB.device_id == device_id,
                WatchDeviceDB.user_id == self.user_id,
            )
            .first()
        )
        if device is None:
            raise ValueError("设备不存在")

        current_settings = device.settings or {}
        current_settings.update(settings)
        device.settings = current_settings
        device.updated_at = datetime.utcnow()
        self.db.commit()

        return self.get_watch_settings(device_id)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_latest_health_data(self, device_id: str, data_type: str) -> Optional[WatchHealthDataDB]:
        """获取最新的健康数据记录.

        Args:
            device_id: 设备ID
            data_type: 数据类型

        Returns:
            最新记录，不存在返回 None
        """
        return (
            self.db.query(WatchHealthDataDB)
            .filter(
                WatchHealthDataDB.device_id == device_id,
                WatchHealthDataDB.user_id == self.user_id,
                WatchHealthDataDB.data_type == data_type,
            )
            .order_by(WatchHealthDataDB.recorded_at.desc())
            .first()
        )

    def _generate_mock_health_history(
        self,
        device_id: str,
        data_type: str,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """生成 mock 健康历史数据.

        Args:
            device_id: 设备ID
            data_type: 数据类型
            days: 天数

        Returns:
            历史数据列表
        """
        history: list[dict[str, Any]] = []
        now = datetime.utcnow()

        if data_type == "heart_rate":
            for i in range(days * 24):
                ts = now - timedelta(hours=i)
                history.append({
                    "value": random.randint(55, 95),
                    "unit": "bpm",
                    "extra": {},
                    "recorded_at": ts,
                })
        elif data_type == "steps":
            for i in range(days):
                ts = now - timedelta(days=i)
                steps = random.randint(3000, 15000)
                history.append({
                    "value": steps,
                    "unit": "steps",
                    "extra": {"goal": 10000},
                    "recorded_at": ts,
                })
        elif data_type == "spo2":
            for i in range(days * 24):
                ts = now - timedelta(hours=i)
                history.append({
                    "value": round(random.uniform(94, 99), 1),
                    "unit": "%",
                    "extra": {},
                    "recorded_at": ts,
                })
        elif data_type == "sleep":
            for i in range(days):
                ts = now - timedelta(days=i)
                total = round(random.uniform(5.5, 9), 1)
                history.append({
                    "value": total,
                    "unit": "hours",
                    "extra": {
                        "total_hours": total,
                        "deep_sleep": round(total * 0.25, 1),
                        "light_sleep": round(total * 0.55, 1),
                        "rem_sleep": round(total * 0.2, 1),
                        "score": random.randint(60, 95),
                    },
                    "recorded_at": ts,
                })

        return history
