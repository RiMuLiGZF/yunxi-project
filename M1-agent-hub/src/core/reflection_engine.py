"""
云汐内核 V3 - 反思与评估引擎

灵感来源：Reflexion 框架 + Multi-Agent Reflexion (MAR)
https://arxiv.org/pdf/2512.20845v2

核心循环：Act → Evaluate → Reflect → Refine
- Act: Agent 执行任务
- Evaluate: 评估执行结果的质量
- Reflect: 生成改进建议（反思）
- Refine: 基于反思优化下次执行

支持单 Agent 自反思和多 Agent 互评。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from src.tools.interfaces import AgentResult

logger = structlog.get_logger(__name__)


@dataclass
class EvaluationResult:
    """评估结果"""

    passed: bool = True
    score: float = 0.0  # 0-1 质量分数
    criteria: dict[str, float] = field(default_factory=dict)
    feedback: str = ""
    suggestions: list[str] = field(default_factory=list)


@dataclass
class Reflection:
    """反思记录"""

    reflection_id: str = ""
    trace_id: str = ""
    agent_id: str = ""
    task_id: str = ""
    evaluation: EvaluationResult | None = None
    reflection_text: str = ""
    action_items: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class Evaluator:
    """执行结果评估器

    基于启发式规则评估 Agent 执行结果的质量。
    生产环境可接入 LLM 进行更精细的评估。
    """

    CRITERIA: list[str] = [
        "completeness",   # 完整性
        "correctness",    # 正确性
        "relevance",      # 相关性
        "safety",         # 安全性
    ]

    def evaluate(self, agent_result: AgentResult, expected_intent: str = "") -> EvaluationResult:
        """评估 Agent 执行结果

        Args:
            agent_result: Agent 返回的结果
            expected_intent: 期望的意图标签

        Returns:
            EvaluationResult: 评估结果
        """
        criteria: dict[str, float] = {}

        # 状态评估
        if agent_result.status == "success":
            criteria["completeness"] = 1.0
            criteria["correctness"] = 1.0
        elif agent_result.status == "partial":
            criteria["completeness"] = 0.5
            criteria["correctness"] = 0.7
        elif agent_result.status == "timeout":
            criteria["completeness"] = 0.3
            criteria["correctness"] = 0.5
        else:  # failure
            criteria["completeness"] = 0.0
            criteria["correctness"] = 0.0

        # 输出内容评估
        output = agent_result.output or {}
        has_reply = bool(output.get("reply") or output.get("answer") or output.get("report"))
        criteria["relevance"] = 0.8 if has_reply else 0.3

        # 延迟评估
        if agent_result.latency_ms < 500:
            criteria["latency"] = 1.0
        elif agent_result.latency_ms < 2000:
            criteria["latency"] = 0.7
        else:
            criteria["latency"] = 0.4

        # 安全性（基础检查）
        criteria["safety"] = 1.0
        reply_text = str(output.get("reply", ""))
        unsafe_keywords = ["密码", "身份证号", "银行卡"]
        for kw in unsafe_keywords:
            if kw in reply_text:
                criteria["safety"] = 0.5
                break

        # 总分
        total_score = sum(criteria.values()) / len(criteria)
        passed = total_score >= 0.6 and agent_result.status != "failure"

        # 生成反馈
        feedback_parts: list[str] = []
        suggestions: list[str] = []
        if not passed:
            feedback_parts.append(f"执行失败: {agent_result.error or '未知错误'}")
            suggestions.append("检查 Agent 实现逻辑或增加容错处理")
        if criteria.get("latency", 1.0) < 0.5:
            feedback_parts.append("响应延迟过高")
            suggestions.append("优化 Agent 执行效率或增加超时配置")
        if criteria.get("relevance", 1.0) < 0.5:
            feedback_parts.append("输出内容不完整")
            suggestions.append("确保 Agent 返回包含 reply/answer 字段")

        return EvaluationResult(
            passed=passed,
            score=round(total_score, 3),
            criteria=criteria,
            feedback="; ".join(feedback_parts) if feedback_parts else "执行质量良好",
            suggestions=suggestions,
        )


class Reflector:
    """反思生成器

    基于评估结果生成反思总结和改进建议。
    """

    def reflect(
        self,
        trace_id: str,
        agent_id: str,
        task_id: str,
        evaluation: EvaluationResult,
    ) -> Reflection:
        """生成反思"""
        reflection_text = self._generate_reflection_text(evaluation)
        action_items = self._generate_action_items(evaluation)

        reflection = Reflection(
            reflection_id=f"ref_{int(time.time() * 1000)}",
            trace_id=trace_id,
            agent_id=agent_id,
            task_id=task_id,
            evaluation=evaluation,
            reflection_text=reflection_text,
            action_items=action_items,
        )

        logger.info(
            "reflection_generated",
            reflection_id=reflection.reflection_id,
            agent_id=agent_id,
            score=evaluation.score,
            passed=evaluation.passed,
        )

        return reflection

    def _generate_reflection_text(self, evaluation: EvaluationResult) -> str:
        """生成反思文本"""
        parts: list[str] = []
        if evaluation.passed:
            parts.append(f"任务执行成功，综合评分 {evaluation.score:.2f}。")
        else:
            parts.append(f"任务执行未通过，综合评分 {evaluation.score:.2f}。")

        # 按维度分析
        low_score_dims = [
            k for k, v in evaluation.criteria.items() if v < 0.6
        ]
        if low_score_dims:
            parts.append(f"待改进维度: {', '.join(low_score_dims)}。")

        if evaluation.feedback:
            parts.append(f"反馈: {evaluation.feedback}")

        return " ".join(parts)

    def _generate_action_items(self, evaluation: EvaluationResult) -> list[str]:
        """生成行动项"""
        items = list(evaluation.suggestions)
        if evaluation.score < 0.8:
            items.append("增加更多测试用例覆盖边界场景")
        if not evaluation.passed:
            items.append("优先修复导致失败的根因")
        return items


class ReflectionEngine:
    """反思引擎

    整合评估器和反思器，提供完整的反思闭环。
    同时维护反思历史，支持基于历史反思改进决策。
    """

    MAX_REFLECTIONS: int = 1000

    def __init__(self) -> None:
        self.evaluator = Evaluator()
        self.reflector = Reflector()
        self._reflections: list[Reflection] = []
        self._agent_reflections: dict[str, list[Reflection]] = {}
        self._logger = logger.bind(service="reflection_engine")

    async def evaluate_and_reflect(
        self,
        trace_id: str,
        agent_id: str,
        task_id: str,
        agent_result: AgentResult,
        expected_intent: str = "",
    ) -> Reflection:
        """评估并生成反思

        完整闭环：评估 → 反思 → 存储
        """
        # 1. 评估
        evaluation = self.evaluator.evaluate(agent_result, expected_intent)

        # 2. 生成反思
        reflection = self.reflector.reflect(
            trace_id=trace_id,
            agent_id=agent_id,
            task_id=task_id,
            evaluation=evaluation,
        )

        # 3. 存储
        self._reflections.append(reflection)
        self._agent_reflections.setdefault(agent_id, []).append(reflection)

        # 容量限制：防止内存泄漏
        if len(self._reflections) > self.MAX_REFLECTIONS:
            self._reflections = self._reflections[-self.MAX_REFLECTIONS:]
            for aid in self._agent_reflections:
                if len(self._agent_reflections[aid]) > 100:
                    self._agent_reflections[aid] = self._agent_reflections[aid][-100:]

        return reflection

    def get_agent_reflections(
        self, agent_id: str, limit: int = 10
    ) -> list[Reflection]:
        """获取指定 Agent 的近期反思"""
        return self._agent_reflections.get(agent_id, [])[-limit:]

    def get_reflection_stats(self, agent_id: str) -> dict[str, Any]:
        """获取 Agent 的反思统计"""
        refs = self._agent_reflections.get(agent_id, [])
        if not refs:
            return {"total": 0, "avg_score": 0, "pass_rate": 0}

        scores = [r.evaluation.score for r in refs if r.evaluation]
        passed = [r for r in refs if r.evaluation and r.evaluation.passed]

        return {
            "total": len(refs),
            "avg_score": round(sum(scores) / len(scores), 3) if scores else 0,
            "pass_rate": round(len(passed) / len(refs), 3),
            "recent_trend": "improving" if len(refs) >= 3 and scores[-1] > scores[-3] else "stable",
        }

    def get_improvement_suggestions(self, agent_id: str) -> list[str]:
        """基于历史反思生成改进建议"""
        refs = self._agent_reflections.get(agent_id, [])
        if not refs:
            return []

        # 聚合最常见的行动项
        all_actions: list[str] = []
        for r in refs[-20:]:
            all_actions.extend(r.action_items)

        # 简单频率统计
        from collections import Counter
        counter = Counter(all_actions)
        return [action for action, _ in counter.most_common(3)]


class MultiAgentPeerReview:
    """多 Agent 互评

    多个 Agent 对同一结果进行交叉评估，提高评估的客观性。
    """

    def __init__(self, reflection_engine: ReflectionEngine) -> None:
        self._engine = reflection_engine

    async def peer_review(
        self,
        trace_id: str,
        target_agent_id: str,
        task_id: str,
        agent_result: AgentResult,
        reviewer_agent_ids: list[str],
    ) -> dict[str, Any]:
        """多 Agent 互评

        每个评审者根据其角色赋予不同的评估权重：
        - 保守评审者：更严格的评分标准
        - 标准评审者：默认评估器
        - 宽容评审者：更宽容的评分标准
        """
        individual_scores: list[float] = []
        individual_reviews: list[dict[str, Any]] = []

        # 为不同评审者定义不同的评估权重配置
        reviewer_profiles = {
            "strict": {"latency_weight": 0.3, "output_weight": 0.8},
            "standard": {"latency_weight": 0.5, "output_weight": 0.5},
            "lenient": {"latency_weight": 0.2, "output_weight": 0.3},
        }
        profile_keys = list(reviewer_profiles.keys())

        for i, reviewer_id in enumerate(reviewer_agent_ids):
            evaluation = self._engine.evaluator.evaluate(agent_result)
            # 每个评审者根据 profile 调整分数
            profile_key = profile_keys[i % len(profile_keys)]
            profile = reviewer_profiles[profile_key]
            adjusted_score = evaluation.score * profile["output_weight"] + (1.0 - evaluation.score) * (1.0 - profile["output_weight"])
            evaluation.score = round(adjusted_score, 3)
            evaluation.passed = evaluation.score >= 0.6

            individual_scores.append(evaluation.score)
            individual_reviews.append({
                "reviewer": reviewer_id,
                "profile": profile_key,
                "score": evaluation.score,
                "passed": evaluation.passed,
                "feedback": evaluation.feedback,
            })

        # 共识计算
        avg_score = sum(individual_scores) / len(individual_scores) if individual_scores else 0
        score_variance = (
            sum((s - avg_score) ** 2 for s in individual_scores) / len(individual_scores)
            if individual_scores else 0
        )
        consensus_reached = score_variance < 0.1 and avg_score >= 0.6

        return {
            "consensus_score": round(avg_score, 3),
            "individual_reviews": individual_reviews,
            "consensus_reached": consensus_reached,
            "score_variance": round(score_variance, 3),
        }
