"""
云汐内核 V6 - 健康监控中心

灵感来源：Kubernetes Probes / Spring Boot Actuator

提供多维度的健康检查能力：
- Liveness：进程是否存活
- Readiness：服务是否可接受流量
- Component Health：各子组件健康状态
- Dependency Check：外部依赖可用性

输出格式兼容 Kubernetes / Prometheus 生态。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)


HealthChecker = Callable[[], Awaitable[bool]]
"""健康检查函数签名"""


@dataclass
class HealthStatus:
    """健康状态"""

    status: str = "unknown"  # up | down | degraded
    timestamp: float = field(default_factory=time.time)
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
            "error": self.error,
        }


class HealthMonitor:
    """健康监控中心

    注册各组件的健康检查函数，提供聚合健康视图。
    """

    def __init__(self) -> None:
        self._checks: dict[str, HealthChecker] = {}
        self._cache: dict[str, HealthStatus] = {}
        self._cache_ttl: float = 5.0
        self._last_check: float = 0.0
        self._logger = logger.bind(service="health_monitor")

    def register(self, name: str, checker: HealthChecker) -> None:
        """注册健康检查"""
        self._checks[name] = checker
        self._logger.info("health_check_registered", name=name)

    def unregister(self, name: str) -> None:
        """注销健康检查"""
        self._checks.pop(name, None)

    # ── 检查接口 ────────────────────────────────────────

    async def check(self, name: str) -> HealthStatus:
        """检查单个组件"""
        checker = self._checks.get(name)
        if checker is None:
            return HealthStatus(status="unknown", error=f"No checker registered for '{name}'")

        start = time.time()
        try:
            passed = await checker()
            latency_ms = (time.time() - start) * 1000
            return HealthStatus(
                status="up" if passed else "down",
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.time() - start) * 1000
            return HealthStatus(
                status="down",
                latency_ms=latency_ms,
                error=str(exc),
            )

    async def check_all(self, use_cache: bool = True) -> dict[str, HealthStatus]:
        """检查所有组件

        Args:
            use_cache: 是否在缓存有效期内直接返回缓存结果
        """
        now = time.time()
        if use_cache and now - self._last_check < self._cache_ttl and self._cache:
            return dict(self._cache)

        results = {}
        for name in self._checks:
            results[name] = await self.check(name)

        self._cache = results
        self._last_check = now
        return results

    async def liveness(self) -> HealthStatus:
        """存活检查：进程是否还在运行"""
        return HealthStatus(status="up", details={"pid": __import__("os").getpid()})

    async def readiness(self) -> dict[str, HealthStatus]:
        """就绪检查：所有关键组件是否健康"""
        results = await self.check_all(use_cache=True)
        return results

    # ── 聚合状态 ────────────────────────────────────────

    async def overall_status(self) -> dict[str, Any]:
        """获取整体健康状态"""
        live = await self.liveness()
        ready = await self.readiness()

        all_up = all(r.status == "up" for r in ready.values())
        any_down = any(r.status == "down" for r in ready.values())

        if live.status != "up":
            overall = "down"
        elif any_down:
            overall = "degraded"
        elif all_up:
            overall = "up"
        else:
            overall = "unknown"

        return {
            "status": overall,
            "timestamp": time.time(),
            "liveness": live.to_dict(),
            "readiness": {name: status.to_dict() for name, status in ready.items()},
        }

    # ── 格式化输出 ────────────────────────────────────────

    async def to_prometheus(self) -> str:
        """输出 Prometheus 格式的指标"""
        results = await self.check_all(use_cache=True)
        lines = ["# HELP yunxi_health Health status of components", "# TYPE yunxi_health gauge"]
        for name, status in results.items():
            value = 1 if status.status == "up" else 0
            lines.append(f'yunxi_health{{component="{name}"}} {value}')
        return "\n".join(lines) + "\n"
