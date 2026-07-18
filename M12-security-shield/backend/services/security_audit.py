"""
云汐 M12 安全盾 - 安全审计增强服务

在原有审计服务基础上增强，提供：
1. 审计事件分类（认证/授权/数据访问/配置变更/系统事件）
2. 审计日志格式增强（事件ID/时间戳/主体/客体/动作/结果/详情/trace_id）
3. 异常行为检测
   - 登录异常（异常时间/异常地点/暴力破解/多次失败后成功）
   - 操作异常（大量数据导出/权限提升/敏感操作频率/非工作时间）
4. 告警机制
   - 实时告警（高危事件）
   - 每日安全报告
   - 告警分级
   - 通知渠道
"""

import time
import uuid
import hashlib
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

DAY_SECONDS = 86400
MAX_ALERTS = 5000
MAX_AUDIT_LOGS = 10000


# ===========================================================================
# 审计事件分类
# ===========================================================================

# 事件分类
EVENT_CATEGORY_AUTH = "authentication"      # 认证事件
EVENT_CATEGORY_AUTHZ = "authorization"     # 授权事件
EVENT_CATEGORY_DATA = "data_access"        # 数据访问
EVENT_CATEGORY_CONFIG = "config_change"    # 配置变更
EVENT_CATEGORY_SYSTEM = "system_event"     # 系统事件

# 严重级别
SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_INFO = "info"

# 动作类型
ACTION_LOGIN = "login"
ACTION_LOGOUT = "logout"
ACTION_LOGIN_FAILED = "login_failed"
ACTION_LOGIN_LOCKED = "login_locked"
ACTION_PERMISSION_CHANGE = "permission_change"
ACTION_ROLE_CHANGE = "role_change"
ACTION_DATA_VIEW = "data_view"
ACTION_DATA_MODIFY = "data_modify"
ACTION_DATA_DELETE = "data_delete"
ACTION_DATA_EXPORT = "data_export"
ACTION_CONFIG_CHANGE = "config_change"
ACTION_SYSTEM_START = "system_start"
ACTION_SYSTEM_SHUTDOWN = "system_shutdown"
ACTION_SYSTEM_UPGRADE = "system_upgrade"

# 告警类型
ALERT_TYPE_BRUTE_FORCE = "brute_force"
ALERT_TYPE_UNUSUAL_LOGIN_TIME = "unusual_login_time"
ALERT_TYPE_UNUSUAL_LOCATION = "unusual_location"
ALERT_TYPE_MULTIPLE_FAILURE_THEN_SUCCESS = "multiple_failure_then_success"
ALERT_TYPE_MASS_DATA_EXPORT = "mass_data_export"
ALERT_TYPE_PRIVILEGE_ESCALATION = "privilege_escalation"
ALERT_TYPE_SENSITIVE_OP_FREQUENCY = "sensitive_op_frequency"
ALERT_TYPE_OFF_HOURS_OPERATION = "off_hours_operation"
ALERT_TYPE_WAF_ATTACK = "waf_attack"


# ===========================================================================
# 告警级别
# ===========================================================================

ALERT_SEVERITY_MAP = {
    ALERT_TYPE_BRUTE_FORCE: SEVERITY_CRITICAL,
    ALERT_TYPE_MULTIPLE_FAILURE_THEN_SUCCESS: SEVERITY_HIGH,
    ALERT_TYPE_PRIVILEGE_ESCALATION: SEVERITY_HIGH,
    ALERT_TYPE_MASS_DATA_EXPORT: SEVERITY_HIGH,
    ALERT_TYPE_UNUSUAL_LOGIN_TIME: SEVERITY_MEDIUM,
    ALERT_TYPE_UNUSUAL_LOCATION: SEVERITY_MEDIUM,
    ALERT_TYPE_SENSITIVE_OP_FREQUENCY: SEVERITY_MEDIUM,
    ALERT_TYPE_OFF_HOURS_OPERATION: SEVERITY_LOW,
    ALERT_TYPE_WAF_ATTACK: SEVERITY_HIGH,
}


# ===========================================================================
# 告警条目
# ===========================================================================

class SecurityAlert:
    """安全告警"""

    def __init__(
        self,
        alert_type: str,
        severity: str,
        title: str,
        description: str,
        source_ip: str = "",
        user_id: str = "",
        username: str = "",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.alert_id = f"ALERT-{int(time.time())}-{hashlib.md5(str(time.time() + id(self)).encode()).hexdigest()[:8]}"
        self.alert_type = alert_type
        self.severity = severity
        self.title = title
        self.description = description
        self.source_ip = source_ip
        self.user_id = user_id
        self.username = username
        self.details = details or {}
        self.status = "active"  # active/acknowledged/resolved
        self.acknowledged_by = ""
        self.acknowledged_at = None
        self.resolved_by = ""
        self.resolved_at = None
        self.created_at = time.time()
        self.created_at_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "source_ip": self.source_ip,
            "user_id": self.user_id,
            "username": self.username,
            "details": self.details,
            "status": self.status,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at,
            "created_at": self.created_at_str,
            "created_at_unix": self.created_at,
        }


# ===========================================================================
# 增强版审计服务
# ===========================================================================

class SecurityAuditEnhanced:
    """
    安全审计增强服务

    提供增强的审计日志、异常行为检测和安全告警功能。
    """

    def __init__(self):
        self._lock = threading.Lock()

        # 审计日志（增强格式）
        self._audit_logs: deque = deque(maxlen=MAX_AUDIT_LOGS)
        self._log_id_counter = 0

        # 告警
        self._alerts: deque = deque(maxlen=MAX_ALERTS)

        # 登录失败跟踪（用于暴力破解检测）
        self._login_failures: Dict[str, List[float]] = defaultdict(list)  # ip -> [timestamps]
        self._user_login_failures: Dict[str, List[float]] = defaultdict(list)  # user_id -> [timestamps]

        # 用户登录历史（用于异常地点/时间检测）
        self._user_login_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        # 操作频率跟踪
        self._sensitive_ops: Dict[str, List[float]] = defaultdict(list)  # user_id -> [timestamps]
        self._export_ops: Dict[str, List[Dict[str, Any]]] = defaultdict(list)  # user_id -> [{time, count}]

        # 配置
        self._config = {
            # 暴力破解阈值
            "brute_force_threshold": 5,       # 失败次数
            "brute_force_window": 300,         # 时间窗口（秒）
            # 工作时间
            "work_hours_start": 9,             # 上班时间（时）
            "work_hours_end": 18,              # 下班时间（时）
            # 敏感操作频率
            "sensitive_op_threshold": 20,      # 次数
            "sensitive_op_window": 3600,       # 时间窗口（秒）
            # 大量数据导出
            "mass_export_threshold": 1000,     # 记录数
            "mass_export_window": 86400,       # 时间窗口（秒）
            # 告警启用
            "alert_enabled": True,
            "alert_channels": ["internal"],   # 通知渠道
        }

        # 统计
        self._stats = {
            "total_logs": 0,
            "total_alerts": 0,
            "alerts_by_type": defaultdict(int),
            "alerts_by_severity": defaultdict(int),
            "today_alerts": 0,
            "start_of_day": time.time(),
        }

        logger.info("安全审计增强服务已初始化")

    # -----------------------------------------------------------------------
    # 配置管理
    # -----------------------------------------------------------------------

    def get_config(self) -> Dict[str, Any]:
        """获取配置"""
        with self._lock:
            return dict(self._config)

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """更新配置"""
        with self._lock:
            for key, value in updates.items():
                if key in self._config:
                    self._config[key] = value
            return dict(self._config)

    # -----------------------------------------------------------------------
    # 审计日志（增强格式）
    # -----------------------------------------------------------------------

    def log_event(
        self,
        category: str,
        action: str,
        severity: str = SEVERITY_INFO,
        subject_type: str = "user",      # 主体类型：user/service/system
        subject_id: str = "",
        subject_name: str = "",
        object_type: str = "",           # 客体类型
        object_id: str = "",
        object_name: str = "",
        result: str = "success",         # success/failed/denied
        source_ip: str = "",
        user_agent: str = "",
        request_method: str = "",
        request_path: str = "",
        details: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        """
        记录审计事件（增强格式）

        Args:
            category: 事件分类
            action: 动作类型
            severity: 严重级别
            subject_type: 主体类型
            subject_id: 主体ID
            subject_name: 主体名称
            object_type: 客体类型
            object_id: 客体ID
            object_name: 客体名称
            result: 结果
            source_ip: 来源IP
            user_agent: 用户代理
            request_method: 请求方法
            request_path: 请求路径
            details: 详情
            trace_id: 追踪ID

        Returns:
            审计日志条目
        """
        with self._lock:
            self._log_id_counter += 1
            event_id = f"AUDIT-{int(time.time())}-{self._log_id_counter}"
            now = time.time()
            now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

            if not trace_id:
                trace_id = uuid.uuid4().hex

            log_entry = {
                "event_id": event_id,
                "timestamp": now_str,
                "timestamp_unix": now,
                "category": category,
                "action": action,
                "severity": severity,
                "subject": {
                    "type": subject_type,
                    "id": subject_id,
                    "name": subject_name,
                },
                "object": {
                    "type": object_type,
                    "id": object_id,
                    "name": object_name,
                },
                "result": result,
                "source_ip": source_ip,
                "user_agent": user_agent,
                "request": {
                    "method": request_method,
                    "path": request_path,
                },
                "details": details or {},
                "trace_id": trace_id,
            }

            self._audit_logs.append(log_entry)
            self._stats["total_logs"] += 1

        # 触发异常检测（在锁外执行，避免死锁）
        self._detect_anomalies(log_entry)

        return log_entry

    def get_audit_logs(
        self,
        category: Optional[str] = None,
        action: Optional[str] = None,
        severity: Optional[str] = None,
        subject_id: Optional[str] = None,
        source_ip: Optional[str] = None,
        result: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """查询审计日志"""
        with self._lock:
            logs = list(self._audit_logs)

        logs.reverse()  # 最新在前

        if category:
            logs = [l for l in logs if l["category"] == category]
        if action:
            logs = [l for l in logs if l["action"] == action]
        if severity:
            logs = [l for l in logs if l["severity"] == severity]
        if subject_id:
            logs = [l for l in logs if l["subject"]["id"] == subject_id]
        if source_ip:
            logs = [l for l in logs if l["source_ip"] == source_ip]
        if result:
            logs = [l for l in logs if l["result"] == result]
        if start_time:
            logs = [l for l in logs if l["timestamp"] >= start_time]
        if end_time:
            logs = [l for l in logs if l["timestamp"] <= end_time]

        total = len(logs)
        offset = (page - 1) * page_size
        paged = logs[offset:offset + page_size]
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        return {
            "items": paged,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    # -----------------------------------------------------------------------
    # 异常行为检测
    # -----------------------------------------------------------------------

    def _detect_anomalies(self, log_entry: Dict[str, Any]) -> None:
        """检测异常行为（需在锁内调用）"""
        if not self._config["alert_enabled"]:
            return

        category = log_entry["category"]
        action = log_entry["action"]
        source_ip = log_entry["source_ip"]
        subject_id = log_entry["subject"]["id"]
        now = log_entry["timestamp_unix"]

        # 认证相关异常检测
        if category == EVENT_CATEGORY_AUTH:
            self._detect_auth_anomalies(action, source_ip, subject_id, now, log_entry)

        # 数据访问异常检测
        elif category == EVENT_CATEGORY_DATA:
            self._detect_data_anomalies(action, subject_id, now, log_entry)

        # 授权异常检测
        elif category == EVENT_CATEGORY_AUTHZ:
            self._detect_authz_anomalies(action, subject_id, log_entry)

    def _detect_auth_anomalies(
        self, action: str, source_ip: str, subject_id: str,
        now: float, log_entry: Dict[str, Any]
    ) -> None:
        """检测认证异常"""

        # 登录失败 -> 暴力破解检测
        if action == ACTION_LOGIN_FAILED:
            # IP 维度
            failures = self._login_failures[source_ip]
            failures.append(now)
            # 清理过期记录
            window = self._config["brute_force_window"]
            failures[:] = [t for t in failures if now - t <= window]

            if len(failures) >= self._config["brute_force_threshold"]:
                self._create_alert(
                    alert_type=ALERT_TYPE_BRUTE_FORCE,
                    title="暴力破解检测",
                    description=f"IP {source_ip} 在 {window}秒内 失败 {len(failures)} 次登录",
                    source_ip=source_ip,
                    details={
                        "failure_count": len(failures),
                        "window_seconds": window,
                        "source_ip": source_ip,
                    },
                )

            # 用户维度
            if subject_id:
                user_failures = self._user_login_failures[subject_id]
                user_failures.append(now)
                user_failures[:] = [t for t in user_failures if now - t <= window]

        # 登录成功 -> 检测多次失败后成功
        if action == ACTION_LOGIN:
            # 检查是否多次失败后成功
            if subject_id:
                user_failures = self._user_login_failures.get(subject_id, [])
                recent_failures = [t for t in user_failures if now - t <= 300]  # 5分钟内
                if len(recent_failures) >= 3:
                    self._create_alert(
                        alert_type=ALERT_TYPE_MULTIPLE_FAILURE_THEN_SUCCESS,
                        title="多次失败后成功登录",
                        description=f"用户 {subject_id} 在多次失败后成功登录",
                        source_ip=source_ip,
                        user_id=subject_id,
                        username=log_entry["subject"]["name"],
                        details={
                            "failure_count": len(recent_failures),
                            "source_ip": source_ip,
                        },
                    )

            # 异常时间登录检测
            hour = datetime.fromtimestamp(now).hour
            work_start = self._config["work_hours_start"]
            work_end = self._config["work_hours_end"]
            if hour < work_start or hour >= work_end:
                self._create_alert(
                    alert_type=ALERT_TYPE_UNUSUAL_LOGIN_TIME,
                    title="非工作时间登录",
                    description=f"用户 {subject_id or source_ip} 在非工作时间登录（{hour:02d}:00）",
                    source_ip=source_ip,
                    user_id=subject_id,
                    username=log_entry["subject"]["name"],
                    details={
                        "login_hour": hour,
                        "work_hours": f"{work_start}:00-{work_end}:00",
                    },
                )

            # 记录登录历史（用于地点检测）
            if subject_id:
                self._user_login_history[subject_id].append({
                    "time": now,
                    "ip": source_ip,
                })
                # 只保留最近 30 天的登录记录
                cutoff = now - 30 * DAY_SECONDS
                self._user_login_history[subject_id] = [
                    h for h in self._user_login_history[subject_id]
                    if h["time"] > cutoff
                ]

                # 异常地点检测：新 IP 登录
                known_ips = {h["ip"] for h in self._user_login_history[subject_id][:-1]}
                if source_ip and source_ip not in known_ips and len(known_ips) >= 2:
                    self._create_alert(
                        alert_type=ALERT_TYPE_UNUSUAL_LOCATION,
                        title="异常地点登录",
                        description=f"用户 {subject_id} 从新 IP {source_ip} 登录",
                        source_ip=source_ip,
                        user_id=subject_id,
                        username=log_entry["subject"]["name"],
                        details={
                            "new_ip": source_ip,
                            "known_ip_count": len(known_ips),
                        },
                    )

    def _detect_data_anomalies(
        self, action: str, subject_id: str,
        now: float, log_entry: Dict[str, Any]
    ) -> None:
        """检测数据访问异常"""

        if not subject_id:
            return

        # 大量数据导出检测
        if action == ACTION_DATA_EXPORT:
            export_count = log_entry["details"].get("record_count", 0)
            self._export_ops[subject_id].append({
                "time": now,
                "count": export_count,
            })

            # 清理过期记录
            window = self._config["mass_export_window"]
            self._export_ops[subject_id] = [
                e for e in self._export_ops[subject_id]
                if now - e["time"] <= window
            ]

            total_exported = sum(e["count"] for e in self._export_ops[subject_id])
            if total_exported >= self._config["mass_export_threshold"]:
                self._create_alert(
                    alert_type=ALERT_TYPE_MASS_DATA_EXPORT,
                    title="大量数据导出",
                    description=f"用户 {subject_id} 在 {window}秒内导出 {total_exported} 条记录",
                    user_id=subject_id,
                    username=log_entry["subject"]["name"],
                    details={
                        "total_exported": total_exported,
                        "threshold": self._config["mass_export_threshold"],
                        "window_seconds": window,
                    },
                )

        # 敏感操作频率检测
        sensitive_actions = [ACTION_DATA_DELETE, ACTION_DATA_MODIFY, ACTION_DATA_EXPORT]
        if action in sensitive_actions:
            self._sensitive_ops[subject_id].append(now)

            window = self._config["sensitive_op_window"]
            self._sensitive_ops[subject_id] = [
                t for t in self._sensitive_ops[subject_id]
                if now - t <= window
            ]

            count = len(self._sensitive_ops[subject_id])
            if count >= self._config["sensitive_op_threshold"]:
                self._create_alert(
                    alert_type=ALERT_TYPE_SENSITIVE_OP_FREQUENCY,
                    title="敏感操作频率异常",
                    description=f"用户 {subject_id} 在 {window}秒内执行 {count} 次敏感操作",
                    user_id=subject_id,
                    username=log_entry["subject"]["name"],
                    details={
                        "operation_count": count,
                        "threshold": self._config["sensitive_op_threshold"],
                        "window_seconds": window,
                    },
                )

        # 非工作时间操作
        hour = datetime.fromtimestamp(now).hour
        work_start = self._config["work_hours_start"]
        work_end = self._config["work_hours_end"]
        if action in [ACTION_DATA_EXPORT, ACTION_DATA_DELETE] and (hour < work_start or hour >= work_end):
            self._create_alert(
                alert_type=ALERT_TYPE_OFF_HOURS_OPERATION,
                title="非工作时间敏感操作",
                description=f"用户 {subject_id} 在非工作时间执行 {action}",
                user_id=subject_id,
                username=log_entry["subject"]["name"],
                details={
                    "action": action,
                    "operation_hour": hour,
                },
            )

    def _detect_authz_anomalies(
        self, action: str, subject_id: str,
        log_entry: Dict[str, Any]
    ) -> None:
        """检测授权异常"""

        if not subject_id:
            return

        # 权限提升检测
        if action in [ACTION_PERMISSION_CHANGE, ACTION_ROLE_CHANGE]:
            new_role = log_entry["details"].get("new_role", "")
            if new_role in ["admin", "super_admin"]:
                self._create_alert(
                    alert_type=ALERT_TYPE_PRIVILEGE_ESCALATION,
                    title="权限提升",
                    description=f"用户 {subject_id} 的角色被变更为 {new_role}",
                    user_id=subject_id,
                    username=log_entry["subject"]["name"],
                    details={
                        "action": action,
                        "new_role": new_role,
                        "old_role": log_entry["details"].get("old_role", ""),
                    },
                )

    # -----------------------------------------------------------------------
    # 告警管理
    # -----------------------------------------------------------------------

    def _create_alert(
        self,
        alert_type: str,
        title: str,
        description: str,
        source_ip: str = "",
        user_id: str = "",
        username: str = "",
        details: Optional[Dict[str, Any]] = None,
        _already_locked: bool = False,
    ) -> SecurityAlert:
        """创建安全告警
        
        Args:
            _already_locked: 内部使用，表示调用方已持有 self._lock
        """
        severity = ALERT_SEVERITY_MAP.get(alert_type, SEVERITY_MEDIUM)

        alert = SecurityAlert(
            alert_type=alert_type,
            severity=severity,
            title=title,
            description=description,
            source_ip=source_ip,
            user_id=user_id,
            username=username,
            details=details,
        )

        if not _already_locked:
            with self._lock:
                self._alerts.append(alert)
                self._stats["total_alerts"] += 1
                self._stats["alerts_by_type"][alert_type] += 1
                self._stats["alerts_by_severity"][severity] += 1
                self._check_day_reset()
                self._stats["today_alerts"] += 1
        else:
            self._alerts.append(alert)
            self._stats["total_alerts"] += 1
            self._stats["alerts_by_type"][alert_type] += 1
            self._stats["alerts_by_severity"][severity] += 1
            self._check_day_reset()
            self._stats["today_alerts"] += 1

        # 实时告警通知（高危事件）
        if severity in (SEVERITY_CRITICAL, SEVERITY_HIGH):
            self._send_alert_notification(alert)

        logger.warning(
            "安全告警: [%s] %s - %s (IP: %s, User: %s)",
            severity.upper(), alert_type, title, source_ip, user_id,
        )

        return alert

    def _send_alert_notification(self, alert: SecurityAlert) -> None:
        """发送告警通知"""
        channels = self._config.get("alert_channels", [])
        for channel in channels:
            try:
                if channel == "internal":
                    # 内部通知（已存储在告警列表中）
                    pass
                # 其他渠道（邮件/短信）可在此扩展
            except Exception as e:
                logger.error("发送告警通知失败 [%s]: %s", channel, e)

    def get_alerts(
        self,
        alert_type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """获取告警列表"""
        with self._lock:
            alerts = [a.to_dict() for a in self._alerts]

        alerts.reverse()  # 最新在前

        if alert_type:
            alerts = [a for a in alerts if a["alert_type"] == alert_type]
        if severity:
            alerts = [a for a in alerts if a["severity"] == severity]
        if status:
            alerts = [a for a in alerts if a["status"] == status]

        total = len(alerts)
        offset = (page - 1) * page_size
        paged = alerts[offset:offset + page_size]
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        return {
            "items": paged,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_alert_by_id(self, alert_id: str) -> Optional[Dict[str, Any]]:
        """根据 ID 获取告警"""
        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id:
                    return alert.to_dict()
        return None

    def acknowledge_alert(
        self, alert_id: str, acknowledged_by: str = "admin"
    ) -> Optional[Dict[str, Any]]:
        """确认告警"""
        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id:
                    alert.status = "acknowledged"
                    alert.acknowledged_by = acknowledged_by
                    alert.acknowledged_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    return alert.to_dict()
        return None

    def resolve_alert(
        self, alert_id: str, resolved_by: str = "admin", resolution_note: str = ""
    ) -> Optional[Dict[str, Any]]:
        """解决告警"""
        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id:
                    alert.status = "resolved"
                    alert.resolved_by = resolved_by
                    alert.resolved_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    if resolution_note:
                        alert.details["resolution_note"] = resolution_note
                    return alert.to_dict()
        return None

    # -----------------------------------------------------------------------
    # 统计信息
    # -----------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取审计统计信息"""
        with self._lock:
            self._check_day_reset()

            active_alerts = sum(
                1 for a in self._alerts if a.status == "active"
            )
            critical_active = sum(
                1 for a in self._alerts
                if a.status == "active" and a.severity == SEVERITY_CRITICAL
            )
            high_active = sum(
                1 for a in self._alerts
                if a.status == "active" and a.severity == SEVERITY_HIGH
            )

            return {
                "total_audit_logs": self._stats["total_logs"],
                "total_alerts": self._stats["total_alerts"],
                "today_alerts": self._stats["today_alerts"],
                "active_alerts": active_alerts,
                "critical_active": critical_active,
                "high_active": high_active,
                "alerts_by_type": dict(self._stats["alerts_by_type"]),
                "alerts_by_severity": dict(self._stats["alerts_by_severity"]),
                "event_categories": {
                    EVENT_CATEGORY_AUTH: "认证事件",
                    EVENT_CATEGORY_AUTHZ: "授权事件",
                    EVENT_CATEGORY_DATA: "数据访问",
                    EVENT_CATEGORY_CONFIG: "配置变更",
                    EVENT_CATEGORY_SYSTEM: "系统事件",
                },
            }

    def get_daily_report(self, date: Optional[str] = None) -> Dict[str, Any]:
        """生成每日安全报告"""
        with self._lock:
            if date is None:
                date = time.strftime("%Y-%m-%d", time.localtime())

            # 筛选当天的日志和告警
            day_logs = [
                l for l in self._audit_logs
                if l["timestamp"].startswith(date)
            ]
            day_alerts = [
                a for a in self._alerts
                if a.created_at_str.startswith(date)
            ]

            # 按分类统计
            logs_by_category = defaultdict(int)
            logs_by_action = defaultdict(int)
            for log in day_logs:
                logs_by_category[log["category"]] += 1
                logs_by_action[log["action"]] += 1

            alerts_by_severity = defaultdict(int)
            alerts_by_type = defaultdict(int)
            for alert in day_alerts:
                alerts_by_severity[alert.severity] += 1
                alerts_by_type[alert.alert_type] += 1

            return {
                "date": date,
                "summary": {
                    "total_audit_logs": len(day_logs),
                    "total_alerts": len(day_alerts),
                    "critical_alerts": alerts_by_severity.get(SEVERITY_CRITICAL, 0),
                    "high_alerts": alerts_by_severity.get(SEVERITY_HIGH, 0),
                    "medium_alerts": alerts_by_severity.get(SEVERITY_MEDIUM, 0),
                    "low_alerts": alerts_by_severity.get(SEVERITY_LOW, 0),
                },
                "logs_by_category": dict(logs_by_category),
                "logs_by_action": dict(logs_by_action),
                "alerts_by_type": dict(alerts_by_type),
                "alerts_by_severity": dict(alerts_by_severity),
            }

    def _check_day_reset(self) -> None:
        """检查并重置每日统计（需在锁内调用）"""
        now = time.time()
        if now - self._stats["start_of_day"] >= DAY_SECONDS:
            self._stats["today_alerts"] = 0
            self._stats["start_of_day"] = now


# ===========================================================================
# 单例管理
# ===========================================================================

_audit_enhanced: Optional[SecurityAuditEnhanced] = None
_audit_enhanced_lock = threading.Lock()


def get_security_audit_enhanced() -> SecurityAuditEnhanced:
    """获取增强版安全审计服务单例"""
    global _audit_enhanced
    if _audit_enhanced is None:
        with _audit_enhanced_lock:
            if _audit_enhanced is None:
                _audit_enhanced = SecurityAuditEnhanced()
    return _audit_enhanced


# ===========================================================================
# 直接运行测试
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    audit = get_security_audit_enhanced()

    print("=== 审计日志测试 ===")
    # 记录一些登录失败（模拟暴力破解）
    for i in range(6):
        audit.log_event(
            category=EVENT_CATEGORY_AUTH,
            action=ACTION_LOGIN_FAILED,
            severity=SEVERITY_MEDIUM,
            subject_id="test_user",
            subject_name="测试用户",
            source_ip="192.168.1.100",
            result="failed",
            details={"reason": "密码错误"},
        )
        time.sleep(0.01)

    # 记录登录成功
    audit.log_event(
        category=EVENT_CATEGORY_AUTH,
        action=ACTION_LOGIN,
        severity=SEVERITY_INFO,
        subject_id="admin_user",
        subject_name="管理员",
        source_ip="10.0.0.1",
        result="success",
    )

    # 记录数据导出
    audit.log_event(
        category=EVENT_CATEGORY_DATA,
        action=ACTION_DATA_EXPORT,
        severity=SEVERITY_LOW,
        subject_id="admin_user",
        subject_name="管理员",
        object_type="user_data",
        result="success",
        details={"record_count": 1500},
    )

    stats = audit.get_stats()
    print(f"审计日志总数: {stats['total_audit_logs']}")
    print(f"告警总数: {stats['total_alerts']}")
    print(f"活跃告警: {stats['active_alerts']}")
    print(f"按类型: {stats['alerts_by_type']}")

    # 获取告警
    alerts = audit.get_alerts(page=1, page_size=10)
    print(f"\n告警列表 ({alerts['total']} 条):")
    for a in alerts["items"]:
        print(f"  [{a['severity'].upper()}] {a['title']} ({a['alert_type']})")
