"""
云汐监控指标系统

支持：
- 计数器（Counter）
- 仪表盘（Gauge）
- 直方图（Histogram）
- 指标注册与查询
- Prometheus格式输出
"""
import time
import threading
from typing import Dict, Any, Optional, List
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Counter:
    """计数器指标"""
    name: str
    help_text: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    _value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def inc(self, amount: float = 1.0):
        """增加计数"""
        with self._lock:
            self._value += amount
    
    def value(self) -> float:
        """获取当前值"""
        with self._lock:
            return self._value
    
    def reset(self):
        """重置"""
        with self._lock:
            self._value = 0.0


@dataclass
class Gauge:
    """仪表盘指标（可增可减）"""
    name: str
    help_text: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    _value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def inc(self, amount: float = 1.0):
        with self._lock:
            self._value += amount
    
    def dec(self, amount: float = 1.0):
        with self._lock:
            self._value -= amount
    
    def set(self, value: float):
        with self._lock:
            self._value = value
    
    def value(self) -> float:
        with self._lock:
            return self._value


@dataclass
class Histogram:
    """直方图指标"""
    name: str
    help_text: str = ""
    buckets: List[float] = field(default_factory=lambda: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])
    labels: Dict[str, str] = field(default_factory=dict)
    _sum: float = 0.0
    _count: int = 0
    _bucket_counts: Dict[float, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def __post_init__(self):
        for b in self.buckets:
            self._bucket_counts[b] = 0
    
    def observe(self, value: float):
        """记录一个观测值"""
        with self._lock:
            self._sum += value
            self._count += 1
            for b in self.buckets:
                if value <= b:
                    self._bucket_counts[b] += 1
    
    def value(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "sum": self._sum,
                "count": self._count,
                "buckets": dict(self._bucket_counts),
            }


class MetricsCollector:
    """指标收集器"""
    
    def __init__(self):
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()
    
    # ---- Counter ----
    
    def counter(self, name: str, help_text: str = "", labels: Optional[Dict[str, str]] = None) -> Counter:
        """获取或创建计数器"""
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._counters:
                self._counters[key] = Counter(
                    name=name,
                    help_text=help_text,
                    labels=labels or {},
                )
            return self._counters[key]
    
    def inc(self, name: str, amount: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """增加计数器（便捷方法）"""
        self.counter(name, labels=labels).inc(amount)
    
    # ---- Gauge ----
    
    def gauge(self, name: str, help_text: str = "", labels: Optional[Dict[str, str]] = None) -> Gauge:
        """获取或创建仪表盘"""
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._gauges:
                self._gauges[key] = Gauge(
                    name=name,
                    help_text=help_text,
                    labels=labels or {},
                )
            return self._gauges[key]
    
    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """设置仪表盘值（便捷方法）"""
        self.gauge(name, labels=labels).set(value)
    
    # ---- Histogram ----
    
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
                default_buckets = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
                self._histograms[key] = Histogram(
                    name=name,
                    help_text=help_text,
                    buckets=buckets or default_buckets,
                    labels=labels or {},
                )
            return self._histograms[key]
    
    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """记录观测值（便捷方法）"""
        self.histogram(name, labels=labels).observe(value)
    
    def _make_key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        """生成指标键"""
        if not labels:
            return name
        sorted_labels = sorted(labels.items())
        label_str = ",".join(f"{k}={v}" for k, v in sorted_labels)
        return f"{name}[{label_str}]"
    
    # ---- 输出 ----
    
    def get_all(self) -> Dict[str, Any]:
        """获取所有指标数据"""
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
            
            return {
                "uptime_seconds": round(uptime, 2),
                "counters": counters,
                "gauges": gauges,
                "histograms": histograms,
                "total_metrics": len(self._counters) + len(self._gauges) + len(self._histograms),
            }
    
    def to_prometheus(self) -> str:
        """
        输出Prometheus格式指标
        
        Returns:
            Prometheus文本格式的指标数据
        """
        with self._lock:
            lines = []
            
            # Counters
            for key, c in self._counters.items():
                if c.help_text:
                    lines.append(f"# HELP {c.name} {c.help_text}")
                lines.append(f"# TYPE {c.name} counter")
                label_str = self._format_labels(c.labels)
                lines.append(f"{c.name}{label_str} {c.value()}")
            
            # Gauges
            for key, g in self._gauges.items():
                if g.help_text:
                    lines.append(f"# HELP {g.name} {g.help_text}")
                lines.append(f"# TYPE {g.name} gauge")
                label_str = self._format_labels(g.labels)
                lines.append(f"{g.name}{label_str} {g.value()}")
            
            # Histograms
            for key, h in self._histograms.items():
                if h.help_text:
                    lines.append(f"# HELP {h.name} {h.help_text}")
                lines.append(f"# TYPE {h.name} histogram")
                
                val = h.value()
                label_str = self._format_labels(h.labels)
                
                for b, count in val["buckets"].items():
                    bucket_label = self._format_labels({**h.labels, "le": str(b)})
                    lines.append(f"{h.name}_bucket{bucket_label} {count}")
                
                lines.append(f"{h.name}_sum{label_str} {val['sum']}")
                lines.append(f"{h.name}_count{label_str} {val['count']}")
            
            return "\n".join(lines) + "\n"
    
    def _format_labels(self, labels: Dict[str, str]) -> str:
        """格式化标签字符串"""
        if not labels:
            return ""
        parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(parts) + "}"


# 全局指标收集器
_metrics: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """获取全局指标收集器"""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics
