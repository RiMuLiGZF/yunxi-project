"""
M6 硬件外设 - SSE 推送管理器
管理设备状态变更、传感器数据、告警通知的实时推送
"""

import asyncio
import json
import logging
import time
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, Set
from fastapi import Request
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

from ..config import get_config
from ..services.device_manager import get_device_manager
from ..services.notification import get_notification_service


class SSEManager:
    """SSE 推送管理器

    提供以下类型的实时推送：
    - device_status: 设备状态变更
    - sensor_data: 传感器数据更新
    - alert: 告警通知
    - notification: 设备通知

    P0-4 改造：移除 __new__ 单例模式，改为由 FastAPI lifespan 统一创建管理。
    模块级 get_sse_manager() 作为向后兼容层保留（标记 deprecated）。
    """

    def __init__(self, device_manager=None, notification_service=None, config=None):
        """
        Args:
            device_manager: 设备管理器实例，为 None 时从兼容层获取（向后兼容）
            notification_service: 通知服务实例，为 None 时从兼容层获取（向后兼容）
            config: 配置实例，为 None 时从兼容层获取（向后兼容）
        """
        self._config = config if config is not None else get_config()
        self._device_manager = device_manager if device_manager is not None else get_device_manager()
        self._notification_service = notification_service if notification_service is not None else get_notification_service()
        self._clients: Set[asyncio.Queue] = set()
        self._push_task: Optional[asyncio.Task] = None
        self._running = False
        self._last_sensor_push = {}
        # P2-改进: 统计指标
        self._drop_count = 0  # 队列满丢弃消息数
        self._consecutive_errors = 0  # 推送循环连续异常数
        self._total_connections = 0  # 历史总连接数

    async def start(self):
        """启动 SSE 推送服务"""
        if self._running:
            return
        self._running = True
        self._push_task = asyncio.create_task(self._push_loop())

    async def stop(self):
        """停止 SSE 推送服务"""
        self._running = False
        if self._push_task:
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass

    async def _push_loop(self):
        """推送循环：定期推送传感器数据和设备状态"""
        while self._running:
            try:
                # 推送传感器数据（每 5 秒）
                await self._push_sensor_data()

                # 检查并推送告警
                await self._push_alerts()

            except Exception as e:
                self._consecutive_errors += 1
                _wait = min(5 * self._consecutive_errors, 60)
                logger.error(
                    "SSE 推送循环异常(连续%d次): %s, 等待%ds\n%s",
                    self._consecutive_errors, e, _wait,
                    traceback.format_exc(),
                )
                await asyncio.sleep(_wait)
                continue
            else:
                self._consecutive_errors = 0

            await asyncio.sleep(self._config.sse_interval)

    async def _push_sensor_data(self):
        """推送所有设备的传感器数据"""
        devices = self._device_manager.list_devices()
        sensor_data = []
        status_changes = []

        for dev in devices:
            device_id = dev["device_id"]

            # 传感器数据
            if "sensors" in dev:
                sensor_data.append({
                    "device_id": device_id,
                    "sensors": dev["sensors"],
                })

            # 状态变更检测
            last_status = self._last_sensor_push.get(device_id, {}).get("status")
            if last_status != dev["status"]:
                status_changes.append({
                    "device_id": device_id,
                    "old_status": last_status,
                    "new_status": dev["status"],
                })
                self._last_sensor_push[device_id] = {
                    "status": dev["status"],
                    "battery": dev.get("battery"),
                }

        # 推送传感器数据
        if sensor_data:
            await self._broadcast("sensor_data", {
                "devices": sensor_data,
                "timestamp": datetime.now().isoformat(),
            })

        # 推送状态变更
        for change in status_changes:
            await self._broadcast("device_status", {
                **change,
                "timestamp": datetime.now().isoformat(),
            })

    async def _push_alerts(self):
        """推送最新告警"""
        alerts = self._notification_service.get_recent_alerts(limit=10)
        # 只推送新告警（简化处理：每次都推，前端去重）
        if alerts:
            # 只推送最近 10 秒内的新告警
            now = time.time()
            new_alerts = []
            for alert in alerts:
                try:
                    ts = datetime.fromisoformat(alert["timestamp"])
                    if now - ts.timestamp() < 10:
                        new_alerts.append(alert)
                except (ValueError, KeyError) as e:
                    logger.warning("告警时间解析失败，跳过该告警: %s, alert=%s", e, alert)
            if new_alerts:
                await self._broadcast("alerts", {
                    "alerts": new_alerts,
                    "timestamp": datetime.now().isoformat(),
                })

    async def _broadcast(self, event: str, data: Dict[str, Any]):
        """向所有客户端广播消息

        按异常类型分级处理：
        - QueueFull: warning 级别 + 清理队列头部（客户端消费太慢）
        - 其他异常: error 级别 + 堆栈 + 移除死连接

        Args:
            event: 事件类型
            data: 事件数据
        """
        message = {
            "event": event,
            "data": data,
        }
        disconnected = set()
        drop_count = 0

        for queue in self._clients:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # 客户端消费太慢：丢弃队列头部消息，腾出空间
                drop_count += 1
                self._drop_count += 1
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    # 再次满，直接丢弃本条消息
                    pass
                except Exception as e:
                    logger.warning(
                        "SSE 队列清理失败，移除该连接: event=%s, error=%s",
                        event, e,
                    )
                    disconnected.add(queue)
            except Exception as e:
                # 其他异常（连接断开、队列失效等）：记 error + 堆栈，移除死连接
                logger.error(
                    "SSE 推送异常，移除死连接: event=%s, error=%s\n%s",
                    event, e, traceback.format_exc(),
                )
                disconnected.add(queue)

        # 周期打印队列满丢弃统计
        if drop_count > 0 and self._drop_count % 100 < drop_count:
            logger.warning(
                "SSE 队列满已累计丢弃 %d 条消息，当前客户端数=%d",
                self._drop_count, len(self._clients),
            )

        # 清理失效连接
        if disconnected:
            for queue in disconnected:
                self._clients.discard(queue)
            logger.info(
                "SSE 清理失效连接 %d 个，剩余客户端数=%d",
                len(disconnected), len(self._clients),
            )

    async def connect(self, request: Request, event_types: Optional[str] = None) -> EventSourceResponse:
        """创建 SSE 连接

        Args:
            request: FastAPI 请求对象
            event_types: 订阅的事件类型（逗号分隔），None 表示全部

        Returns:
            SSE 响应
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._clients.add(queue)
        self._total_connections += 1

        async def event_generator():
            try:
                # 发送欢迎消息
                yield {
                    "event": "connected",
                    "data": json.dumps({
                        "message": "SSE 连接已建立",
                        "client_count": len(self._clients),
                        "timestamp": datetime.now().isoformat(),
                    }, ensure_ascii=False),
                }

                # 初始状态推送
                devices = self._device_manager.list_devices()
                yield {
                    "event": "initial_state",
                    "data": json.dumps({
                        "devices": devices,
                        "stats": self._device_manager.get_stats(),
                        "timestamp": datetime.now().isoformat(),
                    }, ensure_ascii=False),
                }

                # 持续推送
                while True:
                    if await request.is_disconnected():
                        break

                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=self._config.sse_heartbeat_interval)
                        yield {
                            "event": message["event"],
                            "data": json.dumps(message["data"], ensure_ascii=False),
                        }
                    except asyncio.TimeoutError:
                        # 心跳
                        yield {
                            "event": "ping",
                            "data": json.dumps({
                                "timestamp": datetime.now().isoformat(),
                            }, ensure_ascii=False),
                        }

            finally:
                self._clients.discard(queue)
                # P2-改进: 清理队列中未消费的消息，帮助GC
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

        return EventSourceResponse(event_generator())

    @property
    def client_count(self) -> int:
        """当前连接的客户端数量"""
        return len(self._clients)

    @property
    def drop_count(self) -> int:
        """队列满丢弃的消息总数（P2-改进: 监控指标）"""
        return self._drop_count

    @property
    def total_connections(self) -> int:
        """历史总连接数（P2-改进: 监控指标）"""
        return self._total_connections

    async def push_notification(self, notification: Dict[str, Any]):
        """手动推送通知事件

        Args:
            notification: 通知数据
        """
        await self._broadcast("notification", {
            "notification": notification,
            "timestamp": datetime.now().isoformat(),
        })

    async def push_custom_event(self, event: str, data: Dict[str, Any]):
        """推送自定义事件

        Args:
            event: 事件名称
            data: 事件数据
        """
        await self._broadcast(event, data)


_instance: SSEManager | None = None


def get_sse_manager() -> SSEManager:
    """获取 SSE 管理器单例

    .. deprecated:: P0-4
        推荐使用 FastAPI 依赖注入 ``Depends(get_sse_manager)`` 方式，
        由 lifespan 统一管理实例生命周期。本函数作为向后兼容层保留。
    """
    global _instance
    if _instance is None:
        _instance = SSEManager()
    return _instance
