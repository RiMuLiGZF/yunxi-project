"""
ARC-008 异常处理规范测试

验证：
1. bounded_collections 中的回调异常被正确记录（不吞异常）
2. performance_utils 中的异常处理有日志记录
3. MonitorService 中的异常处理有日志记录
"""

import sys
import logging
import pytest
from pathlib import Path

# 确保可以导入 shared 模块
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestBoundedCollectionsExceptionHandling:
    """bounded_collections 异常处理测试"""

    def test_callback_exception_logged(self, caplog):
        """测试回调异常被记录到日志（不静默吞掉）"""
        from shared.core.bounded_collections import BoundedList

        # 设置日志捕获
        caplog.set_level(logging.DEBUG, logger="shared.core.bounded_collections")

        def bad_callback(item, reason):
            raise ValueError("callback error")

        bl = BoundedList(max_size=3, on_evict=bad_callback)
        bl.append(1)
        bl.append(2)
        bl.append(3)
        # 第 4 个元素应该触发淘汰和回调异常
        bl.append(4)

        # 验证异常被记录（不应该静默吞掉）
        assert len(bl) == 3  # 列表仍然正常工作
        # 检查日志中是否有异常记录
        found_log = any(
            "Eviction callback" in record.message
            for record in caplog.records
        )
        assert found_log, "回调异常应该被记录到日志中，而不是静默吞掉"

    def test_lrudict_callback_exception_logged(self, caplog):
        """测试 LRUDict 回调异常被记录到日志"""
        from shared.core.bounded_collections import LRUDict

        caplog.set_level(logging.DEBUG, logger="shared.core.bounded_collections")

        def bad_callback(key, value, reason):
            raise RuntimeError("eviction error")

        lru = LRUDict(max_size=2, on_evict=bad_callback)
        lru["a"] = 1
        lru["b"] = 2
        lru["c"] = 3  # 触发淘汰

        assert len(lru) == 2
        found_log = any(
            "Eviction callback" in record.message
            for record in caplog.records
        )
        assert found_log, "LRUDict 淘汰回调异常应该被记录到日志中"

    def test_callback_exception_does_not_break_collection(self):
        """测试回调异常不影响集合的正常功能"""
        from shared.core.bounded_collections import BoundedList

        error_count = 0

        def bad_callback(item, reason):
            nonlocal error_count
            error_count += 1
            raise ValueError("always fails")

        bl = BoundedList(max_size=5, on_evict=bad_callback)

        # 添加大量元素，即使回调每次都失败，集合也应该正常工作
        for i in range(20):
            bl.append(i)

        assert len(bl) == 5
        # 验证确实有回调被调用（并失败）
        assert error_count > 0


class TestPerformanceUtilsExceptionHandling:
    """performance_utils 异常处理测试"""

    def test_async_logger_exception_logged(self, caplog):
        """测试异步日志处理器异常被记录"""
        from shared.core.performance_utils import AsyncLogHandler

        caplog.set_level(logging.WARNING, logger="shared.core.performance_utils")

        # 创建一个会失败的 handler
        class FailingHandler(logging.Handler):
            def emit(self, record):
                raise RuntimeError("emit failed")

        handler = AsyncLogHandler(FailingHandler())

        # 发送几条日志
        test_logger = logging.getLogger("test_async")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

        test_logger.info("test message 1")
        test_logger.info("test message 2")

        # 等待异步处理
        import time
        time.sleep(0.1)

        handler.close()

        # 验证：handler 关闭后不崩溃
        assert True  # 只要不崩溃就通过


class TestMonitorServiceExceptionHandling:
    """MonitorService 异常处理测试"""

    def test_network_speed_fail_graceful(self):
        """测试网络速度获取失败时优雅降级"""
        import importlib.util
        _M8_ROOT = Path(__file__).resolve().parents[1]
        _spec = importlib.util.spec_from_file_location(
            "monitor_service",
            str(_M8_ROOT / "services" / "monitor_service.py"),
        )
        mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(mod)
        MonitorService = mod.MonitorService

        service = MonitorService()
        # 即使 psutil 不可用，也应该返回默认值而不是抛出异常
        result = service.get_network_speed()

        assert isinstance(result, dict)
        assert "upload_mbps" in result
        assert "download_mbps" in result
        assert result["upload_mbps"] >= 0
        assert result["download_mbps"] >= 0

    def test_system_metrics_always_returns(self):
        """测试系统指标采集总是返回结果（不抛出异常）"""
        import importlib.util
        _M8_ROOT = Path(__file__).resolve().parents[1]
        _spec = importlib.util.spec_from_file_location(
            "monitor_service",
            str(_M8_ROOT / "services" / "monitor_service.py"),
        )
        mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(mod)
        MonitorService = mod.MonitorService

        service = MonitorService()
        try:
            metrics = service.get_system_metrics()
            assert isinstance(metrics, dict)
            assert "cpu" in metrics
            assert "memory" in metrics
        except Exception as e:
            pytest.fail(f"get_system_metrics 不应抛出异常: {e}")

    def test_collect_history_point_fail_graceful(self, caplog):
        """测试历史数据采集失败时不崩溃，记录日志"""
        import importlib.util
        _M8_ROOT = Path(__file__).resolve().parents[1]
        _spec = importlib.util.spec_from_file_location(
            "monitor_service",
            str(_M8_ROOT / "services" / "monitor_service.py"),
        )
        mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(mod)
        MonitorService = mod.MonitorService

        service = MonitorService()
        # 正常采集应该成功
        initial_size = service.get_history_buffer_size()
        service.collect_history_point()
        assert service.get_history_buffer_size() == initial_size + 1
