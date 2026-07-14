"""
M6 硬件外设 - SSE 推送管理器
管理设备状态变更、传感器数据、告警通知的实时推送

P2-1 改造：SSE 连接管理增强
- 连接上限保护（M6_SSE_MAX_CONNECTIONS）
- 心跳机制增强（SSE 注释心跳 + 客户端超时断开）
- 连接元数据（created_at, last_active, device_id）
- 定时清理超时连接任务
"""

import asyncio
import json
import logging
import time
import uuid
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import Request
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

from ..config import get_config
from ..models.errors import M6Exception, ErrorCode
from ..services.device_manager import get_device_manager
from ..services.notification import get_notification_service


@dataclass
class _ConnectionMeta:
    """SSE 连接元数据

    Attributes:
        client_id:   客户端唯一标识（自动生成）
        device_id:   关联设备 ID（可选，用于定向推送）
        created_at:  连接创建时间（unix timestamp）
        last_active: 最后活跃时间（unix timestamp，每次成功推送/心跳更新）
    """
    client_id: str
    device_id: Optional[str]
    created_at: float
    last_active: float


class SSEManager:
    """SSE 推送管理器

    提供以下类型的实时推送：
    - device_status: 设备状态变更
    - sensor_data: 传感器数据更新
    - alert: 告警通知
    - notification: 设备通知

    P0-4 改造：移除 __new__ 单例模式，改为由 FastAPI lifespan 统一创建管理。
    模块级 get_sse_manager() 作为向后兼容层保留（标记 deprecated）。

    P2-1 改造：连接上限保护、心跳增强、连接元数据、定时清理。
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

        # P2-1: 连接管理 —— Dict[queue, meta] 替代原 Set[queue]
        self._connections: Dict[asyncio.Queue, _ConnectionMeta] = {}

        self._push_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        self._last_sensor_push = {}

        # P2-改进: 统计指标
        self._drop_count = 0  # 队列满丢弃消息数
        self._consecutive_errors = 0  # 推送循环连续异常数
        self._total_connections = 0  # 历史总连接数

        # P2-1: 从配置读取连接管理参数
        self._max_connections = self._config.sse_max_connections
        self._heartbeat_interval = self._config.sse_heartbeat_interval
        self._client_timeout = getattr(self._config, 'sse_client_timeout', 120.0)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self):
        """启动 SSE 推送服务"""
        if self._running:
            return
        self._running = True
        self._push_task = asyncio.create_task(self._push_loop())
        # P2-1: 启动定时清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(
            "SSE 管理器已启动: max_connections=%d, heartbeat=%.1fs, timeout=%.1fs",
            self._max_connections, self._heartbeat_interval, self._client_timeout,
        )

    async def stop(self):
        """停止 SSE 推送服务"""
        self._running = False

        # P2-1: 取消清理任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        if self._push_task:
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass
        self._push_task = None

    async def close_all(self):
        """关闭所有连接并停止服务

        P2-1 新增，作为 stop() 的语义别名，便于外部统一调用。
        """
        await self.stop()

    # ------------------------------------------------------------------
    # P2-1: 定时清理
    # ------------------------------------------------------------------

    async def _cleanup_loop(self):
        """定时清理超时连接的后台协程"""
        try:
            while self._running:
                await asyncio.sleep(30)
                if self._running:
                    await self._cleanup_stale_connections()
        except asyncio.CancelledError:
            pass

    async def _cleanup_stale_connections(self):
        """检查并移除超时未活跃的连接"""
        now = time.time()
        stale: list = []

        for queue, meta in list(self._connections.items()):
            if now - meta.last_active > self._client_timeout:
                stale.append((queue, meta))

        if not stale:
            return

        for queue, meta in stale:
            self._connections.pop(queue, None)
            # 清理队列中残留消息，帮助 GC
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            logger.info(
                "SSE 清理超时连接: client_id=%s, device_id=%s, idle=%.1fs",
                meta.client_id, meta.device_id, now - meta.last_active,
            )

        logger.info(
            "SSE 清理超时连接 %d 个，剩余连接数=%d/%d",
            len(stale), len(self._connections), self._max_connections,
        )

    # ------------------------------------------------------------------
    # 推送循环
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 广播
    # ------------------------------------------------------------------

    async def _broadcast(self, event: str, data: Dict[str, Any]):
        """向所有客户端广播消息

        按异常类型分级处理：
        - QueueFull: warning 级别 + 清理队列头部（客户端消费太慢）
        - 其他异常: error 级别 + 堆栈 + 移除死连接

        P2-1: 广播成功后更新连接的 last_active 时间戳。

        Args:
            event: 事件类型
            data: 事件数据
        """
        message = {
            "event": event,
            "data": data,
        }
        disconnected = []
        drop_count = 0

        for queue in list(self._connections):
            try:
                queue.put_nowait(message)
                # P2-1: 成功入队，更新活跃时间
                meta = self._connections.get(queue)
                if meta:
                    meta.last_active = time.time()
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
                    disconnected.append(queue)
            except Exception as e:
                # 其他异常（连接断开、队列失效等）：记 error + 堆栈，移除死连接
                logger.error(
                    "SSE 推送异常，移除死连接: event=%s, error=%s\n%s",
                    event, e, traceback.format_exc(),
                )
                disconnected.append(queue)

        # 周期打印队列满丢弃统计
        if drop_count > 0 and self._drop_count % 100 < drop_count:
            logger.warning(
                "SSE 队列满已累计丢弃 %d 条消息，当前连接数=%d/%d",
                self._drop_count, len(self._connections), self._max_connections,
            )

        # 清理失效连接
        if disconnected:
            for queue in disconnected:
                self._connections.pop(queue, None)
            logger.info(
                "SSE 清理失效连接 %d 个，剩余连接数=%d/%d",
                len(disconnected), len(self._connections), self._max_connections,
            )

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    async def connect(
        self,
        request: Request,
        event_types: Optional[str] = None,
        device_id: str = None,
    ) -> EventSourceResponse:
        """创建 SSE 连接

        P2-1 改造：
        - 新增 device_id 参数（默认 None，可从 query 参数自动提取）
        - 连接上限检查，超限抛出 M6Exception(ErrorCode.SSE_LIMIT_EXCEEDED)
        - 记录连接元数据（client_id, device_id, created_at, last_active）
        - 心跳使用 SSE 标准注释格式（``: heartbeat\\n\\n``）

        Args:
            request: FastAPI 请求对象
            event_types: 订阅的事件类型（逗号分隔），None 表示全部
            device_id: 关联设备 ID（可选），未传时从 request.query_params 提取

        Returns:
            SSE 响应

        Raises:
            M6Exception: 连接数超限时抛出 SSE_LIMIT_EXCEEDED
        """
        # P2-1: 连接上限保护
        if len(self._connections) >= self._max_connections:
            logger.warning(
                "SSE 连接数已达上限: 当前=%d, 上限=%d, 拒绝新连接",
                len(self._connections), self._max_connections,
            )
            raise M6Exception(
                ErrorCode.SSE_LIMIT_EXCEEDED,
                f"SSE连接数已达上限({self._max_connections})",
            )

        # P2-1: device_id 优先使用显式参数，其次从 query 参数提取
        if device_id is None:
            device_id = request.query_params.get("device_id")

        # P2-1: 生成客户端标识与元数据
        client_id = str(uuid.uuid4())[:8]
        now = time.time()

        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        meta = _ConnectionMeta(
            client_id=client_id,
            device_id=device_id,
            created_at=now,
            last_active=now,
        )
        self._connections[queue] = meta
        self._total_connections += 1

        logger.info(
            "SSE 新连接: client_id=%s, device_id=%s, 当前连接数=%d/%d",
            client_id, device_id, len(self._connections), self._max_connections,
        )

        async def event_generator():
            try:
                # 发送欢迎消息
                yield {
                    "event": "connected",
                    "data": json.dumps({
                        "message": "SSE 连接已建立",
                        "client_id": client_id,
                        "client_count": len(self._connections),
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
                        message = await asyncio.wait_for(
                            queue.get(), timeout=self._heartbeat_interval,
                        )
                        # P2-1: 成功消费消息，更新活跃时间
                        conn_meta = self._connections.get(queue)
                        if conn_meta:
                            conn_meta.last_active = time.time()
                        yield {
                            "event": message["event"],
                            "data": json.dumps(message["data"], ensure_ascii=False),
                        }
                    except asyncio.TimeoutError:
                        # P2-1: 发送 SSE 标准心跳注释（浏览器 EventSource 忽略 comment）
                        yield {"comment": "heartbeat"}
                        # P2-1: 心跳同样更新活跃时间
                        conn_meta = self._connections.get(queue)
                        if conn_meta:
                            conn_meta.last_active = time.time()

            finally:
                self._connections.pop(queue, None)
                # P2-改进: 清理队列中未消费的消息，帮助GC
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                logger.info(
                    "SSE 连接断开: client_id=%s, device_id=%s, "
                    "存活=%.1fs, 剩余连接数=%d/%d",
                    client_id, device_id,
                    time.time() - meta.created_at,
                    len(self._connections), self._max_connections,
                )

        return EventSourceResponse(event_generator())

    # ------------------------------------------------------------------
    # 公共属性 & 手动推送
    # ------------------------------------------------------------------

    @property
    def client_count(self) -> int:
        """当前连接的客户端数量"""
        return len(self._connections)

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