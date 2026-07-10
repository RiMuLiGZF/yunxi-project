"""
测试：VectorMemory 向量语义记忆
"""

import pytest
import sys

sys.path.insert(0, "/workspace/agent_cluster")

from vector_memory import VectorMemory, SimpleEmbedder


@pytest.fixture
def vm():
    return VectorMemory(dimension=64, embedder=SimpleEmbedder(dimension=64))


@pytest.mark.asyncio
async def test_add_and_get(vm):
    entry = await vm.add("用户喜欢喝咖啡", memory_type="preference", importance=0.9)
    assert entry.entry_id.startswith("vec_")
    assert entry.content == "用户喜欢喝咖啡"

    fetched = vm.get(entry.entry_id)
    assert fetched is not None
    assert fetched.content == "用户喜欢喝咖啡"


@pytest.mark.asyncio
async def test_search_similar(vm):
    await vm.add("用户喜欢喝咖啡", memory_type="preference")
    await vm.add("用户喜欢喝茶", memory_type="preference")
    await vm.add("明天要下雨", memory_type="fact")

    results = await vm.search("他喜欢咖啡", top_k=3, threshold=0.0)
    assert len(results) > 0
    # 最相似的前几个应该包含咖啡相关
    top_contents = [r[0].content for r in results[:2]]
    assert "咖啡" in top_contents[0] or "咖啡" in top_contents[1]


@pytest.mark.asyncio
async def test_search_with_threshold(vm):
    await vm.add("用户喜欢喝咖啡")
    await vm.add("完全无关的内容 XYZ123")

    # threshold=0 返回所有结果，按相似度排序
    results = await vm.search("用户喜欢喝咖啡", top_k=5, threshold=0.0)
    assert len(results) == 2
    # 第一条应该是完全匹配的
    assert results[0][0].content == "用户喜欢喝咖啡"


@pytest.mark.asyncio
async def test_search_memory_type_filter(vm):
    await vm.add("用户喜欢喝咖啡", memory_type="preference")
    await vm.add("明天要下雨", memory_type="fact")

    results = await vm.search("咖啡", memory_type="preference")
    assert len(results) == 1
    assert results[0][0].memory_type == "preference"


@pytest.mark.asyncio
async def test_add_many(vm):
    items = [
        {"content": "item1", "memory_type": "test"},
        {"content": "item2", "memory_type": "test"},
    ]
    entries = await vm.add_many(items)
    assert len(entries) == 2


@pytest.mark.asyncio
async def test_delete(vm):
    entry = await vm.add("要删除的内容")
    assert vm.delete(entry.entry_id) is True
    assert vm.get(entry.entry_id) is None
    assert vm.delete("nonexistent") is False


@pytest.mark.asyncio
async def test_clear(vm):
    await vm.add("内容1")
    await vm.add("内容2")
    vm.clear()
    assert len(vm.list_all()) == 0


@pytest.mark.asyncio
async def test_stats(vm):
    await vm.add("咖啡", memory_type="preference")
    await vm.add("茶", memory_type="preference")
    stats = vm.stats()
    assert stats["total_entries"] == 2
    assert stats["dimension"] == 64


@pytest.mark.asyncio
async def test_search_similar_dict(vm):
    await vm.add("用户喜欢喝咖啡")
    results = await vm.search_similar("用户喜欢喝咖啡", top_k=3, threshold=0.0)
    assert isinstance(results, list)
    assert len(results) > 0
    assert "similarity" in results[0]
    assert "content" in results[0]


def test_simple_embedder():
    embedder = SimpleEmbedder(dimension=32)
    import asyncio
    vectors = asyncio.run(embedder.embed(["hello", "world"]))
    assert len(vectors) == 2
    assert len(vectors[0]) == 32
    # 归一化后模长应为 1
    import math
    norm = math.sqrt(sum(v * v for v in vectors[0]))
    assert abs(norm - 1.0) < 0.01
