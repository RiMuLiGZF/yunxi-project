"""
云汐内核 V3 - 反馈收集与自优化系统

灵感来源：Human-in-the-loop RL + Agent 反馈驱动优化

支持：
- 显式反馈：用户点赞/点踩、评分、文字反馈
- 隐式反馈：会话时长、重试次数、沉默率
- 反馈驱动的规则自动优化建议
- Agent 行为画像
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Feedback:
    """用户反馈记录"""

    feedback_id: str = ""
    trace_id: str = ""
    agent_id: str = ""
    intent: str = ""
    feedback_type: str = "explicit"  # explicit | implicit
    rating: int = 0  # -1, 0, 1 或 1-5 星
    comment: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class FeedbackCollector:
    """反馈收集器"""

    MAX_FEEDBACKS: int = 5000

    def __init__(self) -> None:
        self._feedbacks: list[Feedback] = []
        self._agent_feedbacks: dict[str, list[Feedback]] = {}
        self._logger = logger.bind(service="feedback_collector")

    def collect_explicit(
        self,
        trace_id: str,
        agent_id: str,
        intent: str,
        rating: int,
        comment: str = "",
    ) -> Feedback:
        """收集显式反馈"""
        fb = Feedback(
            feedback_id=f"fb_{int(time.time() * 1000)}",
            trace_id=trace_id,
            agent_id=agent_id,
            intent=intent,
            feedback_type="explicit",
            rating=rating,
            comment=comment,
        )
        self._add(fb)
        return fb

    def collect_implicit(
        self,
        trace_id: str,
        agent_id: str,
        intent: str,
        session_duration_sec: float = 0.0,
        retry_count: int = 0,
        was_silent: bool = False,
    ) -> Feedback:
        """收集隐式反馈

        将会话行为转化为评分：
        - 会话时长短 + 重试多 = 负面反馈
        - 会话时长适中 = 正面反馈
        """
        rating = 0
        if retry_count >= 2:
            rating -= 1
        if was_silent:
            rating -= 1
        if session_duration_sec > 30:
            rating += 1

        fb = Feedback(
            feedback_id=f"fb_implicit_{int(time.time() * 1000)}",
            trace_id=trace_id,
            agent_id=agent_id,
            intent=intent,
            feedback_type="implicit",
            rating=max(-1, min(1, rating)),
            metadata={
                "session_duration_sec": session_duration_sec,
                "retry_count": retry_count,
                "was_silent": was_silent,
            },
        )
        self._add(fb)
        return fb

    def _add(self, fb: Feedback) -> None:
        self._feedbacks.append(fb)
        self._agent_feedbacks.setdefault(fb.agent_id, []).append(fb)
        # 容量限制
        if len(self._feedbacks) > self.MAX_FEEDBACKS:
            self._feedbacks = self._feedbacks[-self.MAX_FEEDBACKS:]
            for aid in self._agent_feedbacks:
                if len(self._agent_feedbacks[aid]) > 500:
                    self._agent_feedbacks[aid] = self._agent_feedbacks[aid][-500:]

    def get_agent_feedback_summary(self, agent_id: str) -> dict[str, Any]:
        """获取 Agent 的反馈摘要"""
        fbs = self._agent_feedbacks.get(agent_id, [])
        if not fbs:
            return {"total": 0, "avg_rating": 0, "positive_rate": 0}

        explicit = [f for f in fbs if f.feedback_type == "explicit"]
        ratings = [f.rating for f in fbs]
        positive = [r for r in ratings if r > 0]

        return {
            "total": len(fbs),
            "explicit_count": len(explicit),
            "implicit_count": len(fbs) - len(explicit),
            "avg_rating": round(sum(ratings) / len(ratings), 2),
            "positive_rate": round(len(positive) / len(ratings), 2),
        }


class SelfOptimizer:
    """自优化引擎

    基于反馈数据生成优化建议，驱动 Agent 行为改进。
    """

    def __init__(self, feedback_collector: FeedbackCollector) -> None:
        self._feedback = feedback_collector
        self._logger = logger.bind(service="self_optimizer")

    def analyze_agent(self, agent_id: str) -> dict[str, Any]:
        """分析 Agent 表现并生成优化建议"""
        summary = self._feedback.get_agent_feedback_summary(agent_id)
        if summary["total"] < 3:
            return {
                "agent_id": agent_id,
                "status": "insufficient_data",
                "message": "反馈数据不足，无法生成优化建议",
            }

        issues: list[str] = []
        suggestions: list[str] = []

        if summary["avg_rating"] < 0:
            issues.append("整体用户满意度偏低")
            suggestions.append("审查 Agent 的输出质量，增加结果校验")

        if summary["positive_rate"] < 0.5:
            issues.append("正面反馈占比不足 50%")
            suggestions.append("考虑增加 fallback 机制或人工介入阈值")

        return {
            "agent_id": agent_id,
            "status": "analyzed",
            "metrics": summary,
            "issues": issues,
            "suggestions": suggestions,
            "priority": "high" if summary["avg_rating"] < 0 else "medium",
        }

    def generate_rule_updates(self, intent_classifier: Any) -> list[dict[str, Any]]:
        """基于反馈生成意图分类规则更新建议

        例如：某个意图经常被错误路由，建议调整规则权重。
        """
        # 按 intent 聚合反馈
        intent_ratings: dict[str, list[int]] = {}
        for fb in self._feedback._feedbacks:
            intent_ratings.setdefault(fb.intent, []).append(fb.rating)

        updates: list[dict[str, Any]] = []
        for intent, ratings in intent_ratings.items():
            avg = sum(ratings) / len(ratings)
            if avg < -0.3 and len(ratings) >= 3:
                updates.append({
                    "type": "add_fallback_rule",
                    "intent": intent,
                    "reason": f"平均评分 {avg:.2f}，建议增加确认机制",
                })
            elif avg > 0.5 and len(ratings) >= 5:
                updates.append({
                    "type": "lower_confirm_threshold",
                    "intent": intent,
                    "reason": f"平均评分 {avg:.2f}，可降低确认阈值提升体验",
                })

        return updates
