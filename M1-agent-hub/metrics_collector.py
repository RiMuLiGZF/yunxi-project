"""
云汐内核 V3 - 性能指标收集与监控系统

实时收集 Agent 执行指标，支持监控 Dashboard 数据输出。
指标类型：延迟、成功率、错误率、吞吐量、意图分类准确率
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class MetricSnapshot:
    """指标快照"""

    timestamp: float = field(default_factory=time.time)
    agent_id: str = ""
    metric_name: str = ""
    value: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """指标收集器

    采用滑动窗口 + 聚合统计的设计，支持实时查询和历史回溯。
    """

    def __init__(self, window_size: int = 1000) -> None:
        self._snapshots: list[MetricSnapshot] = []
        self._agent_counters: dict[str, dict[str, int]] = {}
        self._agent_latencies: dict[str, list[float]] = {}
        self.window_size = window_size
        self._logger = logger.bind(service="metrics_collector")

    def record_latency(self, agent_id: str, latency_ms: float) -> None:
        """记录延迟指标"""
        self._snapshots.append(MetricSnapshot(
            agent_id=agent_id,
            metric_name="latency_ms",
            value=latency_ms,
        ))
        self._agent_latencies.setdefault(agent_id, []).append(latency_ms)
        # 滑动窗口
        if len(self._agent_latencies[agent_id]) > self.window_size:
            self._agent_latencies[agent_id].pop(0)
        self._cleanup()

    def record_result(self, agent_id: str, status: str) -> None:
        """记录执行结果"""
        counter = self._agent_counters.setdefault(agent_id, {
            "total": 0,
            "success": 0,
            "failure": 0,
            "timeout": 0,
        })
        counter["total"] += 1
        if status in counter:
            counter[status] += 1

        self._snapshots.append(MetricSnapshot(
            agent_id=agent_id,
            metric_name="execution_result",
            value=1.0 if status == "success" else 0.0,
            labels={"status": status},
        ))
        self._cleanup()

    def record_intent_classification(
        self,
        user_input: str,
        predicted_intent: str,
        confidence: float,
    ) -> None:
        """记录意图分类指标"""
        self._snapshots.append(MetricSnapshot(
            metric_name="intent_classification",
            value=confidence,
            labels={
                "predicted_intent": predicted_intent,
                "input_length_bucket": self._bucket_input_length(len(user_input)),
            },
        ))
        self._cleanup()

    def _bucket_input_length(self, length: int) -> str:
        """输入长度分桶"""
        if length < 10:
            return "short"
        elif length < 50:
            return "medium"
        else:
            return "long"

    def _cleanup(self) -> None:
        """清理过期快照"""
        if len(self._snapshots) > self.window_size * 2:
            self._snapshots = self._snapshots[-self.window_size:]

    # ── 查询接口 ────────────────────────────────────────

    def get_agent_metrics(self, agent_id: str) -> dict[str, Any]:
        """获取 Agent 指标"""
        counter = self._agent_counters.get(agent_id, {})
        total = counter.get("total", 0)
        latencies = self._agent_latencies.get(agent_id, [])

        return {
            "agent_id": agent_id,
            "total_executions": total,
            "success_rate": (
                counter.get("success", 0) / total if total > 0 else 0
            ),
            "failure_rate": (
                counter.get("failure", 0) / total if total > 0 else 0
            ),
            "timeout_rate": (
                counter.get("timeout", 0) / total if total > 0 else 0
            ),
            "avg_latency_ms": (
                sum(latencies) / len(latencies) if latencies else 0
            ),
            "p95_latency_ms": (
                self._percentile(latencies, 0.95) if latencies else 0
            ),
            "p99_latency_ms": (
                self._percentile(latencies, 0.99) if latencies else 0
            ),
        }

    def get_system_metrics(self) -> dict[str, Any]:
        """获取系统级指标"""
        all_agents = set(self._agent_counters.keys()) | set(self._agent_latencies.keys())

        total_exec = sum(
            c.get("total", 0) for c in self._agent_counters.values()
        )
        total_success = sum(
            c.get("success", 0) for c in self._agent_counters.values()
        )

        all_latencies: list[float] = []
        for lat_list in self._agent_latencies.values():
            all_latencies.extend(lat_list)

        return {
            "active_agents": len(all_agents),
            "total_executions": total_exec,
            "overall_success_rate": (
                total_success / total_exec if total_exec > 0 else 0
            ),
            "system_avg_latency_ms": (
                sum(all_latencies) / len(all_latencies) if all_latencies else 0
            ),
            "system_p95_latency_ms": (
                self._percentile(all_latencies, 0.95) if all_latencies else 0
            ),
            "agents": [self.get_agent_metrics(a) for a in sorted(all_agents)],
        }

    def get_intent_classification_stats(self) -> dict[str, Any]:
        """获取意图分类统计"""
        intent_snapshots = [
            s for s in self._snapshots if s.metric_name == "intent_classification"
        ]
        if not intent_snapshots:
            return {"total": 0, "avg_confidence": 0}

        confidences = [s.value for s in intent_snapshots]
        high_conf = [c for c in confidences if c >= 0.7]

        return {
            "total_classifications": len(intent_snapshots),
            "avg_confidence": round(sum(confidences) / len(confidences), 3),
            "high_confidence_rate": round(len(high_conf) / len(confidences), 3),
        }

    @staticmethod
    def _percentile(data: list[float], p: float) -> float:
        """计算百分位数"""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * p
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_data) else f
        return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)

    def export_dashboard_data(self) -> dict[str, Any]:
        """导出 Dashboard 数据"""
        return {
            "timestamp": time.time(),
            "system": self.get_system_metrics(),
            "intent_classification": self.get_intent_classification_stats(),
        }
