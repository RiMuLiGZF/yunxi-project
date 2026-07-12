from __future__ import annotations

"""Skill Cluster Health - 全局健康检查聚合.

【第二轮优化 - P2-2 解决】
聚合技能集群各子模块的健康状态，提供统一运维可观测性接口。

检查维度：
- 注册中心健康（技能数量、分类覆盖）
- 路由健康（Bandit/Adaptive指标）
- 缓存健康（命中率、内存占用）
- 熔断器健康（开路数、半开路数）
- 沙箱健康（最近执行成功率）
- 事件总线健康（积压事件数）
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class HealthStatus(Enum):
    """健康状态枚举."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """单个组件健康报告."""
    component_name: str
    status: HealthStatus
    score: float = 1.0  # 0-1，1=完全健康
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: str = ""
    issues: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = datetime.now().isoformat()


@dataclass
class ClusterHealthReport:
    """集群健康总报告."""
    overall_status: HealthStatus
    overall_score: float
    components: list[ComponentHealth] = field(default_factory=list)
    checked_at: str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = datetime.now().isoformat()

    def to_summary(self) -> dict[str, Any]:
        """输出摘要字典."""
        return {
            "overall_status": self.overall_status.value,
            "overall_score": round(self.overall_score, 3),
            "checked_at": self.checked_at,
            "components": [
                {
                    "name": c.component_name,
                    "status": c.status.value,
                    "score": round(c.score, 3),
                    "issues": c.issues,
                }
                for c in self.components
            ],
        }


class SkillClusterHealthChecker:
    """技能集群健康检查器.

    聚合多个子模块的健康状态，输出统一报告。
    通过 register_checker 注册自定义检查器扩展。
    """

    def __init__(self) -> None:
        self._checkers: dict[str, Any] = {}
        self._manual_scores: dict[str, tuple[float, list[str]]] = {}

    def register_checker(self, name: str, checker: Any) -> None:
        """注册检查器（checker 必须有 check() 方法返回 ComponentHealth）."""
        self._checkers[name] = checker

    def set_manual_score(
        self, component_name: str, score: float, issues: list[str] | None = None
    ) -> None:
        """手动设置组件分数（用于无法自动检查的组件）."""
        self._manual_scores[component_name] = (score, issues or [])

    def check(self) -> ClusterHealthReport:
        """执行全量健康检查."""
        components: list[ComponentHealth] = []

        # 自动检查器
        for name, checker in self._checkers.items():
            try:
                health = checker.check()
                components.append(health)
            except Exception as e:
                logger.warning(
                    "health_check_error",
                    component=name,
                    error=str(e),
                )
                components.append(ComponentHealth(
                    component_name=name,
                    status=HealthStatus.UNKNOWN,
                    score=0.0,
                    issues=[f"Check failed: {e}"],
                ))

        # 手动分数
        for name, (score, issues) in self._manual_scores.items():
            status = (
                HealthStatus.HEALTHY
                if score >= 0.8
                else HealthStatus.DEGRADED
                if score >= 0.5
                else HealthStatus.UNHEALTHY
            )
            components.append(ComponentHealth(
                component_name=name,
                status=status,
                score=score,
                issues=issues,
            ))

        # 计算总分
        if components:
            overall_score = sum(c.score for c in components) / len(components)
        else:
            overall_score = 0.0

        overall_status = (
            HealthStatus.HEALTHY
            if overall_score >= 0.8
            else HealthStatus.DEGRADED
            if overall_score >= 0.5
            else HealthStatus.UNHEALTHY
        )

        return ClusterHealthReport(
            overall_status=overall_status,
            overall_score=round(overall_score, 3),
            components=components,
        )


class RegistryHealthChecker:
    """注册中心健康检查器."""

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def check(self) -> ComponentHealth:
        skills = self._registry.list_skills()
        count = len(skills)
        issues: list[str] = []

        if count == 0:
            return ComponentHealth(
                component_name="registry",
                status=HealthStatus.DEGRADED,
                score=0.3,
                details={"skill_count": 0},
                issues=["No skills registered"],
            )

        # 检查是否有无action的技能
        no_action = 0
        for s in skills:
            manifest = self._registry.get_manifest(s)
            if manifest and not manifest.actions:
                no_action += 1

        if no_action > 0:
            issues.append(f"{no_action} skills have no actions")

        score = max(0.5, 1.0 - no_action * 0.1)
        status = (
            HealthStatus.HEALTHY if score >= 0.8 else HealthStatus.DEGRADED
        )
        return ComponentHealth(
            component_name="registry",
            status=status,
            score=round(score, 3),
            details={"skill_count": count, "no_action_count": no_action},
            issues=issues,
        )


class CacheHealthChecker:
    """缓存健康检查器."""

    def __init__(self, cache: Any) -> None:
        self._cache = cache

    def check(self) -> ComponentHealth:
        try:
            stats = self._cache.get_stats()
            hit_rate = stats.get("hit_rate", 0.0)
            entry_count = stats.get("total_entries", 0)
            issues: list[str] = []

            if entry_count == 0:
                issues.append("Cache is empty")

            score = max(0.3, hit_rate) if entry_count > 0 else 0.8
            status = (
                HealthStatus.HEALTHY if score >= 0.8 else HealthStatus.DEGRADED
            )
            return ComponentHealth(
                component_name="cache",
                status=status,
                score=round(score, 3),
                details=stats,
                issues=issues,
            )
        except Exception as e:
            return ComponentHealth(
                component_name="cache",
                status=HealthStatus.UNKNOWN,
                score=0.0,
                issues=[str(e)],
            )


class CircuitBreakerHealthChecker:
    """熔断器健康检查器."""

    def __init__(self, breaker: Any) -> None:
        self._breaker = breaker

    def check(self) -> ComponentHealth:
        try:
            stats = self._breaker.get_stats()
            state = stats.get("state", "closed")
            issues: list[str] = []

            if state == "open":
                issues.append("Circuit breaker is OPEN")
                score = 0.2
                status = HealthStatus.UNHEALTHY
            elif state == "half_open":
                issues.append("Circuit breaker is HALF_OPEN")
                score = 0.6
                status = HealthStatus.DEGRADED
            else:
                score = 1.0
                status = HealthStatus.HEALTHY

            return ComponentHealth(
                component_name="circuit_breaker",
                status=status,
                score=score,
                details=stats,
                issues=issues,
            )
        except Exception as e:
            return ComponentHealth(
                component_name="circuit_breaker",
                status=HealthStatus.UNKNOWN,
                score=0.0,
                issues=[str(e)],
            )
