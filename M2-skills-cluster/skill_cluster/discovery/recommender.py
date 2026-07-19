from __future__ import annotations

"""Skill Recommender - 基于用户目标的技能智能推荐.

独创设计：将用户意图（goal）与技能库进行多维度匹配，
融合 BM25F 关键词评分、经验成功率、记忆上下文偏好、
技能图谱依赖满足度，生成推荐排序。

【第六轮优化】新增语义匹配维度：
- 使用向量嵌入 + 余弦相似度进行语义匹配
- 作为第六维加入评分体系，权重 0.3
- embedding 不可用时自动降级，不影响原有功能
- 复用 shared.semantic 工具包

打通记忆层数据联动：
- 从 AgentMemory 中提取用户历史偏好
- 从 SkillExperienceBank 中提取成功率画像
- 从 SkillGraph 中验证依赖满足度
"""

import math
import re
from typing import Any

import structlog
from pydantic import BaseModel, Field

from skill_cluster.agent.memory import AgentMemory
from skill_cluster.interfaces import SkillManifest

logger = structlog.get_logger()

# 尝试导入语义路由器（可选依赖）
try:
    from skill_cluster.semantic import SemanticSkillRouter

    _SEMANTIC_ROUTER_AVAILABLE = True
except ImportError:
    _SEMANTIC_ROUTER_AVAILABLE = False
    logger.debug("semantic.router_not_available")


class SkillRecommendation(BaseModel):
    """技能推荐结果."""

    skill_id: str = Field(..., description="技能 ID")
    score: float = Field(..., description="推荐评分 (0-1)")
    reasons: list[str] = Field(
        default_factory=list, description="推荐理由"
    )
    match_dimensions: dict[str, float] = Field(
        default_factory=dict, description="各维度匹配分"
    )


class SkillRecommender:
    """技能智能推荐器.

    综合多信号为用户目标推荐最匹配的技能。
    """

    def __init__(
        self,
        memory: AgentMemory | None = None,
        experience: Any | None = None,
        enable_semantic: bool = True,
    ) -> None:
        self._memory = memory
        self._experience = experience
        self._skill_profiles: dict[str, SkillManifest] = {}
        self._weights = {
            "keyword": 0.25,
            "capability": 0.2,
            "experience": 0.15,
            "memory_preference": 0.1,
            "tag_match": 0.05,
            "semantic": 0.25,
        }

        # 语义路由器（可选）
        self._semantic_router: SemanticSkillRouter | None = None
        self._semantic_enabled = False
        if enable_semantic and _SEMANTIC_ROUTER_AVAILABLE:
            try:
                self._semantic_router = SemanticSkillRouter()
                self._semantic_enabled = self._semantic_router.semantic_enabled
                if self._semantic_enabled:
                    logger.info(
                        "recommender.semantic_enabled",
                        provider=self._semantic_router.provider_name,
                    )
                else:
                    logger.info("recommender.semantic_disabled_fallback")
            except Exception as e:
                logger.warning(
                    "recommender.semantic_init_failed",
                    error=str(e),
                )
                self._semantic_enabled = False

    # ---- 技能注册 ----

    def register_profile(self, manifest: SkillManifest) -> None:
        """注册技能画像用于推荐匹配."""
        self._skill_profiles[manifest.skill_id] = manifest
        # 同步注册到语义路由器
        if self._semantic_router is not None:
            try:
                self._semantic_router.register_skill(manifest)
            except Exception as e:
                logger.warning(
                    "recommender.semantic_register_failed",
                    skill_id=manifest.skill_id,
                    error=str(e),
                )

    def register_profiles(self, manifests: list[SkillManifest]) -> None:
        """批量注册技能画像."""
        for m in manifests:
            self.register_profile(m)

    # ---- 推荐接口 ----

    def recommend(
        self,
        goal: str,
        top_k: int = 5,
        agent_id: str | None = None,
        exclude_skills: list[str] | None = None,
    ) -> list[SkillRecommendation]:
        """基于用户目标推荐技能.

        Args:
            goal: 用户目标描述（自然语言）.
            top_k: 返回数量.
            agent_id: Agent ID（用于检索记忆偏好）.
            exclude_skills: 排除的技能 ID.

        Returns:
            推荐列表，按评分降序.
        """
        exclude = set(exclude_skills or [])
        goal_tokens = set(self._tokenize(goal))
        goal_lower = goal.lower()

        # 从记忆中提取用户偏好
        memory_prefs: dict[str, float] = {}
        if self._memory and agent_id:
            memory_prefs = self._extract_memory_preferences(
                goal, agent_id
            )

        # 预计算语义匹配得分
        semantic_scores: dict[str, float] = {}
        if self._semantic_enabled and self._semantic_router is not None:
            try:
                semantic_results = self._semantic_router.match(
                    goal, top_k=len(self._skill_profiles)
                )
                for r in semantic_results:
                    semantic_scores[r.skill_id] = r.score
            except Exception as e:
                logger.warning(
                    "recommender.semantic_match_failed",
                    error=str(e),
                )

        scored: list[SkillRecommendation] = []

        for sid, profile in self._skill_profiles.items():
            if sid in exclude:
                continue

            # 各维度评分
            kw_score = self._keyword_score(goal_tokens, profile, goal_lower)
            cap_score = self._capability_score(goal_tokens, profile)
            exp_score = self._experience_score(sid)
            mem_score = memory_prefs.get(sid, 0.0)
            tag_score = self._tag_score(goal_tokens, profile)
            sem_score = semantic_scores.get(sid, 0.0)

            # 加权融合
            w = self._weights
            total = (
                w["keyword"] * kw_score
                + w["capability"] * cap_score
                + w["experience"] * exp_score
                + w["memory_preference"] * mem_score
                + w["tag_match"] * tag_score
                + w["semantic"] * sem_score
            )

            reasons = self._generate_reasons(
                profile, kw_score, cap_score, exp_score, mem_score, sem_score
            )

            dims = {
                "keyword": round(kw_score, 3),
                "capability": round(cap_score, 3),
                "experience": round(exp_score, 3),
                "memory": round(mem_score, 3),
                "tag": round(tag_score, 3),
            }
            if self._semantic_enabled:
                dims["semantic"] = round(sem_score, 3)

            scored.append(
                SkillRecommendation(
                    skill_id=sid,
                    score=round(total, 4),
                    reasons=reasons,
                    match_dimensions=dims,
                )
            )

        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    # ---- 维度评分 ----

    def _keyword_score(
        self,
        goal_tokens: set[str],
        profile: SkillManifest,
        goal_lower: str,
    ) -> float:
        """BM25F 风格关键词评分."""
        text_pool = (
            profile.name
            + " "
            + profile.description
            + " "
            + " ".join(profile.capabilities)
        ).lower()
        text_tokens = set(self._tokenize(text_pool))
        if not goal_tokens:
            return 0.0
        intersection = goal_tokens & text_tokens
        if not intersection:
            return 0.0
        # Jaccard + IDF 权重
        idf_sum = sum(
            math.log(
                (len(self._skill_profiles) + 1)
                / (sum(
                    1 for p in self._skill_profiles.values()
                    if t in (p.name + " " + p.description).lower()
                ) + 1)
                + 1
            )
            for t in intersection
        )
        return min(1.0, len(intersection) / len(goal_tokens) * idf_sum / len(goal_tokens))

    def _capability_score(
        self,
        goal_tokens: set[str],
        profile: SkillManifest,
    ) -> float:
        """能力匹配评分."""
        if not profile.capabilities or not goal_tokens:
            return 0.0
        cap_tokens: set[str] = set()
        for cap in profile.capabilities:
            cap_tokens.update(self._tokenize(cap))
        intersection = goal_tokens & cap_tokens
        if not intersection:
            return 0.0
        return len(intersection) / len(goal_tokens)

    def _experience_score(self, skill_id: str) -> float:
        """经验评分（基于 SkillExperienceBank）."""
        if self._experience is None:
            return 0.5  # 无经验数据时中性分
        try:
            rate = self._experience.predict_success_rate(skill_id, "*")
            return rate
        except Exception:
            return 0.5

    def _tag_score(
        self,
        goal_tokens: set[str],
        profile: SkillManifest,
    ) -> float:
        """标签匹配评分."""
        if not profile.tags or not goal_tokens:
            return 0.0
        tag_tokens: set[str] = set()
        for tag in profile.tags:
            tag_tokens.update(self._tokenize(tag))
        intersection = goal_tokens & tag_tokens
        if not intersection:
            return 0.0
        return len(intersection) / max(len(goal_tokens), 1)

    def _extract_memory_preferences(
        self, goal: str, agent_id: str
    ) -> dict[str, float]:
        """从 AgentMemory 提取用户偏好."""
        if self._memory is None:
            return {}
        prefs: dict[str, float] = {}
        try:
            results = self._memory.retrieve(goal, top_k=10)
            for entry, score in results:
                # 从记忆内容中提取技能引用
                content = entry.content
                for sid in self._skill_profiles:
                    if sid in content:
                        prefs[sid] = max(
                            prefs.get(sid, 0.0), score * 0.5
                        )
        except Exception:
            pass
        return prefs

    def _generate_reasons(
        self,
        profile: SkillManifest,
        kw: float,
        cap: float,
        exp: float,
        mem: float,
        sem: float = 0.0,
    ) -> list[str]:
        """生成推荐理由."""
        reasons: list[str] = []
        if kw > 0.3:
            reasons.append("关键词高度匹配")
        if cap > 0.3:
            reasons.append(f"具备相关能力: {', '.join(profile.capabilities[:3])}")
        if exp > 0.7:
            reasons.append("历史成功率较高")
        if mem > 0.3:
            reasons.append("用户历史偏好")
        if sem > 0.5:
            reasons.append(f"语义相似度高 ({sem:.0%})")
        if not reasons:
            reasons.append("综合匹配推荐")
        return reasons

    # ---- 内部工具 ----

    def _tokenize(self, text: str) -> list[str]:
        """简单分词."""
        return re.findall(r"\b\w+\b", text.lower())

    # ---- 权重配置 ----

    def set_weights(self, weights: dict[str, float]) -> None:
        """自定义推荐权重.

        Args:
            weights: 维度权重字典，key 为维度名，value 为权重值.
        """
        valid_keys = {
            "keyword", "capability", "experience",
            "memory_preference", "tag_match", "semantic",
        }
        for k, v in weights.items():
            if k in valid_keys:
                self._weights[k] = v
        # 归一化
        total = sum(self._weights.values())
        if total > 0:
            self._weights = {
                k: v / total for k, v in self._weights.items()
            }

    # ---- 在线自适应权重调整（【第三轮优化】新增） ----

    def record_feedback(
        self,
        skill_id: str,
        goal: str,
        accepted: bool,
        agent_id: str | None = None,
    ) -> None:
        """记录推荐反馈，在线调整权重.

        基于用户是否采纳推荐结果，动态调整各维度权重。
        被采纳的推荐中得分高的维度获得正向强化。

        Args:
            skill_id: 推荐的技能 ID.
            goal: 用户目标.
            accepted: 用户是否采纳.
            agent_id: Agent ID.
        """
        # 重新计算该技能在当前 goal 下的各维度得分
        recs = self.recommend(goal, top_k=10, agent_id=agent_id)
        target = next((r for r in recs if r.skill_id == skill_id), None)
        if target is None:
            return

        adjust_rate = 0.02 if accepted else -0.02
        for dim, score in target.match_dimensions.items():
            dim_key = dim if dim != "memory" else "memory_preference"
            if dim_key in self._weights:
                # 高分维度获得更多调整
                self._weights[dim_key] += adjust_rate * score

        # 裁剪并重新归一化
        for k in self._weights:
            self._weights[k] = max(0.05, min(0.8, self._weights[k]))
        total = sum(self._weights.values())
        self._weights = {k: v / total for k, v in self._weights.items()}

        logger.info(
            "recommender_weights_adjusted",
            skill_id=skill_id,
            accepted=accepted,
            new_weights={k: round(v, 3) for k, v in self._weights.items()},
        )
