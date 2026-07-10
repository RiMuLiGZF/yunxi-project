"""
向量检索模块 - 本地 Embedding 实现

支持三种 Embedding 后端（自动降级）：
1. sentence-transformers（首选，本地模型）
2. Ollama（次选，本地服务 API）
3. TF-IDF + SVD（兜底，纯 Python 实现）

支持两种向量索引后端（自动降级）：
1. FAISS（首选，高效向量检索库）
2. 纯 Python numpy 实现（兜底，余弦相似度矩阵计算）

所有用户数据仅本地存储，不上传云端
"""

from __future__ import annotations

import logging
import os
import pickle
import re
from collections import Counter
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)



def is_gpu_available() -> bool:
    """检测 Faiss GPU 是否可用

    Returns:
        True 表示 faiss-gpu 已安装且有可用 GPU
    """
    try:
        import faiss
        if not hasattr(faiss, "StandardGpuResources"):
            return False
        return faiss.get_num_gpus() > 0
    except ImportError:
        return False
    except Exception:
        return False


class VectorSearch:
    """
    向量检索引擎 - 本地 Embedding + 向量索引

    特性：
    - 自动检测并选择最优 Embedding 后端
    - 自动检测并选择最优向量索引后端
    - 索引持久化到本地文件
    - 内存中维护 memory_id -> 向量映射
    """

    def __init__(self, config: dict = None):
        config = config or {}
        self._embedding_provider = config.get("embedding_provider", "auto")
        self._embedding_model = config.get("embedding_model", "all-MiniLM-L6-v2")
        self._embedding_dim = config.get("embedding_dim", 384)
        self._index_path = config.get("index_path", "./data/vector/faiss.index")
        self._similarity_threshold = config.get("similarity_threshold", 0.7)
        self._ollama_base_url = config.get("ollama_base_url", "http://localhost:11434")

        # GPU 加速配置
        self._use_gpu = config.get("use_gpu", False)
        self._gpu_device_id = config.get("gpu_device_id", 0)
        self._gpu_memory_ratio = config.get("gpu_memory_ratio", 0.7)
        self._gpu_resources = None  # faiss GpuResources 实例
        self._gpu_available: bool = False  # 实际是否运行在 GPU 模式

        # P2-12: 检索质量增强配置
        self._enable_mmr = config.get("enable_mmr", True)
        self._mmr_lambda = config.get("mmr_lambda", 0.7)
        self._enable_hybrid = config.get("enable_hybrid", True)
        self._hybrid_alpha = config.get("hybrid_alpha", 0.7)
        self._enable_query_expansion = config.get("enable_query_expansion", True)
        self._min_score_variance = config.get("min_score_variance", 0.05)

        # Embedding 后端实例
        self._embed_model = None
        self._embed_backend: str = "unknown"  # 实际使用的后端

        # 向量索引
        self._faiss_index = None  # faiss.IndexFlatIP 实例
        self._use_faiss: bool = False
        # 纯 numpy 实现的向量矩阵
        self._vectors: np.ndarray | None = None  # shape: (n, dim)
        self._id_list: List[str] = []  # 与向量一一对应的 memory_id 列表
        self._id_to_idx: Dict[str, int] = {}  # memory_id -> 向量矩阵中的索引

        # metadata 存储
        self._metadata_store: Dict[str, dict] = {}

        # 初始化
        self._init_embedding()
        self._init_index()

    # ============================================================
    # Embedding 初始化与降级
    # ============================================================

    def _init_embedding(self) -> None:
        """
        自动选择可用的 Embedding 后端

        优先级：sentence_transformers > ollama > tfidf
        """
        provider = self._embedding_provider

        if provider in ("auto", "sentence_transformers"):
            if self._try_init_sentence_transformers():
                self._embed_backend = "sentence_transformers"
                logger.info(f"Embedding 后端: sentence-transformers ({self._embedding_model})")
                return
            if provider != "auto":
                logger.warning(
                    f"指定的 embedding_provider=sentence_transformers 不可用，尝试降级"
                )

        if provider in ("auto", "ollama"):
            if self._try_init_ollama():
                self._embed_backend = "ollama"
                logger.info(f"Embedding 后端: Ollama ({self._embedding_model})")
                return
            if provider != "auto":
                logger.warning(f"指定的 embedding_provider=ollama 不可用，尝试降级")

        # 兜底方案：TF-IDF + SVD
        self._init_tfidf()
        self._embed_backend = "tfidf"
        logger.info(f"Embedding 后端: TF-IDF + SVD (维度={self._embedding_dim})")
        # TF-IDF 模式下相似度普遍偏低，降低阈值
        if self._similarity_threshold > 0.5:
            self._similarity_threshold = 0.2

    def _try_init_sentence_transformers(self) -> bool:
        """尝试初始化 sentence-transformers 模型"""
        try:
            from sentence_transformers import SentenceTransformer

            self._embed_model = SentenceTransformer(self._embedding_model)
            # 用模型实际输出维度覆盖配置
            test_vec = self._embed_model.encode("test")
            self._embedding_dim = len(test_vec)
            return True
        except ImportError:
            logger.debug("sentence-transformers 未安装")
            return False
        except Exception as e:
            logger.warning(f"sentence-transformers 初始化失败: {e}")
            return False

    def _try_init_ollama(self) -> bool:
        """尝试初始化 Ollama Embedding"""
        try:
            import urllib.request
            import json

            # 测试 Ollama 服务是否可用
            url = f"{self._ollama_base_url}/api/embeddings"
            payload = json.dumps({
                "model": self._embedding_model,
                "prompt": "test",
            }).encode("utf-8")

            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "embedding" in data:
                    self._embedding_dim = len(data["embedding"])
                    self._embed_model = True  # 标记可用
                    return True
            return False
        except Exception as e:
            logger.debug(f"Ollama 不可用: {e}")
            return False

    def _init_tfidf(self) -> None:
        """初始化 TF-IDF + SVD 兜底方案"""
        # 词汇表：运行时动态构建
        self._tfidf_vocab: Dict[str, int] = {}
        self._tfidf_idf: Dict[str, float] = {}
        self._tfidf_doc_count: int = 0
        # SVD 投影矩阵（用于降维到 embedding_dim）
        self._svd_components: np.ndarray | None = None
        # 累积的文档向量，用于计算 SVD
        self._tfidf_accumulated: List[np.ndarray] = []

    def _get_embedding(self, text: str) -> List[float]:
        """
        获取文本的 Embedding 向量

        Args:
            text: 输入文本

        Returns:
            归一化后的向量（长度为 embedding_dim）
        """
        if self._embed_backend == "sentence_transformers":
            vec = self._embed_model.encode(text)
            vec = np.array(vec, dtype=np.float32)
        elif self._embed_backend == "ollama":
            vec = self._ollama_embed(text)
        else:  # tfidf
            vec = self._tfidf_embed(text)

        # 归一化（L2 归一化，内积即余弦相似度）
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def _ollama_embed(self, text: str) -> np.ndarray:
        """调用 Ollama API 获取 Embedding"""
        import urllib.request
        import json

        url = f"{self._ollama_base_url}/api/embeddings"
        payload = json.dumps({
            "model": self._embedding_model,
            "prompt": text,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return np.array(data["embedding"], dtype=np.float32)

    # ============================================================
    # TF-IDF + SVD 兜底 Embedding
    # ============================================================

    def _tfidf_tokenize(self, text: str) -> List[str]:
        """简单分词：英文单词 + 中文2字词"""
        if not text:
            return []
        text = text.lower()
        # 英文单词
        en_words = re.findall(r'[a-zA-Z]{2,}', text)
        # 中文 2 字词
        cn_words = []
        for i in range(len(text) - 1):
            if '\u4e00' <= text[i] <= '\u9fff' and '\u4e00' <= text[i+1] <= '\u9fff':
                cn_words.append(text[i:i+2])
        return en_words + cn_words

    def _tfidf_embed(self, text: str) -> np.ndarray:
        """
        TF-IDF + SVD 生成 embedding 向量

        - 动态构建词汇表和 IDF
        - 使用随机投影（Random Projection）近似 SVD 降维
        - 输出维度固定为 embedding_dim
        """
        tokens = self._tfidf_tokenize(text)
        if not tokens:
            return np.zeros(self._embedding_dim, dtype=np.float32)

        # 如果词汇表足够大，使用随机投影降维
        vocab_size = len(self._tfidf_vocab)
        if vocab_size < self._embedding_dim:
            # 词汇量不足时，用特征哈希 + 随机投影
            return self._random_projection_embed(tokens)

        # 构建 TF-IDF 向量
        vec = np.zeros(vocab_size, dtype=np.float32)
        tf = Counter(tokens)
        total = len(tokens)
        for term, count in tf.items():
            if term in self._tfidf_vocab:
                idx = self._tfidf_vocab[term]
                idf = self._tfidf_idf.get(term, 1.0)
                vec[idx] = (count / total) * idf

        # 使用已有的 SVD 投影矩阵降维
        if self._svd_components is not None:
            reduced = vec @ self._svd_components.T
            return reduced

        # 没有 SVD 矩阵时用前 embedding_dim 维截断（粗糙方案）
        if len(vec) >= self._embedding_dim:
            return vec[:self._embedding_dim]
        padded = np.zeros(self._embedding_dim, dtype=np.float32)
        padded[:len(vec)] = vec
        return padded

    def _random_projection_embed(self, tokens: List[str]) -> np.ndarray:
        """
        基于特征哈希的随机投影 Embedding

        将词哈希到 embedding_dim 维空间，做近似的降维。
        这是 TF-IDF 方案下词汇量不足时的兜底。
        """
        vec = np.zeros(self._embedding_dim, dtype=np.float32)
        tf = Counter(tokens)
        for term, count in tf.items():
            # 简单哈希：用 Python 内置 hash 将词映射到维度索引
            h = hash(term)
            idx = h % self._embedding_dim
            # 用符号位决定正负（保持内积性质）
            sign = 1 if (h >> 31) % 2 == 0 else -1
            vec[idx] += sign * count

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def _update_tfidf_vocab(self, text: str) -> None:
        """更新 TF-IDF 词汇表和 IDF"""
        tokens = self._tfidf_tokenize(text)
        if not tokens:
            return

        self._tfidf_doc_count += 1
        unique_terms = set(tokens)
        for term in unique_terms:
            if term not in self._tfidf_vocab:
                self._tfidf_vocab[term] = len(self._tfidf_vocab)
                self._tfidf_idf[term] = 1.0
            else:
                self._tfidf_idf[term] += 1.0

        # 更新 IDF 值
        import math
        for term in self._tfidf_idf:
            self._tfidf_idf[term] = math.log(
                (self._tfidf_doc_count + 1) / (self._tfidf_idf.get(term, 1) + 1)
            ) + 1.0

    # ============================================================
    # 向量索引初始化
    # ============================================================

    def _init_index(self) -> None:
        """
        初始化向量索引

        优先使用 FAISS，否则使用纯 numpy 实现。
        如果索引文件存在则加载，否则创建空索引。
        """
        # 尝试加载已有的索引
        index_dir = os.path.dirname(self._index_path)
        os.makedirs(index_dir, exist_ok=True)

        # 先尝试加载持久化数据
        loaded = self._load_index()
        if loaded:
            return

        # 新建空索引
        self._try_init_faiss()
        if not self._use_faiss:
            # numpy 模式下空矩阵
            self._vectors = np.zeros((0, self._embedding_dim), dtype=np.float32)

    def _try_init_faiss(self) -> bool:
        """尝试初始化 FAISS 索引（支持 GPU 加速）

        优先级：GPU Faiss > CPU Faiss > numpy
        GPU 模式下自动限制显存使用比例，避免 OOM。
        """
        try:
            import faiss

            # GPU 模式
            if self._use_gpu and hasattr(faiss, "StandardGpuResources") and faiss.get_num_gpus() > 0:
                try:
                    self._gpu_resources = faiss.StandardGpuResources()
                    # 限制临时显存使用比例
                    self._gpu_resources.setTempMemoryFraction(self._gpu_memory_ratio)
                    config = faiss.GpuIndexFlatConfig()
                    config.device = self._gpu_device_id
                    self._faiss_index = faiss.GpuIndexFlatIP(
                        self._gpu_resources, self._embedding_dim, config
                    )
                    self._use_faiss = True
                    self._gpu_available = True
                    logger.info(
                        f"FAISS GPU 初始化成功 (device={self._gpu_device_id}, "
                        f"mem_ratio={self._gpu_memory_ratio})"
                    )
                    return True
                except Exception as e:
                    logger.warning(f"FAISS GPU 初始化失败，降级到 CPU: {e}")
                    self._gpu_available = False
                    # 降级到 CPU

            # CPU 模式
            self._faiss_index = faiss.IndexFlatIP(self._embedding_dim)
            self._use_faiss = True
            self._gpu_available = False
            return True
        except ImportError:
            logger.debug("faiss 未安装，使用 numpy 实现向量检索")
            self._use_faiss = False
            self._gpu_available = False
            return False
        except Exception as e:
            logger.warning(f"FAISS 初始化失败: {e}")
            self._use_faiss = False
            self._gpu_available = False
            return False

    def _load_index(self) -> bool:
        """从磁盘加载索引"""
        meta_path = self._index_path + ".meta.pkl"

        if not os.path.exists(meta_path):
            return False

        try:
            with open(meta_path, "rb") as f:
                meta = pickle.load(f)

            self._id_list = meta.get("id_list", [])
            self._id_to_idx = {mid: i for i, mid in enumerate(self._id_list)}
            self._metadata_store = meta.get("metadata", {})

            # 加载 TF-IDF 状态（如果有）
            if "tfidf_vocab" in meta:
                self._tfidf_vocab = meta["tfidf_vocab"]
                self._tfidf_idf = meta["tfidf_idf"]
                self._tfidf_doc_count = meta.get("tfidf_doc_count", 0)

            # 加载向量数据
            vec_path = self._index_path + ".vectors.npy"
            if os.path.exists(vec_path):
                self._vectors = np.load(vec_path)
                if self._vectors.shape[1] != self._embedding_dim:
                    logger.warning(
                        f"索引维度 {self._vectors.shape[1]} 与配置 {self._embedding_dim} 不匹配，重建索引"
                    )
                    self._vectors = np.zeros((0, self._embedding_dim), dtype=np.float32)
                    self._id_list = []
                    self._id_to_idx = {}
                    return False
                self._embedding_dim = self._vectors.shape[1]
            else:
                self._vectors = np.zeros((0, self._embedding_dim), dtype=np.float32)

            # 尝试加载 FAISS 索引
            if os.path.exists(self._index_path):
                try:
                    import faiss
                    self._faiss_index = faiss.read_index(self._index_path)
                    self._use_faiss = True
                    return True
                except Exception:
                    pass

            # numpy 模式
            self._use_faiss = False
            self._try_init_faiss()
            if self._use_faiss and self._vectors is not None and len(self._id_list) > 0:
                # 有 FAISS 了，把 numpy 的向量加进去
                self._faiss_index.add(self._vectors)
            return True

        except Exception as e:
            logger.warning(f"加载索引失败，将重建: {e}")
            return False

    def _save_index(self) -> None:
        """持久化索引到磁盘"""
        index_dir = os.path.dirname(self._index_path)
        os.makedirs(index_dir, exist_ok=True)

        # 保存元数据
        meta = {
            "id_list": self._id_list,
            "metadata": self._metadata_store,
            "embedding_dim": self._embedding_dim,
            "embed_backend": self._embed_backend,
        }

        # TF-IDF 状态
        if self._embed_backend == "tfidf":
            meta["tfidf_vocab"] = self._tfidf_vocab
            meta["tfidf_idf"] = self._tfidf_idf
            meta["tfidf_doc_count"] = self._tfidf_doc_count

        meta_path = self._index_path + ".meta.pkl"
        with open(meta_path, "wb") as f:
            pickle.dump(meta, f)

        # 保存 FAISS 索引
        if self._use_faiss and self._faiss_index is not None:
            try:
                import faiss
                faiss.write_index(self._faiss_index, self._index_path)
            except Exception as e:
                logger.warning(f"保存 FAISS 索引失败: {e}")

        # 保存 numpy 向量（无论哪种模式都存，方便降级）
        if self._vectors is not None and self._vectors.shape[0] > 0:
            vec_path = self._index_path + ".vectors.npy"
            np.save(vec_path, self._vectors)

    # ============================================================
    # 核心 API：添加 / 搜索 / 删除
    # ============================================================

    def add(self, memory_id: str, text: str, metadata: dict = None) -> bool:
        """
        添加一条记忆的向量

        Args:
            memory_id: 记忆 ID
            text: 记忆文本（用于生成 embedding）
            metadata: 元数据

        Returns:
            是否成功
        """
        try:
            # 如果已存在，先删除旧的
            if memory_id in self._id_to_idx:
                self.delete(memory_id)

            # 更新 TF-IDF 词汇表
            if self._embed_backend == "tfidf":
                self._update_tfidf_vocab(text)

            # 生成 embedding
            vec = self._get_embedding(text)
            vec_arr = np.array([vec], dtype=np.float32)

            # 添加到 numpy 矩阵
            if self._vectors is None or self._vectors.shape[0] == 0:
                self._vectors = vec_arr
            else:
                self._vectors = np.vstack([self._vectors, vec_arr])

            idx = len(self._id_list)
            self._id_list.append(memory_id)
            self._id_to_idx[memory_id] = idx
            self._metadata_store[memory_id] = metadata or {}

            # 添加到 FAISS
            if self._use_faiss and self._faiss_index is not None:
                self._faiss_index.add(vec_arr)

            return True
        except Exception as e:
            logger.error(f"添加向量失败 [{memory_id}]: {e}")
            return False

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict = None,
    ) -> List[Dict]:
        """
        向量相似度搜索（P2-12: 质量增强版）

        增强特性:
        - 混合检索: 向量相似度 + 关键词匹配 融合打分
        - MMR 去重: 减少相似结果冗余
        - 动态阈值: 自适应相似度阈值

        Args:
            query: 查询文本
            top_k: 返回数量
            filters: 过滤条件（匹配 metadata 字段）

        Returns:
            [{memory_id, score, metadata}] 按相似度降序排列
        """
        if len(self._id_list) == 0:
            return []

        try:
            query_vec = np.array([self._get_embedding(query)], dtype=np.float32)

            if self._use_faiss and self._faiss_index is not None:
                # FAISS 搜索（内积，因为已归一化，等价于余弦相似度）
                k = min(top_k * 3, len(self._id_list))  # 多取一些做过滤
                scores, indices = self._faiss_index.search(query_vec, k)
                results = []
                for i in range(len(indices[0])):
                    idx = int(indices[0][i])
                    if idx < 0 or idx >= len(self._id_list):
                        continue
                    mid = self._id_list[idx]
                    score = float(scores[0][i])
                    if score < self._similarity_threshold:
                        continue
                    meta = self._metadata_store.get(mid, {})
                    if filters and not self._match_filters(meta, filters):
                        continue
                    results.append({
                        "memory_id": mid,
                        "score": round(score, 4),
                        "similarity": round(score, 4),
                        "metadata": meta,
                    })
                    if len(results) >= top_k * 3:
                        break

                # P2-12: 混合检索增强
                if self._enable_hybrid and results:
                    for r in results:
                        meta = r.get("metadata", {})
                        text = meta.get("text", meta.get("content", ""))
                        if not text and "title" in meta:
                            text = meta["title"]
                        kw_score = self._keyword_score(query, text)
                        r["keyword_score"] = round(kw_score, 4)
                        vec_score = r["score"]
                        r["hybrid_score"] = round(
                            self._hybrid_alpha * vec_score + (1 - self._hybrid_alpha) * kw_score, 4
                        )
                        r["score"] = r["hybrid_score"]
                    results.sort(key=lambda x: x["score"], reverse=True)

                # P2-12: MMR 去重
                if self._enable_mmr and len(results) > top_k:
                    query_vec = np.array([self._get_embedding(query)], dtype=np.float32)
                    results = self._mmr_rerank(query_vec[0], results, top_k, self._mmr_lambda)

                return results[:top_k]
            else:
                # 纯 numpy 实现：余弦相似度
                # 向量已归一化，内积即余弦相似度
                similarities = (self._vectors @ query_vec.T).flatten()

                # P2-12: 动态阈值
                dynamic_thresh = self._dynamic_threshold(similarities)
                mask = similarities >= dynamic_thresh
                if filters:
                    # 应用 metadata 过滤
                    for i, mid in enumerate(self._id_list):
                        if mask[i]:
                            meta = self._metadata_store.get(mid, {})
                            if not self._match_filters(meta, filters):
                                mask[i] = False

                # 获取 top_k
                valid_indices = np.where(mask)[0]
                if len(valid_indices) == 0:
                    return []

                valid_scores = similarities[valid_indices]
                # 按分数降序排序
                sorted_order = np.argsort(-valid_scores)[:top_k]

                results = []
                for order_idx in sorted_order:
                    orig_idx = int(valid_indices[order_idx])
                    mid = self._id_list[orig_idx]
                    results.append({
                        "memory_id": mid,
                        "score": round(float(similarities[orig_idx]), 4),
                        "similarity": round(float(similarities[orig_idx]), 4),
                        "metadata": self._metadata_store.get(mid, {}),
                    })

                # P2-12: 混合检索增强
                if self._enable_hybrid and results:
                    for r in results:
                        meta = r.get("metadata", {})
                        text = meta.get("text", meta.get("content", ""))
                        if not text and "title" in meta:
                            text = meta["title"]
                        kw_score = self._keyword_score(query, text)
                        r["keyword_score"] = round(kw_score, 4)
                        vec_score = r["score"]
                        r["hybrid_score"] = round(
                            self._hybrid_alpha * vec_score + (1 - self._hybrid_alpha) * kw_score, 4
                        )
                        r["score"] = r["hybrid_score"]
                    results.sort(key=lambda x: x["score"], reverse=True)

                # P2-12: MMR 去重
                if self._enable_mmr and len(results) > top_k:
                    query_vec_arr = np.array([self._get_embedding(query)], dtype=np.float32)
                    results = self._mmr_rerank(query_vec_arr[0], results, top_k, self._mmr_lambda)

                return results[:top_k]

        except Exception as e:
            logger.error(f"向量搜索失败: {e}")
            return []

    def delete(self, memory_id: str) -> bool:
        """
        删除一条记忆的向量

        FAISS 的 IndexFlatIP 不支持直接删除，
        因此采用标记删除 + 重建时清理的策略。
        """
        if memory_id not in self._id_to_idx:
            return False

        try:
            idx = self._id_to_idx[memory_id]

            # 从 numpy 矩阵中移除
            if self._vectors is not None and self._vectors.shape[0] > idx:
                self._vectors = np.delete(self._vectors, idx, axis=0)

            # 从 id 列表中移除
            self._id_list.pop(idx)
            self._id_to_idx.pop(memory_id, None)
            self._metadata_store.pop(memory_id, None)

            # 更新剩余 id 的索引映射
            for i in range(idx, len(self._id_list)):
                self._id_to_idx[self._id_list[i]] = i

            # FAISS 索引需要重建（IndexFlatIP 不支持删除）
            if self._use_faiss and self._faiss_index is not None:
                self._rebuild_faiss_from_vectors()

            return True
        except Exception as e:
            logger.error(f"删除向量失败 [{memory_id}]: {e}")
            return False

    def batch_add(self, items: List[Dict]) -> int:
        """
        批量添加向量

        Args:
            items: [{memory_id, text, metadata?}, ...]

        Returns:
            成功添加的数量
        """
        success = 0
        for item in items:
            mid = item.get("memory_id", "")
            text = item.get("text", "")
            meta = item.get("metadata")
            if self.add(mid, text, meta):
                success += 1
        return success

    def rebuild_index(self) -> None:
        """重建索引（从 memory_id 列表和向量矩阵重建 FAISS 索引）"""
        if self._use_faiss:
            self._rebuild_faiss_from_vectors()
        self._save_index()

    def _rebuild_faiss_from_vectors(self) -> None:
        """从 numpy 向量矩阵重建 FAISS 索引（支持 GPU）"""
        try:
            import faiss

            # GPU 模式重建
            if self._gpu_available and self._gpu_resources is not None:
                try:
                    config = faiss.GpuIndexFlatConfig()
                    config.device = self._gpu_device_id
                    self._faiss_index = faiss.GpuIndexFlatIP(
                        self._gpu_resources, self._embedding_dim, config
                    )
                    if self._vectors is not None and self._vectors.shape[0] > 0:
                        self._faiss_index.add(self._vectors)
                    self._use_faiss = True
                    return
                except Exception as e:
                    logger.warning(f"GPU 索引重建失败，降级到 CPU: {e}")
                    self._gpu_available = False

            # CPU 模式重建
            self._faiss_index = faiss.IndexFlatIP(self._embedding_dim)
            if self._vectors is not None and self._vectors.shape[0] > 0:
                self._faiss_index.add(self._vectors)
            self._use_faiss = True
        except Exception as e:
            logger.warning(f"重建 FAISS 索引失败，降级为 numpy: {e}")
            self._use_faiss = False
            self._gpu_available = False

    def get_stats(self) -> Dict:
        """获取向量库统计信息"""
        return {
            "embed_backend": self._embed_backend,
            "embed_model": self._embedding_model,
            "embedding_dim": self._embedding_dim,
            "dimension": self._embedding_dim,  # 兼容别名
            "index_backend": "faiss" if self._use_faiss else "numpy",
            "backend": self._embed_backend,  # 兼容别名
            "total_vectors": len(self._id_list),
            "similarity_threshold": self._similarity_threshold,
            "index_path": self._index_path,
            "enable_mmr": self._enable_mmr,
            "enable_hybrid": self._enable_hybrid,
            # GPU 加速信息
            "gpu_enabled": self._use_gpu,
            "gpu_available": self._gpu_available,
            "gpu_device_id": self._gpu_device_id if self._gpu_available else None,
            "gpu_memory_ratio": self._gpu_memory_ratio if self._gpu_available else None,
        }

    # ============================================================
    # P2-12: 检索质量增强 - 查询预处理与扩展
    # ============================================================

    def _preprocess_query(self, query: str) -> str:
        """查询预处理：去除多余空格"""
        if not query:
            return ""
        return " ".join(query.split()).strip()

    def _expand_query(self, query: str) -> List[str]:
        """查询扩展：生成相关查询变体，提升召回率"""
        if not query:
            return []
        queries = [query]
        q = query.strip()
        import re
        # 去标点变体
        q_no_punct = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', q)
        q_no_punct = ' '.join(q_no_punct.split())
        if q_no_punct != q and q_no_punct:
            queries.append(q_no_punct)
        # 英文小写变体
        if any(c.isalpha() for c in q):
            if q.lower() != q:
                queries.append(q.lower())
        return list(dict.fromkeys(queries))[:5]

    def _keyword_score(self, query: str, text: str) -> float:
        """计算关键词匹配分数（0~1）"""
        if not query or not text:
            return 0.0
        tokens = self._tfidf_tokenize(query)
        doc_tokens = self._tfidf_tokenize(text)
        if not tokens or not doc_tokens:
            return 0.0
        doc_set = set(doc_tokens)
        match_score = 0.0
        for token in set(tokens):
            if token in doc_set:
                tf = doc_tokens.count(token) / len(doc_tokens)
                match_score += min(tf * 3, 1.0)
        return min(match_score / max(len(tokens), 1), 1.0)

    # ============================================================
    # P2-12: 检索质量增强 - MMR 去重
    # ============================================================

    def _mmr_rerank(
        self,
        query_vec: np.ndarray,
        candidates: List[Dict],
        top_k: int,
        lambda_: float = 0.7,
    ) -> List[Dict]:
        """MMR 去重重排序：平衡相关性与多样性"""
        if len(candidates) <= top_k:
            return candidates
        # 收集候选向量
        candidate_vectors = []
        for cand in candidates:
            mid = cand.get("memory_id", "")
            if mid in self._id_to_idx and self._vectors is not None:
                idx = self._id_to_idx[mid]
                if idx < len(self._vectors):
                    candidate_vectors.append(self._vectors[idx])
                    continue
            candidate_vectors.append(None)
        selected = []
        remaining = list(range(len(candidates)))
        while len(selected) < top_k and remaining:
            best_idx = -1
            best_mmr = -float("inf")
            for idx in remaining:
                rel_score = candidates[idx].get("score", 0.0)
                div_penalty = 0.0
                if selected and candidate_vectors[idx] is not None:
                    max_sim = 0.0
                    for s in selected:
                        if candidate_vectors[s] is not None:
                            sim = float(np.dot(candidate_vectors[idx], candidate_vectors[s]))
                            max_sim = max(max_sim, max(sim, 0.0))
                    div_penalty = max_sim
                mmr = lambda_ * rel_score - (1 - lambda_) * div_penalty
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = idx
            if best_idx < 0:
                break
            selected.append(best_idx)
            remaining.remove(best_idx)
        return [candidates[i] for i in selected]

    # ============================================================
    # P2-12: 检索质量增强 - 动态阈值
    # ============================================================

    def _dynamic_threshold(self, scores: np.ndarray) -> float:
        """根据分数分布动态计算相似度阈值"""
        if len(scores) == 0:
            return self._similarity_threshold
        mean_score = float(np.mean(scores))
        std_score = float(np.std(scores))
        if std_score < self._min_score_variance:
            return self._similarity_threshold
        dynamic_thresh = mean_score - 0.5 * std_score
        dynamic_thresh = max(dynamic_thresh, self._similarity_threshold * 0.7)
        dynamic_thresh = min(dynamic_thresh, 0.95)
        return dynamic_thresh

    # ============================================================
    # 辅助方法
    # ============================================================

    def _match_filters(self, metadata: dict, filters: dict) -> bool:
        """检查 metadata 是否匹配过滤条件"""
        for key, value in filters.items():
            if key not in metadata:
                return False
            if metadata[key] != value:
                return False
        return True

    def flush(self) -> None:
        """手动持久化"""
        self._save_index()
