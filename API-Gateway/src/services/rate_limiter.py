"""
云汐 API 网关 - 速率限制
"""
import time
import asyncio
from typing import Dict
from collections import defaultdict


class RateLimiter:
    """令牌桶速率限制器"""
    
    def __init__(self, total_limit: int = 600, per_ip_limit: int = 100):
        """
        初始化速率限制器
        
        Args:
            total_limit: 全局限速（请求/分钟）
            per_ip_limit: 单IP限速（请求/分钟）
        """
        self.total_limit = total_limit
        self.per_ip_limit = per_ip_limit
        
        self._total_tokens = total_limit
        self._total_last_refill = time.time()
        
        self._ip_tokens: Dict[str, float] = defaultdict(lambda: float(per_ip_limit))
        self._ip_last_refill: Dict[str, float] = defaultdict(time.time)
        
        self._lock = asyncio.Lock()
    
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
    
    async def check_rate_limit(self, ip: str) -> bool:
        """
        检查是否超过速率限制
        
        Args:
            ip: 请求IP
        
        Returns:
            True 表示允许通过，False 表示超过限制
        """
        async with self._lock:
            self._refill_total()
            self._refill_ip(ip)
            
            if self._total_tokens < 1:
                return False
            
            if self._ip_tokens[ip] < 1:
                return False
            
            self._total_tokens -= 1
            self._ip_tokens[ip] -= 1
            return True
    
    def get_stats(self) -> dict:
        """获取限速统计"""
        return {
            "total_limit": self.total_limit,
            "total_remaining": int(self._total_tokens),
            "per_ip_limit": self.per_ip_limit,
        }


# 全局速率限制器实例
_rate_limiter = None


def get_rate_limiter() -> RateLimiter:
    """获取全局速率限制器实例"""
    global _rate_limiter
    if _rate_limiter is None:
        from ..config import settings
        _rate_limiter = RateLimiter(
            total_limit=settings.rate_limit_per_minute,
            per_ip_limit=settings.rate_limit_per_ip,
        )
    return _rate_limiter
