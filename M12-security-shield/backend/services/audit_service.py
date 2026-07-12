"""
云汐 M12 安全盾 - 审计日志服务
提供安全事件记录、操作审计、统计分析等功能，支持：

1. 安全事件记录（WAF 拦截、登录失败、权限异常等）
2. 操作审计日志（所有重要操作的完整轨迹）
3. 事件查询和统计
4. 事件处理和状态管理
5. 趋势分析和威胁分布统计
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict


# ===========================================================================
# 审计服务
# ===========================================================================

class AuditService:
    """
    审计服务

    管理安全事件和操作审计日志，提供查询和统计功能。
    内存存储 + 定期持久化（预留数据库对接接口）。
    线程安全，支持高并发写入。
    """

    def __init__(self):
        """初始化审计服务"""
        # 安全事件存储
        self._security_events: List[Dict[str, Any]] = []
        # 审计日志存储
        self._audit_logs: List[Dict[str, Any]] = []

        # 事件 ID 计数器
        self._event_id_counter = 0
        self._log_id_counter = 0

        # 统计数据
        self._stats: Dict[str, Any] = {
            "total_events": 0,
            "total_logs": 0,
            "events_by_type": defaultdict(int),
            "events_by_severity": defaultdict(int),
            "events_by_hour": defaultdict(int),
            "waf_blocks_today": 0,
            "events_today": 0,
            "start_of_day": time.time(),
        }

        # 线程锁
        self._lock = threading.Lock()

        # 最大保留条数（内存中）
        self._max_events = 10000
        self._max_logs = 10000

    # -----------------------------------------------------------------------
    # 安全事件
    # -----------------------------------------------------------------------

    def log_security_event(
        self,
        event_type: str,
        severity: str = "info",
        source_ip: str = "",
        target_path: str = "",
        method: str = "",
        description: str = "",
        rule_name: str = "",
        user_agent: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记录安全事件

        Args:
            event_type: 事件类型
            severity: 严重级别
            source_ip: 来源 IP
            target_path: 目标路径
            method: 请求方法
            description: 事件描述
            rule_name: 触发的规则名称
            user_agent: 用户代理
            details: 详细信息

        Returns:
            创建的事件记录
        """
        with self._lock:
            self._event_id_counter += 1
            now = time.time()
            now_str = datetime.now().isoformat()

            event = {
                "id": self._event_id_counter,
                "event_type": event_type,
                "severity": severity,
                "source_ip": source_ip,
                "target_path": target_path,
                "method": method,
                "description": description,
                "rule_name": rule_name,
                "user_agent": user_agent,
                "status": "active",
                "resolved_by": "",
                "resolved_at": None,
                "resolution_note": "",
                "extra_data": details or {},
                "created_at": now_str,
                "created_timestamp": now,
            }

            self._security_events.append(event)

            # 更新统计
            self._stats["total_events"] += 1
            self._stats["events_by_type"][event_type] += 1
            self._stats["events_by_severity"][severity] += 1

            # 每日统计
            self._check_day_reset()
            self._stats["events_today"] += 1
            if event_type == "waf_block":
                self._stats["waf_blocks_today"] += 1

            # 按小时统计
            hour_key = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:00")
            self._stats["events_by_hour"][hour_key] += 1

            # 限制最大条数
            if len(self._security_events) > self._max_events:
                self._security_events = self._security_events[-self._max_events:]

            return event

    def get_security_events(
        self,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        source_ip: Optional[str] = None,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """查询安全事件

        Args:
            event_type: 事件类型筛选
            severity: 严重级别筛选
            source_ip: 来源 IP 筛选
            status: 状态筛选
            keyword: 关键词搜索
            start_time: 开始时间
            end_time: 结束时间
            page: 页码
            page_size: 每页数量

        Returns:
            分页结果字典
        """
        with self._lock:
            events = list(self._security_events)

        # 倒序排列（最新在前）
        events.reverse()

        # 过滤
        if event_type:
            events = [e for e in events if e["event_type"] == event_type]
        if severity:
            events = [e for e in events if e["severity"] == severity]
        if source_ip:
            events = [e for e in events if e["source_ip"] == source_ip]
        if status:
            events = [e for e in events if e["status"] == status]
        if keyword:
            kw = keyword.lower()
            events = [
                e for e in events
                if kw in e.get("description", "").lower()
                or kw in e.get("rule_name", "").lower()
                or kw in e.get("source_ip", "").lower()
            ]
        if start_time:
            events = [e for e in events if e["created_at"] >= start_time]
        if end_time:
            events = [e for e in events if e["created_at"] <= end_time]

        # 分页
        total = len(events)
        offset = (page - 1) * page_size
        paged_events = events[offset:offset + page_size]
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        return {
            "items": paged_events,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_event_by_id(self, event_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 获取安全事件

        Args:
            event_id: 事件 ID

        Returns:
            事件详情，不存在返回 None
        """
        with self._lock:
            for event in self._security_events:
                if event["id"] == event_id:
                    return event
        return None

    def resolve_event(
        self,
        event_id: int,
        resolution_note: str = "",
        resolved_by: str = "system",
        status: str = "resolved",
    ) -> Optional[Dict[str, Any]]:
        """处理安全事件

        Args:
            event_id: 事件 ID
            resolution_note: 处理说明
            resolved_by: 处理人
            status: 事件状态

        Returns:
            更新后的事件，不存在返回 None
        """
        with self._lock:
            for event in self._security_events:
                if event["id"] == event_id:
                    event["status"] = status
                    event["resolved_by"] = resolved_by
                    event["resolved_at"] = datetime.now().isoformat()
                    event["resolution_note"] = resolution_note
                    return event
        return None

    # -----------------------------------------------------------------------
    # 审计日志
    # -----------------------------------------------------------------------

    def log_audit(
        self,
        user_id: str = "",
        username: str = "",
        role: str = "",
        module: str = "",
        action: str = "",
        resource_type: str = "",
        resource_id: str = "",
        description: str = "",
        source_ip: str = "",
        user_agent: str = "",
        request_method: str = "",
        request_path: str = "",
        request_params: Optional[Dict[str, Any]] = None,
        response_status: int = 0,
        status: str = "success",
        error_message: str = "",
        duration_ms: int = 0,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记录审计日志

        Args:
            user_id: 用户 ID
            username: 用户名
            role: 角色
            module: 模块
            action: 操作类型
            resource_type: 资源类型
            resource_id: 资源 ID
            description: 操作描述
            source_ip: 来源 IP
            user_agent: 用户代理
            request_method: 请求方法
            request_path: 请求路径
            request_params: 请求参数
            response_status: 响应状态码
            status: 操作状态
            error_message: 错误信息
            duration_ms: 耗时（毫秒）
            extra_data: 附加数据

        Returns:
            创建的审计记录
        """
        with self._lock:
            self._log_id_counter += 1

            log = {
                "id": self._log_id_counter,
                "user_id": user_id,
                "username": username,
                "role": role,
                "module": module,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "description": description,
                "source_ip": source_ip,
                "user_agent": user_agent,
                "request_method": request_method,
                "request_path": request_path,
                "request_params": request_params or {},
                "response_status": response_status,
                "status": status,
                "error_message": error_message,
                "duration_ms": duration_ms,
                "extra_data": extra_data or {},
                "created_at": datetime.now().isoformat(),
            }

            self._audit_logs.append(log)
            self._stats["total_logs"] += 1

            # 限制最大条数
            if len(self._audit_logs) > self._max_logs:
                self._audit_logs = self._audit_logs[-self._max_logs:]

            return log

    def get_audit_logs(
        self,
        user_id: Optional[str] = None,
        module: Optional[str] = None,
        action: Optional[str] = None,
        status: Optional[str] = None,
        source_ip: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """查询审计日志

        Args:
            user_id: 用户 ID 筛选
            module: 模块筛选
            action: 操作类型筛选
            status: 状态筛选
            source_ip: 来源 IP 筛选
            keyword: 关键词搜索
            page: 页码
            page_size: 每页数量

        Returns:
            分页结果字典
        """
        with self._lock:
            logs = list(self._audit_logs)

        # 倒序排列
        logs.reverse()

        # 过滤
        if user_id:
            logs = [l for l in logs if l["user_id"] == user_id]
        if module:
            logs = [l for l in logs if l["module"] == module]
        if action:
            logs = [l for l in logs if l["action"] == action]
        if status:
            logs = [l for l in logs if l["status"] == status]
        if source_ip:
            logs = [l for l in logs if l["source_ip"] == source_ip]
        if keyword:
            kw = keyword.lower()
            logs = [
                l for l in logs
                if kw in l.get("description", "").lower()
                or kw in l.get("username", "").lower()
                or kw in l.get("module", "").lower()
            ]

        # 分页
        total = len(logs)
        offset = (page - 1) * page_size
        paged_logs = logs[offset:offset + page_size]
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        return {
            "items": paged_logs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    # -----------------------------------------------------------------------
    # 统计分析
    # -----------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取审计统计数据

        Returns:
            统计字典
        """
        self._check_day_reset()

        with self._lock:
            # 统计未处理的高危事件
            active_high = sum(
                1 for e in self._security_events
                if e["status"] == "active" and e["severity"] in ("high", "critical")
            )
            active_medium = sum(
                1 for e in self._security_events
                if e["status"] == "active" and e["severity"] == "medium"
            )
            active_low = sum(
                1 for e in self._security_events
                if e["status"] == "active" and e["severity"] == "low"
            )

            # 攻击来源 IP TOP 10
            ip_counts: Dict[str, int] = defaultdict(int)
            for event in self._security_events:
                if event["source_ip"]:
                    ip_counts[event["source_ip"]] += 1
            top_ips = sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            top_source_ips = [
                {"ip": ip, "count": count}
                for ip, count in top_ips
            ]

            # 趋势数据（最近 24 小时，按小时）
            trend_data = self._get_trend_data()

            return {
                "total_events": self._stats["total_events"],
                "events_today": self._stats["events_today"],
                "events_this_week": self._get_week_events(),
                "high_severity_count": active_high,
                "medium_severity_count": active_medium,
                "low_severity_count": active_low,
                "events_by_type": dict(self._stats["events_by_type"]),
                "events_by_severity": dict(self._stats["events_by_severity"]),
                "top_source_ips": top_source_ips,
                "trend_data": trend_data,
                "total_audit_logs": self._stats["total_logs"],
                "waf_blocks_today": self._stats["waf_blocks_today"],
            }

    def get_recent_stats(self) -> Dict[str, Any]:
        """获取近期统计数据（快速调用）

        Returns:
            简要统计字典
        """
        self._check_day_reset()
        with self._lock:
            return {
                "events_today": self._stats["events_today"],
                "waf_blocks_today": self._stats["waf_blocks_today"],
                "total_events": self._stats["total_events"],
            }

    def get_dashboard_data(self) -> Dict[str, Any]:
        """获取仪表盘数据

        Returns:
            仪表盘完整数据
        """
        stats = self.get_stats()

        # 攻击类型分布
        attack_distribution = [
            {"type": k, "count": v}
            for k, v in stats["events_by_type"].items()
        ]
        attack_distribution.sort(key=lambda x: x["count"], reverse=True)

        # 威胁级别分布
        severity_distribution = [
            {"level": k, "count": v}
            for k, v in stats["events_by_severity"].items()
        ]

        return {
            "summary": {
                "total_events": stats["total_events"],
                "today_events": stats["events_today"],
                "high_risk": stats["high_severity_count"],
                "waf_blocks_today": stats["waf_blocks_today"],
            },
            "attack_distribution": attack_distribution,
            "severity_distribution": severity_distribution,
            "top_source_ips": stats["top_source_ips"],
            "trend_data": stats["trend_data"],
        }

    def _get_trend_data(self) -> List[Dict[str, Any]]:
        """获取趋势数据（最近 24 小时）

        Returns:
            按小时统计的趋势数据
        """
        now = datetime.now()
        trend = []
        for i in range(23, -1, -1):
            hour_time = now - timedelta(hours=i)
            hour_key = hour_time.strftime("%Y-%m-%d %H:00")
            count = self._stats["events_by_hour"].get(hour_key, 0)
            trend.append({
                "hour": hour_time.strftime("%H:00"),
                "count": count,
                "time": hour_key,
            })
        return trend

    def _get_week_events(self) -> int:
        """获取本周事件数"""
        now = time.time()
        week_ago = now - 7 * 86400
        count = 0
        for event in self._security_events:
            if event.get("created_timestamp", 0) >= week_ago:
                count += 1
        return count

    def _check_day_reset(self) -> None:
        """检查并重置每日统计"""
        now = time.time()
        if now - self._stats["start_of_day"] >= 86400:
            self._stats["events_today"] = 0
            self._stats["waf_blocks_today"] = 0
            self._stats["start_of_day"] = now

            # 清理超过 48 小时的小时统计
            cutoff = (now - 48 * 3600)
            cutoff_str = datetime.fromtimestamp(cutoff).strftime("%Y-%m-%d %H:00")
            expired_hours = [
                h for h in self._stats["events_by_hour"].keys()
                if h < cutoff_str
            ]
            for h in expired_hours:
                del self._stats["events_by_hour"][h]


# ===========================================================================
# 单例管理
# ===========================================================================

_audit_service: Optional[AuditService] = None


def get_audit_service() -> AuditService:
    """获取审计服务单例

    Returns:
        AuditService 实例
    """
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service


# 兼容直接运行测试
if __name__ == "__main__":
    audit = get_audit_service()
    print("审计服务已初始化")
    print()

    # 测试记录事件
    for i in range(5):
        audit.log_security_event(
            event_type="waf_block",
            severity="high",
            source_ip=f"192.168.1.{100 + i}",
            target_path="/api/test",
            method="GET",
            description=f"测试事件 {i+1}",
            rule_name="sql_injection_keyword",
        )

    audit.log_security_event(
        event_type="auth_fail",
        severity="medium",
        source_ip="10.0.0.50",
        description="登录失败",
    )

    # 测试查询
    result = audit.get_security_events(page=1, page_size=10)
    print(f"安全事件总数: {result['total']}")
    print(f"当前页: {result['page']}/{result['total_pages']}")
    print()

    # 测试统计
    stats = audit.get_stats()
    print("统计数据:")
    print(f"  总事件数: {stats['total_events']}")
    print(f"  今日事件: {stats['events_today']}")
    print(f"  高危事件: {stats['high_severity_count']}")
    print(f"  按类型: {stats['events_by_type']}")
    print(f"  TOP IP: {stats['top_source_ips'][:3]}")
