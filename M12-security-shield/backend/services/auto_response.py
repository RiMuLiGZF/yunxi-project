"""
云汐 M12 安全盾 - 安全事件自动响应引擎

实现安全事件的自动检测、评估和响应，支持多种响应规则和多级响应级别。

响应规则：
1. SQL 注入/XSS 攻击 → 自动封禁 IP 1 小时
2. 暴力破解（同一 IP 5 分钟内 10 次登录失败） → 自动封禁 IP 24 小时
3. 高频扫描（同一 IP 1 分钟内 100 次 404） → 自动封禁 IP 6 小时
4. DDoS 检测（同一 IP 1 秒内 50 次请求） → 自动封禁 IP 12 小时

响应级别：
- detect：只记录，不拦截（默认）
- log：记录 + 告警
- block：记录 + 拦截 + 封禁
"""

import time
import threading
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from collections import deque

logger = logging.getLogger(__name__)


# ===========================================================================
# 常量定义
# ===========================================================================

# 响应级别
RESPONSE_LEVEL_DETECT = "detect"    # 只记录，不拦截（默认）
RESPONSE_LEVEL_LOG = "log"          # 记录 + 告警
RESPONSE_LEVEL_BLOCK = "block"      # 记录 + 拦截 + 封禁

VALID_RESPONSE_LEVELS = {RESPONSE_LEVEL_DETECT, RESPONSE_LEVEL_LOG, RESPONSE_LEVEL_BLOCK}

# 事件类型
EVENT_TYPE_SQL_INJECTION = "sql_injection"
EVENT_TYPE_XSS = "xss"
EVENT_TYPE_COMMAND_INJECTION = "command_injection"
EVENT_TYPE_PATH_TRAVERSAL = "path_traversal"
EVENT_TYPE_LOGIN_FAILED = "login_failed"
EVENT_TYPE_404_SCAN = "scan_404"
EVENT_TYPE_RATE_EXCEEDED = "rate_exceeded"
EVENT_TYPE_DDOS = "ddos"
EVENT_TYPE_WAF_BLOCK = "waf_block"

# 规则 ID
RULE_SQL_XSS_BAN = "sql_xss_ban"
RULE_BRUTE_FORCE_BAN = "brute_force_ban"
RULE_SCAN_404_BAN = "scan_404_ban"
RULE_DDOS_BAN = "ddos_ban"


# ===========================================================================
# 数据类
# ===========================================================================

@dataclass
class SecurityEvent:
    """安全事件"""
    event_type: str                          # 事件类型
    source_ip: str                           # 来源 IP
    severity: str = "medium"                 # 严重级别
    target_path: str = ""                    # 目标路径
    method: str = ""                         # 请求方法
    description: str = ""                    # 事件描述
    rule_name: str = ""                      # 触发的规则名称
    user_agent: str = ""                     # 用户代理
    extra_data: Dict[str, Any] = field(default_factory=dict)  # 附加数据
    timestamp: float = field(default_factory=time.time)       # 时间戳


@dataclass
class ResponseRule:
    """响应规则"""
    rule_id: str                             # 规则 ID
    name: str                                # 规则名称
    description: str = ""                    # 规则描述
    event_types: List[str] = field(default_factory=list)     # 触发事件类型
    # 触发条件
    threshold: int = 1                       # 触发阈值（事件次数）
    time_window_seconds: int = 60            # 时间窗口（秒）
    # 响应动作
    action: str = "log"                      # 动作：log/ban/alert
    ban_duration_minutes: int = 0            # 封禁时长（分钟），0 表示不封禁
    risk_level: str = "medium"               # 风险级别
    # 状态
    enabled: bool = True                     # 是否启用
    is_builtin: bool = False                 # 是否内置规则


@dataclass
class BannedIp:
    """封禁 IP 记录"""
    ip_address: str                          # IP 地址
    reason: str = ""                         # 封禁原因
    rule_id: str = ""                        # 触发的规则 ID
    severity: str = "high"                   # 严重级别
    banned_at: float = field(default_factory=time.time)  # 封禁时间
    expires_at: float = 0.0                  # 过期时间戳（0 表示永久）
    banned_by: str = "auto_response"         # 封禁操作人
    hit_count: int = 0                       # 命中次数
    is_active: bool = True                   # 是否生效


# ===========================================================================
# 自动响应引擎
# ===========================================================================

class AutoResponseEngine:
    """
    安全事件自动响应引擎

    接收安全事件，根据预设规则自动判断并执行响应动作。
    支持三级响应级别，封禁 IP 自动到期解封。
    线程安全，支持高并发场景。
    """

    def __init__(self, response_level: str = RESPONSE_LEVEL_DETECT):
        """初始化自动响应引擎

        Args:
            response_level: 响应级别（detect/log/block）
        """
        self._response_level = response_level
        self._lock = threading.RLock()

        # 响应规则
        self._rules: Dict[str, ResponseRule] = {}
        self._load_builtin_rules()

        # 封禁 IP 列表
        self._banned_ips: Dict[str, BannedIp] = {}

        # 事件计数器：ip -> {event_type -> deque of timestamps}
        # 使用 deque 高效管理时间窗口内的事件
        self._event_counters: Dict[str, Dict[str, deque]] = {}

        # 告警记录（最近 1000 条）
        self._alerts: deque = deque(maxlen=1000)

        # 响应统计
        self._stats = {
            "total_events": 0,
            "total_bans": 0,
            "total_alerts": 0,
            "active_bans": 0,
        }

        # 清理相关
        self._last_cleanup = time.time()
        self._cleanup_interval = 60  # 每 60 秒清理一次

        # 持久化路径（延迟设置）
        self._persist_path: Optional[str] = None

    # -----------------------------------------------------------------------
    # 内置规则
    # -----------------------------------------------------------------------

    def _load_builtin_rules(self) -> None:
        """加载内置响应规则"""
        builtin_rules = [
            ResponseRule(
                rule_id=RULE_SQL_XSS_BAN,
                name="SQL 注入/XSS 攻击自动封禁",
                description="检测到 SQL 注入或 XSS 攻击时，自动封禁 IP 1 小时",
                event_types=[EVENT_TYPE_SQL_INJECTION, EVENT_TYPE_XSS, EVENT_TYPE_WAF_BLOCK],
                threshold=1,
                time_window_seconds=60,
                action="ban",
                ban_duration_minutes=60,  # 1 小时
                risk_level="high",
                is_builtin=True,
            ),
            ResponseRule(
                rule_id=RULE_BRUTE_FORCE_BAN,
                name="暴力破解自动封禁",
                description="同一 IP 5 分钟内 10 次登录失败，自动封禁 IP 24 小时",
                event_types=[EVENT_TYPE_LOGIN_FAILED],
                threshold=10,
                time_window_seconds=300,  # 5 分钟
                action="ban",
                ban_duration_minutes=1440,  # 24 小时
                risk_level="high",
                is_builtin=True,
            ),
            ResponseRule(
                rule_id=RULE_SCAN_404_BAN,
                name="高频扫描自动封禁",
                description="同一 IP 1 分钟内 100 次 404，自动封禁 IP 6 小时",
                event_types=[EVENT_TYPE_404_SCAN],
                threshold=100,
                time_window_seconds=60,  # 1 分钟
                action="ban",
                ban_duration_minutes=360,  # 6 小时
                risk_level="medium",
                is_builtin=True,
            ),
            ResponseRule(
                rule_id=RULE_DDOS_BAN,
                name="DDoS 攻击自动封禁",
                description="同一 IP 1 秒内 50 次请求，自动封禁 IP 12 小时",
                event_types=[EVENT_TYPE_DDOS, EVENT_TYPE_RATE_EXCEEDED],
                threshold=50,
                time_window_seconds=1,  # 1 秒
                action="ban",
                ban_duration_minutes=720,  # 12 小时
                risk_level="critical",
                is_builtin=True,
            ),
        ]

        for rule in builtin_rules:
            self._rules[rule.rule_id] = rule

    # -----------------------------------------------------------------------
    # 响应级别管理
    # -----------------------------------------------------------------------

    def set_response_level(self, level: str) -> bool:
        """设置响应级别

        Args:
            level: 响应级别（detect/log/block）

        Returns:
            是否设置成功
        """
        if level not in VALID_RESPONSE_LEVELS:
            return False
        with self._lock:
            self._response_level = level
        return True

    def get_response_level(self) -> str:
        """获取当前响应级别

        Returns:
            当前响应级别
        """
        with self._lock:
            return self._response_level

    # -----------------------------------------------------------------------
    # 事件处理
    # -----------------------------------------------------------------------

    def process_event(self, event: SecurityEvent) -> Dict[str, Any]:
        """处理安全事件，判断是否触发响应

        Args:
            event: 安全事件

        Returns:
            处理结果字典
            {
                "triggered": bool,           # 是否触发了响应
                "actions": List[str],        # 执行的动作列表
                "rules_triggered": List[str],# 触发的规则 ID 列表
                "banned": bool,              # 是否导致封禁
                "ban_duration_minutes": int, # 封禁时长（分钟）
                "alert_message": str,        # 告警消息
            }
        """
        result = {
            "triggered": False,
            "actions": [],
            "rules_triggered": [],
            "banned": False,
            "ban_duration_minutes": 0,
            "alert_message": "",
        }

        self._maybe_cleanup()

        with self._lock:
            self._stats["total_events"] += 1

            # detect 级别：只记录，不做任何响应
            if self._response_level == RESPONSE_LEVEL_DETECT:
                return result

            # 记录事件到计数器
            self._record_event(event)

            # 检查各规则是否触发
            for rule_id, rule in self._rules.items():
                if not rule.enabled:
                    continue

                if event.event_type not in rule.event_types:
                    continue

                # 检查时间窗口内的事件次数
                count = self._get_event_count(event.source_ip, event.event_type,
                                               rule.time_window_seconds)

                if count >= rule.threshold:
                    result["triggered"] = True
                    result["rules_triggered"].append(rule_id)

                    # 根据响应级别决定动作
                    if self._response_level == RESPONSE_LEVEL_LOG:
                        # log 级别：记录 + 告警
                        if "alert" not in result["actions"]:
                            result["actions"].append("alert")
                            self._stats["total_alerts"] += 1
                            alert_msg = f"[{rule.risk_level.upper()}] {rule.name}: " \
                                        f"IP {event.source_ip} 触发 {rule.rule_id}"
                            self._alerts.append({
                                "timestamp": time.time(),
                                "ip": event.source_ip,
                                "rule_id": rule_id,
                                "rule_name": rule.name,
                                "severity": rule.risk_level,
                                "message": alert_msg,
                                "event_type": event.event_type,
                            })
                            result["alert_message"] = alert_msg

                    elif self._response_level == RESPONSE_LEVEL_BLOCK:
                        # block 级别：记录 + 告警 + 封禁
                        if "alert" not in result["actions"]:
                            result["actions"].append("alert")
                            self._stats["total_alerts"] += 1

                        if rule.action == "ban" and rule.ban_duration_minutes > 0:
                            # 执行封禁
                            is_banned, _ = self._is_ip_banned(event.source_ip)
                            if not is_banned:
                                self._do_ban(
                                    ip=event.source_ip,
                                    duration_minutes=rule.ban_duration_minutes,
                                    reason=rule.description,
                                    rule_id=rule_id,
                                    severity=rule.risk_level,
                                )
                                result["banned"] = True
                                result["ban_duration_minutes"] = rule.ban_duration_minutes
                                if "ban" not in result["actions"]:
                                    result["actions"].append("ban")

            return result

    def _record_event(self, event: SecurityEvent) -> None:
        """记录事件到计数器（需在锁内调用）"""
        ip = event.source_ip
        if ip not in self._event_counters:
            self._event_counters[ip] = {}

        event_type = event.event_type
        if event_type not in self._event_counters[ip]:
            self._event_counters[ip][event_type] = deque()

        self._event_counters[ip][event_type].append(event.timestamp)

    def _get_event_count(self, ip: str, event_type: str, time_window_seconds: int) -> int:
        """获取指定 IP 在时间窗口内的事件次数（需在锁内调用）"""
        if ip not in self._event_counters:
            return 0
        if event_type not in self._event_counters[ip]:
            return 0

        now = time.time()
        dq = self._event_counters[ip][event_type]

        # 清理窗口外的事件
        cutoff = now - time_window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()

        return len(dq)

    # -----------------------------------------------------------------------
    # 封禁管理
    # -----------------------------------------------------------------------

    def ban_ip(self, ip: str, duration_minutes: int = 60,
               reason: str = "", rule_id: str = "manual") -> bool:
        """封禁 IP

        Args:
            ip: IP 地址
            duration_minutes: 封禁时长（分钟），0 表示永久
            reason: 封禁原因
            rule_id: 规则 ID

        Returns:
            是否成功封禁
        """
        with self._lock:
            return self._do_ban(ip, duration_minutes, reason, rule_id)

    def _do_ban(self, ip: str, duration_minutes: int,
                reason: str, rule_id: str,
                severity: str = "high",
                banned_by: str = "auto_response") -> bool:
        """执行封禁（需在锁内调用）"""
        if not ip:
            return False

        now = time.time()
        expires_at = now + duration_minutes * 60 if duration_minutes > 0 else 0.0

        # 如果已经被封禁，更新封禁时间
        if ip in self._banned_ips and self._banned_ips[ip].is_active:
            ban = self._banned_ips[ip]
            # 延长封禁时间（取较长的）
            if expires_at > ban.expires_at or ban.expires_at == 0:
                ban.expires_at = expires_at
            ban.reason = reason
            ban.rule_id = rule_id
            ban.severity = severity
            return True

        ban = BannedIp(
            ip_address=ip,
            reason=reason,
            rule_id=rule_id,
            severity=severity,
            banned_at=now,
            expires_at=expires_at,
            banned_by=banned_by,
            is_active=True,
        )
        self._banned_ips[ip] = ban
        self._stats["total_bans"] += 1
        self._stats["active_bans"] += 1
        return True

    def unban_ip(self, ip: str) -> bool:
        """解封 IP

        Args:
            ip: IP 地址

        Returns:
            是否成功解封
        """
        with self._lock:
            if ip in self._banned_ips and self._banned_ips[ip].is_active:
                self._banned_ips[ip].is_active = False
                self._stats["active_bans"] -= 1
                return True
            return False

    def get_banned_ips(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """获取封禁 IP 列表

        Args:
            active_only: 是否只返回生效的封禁

        Returns:
            封禁 IP 列表
        """
        self._maybe_cleanup()
        with self._lock:
            result = []
            for ban in self._banned_ips.values():
                if active_only and not ban.is_active:
                    continue
                result.append({
                    "ip_address": ban.ip_address,
                    "reason": ban.reason,
                    "rule_id": ban.rule_id,
                    "severity": ban.severity,
                    "banned_at": datetime.fromtimestamp(ban.banned_at).isoformat(),
                    "expires_at": datetime.fromtimestamp(ban.expires_at).isoformat()
                    if ban.expires_at > 0 else None,
                    "remaining_minutes": max(0, int((ban.expires_at - time.time()) / 60))
                    if ban.expires_at > 0 else -1,
                    "banned_by": ban.banned_by,
                    "hit_count": ban.hit_count,
                    "is_active": ban.is_active,
                })
            # 按封禁时间倒序
            result.sort(key=lambda x: x["banned_at"], reverse=True)
            return result

    def is_ip_banned(self, ip: str) -> Tuple[bool, Optional[BannedIp]]:
        """检查 IP 是否被封禁

        Args:
            ip: IP 地址

        Returns:
            (是否被封禁, 封禁记录)
        """
        self._maybe_cleanup()
        with self._lock:
            return self._is_ip_banned(ip)

    def _is_ip_banned(self, ip: str) -> Tuple[bool, Optional[BannedIp]]:
        """检查 IP 是否被封禁（需在锁内调用）"""
        ban = self._banned_ips.get(ip)
        if ban and ban.is_active:
            # 检查是否过期
            if ban.expires_at > 0 and time.time() > ban.expires_at:
                ban.is_active = False
                self._stats["active_bans"] -= 1
                return False, None
            ban.hit_count += 1
            return True, ban
        return False, None

    # -----------------------------------------------------------------------
    # 规则管理
    # -----------------------------------------------------------------------

    def get_rules(self) -> List[Dict[str, Any]]:
        """获取所有响应规则

        Returns:
            规则列表
        """
        with self._lock:
            return [
                {
                    "rule_id": r.rule_id,
                    "name": r.name,
                    "description": r.description,
                    "event_types": r.event_types,
                    "threshold": r.threshold,
                    "time_window_seconds": r.time_window_seconds,
                    "action": r.action,
                    "ban_duration_minutes": r.ban_duration_minutes,
                    "risk_level": r.risk_level,
                    "enabled": r.enabled,
                    "is_builtin": r.is_builtin,
                }
                for r in self._rules.values()
            ]

    def update_rule(self, rule_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """更新响应规则

        Args:
            rule_id: 规则 ID
            updates: 更新字段

        Returns:
            更新后的规则，不存在返回 None
        """
        with self._lock:
            rule = self._rules.get(rule_id)
            if not rule:
                return None

            # 可更新的字段
            allowed_fields = {
                "name", "description", "threshold", "time_window_seconds",
                "action", "ban_duration_minutes", "risk_level", "enabled",
            }
            for key, value in updates.items():
                if key in allowed_fields and hasattr(rule, key):
                    setattr(rule, key, value)

            return {
                "rule_id": rule.rule_id,
                "name": rule.name,
                "description": rule.description,
                "event_types": rule.event_types,
                "threshold": rule.threshold,
                "time_window_seconds": rule.time_window_seconds,
                "action": rule.action,
                "ban_duration_minutes": rule.ban_duration_minutes,
                "risk_level": rule.risk_level,
                "enabled": rule.enabled,
                "is_builtin": rule.is_builtin,
            }

    def add_rule(self, rule_data: Dict[str, Any]) -> Dict[str, Any]:
        """添加自定义响应规则

        Args:
            rule_data: 规则数据

        Returns:
            添加后的规则
        """
        with self._lock:
            rule_id = rule_data.get("rule_id", "")
            if not rule_id:
                rule_id = f"custom_rule_{int(time.time())}"

            # 确保 ID 唯一
            if rule_id in self._rules:
                rule_id = f"{rule_id}_{int(time.time())}"

            rule = ResponseRule(
                rule_id=rule_id,
                name=rule_data.get("name", rule_id),
                description=rule_data.get("description", ""),
                event_types=rule_data.get("event_types", []),
                threshold=rule_data.get("threshold", 1),
                time_window_seconds=rule_data.get("time_window_seconds", 60),
                action=rule_data.get("action", "log"),
                ban_duration_minutes=rule_data.get("ban_duration_minutes", 0),
                risk_level=rule_data.get("risk_level", "medium"),
                enabled=rule_data.get("enabled", True),
                is_builtin=False,
            )
            self._rules[rule_id] = rule
            return asdict(rule)

    def delete_rule(self, rule_id: str) -> bool:
        """删除自定义响应规则

        Args:
            rule_id: 规则 ID

        Returns:
            是否删除成功
        """
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule and not rule.is_builtin:
                del self._rules[rule_id]
                return True
            return False

    # -----------------------------------------------------------------------
    # 告警与统计
    # -----------------------------------------------------------------------

    def get_alerts(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近的告警

        Args:
            limit: 返回数量限制

        Returns:
            告警列表
        """
        with self._lock:
            alerts = list(self._alerts)
            return alerts[-limit:] if limit > 0 else alerts

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计字典
        """
        self._maybe_cleanup()
        with self._lock:
            return {
                "response_level": self._response_level,
                "total_events": self._stats["total_events"],
                "total_bans": self._stats["total_bans"],
                "total_alerts": self._stats["total_alerts"],
                "active_bans": self._stats["active_bans"],
                "total_rules": len(self._rules),
                "enabled_rules": sum(1 for r in self._rules.values() if r.enabled),
            }

    # -----------------------------------------------------------------------
    # 持久化
    # -----------------------------------------------------------------------

    def set_persist_path(self, path: str) -> None:
        """设置持久化文件路径

        Args:
            path: 文件路径
        """
        self._persist_path = path
        # 尝试加载已有的持久化数据
        self._load_from_disk()

    def save_to_disk(self) -> bool:
        """保存数据到磁盘

        Returns:
            是否保存成功
        """
        if not self._persist_path:
            return False
        try:
            with self._lock:
                data = {
                    "response_level": self._response_level,
                    "banned_ips": {
                        ip: {
                            "ip_address": ban.ip_address,
                            "reason": ban.reason,
                            "rule_id": ban.rule_id,
                            "severity": ban.severity,
                            "banned_at": ban.banned_at,
                            "expires_at": ban.expires_at,
                            "banned_by": ban.banned_by,
                            "hit_count": ban.hit_count,
                            "is_active": ban.is_active,
                        }
                        for ip, ban in self._banned_ips.items()
                    },
                    "custom_rules": {
                        rid: asdict(rule)
                        for rid, rule in self._rules.items()
                        if not rule.is_builtin
                    },
                    "stats": self._stats,
                }
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("Failed to save auto-response state to disk: %s", e, exc_info=True)
            return False

    def _load_from_disk(self) -> bool:
        """从磁盘加载数据

        Returns:
            是否加载成功
        """
        if not self._persist_path:
            return False
        try:
            import os
            if not os.path.exists(self._persist_path):
                return False

            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            with self._lock:
                # 加载响应级别
                if "response_level" in data:
                    self._response_level = data["response_level"]

                # 加载封禁 IP
                if "banned_ips" in data:
                    now = time.time()
                    for ip, ban_data in data["banned_ips"].items():
                        # 跳过已过期且不活跃的
                        if not ban_data.get("is_active", True):
                            continue
                        if ban_data.get("expires_at", 0) > 0 and \
                           ban_data["expires_at"] < now:
                            continue

                        ban = BannedIp(
                            ip_address=ban_data["ip_address"],
                            reason=ban_data.get("reason", ""),
                            rule_id=ban_data.get("rule_id", ""),
                            severity=ban_data.get("severity", "high"),
                            banned_at=ban_data.get("banned_at", now),
                            expires_at=ban_data.get("expires_at", 0),
                            banned_by=ban_data.get("banned_by", "auto_response"),
                            hit_count=ban_data.get("hit_count", 0),
                            is_active=ban_data.get("is_active", True),
                        )
                        self._banned_ips[ip] = ban
                        self._stats["active_bans"] += 1

                # 加载自定义规则
                if "custom_rules" in data:
                    for rid, rule_data in data["custom_rules"].items():
                        rule = ResponseRule(
                            rule_id=rule_data["rule_id"],
                            name=rule_data.get("name", rid),
                            description=rule_data.get("description", ""),
                            event_types=rule_data.get("event_types", []),
                            threshold=rule_data.get("threshold", 1),
                            time_window_seconds=rule_data.get("time_window_seconds", 60),
                            action=rule_data.get("action", "log"),
                            ban_duration_minutes=rule_data.get("ban_duration_minutes", 0),
                            risk_level=rule_data.get("risk_level", "medium"),
                            enabled=rule_data.get("enabled", True),
                            is_builtin=False,
                        )
                        self._rules[rid] = rule

            return True
        except Exception as e:
            logger.error("Failed to load auto-response state from disk: %s", e, exc_info=True)
            return False

    # -----------------------------------------------------------------------
    # 清理过期数据
    # -----------------------------------------------------------------------

    def _maybe_cleanup(self) -> None:
        """定期清理过期数据"""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        with self._lock:
            # 双重检查
            if now - self._last_cleanup < self._cleanup_interval:
                return
            self._last_cleanup = now

            # 清理过期的封禁 IP
            expired_ips = []
            for ip, ban in self._banned_ips.items():
                if ban.is_active and ban.expires_at > 0 and ban.expires_at < now:
                    ban.is_active = False
                    expired_ips.append(ip)
                    self._stats["active_bans"] -= 1

            # 清理过期的事件计数器
            expired_ips_counter = []
            max_window = 86400  # 最多保留 24 小时
            for ip, types in self._event_counters.items():
                has_active = False
                for event_type, dq in types.items():
                    # 清理窗口外的
                    cutoff = now - max_window
                    while dq and dq[0] < cutoff:
                        dq.popleft()
                    if dq:
                        has_active = True
                if not has_active:
                    expired_ips_counter.append(ip)

            for ip in expired_ips_counter:
                del self._event_counters[ip]

            # 持久化（如果配置了）
            if self._persist_path:
                self.save_to_disk()


# ===========================================================================
# 单例管理
# ===========================================================================

_auto_response_engine: Optional[AutoResponseEngine] = None
_auto_response_engine_lock = threading.Lock()


def get_auto_response_engine() -> AutoResponseEngine:
    """获取自动响应引擎单例

    Returns:
        AutoResponseEngine 实例
    """
    global _auto_response_engine
    if _auto_response_engine is None:
        with _auto_response_engine_lock:
            if _auto_response_engine is None:
                engine = AutoResponseEngine(response_level=RESPONSE_LEVEL_DETECT)

                # 尝试设置持久化路径
                try:
                    try:
                        from ..config import get_settings
                    except ImportError:
                        from config import get_settings
                    settings = get_settings()
                    persist_path = settings.data_dir / "auto_response.json"
                    engine.set_persist_path(str(persist_path))
                except Exception:
                    pass

                _auto_response_engine = engine
    return _auto_response_engine


# 兼容直接运行测试
if __name__ == "__main__":
    engine = get_auto_response_engine()
    print("自动响应引擎已初始化")
    print(f"响应级别: {engine.get_response_level()}")
    print(f"内置规则数: {len(engine.get_rules())}")
    print()

    # 测试 detect 级别
    print("=== Detect 级别 ===")
    event = SecurityEvent(
        event_type=EVENT_TYPE_SQL_INJECTION,
        source_ip="192.168.1.100",
        severity="high",
        description="SQL 注入攻击",
    )
    result = engine.process_event(event)
    print(f"SQL 注入事件处理: triggered={result['triggered']}")
    print(f"  原因: detect 级别只记录不响应")

    # 切换到 block 级别
    engine.set_response_level(RESPONSE_LEVEL_BLOCK)
    print(f"\n=== Block 级别 (切换后) ===")

    # 测试 SQL 注入封禁
    event2 = SecurityEvent(
        event_type=EVENT_TYPE_SQL_INJECTION,
        source_ip="10.0.0.1",
        severity="high",
        description="SQL 注入攻击测试",
    )
    result2 = engine.process_event(event2)
    print(f"SQL 注入事件处理:")
    print(f"  triggered: {result2['triggered']}")
    print(f"  actions: {result2['actions']}")
    print(f"  banned: {result2['banned']}")
    print(f"  ban_duration: {result2['ban_duration_minutes']} 分钟")

    # 测试暴力破解封禁
    print(f"\n=== 暴力破解测试（需要 10 次登录失败）===")
    for i in range(10):
        ev = SecurityEvent(
            event_type=EVENT_TYPE_LOGIN_FAILED,
            source_ip="172.16.0.50",
            severity="medium",
            description=f"登录失败 #{i+1}",
        )
        result3 = engine.process_event(ev)

    print(f"10 次登录失败后，封禁状态:")
    banned, ban_info = engine.is_ip_banned("172.16.0.50")
    print(f"  被封禁: {banned}")
    if ban_info:
        print(f"  原因: {ban_info.reason}")
        print(f"  时长: {int((ban_info.expires_at - time.time()) / 60)} 分钟")

    # 统计
    print(f"\n=== 统计 ===")
    stats = engine.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # 封禁列表
    print(f"\n=== 封禁列表 ===")
    for ban in engine.get_banned_ips():
        print(f"  {ban['ip_address']}: {ban['reason'][:30]}... "
              f"(剩余 {ban['remaining_minutes']} 分钟)")
