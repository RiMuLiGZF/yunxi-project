"""
通用文本处理工具

提供跨模块复用的文本分词等基础能力。
"""

from __future__ import annotations

import re
from typing import List

import structlog

logger = structlog.get_logger(__name__)


def tokenize(text: str) -> List[str]:
    """
    统一分词函数：英文小写分词 + 中文2字词切分

    - 英文：提取2字符及以上的英文单词，转为小写
    - 中文：使用2字滑窗切分相邻中文字符

    Args:
        text: 输入文本

    Returns:
        分词结果列表
    """
    if not text:
        return []
    # 英文小写
    text = text.lower()
    # 提取英文单词（2字符及以上）
    en_words = re.findall(r'[a-zA-Z]{2,}', text)
    # 中文2字词
    cn_words = []
    for i in range(len(text) - 1):
        if '\u4e00' <= text[i] <= '\u9fff' and '\u4e00' <= text[i+1] <= '\u9fff':
            cn_words.append(text[i:i+2])
    return en_words + cn_words
# vim: set et ts=4 sw=4: