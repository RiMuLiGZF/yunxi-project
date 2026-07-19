"""语义场景识别模块.

为 M4 场景引擎提供基于向量嵌入的语义场景识别能力，
作为现有规则、关键词、贝叶斯三种方法的补充。

设计：
- 复用 shared.semantic 的 EmbeddingProvider 和 VectorIndex
- 将场景描述（名称 + 描述 + 关键词）转换为向量进行匹配
- 与 ensemble 方法集成，作为第四种识别方法
- 语义不可用时自动降级为三方法 ensemble
"""

from .semantic_recognizer import SemanticSceneRecognizer, SemanticRecognitionResult

__all__ = [
    "SemanticSceneRecognizer",
    "SemanticRecognitionResult",
]
