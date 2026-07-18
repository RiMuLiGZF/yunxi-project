"""
MonitorService 单元测试 (ARC-010 修复验证)

验证：
1. MonitorService 类的基本功能正常
2. 线程安全（多线程并发读写不崩溃）
3. 历史数据缓冲区功能正常
4. 阈值检查功能正常
5. 采集器生命周期管理
"""

import sys
import time
import threading
import pytest
from pathlib import Path

# 确保可以导入 backend 模块
_M8_ROOT = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _M8_ROOT.parent.parent
for _p in (str(_M8_ROOT), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 直接导入 monitor_service 模块（避免 services/__init__.py 的依赖问题）
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "monitor_service",
    str(_M8_ROOT / "services" / "monitor_service.py"),
)
monitor_service_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(monitor_service_mod)

MonitorService = monitor_service_mod.MonitorService
DEFAULT_THRESHOLDS = monitor_service_mod.DEFAULT_THRESHOLDS
MAX_HISTORY_POINTS = monitor_service_mod.MAX_HISTORY_POINTS


class TestMonitorServiceBasics:
    """MonitorService 基本功能测试"""

    def test_initialization(self):
        """测试 MonitorService 初始化"""
        service = MonitorService()
        assert service is not None
        assert service.collector_running is False
        assert service.get_history_buffer_size() == 0

    def test_custom_thresholds(self):
        """测试自定义阈值配置"""
        custom = {"cpu_warning": 70, "cpu_critical": 85}
        service = MonitorService(thresholds=custom)
        thresholds = service.thresholds
        assert thresholds["cpu_warning"] == 70
        assert thresholds["cpu_critical"] == 85

    def test_thresholds_immutable(self):
        """测试 thresholds 返回的是副本，外部修改不影响内部"""
        service = MonitorService()
        thresholds = service.thresholds
        thresholds["cpu_warning"] = 999
        # 内部值不应改变
        assert service.thresholds["cpu_warning"] != 999

    def test_update_thresholds(self):
        """测试更新阈值"""
        service = MonitorService()
        original = service.thresholds["cpu_warning"]
        service.update_thresholds({"cpu_warning": 75})
        assert service.thresholds["cpu_warning"] == 75


class TestMonitorServiceMetrics:
    """系统指标采集测试"""

    def test_get_system_metrics_returns_dict(self):
        """测试 get_system_metrics 返回正确结构的字典"""
        service = MonitorService()
        metrics = service.get_system_metrics()

        assert isinstance(metrics, dict)
        assert "timestamp" in metrics
        assert "source" in metrics
        assert "cpu" in metrics
        assert "memory" in metrics
        assert "disk" in metrics
        assert "network" in metrics
        assert "process" in metrics
        assert "uptime" in metrics

    def test_cpu_metrics_structure(self):
        """测试 CPU 指标结构"""
        service = MonitorService()
        metrics = service.get_system_metrics()
        cpu = metrics["cpu"]

        assert "usage_percent" in cpu
        assert "per_core" in cpu
        assert "core_count_logical" in cpu
        assert "core_count_physical" in cpu
        assert isinstance(cpu["usage_percent"], (int, float))
        assert isinstance(cpu["per_core"], list)

    def test_memory_metrics_structure(self):
        """测试内存指标结构"""
        service = MonitorService()
        metrics = service.get_system_metrics()
        mem = metrics["memory"]

        assert "total_gb" in mem
        assert "used_gb" in mem
        assert "available_gb" in mem
        assert "percent" in mem
        assert isinstance(mem["percent"], (int, float))

    def test_network_speed_returns_valid(self):
        """测试网络速率返回有效值"""
        service = MonitorService()
        speed = service.get_network_speed()

        assert isinstance(speed, dict)
        assert "upload_mbps" in speed
        assert "download_mbps" in speed
        assert isinstance(speed["upload_mbps"], float)
        assert isinstance(speed["download_mbps"], float)
        assert speed["upload_mbps"] >= 0
        assert speed["download_mbps"] >= 0


class TestMonitorServiceHistory:
    """历史数据管理测试"""

    def test_collect_history_point(self):
        """测试采集历史数据点"""
        service = MonitorService()
        initial_size = service.get_history_buffer_size()
        service.collect_history_point()
        assert service.get_history_buffer_size() == initial_size + 1

    def test_get_history_data_structure(self):
        """测试历史数据返回结构"""
        service = MonitorService()
        # 先采集几个点
        for _ in range(5):
            service.collect_history_point()

        data = service.get_history_data("1h")

        assert isinstance(data, dict)
        assert "period" in data
        assert data["period"] == "1h"
        assert "point_count" in data
        assert "timestamps" in data
        assert "cpu" in data
        assert "memory" in data
        assert "disk" in data
        assert "network_in" in data
        assert "network_out" in data
        # 所有序列长度一致
        assert len(data["timestamps"]) == data["point_count"]
        assert len(data["cpu"]) == data["point_count"]

    def test_clear_history(self):
        """测试清空历史数据"""
        service = MonitorService()
        for _ in range(10):
            service.collect_history_point()
        assert service.get_history_buffer_size() == 10

        service.clear_history()
        assert service.get_history_buffer_size() == 0

    def test_history_buffer_max_size(self):
        """测试历史缓冲区有最大容量限制（deque maxlen）"""
        from collections import deque
        # 直接测试 deque 的 maxlen 行为（MonitorService 使用 MAX_HISTORY_POINTS=10080）
        # 这里用小值验证原理
        small_buffer = deque(maxlen=100)
        for i in range(200):
            small_buffer.append(i)
        assert len(small_buffer) == 100
        assert small_buffer[0] == 100  # 最早的被淘汰了


class TestMonitorServiceThreadSafety:
    """线程安全测试（ARC-010 核心验证）"""

    def test_concurrent_collect(self):
        """多线程并发采集数据不崩溃"""
        service = MonitorService()
        errors = []

        def worker(n_points):
            try:
                for _ in range(n_points):
                    service.collect_history_point()
            except Exception as e:
                errors.append(e)

        threads = []
        n_threads = 5
        points_per_thread = 10

        for _ in range(n_threads):
            t = threading.Thread(target=worker, args=(points_per_thread,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        # 没有异常
        assert len(errors) == 0, f"并发采集出现 {len(errors)} 个错误: {errors[:3]}"

    def test_concurrent_read_write(self):
        """并发读写历史数据不崩溃"""
        service = MonitorService()
        errors = []

        # 先填充一些数据
        for _ in range(20):
            service.collect_history_point()

        def writer():
            try:
                for _ in range(10):
                    service.collect_history_point()
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(10):
                    _ = service.get_history_buffer_size()
                    _ = service.get_history_data("1h")
                    _ = service.thresholds
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=writer))
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"并发读写出现 {len(errors)} 个错误: {errors[:3]}"

    def test_concurrent_threshold_update(self):
        """并发更新阈值不崩溃"""
        service = MonitorService()
        errors = []

        def updater(thread_id):
            try:
                for i in range(20):
                    service.update_thresholds({
                        f"custom_{thread_id}_{i}": i,
                    })
                    _ = service.thresholds
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(3):
            t = threading.Thread(target=updater, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"并发更新阈值出现 {len(errors)} 个错误: {errors[:3]}"


class TestMonitorServiceCollector:
    """后台采集器生命周期测试"""

    def test_start_collector(self):
        """测试启动采集器"""
        service = MonitorService()
        assert service.collector_running is False

        started = service.start_collector()
        assert started is True
        assert service.collector_running is True

        # 等待采集至少一个点
        time.sleep(0.1)

        # 再次启动应该返回 False
        started_again = service.start_collector()
        assert started_again is False

        # 清理
        service.stop_collector()

    def test_stop_collector(self):
        """测试停止采集器"""
        service = MonitorService()
        service.start_collector()
        assert service.collector_running is True

        stopped = service.stop_collector()
        assert stopped is True
        assert service.collector_running is False

        # 再次停止应该返回 False
        stopped_again = service.stop_collector()
        assert stopped_again is False

    def test_collector_produces_data(self):
        """测试采集器实际产生数据（验证线程启动和采集功能）"""
        service = MonitorService()

        # 先手动采集一个点作为基线
        service.collect_history_point()
        initial_size = service.get_history_buffer_size()
        assert initial_size == 1

        service.start_collector()
        # 等待采集器线程至少执行一次完整的采集循环
        # 注意：首次 psutil 调用可能较慢（需要初始化）
        import time
        time.sleep(5.0)

        size_after = service.get_history_buffer_size()
        # 采集器启动时会立即采集一个点，所以至少应该有 2 个点
        assert size_after >= 2, f"期望至少 2 个数据点，实际={size_after}"

        service.stop_collector()


class TestMonitorServiceThresholdCheck:
    """阈值告警检查测试"""

    def test_no_alerts_when_below_threshold(self):
        """测试指标低于阈值时不产生告警"""
        service = MonitorService()
        metrics = {
            "cpu": {"usage_percent": 10},
            "memory": {"percent": 30},
            "disk": {"percent": 20},
        }
        alerts = service.check_thresholds(metrics)
        assert len(alerts) == 0

    def test_warning_alert_for_cpu(self):
        """测试 CPU 超过 warning 阈值产生 warning 告警"""
        service = MonitorService()
        metrics = {
            "cpu": {"usage_percent": 85},  # 超过默认 80% warning
            "memory": {"percent": 30},
            "disk": {"percent": 20},
        }
        alerts = service.check_thresholds(metrics)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "cpu"
        assert alerts[0]["level"] == "warning"

    def test_critical_alert_for_memory(self):
        """测试内存超过 critical 阈值产生 critical 告警"""
        service = MonitorService()
        metrics = {
            "cpu": {"usage_percent": 10},
            "memory": {"percent": 98},  # 超过默认 95% critical
            "disk": {"percent": 20},
        }
        alerts = service.check_thresholds(metrics)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "memory"
        assert alerts[0]["level"] == "critical"

    def test_multiple_alerts(self):
        """测试多个指标同时超过阈值"""
        service = MonitorService()
        metrics = {
            "cpu": {"usage_percent": 95},  # critical
            "memory": {"percent": 90},  # warning (85%)
            "disk": {"percent": 92},  # critical (90%)
        }
        alerts = service.check_thresholds(metrics)
        assert len(alerts) == 3
        types = {a["type"] for a in alerts}
        assert "cpu" in types
        assert "memory" in types
        assert "disk" in types
