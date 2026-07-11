"""M11 MCP Bus - 告警服务.

监控系统运行状态，检测异常并生成告警。
支持的告警规则：服务器离线、调用成功率低、响应超时、API Key 快过期。
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, List, Optional


# ============================================================
# 告警级别
# ============================================================

class AlertSeverity:
    """告警级别."""

    INFO = "info"        # 信息
    WARNING = "warning"  # 警告
    CRITICAL = "critical"  # 严重


# ============================================================
# 告警规则类型
# ============================================================

class AlertRuleType:
    """告警规则类型."""

    SERVER_OFFLINE = "server_offline"              # 服务器离线
    LOW_SUCCESS_RATE = "low_success_rate"          # 调用成功率低
    HIGH_RESPONSE_TIME = "high_response_time"      # 响应时间过长
    API_KEY_EXPIRING = "api_key_expiring"          # API Key 即将过期


# ============================================================
# 告警对象
# ============================================================

class Alert:
    """告警对象.

    表示一条活跃的告警记录。
    """

    def __init__(
        self,
        rule_type: str,
        severity: str,
        title: str,
        description: str = "",
        resource: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初始化告警.

        Args:
            rule_type: 告警规则类型
            severity: 告警级别
            title: 告警标题
            description: 告警详情描述
            resource: 关联资源标识
            metadata: 附加元数据
        """
        self.id: str = str(uuid.uuid4())[:12]
        self.rule_type = rule_type
        self.severity = severity
        self.title = title
        self.description = description
        self.resource = resource
        self.metadata = metadata or {}
        self.created_at: float = time.time()
        self.acknowledged: bool = False
        self.acknowledged_at: Optional[float] = None
        self.acknowledged_by: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典.

        Returns:
            字典形式的告警信息
        """
        return {
            "id": self.id,
            "rule_type": self.rule_type,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "resource": self.resource,
            "metadata": self.metadata,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "acknowledged": self.acknowledged,
            "acknowledged_at": (
                datetime.fromtimestamp(self.acknowledged_at).isoformat()
                if self.acknowledged_at else None
            ),
            "acknowledged_by": self.acknowledged_by,
        }


# ============================================================
# 告警服务
# ============================================================

class AlertService:
    """告警服务.

    定期检查系统状态，根据预设规则生成告警。
    支持告警确认、获取活跃告警列表等功能。

    告警规则：
    - 服务器离线：超过心跳超时时间未上报心跳
    - 调用成功率低：最近一段时间成功率低于阈值
    - 响应时间过长：平均响应时间超过阈值
    - API Key 快过期：即将在指定天数内过期
    """

    def __init__(self) -> None:
        """初始化告警服务."""
        self._alerts: Dict[str, Alert] = {}
        self._lock = Lock()
        self._last_check: float = 0.0
        self._check_interval: int = 60  # 检查间隔（秒）

        # 告警阈值配置
        self._success_rate_threshold: float = 90.0  # 成功率阈值（%）
        self._response_time_threshold: int = 5000   # 响应时间阈值（ms）
        self._api_key_expiry_days: int = 7          # API Key 过期提醒天数
        self._stats_window_minutes: int = 10        # 统计窗口（分钟）

    # --------------------------------------------------------
    # 配置方法
    # --------------------------------------------------------

    def set_success_rate_threshold(self, threshold: float) -> None:
        """设置成功率告警阈值.

        Args:
            threshold: 成功率阈值（百分比），如 90.0 表示 90%
        """
        self._success_rate_threshold = threshold

    def set_response_time_threshold(self, threshold_ms: int) -> None:
        """设置响应时间告警阈值.

        Args:
            threshold_ms: 响应时间阈值（毫秒）
        """
        self._response_time_threshold = threshold_ms

    def set_api_key_expiry_days(self, days: int) -> None:
        """设置 API Key 过期提醒天数.

        Args:
            days: 提前多少天提醒
        """
        self._api_key_expiry_days = days

    # --------------------------------------------------------
    # 告警检查
    # --------------------------------------------------------

    def check_alerts(self) -> List[Alert]:
        """执行所有告警规则检查.

        依次检查：服务器离线、低成功率、高响应时间、API Key 过期。
        新生成的告警会加入活跃告警列表。

        Returns:
            本次检查新发现的告警列表
        """
        new_alerts: List[Alert] = []

        with self._lock:
            # 检查服务器离线
            offline_alerts = self._check_server_offline()
            new_alerts.extend(offline_alerts)

            # 检查调用成功率
            success_alerts = self._check_success_rate()
            new_alerts.extend(success_alerts)

            # 检查响应时间
            response_alerts = self._check_response_time()
            new_alerts.extend(response_alerts)

            # 检查 API Key 过期
            expiry_alerts = self._check_api_key_expiry()
            new_alerts.extend(expiry_alerts)

            self._last_check = time.time()

        return new_alerts

    def _check_server_offline(self) -> List[Alert]:
        """检查离线服务器并生成告警.

        Returns:
            新生成的服务器离线告警列表
        """
        from ..config import get_settings
        from ..db import get_session
        from ..models_db import McpServer

        new_alerts: List[Alert] = []
        settings = get_settings()

        db = get_session()
        try:
            offline_servers = (
                db.query(McpServer).filter(McpServer.status == "offline").all()
            )

            for server in offline_servers:
                # 用规则类型 + 服务器 ID 作为去重键
                dedup_key = f"{AlertRuleType.SERVER_OFFLINE}:{server.id}"

                # 检查是否已有同类型告警
                existing = self._find_alert_by_resource(dedup_key)
                if existing and not existing.acknowledged:
                    continue

                # 判断是否真的超时（最后心跳超过阈值）
                timeout = timedelta(seconds=settings.heartbeat_timeout * 2)
                if server.last_heartbeat:
                    offline_duration = datetime.utcnow() - server.last_heartbeat
                    if offline_duration < timeout:
                        # 还没到严重超时时间，不告警
                        continue

                alert = Alert(
                    rule_type=AlertRuleType.SERVER_OFFLINE,
                    severity=AlertSeverity.CRITICAL,
                    title=f"服务器离线: {server.name}",
                    description=(
                        f"服务器 {server.name} 已离线，"
                        f"最后心跳: {server.last_heartbeat.isoformat() if server.last_heartbeat else '从未心跳'}"
                    ),
                    resource=dedup_key,
                    metadata={
                        "server_id": server.id,
                        "server_name": server.name,
                        "last_heartbeat": (
                            server.last_heartbeat.isoformat() if server.last_heartbeat else None
                        ),
                    },
                )
                self._alerts[alert.id] = alert
                new_alerts.append(alert)

            return new_alerts
        except Exception:
            return new_alerts
        finally:
            db.close()

    def _check_success_rate(self) -> List[Alert]:
        """检查调用成功率是否低于阈值.

        Returns:
            新生成的低成功率告警列表
        """
        new_alerts: List[Alert] = []

        try:
            from ..services.monitor import mcp_monitor

            stats = mcp_monitor.get_stats()
            total_calls = stats.get("total_calls", 0)
            success_rate = stats.get("success_rate", 100.0)

            # 至少要有一定调用量才告警，避免误报
            if total_calls < 10:
                return new_alerts

            if success_rate < self._success_rate_threshold:
                dedup_key = AlertRuleType.LOW_SUCCESS_RATE

                existing = self._find_alert_by_resource(dedup_key)
                if existing and not existing.acknowledged:
                    return new_alerts

                alert = Alert(
                    rule_type=AlertRuleType.LOW_SUCCESS_RATE,
                    severity=AlertSeverity.WARNING,
                    title="调用成功率过低",
                    description=(
                        f"最近调用成功率为 {success_rate}%，"
                        f"低于阈值 {self._success_rate_threshold}%。"
                        f"总调用数: {total_calls}，"
                        f"失败数: {stats.get('failed_calls', 0)}"
                    ),
                    resource=dedup_key,
                    metadata={
                        "success_rate": success_rate,
                        "threshold": self._success_rate_threshold,
                        "total_calls": total_calls,
                        "failed_calls": stats.get("failed_calls", 0),
                    },
                )
                self._alerts[alert.id] = alert
                new_alerts.append(alert)

            return new_alerts
        except Exception:
            return new_alerts

    def _check_response_time(self) -> List[Alert]:
        """检查平均响应时间是否超过阈值.

        Returns:
            新生成的高响应时间告警列表
        """
        new_alerts: List[Alert] = []

        try:
            from ..services.monitor import mcp_monitor

            stats = mcp_monitor.get_stats()
            avg_duration = stats.get("avg_duration_ms", 0)
            total_calls = stats.get("total_calls", 0)

            if total_calls < 10:
                return new_alerts

            if avg_duration > self._response_time_threshold:
                dedup_key = AlertRuleType.HIGH_RESPONSE_TIME

                existing = self._find_alert_by_resource(dedup_key)
                if existing and not existing.acknowledged:
                    return new_alerts

                alert = Alert(
                    rule_type=AlertRuleType.HIGH_RESPONSE_TIME,
                    severity=AlertSeverity.WARNING,
                    title="响应时间过长",
                    description=(
                        f"平均响应时间为 {avg_duration}ms，"
                        f"超过阈值 {self._response_time_threshold}ms"
                    ),
                    resource=dedup_key,
                    metadata={
                        "avg_duration_ms": avg_duration,
                        "threshold_ms": self._response_time_threshold,
                        "total_calls": total_calls,
                    },
                )
                self._alerts[alert.id] = alert
                new_alerts.append(alert)

            return new_alerts
        except Exception:
            return new_alerts

    def _check_api_key_expiry(self) -> List[Alert]:
        """检查即将过期的 API Key.

        Returns:
            新生成的 API Key 过期告警列表
        """
        new_alerts: List[Alert] = []

        try:
            from ..db import get_session
            from ..models_db import ApiKey

            db = get_session()
            try:
                cutoff = datetime.utcnow() + timedelta(days=self._api_key_expiry_days)

                expiring_keys = (
                    db.query(ApiKey)
                    .filter(
                        ApiKey.expires_at.isnot(None),
                        ApiKey.expires_at <= cutoff,
                        ApiKey.expires_at > datetime.utcnow(),
                    )
                    .all()
                )

                for key in expiring_keys:
                    dedup_key = f"{AlertRuleType.API_KEY_EXPIRING}:{key.id}"

                    existing = self._find_alert_by_resource(dedup_key)
                    if existing and not existing.acknowledged:
                        continue

                    days_left = (key.expires_at - datetime.utcnow()).days if key.expires_at else 0

                    alert = Alert(
                        rule_type=AlertRuleType.API_KEY_EXPIRING,
                        severity=AlertSeverity.INFO,
                        title=f"API Key 即将过期: {key.name}",
                        description=(
                            f"API Key '{key.name}' 将在 {days_left} 天后过期"
                            f"（过期时间: {key.expires_at.isoformat() if key.expires_at else '未知'}）"
                        ),
                        resource=dedup_key,
                        metadata={
                            "key_id": key.id,
                            "key_name": key.name,
                            "expires_at": key.expires_at.isoformat() if key.expires_at else None,
                            "days_left": days_left,
                        },
                    )
                    self._alerts[alert.id] = alert
                    new_alerts.append(alert)

                return new_alerts
            finally:
                db.close()
        except Exception:
            return new_alerts

    def _find_alert_by_resource(self, resource: str) -> Optional[Alert]:
        """按资源标识查找活跃告警.

        Args:
            resource: 资源标识

        Returns:
            告警对象，未找到返回 None
        """
        for alert in self._alerts.values():
            if alert.resource == resource and not alert.acknowledged:
                return alert
        return None

    # --------------------------------------------------------
    # 告警管理
    # --------------------------------------------------------

    def get_active_alerts(
        self,
        severity: Optional[str] = None,
        rule_type: Optional[str] = None,
        include_acknowledged: bool = False,
    ) -> List[Alert]:
        """获取活跃告警列表.

        Args:
            severity: 按级别过滤
            rule_type: 按规则类型过滤
            include_acknowledged: 是否包含已确认的告警

        Returns:
            告警列表（按创建时间倒序）
        """
        with self._lock:
            alerts = list(self._alerts.values())

            if not include_acknowledged:
                alerts = [a for a in alerts if not a.acknowledged]

            if severity:
                alerts = [a for a in alerts if a.severity == severity]

            if rule_type:
                alerts = [a for a in alerts if a.rule_type == rule_type]

            alerts.sort(key=lambda a: a.created_at, reverse=True)
            return alerts

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        """按 ID 获取告警.

        Args:
            alert_id: 告警 ID

        Returns:
            告警对象，不存在返回 None
        """
        with self._lock:
            return self._alerts.get(alert_id)

    def ack_alert(self, alert_id: str, acknowledged_by: str = "system") -> bool:
        """确认告警.

        将告警标记为已确认，不再出现在活跃告警列表中。

        Args:
            alert_id: 告警 ID
            acknowledged_by: 确认人

        Returns:
            是否确认成功
        """
        with self._lock:
            alert = self._alerts.get(alert_id)
            if not alert:
                return False

            alert.acknowledged = True
            alert.acknowledged_at = time.time()
            alert.acknowledged_by = acknowledged_by
            return True

    def clear_resolved_alerts(self) -> int:
        """清理已确认且超过保留时间的告警.

        Returns:
            清理的告警数量
        """
        with self._lock:
            cutoff = time.time() - 24 * 3600  # 保留 24 小时
            to_remove = [
                alert_id
                for alert_id, alert in self._alerts.items()
                if alert.acknowledged and alert.acknowledged_at and alert.acknowledged_at < cutoff
            ]
            for alert_id in to_remove:
                del self._alerts[alert_id]
            return len(to_remove)

    def get_alert_stats(self) -> Dict[str, Any]:
        """获取告警统计信息.

        Returns:
            统计字典
        """
        with self._lock:
            active = [a for a in self._alerts.values() if not a.acknowledged]
            critical = sum(1 for a in active if a.severity == AlertSeverity.CRITICAL)
            warning = sum(1 for a in active if a.severity == AlertSeverity.WARNING)
            info = sum(1 for a in active if a.severity == AlertSeverity.INFO)

            return {
                "total_active": len(active),
                "critical": critical,
                "warning": warning,
                "info": info,
                "total_alerts": len(self._alerts),
                "last_check": (
                    datetime.fromtimestamp(self._last_check).isoformat()
                    if self._last_check > 0 else None
                ),
            }


# ============================================================
# 单例实例
# ============================================================

alert_service = AlertService()
