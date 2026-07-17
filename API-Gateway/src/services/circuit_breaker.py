"""
云汐 API 网关 - 熔断器（增强版）

熔断器模式：
- Closed（关闭）：正常转发请求，记录失败次数
- Open（打开）：熔断状态，直接拒绝请求
- Half-Open（半开）：尝试恢复，放行少量请求探测服务状态

增强特性：
- 按模块独立配置熔断阈值和恢复时间
- 支持降级响应（fallback）
- 熔断事件日志
- 统计信息完善
- 手动重置熔断器
"""
import time
import asyncio
import logging
from enum import Enum
from typing import Dict, Optional, Callable, Awaitable, Any
from collections import defaultdict

from ..config import settings, ModuleRoute

logger = logging.getLogger("yunxi-gateway.circuit_breaker")


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"           # 关闭：正常转发
    OPEN = "open"               # 打开：熔断，拒绝请求
    HALF_OPEN = "half_open"     # 半开：尝试恢复，放行少量请求


class CircuitBreakerConfig:
    """熔断器配置（按模块）"""

    def __init__(self, failure_threshold: int = 5, recovery_time: int = 30,
                 half_open_max_requests: int = 3):
        self.failure_threshold = failure_threshold      # 连续失败次数阈值
        self.recovery_time = recovery_time              # 熔断恢复时间（秒）
        self.half_open_max_requests = half_open_max_requests  # 半开状态最大探测请求数


class CircuitBreaker:
    """熔断器实现（增强版）

    支持：
    - 按模块独立配置
    - Closed/Open/Half-Open 三态
    - 半开状态探测
    - 降级响应
    - 统计与监控
    """

    def __init__(self, failure_threshold: int = 5, recovery_time: int = 30):
        """
        初始化熔断器

        Args:
            failure_threshold: 默认连续失败次数阈值
            recovery_time: 默认熔断恢复时间（秒）
        """
        self._default_config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            recovery_time=recovery_time,
        )

        # 按模块的配置
        self._configs: Dict[str, CircuitBreakerConfig] = {}

        # 运行时状态
        self._states: Dict[str, CircuitState] = defaultdict(lambda: CircuitState.CLOSED)
        self._failure_counts: Dict[str, int] = defaultdict(int)
        self._last_failure_time: Dict[str, float] = defaultdict(float)
        self._half_open_attempts: Dict[str, int] = defaultdict(int)
        self._half_open_successes: Dict[str, int] = defaultdict(int)
        self._last_state_change: Dict[str, float] = defaultdict(float)

        # 统计
        self._stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "total_requests": 0,
            "success_count": 0,
            "failure_count": 0,
            "rejected_count": 0,
            "state_changes": 0,
            "total_open_time": 0.0,
        })

        self._lock = asyncio.Lock()

        # 从路由配置初始化各模块的熔断器配置
        self._init_from_routes()

    def _init_from_routes(self):
        """从路由配置初始化各模块的熔断器配置"""
        for route in settings.routes:
            if route.enabled:
                self._configs[route.key] = CircuitBreakerConfig(
                    failure_threshold=route.cb_failure_threshold,
                    recovery_time=route.cb_recovery_time,
                )
                logger.info(
                    f"[CircuitBreaker] 初始化模块 {route.key} 熔断器配置: "
                    f"threshold={route.cb_failure_threshold}, "
                    f"recovery={route.cb_recovery_time}s"
                )

    def _get_config(self, key: str) -> CircuitBreakerConfig:
        """获取指定模块的熔断器配置"""
        if key not in self._configs:
            self._configs[key] = self._default_config
        return self._configs[key]

    def _get_route(self, key: str) -> Optional[ModuleRoute]:
        """根据key获取路由配置"""
        for route in settings.routes:
            if route.key == key:
                return route
        return None

    async def can_execute(self, key: str) -> bool:
        """
        检查是否可以执行请求

        Args:
            key: 熔断器标识（如模块名）

        Returns:
            True 表示可以执行，False 表示熔断中
        """
        async with self._lock:
            config = self._get_config(key)
            state = self._states[key]
            stats = self._stats[key]
            stats["total_requests"] += 1

            if state == CircuitState.CLOSED:
                return True

            if state == CircuitState.OPEN:
                # 检查是否过了恢复时间
                now = time.time()
                if now - self._last_failure_time[key] >= config.recovery_time:
                    # 切换到半开状态
                    self._states[key] = CircuitState.HALF_OPEN
                    self._half_open_attempts[key] = 0
                    self._half_open_successes[key] = 0
                    self._last_state_change[key] = now
                    stats["state_changes"] += 1
                    logger.info(f"[CircuitBreaker] {key}: OPEN -> HALF_OPEN (recovery timeout)")
                    return True
                stats["rejected_count"] += 1
                return False

            if state == CircuitState.HALF_OPEN:
                # 半开状态下只允许少量请求通过
                if self._half_open_attempts[key] < config.half_open_max_requests:
                    self._half_open_attempts[key] += 1
                    return True
                stats["rejected_count"] += 1
                return False

            return True

    async def record_success(self, key: str):
        """记录请求成功"""
        async with self._lock:
            stats = self._stats[key]
            stats["success_count"] += 1

            if self._states[key] == CircuitState.HALF_OPEN:
                self._half_open_successes[key] += 1
                config = self._get_config(key)

                # 半开状态下，如果连续成功次数达到阈值，则恢复到关闭状态
                if self._half_open_successes[key] >= config.half_open_max_requests:
                    self._states[key] = CircuitState.CLOSED
                    self._failure_counts[key] = 0
                    self._half_open_attempts[key] = 0
                    self._half_open_successes[key] = 0
                    self._last_state_change[key] = time.time()
                    stats["state_changes"] += 1
                    logger.info(f"[CircuitBreaker] {key}: HALF_OPEN -> CLOSED (recovery success)")
            else:
                # 关闭状态下，重置失败计数
                self._failure_counts[key] = 0

    async def record_failure(self, key: str):
        """记录请求失败"""
        async with self._lock:
            config = self._get_config(key)
            stats = self._stats[key]
            stats["failure_count"] += 1
            self._failure_counts[key] += 1
            self._last_failure_time[key] = time.time()

            state = self._states[key]

            if state == CircuitState.HALF_OPEN:
                # 半开状态下失败，立即回到熔断状态
                self._states[key] = CircuitState.OPEN
                self._half_open_attempts[key] = 0
                self._half_open_successes[key] = 0
                self._last_state_change[key] = time.time()
                stats["state_changes"] += 1
                logger.warning(f"[CircuitBreaker] {key}: HALF_OPEN -> OPEN (probe failed)")

            elif state == CircuitState.CLOSED:
                # 关闭状态下，达到失败阈值则熔断
                if self._failure_counts[key] >= config.failure_threshold:
                    self._states[key] = CircuitState.OPEN
                    self._half_open_attempts[key] = 0
                    self._half_open_successes[key] = 0
                    self._last_state_change[key] = time.time()
                    stats["state_changes"] += 1
                    logger.warning(
                        f"[CircuitBreaker] {key}: CLOSED -> OPEN "
                        f"(failures={self._failure_counts[key]}, "
                        f"threshold={config.failure_threshold})"
                    )

    async def reset(self, key: str) -> bool:
        """手动重置熔断器状态"""
        async with self._lock:
            if key in self._states:
                self._states[key] = CircuitState.CLOSED
                self._failure_counts[key] = 0
                self._half_open_attempts[key] = 0
                self._half_open_successes[key] = 0
                self._last_state_change[key] = time.time()
                self._stats[key]["state_changes"] += 1
                logger.info(f"[CircuitBreaker] {key}: manually reset to CLOSED")
                return True
            return False

    async def reset_all(self):
        """重置所有熔断器"""
        async with self._lock:
            for key in list(self._states.keys()):
                self._states[key] = CircuitState.CLOSED
                self._failure_counts[key] = 0
                self._half_open_attempts[key] = 0
                self._half_open_successes[key] = 0
                self._last_state_change[key] = time.time()
                self._stats[key]["state_changes"] += 1
            logger.info("[CircuitBreaker] All circuit breakers manually reset")

    def get_state(self, key: str) -> CircuitState:
        """获取熔断器状态"""
        return self._states[key]

    def get_stats(self) -> Dict[str, Any]:
        """获取所有熔断器统计"""
        result = {}
        for key in set(list(self._states.keys()) + list(self._configs.keys())):
            state = self._states.get(key, CircuitState.CLOSED)
            config = self._get_config(key)
            stats = self._stats.get(key, {})

            now = time.time()
            time_since_change = now - self._last_state_change.get(key, now)
            time_until_recovery = max(
                0,
                config.recovery_time - (now - self._last_failure_time.get(key, 0))
            ) if state == CircuitState.OPEN else 0

            result[key] = {
                "state": state.value,
                "failure_count": self._failure_counts.get(key, 0),
                "failure_threshold": config.failure_threshold,
                "recovery_time_seconds": config.recovery_time,
                "last_failure_time": self._last_failure_time.get(key, 0),
                "last_state_change": self._last_state_change.get(key, 0),
                "time_since_state_change": round(time_since_change, 2),
                "time_until_recovery": round(time_until_recovery, 2),
                "half_open_attempts": self._half_open_attempts.get(key, 0),
                "half_open_successes": self._half_open_successes.get(key, 0),
                "total_requests": stats.get("total_requests", 0),
                "success_count": stats.get("success_count", 0),
                "failure_count_total": stats.get("failure_count", 0),
                "rejected_count": stats.get("rejected_count", 0),
                "state_changes": stats.get("state_changes", 0),
            }
        return result

    def get_fallback_response(self, key: str) -> Dict[str, Any]:
        """获取熔断降级响应

        Args:
            key: 模块标识

        Returns:
            降级响应内容
        """
        route = self._get_route(key)
        module_name = route.name if route else key

        return {
            "code": 503,
            "message": f"Service '{module_name}' is temporarily unavailable (circuit breaker open)",
            "data": {
                "module": key,
                "module_name": module_name,
                "reason": "circuit_breaker_open",
                "retry_after": self._get_config(key).recovery_time,
                "hint": "服务暂时不可用，请稍后重试",
            },
        }


# 全局熔断器实例
_circuit_breaker: Optional[CircuitBreaker] = None
_circuit_breaker_lock = asyncio.Lock()


async def get_circuit_breaker_async() -> CircuitBreaker:
    """异步获取全局熔断器实例（安全初始化）"""
    global _circuit_breaker
    if _circuit_breaker is None:
        async with _circuit_breaker_lock:
            if _circuit_breaker is None:
                from ..config import settings
                _circuit_breaker = CircuitBreaker(
                    failure_threshold=settings.circuit_breaker_threshold,
                    recovery_time=settings.circuit_breaker_recovery_time,
                )
    return _circuit_breaker


def get_circuit_breaker() -> CircuitBreaker:
    """获取全局熔断器实例（同步版本，用于启动初始化）"""
    global _circuit_breaker
    if _circuit_breaker is None:
        from ..config import settings
        _circuit_breaker = CircuitBreaker(
            failure_threshold=settings.circuit_breaker_threshold,
            recovery_time=settings.circuit_breaker_recovery_time,
        )
    return _circuit_breaker
