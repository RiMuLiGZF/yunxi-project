"""
云汐内核 - 多 Agent 集群调度系统
消息总线模块

基于 asyncio 的发布-订阅（Pub/Sub）模式消息总线，
支持 topic 过滤、优先级队列、TTL 过期检查、背压控制。

[V11.4] 全链路追踪增强：
- 发布消息时自动附加当前 contextvars 中的 trace_id（若消息未设置）
- 消费消息时从消息中提取 trace_id 并设置到上下文
- 确保消息处理链路上的所有日志都具有相同 trace_id
"""

from __future__ import annotations

import asyncio
import fnmatch
import time
from typing import Awaitable, Callable

import structlog
from src.tools.interfaces import BusMessage, BusHandler, BusError
from src.core.dead_letter_queue import DeadLetterQueue

logger = structlog.get_logger(__name__)

# 全链路追踪上下文（基于 contextvars，异步安全）
# 惰性导入，避免循环依赖
_trace_ctx = None


def _get_trace_module() -> Any:
    """惰性获取 trace_context 模块。

    Returns:
        trace_context 模块对象，导入失败返回 None
    """
    global _trace_ctx
    if _trace_ctx is not None:
        return _trace_ctx
    try:
        import src.observability.trace_context as tc
        _trace_ctx = tc
        return tc
    except ImportError:
        _trace_ctx = False  # type: ignore[assignment]
        return None


class MessageBus:
    """基于 asyncio 的发布-订阅消息总线

    采用单例模式，整个内核共享一个 MessageBus 实例。

    特性：
    - 按 topic 订阅，支持通配符（如 agent.*）
    - 优先级队列（数字越小优先级越高）
    - 消息 TTL 过期自动丢弃
    - 背压控制（队列最大 10000）
    - 支持直接投递（recipient）与广播
    """

    _instance: MessageBus | None = None
    _lock: asyncio.Lock | None = None

    MAX_QUEUE_SIZE: int = 10000
    CONSUME_INTERVAL: float = 0.01  # 消费者轮询间隔（秒）

    def __init__(self) -> None:
        self._subscriptions: dict[str, tuple[str, str, BusHandler]] = {}
        """subscription_id -> (topic_pattern, subscriber_id, handler)"""
        self._queue: asyncio.PriorityQueue[tuple[int, float, BusMessage]] = (
            asyncio.PriorityQueue(maxsize=self.MAX_QUEUE_SIZE)
        )
        self._running: bool = False
        self._consumer_task: asyncio.Task[None] | None = None
        self._sub_lock: asyncio.Lock = asyncio.Lock()
        self._dlq: DeadLetterQueue = DeadLetterQueue()
        self._max_hops: int = 10
        self._enable_breadcrumb: bool = True
        self._logger: structlog.stdlib.BoundLogger = logger.bind(service="message_bus")

    @classmethod
    async def get_instance(cls) -> MessageBus:
        """获取 MessageBus 单例"""
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    await cls._instance._start()
        return cls._instance

    @classmethod
    async def reset_instance(cls) -> None:
        """重置单例（主要用于测试）"""
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        async with cls._lock:
            if cls._instance is not None:
                await cls._instance.shutdown()
                cls._instance = None

    # ── 订阅管理 ──────────────────────────────────────────

    async def subscribe(
        self,
        topic: str,
        handler: Callable[[BusMessage], Awaitable[None]],
        subscriber_id: str = "anonymous",
    ) -> str:
        """订阅 topic

        Args:
            topic: 主题模式，支持通配符 *（如 agent.*）
            handler: 消息处理回调
            subscriber_id: 订阅者标识

        Returns:
            subscription_id: 订阅 ID，用于取消订阅
        """
        subscription_id = f"{subscriber_id}:{topic}:{id(handler)}"
        async with self._sub_lock:
            self._subscriptions[subscription_id] = (topic, subscriber_id, handler)
        self._logger.info(
            "subscription_added",
            subscription_id=subscription_id,
            topic=topic,
            subscriber_id=subscriber_id,
        )
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> None:
        """取消订阅"""
        async with self._sub_lock:
            if subscription_id in self._subscriptions:
                topic, subscriber_id, _ = self._subscriptions.pop(subscription_id)
                self._logger.info(
                    "subscription_removed",
                    subscription_id=subscription_id,
                    topic=topic,
                    subscriber_id=subscriber_id,
                )

    # ── 发布消息 ──────────────────────────────────────────

    async def publish(self, message: BusMessage) -> None:
        """发布消息到总线（非阻塞）

        将消息放入优先级队列，若队列满则丢弃最低优先级消息并记录错误。
        自动注入 hop_count 和 breadcrumb，检测循环消息。

        [V11.4] 自动注入 trace_id：若消息未设置 trace_id，
        从当前 contextvars 上下文中获取并注入。
        """
        # [V11.4] 自动注入 trace_id
        if not message.trace_id:
            tc = _get_trace_module()
            if tc is not None:
                message.trace_id = tc.get_trace_id()

        # 消息防循环：递增 hop_count 并记录路径
        meta = dict(message.payload.get("_meta", {}))
        hop_count = meta.get("hop_count", 0) + 1
        meta["hop_count"] = hop_count

        if self._enable_breadcrumb:
            breadcrumb = list(meta.get("breadcrumb", []))
            if message.sender and message.sender not in breadcrumb:
                breadcrumb.append(message.sender)
            meta["breadcrumb"] = breadcrumb

            # 循环检测：sender 已在路径中
            if message.sender in breadcrumb[:-1]:
                self._logger.error(
                    "message_loop_detected",
                    trace_id=message.trace_id,
                    msg_id=message.msg_id,
                    sender=message.sender,
                    breadcrumb=breadcrumb,
                )
                self._dlq.enqueue_loop_detected(
                    message,
                    detail=f"loop_detected: sender={message.sender} in breadcrumb",
                )
                return

        # hop 超限检测
        if hop_count > self._max_hops:
            self._logger.error(
                "message_hop_limit_exceeded",
                trace_id=message.trace_id,
                msg_id=message.msg_id,
                hop_count=hop_count,
                max_hops=self._max_hops,
            )
            self._dlq.enqueue(
                message,
                reason="hop_limit_exceeded",
                error_detail=f"hop_count={hop_count} > max_hops={self._max_hops}",
            )
            return

        # 回写 meta
        message.payload["_meta"] = meta

        try:
            self._queue.put_nowait((message.priority, message.timestamp, message))
            self._logger.info(
                "message_published",
                trace_id=message.trace_id,
                msg_id=message.msg_id,
                topic=message.topic,
                priority=message.priority,
                recipient=message.recipient,
                hop_count=hop_count,
            )
        except asyncio.QueueFull:
            await self._evict_lowest_priority(message)
            self._logger.error(
                "message_dropped_queue_full",
                trace_id=message.trace_id,
                msg_id=message.msg_id,
                topic=message.topic,
            )

    async def _evict_lowest_priority(self, new_message: BusMessage) -> None:
        """背压时丢弃最低优先级消息，并尝试放入新消息

        简化实现：直接丢弃队列中一条消息（最旧的，通过 get_nowait），
        然后放入新消息。避免全队列重建的竞态风险。
        """
        try:
            # 取出一条最旧的消息（FIFO，因为相同 priority 按时间排序）
            dropped = self._queue.get_nowait()
            self._queue.task_done()
            self._logger.error(
                "message_evicted_backpressure",
                trace_id=dropped[2].trace_id,
                msg_id=dropped[2].msg_id,
                priority=dropped[0],
            )
            # 尝试放入新消息
            self._queue.put_nowait(
                (new_message.priority, new_message.timestamp, new_message)
            )
        except (asyncio.QueueEmpty, asyncio.QueueFull) as exc:
            self._logger.error("backpressure_eviction_failed", error=str(exc))

    # ── 消费者 ────────────────────────────────────────────

    async def _start(self) -> None:
        """启动后台消费者任务"""
        if self._running:
            return
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_loop())
        self._logger.info("message_bus_started")

    async def _consume_loop(self) -> None:
        """后台消费循环"""
        while self._running:
            try:
                priority, timestamp, message = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
                try:
                    await self._deliver(message)
                finally:
                    self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                self._logger.error(
                    "consume_loop_error", error=str(exc), exc_info=True
                )

    async def _deliver(self, message: BusMessage) -> None:
        """投递消息给匹配的订阅者

        检查 TTL，过期则丢弃。
        若 recipient 不为 None，仅投递给该 recipient 的 handler。
        若 recipient 为 None，投递给所有匹配 topic 的 handler。

        [V11.4] 全链路追踪：投递前从消息中提取 trace_id 并设置到 contextvars，
        确保消息处理链路上的所有日志都带有相同 trace_id。
        """
        # TTL 检查
        if time.time() > message.timestamp + message.ttl:
            self._logger.warning(
                "message_expired",
                trace_id=message.trace_id,
                msg_id=message.msg_id,
                topic=message.topic,
            )
            return

        # 查找匹配的订阅者
        matched_handlers: list[tuple[str, BusHandler]] = []
        async with self._sub_lock:
            for sub_id, (topic_pattern, subscriber_id, handler) in (
                self._subscriptions.items()
            ):
                if fnmatch.fnmatch(message.topic, topic_pattern):
                    # 如果指定了 recipient，只投递给匹配的
                    if message.recipient is not None:
                        if subscriber_id != message.recipient and subscriber_id != "*":
                            continue
                    matched_handlers.append((sub_id, handler))

        # 投递
        delivery_errors: list[str] = []
        for sub_id, handler in matched_handlers:
            # [V11.4] 设置 trace_id 到上下文，确保 handler 内日志有 trace_id
            trace_token = None
            tc = _get_trace_module()
            if tc is not None and message.trace_id:
                trace_token = tc.set_trace_id(message.trace_id)

            try:
                await handler(message)
                self._logger.info(
                    "message_delivered",
                    trace_id=message.trace_id,
                    msg_id=message.msg_id,
                    subscription_id=sub_id,
                    topic=message.topic,
                )
            except Exception as exc:
                error_msg = str(exc)
                delivery_errors.append(f"{sub_id}: {error_msg}")
                self._logger.error(
                    "message_delivery_failed",
                    trace_id=message.trace_id,
                    msg_id=message.msg_id,
                    subscription_id=sub_id,
                    error=error_msg,
                    exc_info=True,
                )
            finally:
                # [V11.4] 恢复 trace_id 上下文
                if trace_token is not None and tc is not None:
                    tc.reset_trace_id(trace_token)

        # 全部投递失败时转入死信队列
        if matched_handlers and len(delivery_errors) == len(matched_handlers):
            self._dlq.enqueue_delivery_failed(
                message,
                error="; ".join(delivery_errors),
            )

    # ── 工具方法 ──────────────────────────────────────────

    def queue_size(self) -> int:
        """当前队列大小"""
        return self._queue.qsize()

    # ── 优雅关闭 ──────────────────────────────────────────

    async def shutdown(self) -> None:
        """优雅关闭消息总线

        等待队列消费完毕后关闭消费者任务。
        """
        self._logger.info("message_bus_shutting_down")
        self._running = False

        # 等待队列消费完毕
        if not self._queue.empty():
            try:
                await asyncio.wait_for(self._queue.join(), timeout=10.0)
            except asyncio.TimeoutError:
                self._logger.warning(
                    "queue_join_timeout",
                    remaining=self._queue.qsize(),
                )

        # 取消消费者任务
        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

        self._subscriptions.clear()
        self._logger.info("message_bus_shutdown_complete")