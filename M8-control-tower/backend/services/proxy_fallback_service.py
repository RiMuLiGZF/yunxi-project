"""
M8 控制塔 - 代理健康检查与降级管理服务 (ProxyFallbackService)

统一管理所有外部模块代理（M4/M5/M6等）的健康检查和降级策略。

主要功能：
1. 健康检查：周期性检查目标模块是否可用
2. 熔断机制：连续失败后自动熔断，避免雪崩
3. 降级策略：目标模块不可用时的降级处理
4. 超时控制：统一的超时配置与管理
5. 统计监控：代理成功率、延迟等指标

设计原则：
- 调用目标模块前先做健康检查（带缓存，不频繁）
- 目标不可用时快速失败，不阻塞 M8 自身
- 提供降级数据或友好提示，而非直接报错
- 支持手动切换代理模式（on/off/fallback）
"""

from __future__ import annotations

import sys
import time
import threading
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Awaitable
from enum import Enum

# 将项目根目录加入 path，以便导入 shared 模块
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

from shared.core.observability import get_logger

logger = get_logger("m8.proxy_fallback")


# ===========================================================================
# 常量与配置
# ===========================================================================

class ProxyMode(str, Enum):
    """代理模式"""
    OFF = "off"             # 关闭代理，使用本地实现
    FALLBACK = "fallback"   # 优先代理，失败回退到本地
    ON = "on"               # 强制使用代理，失败返回 503


class HealthStatus(str, Enum):
    """健康状态"""
    HEALTHY = "healthy"     # 正常
    DEGRADED = "degraded"   # 降级（响应慢或部分接口失败）
    UNHEALTHY = "unhealthy" # 不可用
    UNKNOWN = "unknown"     # 未知

class CircuitState(str, Enum):
    """熔断器状态"""
    CLOSED = "closed"       # 关闭（正常放行）
    OPEN = "open"           # 打开（熔断，拒绝请求）
    HALF_OPEN = "half_open" # 半开（尝试恢复）


# 默认配置
DEFAULT_HEALTH_CHECK_INTERVAL = 30.0   # 健康检查间隔（秒）
DEFAULT_HEALTH_CHECK_TIMEOUT = 3.0     # 健康检查超时（秒）
DEFAULT_PROXY_TIMEOUT = 10.0           # 代理请求超时（秒）
DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 5  # 连续失败多少次触发熔断
DEFAULT_CIRCUIT_BREAKER_RECOVERY = 60.0  # 熔断后多久进入半开状态（秒）
DEFAULT_FAILURE_WINDOW = 60.0          # 失败统计窗口（秒）


# ===========================================================================
# 单个模块的代理状态
# ===========================================================================

class ModuleProxyState:
    """单个模块的代理状态管理

    包含：健康状态、熔断器状态、失败统计、延迟统计
    """

    def __init__(self, module_key: str, base_url: str,
                 health_path: str = "/health"):
        self.module_key = module_key
        self.base_url = base_url
        self.health_path = health_path

        # 健康状态
        self.health_status: HealthStatus = HealthStatus.UNKNOWN
        self.last_health_check: float = 0.0
        self.last_health_success: float = 0.0
        self.last_health_error: Optional[str] = None
        self.latency_ms: float = 0.0

        # 熔断器
        self.circuit_state: CircuitState = CircuitState.CLOSED
        self.circuit_open_time: float = 0.0
        self.circuit_failure_count: int = 0
        self.circuit_success_count: int = 0

        # 统计
        self.total_requests: int = 0
        self.success_requests: int = 0
        self.failed_requests: int = 0
        self.failure_window: List[float] = []  # 失败时间戳列表

        # 配置
        self.timeout: float = DEFAULT_PROXY_TIMEOUT
        self.circuit_threshold: int = DEFAULT_CIRCUIT_BREAKER_THRESHOLD
        self.circuit_recovery: float = DEFAULT_CIRCUIT_BREAKER_RECOVERY

        self._lock = threading.RLock()

    # -------------------------------------------------------------------
    # 健康检查
    # -------------------------------------------------------------------

    async def check_health(self, timeout: Optional[float] = None) -> HealthStatus:
        """执行健康检查

        Args:
            timeout: 超时时间（秒）

        Returns:
            健康状态
        """
        if not _HAS_HTTPX:
            self.health_status = HealthStatus.UNKNOWN
            return self.health_status

        timeout = timeout or DEFAULT_HEALTH_CHECK_TIMEOUT
        self.last_health_check = time.time()

        try:
            start = time.time()
            async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
                response = await client.get(self.health_path)
                self.latency_ms = (time.time() - start) * 1000

                if response.status_code < 500:
                    self.health_status = HealthStatus.HEALTHY
                    self.last_health_success = time.time()
                    self.last_health_error = None
                    # 健康检查成功，重置熔断器失败计数
                    with self._lock:
                        self.circuit_failure_count = 0
                        if self.circuit_state == CircuitState.OPEN:
                            self.circuit_state = CircuitState.HALF_OPEN
                else:
                    self.health_status = HealthStatus.UNHEALTHY
                    self.last_health_error = f"HTTP {response.status_code}"

        except httpx.TimeoutException:
            self.health_status = HealthStatus.UNHEALTHY
            self.last_health_error = "timeout"
            self.latency_ms = timeout * 1000
        except httpx.ConnectError:
            self.health_status = HealthStatus.UNHEALTHY
            self.last_health_error = "connection_refused"
        except Exception as e:
            self.health_status = HealthStatus.UNKNOWN
            self.last_health_error = str(e)

        return self.health_status

    def is_healthy(self, max_age: float = 60.0) -> bool:
        """判断模块是否健康（带缓存）

        Args:
            max_age: 健康检查结果最大有效期（秒）

        Returns:
            是否健康
        """
        if self.health_status == HealthStatus.HEALTHY:
            if time.time() - self.last_health_check < max_age:
                return True
        return False

    # -------------------------------------------------------------------
    # 熔断器
    # -------------------------------------------------------------------

    def can_proceed(self) -> bool:
        """判断是否可以发起代理请求（熔断器检查）

        Returns:
            是否可以继续
        """
        with self._lock:
            if self.circuit_state == CircuitState.CLOSED:
                return True

            if self.circuit_state == CircuitState.OPEN:
                # 检查是否过了恢复时间
                if time.time() - self.circuit_open_time >= self.circuit_recovery:
                    self.circuit_state = CircuitState.HALF_OPEN
                    logger.info(f"[{self.module_key}] 熔断器进入半开状态，尝试恢复")
                    return True
                return False

            if self.circuit_state == CircuitState.HALF_OPEN:
                # 半开状态允许少量请求通过
                return True

            return True

    def record_success(self) -> None:
        """记录一次成功请求"""
        with self._lock:
            self.total_requests += 1
            self.success_requests += 1
            self.circuit_failure_count = 0

            if self.circuit_state == CircuitState.HALF_OPEN:
                self.circuit_success_count += 1
                # 半开状态连续成功一定次数后恢复
                if self.circuit_success_count >= 3:
                    self.circuit_state = CircuitState.CLOSED
                    self.circuit_success_count = 0
                    logger.info(f"[{self.module_key}] 熔断器关闭，服务已恢复")

            # 清理过期的失败记录
            now = time.time()
            self.failure_window = [
                t for t in self.failure_window
                if now - t < DEFAULT_FAILURE_WINDOW
            ]

    def record_failure(self, error: str = "") -> None:
        """记录一次失败请求

        Args:
            error: 错误描述
        """
        now = time.time()
        with self._lock:
            self.total_requests += 1
            self.failed_requests += 1
            self.circuit_failure_count += 1
            self.failure_window.append(now)

            # 清理过期的失败记录
            self.failure_window = [
                t for t in self.failure_window
                if now - t < DEFAULT_FAILURE_WINDOW
            ]

            # 检查是否触发熔断
            if self.circuit_state != CircuitState.OPEN:
                recent_failures = len(self.failure_window)
                if recent_failures >= self.circuit_threshold:
                    self.circuit_state = CircuitState.OPEN
                    self.circuit_open_time = now
                    self.circuit_success_count = 0
                    logger.warning(
                        f"[{self.module_key}] 熔断器已打开 "
                        f"（最近 {recent_failures} 次失败）"
                        f" {error}"
                    )

    # -------------------------------------------------------------------
    # 统计
    # -------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            success_rate = (
                self.success_requests / self.total_requests * 100
                if self.total_requests > 0 else 0
            )
            return {
                "module_key": self.module_key,
                "base_url": self.base_url,
                "health_status": self.health_status.value,
                "last_health_check": self.last_health_check,
                "last_health_error": self.last_health_error,
                "latency_ms": round(self.latency_ms, 2),
                "circuit_state": self.circuit_state.value,
                "circuit_failure_count": self.circuit_failure_count,
                "total_requests": self.total_requests,
                "success_requests": self.success_requests,
                "failed_requests": self.failed_requests,
                "success_rate": round(success_rate, 2),
                "recent_failures": len(self.failure_window),
            }


# ===========================================================================
# ProxyFallbackService - 代理降级管理服务主类
# ===========================================================================

class ProxyFallbackService:
    """代理降级管理服务

    统一管理所有外部模块代理的健康检查、熔断和降级。

    使用方式：
        service = ProxyFallbackService()
        service.register_module("m4", "http://localhost:8004")

        # 方式1：带降级函数的代理调用
        result = await service.proxy_with_fallback(
            module_key="m4",
            path="/api/v1/review/list",
            method="GET",
            fallback_func=local_review_list,
            fallback_args=(),
            fallback_kwargs={},
        )

        # 方式2：仅检查是否可用
        if service.is_healthy("m4"):
            # 代理请求
            ...
        else:
            # 降级处理
            ...
    """

    def __init__(self):
        self._modules: Dict[str, ModuleProxyState] = {}
        self._lock = threading.RLock()
        self._health_check_task = None
        self._health_check_running = False

        # 全局代理模式（可被每个模块的配置覆盖）
        self.global_mode: ProxyMode = ProxyMode.FALLBACK

        # 注册默认模块
        self._register_default_modules()

    # -------------------------------------------------------------------
    # 模块注册
    # -------------------------------------------------------------------

    def _register_default_modules(self) -> None:
        """注册默认的业务模块"""
        import os

        # M4 场景引擎
        m4_url = os.environ.get("M4_BASE_URL", "http://localhost:8004")
        self.register_module("m4", m4_url, "/health")

        # M5 潮汐记忆
        m5_url = os.environ.get("M5_BASE_URL", "http://localhost:8005")
        self.register_module("m5", m5_url, "/health")

        # M6 硬件外设
        m6_url = os.environ.get("M6_BASE_URL", "http://localhost:8006")
        self.register_module("m6", m6_url, "/health")

    def register_module(self, module_key: str, base_url: str,
                        health_path: str = "/health") -> ModuleProxyState:
        """注册一个受管模块

        Args:
            module_key: 模块标识
            base_url: 模块基础 URL
            health_path: 健康检查路径

        Returns:
            模块代理状态对象
        """
        with self._lock:
            state = ModuleProxyState(module_key, base_url, health_path)
            self._modules[module_key] = state
            logger.info(f"注册代理模块: {module_key} -> {base_url}")
            return state

    def get_module_state(self, module_key: str) -> Optional[ModuleProxyState]:
        """获取模块代理状态

        Args:
            module_key: 模块标识

        Returns:
            模块代理状态对象，不存在返回 None
        """
        return self._modules.get(module_key)

    # -------------------------------------------------------------------
    # 健康检查管理
    # -------------------------------------------------------------------

    def is_healthy(self, module_key: str, max_age: float = 60.0) -> bool:
        """快速检查模块是否健康

        Args:
            module_key: 模块标识
            max_age: 健康检查结果最大有效期

        Returns:
            是否健康
        """
        state = self._modules.get(module_key)
        if not state:
            return False
        return state.is_healthy(max_age)

    async def check_module_health(self, module_key: str) -> HealthStatus:
        """立即检查指定模块的健康状态

        Args:
            module_key: 模块标识

        Returns:
            健康状态
        """
        state = self._modules.get(module_key)
        if not state:
            return HealthStatus.UNKNOWN

        return await state.check_health()

    async def check_all_health(self) -> Dict[str, HealthStatus]:
        """检查所有已注册模块的健康状态

        Returns:
            {module_key: health_status}
        """
        results = {}
        tasks = []

        for key, state in self._modules.items():
            tasks.append(self._check_one(key, state))

        health_results = await asyncio.gather(*tasks, return_exceptions=True)
        for key, result in zip(self._modules.keys(), health_results):
            if isinstance(result, HealthStatus):
                results[key] = result
            else:
                results[key] = HealthStatus.UNKNOWN

        return results

    async def _check_one(self, key: str, state: ModuleProxyState) -> HealthStatus:
        """检查单个模块（用于并发）"""
        return await state.check_health()

    def start_health_check_loop(self, interval: float = DEFAULT_HEALTH_CHECK_INTERVAL) -> None:
        """启动周期性健康检查（后台任务）

        Args:
            interval: 检查间隔（秒）
        """
        if self._health_check_running:
            return

        self._health_check_running = True

        async def loop():
            while self._health_check_running:
                try:
                    await self.check_all_health()
                except Exception as e:
                    logger.warning(f"健康检查异常: {e}")
                await asyncio.sleep(interval)

        # 注意：此方法需要在 asyncio 事件循环中调用
        # 实际使用时应通过 FastAPI lifespan 启动
        self._health_check_task = asyncio.create_task(loop())
        logger.info(f"代理健康检查已启动，间隔 {interval} 秒")

    def stop_health_check_loop(self) -> None:
        """停止周期性健康检查"""
        self._health_check_running = False
        if self._health_check_task:
            self._health_check_task.cancel()
            self._health_check_task = None
        logger.info("代理健康检查已停止")

    # -------------------------------------------------------------------
    # 代理调用（带降级）
    # -------------------------------------------------------------------

    async def proxy_with_fallback(
        self,
        module_key: str,
        path: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        fallback_func: Optional[Callable[..., Awaitable[Any]]] = None,
        fallback_args: Optional[tuple] = None,
        fallback_kwargs: Optional[Dict[str, Any]] = None,
        mode: Optional[ProxyMode] = None,
    ) -> Dict[str, Any]:
        """带降级策略的代理调用

        Args:
            module_key: 目标模块标识
            path: 目标路径
            method: HTTP 方法
            params: 查询参数
            body: 请求体
            headers: 请求头
            fallback_func: 降级函数（异步）
            fallback_args: 降级函数位置参数
            fallback_kwargs: 降级函数关键字参数
            mode: 代理模式（不指定则使用全局模式）

        Returns:
            {
                "proxied": bool,         # 是否成功代理
                "degraded": bool,        # 是否为降级响应
                "data": Any,             # 响应数据
                "error": Optional[str],  # 错误信息
                "latency_ms": float,     # 耗时
                "source": str,           # 数据来源: proxy/fallback/error
            }
        """
        effective_mode = mode or self.global_mode
        state = self._modules.get(module_key)

        start_time = time.time()

        # 模式：off - 直接使用本地实现
        if effective_mode == ProxyMode.OFF:
            return await self._call_fallback(
                fallback_func, fallback_args, fallback_kwargs,
                reason="proxy_disabled", source="local",
                start_time=start_time,
            )

        # 检查模块是否已注册
        if not state:
            if effective_mode == ProxyMode.FALLBACK and fallback_func:
                return await self._call_fallback(
                    fallback_func, fallback_args, fallback_kwargs,
                    reason="module_not_registered", source="fallback",
                    start_time=start_time,
                )
            return {
                "proxied": False,
                "degraded": True,
                "data": None,
                "error": f"模块 {module_key} 未注册",
                "latency_ms": (time.time() - start_time) * 1000,
                "source": "error",
            }

        # 熔断器检查
        if not state.can_proceed():
            if effective_mode == ProxyMode.FALLBACK and fallback_func:
                logger.debug(f"[{module_key}] 熔断器已打开，使用降级")
                return await self._call_fallback(
                    fallback_func, fallback_args, fallback_kwargs,
                    reason="circuit_open", source="fallback",
                    start_time=start_time,
                )
            return {
                "proxied": False,
                "degraded": True,
                "data": None,
                "error": f"模块 {module_key} 暂不可用（熔断器已打开）",
                "latency_ms": (time.time() - start_time) * 1000,
                "source": "circuit_breaker",
            }

        # 发起代理请求
        try:
            result = await self._do_proxy(
                state=state,
                path=path,
                method=method,
                params=params,
                body=body,
                headers=headers,
            )

            state.record_success()
            latency_ms = (time.time() - start_time) * 1000

            return {
                "proxied": True,
                "degraded": False,
                "data": result,
                "error": None,
                "latency_ms": round(latency_ms, 2),
                "source": "proxy",
            }

        except Exception as e:
            error_msg = str(e)
            state.record_failure(error_msg)
            latency_ms = (time.time() - start_time) * 1000

            logger.warning(f"[{module_key}] 代理失败: {method} {path} - {error_msg}")

            # 模式：fallback - 降级到本地实现
            if effective_mode == ProxyMode.FALLBACK and fallback_func:
                return await self._call_fallback(
                    fallback_func, fallback_args, fallback_kwargs,
                    reason=error_msg, source="fallback",
                    start_time=start_time,
                )

            # 模式：on - 返回错误
            return {
                "proxied": False,
                "degraded": True,
                "data": None,
                "error": error_msg,
                "latency_ms": round(latency_ms, 2),
                "source": "error",
            }

    async def _do_proxy(
        self,
        state: ModuleProxyState,
        path: str,
        method: str,
        params: Optional[Dict],
        body: Optional[Dict],
        headers: Optional[Dict],
    ) -> Any:
        """执行实际的代理请求

        Args:
            state: 模块代理状态
            path: 目标路径
            method: HTTP 方法
            params: 查询参数
            body: 请求体
            headers: 请求头

        Returns:
            响应数据（JSON 解析后）

        Raises:
            Exception: 请求失败时抛出
        """
        if not _HAS_HTTPX:
            raise RuntimeError("httpx 不可用，无法执行代理请求")

        url = f"{state.base_url}{path}"

        async with httpx.AsyncClient(
            timeout=state.timeout,
            follow_redirects=True,
        ) as client:
            method_upper = method.upper()
            if method_upper == "GET":
                response = await client.get(url, params=params, headers=headers)
            elif method_upper == "POST":
                response = await client.post(url, params=params, json=body, headers=headers)
            elif method_upper == "PUT":
                response = await client.put(url, params=params, json=body, headers=headers)
            elif method_upper == "DELETE":
                response = await client.delete(url, params=params, headers=headers)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {method}")

            response.raise_for_status()
            return response.json()

    async def _call_fallback(
        self,
        fallback_func: Optional[Callable],
        fallback_args: Optional[tuple],
        fallback_kwargs: Optional[Dict],
        reason: str,
        source: str,
        start_time: float,
    ) -> Dict[str, Any]:
        """调用降级函数

        Args:
            fallback_func: 降级函数
            fallback_args: 位置参数
            fallback_kwargs: 关键字参数
            reason: 降级原因
            source: 数据来源标识
            start_time: 开始时间

        Returns:
            标准化的响应 dict
        """
        if fallback_func is None:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "proxied": False,
                "degraded": True,
                "data": None,
                "error": reason,
                "latency_ms": round(latency_ms, 2),
                "source": "no_fallback",
            }

        try:
            args = fallback_args or ()
            kwargs = fallback_kwargs or {}
            result = await fallback_func(*args, **kwargs)
            latency_ms = (time.time() - start_time) * 1000
            return {
                "proxied": False,
                "degraded": True,
                "data": result,
                "error": None,
                "latency_ms": round(latency_ms, 2),
                "source": source,
                "degraded_reason": reason,
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error(f"降级函数也失败了: {e}")
            return {
                "proxied": False,
                "degraded": True,
                "data": None,
                "error": f"降级函数失败: {e}",
                "latency_ms": round(latency_ms, 2),
                "source": "fallback_error",
            }

    # -------------------------------------------------------------------
    # 状态与统计
    # -------------------------------------------------------------------

    def get_all_stats(self) -> Dict[str, Any]:
        """获取所有模块的代理统计信息"""
        stats = {}
        for key, state in self._modules.items():
            stats[key] = state.get_stats()
        return stats

    def get_status_summary(self) -> Dict[str, Any]:
        """获取代理状态总览"""
        total = len(self._modules)
        healthy = 0
        unhealthy = 0
        unknown = 0
        circuit_open = 0

        for state in self._modules.values():
            if state.health_status == HealthStatus.HEALTHY:
                healthy += 1
            elif state.health_status == HealthStatus.UNHEALTHY:
                unhealthy += 1
            else:
                unknown += 1

            if state.circuit_state == CircuitState.OPEN:
                circuit_open += 1

        return {
            "total_modules": total,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "unknown": unknown,
            "circuit_open": circuit_open,
            "global_mode": self.global_mode.value,
        }


# ===========================================================================
# 单例
# ===========================================================================

_proxy_fallback_service: Optional[ProxyFallbackService] = None
_service_lock = threading.Lock()


def get_proxy_fallback_service() -> ProxyFallbackService:
    """获取 ProxyFallbackService 单例"""
    global _proxy_fallback_service
    if _proxy_fallback_service is None:
        with _service_lock:
            if _proxy_fallback_service is None:
                _proxy_fallback_service = ProxyFallbackService()
    return _proxy_fallback_service
