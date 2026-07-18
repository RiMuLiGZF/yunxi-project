"""
云汐系统 - 统一健康检查体系 v2.0

提供 Kubernetes 风格的四级健康检查：
- Liveness（活性）：进程是否在运行
- Readiness（就绪）：是否可以接收流量
- Startup（启动）：是否启动完成
- Deep（深度）：数据库/缓存/依赖服务是否正常

额外能力：
- 健康评分（0-100）
- 依赖健康状态级联
- 健康指标（Prometheus 格式）
- 详细健康信息（含依赖拓扑）

使用方式：
    from shared.health import HealthChecker, create_health_router

    checker = HealthChecker(module_name="m8", version="1.0.0")
    checker.register_liveness_check("process", lambda: True)
    checker.register_readiness_check("db", check_db, critical=True)
    checker.register_startup_check("init", check_init)

    router = create_health_router(checker)
    app.include_router(router)
"""
import time
import os
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Callable, Awaitable, Union
from dataclasses import dataclass, field
from enum import Enum
from functools import partial


# ============================================================================
# 健康状态枚举
# ============================================================================

class HealthStatus(str, Enum):
    """健康状态枚举"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class CheckType(str, Enum):
    """检查类型"""
    LIVENESS = "liveness"       # 活性检查
    READINESS = "readiness"     # 就绪检查
    STARTUP = "startup"         # 启动检查
    DEEP = "deep"               # 深度检查


# ============================================================================
# 数据类
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
        return cls(status=HealthStatus.HEALTHY, details=details)

    @classmethod
    def degraded(cls, error: Optional[str] = None, **details) -> "CheckResult":
        return cls(status=HealthStatus.DEGRADED, error=error, details=details)

    @classmethod
    def unhealthy(cls, error: Optional[str] = None, **details) -> "CheckResult":
        return cls(status=HealthStatus.UNHEALTHY, error=error, details=details)


@dataclass
class HealthResponse:
    """健康检查响应"""
    status: HealthStatus
    version: str
    module: str
    module_name: str
    timestamp: str
    uptime_seconds: float
    score: int = 100
    checks: Dict[str, CheckResult] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "score": self.score,
            "version": self.version,
            "module": self.module,
            "module_name": self.module_name,
            "timestamp": self.timestamp,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "checks": {
                name: result.to_dict()
                for name, result in self.checks.items()
            },
        }


@dataclass
class DependencyInfo:
    """依赖服务信息"""
    name: str
    url: Optional[str] = None
    status: HealthStatus = HealthStatus.UNHEALTHY
    last_check: Optional[str] = None
    response_time_ms: float = 0.0


# ============================================================================
# 内置检查器
# ============================================================================

def check_memory(threshold_percent: float = 90.0) -> CheckResult:
    """检查内存使用情况"""
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
            return CheckResult.degraded(
                error=f"Memory usage {mem.percent}% exceeds threshold {threshold_percent}%",
                **details,
            )
        return CheckResult.healthy(**details)
    except ImportError:
        return CheckResult.degraded(error="psutil not available")
    except Exception as e:
        return CheckResult.degraded(error=str(e))


def check_disk(path: str = ".", threshold_percent: float = 90.0) -> CheckResult:
    """检查磁盘使用情况"""
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
            return CheckResult.degraded(
                error=f"Disk usage {percent:.1f}% exceeds threshold {threshold_percent}%",
                **details,
            )
        return CheckResult.healthy(**details)
    except Exception as e:
        return CheckResult.degraded(error=str(e))


def check_cpu(threshold_percent: float = 90.0) -> CheckResult:
    """检查 CPU 使用情况"""
    start_time = time.time()
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count()
        load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else (0, 0, 0)
        response_time = (time.time() - start_time) * 1000

        details = {
            "percent": cpu_percent,
            "cpu_count": cpu_count,
            "load_avg_1m": round(load_avg[0], 2),
            "load_avg_5m": round(load_avg[1], 2),
            "load_avg_15m": round(load_avg[2], 2),
        }

        if cpu_percent >= threshold_percent:
            return CheckResult.degraded(
                error=f"CPU usage {cpu_percent}% exceeds threshold {threshold_percent}%",
                **details,
            )
        return CheckResult.healthy(**details)
    except ImportError:
        return CheckResult.degraded(error="psutil not available")
    except Exception as e:
        return CheckResult.degraded(error=str(e))


def check_redis(redis_client: Any) -> CheckResult:
    """检查 Redis 连接"""
    start_time = time.time()
    try:
        result = redis_client.ping()
        response_time = (time.time() - start_time) * 1000
        if result:
            return CheckResult.healthy(type="redis", response_time_ms=response_time)
        return CheckResult.degraded(error="Redis ping returned False")
    except Exception as e:
        return CheckResult.unhealthy(error=str(e), type="redis")


def check_http_endpoint(url: str, timeout: float = 5.0) -> CheckResult:
    """检查 HTTP 端点可用性"""
    start_time = time.time()
    try:
        import urllib.request
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.status
            response_time = (time.time() - start_time) * 1000

            if 200 <= status_code < 400:
                return CheckResult.healthy(status_code=status_code, url=url)
            else:
                return CheckResult.degraded(
                    error=f"HTTP {status_code}",
                    status_code=status_code,
                    url=url,
                )
    except Exception as e:
        return CheckResult.unhealthy(error=str(e), url=url)


# ============================================================================
# 健康检查器（增强版）
# ============================================================================

class HealthChecker:
    """
    增强版健康检查器

    支持四种检查类型：
    - liveness_checks: 活性检查（进程是否存活）
    - readiness_checks: 就绪检查（是否可接收流量）
    - startup_checks: 启动检查（是否启动完成）
    - deep_checks: 深度检查（所有依赖）

    健康评分规则：
    - 基础分 100
    - 每个核心检查失败 -20
    - 每个非核心检查失败 -10
    - 每个检查 degraded -5
    - 最低 0 分
    """

    def __init__(
        self,
        module_name: str,
        version: str = "unknown",
        module_display_name: Optional[str] = None,
    ):
        self.module_name = module_name
        self.version = version
        self.module_display_name = module_display_name or module_name
        self._start_time = time.time()
        self._startup_complete = False
        self._startup_completion_time: Optional[float] = None

        # 分类存储检查项
        self._liveness_checks: Dict[str, Callable] = {}
        self._readiness_checks: Dict[str, Callable] = {}
        self._startup_checks: Dict[str, Callable] = {}
        self._deep_checks: Dict[str, Callable] = {}

        # 核心检查标记
        self._critical_checks: set = set()

        # 异步检查
        self._async_liveness: Dict[str, Callable] = {}
        self._async_readiness: Dict[str, Callable] = {}
        self._async_startup: Dict[str, Callable] = {}
        self._async_deep: Dict[str, Callable] = {}
        self._async_critical: set = set()

        # 依赖服务信息
        self._dependencies: Dict[str, DependencyInfo] = {}

    # ---- 注册方法 ----

    def register_liveness_check(
        self,
        name: str,
        check_fn: Callable[[], CheckResult],
    ) -> None:
        """注册活性检查"""
        self._liveness_checks[name] = check_fn

    def register_readiness_check(
        self,
        name: str,
        check_fn: Callable[[], CheckResult],
        critical: bool = False,
    ) -> None:
        """注册就绪检查"""
        self._readiness_checks[name] = check_fn
        if critical:
            self._critical_checks.add(name)

    def register_startup_check(
        self,
        name: str,
        check_fn: Callable[[], CheckResult],
        critical: bool = True,
    ) -> None:
        """注册启动检查"""
        self._startup_checks[name] = check_fn
        if critical:
            self._critical_checks.add(name)

    def register_deep_check(
        self,
        name: str,
        check_fn: Callable[[], CheckResult],
        critical: bool = False,
    ) -> None:
        """注册深度检查"""
        self._deep_checks[name] = check_fn
        if critical:
            self._critical_checks.add(name)

    def register_async_liveness_check(
        self, name: str, check_fn: Callable[[], Awaitable[CheckResult]]
    ) -> None:
        """注册异步活性检查"""
        self._async_liveness[name] = check_fn

    def register_async_readiness_check(
        self,
        name: str,
        check_fn: Callable[[], Awaitable[CheckResult]],
        critical: bool = False,
    ) -> None:
        """注册异步就绪检查"""
        self._async_readiness[name] = check_fn
        if critical:
            self._async_critical.add(name)

    def register_async_startup_check(
        self,
        name: str,
        check_fn: Callable[[], Awaitable[CheckResult]],
        critical: bool = True,
    ) -> None:
        """注册异步启动检查"""
        self._async_startup[name] = check_fn
        if critical:
            self._async_critical.add(name)

    def register_async_deep_check(
        self,
        name: str,
        check_fn: Callable[[], Awaitable[CheckResult]],
        critical: bool = False,
    ) -> None:
        """注册异步深度检查"""
        self._async_deep[name] = check_fn
        if critical:
            self._async_critical.add(name)

    # ---- 便捷注册方法 ----

    def register_memory_check(
        self, threshold_percent: float = 90.0, check_type: CheckType = CheckType.READINESS
    ) -> None:
        """注册内存检查"""
        fn = partial(check_memory, threshold_percent)
        self._register_by_type("memory", fn, check_type)

    def register_disk_check(
        self,
        path: str = ".",
        threshold_percent: float = 90.0,
        check_type: CheckType = CheckType.READINESS,
    ) -> None:
        """注册磁盘检查"""
        fn = partial(check_disk, path, threshold_percent)
        self._register_by_type("disk", fn, check_type)

    def register_cpu_check(
        self, threshold_percent: float = 90.0, check_type: CheckType = CheckType.READINESS
    ) -> None:
        """注册 CPU 检查"""
        fn = partial(check_cpu, threshold_percent)
        self._register_by_type("cpu", fn, check_type)

    def _register_by_type(self, name: str, fn: Callable, check_type: CheckType) -> None:
        """按类型注册检查"""
        if check_type == CheckType.LIVENESS:
            self.register_liveness_check(name, fn)
        elif check_type == CheckType.READINESS:
            self.register_readiness_check(name, fn, critical=False)
        elif check_type == CheckType.STARTUP:
            self.register_startup_check(name, fn, critical=True)
        elif check_type == CheckType.DEEP:
            self.register_deep_check(name, fn, critical=False)

    def add_dependency(self, name: str, url: Optional[str] = None) -> None:
        """添加依赖服务信息"""
        self._dependencies[name] = DependencyInfo(name=name, url=url)

    # ---- 核心检查逻辑 ----

    def _run_sync_checks(self, checks: Dict[str, Callable]) -> Dict[str, CheckResult]:
        """运行同步检查"""
        results = {}
        for name, fn in checks.items():
            try:
                results[name] = fn()
            except Exception as e:
                results[name] = CheckResult.degraded(error=f"Check exception: {str(e)}")
        return results

    async def _run_async_checks(
        self, async_checks: Dict[str, Callable]
    ) -> Dict[str, CheckResult]:
        """运行异步检查（并行）"""
        if not async_checks:
            return {}

        async def _run_check(name: str, fn: Callable):
            try:
                return name, await fn()
            except Exception as e:
                return name, CheckResult.degraded(error=f"Check exception: {str(e)}")

        tasks = [_run_check(name, fn) for name, fn in async_checks.items()]
        results = await asyncio.gather(*tasks)
        return dict(results)

    def _aggregate_status(self, results: Dict[str, CheckResult]) -> HealthStatus:
        """汇总检查结果状态"""
        has_degraded = False

        for name, result in results.items():
            is_critical = name in self._critical_checks or name in self._async_critical
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

    def _calculate_score(self, results: Dict[str, CheckResult]) -> int:
        """计算健康评分（0-100）"""
        score = 100
        if not results:
            return score

        for name, result in results.items():
            is_critical = name in self._critical_checks or name in self._async_critical
            if result.status == HealthStatus.UNHEALTHY:
                score -= 20 if is_critical else 10
            elif result.status == HealthStatus.DEGRADED:
                score -= 10 if is_critical else 5

        return max(0, min(100, score))

    def _build_response(
        self,
        status: HealthStatus,
        checks: Dict[str, CheckResult],
    ) -> HealthResponse:
        """构建健康响应"""
        return HealthResponse(
            status=status,
            version=self.version,
            module=self.module_name,
            module_name=self.module_display_name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            uptime_seconds=time.time() - self._start_time,
            score=self._calculate_score(checks),
            checks=checks,
        )

    # ---- 各类检查接口 ----

    def check_liveness(self) -> HealthResponse:
        """活性检查（同步）"""
        # 活性检查默认总是通过（进程在运行就是存活）
        checks = {}
        if self._liveness_checks:
            checks = self._run_sync_checks(self._liveness_checks)
        else:
            checks["process"] = CheckResult.healthy(pid=os.getpid())

        status = self._aggregate_status(checks)
        return self._build_response(status, checks)

    def check_readiness(self) -> HealthResponse:
        """就绪检查（同步）"""
        # 如果启动未完成，则未就绪
        if not self._startup_complete and self._startup_checks:
            startup_results = self._run_sync_checks(self._startup_checks)
            startup_status = self._aggregate_status(startup_results)
            if startup_status != HealthStatus.HEALTHY:
                checks = {f"startup:{k}": v for k, v in startup_results.items()}
                checks["startup_complete"] = CheckResult.unhealthy(
                    error="Startup not complete"
                )
                return self._build_response(HealthStatus.UNHEALTHY, checks)
            else:
                self._mark_startup_complete()

        checks = self._run_sync_checks(self._readiness_checks)
        status = self._aggregate_status(checks)
        return self._build_response(status, checks)

    def check_startup(self) -> HealthResponse:
        """启动检查（同步）"""
        if self._startup_complete:
            checks = {"startup_complete": CheckResult.healthy()}
            return self._build_response(HealthStatus.HEALTHY, checks)

        checks = self._run_sync_checks(self._startup_checks)
        status = self._aggregate_status(checks)

        if status == HealthStatus.HEALTHY:
            self._mark_startup_complete()

        return self._build_response(status, checks)

    def check_deep(self) -> HealthResponse:
        """深度检查（同步）"""
        all_checks = {}
        all_checks.update(self._run_sync_checks(self._readiness_checks))
        all_checks.update(self._run_sync_checks(self._deep_checks))
        status = self._aggregate_status(all_checks)
        return self._build_response(status, all_checks)

    # ---- 异步版本 ----

    async def async_check_liveness(self) -> HealthResponse:
        """活性检查（异步）"""
        checks = {}
        sync_checks = self._run_sync_checks(self._liveness_checks)
        async_checks = await self._run_async_checks(self._async_liveness)
        checks.update(sync_checks)
        checks.update(async_checks)

        if not checks:
            checks["process"] = CheckResult.healthy(pid=os.getpid())

        status = self._aggregate_status(checks)
        return self._build_response(status, checks)

    async def async_check_readiness(self) -> HealthResponse:
        """就绪检查（异步）"""
        # 如果启动未完成，则未就绪
        if not self._startup_complete and (self._startup_checks or self._async_startup):
            startup_sync = self._run_sync_checks(self._startup_checks)
            startup_async = await self._run_async_checks(self._async_startup)
            startup_results = {**startup_sync, **startup_async}
            startup_status = self._aggregate_status(startup_results)
            if startup_status != HealthStatus.HEALTHY:
                checks = {f"startup:{k}": v for k, v in startup_results.items()}
                checks["startup_complete"] = CheckResult.unhealthy(
                    error="Startup not complete"
                )
                return self._build_response(HealthStatus.UNHEALTHY, checks)
            else:
                self._mark_startup_complete()

        sync_checks = self._run_sync_checks(self._readiness_checks)
        async_checks = await self._run_async_checks(self._async_readiness)
        checks = {**sync_checks, **async_checks}
        status = self._aggregate_status(checks)
        return self._build_response(status, checks)

    async def async_check_startup(self) -> HealthResponse:
        """启动检查（异步）"""
        if self._startup_complete:
            checks = {"startup_complete": CheckResult.healthy()}
            return self._build_response(HealthStatus.HEALTHY, checks)

        sync_checks = self._run_sync_checks(self._startup_checks)
        async_checks = await self._run_async_checks(self._async_startup)
        checks = {**sync_checks, **async_checks}
        status = self._aggregate_status(checks)

        if status == HealthStatus.HEALTHY:
            self._mark_startup_complete()

        return self._build_response(status, checks)

    async def async_check_deep(self) -> HealthResponse:
        """深度检查（异步）"""
        all_checks = {}
        all_checks.update(self._run_sync_checks(self._readiness_checks))
        all_checks.update(self._run_sync_checks(self._deep_checks))
        all_checks.update(await self._run_async_checks(self._async_readiness))
        all_checks.update(await self._run_async_checks(self._async_deep))
        status = self._aggregate_status(all_checks)
        return self._build_response(status, all_checks)

    # ---- 详细信息 ----

    def get_details(self) -> Dict[str, Any]:
        """获取详细健康信息"""
        result = self.check_deep()
        data = result.to_dict()

        # 添加依赖信息
        data["dependencies"] = {
            name: {
                "name": dep.name,
                "url": dep.url,
                "status": dep.status.value,
                "last_check": dep.last_check,
            }
            for name, dep in self._dependencies.items()
        }

        # 添加系统信息
        try:
            import psutil
            data["system"] = {
                "pid": os.getpid(),
                "cpu_count": psutil.cpu_count(),
                "memory_total_mb": round(psutil.virtual_memory().total / (1024 * 1024), 2),
            }
        except ImportError:
            data["system"] = {"pid": os.getpid()}

        return data

    def get_metrics(self) -> Dict[str, Any]:
        """获取健康指标（Prometheus 格式数据）"""
        result = self.check_deep()
        metrics = []

        # 基础指标
        metrics.append(
            f'yunxi_health_status{{module="{self.module_name}"}} '
            f'{1 if result.status == HealthStatus.HEALTHY else 0}'
        )
        metrics.append(
            f'yunxi_health_score{{module="{self.module_name}"}} {result.score}'
        )
        metrics.append(
            f'yunxi_uptime_seconds{{module="{self.module_name}"}} '
            f'{round(result.uptime_seconds, 2)}'
        )

        # 各检查项指标
        for name, check in result.checks.items():
            status_val = 1 if check.status == HealthStatus.HEALTHY else (
                0.5 if check.status == HealthStatus.DEGRADED else 0
            )
            metrics.append(
                f'yunxi_health_check_status{{module="{self.module_name}",check="{name}"}} '
                f'{status_val}'
            )
            metrics.append(
                f'yunxi_health_check_response_time_ms{{module="{self.module_name}",check="{name}"}} '
                f'{round(check.response_time_ms, 2)}'
            )

        return {"prometheus": "\n".join(metrics), "score": result.score}

    # ---- 辅助方法 ----

    def _mark_startup_complete(self) -> None:
        """标记启动完成"""
        if not self._startup_complete:
            self._startup_complete = True
            self._startup_completion_time = time.time()

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time

    @property
    def is_startup_complete(self) -> bool:
        return self._startup_complete

    def reset_start_time(self) -> None:
        self._start_time = time.time()
        self._startup_complete = False
        self._startup_completion_time = None


# ============================================================================
# FastAPI 集成
# ============================================================================

def create_health_router(
    checker: HealthChecker,
    prefix: str = "",
    include_metrics: bool = True,
) -> Any:
    """
    创建 FastAPI 健康检查路由（v2.0 完整版）

    端点：
    - GET /health            - 综合健康状态（就绪检查）
    - GET /health/live       - 活性检查
    - GET /health/ready      - 就绪检查
    - GET /health/startup    - 启动检查
    - GET /health/details    - 详细健康信息
    - GET /health/metrics    - 健康指标（Prometheus 格式）
    """
    from fastapi import APIRouter, Query, Request
    from fastapi.responses import Response, JSONResponse

    router = APIRouter(prefix=prefix, tags=["health"])

    @router.get("/health", summary="综合健康状态")
    async def health_endpoint(
        deep: bool = Query(default=False, description="是否执行深度检查"),
    ):
        """综合健康检查端点"""
        if deep:
            result = await checker.async_check_deep()
        else:
            result = await checker.async_check_readiness()
        return result.to_dict()

    @router.get("/health/live", summary="活性检查")
    async def health_live():
        """活性检查：进程是否在运行"""
        result = await checker.async_check_liveness()
        status_code = 200 if result.status == HealthStatus.HEALTHY else 503
        return JSONResponse(status_code=status_code, content=result.to_dict())

    @router.get("/health/ready", summary="就绪检查")
    async def health_ready():
        """就绪检查：是否可以接收流量"""
        result = await checker.async_check_readiness()
        status_code = 200 if result.status == HealthStatus.HEALTHY else 503
        return JSONResponse(status_code=status_code, content=result.to_dict())

    @router.get("/health/startup", summary="启动检查")
    async def health_startup():
        """启动检查：是否启动完成"""
        result = await checker.async_check_startup()
        status_code = 200 if result.status == HealthStatus.HEALTHY else 503
        return JSONResponse(status_code=status_code, content=result.to_dict())

    @router.get("/health/details", summary="详细健康信息")
    async def health_details():
        """详细健康信息：包含所有检查项、依赖、系统信息"""
        return checker.get_details()

    if include_metrics:
        @router.get("/health/metrics", summary="健康指标")
        async def health_metrics(request: Request):
            """健康指标（Prometheus 格式）"""
            metrics_data = checker.get_metrics()
            return Response(
                content=metrics_data["prometheus"],
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
    """获取全局健康检查器"""
    global _global_checker
    if _global_checker is None:
        if module_name is None:
            module_name = "yunxi"
        if version is None:
            try:
                from shared.core.version import SYSTEM_VERSION
                version = SYSTEM_VERSION
            except ImportError:
                version = "unknown"
        _global_checker = HealthChecker(
            module_name=module_name,
            version=version,
        )
    return _global_checker


def set_health_checker(checker: HealthChecker) -> None:
    """设置全局健康检查器"""
    global _global_checker
    _global_checker = checker
