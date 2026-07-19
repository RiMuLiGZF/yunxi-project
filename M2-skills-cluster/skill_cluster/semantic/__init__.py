"""语义路由模块 - 为 M2 技能集群提供语义匹配能力.

此模块基于 shared.semantic 工具包，实现技能的语义推荐。
作为关键词 BM25F 匹配的补充，提升同义词和隐含意图的识别能力。
"""

from .semantic_router import SemanticSkillRouter, SemanticMatchResult

__all__ = [
    "SemanticSkillRouter",
    "SemanticMatchResult",
]
