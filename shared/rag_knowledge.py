"""
RAG知识库系统 - 云汐大脑知识层
文档管理 + 文本分块 + 向量检索 + 知识增强回复

支持功能：
- 文档入库（txt/md/pdf/docx 等）
- 智能分块（语义分块 + 重叠窗口）
- 向量检索（Ollama embeddings，降级关键词检索）
- 知识库分类管理
- 检索结果重排序
- 上下文组装（RAG prompt构建）
"""

import os
import re
import json
import time
import uuid
import hashlib
import threading
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple


class KnowledgeStatus(str, Enum):
    """知识库状态"""
    PENDING = "pending"      # 待处理
    PROCESSING = "processing"  # 处理中
    READY = "ready"          # 可用
    FAILED = "failed"        # 处理失败


@dataclass
class Document:
    """文档"""
    doc_id: str
    title: str
    source: str  # 文件路径或URL
    source_type: str  # file/url/manual
    category: str = "general"  # 分类
    status: str = KnowledgeStatus.PENDING.value
    total_chunks: int = 0
    total_tokens: int = 0
    
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Document":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Chunk:
    """文本块（检索单元）"""
    chunk_id: str
    doc_id: str
    text: str
    chunk_index: int
    token_count: int = 0
    embedding: Optional[List[float]] = None  # 向量
    
    # 元数据
    section: str = ""  # 所属章节
    keywords: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # 向量可能很大，按需存储
        if self.embedding is None:
            d.pop("embedding", None)
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Chunk":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class RetrievalResult:
    """检索结果"""
    chunk: Chunk
    score: float  # 相似度分数 0-1
    rank: int = 0
    
    @property
    def text(self) -> str:
        return self.chunk.text
    
    @property
    def doc_id(self) -> str:
        return self.chunk.doc_id


class RAGKnowledgeBase:
    """RAG知识库 - 单例模式"""
    
    _instance: Optional["RAGKnowledgeBase"] = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, data_dir: Optional[str] = None):
        if self._initialized:
            return
        self._initialized = True
        
        # 数据目录
        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            self._data_dir = Path.home() / ".yunxi" / "knowledge_base"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._docs_dir = self._data_dir / "documents"
        self._docs_dir.mkdir(exist_ok=True)
        self._chunks_dir = self._data_dir / "chunks"
        self._chunks_dir.mkdir(exist_ok=True)
        
        # 内存缓存
        self._documents: Dict[str, Document] = {}  # doc_id -> Document
        self._chunks: Dict[str, List[Chunk]] = {}  # doc_id -> [Chunk]
        self._lock = threading.RLock()
        
        # 分块参数
        self._chunk_size = 512  # 字符数
        self._chunk_overlap = 100  # 重叠字符数
        
        # Ollama embedding 配置
        self._ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        self._embedding_model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
        self._embedding_available = None  # 延迟检测
        
        # 加载已有数据
        self._load_documents()
    
    # ==================== 存储 ====================
    
    def _docs_index_path(self) -> Path:
        return self._data_dir / "documents_index.json"
    
    def _load_documents(self):
        """加载文档索引"""
        idx_path = self._docs_index_path()
        if idx_path.exists():
            try:
                with open(idx_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._documents = {
                    doc_id: Document.from_dict(doc_data)
                    for doc_id, doc_data in data.items()
                }
            except Exception:
                self._documents = {}
    
    def _save_documents(self):
        """保存文档索引"""
        idx_path = self._docs_index_path()
        with self._lock:
            data = {doc_id: doc.to_dict() for doc_id, doc in self._documents.items()}
            with open(idx_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _chunks_path(self, doc_id: str) -> Path:
        return self._chunks_dir / f"{doc_id}_chunks.json"
    
    def _load_chunks(self, doc_id: str) -> List[Chunk]:
        """加载文档的分块"""
        path = self._chunks_path(doc_id)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return [Chunk.from_dict(c) for c in data]
            except Exception:
                pass
        return []
    
    def _save_chunks(self, doc_id: str, chunks: List[Chunk]):
        """保存文档分块"""
        path = self._chunks_path(doc_id)
        with self._lock:
            data = [c.to_dict() for c in chunks]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    
    # ==================== 文档管理 ====================
    
    def add_document(self,
                     title: str,
                     content: str,
                     source: str = "",
                     source_type: str = "manual",
                     category: str = "general",
                     metadata: Optional[Dict[str, Any]] = None) -> Document:
        """添加文档到知识库
        
        Args:
            title: 文档标题
            content: 文档内容（文本）
            source: 来源（文件路径/URL等）
            source_type: 来源类型（file/url/manual）
            category: 分类
            metadata: 额外元数据
        
        Returns:
            Document对象
        """
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        
        doc = Document(
            doc_id=doc_id,
            title=title,
            source=source or f"manual:{doc_id}",
            source_type=source_type,
            category=category,
            status=KnowledgeStatus.PENDING.value,
            metadata=metadata or {},
        )
        
        # 保存原始文本
        doc_file = self._docs_dir / f"{doc_id}.txt"
        with open(doc_file, "w", encoding="utf-8") as f:
            f.write(content)
        
        with self._lock:
            self._documents[doc_id] = doc
        
        self._save_documents()
        
        # 异步处理（这里同步处理，小文档很快）
        self._process_document(doc_id, content)
        
        return doc
    
    def add_file(self, file_path: str,
                 category: str = "general",
                 title: Optional[str] = None) -> Optional[Document]:
        """从文件添加文档
        
        支持 txt, md 格式。其他格式需要额外解析。
        """
        path = Path(file_path)
        if not path.exists():
            return None
        
        # 读取文本内容
        suffix = path.suffix.lower()
        if suffix in [".txt", ".md", ".markdown"]:
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = path.read_text(encoding="gbk", errors="ignore")
        else:
            # 其他格式暂时只支持纯文本读取
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return None
        
        doc_title = title or path.stem
        return self.add_document(
            title=doc_title,
            content=content,
            source=str(path.absolute()),
            source_type="file",
            category=category,
            metadata={"filename": path.name, "size": path.stat().st_size}
        )
    
    def _process_document(self, doc_id: str, content: str):
        """处理文档：分块 + 向量化"""
        with self._lock:
            if doc_id not in self._documents:
                return
            self._documents[doc_id].status = KnowledgeStatus.PROCESSING.value
        
        try:
            # 1. 文本分块
            chunks = self._chunk_text(content, doc_id)
            
            # 2. 计算向量（如果可用）
            if self._check_embedding_available():
                self._embed_chunks(chunks)
            
            # 3. 保存
            with self._lock:
                self._chunks[doc_id] = chunks
                self._documents[doc_id].total_chunks = len(chunks)
                self._documents[doc_id].total_tokens = sum(c.token_count for c in chunks)
                self._documents[doc_id].status = KnowledgeStatus.READY.value
                self._documents[doc_id].updated_at = time.time()
            
            self._save_chunks(doc_id, chunks)
            self._save_documents()
            
        except Exception as e:
            with self._lock:
                if doc_id in self._documents:
                    self._documents[doc_id].status = KnowledgeStatus.FAILED.value
                    self._documents[doc_id].metadata["error"] = str(e)
            self._save_documents()
    
    # ==================== 文本分块 ====================
    
    def _chunk_text(self, text: str, doc_id: str) -> List[Chunk]:
        """智能分块
        
        策略：
        1. 先按段落分割
        2. 短段落合并，长段落再按句子分割
        3. 保持重叠窗口
        """
        # 预处理
        text = text.strip()
        text = re.sub(r'\n{3,}', '\n\n', text)  # 压缩过多空行
        
        # 按段落分割
        paragraphs = re.split(r'\n\n+', text)
        
        # 合并/拆分成合适大小的块
        chunks_text = []
        current_chunk = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # 如果当前块 + 段落 不超过 chunk_size，追加
            if len(current_chunk) + len(para) + 2 <= self._chunk_size:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
            else:
                # 当前块满了，保存
                if current_chunk:
                    chunks_text.append(current_chunk.strip())
                
                # 如果段落本身很长，按句子再分
                if len(para) > self._chunk_size:
                    sentences = re.split(r'(?<=[。！？.!?])\s*', para)
                    current_chunk = ""
                    for sent in sentences:
                        if len(current_chunk) + len(sent) <= self._chunk_size:
                            current_chunk += sent
                        else:
                            if current_chunk:
                                chunks_text.append(current_chunk.strip())
                            current_chunk = sent
                else:
                    current_chunk = para
        
        if current_chunk:
            chunks_text.append(current_chunk.strip())
        
        # 添加重叠
        final_chunks = []
        for i, chunk_text in enumerate(chunks_text):
            # 从前面的块取尾部作为重叠
            if i > 0 and self._chunk_overlap > 0:
                prev_text = chunks_text[i - 1]
                overlap = prev_text[-self._chunk_overlap:] if len(prev_text) > self._chunk_overlap else prev_text
                chunk_text = overlap + "\n" + chunk_text
            
            final_chunks.append(chunk_text)
        
        # 创建Chunk对象
        chunks = []
        for i, chunk_text in enumerate(final_chunks):
            chunk_id = f"{doc_id}_c{i:04d}"
            # 估算token数（中文约1.5字/token，英文约4字符/token）
            est_tokens = max(10, int(len(chunk_text) / 2))
            
            # 提取关键词（简单的词频统计）
            keywords = self._extract_keywords(chunk_text)
            
            chunk = Chunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                text=chunk_text,
                chunk_index=i,
                token_count=est_tokens,
                keywords=keywords[:5],
            )
            chunks.append(chunk)
        
        return chunks
    
    def _extract_keywords(self, text: str) -> List[str]:
        """简单关键词提取（基于词频）"""
        # 移除标点和空白
        clean = re.sub(r'[^\w\u4e00-\u9fff]', ' ', text)
        words = clean.split()
        
        # 中文按2-gram切分（简单处理）
        all_words = []
        for w in words:
            if re.match(r'^[\u4e00-\u9fff]+$', w) and len(w) >= 2:
                # 提取2-gram
                for i in range(len(w) - 1):
                    all_words.append(w[i:i+2])
            elif len(w) >= 3:
                all_words.append(w.lower())
        
        # 词频统计
        freq: Dict[str, int] = {}
        for w in all_words:
            freq[w] = freq.get(w, 0) + 1
        
        # 按频率排序
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:10]]
    
    # ==================== 向量检索 ====================
    
    def _check_embedding_available(self) -> bool:
        """检查embedding服务是否可用"""
        if self._embedding_available is not None:
            return self._embedding_available
        
        try:
            import requests
            resp = requests.get(f"{self._ollama_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                # 检查是否有embedding模型
                has_embed = any(self._embedding_model in n for n in model_names)
                # 如果没有nomic-embed-text，看看有没有其他模型可用
                if not has_embed:
                    # 尝试用任何模型做embedding（大多数模型都支持）
                    has_embed = len(model_names) > 0
                self._embedding_available = has_embed
            else:
                self._embedding_available = False
        except Exception:
            self._embedding_available = False
        
        return self._embedding_available
    
    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本向量"""
        if not self._check_embedding_available():
            return None
        
        try:
            import requests
            resp = requests.post(
                f"{self._ollama_url}/api/embeddings",
                json={"model": self._embedding_model, "prompt": text[:2000]},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("embedding")
        except Exception:
            pass
        return None
    
    def _embed_chunks(self, chunks: List[Chunk]):
        """批量计算分块向量"""
        for chunk in chunks:
            if chunk.embedding is None:
                emb = self._get_embedding(chunk.text)
                if emb is not None:
                    chunk.embedding = emb
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """余弦相似度"""
        if len(a) != len(b):
            return 0.0
        
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot / (norm_a * norm_b)
    
    # ==================== 检索 ====================
    
    def search(self, query: str,
               category: Optional[str] = None,
               limit: int = 5,
               min_score: float = 0.3) -> List[RetrievalResult]:
        """检索相关知识
        
        Args:
            query: 查询文本
            category: 按分类过滤
            limit: 返回结果数
            min_score: 最低相似度
        
        Returns:
            检索结果列表（按相似度排序）
        """
        all_chunks = []
        
        with self._lock:
            for doc_id, doc in self._documents.items():
                if doc.status != KnowledgeStatus.READY.value:
                    continue
                if category and doc.category != category:
                    continue
                
                # 加载分块（如果没在内存中）
                if doc_id not in self._chunks:
                    self._chunks[doc_id] = self._load_chunks(doc_id)
                
                all_chunks.extend(self._chunks[doc_id])
        
        if not all_chunks:
            return []
        
        # 决定检索方式
        use_vector = self._check_embedding_available() and all(
            c.embedding is not None for c in all_chunks
        )
        
        if use_vector:
            # 向量检索
            query_embedding = self._get_embedding(query)
            if query_embedding is None:
                use_vector = False
        
        results: List[RetrievalResult] = []
        
        if use_vector and query_embedding:
            # 向量相似度检索
            for chunk in all_chunks:
                if chunk.embedding is not None:
                    score = self._cosine_similarity(query_embedding, chunk.embedding)
                    if score >= min_score:
                        results.append(RetrievalResult(chunk=chunk, score=score))
        else:
            # 降级：关键词检索（BM25简化版）
            query_keywords = set(self._extract_keywords(query))
            
            for chunk in all_chunks:
                chunk_keywords = set(chunk.keywords)
                if not query_keywords or not chunk_keywords:
                    continue
                
                # 计算关键词匹配度
                intersection = query_keywords & chunk_keywords
                if not intersection:
                    continue
                
                # 简单的TF-IDF风格评分
                score = len(intersection) / len(query_keywords) * 0.6
                
                # 文本包含加成
                query_lower = query.lower()
                text_lower = chunk.text.lower()
                if query_lower in text_lower:
                    score += 0.3
                
                if score >= min_score:
                    results.append(RetrievalResult(chunk=chunk, score=min(1.0, score)))
        
        # 排序
        results.sort(key=lambda r: r.score, reverse=True)
        
        # 重排（多样性：避免同一文档占太多结果）
        reranked = self._diversity_rerank(results, limit)
        
        # 设置排名
        for i, r in enumerate(reranked):
            r.rank = i + 1
        
        return reranked[:limit]
    
    def _diversity_rerank(self, results: List[RetrievalResult], limit: int) -> List[RetrievalResult]:
        """多样性重排：确保结果来自不同文档"""
        if len(results) <= limit:
            return results
        
        doc_counts: Dict[str, int] = {}
        reranked = []
        
        for r in results:
            doc_id = r.doc_id
            current_count = doc_counts.get(doc_id, 0)
            
            # 每个文档最多占2个结果
            if current_count < 2:
                reranked.append(r)
                doc_counts[doc_id] = current_count + 1
            
            if len(reranked) >= limit:
                break
        
        return reranked
    
    # ==================== RAG上下文构建 ====================
    
    def build_context(self, query: str,
                      category: Optional[str] = None,
                      max_chunks: int = 3,
                      max_tokens: int = 1500) -> Tuple[str, List[RetrievalResult]]:
        """构建RAG上下文
        
        Args:
            query: 查询
            category: 知识库分类
            max_chunks: 最大块数
            max_tokens: 最大token数
        
        Returns:
            (上下文字符串, 检索结果列表)
        """
        results = self.search(query, category=category, limit=max_chunks)
        
        if not results:
            return "", []
        
        # 组装上下文
        context_parts = []
        total_tokens = 0
        used_results = []
        
        for result in results:
            chunk = result.chunk
            if total_tokens + chunk.token_count > max_tokens:
                continue
            
            doc = self._documents.get(chunk.doc_id)
            source = doc.title if doc else "未知来源"
            
            context_parts.append(
                f"【来源：{source}】\n{chunk.text}"
            )
            total_tokens += chunk.token_count
            used_results.append(result)
        
        context = "\n\n---\n\n".join(context_parts)
        return context, used_results
    
    def build_rag_prompt(self, query: str,
                         system_prompt: str = "",
                         category: Optional[str] = None) -> Tuple[str, bool]:
        """构建RAG增强的prompt
        
        Returns:
            (完整prompt, 是否使用了RAG)
        """
        context, results = self.build_context(query, category=category)
        
        if not context:
            return query, False
        
        rag_instruction = (
            "请根据以下参考资料回答用户的问题。"
            "如果参考资料中没有相关信息，请基于你的知识回答，但请说明。\n\n"
            "===== 参考资料 =====\n"
            f"{context}\n"
            "===== 参考资料结束 =====\n\n"
            f"用户问题：{query}\n\n"
            "请回答："
        )
        
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{rag_instruction}"
        else:
            full_prompt = rag_instruction
        
        return full_prompt, True
    
    # ==================== 知识库管理 ====================
    
    def list_documents(self, category: Optional[str] = None) -> List[Document]:
        """列出所有文档"""
        with self._lock:
            docs = list(self._documents.values())
            if category:
                docs = [d for d in docs if d.category == category]
            docs.sort(key=lambda d: d.created_at, reverse=True)
            return docs
    
    def get_document(self, doc_id: str) -> Optional[Document]:
        """获取文档信息"""
        with self._lock:
            return self._documents.get(doc_id)
    
    def delete_document(self, doc_id: str) -> bool:
        """删除文档"""
        with self._lock:
            if doc_id not in self._documents:
                return False
            
            # 删除索引
            del self._documents[doc_id]
            
            # 删除内存中的分块
            self._chunks.pop(doc_id, None)
            
            # 删除分块文件
            chunk_path = self._chunks_path(doc_id)
            if chunk_path.exists():
                chunk_path.unlink()
            
            # 删除原始文件
            doc_file = self._docs_dir / f"{doc_id}.txt"
            if doc_file.exists():
                doc_file.unlink()
        
        self._save_documents()
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """获取知识库统计"""
        with self._lock:
            total_docs = len(self._documents)
            ready_docs = sum(
                1 for d in self._documents.values()
                if d.status == KnowledgeStatus.READY.value
            )
            total_chunks = sum(d.total_chunks for d in self._documents.values())
            total_tokens = sum(d.total_tokens for d in self._documents.values())
            
            categories = {}
            for d in self._documents.values():
                categories[d.category] = categories.get(d.category, 0) + 1
        
        return {
            "total_documents": total_docs,
            "ready_documents": ready_docs,
            "total_chunks": total_chunks,
            "total_tokens_est": total_tokens,
            "categories": categories,
            "vector_search_available": self._check_embedding_available(),
        }


# 全局单例获取函数
_rag_instance: Optional[RAGKnowledgeBase] = None


def get_rag_knowledge_base() -> RAGKnowledgeBase:
    """获取RAG知识库单例"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = RAGKnowledgeBase()
    return _rag_instance
