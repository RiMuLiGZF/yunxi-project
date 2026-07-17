"""
云汐内置告警规则与监控告警体系（OB-003, P1级）

提供生产级别的告警机制，无需依赖 Prometheus + Grafana 即可使用。

核心功能：
- AlertSeverity: 告警严重级别（INFO / WARNING / CRITICAL）
- AlertRule: 告警规则定义（ID、名称、条件、检查间隔、静默期、通知渠道）
- AlertEngine: 告警引擎（规则注册、定时检查、去重静默、历史记录、状态管理）
- 通知渠道：LogNotifier / ConsoleNotifier / WebhookNotifier / NotifierManager
- 内置告警规则：系统资源、服务健康、性能、安全四大类
- Alert API: 告警查询、确认、静默、规则管理

使用方式：
    from shared.core.observability import AlertEngine, AlertSeverity, get_alert_engine

    # 获取全局告警引擎
    engine = get_alert_engine()

    # 启动告警检查
    engine.start()

    # 获取活跃告警
    active_alerts = engine.get_active_alerts()

    # 确认告警
    engine.acknowledge_alert(alert_id, acknowledged_by="admin")
"""

import time
import json
import threading
import asyncio
import re
from enum import Enum
from typing import (
    Dict,
    Any,
    Optional,
    List,
    Callable,
    Union,
    Set,
    Tuple,
)
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import deque


# ============================================================================
# 告警严重级别
# ============================================================================

class AlertSeverity(str, Enum):
    """告警严重级别

    - INFO: 信息级，一般通知性质，不影响服务
    - WARNING: 警告级，需要关注，可能影响服务质量
    - CRITICAL: 严重级，立即处理，服务可能不可用
    """
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @classmethod
    def from_str(cls, value: str) -> "AlertSeverity":
        """从字符串转换为枚举值（不区分大小写）"""
        value_lower = value.lower().strip()
        for s in cls:
            if s.value == value_lower:
                return s
        # 兼容常见别名
        alias_map = {
            "info": cls.INFO,
            "debug": cls.INFO,
            "notice": cls.INFO,
            "warn": cls.WARNING,
            "warning": cls.WARNING,
            "error": cls.WARNING,  # error 映射为 warning 级别
            "err": cls.WARNING,
            "critical": cls.CRITICAL,
            "fatal": cls.CRITICAL,
            "emergency": cls.CRITICAL,
            "alert": cls.CRITICAL,
        }
        return alias_map.get(value_lower, cls.WARNING)

    @property
    def numeric_level(self) -> int:
        """数字级别，用于比较严重程度"""
        return {
            AlertSeverity.INFO: 1,
            AlertSeverity.WARNING: 2,
            AlertSeverity.CRITICAL: 3,
        }[self]

    def __ge__(self, other: "AlertSeverity") -> bool:
        return self.numeric_level >= other.numeric_level

    def __gt__(self, other: "AlertSeverity") -> bool:
        return self.numeric_level > other.numeric_level

    def __le__(self, other: "AlertSeverity") -> bool:
        return self.numeric_level <= other.numeric_level

    def __lt__(self, other: "AlertSeverity") -> bool:
        return self.numeric_level < other.numeric_level


# ============================================================================
# 告警状态
# ============================================================================

class AlertState(str, Enum):
    """告警状态

    - firing: 告警触发中（活跃）
    - acknowledged: 已确认（有人在处理）
    - silenced: 已静默（暂时屏蔽）
    - resolved: 已解决
    """
    FIRING = "firing"
    ACKNOWLEDGED = "acknowledged"
    SILENCED = "silenced"
    RESOLVED = "resolved"


# ============================================================================
# 告警事件数据类
# ============================================================================

@dataclass
class AlertEvent:
    """告警事件

    表示一次具体的告警触发或恢复事件。
    """
    id: str
    rule_id: str
    rule_name: str
    severity: AlertSeverity
    state: AlertState
    summary: str
    description: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    value: Optional[float] = None
    threshold: Optional[float] = None
    started_at: float = field(default_factory=time.time)
    last_updated_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    acknowledged_at: Optional[float] = None
    acknowledged_by: Optional[str] = None
    silenced_until: Optional[float] = None
    silenced_by: Optional[str] = None
    silence_reason: Optional[str] = None
    firing_count: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "state": self.state.value,
            "summary": self.summary,
            "description": self.description,
            "labels": self.labels,
            "annotations": self.annotations,
            "value": self.value,
            "threshold": self.threshold,
            "started_at": self.started_at,
            "started_at_formatted": datetime.fromtimestamp(self.started_at).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "last_updated_at": self.last_updated_at,
            "last_updated_at_formatted": datetime.fromtimestamp(
                self.last_updated_at
            ).strftime("%Y-%m-%d %H:%M:%S"),
            "resolved_at": self.resolved_at,
            "resolved_at_formatted": (
                datetime.fromtimestamp(self.resolved_at).strftime("%Y-%m-%d %H:%M:%S")
                if self.resolved_at
                else None
            ),
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
            "silenced_until": self.silenced_until,
            "silenced_by": self.silenced_by,
            "silence_reason": self.silence_reason,
            "firing_count": self.firing_count,
            "duration_seconds": round(time.time() - self.started_at, 2),
        }


# ============================================================================
# 告警规则
# ============================================================================

@dataclass
class AlertRule:
    """告警规则定义

    属性：
        rule_id: 规则唯一标识
        name: 规则名称
        description: 规则描述
        severity: 告警严重级别
        condition: 告警条件（可调用对象或表达式字符串）
            - 可调用对象: 接收 context 参数，返回 (bool, value, details) 元组
              bool=True 表示触发告警，value 是当前值，details 是额外信息
            - 表达式字符串: 支持简单的比较表达式，如 "cpu_usage > 80"
        check_interval: 检查间隔（秒），默认 60 秒
        silence_period: 静默期（秒），同一告警触发后多久内不重复通知，默认 300 秒
        notification_channels: 通知渠道名称列表，为空则使用默认渠道
        labels: 标签（用于分类和过滤）
        annotations: 注解（附加说明信息）
        enabled: 是否启用
        is_builtin: 是否为内置规则
    """
    rule_id: str
    name: str
    description: str
    severity: AlertSeverity
    condition: Union[Callable[[Dict[str, Any]], Tuple[bool, Optional[float], Dict[str, Any]]], str]
    check_interval: int = 60
    silence_period: int = 300
    notification_channels: List[str] = field(default_factory=list)
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    is_builtin: bool = False

    # 运行时状态
    _last_check_time: float = 0.0
    _last_fire_time: float = 0.0
    _last_value: Optional[float] = None

    def evaluate(self, context: Dict[str, Any]) -> Tuple[bool, Optional[float], Dict[str, Any]]:
        """评估告警条件

        Args:
            context: 评估上下文，包含当前指标数据等

        Returns:
            (是否触发告警, 当前值, 详细信息)
        """
        if not self.enabled:
            return False, None, {}

        if callable(self.condition):
            try:
                result = self.condition(context)
                if isinstance(result, tuple) and len(result) >= 1:
                    triggered = bool(result[0])
                    value = result[1] if len(result) > 1 else None
                    details = result[2] if len(result) > 2 else {}
                    return triggered, value, details
                return bool(result), None, {}
            except Exception as e:
                return False, None, {"error": str(e)}
        elif isinstance(self.condition, str):
            return self._evaluate_expression(self.condition, context)
        return False, None, {}

    def _evaluate_expression(
        self, expr: str, context: Dict[str, Any]
    ) -> Tuple[bool, Optional[float], Dict[str, Any]]:
        """评估表达式字符串

        支持格式：
            - "metric_name > threshold"
            - "metric_name >= threshold"
            - "metric_name < threshold"
            - "metric_name <= threshold"
            - "metric_name == threshold"
            - "metric_name != threshold"
        """
        # 解析表达式
        pattern = r"^\s*(\w+)\s*(>=|<=|==|!=|>|<)\s*([\d.]+)\s*$"
        match = re.match(pattern, expr)
        if not match:
            return False, None, {"error": f"Invalid expression: {expr}"}

        metric_name, op, threshold_str = match.groups()
        try:
            threshold = float(threshold_str)
        except ValueError:
            return False, None, {"error": f"Invalid threshold: {threshold_str}"}

        # 从 context 中获取指标值
        value = context.get(metric_name)
        if value is None:
            # 尝试从嵌套字典中获取
            for key in context:
                if isinstance(context[key], dict) and metric_name in context[key]:
                    value = context[key][metric_name]
                    break

        if value is None:
            return False, None, {"error": f"Metric '{metric_name}' not found in context"}

        try:
            value_float = float(value)
        except (ValueError, TypeError):
            return False, None, {"error": f"Metric '{metric_name}' is not numeric"}

        # 比较
        triggered = False
        if op == ">":
            triggered = value_float > threshold
        elif op == ">=":
            triggered = value_float >= threshold
        elif op == "<":
            triggered = value_float < threshold
        elif op == "<=":
            triggered = value_float <= threshold
        elif op == "==":
            triggered = value_float == threshold
        elif op == "!=":
            triggered = value_float != threshold

        return triggered, value_float, {
            "metric": metric_name,
            "operator": op,
            "threshold": threshold,
            "value": value_float,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "severity": self.severity.value,
            "condition": self.condition if isinstance(self.condition, str) else "<callable>",
            "check_interval": self.check_interval,
            "silence_period": self.silence_period,
            "notification_channels": self.notification_channels,
            "labels": self.labels,
            "annotations": self.annotations,
            "enabled": self.enabled,
            "is_builtin": self.is_builtin,
            "last_check_time": self._last_check_time,
            "last_fire_time": self._last_fire_time,
        }


# ============================================================================
# 通知渠道基类
# ============================================================================

class Notifier:
    """通知渠道基类"""

    def __init__(self, name: str, min_severity: AlertSeverity = AlertSeverity.INFO):
        self.name = name
        self.min_severity = min_severity
        self.enabled = True

    def should_notify(self, severity: AlertSeverity) -> bool:
        """判断是否应该通过此渠道发送通知"""
        return self.enabled and severity >= self.min_severity

    def notify(self, alert: AlertEvent) -> bool:
        """发送告警通知

        Args:
            alert: 告警事件

        Returns:
            是否发送成功
        """
        if not self.should_notify(alert.severity):
            return False
        try:
            return self._do_notify(alert)
        except Exception:
            return False

    def _do_notify(self, alert: AlertEvent) -> bool:
        """实际发送通知的实现，子类重写"""
        raise NotImplementedError

    def notify_resolved(self, alert: AlertEvent) -> bool:
        """发送告警恢复通知

        Args:
            alert: 已恢复的告警事件

        Returns:
            是否发送成功
        """
        if not self.should_notify(alert.severity):
            return False
        try:
            return self._do_notify_resolved(alert)
        except Exception:
            return False

    def _do_notify_resolved(self, alert: AlertEvent) -> bool:
        """实际发送恢复通知的实现，子类可重写"""
        return False


# ============================================================================
# LogNotifier - 日志通知
# ============================================================================

class LogNotifier(Notifier):
    """日志通知渠道

    将告警信息写入日志文件。默认启用，是最基础的通知方式。
    """

    def __init__(
        self,
        name: str = "log",
        min_severity: AlertSeverity = AlertSeverity.INFO,
        logger: Optional[Any] = None,
    ):
        super().__init__(name=name, min_severity=min_severity)
        self._logger = logger

    @property
    def logger(self):
        """懒加载日志器"""
        if self._logger is None:
            try:
                from .unified_logger import get_logger
                self._logger = get_logger("yunxi.alerts")
            except ImportError:
                import logging
                self._logger = logging.getLogger("yunxi.alerts")
        return self._logger

    def _do_notify(self, alert: AlertEvent) -> bool:
        msg = (
            f"[ALERT FIRING] {alert.severity.value.upper()}: {alert.summary} "
            f"(rule={alert.rule_id}, value={alert.value}, threshold={alert.threshold})"
        )
        details = {
            "alert_id": alert.id,
            "rule_id": alert.rule_id,
            "severity": alert.severity.value,
            "summary": alert.summary,
            "description": alert.description,
            "value": alert.value,
            "threshold": alert.threshold,
            "labels": alert.labels,
            "started_at": alert.started_at,
        }

        if alert.severity == AlertSeverity.CRITICAL:
            self.logger.critical(msg, **details)
        elif alert.severity == AlertSeverity.WARNING:
            self.logger.warning(msg, **details)
        else:
            self.logger.info(msg, **details)

        return True

    def _do_notify_resolved(self, alert: AlertEvent) -> bool:
        msg = (
            f"[ALERT RESOLVED] {alert.severity.value.upper()}: {alert.summary} "
            f"(rule={alert.rule_id}, duration={round(time.time() - alert.started_at, 1)}s)"
        )
        self.logger.info(msg, alert_id=alert.id, rule_id=alert.rule_id)
        return True


# ============================================================================
# ConsoleNotifier - 控制台通知
# ============================================================================

class ConsoleNotifier(Notifier):
    """控制台通知渠道

    将告警信息输出到控制台，开发环境使用。
    """

    # 颜色代码
    COLORS = {
        AlertSeverity.INFO: "\033[36m",      # 青色
        AlertSeverity.WARNING: "\033[33m",   # 黄色
        AlertSeverity.CRITICAL: "\033[31m",  # 红色
    }
    RESET = "\033[0m"

    def __init__(
        self,
        name: str = "console",
        min_severity: AlertSeverity = AlertSeverity.INFO,
        use_color: bool = True,
    ):
        super().__init__(name=name, min_severity=min_severity)
        self.use_color = use_color

    def _do_notify(self, alert: AlertEvent) -> bool:
        color = self.COLORS.get(alert.severity, "") if self.use_color else ""
        reset = self.RESET if color else ""
        timestamp = datetime.fromtimestamp(alert.started_at).strftime("%Y-%m-%d %H:%M:%S")

        print(
            f"{color}[{timestamp}] ALERT [{alert.severity.value.upper()}] "
            f"{alert.summary}{reset}"
        )
        if alert.description:
            print(f"  {alert.description}")
        if alert.value is not None and alert.threshold is not None:
            print(f"  Value: {alert.value}, Threshold: {alert.threshold}")
        return True

    def _do_notify_resolved(self, alert: AlertEvent) -> bool:
        green = "\033[32m" if self.use_color else ""
        reset = self.RESET if self.use_color else ""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        duration = round(time.time() - alert.started_at, 1)

        print(
            f"{green}[{timestamp}] RESOLVED [{alert.severity.value.upper()}] "
            f"{alert.summary} (duration: {duration}s){reset}"
        )
        return True


# ============================================================================
# WebhookNotifier - Webhook 通知
# ============================================================================

class WebhookNotifier(Notifier):
    """Webhook 通知渠道

    通过 HTTP POST 将告警信息发送到配置的 Webhook URL。
    支持自定义请求头和超时设置。
    """

    def __init__(
        self,
        name: str = "webhook",
        url: str = "",
        min_severity: AlertSeverity = AlertSeverity.WARNING,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 5.0,
    ):
        super().__init__(name=name, min_severity=min_severity)
        self.url = url
        self.headers = headers or {"Content-Type": "application/json"}
        self.timeout = timeout

    def _build_payload(self, alert: AlertEvent, event_type: str = "firing") -> Dict[str, Any]:
        """构建 Webhook 请求体"""
        return {
            "event_type": event_type,
            "alert": alert.to_dict(),
            "timestamp": time.time(),
            "source": "yunxi-alerting",
        }

    def _do_notify(self, alert: AlertEvent) -> bool:
        if not self.url:
            return False
        try:
            import urllib.request
            payload = json.dumps(self._build_payload(alert, "firing")).encode("utf-8")
            req = urllib.request.Request(
                self.url, data=payload, headers=self.headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    def _do_notify_resolved(self, alert: AlertEvent) -> bool:
        if not self.url:
            return False
        try:
            import urllib.request
            payload = json.dumps(self._build_payload(alert, "resolved")).encode("utf-8")
            req = urllib.request.Request(
                self.url, data=payload, headers=self.headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False


# ============================================================================
# NotifierManager - 通知管理器
# ============================================================================

class NotifierManager:
    """通知管理器

    管理多个通知渠道，按严重级别和规则配置路由到不同渠道。
    """

    def __init__(self):
        self._notifiers: Dict[str, Notifier] = {}
        self._default_channels: List[str] = []
        self._lock = threading.Lock()

    def register(self, notifier: Notifier) -> None:
        """注册通知渠道"""
        with self._lock:
            self._notifiers[notifier.name] = notifier

    def unregister(self, name: str) -> None:
        """注销通知渠道"""
        with self._lock:
            self._notifiers.pop(name, None)

    def get(self, name: str) -> Optional[Notifier]:
        """获取通知渠道"""
        with self._lock:
            return self._notifiers.get(name)

    def set_default_channels(self, channels: List[str]) -> None:
        """设置默认通知渠道列表"""
        self._default_channels = list(channels)

    def notify(self, alert: AlertEvent, channels: Optional[List[str]] = None) -> Dict[str, bool]:
        """发送告警通知

        Args:
            alert: 告警事件
            channels: 指定通知渠道，为空则使用默认渠道

        Returns:
            各渠道发送结果字典 {channel_name: success}
        """
        channel_names = channels or self._default_channels
        results = {}

        with self._lock:
            notifiers = list(self._notifiers.items())

        for name, notifier in notifiers:
            if channel_names and name not in channel_names:
                continue
            results[name] = notifier.notify(alert)

        return results

    def notify_resolved(
        self, alert: AlertEvent, channels: Optional[List[str]] = None
    ) -> Dict[str, bool]:
        """发送告警恢复通知"""
        channel_names = channels or self._default_channels
        results = {}

        with self._lock:
            notifiers = list(self._notifiers.items())

        for name, notifier in notifiers:
            if channel_names and name not in channel_names:
                continue
            results[name] = notifier.notify_resolved(alert)

        return results

    def list_channels(self) -> List[Dict[str, Any]]:
        """列出所有通知渠道"""
        with self._lock:
            return [
                {
                    "name": n.name,
                    "type": type(n).__name__,
                    "min_severity": n.min_severity.value,
                    "enabled": n.enabled,
                }
                for n in self._notifiers.values()
            ]


# ============================================================================
# 系统指标采集（用于告警评估上下文）
# ============================================================================

def _collect_system_metrics() -> Dict[str, Any]:
    """采集系统指标作为告警评估上下文

    返回包含 CPU、内存、磁盘等指标的字典。
    """
    context: Dict[str, Any] = {
        "timestamp": time.time(),
    }

    # CPU 和内存（需要 psutil）
    try:
        import psutil

        # CPU 使用率
        cpu_percent = psutil.cpu_percent(interval=0.1)
        context["cpu_usage"] = cpu_percent
        context["cpu_percent"] = cpu_percent
        context["cpu"] = {
            "usage_percent": cpu_percent,
            "core_count": psutil.cpu_count(logical=True),
        }

        # 内存使用
        mem = psutil.virtual_memory()
        context["memory_usage"] = mem.percent
        context["memory_percent"] = mem.percent
        context["memory"] = {
            "total_bytes": mem.total,
            "used_bytes": mem.used,
            "available_bytes": mem.available,
            "percent": mem.percent,
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "used_gb": round(mem.used / (1024 ** 3), 2),
            "available_gb": round(mem.available / (1024 ** 3), 2),
        }

        # 磁盘使用
        try:
            import shutil
            import os
            disk = shutil.disk_usage(".")
            disk_percent = (disk.used / disk.total) * 100
            context["disk_usage"] = disk_percent
            context["disk_percent"] = disk_percent
            context["disk_free_bytes"] = disk.free
            context["disk_free_gb"] = round(disk.free / (1024 ** 3), 2)
            context["disk"] = {
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "free_bytes": disk.free,
                "percent": round(disk_percent, 2),
                "total_gb": round(disk.total / (1024 ** 3), 2),
                "used_gb": round(disk.used / (1024 ** 3), 2),
                "free_gb": round(disk.free / (1024 ** 3), 2),
                "path": os.path.abspath("."),
            }
        except Exception:
            pass

    except ImportError:
        # psutil 不可用，设置默认值
        context["cpu_usage"] = 0.0
        context["memory_usage"] = 0.0
        context["disk_usage"] = 0.0
        context["disk_free_bytes"] = float("inf")

    return context


# ============================================================================
# 内置告警规则定义
# ============================================================================

def _build_builtin_rules() -> List[AlertRule]:
    """构建内置告警规则列表

    分为四大类：
    1. 系统资源类（CPU、内存、磁盘）
    2. 服务健康类（模块健康检查、重启次数）
    3. 性能类（API 错误率、响应时间、请求队列）
    4. 安全类（登录失败、WAF 攻击、配置修改）
    """
    rules: List[AlertRule] = []

    # ---- 系统资源类 ----

    # CPU 使用率 > 80% (WARNING)
    rules.append(
        AlertRule(
            rule_id="system_cpu_high_warning",
            name="CPU使用率偏高",
            description="CPU 使用率超过 80%，系统负载较高，建议关注",
            severity=AlertSeverity.WARNING,
            condition="cpu_usage > 80",
            check_interval=60,
            silence_period=300,
            labels={"category": "system", "resource": "cpu"},
            annotations={
                "runbook": "检查高 CPU 进程，考虑扩容或优化",
                "impact": "系统响应可能变慢",
            },
            is_builtin=True,
        )
    )

    # CPU 使用率 > 95% (CRITICAL)
    rules.append(
        AlertRule(
            rule_id="system_cpu_high_critical",
            name="CPU使用率严重过高",
            description="CPU 使用率超过 95%，系统可能出现严重性能问题",
            severity=AlertSeverity.CRITICAL,
            condition="cpu_usage > 95",
            check_interval=30,
            silence_period=120,
            labels={"category": "system", "resource": "cpu"},
            annotations={
                "runbook": "立即排查高 CPU 进程，考虑限流或紧急扩容",
                "impact": "服务可能不可用",
            },
            is_builtin=True,
        )
    )

    # 内存使用率 > 85% (WARNING)
    rules.append(
        AlertRule(
            rule_id="system_memory_high_warning",
            name="内存使用率偏高",
            description="内存使用率超过 85%，建议关注内存占用情况",
            severity=AlertSeverity.WARNING,
            condition="memory_usage > 85",
            check_interval=60,
            silence_period=300,
            labels={"category": "system", "resource": "memory"},
            annotations={
                "runbook": "检查内存占用高的进程，考虑释放缓存或扩容",
                "impact": "可能触发 OOM，影响服务稳定性",
            },
            is_builtin=True,
        )
    )

    # 内存使用率 > 95% (CRITICAL)
    rules.append(
        AlertRule(
            rule_id="system_memory_high_critical",
            name="内存使用率严重过高",
            description="内存使用率超过 95%，随时可能 OOM，需立即处理",
            severity=AlertSeverity.CRITICAL,
            condition="memory_usage > 95",
            check_interval=30,
            silence_period=120,
            labels={"category": "system", "resource": "memory"},
            annotations={
                "runbook": "立即释放内存或重启服务，考虑紧急扩容",
                "impact": "OOM 导致进程被杀死，服务中断",
            },
            is_builtin=True,
        )
    )

    # 磁盘使用率 > 80% (WARNING)
    rules.append(
        AlertRule(
            rule_id="system_disk_high_warning",
            name="磁盘空间不足",
            description="磁盘使用率超过 80%，建议及时清理磁盘空间",
            severity=AlertSeverity.WARNING,
            condition="disk_usage > 80",
            check_interval=300,
            silence_period=1800,
            labels={"category": "system", "resource": "disk"},
            annotations={
                "runbook": "清理日志文件、临时文件，考虑扩容磁盘",
                "impact": "日志写入失败、数据库异常",
            },
            is_builtin=True,
        )
    )

    # 磁盘使用率 > 90% (CRITICAL)
    rules.append(
        AlertRule(
            rule_id="system_disk_high_critical",
            name="磁盘空间严重不足",
            description="磁盘使用率超过 90%，请立即清理磁盘空间",
            severity=AlertSeverity.CRITICAL,
            condition="disk_usage > 90",
            check_interval=120,
            silence_period=600,
            labels={"category": "system", "resource": "disk"},
            annotations={
                "runbook": "紧急清理大文件，考虑扩容或迁移数据",
                "impact": "服务无法写入，数据库崩溃",
            },
            is_builtin=True,
        )
    )

    # 磁盘剩余空间 < 1GB (CRITICAL)
    def _check_disk_free(context: Dict[str, Any]) -> Tuple[bool, Optional[float], Dict[str, Any]]:
        free_bytes = context.get("disk_free_bytes", float("inf"))
        free_gb = free_bytes / (1024 ** 3) if isinstance(free_bytes, (int, float)) else float("inf")
        threshold_gb = 1.0
        triggered = free_gb < threshold_gb
        return triggered, round(free_gb, 2), {"threshold_gb": threshold_gb, "unit": "GB"}

    rules.append(
        AlertRule(
            rule_id="system_disk_free_critical",
            name="磁盘剩余空间不足1GB",
            description="磁盘剩余空间不足 1GB，服务随时可能停止写入",
            severity=AlertSeverity.CRITICAL,
            condition=_check_disk_free,
            check_interval=120,
            silence_period=600,
            labels={"category": "system", "resource": "disk"},
            annotations={
                "runbook": "立即清理磁盘空间，否则服务将无法正常运行",
                "impact": "所有需要写入磁盘的操作都会失败",
            },
            is_builtin=True,
        )
    )

    # ---- 服务健康类 ----

    # 模块健康检查失败（WARNING）- 由外部触发
    rules.append(
        AlertRule(
            rule_id="service_health_failure_warning",
            name="模块健康检查失败",
            description="模块健康检查失败，服务可能出现异常",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (False, None, {}),  # 默认不自动触发，由外部调用
            check_interval=0,
            silence_period=300,
            labels={"category": "service", "type": "health"},
            annotations={
                "runbook": "检查模块日志，确认服务状态",
                "impact": "部分功能可能不可用",
            },
            is_builtin=True,
            enabled=False,  # 手动触发类型，默认禁用自动检查
        )
    )

    # 模块连续 3 次健康检查失败（CRITICAL）- 由外部触发
    rules.append(
        AlertRule(
            rule_id="service_health_failure_critical",
            name="模块连续健康检查失败",
            description="模块连续 3 次健康检查失败，服务可能已不可用",
            severity=AlertSeverity.CRITICAL,
            condition=lambda ctx: (False, None, {}),  # 默认不自动触发，由外部调用
            check_interval=0,
            silence_period=300,
            labels={"category": "service", "type": "health"},
            annotations={
                "runbook": "立即排查服务状态，尝试重启服务",
                "impact": "服务不可用",
            },
            is_builtin=True,
            enabled=False,
        )
    )

    # 模块重启次数 > 5 次/小时（WARNING）- 由外部触发
    rules.append(
        AlertRule(
            rule_id="service_restart_high_warning",
            name="模块重启频繁",
            description="模块 1 小时内重启次数超过 5 次，可能存在稳定性问题",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (False, None, {}),  # 默认不自动触发
            check_interval=0,
            silence_period=1800,
            labels={"category": "service", "type": "restart"},
            annotations={
                "runbook": "检查模块崩溃日志，排查稳定性问题",
                "impact": "服务间歇性不可用",
            },
            is_builtin=True,
            enabled=False,
        )
    )

    # ---- 性能类 ----

    # API 错误率 > 5% (WARNING) - 由外部触发
    rules.append(
        AlertRule(
            rule_id="api_error_rate_warning",
            name="API错误率偏高",
            description="API 错误率超过 5%，建议排查错误原因",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (False, None, {}),
            check_interval=0,
            silence_period=300,
            labels={"category": "performance", "type": "api"},
            annotations={
                "runbook": "查看错误日志，排查高错误率接口",
                "impact": "用户体验下降",
            },
            is_builtin=True,
            enabled=False,
        )
    )

    # API 错误率 > 10% (CRITICAL) - 由外部触发
    rules.append(
        AlertRule(
            rule_id="api_error_rate_critical",
            name="API错误率严重过高",
            description="API 错误率超过 10%，服务可能存在严重问题",
            severity=AlertSeverity.CRITICAL,
            condition=lambda ctx: (False, None, {}),
            check_interval=0,
            silence_period=300,
            labels={"category": "performance", "type": "api"},
            annotations={
                "runbook": "立即排查错误原因，考虑回滚或限流",
                "impact": "大量用户请求失败",
            },
            is_builtin=True,
            enabled=False,
        )
    )

    # API 平均响应时间 > 1s (WARNING) - 由外部触发
    rules.append(
        AlertRule(
            rule_id="api_latency_warning",
            name="API响应时间偏高",
            description="API 平均响应时间超过 1 秒，用户体验可能受影响",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (False, None, {}),
            check_interval=0,
            silence_period=300,
            labels={"category": "performance", "type": "latency"},
            annotations={
                "runbook": "排查慢接口，优化性能",
                "impact": "用户体验下降",
            },
            is_builtin=True,
            enabled=False,
        )
    )

    # API 平均响应时间 > 3s (CRITICAL) - 由外部触发
    rules.append(
        AlertRule(
            rule_id="api_latency_critical",
            name="API响应时间严重过高",
            description="API 平均响应时间超过 3 秒，服务性能严重下降",
            severity=AlertSeverity.CRITICAL,
            condition=lambda ctx: (False, None, {}),
            check_interval=0,
            silence_period=300,
            labels={"category": "performance", "type": "latency"},
            annotations={
                "runbook": "立即排查性能瓶颈，考虑扩容或降级",
                "impact": "服务严重卡顿，用户大量流失",
            },
            is_builtin=True,
            enabled=False,
        )
    )

    # 请求队列堆积 > 100 (WARNING) - 由外部触发
    rules.append(
        AlertRule(
            rule_id="request_queue_backlog_warning",
            name="请求队列堆积",
            description="请求队列堆积超过 100，系统处理能力不足",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (False, None, {}),
            check_interval=0,
            silence_period=300,
            labels={"category": "performance", "type": "queue"},
            annotations={
                "runbook": "考虑扩容或限流，优化处理速度",
                "impact": "请求延迟增加",
            },
            is_builtin=True,
            enabled=False,
        )
    )

    # ---- 安全类 ----

    # 登录失败次数 > 10 次/分钟（WARNING）- 由外部触发
    rules.append(
        AlertRule(
            rule_id="security_login_failures_warning",
            name="登录失败次数过多",
            description="1 分钟内登录失败超过 10 次，可能存在暴力破解攻击",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (False, None, {}),
            check_interval=0,
            silence_period=300,
            labels={"category": "security", "type": "auth"},
            annotations={
                "runbook": "检查登录日志，考虑启用 IP 限流或验证码",
                "impact": "账户安全风险",
            },
            is_builtin=True,
            enabled=False,
        )
    )

    # 检测到 WAF 攻击（WARNING）- 由外部触发
    rules.append(
        AlertRule(
            rule_id="security_waf_attack_warning",
            name="WAF检测到攻击",
            description="WAF 检测到潜在攻击行为，已拦截",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (False, None, {}),
            check_interval=0,
            silence_period=60,
            labels={"category": "security", "type": "waf"},
            annotations={
                "runbook": "查看 WAF 日志，确认攻击类型和来源",
                "impact": "潜在安全威胁",
            },
            is_builtin=True,
            enabled=False,
        )
    )

    # 配置修改（INFO）- 由外部触发
    rules.append(
        AlertRule(
            rule_id="security_config_change_info",
            name="配置变更通知",
            description="系统配置被修改，请确认是否为预期变更",
            severity=AlertSeverity.INFO,
            condition=lambda ctx: (False, None, {}),
            check_interval=0,
            silence_period=60,
            labels={"category": "security", "type": "config"},
            annotations={
                "runbook": "确认配置变更是否为预期操作",
                "impact": "配置变更可能影响系统行为",
            },
            is_builtin=True,
            enabled=False,
        )
    )

    return rules


# ============================================================================
# AlertEngine - 告警引擎
# ============================================================================

class AlertEngine:
    """告警引擎

    核心功能：
    - 注册/管理告警规则
    - 定时检查所有规则
    - 触发告警（去重、静默）
    - 告警历史记录
    - 告警状态管理（firing/acknowledged/silenced/resolved）
    - 通知发送

    线程安全设计：
    - 活跃告警和历史记录使用锁保护
    - 规则注册使用锁保护
    - 后台检查线程独立运行
    """

    def __init__(
        self,
        service_name: str = "yunxi",
        history_limit: int = 1000,
        auto_start: bool = False,
    ):
        """
        Args:
            service_name: 服务名称
            history_limit: 历史告警最大保留数量
            auto_start: 是否自动启动检查线程
        """
        self.service_name = service_name
        self.history_limit = history_limit

        # 规则存储
        self._rules: Dict[str, AlertRule] = {}
        self._rules_lock = threading.Lock()

        # 活跃告警（当前 firing / acknowledged / silenced 的告警）
        self._active_alerts: Dict[str, AlertEvent] = {}
        self._active_alerts_lock = threading.Lock()

        # 告警历史（环形缓冲区）
        self._history: deque = deque(maxlen=history_limit)
        self._history_lock = threading.Lock()

        # 通知管理器
        self.notifier_manager = NotifierManager()

        # 后台线程
        self._check_thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()

        # 计数器
        self._total_fired = 0
        self._total_resolved = 0

        # 自定义上下文提供者（用于扩展评估上下文）
        self._context_providers: List[Callable[[], Dict[str, Any]]] = []
        self._context_providers_lock = threading.Lock()

        # 注册内置规则
        self._register_builtin_rules()

        # 初始化默认通知渠道
        self._init_default_notifiers()

        if auto_start:
            self.start()

    # -----------------------------------------------------------------------
    # 初始化
    # -----------------------------------------------------------------------

    def _register_builtin_rules(self) -> None:
        """注册内置告警规则"""
        for rule in _build_builtin_rules():
            self._rules[rule.rule_id] = rule

    def _init_default_notifiers(self) -> None:
        """初始化默认通知渠道"""
        # 日志通知（默认启用）
        self.notifier_manager.register(
            LogNotifier(name="log", min_severity=AlertSeverity.INFO)
        )

        # 控制台通知（开发环境，默认 WARNING 以上）
        env = _get_env()
        if env in ("development", "dev", "debug"):
            self.notifier_manager.register(
                ConsoleNotifier(name="console", min_severity=AlertSeverity.WARNING)
            )

        # 设置默认渠道
        default_channels = ["log"]
        if env in ("development", "dev", "debug"):
            default_channels.append("console")
        self.notifier_manager.set_default_channels(default_channels)

        # Webhook 通知（从环境变量配置）
        webhook_url = _get_webhook_url()
        if webhook_url:
            self.notifier_manager.register(
                WebhookNotifier(
                    name="webhook",
                    url=webhook_url,
                    min_severity=AlertSeverity.WARNING,
                )
            )

    # -----------------------------------------------------------------------
    # 规则管理
    # -----------------------------------------------------------------------

    def register_rule(self, rule: AlertRule) -> None:
        """注册告警规则

        Args:
            rule: 告警规则
        """
        with self._rules_lock:
            self._rules[rule.rule_id] = rule

    def unregister_rule(self, rule_id: str) -> bool:
        """注销告警规则

        Args:
            rule_id: 规则 ID

        Returns:
            是否成功
        """
        with self._rules_lock:
            return self._rules.pop(rule_id, None) is not None

    def get_rule(self, rule_id: str) -> Optional[AlertRule]:
        """获取告警规则"""
        with self._rules_lock:
            return self._rules.get(rule_id)

    def list_rules(
        self,
        category: Optional[str] = None,
        severity: Optional[AlertSeverity] = None,
        enabled_only: bool = False,
    ) -> List[AlertRule]:
        """列出告警规则

        Args:
            category: 按类别过滤（对应 label 中的 category）
            severity: 按严重级别过滤
            enabled_only: 只返回启用的规则

        Returns:
            规则列表
        """
        with self._rules_lock:
            rules = list(self._rules.values())

        if category:
            rules = [r for r in rules if r.labels.get("category") == category]

        if severity:
            rules = [r for r in rules if r.severity == severity]

        if enabled_only:
            rules = [r for r in rules if r.enabled]

        return sorted(rules, key=lambda r: (r.severity.numeric_level, r.rule_id))

    def enable_rule(self, rule_id: str) -> bool:
        """启用规则"""
        rule = self.get_rule(rule_id)
        if rule:
            rule.enabled = True
            return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """禁用规则"""
        rule = self.get_rule(rule_id)
        if rule:
            rule.enabled = False
            # 禁用规则时，解决该规则的所有活跃告警
            self._resolve_alerts_for_rule(rule_id, reason="rule_disabled")
            return True
        return False

    def update_rule(self, rule_id: str, **kwargs) -> bool:
        """更新规则属性

        Args:
            rule_id: 规则 ID
            **kwargs: 要更新的属性

        Returns:
            是否成功
        """
        rule = self.get_rule(rule_id)
        if not rule:
            return False

        allowed_fields = {
            "name", "description", "severity", "condition",
            "check_interval", "silence_period", "notification_channels",
            "labels", "annotations", "enabled",
        }

        for key, value in kwargs.items():
            if key in allowed_fields and hasattr(rule, key):
                setattr(rule, key, value)

        return True

    # -----------------------------------------------------------------------
    # 上下文提供者
    # -----------------------------------------------------------------------

    def add_context_provider(self, provider: Callable[[], Dict[str, Any]]) -> None:
        """添加上下文提供者

        上下文提供者是一个返回字典的可调用对象，其返回值会合并到
        告警评估上下文中。用于提供业务指标等额外数据。
        """
        with self._context_providers_lock:
            self._context_providers.append(provider)

    def remove_context_provider(self, provider: Callable) -> None:
        """移除上下文提供者"""
        with self._context_providers_lock:
            try:
                self._context_providers.remove(provider)
            except ValueError:
                pass

    def _build_context(self) -> Dict[str, Any]:
        """构建评估上下文"""
        context = _collect_system_metrics()
        context["service_name"] = self.service_name

        # 合并上下文提供者的数据
        with self._context_providers_lock:
            providers = list(self._context_providers)

        for provider in providers:
            try:
                provider_context = provider()
                if isinstance(provider_context, dict):
                    context.update(provider_context)
            except Exception:
                pass

        return context

    # -----------------------------------------------------------------------
    # 告警检查与触发
    # -----------------------------------------------------------------------

    def check_all_rules(self) -> Dict[str, Any]:
        """检查所有启用的规则

        Returns:
            检查结果摘要
        """
        context = self._build_context()
        fired_count = 0
        resolved_count = 0
        checked_count = 0

        with self._rules_lock:
            rules = list(self._rules.values())

        for rule in rules:
            if not rule.enabled or rule.check_interval <= 0:
                continue

            # 检查是否到达检查间隔
            now = time.time()
            if now - rule._last_check_time < rule.check_interval:
                continue

            rule._last_check_time = now
            checked_count += 1

            try:
                triggered, value, details = rule.evaluate(context)
                rule._last_value = value

                if triggered:
                    fired = self._fire_alert(rule, value, details, context)
                    if fired:
                        fired_count += 1
                else:
                    # 检查是否有该规则的活跃告警需要恢复
                    resolved = self._check_resolve(rule, value, details)
                    if resolved:
                        resolved_count += 1
            except Exception:
                pass

        return {
            "checked_count": checked_count,
            "fired_count": fired_count,
            "resolved_count": resolved_count,
            "active_count": len(self._active_alerts),
            "timestamp": time.time(),
        }

    def _fire_alert(
        self,
        rule: AlertRule,
        value: Optional[float],
        details: Dict[str, Any],
        context: Dict[str, Any],
    ) -> bool:
        """触发告警

        Args:
            rule: 触发的规则
            value: 当前值
            details: 详细信息
            context: 评估上下文

        Returns:
            是否是新触发的告警（去重后）
        """
        alert_key = rule.rule_id  # 同一规则的告警使用规则 ID 作为 key

        with self._active_alerts_lock:
            existing = self._active_alerts.get(alert_key)

            if existing:
                # 已有活跃告警，更新状态
                existing.last_updated_at = time.time()
                existing.firing_count += 1
                existing.value = value
                existing.state = AlertState.FIRING  # 确保是 firing 状态

                # 检查静默期
                now = time.time()
                if now - rule._last_fire_time < rule.silence_period:
                    return False  # 静默期内，不重复通知

                rule._last_fire_time = now
                # 重新发送通知（静默期已过）
                self._send_notifications(existing, rule)
                return False  # 不是新告警

            # 新告警
            import uuid
            alert_id = str(uuid.uuid4())[:8]

            threshold = details.get("threshold")
            summary = rule.name
            description = rule.description
            if value is not None and threshold is not None:
                description = f"{rule.description} 当前值: {value}, 阈值: {threshold}"

            alert = AlertEvent(
                id=alert_id,
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=rule.severity,
                state=AlertState.FIRING,
                summary=summary,
                description=description,
                labels=dict(rule.labels),
                annotations=dict(rule.annotations),
                value=value,
                threshold=threshold,
                started_at=time.time(),
                last_updated_at=time.time(),
            )

            self._active_alerts[alert_key] = alert
            rule._last_fire_time = time.time()
            self._total_fired += 1

            # 加入历史
            with self._history_lock:
                self._history.append(alert.to_dict())

        # 发送通知（在锁外发送，避免阻塞）
        self._send_notifications(alert, rule)

        return True

    def _check_resolve(
        self,
        rule: AlertRule,
        value: Optional[float],
        details: Dict[str, Any],
    ) -> bool:
        """检查告警是否恢复

        Args:
            rule: 规则
            value: 当前值
            details: 详细信息

        Returns:
            是否恢复
        """
        alert_key = rule.rule_id

        with self._active_alerts_lock:
            alert = self._active_alerts.get(alert_key)
            if not alert:
                return False

            if alert.state in (AlertState.RESOLVED,):
                return False

            # 条件不再满足，标记为已解决
            alert.state = AlertState.RESOLVED
            alert.resolved_at = time.time()
            alert.last_updated_at = time.time()

            # 从活跃告警中移除
            del self._active_alerts[alert_key]
            self._total_resolved += 1

            # 更新历史记录
            with self._history_lock:
                self._history.append(alert.to_dict())

        # 发送恢复通知
        self._send_resolved_notifications(alert, rule)

        return True

    def _resolve_alerts_for_rule(self, rule_id: str, reason: str = "") -> None:
        """解决指定规则的所有活跃告警"""
        with self._active_alerts_lock:
            to_resolve = [
                alert for key, alert in self._active_alerts.items()
                if alert.rule_id == rule_id
            ]
            for alert in to_resolve:
                alert.state = AlertState.RESOLVED
                alert.resolved_at = time.time()
                alert.last_updated_at = time.time()
                if reason:
                    alert.annotations["resolve_reason"] = reason
                del self._active_alerts[alert.rule_id]
                self._total_resolved += 1

                with self._history_lock:
                    self._history.append(alert.to_dict())

    def _send_notifications(self, alert: AlertEvent, rule: AlertRule) -> None:
        """发送告警通知"""
        channels = rule.notification_channels if rule.notification_channels else None
        self.notifier_manager.notify(alert, channels=channels)

    def _send_resolved_notifications(self, alert: AlertEvent, rule: AlertRule) -> None:
        """发送恢复通知"""
        channels = rule.notification_channels if rule.notification_channels else None
        self.notifier_manager.notify_resolved(alert, channels=channels)

    # -----------------------------------------------------------------------
    # 手动触发告警（用于外部事件驱动）
    # -----------------------------------------------------------------------

    def trigger_alert(
        self,
        rule_id: str,
        value: Optional[float] = None,
        labels: Optional[Dict[str, str]] = None,
        annotations: Optional[Dict[str, str]] = None,
        summary: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[AlertEvent]:
        """手动触发告警（用于外部事件驱动的规则）

        Args:
            rule_id: 规则 ID
            value: 当前值
            labels: 额外标签
            annotations: 额外注解
            summary: 自定义摘要（覆盖规则名称）
            description: 自定义描述（覆盖规则描述）

        Returns:
            告警事件（如果是新触发的）
        """
        rule = self.get_rule(rule_id)
        if not rule:
            # 规则不存在，创建一个临时规则
            rule = AlertRule(
                rule_id=rule_id,
                name=summary or rule_id,
                description=description or f"Custom alert: {rule_id}",
                severity=AlertSeverity.WARNING,
                condition=lambda ctx: (True, None, {}),
                is_builtin=False,
                enabled=True,
            )
            if labels:
                rule.labels.update(labels)

        # 使用模拟上下文触发
        context = self._build_context()
        details: Dict[str, Any] = {}
        if value is not None:
            details["value"] = value

        # 临时修改规则的 condition 使其触发
        original_condition = rule.condition

        def _always_trigger(ctx):
            return True, value, details

        rule.condition = _always_trigger

        was_new = self._fire_alert(rule, value, details, context)

        # 恢复原条件
        rule.condition = original_condition

        # 返回告警事件
        with self._active_alerts_lock:
            alert = self._active_alerts.get(rule_id)
            if alert and (summary or description or labels or annotations):
                if summary:
                    alert.summary = summary
                if description:
                    alert.description = description
                if labels:
                    alert.labels.update(labels)
                if annotations:
                    alert.annotations.update(annotations)
            return alert

    # -----------------------------------------------------------------------
    # 告警状态管理
    # -----------------------------------------------------------------------

    def get_active_alerts(
        self,
        severity: Optional[AlertSeverity] = None,
        category: Optional[str] = None,
    ) -> List[AlertEvent]:
        """获取活跃告警

        Args:
            severity: 按级别过滤
            category: 按类别过滤

        Returns:
            活跃告警列表
        """
        with self._active_alerts_lock:
            alerts = list(self._active_alerts.values())

        if severity:
            alerts = [a for a in alerts if a.severity == severity]

        if category:
            alerts = [a for a in alerts if a.labels.get("category") == category]

        return sorted(alerts, key=lambda a: (a.severity.numeric_level, a.started_at), reverse=True)

    def get_alert(self, alert_id: str) -> Optional[AlertEvent]:
        """获取单个告警"""
        with self._active_alerts_lock:
            # 先在活跃告警中找
            for alert in self._active_alerts.values():
                if alert.id == alert_id:
                    return alert

        # 在历史记录中找
        with self._history_lock:
            for record in reversed(self._history):
                if record["id"] == alert_id:
                    # 从字典重建 AlertEvent
                    return self._alert_from_dict(record)

        return None

    def acknowledge_alert(
        self,
        alert_id: str,
        acknowledged_by: str = "system",
    ) -> bool:
        """确认告警

        Args:
            alert_id: 告警 ID
            acknowledged_by: 确认人

        Returns:
            是否成功
        """
        with self._active_alerts_lock:
            for alert in self._active_alerts.values():
                if alert.id == alert_id:
                    alert.state = AlertState.ACKNOWLEDGED
                    alert.acknowledged_at = time.time()
                    alert.acknowledged_by = acknowledged_by
                    alert.last_updated_at = time.time()
                    return True

        return False

    def silence_alert(
        self,
        alert_id: str,
        duration_seconds: int = 3600,
        silenced_by: str = "system",
        reason: str = "",
    ) -> bool:
        """静默告警

        Args:
            alert_id: 告警 ID
            duration_seconds: 静默时长（秒）
            silenced_by: 操作人
            reason: 静默原因

        Returns:
            是否成功
        """
        with self._active_alerts_lock:
            for alert in self._active_alerts.values():
                if alert.id == alert_id:
                    alert.state = AlertState.SILENCED
                    alert.silenced_until = time.time() + duration_seconds
                    alert.silenced_by = silenced_by
                    alert.silence_reason = reason
                    alert.last_updated_at = time.time()
                    return True

        return False

    def resolve_alert(
        self,
        alert_id: str,
        resolved_by: str = "system",
        reason: str = "",
    ) -> bool:
        """手动解决告警

        Args:
            alert_id: 告警 ID
            resolved_by: 解决人
            reason: 解决原因

        Returns:
            是否成功
        """
        with self._active_alerts_lock:
            alert = None
            alert_key = None
            for key, a in self._active_alerts.items():
                if a.id == alert_id:
                    alert = a
                    alert_key = key
                    break

            if not alert:
                return False

            alert.state = AlertState.RESOLVED
            alert.resolved_at = time.time()
            alert.last_updated_at = time.time()
            if reason:
                alert.annotations["resolve_reason"] = reason
                alert.annotations["resolved_by"] = resolved_by

            # 从活跃告警中移除
            del self._active_alerts[alert_key]
            self._total_resolved += 1

            # 加入历史
            with self._history_lock:
                self._history.append(alert.to_dict())

        # 发送恢复通知
        rule = self.get_rule(alert.rule_id)
        if rule:
            self._send_resolved_notifications(alert, rule)

        return True

    def get_history(
        self,
        limit: int = 100,
        severity: Optional[AlertSeverity] = None,
        category: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """获取告警历史

        Args:
            limit: 返回条数上限
            severity: 按级别过滤
            category: 按类别过滤
            start_time: 开始时间戳
            end_time: 结束时间戳

        Returns:
            告警历史记录列表（按时间倒序）
        """
        with self._history_lock:
            records = list(reversed(self._history))

        # 过滤
        if severity:
            records = [r for r in records if r["severity"] == severity.value]

        if category:
            records = [r for r in records if r.get("labels", {}).get("category") == category]

        if start_time:
            records = [r for r in records if r["started_at"] >= start_time]

        if end_time:
            records = [r for r in records if r["started_at"] <= end_time]

        return records[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """获取告警统计信息"""
        active = self.get_active_alerts()

        by_severity = {
            "info": 0,
            "warning": 0,
            "critical": 0,
        }
        by_state = {
            "firing": 0,
            "acknowledged": 0,
            "silenced": 0,
            "resolved": 0,
        }
        by_category: Dict[str, int] = {}

        for alert in active:
            by_severity[alert.severity.value] += 1
            by_state[alert.state.value] += 1
            cat = alert.labels.get("category", "unknown")
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            "total_fired": self._total_fired,
            "total_resolved": self._total_resolved,
            "active_count": len(active),
            "by_severity": by_severity,
            "by_state": by_state,
            "by_category": by_category,
            "history_size": len(self._history),
            "rules_count": len(self._rules),
            "service_name": self.service_name,
        }

    # -----------------------------------------------------------------------
    # 后台线程
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """启动告警检查后台线程"""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        self._check_thread = threading.Thread(
            target=self._check_loop,
            daemon=True,
            name="alert-engine",
        )
        self._check_thread.start()

    def stop(self) -> None:
        """停止告警检查"""
        self._running = False
        self._stop_event.set()
        if self._check_thread:
            self._check_thread.join(timeout=5)
            self._check_thread = None

    def _check_loop(self) -> None:
        """后台检查循环"""
        # 启动时延迟 2 秒，避免启动风暴
        self._stop_event.wait(2.0)

        while self._running and not self._stop_event.is_set():
            try:
                self.check_all_rules()
            except Exception:
                pass

            # 每 10 秒检查一次（实际执行频率由各规则的 check_interval 控制）
            self._stop_event.wait(10)

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running

    # -----------------------------------------------------------------------
    # 健康检查集成
    # -----------------------------------------------------------------------

    def get_health_impact(self) -> Dict[str, Any]:
        """获取告警对健康检查的影响

        Returns:
            {
                "status": "healthy" | "degraded" | "unhealthy",
                "active_alerts_count": N,
                "critical_alerts_count": N,
                "warning_alerts_count": N,
                "top_alerts": [...]
            }
        """
        active = self.get_active_alerts()
        critical_count = sum(1 for a in active if a.severity == AlertSeverity.CRITICAL)
        warning_count = sum(1 for a in active if a.severity == AlertSeverity.WARNING)

        if critical_count > 0:
            status = "degraded"  # CRITICAL 告警导致 degraded 状态
        elif warning_count > 0:
            status = "degraded"
        else:
            status = "healthy"

        top_alerts = [
            {
                "id": a.id,
                "severity": a.severity.value,
                "summary": a.summary,
                "started_at": a.started_at,
            }
            for a in active[:5]
        ]

        return {
            "status": status,
            "active_alerts_count": len(active),
            "critical_alerts_count": critical_count,
            "warning_alerts_count": warning_count,
            "top_alerts": top_alerts,
        }

    # -----------------------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------------------

    def _alert_from_dict(self, data: Dict[str, Any]) -> AlertEvent:
        """从字典重建 AlertEvent"""
        return AlertEvent(
            id=data.get("id", ""),
            rule_id=data.get("rule_id", ""),
            rule_name=data.get("rule_name", ""),
            severity=AlertSeverity.from_str(data.get("severity", "warning")),
            state=AlertState(data.get("state", "firing")),
            summary=data.get("summary", ""),
            description=data.get("description", ""),
            labels=data.get("labels", {}),
            annotations=data.get("annotations", {}),
            value=data.get("value"),
            threshold=data.get("threshold"),
            started_at=data.get("started_at", time.time()),
            last_updated_at=data.get("last_updated_at", time.time()),
            resolved_at=data.get("resolved_at"),
            acknowledged_at=data.get("acknowledged_at"),
            acknowledged_by=data.get("acknowledged_by"),
            silenced_until=data.get("silenced_until"),
            silenced_by=data.get("silenced_by"),
            silence_reason=data.get("silence_reason"),
            firing_count=data.get("firing_count", 1),
        )


# ============================================================================
# 辅助函数
# ============================================================================

def _get_env() -> str:
    """获取当前运行环境"""
    import os
    return os.environ.get("YUNXI_ENV", os.environ.get("ENV", "development")).lower()


def _get_webhook_url() -> str:
    """从环境变量获取告警 Webhook URL"""
    import os
    return os.environ.get("ALERT_WEBHOOK_URL", os.environ.get("YUNXI_ALERT_WEBHOOK", ""))


# ============================================================================
# 全局告警引擎（单例）
# ============================================================================

_global_alert_engine: Optional[AlertEngine] = None
_global_engine_lock = threading.Lock()


def get_alert_engine(
    service_name: str = "yunxi",
    history_limit: int = 1000,
    auto_start: bool = True,
) -> AlertEngine:
    """获取全局告警引擎（单例模式，线程安全）

    Args:
        service_name: 服务名称（首次调用时设置）
        history_limit: 历史告警最大保留数量
        auto_start: 是否自动启动后台检查线程

    Returns:
        AlertEngine 实例
    """
    global _global_alert_engine
    if _global_alert_engine is None:
        with _global_engine_lock:
            if _global_alert_engine is None:
                _global_alert_engine = AlertEngine(
                    service_name=service_name,
                    history_limit=history_limit,
                    auto_start=auto_start,
                )
    return _global_alert_engine


def reset_alert_engine() -> None:
    """重置全局告警引擎（主要用于测试）"""
    global _global_alert_engine
    with _global_engine_lock:
        if _global_alert_engine:
            _global_alert_engine.stop()
        _global_alert_engine = None


# ============================================================================
# FastAPI 告警路由
# ============================================================================

def create_alert_router(
    engine: Optional[AlertEngine] = None,
    prefix: str = "",
    include_in_schema: bool = True,
) -> Any:
    """创建 FastAPI 告警路由

    提供完整的告警管理 API：
    - GET /alerts - 获取当前活跃告警
    - GET /alerts/history - 获取告警历史
    - POST /alerts/{id}/acknowledge - 确认告警
    - POST /alerts/{id}/silence - 静默告警
    - POST /alerts/{id}/resolve - 解决告警
    - GET /alerts/rules - 获取告警规则列表
    - POST /alerts/rules - 创建自定义规则
    - PUT /alerts/rules/{id} - 修改规则
    - DELETE /alerts/rules/{id} - 删除规则
    - GET /alerts/stats - 告警统计

    Args:
        engine: AlertEngine 实例，为空则使用全局实例
        prefix: 路由前缀
        include_in_schema: 是否在 OpenAPI 文档中显示

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, Query, HTTPException
    from pydantic import BaseModel, Field
    from typing import Optional as Opt

    if engine is None:
        engine = get_alert_engine()

    router = APIRouter(prefix=prefix, tags=["alerts"], include_in_schema=include_in_schema)

    # ---- 请求体模型 ----

    class AlertRuleCreate(BaseModel):
        rule_id: str = Field(..., description="规则唯一标识")
        name: str = Field(..., description="规则名称")
        description: str = Field("", description="规则描述")
        severity: str = Field("warning", description="告警级别: info/warning/critical")
        condition: str = Field(..., description="告警条件表达式")
        check_interval: int = Field(60, description="检查间隔（秒）")
        silence_period: int = Field(300, description="静默期（秒）")
        labels: Dict[str, str] = Field(default_factory=dict, description="标签")
        enabled: bool = Field(True, description="是否启用")

    class AlertRuleUpdate(BaseModel):
        name: Opt[str] = Field(None, description="规则名称")
        description: Opt[str] = Field(None, description="规则描述")
        severity: Opt[str] = Field(None, description="告警级别")
        condition: Opt[str] = Field(None, description="告警条件表达式")
        check_interval: Opt[int] = Field(None, description="检查间隔（秒）")
        silence_period: Opt[int] = Field(None, description="静默期（秒）")
        enabled: Opt[bool] = Field(None, description="是否启用")
        labels: Opt[Dict[str, str]] = Field(None, description="标签")

    class AcknowledgeRequest(BaseModel):
        acknowledged_by: str = Field("system", description="确认人")

    class SilenceRequest(BaseModel):
        duration_seconds: int = Field(3600, description="静默时长（秒）")
        silenced_by: str = Field("system", description="操作人")
        reason: str = Field("", description="静默原因")

    class ResolveRequest(BaseModel):
        resolved_by: str = Field("system", description="解决人")
        reason: str = Field("", description="解决原因")

    # ---- 告警查询 ----

    @router.get("/alerts", summary="获取活跃告警列表")
    async def get_active_alerts(
        severity: Opt[str] = Query(None, description="按级别过滤: info/warning/critical"),
        category: Opt[str] = Query(None, description="按类别过滤: system/service/performance/security"),
        limit: int = Query(100, description="返回条数上限"),
    ):
        sev = AlertSeverity.from_str(severity) if severity else None
        alerts = engine.get_active_alerts(severity=sev, category=category)
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "total": len(alerts),
                "items": [a.to_dict() for a in alerts[:limit]],
            },
        }

    @router.get("/alerts/history", summary="获取告警历史")
    async def get_alert_history(
        severity: Opt[str] = Query(None, description="按级别过滤"),
        category: Opt[str] = Query(None, description="按类别过滤"),
        limit: int = Query(100, description="返回条数上限"),
    ):
        sev = AlertSeverity.from_str(severity) if severity else None
        records = engine.get_history(limit=limit, severity=sev, category=category)
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "total": len(records),
                "items": records,
            },
        }

    @router.get("/alerts/stats", summary="告警统计")
    async def get_alert_stats():
        stats = engine.get_stats()
        return {
            "code": 0,
            "message": "ok",
            "data": stats,
        }

    @router.get("/alerts/{alert_id}", summary="获取告警详情")
    async def get_alert_detail(alert_id: str):
        alert = engine.get_alert(alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="告警不存在")
        return {
            "code": 0,
            "message": "ok",
            "data": alert.to_dict(),
        }

    # ---- 告警操作 ----

    @router.post("/alerts/{alert_id}/acknowledge", summary="确认告警")
    async def acknowledge_alert(alert_id: str, body: AcknowledgeRequest):
        success = engine.acknowledge_alert(alert_id, acknowledged_by=body.acknowledged_by)
        if not success:
            raise HTTPException(status_code=404, detail="告警不存在")
        alert = engine.get_alert(alert_id)
        return {
            "code": 0,
            "message": "告警已确认",
            "data": alert.to_dict() if alert else None,
        }

    @router.post("/alerts/{alert_id}/silence", summary="静默告警")
    async def silence_alert(alert_id: str, body: SilenceRequest):
        success = engine.silence_alert(
            alert_id,
            duration_seconds=body.duration_seconds,
            silenced_by=body.silenced_by,
            reason=body.reason,
        )
        if not success:
            raise HTTPException(status_code=404, detail="告警不存在")
        alert = engine.get_alert(alert_id)
        return {
            "code": 0,
            "message": "告警已静默",
            "data": alert.to_dict() if alert else None,
        }

    @router.post("/alerts/{alert_id}/resolve", summary="解决告警")
    async def resolve_alert(alert_id: str, body: ResolveRequest):
        success = engine.resolve_alert(
            alert_id,
            resolved_by=body.resolved_by,
            reason=body.reason,
        )
        if not success:
            raise HTTPException(status_code=404, detail="告警不存在")
        return {
            "code": 0,
            "message": "告警已解决",
        }

    # ---- 规则管理 ----

    @router.get("/alerts/rules", summary="获取告警规则列表")
    async def get_alert_rules(
        category: Opt[str] = Query(None, description="按类别过滤"),
        severity: Opt[str] = Query(None, description="按级别过滤"),
        enabled_only: bool = Query(False, description="只返回启用的规则"),
    ):
        sev = AlertSeverity.from_str(severity) if severity else None
        rules = engine.list_rules(
            category=category,
            severity=sev,
            enabled_only=enabled_only,
        )
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "total": len(rules),
                "items": [r.to_dict() for r in rules],
            },
        }

    @router.post("/alerts/rules", summary="创建自定义告警规则")
    async def create_alert_rule(rule_data: AlertRuleCreate):
        existing = engine.get_rule(rule_data.rule_id)
        if existing:
            raise HTTPException(status_code=400, detail="规则 ID 已存在")

        rule = AlertRule(
            rule_id=rule_data.rule_id,
            name=rule_data.name,
            description=rule_data.description,
            severity=AlertSeverity.from_str(rule_data.severity),
            condition=rule_data.condition,
            check_interval=rule_data.check_interval,
            silence_period=rule_data.silence_period,
            labels=rule_data.labels,
            enabled=rule_data.enabled,
            is_builtin=False,
        )
        engine.register_rule(rule)
        return {
            "code": 0,
            "message": "规则创建成功",
            "data": rule.to_dict(),
        }

    @router.put("/alerts/rules/{rule_id}", summary="修改告警规则")
    async def update_alert_rule(rule_id: str, rule_data: AlertRuleUpdate):
        rule = engine.get_rule(rule_id)
        if not rule:
            raise HTTPException(status_code=404, detail="规则不存在")

        updates: Dict[str, Any] = {}
        if rule_data.name is not None:
            updates["name"] = rule_data.name
        if rule_data.description is not None:
            updates["description"] = rule_data.description
        if rule_data.severity is not None:
            updates["severity"] = AlertSeverity.from_str(rule_data.severity)
        if rule_data.condition is not None:
            updates["condition"] = rule_data.condition
        if rule_data.check_interval is not None:
            updates["check_interval"] = rule_data.check_interval
        if rule_data.silence_period is not None:
            updates["silence_period"] = rule_data.silence_period
        if rule_data.enabled is not None:
            updates["enabled"] = rule_data.enabled
        if rule_data.labels is not None:
            updates["labels"] = rule_data.labels

        engine.update_rule(rule_id, **updates)
        return {
            "code": 0,
            "message": "规则更新成功",
            "data": rule.to_dict(),
        }

    @router.delete("/alerts/rules/{rule_id}", summary="删除告警规则")
    async def delete_alert_rule(rule_id: str):
        rule = engine.get_rule(rule_id)
        if not rule:
            raise HTTPException(status_code=404, detail="规则不存在")
        if rule.is_builtin:
            raise HTTPException(status_code=400, detail="内置规则不可删除，可禁用")

        engine.unregister_rule(rule_id)
        return {
            "code": 0,
            "message": "规则删除成功",
        }

    # ---- 通知渠道 ----

    @router.get("/alerts/channels", summary="获取通知渠道列表")
    async def get_notification_channels():
        channels = engine.notifier_manager.list_channels()
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "total": len(channels),
                "items": channels,
            },
        }

    return router
