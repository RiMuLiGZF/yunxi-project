"""
统一审计框架单元测试
=====================
SC-007 P1级 - 审计日志全覆盖

测试覆盖：
1. 审计事件创建和记录
2. 查询和筛选
3. 导出功能（CSV/JSON）
4. 装饰器功能
5. 防篡改验证（链式哈希）
6. 统计功能
7. 内存存储后端
8. AuthAuditHook 认证审计钩子
"""

import sys
import os
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

# 确保项目根目录在路径中
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
from shared.core.audit_framework import (
    AuditEvent,
    AuditCategory,
    AuditLevel,
    AuditResult,
    AuditLogger,
    MemoryAuditStorage,
    JsonFileAuditStorage,
    audit_log,
    AuthAuditHook,
    AuditMiddleware,
)


# ===========================================================================
# 审计事件模型测试
# ===========================================================================

class TestAuditEvent(unittest.TestCase):
    """审计事件数据模型测试"""

    def test_create_event_defaults(self):
        """测试创建默认审计事件"""
        event = AuditEvent(action="test_action")
        self.assertIsNotNone(event.event_id)
        self.assertEqual(len(event.event_id), 32)  # UUID hex
        self.assertIsNotNone(event.timestamp)
        self.assertEqual(event.category, AuditCategory.SYSTEM)
        self.assertEqual(event.level, AuditLevel.INFO)
        self.assertEqual(event.action, "test_action")
        self.assertEqual(event.result, AuditResult.SUCCESS)

    def test_create_event_full(self):
        """测试创建完整审计事件"""
        event = AuditEvent(
            category=AuditCategory.AUTHENTICATION,
            level=AuditLevel.WARNING,
            actor="user123",
            module="auth",
            action="login_failed",
            resource_type="user",
            resource_id="user123",
            description="密码错误",
            result=AuditResult.FAILURE,
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0",
            request_id="req-001",
            metadata={"attempt": 3, "lockout": False},
        )
        self.assertEqual(event.category, "authentication")
        self.assertEqual(event.level, "warning")
        self.assertEqual(event.actor, "user123")
        self.assertEqual(event.module, "auth")
        self.assertEqual(event.action, "login_failed")
        self.assertEqual(event.resource_type, "user")
        self.assertEqual(event.resource_id, "user123")
        self.assertEqual(event.description, "密码错误")
        self.assertEqual(event.result, "failure")
        self.assertEqual(event.ip_address, "192.168.1.100")
        self.assertEqual(event.user_agent, "Mozilla/5.0")
        self.assertEqual(event.request_id, "req-001")
        self.assertEqual(event.metadata["attempt"], 3)

    def test_event_to_dict(self):
        """测试事件转字典"""
        event = AuditEvent(
            category=AuditCategory.SECURITY,
            action="attack_detected",
            actor="system",
        )
        d = event.to_dict(sanitize=False)
        self.assertEqual(d["category"], "security")
        self.assertEqual(d["action"], "attack_detected")
        self.assertIn("event_id", d)
        self.assertIn("timestamp", d)
        self.assertIn("hash", d)

    def test_event_from_dict(self):
        """测试从字典创建事件"""
        now = datetime.now(tz=timezone.utc)
        data = {
            "event_id": "test-id-123",
            "timestamp": now.isoformat(),
            "category": "authentication",
            "level": "critical",
            "actor": "admin",
            "module": "auth",
            "action": "login",
            "resource_type": "",
            "resource_id": "",
            "description": "管理员登录",
            "result": "success",
            "ip_address": "10.0.0.1",
            "user_agent": "curl/7.0",
            "request_id": "abc",
            "metadata": {"role": "admin"},
            "prev_hash": "",
            "hash": "abc123",
        }
        event = AuditEvent.from_dict(data)
        self.assertEqual(event.event_id, "test-id-123")
        self.assertEqual(event.category, "authentication")
        self.assertEqual(event.level, "critical")
        self.assertEqual(event.actor, "admin")
        self.assertEqual(event._hash, "abc123")

    def test_event_hash_computation(self):
        """测试事件哈希计算"""
        event = AuditEvent(
            category=AuditCategory.AUTHENTICATION,
            action="login",
            actor="user1",
        )
        h = event.compute_hash()
        self.assertEqual(len(h), 64)  # SHA256 hex
        self.assertEqual(event.hash_value, h)

    def test_event_hash_verification(self):
        """测试哈希验证"""
        event = AuditEvent(
            category=AuditCategory.SYSTEM,
            action="test",
            actor="test",
        )
        event.compute_hash()
        self.assertTrue(event.verify_hash())

    def test_event_hash_tamper_detection(self):
        """测试篡改检测"""
        event = AuditEvent(
            category=AuditCategory.SYSTEM,
            action="test",
            actor="test",
        )
        event.compute_hash()
        # 篡改 action
        event.action = "tampered"
        self.assertFalse(event.verify_hash())

    def test_sensitive_data_masking(self):
        """测试敏感数据脱敏"""
        event = AuditEvent(
            action="password_change",
            metadata={
                "password": "mysecret123",
                "token": "eyJabc.def.ghi",
                "api_key": "sk-1234567890abcdef",
                "username": "testuser",
            },
            description="用户修改密码，旧密码为 oldpass123",
        )
        d = event.to_dict(sanitize=True)
        metadata = d.get("metadata", {})
        # 敏感字段应该被脱敏
        self.assertIn("***", str(metadata.get("password", "")))
        self.assertIn("***", str(metadata.get("token", "")))
        self.assertIn("***", str(metadata.get("api_key", "")))
        # 非敏感字段不应该被脱敏
        self.assertEqual(metadata.get("username"), "testuser")

    def test_user_agent_truncation(self):
        """测试 User-Agent 长度截断"""
        long_ua = "A" * 1000
        event = AuditEvent(action="test", user_agent=long_ua)
        self.assertLessEqual(len(event.user_agent), 500)


# ===========================================================================
# 内存存储后端测试
# ===========================================================================

class TestMemoryAuditStorage(unittest.TestCase):
    """内存存储后端测试"""

    def setUp(self):
        self.storage = MemoryAuditStorage()

    def test_append_and_count(self):
        """测试追加记录"""
        self.assertEqual(len(self.storage.get_all()), 0)
        event = AuditEvent(action="test1", actor="user1")
        self.storage.append(event)
        self.assertEqual(len(self.storage.get_all()), 1)

    def test_query_by_category(self):
        """测试按分类查询"""
        self.storage.append(AuditEvent(category=AuditCategory.AUTHENTICATION, action="login"))
        self.storage.append(AuditEvent(category=AuditCategory.SYSTEM, action="start"))
        self.storage.append(AuditEvent(category=AuditCategory.AUTHENTICATION, action="logout"))

        items, total = self.storage.query(category="authentication")
        self.assertEqual(total, 2)
        self.assertEqual(len(items), 2)

    def test_query_by_level(self):
        """测试按级别查询"""
        self.storage.append(AuditEvent(level=AuditLevel.INFO, action="info1"))
        self.storage.append(AuditEvent(level=AuditLevel.WARNING, action="warn1"))
        self.storage.append(AuditEvent(level=AuditLevel.CRITICAL, action="crit1"))
        self.storage.append(AuditEvent(level=AuditLevel.WARNING, action="warn2"))

        items, total = self.storage.query(level="warning")
        self.assertEqual(total, 2)

    def test_query_by_actor(self):
        """测试按操作者查询"""
        self.storage.append(AuditEvent(actor="alice", action="login"))
        self.storage.append(AuditEvent(actor="bob", action="login"))
        self.storage.append(AuditEvent(actor="alice", action="logout"))

        items, total = self.storage.query(actor="alice")
        self.assertEqual(total, 2)

    def test_query_pagination(self):
        """测试分页查询"""
        for i in range(25):
            self.storage.append(AuditEvent(action=f"action_{i}"))

        items, total = self.storage.query(page=1, page_size=10)
        self.assertEqual(total, 25)
        self.assertEqual(len(items), 10)

        items, total = self.storage.query(page=3, page_size=10)
        self.assertEqual(len(items), 5)

    def test_query_time_range(self):
        """测试按时间范围查询"""
        now = datetime.now(tz=timezone.utc)
        old_event = AuditEvent(action="old", timestamp=now - timedelta(days=2))
        new_event = AuditEvent(action="new", timestamp=now)
        self.storage.append(old_event)
        self.storage.append(new_event)

        items, total = self.storage.query(
            start_time=now - timedelta(days=1),
        )
        self.assertEqual(total, 1)
        self.assertEqual(items[0].action, "new")

    def test_query_sort_order(self):
        """测试排序"""
        now = datetime.now(tz=timezone.utc)
        self.storage.append(AuditEvent(action="first", timestamp=now - timedelta(seconds=10)))
        self.storage.append(AuditEvent(action="second", timestamp=now - timedelta(seconds=5)))
        self.storage.append(AuditEvent(action="third", timestamp=now))

        items, _ = self.storage.query(sort_order="desc")
        self.assertEqual(items[0].action, "third")

        items, _ = self.storage.query(sort_order="asc")
        self.assertEqual(items[0].action, "first")

    def test_max_records_limit(self):
        """测试最大记录数限制"""
        storage = MemoryAuditStorage(max_records=10)
        for i in range(20):
            storage.append(AuditEvent(action=f"action_{i}"))
        self.assertLessEqual(len(storage.get_all()), 10)

    def test_last_hash(self):
        """测试获取最后哈希"""
        self.assertEqual(self.storage.get_last_hash(), "")
        event = AuditEvent(action="test")
        self.storage.append(event)
        self.assertNotEqual(self.storage.get_last_hash(), "")

    def test_clean_expired(self):
        """测试清理过期记录"""
        now = datetime.now(tz=timezone.utc)
        self.storage.append(AuditEvent(action="old", timestamp=now - timedelta(days=10)))
        self.storage.append(AuditEvent(action="new", timestamp=now))

        deleted = self.storage.clean_expired(retention_days=5)
        self.assertEqual(deleted, 1)
        self.assertEqual(len(self.storage.get_all()), 1)


# ===========================================================================
# JSON 文件存储后端测试
# ===========================================================================

class TestJsonFileAuditStorage(unittest.TestCase):
    """JSON 文件存储后端测试"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = JsonFileAuditStorage(
            log_dir=Path(self.temp_dir),
            retention_days=180,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_append_and_read(self):
        """测试追加和读取"""
        event = AuditEvent(
            category=AuditCategory.AUTHENTICATION,
            action="login",
            actor="user1",
            ip_address="192.168.1.1",
        )
        self.storage.append(event)

        all_events = self.storage.get_all()
        self.assertEqual(len(all_events), 1)
        self.assertEqual(all_events[0].action, "login")
        self.assertEqual(all_events[0].actor, "user1")

    def test_chain_hash(self):
        """测试链式哈希"""
        event1 = AuditEvent(action="first")
        self.storage.append(event1)

        event2 = AuditEvent(action="second")
        self.storage.append(event2)

        # 第二条记录的 prev_hash 应该等于第一条记录的哈希
        all_events = self.storage.get_all()
        self.assertEqual(len(all_events), 2)
        self.assertEqual(all_events[1].prev_hash, all_events[0].hash_value)

    def test_query_file_storage(self):
        """测试文件存储的查询功能"""
        for i in range(5):
            self.storage.append(AuditEvent(
                category=AuditCategory.SYSTEM if i % 2 == 0 else AuditCategory.SECURITY,
                action=f"action_{i}",
                actor=f"user_{i % 2}",
            ))

        items, total = self.storage.query(category="security")
        self.assertEqual(total, 2)

    def test_export_json(self):
        """测试 JSON 导出（通过 get_all 验证）"""
        self.storage.append(AuditEvent(action="test1", actor="a"))
        self.storage.append(AuditEvent(action="test2", actor="b"))

        all_events = self.storage.get_all()
        self.assertEqual(len(all_events), 2)

        # 验证所有记录都有哈希
        for event in all_events:
            self.assertTrue(event.verify_hash())

    def test_last_hash_persistence(self):
        """测试最后哈希持久化"""
        event = AuditEvent(action="test")
        self.storage.append(event)

        # 创建新的 storage 实例，验证哈希已持久化
        storage2 = JsonFileAuditStorage(log_dir=Path(self.temp_dir))
        self.assertEqual(storage2.get_last_hash(), event.hash_value)


# ===========================================================================
# AuditLogger 主日志器测试
# ===========================================================================

class TestAuditLogger(unittest.TestCase):
    """主审计日志器测试"""

    def setUp(self):
        self.storage = MemoryAuditStorage()
        self.logger = AuditLogger(storage=self.storage)

    def test_log_event(self):
        """测试记录事件"""
        event = AuditEvent(action="test", actor="user1")
        result = self.logger.log(event)
        self.assertIsNotNone(result.event_id)
        self.assertEqual(len(self.storage.get_all()), 1)

    def test_log_simple(self):
        """测试便捷记录方法"""
        self.logger.log_simple(
            action="login",
            category=AuditCategory.AUTHENTICATION,
            level=AuditLevel.INFO,
            actor="user1",
            module="auth",
            result=AuditResult.SUCCESS,
            ip_address="192.168.1.1",
            description="用户登录",
        )
        events = self.storage.get_all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "login")
        self.assertEqual(events[0].category, "authentication")

    def test_query(self):
        """测试查询"""
        for i in range(10):
            self.logger.log_simple(
                action=f"action_{i}",
                category=AuditCategory.SYSTEM if i < 5 else AuditCategory.SECURITY,
                actor=f"user_{i % 3}",
            )

        result = self.logger.query(category=AuditCategory.SECURITY)
        self.assertEqual(result["total"], 5)
        self.assertEqual(len(result["items"]), 5)

    def test_get_event(self):
        """测试获取单条事件"""
        event = AuditEvent(action="test_get")
        self.logger.log(event)

        found = self.logger.get_event(event.event_id)
        self.assertIsNotNone(found)
        self.assertEqual(found["action"], "test_get")

    def test_get_event_not_found(self):
        """测试获取不存在的事件"""
        found = self.logger.get_event("nonexistent-id")
        self.assertIsNone(found)

    def test_export_csv(self):
        """测试 CSV 导出"""
        self.logger.log_simple(action="login", actor="user1", category=AuditCategory.AUTHENTICATION)
        self.logger.log_simple(action="logout", actor="user1", category=AuditCategory.AUTHENTICATION)

        csv_data = self.logger.export(format="csv")
        self.assertIn("事件ID", csv_data)
        self.assertIn("login", csv_data)
        self.assertIn("logout", csv_data)

    def test_export_json(self):
        """测试 JSON 导出"""
        self.logger.log_simple(action="test1", actor="a")
        self.logger.log_simple(action="test2", actor="b")

        json_data = self.logger.export(format="json")
        data = json.loads(json_data)
        self.assertEqual(len(data), 2)

    def test_get_stats(self):
        """测试统计功能"""
        # 添加一些测试数据
        self.logger.log_simple(action="login", category=AuditCategory.AUTHENTICATION, level=AuditLevel.INFO, result="success")
        self.logger.log_simple(action="login_failed", category=AuditCategory.AUTHENTICATION, level=AuditLevel.WARNING, result="failure")
        self.logger.log_simple(action="attack", category=AuditCategory.SECURITY, level=AuditLevel.CRITICAL, result="success")
        self.logger.log_simple(action="module_start", category=AuditCategory.SYSTEM, level=AuditLevel.INFO, result="success")

        stats = self.logger.get_stats(time_range="24h")
        self.assertIn("total", stats)
        self.assertEqual(stats["total"], 4)
        self.assertIn("by_category", stats)
        self.assertIn("by_level", stats)
        self.assertIn("top_actions", stats)
        self.assertEqual(stats["critical_count"], 1)
        self.assertEqual(stats["warning_count"], 1)
        self.assertEqual(stats["failure_count"], 1)

    def test_verify_integrity(self):
        """测试完整性验证"""
        for i in range(5):
            self.logger.log_simple(action=f"action_{i}")

        result = self.logger.verify_integrity()
        self.assertTrue(result["valid"])
        self.assertEqual(result["total_records"], 5)

    def test_verify_integrity_tampered(self):
        """测试篡改后的完整性验证"""
        for i in range(5):
            self.logger.log_simple(action=f"action_{i}")

        # 篡改中间一条记录
        events = self.storage.get_all()
        events[2].action = "tampered"

        result = self.logger.verify_integrity()
        self.assertFalse(result["valid"])
        self.assertEqual(result["error_index"], 2)


# ===========================================================================
# 审计装饰器测试
# ===========================================================================

class TestAuditDecorator(unittest.TestCase):
    """审计装饰器测试"""

    def setUp(self):
        self.storage = MemoryAuditStorage()
        self.logger = AuditLogger(storage=self.storage)

    def test_sync_decorator_success(self):
        """测试同步函数装饰器（成功）"""
        @audit_log("test_action", AuditCategory.SYSTEM, audit_logger=self.logger)
        def my_function(x, y):
            return x + y

        result = my_function(3, 4)
        self.assertEqual(result, 7)

        events = self.storage.get_all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "test_action")
        self.assertEqual(events[0].result, "success")

    def test_sync_decorator_failure(self):
        """测试同步函数装饰器（失败）"""
        @audit_log("risky_action", AuditCategory.SECURITY, audit_logger=self.logger)
        def failing_function():
            raise ValueError("something went wrong")

        with self.assertRaises(ValueError):
            failing_function()

        events = self.storage.get_all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].result, "failure")
        self.assertIn("ValueError", events[0].metadata.get("error_type", ""))

    def test_async_decorator_success(self):
        """测试异步函数装饰器（成功）"""
        import asyncio

        @audit_log("async_action", AuditCategory.API, audit_logger=self.logger)
        async def async_func(x):
            await asyncio.sleep(0.01)
            return x * 2

        result = asyncio.run(async_func(5))
        self.assertEqual(result, 10)

        events = self.storage.get_all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].result, "success")

    def test_decorator_with_current_user(self):
        """测试装饰器从 current_user 提取操作者"""
        @audit_log("user_action", AuditCategory.USER_MANAGEMENT, audit_logger=self.logger)
        def user_func(current_user=None):
            return "done"

        user_func(current_user={"username": "alice", "id": 123})

        events = self.storage.get_all()
        self.assertEqual(events[0].actor, "alice")


# ===========================================================================
# AuthAuditHook 测试
# ===========================================================================

class TestAuthAuditHook(unittest.TestCase):
    """认证审计钩子测试"""

    def setUp(self):
        self.storage = MemoryAuditStorage()
        self.logger = AuditLogger(storage=self.storage)
        self.hook = AuthAuditHook(audit_logger=self.logger)

    def test_log_auth_success(self):
        """测试认证成功审计"""
        self.hook.log_auth(
            request=None,
            auth_result="success",
            auth_type="jwt",
            user_info={"username": "user1", "user_id": "123"},
        )

        events = self.storage.get_all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].category, "authentication")
        self.assertEqual(events[0].result, "success")
        self.assertEqual(events[0].actor, "user1")
        self.assertEqual(events[0].level, "info")

    def test_log_auth_failure(self):
        """测试认证失败审计"""
        self.hook.log_auth(
            request=None,
            auth_result="failed",
            auth_type="jwt",
            error_detail="Token 已过期",
        )

        events = self.storage.get_all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].result, "failure")
        self.assertEqual(events[0].level, "warning")
        self.assertIn("已过期", events[0].description)

    def test_log_auth_denied(self):
        """测试访问拒绝审计"""
        self.hook.log_auth(
            request=None,
            auth_result="denied",
            auth_type="jwt",
            user_info={"username": "user1"},
            error_detail="权限不足",
        )

        events = self.storage.get_all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].level, "warning")


# ===========================================================================
# 审计分类和级别测试
# ===========================================================================

class TestAuditEnums(unittest.TestCase):
    """审计枚举类型测试"""

    def test_all_categories(self):
        """测试所有分类"""
        cats = AuditCategory.all_categories()
        self.assertEqual(len(cats), 8)
        self.assertIn("authentication", cats)
        self.assertIn("authorization", cats)
        self.assertIn("configuration", cats)
        self.assertIn("data_management", cats)
        self.assertIn("user_management", cats)
        self.assertIn("security", cats)
        self.assertIn("system", cats)
        self.assertIn("api", cats)

    def test_all_levels(self):
        """测试所有级别"""
        levels = AuditLevel.all_levels()
        self.assertEqual(len(levels), 3)
        self.assertIn("info", levels)
        self.assertIn("warning", levels)
        self.assertIn("critical", levels)

    def test_category_string_compatibility(self):
        """测试分类字符串兼容性"""
        cat = AuditCategory.AUTHENTICATION
        self.assertEqual(cat, "authentication")
        self.assertTrue(isinstance(cat, str))

    def test_level_string_compatibility(self):
        """测试级别字符串兼容性"""
        lvl = AuditLevel.CRITICAL
        self.assertEqual(lvl, "critical")
        self.assertTrue(isinstance(lvl, str))


# ===========================================================================
# 主入口
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
