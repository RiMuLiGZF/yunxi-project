"""M11 MCP Bus - SSE 管理器单元测试.

测试 SseConnectionManager 的会话管理、消息队列、清理等功能。
"""

import asyncio
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

# 确保项目根目录在 Python 路径中，使 src 作为包导入
# 这样源码中的相对导入（from ..config import ...）才能正确解析
from src.services.sse_manager import SseConnectionManager, SseSession


def async_test(coro):
    """装饰器：将异步测试转换为同步测试."""
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro(*args, **kwargs))
        finally:
            loop.close()
    return wrapper


class TestSseSession(unittest.TestCase):
    """测试 SseSession 类."""

    def test_session_init(self) -> None:
        """测试会话初始化."""
        session = SseSession("test_session_123")
        self.assertEqual(session.session_id, "test_session_123")
        self.assertTrue(session.connected)
        self.assertIsInstance(session.message_queue, asyncio.Queue)
        self.assertEqual(session.client_info, {})

    @async_test
    async def test_put_message_success(self) -> None:
        """测试消息入队成功."""
        session = SseSession("test")
        result = await session.put_message('{"type": "test"}')
        self.assertTrue(result)
        self.assertEqual(session.message_queue.qsize(), 1)

    @async_test
    async def test_get_message_success(self) -> None:
        """测试消息出队正确."""
        session = SseSession("test")
        test_msg = '{"hello": "world"}'
        await session.put_message(test_msg)
        msg = await session.get_message(timeout=1.0)
        self.assertEqual(msg, test_msg)

    @async_test
    async def test_get_message_timeout(self) -> None:
        """测试消息获取超时返回 None."""
        session = SseSession("test")
        msg = await session.get_message(timeout=0.1)
        self.assertIsNone(msg)

    @async_test
    async def test_put_message_updates_last_activity(self) -> None:
        """测试放入消息后更新 last_activity."""
        session = SseSession("test")
        old_activity = session.last_activity
        time.sleep(0.01)
        await session.put_message("test")
        self.assertGreater(session.last_activity, old_activity)

    def test_close_session(self) -> None:
        """测试关闭会话."""
        session = SseSession("test")
        self.assertTrue(session.connected)
        session.close()
        self.assertFalse(session.connected)


class TestSseConnectionManagerSession(unittest.TestCase):
    """测试 SseConnectionManager 的会话管理功能."""

    def setUp(self) -> None:
        """每个测试前创建新的管理器实例，并 mock settings."""
        self.settings_patcher = patch("src.services.sse_manager.get_settings")
        mock_settings = self.settings_patcher.start()
        mock_settings.return_value.sse_max_clients = 100
        self.manager = SseConnectionManager()

    def tearDown(self) -> None:
        """每个测试后清理 patch."""
        self.settings_patcher.stop()

    @async_test
    async def test_create_session_success(self) -> None:
        """测试创建会话成功."""
        session = await self.manager.create_session()
        self.assertIsNotNone(session)
        self.assertIsInstance(session, SseSession)
        self.assertTrue(session.session_id.startswith("sse_"))
        self.assertEqual(await self.manager.get_session_count(), 1)

    @async_test
    async def test_session_id_unique(self) -> None:
        """测试会话 ID 唯一."""
        session1 = await self.manager.create_session()
        session2 = await self.manager.create_session()
        self.assertNotEqual(session1.session_id, session2.session_id)

    @async_test
    async def test_get_session_existing(self) -> None:
        """测试获取存在的会话."""
        session = await self.manager.create_session()
        retrieved = await self.manager.get_session(session.session_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.session_id, session.session_id)

    @async_test
    async def test_get_session_not_found(self) -> None:
        """测试获取不存在的会话返回 None."""
        session = await self.manager.get_session("nonexistent_session")
        self.assertIsNone(session)

    @async_test
    async def test_remove_session(self) -> None:
        """测试移除会话."""
        session = await self.manager.create_session()
        sid = session.session_id
        self.assertEqual(await self.manager.get_session_count(), 1)
        await self.manager.remove_session(sid)
        self.assertEqual(await self.manager.get_session_count(), 0)
        # 会话应该已关闭
        self.assertFalse(session.connected)

    @async_test
    async def test_remove_nonexistent_session_no_error(self) -> None:
        """测试移除不存在的会话不抛异常."""
        await self.manager.remove_session("nonexistent")
        # 不抛异常即通过
        self.assertEqual(await self.manager.get_session_count(), 0)


class TestSseConnectionManagerMessages(unittest.TestCase):
    """测试 SseConnectionManager 的消息推送功能."""

    def setUp(self) -> None:
        """每个测试前创建新的管理器实例，并 mock settings."""
        self.settings_patcher = patch("src.services.sse_manager.get_settings")
        mock_settings = self.settings_patcher.start()
        mock_settings.return_value.sse_max_clients = 100
        self.manager = SseConnectionManager()

    def tearDown(self) -> None:
        """每个测试后清理 patch."""
        self.settings_patcher.stop()

    @async_test
    async def test_send_to_session_success(self) -> None:
        """测试向存在的会话发送消息成功."""
        session = await self.manager.create_session()
        message = {"type": "notification", "data": "hello"}
        result = await self.manager.send_to_session(session.session_id, message)
        self.assertTrue(result)
        # 验证消息在队列中
        msg = await session.get_message(timeout=1.0)
        self.assertIn("notification", msg)
        self.assertIn("hello", msg)

    @async_test
    async def test_send_to_nonexistent_session_returns_false(self) -> None:
        """测试会话不存在时发送消息返回 False."""
        result = await self.manager.send_to_session(
            "nonexistent", {"type": "test"}
        )
        self.assertFalse(result)

    @async_test
    async def test_broadcast_sends_to_all_sessions(self) -> None:
        """测试广播消息发送到所有会话."""
        session1 = await self.manager.create_session()
        session2 = await self.manager.create_session()
        session3 = await self.manager.create_session()
        message = {"type": "broadcast", "content": "all"}
        count = await self.manager.broadcast(message)
        self.assertEqual(count, 3)
        # 每个会话都应该收到消息
        msg1 = await session1.get_message(timeout=1.0)
        msg2 = await session2.get_message(timeout=1.0)
        msg3 = await session3.get_message(timeout=1.0)
        self.assertIsNotNone(msg1)
        self.assertIsNotNone(msg2)
        self.assertIsNotNone(msg3)


class TestSseConnectionManagerCleanup(unittest.TestCase):
    """测试 SseConnectionManager 的过期会话清理功能."""

    def setUp(self) -> None:
        """每个测试前创建新的管理器实例，并 mock settings."""
        self.settings_patcher = patch("src.services.sse_manager.get_settings")
        mock_settings = self.settings_patcher.start()
        mock_settings.return_value.sse_max_clients = 100
        self.manager = SseConnectionManager()

    def tearDown(self) -> None:
        """每个测试后清理 patch."""
        self.settings_patcher.stop()

    @async_test
    async def test_cleanup_stale_sessions(self) -> None:
        """测试清理过期会话."""
        session1 = await self.manager.create_session()
        session2 = await self.manager.create_session()
        # 手动将会话1的 last_activity 设为很久以前
        session1.last_activity = time.time() - 1000  # 1000 秒前

        # 清理超过 60 秒空闲的会话
        cleaned = await self.manager.cleanup_stale_sessions(max_idle=60)
        self.assertEqual(cleaned, 1)
        self.assertEqual(await self.manager.get_session_count(), 1)
        # session2 应该还在
        self.assertIsNotNone(
            await self.manager.get_session(session2.session_id)
        )

    @async_test
    async def test_cleanup_closed_sessions(self) -> None:
        """测试清理已关闭的会话."""
        session = await self.manager.create_session()
        session.close()
        cleaned = await self.manager.cleanup_stale_sessions(max_idle=60)
        self.assertEqual(cleaned, 1)
        self.assertEqual(await self.manager.get_session_count(), 0)

    @async_test
    async def test_cleanup_no_stale_sessions(self) -> None:
        """测试没有过期会话时清理返回 0."""
        await self.manager.create_session()
        await self.manager.create_session()
        cleaned = await self.manager.cleanup_stale_sessions(max_idle=9999)
        self.assertEqual(cleaned, 0)
        self.assertEqual(await self.manager.get_session_count(), 2)


class TestSseConnectionManagerMaxClients(unittest.TestCase):
    """测试 SseConnectionManager 的最大连接数限制."""

    def setUp(self) -> None:
        """每个测试前创建新的管理器实例，并 mock settings."""
        self.settings_patcher = patch("src.services.sse_manager.get_settings")
        mock_settings = self.settings_patcher.start()
        mock_settings.return_value.sse_max_clients = 3  # 限制 3 个连接
        self.manager = SseConnectionManager()

    def tearDown(self) -> None:
        """每个测试后清理 patch."""
        self.settings_patcher.stop()

    @async_test
    async def test_max_connections_limit(self) -> None:
        """测试达到最大连接数后无法创建新会话."""
        s1 = await self.manager.create_session()
        s2 = await self.manager.create_session()
        s3 = await self.manager.create_session()
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        self.assertIsNotNone(s3)
        self.assertEqual(await self.manager.get_session_count(), 3)

        # 第 4 个应该返回 None
        s4 = await self.manager.create_session()
        self.assertIsNone(s4)
        self.assertEqual(await self.manager.get_session_count(), 3)

    @async_test
    async def test_remove_then_can_create_again(self) -> None:
        """测试移除一个会话后可以再创建新的."""
        sessions = []
        for _ in range(3):
            s = await self.manager.create_session()
            sessions.append(s)
        # 已满
        self.assertIsNone(await self.manager.create_session())
        # 移除一个
        await self.manager.remove_session(sessions[0].session_id)
        # 可以再创建
        new_s = await self.manager.create_session()
        self.assertIsNotNone(new_s)


class TestSseFormat(unittest.TestCase):
    """测试 SSE 消息格式化静态方法."""

    def test_format_sse_message(self) -> None:
        """测试 format_sse_message 输出符合 SSE 协议格式."""
        result = SseConnectionManager.format_sse_message("hello world")
        self.assertIn("event: message", result)
        self.assertIn("data: hello world", result)
        # SSE 消息以双换行结尾
        self.assertTrue(result.endswith("\n\n"))

    def test_format_sse_message_custom_event(self) -> None:
        """测试自定义事件类型."""
        result = SseConnectionManager.format_sse_message("data", event="error")
        self.assertIn("event: error", result)

    def test_format_sse_message_multiline_data(self) -> None:
        """测试多行数据的格式化."""
        result = SseConnectionManager.format_sse_message("line1\nline2")
        self.assertIn("data: line1", result)
        self.assertIn("data: line2", result)

    def test_format_heartbeat(self) -> None:
        """测试心跳消息格式."""
        result = SseConnectionManager.format_heartbeat()
        self.assertEqual(result, ": ping\n\n")


if __name__ == "__main__":
    unittest.main()
