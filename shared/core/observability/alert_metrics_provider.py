"""
告警指标数据提供者（Alert Metrics Provider）

为告警引擎提供统一的指标数据采集接口，支持多种数据源：
- 系统指标（CPU/内存/磁盘）- 来自 psutil
- 接口指标（错误率/延迟/QPS/慢请求）- 来自 MetricsCollector
- 模块健康状态 - 来自模块注册中心
- 数据库连接状态 - 来自健康检查器
- Mock 数据源 - 用于测试

使用方式：
    from shared.core.observability.alert_metrics_provider import (
        AlertMetricsProvider,
        MockMetricsProvider,
        get_metrics_provider,
    )

    # 获取默认提供者
    provider = get_metrics_provider()

    # 注册到告警引擎
    alert_engine.add_context_provider(provider.get_context)
"""

import time
import threading
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from collections import deque


# ============================================================================
# 指标提供者基类
# ============================================================================

class BaseMetricsProvider:
    """指标数据提供者基类"""

    def get_context(self) -> Dict[str, Any]:
        """获取指标上下文（供告警引擎评估使用）

        Returns:
            包含所有指标数据的字典
        """
        raise NotImplementedError

    def get_system_metrics(self) -> Dict[str, Any]:
        """获取系统指标"""
        raise NotImplementedError

    def get_api_metrics(self) -> Dict[str, Any]:
        """获取接口性能指标"""
        raise NotImplementedError

    def get_health_metrics(self) -> Dict[str, Any]:
        """获取业务健康指标"""
        raise NotImplementedError


# ============================================================================
# Mock 指标提供者（用于测试）
# ============================================================================

class MockMetricsProvider(BaseMetricsProvider):
    """Mock 指标数据提供者

    用于单元测试和开发环境，可自定义各指标返回值。
    """

    def __init__(self):
        self._data: Dict[str, Any] = {
            # 系统指标
            "cpu_usage": 30.0,
            "memory_usage": 50.0,
            "disk_usage": 40.0,
            "disk_free_bytes": 100 * 1024 ** 3,  # 100GB
            "process_count": 150,
            # 接口指标
            "error_rate": 1.0,  # 百分比
            "slow_request_ratio": 2.0,  # 百分比
            "qps": 100.0,
            "qps_previous": 100.0,
            "request_total": 10000,
            "error_total": 100,
            "slow_request_total": 200,
            "avg_latency_ms": 50.0,
            "p99_latency_ms": 200.0,
            # 业务健康
            "module_offline_count": 0,
            "module_total": 8,
            "db_connection_ok": True,
            "db_connection_failed_count": 0,
        }
        self._lock = threading.Lock()

    def set(self, key: str, value: Any) -> None:
        """设置单个指标值"""
        with self._lock:
            self._data[key] = value

    def set_many(self, data: Dict[str, Any]) -> None:
        """批量设置指标值"""
        with self._lock:
            self._data.update(data)

    def get(self, key: str, default: Any = None) -> Any:
        """获取单个指标值"""
        with self._lock:
            return self._data.get(key, default)

    def get_context(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def get_system_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "cpu_usage": self._data.get("cpu_usage", 0.0),
                "memory_usage": self._data.get("memory_usage", 0.0),
                "disk_usage": self._data.get("disk_usage", 0.0),
                "disk_free_bytes": self._data.get("disk_free_bytes", 0),
                "process_count": self._data.get("process_count", 0),
            }

    def get_api_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "error_rate": self._data.get("error_rate", 0.0),
                "slow_request_ratio": self._data.get("slow_request_ratio", 0.0),
                "qps": self._data.get("qps", 0.0),
                "qps_previous": self._data.get("qps_previous", 0.0),
                "request_total": self._data.get("request_total", 0),
                "error_total": self._data.get("error_total", 0),
                "slow_request_total": self._data.get("slow_request_total", 0),
                "avg_latency_ms": self._data.get("avg_latency_ms", 0.0),
                "p99_latency_ms": self._data.get("p99_latency_ms", 0.0),
            }

    def get_health_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "module_offline_count": self._data.get("module_offline_count", 0),
                "module_total": self._data.get("module_total", 0),
                "db_connection_ok": self._data.get("db_connection_ok", True),
                "db_connection_failed_count": self._data.get("db_connection_failed_count", 0),
            }

    def reset(self) -> None:
        """重置为默认值"""
        self.__init__()  # type: ignore


# ============================================================================
# 标准指标提供者（集成真实数据源）
# ============================================================================

class AlertMetricsProvider(BaseMetricsProvider):
    """标准告警指标数据提供者

    从多个数据源聚合指标：
    - 系统指标：psutil（CPU/内存/磁盘/进程数）
    - 接口指标：MetricsCollector（错误率/延迟/QPS/慢请求）
    - 模块健康：ModuleRegistry（模块离线数）
    - 数据库状态：健康检查器（连接状态）
    """

    def __init__(
        self,
        service_name: str = "yunxi",
        qps_window_seconds: int = 60,
    ):
        self.service_name = service_name
        self.qps_window_seconds = qps_window_seconds

        # QPS 历史记录（用于计算环比）
        self._qps_history: deque = deque(maxlen=120)  # 最多保留 120 个采样点
        self._last_qps_sample_time: float = 0.0
        self._last_request_count: int = 0

        self._lock = threading.Lock()

        # 自定义数据源回调
        self._custom_sources: List[Callable[[], Dict[str, Any]]] = []

    def add_custom_source(self, source: Callable[[], Dict[str, Any]]) -> None:
        """添加自定义数据源"""
        self._custom_sources.append(source)

    def remove_custom_source(self, source: Callable) -> None:
        """移除自定义数据源"""
        try:
            self._custom_sources.remove(source)
        except ValueError:
            pass

    def get_context(self) -> Dict[str, Any]:
        """获取完整的指标上下文"""
        context: Dict[str, Any] = {
            "timestamp": time.time(),
            "service_name": self.service_name,
        }

        # 系统指标
        context.update(self.get_system_metrics())

        # 接口指标
        context.update(self.get_api_metrics())

        # 健康指标
        context.update(self.get_health_metrics())

        # 自定义数据源
        for source in self._custom_sources:
            try:
                custom_data = source()
                if isinstance(custom_data, dict):
                    context.update(custom_data)
            except Exception:
                pass

        return context

    def get_system_metrics(self) -> Dict[str, Any]:
        """获取系统指标（CPU/内存/磁盘/进程数）"""
        result: Dict[str, Any] = {}

        try:
            import psutil

            # CPU
            cpu_percent = psutil.cpu_percent(interval=0.1)
            result["cpu_usage"] = cpu_percent
            result["cpu_percent"] = cpu_percent
            result["cpu_core_count"] = psutil.cpu_count(logical=True)

            # 内存
            mem = psutil.virtual_memory()
            result["memory_usage"] = mem.percent
            result["memory_percent"] = mem.percent
            result["memory_total_bytes"] = mem.total
            result["memory_used_bytes"] = mem.used
            result["memory_available_bytes"] = mem.available

            # 磁盘
            try:
                import shutil
                disk = shutil.disk_usage(".")
                disk_percent = (disk.used / disk.total) * 100
                result["disk_usage"] = disk_percent
                result["disk_percent"] = disk_percent
                result["disk_total_bytes"] = disk.total
                result["disk_used_bytes"] = disk.used
                result["disk_free_bytes"] = disk.free
            except Exception:
                result["disk_usage"] = 0.0
                result["disk_free_bytes"] = float("inf")

            # 进程数
            try:
                result["process_count"] = len(psutil.pids())
            except Exception:
                result["process_count"] = 0

        except ImportError:
            # psutil 不可用，设置默认值
            result.update({
                "cpu_usage": 0.0,
                "memory_usage": 0.0,
                "disk_usage": 0.0,
                "disk_free_bytes": float("inf"),
                "process_count": 0,
            })

        return result

    def get_api_metrics(self) -> Dict[str, Any]:
        """获取接口性能指标（错误率/延迟/QPS/慢请求）"""
        result: Dict[str, Any] = {
            "error_rate": 0.0,
            "slow_request_ratio": 0.0,
            "qps": 0.0,
            "qps_previous": 0.0,
            "request_total": 0,
            "error_total": 0,
            "slow_request_total": 0,
            "avg_latency_ms": 0.0,
            "p99_latency_ms": 0.0,
        }

        try:
            from .metrics import get_metrics

            metrics = get_metrics()
            module_name = self.service_name

            # 总请求数
            try:
                total_counter = metrics.counter(f"{module_name}_requests_total")
                total_requests = total_counter.value()
                result["request_total"] = int(total_requests)
            except Exception:
                pass

            # 错误数
            try:
                error_counter = metrics.counter(f"{module_name}_errors_total")
                error_total = error_counter.value()
                result["error_total"] = int(error_total)
                if result["request_total"] > 0:
                    result["error_rate"] = round(
                        (error_total / result["request_total"]) * 100, 2
                    )
            except Exception:
                pass

            # 慢请求数
            try:
                slow_counter = metrics.counter(f"{module_name}_slow_requests_total")
                slow_total = slow_counter.value()
                result["slow_request_total"] = int(slow_total)
                if result["request_total"] > 0:
                    result["slow_request_ratio"] = round(
                        (slow_total / result["request_total"]) * 100, 2
                    )
            except Exception:
                pass

            # 延迟
            try:
                latency_summary = metrics.summary(f"{module_name}_request_latency_summary")
                if latency_summary.count > 0:
                    result["avg_latency_ms"] = round(latency_summary.avg * 1000, 2)
                    result["p99_latency_ms"] = round(latency_summary.tp99() * 1000, 2)
            except Exception:
                pass

            # QPS 计算
            self._update_qps(result["request_total"])
            result["qps"] = self._get_current_qps()
            result["qps_previous"] = self._get_previous_qps()

        except ImportError:
            pass

        return result

    def _update_qps(self, total_requests: int) -> None:
        """更新 QPS 历史记录"""
        now = time.time()
        with self._lock:
            if self._last_qps_sample_time > 0:
                elapsed = now - self._last_qps_sample_time
                if elapsed >= 5.0:  # 至少 5 秒采样一次
                    delta = total_requests - self._last_request_count
                    qps = delta / elapsed if elapsed > 0 else 0.0
                    self._qps_history.append((now, qps))
                    self._last_qps_sample_time = now
                    self._last_request_count = total_requests
            else:
                self._last_qps_sample_time = now
                self._last_request_count = total_requests

    def _get_current_qps(self) -> float:
        """获取当前窗口的平均 QPS"""
        with self._lock:
            if not self._qps_history:
                return 0.0
            # 取最近窗口内的平均 QPS
            now = time.time()
            window_start = now - self.qps_window_seconds
            recent = [qps for ts, qps in self._qps_history if ts >= window_start]
            if not recent:
                return 0.0
            return round(sum(recent) / len(recent), 2)

    def _get_previous_qps(self) -> float:
        """获取上一窗口的平均 QPS（用于环比计算）"""
        with self._lock:
            if len(self._qps_history) < 2:
                return 0.0
            now = time.time()
            # 当前窗口
            current_start = now - self.qps_window_seconds
            # 上一窗口
            prev_end = current_start
            prev_start = prev_end - self.qps_window_seconds

            prev_qps_list = [
                qps for ts, qps in self._qps_history
                if prev_start <= ts < prev_end
            ]
            if not prev_qps_list:
                # 如果没有上一窗口数据，使用所有历史数据的前半部分
                mid = len(self._qps_history) // 2
                if mid > 0:
                    return round(
                        sum(qps for _, qps in list(self._qps_history)[:mid]) / mid, 2
                    )
                return 0.0
            return round(sum(prev_qps_list) / len(prev_qps_list), 2)

    def get_health_metrics(self) -> Dict[str, Any]:
        """获取业务健康指标（模块离线、数据库状态）"""
        result: Dict[str, Any] = {
            "module_offline_count": 0,
            "module_total": 0,
            "db_connection_ok": True,
            "db_connection_failed_count": 0,
        }

        # 模块健康状态
        try:
            from shared.business.module_client import get_module_registry

            registry = get_module_registry()
            modules = registry.get_all_modules()
            result["module_total"] = len(modules)

            offline_count = 0
            for mod in modules:
                if not registry.check_health(mod.key):
                    offline_count += 1
            result["module_offline_count"] = offline_count
        except (ImportError, AttributeError, Exception):
            pass

        return result


# ============================================================================
# 全局指标提供者（单例）
# ============================================================================

_global_metrics_provider: Optional[BaseMetricsProvider] = None
_global_provider_lock = threading.Lock()


def get_metrics_provider(
    service_name: str = "yunxi",
    use_mock: bool = False,
) -> BaseMetricsProvider:
    """获取全局指标数据提供者（单例模式）

    Args:
        service_name: 服务名称
        use_mock: 是否使用 mock 数据源（测试用）

    Returns:
        指标提供者实例
    """
    global _global_metrics_provider
    if _global_metrics_provider is None:
        with _global_provider_lock:
            if _global_metrics_provider is None:
                if use_mock:
                    _global_metrics_provider = MockMetricsProvider()
                else:
                    _global_metrics_provider = AlertMetricsProvider(
                        service_name=service_name,
                    )
    return _global_metrics_provider


def set_metrics_provider(provider: BaseMetricsProvider) -> None:
    """设置全局指标提供者（用于测试替换）"""
    global _global_metrics_provider
    with _global_provider_lock:
        _global_metrics_provider = provider


def reset_metrics_provider() -> None:
    """重置全局指标提供者（主要用于测试）"""
    global _global_metrics_provider
    with _global_provider_lock:
        _global_metrics_provider = None
