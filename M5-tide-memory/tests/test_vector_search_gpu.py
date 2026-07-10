# -*- coding: utf-8 -*-
"""M5 向量检索 GPU 加速测试

注意：需要安装 faiss-gpu 和 CUDA 才能运行 GPU 测试。
无 GPU 环境下自动跳过 GPU 相关断言，只测试 CPU fallback 功能。
"""
import sys
import os
import pytest
import numpy as np

# 确保可以导入 tide_memory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_is_gpu_available_function_exists():
    """is_gpu_available 函数存在且返回布尔值"""
    from tide_memory.recall.vector_search import is_gpu_available
    result = is_gpu_available()
    assert isinstance(result, bool)


def test_vector_search_cpu_mode():
    """CPU 模式下向量检索正常工作"""
    from tide_memory.recall.vector_search import VectorSearch

    vs = VectorSearch(config={
        "embedding_provider": "tfidf",  # 用 TF-IDF 避免依赖外部模型
        "embedding_dim": 64,
        "use_gpu": False,
    })

    # 添加 10 条测试数据
    for i in range(10):
        vs.add(f"mem_{i}", f"这是第{i}条测试记忆，内容包含关键词{i}")

    stats = vs.get_stats()
    assert stats["total_vectors"] == 10
    assert stats["index_backend"] in ("faiss", "numpy")
    assert stats["gpu_enabled"] is False
    assert stats["gpu_available"] is False

    # 搜索测试
    results = vs.search("第5条测试记忆", top_k=3)
    assert isinstance(results, list)
    assert len(results) <= 3


def test_vector_search_gpu_config_toggle():
    """GPU 配置参数正确传递，无 GPU 时自动降级"""
    from tide_memory.recall.vector_search import VectorSearch, is_gpu_available

    has_gpu = is_gpu_available()

    vs = VectorSearch(config={
        "embedding_provider": "tfidf",
        "embedding_dim": 64,
        "use_gpu": True,  # 尝试启用 GPU
        "gpu_device_id": 0,
        "gpu_memory_ratio": 0.5,
    })

    stats = vs.get_stats()
    assert stats["gpu_enabled"] is True  # 配置上启用了

    if has_gpu:
        # 有 GPU 环境时，应该实际运行在 GPU 模式
        assert stats["gpu_available"] is True
        assert stats["gpu_device_id"] == 0
        assert stats["gpu_memory_ratio"] == 0.5
    else:
        # 无 GPU 环境时，自动降级
        assert stats["gpu_available"] is False
        assert stats["gpu_device_id"] is None


def test_vector_search_add_and_search_gpu_mode():
    """GPU 模式下添加和搜索（有 GPU 时验证，无 GPU 时验证降级正常）"""
    from tide_memory.recall.vector_search import VectorSearch, is_gpu_available

    has_gpu = is_gpu_available()

    vs = VectorSearch(config={
        "embedding_provider": "tfidf",
        "embedding_dim": 128,
        "use_gpu": True,
    })

    # 批量添加
    n = 100
    for i in range(n):
        vs.add(f"id_{i}", f"document number {i} with keyword data{i % 10}")

    assert vs.get_stats()["total_vectors"] == n

    # 搜索
    results = vs.search("keyword data3 document", top_k=10)
    assert isinstance(results, list)
    assert len(results) <= 10

    # 删除
    vs.delete("id_0")
    assert vs.get_stats()["total_vectors"] == n - 1

    # 重建索引
    vs.rebuild_index()
    assert vs.get_stats()["total_vectors"] == n - 1


def test_vector_search_stats_contains_gpu_fields():
    """get_stats 返回值包含所有 GPU 相关字段"""
    from tide_memory.recall.vector_search import VectorSearch

    vs = VectorSearch(config={
        "embedding_provider": "tfidf",
        "embedding_dim": 32,
        "use_gpu": False,
    })

    stats = vs.get_stats()
    required_fields = [
        "gpu_enabled",
        "gpu_available",
        "gpu_device_id",
        "gpu_memory_ratio",
    ]
    for field in required_fields:
        assert field in stats, f"stats 缺少字段: {field}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
