"""
云汐健康检查标准化模块

提供统一的健康检查框架，支持：
- 统一健康检查响应格式（status/version/module/timestamp/uptime/checks）
- 三级健康状态：healthy / degraded / unhealthy
- 深度检查（deep=true，检查所有依赖）
- 轻量检查（默认，只检查自身状态）
- 依赖健康检查：数据库、Redis、磁盘、内存、外部服务等
- 健康状态汇总逻辑（所有依赖健康=healthy，部分降级=degraded，核心失败=unhealthy）
- 可扩展的检查器注册机制

使用方式：
    from shared.core.health import HealthChecker, HealthStatus, CheckResult
    from shared.core.health import create_fastapi_health_router

    # 创建健康检查器
    checker = HealthChecker(module_name="m8", version="1.0.0")

    # 注册依赖检查
    checker.register_check("database", check_db, critical=True)
    checker.register_check("redis", check_redis, critical=False)
    checker.register_check("disk", check_disk, critical=False)

    # 获取健康状态
    result = checker.check(deep=True)

    # FastAPI 集成
    router = create_fastapi_health_router(checker)
    app.include_router(router)
"""
import time
import os
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Callable, Awaitable, Union
from dataclasses import dataclass, field
from enum import Enum


# ============================================================================
# 健康状态枚举
# ============================================================================

class HealthStatus(str, Enum):
    """健康状态枚举

    - healthy: 所有检查通过，系统正常运行
    - degraded: 部分非核心检查失败，系统仍可提供核心服务
    - unhealthy: 核心检查失败，系统无法正常提供服务
    """
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


# ============================================================================
# 检查结果
# ============================================================================

@dataclass
class CheckResult:
    """单项检查结果"""
    status: HealthStatus
    response_time_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": self.status.value,
            "response_time_ms": round(self.response_time_ms, 2),
        }
        if self.details:
            result.update(self.details)
        if self.error:
            result["error"] = self.error
        return result

    @classmethod
    def healthy(cls, **details) -> "CheckResult":
        """创建健康的检查结果"""
        return cls(status=HealthStatus.HEALTHY, details=details)

    @classmethod
    def degraded(cls, error: Optional[str] = None, **details) -> "CheckResult":
        """创建降级的检查结果"""
        return cls(status=HealthStatus.DEGRADED, error=error, details=details)

    @classmethod
    def unhealthy(cls, error: Optional[str] = None, **details) -> "CheckResult":
        """创建不健康的检查结果"""
        return cls(status=HealthStatus.UNHEALTHY, error=error, details=details)


# ============================================================================
# 健康检查响应
# ============================================================================

@dataclass
class HealthResponse:
    """健康检查响应（标准格式）"""
    status: HealthStatus
    version: str
    module: str
    timestamp: str
    uptime_seconds: float
    checks: Dict[str, CheckResult] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "version": self.version,
            "module": self.module,
            "timestamp": self.timestamp,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "checks": {
                name: result.to_dict()
                for name, result in self.checks.items()
            },
        }


# ============================================================================
# 内置检查器
# ============================================================================

def check_memory(threshold_percent: float = 90.0) -> CheckResult:
    """检查内存使用情况

    Args:
        threshold_percent: 告警阈值（百分比），默认 90%

    Returns:
        CheckResult
    """
    start_time = time.time()
    try:
        import psutil
        mem = psutil.virtual_memory()
        response_time = (time.time() - start_time) * 1000

        details = {
            "total_mb": round(mem.total / (1024 * 1024), 2),
            "used_mb": round(mem.used / (1024 * 1024), 2),
            "available_mb": round(mem.available / (1024 * 1024), 2),
            "percent": mem.percent,
        }

        if mem.percent >= threshold_percent:
            return CheckResult(
                status=HealthStatus.DEGRADED,
                response_time_ms=response_time,
                details=details,
                error=f"Memory usage {mem.percent}% exceeds threshold {threshold_percent}%",
            )
        return CheckResult(
            status=HealthStatus.HEALTHY,
            response_time_ms=response_time,
            details=details,
        )
    except ImportError:
        return CheckResult(
            status=HealthStatus.DEGRADED,
            response_time_ms=(time.time() - start_time) * 1000,
            error="psutil not available",
        )
    except Exception as e:
        return CheckResult(
            status=HealthStatus.DEGRADED,
            response_time_ms=(time.time() - start_time) * 1000,
            error=str(e),
        )


def check_disk(path: str = ".", threshold_percent: float = 90.0) -> CheckResult:
    """检查磁盘使用情况

    Args:
        path: 要检查的磁盘路径
        threshold_percent: 告警阈值（百分比），默认 90%

    Returns:
        CheckResult
    """
    start_time = time.time()
    try:
        import shutil
        usage = shutil.disk_usage(path)
        percent = (usage.used / usage.total) * 100
        response_time = (time.time() - start_time) * 1000

        details = {
            "path": os.path.abspath(path),
            "total_gb": round(usage.total / (1024 ** 3), 2),
            "used_gb": round(usage.used / (1024 ** 3), 2),
            "free_gb": round(usage.free / (1024 ** 3), 2),
            "percent": round(percent, 2),
        }

        if percent >= threshold_percent:
            return CheckResult(
                status=HealthStatus.DEGRADED,
                response_time_ms=response_time,
                details=details,
                error=f"Disk usage {percent:.1f}% exceeds threshold {threshold_percent}%",
            )
        return CheckResult(
            status=HealthStatus.HEALTHY,
            response_time_ms=response_time,
            details=details,
        )
    except Exception as e:
        return CheckResult(
            status=HealthStatus.DEGRADED,
            response_time_ms=(time.time() - start_time) * 1000,
            error=str(e),
        )


def check_database_sqlalchemy(session_factory: Callable) -> CheckResult:
    """检查 SQLAlchemy 数据库连接

    Args:
        session_factory: 数据库会话工厂函数（返回 Session）

    Returns:
        CheckResult
    """
    start_time = time.time()
    try:
        session = session_factory()
        try:
            # 执行简单查询验证连接
            session.execute("SELECT 1")
            response_time = (time.time() - start_time) * 1000
            return CheckResult(
                status=HealthStatus.HEALTHY,
                response_time_ms=response_time,
                details={"type": "sqlalchemy"},
            )
        finally:
            session.close()
    except Exception as e:
        return CheckResult(
            status=HealthStatus.UNHEALTHY,
            response_time_ms=(time.time() - start_time) * 1000,
            error=str(e),
            details={"type": "sqlalchemy"},
        )


def check_redis(redis_client: Any) -> CheckResult:
    """检查 Redis 连接

    Args:
        redis_client: Redis 客户端实例（需支持 ping() 方法）

    Returns:
        CheckResult
    """
    start_time = time.time()
    try:
        result = redis_client.ping()
        response_time = (time.time() - start_time) * 1000
        if result:
            return CheckResult(
                status=HealthStatus.HEALTHY,
                response_time_ms=response_time,
                details={"type": "redis"},
            )
        return CheckResult(
            status=HealthStatus.DEGRADED,
            response_time_ms=response_time,
            error="Redis ping returned False",
        )
    except Exception as e:
        return CheckResult(
            status=HealthStatus.UNHEALTHY,
            response_time_ms=(time.time() - start_time) * 1000,
            error=str(e),
            details={"type": "redis"},
        )


def check_http_endpoint(url: str, timeout: float = 5.0) -> CheckResult:
    """检查 HTTP 端点可用性

    Args:
        url: 要检查的 URL
        timeout: 超时时间（秒）

    Returns:
        CheckResult
    """
    start_time = time.time()
    try:
        import urllib.request
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.status
            response_time = (time.time() - start_time) * 1000

            if 200 <= status_code < 400:
                return CheckResult(
                    status=HealthStatus.HEALTHY,
                    response_time_ms=response_time,
                    details={"status_code": status_code, "url": url},
                )
            else:
                return CheckResult(
                    status=HealthStatus.DEGRADED,
                    response_time_ms=response_time,
                    error=f"HTTP {status_code}",
                    details={"status_code": status_code, "url": url},
                )
    except Exception as e:
        return CheckResult(
            status=HealthStatus.UNHEALTHY,
            response_time_ms=(time.time() - start_time) * 1000,
            error=str(e),
            details={"url": url},
        )


# ============================================================================
# 健康检查器
# ============================================================================

class HealthChecker:
    """健康检查器

    支持注册多个检查项，自动汇总健康状态。

    检查项分为：
    - 核心检查（critical=True）：失败则整体状态为 unhealthy
    - 非核心检查（critical=False）：失败则整体状态为 degraded
    """

    def __init__(
        self,
        module_name: str,
        version: str = "unknown",
        module_display_name: Optional[str] = None,
    ):
        """
        Args:
            module_name: 模块名称（如 "m8", "gateway"）
            version: 版本号
            module_display_name: 模块显示名称（如 "云汐管理台"）
        """
        self.module_name = module_name
        self.version = version
        self.module_display_name = module_display_name or module_name
        self._start_time = time.time()
        self._checks: Dict[str, Callable[[], CheckResult]] = {}
        self._critical_checks: set = set()
        self._async_checks: Dict[str, Callable[[], Awaitable[CheckResult]]] = {}
        self._async_critical_checks: set = set()
        self._lightweight_checks: set = set()  # 轻量检查（默认执行）

    def register_check(
        self,
        name: str,
        check_fn: Callable[[], CheckResult],
        critical: bool = False,
        lightweight: bool = False,
    ) -> None:
        """注册一个同步检查项

        Args:
            name: 检查项名称（如 "database", "redis"）
            check_fn: 检查函数，返回 CheckResult
            critical: 是否为核心检查（失败则 unhealthy）
            lightweight: 是否为轻量检查（默认执行，非 deep 模式也执行）
        """
        self._checks[name] = check_fn
        if critical:
            self._critical_checks.add(name)
        if lightweight:
            self._lightweight_checks.add(name)

    def register_async_check(
        self,
        name: str,
        check_fn: Callable[[], Awaitable[CheckResult]],
        critical: bool = False,
        lightweight: bool = False,
    ) -> None:
        """注册一个异步检查项

        Args:
            name: 检查项名称
            check_fn: 异步检查函数，返回 CheckResult
            critical: 是否为核心检查
            lightweight: 是否为轻量检查
        """
        self._async_checks[name] = check_fn
        if critical:
            self._async_critical_checks.add(name)
        if lightweight:
            self._lightweight_checks.add(name)

    def register_memory_check(
        self,
        threshold_percent: float = 90.0,
        critical: bool = False,
        lightweight: bool = True,
    ) -> None:
        """注册内存检查（便捷方法）"""
        self.register_check(
            "memory",
            lambda: check_memory(threshold_percent),
            critical=critical,
            lightweight=lightweight,
        )

    def register_disk_check(
        self,
        path: str = ".",
        threshold_percent: float = 90.0,
        critical: bool = False,
        lightweight: bool = True,
    ) -> None:
        """注册磁盘检查（便捷方法）"""
        self.register_check(
            "disk",
            lambda: check_disk(path, threshold_percent),
            critical=critical,
            lightweight=lightweight,
        )

    def register_database_check(
        self,
        session_factory: Callable,
        critical: bool = True,
        lightweight: bool = False,
    ) -> None:
        """注册数据库检查（便捷方法）"""
        self.register_check(
            "database",
            lambda: check_database_sqlalchemy(session_factory),
            critical=critical,
            lightweight=lightweight,
        )

    def register_redis_check(
        self,
        redis_client: Any,
        critical: bool = False,
        lightweight: bool = False,
    ) -> None:
        """注册 Redis 检查（便捷方法）"""
        self.register_check(
            "redis",
            lambda: check_redis(redis_client),
            critical=critical,
            lightweight=lightweight,
        )

    def _get_check_names(self, deep: bool) -> List[str]:
        """获取要执行的检查项名称列表"""
        if deep:
            return list(self._checks.keys()) + list(self._async_checks.keys())
        # 非 deep 模式：只执行轻量检查
        return list(self._lightweight_checks)

    def _aggregate_status(self, results: Dict[str, CheckResult]) -> HealthStatus:
        """汇总检查结果状态

        规则：
        - 任一核心检查失败（unhealthy）→ 整体 unhealthy
        - 任一非核心检查失败（degraded 或 unhealthy）→ 整体 degraded
        - 所有检查健康 → healthy
        """
        has_degraded = False

        for name, result in results.items():
            is_critical = (
                name in self._critical_checks
                or name in self._async_critical_checks
            )
            if result.status == HealthStatus.UNHEALTHY:
                if is_critical:
                    return HealthStatus.UNHEALTHY
                else:
                    has_degraded = True
            elif result.status == HealthStatus.DEGRADED:
                has_degraded = True

        if has_degraded:
            return HealthStatus.DEGRADED

        return HealthStatus.HEALTHY

    def check(self, deep: bool = False) -> HealthResponse:
        """执行健康检查（同步版本）

        Args:
            deep: 是否执行深度检查（包含所有非轻量检查）

        Returns:
            HealthResponse
        """
        results: Dict[str, CheckResult] = {}
        check_names = self._get_check_names(deep)

        for name in check_names:
            if name in self._checks:
                try:
                    results[name] = self._checks[name]()
                except Exception as e:
                    results[name] = CheckResult(
                        status=HealthStatus.DEGRADED,
                        error=f"Check exception: {str(e)}",
                    )
            # 异步检查在同步模式下跳过（提示需使用 async_check）

        overall_status = self._aggregate_status(results)

        return HealthResponse(
            status=overall_status,
            version=self.version,
            module=self.module_name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            uptime_seconds=time.time() - self._start_time,
            checks=results,
        )

    async def async_check(self, deep: bool = False) -> HealthResponse:
        """执行健康检查（异步版本，支持异步检查项）

        Args:
            deep: 是否执行深度检查

        Returns:
            HealthResponse
        """
        results: Dict[str, CheckResult] = {}
        check_names = self._get_check_names(deep)

        # 收集同步和异步任务
        sync_names = [n for n in check_names if n in self._checks]
        async_names = [n for n in check_names if n in self._async_checks]

        # 同步检查
        for name in sync_names:
            try:
                results[name] = self._checks[name]()
            except Exception as e:
                results[name] = CheckResult(
                    status=HealthStatus.DEGRADED,
                    error=f"Check exception: {str(e)}",
                )

        # 异步检查（并行执行）
        if async_names:
            async_tasks = []
            for name in async_names:
                async def _run_check(fn, n):
                    try:
                        return n, await fn()
                    except Exception as e:
                        return n, CheckResult(
                            status=HealthStatus.DEGRADED,
                            error=f"Check exception: {str(e)}",
                        )
                async_tasks.append(_run_check(self._async_checks[name], name))

            async_results = await asyncio.gather(*async_tasks)
            for name, result in async_results:
                results[name] = result

        overall_status = self._aggregate_status(results)

        return HealthResponse(
            status=overall_status,
            version=self.version,
            module=self.module_name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            uptime_seconds=time.time() - self._start_time,
            checks=results,
        )

    @property
    def uptime_seconds(self) -> float:
        """获取运行时间（秒）"""
        return time.time() - self._start_time

    def reset_start_time(self) -> None:
        """重置启动时间"""
        self._start_time = time.time()


# ============================================================================
# FastAPI 集成
# ============================================================================

def create_fastapi_health_router(
    checker: HealthChecker,
    prefix: str = "",
    include_metrics: bool = True,
) -> Any:
    """创建 FastAPI 健康检查路由

    Args:
        checker: HealthChecker 实例
        prefix: 路由前缀
        include_metrics: 是否包含 /metrics 端点

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, Query, Request
    from fastapi.responses import Response

    router = APIRouter(prefix=prefix, tags=["health"])

    @router.get("/health", summary="健康检查")
    async def health_endpoint(
        deep: bool = Query(default=False, description="是否执行深度检查（检查所有依赖）"),
    ):
        """健康检查端点

        - 轻量检查（默认）：只检查自身状态和轻量依赖
        - 深度检查（deep=true）：检查所有依赖项

        返回标准健康检查格式。
        """
        result = await checker.async_check(deep=deep)
        return result.to_dict()

    if include_metrics:
        @router.get("/metrics", summary="Prometheus 指标")
        async def metrics_endpoint(request: Request):
            """Prometheus 格式的指标端点"""
            from .metrics import get_metrics
            metrics = get_metrics()
            return Response(
                content=metrics.to_prometheus(),
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )

    return router


# ============================================================================
# 全局健康检查器（单例）
# ============================================================================

_global_checker: Optional[HealthChecker] = None


def get_health_checker(
    module_name: Optional[str] = None,
    version: Optional[str] = None,
) -> HealthChecker:
    """获取全局健康检查器

    Args:
        module_name: 模块名（首次调用时设置）
        version: 版本号（首次调用时设置）

    Returns:
        HealthChecker 实例
    """
    global _global_checker
    if _global_checker is None:
        if module_name is None:
            module_name = "yunxi"
        if version is None:
            try:
                from ..version import SYSTEM_VERSION
                version = SYSTEM_VERSION
            except ImportError:
                version = "unknown"
        _global_checker = HealthChecker(module_name=module_name, version=version)
    return _global_checker


def set_health_checker(checker: HealthChecker) -> None:
    """设置全局健康检查器"""
    global _global_checker
    _global_checker = checker
