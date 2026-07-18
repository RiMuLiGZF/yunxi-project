"""
性能报告模块 (Performance Report)

功能:
- 实时性能仪表盘数据
- 每日性能报告
- 性能趋势分析
- 告警规则 (响应超时/错误率过高)

使用方式::

    from shared.perf.performance_report import PerformanceReportGenerator

    reporter = PerformanceReportGenerator()

    # 仪表盘数据
    dashboard = reporter.get_dashboard()

    # 每日报告
    report = reporter.get_daily_report()

    # 告警
    alerts = reporter.get_alerts()
"""

from __future__ import annotations

import time
import threading
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
import json
import os


# ============================================================
# 告警级别
# ============================================================

class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    RESPONSE_TIMEOUT = "response_timeout"
    ERROR_RATE_HIGH = "error_rate_high"
    SLOW_QUERY = "slow_query"
    HIGH_CONCURRENCY = "high_concurrency"
    HIGH_MEMORY = "high_memory"
    HIGH_CPU = "high_cpu"
    CACHE_LOW_HIT_RATE = "cache_low_hit_rate"


# ============================================================
# 告警规则
# ============================================================

@dataclass
class AlertRule:
    """告警规则"""
    name: str
    type: AlertType
    level: AlertLevel
    threshold: float
    duration: int = 1  # 持续多少个周期才触发
    enabled: bool = True
    description: str = ""


@dataclass
class Alert:
    """告警实例"""
    id: str
    rule_name: str
    type: AlertType
    level: AlertLevel
    message: str
    value: float
    threshold: float
    timestamp: float
    acknowledged: bool = False
    acknowledged_at: Optional[float] = None
    acknowledged_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "rule_name": self.rule_name,
            "type": self.type.value,
            "level": self.level.value,
            "message": self.message,
            "value": round(self.value, 3),
            "threshold": self.threshold,
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
        }


# ============================================================
# 默认告警规则
# ============================================================

DEFAULT_ALERT_RULES: List[AlertRule] = [
    AlertRule(
        name="P95 响应超时",
        type=AlertType.RESPONSE_TIMEOUT,
        level=AlertLevel.WARNING,
        threshold=1000.0,  # ms
        duration=3,
        description="P95 响应时间超过 1s",
    ),
    AlertRule(
        name="错误率过高",
        type=AlertType.ERROR_RATE_HIGH,
        level=AlertLevel.WARNING,
        threshold=0.05,  # 5%
        duration=3,
        description="错误率超过 5%",
    ),
    AlertRule(
        name="错误率严重",
        type=AlertType.ERROR_RATE_HIGH,
        level=AlertLevel.CRITICAL,
        threshold=0.20,  # 20%
        duration=1,
        description="错误率超过 20%",
    ),
    AlertRule(
        name="慢查询频繁",
        type=AlertType.SLOW_QUERY,
        level=AlertLevel.WARNING,
        threshold=10.0,  # 每分钟慢查询数
        duration=2,
        description="每分钟慢查询超过 10 次",
    ),
    AlertRule(
        name="高并发",
        type=AlertType.HIGH_CONCURRENCY,
        level=AlertLevel.WARNING,
        threshold=100.0,
        duration=2,
        description="并发请求数超过 100",
    ),
    AlertRule(
        name="内存过高",
        type=AlertType.HIGH_MEMORY,
        level=AlertLevel.WARNING,
        threshold=80.0,  # %
        duration=3,
        description="内存使用率超过 80%",
    ),
    AlertRule(
        name="CPU 过高",
        type=AlertType.HIGH_CPU,
        level=AlertLevel.WARNING,
        threshold=80.0,  # %
        duration=3,
        description="CPU 使用率超过 80%",
    ),
    AlertRule(
        name="缓存命中率低",
        type=AlertType.CACHE_LOW_HIT_RATE,
        level=AlertLevel.INFO,
        threshold=0.50,  # 50%
        duration=5,
        description="缓存命中率低于 50%",
    ),
]


# ============================================================
# 性能报告生成器
# ============================================================

class PerformanceReportGenerator:
    """性能报告生成器

    功能:
    - 实时性能仪表盘
    - 每日性能报告
    - 性能趋势分析
    - 告警管理
    """

    def __init__(
        self,
        metrics_collector=None,
        cache_manager=None,
        profiler=None,
        alert_rules: Optional[List[AlertRule]] = None,
        max_alerts: int = 1000,
        report_dir: Optional[str] = None,
    ):
        self.metrics = metrics_collector
        self.cache_mgr = cache_manager
        self.profiler = profiler

        # 告警规则
        self.alert_rules = alert_rules or list(DEFAULT_ALERT_RULES)

        # 告警历史
        self._alerts: deque = deque(maxlen=max_alerts)
        self._alerts_lock = threading.Lock()

        # 告警抑制 (防止重复告警)
        self._alert_suppression: Dict[str, float] = {}
        self._suppression_ttl = 300  # 5 分钟内同一告警不重复

        # 历史数据 (用于趋势分析)
        self._history: deque = deque(maxlen=1440)  # 24 小时 * 60 分钟
        self._history_lock = threading.Lock()

        # 报告存储目录
        self.report_dir = report_dir

        # 上次检查时间
        self._last_alert_check = 0.0
        self._alert_check_interval = 60.0  # 每分钟检查一次

    # ---------- 仪表盘 ----------

    def get_dashboard(self) -> Dict[str, Any]:
        """获取实时性能仪表盘数据

        返回完整的性能概览，包含:
        - 系统概览 (QPS/延迟/错误率/并发)
        - 资源使用 (CPU/内存)
        - 缓存状态
        - 慢请求/慢查询
        - 活跃告警
        """
        # 基础指标
        summary = self.metrics.get_summary() if self.metrics else {}
        system = self.metrics.get_system_metrics() if self.metrics else {}

        # 缓存统计
        cache_stats = {}
        if self.cache_mgr:
            cache_stats = self.cache_mgr.get_stats()

        # 慢请求
        slow_requests = []
        if self.profiler:
            slow_requests = self.profiler.get_slow_requests(limit=10)

        # 慢查询
        slow_queries = []
        if self.metrics:
            slow_queries = self.metrics.get_slow_queries(limit=10)

        # 活跃告警
        active_alerts = self.get_active_alerts()

        # 性能评分 (0-100)
        perf_score = self._calculate_perf_score(summary, system, cache_stats)

        return {
            "timestamp": time.time(),
            "performance_score": perf_score,
            "overview": {
                "qps": summary.get("qps", {}),
                "avg_response_time_ms": summary.get("avg_response_time_ms", 0),
                "p50_ms": summary.get("p50_ms", 0),
                "p95_ms": summary.get("p95_ms", 0),
                "p99_ms": summary.get("p99_ms", 0),
                "error_rate": summary.get("error_rate", 0),
                "total_requests": summary.get("total_requests", 0),
                "concurrent_requests": summary.get("concurrent_requests", 0),
                "uptime_seconds": summary.get("uptime_seconds", 0),
            },
            "system": {
                "cpu_percent": system.get("system_cpu", {}).get("percent", 0),
                "memory_percent": system.get("system_memory", {}).get("percent", 0),
                "memory_mb": system.get("memory", {}).get("rss_mb", 0),
                "num_threads": system.get("cpu", {}).get("num_threads", 0),
            },
            "cache": {
                "overall_hit_rate": cache_stats.get("overall_hit_rate", 0),
                "l1_hit_rate": cache_stats.get("l1", {}).get("hit_rate", 0),
                "l2_hit_rate": cache_stats.get("l2", {}).get("hit_rate", 0),
                "total_requests": cache_stats.get("total_requests", 0),
                "size": cache_stats.get("l1", {}).get("size", 0),
            },
            "slow_requests": slow_requests,
            "slow_queries": slow_queries,
            "active_alerts": len(active_alerts),
            "alerts": active_alerts[:5],
        }

    def _calculate_perf_score(
        self,
        summary: Dict[str, Any],
        system: Dict[str, Any],
        cache_stats: Dict[str, Any],
    ) -> int:
        """计算性能评分 (0-100)"""
        score = 100

        # 响应时间扣分
        p95 = summary.get("p95_ms", 0)
        if p95 > 1000:
            score -= 20
        elif p95 > 500:
            score -= 10
        elif p95 > 200:
            score -= 5

        # 错误率扣分
        error_rate = summary.get("error_rate", 0)
        if error_rate > 0.1:
            score -= 30
        elif error_rate > 0.05:
            score -= 15
        elif error_rate > 0.01:
            score -= 5

        # 资源使用扣分
        cpu = system.get("system_cpu", {}).get("percent", 0)
        mem = system.get("system_memory", {}).get("percent", 0)
        if cpu > 90 or mem > 90:
            score -= 15
        elif cpu > 80 or mem > 80:
            score -= 8

        # 缓存命中率加分/扣分
        hit_rate = cache_stats.get("overall_hit_rate", 0)
        if hit_rate > 0 and hit_rate < 0.3:
            score -= 5
        elif hit_rate > 0.8:
            score += 5

        return max(0, min(100, score))

    # ---------- 每日报告 ----------

    def get_daily_report(self, date: Optional[str] = None) -> Dict[str, Any]:
        """获取每日性能报告

        Args:
            date: 日期字符串 (YYYY-MM-DD)，None 表示今天

        Returns:
            每日性能报告
        """
        if date is None:
            date = time.strftime("%Y-%m-%d")

        # 从历史数据中筛选当天的
        day_start = time.mktime(time.strptime(date, "%Y-%m-%d"))
        day_end = day_start + 86400

        day_data = []
        with self._history_lock:
            for item in self._history:
                if day_start <= item["timestamp"] < day_end:
                    day_data.append(item)

        # 计算日汇总
        if day_data:
            total_requests = sum(d.get("total_requests", 0) for d in day_data)
            avg_p95 = sum(d.get("p95_ms", 0) for d in day_data) / len(day_data)
            max_p95 = max(d.get("p95_ms", 0) for d in day_data)
            avg_error_rate = sum(d.get("error_rate", 0) for d in day_data) / len(day_data)
            max_concurrent = max(d.get("concurrent_requests", 0) for d in day_data)
            peak_qps = max(d.get("qps_1m", 0) for d in day_data)
        else:
            total_requests = 0
            avg_p95 = 0
            max_p95 = 0
            avg_error_rate = 0
            max_concurrent = 0
            peak_qps = 0

        # 告警统计
        day_alerts = []
        with self._alerts_lock:
            for alert in self._alerts:
                if day_start <= alert.timestamp < day_end:
                    day_alerts.append(alert)

        alert_counts = {
            "total": len(day_alerts),
            "critical": sum(1 for a in day_alerts if a.level == AlertLevel.CRITICAL),
            "warning": sum(1 for a in day_alerts if a.level == AlertLevel.WARNING),
            "info": sum(1 for a in day_alerts if a.level == AlertLevel.INFO),
        }

        report = {
            "date": date,
            "summary": {
                "total_requests": total_requests,
                "avg_p95_ms": round(avg_p95, 3),
                "max_p95_ms": round(max_p95, 3),
                "avg_error_rate": round(avg_error_rate, 4),
                "max_concurrent": max_concurrent,
                "peak_qps": round(peak_qps, 2),
            },
            "alerts": alert_counts,
            "trend": {
                "data_points": len(day_data),
                "hours_covered": round(len(day_data) / 60, 1),
            },
            "recommendations": self._generate_recommendations(day_data, day_alerts),
        }

        # 保存报告
        if self.report_dir:
            self._save_report(report, "daily", date)

        return report

    def _generate_recommendations(
        self,
        day_data: List[Dict[str, Any]],
        alerts: List[Alert],
    ) -> List[str]:
        """生成优化建议"""
        recs = []

        if not day_data:
            return ["数据不足，无法生成建议"]

        max_p95 = max(d.get("p95_ms", 0) for d in day_data)
        if max_p95 > 1000:
            recs.append(f"P95 响应时间最高达 {max_p95:.1f}ms，建议排查慢请求并优化关键接口")

        avg_error_rate = sum(d.get("error_rate", 0) for d in day_data) / len(day_data)
        if avg_error_rate > 0.05:
            recs.append(f"平均错误率 {avg_error_rate*100:.1f}%，建议检查错误日志并修复问题")

        critical_alerts = sum(1 for a in alerts if a.level == AlertLevel.CRITICAL)
        if critical_alerts > 0:
            recs.append(f"当日产生 {critical_alerts} 个严重告警，请优先处理")

        if not recs:
            recs.append("系统运行状态良好，继续保持")

        return recs

    # ---------- 趋势分析 ----------

    def get_trend_analysis(
        self,
        metric: str = "p95_ms",
        hours: int = 24,
    ) -> Dict[str, Any]:
        """获取性能趋势分析

        Args:
            metric: 指标名 (p95_ms, qps, error_rate, concurrent_requests)
            hours: 小时数

        Returns:
            趋势数据
        """
        cutoff = time.time() - hours * 3600

        data_points = []
        with self._history_lock:
            for item in self._history:
                if item["timestamp"] >= cutoff:
                    data_points.append(item)

        values = [d.get(metric, 0) for d in data_points]

        if not values:
            return {
                "metric": metric,
                "hours": hours,
                "data_points": 0,
                "trend": "insufficient_data",
            }

        # 简单趋势判断 (比较前半和后半)
        mid = len(values) // 2
        if mid > 0:
            first_half = sum(values[:mid]) / mid
            second_half = sum(values[mid:]) / (len(values) - mid)
            if second_half > first_half * 1.1:
                trend = "rising"
            elif second_half < first_half * 0.9:
                trend = "falling"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "metric": metric,
            "hours": hours,
            "data_points": len(data_points),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
            "avg": round(sum(values) / len(values), 3),
            "trend": trend,
            "timestamps": [d["timestamp"] for d in data_points],
            "values": values,
        }

    def record_history_point(self, summary: Optional[Dict[str, Any]] = None) -> None:
        """记录一个历史数据点 (每分钟调用一次)

        Args:
            summary: 指标摘要，None 则从 metrics_collector 获取
        """
        if summary is None and self.metrics:
            summary = self.metrics.get_summary()
        if summary is None:
            return

        point = {
            "timestamp": time.time(),
            "total_requests": summary.get("total_requests", 0),
            "qps_1m": summary.get("qps", {}).get("1m", 0),
            "avg_response_time_ms": summary.get("avg_response_time_ms", 0),
            "p50_ms": summary.get("p50_ms", 0),
            "p95_ms": summary.get("p95_ms", 0),
            "p99_ms": summary.get("p99_ms", 0),
            "error_rate": summary.get("error_rate", 0),
            "concurrent_requests": summary.get("concurrent_requests", 0),
        }

        with self._history_lock:
            self._history.append(point)

    # ---------- 告警管理 ----------

    def check_alerts(self) -> List[Alert]:
        """检查告警规则，返回新触发的告警"""
        now = time.time()
        if now - self._last_alert_check < self._alert_check_interval:
            return []
        self._last_alert_check = now

        new_alerts: List[Alert] = []

        if not self.metrics:
            return new_alerts

        summary = self.metrics.get_summary()
        system = self.metrics.get_system_metrics()

        for rule in self.alert_rules:
            if not rule.enabled:
                continue

            value = self._get_metric_value(rule.type, summary, system)
            if value is None:
                continue

            # 判断是否超过阈值
            triggered = False
            if rule.type in (AlertType.CACHE_LOW_HIT_RATE,):
                # 低于阈值触发
                triggered = value < rule.threshold
            else:
                # 高于阈值触发
                triggered = value > rule.threshold

            if triggered:
                # 检查抑制
                suppress_key = rule.name
                if suppress_key in self._alert_suppression:
                    if now - self._alert_suppression[suppress_key] < self._suppression_ttl:
                        continue

                # 创建告警
                alert = Alert(
                    id=f"alert_{int(now)}_{rule.name.replace(' ', '_')}",
                    rule_name=rule.name,
                    type=rule.type,
                    level=rule.level,
                    message=f"{rule.description} (当前: {value:.2f}, 阈值: {rule.threshold})",
                    value=value,
                    threshold=rule.threshold,
                    timestamp=now,
                )

                with self._alerts_lock:
                    self._alerts.append(alert)

                self._alert_suppression[suppress_key] = now
                new_alerts.append(alert)

        return new_alerts

    def _get_metric_value(
        self,
        alert_type: AlertType,
        summary: Dict[str, Any],
        system: Dict[str, Any],
    ) -> Optional[float]:
        """获取指标值"""
        try:
            if alert_type == AlertType.RESPONSE_TIMEOUT:
                return summary.get("p95_ms", 0)
            elif alert_type == AlertType.ERROR_RATE_HIGH:
                return summary.get("error_rate", 0)
            elif alert_type == AlertType.HIGH_CONCURRENCY:
                return float(summary.get("concurrent_requests", 0))
            elif alert_type == AlertType.HIGH_MEMORY:
                return float(system.get("system_memory", {}).get("percent", 0))
            elif alert_type == AlertType.HIGH_CPU:
                return float(system.get("system_cpu", {}).get("percent", 0))
            elif alert_type == AlertType.CACHE_LOW_HIT_RATE:
                if self.cache_mgr:
                    stats = self.cache_mgr.get_stats()
                    return stats.get("overall_hit_rate", 0)
                return None
            elif alert_type == AlertType.SLOW_QUERY:
                if self.metrics:
                    db = self.metrics.get_db_metrics()
                    return float(db.get("slow_count", 0))
                return None
        except Exception:
            return None
        return None

    def get_alerts(
        self,
        level: Optional[AlertLevel] = None,
        limit: int = 100,
        acknowledged: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """获取告警列表

        Args:
            level: 按级别过滤
            limit: 返回数量
            acknowledged: 是否确认 (None 表示全部)

        Returns:
            告警列表 (最新的在前)
        """
        with self._alerts_lock:
            alerts = list(self._alerts)

        alerts.reverse()  # 最新的在前

        if level is not None:
            alerts = [a for a in alerts if a.level == level]

        if acknowledged is not None:
            alerts = [a for a in alerts if a.acknowledged == acknowledged]

        return [a.to_dict() for a in alerts[:limit]]

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """获取活跃告警 (未确认的)"""
        return self.get_alerts(acknowledged=False, limit=20)

    def acknowledge_alert(
        self,
        alert_id: str,
        acknowledged_by: str = "system",
    ) -> bool:
        """确认告警

        Args:
            alert_id: 告警 ID
            acknowledged_by: 确认者

        Returns:
            是否成功
        """
        with self._alerts_lock:
            for alert in self._alerts:
                if alert.id == alert_id:
                    alert.acknowledged = True
                    alert.acknowledged_at = time.time()
                    alert.acknowledged_by = acknowledged_by
                    return True
        return False

    # ---------- 报告持久化 ----------

    def _save_report(self, report: Dict[str, Any], report_type: str, identifier: str) -> None:
        """保存报告到文件"""
        if not self.report_dir:
            return
        try:
            os.makedirs(self.report_dir, exist_ok=True)
            filename = f"{report_type}_{identifier}.json"
            filepath = os.path.join(self.report_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------- 重置 ----------

    def reset(self) -> None:
        """重置所有数据"""
        with self._alerts_lock:
            self._alerts.clear()
            self._alert_suppression.clear()
        with self._history_lock:
            self._history.clear()
        self._last_alert_check = 0.0
