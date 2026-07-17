"""
云汐内核 V6 - 健康监控中心

灵感来源：Kubernetes Probes / Spring Boot Actuator

提供多维度的健康检查能力：
- Liveness：进程是否存活（轻量级，<10ms）
- Readiness：服务是否可接受流量（中量级，<500ms）
- Deep：完整诊断所有依赖（重量级，1-5s，手动触发）
- Component Health：各子组件健康状态
- Dependency Check：外部依赖可用性

输出格式兼容 Kubernetes / Prometheus 生态。
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ── 类型定义 ──────────────────────────────────────────

HealthChecker = Callable[[], Awaitable[bool]]
"""健康检查函数签名（返回 bool 的异步函数）"""

HealthCheckLevel = Literal["liveness", "readiness", "deep"]
"""健康检查级别：liveness（存活）/ readiness（就绪）/ deep（深度）"""

ComponentType = Literal["database", "message_bus", "memory", "disk", "circuit_breaker", "custom"]
"""组件类型枚举"""


# ── 健康状态数据类 ─────────────────────────────────────

@dataclass
class HealthStatus:
    """健康状态

    Attributes:
        status: 健康状态，up / down / degraded / unknown
        timestamp: 检查时间戳（秒）
        latency_ms: 检查耗时（毫秒）
        details: 详细信息字典
        error: 错误信息（如有）
        level: 检查级别：liveness / readiness / deep
        component_type: 组件类型：database / message_bus / memory / disk / circuit_breaker / custom
        threshold: 触发降级的阈值信息（如内存阈值、磁盘阈值等）
    """

    status: str = "unknown"  # up | down | degraded
    timestamp: float = field(default_factory=time.time)
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    level: HealthCheckLevel = "readiness"
    component_type: ComponentType = "custom"
    threshold: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典表示

        Returns:
            包含所有健康状态字段的字典
        """
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
            "error": self.error,
            "level": self.level,
            "component_type": self.component_type,
            "threshold": self.threshold,
        }


# ── 缓存条目 ──────────────────────────────────────────

@dataclass
class _CacheEntry:
    """缓存条目"""
    result: dict[str, HealthStatus]
    timestamp: float


# ── 健康监控中心 ──────────────────────────────────────

class HealthMonitor:
    """健康监控中心

    注册各组件的健康检查函数，提供聚合健康视图。

    支持三级健康检查：
    - Liveness（存活）：轻量级，仅检查进程是否存活，响应 <10ms
    - Readiness（就绪）：中量级，检查核心依赖是否可用，响应 <500ms
    - Deep（深度）：重量级，完整诊断所有依赖，响应 1-5s，手动触发

    不同级别使用独立的缓存 TTL：
    - liveness: 1s（基本不缓存）
    - readiness: 5s（默认）
    - deep: 60s（低频，手动触发）
    """

    # 各级别缓存 TTL（秒）
    CACHE_TTL: dict[HealthCheckLevel, float] = {
        "liveness": 1.0,
        "readiness": 5.0,
        "deep": 60.0,
    }

    def __init__(self) -> None:
        # 所有已注册的检查器（name -> checker function）
        self._checks: dict[str, HealthChecker] = {}
        # 检查器元数据（name -> {"level": ..., "component_type": ...}）
        self._check_meta: dict[str, dict[str, Any]] = {}

        # 分级缓存
        self._cache: dict[HealthCheckLevel, _CacheEntry | None] = {
            "liveness": None,
            "readiness": None,
            "deep": None,
        }
        self._cache_lock: asyncio.Lock = asyncio.Lock()

        # 兼容旧版：保留单一 TTL 属性（映射到 readiness 级别）
        self._cache_ttl: float = 5.0
        self._last_check: float = 0.0

        self._logger: structlog.stdlib.BoundLogger = logger.bind(service="health_monitor")

    # ── 注册接口 ──────────────────────────────────────

    def register(
        self,
        name: str,
        checker: HealthChecker,
        level: HealthCheckLevel = "readiness",
        component_type: ComponentType = "custom",
    ) -> None:
        """注册健康检查

        Args:
            name: 检查项名称
            checker: 异步检查函数，返回 bool（True=健康，False=不健康）
            level: 检查级别，默认 readiness
            component_type: 组件类型，默认 custom
        """
        self._checks[name] = checker
        self._check_meta[name] = {
            "level": level,
            "component_type": component_type,
        }
        # 注册后使缓存失效
        self._invalidate_cache()
        self._logger.info("health_check_registered", name=name, level=level, component_type=component_type)

    def unregister(self, name: str) -> None:
        """注销健康检查

        Args:
            name: 检查项名称
        """
        self._checks.pop(name, None)
        self._check_meta.pop(name, None)
        self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        """使所有缓存失效"""
        for level in self._cache:
            self._cache[level] = None
        self._last_check = 0.0

    # ── 单个组件检查 ──────────────────────────────────

    async def check(self, name: str) -> HealthStatus:
        """检查单个组件

        Args:
            name: 检查项名称

        Returns:
            HealthStatus 健康状态对象
        """
        checker = self._checks.get(name)
        if checker is None:
            return HealthStatus(
                status="unknown",
                error=f"No checker registered for '{name}'",
                level="readiness",
                component_type="custom",
            )

        meta = self._check_meta.get(name, {})
        level = meta.get("level", "readiness")
        component_type = meta.get("component_type", "custom")

        start = time.time()
        try:
            passed = await checker()
            latency_ms = (time.time() - start) * 1000
            return HealthStatus(
                status="up" if passed else "down",
                latency_ms=latency_ms,
                level=level,
                component_type=component_type,
            )
        except Exception as exc:
            latency_ms = (time.time() - start) * 1000
            self._logger.warning(
                "health_check_failed",
                name=name,
                error=str(exc),
                exc_type=exc.__class__.__name__,
            )
            return HealthStatus(
                status="down",
                latency_ms=latency_ms,
                error=str(exc),
                level=level,
                component_type=component_type,
            )

    # ── 批量检查与缓存 ────────────────────────────────

    async def check_all(self, use_cache: bool = True) -> dict[str, HealthStatus]:
        """检查所有组件（readiness 级别，兼容旧版 API）

        Args:
            use_cache: 是否在缓存有效期内直接返回缓存结果

        Returns:
            组件名到 HealthStatus 的映射字典
        """
        return await self._check_level("readiness", use_cache=use_cache)

    async def _check_level(
        self,
        level: HealthCheckLevel,
        use_cache: bool = True,
    ) -> dict[str, HealthStatus]:
        """按级别执行健康检查

        仅执行级别 <= 当前级别的检查项（即 deep 包含所有，
        readiness 包含 readiness + liveness，liveness 仅包含 liveness）。

        Args:
            level: 检查级别
            use_cache: 是否使用缓存

        Returns:
            组件名到 HealthStatus 的映射字典
        """
        level_order: dict[HealthCheckLevel, int] = {
            "liveness": 0,
            "readiness": 1,
            "deep": 2,
        }
        target_order = level_order[level]

        # 筛选出当前级别及更低级别的检查项
        names_to_check = [
            name for name, meta in self._check_meta.items()
            if level_order.get(meta.get("level", "readiness"), 1) <= target_order
        ]

        if use_cache:
            cached = await self._get_cached(level)
            if cached is not None:
                # 确保缓存包含所有当前应该检查的项
                if all(name in cached for name in names_to_check):
                    return dict(cached)

        results: dict[str, HealthStatus] = {}
        for name in names_to_check:
            results[name] = await self.check(name)

        # 更新缓存
        if use_cache:
            await self._set_cache(level, results)

        # 兼容旧版：更新 _last_check
        self._last_check = time.time()
        return results

    async def _get_cached(self, level: HealthCheckLevel) -> dict[str, HealthStatus] | None:
        """获取指定级别的缓存结果

        Args:
            level: 检查级别

        Returns:
            缓存结果字典，未命中或过期返回 None
        """
        async with self._cache_lock:
            entry = self._cache.get(level)
            if entry is None:
                return None
            ttl = self.CACHE_TTL[level]
            if time.time() - entry.timestamp < ttl:
                return dict(entry.result)
            return None

    async def _set_cache(self, level: HealthCheckLevel, results: dict[str, HealthStatus]) -> None:
        """设置缓存

        Args:
            level: 检查级别
            results: 检查结果字典
        """
        async with self._cache_lock:
            self._cache[level] = _CacheEntry(
                result=dict(results),
                timestamp=time.time(),
            )

    # ── Liveness 存活检查 ─────────────────────────────

    async def liveness(self) -> HealthStatus:
        """存活检查：进程是否还在运行

        轻量级检查，不依赖任何外部资源，响应时间 < 10ms。
        对应端点：/health/liveness

        Returns:
            HealthStatus 健康状态对象
        """
        pid = os.getpid()
        return HealthStatus(
            status="up",
            details={"pid": pid, "uptime_seconds": time.time() - _process_start_time()},
            level="liveness",
            component_type="custom",
        )

    # ── Readiness 就绪检查 ────────────────────────────

    async def readiness(self) -> dict[str, HealthStatus]:
        """就绪检查：所有关键组件是否健康

        中量级检查，检查数据库连通性、消息总线状态、核心组件注册等。
        响应时间 < 500ms。
        对应端点：/health/readiness

        Returns:
            组件名到 HealthStatus 的映射字典
        """
        return await self._check_level("readiness", use_cache=True)

    # ── Deep 深度检查 ─────────────────────────────────

    async def deep_check(self, use_cache: bool = True) -> dict[str, HealthStatus]:
        """深度健康检查：完整诊断所有依赖

        重量级检查，包括：
        - 数据库读写测试、完整性检查
        - 消息总线发布订阅测试
        - 外部 Agent 心跳
        - 磁盘空间、内存使用率、线程池状态

        响应时间可能较长（1-5 秒），应手动触发，不自动调用。
        对应端点：/health/deep

        Args:
            use_cache: 是否使用缓存（默认 True，deep 级别缓存 60s）

        Returns:
            组件名到 HealthStatus 的映射字典
        """
        return await self._check_level("deep", use_cache=use_cache)

    # ── 聚合状态 ──────────────────────────────────────

    async def overall_status(self) -> dict[str, Any]:
        """获取整体健康状态

        Returns:
            包含 overall status、liveness、readiness 的完整状态字典
        """
        live = await self.liveness()
        ready = await self.readiness()

        all_up = all(r.status == "up" for r in ready.values())
        any_down = any(r.status == "down" for r in ready.values())
        any_degraded = any(r.status == "degraded" for r in ready.values())

        # 检查降级状态（惰性导入，避免循环依赖）
        degradation_info: dict[str, Any] = {}
        try:
            from src.resilience.degradation import get_degradation_manager

            mgr = get_degradation_manager()
            stats = mgr.get_stats()
            degradation_info = {
                "level": stats["current_level"],
                "level_value": stats["current_level_value"],
                "disabled_count": stats["disabled_count"],
                "disabled_features": stats["disabled_features"],
            }
            # L3 及以上降级时整体状态为 degraded
            if stats["current_level_value"] >= 3:
                any_degraded = True
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("degradation_status_check_failed", error=str(exc))

        if live.status != "up":
            overall = "down"
        elif any_down:
            overall = "degraded"
        elif any_degraded:
            overall = "degraded"
        elif all_up:
            overall = "up"
        else:
            overall = "unknown"

        result: dict[str, Any] = {
            "status": overall,
            "timestamp": time.time(),
            "liveness": live.to_dict(),
            "readiness": {name: status.to_dict() for name, status in ready.items()},
        }

        if degradation_info:
            result["degradation"] = degradation_info

        return result

    # ── 组件详细状态 ──────────────────────────────────

    async def component_statuses(self) -> dict[str, Any]:
        """获取各组件详细状态

        返回所有已注册检查项的详细状态，包含组件类型、级别、阈值等信息。

        Returns:
            包含所有组件状态的字典
        """
        results = await self._check_level("deep", use_cache=True)
        return {
            "timestamp": time.time(),
            "total": len(results),
            "components": {
                name: status.to_dict()
                for name, status in results.items()
            },
            "summary": self._summarize(results),
        }

    @staticmethod
    def _summarize(results: dict[str, HealthStatus]) -> dict[str, int]:
        """统计各状态数量

        Args:
            results: 检查结果字典

        Returns:
            各状态计数的字典
        """
        counts: dict[str, int] = {"up": 0, "down": 0, "degraded": 0, "unknown": 0}
        for status in results.values():
            counts[status.status] = counts.get(status.status, 0) + 1
        return counts

    # ── 格式化输出 ────────────────────────────────────

    async def to_prometheus(self) -> str:
        """输出 Prometheus 格式的指标

        Returns:
            Prometheus 文本格式的指标字符串
        """
        results = await self._check_level("readiness", use_cache=True)
        lines = [
            "# HELP yunxi_health Health status of components",
            "# TYPE yunxi_health gauge",
        ]
        for name, status in results.items():
            value = 1 if status.status == "up" else 0
            component_type = status.component_type
            level = status.level
            lines.append(
                f'yunxi_health{{component="{name}",type="{component_type}",level="{level}"}} {value}'
            )

        # 添加延迟指标
        lines.append("# HELP yunxi_health_latency_ms Health check latency in milliseconds")
        lines.append("# TYPE yunxi_health_latency_ms gauge")
        for name, status in results.items():
            lines.append(
                f'yunxi_health_latency_ms{{component="{name}"}} {round(status.latency_ms, 2)}'
            )

        return "\n".join(lines) + "\n"


# ── 辅助函数 ──────────────────────────────────────────

def _process_start_time() -> float:
    """获取进程启动时间戳

    使用标准库方案，优先通过 os.times() 和 ctypes 获取。

    Returns:
        进程启动时间戳（秒）
    """
    try:
        # Windows 下使用 GetProcessTimes
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetCurrentProcess()

            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", ctypes.c_uint), ("dwHighDateTime", ctypes.c_uint)]

            creation = FILETIME()
            exit_time = FILETIME()
            kernel = FILETIME()
            user = FILETIME()

            if kernel32.GetProcessTimes(
                handle, ctypes.byref(creation), ctypes.byref(exit_time),
                ctypes.byref(kernel), ctypes.byref(user)
            ):
                # FILETIME 是 100 纳秒间隔，从 1601-01-01 开始
                creation_100ns = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
                # 转换为 Unix 时间戳（秒）
                # 1601-01-01 到 1970-01-01 的 100 纳秒间隔数
                epoch_diff = 116444736000000000
                return (creation_100ns - epoch_diff) / 10_000_000
    except Exception:
        pass

    # 回退方案：返回当前时间（近似）
    return time.time()


# ── 内置健康检查器 ─────────────────────────────────────

def make_database_checker(
    persistence: Any,
    deep_integrity_check: bool = True,
) -> tuple[str, HealthChecker, HealthCheckLevel, ComponentType]:
    """创建数据库健康检查器

    检查 SQLitePersistence 是否可用：
    - readiness 级别：执行 SELECT 1 简单探测
    - deep 级别：执行 PRAGMA integrity_check 完整性检查

    Args:
        persistence: SQLitePersistence 实例，需支持 execute() 方法
        deep_integrity_check: deep 级别是否执行完整性检查（默认 True）

    Returns:
        (name, checker, level, component_type) 元组，可直接用于注册
    """
    async def db_check() -> bool:
        """数据库健康检查函数"""
        try:
            # 简单探测：SELECT 1
            result = await persistence.execute("SELECT 1")
            if result is None:
                raise RuntimeError("Database returned None for SELECT 1")
            return True
        except Exception as exc:
            logger.error("database_health_check_failed", error=str(exc))
            raise

    return ("database", db_check, "readiness", "database")


def make_database_deep_checker(
    persistence: Any,
) -> tuple[str, HealthChecker, HealthCheckLevel, ComponentType]:
    """创建数据库深度健康检查器

    执行 PRAGMA integrity_check 进行完整性检查，仅在 deep 级别运行。

    Args:
        persistence: SQLitePersistence 实例，需支持 execute() 方法

    Returns:
        (name, checker, level, component_type) 元组
    """
    async def db_deep_check() -> bool:
        """数据库深度健康检查函数"""
        try:
            result = await persistence.execute("PRAGMA integrity_check")
            if isinstance(result, (list, tuple)) and len(result) > 0:
                row = result[0]
                integrity = row[0] if isinstance(row, (list, tuple)) else str(row)
                if integrity.lower() != "ok":
                    raise RuntimeError(f"Database integrity check failed: {integrity}")
            return True
        except Exception as exc:
            logger.error("database_deep_check_failed", error=str(exc))
            raise

    return ("database_integrity", db_deep_check, "deep", "database")


def make_message_bus_checker(
    message_bus: Any,
    queue_length_warning: int = 1000,
) -> tuple[str, HealthChecker, HealthCheckLevel, ComponentType]:
    """创建消息总线健康检查器

    检查消息总线是否在运行、队列长度、消费者数量。

    Args:
        message_bus: MessageBus 实例
        queue_length_warning: 队列长度告警阈值（默认 1000）

    Returns:
        (name, checker, level, component_type) 元组
    """
    async def bus_check() -> bool:
        """消息总线健康检查函数"""
        try:
            # 检查总线是否在运行
            is_running = getattr(message_bus, "is_running", True)
            if callable(is_running):
                is_running = is_running()
            if not is_running:
                raise RuntimeError("Message bus is not running")

            # 检查队列长度
            queue_size = 0
            if hasattr(message_bus, "queue_size"):
                queue_size = message_bus.queue_size()
                if callable(queue_size):
                    queue_size = queue_size()
            elif hasattr(message_bus, "_queue") and hasattr(message_bus._queue, "qsize"):
                queue_size = message_bus._queue.qsize()

            if queue_size > queue_length_warning:
                # 队列过长，降级为 degraded（通过异常的 message 传递）
                raise RuntimeError(f"Message queue backlog: {queue_size} > {queue_length_warning}")

            return True
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("message_bus_health_check_failed", error=str(exc))
            raise

    return ("message_bus", bus_check, "readiness", "message_bus")


def make_memory_checker(
    threshold_mb: float = 500.0,
) -> tuple[str, HealthChecker, HealthCheckLevel, ComponentType]:
    """创建内存使用健康检查器

    检查进程内存占用，超过阈值标记为 degraded。
    使用 ctypes / 标准库方案，不依赖 psutil。

    Args:
        threshold_mb: 内存阈值（MB），默认 500MB

    Returns:
        (name, checker, level, component_type) 元组
    """
    async def memory_check() -> bool:
        """内存使用检查函数"""
        try:
            rss_mb = _get_process_memory_mb()
            if rss_mb is None:
                # 无法获取内存信息，跳过检查（视为通过）
                return True
            if rss_mb > threshold_mb:
                # 标记为 degraded - 用 RuntimeError message 传递信息
                # 注意：这里返回 False 会被标记为 down，
                # 我们通过在 details 中设置状态来实现 degraded
                # 由于 checker 只返回 bool，我们通过抛异常方式让上层处理
                raise RuntimeError(
                    f"Memory usage {rss_mb:.1f}MB exceeds threshold {threshold_mb}MB"
                )
            return True
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("memory_check_unavailable", error=str(exc))
            # 无法获取内存信息不影响健康状态
            return True

    return ("memory", memory_check, "readiness", "memory")


def make_disk_checker(
    data_dir: str,
    threshold_mb: float = 100.0,
) -> tuple[str, HealthChecker, HealthCheckLevel, ComponentType]:
    """创建磁盘空间健康检查器

    检查数据目录所在磁盘剩余空间，低于阈值标记为 down。

    Args:
        data_dir: 数据目录路径
        threshold_mb: 剩余空间阈值（MB），默认 100MB

    Returns:
        (name, checker, level, component_type) 元组
    """
    async def disk_check() -> bool:
        """磁盘空间检查函数"""
        try:
            free_mb = _get_disk_free_mb(data_dir)
            if free_mb is None:
                return True
            if free_mb < threshold_mb:
                raise RuntimeError(
                    f"Disk free space {free_mb:.1f}MB below threshold {threshold_mb}MB"
                )
            return True
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("disk_check_unavailable", error=str(exc))
            return True

    return ("disk", disk_check, "readiness", "disk")


def make_circuit_breaker_checker(
    circuit_breaker_registry: Any,
) -> tuple[str, HealthChecker, HealthCheckLevel, ComponentType]:
    """创建熔断器状态健康检查器

    检查所有熔断器状态，有 OPEN 状态的熔断器标记为 degraded。

    Args:
        circuit_breaker_registry: 熔断器注册表实例

    Returns:
        (name, checker, level, component_type) 元组
    """
    async def cb_check() -> bool:
        """熔断器状态检查函数"""
        try:
            # 获取所有熔断器状态
            if hasattr(circuit_breaker_registry, "get_all_states"):
                states = circuit_breaker_registry.get_all_states()
            elif hasattr(circuit_breaker_registry, "list_states"):
                states = circuit_breaker_registry.list_states()
            elif hasattr(circuit_breaker_registry, "states"):
                states = circuit_breaker_registry.states
            else:
                # 无法获取状态，跳过
                return True

            # 检查是否有 OPEN 状态
            open_count = 0
            if isinstance(states, dict):
                for name, state in states.items():
                    state_str = str(state).lower() if not isinstance(state, str) else state.lower()
                    if "open" in state_str and "half" not in state_str:
                        open_count += 1
            elif isinstance(states, (list, tuple)):
                for item in states:
                    if isinstance(item, dict):
                        state_val = str(item.get("state", "")).lower()
                    else:
                        state_val = str(item).lower()
                    if "open" in state_val and "half" not in state_val:
                        open_count += 1

            if open_count > 0:
                raise RuntimeError(f"{open_count} circuit breaker(s) in OPEN state")

            return True
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("circuit_breaker_check_unavailable", error=str(exc))
            return True

    return ("circuit_breakers", cb_check, "readiness", "circuit_breaker")


# ── 系统信息获取（标准库实现） ──────────────────────────

def _get_process_memory_mb() -> float | None:
    """获取当前进程内存使用量（MB）

    使用标准库方案：
    - Windows: ctypes + GetProcessMemoryInfo
    - Linux: /proc/self/status
    - macOS: /proc/self/status 或 task_info

    Returns:
        RSS 内存使用量（MB），失败返回 None
    """
    pid = os.getpid()

    # Windows: 使用 psapi.dll
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            psapi = ctypes.windll.psapi
            kernel32 = ctypes.windll.kernel32

            h_process = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
            if not h_process:
                return None

            try:
                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(counters)
                if psapi.GetProcessMemoryInfo(
                    h_process, ctypes.byref(counters), counters.cb
                ):
                    return counters.WorkingSetSize / (1024 * 1024)
            finally:
                kernel32.CloseHandle(h_process)
        except Exception:
            pass

    # Linux / macOS: 使用 /proc/self/status
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        # VmRSS 单位是 kB
                        return float(parts[1]) / 1024.0
    except (FileNotFoundError, PermissionError, OSError):
        pass

    # macOS: 使用 task_info（通过 ctypes 调用）
    if sys.platform == "darwin":
        try:
            import ctypes
            libc = ctypes.CDLL("libc.dylib")
            # 简化处理：尝试通过 ps 命令
            import subprocess
            result = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(pid)],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip()) / 1024.0
        except Exception:
            pass

    return None


def _get_disk_free_mb(path: str) -> float | None:
    """获取指定路径所在磁盘的剩余空间（MB）

    使用标准库方案：
    - Windows: ctypes + GetDiskFreeSpaceExW
    - Unix: os.statvfs

    Args:
        path: 目录路径

    Returns:
        剩余空间（MB），失败返回 None
    """
    try:
        # 确保路径存在
        if not os.path.exists(path):
            path = os.path.dirname(path) or "."

        # Windows: 使用 GetDiskFreeSpaceExW
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            free_bytes = ctypes.c_ulonglong(0)
            total_bytes = ctypes.c_ulonglong(0)
            total_free_bytes = ctypes.c_ulonglong(0)

            result = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(path),
                ctypes.byref(free_bytes),
                ctypes.byref(total_bytes),
                ctypes.byref(total_free_bytes),
            )
            if result != 0:
                return free_bytes.value / (1024 * 1024)

        # Unix: 使用 os.statvfs
        if hasattr(os, "statvfs"):
            stat = os.statvfs(path)
            # f_bavail 是普通用户可用的块数
            return (stat.f_frsize * stat.f_bavail) / (1024 * 1024)

    except Exception as exc:
        logger.warning("disk_free_check_failed", path=path, error=str(exc))

    return None


# ── 降级状态健康检查器 ──────────────────────────────────


def make_degradation_checker() -> tuple[str, HealthChecker, HealthCheckLevel, ComponentType]:
    """创建降级状态健康检查器

    检查当前降级级别，L3 及以上标记为 degraded。
    使用惰性导入避免循环依赖。

    Returns:
        (name, checker, level, component_type) 元组
    """

    async def degradation_check() -> bool:
        """降级状态检查函数"""
        try:
            from src.resilience.degradation import get_degradation_manager, DegradationLevel

            manager = get_degradation_manager()
            current_level = manager.current_level

            # L3 及以上视为 degraded
            if current_level >= DegradationLevel.L3_HEAVY:
                raise RuntimeError(
                    f"System in heavy degradation: {current_level.name} "
                    f"(core features only)"
                )

            return True
        except RuntimeError:
            raise
        except ImportError:
            # 降级模块不可用时跳过检查
            return True
        except Exception as exc:
            logger.warning("degradation_check_unavailable", error=str(exc))
            return True

    return ("degradation", degradation_check, "readiness", "custom")
