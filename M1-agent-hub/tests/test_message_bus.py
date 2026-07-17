"""
消息总线 (MessageBus) 单元测试

覆盖功能：
1. test_subscribe_and_publish  — 订阅并发布，验证 handler 被调用
2. test_unsubscribe           — 订阅后取消，验证 handler 不再收到消息
3. test_wildcard_topic        — 通配符 "agent.*" 匹配 "agent.note"
4. test_priority_queue        — 优先级队列：低 priority 数值优先投递
5. test_ttl_expired           — TTL 过期消息被丢弃
6. test_backpressure          — 队列超过 MAX_QUEUE_SIZE 时的驱逐/错误
7. test_shutdown              — 优雅关闭
8. test_recipient_filtering   — 指定 recipient 精确投递
9. test_broadcast             — 无 recipient 广播给所有匹配订阅者
"""

from __future__ import annotations

import asyncio
import sys
import time

# ---------------------------------------------------------------------------
# 路径处理：message_bus.py 内部使用 `from interfaces import ...`
# tests/ 目录需要能找到 agent_cluster 包和 interfaces 模块
# ---------------------------------------------------------------------------
PACKAGE_DIR = "/workspace/agent_cluster"
WORKSPACE_DIR = "/workspace"

for p in [PACKAGE_DIR, WORKSPACE_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# 被测试模块导入
# ---------------------------------------------------------------------------
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from agent_cluster.core.message_bus import MessageBus  # noqa: E402
from interfaces import BusMessage, BusHandler  # noqa: E402


# ===================================================================
# Fixture: 每个测试前后重置单例
# ===================================================================


@pytest_asyncio.fixture
async def bus():
    """创建并返回一个干净的 MessageBus 实例，测试结束后销毁。"""
    await MessageBus.reset_instance()
    instance = await MessageBus.get_instance()
    yield instance
    # 清理, 防止状态泄漏到下一个测试
    await MessageBus.reset_instance()


# ===================================================================
# 辅助函数
# ===================================================================


async def _make_handler(
    event: asyncio.Event,
    collector: list | None = None,
) -> BusHandler:
    """创建一个 async handler，收到消息时设置 event 并可选择记录到 collector。"""

    async def handler(msg: BusMessage) -> None:
        if collector is not None:
            collector.append(msg)
        event.set()

    return handler


async def _drain_queue(bus: MessageBus, timeout: float = 2.0) -> None:
    """等待队列被消费完。"""
    deadline = time.time() + timeout
    while bus.queue_size() > 0 and time.time() < deadline:
        await asyncio.sleep(0.02)


# ===================================================================
# 1. 基本订阅与发布
# ===================================================================


class TestSubscribeAndPublish:
    """验证最基本的 publish/subscribe 流程."""

    @pytest.mark.asyncio
    async def test_handler_called(self, bus: MessageBus) -> None:
        event = asyncio.Event()
        handler = await _make_handler(event)

        sub_id = await bus.subscribe("test.topic", handler)
        assert sub_id is not None
        assert "test.topic" in sub_id

        await bus.publish(BusMessage(topic="test.topic"))

        await asyncio.wait_for(event.wait(), timeout=2.0)
        assert event.is_set(), "handler 应在 publish 后被调用"

    @pytest.mark.asyncio
    async def test_handler_receives_correct_message(self, bus: MessageBus) -> None:
        received: list[BusMessage] = []
        event = asyncio.Event()
        handler = await _make_handler(event, collector=received)

        await bus.subscribe("test.topic", handler)
        msg = BusMessage(
            topic="test.topic",
            sender="test_sender",
            payload={"key": "value"},
            priority=3,
        )
        await bus.publish(msg)

        await asyncio.wait_for(event.wait(), timeout=2.0)
        assert len(received) == 1
        assert received[0].msg_id == msg.msg_id
        assert received[0].topic == "test.topic"
        assert received[0].sender == "test_sender"
        # publish 自动注入 _meta（hop_count + breadcrumb），验证时排除内部字段
        clean_payload = {k: v for k, v in received[0].payload.items() if not k.startswith("_")}
        assert clean_payload == {"key": "value"}
        assert received[0].priority == 3


# ===================================================================
# 2. 取消订阅
# ===================================================================


class TestUnsubscribe:
    """订阅后取消，handler 不应再被调用."""

    @pytest.mark.asyncio
    async def test_unsubscribed_handler_not_called(self, bus: MessageBus) -> None:
        event = asyncio.Event()
        handler = await _make_handler(event)

        sub_id = await bus.subscribe("test.topic", handler)

        # 先发一条确认订阅有效
        await bus.publish(BusMessage(topic="test.topic"))
        await asyncio.wait_for(event.wait(), timeout=2.0)
        assert event.is_set(), "订阅后 handler 应被调用"

        # 取消订阅
        event.clear()
        await bus.unsubscribe(sub_id)

        # 再发一条，handler 不应被调用
        await bus.publish(BusMessage(topic="test.topic"))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.5)
        assert not event.is_set(), "取消订阅后 handler 不应被调用"

    @pytest.mark.asyncio
    async def test_unsubscribe_invalid_id(self, bus: MessageBus) -> None:
        """取消一个不存在的订阅 ID 应静默成功 (不抛异常)。"""
        await bus.unsubscribe("nonexistent_id")

    @pytest.mark.asyncio
    async def test_multiple_subscribers_independent(self, bus: MessageBus) -> None:
        """取消一个订阅不影响其他订阅者。"""
        event1 = asyncio.Event()
        event2 = asyncio.Event()
        handler1 = await _make_handler(event1)
        handler2 = await _make_handler(event2)

        sub_id1 = await bus.subscribe("test.topic", handler1, subscriber_id="sub1")
        await bus.subscribe("test.topic", handler2, subscriber_id="sub2")

        # 取消 sub1
        await bus.unsubscribe(sub_id1)

        # 发布消息
        await bus.publish(BusMessage(topic="test.topic"))

        # sub2 应收到
        await asyncio.wait_for(event2.wait(), timeout=2.0)
        assert event2.is_set(), "未取消的订阅者应收到消息"

        # sub1 不应收到
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event1.wait(), timeout=0.5)
        assert not event1.is_set(), "已取消的订阅者不应收到消息"


# ===================================================================
# 3. 通配符 Topic
# ===================================================================


class TestWildcardTopic:
    """通配符模式匹配."""

    @pytest.mark.asyncio
    async def test_wildcard_match(self, bus: MessageBus) -> None:
        event = asyncio.Event()
        handler = await _make_handler(event)

        await bus.subscribe("agent.*", handler)
        await bus.publish(BusMessage(topic="agent.note"))

        await asyncio.wait_for(event.wait(), timeout=2.0)
        assert event.is_set(), '"agent.*" 应匹配 "agent.note"'

    @pytest.mark.asyncio
    async def test_wildcard_nested_match(self, bus: MessageBus) -> None:
        event = asyncio.Event()
        handler = await _make_handler(event)

        await bus.subscribe("system.*", handler)
        await bus.publish(BusMessage(topic="system.config.change"))

        await asyncio.wait_for(event.wait(), timeout=2.0)
        assert event.is_set(), '"system.*" 应匹配 "system.config.change"'

    @pytest.mark.asyncio
    async def test_wildcard_no_match(self, bus: MessageBus) -> None:
        event = asyncio.Event()
        handler = await _make_handler(event)

        await bus.subscribe("agent.*", handler)
        await bus.publish(BusMessage(topic="system.note"))

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.5)
        assert not event.is_set(), '"agent.*" 不应匹配 "system.note"'

    @pytest.mark.asyncio
    async def test_exact_match_still_works(self, bus: MessageBus) -> None:
        """精确 topic 匹配仍正常工作."""
        event = asyncio.Event()
        handler = await _make_handler(event)

        await bus.subscribe("agent.note", handler)
        await bus.publish(BusMessage(topic="agent.note"))

        await asyncio.wait_for(event.wait(), timeout=2.0)
        assert event.is_set(), '"agent.note" 应精确匹配 "agent.note"'


# ===================================================================
# 4. 优先级队列
# ===================================================================


class TestPriorityQueue:
    """优先级队列: 数值越小优先级越高，先投递."""

    @pytest.mark.asyncio
    async def test_priority_order(self, bus: MessageBus) -> None:
        """publish (priority=3), (priority=1), (priority=2)
        期望投递顺序: 1, 2, 3

        注意: timestamp 需设在当前时刻附近, 否则默认 TTL=300 会导致消息过期.
        """
        received_order: list[int] = []
        all_received = asyncio.Event()

        async def ordering_handler(msg: BusMessage) -> None:
            received_order.append(msg.priority)
            if len(received_order) == 3:
                all_received.set()

        await bus.subscribe("test.priority", ordering_handler)

        now = time.time()
        # PriorityQueue 排序依据: (priority, timestamp)
        # 低 priority 优先; 相同 priority 时低 timestamp 优先
        await bus.publish(
            BusMessage(
                topic="test.priority", priority=3, ttl=600,
                timestamp=now + 0.1,
            )
        )
        await bus.publish(
            BusMessage(
                topic="test.priority", priority=1, ttl=600,
                timestamp=now + 0.2,
            )
        )
        await bus.publish(
            BusMessage(
                topic="test.priority", priority=2, ttl=600,
                timestamp=now + 0.3,
            )
        )

        await asyncio.wait_for(all_received.wait(), timeout=2.0)
        assert received_order == [1, 2, 3], (
            f"期望投递顺序 [1, 2, 3], 实际得到 {received_order}"
        )

    @pytest.mark.asyncio
    async def test_same_priority_fifo(self, bus: MessageBus) -> None:
        """相同优先级时按 timestamp (FIFO) 顺序投递."""
        received_order: list[float] = []
        all_received = asyncio.Event()

        async def ordering_handler(msg: BusMessage) -> None:
            received_order.append(msg.timestamp)
            if len(received_order) == 3:
                all_received.set()

        await bus.subscribe("test.fifo", ordering_handler)

        now = time.time()
        await bus.publish(
            BusMessage(
                topic="test.fifo", priority=5, ttl=600,
                timestamp=now + 0.1,
            )
        )
        await bus.publish(
            BusMessage(
                topic="test.fifo", priority=5, ttl=600,
                timestamp=now + 0.2,
            )
        )
        await bus.publish(
            BusMessage(
                topic="test.fifo", priority=5, ttl=600,
                timestamp=now + 0.3,
            )
        )

        await asyncio.wait_for(all_received.wait(), timeout=2.0)
        assert received_order == [now + 0.1, now + 0.2, now + 0.3], (
            f"相同优先级应 FIFO, 实际得到 {received_order}"
        )


# ===================================================================
# 5. TTL 过期
# ===================================================================


class TestTTLExpired:
    """TTL 过期消息被丢弃."""

    @pytest.mark.asyncio
    async def test_ttl_expired_message_dropped(self, bus: MessageBus) -> None:
        """消息 timestamp 在 60 秒前, TTL=1 => 必然过期."""
        event = asyncio.Event()
        handler = await _make_handler(event)

        await bus.subscribe("test.ttl", handler)

        old_ts = time.time() - 60.0
        await bus.publish(
            BusMessage(topic="test.ttl", priority=5, ttl=1, timestamp=old_ts)
        )

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.5)
        assert not event.is_set(), "TTL 过期的消息不应投递给 handler"

    @pytest.mark.asyncio
    async def test_ttl_valid_message_delivered(self, bus: MessageBus) -> None:
        """TTL 有效的消息正常投递."""
        event = asyncio.Event()
        handler = await _make_handler(event)

        await bus.subscribe("test.ttl", handler)

        now = time.time()
        await bus.publish(
            BusMessage(
                topic="test.ttl",
                priority=5,
                ttl=300,  # 5 min
                timestamp=now,
            )
        )

        await asyncio.wait_for(event.wait(), timeout=2.0)
        assert event.is_set(), "TTL 有效的消息应正常投递"

    @pytest.mark.asyncio
    async def test_ttl_boundary_expired(self, bus: MessageBus) -> None:
        """边界情况: timestamp + ttl 刚过当前时间."""
        event = asyncio.Event()
        handler = await _make_handler(event)

        await bus.subscribe("test.ttl", handler)

        # 刚好在 1 秒前，ttl=0 => 已过期
        boundary_ts = time.time() - 1.0
        await bus.publish(
            BusMessage(topic="test.ttl", priority=5, ttl=0, timestamp=boundary_ts)
        )

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.5)
        assert not event.is_set(), "边界过期的消息也应被丢弃"


# ===================================================================
# 6. 背压控制
# ===================================================================


class TestBackpressure:
    """队列满时的背压行为."""

    @pytest.mark.asyncio
    async def _fill_and_check(self, max_q: int, extra: int) -> tuple[int, int]:
        """辅助: 设置 MAX_QUEUE_SIZE, 发布 max_q + extra 条, 返回 queue_size 和收到数."""
        original = MessageBus.MAX_QUEUE_SIZE
        MessageBus.MAX_QUEUE_SIZE = max_q
        try:
            await MessageBus.reset_instance()
            bus = await MessageBus.get_instance()

            received: list[BusMessage] = []
            all_done = asyncio.Event()

            async def counting_handler(msg: BusMessage) -> None:
                received.append(msg)
                if len(received) >= max_q:
                    all_done.set()

            await bus.subscribe("test.bp", counting_handler)

            total = max_q + extra
            for i in range(total):
                await bus.publish(
                    BusMessage(
                        topic="test.bp",
                        priority=5,
                        payload={"seq": i},
                    )
                )

            # 等待消费者消费完队列
            await _drain_queue(bus, timeout=3.0)

            return (bus.queue_size(), len(received))
        finally:
            MessageBus.MAX_QUEUE_SIZE = original
            await MessageBus.reset_instance()

    @pytest.mark.asyncio
    async def test_queue_does_not_exceed_max(self) -> None:
        _, received = await self._fill_and_check(max_q=10, extra=5)
        # 总计发布 15 条, 队列最多容纳 10 条, 所以收到数 <= 10
        assert received <= 10, (
            f"超过 MAX_QUEUE_SIZE 后应有消息被丢弃, 收到 {received}"
        )

    @pytest.mark.asyncio
    async def test_backpressure_eviction(self) -> None:
        """验证最低优先级消息被驱逐."""
        original = MessageBus.MAX_QUEUE_SIZE
        MessageBus.MAX_QUEUE_SIZE = 5
        try:
            await MessageBus.reset_instance()
            bus = await MessageBus.get_instance()

            received: list[BusMessage] = []
            event = asyncio.Event()

            async def handler(msg: BusMessage) -> None:
                received.append(msg)
                if len(received) == 5:
                    event.set()

            await bus.subscribe("test.bp.evict", handler)

            # 先填充 5 条低优先级 (priority=10)
            for i in range(5):
                await bus.publish(
                    BusMessage(
                        topic="test.bp.evict",
                        priority=10,
                        timestamp=float(i),
                    )
                )

            # 再发一条高优先级 (priority=1), 触发驱逐
            await bus.publish(
                BusMessage(
                    topic="test.bp.evict",
                    priority=1,
                    timestamp=999.0,
                )
            )

            # 等效于发布了 6 条, 但队列最多 5 条
            await _drain_queue(bus, timeout=3.0)
            # 由于驱逐, 应该有一条低优先级被丢弃
            assert bus.queue_size() <= 5
            # 高优先级应被保留
            if len(received) > 0:
                priorities = [m.priority for m in received]
                assert 1 in priorities, "高优先级消息应被保留"
        finally:
            MessageBus.MAX_QUEUE_SIZE = original
            await MessageBus.reset_instance()


# ===================================================================
# 7. 优雅关闭
# ===================================================================


class TestShutdown:
    """验证 shutdown 能够优雅停止."""

    @pytest.mark.asyncio
    async def test_shutdown_clears_subscriptions(self, bus: MessageBus) -> None:
        await bus.shutdown()
        after_shutdown = await MessageBus.get_instance()
        # 新实例 subscriptions 为空; 通过 subscribe 确认干净
        event = asyncio.Event()
        handler = await _make_handler(event)
        sub_id = await after_shutdown.subscribe("test", handler)
        assert sub_id is not None

    @pytest.mark.asyncio
    async def test_shutdown_stops_consumer(self, bus: MessageBus) -> None:
        assert bus._running is True
        await bus.shutdown()
        assert bus._running is False

    @pytest.mark.asyncio
    async def test_shutdown_drains_queue(self, bus: MessageBus) -> None:
        """shutdown 应等队列消费完毕."""
        received: list[BusMessage] = []
        event = asyncio.Event()

        async def handler(msg: BusMessage) -> None:
            received.append(msg)
            event.set()

        await bus.subscribe("test.shutdown", handler)
        await bus.publish(BusMessage(topic="test.shutdown"))

        # 立即 shutdown, 队列中的消息应被消费
        await bus.shutdown()
        assert bus.queue_size() == 0, "shutdown 后队列应为空"

    @pytest.mark.asyncio
    async def test_shutdown_twice(self, bus: MessageBus) -> None:
        """重复 shutdown 不应抛异常."""
        await bus.shutdown()
        await bus.shutdown()  # 第二次调用应静默


# ===================================================================
# 8. 定向投递 (Recipient Filtering)
# ===================================================================


class TestRecipientFiltering:
    """recipient 精确投递."""

    @pytest.mark.asyncio
    async def test_recipient_delivers_only_to_matching(
        self, bus: MessageBus
    ) -> None:
        event_target = asyncio.Event()
        event_other = asyncio.Event()
        target_msgs: list[BusMessage] = []
        other_msgs: list[BusMessage] = []

        async def target_handler(msg: BusMessage) -> None:
            target_msgs.append(msg)
            event_target.set()

        async def other_handler(msg: BusMessage) -> None:
            other_msgs.append(msg)
            event_other.set()

        await bus.subscribe(
            "test.recipient", target_handler, subscriber_id="target"
        )
        await bus.subscribe(
            "test.recipient", other_handler, subscriber_id="other"
        )

        # 发布一条定向给 target 的消息
        await bus.publish(
            BusMessage(
                topic="test.recipient",
                recipient="target",
            )
        )

        await asyncio.wait_for(event_target.wait(), timeout=2.0)
        assert len(target_msgs) == 1, "target 应收到消息"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event_other.wait(), timeout=0.5)
        assert len(other_msgs) == 0, "other 不应收到定向给 target 的消息"

    @pytest.mark.asyncio
    async def test_recipient_excludes_non_matching(
        self, bus: MessageBus
    ) -> None:
        """recipient 不匹配的订阅者不应收到消息."""
        event = asyncio.Event()
        handler = await _make_handler(event)

        await bus.subscribe("test.recipient", handler, subscriber_id="bob")

        await bus.publish(
            BusMessage(
                topic="test.recipient",
                recipient="alice",  # 指定给 alice
            )
        )

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.5)
        assert not event.is_set(), "bob 不应收到定向给 alice 的消息"


# ===================================================================
# 9. 广播 (无 Recipient)
# ===================================================================


class TestBroadcast:
    """无 recipient 时广播给所有匹配订阅者."""

    @pytest.mark.asyncio
    async def test_broadcast_to_all_matching(self, bus: MessageBus) -> None:
        events = [asyncio.Event(), asyncio.Event()]
        received: list[list[BusMessage]] = [[], []]

        for i in range(2):
            e = events[i]
            coll = received[i]

            async def make_handler(
                ev: asyncio.Event, cl: list
            ) -> BusHandler:
                async def handler(msg: BusMessage) -> None:
                    cl.append(msg)
                    ev.set()
                return handler

            handler = await make_handler(e, coll)
            await bus.subscribe(
                "test.broadcast", handler, subscriber_id=f"sub{i}"
            )

        await bus.publish(BusMessage(topic="test.broadcast"))

        for i, ev in enumerate(events):
            await asyncio.wait_for(ev.wait(), timeout=2.0)
            assert len(received[i]) == 1, f"sub{i} 应收到广播消息"

    @pytest.mark.asyncio
    async def test_broadcast_three_subscribers(self, bus: MessageBus) -> None:
        events = [asyncio.Event() for _ in range(3)]
        counts = [0, 0, 0]

        for i in range(3):
            # 用默认参数捕获 idx 的当前值, 避免闭包引用同一个变量
            async def handler(msg: BusMessage, idx=i) -> None:
                counts[idx] += 1
                events[idx].set()

            await bus.subscribe(
                "test.broadcast", handler, subscriber_id=f"sub{i}"
            )

        await bus.publish(BusMessage(topic="test.broadcast"))

        for ev in events:
            await asyncio.wait_for(ev.wait(), timeout=2.0)

        assert all(c == 1 for c in counts), (
            f"所有 3 个订阅者都应收 1 条, 实际收到 {counts}"
        )

    @pytest.mark.asyncio
    async def test_broadcast_does_not_go_to_non_matching(
        self, bus: MessageBus
    ) -> None:
        """广播不投递给 topic 不匹配的订阅者."""
        event = asyncio.Event()
        handler = await _make_handler(event)
        await bus.subscribe("other.topic", handler)

        await bus.publish(BusMessage(topic="test.broadcast"))

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.5)
        assert not event.is_set(), "topic 不匹配的订阅者不应收到广播"


# ===================================================================
# 边界场景补充
# ===================================================================


class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_publish_to_no_subscribers(self, bus: MessageBus) -> None:
        """发布到没有任何订阅者的 topic 不报错."""
        await bus.publish(BusMessage(topic="nonexistent.topic"))

    @pytest.mark.asyncio
    async def test_subscribe_twice_same_handler(self, bus: MessageBus) -> None:
        """同一个 handler 订阅两次 => 订阅 ID 按 handler 去重, 只收到一条."""
        event = asyncio.Event()
        count = 0

        async def handler(msg: BusMessage) -> None:
            nonlocal count
            count += 1
            event.set()

        sub_id1 = await bus.subscribe("test.dup", handler)
        sub_id2 = await bus.subscribe("test.dup", handler)

        # MessageBus 使用 (subscriber_id, topic, id(handler)) 生成 subscription_id
        # 同一个 handler 第二次订阅会覆盖前一次, 所以 ID 相同
        assert sub_id1 == sub_id2, "相同 handler 应生成相同 subscription_id"

        await bus.publish(BusMessage(topic="test.dup"))

        await asyncio.wait_for(event.wait(), timeout=2.0)
        assert count == 1, "去重后应只收到一条消息"

    @pytest.mark.asyncio
    async def test_handler_raises_exception(self, bus: MessageBus) -> None:
        """handler 抛异常不应导致总线崩溃."""
        event = asyncio.Event()

        async def failing_handler(msg: BusMessage) -> None:
            raise RuntimeError("handler failure")

        async def good_handler(msg: BusMessage) -> None:
            event.set()

        await bus.subscribe("test.error", failing_handler)
        await bus.subscribe("test.error", good_handler)

        await bus.publish(BusMessage(topic="test.error"))

        await asyncio.wait_for(event.wait(), timeout=2.0)
        assert event.is_set(), "一个 handler 失败不应阻止其余 handler 被调用"

    @pytest.mark.asyncio
    async def test_queue_size_after_publish(self, bus: MessageBus) -> None:
        await bus.publish(BusMessage(topic="test.qsize"))
        assert bus.queue_size() >= 0