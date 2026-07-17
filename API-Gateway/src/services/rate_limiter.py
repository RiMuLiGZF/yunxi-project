"""
云汐 API 网关 - 速率限制服务

提供多层级速率限制，防止暴力破解、DDoS、接口滥用：
1. 全局限速（令牌桶）
2. 单 IP 限速（令牌桶）
3. 分级限速（敏感接口更严格）
4. 渐进式封禁（多次超限后延长封禁时间）
5. 用户级限速（登录用户按用户ID限速）
6. 滑动窗口精确计数（可选，用于关键接口）
"""
import time
import asyncio
import threading
from typing import Dict, Optional, Tuple, Any
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class RateLimitTier:
    """分级限速配置"""
    name: str
    requests_per_minute: int
    requests_per_hour: int = 0
    burst_size: int = 0  # 突发大小，0=使用默认
    description: str = ""


# 预定义的限速级别
RATE_LIMIT_TIERS = {
    "public": RateLimitTier(
        name="public",
        requests_per_minute=100,
        requests_per_hour=2000,
        description="公开接口（默认）",
    ),
    "sensitive": RateLimitTier(
        name="sensitive",
        requests_per_minute=10,
        requests_per_hour=100,
        description="敏感接口（登录、注册、验证码等）",
    ),
    "strict": RateLimitTier(
        name="strict",
        requests_per_minute=5,
        requests_per_hour=20,
        description="严格接口（密码重置、API Key管理等）",
    ),
    "admin": RateLimitTier(
        name="admin",
        requests_per_minute=30,
        requests_per_hour=500,
        description="管理接口",
    ),
    "mcp": RateLimitTier(
        name="mcp",
        requests_per_minute=60,
        requests_per_hour=1000,
        description="MCP 工具调用接口",
    ),
}


@dataclass
class BanEntry:
    """封禁记录"""
    ip: str
    until: float  # 解封时间戳
    reason: str
    count: int = 1  # 累计超限次数


@dataclass
class SlidingWindowCounter:
    """滑动窗口计数器（用于精确的短时间窗口）"""
    requests: list = field(default_factory=list)  # 时间戳列表
    window_seconds: int = 60
    max_requests: int = 100
    
    def add_and_check(self) -> Tuple[bool, int]:
        """添加请求并检查是否超限.
        
        Returns:
            (是否允许, 窗口内剩余请求数)
        """
        now = time.time()
        # 清理过期的请求记录
        cutoff = now - self.window_seconds
        self.requests = [t for t in self.requests if t > cutoff]
        
        if len(self.requests) >= self.max_requests:
            return False, 0
        
        self.requests.append(now)
        return True, self.max_requests - len(self.requests)


class RateLimiter:
    """增强版速率限制器
    
    支持：
    - 令牌桶全局/单IP限速
    - 分级限速（不同接口不同级别）
    - 渐进式封禁（连续超限自动封禁，时间递增）
    - 滑动窗口精确计数
    - 用户级限速（登录用户）
    """
    
    def __init__(self, total_limit: int = 600, per_ip_limit: int = 100):
        """
        初始化速率限制器
        
        Args:
            total_limit: 全局限速（请求/分钟）
            per_ip_limit: 单IP限速（请求/分钟）
        """
        self.total_limit = total_limit
        self.per_ip_limit = per_ip_limit
        
        # 令牌桶 - 全局
        self._total_tokens = float(total_limit)
        self._total_last_refill = time.time()
        
        # 令牌桶 - 单IP
        self._ip_tokens: Dict[str, float] = defaultdict(lambda: float(per_ip_limit))
        self._ip_last_refill: Dict[str, float] = defaultdict(time.time)
        
        # 渐进式封禁
        self._ban_entries: Dict[str, BanEntry] = {}
        self._ip_violation_count: Dict[str, int] = defaultdict(int)
        
        # 分级限速 - 滑动窗口（用于敏感接口）
        self._tier_counters: Dict[str, Dict[str, SlidingWindowCounter]] = defaultdict(
            lambda: defaultdict(lambda: SlidingWindowCounter())
        )
        
        # 用户级限速（user_id -> 滑动窗口）
        self._user_counters: Dict[str, SlidingWindowCounter] = {}
        
        # 统计
        self._stats = {
            "total_requests": 0,
            "blocked_total": 0,
            "blocked_by_ip": 0,
            "blocked_by_tier": 0,
            "banned_ips": 0,
        }
        
        self._lock = asyncio.Lock()
        self._thread_lock = threading.Lock()  # 同步代码使用
    
    # ===================================================================
    # 令牌桶核心方法
    # ===================================================================
    
    def _refill_total(self):
        """补充全局限速令牌"""
        now = time.time()
        elapsed = now - self._total_last_refill
        refill = (elapsed / 60.0) * self.total_limit
        self._total_tokens = min(self.total_limit, self._total_tokens + refill)
        self._total_last_refill = now
    
    def _refill_ip(self, ip: str):
        """补充单IP限速令牌"""
        now = time.time()
        elapsed = now - self._ip_last_refill[ip]
        refill = (elapsed / 60.0) * self.per_ip_limit
        self._ip_tokens[ip] = min(self.per_ip_limit, self._ip_tokens[ip] + refill)
        self._ip_last_refill[ip] = now
    
    # ===================================================================
    # 封禁管理
    # ===================================================================
    
    def _check_ban(self, ip: str) -> bool:
        """检查IP是否被封禁.
        
        Returns:
            True = 被封禁，False = 未封禁
        """
        if ip not in self._ban_entries:
            return False
        
        entry = self._ban_entries[ip]
        if time.time() > entry.until:
            # 封禁到期，移除
            del self._ban_entries[ip]
            return False
        
        return True
    
    def _register_violation(self, ip: str, reason: str = "rate_limit"):
        """记录一次超限，触发渐进式封禁.
        
        封禁策略：
        - 第1-3次超限：不封禁，仅记录
        - 第4-6次：封禁 5 分钟
        - 第7-10次：封禁 30 分钟
        - 第11+次：封禁 24 小时
        """
        self._ip_violation_count[ip] += 1
        count = self._ip_violation_count[ip]
        
        now = time.time()
        
        if count <= 3:
            return  # 仅警告，不封禁
        elif count <= 6:
            ban_seconds = 5 * 60  # 5分钟
        elif count <= 10:
            ban_seconds = 30 * 60  # 30分钟
        else:
            ban_seconds = 24 * 60 * 60  # 24小时
        
        self._ban_entries[ip] = BanEntry(
            ip=ip,
            until=now + ban_seconds,
            reason=reason,
            count=count,
        )
        self._stats["banned_ips"] = len(self._ban_entries)
    
    def unban_ip(self, ip: str) -> bool:
        """手动解封IP.
        
        Returns:
            True = 成功解封，False = IP未被封禁
        """
        with self._thread_lock:
            if ip in self._ban_entries:
                del self._ban_entries[ip]
                self._ip_violation_count.pop(ip, None)
                self._stats["banned_ips"] = len(self._ban_entries)
                return True
            return False
    
    # ===================================================================
    # 分级限速
    # ===================================================================
    
    def _check_tier_rate_limit(self, ip: str, tier: str) -> Tuple[bool, int]:
        """检查分级限速（滑动窗口）.
        
        Args:
            ip: 请求IP
            tier: 限速级别名称
        
        Returns:
            (是否允许, 剩余请求数)
        """
        tier_config = RATE_LIMIT_TIERS.get(tier)
        if not tier_config:
            return True, -1  # 未知级别，放行
        
        key = f"{tier}:{ip}"
        counter = self._tier_counters[tier].get(ip)
        
        if counter is None or counter.window_seconds != 60:
            counter = SlidingWindowCounter(
                window_seconds=60,
                max_requests=tier_config.requests_per_minute,
            )
            self._tier_counters[tier][ip] = counter
        
        return counter.add_and_check()
    
    # ===================================================================
    # 主要检查方法
    # ===================================================================
    
    async def check_rate_limit(
        self,
        ip: str,
        tier: str = "public",
        user_id: Optional[str] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        检查是否超过速率限制（完整检查链）
        
        检查顺序：
        1. 是否被封禁
        2. 分级限速（敏感接口更严格）
        3. 单 IP 令牌桶
        4. 全局令牌桶
        
        Args:
            ip: 请求IP
            tier: 限速级别（public/sensitive/strict/admin/mcp）
            user_id: 登录用户ID（可选）
        
        Returns:
            (是否允许, 拒绝原因, 限流信息头字典)
        """
        async with self._lock:
            self._stats["total_requests"] += 1
            
            # 1. 检查封禁
            if self._check_ban(ip):
                self._stats["blocked_total"] += 1
                entry = self._ban_entries[ip]
                remaining = int(entry.until - time.time())
                return False, "ip_banned", {
                    "X-RateLimit-Banned": "true",
                    "X-RateLimit-Ban-Remaining": str(remaining),
                    "X-RateLimit-Ban-Reason": entry.reason,
                }
            
            # 2. 分级限速（滑动窗口）
            tier_allowed, tier_remaining = self._check_tier_rate_limit(ip, tier)
            if not tier_allowed:
                self._stats["blocked_total"] += 1
                self._stats["blocked_by_tier"] += 1
                self._register_violation(ip, f"tier_{tier}_exceeded")
                tier_config = RATE_LIMIT_TIERS.get(tier)
                return False, "tier_rate_limit_exceeded", {
                    "X-RateLimit-Limit": str(tier_config.requests_per_minute if tier_config else 0),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Tier": tier,
                    "Retry-After": "60",
                }
            
            # 3. 单 IP 令牌桶
            self._refill_ip(ip)
            if self._ip_tokens[ip] < 1:
                self._stats["blocked_total"] += 1
                self._stats["blocked_by_ip"] += 1
                self._register_violation(ip, "ip_rate_limit_exceeded")
                return False, "ip_rate_limit_exceeded", {
                    "X-RateLimit-Limit": str(self.per_ip_limit),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": "60",
                }
            
            # 4. 全局令牌桶
            self._refill_total()
            if self._total_tokens < 1:
                self._stats["blocked_total"] += 1
                return False, "global_rate_limit_exceeded", {
                    "X-RateLimit-Limit": str(self.total_limit),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": "60",
                }
            
            # 允许通过，消耗令牌
            self._total_tokens -= 1
            self._ip_tokens[ip] -= 1
            
            # 返回限流信息头
            headers = {
                "X-RateLimit-Limit": str(self.per_ip_limit),
                "X-RateLimit-Remaining": str(int(self._ip_tokens[ip])),
                "X-RateLimit-Tier": tier,
            }
            if tier_remaining >= 0:
                headers["X-RateLimit-Tier-Remaining"] = str(tier_remaining)
            
            return True, "", headers
    
    # ===================================================================
    # 同步版本（用于非 async 上下文）
    # ===================================================================
    
    def check_rate_limit_sync(
        self,
        ip: str,
        tier: str = "public",
    ) -> Tuple[bool, str]:
        """同步版本的速率限制检查（用于中间件等同步上下文）.
        
        Args:
            ip: 请求IP
            tier: 限速级别
        
        Returns:
            (是否允许, 拒绝原因)
        """
        with self._thread_lock:
            # 1. 检查封禁
            if self._check_ban(ip):
                return False, "ip_banned"
            
            # 2. 分级限速
            tier_allowed, _ = self._check_tier_rate_limit(ip, tier)
            if not tier_allowed:
                self._register_violation(ip, f"tier_{tier}_exceeded")
                return False, "tier_rate_limit_exceeded"
            
            # 3. 单 IP
            self._refill_ip(ip)
            if self._ip_tokens[ip] < 1:
                self._register_violation(ip, "ip_rate_limit_exceeded")
                return False, "ip_rate_limit_exceeded"
            
            # 4. 全局
            self._refill_total()
            if self._total_tokens < 1:
                return False, "global_rate_limit_exceeded"
            
            self._total_tokens -= 1
            self._ip_tokens[ip] -= 1
            return True, ""
    
    # ===================================================================
    # 统计与管理
    # ===================================================================
    
    def get_stats(self) -> dict:
        """获取限速统计"""
        return {
            "total_limit": self.total_limit,
            "total_remaining": int(self._total_tokens),
            "per_ip_limit": self.per_ip_limit,
            "total_requests": self._stats["total_requests"],
            "blocked_total": self._stats["blocked_total"],
            "blocked_by_ip": self._stats["blocked_by_ip"],
            "blocked_by_tier": self._stats["blocked_by_tier"],
            "banned_ips": len(self._ban_entries),
            "active_ips": len(self._ip_tokens),
        }
    
    def get_ban_list(self) -> list:
        """获取封禁列表"""
        now = time.time()
        result = []
        for ip, entry in self._ban_entries.items():
            if now <= entry.until:
                result.append({
                    "ip": ip,
                    "until": entry.until,
                    "remaining_seconds": int(entry.until - now),
                    "reason": entry.reason,
                    "violation_count": entry.count,
                })
        return result
    
    def cleanup(self):
        """清理过期数据（定期调用）"""
        now = time.time()
        
        # 清理过期封禁
        expired_bans = [ip for ip, e in self._ban_entries.items() if now > e.until]
        for ip in expired_bans:
            del self._ban_entries[ip]
        
        # 清理长时间未活动的 IP 令牌桶（保留最近1小时活跃的）
        cutoff = now - 3600
        expired_ips = [ip for ip, t in self._ip_last_refill.items() if t < cutoff]
        for ip in expired_ips:
            self._ip_tokens.pop(ip, None)
            self._ip_last_refill.pop(ip, None)
            self._ip_violation_count.pop(ip, None)
        
        # 清理分级计数器
        for tier in list(self._tier_counters.keys()):
            tier_data = self._tier_counters[tier]
            expired = [ip for ip, c in tier_data.items() 
                       if c.requests and c.requests[-1] < cutoff]
            for ip in expired:
                del tier_data[ip]
        
        self._stats["banned_ips"] = len(self._ban_entries)


# 全局速率限制器实例
_rate_limiter: Optional[RateLimiter] = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter() -> RateLimiter:
    """获取全局速率限制器单例"""
    global _rate_limiter
    if _rate_limiter is None:
        with _rate_limiter_lock:
            if _rate_limiter is None:
                from ..config import settings
                _rate_limiter = RateLimiter(
                    total_limit=settings.rate_limit_per_minute,
                    per_ip_limit=settings.rate_limit_per_ip,
                )
    return _rate_limiter
