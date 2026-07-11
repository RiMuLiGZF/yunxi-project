from __future__ import annotations

"""Edge-Cloud Orchestrator - 端云协同降级编排器.

独创设计：端侧部署 SLM（7B/14B）优先执行，失败或超时后自动降级到云端大模型。
结合 TokenBudget 动态控制端侧/云侧的任务分配，实现"端侧优先、云端兜底"的弹性策略。
"""

import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult
from skill_cluster.token_budget import TokenBudget

logger = structlog.get_logger()


class EdgeCloudConfig(BaseModel):
    """端云协同配置."""

    enable_cloud_fallback: bool = Field(default=True, description="启用云端降级")
    cloud_timeout_multiplier: float = Field(
        default=2.0, description="云端超时倍数（相对端侧）"
    )
    max_cloud_retries: int = Field(default=1, description="云端最大重试次数")
    budget_threshold_for_cloud: float = Field(
        default=0.8, description="预算使用率超过此阈值时优先云端"
    )


class EdgeCloudOrchestrator:
    """端云协同编排器.

    1. 端侧优先：简单/实时/隐私敏感任务优先本地 7B 执行
    2. 预算感知：Token 预算紧张时动态裁剪端侧工具列表
    3. 自动降级：端侧 timeout/not_found 时无缝切换到云端
    4. 成本标记：云端调用标记为高成本，供经验库学习
    """

    def __init__(
        self,
        edge_router: Any,
        cloud_router: Any,
        token_budget: TokenBudget,
        config: EdgeCloudConfig | None = None,
    ) -> None:
        self._edge = edge_router
        self._cloud = cloud_router
        self._budget = token_budget
        self._config = config or EdgeCloudConfig()
        self._cloud_call_count = 0
        self._edge_call_count = 0

    async def invoke(
        self,
        request: SkillInvokeRequest,
        agent_id: str,
        force_cloud: bool = False,
    ) -> SkillInvokeResult:
        """端云协同调用.

        Args:
            request: 调用请求.
            agent_id: Agent 标识.
            force_cloud: 强制使用云端（跳过端侧尝试）.

        Returns:
            调用结果.
        """
        # 阶段1: 预算检查与路由决策
        usage_ratio = self._budget.usage_ratio
        if usage_ratio > self._config.budget_threshold_for_cloud:
            # 预算紧张时直接走云端（云端通常有更大的token预算）
            logger.info(
                "budget_high_direct_cloud",
                usage_ratio=usage_ratio,
                skill_id=request.skill_id,
            )
            return await self._invoke_cloud(request, agent_id)

        if force_cloud or not self._config.enable_cloud_fallback:
            return await self._invoke_cloud(request, agent_id)

        # 阶段2: 端侧尝试
        edge_result = await self._invoke_edge(request, agent_id)
        if edge_result.status == "success":
            return edge_result

        # 阶段3: 判断是否降级到云端
        if edge_result.status in ("timeout", "not_found"):
            logger.info(
                "edge_fail_fallback_to_cloud",
                skill_id=request.skill_id,
                edge_status=edge_result.status,
            )
            return await self._invoke_cloud(request, agent_id)

        # 端侧业务失败（非 timeout），直接返回错误
        return edge_result

    async def _invoke_edge(
        self, request: SkillInvokeRequest, agent_id: str
    ) -> SkillInvokeResult:
        """端侧调用."""
        start = time.perf_counter()
        try:
            result = await self._edge.invoke(request, agent_id)
            self._edge_call_count += 1
            return result
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=request.skill_id,
                action=request.action,
                status="failure",
                error=f"Edge invoke error: {e}",
                latency_ms=latency,
                trace_id=request.trace_id,
            )

    async def _invoke_cloud(
        self, request: SkillInvokeRequest, agent_id: str
    ) -> SkillInvokeResult:
        """云端调用（带超时倍增）."""
        start = time.perf_counter()
        timeout = request.timeout
        if timeout is not None:
            timeout = int(timeout * self._config.cloud_timeout_multiplier)

        cloud_request = request.model_copy(
            update={"timeout": timeout} if timeout else {}
        )

        try:
            result = await self._cloud.invoke(cloud_request, agent_id)
            self._cloud_call_count += 1
            # 标记云端调用成本
            logger.info(
                "cloud_invoke",
                skill_id=request.skill_id,
                latency_ms=result.latency_ms,
            )
            return result
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=request.skill_id,
                action=request.action,
                status="failure",
                error=f"Cloud invoke error: {e}",
                latency_ms=latency,
                trace_id=request.trace_id,
            )

    def get_stats(self) -> dict[str, Any]:
        """获取端云调用统计."""
        total = self._edge_call_count + self._cloud_call_count
        return {
            "edge_calls": self._edge_call_count,
            "cloud_calls": self._cloud_call_count,
            "total_calls": total,
            "edge_ratio": (
                self._edge_call_count / total if total > 0 else 0.0
            ),
            "budget_usage_ratio": self._budget.usage_ratio,
        }

    def get_available_tools(
        self, all_tools: list[dict[str, Any]], budget_ratio: float | None = None
    ) -> list[dict[str, Any]]:
        """按预算动态裁剪工具列表.

        Args:
            all_tools: 全部可用工具列表.
            budget_ratio: 预算使用比例，None 时自动获取.

        Returns:
            裁剪后的工具列表.
        """
        ratio = budget_ratio if budget_ratio is not None else self._budget.usage_ratio()
        if ratio < 0.5:
            # 预算充裕：返回全部工具
            return all_tools
        elif ratio < 0.8:
            # 预算中等：只返回高频/轻量工具（前70%）
            cutoff = max(1, int(len(all_tools) * 0.7))
            return all_tools[:cutoff]
        else:
            # 预算紧张：只返回核心工具（前30%）
            cutoff = max(1, int(len(all_tools) * 0.3))
            return all_tools[:cutoff]
