"""
M10 系统卫士 - Prometheus Exporter 测试

测试覆盖：
1. 指标注册与管理
2. 指标更新与导出
3. MetricRegistry 功能
4. PrometheusExporter 生命周期
5. 配置开关
6. M8 指标上报
7. HTTP 端点（集成测试）
"""

from __future__ import annotations

import os
import sys
import time
import threading
import pytest
from unittest.mock import patch, MagicMock


# ============================================================
# 测试配置：确保沙盒模式启用
# ============================================================

def _enable_sandbox_mode():
    """启用沙盒模式，避免真实系统调用导致测试缓慢."""
    from m10_system_guard.config import get_config
    config = get_config()
    config.sandbox.enabled = True

    # 重置可能已初始化的单例
    import m10_system_guard.system_monitor as sm_mod
    import m10_system_guard.process_manager as pm_mod

    sm_mod._system_monitor_instance = None
    pm_mod._process_manager_instance = None


_enable_sandbox_mode()


# ============================================================
# 测试：MetricRegistry 指标注册中心
# ============================================================

class TestMetricRegistry:
    """测试指标注册中心."""

    def test_register_gauge(self):
        """测试注册 Gauge 指标."""
        from m10_system_guard.prometheus_exporter import MetricRegistry

        registry = MetricRegistry()
        gauge = registry.register_gauge(
            "test_cpu_percent",
            "Test CPU usage",
            category="system"
        )

        info = registry.get_metric_info("test_cpu_percent")
        assert info is not None
        assert info.name == "test_cpu_percent"
        assert info.metric_type == "gauge"
        assert info.category == "system"
        assert info.help_text == "Test CPU usage"

    def test_register_gauge_with_labels(self):
        """测试带标签的 Gauge 指标注册."""
        from m10_system_guard.prometheus_exporter import MetricRegistry

        registry = MetricRegistry()
        registry.register_gauge(
            "test_gpu_util",
            "GPU utilization",
            labels=["gpu_id", "hostname"],
            category="gpu"
        )

        info = registry.get_metric_info("test_gpu_util")
        assert info is not None
        assert info.labels == ["gpu_id", "hostname"]

    def test_register_counter(self):
        """测试注册 Counter 指标."""
        from m10_system_guard.prometheus_exporter import MetricRegistry

        registry = MetricRegistry()
        registry.register_counter(
            "test_requests_total",
            "Total requests",
            category="system"
        )

        info = registry.get_metric_info("test_requests_total")
        assert info is not None
        assert info.metric_type == "counter"

    def test_set_gauge_value(self):
        """测试设置 Gauge 指标值."""
        from m10_system_guard.prometheus_exporter import MetricRegistry

        registry = MetricRegistry()
        registry.register_gauge("test_metric", "Test metric")

        registry.set_gauge("test_metric", 42.5)

        # 通过 dict 方式验证
        metrics_dict = registry.to_dict()
        assert "test_metric" in metrics_dict
        # 降级模式下检查值
        if not registry.prometheus_available:
            assert registry._fallback_values["test_metric"]["values"][()] == 42.5

    def test_set_gauge_with_labels(self):
        """测试设置带标签的 Gauge 指标值."""
        from m10_system_guard.prometheus_exporter import MetricRegistry

        registry = MetricRegistry()
        registry.register_gauge(
            "test_gpu_temp",
            "GPU temperature",
            labels=["gpu_id"]
        )

        registry.set_gauge("test_gpu_temp", 75.0, {"gpu_id": "0"})
        registry.set_gauge("test_gpu_temp", 80.0, {"gpu_id": "1"})

        if not registry.prometheus_available:
            fb = registry._fallback_values["test_gpu_temp"]
            values = fb["values"]
            assert len(values) == 2

    def test_inc_counter(self):
        """测试增加 Counter 指标值."""
        from m10_system_guard.prometheus_exporter import MetricRegistry

        registry = MetricRegistry()
        registry.register_counter("test_counter", "Test counter")

        registry.inc_counter("test_counter", 5)
        registry.inc_counter("test_counter", 3)

        if not registry.prometheus_available:
            assert registry._fallback_values["test_counter"]["values"][()] == 8

    def test_list_metrics_by_category(self):
        """测试按类别列出指标."""
        from m10_system_guard.prometheus_exporter import MetricRegistry

        registry = MetricRegistry()
        registry.register_gauge("sys_cpu", "CPU", category="system")
        registry.register_gauge("gpu_mem", "GPU mem", category="gpu")
        registry.register_gauge("tide_task", "Tide tasks", category="tide")

        all_metrics = registry.list_metrics()
        assert len(all_metrics) == 3

        gpu_metrics = registry.list_metrics("gpu")
        assert len(gpu_metrics) == 1
        assert gpu_metrics[0].name == "gpu_mem"

    def test_generate_text(self):
        """测试生成 Prometheus 文本格式."""
        from m10_system_guard.prometheus_exporter import MetricRegistry

        registry = MetricRegistry()
        registry.register_gauge("test_value", "Test value")
        registry.set_gauge("test_value", 123.4)

        text = registry.generate_text()
        assert "test_value" in text
        assert "123.4" in text
        assert "Test value" in text

    def test_to_dict(self):
        """测试导出为字典格式."""
        from m10_system_guard.prometheus_exporter import MetricRegistry

        registry = MetricRegistry()
        registry.register_gauge("my_gauge", "My gauge", category="custom")
        registry.set_gauge("my_gauge", 99.9)

        result = registry.to_dict()
        assert "my_gauge" in result
        assert result["my_gauge"]["type"] == "gauge"
        assert result["my_gauge"]["help"] == "My gauge"
        assert result["my_gauge"]["category"] == "custom"

    def test_nonexistent_metric(self):
        """测试查询不存在的指标."""
        from m10_system_guard.prometheus_exporter import MetricRegistry

        registry = MetricRegistry()
        assert registry.get_metric("nonexistent") is None
        assert registry.get_metric_info("nonexistent") is None


# ============================================================
# 测试：PrometheusExporter 主类
# ============================================================

class TestPrometheusExporter:
    """测试 Prometheus Exporter 主类."""

    def setup_method(self):
        """每个测试用例前重置单例状态."""
        import m10_system_guard.prometheus_exporter as pe_mod
        pe_mod._exporter_instance = None
        _enable_sandbox_mode()

    def test_exporter_initialization(self):
        """测试 Exporter 初始化."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        exporter = PrometheusExporter()
        # 默认启用
        assert isinstance(exporter.enabled, bool)
        assert exporter.hostname is not None
        assert exporter.collect_interval > 0

    def test_exporter_disabled_via_env(self):
        """测试通过环境变量禁用 Exporter."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        with patch.dict(os.environ, {"M10_PROMETHEUS_ENABLED": "false"}):
            exporter = PrometheusExporter()
            assert exporter.enabled is False

    def test_exporter_collect_interval_env(self):
        """测试通过环境变量配置采集间隔."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        with patch.dict(os.environ, {"M10_PROMETHEUS_COLLECT_INTERVAL": "30"}):
            exporter = PrometheusExporter()
            assert exporter.collect_interval == 30

    def test_collect_metrics(self):
        """测试执行一次指标采集."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        exporter = PrometheusExporter()
        result = exporter.collect_metrics()

        assert "timestamp" in result
        assert "hostname" in result
        assert "system" in result
        assert "gpu" in result
        assert "guard" in result
        assert "process" in result

    def test_system_metrics_collected(self):
        """测试系统指标采集."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        exporter = PrometheusExporter()
        result = exporter.collect_metrics()

        system_data = result.get("system", {})
        # 沙盒模式下应该有数据
        assert "cpu_percent" in system_data
        assert "memory_percent" in system_data
        assert "process_count" in system_data

    def test_gpu_metrics_collected(self):
        """测试 GPU 指标采集."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        exporter = PrometheusExporter()
        result = exporter.collect_metrics()

        gpu_data = result.get("gpu", {})
        assert "gpu_count" in gpu_data
        assert "devices" in gpu_data

    def test_guard_metrics_collected(self):
        """测试防护引擎指标采集."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        exporter = PrometheusExporter()
        result = exporter.collect_metrics()

        guard_data = result.get("guard", {})
        assert "total_alerts" in guard_data
        assert "overall_level" in guard_data

    def test_generate_metrics_text(self):
        """测试生成 Prometheus 格式文本."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        exporter = PrometheusExporter()
        content_type, body = exporter.generate_metrics_text()

        assert content_type is not None
        assert len(body) > 0
        # 应该包含系统指标
        assert "system_cpu_percent" in body

    def test_generate_metrics_json(self):
        """测试生成 JSON 格式指标."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        exporter = PrometheusExporter()
        result = exporter.generate_metrics_json()

        assert "metrics" in result
        assert "exporter_enabled" in result
        assert "hostname" in result
        assert "metric_count" in result
        assert result["metric_count"] > 0

    def test_health_check(self):
        """测试健康检查."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        exporter = PrometheusExporter()
        health = exporter.health_check()

        assert "status" in health
        assert "enabled" in health
        assert "running" in health
        assert "metric_count" in health
        assert health["enabled"] == exporter.enabled

    def test_start_stop(self):
        """测试启动和停止采集."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        exporter = PrometheusExporter()
        if not exporter.enabled:
            pytest.skip("Exporter is disabled")

        # 启动
        started = exporter.start()
        assert started is True
        assert exporter.running is True

        # 等待一次采集完成
        time.sleep(0.5)
        assert exporter._last_collect_time > 0

        # 重复启动应该返回 False
        assert exporter.start() is False

        # 停止
        stopped = exporter.stop()
        assert stopped is True
        assert exporter.running is False

        # 重复停止应该返回 False
        assert exporter.stop() is False

    def test_custom_metric_registration(self):
        """测试动态注册自定义指标."""
        from m10_system_guard.prometheus_exporter import PrometheusExporter

        exporter = PrometheusExporter()

        # 注册自定义 Gauge
        exporter.register_custom_gauge(
            "custom_app_metric",
            "Custom application metric",
            labels=["instance"],
            category="custom"
        )

        info = exporter.registry.get_metric_info("custom_app_metric")
        assert info is not None
        assert info.category == "custom"
        assert "instance" in info.labels

        # 设置值
        exporter.registry.set_gauge("custom_app_metric", 100.0, {"instance": "test"})


# ============================================================
# 测试：M8 指标上报
# ============================================================

class TestM8MetricsReporter:
    """测试 M8 指标上报器."""

    def setup_method(self):
        """每个测试用例前重置单例状态."""
        import m10_system_guard.prometheus_exporter as pe_mod
        pe_mod._exporter_instance = None
        _enable_sandbox_mode()

    def test_reporter_disabled_by_default(self):
        """测试默认禁用 M8 上报."""
        from m10_system_guard.prometheus_exporter import (
            PrometheusExporter, M8MetricsReporter
        )

        exporter = PrometheusExporter()
        reporter = M8MetricsReporter(exporter)
        assert reporter.enabled is False

    def test_reporter_enabled_via_env(self):
        """测试通过环境变量启用 M8 上报."""
        from m10_system_guard.prometheus_exporter import (
            PrometheusExporter, M8MetricsReporter
        )

        exporter = PrometheusExporter()
        with patch.dict(os.environ, {"M10_M8_REPORT_ENABLED": "true"}):
            reporter = M8MetricsReporter(exporter)
            # 需要重新初始化才能读取环境变量
            reporter._enabled = reporter._check_enabled()
            assert reporter.enabled is True

    def test_report_interval_env(self):
        """测试通过环境变量配置上报间隔."""
        from m10_system_guard.prometheus_exporter import (
            PrometheusExporter, M8MetricsReporter
        )

        exporter = PrometheusExporter()
        with patch.dict(os.environ, {"M10_M8_REPORT_INTERVAL": "120"}):
            reporter = M8MetricsReporter(exporter)
            reporter._report_interval = reporter._get_report_interval()
            assert reporter.report_interval == 120

    def test_build_report_payload(self):
        """测试构建上报数据."""
        from m10_system_guard.prometheus_exporter import (
            PrometheusExporter, M8MetricsReporter
        )

        exporter = PrometheusExporter()
        reporter = M8MetricsReporter(exporter)
        payload = reporter.build_report_payload()

        assert "module" in payload
        assert payload["module"] == "m10"
        assert "module_name" in payload
        assert "hostname" in payload
        assert "timestamp" in payload
        assert "metrics" in payload

        metrics = payload["metrics"]
        assert "cpu" in metrics
        assert "memory" in metrics
        assert "gpu" in metrics
        assert "guard" in metrics
        assert "process" in metrics

    def test_get_stats(self):
        """测试获取上报统计."""
        from m10_system_guard.prometheus_exporter import (
            PrometheusExporter, M8MetricsReporter
        )

        exporter = PrometheusExporter()
        reporter = M8MetricsReporter(exporter)
        stats = reporter.get_stats()

        assert "enabled" in stats
        assert "running" in stats
        assert "report_interval" in stats
        assert "report_count" in stats
        assert "success_count" in stats
        assert "fail_count" in stats

    def test_report_to_m8_connection_error(self):
        """测试上报到 M8 连接失败的情况（返回 False，不崩溃）."""
        from m10_system_guard.prometheus_exporter import (
            PrometheusExporter, M8MetricsReporter
        )

        exporter = PrometheusExporter()
        reporter = M8MetricsReporter(exporter)
        reporter._enabled = True
        reporter._m8_base_url = "http://localhost:19999"  # 不存在的端口
        reporter._max_retries = 1  # 减少重试次数，加速测试

        # 应该返回 False（失败），但不会抛出异常
        result = reporter.report_to_m8()
        assert result is False
        assert reporter._fail_count > 0
        assert reporter._consecutive_failures > 0

    def test_start_stop_reporter(self):
        """测试启动和停止上报器."""
        from m10_system_guard.prometheus_exporter import (
            PrometheusExporter, M8MetricsReporter
        )

        exporter = PrometheusExporter()
        reporter = M8MetricsReporter(exporter)
        reporter._enabled = True

        # 启动
        started = reporter.start()
        assert started is True
        assert reporter.running is True

        # 重复启动
        assert reporter.start() is False

        # 停止
        stopped = reporter.stop()
        assert stopped is True
        assert reporter.running is False

        # 重复停止
        assert reporter.stop() is False

    def test_reporter_disabled_start_returns_false(self):
        """测试禁用状态下启动返回 False."""
        from m10_system_guard.prometheus_exporter import (
            PrometheusExporter, M8MetricsReporter
        )

        exporter = PrometheusExporter()
        reporter = M8MetricsReporter(exporter)
        reporter._enabled = False

        assert reporter.start() is False


# ============================================================
# 测试：向后兼容的全局函数
# ============================================================

class TestBackwardCompatibility:
    """测试向后兼容的全局函数接口."""

    def test_is_prometheus_available(self):
        """测试 is_prometheus_available 函数."""
        from m10_system_guard.prometheus_exporter import is_prometheus_available

        result = is_prometheus_available()
        assert isinstance(result, bool)

    def test_generate_prometheus_metrics(self):
        """测试 generate_prometheus_metrics 函数."""
        from m10_system_guard.prometheus_exporter import generate_prometheus_metrics

        content_type, body = generate_prometheus_metrics()
        assert content_type is not None
        assert isinstance(body, str)
        assert len(body) > 0

    def test_generate_metrics_json(self):
        """测试 generate_metrics_json 函数."""
        from m10_system_guard.prometheus_exporter import generate_metrics_json

        result = generate_metrics_json()
        assert "metrics" in result
        assert "timestamp" in result

    def test_start_stop_functions(self):
        """测试 start/stop 便捷函数."""
        from m10_system_guard.prometheus_exporter import (
            start_prometheus_exporter,
            stop_prometheus_exporter,
            get_prometheus_exporter,
        )

        exporter = get_prometheus_exporter()
        if not exporter.enabled:
            pytest.skip("Exporter is disabled")

        # 确保停止状态
        if exporter.running:
            stop_prometheus_exporter()

        result = start_prometheus_exporter()
        assert result is True
        assert exporter.running is True

        result = stop_prometheus_exporter()
        assert result is True
        assert exporter.running is False

    def test_exporter_health_check(self):
        """测试 exporter_health_check 便捷函数."""
        from m10_system_guard.prometheus_exporter import exporter_health_check

        health = exporter_health_check()
        assert "status" in health
        assert "metric_count" in health
        assert health["metric_count"] > 0
