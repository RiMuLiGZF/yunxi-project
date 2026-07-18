"""
分块策略模块 (Chunking Strategies)

实现 4 种分块策略：
1. FixedSizeChunker     - 固定大小分块
2. SemanticChunker      - 语义分块（句子/段落边界）
3. StructuredChunker    - 结构化分块（Markdown/HTML 结构感知）
4. RecursiveChunker     - 递归分块（从大到小递归分割）

所有分块器均支持：
- 可配置 chunk_size / chunk_overlap
- 丰富的 Chunk 元数据
- 纯 Python 实现，无外部依赖
"""

from __future__ import annotations

import re
import uuid
import hashlib
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


class ChunkingStrategy(str, Enum):
    """分块策略枚举"""
    FIXED = "fixed"
    SEMANTIC = "semantic"
    STRUCTURED = "structured"
    RECURSIVE = "recursive"


class ContentType(str, Enum):
    """内容类型"""
    TEXT = "text"
    TABLE = "table"
    CODE = "code"
    IMAGE_CAPTION = "image_caption"
    HEADING = "heading"
    LIST = "list"


@dataclass
class ChunkMetadata:
    """
    Chunk 元数据（增强版）

    包含完整的溯源和上下文信息，支持引用追溯和上下文扩展。
    """
    chunk_index: int = 0
    total_chunks: int = 0
    document_id: str = ""
    document_title: str = ""
    section_path: str = ""          # 章节路径，如 "第一章/第二节/三、xxx"
    token_count: int = 0
    char_count: int = 0
    content_type: str = ContentType.TEXT.value
    keywords: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    start_pos: int = 0              # 在原文中的起始位置
    end_pos: int = 0                # 在原文中的结束位置
    heading_level: int = 0          # 标题层级（结构化分块用）
    parent_chunk_id: str = ""       # 父 chunk ID（递归分块用）
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "section_path": self.section_path,
            "token_count": self.token_count,
            "char_count": self.char_count,
            "content_type": self.content_type,
            "keywords": self.keywords.copy(),
            "entities": self.entities.copy(),
            "start_pos": self.start_pos,
            "end_pos": self.end_pos,
            "heading_level": self.heading_level,
            "parent_chunk_id": self.parent_chunk_id,
            "extra": self.extra.copy(),
        }


@dataclass
class ChunkResult:
    """分块结果"""
    chunk_id: str
    text: str
    metadata: ChunkMetadata

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "metadata": self.metadata.to_dict(),
        }


# ============================================================
# 工具函数
# ============================================================

def estimate_tokens(text: str) -> int:
    """
    估算 token 数量

    粗略估算：中文约 1.5 字/token，英文约 4 字符/token
    """
    if not text:
        return 0
    # 统计中文字符数
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    # 统计英文单词数（粗略）
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    # 其他字符
    other_chars = len(text) - chinese_chars - len(re.findall(r'[a-zA-Z]', text))

    tokens = (chinese_chars / 1.5) + (english_words * 1.3) + (other_chars / 4)
    return max(1, int(tokens))


def extract_keywords(text: str, top_k: int = 10) -> List[str]:
    """
    提取关键词（基于词频的简单实现）

    支持中英文混合文本。
    """
    if not text:
        return []

    # 移除标点和空白
    clean = re.sub(r'[^\w\u4e00-\u9fff]', ' ', text)
    words = clean.split()

    all_words = []
    for w in words:
        if re.match(r'^[\u4e00-\u9fff]+$', w) and len(w) >= 2:
            # 中文：提取 2-gram 和 3-gram
            for n in [2, 3]:
                if len(w) >= n:
                    for i in range(len(w) - n + 1):
                        all_words.append(w[i:i + n])
        elif len(w) >= 3:
            all_words.append(w.lower())

    # 词频统计
    freq: Dict[str, int] = {}
    for w in all_words:
        freq[w] = freq.get(w, 0) + 1

    # 按频率排序
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:top_k]]


def extract_entities(text: str) -> List[str]:
    """
    简单实体提取（基于正则模式）

    提取：日期、数字、专有名词（大写开头连续词）、引号内容等
    """
    entities = []

    # 日期模式
    date_patterns = [
        r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?',
        r'\d{1,2}月\d{1,2}[日号]',
    ]
    for pattern in date_patterns:
        entities.extend(re.findall(pattern, text))

    # 数字 + 单位
    unit_pattern = r'\d+(?:\.\d+)?\s*(?:个|条|项|人|天|小时|分钟|秒|米|公里|千克|%|倍|MB|GB|KB|TB)'
    entities.extend(re.findall(unit_pattern, text))

    # 引号中的内容（可能是专有名词）
    quote_pattern = r'[""]([^""]{2,30})[""]'
    entities.extend(re.findall(quote_pattern, text))

    # 书名号中的内容
    book_pattern = r'[《]([^《》]{2,50})[》]'
    entities.extend(re.findall(book_pattern, text))

    # 去重并限制数量
    seen = set()
    unique_entities = []
    for e in entities:
        e = e.strip()
        if e and e not in seen and len(e) <= 50:
            seen.add(e)
            unique_entities.append(e)

    return unique_entities[:20]


def generate_chunk_id(doc_id: str, index: int) -> str:
    """生成 chunk ID"""
    return f"{doc_id}_c{index:04d}"


# ============================================================
# 基础分块器
# ============================================================

class BaseChunker(ABC):
    """分块器基类"""

    def __init__(self,
                 chunk_size: int = 512,
                 chunk_overlap: int = 50,
                 min_chunk_size: int = 50,
                 by_tokens: bool = False):
        """
        Args:
            chunk_size: 分块大小（字符数或 token 数）
            chunk_overlap: 重叠大小
            min_chunk_size: 最小分块大小
            by_tokens: 是否按 token 数计算（否则按字符数）
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # 确保 min_chunk_size 不超过 chunk_size 的一半，避免合并过度
        self.min_chunk_size = min(min_chunk_size, max(1, chunk_size // 2))
        self.by_tokens = by_tokens

    def _measure(self, text: str) -> int:
        """测量文本大小"""
        if self.by_tokens:
            return estimate_tokens(text)
        return len(text)

    @abstractmethod
    def chunk(self,
              text: str,
              doc_id: str = "",
              doc_title: str = "") -> List[ChunkResult]:
        """
        对文本进行分块

        Args:
            text: 待分块的文本
            doc_id: 文档 ID
            doc_title: 文档标题

        Returns:
            分块结果列表
        """
        ...

    def _build_chunks(self,
                      chunks_text: List[str],
                      doc_id: str,
                      doc_title: str,
                      start_positions: Optional[List[int]] = None,
                      content_type: str = ContentType.TEXT.value,
                      section_path: str = "",
                      heading_level: int = 0) -> List[ChunkResult]:
        """
        根据文本列表构建 ChunkResult 对象

        Args:
            chunks_text: 分块文本列表
            doc_id: 文档 ID
            doc_title: 文档标题
            start_positions: 每个块在原文中的起始位置
            content_type: 内容类型
            section_path: 章节路径
            heading_level: 标题层级

        Returns:
            ChunkResult 列表
        """
        if not doc_id:
            doc_id = f"doc_{uuid.uuid4().hex[:8]}"

        total = len(chunks_text)
        results = []

        for i, chunk_text in enumerate(chunks_text):
            chunk_id = generate_chunk_id(doc_id, i)
            char_count = len(chunk_text)
            token_count = estimate_tokens(chunk_text)
            keywords = extract_keywords(chunk_text, top_k=5)
            entities = extract_entities(chunk_text)

            start_pos = start_positions[i] if start_positions and i < len(start_positions) else 0
            end_pos = start_pos + char_count

            metadata = ChunkMetadata(
                chunk_index=i,
                total_chunks=total,
                document_id=doc_id,
                document_title=doc_title,
                section_path=section_path,
                token_count=token_count,
                char_count=char_count,
                content_type=content_type,
                keywords=keywords,
                entities=entities,
                start_pos=start_pos,
                end_pos=end_pos,
                heading_level=heading_level,
            )

            results.append(ChunkResult(
                chunk_id=chunk_id,
                text=chunk_text,
                metadata=metadata,
            ))

        return results


# ============================================================
# 1. 固定大小分块
# ============================================================

class FixedSizeChunker(BaseChunker):
    """
    固定大小分块 (Fixed Size Chunking)

    按固定字符数/token 数分割文本，保持重叠窗口。
    最简单可靠的分块方式，适用于无结构文本。
    """

    def chunk(self,
              text: str,
              doc_id: str = "",
              doc_title: str = "") -> List[ChunkResult]:
        if not text or not text.strip():
            return []

        text = text.strip()
        chunks_text = []
        start_positions = []

        if self._measure(text) <= self.chunk_size:
            # 文本本身就小于 chunk_size
            return self._build_chunks([text], doc_id, doc_title, [0])

        step = self.chunk_size - self.chunk_overlap
        if step <= 0:
            step = self.chunk_size  # 防止重叠大于块大小

        pos = 0
        text_len = len(text)

        while pos < text_len:
            end = pos + self.chunk_size
            if end >= text_len:
                # 最后一块
                chunk = text[pos:]
                if self._measure(chunk) >= self.min_chunk_size or not chunks_text:
                    chunks_text.append(chunk)
                    start_positions.append(pos)
                else:
                    # 最后一块太小，合并到前一块
                    if chunks_text:
                        chunks_text[-1] = chunks_text[-1] + chunk
                break

            # 尝试在空格或标点处断开（避免截断单词）
            chunk = text[pos:end]
            # 从后往前找合适的断点
            break_point = self._find_break_point(chunk)
            actual_end = pos + break_point

            chunk = text[pos:actual_end]
            chunks_text.append(chunk)
            start_positions.append(pos)

            # 移动到下一个位置（考虑重叠）
            next_pos = actual_end - self.chunk_overlap
            if next_pos <= pos:
                next_pos = pos + max(1, break_point)  # 确保前进
            pos = next_pos

        return self._build_chunks(chunks_text, doc_id, doc_title, start_positions)

    def _find_break_point(self, text: str) -> int:
        """
        在文本末尾附近找合适的断点（句子/段落/词边界）

        返回断点位置（相对于 text 开头的偏移）
        """
        if len(text) < 20:
            return len(text)

        # 优先在段落边界断开
        last_para = text.rfind('\n\n', int(len(text) * 0.7))
        if last_para > 0:
            return last_para

        # 其次在句子末尾断开
        sentence_end = re.search(r'[。！？.!?][\s"\')）\]]*', text[int(len(text) * 0.7):])
        if sentence_end:
            pos = int(len(text) * 0.7) + sentence_end.end()
            return pos

        # 再次在换行处断开
        last_newline = text.rfind('\n', int(len(text) * 0.7))
        if last_newline > 0:
            return last_newline

        # 最后在空格处断开
        last_space = text.rfind(' ', int(len(text) * 0.8))
        if last_space > 0:
            return last_space

        return len(text)


# ============================================================
# 2. 语义分块
# ============================================================

class SemanticChunker(BaseChunker):
    """
    语义分块 (Semantic Chunking)

    按句子/段落/语义边界分割，避免语义断裂。
    策略：
    1. 先按段落分割
    2. 短段落合并，长段落按句子分割
    3. 保持语义单元完整
    4. 添加重叠窗口
    """

    def chunk(self,
              text: str,
              doc_id: str = "",
              doc_title: str = "") -> List[ChunkResult]:
        if not text or not text.strip():
            return []

        text = text.strip()
        # 压缩过多空行
        text = re.sub(r'\n{3,}', '\n\n', text)

        # 按段落分割
        paragraphs = re.split(r'\n\n+', text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        if not paragraphs:
            return []

        # 计算每个段落的起始位置
        para_start_positions = []
        current_pos = 0
        for p in paragraphs:
            idx = text.find(p, current_pos)
            if idx >= 0:
                para_start_positions.append(idx)
                current_pos = idx + len(p)
            else:
                para_start_positions.append(current_pos)
                current_pos += len(p)

        # 合并/拆分成合适大小的块
        chunks_text = []
        chunk_start_positions = []
        current_chunk = ""
        current_chunk_start = -1

        for i, para in enumerate(paragraphs):
            para_size = self._measure(para)

            if current_chunk_start < 0:
                current_chunk_start = para_start_positions[i]

            # 如果当前块 + 段落 不超过 chunk_size，追加
            if self._measure(current_chunk) + para_size + 2 <= self.chunk_size:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
            else:
                # 当前块满了，保存
                if current_chunk:
                    chunks_text.append(current_chunk.strip())
                    chunk_start_positions.append(current_chunk_start)

                # 如果段落本身很长，按句子再分
                if para_size > self.chunk_size:
                    sentence_chunks, sent_starts = self._split_by_sentences(
                        para, para_start_positions[i]
                    )
                    for sc, ss in zip(sentence_chunks, sent_starts):
                        chunks_text.append(sc)
                        chunk_start_positions.append(ss)
                    current_chunk = ""
                    current_chunk_start = -1
                else:
                    current_chunk = para
                    current_chunk_start = para_start_positions[i]

        if current_chunk:
            chunks_text.append(current_chunk.strip())
            chunk_start_positions.append(current_chunk_start)

        # 添加重叠
        final_chunks, final_positions = self._add_overlap(chunks_text, chunk_start_positions)

        # 过滤掉太小的块（合并到前一块）
        final_chunks, final_positions = self._merge_small_chunks(
            final_chunks, final_positions
        )

        return self._build_chunks(final_chunks, doc_id, doc_title, final_positions)

    def _split_by_sentences(self, text: str, base_pos: int) -> tuple:
        """按句子分割长文本"""
        sentences = re.split(r'(?<=[。！？.!?])\s*', text)
        sentences = [s for s in sentences if s.strip()]

        if not sentences:
            return [text], [base_pos]

        chunks = []
        positions = []
        current = ""
        current_start = base_pos

        # 计算每个句子的起始位置
        sent_positions = []
        pos = 0
        for s in sentences:
            idx = text.find(s, pos)
            if idx >= 0:
                sent_positions.append(base_pos + idx)
                pos = idx + len(s)
            else:
                sent_positions.append(base_pos + pos)
                pos += len(s)

        for i, sent in enumerate(sentences):
            sent_size = self._measure(sent)
            if self._measure(current) + sent_size <= self.chunk_size:
                if not current:
                    current_start = sent_positions[i]
                current += sent
            else:
                if current:
                    chunks.append(current.strip())
                    positions.append(current_start)
                current = sent
                current_start = sent_positions[i]

        if current:
            chunks.append(current.strip())
            positions.append(current_start)

        return chunks, positions

    def _add_overlap(self, chunks: List[str], positions: List[int]) -> tuple:
        """为分块添加重叠"""
        if len(chunks) <= 1 or self.chunk_overlap <= 0:
            return chunks, positions

        final_chunks = []
        final_positions = []

        for i, chunk in enumerate(chunks):
            # 从前面的块取尾部作为重叠
            if i > 0:
                prev_text = chunks[i - 1]
                overlap_text = prev_text[-self.chunk_overlap:]
                overlap_start = positions[i - 1] + len(prev_text) - len(overlap_text)
                # 确保重叠以完整句子或单词开头
                actual_overlap = self._adjust_overlap_start(overlap_text)
                chunk = actual_overlap + chunk
                overlap_start += len(overlap_text) - len(actual_overlap)
                final_positions.append(overlap_start)
            else:
                final_positions.append(positions[i])

            final_chunks.append(chunk)

        return final_chunks, final_positions

    def _adjust_overlap_start(self, text: str) -> str:
        """调整重叠文本的起始位置，使其从完整语义单元开始"""
        if not text:
            return text

        # 找到第一个句子开头
        match = re.search(r'(?<=[。！？.!?\n])\s*', text)
        if match and match.start() < len(text) * 0.5:
            return text[match.end():]

        # 找到第一个换行
        newline_pos = text.find('\n')
        if 0 < newline_pos < len(text) * 0.5:
            return text[newline_pos + 1:]

        return text

    def _merge_small_chunks(self, chunks: List[str], positions: List[int]) -> tuple:
        """合并过小的块"""
        if len(chunks) <= 1:
            return chunks, positions

        merged_chunks = []
        merged_positions = []

        for i, chunk in enumerate(chunks):
            if self._measure(chunk) < self.min_chunk_size and merged_chunks:
                # 合并到前一块
                merged_chunks[-1] = merged_chunks[-1] + chunk
            else:
                merged_chunks.append(chunk)
                merged_positions.append(positions[i])

        return merged_chunks, merged_positions


# ============================================================
# 3. 结构化分块
# ============================================================

class StructuredChunker(BaseChunker):
    """
    结构化分块 (Structured Chunking)

    按文档结构（标题/章节/列表）分块，保留层级关系。
    支持 Markdown 结构感知。

    特点：
    - 识别 Markdown 标题（# ## ### 等）
    - 按章节层级分割
    - 保留 section_path（章节路径）
    - 标题层级信息写入元数据
    - 代码块、表格等特殊内容完整保留
    """

    # Markdown 标题正则
    _HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    # 代码块正则
    _CODE_BLOCK_RE = re.compile(r'```[\w]*\n.*?```', re.DOTALL)
    # 表格正则（简单匹配）
    _TABLE_RE = re.compile(r'^\|.*\|$\n^\|[-:| ]+\|$\n(?:^\|.*\|$\n?)*', re.MULTILINE)
    # 列表项正则
    _LIST_ITEM_RE = re.compile(r'^[\s]*[-*+]\s+|\d+\.\s+', re.MULTILINE)

    def chunk(self,
              text: str,
              doc_id: str = "",
              doc_title: str = "") -> List[ChunkResult]:
        if not text or not text.strip():
            return []

        text = text.strip()

        # 解析文档结构
        sections = self._parse_structure(text)

        if not sections:
            # 没有识别到结构，退化为语义分块
            semantic = SemanticChunker(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                min_chunk_size=self.min_chunk_size,
                by_tokens=self.by_tokens,
            )
            return semantic.chunk(text, doc_id, doc_title)

        # 按章节分块
        all_chunks: List[ChunkResult] = []
        chunk_index = 0

        for section in sections:
            section_chunks = self._chunk_section(
                section, doc_id, doc_title, chunk_index
            )
            all_chunks.extend(section_chunks)
            chunk_index += len(section_chunks)

        # 更新 total_chunks
        total = len(all_chunks)
        for i, c in enumerate(all_chunks):
            c.metadata.chunk_index = i
            c.metadata.total_chunks = total
            # 重新生成 chunk_id 以保持索引一致
            c.chunk_id = generate_chunk_id(doc_id, i)

        return all_chunks

    def _parse_structure(self, text: str) -> List[Dict[str, Any]]:
        """
        解析文档结构，提取章节信息

        Returns:
            章节列表，每个章节包含：
            - heading: 标题文本
            - level: 标题层级
            - content: 章节内容
            - start_pos: 起始位置
            - section_path: 章节路径
        """
        sections = []

        # 查找所有标题
        headings = list(self._HEADING_RE.finditer(text))

        if not headings:
            return []

        # 构建层级路径
        heading_stack: List[tuple] = []  # [(level, text)]

        for i, match in enumerate(headings):
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            start = match.start()

            # 计算章节内容（到下一个同级或更高级标题之前）
            if i + 1 < len(headings):
                end = headings[i + 1].start()
            else:
                end = len(text)

            content = text[start:end].strip()

            # 维护层级栈
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading_text))

            # 构建 section_path
            section_path = "/".join(h[1] for h in heading_stack)

            sections.append({
                "heading": heading_text,
                "level": level,
                "content": content,
                "start_pos": start,
                "section_path": section_path,
            })

        return sections

    def _chunk_section(self,
                       section: Dict[str, Any],
                       doc_id: str,
                       doc_title: str,
                       start_index: int) -> List[ChunkResult]:
        """对单个章节进行分块"""
        content = section["content"]
        section_path = section["section_path"]
        heading_level = section["level"]

        # 提取特殊块（代码块、表格）
        special_blocks = self._extract_special_blocks(content)

        if not special_blocks and self._measure(content) <= self.chunk_size:
            # 章节内容较小，作为单个块
            chunk_id = generate_chunk_id(doc_id, start_index)
            metadata = ChunkMetadata(
                chunk_index=start_index,
                document_id=doc_id,
                document_title=doc_title,
                section_path=section_path,
                token_count=estimate_tokens(content),
                char_count=len(content),
                content_type=ContentType.TEXT.value,
                keywords=extract_keywords(content, top_k=5),
                entities=extract_entities(content),
                start_pos=section["start_pos"],
                end_pos=section["start_pos"] + len(content),
                heading_level=heading_level,
            )
            return [ChunkResult(chunk_id=chunk_id, text=content, metadata=metadata)]

        # 分离特殊块和普通文本
        normal_texts = []
        normal_positions = []
        pos = 0

        for block in special_blocks:
            if block["start"] > pos:
                normal_texts.append(content[pos:block["start"]])
                normal_positions.append(section["start_pos"] + pos)
            pos = block["end"]

        if pos < len(content):
            normal_texts.append(content[pos:])
            normal_positions.append(section["start_pos"] + pos)

        # 对普通文本进行语义分块
        semantic = SemanticChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            min_chunk_size=self.min_chunk_size,
            by_tokens=self.by_tokens,
        )

        results = []
        idx = start_index

        for text, text_pos in zip(normal_texts, normal_positions):
            if text.strip():
                chunks = semantic.chunk(text.strip(), doc_id, doc_title)
                for c in chunks:
                    # 更新元数据
                    c.metadata.section_path = section_path
                    c.metadata.heading_level = heading_level
                    c.metadata.start_pos += text_pos
                    c.metadata.end_pos += text_pos
                    c.chunk_id = generate_chunk_id(doc_id, idx)
                    c.metadata.chunk_index = idx
                    results.append(c)
                    idx += 1

        # 添加特殊块（代码块、表格等作为独立块）
        for block in special_blocks:
            if self._measure(block["content"]) < self.min_chunk_size:
                continue

            chunk_id = generate_chunk_id(doc_id, idx)
            metadata = ChunkMetadata(
                chunk_index=idx,
                document_id=doc_id,
                document_title=doc_title,
                section_path=section_path,
                token_count=estimate_tokens(block["content"]),
                char_count=len(block["content"]),
                content_type=block["content_type"],
                keywords=extract_keywords(block["content"], top_k=3),
                entities=[],
                start_pos=section["start_pos"] + block["start"],
                end_pos=section["start_pos"] + block["end"],
                heading_level=heading_level,
            )
            results.append(ChunkResult(
                chunk_id=chunk_id,
                text=block["content"],
                metadata=metadata,
            ))
            idx += 1

        # 按起始位置排序
        results.sort(key=lambda c: c.metadata.start_pos)

        # 重新编号
        for i, c in enumerate(results):
            c.metadata.chunk_index = start_index + i
            c.chunk_id = generate_chunk_id(doc_id, start_index + i)

        return results

    def _extract_special_blocks(self, text: str) -> List[Dict[str, Any]]:
        """提取特殊块（代码块、表格）"""
        blocks = []

        # 代码块
        for match in self._CODE_BLOCK_RE.finditer(text):
            blocks.append({
                "start": match.start(),
                "end": match.end(),
                "content": match.group(),
                "content_type": ContentType.CODE.value,
            })

        # 表格
        for match in self._TABLE_RE.finditer(text):
            blocks.append({
                "start": match.start(),
                "end": match.end(),
                "content": match.group(),
                "content_type": ContentType.TABLE.value,
            })

        # 按起始位置排序
        blocks.sort(key=lambda b: b["start"])
        return blocks


# ============================================================
# 4. 递归分块
# ============================================================

class RecursiveChunker(BaseChunker):
    """
    递归分块 (Recursive Chunking)

    从大到小递归分割，优先保持语义单元完整。
    分割优先级（从高到低）：
    1. 段落分隔符 (\n\n)
    2. 句子结束符 (。！？.!?)
    3. 子句分隔符 (，,；;)
    4. 单词/字符

    类似 LangChain 的 RecursiveCharacterTextSplitter。
    """

    # 递归分隔符列表（从大到小）
    _SEPARATORS = [
        ("\n\n", "paragraph"),
        ("\n", "line"),
        ("。", "sentence_cn"),
        ("！", "sentence_cn"),
        ("？", "sentence_cn"),
        (". ", "sentence_en"),
        ("! ", "sentence_en"),
        ("? ", "sentence_en"),
        ("，", "clause_cn"),
        (", ", "clause_en"),
        ("；", "semicolon_cn"),
        ("; ", "semicolon_en"),
        (" ", "word"),
        ("", "character"),
    ]

    def chunk(self,
              text: str,
              doc_id: str = "",
              doc_title: str = "") -> List[ChunkResult]:
        if not text or not text.strip():
            return []

        text = text.strip()

        # 递归分割
        chunks_text = self._split_text(text, 0)

        # 计算每个块的起始位置
        positions = []
        current_pos = 0
        for chunk in chunks_text:
            idx = text.find(chunk, current_pos)
            if idx >= 0:
                positions.append(idx)
                current_pos = idx + len(chunk)
            else:
                positions.append(current_pos)
                current_pos += len(chunk)

        return self._build_chunks(chunks_text, doc_id, doc_title, positions)

    def _split_text(self, text: str, separator_index: int) -> List[str]:
        """
        递归分割文本

        Args:
            text: 待分割文本
            separator_index: 当前使用的分隔符索引

        Returns:
            分割后的文本块列表
        """
        if self._measure(text) <= self.chunk_size:
            return [text] if text.strip() else []

        if separator_index >= len(self._SEPARATORS):
            # 已经到最小粒度，按字符硬切
            return self._hard_split(text)

        separator, _ = self._SEPARATORS[separator_index]

        if not separator:
            # 空分隔符 = 按字符分割
            return self._hard_split(text)

        # 使用当前分隔符分割
        if separator in text:
            parts = text.split(separator)
            # 把分隔符加回去（除了最后一部分）
            parts_with_sep = []
            for i, p in enumerate(parts):
                if i < len(parts) - 1:
                    parts_with_sep.append(p + separator)
                elif p:
                    parts_with_sep.append(p)
        else:
            # 当前分隔符不存在，尝试下一级
            return self._split_text(text, separator_index + 1)

        # 合并小的部分，拆分大的部分
        chunks = []
        current_chunk = ""

        for part in parts_with_sep:
            part_size = self._measure(part)

            if self._measure(current_chunk) + part_size <= self.chunk_size:
                current_chunk += part
            else:
                # 当前块已满
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""

                if part_size > self.chunk_size:
                    # 部分本身太大，递归下一级分隔符
                    sub_chunks = self._split_text(part, separator_index + 1)
                    chunks.extend(sub_chunks)
                else:
                    current_chunk = part

        if current_chunk:
            chunks.append(current_chunk)

        # 合并最后几个小块
        chunks = self._merge_small_parts(chunks)

        # 添加重叠
        chunks = self._add_overlap_to_chunks(chunks)

        return chunks

    def _hard_split(self, text: str) -> List[str]:
        """硬切分（按字符）"""
        chunks = []
        pos = 0
        while pos < len(text):
            end = min(pos + self.chunk_size, len(text))
            chunk = text[pos:end]
            if chunk.strip():
                chunks.append(chunk)
            pos = end
            if pos < len(text) and self.chunk_overlap > 0:
                pos -= self.chunk_overlap
        return chunks

    def _merge_small_parts(self, chunks: List[str]) -> List[str]:
        """合并过小的部分"""
        if len(chunks) <= 1:
            return chunks

        merged = []
        for chunk in chunks:
            if merged and self._measure(merged[-1] + chunk) <= self.chunk_size:
                merged[-1] += chunk
            else:
                merged.append(chunk)

        return merged

    def _add_overlap_to_chunks(self, chunks: List[str]) -> List[str]:
        """为分块列表添加重叠"""
        if len(chunks) <= 1 or self.chunk_overlap <= 0:
            return chunks

        result = []
        for i, chunk in enumerate(chunks):
            if i > 0:
                prev = chunks[i - 1]
                overlap = prev[-self.chunk_overlap:]
                chunk = overlap + chunk
            result.append(chunk)

        return result


# ============================================================
# 工厂函数
# ============================================================

def create_chunker(strategy: str = "fixed",
                   chunk_size: int = 512,
                   chunk_overlap: int = 50,
                   min_chunk_size: int = 50,
                   by_tokens: bool = False) -> BaseChunker:
    """
    创建分块器工厂函数

    Args:
        strategy: 分块策略（fixed/semantic/structured/recursive）
        chunk_size: 分块大小
        chunk_overlap: 重叠大小
        min_chunk_size: 最小分块大小
        by_tokens: 是否按 token 计算

    Returns:
        分块器实例

    Raises:
        ValueError: 策略名称无效
    """
    strategy = strategy.lower()

    if strategy == ChunkingStrategy.FIXED.value:
        return FixedSizeChunker(chunk_size, chunk_overlap, min_chunk_size, by_tokens)
    elif strategy == ChunkingStrategy.SEMANTIC.value:
        return SemanticChunker(chunk_size, chunk_overlap, min_chunk_size, by_tokens)
    elif strategy == ChunkingStrategy.STRUCTURED.value:
        return StructuredChunker(chunk_size, chunk_overlap, min_chunk_size, by_tokens)
    elif strategy == ChunkingStrategy.RECURSIVE.value:
        return RecursiveChunker(chunk_size, chunk_overlap, min_chunk_size, by_tokens)
    else:
        raise ValueError(
            f"未知分块策略: {strategy}。"
            f"支持的策略: {[s.value for s in ChunkingStrategy]}"
        )
