"""
向量检索模块 - 本地 Embedding 实现

支持三种 Embedding 后端（自动降级）：
1. sentence-transformers（首选，本地模型）
2. Ollama（次选，本地服务 API）
3. TF-IDF + SVD（兜底，纯 Python 实现）

支持两种向量索引后端（自动降级）：
1. FAISS（首选，高效向量检索库）
   - IndexHNSWFlat: O(log n)，适合 10万+ 向量（P2-任务2 新增）
   - IndexFlatIP: O(n)，暴力搜索，适合小数据集
2. 纯 Python numpy 实现（兜底，余弦相似度矩阵计算）

P2-任务2: HNSW 索引升级
- 新建索引默认使用 HNSW（M=32, ef_construction=200, ef_search=128）
- 已有 Flat 索引保持不变，提供迁移工具
- HNSW 不可用时自动回退到 Flat
- 性能提升预期：10万向量时检索速度从 ~100ms 降到 ~1ms（约100倍）

所有用户数据仅本地存储，不上传云端
"""

from __future__ import annotations

import os
import pickle
from collections import Counter
from typing import Any, Dict, List, Optional, Set

import numpy as np
import structlog

from ..common.constants import (
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_INDEX_PATH,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_OLLAMA_BASE_URL,
    OLLAMA_TIMEOUT_CONNECT,
    OLLAMA_TIMEOUT_REQUEST,
    DEFAULT_USE_GPU,
    DEFAULT_GPU_DEVICE_ID,
    DEFAULT_GPU_MEMORY_RATIO,
    DEFAULT_ENABLE_MMR,
    DEFAULT_MMR_LAMBDA,
    DEFAULT_ENABLE_HYBRID,
    DEFAULT_HYBRID_ALPHA,
    DEFAULT_ENABLE_QUERY_EXPANSION,
    MIN_SCORE_VARIANCE,
    DEFAULT_VECTOR_INDEX_TYPE,
    HNSW_DEFAULT_M,
    HNSW_DEFAULT_EF_CONSTRUCTION,
    HNSW_DEFAULT_EF_SEARCH,
    HNSW_MIN_EF_SEARCH,
    HNSW_MAX_EF_SEARCH,
    FILTER_EXPAND_MULTIPLIER,
    KEYWORD_MATCH_MAX_TF_FACTOR,
    DYNAMIC_THRESHOLD_STD_FACTOR,
    DYNAMIC_THRESHOLD_MIN_RATIO,
    DYNAMIC_THRESHOLD_MAX,
    TFIDF_SIMILARITY_THRESHOLD,
    QUERY_EXPANSION_MAX_VARIANTS,
    DEFAULT_TOP_K,
    INDEX_META_SUFFIX,
    INDEX_VECTORS_SUFFIX,
    VECTOR_INDEX_TYPE_HNSW,
    VECTOR_INDEX_TYPE_FLAT,
)
from ..common.text_utils import tokenize

logger = structlog.get_logger(__name__)



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

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        config = config or {}
        self._embedding_provider = config.get("embedding_provider", DEFAULT_EMBEDDING_PROVIDER)
        self._embedding_model = config.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
        self._embedding_dim = config.get("embedding_dim", DEFAULT_EMBEDDING_DIM)
        self._index_path = config.get("index_path", DEFAULT_INDEX_PATH)
        self._similarity_threshold = config.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD)
        self._ollama_base_url = config.get("ollama_base_url", DEFAULT_OLLAMA_BASE_URL)

        # GPU 加速配置
        self._use_gpu = config.get("use_gpu", DEFAULT_USE_GPU)
        self._gpu_device_id = config.get("gpu_device_id", DEFAULT_GPU_DEVICE_ID)
        self._gpu_memory_ratio = config.get("gpu_memory_ratio", DEFAULT_GPU_MEMORY_RATIO)
        self._gpu_resources = None  # faiss GpuResources 实例
        self._gpu_available: bool = False  # 实际是否运行在 GPU 模式

        # P2-12: 检索质量增强配置
        self._enable_mmr = config.get("enable_mmr", DEFAULT_ENABLE_MMR)
        self._mmr_lambda = config.get("mmr_lambda", DEFAULT_MMR_LAMBDA)
        self._enable_hybrid = config.get("enable_hybrid", DEFAULT_ENABLE_HYBRID)
        self._hybrid_alpha = config.get("hybrid_alpha", DEFAULT_HYBRID_ALPHA)
        self._enable_query_expansion = config.get("enable_query_expansion", DEFAULT_ENABLE_QUERY_EXPANSION)
        self._min_score_variance = config.get("min_score_variance", MIN_SCORE_VARIANCE)

        # P2-任务2: HNSW 索引配置
        self._index_type = config.get("vector_index_type", DEFAULT_VECTOR_INDEX_TYPE)  # HNSW / Flat
        self._hnsw_m = config.get("hnsw_m", HNSW_DEFAULT_M)                      # 每层最大连接数
        self._hnsw_ef_construction = config.get("hnsw_ef_construction", HNSW_DEFAULT_EF_CONSTRUCTION)  # 构建时搜索邻居数
        self._hnsw_ef_search = config.get("hnsw_ef_search", HNSW_DEFAULT_EF_SEARCH)     # 搜索时搜索邻居数
        self._actual_index_type: str = "unknown"  # 实际使用的索引类型

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

        # P2-任务3: 标记删除 + 惰性重建
        self._deleted_ids: Set[str] = set()  # 已标记删除的 memory_id 集合
        self._deleted_indices: Set[int] = set()  # 已标记删除的索引集合（内部过滤用）
        self._rebuild_ratio: float = 0.2  # 重建阈值比例（删除数达到总数的百分比）
        self._rebuild_abs_threshold: int = 100  # 重建绝对阈值（删除数达到固定条数）

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
            self._similarity_threshold = TFIDF_SIMILARITY_THRESHOLD

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

            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_CONNECT) as resp:
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

        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_REQUEST) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return np.array(data["embedding"], dtype=np.float32)

    # ============================================================
    # TF-IDF + SVD 兜底 Embedding
    # ============================================================

    def _tfidf_tokenize(self, text: str) -> List[str]:
        """简单分词：英文单词 + 中文2字词（委托给统一 tokenize）"""
        return tokenize(text)

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
        """尝试初始化 FAISS 索引（支持 GPU 加速 + HNSW/Flat 两种索引）

        优先级：GPU HNSW > GPU Flat > CPU HNSW > CPU Flat > numpy
        GPU 模式下自动限制显存使用比例，避免 OOM。

        P2-任务2: 新增 HNSW 索引支持，O(log n) 复杂度，10万+向量性能提升显著。
        """
        try:
            import faiss

            # GPU 模式
            if self._use_gpu and hasattr(faiss, "StandardGpuResources") and faiss.get_num_gpus() > 0:
                try:
                    self._gpu_resources = faiss.StandardGpuResources()
                    # 限制临时显存使用比例
                    self._gpu_resources.setTempMemoryFraction(self._gpu_memory_ratio)

                    # P2-任务2: 尝试 HNSW GPU 索引
                    if self._index_type.upper() == "HNSW":
                        try:
                            # HNSW 在 GPU 上通过 GpuIndexIVFPQ 等实现，
                            # 但标准 HNSW 通常在 CPU 上构建，GPU 加速搜索。
                            # 这里优先尝试 CPU HNSW（更通用），GPU 加速搜索。
                            # 先构建 CPU HNSW，再尝试搬到 GPU
                            self._faiss_index = faiss.IndexHNSWFlat(
                                self._embedding_dim, self._hnsw_m, faiss.METRIC_INNER_PRODUCT
                            )
                            self._faiss_index.hnsw.efConstruction = self._hnsw_ef_construction
                            self._faiss_index.hnsw.efSearch = self._hnsw_ef_search
                            self._use_faiss = True
                            self._gpu_available = False  # HNSW 默认 CPU 模式
                            self._actual_index_type = "HNSW"
                            logger.info(
                                f"FAISS HNSW 索引初始化成功 (M={self._hnsw_m}, "
                                f"ef_construction={self._hnsw_ef_construction}, "
                                f"ef_search={self._hnsw_ef_search})"
                            )
                            return True
                        except Exception as e:
                            logger.warning(f"FAISS HNSW 初始化失败，降级到 Flat: {e}")

                    # 降级到 GPU Flat
                    config = faiss.GpuIndexFlatConfig()
                    config.device = self._gpu_device_id
                    self._faiss_index = faiss.GpuIndexFlatIP(
                        self._gpu_resources, self._embedding_dim, config
                    )
                    self._use_faiss = True
                    self._gpu_available = True
                    self._actual_index_type = "Flat"
                    logger.info(
                        f"FAISS GPU Flat 初始化成功 (device={self._gpu_device_id}, "
                        f"mem_ratio={self._gpu_memory_ratio})"
                    )
                    return True
                except Exception as e:
                    logger.warning(f"FAISS GPU 初始化失败，降级到 CPU: {e}")
                    self._gpu_available = False
                    # 降级到 CPU

            # CPU 模式
            # P2-任务2: 优先尝试 HNSW
            if self._index_type.upper() == "HNSW":
                try:
                    self._faiss_index = faiss.IndexHNSWFlat(
                        self._embedding_dim, self._hnsw_m, faiss.METRIC_INNER_PRODUCT
                    )
                    self._faiss_index.hnsw.efConstruction = self._hnsw_ef_construction
                    self._faiss_index.hnsw.efSearch = self._hnsw_ef_search
                    self._use_faiss = True
                    self._gpu_available = False
                    self._actual_index_type = "HNSW"
                    logger.info(
                        f"FAISS CPU HNSW 索引初始化成功 (M={self._hnsw_m}, "
                        f"ef_construction={self._hnsw_ef_construction}, "
                        f"ef_search={self._hnsw_ef_search})"
                    )
                    return True
                except Exception as e:
                    logger.warning(f"FAISS HNSW 初始化失败，降级到 Flat: {e}")

            # 降级到 Flat
            self._faiss_index = faiss.IndexFlatIP(self._embedding_dim)
            self._use_faiss = True
            self._gpu_available = False
            self._actual_index_type = "Flat"
            return True
        except ImportError:
            logger.debug("faiss 未安装，使用 numpy 实现向量检索")
            self._use_faiss = False
            self._gpu_available = False
            self._actual_index_type = "numpy"
            return False
        except Exception as e:
            logger.warning(f"FAISS 初始化失败: {e}")
            self._use_faiss = False
            self._gpu_available = False
            self._actual_index_type = "numpy"
            return False

    def _load_index(self) -> bool:
        """从磁盘加载索引

        P2-任务2: 支持加载 HNSW 和 Flat 两种索引类型，根据元数据自动识别。
        """
        meta_path = self._index_path + INDEX_META_SUFFIX

        if not os.path.exists(meta_path):
            return False

        try:
            with open(meta_path, "rb") as f:
                meta = pickle.load(f)

            self._id_list = meta.get("id_list", [])
            self._id_to_idx = {mid: i for i, mid in enumerate(self._id_list)}
            self._metadata_store = meta.get("metadata", {})

            # P2-任务3: 加载标记删除状态
            self._deleted_ids = set(meta.get("deleted_ids", []))
            self._deleted_indices = set(meta.get("deleted_indices", []))

            # P2-任务2: 读取索引类型元数据
            saved_index_type = meta.get("index_type", VECTOR_INDEX_TYPE_FLAT)
            self._actual_index_type = saved_index_type

            # 加载 TF-IDF 状态（如果有）
            if "tfidf_vocab" in meta:
                self._tfidf_vocab = meta["tfidf_vocab"]
                self._tfidf_idf = meta["tfidf_idf"]
                self._tfidf_doc_count = meta.get("tfidf_doc_count", 0)

            # 加载向量数据
            vec_path = self._index_path + INDEX_VECTORS_SUFFIX
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

                    # P2-任务2: 如果是 HNSW 索引，恢复 efSearch 参数
                    if hasattr(self._faiss_index, 'hnsw'):
                        self._actual_index_type = "HNSW"
                        # 用配置的 ef_search 覆盖（允许动态调整）
                        try:
                            self._faiss_index.hnsw.efSearch = self._hnsw_ef_search
                        except Exception:
                            pass
                        logger.info(f"加载 HNSW 索引 (ef_search={self._hnsw_ef_search})")
                    else:
                        self._actual_index_type = "Flat"
                        logger.info("加载 Flat 索引")
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
        """持久化索引到磁盘

        P2-任务2: 同时保存索引类型元数据（HNSW/Flat），方便加载时识别。
        """
        index_dir = os.path.dirname(self._index_path)
        os.makedirs(index_dir, exist_ok=True)

        # 保存元数据
        meta = {
            "id_list": self._id_list,
            "metadata": self._metadata_store,
            "embedding_dim": self._embedding_dim,
            "embed_backend": self._embed_backend,
            "index_type": self._actual_index_type,  # P2-任务2: 索引类型
            # P2-任务3: 标记删除状态
            "deleted_ids": list(self._deleted_ids),
            "deleted_indices": list(self._deleted_indices),
        }

        # TF-IDF 状态
        if self._embed_backend == "tfidf":
            meta["tfidf_vocab"] = self._tfidf_vocab
            meta["tfidf_idf"] = self._tfidf_idf
            meta["tfidf_doc_count"] = self._tfidf_doc_count

        meta_path = self._index_path + INDEX_META_SUFFIX
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
            vec_path = self._index_path + INDEX_VECTORS_SUFFIX
            np.save(vec_path, self._vectors)

    # ============================================================
    # 核心 API：添加 / 搜索 / 删除
    # ============================================================

    def add(self, memory_id: str, text: str, metadata: dict = None) -> bool:
        """
        添加一条记忆的向量

        对于已存在的 memory_id，采用"标记旧的为过期 + 追加新的"策略，
        旧条目会在下次惰性重建时被物理清理。

        Args:
            memory_id: 记忆 ID
            text: 记忆文本（用于生成 embedding）
            metadata: 元数据

        Returns:
            是否成功
        """
        try:
            # P2-任务3: 惰性删除模式下处理已有 ID
            was_deleted = memory_id in self._deleted_ids
            if memory_id in self._id_to_idx and not was_deleted:
                # 活动条目被替换：旧索引标记为过期（不计入 deleted_ids）
                old_idx = self._id_to_idx[memory_id]
                self._deleted_indices.add(old_idx)
            elif was_deleted:
                # 重新添加已删除的 ID：从 deleted_ids 中移除
                self._deleted_ids.discard(memory_id)

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

            # P2-任务3: 添加后检查是否需要惰性重建
            if self._should_rebuild():
                self._do_lazy_rebuild()

            return True
        except Exception as e:
            logger.error(f"添加向量失败 [{memory_id}]: {e}")
            return False

    # ============================================================
    # 核心 API：搜索（拆分后的子函数）
    # ============================================================

    def _prepare_query(self, query: str) -> np.ndarray:
        """查询预处理：将文本转换为归一化向量。

        调用当前 Embedding 后端生成向量，并转换为 shape (1, dim) 的
        float32 numpy 数组，以便直接用于 FAISS 或 numpy 检索。

        Args:
            query: 查询文本

        Returns:
            shape 为 (1, embedding_dim) 的 float32 向量数组
        """
        return np.array([self._get_embedding(query)], dtype=np.float32)

    def _do_faiss_search(
        self,
        query_vec: np.ndarray,
        top_k: int,
        filters: dict = None,
    ) -> List[Dict[str, Any]]:
        """执行 FAISS 向量搜索，返回候选结果列表。

        使用内积（IP）度量，因向量已 L2 归一化，内积等价于余弦相似度。
        搜索时多取 FILTER_EXPAND_MULTIPLIER 倍候选，经过相似度阈值过滤
        和 metadata 过滤后返回。

        Args:
            query_vec: 查询向量，shape (1, dim)
            top_k: 期望返回数量
            filters: metadata 过滤条件字典

        Returns:
            候选结果列表 [{memory_id, score, similarity, metadata}]，
            按分数降序排列，数量不超过 top_k * FILTER_EXPAND_MULTIPLIER
        """
        k = min(top_k * FILTER_EXPAND_MULTIPLIER, len(self._id_list))
        scores, indices = self._faiss_index.search(query_vec, k)
        results = []
        for i in range(len(indices[0])):
            idx = int(indices[0][i])
            if idx < 0 or idx >= len(self._id_list):
                continue
            # P2-任务3: 过滤已标记删除的索引
            if idx in self._deleted_indices:
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
            if len(results) >= top_k * FILTER_EXPAND_MULTIPLIER:
                break
        return results

    def _do_numpy_search(
        self,
        query_vec: np.ndarray,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """执行纯 numpy 向量搜索，返回所有候选结果。

        使用矩阵乘法计算余弦相似度（向量已归一化，内积即余弦相似度），
        按分数降序构建全部结果列表。不做阈值过滤，交由后续
        ``_apply_dynamic_threshold`` 处理。

        Args:
            query_vec: 查询向量，shape (1, dim)
            top_k: 期望返回数量（当前实现中暂不用于截断，保留接口一致性）

        Returns:
            全部候选结果列表 [{memory_id, score, similarity, metadata}]，
            按分数降序排列
        """
        similarities = (self._vectors @ query_vec.T).flatten()
        sorted_indices = np.argsort(-similarities)
        results = []
        for idx in sorted_indices:
            orig_idx = int(idx)
            # P2-任务3: 过滤已标记删除的索引
            if orig_idx in self._deleted_indices:
                continue
            mid = self._id_list[orig_idx]
            results.append({
                "memory_id": mid,
                "score": round(float(similarities[orig_idx]), 4),
                "similarity": round(float(similarities[orig_idx]), 4),
                "metadata": self._metadata_store.get(mid, {}),
            })
        return results

    def _apply_mmr(
        self,
        results: List[Dict[str, Any]],
        query_vec: np.ndarray,
        top_k: int,
        lambda_param: float = None,
    ) -> List[Dict[str, Any]]:
        """对搜索结果应用 MMR 去重，平衡相关性与多样性。

        当启用 MMR 且结果数量超过 top_k 时，调用 ``_mmr_rerank``
        进行最大边缘相关重排序。否则直接返回原结果。

        Args:
            results: 候选结果列表
            query_vec: 查询向量，shape (1, dim)
            top_k: 期望返回数量
            lambda_param: MMR lambda 参数，None 时使用配置值

        Returns:
            MMR 重排序后的结果列表
        """
        if not self._enable_mmr or len(results) <= top_k:
            return results
        lambda_param = lambda_param if lambda_param is not None else self._mmr_lambda
        return self._mmr_rerank(query_vec[0], results, top_k, lambda_param)

    def _apply_dynamic_threshold(
        self,
        results: List[Dict[str, Any]],
        base_threshold: float = None,
    ) -> List[Dict[str, Any]]:
        """根据结果分数分布动态计算相似度阈值并过滤。

        从结果列表中提取分数数组，调用 ``_dynamic_threshold`` 计算
        自适应阈值，然后返回分数不低于该阈值的结果。

        Args:
            results: 候选结果列表，每项需包含 ``score`` 字段
            base_threshold: 基础相似度阈值，None 时使用配置值

        Returns:
            过滤后的结果列表
        """
        if not results:
            return results
        scores = np.array([r["score"] for r in results], dtype=np.float32)
        dynamic_thresh = self._dynamic_threshold(scores, base_threshold)
        return [r for r in results if r["score"] >= dynamic_thresh]

    def _apply_hybrid_enhancement(
        self,
        results: List[Dict[str, Any]],
        query: str,
    ) -> List[Dict[str, Any]]:
        """对搜索结果应用混合检索增强（向量 + 关键词融合打分）。

        计算每条结果的关键词匹配分数，按 hybrid_alpha 权重与向量
        相似度融合，更新 ``score`` 字段并重新排序。

        Args:
            results: 候选结果列表
            query: 查询文本（用于关键词匹配）

        Returns:
            融合打分后的结果列表，按混合分数降序排列
        """
        if not self._enable_hybrid or not results:
            return results
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
        return results

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        filters: dict = None,
    ) -> List[Dict[str, Any]]:
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
        if len(self._id_list) == 0 or len(self._id_list) == len(self._deleted_indices):
            return []

        try:
            # P2-任务3: 搜索前检查是否需要惰性重建
            if self._should_rebuild():
                self._do_lazy_rebuild()

            query_vec = self._prepare_query(query)

            if self._use_faiss and self._faiss_index is not None:
                # FAISS 搜索 + 阈值过滤 + metadata 过滤
                results = self._do_faiss_search(query_vec, top_k, filters)
                # 混合检索增强
                results = self._apply_hybrid_enhancement(results, query)
                # MMR 去重
                results = self._apply_mmr(results, query_vec, top_k)
                return results[:top_k]
            else:
                # numpy 全量搜索
                results = self._do_numpy_search(query_vec, top_k)
                # 动态阈值过滤
                results = self._apply_dynamic_threshold(results, self._similarity_threshold)
                # metadata 过滤
                if filters:
                    results = [
                        r for r in results
                        if self._match_filters(r.get("metadata", {}), filters)
                    ]
                if not results:
                    return []
                # 取 top_k
                results = results[:top_k]
                # 混合检索增强
                results = self._apply_hybrid_enhancement(results, query)
                # MMR 去重
                results = self._apply_mmr(results, query_vec, top_k)
                return results[:top_k]

        except Exception as e:
            logger.error(f"向量搜索失败: {e}")
            return []

    def delete(self, memory_id: str) -> bool:
        """
        删除一条记忆的向量（标记删除 + 惰性重建）

        采用标记删除策略：删除操作只标记不立即重建索引，
        当删除数达到阈值时在下一次搜索/添加操作中触发惰性重建。
        删除复杂度从 O(n) 降为 O(1)，搜索性能影响极小。

        P2-任务3: 标记删除 + 惰性重建机制
        """
        if memory_id not in self._id_to_idx:
            return False

        if memory_id in self._deleted_ids:
            # 已经标记为删除，直接返回
            return False

        try:
            idx = self._id_to_idx[memory_id]
            self._deleted_ids.add(memory_id)
            self._deleted_indices.add(idx)

            logger.debug(f"标记删除向量 [{memory_id}] (idx={idx})")

            # 检查是否达到重建阈值（不立即重建，惰性触发）
            if self._should_rebuild():
                logger.debug(
                    f"删除数达到重建阈值 "
                    f"(deleted={len(self._deleted_indices)}, "
                    f"total={len(self._id_list)})，将在下次操作时惰性重建"
                )

            return True
        except Exception as e:
            logger.error(f"标记删除向量失败 [{memory_id}]: {e}")
            return False

    # ============================================================
    # P2-任务3: 标记删除 + 惰性重建机制
    # ============================================================

    def _should_rebuild(self) -> bool:
        """检查是否达到惰性重建阈值

        触发条件（满足任一即触发）：
        - 待清理索引数达到总条目数的 rebuild_ratio（默认 20%）
        - 待清理索引数达到 rebuild_abs_threshold（默认 100 条）

        Returns:
            True 表示需要触发重建
        """
        total = len(self._id_list)
        if total == 0:
            return False
        pending = len(self._deleted_indices)
        if pending == 0:
            return False
        ratio_threshold = int(total * self._rebuild_ratio)
        return pending >= ratio_threshold or pending >= self._rebuild_abs_threshold

    def _do_lazy_rebuild(self) -> None:
        """执行惰性重建：清理标记删除的条目并重建索引

        物理压缩向量矩阵和 ID 列表，重建 FAISS 索引。
        重建后清空 _deleted_ids 和 _deleted_indices。
        """
        if not self._deleted_indices:
            return

        deleted_count = len(self._deleted_indices)
        total_before = len(self._id_list)

        logger.info(
            f"触发惰性索引重建: 待清理 {deleted_count} 条, "
            f"总计 {total_before} 条, 比例 {deleted_count/total_before:.1%}"
        )

        # 压缩向量矩阵和 ID 列表
        self._compact_vectors()

        # 重建 FAISS 索引
        if self._use_faiss and self._faiss_index is not None:
            self._rebuild_faiss_from_vectors()

        total_after = len(self._id_list)
        logger.info(f"惰性重建完成: {total_before} -> {total_after} 条向量")

    def _compact_vectors(self) -> None:
        """物理压缩向量矩阵和 ID 列表，移除标记删除的条目

        重建后：
        - _vectors: 只保留活动向量
        - _id_list: 只保留活动 ID
        - _id_to_idx: 更新为新的索引映射
        - _metadata_store: 只保留活动 ID 的元数据
        - _deleted_ids / _deleted_indices: 清空
        """
        if not self._deleted_indices:
            return

        total = len(self._id_list)
        keep_mask = np.ones(total, dtype=bool)
        for idx in self._deleted_indices:
            if 0 <= idx < total:
                keep_mask[idx] = False

        # 压缩向量矩阵
        if self._vectors is not None and self._vectors.shape[0] == total:
            self._vectors = self._vectors[keep_mask]

        # 压缩 ID 列表
        new_id_list = []
        new_id_to_idx: Dict[str, int] = {}
        new_metadata_store: Dict[str, dict] = {}
        new_idx = 0
        for i in range(total):
            if keep_mask[i]:
                mid = self._id_list[i]
                new_id_list.append(mid)
                new_id_to_idx[mid] = new_idx
                if mid in self._metadata_store:
                    new_metadata_store[mid] = self._metadata_store[mid]
                new_idx += 1

        self._id_list = new_id_list
        self._id_to_idx = new_id_to_idx
        self._metadata_store = new_metadata_store

        # 清空删除标记
        self._deleted_ids.clear()
        self._deleted_indices.clear()

    def force_rebuild(self) -> None:
        """强制重建索引（清理所有标记删除的条目）

        无论是否达到阈值，立即执行完整的索引重建。
        可用于定期维护或在批量删除后手动调用。

        P2-任务3: 标记删除 + 惰性重建机制
        """
        if not self._deleted_indices:
            logger.debug("force_rebuild: 没有待清理的条目，跳过")
            return

        logger.info(
            f"强制重建索引: 待清理 {len(self._deleted_indices)} 条, "
            f"总计 {len(self._id_list)} 条"
        )

        self._compact_vectors()

        if self._use_faiss and self._faiss_index is not None:
            self._rebuild_faiss_from_vectors()

        self._save_index()

        logger.info(f"强制重建完成: 当前 {len(self._id_list)} 条活动向量")

    def get_deleted_count(self) -> int:
        """查询当前标记待删除的 memory_id 数量

        Returns:
            已标记删除的唯一 memory_id 数量

        P2-任务3: 标记删除 + 惰性重建机制
        """
        return len(self._deleted_ids)

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
        """重建索引（从 memory_id 列表和向量矩阵重建 FAISS 索引）

        P2-任务3: 重建时清理标记删除的条目，物理压缩向量矩阵。
        """
        # 先清理标记删除的条目
        self._compact_vectors()
        if self._use_faiss:
            self._rebuild_faiss_from_vectors()
        self._save_index()

    def _rebuild_faiss_from_vectors(self) -> None:
        """从 numpy 向量矩阵重建 FAISS 索引（支持 GPU + HNSW/Flat）

        P2-任务2: 支持 HNSW 索引重建。
        """
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
                    self._actual_index_type = "Flat"
                    return
                except Exception as e:
                    logger.warning(f"GPU 索引重建失败，降级到 CPU: {e}")
                    self._gpu_available = False

            # CPU 模式重建
            # P2-任务2: 根据配置选择 HNSW 或 Flat
            if self._index_type.upper() == "HNSW":
                try:
                    self._faiss_index = faiss.IndexHNSWFlat(
                        self._embedding_dim, self._hnsw_m, faiss.METRIC_INNER_PRODUCT
                    )
                    self._faiss_index.hnsw.efConstruction = self._hnsw_ef_construction
                    self._faiss_index.hnsw.efSearch = self._hnsw_ef_search
                    if self._vectors is not None and self._vectors.shape[0] > 0:
                        self._faiss_index.add(self._vectors)
                    self._use_faiss = True
                    self._actual_index_type = "HNSW"
                    logger.info(f"重建 HNSW 索引 ({self._vectors.shape[0] if self._vectors is not None else 0} 条向量)")
                    return
                except Exception as e:
                    logger.warning(f"HNSW 索引重建失败，降级到 Flat: {e}")

            # 降级到 Flat
            self._faiss_index = faiss.IndexFlatIP(self._embedding_dim)
            if self._vectors is not None and self._vectors.shape[0] > 0:
                self._faiss_index.add(self._vectors)
            self._use_faiss = True
            self._actual_index_type = "Flat"
        except Exception as e:
            logger.warning(f"重建 FAISS 索引失败，降级为 numpy: {e}")
            self._use_faiss = False
            self._gpu_available = False
            self._actual_index_type = "numpy"

    # ============================================================
    # P2-任务2: HNSW 迁移工具
    # ============================================================

    def migrate_to_hnsw(self) -> Dict[str, Any]:
        """
        将现有 Flat 索引迁移为 HNSW 索引

        Returns:
            {"success": bool, "message": str, "index_type": str, "total_vectors": int}
        """
        if not self._use_faiss or self._vectors is None:
            return {
                "success": False,
                "message": "FAISS 未启用或无向量数据",
                "index_type": self._actual_index_type,
                "total_vectors": len(self._id_list),
            }

        if self._actual_index_type == "HNSW":
            return {
                "success": True,
                "message": "已经是 HNSW 索引",
                "index_type": "HNSW",
                "total_vectors": len(self._id_list),
            }

        try:
            import faiss

            # 保存当前向量数
            n_vectors = self._vectors.shape[0] if self._vectors is not None else 0

            # 构建新的 HNSW 索引
            new_index = faiss.IndexHNSWFlat(
                self._embedding_dim, self._hnsw_m, faiss.METRIC_INNER_PRODUCT
            )
            new_index.hnsw.efConstruction = self._hnsw_ef_construction
            new_index.hnsw.efSearch = self._hnsw_ef_search

            # 添加所有向量
            if self._vectors is not None and self._vectors.shape[0] > 0:
                new_index.add(self._vectors)

            # 替换旧索引
            self._faiss_index = new_index
            self._actual_index_type = "HNSW"
            self._index_type = "HNSW"

            # 保存到磁盘
            self._save_index()

            logger.info(f"索引迁移完成: Flat → HNSW ({n_vectors} 条向量)")
            return {
                "success": True,
                "message": f"成功迁移 {n_vectors} 条向量到 HNSW 索引",
                "index_type": "HNSW",
                "total_vectors": n_vectors,
            }
        except Exception as e:
            logger.error(f"HNSW 迁移失败: {e}")
            return {
                "success": False,
                "message": str(e),
                "index_type": self._actual_index_type,
                "total_vectors": len(self._id_list),
            }

    def set_ef_search(self, ef_search: int) -> bool:
        """
        动态调整 HNSW 索引的 ef_search 参数

        ef_search 越大，搜索精度越高，但速度越慢。
        建议范围：16 ~ 512，默认 128。

        Args:
            ef_search: 新的 ef_search 值

        Returns:
            是否成功
        """
        if self._actual_index_type != "HNSW" or self._faiss_index is None:
            return False
        try:
            self._faiss_index.hnsw.efSearch = ef_search
            self._hnsw_ef_search = ef_search
            return True
        except Exception as e:
            logger.warning(f"设置 ef_search 失败: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """获取向量库统计信息"""
        active_count = len(self._id_list) - len(self._deleted_indices)
        return {
            "embed_backend": self._embed_backend,
            "embed_model": self._embedding_model,
            "embedding_dim": self._embedding_dim,
            "dimension": self._embedding_dim,  # 兼容别名
            "index_backend": "faiss" if self._use_faiss else "numpy",
            "backend": self._embed_backend,  # 兼容别名
            "total_vectors": active_count,  # P2-任务3: 返回活动向量数
            "total_indexed": len(self._id_list),  # 索引中总条目数（含待删除）
            "deleted_count": len(self._deleted_ids),  # 标记删除的唯一 ID 数
            "pending_cleanup": len(self._deleted_indices),  # 待清理的索引槽位数
            "similarity_threshold": self._similarity_threshold,
            "index_path": self._index_path,
            "enable_mmr": self._enable_mmr,
            "enable_hybrid": self._enable_hybrid,
            # P2-任务2: HNSW 索引信息
            "index_type": self._actual_index_type,
            "hnsw_m": self._hnsw_m if self._actual_index_type == "HNSW" else None,
            "hnsw_ef_construction": self._hnsw_ef_construction if self._actual_index_type == "HNSW" else None,
            "hnsw_ef_search": self._hnsw_ef_search if self._actual_index_type == "HNSW" else None,
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
        return list(dict.fromkeys(queries))[:QUERY_EXPANSION_MAX_VARIANTS]

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
                match_score += min(tf * KEYWORD_MATCH_MAX_TF_FACTOR, 1.0)
        return min(match_score / max(len(tokens), 1), 1.0)

    # ============================================================
    # P2-12: 检索质量增强 - MMR 去重
    # ============================================================

    def _mmr_rerank(
        self,
        query_vec: np.ndarray,
        candidates: List[Dict[str, Any]],
        top_k: int,
        lambda_: float = DEFAULT_MMR_LAMBDA,
    ) -> List[Dict[str, Any]]:
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

    def _dynamic_threshold(self, scores: np.ndarray, base_threshold: float = None) -> float:
        """根据分数分布动态计算相似度阈值。

        Args:
            scores: 分数数组
            base_threshold: 基础相似度阈值，None 时使用配置值

        Returns:
            动态计算后的相似度阈值
        """
        base_threshold = base_threshold if base_threshold is not None else self._similarity_threshold
        if len(scores) == 0:
            return base_threshold
        mean_score = float(np.mean(scores))
        std_score = float(np.std(scores))
        if std_score < self._min_score_variance:
            return base_threshold
        dynamic_thresh = mean_score - DYNAMIC_THRESHOLD_STD_FACTOR * std_score
        dynamic_thresh = max(dynamic_thresh, base_threshold * DYNAMIC_THRESHOLD_MIN_RATIO)
        dynamic_thresh = min(dynamic_thresh, DYNAMIC_THRESHOLD_MAX)
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
# vim: set et ts=4 sw=4:
