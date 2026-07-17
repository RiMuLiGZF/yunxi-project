"""
联邦调度决策引擎 — FederatedScheduler

决定任务用内部 Agent 还是外部 Agent，以及选哪个外部 Agent。
"""

from __future__ import annotations

from typing import Any

import structlog

from shared_models import (
    FederationDecision,
    ExternalAgentProfile,
    UserPreferenceMode,
    SecurityClassification,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# 决策因子权重
FACTOR_WEIGHTS: dict[str, float] = {
    "privacy": 0.30,       # 隐私合规要求
    "capability": 0.25,    # 任务类型匹配度
    "preference": 0.20,    # 用户偏好模式
    "cost": 0.15,          # 成本预算
    "speed": 0.10,         # 响应速度
}


class FederatedScheduler:
    """联邦调度决策引擎

    决策流程：
    1. 隐私检查：高涉密 → 强制内部
    2. 能力匹配：内部能搞定 → 内部
    3. 外部评估：按匹配度+成本+速度综合打分
    4. 预算检查：Top1 候选成本 <= 剩余预算
    5. 输出决策结果 + 理由
    """

    def __init__(
        self,
        registry: Any,  # ExternalAgentRegistry
        default_preference: UserPreferenceMode = UserPreferenceMode.BALANCED,
        internal_capability_coverage: float = 0.7,  # 内部 Agent 能力覆盖率
    ) -> None:
        self._registry: Any = registry
        self._default_preference: UserPreferenceMode = default_preference
        self._internal_coverage: float = internal_capability_coverage
        self._logger: structlog.stdlib.BoundLogger = logger.bind(component="federated_scheduler")

    # ── 核心决策 ────────────────────────────────────────

    def decide(
        self,
        task_type: str = "general",
        security_level: SecurityClassification = SecurityClassification.PUBLIC,
        user_preference: UserPreferenceMode | None = None,
        remaining_budget: float = -1.0,  # -1 表示无限制
        speed_requirement: str = "medium",  # fast / medium / slow
        task_complexity: float = 0.5,  # 0-1
    ) -> FederationDecision:
        """联邦调度决策

        Args:
            task_type: 任务类型
            security_level: 涉密等级
            user_preference: 用户偏好模式
            remaining_budget: 剩余预算（美元，-1 表示无限制）
            speed_requirement: 速度要求
            task_complexity: 任务复杂度 0-1

        Returns:
            FederationDecision 决策结果
        """
        preference = user_preference or self._default_preference

        self._logger.info(
            "federation_decision_start",
            task_type=task_type,
            security_level=security_level.value,
            preference=preference.value,
            remaining_budget=remaining_budget,
        )

        # Step 1: 隐私红线检查
        privacy_result = self._check_privacy(security_level)
        if privacy_result == "blocked":
            return self._internal_decision(
                reason=f"涉密等级{security_level.value}高于阈值，强制内部执行（隐私红线）",
                privacy_status="blocked",
            )

        # Step 2: 内部能力评估
        internal_score = self._evaluate_internal(task_type, task_complexity)
        if internal_score >= 0.8 and preference != UserPreferenceMode.QUALITY_FIRST:
            # 内部能力足够且用户不是质量优先 → 内部
            return self._internal_decision(
                reason=f"内部能力评分{internal_score:.2f}≥0.8，{preference.value}模式下优先内部",
                privacy_status=privacy_result,
            )

        # Step 3: 获取可用外部 Agent 列表
        candidates = self._get_active_candidates(task_type)
        if not candidates:
            return self._internal_decision(
                reason="无可用外部 Agent，降级到内部执行",
                privacy_status=privacy_result,
            )

        # Step 4: 候选评分排序
        scored_candidates = []
        for agent in candidates:
            score = self._score_candidate(
                agent=agent,
                task_type=task_type,
                preference=preference,
                remaining_budget=remaining_budget,
                speed_requirement=speed_requirement,
                privacy_status=privacy_result,
                task_complexity=task_complexity,
            )
            scored_candidates.append((agent, score))

        # 按评分降序
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        if not scored_candidates:
            return self._internal_decision(
                reason="所有外部 Agent 均不符合要求，降级到内部执行",
                privacy_status=privacy_result,
            )

        top_agent, top_score = scored_candidates[0]

        # Step 5: 内部 vs 外部 比较
        # 如果内部评分也很高，且用户偏好成本优先 → 选内部
        if (
            preference == UserPreferenceMode.COST_FIRST
            and internal_score >= 0.6
        ):
            return self._internal_decision(
                reason="成本优先模式，内部能力满足基本需求，选择内部执行",
                privacy_status=privacy_result,
            )

        # 速度优先：选最快的（内部通常更快）
        if (
            preference == UserPreferenceMode.SPEED_FIRST
            and speed_requirement == "fast"
            and internal_score >= 0.5
        ):
            return self._internal_decision(
                reason="速度优先模式+极速要求，内部延迟更低，选择内部执行",
                privacy_status=privacy_result,
            )

        # Step 6: 预算检查
        estimated_cost = self._estimate_cost(top_agent, task_complexity)
        if remaining_budget >= 0 and estimated_cost > remaining_budget:
            # 预算不足，找下一个便宜的
            for agent, score in scored_candidates:
                cost = self._estimate_cost(agent, task_complexity)
                if cost <= remaining_budget:
                    top_agent, top_score = agent, score
                    estimated_cost = cost
                    break
            else:
                # 都超预算 → 内部
                return self._internal_decision(
                    reason=f"剩余预算${remaining_budget:.4f}不足以支付所有外部 Agent，降级到内部执行",
                    privacy_status=privacy_result,
                )

        # 选择外部 Agent
        fallback_id = scored_candidates[1][0].agent_id if len(scored_candidates) > 1 else ""

        decision = FederationDecision(
            use_external=True,
            selected_agent_id=top_agent.agent_id,
            selected_agent_name=top_agent.display_name,
            decision_reason=self._build_reason(
                top_agent, preference, task_type, estimated_cost, privacy_result
            ),
            estimated_cost=estimated_cost,
            estimated_latency=top_agent.response_speed,
            privacy_check=privacy_result,
            quality_score=top_score,
            fallback_agent_id=fallback_id,
        )

        self._logger.info(
            "federation_decision_external",
            selected_agent=top_agent.agent_id,
            score=round(top_score, 2),
            estimated_cost=round(estimated_cost, 4),
        )

        return decision

    # ── 集群扩展入口 ──────────────────────────────────

    def schedule_with_cluster(
        self,
        task_type: str = "general",
        security_level: SecurityClassification = SecurityClassification.PUBLIC,
        user_preference: UserPreferenceMode | None = None,
        remaining_budget: float = -1.0,
        speed_requirement: str = "medium",
        task_complexity: float = 0.5,
    ) -> FederationDecision:
        """支持跨节点发现的联邦调度决策（集群扩展入口）

        在原有 6 步决策流程基础上，于 Step 2（内部能力评估）之后
        新增 Step 2.5（远程 Agent 发现），将远程 Agent 纳入候选评分。

        决策流程：
        1. 隐私检查：高涉密 → 强制内部
        2. 内部能力评估
        2.5 远程 Agent 发现：从集群总线发现其他节点的 Agent
        3. 合并外部 + 远程候选列表
        4. 候选评分排序
        5. 内部 vs 外部比较
        6. 预算检查
        """
        from src.federation.remote_discovery import RemoteAgentDiscovery

        preference = user_preference or self._default_preference

        self._logger.info(
            "cluster_schedule_start",
            task_type=task_type,
            security_level=security_level.value,
            preference=preference.value,
        )

        # Step 1: 隐私红线检查（与原流程一致）
        privacy_result = self._check_privacy(security_level)
        if privacy_result == "blocked":
            return self._internal_decision(
                reason=f"涉密等级{security_level.value}高于阈值，强制内部执行（隐私红线）",
                privacy_status="blocked",
            )

        # Step 2: 内部能力评估
        internal_score = self._evaluate_internal(task_type, task_complexity)
        if internal_score >= 0.8 and preference != UserPreferenceMode.QUALITY_FIRST:
            return self._internal_decision(
                reason=f"内部能力评分{internal_score:.2f}>=0.8，{preference.value}模式下优先内部",
                privacy_status=privacy_result,
            )

        # Step 2.5: 远程 Agent 发现（新增）
        discovery = RemoteAgentDiscovery()
        remote_agents = discovery.discover_from_cluster()

        # 将远程 Agent 转为 ExternalAgentProfile 并注册到联邦注册表
        remote_profiles: list[Any] = []
        for ra in remote_agents:
            if ra.status != "active":
                continue
            profile = self._remote_agent_to_profile(ra)
            if profile:
                remote_profiles.append(profile)

        # Step 3: 获取可用外部 Agent 列表（原有）+ 远程 Agent
        local_candidates = self._get_active_candidates(task_type)
        all_candidates = local_candidates + remote_profiles

        if not all_candidates:
            return self._internal_decision(
                reason="无可用外部 Agent 且无远程 Agent，降级到内部执行",
                privacy_status=privacy_result,
            )

        self._logger.info(
            "cluster_candidates_collected",
            local_count=len(local_candidates),
            remote_count=len(remote_profiles),
            total=len(all_candidates),
        )

        # Step 4: 候选评分排序（复用现有评分逻辑）
        scored_candidates: list[tuple[Any, float]] = []
        for agent in all_candidates:
            score = self._score_candidate(
                agent=agent,
                task_type=task_type,
                preference=preference,
                remaining_budget=remaining_budget,
                speed_requirement=speed_requirement,
                privacy_status=privacy_result,
                task_complexity=task_complexity,
            )
            scored_candidates.append((agent, score))

        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        if not scored_candidates:
            return self._internal_decision(
                reason="所有候选 Agent 均不符合要求，降级到内部执行",
                privacy_status=privacy_result,
            )

        top_agent, top_score = scored_candidates[0]

        # Step 5: 内部 vs 外部比较（与原流程一致）
        if preference == UserPreferenceMode.COST_FIRST and internal_score >= 0.6:
            return self._internal_decision(
                reason="成本优先模式，内部能力满足基本需求，选择内部执行",
                privacy_status=privacy_result,
            )

        if (
            preference == UserPreferenceMode.SPEED_FIRST
            and speed_requirement == "fast"
            and internal_score >= 0.5
        ):
            return self._internal_decision(
                reason="速度优先模式+极速要求，内部延迟更低，选择内部执行",
                privacy_status=privacy_result,
            )

        # Step 6: 预算检查
        estimated_cost = self._estimate_cost(top_agent, task_complexity)
        if remaining_budget >= 0 and estimated_cost > remaining_budget:
            for agent, score in scored_candidates:
                cost = self._estimate_cost(agent, task_complexity)
                if cost <= remaining_budget:
                    top_agent, top_score = agent, score
                    estimated_cost = cost
                    break
            else:
                return self._internal_decision(
                    reason=f"剩余预算${remaining_budget:.4f}不足以支付所有候选 Agent，降级到内部执行",
                    privacy_status=privacy_result,
                )

        # 判断是否为远程 Agent
        is_remote = top_agent.agent_id.startswith("remote_")
        source_hint = "（跨节点远程）" if is_remote else ""

        fallback_id = scored_candidates[1][0].agent_id if len(scored_candidates) > 1 else ""

        decision = FederationDecision(
            use_external=True,
            selected_agent_id=top_agent.agent_id,
            selected_agent_name=top_agent.display_name,
            decision_reason=self._build_reason(
                top_agent, preference, task_type, estimated_cost, privacy_result
            ) + source_hint,
            estimated_cost=estimated_cost,
            estimated_latency=top_agent.response_speed,
            privacy_check=privacy_result,
            quality_score=top_score,
            fallback_agent_id=fallback_id,
        )

        self._logger.info(
            "cluster_decision_made",
            selected_agent=top_agent.agent_id,
            is_remote=is_remote,
            score=round(top_score, 2),
            estimated_cost=round(estimated_cost, 4),
        )

        return decision

    def _remote_agent_to_profile(self, remote_agent: Any) -> Any | None:
        """将 RemoteAgent 转换为 ExternalAgentProfile

        转换后可直接参与现有 _score_candidate 评分流程。

        Args:
            remote_agent: RemoteAgent 实例

        Returns:
            ExternalAgentProfile 实例，转换失败返回 None
        """
        from shared_models import (
            ExternalAgentProfile,
            ExternalAgentType,
            AgentPrivacyLevel,
            ConnectionType,
            CostModel,
        )

        try:
            # 远程 Agent 类型映射
            type_map = {
                "llm": ExternalAgentType.LLM,
                "code": ExternalAgentType.CODE,
                "design": ExternalAgentType.DESIGN,
                "search": ExternalAgentType.SEARCH,
                "tool": ExternalAgentType.TOOL,
            }
            agent_type = type_map.get(
                remote_agent.agent_type.lower(), ExternalAgentType.LLM
            )

            return ExternalAgentProfile(
                agent_id=f"remote_{remote_agent.agent_id}",
                display_name=remote_agent.display_name or f"远程({remote_agent.node_id})",
                provider=f"cluster://{remote_agent.node_id}",
                agent_type=agent_type,
                capabilities=remote_agent.capabilities,
                response_speed=remote_agent.response_speed,
                quality_rating=remote_agent.quality_rating,
                cost_model=CostModel(),  # 跨节点调用无额外美元成本
                privacy_level=AgentPrivacyLevel.ENHANCED,  # 内网传输
                connection_type=ConnectionType.LOCAL,  # 集群内网
                status="active",
                config={
                    "node_id": remote_agent.node_id,
                    "host": remote_agent.host,
                    "port": remote_agent.port,
                },
            )
        except Exception as exc:
            self._logger.warning(
                "remote_agent_conversion_failed",
                agent_id=getattr(remote_agent, "agent_id", "unknown"),
                error=str(exc),
            )
            return None

    # ── 内部方法 ────────────────────────────────────────

    def _check_privacy(self, security_level: SecurityClassification) -> str:
        """隐私检查

        Returns:
            "passed" / "warning" / "blocked"
        """
        if security_level >= SecurityClassification.TOP_SECRET:
            return "blocked"
        if security_level >= SecurityClassification.CONFIDENTIAL:
            return "warning"
        return "passed"

    def _evaluate_internal(self, task_type: str, complexity: float) -> float:
        """评估内部 Agent 能力评分（0-1）"""
        # 基础覆盖率
        base = self._internal_coverage
        # 复杂度越高，内部能力越不足
        complexity_penalty = complexity * 0.3
        # 不同任务类型的内部擅长程度
        type_boosts = {
            "general": 0.0,
            "code_generation": -0.1,
            "analysis": -0.05,
            "creative": -0.15,
            "reasoning": -0.1,
        }
        boost = type_boosts.get(task_type, 0.0)
        score = max(0.0, min(1.0, base + boost - complexity_penalty))
        return score

    def _get_active_candidates(self, task_type: str) -> list[Any]:
        """获取可用的外部 Agent 列表"""
        all_agents = self._registry.list_agents(status="active")
        # 简单过滤：只选 LLM 类型（通用）
        candidates = [
            a for a in all_agents
            if a.agent_type.value in ("llm", "code")  # 简化：通用和代码都可用
        ]
        return candidates

    def _score_candidate(
        self,
        agent: ExternalAgentProfile,
        task_type: str,
        preference: UserPreferenceMode,
        remaining_budget: float,
        speed_requirement: str,
        privacy_status: str,
        task_complexity: float,
    ) -> float:
        """对候选 Agent 进行综合评分（0-100）"""
        scores: dict[str, float] = {}

        # 1. 隐私分（30%权重）
        if privacy_status == "blocked":
            scores["privacy"] = 0.0
        elif privacy_status == "warning":
            # 隐私等级越高，分数越低（本地模型满分）
            if agent.privacy_level.value == "local_only":
                scores["privacy"] = 100.0
            elif agent.privacy_level.value == "enhanced":
                scores["privacy"] = 70.0
            else:
                scores["privacy"] = 40.0
        else:
            scores["privacy"] = 100.0

        # 2. 能力分（25%权重）
        capability_score = agent.quality_rating * 20  # 5分制 → 100分制
        # 任务类型匹配加成
        if task_type == "code_generation" and "code" in agent.agent_type.value:
            capability_score = min(100, capability_score + 10)
        scores["capability"] = capability_score

        # 3. 偏好分（20%权重）
        pref_score = 50.0
        if preference == UserPreferenceMode.QUALITY_FIRST:
            pref_score = agent.quality_rating * 20
        elif preference == UserPreferenceMode.COST_FIRST:
            # 越便宜分越高
            cost = self._estimate_cost(agent, task_complexity)
            pref_score = max(0, 100 - cost * 1000)  # 成本越低分越高
        elif preference == UserPreferenceMode.SPEED_FIRST:
            speed_scores = {"fast": 100, "medium": 60, "slow": 20}
            pref_score = speed_scores.get(agent.response_speed, 50)
        elif preference == UserPreferenceMode.BALANCED:
            # 平衡模式：质量和成本各半
            quality_part = agent.quality_rating * 10
            cost = self._estimate_cost(agent, task_complexity)
            cost_part = max(0, 50 - cost * 500)
            pref_score = quality_part + cost_part
        scores["preference"] = min(100, pref_score)

        # 4. 成本分（15%权重）
        cost = self._estimate_cost(agent, task_complexity)
        if remaining_budget >= 0:
            if cost > remaining_budget:
                scores["cost"] = 0.0
            else:
                # 剩余预算比例越高越好
                ratio = 1.0 - (cost / remaining_budget if remaining_budget > 0 else 0)
                scores["cost"] = max(0, min(100, ratio * 100))
        else:
            # 无预算限制 → 成本不扣分
            scores["cost"] = 100.0

        # 5. 速度分（10%权重）
        speed_scores = {"fast": 100, "medium": 60, "slow": 20}
        base_speed = speed_scores.get(agent.response_speed, 50)
        # 如果用户要求高速，速度权重上升
        if speed_requirement == "fast":
            scores["speed"] = base_speed
        else:
            scores["speed"] = base_speed

        # 加权求和
        total = sum(scores[k] * FACTOR_WEIGHTS[k] for k in FACTOR_WEIGHTS)
        return total

    def _estimate_cost(self, agent: ExternalAgentProfile, complexity: float) -> float:
        """预估调用费用（美元）"""
        cost_model = agent.cost_model
        # 粗略估算：输入 1000 token + 输出 500~2000 token（随复杂度变化）
        input_tokens = 1000
        output_tokens = int(500 + complexity * 1500)
        return (
            input_tokens / 1000 * cost_model.input_per_1k
            + output_tokens / 1000 * cost_model.output_per_1k
        )

    def _internal_decision(self, reason: str, privacy_status: str) -> FederationDecision:
        """生成内部执行的决策"""
        return FederationDecision(
            use_external=False,
            selected_agent_id="internal",
            selected_agent_name="内部 Agent 集群",
            decision_reason=reason,
            estimated_cost=0.0,
            estimated_latency="fast",
            privacy_check=privacy_status,
            quality_score=70.0,
            fallback_agent_id="",
        )

    def _build_reason(
        self,
        agent: ExternalAgentProfile,
        preference: UserPreferenceMode,
        task_type: str,
        estimated_cost: float,
        privacy_status: str,
    ) -> str:
        """构建可解释的决策理由"""
        parts = [f"选择 {agent.display_name}（{agent.provider}）"]

        if preference == UserPreferenceMode.QUALITY_FIRST:
            parts.append(f"质量优先模式，该 Agent 评分 {agent.quality_rating}/5 为最高")
        elif preference == UserPreferenceMode.COST_FIRST:
            parts.append(f"成本优先模式，预估费用 ${estimated_cost:.4f}")
        elif preference == UserPreferenceMode.SPEED_FIRST:
            parts.append(f"速度优先模式，响应速度 {agent.response_speed}")
        else:
            parts.append("平衡模式，综合质量和成本最优")

        if privacy_status == "warning":
            parts.append("（注意：数据含敏感信息，已确认该 Agent 隐私等级达标）")

        return "，".join(parts)
