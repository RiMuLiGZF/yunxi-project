"""语义场景识别器.

使用向量嵌入 + 余弦相似度进行场景识别，
作为规则、关键词、贝叶斯之外的第四种识别方法。

设计原则：
- 复用 shared.semantic 工具包
- 场景描述生成 embedding 并缓存
- 不可用时自动降级
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()

# 尝试从 shared 层导入语义工具
try:
    from shared.semantic import (
        EmbeddingProvider,
        VectorIndex,
        get_default_provider,
    )

    _SEMANTIC_AVAILABLE = True
except ImportError:
    _SEMANTIC_AVAILABLE = False
    logger.warning("semantic.shared_module_not_found_m4")


@dataclass
class SemanticRecognitionResult:
    """语义识别结果."""

    scene: str
    confidence: float
    method: str = "semantic"
    candidates: list[tuple[str, float]] = field(default_factory=list)
    reason: str = ""


class SemanticSceneRecognizer:
    """语义场景识别器.

    使用文本嵌入将用户输入与场景描述进行语义相似度匹配。
    作为 ensemble 的第四种方法，补充关键词匹配在同义词、
    隐含意图方面的不足。
    """

    def __init__(
        self,
        scene_definitions: dict[str, dict[str, Any]],
        provider: EmbeddingProvider | None = None,
    ) -> None:
        """初始化语义场景识别器.

        Args:
            scene_definitions: 场景定义字典
            provider: Embedding 提供者，None 则使用默认
        """
        self._scene_definitions = scene_definitions
        self._provider: EmbeddingProvider | None = None
        self._index: VectorIndex | None = None
        self._enabled = False

        if _SEMANTIC_AVAILABLE:
            try:
                self._provider = provider or get_default_provider()
                self._index = VectorIndex(dimension=self._provider.dimension)
                self._enabled = True
                self._build_index()
                logger.info(
                    "semantic.recognizer_initialized",
                    provider=self._provider.name,
                    scene_count=len(scene_definitions),
                )
            except Exception as e:
                logger.warning(
                    "semantic.recognizer_init_failed",
                    error=str(e),
                )
                self._enabled = False

    @property
    def enabled(self) -> bool:
        """语义识别是否启用."""
        return self._enabled

    @property
    def provider_name(self) -> str:
        """当前使用的 embedding 提供者名称."""
        if self._provider is None:
            return "disabled"
        return self._provider.name

    def _build_index(self) -> None:
        """构建场景向量索引."""
        assert self._index is not None
        assert self._provider is not None

        for scene_id, scene_def in self._scene_definitions.items():
            desc_text = self._build_scene_text(scene_def)
            try:
                embedding = self._provider.embed(desc_text)
                self._index.add(
                    vector_id=scene_id,
                    vector=embedding.vector,
                    metadata={
                        "scene_id": scene_id,
                        "name": scene_def.get("name", ""),
                        "category": "scene",
                    },
                )
            except Exception as e:
                logger.warning(
                    "semantic.scene_index_build_failed",
                    scene_id=scene_id,
                    error=str(e),
                )

    def _build_scene_text(self, scene_def: dict[str, Any]) -> str:
        """构建场景描述文本用于 embedding.

        组合场景名称、描述、关键词等信息。
        """
        parts: list[str] = []

        name = scene_def.get("name", "")
        if name:
            parts.append(name)

        description = scene_def.get("description", "")
        if description:
            parts.append(description)

        keywords = scene_def.get("keywords", [])
        if keywords:
            parts.append(" ".join(keywords))

        tone = scene_def.get("tone", "")
        if tone:
            parts.append(f"语气: {tone}")

        return " ".join(parts)

    def recognize(
        self,
        text: str,
        top_k: int = 5,
    ) -> SemanticRecognitionResult:
        """语义识别场景.

        Args:
            text: 用户输入文本
            top_k: 返回候选场景数

        Returns:
            SemanticRecognitionResult 识别结果
        """
        if not self._enabled or self._index is None:
            return self._fallback_result(text)

        if not text or not text.strip():
            return SemanticRecognitionResult(
                scene="unknown",
                confidence=0.0,
                method="semantic_disabled",
                reason="输入文本为空",
            )

        try:
            assert self._provider is not None
            query_embedding = self._provider.embed(text)
            results = self._index.search(query_embedding.vector, top_k=top_k)

            if not results:
                return SemanticRecognitionResult(
                    scene="unknown",
                    confidence=0.0,
                    method="semantic",
                    reason="无匹配场景",
                )

            best = results[0]
            candidates = [(r.id, r.score) for r in results]

            return SemanticRecognitionResult(
                scene=best.id,
                confidence=best.score,
                method="semantic",
                candidates=candidates,
                reason=f"语义相似度匹配，最接近场景: {best.id}",
            )

        except Exception as e:
            logger.warning(
                "semantic.recognize_failed",
                error=str(e),
            )
            return self._fallback_result(text)

    def _fallback_result(self, text: str) -> SemanticRecognitionResult:
        """关键词兜底识别（语义不可用时）.

        使用简单的关键词命中数进行场景匹配。
        """
        if not text or not text.strip():
            return SemanticRecognitionResult(
                scene="unknown",
                confidence=0.0,
                method="semantic_fallback",
                reason="输入为空",
            )

        text_lower = text.lower()
        scored: list[tuple[str, float]] = []

        for scene_id, scene_def in self._scene_definitions.items():
            keywords = scene_def.get("keywords", [])
            if not keywords:
                continue

            matched = 0
            for kw in keywords:
                if kw.lower() in text_lower:
                    matched += 1

            if matched > 0:
                # 归一化得分
                score = min(matched / len(keywords), 1.0)
                scored.append((scene_id, score))

        if not scored:
            return SemanticRecognitionResult(
                scene="unknown",
                confidence=0.0,
                method="semantic_fallback",
                reason="无关键词匹配",
            )

        scored.sort(key=lambda x: x[1], reverse=True)
        best_scene, best_score = scored[0]

        return SemanticRecognitionResult(
            scene=best_scene,
            confidence=best_score,
            method="semantic_fallback_keyword",
            candidates=scored[:5],
            reason=f"关键词兜底匹配: {best_scene}",
        )

    def get_scene_semantic_score(self, scene_id: str, text: str) -> float:
        """获取指定场景对文本的语义匹配得分.

        Args:
            scene_id: 场景 ID
            text: 输入文本

        Returns:
            语义匹配得分 (0-1)
        """
        result = self.recognize(text, top_k=len(self._scene_definitions))
        for sid, score in result.candidates:
            if sid == scene_id:
                return score
        return 0.0

    def rebuild_index(self) -> None:
        """重建场景索引."""
        if not self._enabled or self._index is None:
            return

        self._index.clear()
        self._build_index()
        logger.info("semantic.index_rebuilt")

    def update_scene(
        self,
        scene_id: str,
        scene_def: dict[str, Any],
    ) -> None:
        """更新单个场景的索引.

        Args:
            scene_id: 场景 ID
            scene_def: 场景定义
        """
        self._scene_definitions[scene_id] = scene_def

        if not self._enabled or self._index is None or self._provider is None:
            return

        try:
            desc_text = self._build_scene_text(scene_def)
            embedding = self._provider.embed(desc_text)
            self._index.add(
                vector_id=scene_id,
                vector=embedding.vector,
                metadata={
                    "scene_id": scene_id,
                    "name": scene_def.get("name", ""),
                    "category": "scene",
                },
            )
        except Exception as e:
            logger.warning(
                "semantic.scene_update_failed",
                scene_id=scene_id,
                error=str(e),
            )
