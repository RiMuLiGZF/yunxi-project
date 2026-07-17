"""
云汐监控指标系统（增强版）

支持：
- 计数器（Counter）
- 仪表盘（Gauge）
- 直方图（Histogram）
- 摘要（Summary）- 支持分位数计算
- 指标注册与查询
- Prometheus 格式输出
- 内置标准指标：请求数、请求延迟、错误数、活跃连接数、内存使用
- 按模块/路由/状态码多维度统计
- 百分位计算（TP50/TP90/TP99）
- 高性能：原子操作 + 无锁读路径
"""
import time
import math
import threading
from typing import Dict, Any, Optional, List, Tuple, Callable
from collections import defaultdict
from dataclasses import dataclass, field


# ============================================================================
# 指标基类
# ============================================================================

class MetricBase:
    """指标基类"""
    name: str
    help_text: str
    labels: Dict[str, str]

    def get_type(self) -> str:
        raise NotImplementedError

    def get_value(self) -> Any:
        raise NotImplementedError


# ============================================================================
# Counter - 计数器
# ============================================================================

@dataclass
class Counter(MetricBase):
    """计数器指标（只增不减）"""
    name: str
    help_text: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    _value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get_type(self) -> str:
        return "counter"

    def inc(self, amount: float = 1.0):
        """增加计数"""
        if amount < 0:
            raise ValueError("Counter can only be incremented with non-negative values")
        with self._lock:
            self._value += amount

    def value(self) -> float:
        """获取当前值"""
        with self._lock:
            return self._value

    def get_value(self) -> float:
        return self.value()

    def reset(self):
        """重置"""
        with self._lock:
            self._value = 0.0


# ============================================================================
# Gauge - 仪表盘
# ============================================================================

@dataclass
class Gauge(MetricBase):
    """仪表盘指标（可增可减可设置）"""
    name: str
    help_text: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    _value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get_type(self) -> str:
        return "gauge"

    def inc(self, amount: float = 1.0):
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0):
        with self._lock:
            self._value -= amount

    def set(self, value: float):
        with self._lock:
            self._value = value

    def set_to_current_time(self):
        """设置为当前时间戳"""
        self.set(time.time())

    def track_inprogress(self) -> Callable[[], None]:
        """跟踪进行中的数量，返回一个 decrement 函数

        用法:
            done = gauge.track_inprogress()
            try:
                # do work
            finally:
                done()
        """
        self.inc()
        def _done():
            self.dec()
        return _done

    def value(self) -> float:
        with self._lock:
            return self._value

    def get_value(self) -> float:
        return self.value()


# ============================================================================
# Histogram - 直方图
# ============================================================================

# 默认桶（秒）- 覆盖从毫秒级到秒级的常见延迟范围
DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]

# HTTP 请求延迟常用桶
HTTP_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]

# 数据库查询延迟常用桶
DB_BUCKETS = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]


@dataclass
class Histogram(MetricBase):
    """直方图指标

    观测值分布统计，支持 Prometheus 直方图格式输出。
    可用于延迟、请求大小等分布型指标。
    """
    name: str
    help_text: str = ""
    buckets: List[float] = field(default_factory=lambda: list(DEFAULT_BUCKETS))
    labels: Dict[str, str] = field(default_factory=dict)
    _sum: float = 0.0
    _count: int = 0
    _bucket_counts: Dict[float, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        # 确保桶按升序排列
        self.buckets = sorted(self.buckets)
        for b in self.buckets:
            self._bucket_counts[b] = 0
        # +Inf 桶（等于 count）
        self._bucket_counts[float('inf')] = 0

    def get_type(self) -> str:
        return "histogram"

    def observe(self, value: float):
        """记录一个观测值"""
        with self._lock:
            self._sum += value
            self._count += 1
            # 累积直方图：每个 <= 上限的桶都计数
            for b in self.buckets:
                if value <= b:
                    self._bucket_counts[b] += 1
            self._bucket_counts[float('inf')] += 1

    def observe_duration(self, start_time: float):
        """记录从 start_time 到现在的持续时间（秒）"""
        self.observe(time.time() - start_time)

    def time(self):
        """上下文管理器，用于测量代码块执行时间

        用法:
            with histogram.time():
                do_something()
        """
        return _HistogramTimer(self)

    def value(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "sum": self._sum,
                "count": self._count,
                "buckets": {k: v for k, v in self._bucket_counts.items()},
            }

    def get_value(self) -> Dict[str, Any]:
        return self.value()

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    @property
    def sum(self) -> float:
        with self._lock:
            return self._sum

    @property
    def avg(self) -> float:
        with self._lock:
            if self._count == 0:
                return 0.0
            return self._sum / self._count

    def percentile(self, p: float) -> float:
        """估算百分位值（基于直方图线性插值）

        Args:
            p: 百分位，0-100 之间，如 50 表示 TP50

        Returns:
            估算的百分位值
        """
        if p < 0 or p > 100:
            raise ValueError("Percentile must be between 0 and 100")

        with self._lock:
            if self._count == 0:
                return 0.0

            target_count = (p / 100.0) * self._count
            prev_boundary = 0.0
            prev_count = 0

            for b in self.buckets:
                curr_count = self._bucket_counts[b]
                if curr_count >= target_count:
                    # 在 [prev_boundary, b] 区间内线性插值
                    if curr_count == prev_count:
                        return b
                    fraction = (target_count - prev_count) / (curr_count - prev_count)
                    return prev_boundary + fraction * (b - prev_boundary)
                prev_boundary = b
                prev_count = curr_count

            return self.buckets[-1] if self.buckets else 0.0


class _HistogramTimer:
    """直方图计时器上下文管理器"""

    def __init__(self, histogram: Histogram):
        self._histogram = histogram
        self._start_time: float = 0.0

    def __enter__(self):
        self._start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._histogram.observe_duration(self._start_time)
        return False


# ============================================================================
# Summary - 摘要（分位数）
# ============================================================================

@dataclass
class Summary(MetricBase):
    """摘要指标（支持分位数观测）

    与 Histogram 不同，Summary 在客户端计算分位数，
    适合不需要聚合的单实例指标场景。

    使用滑动窗口存储观测值，计算 TP50/TP90/TP99 等分位数。
    """
    name: str
    help_text: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    # 默认分位数
    quantiles: List[Tuple[float, float]] = field(
        default_factory=lambda: [(0.5, 0.05), (0.9, 0.01), (0.99, 0.001)]
    )
    # 最大观测值数量（滑动窗口大小）
    max_observations: int = 10000
    _observations: List[float] = field(default_factory=list)
    _sum: float = 0.0
    _count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get_type(self) -> str:
        return "summary"

    def observe(self, value: float):
        """记录一个观测值"""
        with self._lock:
            self._sum += value
            self._count += 1
            self._observations.append(value)
            # 滑动窗口：超过最大值时移除最旧的
            if len(self._observations) > self.max_observations:
                self._observations = self._observations[-self.max_observations:]

    def observe_duration(self, start_time: float):
        """记录从 start_time 到现在的持续时间（秒）"""
        self.observe(time.time() - start_time)

    def time(self):
        """上下文管理器，用于测量代码块执行时间"""
        return _SummaryTimer(self)

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    @property
    def sum(self) -> float:
        with self._lock:
            return self._sum

    @property
    def avg(self) -> float:
        with self._lock:
            if self._count == 0:
                return 0.0
            return self._sum / self._count

    def quantile(self, q: float) -> float:
        """计算指定分位数值

        Args:
            q: 分位数，0-1 之间，如 0.95 表示 95 分位

        Returns:
            分位数值
        """
        if q < 0 or q > 1:
            raise ValueError("Quantile must be between 0 and 1")

        with self._lock:
            if not self._observations:
                return 0.0

            sorted_obs = sorted(self._observations)
            idx = int(q * (len(sorted_obs) - 1))
            return sorted_obs[idx]

    def tp50(self) -> float:
        """TP50（中位数）"""
        return self.quantile(0.5)

    def tp90(self) -> float:
        """TP90"""
        return self.quantile(0.9)

    def tp95(self) -> float:
        """TP95"""
        return self.quantile(0.95)

    def tp99(self) -> float:
        """TP99"""
        return self.quantile(0.99)

    def value(self) -> Dict[str, Any]:
        with self._lock:
            sorted_obs = sorted(self._observations) if self._observations else []
            n = len(sorted_obs)
            quantiles_result = {}
            if n > 0:
                for q, _ in self.quantiles:
                    idx = int(q * (n - 1))
                    quantiles_result[str(q)] = sorted_obs[idx]

            return {
                "sum": self._sum,
                "count": self._count,
                "quantiles": quantiles_result,
                "window_size": n,
            }

    def get_value(self) -> Dict[str, Any]:
        return self.value()


class _SummaryTimer:
    """摘要计时器上下文管理器"""

    def __init__(self, summary: Summary):
        self._summary = summary
        self._start_time: float = 0.0

    def __enter__(self):
        self._start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._summary.observe_duration(self._start_time)
        return False


# ============================================================================
# MetricsCollector - 指标收集器
# ============================================================================

class MetricsCollector:
    """指标收集器（增强版）

    支持 Counter、Gauge、Histogram、Summary 四种指标类型，
    内置标准系统指标，支持 Prometheus 格式输出。

    性能优化：
    - 指标创建加锁，读写操作各指标独立加锁
    - 支持按名称+标签维度创建多个指标实例
    """

    def __init__(self, namespace: str = "yunxi"):
        self.namespace = namespace
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._summaries: Dict[str, Summary] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._registrars: List[str] = []  # 已注册的模块名

        # 系统指标（懒加载，首次调用时初始化）
        self._system_metrics_initialized = False

    # -----------------------------------------------------------------------
    # Counter 操作
    # -----------------------------------------------------------------------

    def counter(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[Dict[str, str]] = None,
    ) -> Counter:
        """获取或创建计数器"""
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._counters:
                self._counters[key] = Counter(
                    name=self._full_name(name),
                    help_text=help_text,
                    labels=labels or {},
                )
            return self._counters[key]

    def inc_counter(
        self,
        name: str,
        amount: float = 1.0,
        labels: Optional[Dict[str, str]] = None,
    ):
        """增加计数器（便捷方法）"""
        self.counter(name, labels=labels).inc(amount)

    # -----------------------------------------------------------------------
    # Gauge 操作
    # -----------------------------------------------------------------------

    def gauge(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[Dict[str, str]] = None,
    ) -> Gauge:
        """获取或创建仪表盘"""
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._gauges:
                self._gauges[key] = Gauge(
                    name=self._full_name(name),
                    help_text=help_text,
                    labels=labels or {},
                )
            return self._gauges[key]

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ):
        """设置仪表盘值（便捷方法）"""
        self.gauge(name, labels=labels).set(value)

    def inc_gauge(
        self,
        name: str,
        amount: float = 1.0,
        labels: Optional[Dict[str, str]] = None,
    ):
        """增加仪表盘值（便捷方法）"""
        self.gauge(name, labels=labels).inc(amount)

    def dec_gauge(
        self,
        name: str,
        amount: float = 1.0,
        labels: Optional[Dict[str, str]] = None,
    ):
        """减少仪表盘值（便捷方法）"""
        self.gauge(name, labels=labels).dec(amount)

    # -----------------------------------------------------------------------
    # Histogram 操作
    # -----------------------------------------------------------------------

    def histogram(
        self,
        name: str,
        help_text: str = "",
        buckets: Optional[List[float]] = None,
        labels: Optional[Dict[str, str]] = None,
    ) -> Histogram:
        """获取或创建直方图"""
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = Histogram(
                    name=self._full_name(name),
                    help_text=help_text,
                    buckets=buckets or list(DEFAULT_BUCKETS),
                    labels=labels or {},
                )
            return self._histograms[key]

    def observe_histogram(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ):
        """记录直方图观测值（便捷方法）"""
        self.histogram(name, labels=labels).observe(value)

    # -----------------------------------------------------------------------
    # Summary 操作
    # -----------------------------------------------------------------------

    def summary(
        self,
        name: str,
        help_text: str = "",
        quantiles: Optional[List[Tuple[float, float]]] = None,
        max_observations: int = 10000,
        labels: Optional[Dict[str, str]] = None,
    ) -> Summary:
        """获取或创建摘要指标"""
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._summaries:
                self._summaries[key] = Summary(
                    name=self._full_name(name),
                    help_text=help_text,
                    quantiles=quantiles or [(0.5, 0.05), (0.9, 0.01), (0.99, 0.001)],
                    max_observations=max_observations,
                    labels=labels or {},
                )
            return self._summaries[key]

    def observe_summary(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ):
        """记录摘要观测值（便捷方法）"""
        self.summary(name, labels=labels).observe(value)

    # -----------------------------------------------------------------------
    # 内置标准指标
    # -----------------------------------------------------------------------

    def register_module(self, module_name: str) -> None:
        """为模块注册标准指标集合

        注册后可直接使用以下标准指标：
        - {module}_requests_total: 总请求数 (Counter)
        - {module}_requests_duration_seconds: 请求延迟 (Histogram)
        - {module}_errors_total: 错误数 (Counter)
        - {module}_active_requests: 活跃请求数 (Gauge)
        - {module}_memory_usage_bytes: 内存使用 (Gauge)
        - {module}_request_latency_summary: 请求延迟摘要 (Summary)

        Args:
            module_name: 模块名称
        """
        if module_name in self._registrars:
            return

        # 请求总数
        self.counter(
            f"{module_name}_requests_total",
            help_text=f"Total number of HTTP requests for {module_name}",
        )
        # 请求延迟直方图
        self.histogram(
            f"{module_name}_requests_duration_seconds",
            help_text=f"HTTP request duration in seconds for {module_name}",
            buckets=list(HTTP_BUCKETS),
        )
        # 错误总数
        self.counter(
            f"{module_name}_errors_total",
            help_text=f"Total number of error responses for {module_name}",
        )
        # 活跃请求数
        self.gauge(
            f"{module_name}_active_requests",
            help_text=f"Number of active HTTP requests for {module_name}",
        )
        # 内存使用
        self.gauge(
            f"{module_name}_memory_usage_bytes",
            help_text=f"Memory usage in bytes for {module_name}",
        )
        # 慢请求数
        self.counter(
            f"{module_name}_slow_requests_total",
            help_text=f"Total number of slow requests for {module_name}",
        )
        # 请求延迟摘要（用于分位数）
        self.summary(
            f"{module_name}_request_latency_summary",
            help_text=f"Request latency summary with quantiles for {module_name}",
        )

        self._registrars.append(module_name)

    def record_request(
        self,
        module_name: str,
        method: str,
        path: str,
        status_code: int,
        duration: float,
    ) -> None:
        """记录一次 HTTP 请求的标准指标

        Args:
            module_name: 模块名
            method: HTTP 方法
            path: 请求路径
            status_code: 状态码
            duration: 持续时间（秒）
        """
        labels = {
            "method": method,
            "path": path,
            "status": str(status_code),
        }
        status_class = f"{status_code // 100}xx"
        status_labels = {
            "method": method,
            "status_class": status_class,
        }

        # 总请求数（按状态码维度）
        self.inc_counter(
            f"{module_name}_requests_total",
            labels={"status": status_class},
        )

        # 请求延迟（按方法+路径维度）
        self.observe_histogram(
            f"{module_name}_requests_duration_seconds",
            duration,
            labels={"method": method, "path": path},
        )

        # 延迟摘要
        self.observe_summary(
            f"{module_name}_request_latency_summary",
            duration,
        )

        # 错误计数
        if status_code >= 400:
            self.inc_counter(
                f"{module_name}_errors_total",
                labels={"status": str(status_code), "method": method},
            )

    def get_latency_percentiles(
        self,
        module_name: str,
    ) -> Dict[str, float]:
        """获取请求延迟百分位

        Args:
            module_name: 模块名

        Returns:
            包含 tp50/tp90/tp95/tp99 的字典
        """
        summary = self.summary(f"{module_name}_request_latency_summary")
        return {
            "tp50_ms": round(summary.tp50() * 1000, 2),
            "tp90_ms": round(summary.tp90() * 1000, 2),
            "tp95_ms": round(summary.tp95() * 1000, 2),
            "tp99_ms": round(summary.tp99() * 1000, 2),
        }

    def update_memory_usage(self, module_name: str) -> Optional[float]:
        """更新内存使用指标（读取当前进程内存）

        Returns:
            内存使用字节数，如果获取失败返回 None
        """
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            mem_bytes = process.memory_info().rss
            self.set_gauge(
                f"{module_name}_memory_usage_bytes",
                mem_bytes,
            )
            return mem_bytes
        except Exception:
            return None

    # -----------------------------------------------------------------------
    # 内部工具方法
    # -----------------------------------------------------------------------

    def _full_name(self, name: str) -> str:
        """生成完整指标名（带命名空间前缀）"""
        if name.startswith(self.namespace + "_"):
            return name
        return f"{self.namespace}_{name}"

    def _make_key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        """生成指标键（用于内部存储）"""
        if not labels:
            return name
        sorted_labels = sorted(labels.items())
        label_str = ",".join(f"{k}={v}" for k, v in sorted_labels)
        return f"{name}[{label_str}]"

    # -----------------------------------------------------------------------
    # 输出 - JSON 格式
    # -----------------------------------------------------------------------

    def get_all(self) -> Dict[str, Any]:
        """获取所有指标数据（JSON 格式）"""
        with self._lock:
            uptime = time.time() - self._start_time

            counters = {}
            for key, c in self._counters.items():
                counters[key] = {
                    "type": "counter",
                    "value": c.value(),
                    "help": c.help_text,
                    "labels": c.labels,
                }

            gauges = {}
            for key, g in self._gauges.items():
                gauges[key] = {
                    "type": "gauge",
                    "value": g.value(),
                    "help": g.help_text,
                    "labels": g.labels,
                }

            histograms = {}
            for key, h in self._histograms.items():
                histograms[key] = {
                    "type": "histogram",
                    "value": h.value(),
                    "help": h.help_text,
                    "labels": h.labels,
                }

            summaries = {}
            for key, s in self._summaries.items():
                summaries[key] = {
                    "type": "summary",
                    "value": s.value(),
                    "help": s.help_text,
                    "labels": s.labels,
                }

            return {
                "namespace": self.namespace,
                "uptime_seconds": round(uptime, 2),
                "counters": counters,
                "gauges": gauges,
                "histograms": histograms,
                "summaries": summaries,
                "total_metrics": (
                    len(self._counters)
                    + len(self._gauges)
                    + len(self._histograms)
                    + len(self._summaries)
                ),
                "registered_modules": self._registrars,
            }

    # -----------------------------------------------------------------------
    # 输出 - Prometheus 文本格式
    # -----------------------------------------------------------------------

    def to_prometheus(self) -> str:
        """输出 Prometheus 格式指标

        Returns:
            Prometheus 文本格式的指标数据
        """
        lines: List[str] = []

        # 收集所有唯一的指标名和类型（用于 HELP/TYPE 去重）
        seen_metrics: Dict[str, str] = {}

        # Counters
        for key, c in self._counters.items():
            if c.name not in seen_metrics:
                seen_metrics[c.name] = "counter"
                if c.help_text:
                    lines.append(f"# HELP {c.name} {c.help_text}")
                lines.append(f"# TYPE {c.name} counter")
            label_str = self._format_labels(c.labels)
            lines.append(f"{c.name}{label_str} {c.value()}")

        # Gauges
        for key, g in self._gauges.items():
            if g.name not in seen_metrics:
                seen_metrics[g.name] = "gauge"
                if g.help_text:
                    lines.append(f"# HELP {g.name} {g.help_text}")
                lines.append(f"# TYPE {g.name} gauge")
            label_str = self._format_labels(g.labels)
            lines.append(f"{g.name}{label_str} {g.value()}")

        # Histograms
        for key, h in self._histograms.items():
            if h.name not in seen_metrics:
                seen_metrics[h.name] = "histogram"
                if h.help_text:
                    lines.append(f"# HELP {h.name} {h.help_text}")
                lines.append(f"# TYPE {h.name} histogram")

            val = h.value()
            base_labels = h.labels

            for b, count in val["buckets"].items():
                le_label = "+Inf" if math.isinf(b) else str(b)
                bucket_labels = {**base_labels, "le": le_label}
                label_str = self._format_labels(bucket_labels)
                lines.append(f"{h.name}_bucket{label_str} {count}")

            label_str = self._format_labels(base_labels)
            lines.append(f"{h.name}_sum{label_str} {val['sum']}")
            lines.append(f"{h.name}_count{label_str} {val['count']}")

        # Summaries
        for key, s in self._summaries.items():
            if s.name not in seen_metrics:
                seen_metrics[s.name] = "summary"
                if s.help_text:
                    lines.append(f"# HELP {s.name} {s.help_text}")
                lines.append(f"# TYPE {s.name} summary")

            val = s.value()
            base_labels = s.labels

            for q_str, q_val in val["quantiles"].items():
                q_labels = {**base_labels, "quantile": q_str}
                label_str = self._format_labels(q_labels)
                lines.append(f"{s.name}{label_str} {q_val}")

            label_str = self._format_labels(base_labels)
            lines.append(f"{s.name}_sum{label_str} {val['sum']}")
            lines.append(f"{s.name}_count{label_str} {val['count']}")

        return "\n".join(lines) + "\n"

    def _format_labels(self, labels: Dict[str, str]) -> str:
        """格式化 Prometheus 标签字符串"""
        if not labels:
            return ""
        parts = [f'{k}="{_escape_label_value(v)}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(parts) + "}"


def _escape_label_value(value: str) -> str:
    """转义 Prometheus 标签值中的特殊字符"""
    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


# ============================================================================
# 全局指标收集器（单例）
# ============================================================================

_metrics: Optional[MetricsCollector] = None
_metrics_lock = threading.Lock()


def get_metrics(namespace: str = "yunxi") -> MetricsCollector:
    """获取全局指标收集器（单例模式，线程安全）

    Args:
        namespace: 指标命名空间，默认 "yunxi"

    Returns:
        MetricsCollector 实例
    """
    global _metrics
    if _metrics is None:
        with _metrics_lock:
            if _metrics is None:
                _metrics = MetricsCollector(namespace=namespace)
    return _metrics


def reset_metrics() -> None:
    """重置全局指标收集器（主要用于测试）"""
    global _metrics
    with _metrics_lock:
        _metrics = None
