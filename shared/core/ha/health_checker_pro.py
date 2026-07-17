"""
云汐健康检查增强模块 (Health Checker Pro)

在原有 HealthChecker 基础上增强：
- TCP 端口健康检查
- 依赖健康检查（数据库、缓存、外部服务）
- 资源健康检查（CPU、内存、磁盘）
- 不健康实例自动摘除
- 健康实例自动恢复
- 健康检查历史记录与趋势分析

使用方式：
    from shared.core.ha.health_checker_pro import HealthCheckerPro, HealthCheckType

    checker = HealthCheckerPro(module_name="m8", version="1.0.0")
    checker.register_tcp_check("database", "127.0.0.1", 5432)
    checker.register_resource_check(cpu_threshold=80, memory_threshold=85)
    result = checker.check_all()
"""

from __future__ import annotations

import time
import socket
import threading
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable, Tuple
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ============================================================
# 枚举与常量
# ============================================================

class HealthCheckType(str, Enum):
    """健康检查类型"""
    HTTP = "http"               # HTTP 端点检查
    TCP = "tcp"                 # TCP 端口检查
    DEPENDENCY = "dependency"   # 依赖检查（数据库、缓存等）
    RESOURCE = "resource"       # 资源检查（CPU、内存、磁盘）
    CUSTOM = "custom"           # 自定义检查


class HealthLevel(str, Enum):
    """健康等级"""
    HEALTHY = "healthy"         # 健康
    DEGRADED = "degraded"       # 降级
    UNHEALTHY = "unhealthy"     # 不健康
    UNKNOWN = "unknown"         # 未知


# ============================================================
# 数据类
# ============================================================

@dataclass
class HealthCheckResult:
    """健康检查结果"""
    check_name: str
    check_type: HealthCheckType
    status: HealthLevel
    response_time_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_name": self.check_name,
            "check_type": self.check_type.value,
            "status": self.status.value,
            "response_time_ms": round(self.response_time_ms, 2),
            "details": self.details,
            "error": self.error,
            "timestamp": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
        }


@dataclass
class HealthCheckConfig:
    """健康检查配置"""
    name: str
    check_type: HealthCheckType
    check_fn: Callable[[], HealthCheckResult]
    critical: bool = False          # 是否核心检查（失败则整体不健康）
    interval: float = 30.0          # 检查间隔（秒）
    timeout: float = 5.0            # 超时时间（秒）
    failure_threshold: int = 3      # 连续失败次数阈值（达到后判定不健康）
    recovery_threshold: int = 2     # 连续成功次数阈值（达到后判定恢复）
    auto_remove: bool = True        # 是否自动摘除不健康实例
    auto_recover: bool = True       # 是否自动恢复健康实例


@dataclass
class CheckState:
    """检查项状态（用于跟踪连续失败/成功次数）"""
    config: HealthCheckConfig
    last_result: Optional[HealthCheckResult] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    is_removed: bool = False        # 是否已被摘除
    removed_at: Optional[float] = None
    history: deque = field(default_factory=lambda: deque(maxlen=100))

    def record_result(self, result: HealthCheckResult) -> None:
        """记录一次检查结果"""
        self.last_result = result
        self.history.append(result)

        if result.status == HealthLevel.HEALTHY:
            self.consecutive_successes += 1
            self.consecutive_failures = 0
        elif result.status in (HealthLevel.UNHEALTHY, HealthLevel.DEGRADED):
            self.consecutive_failures += 1
            self.consecutive_successes = 0

    @property
    def should_remove(self) -> bool:
        """是否应该摘除（达到失败阈值）"""
        if not self.config.auto_remove:
            return False
        if self.is_removed:
            return False
        return self.consecutive_failures >= self.config.failure_threshold

    @property
    def should_recover(self) -> bool:
        """是否应该恢复（达到成功阈值）"""
        if not self.config.auto_recover:
            return False
        if not self.is_removed:
            return False
        return self.consecutive_successes >= self.config.recovery_threshold


# ============================================================
# 内置检查实现
# ============================================================

class TcpHealthCheck:
    """TCP 端口健康检查"""

    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        timeout: float = 3.0,
    ):
        self.name = name
        self.host = host
        self.port = port
        self.timeout = timeout

    def check(self) -> HealthCheckResult:
        """执行 TCP 端口检查"""
        start_time = time.time()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex((self.host, self.port))
            sock.close()

            response_time = (time.time() - start_time) * 1000

            if result == 0:
                return HealthCheckResult(
                    check_name=self.name,
                    check_type=HealthCheckType.TCP,
                    status=HealthLevel.HEALTHY,
                    response_time_ms=response_time,
                    details={"host": self.host, "port": self.port},
                )
            else:
                return HealthCheckResult(
                    check_name=self.name,
                    check_type=HealthCheckType.TCP,
                    status=HealthLevel.UNHEALTHY,
                    response_time_ms=response_time,
                    details={"host": self.host, "port": self.port},
                    error=f"Connection refused (errno={result})",
                )
        except socket.timeout:
            return HealthCheckResult(
                check_name=self.name,
                check_type=HealthCheckType.TCP,
                status=HealthLevel.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                details={"host": self.host, "port": self.port},
                error=f"Connection timed out after {self.timeout}s",
            )
        except Exception as e:
            return HealthCheckResult(
                check_name=self.name,
                check_type=HealthCheckType.TCP,
                status=HealthLevel.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                details={"host": self.host, "port": self.port},
                error=str(e),
            )


class DependencyHealthCheck:
    """依赖健康检查（数据库、缓存、外部服务等）

    支持的依赖类型：
    - sqlite: SQLite 数据库连通性
    - redis: Redis 缓存连通性
    - http: HTTP 服务依赖
    - custom: 自定义检查函数
    """

    def __init__(
        self,
        name: str,
        dep_type: str,
        dep_config: Dict[str, Any],
        timeout: float = 5.0,
    ):
        self.name = name
        self.dep_type = dep_type.lower()
        self.dep_config = dep_config
        self.timeout = timeout

    def check(self) -> HealthCheckResult:
        """执行依赖检查"""
        start_time = time.time()
        try:
            if self.dep_type == "sqlite":
                return self._check_sqlite(start_time)
            elif self.dep_type == "redis":
                return self._check_redis(start_time)
            elif self.dep_type == "http":
                return self._check_http(start_time)
            else:
                return HealthCheckResult(
                    check_name=self.name,
                    check_type=HealthCheckType.DEPENDENCY,
                    status=HealthLevel.UNKNOWN,
                    response_time_ms=(time.time() - start_time) * 1000,
                    details={"dep_type": self.dep_type},
                    error=f"Unsupported dependency type: {self.dep_type}",
                )
        except Exception as e:
            return HealthCheckResult(
                check_name=self.name,
                check_type=HealthCheckType.DEPENDENCY,
                status=HealthLevel.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                details={"dep_type": self.dep_type},
                error=str(e),
            )

    def _check_sqlite(self, start_time: float) -> HealthCheckResult:
        """检查 SQLite 数据库"""
        import sqlite3

        db_path = self.dep_config.get("path", "")
        if not db_path:
            return HealthCheckResult(
                check_name=self.name,
                check_type=HealthCheckType.DEPENDENCY,
                status=HealthLevel.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                details={"dep_type": "sqlite"},
                error="Database path not configured",
            )

        try:
            conn = sqlite3.connect(db_path, timeout=self.timeout)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()

            # 检查 WAL 模式
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]

            cursor.close()
            conn.close()

            return HealthCheckResult(
                check_name=self.name,
                check_type=HealthCheckType.DEPENDENCY,
                status=HealthLevel.HEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                details={
                    "dep_type": "sqlite",
                    "path": db_path,
                    "journal_mode": journal_mode,
                },
            )
        except Exception as e:
            return HealthCheckResult(
                check_name=self.name,
                check_type=HealthCheckType.DEPENDENCY,
                status=HealthLevel.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                details={"dep_type": "sqlite", "path": db_path},
                error=str(e),
            )

    def _check_redis(self, start_time: float) -> HealthCheckResult:
        """检查 Redis 缓存"""
        try:
            import redis
        except ImportError:
            return HealthCheckResult(
                check_name=self.name,
                check_type=HealthCheckType.DEPENDENCY,
                status=HealthLevel.DEGRADED,
                response_time_ms=(time.time() - start_time) * 1000,
                details={"dep_type": "redis"},
                error="redis package not installed",
            )

        host = self.dep_config.get("host", "127.0.0.1")
        port = self.dep_config.get("port", 6379)
        db = self.dep_config.get("db", 0)

        try:
            r = redis.Redis(host=host, port=port, db=db, socket_timeout=self.timeout)
            result = r.ping()
            info = r.info("server")
            r.close()

            return HealthCheckResult(
                check_name=self.name,
                check_type=HealthCheckType.DEPENDENCY,
                status=HealthLevel.HEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                details={
                    "dep_type": "redis",
                    "host": host,
                    "port": port,
                    "redis_version": info.get("redis_version", "unknown"),
                },
            )
        except Exception as e:
            return HealthCheckResult(
                check_name=self.name,
                check_type=HealthCheckType.DEPENDENCY,
                status=HealthLevel.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                details={"dep_type": "redis", "host": host, "port": port},
                error=str(e),
            )

    def _check_http(self, start_time: float) -> HealthCheckResult:
        """检查 HTTP 服务依赖"""
        import urllib.request

        url = self.dep_config.get("url", "")
        if not url:
            return HealthCheckResult(
                check_name=self.name,
                check_type=HealthCheckType.DEPENDENCY,
                status=HealthLevel.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                details={"dep_type": "http"},
                error="URL not configured",
            )

        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                status_code = response.status

                if 200 <= status_code < 400:
                    return HealthCheckResult(
                        check_name=self.name,
                        check_type=HealthCheckType.DEPENDENCY,
                        status=HealthLevel.HEALTHY,
                        response_time_ms=(time.time() - start_time) * 1000,
                        details={
                            "dep_type": "http",
                            "url": url,
                            "status_code": status_code,
                        },
                    )
                else:
                    return HealthCheckResult(
                        check_name=self.name,
                        check_type=HealthCheckType.DEPENDENCY,
                        status=HealthLevel.DEGRADED,
                        response_time_ms=(time.time() - start_time) * 1000,
                        details={
                            "dep_type": "http",
                            "url": url,
                            "status_code": status_code,
                        },
                        error=f"HTTP {status_code}",
                    )
        except Exception as e:
            return HealthCheckResult(
                check_name=self.name,
                check_type=HealthCheckType.DEPENDENCY,
                status=HealthLevel.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                details={"dep_type": "http", "url": url},
                error=str(e),
            )


class ResourceHealthCheck:
    """资源健康检查（CPU、内存、磁盘）"""

    def __init__(
        self,
        name: str = "resource",
        cpu_threshold: float = 90.0,
        memory_threshold: float = 90.0,
        disk_threshold: float = 90.0,
        disk_path: str = ".",
        check_cpu: bool = True,
        check_memory: bool = True,
        check_disk: bool = True,
    ):
        self.name = name
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.disk_threshold = disk_threshold
        self.disk_path = disk_path
        self.check_cpu = check_cpu
        self.check_memory = check_memory
        self.check_disk = check_disk

    def check(self) -> HealthCheckResult:
        """执行资源检查"""
        start_time = time.time()
        details: Dict[str, Any] = {}
        errors: List[str] = []
        overall_status = HealthLevel.HEALTHY

        # CPU 检查
        if self.check_cpu:
            cpu_result = self._check_cpu()
            details["cpu"] = cpu_result["value"]
            if cpu_result["exceeded"]:
                errors.append(f"CPU usage {cpu_result['value']}% exceeds threshold {self.cpu_threshold}%")
                overall_status = HealthLevel.DEGRADED

        # 内存检查
        if self.check_memory:
            mem_result = self._check_memory()
            details["memory"] = mem_result["value"]
            details["memory_total_mb"] = mem_result["total_mb"]
            details["memory_used_mb"] = mem_result["used_mb"]
            if mem_result["exceeded"]:
                errors.append(f"Memory usage {mem_result['value']}% exceeds threshold {self.memory_threshold}%")
                overall_status = HealthLevel.DEGRADED

        # 磁盘检查
        if self.check_disk:
            disk_result = self._check_disk()
            details["disk"] = disk_result["value"]
            details["disk_total_gb"] = disk_result["total_gb"]
            details["disk_used_gb"] = disk_result["used_gb"]
            details["disk_path"] = disk_result["path"]
            if disk_result["exceeded"]:
                errors.append(f"Disk usage {disk_result['value']}% exceeds threshold {self.disk_threshold}%")
                overall_status = HealthLevel.DEGRADED

        return HealthCheckResult(
            check_name=self.name,
            check_type=HealthCheckType.RESOURCE,
            status=overall_status,
            response_time_ms=(time.time() - start_time) * 1000,
            details=details,
            error="; ".join(errors) if errors else None,
        )

    def _check_cpu(self) -> Dict[str, Any]:
        """检查 CPU 使用率"""
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.5)
            return {
                "value": round(cpu_percent, 2),
                "exceeded": cpu_percent >= self.cpu_threshold,
            }
        except ImportError:
            return {"value": 0, "exceeded": False, "note": "psutil not available"}
        except Exception:
            return {"value": 0, "exceeded": False, "note": "check failed"}

    def _check_memory(self) -> Dict[str, Any]:
        """检查内存使用率"""
        try:
            import psutil
            mem = psutil.virtual_memory()
            return {
                "value": round(mem.percent, 2),
                "total_mb": round(mem.total / (1024 * 1024), 2),
                "used_mb": round(mem.used / (1024 * 1024), 2),
                "exceeded": mem.percent >= self.memory_threshold,
            }
        except ImportError:
            return {"value": 0, "total_mb": 0, "used_mb": 0, "exceeded": False, "note": "psutil not available"}
        except Exception:
            return {"value": 0, "total_mb": 0, "used_mb": 0, "exceeded": False, "note": "check failed"}

    def _check_disk(self) -> Dict[str, Any]:
        """检查磁盘使用率"""
        try:
            import shutil
            import os
            path = os.path.abspath(self.disk_path)
            usage = shutil.disk_usage(path)
            percent = (usage.used / usage.total) * 100
            return {
                "value": round(percent, 2),
                "total_gb": round(usage.total / (1024 ** 3), 2),
                "used_gb": round(usage.used / (1024 ** 3), 2),
                "path": path,
                "exceeded": percent >= self.disk_threshold,
            }
        except Exception:
            return {"value": 0, "total_gb": 0, "used_gb": 0, "path": self.disk_path, "exceeded": False, "note": "check failed"}


# ============================================================
# HealthCheckerPro - 增强版健康检查器
# ============================================================

class HealthCheckerPro:
    """
    增强版健康检查器

    在基础健康检查基础上增加：
    - 多种检查类型（HTTP/TCP/依赖/资源）
    - 自动摘除与恢复机制
    - 健康检查历史与趋势
    - 后台定时检查
    - 事件回调（摘除/恢复时触发）
    """

    def __init__(
        self,
        module_name: str,
        version: str = "1.0.0",
        auto_remove_default: bool = True,
        auto_recover_default: bool = True,
    ):
        self.module_name = module_name
        self.version = version
        self.auto_remove_default = auto_remove_default
        self.auto_recover_default = auto_recover_default

        self._checks: Dict[str, CheckState] = {}
        self._lock = threading.RLock()
        self._start_time = time.time()

        # 事件回调
        self._on_remove_callbacks: List[Callable[[str, HealthCheckResult], None]] = []
        self._on_recover_callbacks: List[Callable[[str, HealthCheckResult], None]] = []

        # 后台监控线程
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()

    # ------------------------------------------------------------------
    #  注册检查项
    # ------------------------------------------------------------------

    def register_check(
        self,
        name: str,
        check_type: HealthCheckType,
        check_fn: Callable[[], HealthCheckResult],
        critical: bool = False,
        interval: float = 30.0,
        timeout: float = 5.0,
        failure_threshold: int = 3,
        recovery_threshold: int = 2,
        auto_remove: Optional[bool] = None,
        auto_recover: Optional[bool] = None,
    ) -> None:
        """注册一个健康检查项"""
        config = HealthCheckConfig(
            name=name,
            check_type=check_type,
            check_fn=check_fn,
            critical=critical,
            interval=interval,
            timeout=timeout,
            failure_threshold=failure_threshold,
            recovery_threshold=recovery_threshold,
            auto_remove=auto_remove if auto_remove is not None else self.auto_remove_default,
            auto_recover=auto_recover if auto_recover is not None else self.auto_recover_default,
        )

        with self._lock:
            self._checks[name] = CheckState(config=config)

        logger.info("Health check registered: %s (type=%s, critical=%s)", name, check_type.value, critical)

    def register_tcp_check(
        self,
        name: str,
        host: str,
        port: int,
        critical: bool = False,
        timeout: float = 3.0,
        interval: float = 30.0,
        **kwargs,
    ) -> None:
        """注册 TCP 端口检查"""
        tcp_check = TcpHealthCheck(name=name, host=host, port=port, timeout=timeout)
        self.register_check(
            name=name,
            check_type=HealthCheckType.TCP,
            check_fn=tcp_check.check,
            critical=critical,
            interval=interval,
            timeout=timeout,
            **kwargs,
        )

    def register_dependency_check(
        self,
        name: str,
        dep_type: str,
        dep_config: Dict[str, Any],
        critical: bool = True,
        timeout: float = 5.0,
        interval: float = 30.0,
        **kwargs,
    ) -> None:
        """注册依赖检查"""
        dep_check = DependencyHealthCheck(name=name, dep_type=dep_type, dep_config=dep_config, timeout=timeout)
        self.register_check(
            name=name,
            check_type=HealthCheckType.DEPENDENCY,
            check_fn=dep_check.check,
            critical=critical,
            interval=interval,
            timeout=timeout,
            **kwargs,
        )

    def register_resource_check(
        self,
        name: str = "resource",
        cpu_threshold: float = 90.0,
        memory_threshold: float = 90.0,
        disk_threshold: float = 90.0,
        disk_path: str = ".",
        critical: bool = False,
        interval: float = 60.0,
        **kwargs,
    ) -> None:
        """注册资源检查"""
        res_check = ResourceHealthCheck(
            name=name,
            cpu_threshold=cpu_threshold,
            memory_threshold=memory_threshold,
            disk_threshold=disk_threshold,
            disk_path=disk_path,
        )
        self.register_check(
            name=name,
            check_type=HealthCheckType.RESOURCE,
            check_fn=res_check.check,
            critical=critical,
            interval=interval,
            **kwargs,
        )

    def unregister_check(self, name: str) -> bool:
        """注销检查项"""
        with self._lock:
            if name in self._checks:
                del self._checks[name]
                logger.info("Health check unregistered: %s", name)
                return True
        return False

    # ------------------------------------------------------------------
    #  事件回调
    # ------------------------------------------------------------------

    def on_remove(self, callback: Callable[[str, HealthCheckResult], None]) -> None:
        """注册实例摘除回调"""
        self._on_remove_callbacks.append(callback)

    def on_recover(self, callback: Callable[[str, HealthCheckResult], None]) -> None:
        """注册实例恢复回调"""
        self._on_recover_callbacks.append(callback)

    def _fire_remove_event(self, name: str, result: HealthCheckResult) -> None:
        """触发摘除事件"""
        for cb in self._on_remove_callbacks:
            try:
                cb(name, result)
            except Exception as e:
                logger.error("Remove callback error: %s", e)

    def _fire_recover_event(self, name: str, result: HealthCheckResult) -> None:
        """触发恢复事件"""
        for cb in self._on_recover_callbacks:
            try:
                cb(name, result)
            except Exception as e:
                logger.error("Recover callback error: %s", e)

    # ------------------------------------------------------------------
    #  执行检查
    # ------------------------------------------------------------------

    def check_all(self) -> Dict[str, Any]:
        """执行所有检查并返回汇总结果"""
        results: Dict[str, HealthCheckResult] = {}
        removed_items: List[str] = []
        recovered_items: List[str] = []

        with self._lock:
            checks = list(self._checks.items())

        for name, state in checks:
            try:
                result = state.config.check_fn()
            except Exception as e:
                result = HealthCheckResult(
                    check_name=name,
                    check_type=state.config.check_type,
                    status=HealthLevel.UNHEALTHY,
                    error=f"Check exception: {str(e)}",
                )

            state.record_result(result)
            results[name] = result

            # 检查是否需要摘除
            if state.should_remove:
                state.is_removed = True
                state.removed_at = time.time()
                removed_items.append(name)
                logger.warning("Health check removed: %s (consecutive failures: %d)",
                               name, state.consecutive_failures)
                self._fire_remove_event(name, result)

            # 检查是否需要恢复
            elif state.should_recover:
                state.is_removed = False
                state.removed_at = None
                recovered_items.append(name)
                logger.info("Health check recovered: %s (consecutive successes: %d)",
                            name, state.consecutive_successes)
                self._fire_recover_event(name, result)

        # 汇总状态
        overall_status = self._aggregate_status(results)

        return {
            "module": self.module_name,
            "version": self.version,
            "overall_status": overall_status.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": round(time.time() - self._start_time, 2),
            "check_count": len(results),
            "healthy_count": sum(1 for r in results.values() if r.status == HealthLevel.HEALTHY),
            "degraded_count": sum(1 for r in results.values() if r.status == HealthLevel.DEGRADED),
            "unhealthy_count": sum(1 for r in results.values() if r.status == HealthLevel.UNHEALTHY),
            "removed_count": sum(1 for s in self._checks.values() if s.is_removed),
            "removed_items": removed_items,
            "recovered_items": recovered_items,
            "checks": {name: result.to_dict() for name, result in results.items()},
        }

    def check_single(self, name: str) -> Optional[HealthCheckResult]:
        """执行单个检查"""
        with self._lock:
            state = self._checks.get(name)

        if state is None:
            return None

        try:
            result = state.config.check_fn()
        except Exception as e:
            result = HealthCheckResult(
                check_name=name,
                check_type=state.config.check_type,
                status=HealthLevel.UNHEALTHY,
                error=f"Check exception: {str(e)}",
            )

        state.record_result(result)
        return result

    def _aggregate_status(self, results: Dict[str, HealthCheckResult]) -> HealthLevel:
        """汇总健康状态"""
        has_degraded = False

        for name, result in results.items():
            state = self._checks.get(name)
            if state is None:
                continue

            is_critical = state.config.critical
            is_removed = state.is_removed

            if is_removed and is_critical:
                return HealthLevel.UNHEALTHY

            if result.status == HealthLevel.UNHEALTHY:
                if is_critical and not is_removed:
                    return HealthLevel.UNHEALTHY
                else:
                    has_degraded = True
            elif result.status == HealthLevel.DEGRADED:
                has_degraded = True

        if has_degraded:
            return HealthLevel.DEGRADED

        return HealthLevel.HEALTHY

    # ------------------------------------------------------------------
    #  查询接口
    # ------------------------------------------------------------------

    def get_check_names(self) -> List[str]:
        """获取所有检查项名称"""
        with self._lock:
            return list(self._checks.keys())

    def get_check_state(self, name: str) -> Optional[Dict[str, Any]]:
        """获取检查项状态"""
        with self._lock:
            state = self._checks.get(name)

        if state is None:
            return None

        return {
            "name": name,
            "type": state.config.check_type.value,
            "critical": state.config.critical,
            "is_removed": state.is_removed,
            "removed_at": state.removed_at,
            "consecutive_failures": state.consecutive_failures,
            "consecutive_successes": state.consecutive_successes,
            "last_result": state.last_result.to_dict() if state.last_result else None,
            "history_count": len(state.history),
        }

    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """获取所有检查项状态"""
        result = {}
        with self._lock:
            for name in self._checks:
                state = self.get_check_state(name)
                if state:
                    result[name] = state
        return result

    def get_removed_checks(self) -> List[str]:
        """获取已摘除的检查项列表"""
        with self._lock:
            return [name for name, state in self._checks.items() if state.is_removed]

    def get_check_history(self, name: str, limit: int = 20) -> List[Dict[str, Any]]:
        """获取检查历史记录"""
        with self._lock:
            state = self._checks.get(name)

        if state is None:
            return []

        history = list(state.history)[-limit:]
        return [r.to_dict() for r in reversed(history)]

    # ------------------------------------------------------------------
    #  后台监控
    # ------------------------------------------------------------------

    def start_monitor(self, interval: float = 30.0) -> bool:
        """启动后台健康监控线程"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return True

        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            name=f"HealthMonitor-{self.module_name}",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info("Health monitor started for %s (interval=%.1fs)", self.module_name, interval)
        return True

    def stop_monitor(self) -> None:
        """停止后台健康监控"""
        self._monitor_stop.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None
        logger.info("Health monitor stopped for %s", self.module_name)

    def _monitor_loop(self, interval: float) -> None:
        """监控循环"""
        while not self._monitor_stop.is_set():
            try:
                self.check_all()
            except Exception as e:
                logger.error("Health monitor error: %s", e)

            self._monitor_stop.wait(interval)

    @property
    def is_monitoring(self) -> bool:
        """是否正在监控"""
        return self._monitor_thread is not None and self._monitor_thread.is_alive()

    # ------------------------------------------------------------------
    #  手动摘除/恢复
    # ------------------------------------------------------------------

    def manual_remove(self, name: str, reason: str = "manual") -> bool:
        """手动摘除检查项"""
        with self._lock:
            state = self._checks.get(name)
            if state is None:
                return False
            if state.is_removed:
                return False

            state.is_removed = True
            state.removed_at = time.time()

            result = HealthCheckResult(
                check_name=name,
                check_type=state.config.check_type,
                status=HealthLevel.UNHEALTHY,
                error=f"Manual removal: {reason}",
            )
            self._fire_remove_event(name, result)
            logger.warning("Manual remove: %s (reason=%s)", name, reason)
            return True

    def manual_recover(self, name: str, reason: str = "manual") -> bool:
        """手动恢复检查项"""
        with self._lock:
            state = self._checks.get(name)
            if state is None:
                return False
            if not state.is_removed:
                return False

            state.is_removed = False
            state.removed_at = None
            state.consecutive_failures = 0
            state.consecutive_successes = state.config.recovery_threshold

            result = HealthCheckResult(
                check_name=name,
                check_type=state.config.check_type,
                status=HealthLevel.HEALTHY,
                details={"recovered_by": reason},
            )
            self._fire_recover_event(name, result)
            logger.info("Manual recover: %s (reason=%s)", name, reason)
            return True

    # ------------------------------------------------------------------
    #  趋势分析
    # ------------------------------------------------------------------

    def get_trend_analysis(self, name: str) -> Dict[str, Any]:
        """获取检查趋势分析"""
        with self._lock:
            state = self._checks.get(name)

        if state is None or len(state.history) < 2:
            return {"available": False}

        history = list(state.history)
        recent = history[-min(10, len(history)):]
        response_times = [r.response_time_ms for r in recent if r.response_time_ms > 0]

        avg_response = sum(response_times) / len(response_times) if response_times else 0
        max_response = max(response_times) if response_times else 0
        min_response = min(response_times) if response_times else 0

        healthy_count = sum(1 for r in history if r.status == HealthLevel.HEALTHY)
        unhealthy_count = sum(1 for r in history if r.status == HealthLevel.UNHEALTHY)
        degraded_count = sum(1 for r in history if r.status == HealthLevel.DEGRADED)

        # 趋势判断
        if unhealthy_count > len(history) * 0.3:
            trend = "deteriorating"
        elif healthy_count > len(history) * 0.9:
            trend = "stable_healthy"
        elif degraded_count > len(history) * 0.2:
            trend = "fluctuating"
        else:
            trend = "stable"

        return {
            "available": True,
            "total_samples": len(history),
            "healthy_count": healthy_count,
            "unhealthy_count": unhealthy_count,
            "degraded_count": degraded_count,
            "avg_response_ms": round(avg_response, 2),
            "max_response_ms": round(max_response, 2),
            "min_response_ms": round(min_response, 2),
            "trend": trend,
            "health_rate": round(healthy_count / len(history) * 100, 2),
        }
