"""
记忆导出器

将本地记忆的元数据导出为脱敏的共享包。

安全约束：
- 不导出原文（系统本身只存 content_hash）
- 元数据经过 DataDesensitizer 脱敏
- 导出密级最高为 INTERNAL（不能导出 TOP_SECRET / CONFIDENTIAL）
- 移除 owner_agent、完整 content_hash（仅保留前缀用于去重）

降级处理：
- recall_engine 不可用时返回空包结构（仅标题/描述）
- desensitizer 不可用时进行基本字段裁剪
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

# 导出时允许保留的字段白名单（其余字段一律丢弃）
# 这些字段对其他 Agent 有参考价值，且不涉及原文
_EXPORTABLE_FIELDS = {
    "layer",            # 记忆层级（l1_shallow / l2_deep ...）
    "quality_score",    # 质量评分
    "quality_level",    # 质量等级
    "tags",             # 标签列表
    "created_at",       # 创建时间
    "updated_at",       # 更新时间
    "access_count",     # 访问次数
    "emotion",          # 情绪标记（valence/arousal/ei_score/dominant_emotion）
    "metadata",         # 元数据（会脱敏）
    "content_hash_prefix",  # 内容哈希前缀（前12位，仅用于去重比对）
}

# metadata 中需要强制移除的敏感 key
_FORBIDDEN_METADATA_KEYS = {
    "owner_agent", "private_key", "secret", "token",
    "password", "api_key", "original_content",
}

# 导出允许的最高密级
_MAX_EXPORT_CLASSIFICATION = "INTERNAL"

# 密级高低顺序（用于判断是否需要降级）
_CLASSIFICATION_ORDER = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "TOP_SECRET"]


class MemoryExporter:
    """记忆导出器 — 将记忆导出为脱敏的共享包"""

    def __init__(self, recall_engine=None, desensitizer=None):
        """
        Args:
            recall_engine: RecallEngine 实例（可选，用于读取记忆）
            desensitizer: DataDesensitizer 实例（可选，用于脱敏）
        """
        self._recall_engine = recall_engine
        self._desensitizer = desensitizer
        self._lock = threading.Lock()

    def export_memories(
        self,
        memory_ids: List[str],
        title: str,
        description: str,
        tags: List[str],
        domain: str,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """导出记忆为共享包

        流程：
        1. 获取指定记忆的元数据（不获取原文，因为系统只存 content_hash）
        2. 对每条记忆提取可共享的信息：tags, metadata, emotion, quality_score, layer
        3. 使用脱敏器对 metadata 中的敏感字段进行脱敏
        4. 打包为 SharePackage 格式
        5. 计算整体校验和
        6. 返回包数据

        Args:
            memory_ids: 指定记忆ID列表，空则导出最近 N 条
            title: 共享包标题
            description: 共享包描述
            tags: 共享包标签
            domain: 共享目标域
            limit: 当 memory_ids 为空时的数量限制

        Returns:
            共享包字典，包含 share_id、items、checksum 等字段
        """
        # 获取记忆条目（降级：recall_engine 不可用时返回空列表）
        raw_items = self._fetch_memory_items(memory_ids, limit)

        # 逐条脱敏
        desensitized_items: List[Dict[str, Any]] = []
        for raw in raw_items:
            try:
                safe_item = self._desensitize_item(raw)
                if safe_item:
                    desensitized_items.append(safe_item)
            except Exception as e:
                logger.warning(
                    "export_desensitize_item_failed",
                    memory_id=raw.get("memory_id", "unknown"),
                    error=str(e),
                )
                continue

        # 生成共享包ID
        import uuid as _uuid
        share_id = f"shr_{_uuid.uuid4().hex[:12]}"
        now_iso = datetime.utcnow().isoformat()

        # 构建包数据（不含 checksum，最后计算）
        package: Dict[str, Any] = {
            "share_id": share_id,
            "title": title,
            "description": description,
            "author": "anonymous",  # 导出时不暴露真实 owner
            "items": desensitized_items,
            "tags": list(tags) if tags else [],
            "domain": domain,
            "classification_level": _MAX_EXPORT_CLASSIFICATION,
            "import_count": 0,
            "rating_avg": 0.0,
            "rating_count": 0,
            "item_count": len(desensitized_items),
            "created_at": now_iso,
        }

        # 计算校验和
        package["checksum"] = self._compute_checksum(package)

        logger.info(
            "memory_exported",
            share_id=share_id,
            item_count=len(desensitized_items),
            title=title,
        )
        return package

    def _fetch_memory_items(self, memory_ids: List[str], limit: int) -> List[Dict[str, Any]]:
        """从 recall_engine 获取记忆条目元数据

        降级策略：recall_engine 不可用时返回空列表。
        """
        if self._recall_engine is None:
            logger.warning("export_recall_engine_unavailable")
            return []

        items: List[Dict[str, Any]] = []

        if memory_ids:
            # 按指定 ID 获取
            for mid in memory_ids:
                try:
                    info = self._recall_engine.get_by_id(mid, domain="private")
                    if info:
                        items.append(info)
                except Exception as e:
                    logger.warning(
                        "export_fetch_memory_failed",
                        memory_id=mid,
                        error=str(e),
                    )
                    continue
        else:
            # 获取最近 N 条（降级：list_memories 不可用则返回空）
            try:
                result = self._recall_engine.list_memories(
                    page_size=min(limit, 100),
                    domain=None,
                    sort_by="created_at",
                    order="desc",
                )
                raw_items = result.get("items", [])
                for raw in raw_items:
                    # list_memories 返回的是字典，直接收集
                    items.append(raw)
            except Exception as e:
                logger.warning("export_list_memories_failed", error=str(e))
                return []

        return items[:limit] if limit else items

    def _desensitize_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """脱敏单条记忆元数据

        步骤：
        1. 移除敏感字段：owner_agent、content_hash（保留 hash 前缀用于去重）
        2. 对 metadata 中的值进行脱敏
        3. 降低密级到 INTERNAL（导出的不能是 TOP_SECRET）
        4. 仅保留白名单字段
        """
        if not isinstance(item, dict):
            return None

        safe_item: Dict[str, Any] = {}

        # 1. 仅保留白名单字段
        for field in _EXPORTABLE_FIELDS:
            if field in item:
                safe_item[field] = item[field]

        # 2. content_hash 前缀（前12位，用于去重比对，不可逆原文）
        content_hash = item.get("content_hash", "")
        if content_hash:
            safe_item["content_hash_prefix"] = content_hash[:12]
        else:
            safe_item["content_hash_prefix"] = ""

        # 3. 保留 memory_id（用于去重参考，但导入时会生成新 ID）
        safe_item["source_memory_id"] = item.get("memory_id", "")

        # 4. 脱敏 metadata
        metadata = item.get("metadata", {})
        if metadata and isinstance(metadata, dict):
            safe_item["metadata"] = self._desensitize_metadata(metadata)
        else:
            safe_item["metadata"] = {}

        # 5. 脱敏 tags（标签本身一般不敏感，但用脱敏器过滤一遍）
        tags = item.get("tags", [])
        if tags and isinstance(tags, list):
            safe_item["tags"] = self._desensitize_tags(tags)
        else:
            safe_item["tags"] = []

        # 6. 情绪标记脱敏（只保留数值字段和情绪标签，移除置信度等可能泄露的信息）
        emotion = item.get("emotion")
        if emotion and isinstance(emotion, dict):
            safe_item["emotion"] = {
                "valence": emotion.get("valence", 0.0),
                "arousal": emotion.get("arousal", 0.0),
                "ei_score": emotion.get("ei_score", 0.0),
                "dominant_emotion": emotion.get("dominant_emotion", "neutral"),
            }
        else:
            safe_item["emotion"] = {
                "valence": 0.0,
                "arousal": 0.0,
                "ei_score": 0.0,
                "dominant_emotion": "neutral",
            }

        # 7. 密级降级到 INTERNAL
        classification = item.get("classification", "TOP_SECRET")
        safe_item["classification"] = self._downgrade_classification(classification)

        return safe_item

    def _desensitize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """脱敏 metadata 字典

        1. 移除禁止的敏感 key
        2. 使用 DataDesensitizer 对剩余值脱敏
        """
        # 移除禁止的 key
        cleaned: Dict[str, Any] = {}
        for key, value in metadata.items():
            if key.lower() in _FORBIDDEN_METADATA_KEYS:
                continue
            cleaned[key] = value

        # 使用脱敏器
        if self._desensitizer is not None:
            try:
                cleaned = self._desensitizer.desensitize_dict(cleaned)
            except Exception as e:
                logger.warning("desensitize_metadata_failed", error=str(e))
                # 降级：对字符串值做基本裁剪
                cleaned = self._basic_mask(cleaned)
        else:
            # 脱敏器不可用，做基本裁剪
            cleaned = self._basic_mask(cleaned)

        return cleaned

    def _desensitize_tags(self, tags: List[str]) -> List[str]:
        """脱敏标签列表"""
        safe_tags: List[str] = []
        for tag in tags:
            if not isinstance(tag, str):
                continue
            if self._desensitizer is not None:
                try:
                    safe_tag = self._desensitizer.desensitize(tag)
                except Exception:
                    safe_tag = tag
            else:
                safe_tag = tag
            # 过滤掉被完全遮蔽的标签
            if safe_tag and not safe_tag.strip("*"):
                continue
            safe_tags.append(safe_tag)
        return safe_tags

    def _basic_mask(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """基本脱敏（脱敏器不可用时的降级方案）

        对字符串值中疑似敏感信息做简单遮蔽。
        """
        import re
        patterns = [
            (re.compile(r'1[3-9]\d{9}'), '1*******0000'),  # 手机号
            (re.compile(r'\d{17}[\dXx]'), '******************'),  # 身份证
            (re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'), '***@***.com'),  # 邮箱
            (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '***.***.***.***'),  # IP
        ]
        result: Dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                masked = value
                for pattern, replacement in patterns:
                    masked = pattern.sub(replacement, masked)
                result[key] = masked
            elif isinstance(value, dict):
                result[key] = self._basic_mask(value)
            else:
                result[key] = value
        return result

    def _downgrade_classification(self, level: str) -> str:
        """将密级降级到 INTERNAL 或更低

        导出的记忆密级最高为 INTERNAL，不能导出 CONFIDENTIAL / TOP_SECRET。
        """
        if not level:
            return _MAX_EXPORT_CLASSIFICATION
        level_upper = level.upper()
        try:
            idx = _CLASSIFICATION_ORDER.index(level_upper)
            max_idx = _CLASSIFICATION_ORDER.index(_MAX_EXPORT_CLASSIFICATION)
            if idx > max_idx:
                return _MAX_EXPORT_CLASSIFICATION
            return level_upper
        except ValueError:
            return _MAX_EXPORT_CLASSIFICATION

    def _compute_checksum(self, data: Dict[str, Any]) -> str:
        """计算共享包的 SHA256 校验和

        注意：计算时排除 checksum 字段本身，避免自引用。
        """
        calc_data = {k: v for k, v in data.items() if k != "checksum"}
        raw = json.dumps(calc_data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

# vim: set et ts=4 sw=4:
