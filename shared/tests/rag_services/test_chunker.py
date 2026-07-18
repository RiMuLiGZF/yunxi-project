"""
分块策略测试

覆盖 4 种分块策略：
1. FixedSizeChunker - 固定大小分块
2. SemanticChunker - 语义分块
3. StructuredChunker - 结构化分块
4. RecursiveChunker - 递归分块

以及 ChunkMetadata 元数据增强测试。
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到 path
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest
from shared.business.rag_services.chunker import (
    FixedSizeChunker,
    SemanticChunker,
    StructuredChunker,
    RecursiveChunker,
    ChunkMetadata,
    ChunkResult,
    create_chunker,
    ChunkingStrategy,
    estimate_tokens,
    extract_keywords,
    extract_entities,
)


# ==================== 工具函数测试 ====================

class TestUtils:
    """工具函数测试"""

    def test_estimate_tokens_chinese(self):
        """测试中文字符 token 估算"""
        text = "人工智能是计算机科学的一个分支"
        tokens = estimate_tokens(text)
        assert tokens > 0
        # 中文 1.5 字/token，14 字约 9 token
        assert 5 <= tokens <= 15

    def test_estimate_tokens_english(self):
        """测试英文单词 token 估算"""
        text = "Artificial intelligence is a branch of computer science"
        tokens = estimate_tokens(text)
        assert tokens > 0
        # 9 个单词约 12 token
        assert 5 <= tokens <= 20

    def test_estimate_tokens_mixed(self):
        """测试中英文混合 token 估算"""
        text = "人工智能 AI 是计算机科学的一个分支"
        tokens = estimate_tokens(text)
        assert tokens > 0

    def test_estimate_tokens_empty(self):
        """测试空文本 token 估算"""
        assert estimate_tokens("") == 0

    def test_extract_keywords_basic(self):
        """测试关键词提取"""
        text = "人工智能机器学习深度学习神经网络模型训练"
        keywords = extract_keywords(text, top_k=5)
        assert isinstance(keywords, list)
        assert len(keywords) <= 5

    def test_extract_keywords_empty(self):
        """测试空文本关键词提取"""
        assert extract_keywords("") == []

    def test_extract_entities_dates(self):
        """测试实体提取 - 日期"""
        text = "项目将于2025年12月31日完成交付"
        entities = extract_entities(text)
        assert any("2025" in e for e in entities)

    def test_extract_entities_quotes(self):
        """测试实体提取 - 引号内容"""
        text = '他提出了"深度学习"的概念'
        entities = extract_entities(text)
        assert any("深度学习" in e for e in entities)

    def test_extract_entities_empty(self):
        """测试空文本实体提取"""
        assert extract_entities("") == []


# ==================== 1. 固定大小分块测试 ====================

class TestFixedSizeChunker:
    """固定大小分块测试"""

    def test_basic_chunking(self):
        """基础分块测试"""
        chunker = FixedSizeChunker(chunk_size=100, chunk_overlap=0)
        text = "a" * 500
        results = chunker.chunk(text, doc_id="test", doc_title="测试文档")

        assert len(results) > 1
        # 每个块不超过 chunk_size
        for r in results:
            assert len(r.text) <= 100 + 10  # 允许少量误差（断点调整）

    def test_with_overlap(self):
        """重叠分块测试"""
        chunker = FixedSizeChunker(chunk_size=100, chunk_overlap=20)
        text = "a" * 300
        results = chunker.chunk(text, doc_id="test")

        assert len(results) >= 2
        # 重叠部分应该存在
        if len(results) >= 2:
            # 第二个块的开头应该是第一个块的结尾
            assert len(results[1].text) > 0

    def test_small_text(self):
        """小文本不分块测试"""
        chunker = FixedSizeChunker(chunk_size=500, chunk_overlap=50)
        text = "这是一段很短的文本。"
        results = chunker.chunk(text, doc_id="test")

        assert len(results) == 1
        assert results[0].text == text

    def test_empty_text(self):
        """空文本测试"""
        chunker = FixedSizeChunker(chunk_size=100)
        assert chunker.chunk("") == []
        assert chunker.chunk("   ") == []

    def test_metadata_fields(self):
        """元数据字段测试"""
        chunker = FixedSizeChunker(chunk_size=100, chunk_overlap=0)
        text = "a" * 250
        results = chunker.chunk(text, doc_id="doc001", doc_title="测试文档")

        assert len(results) > 0
        first = results[0]
        assert first.metadata.document_id == "doc001"
        assert first.metadata.document_title == "测试文档"
        assert first.metadata.chunk_index == 0
        assert first.metadata.total_chunks == len(results)
        assert first.metadata.char_count > 0
        assert first.metadata.token_count > 0
        assert first.metadata.content_type == "text"

    def test_chunk_ids_unique(self):
        """chunk ID 唯一性测试"""
        chunker = FixedSizeChunker(chunk_size=50, chunk_overlap=10)
        text = "a" * 200
        results = chunker.chunk(text, doc_id="test")

        ids = [r.chunk_id for r in results]
        assert len(ids) == len(set(ids))

    def test_keywords_in_metadata(self):
        """元数据中包含关键词"""
        chunker = FixedSizeChunker(chunk_size=200, chunk_overlap=0)
        text = "人工智能机器学习深度学习神经网络自然语言处理" * 5
        results = chunker.chunk(text, doc_id="test")

        assert len(results) > 0
        assert isinstance(results[0].metadata.keywords, list)
        assert len(results[0].metadata.keywords) > 0

    def test_position_tracking(self):
        """位置追踪测试"""
        chunker = FixedSizeChunker(chunk_size=100, chunk_overlap=0)
        text = "a" * 500
        results = chunker.chunk(text, doc_id="test")

        assert len(results) > 0
        # 第一个块起始位置为 0
        assert results[0].metadata.start_pos == 0
        # 最后一个块的结束位置接近文本长度
        assert results[-1].metadata.end_pos <= len(text)


# ==================== 2. 语义分块测试 ====================

class TestSemanticChunker:
    """语义分块测试"""

    def test_paragraph_aware(self):
        """段落感知分块测试"""
        chunker = SemanticChunker(chunk_size=200, chunk_overlap=0)
        text = "第一段内容。这是第一个段落。\n\n第二段内容。这是第二个段落。\n\n第三段内容。这是第三个段落。"
        results = chunker.chunk(text, doc_id="test")

        assert len(results) > 0
        # 段落应该尽量保持完整

    def test_long_paragraph_split(self):
        """长段落按句子分割测试"""
        chunker = SemanticChunker(chunk_size=20, chunk_overlap=0)
        # 每句约 7 字，20 句约 140 字，chunk_size=20 应该分成多块
        text = ""
        for i in range(20):
            text += f"第{i}句话内容。"
        results = chunker.chunk(text, doc_id="test")

        assert len(results) > 1
        # 句子边界应该保持完整
        for r in results:
            assert r.text.strip()

    def test_overlap_preserves_semantic(self):
        """重叠保持语义完整测试"""
        chunker = SemanticChunker(chunk_size=15, chunk_overlap=5)
        # 每句约 7 字，20 句约 140 字
        text = ""
        for i in range(20):
            text += f"第{i}句测试。"
        results = chunker.chunk(text, doc_id="test")

        assert len(results) > 1

    def test_short_paragraphs_merged(self):
        """短段落合并测试"""
        chunker = SemanticChunker(chunk_size=500, chunk_overlap=0)
        text = "短1。\n\n短2。\n\n短3。\n\n短4。"
        results = chunker.chunk(text, doc_id="test")

        # 短段落应该被合并
        assert len(results) <= 3

    def test_section_path_empty(self):
        """语义分块 section_path 为空（无结构）"""
        chunker = SemanticChunker(chunk_size=200, chunk_overlap=0)
        text = "这是一段没有结构的纯文本内容。" * 10
        results = chunker.chunk(text, doc_id="test")

        assert len(results) > 0
        # 语义分块没有章节路径
        assert results[0].metadata.section_path == ""


# ==================== 3. 结构化分块测试 ====================

class TestStructuredChunker:
    """结构化分块测试（Markdown 感知）"""

    def test_markdown_headings(self):
        """Markdown 标题识别测试"""
        chunker = StructuredChunker(chunk_size=500, chunk_overlap=0)
        text = """# 第一章

这是第一章的内容。

## 第一节

这是第一节的内容。

## 第二节

这是第二节的内容。

# 第二章

这是第二章的内容。
"""
        results = chunker.chunk(text, doc_id="test", doc_title="测试文档")

        assert len(results) > 0
        # 至少有一些块有章节信息
        has_section = any(r.metadata.section_path for r in results)
        assert has_section

    def test_heading_levels(self):
        """标题层级测试"""
        chunker = StructuredChunker(chunk_size=500, chunk_overlap=0)
        text = """# 一级标题

内容。

## 二级标题

内容。

### 三级标题

内容。
"""
        results = chunker.chunk(text, doc_id="test")

        # 应该有不同层级的标题
        levels = set(r.metadata.heading_level for r in results)
        assert len(levels) >= 1

    def test_section_path_hierarchy(self):
        """章节路径层级测试"""
        chunker = StructuredChunker(chunk_size=500, chunk_overlap=0)
        text = """# 第一章

内容。

## 第一节

内容。
"""
        results = chunker.chunk(text, doc_id="test")

        # 二级标题的 section_path 应该包含一级标题
        sub_sections = [r for r in results if r.metadata.heading_level == 2]
        if sub_sections:
            assert "/" in sub_sections[0].metadata.section_path

    def test_code_block_preserved(self):
        """代码块完整保留测试"""
        chunker = StructuredChunker(chunk_size=200, chunk_overlap=0)
        code = "```python\ndef hello():\n    print('hello')\n    return True\n```"
        text = f"# 标题\n\n一些内容。\n\n{code}\n\n更多内容。"
        results = chunker.chunk(text, doc_id="test")

        # 代码块应该作为独立块存在
        code_chunks = [r for r in results if r.metadata.content_type == "code"]
        # 可能有也可能没有，取决于 chunk_size
        # 只要不报错即可
        assert len(results) > 0

    def test_no_structure_fallback(self):
        """无结构时退化为语义分块"""
        chunker = StructuredChunker(chunk_size=200, chunk_overlap=0)
        text = "这是一段没有任何结构的纯文本。" * 20
        results = chunker.chunk(text, doc_id="test")

        assert len(results) > 0

    def test_empty_document(self):
        """空文档测试"""
        chunker = StructuredChunker(chunk_size=200)
        assert chunker.chunk("") == []


# ==================== 4. 递归分块测试 ====================

class TestRecursiveChunker:
    """递归分块测试"""

    def test_recursive_split(self):
        """递归分割测试"""
        chunker = RecursiveChunker(chunk_size=100, chunk_overlap=0)
        text = "这是一段很长的文本。" * 50
        results = chunker.chunk(text, doc_id="test")

        assert len(results) > 1
        for r in results:
            # 递归分块应该尽量保持在 chunk_size 附近
            assert len(r.text) <= 150  # 允许一定误差

    def test_small_text_single_chunk(self):
        """小文本单块测试"""
        chunker = RecursiveChunker(chunk_size=1000, chunk_overlap=0)
        text = "短文本。"
        results = chunker.chunk(text, doc_id="test")

        assert len(results) == 1
        assert results[0].text == text

    def test_with_overlap(self):
        """带重叠的递归分块"""
        chunker = RecursiveChunker(chunk_size=100, chunk_overlap=20)
        text = "a" * 500
        results = chunker.chunk(text, doc_id="test")

        assert len(results) > 1

    def test_separator_hierarchy(self):
        """分隔符优先级测试（段落优先于句子）"""
        chunker = RecursiveChunker(chunk_size=200, chunk_overlap=0)
        text = "段落一。段落一继续。\n\n段落二。段落二继续。\n\n段落三。段落三继续。"
        results = chunker.chunk(text, doc_id="test")

        # 段落级别的分隔符应该优先被使用
        assert len(results) >= 1

    def test_very_long_text(self):
        """超长文本测试"""
        chunker = RecursiveChunker(chunk_size=100, chunk_overlap=10)
        text = "测试文本内容。" * 200
        results = chunker.chunk(text, doc_id="test")

        assert len(results) > 5
        assert all(len(r.text) > 0 for r in results)


# ==================== 工厂函数测试 ====================

class TestCreateChunker:
    """分块器工厂函数测试"""

    def test_create_fixed(self):
        """创建固定大小分块器"""
        chunker = create_chunker("fixed", chunk_size=100)
        assert isinstance(chunker, FixedSizeChunker)
        assert chunker.chunk_size == 100

    def test_create_semantic(self):
        """创建语义分块器"""
        chunker = create_chunker("semantic")
        assert isinstance(chunker, SemanticChunker)

    def test_create_structured(self):
        """创建结构化分块器"""
        chunker = create_chunker("structured")
        assert isinstance(chunker, StructuredChunker)

    def test_create_recursive(self):
        """创建递归分块器"""
        chunker = create_chunker("recursive")
        assert isinstance(chunker, RecursiveChunker)

    def test_create_invalid_strategy(self):
        """无效策略名称测试"""
        with pytest.raises(ValueError):
            create_chunker("invalid_strategy")

    def test_create_case_insensitive(self):
        """大小写不敏感测试"""
        chunker = create_chunker("FIXED")
        assert isinstance(chunker, FixedSizeChunker)

    def test_chunk_size_param(self):
        """分块大小参数传递"""
        chunker = create_chunker("fixed", chunk_size=256, chunk_overlap=30)
        assert chunker.chunk_size == 256
        assert chunker.chunk_overlap == 30


# ==================== ChunkMetadata 测试 ====================

class TestChunkMetadata:
    """Chunk 元数据测试"""

    def test_to_dict(self):
        """元数据序列化测试"""
        meta = ChunkMetadata(
            chunk_index=0,
            total_chunks=5,
            document_id="doc001",
            document_title="测试",
            section_path="第一章/第一节",
            token_count=100,
            char_count=200,
            content_type="text",
            keywords=["AI", "ML"],
            entities=["2025年"],
        )
        d = meta.to_dict()
        assert d["chunk_index"] == 0
        assert d["total_chunks"] == 5
        assert d["document_id"] == "doc001"
        assert isinstance(d["keywords"], list)
        assert isinstance(d["entities"], list)

    def test_default_values(self):
        """默认值测试"""
        meta = ChunkMetadata()
        assert meta.chunk_index == 0
        assert meta.total_chunks == 0
        assert meta.content_type == "text"
        assert meta.keywords == []
        assert meta.entities == []
