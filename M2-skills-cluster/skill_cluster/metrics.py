from __future__ import annotations

"""Metrics Collector - 结构化指标收集.

Prometheus-style 指标收集：计数器（Counter）、直方图（Histogram），
支持按 skill_id / action / agent_id / status 多维度聚合。

【第四轮优化】增加高基数维度防护：限制 label 组合上限，
防止 agent_id 等高基数维度导致内存无限增长。
"""

import time
import warnings
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Any

# 默认最大 label 唯一组合数上限（防内存泄漏）
_DEFAULT_MAX_CARDINALITY = 10000


@dataclass
class MetricSample:
    """单个指标样本."""

    timestamp: float
    value: float
    labels: dict[str, str] = field(default_factory=dict)


class Counter:
    """计数器（只增不减）.

    【第四轮优化】增加 max_cardinality 上限，超限时静默丢弃新 label 组合并告警。
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        max_cardinality: int = _DEFAULT_MAX_CARDINALITY,
    ) -> None:
        self.name = name
        self.description = description
        self._max_cardinality = max_cardinality
        self._values: dict[tuple[tuple[str, str], ...], int] = defaultdict(int)

    def inc(self, labels: dict[str, str] | None = None, amount: int = 1) -> None:
        """增加计数."""
        key = self._labels_to_key(labels)
        if key not in self._values:
            if len(self._values) >= self._max_cardinality:
                warnings.warn(
                    f"Counter '{self.name}' reached max cardinality "
                    f"({self._max_cardinality}), dropping new label combination",
                    stacklevel=3,
                )
                return
        self._values[key] += amount

    def get(self, labels: dict[str, str] | None = None) -> int:
        """获取当前值."""
        key = self._labels_to_key(labels)
        return self._values[key]

    def get_all(self) -> dict[tuple[tuple[str, str], ...], int]:
        """获取所有标签组合的值."""
        return dict(self._values)

    @staticmethod
    def _labels_to_key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        if labels is None:
            return ()
        return tuple(sorted(labels.items()))


class Histogram:
    """直方图（记录数值分布）.

    【第四轮优化】增加 max_cardinality 上限，防内存泄漏。
    """

    DEFAULT_BUCKETS = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]

    def __init__(
        self,
        name: str,
        description: str = "",
        buckets: list[float] | None = None,
        max_cardinality: int = _DEFAULT_MAX_CARDINALITY,
    ) -> None:
        self.name = name
        self.description = description
        self._max_cardinality = max_cardinality
        self.buckets = sorted(buckets or self.DEFAULT_BUCKETS)
        self._sums: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._counts: dict[tuple[tuple[str, str], ...], int] = defaultdict(int)
        self._bucket_counts: dict[
            tuple[tuple[str, str], ...], dict[float, int]
        ] = defaultdict(lambda: {b: 0 for b in self.buckets})

    def observe(
        self, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """记录观测值."""
        key = self._labels_to_key(labels)
        if key not in self._counts:
            if len(self._counts) >= self._max_cardinality:
                warnings.warn(
                    f"Histogram '{self.name}' reached max cardinality "
                    f"({self._max_cardinality}), dropping new label combination",
                    stacklevel=3,
                )
                return
        self._sums[key] += value
        self._counts[key] += 1
        for bucket in self.buckets:
            if value <= bucket:
                self._bucket_counts[key][bucket] += 1

    def get(self, labels: dict[str, str] | None = None) -> dict[str, Any]:
        """获取统计信息."""
        key = self._labels_to_key(labels)
        count = self._counts[key]
        total = self._sums[key]
        return {
            "count": count,
            "sum": total,
            "avg": total / count if count > 0 else 0.0,
            "buckets": {
                f"le_{b}": self._bucket_counts[key][b]
                for b in self.buckets
            },
        }

    @staticmethod
    def _labels_to_key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        if labels is None:
            return ()
        return tuple(sorted(labels.items()))


class MetricsCollector:
    """指标收集器.

    统一管理 Skill 集群系统的所有指标。
    """

    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}

    def counter(self, name: str, description: str = "") -> Counter:
        """获取或创建计数器."""
        if name not in self._counters:
            self._counters[name] = Counter(name, description)
        return self._counters[name]

    def histogram(
        self, name: str, description: str = "", buckets: list[float] | None = None
    ) -> Histogram:
        """获取或创建直方图."""
        if name not in self._histograms:
            self._histograms[name] = Histogram(name, description, buckets)
        return self._histograms[name]

    def record(
        self,
        skill_id: str,
        action: str,
        agent_id: str,
        status: str,
        latency_ms: float,
    ) -> None:
        """记录一次 Skill 调用指标."""
        labels = {
            "skill_id": skill_id,
            "action": action,
            "agent_id": agent_id,
            "status": status,
        }

        # 调用总数
        self.counter("skill_invocations_total", "Total skill invocations").inc(labels)

        # 按状态分类的调用数
        status_labels = {
            "skill_id": skill_id,
            "action": action,
            "status": status,
        }
        self.counter("skill_invocations_by_status", "Invocations by status").inc(
            status_labels
        )

        # 延迟直方图
        latency_labels = {
            "skill_id": skill_id,
            "action": action,
        }
        self.histogram(
            "skill_invocation_latency_ms",
            "Invocation latency in milliseconds",
        ).observe(latency_ms, latency_labels)

    def get_all_metrics(self) -> dict[str, Any]:
        """获取所有指标的当前值."""
        return {
            "counters": {
                name: {
                    "description": c.description,
                    "values": {
                        str(k): v for k, v in c.get_all().items()
                    },
                }
                for name, c in self._counters.items()
            },
            "histograms": {
                name: {
                    "description": h.description,
                    "values": {
                        str(labels_key): h.get(dict(labels_key))
                        for labels_key in list(h._counts.keys())
                    },
                }
                for name, h in self._histograms.items()
            },
        }

    def export_prometheus_format(self) -> str:
        """导出为 Prometheus 文本格式."""
        lines: list[str] = []

        for name, counter in self._counters.items():
            lines.append(f"# HELP {name} {counter.description}")
            lines.append(f"# TYPE {name} counter")
            for labels, value in counter.get_all().items():
                label_str = ",".join(f'{k}="{v}"' for k, v in labels)
                lines.append(f'{name}{{{label_str}}} {value}')
            lines.append("")

        for name, hist in self._histograms.items():
            lines.append(f"# HELP {name} {hist.description}")
            lines.append(f"# TYPE {name} histogram")
            for labels in list(hist._counts.keys()):
                label_dict = dict(labels)
                stats = hist.get(label_dict)
                label_str = ",".join(f'{k}="{v}"' for k, v in dict(labels).items())
                lines.append(f'{name}_count{{{label_str}}} {stats["count"]}')
                lines.append(f'{name}_sum{{{label_str}}} {stats["sum"]}')
            lines.append("")

        return "\n".join(lines)
