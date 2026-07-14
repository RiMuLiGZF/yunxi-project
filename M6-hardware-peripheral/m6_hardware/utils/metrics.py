"""
M6 硬件外设 - 轻量级指标收集器

P2-4 改造：提供线程安全的 Metrics 单例，用于请求计数、延迟直方图、
设备状态仪表盘等性能监控埋点。
"""

import time
import threading
from collections import defaultdict
from typing import Dict, List, Optional


class Metrics:
    """轻量级指标收集器（线程安全）

    指标类型:
    - counters:  只增不减的计数器（请求总数、采集次数等）
    - gauges:    可升可降的仪表值（当前在线设备数、队列深度等）
    - histograms: 直方图分布（响应延迟、采集耗时等）

    使用方式:
        metrics = Metrics()
        metrics.inc("requests_total")
        metrics.observe("response_latency_ms", 42.5)
        snapshot = metrics.snapshot()
    """

    _instance: Optional["Metrics"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "Metrics":
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._counters = defaultdict(int)
                instance._gauges: Dict[str, float] = {}
                instance._histograms: Dict[str, List[float]] = defaultdict(list)
                cls._instance = instance
        return cls._instance

    # ------------------------------------------------------------------
    # 指标写入
    # ------------------------------------------------------------------
    def inc(self, name: str, value: int = 1, labels: dict = None) -> None:
        """递增计数器

        Args:
            name: 指标名
            value: 递增步长（默认 +1）
            labels: 可选标签字典（拼接为 key 后缀）
        """
        key = self._make_key(name, labels)
        self._counters[key] += value

    def set_gauge(self, name: str, value: float) -> None:
        """设置仪表值

        Args:
            name: 指标名
            value: 当前值（覆盖）
        """
        self._gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        """记录直方图观测值

        Args:
            name: 指标名
            value: 观测值
        """
        self._histograms[name].append(value)

    # ------------------------------------------------------------------
    # 查询 / 快照
    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        """获取指标快照

        Returns:
            包含 counters / gauges / histograms 的字典
        """
        hist_summary: dict = {}
        for k, v in self._histograms.items():
            hist_summary[k] = {
                "count": len(v),
                "avg": sum(v) / len(v) if v else 0,
                "min": min(v) if v else 0,
                "max": max(v) if v else 0,
            }
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": hist_summary,
        }

    # ------------------------------------------------------------------
    # 重置
    # ------------------------------------------------------------------
    def reset(self) -> None:
        """清空所有指标"""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _make_key(name: str, labels: Optional[dict]) -> str:
        if not labels:
            return name
        parts = [f"{k}={v}" for k, v in sorted(labels.items())]
        return f"{name}{{{','.join(parts)}}}"
