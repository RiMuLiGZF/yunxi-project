"""
事件总线测试 - 发布/订阅/取消/通配符/历史/重放
"""

import sys
import time
from pathlib import Path

import pytest

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from shared.module_sdk.event_bus import (
    InMemoryEventBus,
    EventBus,
    get_event_bus,
    reset_event_bus,
)
from shared.module_sdk.models import Event


# ============================================================
# InMemoryEventBus 测试
# ============================================================

class TestInMemoryEventBus:
    """内存事件总线测试"""

    def setup_method(self):
        self.bus = InMemoryEventBus(max_history=100)

    def teardown_method(self):
        self.bus.clear()

    def test_publish_subscribe(self):
        """测试基本的发布/订阅"""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe("test.event", handler)
        self.bus.publish("test.event", {"key": "value"})

        assert len(received) == 1
        assert received[0].event_type == "test.event"
        assert received[0].data == {"key": "value"}

    def test_subscribe_returns_id(self):
        """测试订阅返回 ID"""
        def handler(event):
            pass

        sub_id = self.bus.subscribe("test", handler)
        assert isinstance(sub_id, str)
        assert len(sub_id) > 0

    def test_multiple_subscribers(self):
        """测试多个订阅者"""
        received1 = []
        received2 = []

        def handler1(event):
            received1.append(event)

        def handler2(event):
            received2.append(event)

        self.bus.subscribe("test.event", handler1)
        self.bus.subscribe("test.event", handler2)
        self.bus.publish("test.event", {"x": 1})

        assert len(received1) == 1
        assert len(received2) == 1

    def test_unsubscribe(self):
        """测试取消订阅"""
        received = []

        def handler(event):
            received.append(event)

        sub_id = self.bus.subscribe("test.event", handler)
        self.bus.publish("test.event", {"n": 1})
        assert len(received) == 1

        result = self.bus.unsubscribe(sub_id)
        assert result is True

        self.bus.publish("test.event", {"n": 2})
        assert len(received) == 1  # 不再增加

    def test_unsubscribe_nonexistent(self):
        """测试取消不存在的订阅"""
        result = self.bus.unsubscribe("nonexistent-id")
        assert result is False

    def test_wildcard_single_star(self):
        """测试单级通配符 *"""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe("user.*", handler)
        self.bus.publish("user.created", {"id": 1})
        self.bus.publish("user.deleted", {"id": 2})
        self.bus.publish("order.created", {"id": 3})  # 不匹配

        assert len(received) == 2
        assert received[0].event_type == "user.created"
        assert received[1].event_type == "user.deleted"

    def test_wildcard_hash(self):
        """测试多级通配符 #"""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe("module.#", handler)
        self.bus.publish("module.started", {"id": 1})
        self.bus.publish("module.started.error", {"id": 2, "err": "oops"})
        self.bus.publish("other.event", {"id": 3})  # 不匹配

        assert len(received) == 2

    def test_wildcard_hash_all(self):
        """测试 # 匹配所有事件"""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe("#", handler)
        self.bus.publish("a.b.c", {})
        self.bus.publish("x.y", {})
        self.bus.publish("single", {})

        assert len(received) == 3

    def test_event_source(self):
        """测试事件来源"""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe("test", handler)
        self.bus.publish("test", {"a": 1}, source="m1")

        assert received[0].source == "m1"

    def test_event_history(self):
        """测试事件历史记录"""
        self.bus.publish("event.1", {"n": 1})
        self.bus.publish("event.2", {"n": 2})
        self.bus.publish("other.1", {"n": 3})

        # 获取所有历史
        history = self.bus.get_history(limit=10)
        assert len(history) == 3
        # 最新的在前
        assert history[0].event_type == "other.1"

    def test_event_history_filtered(self):
        """测试按类型过滤历史"""
        self.bus.publish("user.created", {"id": 1})
        self.bus.publish("user.deleted", {"id": 2})
        self.bus.publish("order.created", {"id": 3})

        history = self.bus.get_history(event_type="user.*", limit=10)
        assert len(history) == 2

    def test_event_history_limit(self):
        """测试历史记录限制"""
        for i in range(20):
            self.bus.publish(f"event.{i}", {"i": i})

        history = self.bus.get_history(limit=5)
        assert len(history) == 5

    def test_event_history_since(self):
        """测试按时间过滤历史"""
        t0 = time.time()
        self.bus.publish("event.early", {"t": 0})
        time.sleep(0.01)
        t1 = time.time()
        self.bus.publish("event.late", {"t": 1})

        history = self.bus.get_history(since=t1, limit=10)
        assert len(history) >= 1
        assert all(e.event_type == "event.late" for e in history)

    def test_max_history(self):
        """测试最大历史记录数"""
        bus = InMemoryEventBus(max_history=10)
        for i in range(20):
            bus.publish(f"e.{i}", {"i": i})

        history = bus.get_history(limit=100)
        assert len(history) == 10
        bus.clear()

    def test_replay(self):
        """测试事件重放"""
        self.bus.publish("test.a", {"n": 1})
        self.bus.publish("test.b", {"n": 2})
        self.bus.publish("other.c", {"n": 3})

        replayed = []

        def handler(event):
            replayed.append(event)

        count = self.bus.replay("test.*", handler=handler)
        assert count == 2
        assert len(replayed) == 2
        # 重放是按时间顺序（从旧到新）
        assert replayed[0].event_type == "test.a"
        assert replayed[1].event_type == "test.b"

    def test_replay_to_subscribers(self):
        """测试重放到当前订阅者"""
        # 先发布事件
        self.bus.publish("test.a", {"n": 1})

        # 再订阅
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe("test.*", handler)

        # 重放
        count = self.bus.replay("test.*")
        assert count == 1
        # handler 被调用
        assert len(received) == 1

    def test_subscription_count(self):
        """测试订阅数量"""
        assert self.bus.get_subscription_count() == 0

        def h1(e): pass
        def h2(e): pass

        self.bus.subscribe("a", h1)
        assert self.bus.get_subscription_count() == 1
        assert self.bus.get_subscription_count("a") == 1
        assert self.bus.get_subscription_count("b") == 0

        self.bus.subscribe("a", h2)
        assert self.bus.get_subscription_count("a") == 2

    def test_handler_error_does_not_break(self):
        """测试处理器错误不会中断其他处理器"""
        received = []

        def bad_handler(event):
            raise ValueError("oops")

        def good_handler(event):
            received.append(event)

        self.bus.subscribe("test", bad_handler)
        self.bus.subscribe("test", good_handler)

        # 不应抛出异常
        self.bus.publish("test", {"x": 1})
        assert len(received) == 1

    def test_event_id_unique(self):
        """测试事件 ID 唯一"""
        ids = set()

        def handler(event):
            ids.add(event.event_id)

        self.bus.subscribe("test.*", handler)
        for i in range(10):
            self.bus.publish(f"test.{i}", {"i": i})

        assert len(ids) == 10


# ============================================================
# EventBus 统一接口测试
# ============================================================

class TestEventBus:
    """EventBus 统一接口测试"""

    def test_memory_backend(self):
        """测试内存后端"""
        bus = EventBus(backend="memory")
        assert bus.backend == "memory"

        received = []
        def handler(e):
            received.append(e)

        bus.subscribe("test", handler)
        bus.publish("test", {"a": 1})
        assert len(received) == 1

    def test_invalid_backend(self):
        """测试无效后端"""
        with pytest.raises(ValueError, match="Unsupported event bus backend"):
            EventBus(backend="invalid")

    def test_redis_backend_not_implemented(self):
        """测试 Redis 后端未实现"""
        with pytest.raises(NotImplementedError):
            EventBus(backend="redis")

    def test_publish_returns_bool(self):
        """测试 publish 返回布尔值"""
        bus = EventBus(backend="memory")
        result = bus.publish("test", {})
        assert isinstance(result, bool)
        assert result is True

    def test_subscribe_unsubscribe(self):
        """测试订阅和取消订阅"""
        bus = EventBus(backend="memory")
        sub_id = bus.subscribe("test", lambda e: None)
        assert isinstance(sub_id, str)
        assert bus.unsubscribe(sub_id) is True
        assert bus.unsubscribe("nonexistent") is False

    def test_get_history(self):
        """测试获取历史"""
        bus = EventBus(backend="memory")
        bus.publish("a", {})
        bus.publish("b", {})
        history = bus.get_history(limit=10)
        assert len(history) == 2

    def test_replay(self):
        """测试重放"""
        bus = EventBus(backend="memory")
        bus.publish("test.a", {})
        count = bus.replay("test.*", handler=lambda e: None)
        assert count == 1

    def test_clear(self):
        """测试清空"""
        bus = EventBus(backend="memory")
        bus.subscribe("test", lambda e: None)
        bus.publish("test", {})

        bus.clear()
        assert bus.get_subscription_count() == 0
        assert len(bus.get_history()) == 0


# ============================================================
# 全局单例测试
# ============================================================

class TestEventBusSingleton:
    """全局单例测试"""

    def setup_method(self):
        reset_event_bus()

    def teardown_method(self):
        reset_event_bus()

    def test_get_event_bus_singleton(self):
        """测试全局单例"""
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_reset_event_bus(self):
        """测试重置单例"""
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        assert bus1 is not bus2

    def test_get_event_bus_with_config(self):
        """测试首次获取时配置"""
        bus = get_event_bus(backend="memory", max_history=50)
        assert bus.backend == "memory"


# ============================================================
# 异步发布测试
# ============================================================

class TestAsyncPublish:
    """异步发布测试"""

    @pytest.mark.asyncio
    async def test_publish_async(self):
        """测试异步发布"""
        bus = InMemoryEventBus(max_history=100)
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("test.async", handler)

        result = await bus.publish_async("test.async", {"val": 42})
        assert result is True

        # 历史记录应该有
        history = bus.get_history(limit=10)
        assert any(e.event_type == "test.async" for e in history)

        bus.clear()
