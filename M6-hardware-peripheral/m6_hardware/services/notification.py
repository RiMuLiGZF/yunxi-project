"""
M6 硬件外设 - 通知推送服务
管理设备通知和告警的推送
"""

import logging
import time
import traceback
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import deque

from .device_manager import get_device_manager

logger = logging.getLogger(__name__)


class NotificationService:
    """通知推送服务

    管理设备通知、告警事件的分发。
    与 SSE 管理器配合实现实时推送。

    P0-4 改造：移除 __new__ 单例模式，改为由 FastAPI lifespan 统一创建管理。
    模块级 get_notification_service() 作为向后兼容层保留（标记 deprecated）。
    """

    def __init__(self, device_manager=None):
        """
        Args:
            device_manager: 设备管理器实例，为 None 时从兼容层获取（向后兼容）
        """
        self._device_manager = device_manager if device_manager is not None else get_device_manager()
        self._notifications: deque = deque(maxlen=500)  # 最近通知缓存
        self._alerts: deque = deque(maxlen=200)         # 最近告警缓存
        self._listeners: List[Any] = []  # SSE 监听器

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

        按异常类型分级处理：
        - 已知的监听器失效（AttributeError 等）: warning 级别 + 移除
        - 其他异常: error 级别 + 堆栈 + 移除
        - 所有异常均记录日志，无静默吞异常

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        message = {
            "event": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        failed_listeners = []

        for listener in self._listeners:
            try:
                if hasattr(listener, "send"):
                    listener.send(message)
                else:
                    # 监听器没有 send 方法，记 warning 并标记移除
                    logger.warning(
                        "通知监听器缺少 send 方法，将移除: listener=%s, event=%s",
                        type(listener).__name__, event_type,
                    )
                    failed_listeners.append(listener)
            except AttributeError as e:
                # 属性错误：监听器对象异常
                logger.warning(
                    "通知监听器属性错误，将移除: listener=%s, event=%s, error=%s",
                    type(listener).__name__, event_type, e,
                )
                failed_listeners.append(listener)
            except Exception as e:
                # 其他异常：记 error + 堆栈，移除监听器
                logger.error(
                    "通知广播异常，将移除监听器: listener=%s, event=%s, error=%s\n%s",
                    type(listener).__name__, event_type, e,
                    traceback.format_exc(),
                )
                failed_listeners.append(listener)

        # 清理失效监听器
        if failed_listeners:
            for listener in failed_listeners:
                if listener in self._listeners:
                    self._listeners.remove(listener)
            logger.info(
                "通知服务清理失效监听器 %d 个，剩余监听器数=%d",
                len(failed_listeners), len(self._listeners),
            )


_instance: NotificationService | None = None


def get_notification_service() -> NotificationService:
    """获取通知服务单例

    .. deprecated:: P0-4
        推荐使用 FastAPI 依赖注入 ``Depends(get_notification_service)`` 方式，
        由 lifespan 统一管理实例生命周期。本函数作为向后兼容层保留。
    """
    global _instance
    if _instance is None:
        _instance = NotificationService()
    return _instance
