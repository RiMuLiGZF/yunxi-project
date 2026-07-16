"""
云汐 API 网关 - 熔断器
"""
import time
import asyncio
from enum import Enum
from typing import Dict, Optional
from collections import defaultdict


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"           # 关闭：正常转发
    OPEN = "open"               # 打开：熔断，拒绝请求
    HALF_OPEN = "half_open"     # 半开：尝试恢复，放行少量请求


class CircuitBreaker:
    """熔断器实现"""
    
    def __init__(self, failure_threshold: int = 5, recovery_time: int = 30):
        """
        初始化熔断器
        
        Args:
            failure_threshold: 连续失败次数阈值
            recovery_time: 熔断恢复时间（秒）
        """
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        
        self._states: Dict[str, CircuitState] = defaultdict(lambda: CircuitState.CLOSED)
        self._failure_counts: Dict[str, int] = defaultdict(int)
        self._last_failure_time: Dict[str, float] = defaultdict(float)
        self._half_open_attempts: Dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
    
    async def can_execute(self, key: str) -> bool:
        """
        检查是否可以执行请求
        
        Args:
            key: 熔断器标识（如模块名）
        
        Returns:
            True 表示可以执行，False 表示熔断中
        """
        async with self._lock:
            state = self._states[key]
            
            if state == CircuitState.CLOSED:
                return True
            
            if state == CircuitState.OPEN:
                # 检查是否过了恢复时间
                if time.time() - self._last_failure_time[key] >= self.recovery_time:
                    self._states[key] = CircuitState.HALF_OPEN
                    self._half_open_attempts[key] = 0
                    return True
                return False
            
            if state == CircuitState.HALF_OPEN:
                # 半开状态下只允许少量请求通过
                if self._half_open_attempts[key] < 3:
                    self._half_open_attempts[key] += 1
                    return True
                return False
            
            return True
    
    async def record_success(self, key: str):
        """记录请求成功"""
        async with self._lock:
            if self._states[key] == CircuitState.HALF_OPEN:
                # 半开状态下成功，恢复到关闭状态
                self._states[key] = CircuitState.CLOSED
                self._failure_counts[key] = 0
                self._half_open_attempts[key] = 0
            else:
                self._failure_counts[key] = 0
    
    async def record_failure(self, key: str):
        """记录请求失败"""
        async with self._lock:
            self._failure_counts[key] += 1
            self._last_failure_time[key] = time.time()
            
            if self._failure_counts[key] >= self.failure_threshold:
                self._states[key] = CircuitState.OPEN
                self._half_open_attempts[key] = 0
    
    def get_state(self, key: str) -> CircuitState:
        """获取熔断器状态"""
        return self._states[key]
    
    def get_stats(self) -> dict:
        """获取所有熔断器统计"""
        return {
            key: {
                "state": state.value,
                "failures": self._failure_counts[key],
                "last_failure": self._last_failure_time[key],
            }
            for key, state in self._states.items()
        }


# 全局熔断器实例
_circuit_breaker: Optional[CircuitBreaker] = None


def get_circuit_breaker() -> CircuitBreaker:
    """获取全局熔断器实例"""
    global _circuit_breaker
    if _circuit_breaker is None:
        from ..config import settings
        _circuit_breaker = CircuitBreaker(
            failure_threshold=settings.circuit_breaker_threshold,
            recovery_time=settings.circuit_breaker_recovery_time,
        )
    return _circuit_breaker
