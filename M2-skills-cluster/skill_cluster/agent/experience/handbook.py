from __future__ import annotations

"""Skill Handbook - 技能手册（经验驱动编排）.

独创设计：参考 SkillOrchestra 论文思想，从经验沉淀库中提取
(agent_id, skill_id, action) -> SkillProfile 的映射视图。
编排器通过效用函数 U = P(success) - lambda_c * C(cost) 选择最优执行路径。
仅需 50 个以内的执行日志即可收敛，学习成本比 RL 低 700 倍。
"""

import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

from skill_cluster.agent.experience.bank import SkillExperienceBank

logger = structlog.get_logger()


class SkillProfile(BaseModel):
    """技能画像——某 Agent 在某 Skill 上的经验统计."""

    agent_id: str = Field(..., description="Agent ID")
    skill_id: str = Field(..., description="技能 ID")
    action: str = Field(..., description="动作标识")
    success_rate: float = Field(default=0.5, description="历史成功率")
    avg_latency_ms: float = Field(default=0.0, description="平均延迟")
    avg_cost: float = Field(default=1.0, description="平均成本（归一化）")
    best_params: dict[str, Any] | None = Field(
        default=None, description="历史最优参数"
    )
    failure_patterns: list[str] = Field(
        default_factory=list, description="已知失败模式"
    )
    total_calls: int = Field(default=0, description="总调用次数")
    last_used: float = Field(default=0.0, description="最后调用时间戳")


class SkillHandbook:
    """技能手册.

    从 SkillExperienceBank 构建经验视图，提供数据驱动的路由决策。
    """

    def __init__(
        self,
        experience_bank: SkillExperienceBank,
        lambda_cost: float = 0.3,
        min_calls_for_trust: int = 3,
    ) -> None:
        self._bank = experience_bank
        self._lambda_cost = lambda_cost
        self._min_calls = min_calls_for_trust

    def get_profile(
        self, agent_id: str, skill_id: str, action: str
    ) -> SkillProfile:
        """获取某 Agent 在某 Skill 上的经验画像.

        Args:
            agent_id: Agent ID.
            skill_id: 技能 ID.
            action: 动作标识.

        Returns:
            SkillProfile 画像.
        """
        # 从经验库过滤该三元组的所有记录
        records = [
            r
            for r in self._bank._records
            if r.agent_id == agent_id
            and r.skill_id == skill_id
            and r.action == action
        ]

        total = len(records)
        if total < self._min_calls:
            # 经验不足，返回中性预测
            return SkillProfile(
                agent_id=agent_id,
                skill_id=skill_id,
                action=action,
                success_rate=0.5,
                avg_latency_ms=0.0,
                avg_cost=1.0,
                total_calls=total,
            )

        successes = sum(1 for r in records if r.outcome == "success")
        avg_lat = sum(r.latency_ms for r in records) / total
        # 成本归一化：以 5000ms 为满分基准
        cost = min(1.0, avg_lat / 5000.0)
        best = self._bank.get_best_params(skill_id, action)

        # 收集失败模式
        failures = [
            r.error or r.outcome
            for r in records
            if r.outcome != "success" and r.error
        ]
        failure_patterns = list(dict.fromkeys(failures))[:5]

        last_ts = max(r.timestamp for r in records) if records else 0.0

        return SkillProfile(
            agent_id=agent_id,
            skill_id=skill_id,
            action=action,
            success_rate=successes / total,
            avg_latency_ms=round(avg_lat, 2),
            avg_cost=round(cost, 3),
            best_params=best,
            failure_patterns=failure_patterns,
            total_calls=total,
            last_used=last_ts,
        )

    def utility(
        self, agent_id: str, skill_id: str, action: str
    ) -> float:
        """计算效用值 U = P(success) - lambda_c * C(cost).

        Args:
            agent_id: Agent ID.
            skill_id: 技能 ID.
            action: 动作标识.

        Returns:
            效用值（越高越好）.
        """
        profile = self.get_profile(agent_id, skill_id, action)
        return profile.success_rate - self._lambda_cost * profile.avg_cost

    def recommend_best_agent(
        self,
        skill_id: str,
        action: str,
        candidates: list[str],
    ) -> str | None:
        """为指定技能选择最优 Agent.

        Args:
            skill_id: 技能 ID.
            action: 动作标识.
            candidates: Agent 候选列表.

        Returns:
            最优 Agent ID，若候选为空返回 None.
        """
        if not candidates:
            return None
        scored = [
            (agent_id, self.utility(agent_id, skill_id, action))
            for agent_id in candidates
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        best_agent, best_score = scored[0]
        logger.info(
            "handbook_recommend_agent",
            skill_id=skill_id,
            action=action,
            best_agent=best_agent,
            best_score=round(best_score, 3),
            candidates=len(candidates),
        )
        return best_agent

    def rank_skills_for_agent(
        self, agent_id: str, skills: list[tuple[str, str]]
    ) -> list[tuple[str, str, float]]:
        """为某 Agent 排序其最擅长的技能.

        Args:
            agent_id: Agent ID.
            skills: [(skill_id, action)] 列表.

        Returns:
            [(skill_id, action, utility)] 按效用降序排列.
        """
        ranked = [
            (sid, act, self.utility(agent_id, sid, act))
            for sid, act in skills
        ]
        ranked.sort(key=lambda x: x[2], reverse=True)
        return ranked

    def export_matrix(self) -> dict[str, Any]:
        """导出经验矩阵（用于可视化或调试）."""
        matrix: dict[str, dict[str, dict[str, Any]]] = {}
        for r in self._bank._records:
            key = f"{r.agent_id}:{r.skill_id}:{r.action}"
            if r.agent_id not in matrix:
                matrix[r.agent_id] = {}
            if r.skill_id not in matrix[r.agent_id]:
                matrix[r.agent_id][r.skill_id] = {}
            profile = self.get_profile(r.agent_id, r.skill_id, r.action)
            matrix[r.agent_id][r.skill_id][r.action] = profile.model_dump()
        return matrix
