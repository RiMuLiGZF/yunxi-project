"""技能演化引擎.

收集技能使用数据，评估技能效果，生成优化建议。
支持：使用数据收集、效果评估、优化建议、自动优化、版本管理。
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Optional


@dataclass
class SkillUsageRecord:
    """技能使用记录."""
    skill_id: str
    user_id: str
    success: bool
    duration: float
    input_type: str = "text"
    output_type: str = "text"
    error_message: str = ""
    timestamp: float = field(default_factory=time.time)
    input_tokens: int = 0
    output_tokens: int = 0
    rating: Optional[int] = None  # 用户评分 1-5


@dataclass
class SkillEvolutionMetrics:
    """技能演化指标."""
    skill_id: str
    use_count: int = 0
    success_count: int = 0
    total_duration: float = 0.0
    avg_duration: float = 0.0
    success_rate: float = 0.0
    improvement_score: float = 0.0
    total_rating: float = 0.0
    avg_rating: float = 0.0
    last_evaluated_at: float = 0.0


class SkillEvolutionEngine:
    """技能演化引擎.

    收集使用数据，评估效果，生成优化建议。
    """

    def __init__(self, max_history: int = 5000) -> None:
        self._usage_history: deque[SkillUsageRecord] = deque(maxlen=max_history)
        self._metrics: dict[str, SkillEvolutionMetrics] = {}
        self._versions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = Lock()
        self._max_history = max_history

    # ------------------------------------------------------------------
    # 使用数据收集
    # ------------------------------------------------------------------

    def record_usage(
        self,
        skill_id: str,
        user_id: str,
        success: bool,
        duration: float,
        input_type: str = "text",
        output_type: str = "text",
        error_message: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        rating: Optional[int] = None,
    ) -> None:
        """记录一次技能使用."""
        record = SkillUsageRecord(
            skill_id=skill_id,
            user_id=user_id,
            success=success,
            duration=duration,
            input_type=input_type,
            output_type=output_type,
            error_message=error_message,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            rating=rating,
        )

        with self._lock:
            self._usage_history.append(record)
            # 更新实时指标
            if skill_id not in self._metrics:
                self._metrics[skill_id] = SkillEvolutionMetrics(skill_id=skill_id)
            metrics = self._metrics[skill_id]
            metrics.use_count += 1
            if success:
                metrics.success_count += 1
            metrics.total_duration += duration
            metrics.avg_duration = metrics.total_duration / metrics.use_count
            metrics.success_rate = metrics.success_count / metrics.use_count
            if rating:
                metrics.total_rating += rating
                metrics.avg_rating = metrics.total_rating / metrics.use_count
            metrics.last_evaluated_at = time.time()

    def get_usage_stats(
        self,
        skill_id: str,
        period_hours: int = 24,
    ) -> dict[str, Any]:
        """获取技能使用统计."""
        now = time.time()
        cutoff = now - period_hours * 3600

        with self._lock:
            records = [
                r for r in self._usage_history
                if r.skill_id == skill_id and r.timestamp >= cutoff
            ]

        if not records:
            return {
                "skill_id": skill_id,
                "period_hours": period_hours,
                "use_count": 0,
                "success_rate": 0.0,
                "avg_duration": 0.0,
                "avg_rating": 0.0,
            }

        success_count = sum(1 for r in records if r.success)
        avg_duration = sum(r.duration for r in records) / len(records)
        rated = [r.rating for r in records if r.rating]
        avg_rating = sum(rated) / len(rated) if rated else 0.0

        return {
            "skill_id": skill_id,
            "period_hours": period_hours,
            "use_count": len(records),
            "success_count": success_count,
            "success_rate": success_count / len(records),
            "avg_duration": avg_duration,
            "avg_rating": avg_rating,
            "total_tokens": sum(r.input_tokens + r.output_tokens for r in records),
            "error_count": sum(1 for r in records if not r.success),
        }

    # ------------------------------------------------------------------
    # 效果评估
    # ------------------------------------------------------------------

    def evaluate_skill(self, skill_id: str) -> dict[str, Any]:
        """评估技能效果.

        Returns:
            包含各项评分的评估结果
        """
        with self._lock:
            metrics = self._metrics.get(skill_id)
            history = [r for r in self._usage_history if r.skill_id == skill_id]

        if not metrics or metrics.use_count == 0:
            return {
                "skill_id": skill_id,
                "overall_score": 0.0,
                "evaluated": False,
                "reason": "使用数据不足",
            }

        # 各项评分（满分 1.0）
        success_score = metrics.success_rate  # 成功率
        speed_score = min(1.0, 5.0 / max(metrics.avg_duration, 0.1))  # 速度（5秒为满分基准）
        rating_score = metrics.avg_rating / 5.0 if metrics.avg_rating else 0.5  # 评分

        # 综合评分
        overall_score = (
            success_score * 0.4 +
            speed_score * 0.3 +
            rating_score * 0.3
        )

        # 改进空间分数（越高说明改进空间越大）
        improvement_score = 1.0 - overall_score

        return {
            "skill_id": skill_id,
            "overall_score": round(overall_score, 3),
            "success_score": round(success_score, 3),
            "speed_score": round(speed_score, 3),
            "rating_score": round(rating_score, 3),
            "improvement_score": round(improvement_score, 3),
            "use_count": metrics.use_count,
            "avg_duration": round(metrics.avg_duration, 3),
            "success_rate": round(metrics.success_rate, 3),
            "evaluated": True,
            "last_evaluated_at": metrics.last_evaluated_at,
        }

    def calculate_improvement_score(self, skill_id: str) -> float:
        """计算改进分数（越高越需要改进）."""
        result = self.evaluate_skill(skill_id)
        return result.get("improvement_score", 0.0)

    def get_skill_rankings(
        self,
        category: Optional[str] = None,
        sort_by: str = "overall_score",
        top_n: int = 10,
    ) -> list[dict[str, Any]]:
        """技能排行榜."""
        with self._lock:
            skill_ids = list(self._metrics.keys())

        results = []
        for skill_id in skill_ids:
            evaluation = self.evaluate_skill(skill_id)
            results.append(evaluation)

        results.sort(key=lambda x: x.get(sort_by, 0), reverse=True)
        return results[:top_n]

    # ------------------------------------------------------------------
    # 优化建议
    # ------------------------------------------------------------------

    def generate_optimization_suggestions(
        self,
        skill_id: str,
    ) -> list[dict[str, Any]]:
        """生成优化建议."""
        evaluation = self.evaluate_skill(skill_id)
        suggestions = []

        if not evaluation.get("evaluated"):
            return [
                {
                    "type": "info",
                    "priority": "low",
                    "title": "数据不足",
                    "description": "使用数据不足，暂时无法生成优化建议",
                }
            ]

        # 成功率低
        if evaluation["success_score"] < 0.7:
            suggestions.append({
                "type": "success_rate",
                "priority": "high",
                "title": "提升成功率",
                "description": f"当前成功率 {evaluation['success_rate']:.0%}，建议优化提示词或增加错误处理",
                "action": "review_prompt",
            })

        # 速度慢
        if evaluation["speed_score"] < 0.5:
            suggestions.append({
                "type": "performance",
                "priority": "medium",
                "title": "优化响应速度",
                "description": f"平均响应时间 {evaluation['avg_duration']:.1f}秒，建议优化处理逻辑",
                "action": "optimize_performance",
            })

        # 用户评分低
        if 0 < evaluation["rating_score"] < 0.6:
            suggestions.append({
                "type": "user_rating",
                "priority": "high",
                "title": "改进用户体验",
                "description": "用户评分偏低，建议收集反馈并改进输出质量",
                "action": "improve_ux",
            })

        # 使用量低
        if evaluation["use_count"] < 10:
            suggestions.append({
                "type": "discovery",
                "priority": "low",
                "title": "提升发现度",
                "description": "使用量较少，建议优化技能描述和关键词，提升可发现性",
                "action": "improve_discoverability",
            })

        # 默认建议
        if not suggestions:
            suggestions.append({
                "type": "info",
                "priority": "low",
                "title": "表现良好",
                "description": "该技能各项指标表现良好，继续保持",
                "action": "none",
            })

        return suggestions

    def auto_optimize_prompt(
        self,
        skill_id: str,
        current_prompt: str,
    ) -> dict[str, Any]:
        """自动优化提示词（简化版）.

        基于使用数据生成提示词优化建议。
        """
        evaluation = self.evaluate_skill(skill_id)
        suggestions = self.generate_optimization_suggestions(skill_id)

        # 简单的提示词优化规则
        optimizations = []

        if len(current_prompt) < 50:
            optimizations.append({
                "aspect": "prompt_length",
                "suggestion": "增加提示词详细程度，明确输入输出格式",
                "impact": "medium",
            })

        if "输出" not in current_prompt and "output" not in current_prompt.lower():
            optimizations.append({
                "aspect": "output_format",
                "suggestion": "明确指定输出格式，减少不确定性",
                "impact": "high",
            })

        if "错误" not in current_prompt and "error" not in current_prompt.lower():
            optimizations.append({
                "aspect": "error_handling",
                "suggestion": "添加错误处理说明，提高健壮性",
                "impact": "low",
            })

        return {
            "skill_id": skill_id,
            "current_prompt_length": len(current_prompt),
            "evaluation": evaluation,
            "optimizations": optimizations,
            "suggestions": suggestions,
            "overall_quality": evaluation.get("overall_score", 0),
        }

    # ------------------------------------------------------------------
    # 版本管理
    # ------------------------------------------------------------------

    def create_version(
        self,
        skill_id: str,
        version_data: dict[str, Any],
        description: str = "",
    ) -> dict[str, Any]:
        """创建技能版本."""
        version = {
            "version_id": f"v{uuid.uuid4().hex[:8]}",
            "skill_id": skill_id,
            "data": version_data,
            "description": description,
            "created_at": time.time(),
        }

        with self._lock:
            self._versions[skill_id].append(version)

        return version

    def list_versions(self, skill_id: str) -> list[dict[str, Any]]:
        """获取技能版本列表."""
        with self._lock:
            versions = list(self._versions.get(skill_id, []))

        versions.sort(key=lambda v: v["created_at"], reverse=True)
        return versions

    def rollback_version(
        self,
        skill_id: str,
        version_id: str,
    ) -> Optional[dict[str, Any]]:
        """回滚到指定版本."""
        with self._lock:
            versions = self._versions.get(skill_id, [])
            for v in versions:
                if v["version_id"] == version_id:
                    # 创建一个新版本（内容等于被回滚的版本）
                    rollback_version = {
                        "version_id": f"v{uuid.uuid4().hex[:8]}",
                        "skill_id": skill_id,
                        "data": v["data"],
                        "description": f"回滚到 {version_id}",
                        "created_at": time.time(),
                        "rollback_from": version_id,
                    }
                    versions.append(rollback_version)
                    return rollback_version

        return None

    # ------------------------------------------------------------------
    # 统计总览
    # ------------------------------------------------------------------

    def get_overall_stats(self) -> dict[str, Any]:
        """获取整体演化统计."""
        with self._lock:
            total_skills = len(self._metrics)
            total_uses = sum(m.use_count for m in self._metrics.values())
            avg_success = (
                sum(m.success_rate for m in self._metrics.values()) / total_skills
                if total_skills > 0 else 0.0
            )
            history_size = len(self._usage_history)

        return {
            "total_skills_tracked": total_skills,
            "total_usage_records": total_uses,
            "average_success_rate": round(avg_success, 3),
            "history_size": history_size,
            "max_history": self._max_history,
        }
