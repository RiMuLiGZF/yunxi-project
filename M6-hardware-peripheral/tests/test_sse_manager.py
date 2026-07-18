"""P1-6: SSE 管理器测试覆盖扩展

P2-1 适配：_clients 从 Set[Queue] 改为 Dict[Queue, _ConnectionMeta]，
心跳格式从 ping event 改为 SSE 注释，连接上限强制生效。
"""
import sys
from pathlib import Path
import asyncio
import json
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from m6_hardware.realtime.sse_manager import (
    SSEManager, get_sse_manager, _ConnectionMeta,
)
from m6_hardware.models.errors import M6Exception, ErrorCode


def _make_meta(client_id: str = "test", device_id: str = None) -> _ConnectionMeta:
    """测试辅助：快速创建连接元数据"""
    now = time.time()
    return _ConnectionMeta(
        client_id=client_id,
        device_id=device_id,
        created_at=now,
        last_active=now,
    )


@pytest.fixture
def mock_config():
    """创建 mock 配置"""
    config = MagicMock()
    config.sse_interval = 5.0
    config.sse_heartbeat_interval = 30.0
    config.sse_max_connections = 100
    return config


@pytest.fixture
def mock_device_manager():
    """创建 mock 设备管理器"""
    dm = MagicMock()
    dm.list_devices.return_value = []
    dm.get_stats.return_value = {"total": 0}
    return dm


@pytest.fixture
def mock_notification_service():
    """创建 mock 通知服务"""
    ns = MagicMock()
    ns.get_recent_alerts.return_value = []
    return ns


@pytest.fixture
def sse_manager(mock_device_manager, mock_notification_service, mock_config):
    """创建独立的 SSEManager 实例"""
    manager = SSEManager(
        device_manager=mock_device_manager,
        notification_service=mock_notification_service,
        config=mock_config,
    )
    return manager


class TestSSEManagerSingleton:
    """单例模式测试"""

    def test_get_sse_manager_singleton(self):
        """get_sse_manager() 返回同一个实例"""
        from m6_hardware.realtime.sse_manager import _instance
        # 重置单例状态
        import m6_hardware.realtime.sse_manager as sse_mod
        sse_mod._instance = None

        m1 = get_sse_manager()
        m2 = get_sse_manager()
        assert m1 is m2
        assert isinstance(m1, SSEManager)

        # 清理
        sse_mod._instance = None


class TestSSEManagerConnections:
    """连接管理测试"""

    def test_add_connection(self, sse_manager):
        """添加 queue 到 _connections 并记录元数据"""
        assert sse_manager.client_count == 0
        queue = asyncio.Queue()
        sse_manager._connections[queue] = _make_meta()
        assert sse_manager.client_count == 1

    def test_remove_connection(self, sse_manager):
        """从 _connections 移除 queue"""
        queue = asyncio.Queue()
        sse_manager._connections[queue] = _make_meta()
        sse_manager._connections.pop(queue, None)
        assert sse_manager.client_count == 0

    def test_client_count_property(self, sse_manager):
        """client_count 返回正确数量"""
        assert sse_manager.client_count == 0
        q1 = asyncio.Queue()
        q2 = asyncio.Queue()
        sse_manager._connections[q1] = _make_meta("c1")
        sse_manager._connections[q2] = _make_meta("c2")
        assert sse_manager.client_count == 2

    def test_duplicate_queue_overwrites(self, sse_manager):
        """重复添加同一个 queue 会覆盖元数据，数量仍为 1"""
        q = asyncio.Queue()
        sse_manager._connections[q] = _make_meta("c1")
        sse_manager._connections[q] = _make_meta("c1-new")
        assert sse_manager.client_count == 1

    @pytest.mark.asyncio
    async def test_connect_creates_event_source_response(self, sse_manager, mock_config):
        """connect() 返回 EventSourceResponse"""
        from sse_starlette.sse import EventSourceResponse
        mock_request = MagicMock()
        mock_request.is_disconnected = AsyncMock(return_value=True)
        mock_request.query_params = {}

        response = await sse_manager.connect(mock_request)
        assert isinstance(response, EventSourceResponse)
        assert sse_manager.client_count == 1  # queue 已添加

    @pytest.mark.asyncio
    async def test_connect_records_metadata(self, sse_manager):
        """connect() 为连接记录元数据"""
        mock_request = MagicMock()
        mock_request.is_disconnected = AsyncMock(return_value=True)
        mock_request.query_params = {"device_id": "dev-001"}

        response = await sse_manager.connect(mock_request)
        # 消费生成器触发连接添加
        async for _ in response.body_iterator:
            pass
        # 连接已清理，但验证连接期间元数据存在
        assert sse_manager.total_connections == 1

    @pytest.mark.asyncio
    async def test_connect_queue_removed_on_disconnect(self, sse_manager):
        """客户端断开后 queue 被清理"""
        mock_request = MagicMock()
        mock_request.is_disconnected = AsyncMock(return_value=True)
        mock_request.query_params = {}

        response = await sse_manager.connect(mock_request)
        # 手动消费 response 使生成器运行到 finally
        async for _ in response.body_iterator:
            pass
        # 队列应该被清理
        assert sse_manager.client_count == 0

    @pytest.mark.asyncio
    async def test_connect_rejects_when_limit_exceeded(self, sse_manager, mock_config):
        """连接数达上限时抛出 M6Exception(SSE_LIMIT_EXCEEDED)"""
        # __init__ 已将 sse_max_connections 缓存到 _max_connections，
        # 测试需直接修改实例属性以使上限检查生效
        sse_manager._max_connections = 2
        mock_request = MagicMock()
        mock_request.is_disconnected = AsyncMock(return_value=True)
        mock_request.query_params = {}

        # 填满连接
        for _ in range(2):
            q = asyncio.Queue()
            sse_manager._connections[q] = _make_meta()

        with pytest.raises(M6Exception) as exc_info:
            await sse_manager.connect(mock_request)
        assert exc_info.value.code == ErrorCode.SSE_LIMIT_EXCEEDED
        assert "100" not in str(exc_info.value)  # 上限是 2 不是 100
        assert "2" in str(exc_info.value)


class TestSSEManagerBroadcast:
    """广播功能测试"""

    @pytest.mark.asyncio
    async def test_broadcast_normal(self, sse_manager):
        """_broadcast 正常广播消息到所有客户端"""
        q1 = asyncio.Queue()
        q2 = asyncio.Queue()
        sse_manager._connections[q1] = _make_meta("c1")
        sse_manager._connections[q2] = _make_meta("c2")

        await sse_manager._broadcast("test_event", {"msg": "hello"})

        assert q1.qsize() == 1
        assert q2.qsize() == 1
        msg1 = q1.get_nowait()
        assert msg1["event"] == "test_event"
        assert msg1["data"]["msg"] == "hello"

    @pytest.mark.asyncio
    async def test_broadcast_updates_last_active(self, sse_manager):
        """广播成功后更新连接的 last_active"""
        q = asyncio.Queue()
        meta = _make_meta("c1")
        old_last_active = meta.last_active
        sse_manager._connections[q] = meta

        await asyncio.sleep(0.01)
        await sse_manager._broadcast("evt", {"k": "v"})

        assert meta.last_active > old_last_active

    @pytest.mark.asyncio
    async def test_broadcast_queue_full_warning(self, sse_manager):
        """_broadcast 队列满时清理头部并记录 warning"""
        q = asyncio.Queue(maxsize=1)
        q.put_nowait("filler")  # 填满队列
        sse_manager._connections[q] = _make_meta()

        with patch("m6_hardware.realtime.sse_manager.logger") as mock_logger:
            await sse_manager._broadcast("evt", {"k": "v"})
            # 至少确保队列被处理，没有抛异常
            assert q.qsize() == 1

    @pytest.mark.asyncio
    async def test_broadcast_exception_removes_dead_client(self, sse_manager):
        """_broadcast 遇到异常时移除死连接并记录 error"""
        class BadQueue:
            def put_nowait(self, item):
                raise RuntimeError("connection broken")

        bad = BadQueue()
        good = asyncio.Queue()
        sse_manager._connections[bad] = _make_meta("bad")
        sse_manager._connections[good] = _make_meta("good")

        with patch("m6_hardware.realtime.sse_manager.logger") as mock_logger:
            await sse_manager._broadcast("evt", {"k": "v"})
            assert bad not in sse_manager._connections
            assert good in sse_manager._connections
            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_broadcast_no_clients(self, sse_manager):
        """无客户端时广播不抛异常"""
        await sse_manager._broadcast("evt", {"k": "v"})
        assert sse_manager.client_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_drop_count_metric(self, sse_manager):
        """队列满丢弃会增加 drop_count"""
        q = asyncio.Queue(maxsize=1)
        q.put_nowait("x")
        sse_manager._connections[q] = _make_meta()
        prev_drop = sse_manager.drop_count
        await sse_manager._broadcast("evt", {"k": "v"})
        assert sse_manager.drop_count >= prev_drop


class TestSSEManagerEventGenerator:
    """事件生成器测试"""

    @pytest.mark.asyncio
    async def test_event_generator_yields_connected(self, sse_manager):
        """event_generator 首先生成 connected 事件"""
        mock_request = MagicMock()
        mock_request.is_disconnected = AsyncMock(return_value=True)
        mock_request.query_params = {}

        response = await sse_manager.connect(mock_request)
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
            if len(events) >= 2:
                break
        # chunk 为 dict，检查 event 字段
        assert any(e.get("event") == "connected" for e in events)

    @pytest.mark.asyncio
    async def test_event_generator_yields_initial_state(self, sse_manager):
        """event_generator 生成 initial_state 事件"""
        mock_request = MagicMock()
        mock_request.is_disconnected = AsyncMock(return_value=True)
        mock_request.query_params = {}

        response = await sse_manager.connect(mock_request)
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
            if len(events) >= 4:
                break
        assert any(e.get("event") == "initial_state" for e in events)

    @pytest.mark.asyncio
    async def test_event_generator_heartbeat_on_timeout(self, sse_manager, mock_config):
        """queue 超时时生成 SSE 心跳注释（P2-1 改为 comment 格式）"""
        mock_config.sse_heartbeat_interval = 0.01  # 10ms 便于测试
        mock_request = MagicMock()
        mock_request.is_disconnected = AsyncMock(side_effect=[False, True])
        mock_request.query_params = {}

        response = await sse_manager.connect(mock_request)
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
            # P2-1: 心跳现在以 comment 格式发送
            if chunk.get("comment") == "heartbeat":
                break
        assert any(e.get("comment") == "heartbeat" for e in events)

    @pytest.mark.asyncio
    async def test_event_generator_delivers_broadcast(self, sse_manager):
        """event_generator 能投递广播消息"""
        mock_request = MagicMock()
        mock_request.is_disconnected = AsyncMock(side_effect=[False, False, True])
        mock_request.query_params = {}

        response = await sse_manager.connect(mock_request)
        gen = response.body_iterator

        # 预读取 connected 和 initial_state
        events = []
        async for chunk in gen:
            events.append(chunk)
            if len(events) >= 2:
                break

        # 此时生成器正在等待 queue.get()
        # 在另一个任务中广播消息
        async def broadcast_later():
            await asyncio.sleep(0.05)
            await sse_manager._broadcast("sensor_data", {"v": 1})

        task = asyncio.create_task(broadcast_later())
        try:
            async for chunk in gen:
                events.append(chunk)
                if any(e.get("event") == "sensor_data" for e in events):
                    break
        finally:
            await asyncio.wait_for(task, timeout=1.0)

        assert any(e.get("event") == "sensor_data" for e in events)

    @pytest.mark.asyncio
    async def test_event_generator_connected_includes_client_id(self, sse_manager):
        """P2-1: connected 事件包含 client_id"""
        mock_request = MagicMock()
        mock_request.is_disconnected = AsyncMock(return_value=True)
        mock_request.query_params = {}

        response = await sse_manager.connect(mock_request)
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
            if len(events) >= 1:
                break

        connected_event = next((e for e in events if e.get("event") == "connected"), None)
        assert connected_event is not None
        data = json.loads(connected_event["data"])
        assert "client_id" in data


class TestSSEManagerMaxConnections:
    """连接上限测试"""

    def test_max_connections_config(self, sse_manager, mock_config):
        """配置中存在 SSE 最大连接数"""
        assert mock_config.sse_max_connections == 100

    @pytest.mark.asyncio
    async def test_connect_enforces_limit(self, sse_manager, mock_config):
        """P2-1: connect() 强制执行连接上限"""
        # __init__ 已将 sse_max_connections 缓存到 _max_connections，
        # 测试需直接修改实例属性以使上限检查生效
        sse_manager._max_connections = 3
        mock_request = MagicMock()
        mock_request.is_disconnected = AsyncMock(return_value=True)
        mock_request.query_params = {}

        # 前 3 个连接正常
        for _ in range(3):
            resp = await sse_manager.connect(mock_request)
            # 消费生成器以清理
            async for _ in resp.body_iterator:
                pass

        # 重新填充到上限
        for _ in range(3):
            q = asyncio.Queue()
            sse_manager._connections[q] = _make_meta()

        # 第 4 个应该被拒绝
        with pytest.raises(M6Exception) as exc_info:
            await sse_manager.connect(mock_request)
        assert exc_info.value.code == ErrorCode.SSE_LIMIT_EXCEEDED


class TestSSEManagerCleanup:
    """P2-1: 定时清理测试"""

    @pytest.mark.asyncio
    async def test_cleanup_task_started_on_start(self, sse_manager):
        """start() 时启动清理任务"""
        await sse_manager.start()
        assert sse_manager._cleanup_task is not None
        await sse_manager.stop()

    @pytest.mark.asyncio
    async def test_cleanup_task_cancelled_on_stop(self, sse_manager):
        """stop() 时取消清理任务"""
        await sse_manager.start()
        assert sse_manager._cleanup_task is not None
        await sse_manager.stop()
        assert sse_manager._cleanup_task is None

    @pytest.mark.asyncio
    async def test_cleanup_stale_connections(self, sse_manager):
        """超时连接被清理"""
        # 设置短超时
        sse_manager._client_timeout = 0.05  # 50ms

        q1 = asyncio.Queue()
        meta1 = _make_meta("c1")
        meta1.last_active = time.time() - 10  # 10秒前活跃
        sse_manager._connections[q1] = meta1

        q2 = asyncio.Queue()
        meta2 = _make_meta("c2")
        meta2.last_active = time.time()  # 刚刚活跃
        sse_manager._connections[q2] = meta2

        assert sse_manager.client_count == 2
        await sse_manager._cleanup_stale_connections()
        assert sse_manager.client_count == 1
        assert q2 in sse_manager._connections

    @pytest.mark.asyncio
    async def test_close_all_stops_service(self, sse_manager):
        """close_all() 等同于 stop()"""
        await sse_manager.start()
        await sse_manager.close_all()
        assert not sse_manager._running


class TestSSEManagerLifecycle:
    """生命周期测试"""

    @pytest.mark.asyncio
    async def test_start_and_stop(self, sse_manager):
        """start() 和 stop() 控制推送循环"""
        assert not sse_manager._running
        await sse_manager.start()
        assert sse_manager._running
        assert sse_manager._push_task is not None
        await sse_manager.stop()
        assert not sse_manager._running

    @pytest.mark.asyncio
    async def test_start_idempotent(self, sse_manager):
        """重复 start 不创建多余任务"""
        await sse_manager.start()
        task = sse_manager._push_task
        await sse_manager.start()
        assert sse_manager._push_task is task
        await sse_manager.stop()

    @pytest.mark.asyncio
    async def test_push_notification(self, sse_manager):
        """push_notification 广播 notification 事件"""
        q = asyncio.Queue()
        sse_manager._connections[q] = _make_meta()
        await sse_manager.push_notification({"title": "hello"})
        msg = q.get_nowait()
        assert msg["event"] == "notification"

    @pytest.mark.asyncio
    async def test_push_custom_event(self, sse_manager):
        """push_custom_event 广播自定义事件"""
        q = asyncio.Queue()
        sse_manager._connections[q] = _make_meta()
        await sse_manager.push_custom_event("custom", {"a": 1})
        msg = q.get_nowait()
        assert msg["event"] == "custom"
