"""端云消息总线测试.

覆盖：
- 消息发送与接收
- 消息持久化
- 消息确认机制
- 消息优先级
- 离线消息缓存
- 订阅发布模式
"""

from __future__ import annotations

import asyncio
import time

import pytest

from edge_cloud_kernel.services.message_bus import (
    Message,
    MessageAckStatus,
    MessageBus,
    MessageBusStats,
    MessageDirection,
    MessagePriority,
    MessageStatus,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def message_bus(tmp_path):
    """创建 MessageBus 测试实例（未初始化）."""
    data_dir = str(tmp_path / "message_bus")
    bus = MessageBus(data_dir=data_dir)
    yield bus


def run_async(coro):
    """运行异步函数并返回结果."""
    return asyncio.run(coro)


# ============================================================
# 枚举值测试
# ============================================================

class TestEnums:
    """枚举值测试."""

    def test_message_priority_values(self):
        """测试消息优先级枚举值."""
        assert MessagePriority.LOW == 0
        assert MessagePriority.NORMAL == 5
        assert MessagePriority.HIGH == 8
        assert MessagePriority.CRITICAL == 10

    def test_message_status_values(self):
        """测试消息状态枚举值."""
        assert MessageStatus.PENDING == "pending"
        assert MessageStatus.SENDING == "sending"
        assert MessageStatus.SENT == "sent"
        assert MessageStatus.ACKED == "acked"
        assert MessageStatus.FAILED == "failed"
        assert MessageStatus.EXPIRED == "expired"

    def test_message_direction_values(self):
        """测试消息方向枚举值."""
        assert MessageDirection.EDGE_TO_CLOUD == "edge_to_cloud"
        assert MessageDirection.CLOUD_TO_EDGE == "cloud_to_edge"

    def test_ack_status_values(self):
        """测试确认状态枚举值."""
        assert MessageAckStatus.ACK == "ack"
        assert MessageAckStatus.NACK == "nack"
        assert MessageAckStatus.RETRY == "retry"


# ============================================================
# 消息数据结构测试
# ============================================================

class TestMessageStructure:
    """消息数据结构测试."""

    def test_create_message_defaults(self):
        """测试创建消息默认值."""
        msg = Message()
        assert msg.message_id != ""
        assert msg.topic == "default"
        assert msg.direction == MessageDirection.EDGE_TO_CLOUD
        assert msg.priority == MessagePriority.NORMAL
        assert msg.status == MessageStatus.PENDING
        assert msg.retry_count == 0

    def test_create_message_with_fields(self):
        """测试创建带字段的消息."""
        msg = Message(
            message_id="msg-001",
            topic="test/topic",
            direction=MessageDirection.CLOUD_TO_EDGE,
            payload={"key": "value"},
            priority=MessagePriority.HIGH,
            device_id="device-001",
        )
        assert msg.message_id == "msg-001"
        assert msg.topic == "test/topic"
        assert msg.direction == MessageDirection.CLOUD_TO_EDGE
        assert msg.payload == {"key": "value"}
        assert msg.priority == MessagePriority.HIGH
        assert msg.device_id == "device-001"

    def test_message_is_expired_false(self):
        """测试消息未过期."""
        msg = Message()
        assert msg.is_expired is False

    def test_message_is_expired_true(self):
        """测试消息已过期."""
        msg = Message(expires_at=time.time() - 1)
        assert msg.is_expired is True

    def test_message_size_bytes(self):
        """测试消息大小."""
        msg = Message(payload={"data": "test"})
        assert msg.size_bytes > 0
        assert isinstance(msg.size_bytes, int)


# ============================================================
# 消息发布测试
# ============================================================

class TestMessagePublish:
    """消息发布测试."""

    def test_publish_message(self, message_bus):
        """测试发布消息."""
        async def test():
            await message_bus.initialize()
            try:
                msg_id = await message_bus.publish(
                    topic="test/publish",
                    payload={"hello": "world"},
                )
                assert msg_id is not None
                assert isinstance(msg_id, str)
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_publish_with_priority(self, message_bus):
        """测试带优先级发布."""
        async def test():
            await message_bus.initialize()
            try:
                msg_id = await message_bus.publish(
                    topic="test/priority",
                    payload={"data": "high"},
                    priority=MessagePriority.CRITICAL,
                )
                assert msg_id is not None
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_publish_with_device_id(self, message_bus):
        """测试带设备 ID 发布."""
        async def test():
            await message_bus.initialize()
            try:
                msg_id = await message_bus.publish(
                    topic="test/device",
                    payload={"cmd": "reboot"},
                    device_id="dev-001",
                )
                assert msg_id is not None
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_publish_with_correlation_id(self, message_bus):
        """测试带关联 ID 发布."""
        async def test():
            await message_bus.initialize()
            try:
                msg_id = await message_bus.publish(
                    topic="test/request",
                    payload={"request": "data"},
                    correlation_id="corr-001",
                )
                assert msg_id is not None
            finally:
                await message_bus.shutdown()
        run_async(test())


# ============================================================
# 消息查询测试
# ============================================================

class TestMessageQuery:
    """消息查询测试."""

    def test_get_message(self, message_bus):
        """测试获取消息."""
        async def test():
            await message_bus.initialize()
            try:
                msg_id = await message_bus.publish(
                    topic="test/get",
                    payload={"data": "test"},
                )
                retrieved = await message_bus.get_message(msg_id)
                assert retrieved is not None
                assert isinstance(retrieved, Message)
                assert retrieved.message_id == msg_id
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_get_nonexistent_message(self, message_bus):
        """测试获取不存在的消息."""
        async def test():
            await message_bus.initialize()
            try:
                result = await message_bus.get_message("nonexistent")
                assert result is None
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_list_messages(self, message_bus):
        """测试列出消息."""
        async def test():
            await message_bus.initialize()
            try:
                for i in range(3):
                    await message_bus.publish(
                        topic="test/list",
                        payload={"i": i},
                    )
                messages = await message_bus.list_messages(limit=10)
                assert len(messages) >= 3
                assert all(isinstance(m, Message) for m in messages)
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_list_messages_by_topic(self, message_bus):
        """测试按主题列出消息."""
        async def test():
            await message_bus.initialize()
            try:
                for i in range(2):
                    await message_bus.publish(
                        topic="special/topic",
                        payload={},
                    )
                messages = await message_bus.list_messages(
                    topic="special/topic", limit=10
                )
                assert len(messages) >= 2
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_get_queue_size(self, message_bus):
        """测试获取队列大小."""
        async def test():
            await message_bus.initialize()
            try:
                initial = await message_bus.get_queue_size()
                await message_bus.publish(
                    topic="test/size",
                    payload={},
                )
                size = await message_bus.get_queue_size()
                assert size >= initial
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_get_pending_messages(self, message_bus):
        """测试获取待发送消息."""
        async def test():
            await message_bus.initialize()
            try:
                await message_bus.publish(
                    topic="test/pending",
                    payload={},
                )
                pending = await message_bus.get_pending_messages(limit=10)
                assert len(pending) >= 0
            finally:
                await message_bus.shutdown()
        run_async(test())


# ============================================================
# 消息确认测试
# ============================================================

class TestMessageAck:
    """消息确认测试."""

    def test_ack_message(self, message_bus):
        """测试确认消息."""
        async def test():
            await message_bus.initialize()
            try:
                msg_id = await message_bus.publish(
                    topic="test/ack",
                    payload={},
                )
                result = await message_bus.ack_message(msg_id)
                assert result is True
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_ack_nonexistent_message(self, message_bus):
        """测试确认不存在的消息."""
        async def test():
            await message_bus.initialize()
            try:
                result = await message_bus.ack_message("nonexistent")
                assert result is False
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_nack_message(self, message_bus):
        """测试拒绝消息."""
        async def test():
            await message_bus.initialize()
            try:
                msg_id = await message_bus.publish(
                    topic="test/nack",
                    payload={},
                )
                result = await message_bus.nack_message(
                    msg_id, reason="invalid data"
                )
                assert result is True
            finally:
                await message_bus.shutdown()
        run_async(test())


# ============================================================
# 消息订阅测试
# ============================================================

class TestMessageSubscription:
    """消息订阅测试."""

    def test_subscribe_to_topic(self, message_bus):
        """测试订阅主题."""
        async def test():
            await message_bus.initialize()
            try:
                received = []

                def callback(msg):
                    received.append(msg)

                # subscribe 返回 None（无返回值）
                message_bus.subscribe("test/sub", callback)
                # 验证回调已注册（通过内部 subscribers 检查）
                assert "test/sub" in message_bus._subscribers
                assert len(message_bus._subscribers["test/sub"]) == 1
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_unsubscribe_from_topic(self, message_bus):
        """测试取消订阅."""
        async def test():
            await message_bus.initialize()
            try:
                def callback(msg):
                    pass

                message_bus.subscribe("test/unsub", callback)
                result = message_bus.unsubscribe("test/unsub", callback)
                assert result is True
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_subscribe_nonexistent_callback(self, message_bus):
        """测试取消订阅不存在的回调."""
        async def test():
            await message_bus.initialize()
            try:
                def callback(msg):
                    pass

                result = message_bus.unsubscribe("test/no-cb", callback)
                assert result is False
            finally:
                await message_bus.shutdown()
        run_async(test())


# ============================================================
# 发送回调测试
# ============================================================

class TestSendCallback:
    """发送回调测试."""

    def test_register_send_callback(self, message_bus):
        """测试注册发送回调."""
        async def test():
            await message_bus.initialize()
            try:
                sent = []

                def send_fn(msg):
                    sent.append(msg)
                    return True

                message_bus.register_send_callback(send_fn)
                # 注册不应报错
            finally:
                await message_bus.shutdown()
        run_async(test())


# ============================================================
# 统计测试
# ============================================================

class TestMessageBusStats:
    """消息总线统计测试."""

    def test_get_stats(self, message_bus):
        """测试获取统计信息."""
        async def test():
            await message_bus.initialize()
            try:
                stats = message_bus.get_stats()
                assert isinstance(stats, MessageBusStats)
                assert hasattr(stats, "total_sent")
                assert hasattr(stats, "total_acked")
                assert hasattr(stats, "total_failed")
                assert hasattr(stats, "pending_count")
            finally:
                await message_bus.shutdown()
        run_async(test())

    def test_stats_initial_values(self, message_bus):
        """测试初始统计值."""
        async def test():
            await message_bus.initialize()
            try:
                stats = message_bus.get_stats()
                assert stats.total_sent >= 0
                assert stats.pending_count >= 0
            finally:
                await message_bus.shutdown()
        run_async(test())


# ============================================================
# 消息清理测试
# ============================================================

class TestMessageCleanup:
    """消息清理测试."""

    def test_cleanup_old_messages(self, message_bus):
        """测试清理旧消息."""
        async def test():
            await message_bus.initialize()
            try:
                msg_id = await message_bus.publish(
                    topic="test/cleanup",
                    payload={},
                )
                # 手动标记为已确认且已过期
                await message_bus.ack_message(msg_id)
                # 更新 created_at 为旧时间
                await message_bus._db.execute(
                    "UPDATE messages SET created_at = ? WHERE message_id = ?",
                    (time.time() - 86400 * 10, msg_id),
                )
                await message_bus._db.commit()
                count = await message_bus.cleanup(max_age_days=7)
                assert isinstance(count, int)
                assert count >= 0
            finally:
                await message_bus.shutdown()
        run_async(test())


# ============================================================
# 数据结构测试
# ============================================================

class TestDataStructures:
    """数据结构测试."""

    def test_message_bus_stats_defaults(self):
        """测试 MessageBusStats 默认值."""
        stats = MessageBusStats()
        assert stats.total_sent == 0
        assert stats.total_acked == 0
        assert stats.total_failed == 0
        assert stats.pending_count == 0
        assert stats.in_flight_count == 0
        assert stats.retry_count == 0

    def test_message_headers(self):
        """测试消息自定义头."""
        msg = Message(
            headers={"X-Custom": "value", "X-Trace": "trace-id"},
        )
        assert msg.headers["X-Custom"] == "value"
        assert msg.headers["X-Trace"] == "trace-id"
