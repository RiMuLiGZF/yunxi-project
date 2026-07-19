"""纯关键词兜底 Embedding 提供者.

当 sentence-transformers 不可用时，使用基于 TF-IDF 风格的
关键词词袋模型作为兜底 embedding 实现。

特点：
- 纯 Python 实现，零外部依赖
- 基于字符 n-gram + 词频的稀疏向量
- 输出维度固定（默认 256 维），便于向量索引使用
- 支持中英文混合文本
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from .embedding_base import EmbeddingProvider, EmbeddingResult


class FallbackKeywordProvider(EmbeddingProvider):
    """基于关键词哈希的兜底 Embedding 提供者.

    使用字符 n-gram + 哈希映射的方法，将文本映射到固定维度的向量。
    这是一种轻量级的"伪语义"表示，比纯关键词匹配略好，
    主要用于在没有 sentence-transformers 时保持接口一致性。

    原理：
    1. 对文本进行分词（英文单词 + 中文单字/双字）
    2. 提取字符 n-gram (n=2,3)
    3. 使用哈希函数将 token 映射到固定维度的桶
    4. 统计频次并做 L2 归一化

    注意：这不是真正的语义嵌入，只是关键词级别的特征表示。
    当 sentence-transformers 可用时，会自动升级到真正的语义嵌入。
    """

    def __init__(self, dimension: int = 256) -> None:
        """初始化兜底提供者.

        Args:
            dimension: 输出向量维度，默认 256
        """
        self._dimension = dimension

    @property
    def name(self) -> str:
        return f"fallback_keyword(dim={self._dimension})"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> EmbeddingResult:
        if not text or not text.strip():
            vector = [0.0] * self._dimension
            return EmbeddingResult(
                vector=vector,
                dimension=self._dimension,
                provider=self.name,
                normalized=True,
            )

        # 提取 tokens
        tokens = self._tokenize(text)

        # 哈希到向量
        vector = [0.0] * self._dimension
        for token in tokens:
            idx = self._hash_token(token)
            vector[idx] += 1.0

        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]

        return EmbeddingResult(
            vector=vector,
            dimension=self._dimension,
            provider=self.name,
            normalized=True,
        )

    def _tokenize(self, text: str) -> list[str]:
        """提取文本的 token 列表.

        包含：
        - 英文单词（\w+）
        - 中文字符的 bigram（连续两个汉字）
        - 中文字符的 unigram（单个汉字）
        - 通用字符 trigram

        Args:
            text: 输入文本

        Returns:
            token 列表
        """
        tokens: list[str] = []
        text_lower = text.lower()

        # 1. 英文单词
        words = re.findall(r"[a-zA-Z0-9_]+", text_lower)
        tokens.extend(words)

        # 2. 中文字符
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text_lower)

        # 中文 unigram
        tokens.extend(chinese_chars)

        # 中文 bigram
        for i in range(len(chinese_chars) - 1):
            tokens.append(chinese_chars[i] + chinese_chars[i + 1])

        # 3. 通用字符 trigram（对短文本有效）
        if len(text_lower) >= 3:
            for i in range(len(text_lower) - 2):
                trigram = text_lower[i:i + 3]
                # 跳过纯空白
                if trigram.strip():
                    tokens.append(f"__3gram__{trigram}")

        return tokens

    def _hash_token(self, token: str) -> int:
        """将 token 哈希到向量维度索引.

        使用 MD5 哈希取模，分布较均匀。

        Args:
            token: 输入 token

        Returns:
            0 到 dimension-1 的索引
        """
        h = hashlib.md5(token.encode("utf-8")).hexdigest()
        # 取前 8 位十六进制转整数，再取模
        return int(h[:8], 16) % self._dimension

    def keyword_match_score(self, query: str, document: str) -> float:
        """直接计算关键词匹配得分（用于不需要向量的场景）.

        基于 Jaccard 相似度 + 关键词覆盖度。

        Args:
            query: 查询文本
            document: 文档文本

        Returns:
            匹配得分 (0-1)
        """
        query_tokens = set(self._tokenize(query))
        doc_tokens = set(self._tokenize(document))

        if not query_tokens or not doc_tokens:
            return 0.0

        intersection = query_tokens & doc_tokens
        if not intersection:
            return 0.0

        # Jaccard 相似度
        jaccard = len(intersection) / len(query_tokens | doc_tokens)

        # 查询覆盖度（有多少查询 token 出现在文档中）
        coverage = len(intersection) / len(query_tokens)

        # 加权融合
        return 0.4 * jaccard + 0.6 * coverage
