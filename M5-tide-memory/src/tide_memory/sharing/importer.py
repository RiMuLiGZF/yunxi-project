"""
记忆导入器

从共享包导入记忆到本地系统的 shared 域。

安全约束：
- 导入的记忆只能写入 shared 域，不能写入 private 或 core
- 导入前校验包完整性（checksum）
- 导入时生成新的 memory_id（不复用源 ID，避免冲突）
- 原文不可恢复（只有元数据），创建的是"参考记忆"

降级处理：
- recall_engine 不可用时返回失败统计（不写入）
- domain_manager 不可用时不做权限校验（默认放行 shared 域写入）
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

# 允许导入的目标域（安全约束：仅 shared）
_ALLOWED_IMPORT_DOMAINS = {"shared"}


class MemoryImporter:
    """记忆导入器 — 从共享包导入记忆到本地系统"""

    def __init__(self, recall_engine=None, domain_manager=None):
        """
        Args:
            recall_engine: RecallEngine 实例（用于 archive_memory 创建新记忆）
            domain_manager: DomainManager 实例（用于权限校验）
        """
        self._recall_engine = recall_engine
        self._domain_manager = domain_manager
        self._lock = threading.Lock()

    def import_package(
        self,
        package: Dict[str, Any],
        target_domain: str = "shared",
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """导入共享记忆包

        流程：
        1. 校验包完整性（checksum）
        2. 安全约束：目标域只能是 shared
        3. 遍历共享记忆条目
        4. 对每条记忆，在 shared 域创建新记忆（使用新 memory_id）
        5. 记录导入日志
        6. 返回导入结果统计

        Args:
            package: 共享包字典
            target_domain: 目标域（仅允许 shared）
            overwrite: 是否覆盖已存在的记忆（目前始终创建新记忆）

        Returns:
            {
                "success": bool,
                "share_id": str,
                "imported_count": int,
                "failed_count": int,
                "new_memory_ids": List[str],
                "errors": List[str],
            }
        """
        result: Dict[str, Any] = {
            "success": False,
            "share_id": package.get("share_id", ""),
            "imported_count": 0,
            "failed_count": 0,
            "new_memory_ids": [],
            "errors": [],
        }

        # 安全约束：目标域只能是 shared
        if target_domain not in _ALLOWED_IMPORT_DOMAINS:
            result["errors"].append(
                f"目标域 '{target_domain}' 不被允许，仅支持 shared 域导入"
            )
            return result

        # 校验包完整性
        if not self._verify_checksum(package):
            result["errors"].append("共享包校验和验证失败，包可能被篡改")
            return result

        items = package.get("items", [])
        if not items:
            result["errors"].append("共享包中没有可导入的记忆条目")
            result["success"] = True  # 空包视为成功
            return result

        # recall_engine 不可用时降级
        if self._recall_engine is None:
            result["errors"].append("recall_engine 不可用，无法导入记忆")
            return result

        # 权限校验（降级：domain_manager 不可用时跳过）
        if self._domain_manager is not None:
            try:
                allowed = self._domain_manager.check_permission(
                    "system", "shared", "write"
                )
                if not allowed:
                    result["errors"].append("系统没有 shared 域的写入权限")
                    return result
            except Exception as e:
                logger.warning("import_permission_check_failed", error=str(e))
                # 降级：权限校验失败时继续导入（共享域默认可写）

        # 逐条导入
        new_memory_ids: List[str] = []
        imported_count = 0
        failed_count = 0
        errors: List[str] = []

        for idx, item in enumerate(items):
            try:
                new_mid = self._create_shared_memory(item, target_domain)
                if new_mid:
                    new_memory_ids.append(new_mid)
                    imported_count += 1
                else:
                    failed_count += 1
                    errors.append(f"条目 {idx}: 创建记忆返回空 ID")
            except Exception as e:
                failed_count += 1
                errors.append(f"条目 {idx}: {str(e)}")
                logger.warning(
                    "import_item_failed",
                    index=idx,
                    source_memory_id=item.get("source_memory_id", "unknown"),
                    error=str(e),
                )

        result["imported_count"] = imported_count
        result["failed_count"] = failed_count
        result["new_memory_ids"] = new_memory_ids
        result["errors"] = errors
        result["success"] = imported_count > 0 or (len(items) == 0)

        logger.info(
            "memory_imported",
            share_id=result["share_id"],
            imported_count=imported_count,
            failed_count=failed_count,
        )
        return result

    def _verify_checksum(self, package: Dict[str, Any]) -> bool:
        """校验包完整性

        重新计算包的 SHA256 并与包内 checksum 字段比对。
        计算时排除 checksum 字段本身。
        """
        stored_checksum = package.get("checksum", "")
        if not stored_checksum:
            # 没有校验和的包，降级为通过（兼容旧包）
            logger.warning("import_package_missing_checksum")
            return True

        calc_data = {k: v for k, v in package.items() if k != "checksum"}
        raw = json.dumps(calc_data, sort_keys=True, default=str).encode("utf-8")
        computed = hashlib.sha256(raw).hexdigest()
        return computed == stored_checksum

    def _create_shared_memory(
        self, item: Dict[str, Any], target_domain: str
    ) -> Optional[str]:
        """从共享条目创建本地记忆，返回新 memory_id

        使用 recall_engine.archive_memory() 创建新记忆。
        原文不可恢复（只有元数据），所以创建的是"参考记忆"。

        构建的 content_hash 使用源 hash 前缀 + 时间戳，确保唯一性。
        """
        if self._recall_engine is None:
            return None

        # 构建 content_hash（源前缀 + 时间戳，确保唯一）
        source_prefix = item.get("content_hash_prefix", "")
        timestamp = datetime.utcnow().isoformat()
        hash_input = f"{source_prefix}:{timestamp}:shared_import".encode("utf-8")
        content_hash = hashlib.sha256(hash_input).hexdigest()

        # 提取 tags 和 metadata
        tags = item.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        # 标记来源
        metadata = dict(metadata)  # 浅拷贝，避免修改原数据
        metadata["_shared_source"] = item.get("source_memory_id", "")
        metadata["_imported_at"] = timestamp
        metadata["_source_classification"] = item.get("classification", "INTERNAL")

        # 情绪上下文
        emotion = item.get("emotion", {})
        emotion_context = None
        if emotion and isinstance(emotion, dict):
            emotion_context = {
                "valence": emotion.get("valence", 0.0),
                "arousal": emotion.get("arousal", 0.0),
                "ei_score": emotion.get("ei_score", 0.0),
                "dominant_emotion": emotion.get("dominant_emotion", "neutral"),
                "confidence": 0.5,  # 导入记忆置信度设为中等
            }

        # 调用 recall_engine.archive_memory()
        # 注意：content_text 为空（原文不可恢复），仅用元数据建索引
        result = self._recall_engine.archive_memory(
            content_hash=content_hash,
            source="shared_import",
            domain=target_domain,
            agent_id="system",  # 导入的记忆归属系统
            tags=tags,
            emotion_context=emotion_context,
            metadata=metadata,
            content_text="",  # 无原文
            store_original=False,
        )

        if isinstance(result, dict):
            return result.get("memory_id")
        return None

# vim: set et ts=4 sw=4:
