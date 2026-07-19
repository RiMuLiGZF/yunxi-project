"""技能语义路由器.

使用向量相似度匹配用户目标与技能描述，
作为关键词 BM25F 匹配的补充维度。

设计：
- 复用 shared.semantic 的 EmbeddingProvider 和 VectorIndex
- 首次加载时生成所有技能描述的 embedding 并缓存
- 技能注册时增量更新向量索引
- embedding 不可用时自动降级为纯关键词匹配
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import structlog

from skill_cluster.interfaces import SkillManifest

logger = structlog.get_logger()

# 尝试从 shared 层导入语义工具
try:
    from shared.semantic import (
        EmbeddingProvider,
        VectorIndex,
        SearchResult,
        get_default_provider,
        FallbackKeywordProvider,
    )

    _SEMANTIC_AVAILABLE = True
except ImportError:
    _SEMANTIC_AVAILABLE = False
    logger.warning("semantic.shared_module_not_found")


@dataclass
class SemanticMatchResult:
    """语义匹配结果."""

    skill_id: str
    score: float
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class SemanticSkillRouter:
    """技能语义路由器.

    使用文本嵌入 + 向量相似度匹配用户目标与技能描述。
    作为关键词匹配的补充，提升同义词识别能力。

    特点：
    - 自动检测 embedding 后端，不可用时降级为关键词匹配
    - 技能描述 embedding 缓存，增量更新
    - 与 SkillRecommender 无缝集成
    """

    def __init__(
        self,
        provider: EmbeddingProvider | None = None,
        description_fields: list[str] | None = None,
    ) -> None:
        """初始化语义路由器.

        Args:
            provider: Embedding 提供者，None 则使用默认提供者
            description_fields: 用于生成 embedding 的技能字段列表
        """
        self._provider: EmbeddingProvider | None = None
        self._index: VectorIndex | None = None
        self._skill_manifests: dict[str, SkillManifest] = {}
        self._description_fields = description_fields or [
            "name", "description", "capabilities", "tags"
        ]
        self._semantic_enabled = False

        # 尝试初始化语义组件
        if _SEMANTIC_AVAILABLE:
            try:
                self._provider = provider or get_default_provider()
                self._index = VectorIndex(dimension=self._provider.dimension)
                self._semantic_enabled = True
                logger.info(
                    "semantic.router_initialized",
                    provider=self._provider.name,
                    dimension=self._provider.dimension,
                )
            except Exception as e:
                logger.warning(
                    "semantic.router_init_failed_fallback_to_keyword",
                    error=str(e),
                )
                self._semantic_enabled = False

    @property
    def semantic_enabled(self) -> bool:
        """是否启用了语义匹配."""
        return self._semantic_enabled

    @property
    def provider_name(self) -> str:
        """当前使用的 embedding 提供者名称."""
        if self._provider is None:
            return "disabled"
        return self._provider.name

    @property
    def size(self) -> int:
        """已索引的技能数量."""
        if self._index is None:
            return len(self._skill_manifests)
        return self._index.size

    # ------------------------------------------------------------------
    # 技能注册
    # ------------------------------------------------------------------

    def register_skill(self, manifest: SkillManifest) -> None:
        """注册单个技能到语义索引.

        Args:
            manifest: 技能清单
        """
        self._skill_manifests[manifest.skill_id] = manifest

        if not self._semantic_enabled or self._index is None:
            return

        try:
            desc_text = self._build_description_text(manifest)
            embedding = self._provider.embed(desc_text) if self._provider else None
            if embedding:
                self._index.add(
                    vector_id=manifest.skill_id,
                    vector=embedding.vector,
                    metadata={
                        "skill_id": manifest.skill_id,
                        "name": manifest.name,
                        "category": "skill",
                    },
                )
                logger.debug(
                    "semantic.skill_registered",
                    skill_id=manifest.skill_id,
                )
        except Exception as e:
            logger.warning(
                "semantic.skill_registration_failed",
                skill_id=manifest.skill_id,
                error=str(e),
            )

    def register_skills(self, manifests: list[SkillManifest]) -> None:
        """批量注册技能.

        Args:
            manifests: 技能清单列表
        """
        for manifest in manifests:
            self.register_skill(manifest)

    def unregister_skill(self, skill_id: str) -> bool:
        """注销技能.

        Args:
            skill_id: 技能 ID

        Returns:
            True 表示成功删除
        """
        if skill_id in self._skill_manifests:
            del self._skill_manifests[skill_id]

        if self._index is not None:
            return self._index.delete(skill_id)

        return False

    # ------------------------------------------------------------------
    # 语义匹配
    # ------------------------------------------------------------------

    def match(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[SemanticMatchResult]:
        """语义匹配技能.

        Args:
            query: 用户目标/查询文本
            top_k: 返回前 K 个结果

        Returns:
            语义匹配结果列表，按得分降序
        """
        if not query or not query.strip():
            return []

        if self._semantic_enabled and self._index is not None and self._index.size > 0:
            return self._semantic_match(query, top_k)
        else:
            return self._keyword_fallback_match(query, top_k)

    def _semantic_match(
        self, query: str, top_k: int
    ) -> list[SemanticMatchResult]:
        """使用向量索引进行语义匹配."""
        assert self._provider is not None
        assert self._index is not None

        try:
            query_embedding = self._provider.embed(query)
            results = self._index.search(query_embedding.vector, top_k=top_k)

            return [
                SemanticMatchResult(
                    skill_id=r.id,
                    score=r.score,
                    reason=f"语义相似度: {r.score:.3f}",
                    metadata=r.metadata,
                )
                for r in results
            ]
        except Exception as e:
            logger.warning(
                "semantic.match_failed_fallback_to_keyword",
                error=str(e),
            )
            return self._keyword_fallback_match(query, top_k)

    def _keyword_fallback_match(
        self, query: str, top_k: int
    ) -> list[SemanticMatchResult]:
        """关键词兜底匹配.

        当语义匹配不可用时，使用简单的关键词相似度。
        """
        query_lower = query.lower()
        query_tokens = set(self._simple_tokenize(query_lower))

        if not query_tokens:
            return []

        scored: list[tuple[str, float, str]] = []

        for sid, manifest in self._skill_manifests.items():
            desc_text = self._build_description_text(manifest).lower()
            desc_tokens = set(self._simple_tokenize(desc_text))

            if not desc_tokens:
                continue

            intersection = query_tokens & desc_tokens
            if not intersection:
                continue

            # 计算 Jaccard 相似度 + 覆盖率
            jaccard = len(intersection) / len(query_tokens | desc_tokens)
            coverage = len(intersection) / len(query_tokens)
            score = 0.4 * jaccard + 0.6 * coverage

            matched_words = ", ".join(list(intersection)[:3])
            reason = f"关键词匹配: {matched_words}"

            scored.append((sid, score, reason))

        scored.sort(key=lambda x: x[1], reverse=True)

        return [
            SemanticMatchResult(skill_id=sid, score=score, reason=reason)
            for sid, score, reason in scored[:top_k]
        ]

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _build_description_text(self, manifest: SkillManifest) -> str:
        """构建用于 embedding 的技能描述文本.

        将多个字段组合成一段完整的描述文本。
        """
        parts: list[str] = []

        if "name" in self._description_fields:
            parts.append(manifest.name)
        if "description" in self._description_fields:
            parts.append(manifest.description)
        if "capabilities" in self._description_fields and manifest.capabilities:
            parts.append(" ".join(manifest.capabilities))
        if "tags" in self._description_fields and manifest.tags:
            parts.append(" ".join(manifest.tags))

        return " ".join(parts)

    def _simple_tokenize(self, text: str) -> list[str]:
        """简单分词（用于 fallback 关键词匹配）."""
        import re

        # 英文单词
        tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        # 中文字符
        chinese = re.findall(r"[\u4e00-\u9fff]", text)
        tokens.extend(chinese)
        # 中文 bigram
        for i in range(len(chinese) - 1):
            tokens.append(chinese[i] + chinese[i + 1])

        return tokens

    def get_skill_semantic_score(self, skill_id: str, query: str) -> float:
        """获取指定技能对查询的语义匹配得分.

        Args:
            skill_id: 技能 ID
            query: 查询文本

        Returns:
            语义匹配得分 (0-1)，技能不存在时返回 0
        """
        if skill_id not in self._skill_manifests:
            return 0.0

        results = self.match(query, top_k=len(self._skill_manifests))
        for r in results:
            if r.skill_id == skill_id:
                return r.score

        return 0.0

    def rebuild_index(self) -> None:
        """重建向量索引.

        当 embedding 提供者变化时，重新生成所有向量。
        """
        if not self._semantic_enabled or self._index is None:
            return

        self._index.clear()
        manifests = list(self._skill_manifests.values())
        self.register_skills(manifests)

        logger.info(
            "semantic.index_rebuilt",
            skill_count=len(self._skill_manifests),
        )
