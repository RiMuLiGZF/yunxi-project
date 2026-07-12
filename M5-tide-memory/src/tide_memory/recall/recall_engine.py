"""
记忆检索引擎 - 统一入口

整合向量检索、关键词检索、情绪加权检索
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class RecallEngine:
    """
    潮汐记忆检索引擎

    多层级混合检索：
    - 关键词检索（倒排索引，基于tags+metadata）
    - 向量检索（语义相似度）
    - 层级检索（L0→L1→L2→L3）
    - 情绪加权排序
    """

    # RRF 融合参数
    RRF_K = 60  # Reciprocal Rank Fusion 的 k 值

    def __init__(
        self,
        l0=None,
        l1=None,
        l2=None,
        l3=None,
        ei_engine=None,
        keyword_search=None,
        vector_search=None,
    ):
        self._l0 = l0
        self._l1 = l1
        self._l2 = l2
        self._l3 = l3
        self._ei = ei_engine
        self._layer_map = {"l0_beach": l0, "l1_shallow": l1, "l2_deep": l2, "l3_abyss": l3}

        # 关键词检索引擎
        if keyword_search is not None:
            self._keyword = keyword_search
        else:
            from .keyword_search import KeywordSearch
            self._keyword = KeywordSearch()

        # 向量检索引擎
        if vector_search is not None:
            self._vector = vector_search
        else:
            try:
                from .vector_search import VectorSearch
                self._vector = VectorSearch()
            except Exception as e:
                logger.warning(f"向量检索引擎初始化失败，将仅使用关键词检索: {e}")
                self._vector = None

        # 域索引映射：domain -> set of memory_ids（用于域过滤）
        self._domain_index: Dict[str, set] = {}

        # 启动时从L1/L2加载已有记忆到索引
        self._rebuild_index()

    def search(
        self,
        query: str,
        layers: List[str] = None,
        emotion_context: Dict = None,
        top_k: int = 10,
        domain: str = "private",
    ) -> List[Dict]:
        """
        执行多层混合检索

        检索策略：
        1. 关键词倒排索引快速召回（tags + metadata keys + emotion label）
        2. 向量语义检索召回
        3. RRF 融合两路结果
        4. 从各层获取详细信息，做域过滤和层级过滤
        5. 情绪加权重排序
        6. 返回 top_k 结果

        Args:
            query: 查询文本
            layers: 搜索层级，默认 L1+L2
            emotion_context: 情绪上下文，用于加权排序
            top_k: 返回数量
            domain: 记忆域（支持 "private" 或 "private:agent_id" 格式）
        """
        if layers is None:
            layers = ["l1_shallow", "l2_deep"]

        # 解析域信息
        domain_parts = domain.split(":") if domain else []
        domain_type = domain_parts[0] if domain_parts else "private"
        domain_owner = domain_parts[1] if len(domain_parts) > 1 else None

        # 第一步：关键词检索（倒排索引，速度快，召回候选）
        kw_results = self._keyword.search(query, top_k=top_k * 5)

        # 第二步：向量检索（语义相似度，稍慢）
        vec_results = []
        if self._vector is not None:
            try:
                vec_results = self._vector.search(query, top_k=top_k * 5)
            except Exception as e:
                logger.warning(f"向量检索失败，仅使用关键词结果: {e}")

        # 第三步：RRF 融合两路结果
        fused_scores = self._rrf_fusion(kw_results, vec_results)

        # 第四步：从各层获取详细信息 + 域/层级过滤
        all_results = []
        seen_ids = set()

        # 按融合分数排序
        sorted_ids = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

        for mid, fused_score in sorted_ids:
            if mid in seen_ids:
                continue

            # 从各层找完整信息
            item_info = self._get_memory_info(mid, layers, domain_type)
            if not item_info:
                continue

            # 私有域 owner 过滤
            if domain_type == "private" and domain_owner:
                if not self._check_owner(mid, domain_owner, layers):
                    continue

            # 融合得分作为 similarity
            final_score = round(min(1.0, fused_score), 4)
            item_info["similarity"] = final_score
            item_info["fused_score"] = fused_score

            # 标记匹配来源
            in_kw = any(r["memory_id"] == mid for r in kw_results)
            in_vec = any(r["memory_id"] == mid for r in vec_results)
            item_info["keyword_matched"] = in_kw
            item_info["vector_matched"] = in_vec

            if in_kw:
                kw_r = next((r for r in kw_results if r["memory_id"] == mid), {})
                item_info["matched_terms"] = kw_r.get("matched_terms", [])
                item_info["matched_tags"] = kw_r.get("matched_tags", [])
            else:
                item_info["matched_terms"] = []
                item_info["matched_tags"] = []

            all_results.append(item_info)
            seen_ids.add(mid)

            if len(all_results) >= top_k * 2:
                break

        # 第五步：补充层级搜索结果（如果融合结果不够）
        if len(all_results) < top_k:
            for layer_name in layers:
                layer = self._layer_map.get(layer_name)
                if layer is None:
                    continue
                try:
                    layer_results = layer.search(query, domain=domain_type, top_k=top_k)
                except Exception:
                    continue
                for r in layer_results:
                    mid = r.get("memory_id", "")
                    if mid in seen_ids:
                        continue
                    # owner过滤
                    if domain_type == "private" and domain_owner:
                        if not self._check_owner(mid, domain_owner, layers):
                            continue
                    r["layer"] = layer_name
                    r["keyword_matched"] = False
                    r["vector_matched"] = False
                    r["fused_score"] = r.get("similarity", 0.0)
                    all_results.append(r)
                    seen_ids.add(mid)
                    if len(all_results) >= top_k * 2:
                        break
                if len(all_results) >= top_k * 2:
                    break

        # 第六步：情绪加权排序
        if emotion_context and self._ei:
            all_results = self._emotion_rerank(all_results, emotion_context)
        else:
            all_results.sort(key=lambda x: x.get("similarity", 0), reverse=True)

        return all_results[:top_k]

    def _rrf_fusion(
        self,
        kw_results: List[Dict],
        vec_results: List[Dict],
    ) -> Dict[str, float]:
        """
        Reciprocal Rank Fusion (RRF) 融合算法

        公式: score = sum(1 / (k + rank))

        Args:
            kw_results: 关键词检索结果 [{memory_id, score, ...}]
            vec_results: 向量检索结果 [{memory_id, score, ...}]

        Returns:
            {memory_id: fused_score}
        """
        fused: Dict[str, float] = {}
        k = self.RRF_K

        # 关键词检索的排名贡献
        for rank, r in enumerate(kw_results):
            mid = r["memory_id"]
            fused[mid] = fused.get(mid, 0.0) + 1.0 / (k + rank + 1)

        # 向量检索的排名贡献
        for rank, r in enumerate(vec_results):
            mid = r["memory_id"]
            fused[mid] = fused.get(mid, 0.0) + 1.0 / (k + rank + 1)

        return fused

    def _emotion_rerank(self, results: List[Dict], emotion_context: Dict) -> List[Dict]:
        """情绪一致的记忆加权排序"""
        target_ei = emotion_context.get("ei_score", 0.5)
        target_label = emotion_context.get("dominant_emotion", "neutral")

        for r in results:
            base_score = r.get("similarity", 0.5)
            emotion_tags = r.get("emotion_tags", [])

            # 情绪一致性加分
            emotion_bonus = 0.0
            if target_label in emotion_tags:
                emotion_bonus = 0.15

            r["_final_score"] = base_score + emotion_bonus

        results.sort(key=lambda x: x.get("_final_score", 0), reverse=True)
        # 清理临时字段
        for r in results:
            r.pop("_final_score", None)

        return results

    def archive_memory(
        self,
        content_hash: str,
        source: str,
        domain: str,
        agent_id: str,
        tags: List[str],
        emotion_context: Dict = None,
        metadata: Dict = None,
        content_text: str = "",
    ) -> Dict:
        """
        归档新记忆

        Args:
            content_hash: 内容哈希
            source: 来源
            domain: 记忆域
            agent_id: 所属 agent
            tags: 标签列表
            emotion_context: 情绪上下文
            metadata: 元数据
            content_text: 记忆内容文本（用于向量索引，不存储原文）

        Returns:
            {memory_id, layer, created_at}
        """
        from datetime import datetime
        import uuid
        from ..core.models import MemoryItem, MemoryDomain, MemoryLayer

        memory_id = f"mem_{uuid.uuid4().hex[:16]}"

        item = MemoryItem(
            memory_id=memory_id,
            content_hash=content_hash,
            layer=MemoryLayer.L1_SHALLOW,
            domain=MemoryDomain(domain) if domain in ["private", "shared", "core"] else MemoryDomain.PRIVATE,
            owner_agent=agent_id,
            tags=tags,
            metadata=metadata or {},
        )

        # 情绪推断
        if self._ei and emotion_context:
            from ..core.models import EmotionState
            item.emotion = EmotionState(
                valence=emotion_context.get("valence", 0),
                arousal=emotion_context.get("arousal", 0.2),
                ei_score=emotion_context.get("ei_score", 0),
                dominant_emotion=emotion_context.get("dominant_emotion", "neutral"),
                confidence=emotion_context.get("confidence", 0.5),
            )

        # 写入L1
        if self._l1:
            self._l1.add(item)

        # 建立关键词索引（基于tags + metadata keys + emotion label）
        index_text = " ".join(tags) if tags else ""
        if metadata:
            # 只索引metadata的key，不索引value（保护隐私）
            index_text += " " + " ".join(metadata.keys())
        if item.emotion.dominant_emotion:
            index_text += " " + item.emotion.dominant_emotion

        self._keyword.index(
            memory_id=memory_id,
            text=index_text,
            tags=tags,
            metadata={
                "layer": "l1_shallow",
                "domain": domain,
                "source": source,
            },
        )

        # 建立向量索引
        if self._vector is not None and content_text:
            try:
                self._vector.add(
                    memory_id=memory_id,
                    text=content_text,
                    metadata={
                        "layer": "l1_shallow",
                        "domain": domain,
                        "tags": tags,
                    },
                )
            except Exception as e:
                logger.warning(f"向量索引建立失败 [{memory_id}]: {e}")

        # 域索引
        if domain not in self._domain_index:
            self._domain_index[domain] = set()
        self._domain_index[domain].add(memory_id)

        return {
            "memory_id": memory_id,
            "layer": "l1_shallow",
            "created_at": datetime.now().isoformat(),
        }

    def batch_archive(
        self,
        items: List[Dict],
        domain: str = "private",
        agent_id: str = "system",
    ) -> Dict:
        """
        批量归档记忆

        Args:
            items: 记忆项字典列表，每项包含 content/tags/emotion_context/metadata 等
            domain: 记忆域
            agent_id: 所属 agent

        Returns:
            {"success_count": n, "failed": [ids]}
        """
        success_count = 0
        failed = []
        for item_data in items:
            try:
                content = item_data.get("content", "")
                content_hash = item_data.get("content_hash", "")
                if not content_hash and content:
                    import hashlib
                    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

                result = self.archive_memory(
                    content_hash=content_hash,
                    source=item_data.get("source", "batch"),
                    domain=domain,
                    agent_id=item_data.get("agent_id", agent_id),
                    tags=item_data.get("tags", []),
                    emotion_context=item_data.get("emotion_context"),
                    metadata=item_data.get("metadata", {}),
                    content_text=content,
                )
                success_count += 1
            except Exception:
                failed.append(item_data.get("memory_id", f"unknown_{success_count + len(failed)}"))

        return {"success_count": success_count, "failed": failed}

    def batch_delete(
        self,
        memory_ids: List[str],
        domain: str = "private",
    ) -> Dict:
        """
        批量删除记忆（跨层）

        Args:
            memory_ids: 记忆ID列表
            domain: 域（用于权限校验）

        Returns:
            {"deleted_count": n}
        """
        deleted_count = 0
        for mid in memory_ids:
            if self.delete_by_id(mid, domain):
                deleted_count += 1
        return {"deleted_count": deleted_count}

    def list_memories(
        self,
        page_size: int = 20,
        cursor: str = None,
        domain: str = None,
        sort_by: str = "created_at",
        order: str = "desc",
        layers: List[str] = None,
    ) -> Dict:
        """
        分页查询记忆列表（游标分页）

        优先从 L2 层查询（L2 是中期记忆主存储），
        同时合并 L1 层的结果（短期记忆）。

        Args:
            page_size: 每页数量
            cursor: 游标值
            domain: 按域过滤
            sort_by: 排序字段
            order: 排序方向
            layers: 查询层级，默认 L1+L2

        Returns:
            {"items": [...], "next_cursor": "...", "has_more": true/false, "total": n}
        """
        if layers is None:
            layers = ["l1_shallow", "l2_deep"]

        # 解析域类型（用于数据库查询）
        domain_type = None
        if domain:
            domain_parts = domain.split(":")
            domain_type = domain_parts[0] if domain_parts else None

        all_items = []
        total = 0

        # 从各层收集记忆
        for layer_name in layers:
            layer = self._layer_map.get(layer_name)
            if layer is None or not hasattr(layer, "list_items"):
                continue
            try:
                result = layer.list_items(
                    page_size=page_size * 2,  # 每层多取一些，后面统一排序
                    cursor=cursor,
                    domain=domain_type,
                    sort_by=sort_by,
                    order=order,
                )
                all_items.extend(result["items"])
                total += result["total"]
            except Exception:
                continue

        # 统一排序
        reverse = order == "desc"
        if sort_by == "created_at":
            all_items.sort(key=lambda x: x.created_at, reverse=reverse)
        elif sort_by == "quality_score":
            all_items.sort(key=lambda x: x.quality_score, reverse=reverse)
        elif sort_by == "access_count":
            all_items.sort(key=lambda x: x.access_count, reverse=reverse)

        # 取当前页
        page_items = all_items[:page_size]
        has_more = len(all_items) > page_size

        # 构建下一页游标
        next_cursor = None
        if has_more and page_items:
            last_item = page_items[-1]
            if sort_by == "created_at":
                next_cursor = last_item.created_at.isoformat()
            elif sort_by == "quality_score":
                next_cursor = str(last_item.quality_score)
            elif sort_by == "access_count":
                next_cursor = str(last_item.access_count)

        # 转换为字典（脱敏）
        items_dict = []
        for item in page_items:
            items_dict.append({
                "memory_id": item.memory_id,
                "content_available": True,
                "content_hint": "[ENCRYPTED_CONTENT]",
                "layer": item.layer.value,
                "domain": item.domain.value,
                "classification": item.classification.value,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "last_accessed_at": item.last_accessed_at.isoformat() if item.last_accessed_at else None,
                "access_count": item.access_count,
                "quality_score": item.quality_score,
                "quality_level": item.quality_level,
                "tags": item.tags,
                "owner_agent": item.owner_agent,
                "retention_days": item.retention_days,
            })

        return {
            "items": items_dict,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total": total,
        }

    def compress_layer(self, target_layer: str) -> Dict:
        """压缩指定层"""
        layer = self._layer_map.get(target_layer)
        if hasattr(layer, "compress"):
            return layer.compress()
        return {"compressed_count": 0, "remaining_count": 0}

    def generate_reflection(self, scope: str, domain: str) -> Dict:
        """生成反思复盘报告（框架）"""
        total = 0
        for layer_name, layer in self._layer_map.items():
            if layer and hasattr(layer, "count"):
                total += layer.count()

        return {
            "scope": scope,
            "domain": domain,
            "total_memories": total,
            "high_quality_count": 0,
            "key_insights": [],
            "action_items": [],
        }

    def get_by_id(self, memory_id: str, domain: str = "private") -> dict:
        """根据 memory_id 获取单条记忆信息（跨层查找）.

        Args:
            memory_id: 记忆ID
            domain: 域（用于权限校验，支持 "private" 或 "private:agent_id" 格式）

        Returns:
            记忆信息字典，不存在返回 None
        """
        # 解析域信息（与recall方法保持一致）
        domain_parts = domain.split(":") if domain else []
        domain_type = domain_parts[0] if domain_parts else "private"
        domain_owner = domain_parts[1] if len(domain_parts) > 1 else None

        # 按 L0 -> L1 -> L2 -> L3 顺序查找
        layers = ["l0_beach", "l1_shallow", "l2_deep", "l3_abyss"]
        for layer_name in layers:
            layer = self._layer_map.get(layer_name)
            if not layer or not hasattr(layer, "get"):
                continue
            try:
                item = layer.get(memory_id)
            except Exception:
                continue
            if item:
                # 域类型过滤
                if domain_type and item.domain.value != domain_type:
                    return None
                # owner 过滤（私有域且指定了owner时）
                if domain_type == "private" and domain_owner:
                    if item.owner_agent != domain_owner:
                        return None
                # 组装返回信息（脱敏，不返回原文）
                return {
                    "memory_id": item.memory_id,
                    "content_available": True,
                    "content_hint": "[ENCRYPTED_CONTENT]",
                    "encryption": "AES-256-GCM" if layer_name == "l3_abyss" else "none",
                    "layer": layer_name,
                    "domain": item.domain.value,
                    "classification": item.classification.value,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                    "last_accessed_at": item.last_accessed_at.isoformat() if item.last_accessed_at else None,
                    "access_count": item.access_count,
                    "quality_score": item.quality_score,
                    "quality_level": item.quality_level,
                    "tags": item.tags,
                    "owner_agent": item.owner_agent,
                }
        return None

    def delete_by_id(self, memory_id: str, domain: str = "private") -> bool:
        """根据 memory_id 删除记忆（跨层删除）.

        Args:
            memory_id: 记忆ID
            domain: 域（用于权限校验，支持 "private" 或 "private:agent_id" 格式）

        Returns:
            是否删除成功
        """
        # 解析域信息（与recall方法保持一致）
        domain_parts = domain.split(":") if domain else []
        domain_type = domain_parts[0] if domain_parts else "private"
        domain_owner = domain_parts[1] if len(domain_parts) > 1 else None

        deleted = False
        layers = ["l0_beach", "l1_shallow", "l2_deep", "l3_abyss"]
        for layer_name in layers:
            layer = self._layer_map.get(layer_name)
            if not layer or not hasattr(layer, "remove"):
                continue
            try:
                # 先检查是否存在且属于该域
                item = layer.get(memory_id)
                if item:
                    # 域类型过滤
                    if domain_type and item.domain.value != domain_type:
                        continue  # 不属于该域类型，跳过
                    # owner 过滤（私有域且指定了owner时）
                    if domain_type == "private" and domain_owner:
                        if item.owner_agent != domain_owner:
                            continue  # 不属于该owner，跳过
                    if layer.remove(memory_id):
                        deleted = True
            except Exception:
                continue
        return deleted

    def get_stats(self, domain: str = None) -> Dict:
        """获取统计信息"""
        stats = {"total": 0, "layers": {}}
        for name, layer in self._layer_map.items():
            if layer and hasattr(layer, "count"):
                count = layer.count()
                stats["layers"][name] = {"count": count}
                stats["total"] += count

        # 关键词检索统计
        kw_stats = self._keyword.get_stats()
        stats["keyword_index"] = kw_stats

        # 向量检索统计
        if self._vector is not None:
            try:
                vec_stats = self._vector.get_stats()
                stats["vector_index"] = vec_stats
            except Exception:
                pass

        return stats

    def _rebuild_index(self) -> None:
        """从L1/L2层重建关键词索引和向量索引（启动时调用）."""
        indexed_kw = 0
        indexed_vec = 0
        for layer_name in ["l1_shallow", "l2_deep"]:
            layer = self._layer_map.get(layer_name)
            if not layer or not hasattr(layer, "items"):
                continue
            try:
                items = layer.items()
            except Exception:
                continue

            for item in items:
                # 构建索引文本（tags + metadata keys + emotion label）
                index_text = " ".join(item.tags) if item.tags else ""
                if item.metadata:
                    index_text += " " + " ".join(item.metadata.keys())
                if item.emotion and item.emotion.dominant_emotion:
                    index_text += " " + item.emotion.dominant_emotion

                self._keyword.index(
                    memory_id=item.memory_id,
                    text=index_text,
                    tags=item.tags,
                    metadata={
                        "layer": layer_name,
                        "domain": item.domain.value,
                        "quality_score": item.quality_score,
                    },
                )
                indexed_kw += 1

                # 向量索引（使用 content_hash + tags 作为文本代理）
                # 注意：真实内容无法从 item 中获取，这里用标签和元数据构建代理文本
                if self._vector is not None:
                    try:
                        vec_text = self._build_vector_text(item)
                        if vec_text:
                            self._vector.add(
                                memory_id=item.memory_id,
                                text=vec_text,
                                metadata={
                                    "layer": layer_name,
                                    "domain": item.domain.value,
                                    "tags": item.tags,
                                },
                            )
                            indexed_vec += 1
                    except Exception:
                        pass

                # 域索引
                domain_val = item.domain.value
                if domain_val not in self._domain_index:
                    self._domain_index[domain_val] = set()
                self._domain_index[domain_val].add(item.memory_id)

        if indexed_kw > 0:
            logger.info(f"Rebuilt keyword index from layers: {indexed_kw} items")
        if indexed_vec > 0:
            logger.info(f"Rebuilt vector index from layers: {indexed_vec} items")

    def _build_vector_text(self, item) -> str:
        """从记忆项构建用于向量索引的文本（内容不可用时的代理文本）"""
        parts = []
        if item.tags:
            parts.extend(item.tags)
        if item.metadata:
            parts.extend(item.metadata.keys())
            # 也加入一些短的字符串值（如果有）
            for key, val in item.metadata.items():
                if isinstance(val, str) and len(val) < 50:
                    parts.append(val)
        if item.emotion and item.emotion.dominant_emotion:
            parts.append(item.emotion.dominant_emotion)
        return " ".join(parts)

    def _get_memory_info(
        self, memory_id: str, layers: List[str], domain: str
    ) -> Optional[Dict]:
        """根据memory_id获取记忆详细信息."""
        for layer_name in layers:
            layer = self._layer_map.get(layer_name)
            if not layer or not hasattr(layer, "get"):
                continue
            try:
                item = layer.get(memory_id)
            except Exception:
                continue
            if item:
                # 域过滤
                if domain and item.domain.value != domain:
                    return None
                return {
                    "memory_id": item.memory_id,
                    "content_preview": "[SANITIZED]",
                    "layer": layer_name,
                    "domain": item.domain.value,
                    "similarity": 0.0,
                    "created_at": item.created_at.isoformat() if hasattr(item.created_at, 'isoformat') else str(item.created_at),
                    "emotion_tags": [item.emotion.dominant_emotion] if item.emotion and item.emotion.dominant_emotion else [],
                    "quality_score": item.quality_score,
                    "owner_agent": item.owner_agent,
                }
        return None

    def _check_owner(self, memory_id: str, owner: str, layers: List[str]) -> bool:
        """检查记忆的所有者是否匹配."""
        for layer_name in layers:
            layer = self._layer_map.get(layer_name)
            if not layer or not hasattr(layer, "get"):
                continue
            try:
                item = layer.get(memory_id)
            except Exception:
                continue
            if item:
                return item.owner_agent == owner
        return False
# vim: set et ts=4 sw=4:
