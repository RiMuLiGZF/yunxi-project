"""
M6 硬件外设 - 通知推送服务
管理设备通知和告警的推送
"""

import time
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import deque

from .device_manager import get_device_manager


class NotificationService:
    """通知推送服务

    管理设备通知、告警事件的分发。
    与 SSE 管理器配合实现实时推送。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._device_manager = get_device_manager()
        self._notifications: deque = deque(maxlen=500)  # 最近通知缓存
        self._alerts: deque = deque(maxlen=200)         # 最近告警缓存
        self._listeners: List[Any] = []  # SSE 监听器
        self._initialized = True

    def push_to_device(
        self,
        device_id: str,
        title: str,
        content: str,
        notification_type: str = "info",
        **kwargs,
    ) -> Dict[str, Any]:
        """向设备推送通知

        Args:
            device_id: 设备ID
            title: 通知标题
            content: 通知内容
            notification_type: 通知类型 info/warning/error

        Returns:
            推送结果
        """
        dev = self._device_manager.get_simulator(device_id)
        if not dev:
            return {"success": False, "message": f"设备不存在: {device_id}"}

        # 调用设备的通知推送方法
        result = dev.push_notification(title, content, **kwargs)

        # 记录通知
        notification = {
            "notification_id": result.get("notification_id", f"notif_{uuid.uuid4().hex[:12]}"),
            "device_id": device_id,
            "title": title,
            "content": content,
            "type": notification_type,
            "timestamp": datetime.now().isoformat(),
            "success": result.get("success", True),
        }
        self._notifications.append(notification)

        # 推送给 SSE 监听器
        self._broadcast("notification", notification)

        return result

    def get_recent_notifications(
        self,
        device_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取最近的通知

        Args:
            device_id: 按设备过滤（可选）
            limit: 返回条数

        Returns:
            通知列表
        """
        notifications = list(self._notifications)
        if device_id:
            notifications = [n for n in notifications if n["device_id"] == device_id]
        return notifications[-limit:]

    def get_recent_alerts(
        self,
        device_id: Optional[str] = None,
        limit: int = 50,
        clear: bool = False,
    ) -> List[Dict[str, Any]]:
        """获取最近的告警

        Args:
            device_id: 按设备过滤（可选）
            limit: 返回条数
            clear: 是否清除已读告警

        Returns:
            告警列表
        """
        # 从各设备收集最新告警
        all_alerts = list(self._alerts)

        for dev_id in self._device_manager._devices:
            sim = self._device_manager.get_simulator(dev_id)
            if sim:
                device_alerts = sim.get_alerts(clear=clear)
                for alert in device_alerts:
                    # 检查是否已存在
                    if not any(
                        a.get("device_id") == alert["device_id"]
                        and a.get("type") == alert["type"]
                        and a.get("timestamp") == alert["timestamp"]
                        for a in all_alerts
                    ):
                        all_alerts.append(alert)
                        self._alerts.append(alert)
                        # 广播新告警
                        self._broadcast("alert", alert)

        if device_id:
            all_alerts = [a for a in all_alerts if a.get("device_id") == device_id]

        # 按时间排序
        all_alerts.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return all_alerts[-limit:]

    def add_listener(self, listener):
        """添加 SSE 监听器

        Args:
            listener: 监听器对象（需有 send 方法）
        """
        self._listeners.append(listener)

    def remove_listener(self, listener):
        """移除 SSE 监听器"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _broadcast(self, event_type: str, data: Dict[str, Any]):
        """向所有监听器广播事件

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        message = {
            "event": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        for listener in self._listeners:
            try:
                if hasattr(listener, "send"):
                    listener.send(message)
            except Exception:
                pass  # 监听器失效时忽略


def get_notification_service() -> NotificationService:
    """获取通知服务单例"""
    return NotificationService()
