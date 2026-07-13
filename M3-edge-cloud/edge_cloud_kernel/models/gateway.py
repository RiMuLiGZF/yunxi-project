"""网关层模型.

定义网关层的统计快照模型，包括健康检查和限流统计。
整合自原 gateway/health_checker.py 和 gateway/rate_limiter.py。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from edge_cloud_kernel.models.base import EdgeCloudBaseModel


# ---------------------------------------------------------------------------
# 健康检查模型
# ---------------------------------------------------------------------------


class HealthCheckerStats(EdgeCloudBaseModel):
    """健康探测统计快照.

    Attributes:
        current_status: 当前聚合健康状态.
        last_check_time: 最近一次探测完成的时间戳.
        consecutive_failures: 当前连续失败次数.
        total_checks: 累计探测总次数.
        healthy_checks: 健康探测次数.
        uptime_ratio: 健康比率 (healthy_checks / total_checks).
        endpoint_count: 已注册端点数量.
    """

    current_status: str
    last_check_time: float | None = None
    consecutive_failures: int = 0
    total_checks: int = 0
    healthy_checks: int = 0
    uptime_ratio: float = 0.0
    endpoint_count: int = 0


# ---------------------------------------------------------------------------
# 限流器模型
# ---------------------------------------------------------------------------


class RateLimiterStats(EdgeCloudBaseModel):
    """限流器统计快照.

    用于 Prometheus 指标暴露和运维监控面板。

    Attributes:
        global_tokens: 全局桶当前可用令牌数.
        global_max_tokens: 全局桶最大容量.
        global_refill_rate: 全局桶每秒补充速率.
        global_rejection_count: 全局桶累计拒绝次数.
        agent_count: 已注册的 agent 桶数量.
        agent_buckets: 各 agent 桶的详细状态.
    """

    global_tokens: float = Field(description="全局桶当前可用令牌数")
    global_max_tokens: float = Field(description="全局桶最大容量")
    global_refill_rate: float = Field(description="全局桶每秒补充速率")
    global_rejection_count: int = Field(description="全局桶累计拒绝次数")
    agent_count: int = Field(description="已注册的 agent 桶数量")
    agent_buckets: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="各 agent 桶详细状态"
    )
