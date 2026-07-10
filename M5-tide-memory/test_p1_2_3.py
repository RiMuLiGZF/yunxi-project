"""
P1-2 & P1-3 功能验证脚本

测试内容：
1. VectorSearch 三种后端的降级（tfidf 模式必过）
2. 向量搜索的基本功能（增删查、批量、持久化）
3. L3 AbyssLayer 的加密存储和解密
4. 索引持久化和加载
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from tide_memory.recall.vector_search import VectorSearch
from tide_memory.recall.recall_engine import RecallEngine
from tide_memory.layers.l3_abyss import AbyssLayer
from tide_memory.core.models import (
    MemoryItem,
    MemoryLayer,
    MemoryDomain,
    EmotionState,
    ClassificationLevel,
)


def print_header(title: str) -> None:
    """打印测试标题"""
    line = "=" * 60
    print(f"\n{line}")
    print(f"  {title}")
    print(line)


def print_subheader(title: str) -> None:
    """打印子标题"""
    print(f"\n--- {title} ---")


# ============================================================
# 测试 1: VectorSearch 三种后端降级
# ============================================================

def test_vector_search_backends():
    """测试 VectorSearch 三种后端的降级"""
    print_header("测试 1: VectorSearch 三种后端降级")

    # 临时目录
    tmpdir = tempfile.mkdtemp(prefix="vec_test_")
    index_path = os.path.join(tmpdir, "test.index")

    try:
        # 测试 tfidf 模式（必过）
        print_subheader("1.1 TF-IDF 模式（兜底方案）")
        vs_tfidf = VectorSearch({
            "embedding_provider": "tfidf",
            "embedding_dim": 128,
            "index_path": index_path,
            "similarity_threshold": 0.1,
        })
        stats = vs_tfidf.get_stats()
        print(f"  Embedding 后端: {stats['embed_backend']}")
        print(f"  索引后端: {stats['index_backend']}")
        print(f"  向量维度: {stats['embedding_dim']}")
        assert stats["embed_backend"] == "tfidf", f"期望 tfidf，实际 {stats['embed_backend']}"
        print("  ✅ TF-IDF 模式初始化成功")

        # 测试 auto 模式（会自动降级到 tfidf，如果没有 sentence-transformers 和 ollama）
        print_subheader("1.2 Auto 模式（自动降级）")
        vs_auto = VectorSearch({
            "embedding_provider": "auto",
            "embedding_dim": 128,
            "index_path": index_path + "_auto",
            "similarity_threshold": 0.1,
        })
        stats = vs_auto.get_stats()
        print(f"  自动选择的后端: {stats['embed_backend']}")
        print(f"  索引后端: {stats['index_backend']}")
        print("  ✅ Auto 模式初始化成功")

        # 测试指定 ollama 模式（不可用时降级到 tfidf）
        print_subheader("1.3 指定 Ollama 模式（不可用时降级）")
        vs_ollama = VectorSearch({
            "embedding_provider": "ollama",
            "embedding_model": "nomic-embed-text",
            "embedding_dim": 128,
            "index_path": index_path + "_ollama",
            "similarity_threshold": 0.1,
        })
        stats = vs_ollama.get_stats()
        print(f"  实际使用后端: {stats['embed_backend']}")
        print("  ✅ Ollama 模式（含降级）初始化成功")

        # 测试指定 sentence_transformers 模式（不可用时降级）
        print_subheader("1.4 指定 sentence-transformers 模式（不可用时降级）")
        vs_st = VectorSearch({
            "embedding_provider": "sentence_transformers",
            "embedding_model": "all-MiniLM-L6-v2",
            "embedding_dim": 128,
            "index_path": index_path + "_st",
            "similarity_threshold": 0.1,
        })
        stats = vs_st.get_stats()
        print(f"  实际使用后端: {stats['embed_backend']}")
        print("  ✅ Sentence-Transformers 模式（含降级）初始化成功")

        print("\n✅ 测试 1 通过：三种后端降级均正常")
        return True

    except Exception as e:
        logger.error(f"测试 1 失败: {e}", exc_info=True)
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# 测试 2: 向量搜索基本功能
# ============================================================

def test_vector_search_basic():
    """测试向量搜索的基本功能"""
    print_header("测试 2: 向量搜索基本功能")

    tmpdir = tempfile.mkdtemp(prefix="vec_basic_")
    index_path = os.path.join(tmpdir, "test.index")

    try:
        vs = VectorSearch({
            "embedding_provider": "tfidf",
            "embedding_dim": 128,
            "index_path": index_path,
            "similarity_threshold": 0.0,  # 调低阈值便于测试
        })

        # 2.1 添加向量
        print_subheader("2.1 添加向量")
        test_docs = [
            ("mem_001", "人工智能和机器学习的发展历程", {"tag": "AI", "domain": "tech"}),
            ("mem_002", "深度学习神经网络模型训练方法", {"tag": "AI", "domain": "tech"}),
            ("mem_003", "Python编程语言基础教程入门", {"tag": "programming", "domain": "tech"}),
            ("mem_004", "健康饮食和营养搭配建议", {"tag": "health", "domain": "life"}),
            ("mem_005", "运动健身计划制定与执行", {"tag": "health", "domain": "life"}),
            ("mem_006", "金融投资理财策略分析", {"tag": "finance", "domain": "work"}),
        ]

        for mid, text, meta in test_docs:
            result = vs.add(mid, text, meta)
            assert result, f"添加失败: {mid}"

        stats = vs.get_stats()
        print(f"  添加后向量数量: {stats['total_vectors']}")
        assert stats["total_vectors"] == 6
        print("  ✅ 6 条向量添加成功")

        # 2.2 搜索测试
        print_subheader("2.2 向量搜索")
        results = vs.search("人工智能深度学习", top_k=3)
        print(f"  查询: '人工智能深度学习'")
        for r in results:
            print(f"    - {r['memory_id']}: score={r['score']}")
        assert len(results) > 0, "搜索结果为空"
        assert results[0]["memory_id"] in ("mem_001", "mem_002"), f"最相关的应该是AI相关，实际是{results[0]['memory_id']}"
        print("  ✅ 语义搜索返回相关结果")

        # 2.3 搜索过滤
        print_subheader("2.3 搜索 + 元数据过滤")
        results = vs.search("健康", top_k=5, filters={"domain": "life"})
        print(f"  查询: '健康' + 过滤 domain=life")
        for r in results:
            print(f"    - {r['memory_id']}: score={r['score']}, domain={r['metadata'].get('domain')}")
        for r in results:
            assert r["metadata"].get("domain") == "life", f"过滤失败: {r['memory_id']}"
        print("  ✅ 元数据过滤正常工作")

        # 2.4 删除向量
        print_subheader("2.4 删除向量")
        delete_result = vs.delete("mem_006")
        assert delete_result, "删除失败"
        stats = vs.get_stats()
        print(f"  删除后向量数量: {stats['total_vectors']}")
        assert stats["total_vectors"] == 5

        # 确认已删除
        results = vs.search("金融投资", top_k=5)
        found = any(r["memory_id"] == "mem_006" for r in results)
        assert not found, "已删除的记忆不应再出现"
        print("  ✅ 删除功能正常")

        # 2.5 批量添加
        print_subheader("2.5 批量添加")
        batch_items = [
            {"memory_id": "mem_007", "text": "量子计算的原理和应用前景", "metadata": {"tag": "quantum"}},
            {"memory_id": "mem_008", "text": "区块链技术去中心化应用", "metadata": {"tag": "blockchain"}},
        ]
        count = vs.batch_add(batch_items)
        assert count == 2, f"批量添加失败，期望2，实际{count}"
        stats = vs.get_stats()
        assert stats["total_vectors"] == 7
        print(f"  批量添加 {count} 条，总数: {stats['total_vectors']}")
        print("  ✅ 批量添加功能正常")

        # 2.6 重复添加（覆盖）
        print_subheader("2.6 重复添加（覆盖更新）")
        result = vs.add("mem_001", "人工智能机器学习深度学习神经网络", {"tag": "AI", "updated": True})
        assert result
        stats = vs.get_stats()
        assert stats["total_vectors"] == 7, f"重复添加不应增加数量，实际{stats['total_vectors']}"
        print("  ✅ 重复添加（覆盖）功能正常")

        print("\n✅ 测试 2 通过：向量搜索基本功能全部正常")
        return True

    except Exception as e:
        logger.error(f"测试 2 失败: {e}", exc_info=True)
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# 测试 3: 索引持久化和加载
# ============================================================

def test_vector_persistence():
    """测试向量索引的持久化和加载"""
    print_header("测试 3: 索引持久化和加载")

    tmpdir = tempfile.mkdtemp(prefix="vec_persist_")
    index_path = os.path.join(tmpdir, "persist.index")

    try:
        # 3.1 创建并填充索引
        print_subheader("3.1 创建并填充索引")
        vs1 = VectorSearch({
            "embedding_provider": "tfidf",
            "embedding_dim": 128,
            "index_path": index_path,
            "similarity_threshold": 0.0,
        })

        test_docs = [
            ("mem_001", "今天天气真好适合出去散步", {"mood": "happy"}),
            ("mem_002", "工作任务太多压力很大", {"mood": "stressed"}),
            ("mem_003", "周末和朋友一起看电影", {"mood": "happy"}),
        ]

        for mid, text, meta in test_docs:
            vs1.add(mid, text, meta)

        vs1.flush()  # 手动持久化
        stats1 = vs1.get_stats()
        print(f"  保存前向量数: {stats1['total_vectors']}")

        # 检查文件是否存在
        meta_file = index_path + ".meta.pkl"
        vec_file = index_path + ".vectors.npy"
        assert os.path.exists(meta_file), f"元数据文件不存在: {meta_file}"
        assert os.path.exists(vec_file), f"向量文件不存在: {vec_file}"
        print(f"  元数据文件: {os.path.getsize(meta_file)} bytes")
        print(f"  向量文件: {os.path.getsize(vec_file)} bytes")
        print("  ✅ 索引持久化到磁盘成功")

        # 3.2 加载索引
        print_subheader("3.2 加载索引")
        vs2 = VectorSearch({
            "embedding_provider": "tfidf",
            "embedding_dim": 128,
            "index_path": index_path,
            "similarity_threshold": 0.0,
        })

        stats2 = vs2.get_stats()
        print(f"  加载后向量数: {stats2['total_vectors']}")
        assert stats2["total_vectors"] == 3, f"加载后数量不对，期望3，实际{stats2['total_vectors']}"

        # 验证搜索功能正常
        results = vs2.search("天气散步", top_k=3)
        assert len(results) > 0, "加载后搜索失败"
        print(f"  加载后搜索返回 {len(results)} 条结果")
        print("  ✅ 索引加载和搜索正常")

        # 3.3 重建索引
        print_subheader("3.3 重建索引")
        vs2.rebuild_index()
        stats3 = vs2.get_stats()
        assert stats3["total_vectors"] == 3
        print("  ✅ 索引重建成功")

        print("\n✅ 测试 3 通过：索引持久化和加载功能正常")
        return True

    except Exception as e:
        logger.error(f"测试 3 失败: {e}", exc_info=True)
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# 测试 4: L3 AbyssLayer 加密存储
# ============================================================

def test_abyss_layer():
    """测试 L3 AbyssLayer 的加密存储和解密"""
    print_header("测试 4: L3 AbyssLayer 加密存储")

    tmpdir = tempfile.mkdtemp(prefix="abyss_test_")
    storage_path = os.path.join(tmpdir, "l3_abyss")

    try:
        # 4.1 初始化
        print_subheader("4.1 初始化 AbyssLayer")
        abyss = AbyssLayer({
            "storage_path": storage_path,
        })

        stats = abyss.get_stats()
        print(f"  加密后端: {stats['encryption_backend']}")
        print(f"  主密钥加密: {stats['master_key_encrypted']}")
        print(f"  存储路径: {stats['storage_path']}")
        print("  ✅ AbyssLayer 初始化成功")

        # 4.2 添加记忆
        print_subheader("4.2 添加加密记忆")
        items = []
        for i in range(5):
            item = MemoryItem(
                memory_id=f"mem_test_{i:03d}",
                content_hash=f"hash_{i:03d}_content",
                layer=MemoryLayer.L3_ABYSS,
                domain=MemoryDomain.PRIVATE,
                owner_agent="test_agent",
                tags=[f"tag_{i % 3}", "important"],
                quality_score=60.0 + i * 5,
                emotion=EmotionState(
                    valence=0.5,
                    arousal=0.3,
                    ei_score=0.7,
                    dominant_emotion="happy" if i % 2 == 0 else "sad",
                ),
                classification=ClassificationLevel.TOP_SECRET,
                metadata={"source": "test", "index": i},
            )
            items.append(item)
            result = abyss.add(item)
            assert result, f"添加失败: {item.memory_id}"

        count = abyss.count()
        assert count == 5, f"数量不对，期望5，实际{count}"
        print(f"  添加 {count} 条加密记忆")

        # 检查 vault 目录
        vault_path = os.path.join(storage_path, "vault")
        files = os.listdir(vault_path)
        print(f"  加密文件数量: {len(files)}")
        assert len(files) == 5, "加密文件数量不对"

        # 检查文件大小
        total_size = sum(os.path.getsize(os.path.join(vault_path, f)) for f in files)
        print(f"  加密文件总大小: {total_size} bytes")
        print("  ✅ 加密存储成功")

        # 4.3 获取和解密
        print_subheader("4.3 获取解密记忆")
        for item in items:
            retrieved = abyss.get(item.memory_id)
            assert retrieved is not None, f"获取失败: {item.memory_id}"
            assert retrieved.memory_id == item.memory_id
            assert retrieved.content_hash == item.content_hash
            assert retrieved.domain == item.domain
            assert retrieved.tags == item.tags
            assert retrieved.quality_score == item.quality_score
            assert retrieved.emotion.dominant_emotion == item.emotion.dominant_emotion
            assert retrieved.classification == item.classification
            assert retrieved.metadata.get("index") == item.metadata.get("index")

        print(f"  成功解密 {len(items)} 条记忆")
        print("  ✅ 加密/解密功能正常")

        # 4.4 搜索（只搜元数据）
        print_subheader("4.4 元数据搜索（不解密内容）")
        results = abyss.search("tag_1", domain="private", top_k=5)
        print(f"  搜索 tag_1，返回 {len(results)} 条结果")
        for r in results:
            assert r["encrypted"] is True
            assert r["content_preview"] == "[ENCRYPTED]"
            print(f"    - {r['memory_id']}: {r['domain']}, quality={r['quality_score']}")
        print("  ✅ 元数据搜索功能正常")

        # 4.5 删除
        print_subheader("4.5 删除记忆")
        delete_id = "mem_test_004"
        result = abyss.remove(delete_id)
        assert result, "删除失败"

        count_after = abyss.count()
        assert count_after == 4, f"删除后数量不对，期望4，实际{count_after}"

        # 确认获取不到
        retrieved = abyss.get(delete_id)
        assert retrieved is None, "已删除的记忆不应再能获取"

        # 确认文件已删除
        vault_files = os.listdir(vault_path)
        assert len(vault_files) == 4, f"加密文件未删除，期望4，实际{len(vault_files)}"
        print("  ✅ 删除功能正常")

        # 4.6 遍历所有记忆
        print_subheader("4.6 遍历所有记忆")
        all_items = abyss.items()
        assert len(all_items) == 4, f"遍历数量不对，期望4，实际{len(all_items)}"
        for item in all_items:
            assert isinstance(item, MemoryItem)
            assert item.layer == MemoryLayer.L3_ABYSS
        print(f"  成功遍历 {len(all_items)} 条记忆")
        print("  ✅ 遍历功能正常")

        # 4.7 带密码的主密钥
        print_subheader("4.7 带密码保护的主密钥")
        storage_path_pw = os.path.join(tmpdir, "l3_abyss_pw")
        abyss_pw = AbyssLayer({
            "storage_path": storage_path_pw,
            "password": "my_secret_password",
        })

        item_pw = MemoryItem(
            memory_id="mem_pw_001",
            content_hash="pw_content_hash_001",
            layer=MemoryLayer.L3_ABYSS,
            domain=MemoryDomain.PRIVATE,
            owner_agent="test_agent",
            tags=["password_protected"],
            metadata={"secret": "true"},
        )
        abyss_pw.add(item_pw)

        stats_pw = abyss_pw.get_stats()
        assert stats_pw["master_key_encrypted"] is True
        print(f"  主密钥加密: {stats_pw['master_key_encrypted']}")

        # 重新加载（用正确密码）
        abyss_pw2 = AbyssLayer({
            "storage_path": storage_path_pw,
            "password": "my_secret_password",
        })
        retrieved_pw = abyss_pw2.get("mem_pw_001")
        assert retrieved_pw is not None
        assert retrieved_pw.memory_id == "mem_pw_001"
        print("  ✅ 密码保护的主密钥正常工作")

        # 统计信息
        final_stats = abyss.get_stats()
        print_subheader("4.8 统计信息")
        for key, val in final_stats.items():
            print(f"  {key}: {val}")

        print("\n✅ 测试 4 通过：L3 AbyssLayer 加密存储功能全部正常")
        return True

    except Exception as e:
        logger.error(f"测试 4 失败: {e}", exc_info=True)
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# 测试 5: RecallEngine 集成（关键词 + 向量 + RRF 融合）
# ============================================================

def test_recall_engine_integration():
    """测试 RecallEngine 集成向量检索和 RRF 融合"""
    print_header("测试 5: RecallEngine 集成测试")

    tmpdir = tempfile.mkdtemp(prefix="recall_test_")
    l1_db_path = os.path.join(tmpdir, "l1_shallow.db")
    l2_db_path = os.path.join(tmpdir, "l2_deep.db")
    vec_index_path = os.path.join(tmpdir, "vector.index")

    try:
        # 初始化 L1、L2 和向量搜索
        from tide_memory.layers.l1_shallow import ShallowLayer
        from tide_memory.layers.l2_deep import DeepLayer
        from tide_memory.recall.vector_search import VectorSearch
        from tide_memory.recall.keyword_search import KeywordSearch

        l1 = ShallowLayer({"db_path": l1_db_path})
        l2 = DeepLayer({"db_path": l2_db_path})
        vector_search = VectorSearch({
            "embedding_provider": "tfidf",
            "embedding_dim": 128,
            "index_path": vec_index_path,
            "similarity_threshold": 0.0,
        })
        keyword_search = KeywordSearch()

        engine = RecallEngine(
            l1=l1,
            l2=l2,
            keyword_search=keyword_search,
            vector_search=vector_search,
        )

        # 5.1 归档记忆
        print_subheader("5.1 归档记忆")
        memories = [
            {
                "content_hash": "hash_001",
                "source": "test",
                "domain": "private",
                "agent_id": "agent_a",
                "tags": ["AI", "机器学习", "深度学习"],
                "content_text": "人工智能机器学习深度学习神经网络",
            },
            {
                "content_hash": "hash_002",
                "source": "test",
                "domain": "private",
                "agent_id": "agent_a",
                "tags": ["编程", "Python", "教程"],
                "content_text": "Python编程入门教程基础语法",
            },
            {
                "content_hash": "hash_003",
                "source": "test",
                "domain": "private",
                "agent_id": "agent_a",
                "tags": ["健康", "运动", "健身"],
                "content_text": "健康饮食运动健身计划",
            },
            {
                "content_hash": "hash_004",
                "source": "test",
                "domain": "shared",
                "agent_id": "agent_b",
                "tags": ["金融", "投资", "理财"],
                "content_text": "金融投资理财策略分析方法",
            },
        ]

        archived_ids = []
        for mem in memories:
            result = engine.archive_memory(**mem)
            archived_ids.append(result["memory_id"])
            print(f"  归档: {result['memory_id']}")

        print(f"  共归档 {len(archived_ids)} 条记忆")

        # 5.2 检索测试
        print_subheader("5.2 混合检索（关键词 + 向量 + RRF）")
        results = engine.search(
            query="机器学习人工智能",
            layers=["l1_shallow"],
            top_k=3,
            domain="private",
        )

        print(f"  查询: '机器学习人工智能'")
        for r in results:
            print(f"    - {r['memory_id']}: similarity={r['similarity']}, "
                  f"kw={r['keyword_matched']}, vec={r['vector_matched']}")

        assert len(results) > 0, "搜索结果为空"

        # 检查融合标记
        for r in results:
            assert "keyword_matched" in r
            assert "vector_matched" in r
            assert "fused_score" in r

        print("  ✅ 混合检索 + RRF 融合正常")

        # 5.3 统计信息
        print_subheader("5.3 统计信息")
        stats = engine.get_stats()
        print(f"  总记忆数: {stats['total']}")
        print(f"  关键词索引: {stats.get('keyword_index', {})}")
        print(f"  向量索引: {stats.get('vector_index', {})}")
        assert "vector_index" in stats
        print("  ✅ 统计信息包含向量索引")

        print("\n✅ 测试 5 通过：RecallEngine 集成语义检索正常")
        return True

    except Exception as e:
        logger.error(f"测试 5 失败: {e}", exc_info=True)
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# 主函数
# ============================================================

def main():
    """运行所有测试"""
    print_header("P1-2 & P1-3 功能验证")
    print("  向量检索 + L3 深海层加密存储")
    print("=" * 60)

    results = {}

    # 运行测试
    results["测试1-后端降级"] = test_vector_search_backends()
    results["测试2-基本功能"] = test_vector_search_basic()
    results["测试3-持久化"] = test_vector_persistence()
    results["测试4-L3加密"] = test_abyss_layer()
    results["测试5-集成检索"] = test_recall_engine_integration()

    # 汇总
    print_header("测试结果汇总")
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")

    print(f"\n  总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
