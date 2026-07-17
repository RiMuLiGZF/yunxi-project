"""
M6 可穿戴设备模块 P1 优化单元测试
==================================

测试覆盖：
- 错误码体系 (P1-4)
- 数据库连接 WAL 模式 (P1-08)
- TTL 缓存 (P1-6-1)
- 事件钩子 (P1-03)
- 迁移脚本重试 (P1-03)
- 迁移脚本断点续传 (P1-04)
- 迁移脚本进度追踪 (P1-05)
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from datetime import datetime, timedelta

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# P1-4: 错误码体系测试
# ============================================================================

class TestErrorCodeSystem(unittest.TestCase):
    """测试统一错误码体系"""

    def test_wearable_error_codes_exist(self):
        """可穿戴设备错误码应存在"""
        from m6_hardware.models.errors import ErrorCode

        # 可穿戴设备域错误码 (4xx)
        self.assertTrue(hasattr(ErrorCode, "WEARABLE_DEVICE_NOT_FOUND"))
        self.assertTrue(hasattr(ErrorCode, "WEARABLE_DEVICE_ALREADY_EXISTS"))
        self.assertTrue(hasattr(ErrorCode, "WEARABLE_DEVICE_TYPE_INVALID"))
        self.assertTrue(hasattr(ErrorCode, "WEARABLE_HEALTH_DATA_INVALID"))
        self.assertTrue(hasattr(ErrorCode, "WEARABLE_HEALTH_DATA_TYPE_UNSUPPORTED"))
        self.assertTrue(hasattr(ErrorCode, "WEARABLE_NOTIFICATION_NOT_FOUND"))
        self.assertTrue(hasattr(ErrorCode, "WEARABLE_SETTINGS_NOT_FOUND"))
        self.assertTrue(hasattr(ErrorCode, "WEARABLE_BATCH_SIZE_EXCEEDED"))
        self.assertTrue(hasattr(ErrorCode, "WEARABLE_MAC_ADDRESS_INVALID"))

    def test_wearable_error_code_values(self):
        """可穿戴设备错误码值应在 4xx 范围内"""
        from m6_hardware.models.errors import ErrorCode

        wearable_codes = [
            ErrorCode.WEARABLE_DEVICE_NOT_FOUND,
            ErrorCode.WEARABLE_DEVICE_ALREADY_EXISTS,
            ErrorCode.WEARABLE_DEVICE_TYPE_INVALID,
            ErrorCode.WEARABLE_HEALTH_DATA_INVALID,
            ErrorCode.WEARABLE_HEALTH_DATA_TYPE_UNSUPPORTED,
            ErrorCode.WEARABLE_NOTIFICATION_NOT_FOUND,
            ErrorCode.WEARABLE_SETTINGS_NOT_FOUND,
            ErrorCode.WEARABLE_BATCH_SIZE_EXCEEDED,
            ErrorCode.WEARABLE_MAC_ADDRESS_INVALID,
        ]
        for code in wearable_codes:
            self.assertGreaterEqual(code.value, 440)
            self.assertLess(code.value, 450)

    def test_m6_exception_creation(self):
        """M6Exception 应正确创建并携带 details"""
        from m6_hardware.models.errors import M6Exception, ErrorCode

        exc = M6Exception(
            code=ErrorCode.WEARABLE_DEVICE_NOT_FOUND,
            message="设备不存在",
            details={"device_id": "test-001"},
        )
        self.assertEqual(exc.code, ErrorCode.WEARABLE_DEVICE_NOT_FOUND)
        self.assertEqual(exc.message, "设备不存在")
        self.assertEqual(exc.details["device_id"], "test-001")
        self.assertEqual(exc.http_status, 404)  # NOT_FOUND 应映射到 404

    def test_m6_exception_http_status_inference(self):
        """错误码应正确映射到 HTTP 状态码"""
        from m6_hardware.models.errors import M6Exception, ErrorCode

        # 404 类
        exc1 = M6Exception(ErrorCode.WEARABLE_DEVICE_NOT_FOUND, "x")
        self.assertEqual(exc1.http_status, 404)

        exc2 = M6Exception(ErrorCode.WEARABLE_NOTIFICATION_NOT_FOUND, "x")
        self.assertEqual(exc2.http_status, 404)

        # 409 类
        exc3 = M6Exception(ErrorCode.WEARABLE_DEVICE_ALREADY_EXISTS, "x")
        self.assertEqual(exc3.http_status, 409)

        exc4 = M6Exception(ErrorCode.WEARABLE_BATCH_SIZE_EXCEEDED, "x")
        self.assertEqual(exc4.http_status, 409)

        # 400 类
        exc5 = M6Exception(ErrorCode.WEARABLE_HEALTH_DATA_INVALID, "x")
        self.assertEqual(exc5.http_status, 400)

    def test_m6_exception_to_dict(self):
        """M6Exception 应能转换为标准字典格式"""
        from m6_hardware.models.errors import M6Exception, ErrorCode

        exc = M6Exception(
            code=ErrorCode.WEARABLE_MAC_ADDRESS_INVALID,
            message="MAC 地址无效",
            details={"mac": "invalid"},
        )
        d = exc.to_dict()
        self.assertEqual(d["code"], ErrorCode.WEARABLE_MAC_ADDRESS_INVALID)
        self.assertEqual(d["message"], "MAC 地址无效")
        self.assertIn("mac", d["details"])


# ============================================================================
# P1-08: 数据库性能优化测试
# ============================================================================

class TestDatabasePerformance(unittest.TestCase):
    """测试数据库 WAL 模式和性能 PRAGMA"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmp_dir) / "test.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_wal_mode_enabled(self):
        """数据库连接应启用 WAL 模式"""
        from m6_hardware.database.connection import DatabaseConnection

        with DatabaseConnection(self.db_path) as conn:
            cursor = conn.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            self.assertEqual(mode.lower(), "wal")

    def test_pragmas_applied(self):
        """关键 PRAGMA 应正确设置"""
        from m6_hardware.database.connection import DatabaseConnection, DEFAULT_PRAGMAS

        with DatabaseConnection(self.db_path) as conn:
            # 检查 busy_timeout
            cursor = conn.execute("PRAGMA busy_timeout")
            result = cursor.fetchone()[0]
            self.assertEqual(result, int(DEFAULT_PRAGMAS["busy_timeout"]))

            # 检查 foreign_keys
            cursor = conn.execute("PRAGMA foreign_keys")
            result = cursor.fetchone()[0]
            self.assertEqual(result, 1)  # ON

    def test_cleanup_expired_data(self):
        """TTL 清理应正确删除过期数据"""
        from m6_hardware.database.connection import (
            DatabaseConnection,
            _init_tables,
            cleanup_expired_data,
        )

        # 初始化表
        with DatabaseConnection(self.db_path) as conn:
            _init_tables(conn)

            # 插入一些过期和未过期的健康数据
            old_date = (datetime.now() - timedelta(days=100)).isoformat()
            new_date = datetime.now().isoformat()

            conn.execute(
                """INSERT INTO wearable_health_data
                   (device_id, user_id, data_type, value, unit, recorded_at, source, quality, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("dev-1", "u1", "heart_rate", 70, "bpm", old_date, "device", "good", old_date),
            )
            conn.execute(
                """INSERT INTO wearable_health_data
                   (device_id, user_id, data_type, value, unit, recorded_at, source, quality, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("dev-2", "u1", "steps", 1000, "step", new_date, "device", "good", new_date),
            )
            conn.commit()

            # 执行 TTL 清理（保留 90 天）
            result = cleanup_expired_data(conn, health_ttl_days=90)

            # 验证旧数据被删除
            self.assertGreaterEqual(result.get("health_data_deleted", 0), 1)

            # 验证新数据还在
            cursor = conn.execute("SELECT COUNT(*) FROM wearable_health_data")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 1)  # 只剩新数据


# ============================================================================
# P1-6-1: LRU 缓存 + TTL 测试
# ============================================================================

class TestTTLCache(unittest.TestCase):
    """测试带 TTL 的 LRU 缓存"""

    def test_basic_set_get(self):
        """基本的 set/get 操作"""
        from m6_hardware.services.wearable_service import TTLCache

        cache = TTLCache(max_size=10, ttl_seconds=60)
        cache.set("key1", "value1")
        self.assertEqual(cache.get("key1"), "value1")

    def test_cache_miss(self):
        """不存在的 key 应返回 None"""
        from m6_hardware.services.wearable_service import TTLCache

        cache = TTLCache(max_size=10, ttl_seconds=60)
        self.assertIsNone(cache.get("nonexistent"))

    def test_ttl_expiration(self):
        """TTL 过期的条目应返回 None"""
        from m6_hardware.services.wearable_service import TTLCache

        cache = TTLCache(max_size=10, ttl_seconds=0.1)  # 100ms TTL
        cache.set("key1", "value1")
        self.assertEqual(cache.get("key1"), "value1")

        time.sleep(0.15)  # 等待过期
        self.assertIsNone(cache.get("key1"))

    def test_max_size_eviction(self):
        """超出容量应淘汰最久未使用的条目"""
        from m6_hardware.services.wearable_service import TTLCache

        cache = TTLCache(max_size=3, ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)

        # 访问 a，使其变为最近使用
        cache.get("a")

        # 插入 d，应淘汰 b（最久未使用）
        cache.set("d", 4)

        self.assertEqual(cache.get("a"), 1)  # 最近使用，保留
        self.assertIsNone(cache.get("b"))  # 最久未使用，被淘汰
        self.assertEqual(cache.get("c"), 3)
        self.assertEqual(cache.get("d"), 4)

    def test_invalidate(self):
        """invalidate 应删除指定条目"""
        from m6_hardware.services.wearable_service import TTLCache

        cache = TTLCache(max_size=10, ttl_seconds=60)
        cache.set("key1", "value1")
        self.assertTrue(cache.invalidate("key1"))
        self.assertIsNone(cache.get("key1"))
        self.assertFalse(cache.invalidate("key1"))  # 再次删除返回 False

    def test_clear(self):
        """clear 应清空所有条目"""
        from m6_hardware.services.wearable_service import TTLCache

        cache = TTLCache(max_size=10, ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        self.assertEqual(cache.stats()["size"], 0)

    def test_stats(self):
        """统计信息应正确记录"""
        from m6_hardware.services.wearable_service import TTLCache

        cache = TTLCache(max_size=10, ttl_seconds=60)
        cache.set("a", 1)
        cache.get("a")  # hit
        cache.get("a")  # hit
        cache.get("b")  # miss

        stats = cache.stats()
        self.assertEqual(stats["hits"], 2)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["size"], 1)
        self.assertGreater(stats["hit_rate_percent"], 0)


# ============================================================================
# P1-03: 事件钩子测试
# ============================================================================

class TestEventHooks(unittest.TestCase):
    """测试事件回调钩子"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmp_dir) / "test_service.db")
        # 初始化数据库表
        from m6_hardware.database.connection import DatabaseConnection, _init_tables
        with DatabaseConnection(self.db_path) as conn:
            _init_tables(conn)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_on_event_registration(self):
        """应能注册事件回调"""
        from m6_hardware.services.wearable_service import WearableService

        service = WearableService(db_manager=None, db_name="test")
        events = []

        def handler(device):
            events.append(device)

        service.on("device_created", handler)
        self.assertEqual(len(service._event_handlers["device_created"]), 1)

    def test_invalid_event_raises(self):
        """注册不支持的事件应抛出 ValueError"""
        from m6_hardware.services.wearable_service import WearableService

        service = WearableService(db_manager=None, db_name="test")
        with self.assertRaises(ValueError):
            service.on("invalid_event", lambda x: x)

    def _create_service(self):
        """创建使用临时数据库的 WearableService"""
        from m6_hardware.services.wearable_service import WearableService
        from shared.data_layer import DatabaseManager
        from m6_hardware.database.connection import _init_tables
        import sqlite3

        # 使用 DatabaseManager 指向临时数据库目录
        db_manager = DatabaseManager(data_root=self.tmp_dir)
        service = WearableService(db_manager=db_manager, db_name="test_service")

        # 手动初始化表（通过 DatabaseManager 的连接执行 _init_tables）
        db_path = db_manager._get_db_path("test_service")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        _init_tables(conn)
        conn.close()

        return service

    def test_device_created_event(self):
        """创建设备应触发 device_created 事件"""
        service = self._create_service()
        created_devices = []

        def on_created(device):
            created_devices.append(device)

        service.on("device_created", on_created)

        device = service.create_device({
            "device_id": "test-watch-001",
            "user_id": "test_user",
            "name": "测试手表",
            "device_type": "watch",
            "status": "online",
        })

        self.assertEqual(len(created_devices), 1)
        self.assertEqual(created_devices[0]["device_id"], "test-watch-001")

    def test_device_status_changed_event(self):
        """状态变更应触发 device_status_changed 事件"""
        service = self._create_service()
        status_changes = []

        def on_status_changed(device_id, old_status, new_status):
            status_changes.append((device_id, old_status, new_status))

        service.on("device_status_changed", on_status_changed)

        # 创建设备
        service.create_device({
            "device_id": "test-watch-002",
            "user_id": "test_user",
            "name": "测试手表",
            "device_type": "watch",
            "status": "offline",
        })

        # 更新状态
        service.update_device("test-watch-002", {"status": "online"})

        self.assertEqual(len(status_changes), 1)
        self.assertEqual(status_changes[0][0], "test-watch-002")
        self.assertEqual(status_changes[0][1], "offline")
        self.assertEqual(status_changes[0][2], "online")

    def test_device_deleted_event(self):
        """删除设备应触发 device_deleted 事件"""
        service = self._create_service()
        deleted_ids = []

        def on_deleted(device_id):
            deleted_ids.append(device_id)

        service.on("device_deleted", on_deleted)

        service.create_device({
            "device_id": "test-watch-003",
            "user_id": "test_user",
            "device_type": "watch",
            "status": "offline",
        })
        service.delete_device("test-watch-003")

        self.assertEqual(len(deleted_ids), 1)
        self.assertEqual(deleted_ids[0], "test-watch-003")


# ============================================================================
# P1-03: 重试工具测试
# ============================================================================

class TestRetryWithBackoff(unittest.TestCase):
    """测试指数退避重试工具"""

    def test_successful_first_try(self):
        """首次成功不应重试"""
        from scripts.migrate_wearable_m8_to_m6 import retry_with_backoff

        call_count = 0

        def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = retry_with_backoff(success_func, max_retries=3, base_delay=0.01)
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 1)

    def test_retry_then_success(self):
        """失败几次后成功"""
        from scripts.migrate_wearable_m8_to_m6 import retry_with_backoff

        call_count = 0

        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary error")
            return "eventual success"

        result = retry_with_backoff(flaky_func, max_retries=3, base_delay=0.01)
        self.assertEqual(result, "eventual success")
        self.assertEqual(call_count, 3)

    def test_max_retries_exhausted(self):
        """超过最大重试次数应抛出最后一次异常"""
        from scripts.migrate_wearable_m8_to_m6 import retry_with_backoff

        call_count = 0

        def always_fails():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("always fails")

        with self.assertRaises(RuntimeError):
            retry_with_backoff(always_fails, max_retries=2, base_delay=0.01)

        self.assertEqual(call_count, 3)  # 1 次首次 + 2 次重试


# ============================================================================
# P1-05: 进度追踪测试
# ============================================================================

class TestProgressTracker(unittest.TestCase):
    """测试进度追踪器"""

    def test_progress_calculation(self):
        """进度百分比应正确计算"""
        from scripts.migrate_wearable_m8_to_m6 import ProgressTracker

        tracker = ProgressTracker(100, label="测试")
        tracker.update(30)
        report = tracker.get_report()
        self.assertIn("30/100", report)
        self.assertIn("30.0%", report)

    def test_zero_total(self):
        """总数为 0 时不应崩溃"""
        from scripts.migrate_wearable_m8_to_m6 import ProgressTracker

        tracker = ProgressTracker(0, label="测试")
        report = tracker.get_report()
        self.assertIn("0%", report)

    def test_should_report(self):
        """should_report 应按间隔返回 True"""
        from scripts.migrate_wearable_m8_to_m6 import ProgressTracker

        tracker = ProgressTracker(100, label="测试")
        tracker.report_interval = 0.1  # 100ms

        # 首次应立即可以报告
        self.assertTrue(tracker.should_report())

        # 刚报告过，不应立即再次报告
        tracker.last_report = time.time()
        self.assertFalse(tracker.should_report())

        time.sleep(0.12)
        self.assertTrue(tracker.should_report())


# ============================================================================
# P1-04: 断点续传测试
# ============================================================================

class TestCheckpoint(unittest.TestCase):
    """测试 checkpoint 断点管理"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save_and_load_checkpoint(self):
        """保存和加载 checkpoint"""
        # 临时替换 checkpoint 路径
        import scripts.migrate_wearable_m8_to_m6 as mig
        original_path = mig.CHECKPOINT_PATH
        mig.CHECKPOINT_PATH = Path(self.tmp_dir) / "test_checkpoint.json"

        try:
            test_data = {
                "timestamp": datetime.now().isoformat(),
                "health_offset": 5000,
                "migrated_so_far": 4500,
            }

            mig.save_checkpoint(test_data)
            self.assertTrue(mig.CHECKPOINT_PATH.exists())

            loaded = mig.load_checkpoint()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["health_offset"], 5000)
            self.assertEqual(loaded["migrated_so_far"], 4500)
        finally:
            mig.CHECKPOINT_PATH = original_path

    def test_clear_checkpoint(self):
        """清除 checkpoint"""
        import scripts.migrate_wearable_m8_to_m6 as mig
        original_path = mig.CHECKPOINT_PATH
        mig.CHECKPOINT_PATH = Path(self.tmp_dir) / "test_checkpoint.json"

        try:
            mig.save_checkpoint({"test": True})
            self.assertTrue(mig.CHECKPOINT_PATH.exists())

            mig.clear_checkpoint()
            self.assertFalse(mig.CHECKPOINT_PATH.exists())
        finally:
            mig.CHECKPOINT_PATH = original_path

    def test_load_nonexistent_checkpoint(self):
        """加载不存在的 checkpoint 应返回 None"""
        import scripts.migrate_wearable_m8_to_m6 as mig
        original_path = mig.CHECKPOINT_PATH
        mig.CHECKPOINT_PATH = Path(self.tmp_dir) / "nonexistent.json"

        try:
            result = mig.load_checkpoint()
            self.assertIsNone(result)
        finally:
            mig.CHECKPOINT_PATH = original_path


# ============================================================================
# 主入口
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
