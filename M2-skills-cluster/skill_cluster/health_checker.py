"""Health Checker - 技能集群健康检查器（门面模块）.

本模块为 start_server.py 提供统一的 HealthChecker 入口类，
底层复用 skill_health.py 中的 SkillClusterHealthChecker 和 RegistryHealthChecker。
"""

from __future__ import annotations

from typing import Any

from skill_cluster.skill_health import (
    SkillClusterHealthChecker,
    RegistryHealthChecker,
    HealthStatus,
    ClusterHealthReport,
)


class HealthChecker:
    """技能集群健康检查器（门面类）.

    对 start_server.py 和 api_v2 提供简洁的 HealthChecker 接口，
    内部聚合 SkillClusterHealthChecker 并自动注册注册中心检查器。

    用法：
        health_checker = HealthChecker(registry=registry)
        report = health_checker.check()
    """

    def __init__(self, registry: Any = None) -> None:
        """初始化健康检查器.

        Args:
            registry: SkillRegistry 实例，可选。
        """
        self._registry = registry
        self._checker = SkillClusterHealthChecker()

        # 自动注册注册中心健康检查器
        if registry is not None:
            self._checker.register_checker("registry", RegistryHealthChecker(registry))

    def check(self) -> ClusterHealthReport:
        """执行全量健康检查.

        Returns:
            ClusterHealthReport 集群健康总报告
        """
        return self._checker.check()

    def register_checker(self, name: str, checker: Any) -> None:
        """注册自定义检查器.

        Args:
            name: 检查器名称
            checker: 具有 check() 方法的检查器实例
        """
        self._checker.register_checker(name, checker)

    def set_manual_score(
        self, component_name: str, score: float, issues: list[str] | None = None
    ) -> None:
        """手动设置组件分数.

        Args:
            component_name: 组件名称
            score: 健康分数（0-1）
            issues: 问题列表
        """
        self._checker.set_manual_score(component_name, score, issues)

    @property
    def status(self) -> str:
        """快速获取当前总体健康状态字符串."""
        return self.check().overall_status.value

    @property
    def score(self) -> float:
        """快速获取当前总体健康评分."""
        return self.check().overall_score


__all__ = [
    "HealthChecker",
    "HealthStatus",
    "ClusterHealthReport",
]
