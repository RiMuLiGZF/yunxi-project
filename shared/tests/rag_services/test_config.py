"""
配置模块测试

覆盖：
1. RAGConfig 默认值
2. 配置更新
3. 配置校验
4. 环境变量加载
5. 动态更新
"""

import sys
import os
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest
from shared.business.rag_services.config import (
    RAGConfig,
    ChunkingStrategyType,
    FusionMethod,
    RewriteStrategyType,
    get_rag_config,
    reset_rag_config,
)


class TestRAGConfigDefaults:
    """配置默认值测试"""

    def test_default_chunk_size(self):
        """默认分块大小"""
        config = RAGConfig()
        assert config.default_chunk_size == 512

    def test_default_chunk_overlap(self):
        """默认重叠大小"""
        config = RAGConfig()
        assert config.default_chunk_overlap == 50

    def test_default_chunking_strategy(self):
        """默认分块策略"""
        config = RAGConfig()
        assert config.chunking_strategy == "fixed"

    def test_default_retrieval_top_k(self):
        """默认检索 Top K"""
        config = RAGConfig()
        assert config.retrieval_top_k == 10

    def test_default_hybrid_search_enabled(self):
        """默认启用混合检索"""
        config = RAGConfig()
        assert config.enable_hybrid_search == True

    def test_default_hybrid_weight(self):
        """默认混合检索权重"""
        config = RAGConfig()
        assert config.hybrid_search_weight == 0.7

    def test_default_rerank_enabled(self):
        """默认启用重排序"""
        config = RAGConfig()
        assert config.enable_rerank == True

    def test_default_rerank_top_n(self):
        """默认重排序 Top N"""
        config = RAGConfig()
        assert config.rerank_top_n == 20

    def test_default_query_rewrite_disabled(self):
        """默认禁用查询改写"""
        config = RAGConfig()
        assert config.enable_query_rewrite == False

    def test_default_mmr_disabled(self):
        """默认禁用 MMR"""
        config = RAGConfig()
        assert config.enable_mmr == False

    def test_default_mmr_lambda(self):
        """默认 MMR lambda"""
        config = RAGConfig()
        assert config.mmr_lambda == 0.5

    def test_default_context_expansion_enabled(self):
        """默认启用上下文扩展"""
        config = RAGConfig()
        assert config.context_window_expansion == True

    def test_default_fusion_method(self):
        """默认融合方法"""
        config = RAGConfig()
        assert config.fusion_method == "rrf"

    def test_default_dedup_enabled(self):
        """默认启用去重"""
        config = RAGConfig()
        assert config.enable_dedup == True


class TestConfigUpdate:
    """配置更新测试"""

    def test_update_single_value(self):
        """更新单个配置项"""
        config = RAGConfig()
        old = config.default_chunk_size
        changed = config.update({"default_chunk_size": 1024})
        assert config.default_chunk_size == 1024
        assert "default_chunk_size" in changed
        assert changed["default_chunk_size"]["old"] == old
        assert changed["default_chunk_size"]["new"] == 1024

    def test_update_multiple_values(self):
        """更新多个配置项"""
        config = RAGConfig()
        changed = config.update({
            "default_chunk_size": 256,
            "default_chunk_overlap": 30,
            "retrieval_top_k": 20,
        })
        assert len(changed) == 3
        assert config.default_chunk_size == 256
        assert config.default_chunk_overlap == 30
        assert config.retrieval_top_k == 20

    def test_update_no_change(self):
        """更新相同的值（无变化）"""
        config = RAGConfig()
        changed = config.update({"default_chunk_size": 512})
        assert len(changed) == 0

    def test_update_unknown_key(self):
        """更新未知配置项"""
        config = RAGConfig()
        with pytest.raises(ValueError):
            config.update({"unknown_key": "value"})

    def test_update_invalid_chunk_size(self):
        """无效的分块大小"""
        config = RAGConfig()
        with pytest.raises(ValueError):
            config.update({"default_chunk_size": 0})

    def test_update_invalid_weight(self):
        """无效的权重值（超出 0-1）"""
        config = RAGConfig()
        with pytest.raises(ValueError):
            config.update({"hybrid_search_weight": 1.5})
        with pytest.raises(ValueError):
            config.update({"mmr_lambda": -0.1})

    def test_update_invalid_strategy(self):
        """无效的分块策略"""
        config = RAGConfig()
        with pytest.raises(ValueError):
            config.update({"chunking_strategy": "invalid_strategy"})

    def test_update_invalid_fusion_method(self):
        """无效的融合方法"""
        config = RAGConfig()
        with pytest.raises(ValueError):
            config.update({"fusion_method": "invalid"})

    def test_update_boolean_value(self):
        """更新布尔值"""
        config = RAGConfig()
        changed = config.update({"enable_query_rewrite": True})
        assert config.enable_query_rewrite == True
        assert "enable_query_rewrite" in changed

    def test_update_type_conversion(self):
        """类型转换"""
        config = RAGConfig()
        changed = config.update({"default_chunk_size": "1024"})
        assert config.default_chunk_size == 1024
        assert isinstance(config.default_chunk_size, int)


class TestConfigToDict:
    """配置序列化测试"""

    def test_to_dict_returns_dict(self):
        """to_dict 返回字典"""
        config = RAGConfig()
        d = config.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_excludes_internal(self):
        """to_dict 排除内部字段"""
        config = RAGConfig()
        d = config.to_dict()
        assert "_lock" not in d

    def test_to_dict_contains_key_fields(self):
        """to_dict 包含关键字段"""
        config = RAGConfig()
        d = config.to_dict()
        assert "default_chunk_size" in d
        assert "chunking_strategy" in d
        assert "retrieval_top_k" in d
        assert "enable_hybrid_search" in d


class TestConfigGet:
    """配置获取测试"""

    def test_get_existing_key(self):
        """获取存在的配置项"""
        config = RAGConfig()
        assert config.get("default_chunk_size") == 512

    def test_get_missing_key(self):
        """获取不存在的配置项"""
        config = RAGConfig()
        assert config.get("nonexistent", "default") == "default"

    def test_get_default_value(self):
        """获取配置项的默认值"""
        config = RAGConfig()
        assert config.get("nonexistent") is None


class TestConfigSingleton:
    """配置单例测试"""

    def setup_method(self):
        """每个测试前重置单例"""
        reset_rag_config()

    def test_get_config_returns_same_instance(self):
        """get_rag_config 返回相同实例"""
        config1 = get_rag_config()
        config2 = get_rag_config()
        assert config1 is config2

    def test_reset_config(self):
        """重置配置单例"""
        config1 = get_rag_config()
        reset_rag_config()
        config2 = get_rag_config()
        assert config1 is not config2


class TestEnvVarLoading:
    """环境变量加载测试"""

    def setup_method(self):
        """每个测试前清理环境变量和单例"""
        reset_rag_config()
        # 清理 RAG_ 开头的环境变量
        for key in list(os.environ.keys()):
            if key.startswith("RAG_"):
                del os.environ[key]

    def teardown_method(self):
        """测试后清理"""
        reset_rag_config()
        for key in list(os.environ.keys()):
            if key.startswith("RAG_"):
                del os.environ[key]

    def test_env_chunk_size(self):
        """环境变量设置分块大小"""
        os.environ["RAG_CHUNK_SIZE"] = "256"
        reset_rag_config()
        config = get_rag_config()
        assert config.default_chunk_size == 256

    def test_env_enable_hybrid(self):
        """环境变量设置混合检索开关"""
        os.environ["RAG_ENABLE_HYBRID"] = "false"
        reset_rag_config()
        config = get_rag_config()
        assert config.enable_hybrid_search == False

    def test_env_hybrid_weight(self):
        """环境变量设置混合权重"""
        os.environ["RAG_HYBRID_WEIGHT"] = "0.8"
        reset_rag_config()
        config = get_rag_config()
        assert config.hybrid_search_weight == 0.8

    def test_env_invalid_value_ignored(self):
        """无效环境变量值被忽略"""
        os.environ["RAG_CHUNK_SIZE"] = "not_a_number"
        reset_rag_config()
        config = get_rag_config()
        # 无效值应使用默认值
        assert config.default_chunk_size == 512


class TestChunkingStrategyType:
    """分块策略枚举测试"""

    def test_all_strategies_exist(self):
        """所有策略都存在"""
        assert ChunkingStrategyType.FIXED.value == "fixed"
        assert ChunkingStrategyType.SEMANTIC.value == "semantic"
        assert ChunkingStrategyType.STRUCTURED.value == "structured"
        assert ChunkingStrategyType.RECURSIVE.value == "recursive"

    def test_strategy_count(self):
        """策略数量为 4"""
        assert len(ChunkingStrategyType) == 4


class TestFusionMethod:
    """融合方法枚举测试"""

    def test_all_methods_exist(self):
        """所有融合方法都存在"""
        assert FusionMethod.WEIGHTED.value == "weighted"
        assert FusionMethod.RRF.value == "rrf"

    def test_method_count(self):
        """融合方法数量为 2"""
        assert len(FusionMethod) == 2


class TestRewriteStrategyType:
    """改写策略枚举测试"""

    def test_all_strategies_exist(self):
        """所有改写策略都存在"""
        assert RewriteStrategyType.EXPANSION.value == "expansion"
        assert RewriteStrategyType.DECOMPOSITION.value == "decomposition"
        assert RewriteStrategyType.CONVERSATIONAL.value == "conversational"
        assert RewriteStrategyType.HYDE.value == "hyde"

    def test_strategy_count(self):
        """改写策略数量为 4"""
        assert len(RewriteStrategyType) == 4
