"""
云汐 M12 安全盾 - IP 过滤服务
提供 IP 黑白名单管理和 IP 访问控制功能，支持：

1. IP 黑名单管理（封禁）
2. IP 白名单管理（放行）
3. 单个 IP / CIDR 段 / IP 范围支持
4. 自动封禁和自动解封
5. IP 地理位置信息（预留接口）
"""

import ipaddress
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field


# ===========================================================================
# IP 条目数据类
# ===========================================================================

@dataclass
class IpEntry:
    """IP 条目数据类"""
    ip_address: str
    ip_type: str = "single"  # single / cidr / range
    reason: str = ""
    severity: str = "medium"
    source: str = "manual"
    added_by: str = "system"
    added_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None  # None = 永久
    is_active: bool = True
    hit_count: int = 0
    last_hit_at: Optional[float] = None
    description: str = ""
    extra_data: dict = field(default_factory=dict)

    # 内部使用：解析后的 IP 网络对象（用于 CIDR 匹配）
    _network: Optional[ipaddress.ip_network] = None

    def __post_init__(self):
        """初始化后解析 IP 网络"""
        try:
            if self.ip_type == "cidr":
                self._network = ipaddress.ip_network(self.ip_address, strict=False)
            elif self.ip_type == "single":
                self._network = ipaddress.ip_network(self.ip_address)
        except ValueError:
            self._network = None


# ===========================================================================
# IP 过滤器
# ===========================================================================

class IpFilter:
    """
    IP 过滤器

    管理 IP 黑白名单，提供 IP 访问控制功能。
    支持单个 IP、CIDR 段和 IP 范围的匹配。
    线程安全，支持高并发访问。
    """

    def __init__(self):
        """初始化 IP 过滤器"""
        # 黑名单：key -> IpEntry
        self._blacklist: Dict[str, IpEntry] = {}
        # 白名单：key -> IpEntry
        self._whitelist: Dict[str, IpEntry] = {}

        # 快速查找集合（用于单 IP 快速匹配）
        self._black_ips: Set[str] = set()
        self._white_ips: Set[str] = set()

        # CIDR 列表（用于范围匹配）
        self._black_cidrs: List[IpEntry] = []
        self._white_cidrs: List[IpEntry] = []

        # 自动封禁计数器：ip -> (count, first_time)
        self._failure_counts: Dict[str, Tuple[int, float]] = {}

        # 线程锁
        self._lock = threading.Lock()

        # 清理相关
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 每 5 分钟清理一次

    # -----------------------------------------------------------------------
    # 黑名单管理
    # -----------------------------------------------------------------------

    def add_to_blacklist(
        self,
        ip_address: str,
        reason: str = "",
        severity: str = "medium",
        source: str = "manual",
        added_by: str = "system",
        expires_at: Optional[datetime] = None,
        description: str = "",
    ) -> IpEntry:
        """添加 IP 到黑名单

        Args:
            ip_address: IP 地址或 CIDR 段
            reason: 封禁原因
            severity: 威胁级别
            source: 来源
            added_by: 操作人
            expires_at: 过期时间
            description: 描述

        Returns:
            创建的 IP 条目
        """
        with self._lock:
            ip_type = self._detect_ip_type(ip_address)
            entry = IpEntry(
                ip_address=ip_address,
                ip_type=ip_type,
                reason=reason,
                severity=severity,
                source=source,
                added_by=added_by,
                expires_at=expires_at.timestamp() if expires_at else None,
                description=description,
            )

            self._blacklist[ip_address] = entry

            # 更新快速查找结构
            if ip_type == "single":
                self._black_ips.add(ip_address)
            elif ip_type == "cidr":
                self._black_cidrs.append(entry)

            return entry

    def remove_from_blacklist(self, ip_address: str) -> bool:
        """从黑名单移除 IP

        Args:
            ip_address: IP 地址或 CIDR 段

        Returns:
            是否移除成功
        """
        with self._lock:
            entry = self._blacklist.pop(ip_address, None)
            if not entry:
                return False

            if entry.ip_type == "single":
                self._black_ips.discard(ip_address)
            elif entry.ip_type == "cidr":
                self._black_cidrs = [e for e in self._black_cidrs if e.ip_address != ip_address]

            return True

    def get_blacklist(
        self,
        severity: Optional[str] = None,
        active_only: bool = True,
    ) -> List[IpEntry]:
        """获取黑名单列表

        Args:
            severity: 按威胁级别筛选
            active_only: 只返回生效的条目

        Returns:
            黑名单条目列表
        """
        self._maybe_cleanup()
        with self._lock:
            entries = list(self._blacklist.values())
            if active_only:
                entries = [e for e in entries if e.is_active]
            if severity:
                entries = [e for e in entries if e.severity == severity]
            return entries

    # -----------------------------------------------------------------------
    # 白名单管理
    # -----------------------------------------------------------------------

    def add_to_whitelist(
        self,
        ip_address: str,
        reason: str = "",
        source: str = "manual",
        added_by: str = "system",
        expires_at: Optional[datetime] = None,
        description: str = "",
    ) -> IpEntry:
        """添加 IP 到白名单

        Args:
            ip_address: IP 地址或 CIDR 段
            reason: 添加原因
            source: 来源
            added_by: 操作人
            expires_at: 过期时间
            description: 描述

        Returns:
            创建的 IP 条目
        """
        with self._lock:
            ip_type = self._detect_ip_type(ip_address)
            entry = IpEntry(
                ip_address=ip_address,
                ip_type=ip_type,
                reason=reason,
                source=source,
                added_by=added_by,
                expires_at=expires_at.timestamp() if expires_at else None,
                description=description,
            )

            self._whitelist[ip_address] = entry

            # 更新快速查找结构
            if ip_type == "single":
                self._white_ips.add(ip_address)
            elif ip_type == "cidr":
                self._white_cidrs.append(entry)

            return entry

    def remove_from_whitelist(self, ip_address: str) -> bool:
        """从白名单移除 IP

        Args:
            ip_address: IP 地址或 CIDR 段

        Returns:
            是否移除成功
        """
        with self._lock:
            entry = self._whitelist.pop(ip_address, None)
            if not entry:
                return False

            if entry.ip_type == "single":
                self._white_ips.discard(ip_address)
            elif entry.ip_type == "cidr":
                self._white_cidrs = [e for e in self._white_cidrs if e.ip_address != ip_address]

            return True

    def get_whitelist(self, active_only: bool = True) -> List[IpEntry]:
        """获取白名单列表

        Args:
            active_only: 只返回生效的条目

        Returns:
            白名单条目列表
        """
        self._maybe_cleanup()
        with self._lock:
            entries = list(self._whitelist.values())
            if active_only:
                entries = [e for e in entries if e.is_active]
            return entries

    # -----------------------------------------------------------------------
    # IP 检测
    # -----------------------------------------------------------------------

    def is_blacklisted(self, ip_address: str) -> Tuple[bool, Optional[IpEntry]]:
        """检查 IP 是否在黑名单中

        Args:
            ip_address: 要检查的 IP 地址

        Returns:
            (是否在黑名单, 匹配的条目)
        """
        self._maybe_cleanup()

        # 快速匹配：单 IP
        if ip_address in self._black_ips:
            entry = self._blacklist.get(ip_address)
            if entry and entry.is_active and not self._is_expired(entry):
                self._record_hit(entry)
                return True, entry

        # CIDR 匹配
        try:
            ip_obj = ipaddress.ip_address(ip_address)
            for entry in self._black_cidrs:
                if not entry.is_active or self._is_expired(entry):
                    continue
                if entry._network and ip_obj in entry._network:
                    self._record_hit(entry)
                    return True, entry
        except ValueError:
            pass

        return False, None

    def is_whitelisted(self, ip_address: str) -> Tuple[bool, Optional[IpEntry]]:
        """检查 IP 是否在白名单中

        Args:
            ip_address: 要检查的 IP 地址

        Returns:
            (是否在白名单, 匹配的条目)
        """
        self._maybe_cleanup()

        # 快速匹配：单 IP
        if ip_address in self._white_ips:
            entry = self._whitelist.get(ip_address)
            if entry and entry.is_active and not self._is_expired(entry):
                return True, entry

        # CIDR 匹配
        try:
            ip_obj = ipaddress.ip_address(ip_address)
            for entry in self._white_cidrs:
                if not entry.is_active or self._is_expired(entry):
                    continue
                if entry._network and ip_obj in entry._network:
                    return True, entry
        except ValueError:
            pass

        return False, None

    def check_ip(self, ip_address: str) -> Dict:
        """综合检查 IP 状态

        Args:
            ip_address: 要检查的 IP 地址

        Returns:
            IP 状态字典
        """
        whitelisted, wl_entry = self.is_whitelisted(ip_address)
        blacklisted, bl_entry = self.is_blacklisted(ip_address)

        # 白名单优先级最高
        if whitelisted:
            risk_level = "low"
            recommendation = "allow"
        elif blacklisted:
            risk_level = bl_entry.severity if bl_entry else "high"
            recommendation = "block"
        else:
            risk_level = "low"
            recommendation = "allow"

        return {
            "ip_address": ip_address,
            "is_blacklisted": blacklisted,
            "is_whitelisted": whitelisted,
            "blacklist_info": bl_entry.__dict__ if bl_entry else None,
            "whitelist_info": wl_entry.__dict__ if wl_entry else None,
            "risk_level": risk_level,
            "recommendation": recommendation,
        }

    # -----------------------------------------------------------------------
    # 自动封禁
    # -----------------------------------------------------------------------

    def record_failure(
        self,
        ip_address: str,
        threshold: int = 10,
        ban_minutes: int = 60,
    ) -> bool:
        """记录失败尝试，达到阈值自动封禁

        Args:
            ip_address: IP 地址
            threshold: 失败次数阈值
            ban_minutes: 封禁时长（分钟）

        Returns:
            是否触发了自动封禁
        """
        with self._lock:
            now = time.time()
            count, first_time = self._failure_counts.get(ip_address, (0, now))

            # 如果距离第一次失败超过 10 分钟，重置计数
            if now - first_time > 600:
                count = 0
                first_time = now

            count += 1
            self._failure_counts[ip_address] = (count, first_time)

            # 达到阈值，自动封禁
            if count >= threshold:
                expires_at = datetime.fromtimestamp(now + ban_minutes * 60)
                self._auto_ban(ip_address, expires_at, f"自动封禁：失败 {count} 次")
                # 重置计数
                self._failure_counts.pop(ip_address, None)
                return True

            return False

    def _auto_ban(self, ip_address: str, expires_at: datetime, reason: str) -> None:
        """自动封禁（内部方法，需在锁内调用）"""
        ip_type = self._detect_ip_type(ip_address)
        entry = IpEntry(
            ip_address=ip_address,
            ip_type=ip_type,
            reason=reason,
            severity="high",
            source="auto",
            added_by="system",
            expires_at=expires_at.timestamp(),
        )

        self._blacklist[ip_address] = entry
        if ip_type == "single":
            self._black_ips.add(ip_address)
        elif ip_type == "cidr":
            self._black_cidrs.append(entry)

    def reset_failure_count(self, ip_address: str) -> None:
        """重置失败计数

        Args:
            ip_address: IP 地址
        """
        with self._lock:
            self._failure_counts.pop(ip_address, None)

    # -----------------------------------------------------------------------
    # 统计信息
    # -----------------------------------------------------------------------

    def get_counts(self) -> Tuple[int, int]:
        """获取黑白名单数量

        Returns:
            (黑名单数量, 白名单数量)
        """
        self._maybe_cleanup()
        with self._lock:
            bl_count = sum(1 for e in self._blacklist.values() if e.is_active)
            wl_count = sum(1 for e in self._whitelist.values() if e.is_active)
            return bl_count, wl_count

    def get_stats(self) -> Dict:
        """获取详细统计信息

        Returns:
            统计字典
        """
        self._maybe_cleanup()
        with self._lock:
            # 按严重级别统计
            by_severity: Dict[str, int] = {}
            total_hits = 0
            top_hits: List[IpEntry] = []

            for entry in self._blacklist.values():
                if not entry.is_active:
                    continue
                sev = entry.severity
                by_severity[sev] = by_severity.get(sev, 0) + 1
                total_hits += entry.hit_count
                top_hits.append(entry)

            # 按命中次数排序取前 10
            top_hits.sort(key=lambda e: e.hit_count, reverse=True)
            top_10 = [
                {"ip": e.ip_address, "hits": e.hit_count, "severity": e.severity}
                for e in top_hits[:10]
            ]

            return {
                "blacklist_count": len(self._blacklist),
                "whitelist_count": len(self._whitelist),
                "active_blacklist": sum(1 for e in self._blacklist.values() if e.is_active),
                "active_whitelist": sum(1 for e in self._whitelist.values() if e.is_active),
                "by_severity": by_severity,
                "total_hits": total_hits,
                "top_blocked_ips": top_10,
                "auto_ban_threshold": 10,
            }

    # -----------------------------------------------------------------------
    # 内部方法
    # -----------------------------------------------------------------------

    def _detect_ip_type(self, ip_address: str) -> str:
        """检测 IP 类型

        Args:
            ip_address: IP 地址字符串

        Returns:
            IP 类型：single / cidr / range
        """
        if "/" in ip_address:
            return "cidr"
        if "-" in ip_address:
            return "range"
        return "single"

    def _is_expired(self, entry: IpEntry) -> bool:
        """检查条目是否过期

        Args:
            entry: IP 条目

        Returns:
            是否过期
        """
        if entry.expires_at is None:
            return False
        return time.time() > entry.expires_at

    def _record_hit(self, entry: IpEntry) -> None:
        """记录命中（更新计数）"""
        with self._lock:
            entry.hit_count += 1
            entry.last_hit_at = time.time()

    def _maybe_cleanup(self) -> None:
        """定期清理过期条目"""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        with self._lock:
            # 双重检查
            if now - self._last_cleanup < self._cleanup_interval:
                return

            self._last_cleanup = now

            # 清理过期黑名单
            expired_black = [
                ip for ip, entry in self._blacklist.items()
                if self._is_expired(entry)
            ]
            for ip in expired_black:
                entry = self._blacklist.pop(ip)
                if entry.ip_type == "single":
                    self._black_ips.discard(ip)
                elif entry.ip_type == "cidr":
                    self._black_cidrs = [e for e in self._black_cidrs if e.ip_address != ip]

            # 清理过期白名单
            expired_white = [
                ip for ip, entry in self._whitelist.items()
                if self._is_expired(entry)
            ]
            for ip in expired_white:
                entry = self._whitelist.pop(ip)
                if entry.ip_type == "single":
                    self._white_ips.discard(ip)
                elif entry.ip_type == "cidr":
                    self._white_cidrs = [e for e in self._white_cidrs if e.ip_address != ip]

            # 清理过期的失败计数
            expired_failures = [
                ip for ip, (count, first_time) in self._failure_counts.items()
                if now - first_time > 1800  # 30 分钟
            ]
            for ip in expired_failures:
                self._failure_counts.pop(ip, None)


# ===========================================================================
# 单例管理
# ===========================================================================

_ip_filter: Optional[IpFilter] = None


def get_ip_filter() -> IpFilter:
    """获取 IP 过滤器单例

    Returns:
        IpFilter 实例
    """
    global _ip_filter
    if _ip_filter is None:
        _ip_filter = IpFilter()
    return _ip_filter


# 兼容直接运行测试
if __name__ == "__main__":
    ipf = get_ip_filter()
    print("IP 过滤器已初始化")
    print()

    # 测试添加黑名单
    ipf.add_to_blacklist("192.168.1.100", reason="恶意扫描", severity="high")
    ipf.add_to_blacklist("10.0.0.0/24", reason="内网网段", severity="medium")

    # 测试添加白名单
    ipf.add_to_whitelist("127.0.0.1", reason="本地回环")

    # 测试检测
    print("检测 192.168.1.100:")
    result = ipf.check_ip("192.168.1.100")
    print(f"  黑名单: {result['is_blacklisted']}")
    print(f"  风险级别: {result['risk_level']}")
    print(f"  建议: {result['recommendation']}")

    print()
    print("检测 127.0.0.1:")
    result = ipf.check_ip("127.0.0.1")
    print(f"  白名单: {result['is_whitelisted']}")
    print(f"  建议: {result['recommendation']}")

    print()
    print("检测 10.0.0.50 (CIDR 匹配):")
    result = ipf.check_ip("10.0.0.50")
    print(f"  黑名单: {result['is_blacklisted']}")
    print(f"  建议: {result['recommendation']}")

    print()
    bl_count, wl_count = ipf.get_counts()
    print(f"黑名单数量: {bl_count}")
    print(f"白名单数量: {wl_count}")
