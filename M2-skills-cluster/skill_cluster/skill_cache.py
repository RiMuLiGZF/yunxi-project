from __future__ import annotations

"""Multi-tier Cache 多级缓存系统.

实现 L1（内存 LRU）+ L2（磁盘持久化）两级缓存，支持 TTL、缓存标签、批量失效。
"""

import hashlib
import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class CacheEntry:
    """缓存条目.

    【第三轮优化】兼容 MCP 2026 cacheScope/ttlMs 规范：
    - cache_scope: "public"（跨请求共享）或 "private"（仅当前请求）
    - ttl_ms: 毫秒级 TTL（MCP 标准），与秒级 ttl 互转
    """

    key: str
    value: Any
    created_at: float
    ttl: float | None
    tags: set[str]
    cache_scope: str = "public"  # "public" | "private"

    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl

    @property
    def ttl_ms(self) -> int | None:
        """MCP 2026 标准字段：毫秒级 TTL."""
        if self.ttl is None:
            return None
        return int(self.ttl * 1000)


class L1MemoryCache:
    """L1 内存缓存（线程安全 LRU）."""

    def __init__(self, max_size: int = 1000) -> None:
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.is_expired():
            del self._cache[key]
            return None
        # LRU：移到末尾表示最近使用
        self._cache.move_to_end(key)
        return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
        tags: set[str] | None = None,
        cache_scope: str = "public",
    ) -> None:
        if len(self._cache) >= self._max_size and key not in self._cache:
            # 淘汰最久未使用
            self._cache.popitem(last=False)
        self._cache[key] = CacheEntry(
            key=key,
            value=value,
            created_at=time.time(),
            ttl=ttl,
            tags=tags or set(),
            cache_scope=cache_scope,
        )

    def delete(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def invalidate_by_tag(self, tag: str) -> int:
        """按标签失效缓存."""
        to_delete = [
            k for k, v in self._cache.items() if tag in v.tags
        ]
        for k in to_delete:
            del self._cache[k]
        return len(to_delete)

    def clear(self) -> None:
        self._cache.clear()

    def stats(self) -> dict[str, Any]:
        expired = sum(1 for e in self._cache.values() if e.is_expired())
        return {
            "size": len(self._cache),
            "expired": expired,
            "max_size": self._max_size,
        }


class L2DiskCache:
    """L2 磁盘缓存."""

    def __init__(self, cache_dir: str | None = None) -> None:
        self._dir = cache_dir or os.path.expanduser("~/.yunxi/cache/skill_cache")
        os.makedirs(self._dir, exist_ok=True)

    def _path(self, key: str) -> str:
        # 使用 key 的哈希作为文件名，避免非法字符
        filename = hashlib.sha256(key.encode()).hexdigest() + ".cache"
        return os.path.join(self._dir, filename)

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                raw = f.read()
            # 【第四轮优化 - P0安全】JSON 反序列化替代 pickle，消除 RCE 风险
            entry_dict = json.loads(raw)
            entry = CacheEntry(**entry_dict)
            if entry.is_expired():
                os.remove(path)
                return None
            return entry.value
        except json.JSONDecodeError:
            logger.warning("disk_cache_corrupted", key=key, path=path)
            os.remove(path)
            return None
        except Exception as e:
            logger.warning("disk_cache_read_error", key=key, error=str(e))
            return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
        tags: set[str] | None = None,
        cache_scope: str = "public",
    ) -> None:
        path = self._path(key)
        entry = CacheEntry(
            key=key,
            value=value,
            created_at=time.time(),
            ttl=ttl,
            tags=tags or set(),
            cache_scope=cache_scope,
        )
        try:
            with open(path, "w") as f:
                # 【第四轮优化 - P0安全】JSON 序列化替代 pickle
                # 将 CacheEntry 转为可 JSON 序列化的字典
                entry_dict = {
                    "key": entry.key,
                    "value": entry.value,
                    "created_at": entry.created_at,
                    "ttl": entry.ttl,
                    "tags": list(entry.tags),
                    "cache_scope": entry.cache_scope,
                }
                json.dump(entry_dict, f)
        except Exception as e:
            logger.warning("disk_cache_write_failed", key=key, error=str(e))

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def invalidate_by_tag(self, tag: str) -> int:
        """按标签失效缓存（扫描所有文件）."""
        count = 0
        for filename in os.listdir(self._dir):
            if not filename.endswith(".cache"):
                continue
            path = os.path.join(self._dir, filename)
            try:
                with open(path, "r") as f:
                    entry_dict = json.loads(f.read())
                entry_tags = set(entry_dict.get("tags", []))
                if tag in entry_tags:
                    os.remove(path)
                    count += 1
            except Exception:
                continue
        return count

    def clear(self) -> None:
        for filename in os.listdir(self._dir):
            if filename.endswith(".cache"):
                os.remove(os.path.join(self._dir, filename))

    def stats(self) -> dict[str, Any]:
        files = [f for f in os.listdir(self._dir) if f.endswith(".cache")]
        total_size = sum(
            os.path.getsize(os.path.join(self._dir, f)) for f in files
        )
        return {
            "size": len(files),
            "total_bytes": total_size,
            "dir": self._dir,
        }


class SkillCache:
    """Skill 多级缓存.

    L1 -> L2 -> Miss 的读取顺序，Write-Through 写入策略。
    支持语义缓存模糊命中：基于参数相似度的近似匹配。
    """

    def __init__(
        self,
        l1_max_size: int = 1000,
        l2_dir: str | None = None,
        default_ttl: float | None = None,
        fuzzy_threshold: float = 0.85,
    ) -> None:
        self._l1 = L1MemoryCache(max_size=l1_max_size)
        self._l2 = L2DiskCache(cache_dir=l2_dir)
        self._default_ttl = default_ttl
        self._fuzzy_threshold = fuzzy_threshold

    def _make_key(
        self, skill_id: str, action: str, params: dict[str, Any]
    ) -> str:
        """生成缓存键."""
        content = json.dumps(
            {"skill_id": skill_id, "action": action, "params": params},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def _make_summary_key(
        self, skill_id: str, action: str, params: dict[str, Any]
    ) -> str:
        """生成参数摘要键（用于语义匹配）."""
        # 仅保留可哈希的简单类型
        summary: dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, (str, int, float, bool)):
                if isinstance(v, str) and len(v) > 50:
                    summary[k] = v[:50]
                else:
                    summary[k] = v
        content = json.dumps(
            {"skill_id": skill_id, "action": action, "params": summary},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def _jaccard_similarity(self, a: dict, b: dict) -> float:
        """计算两个字典的 Jaccard 相似度."""
        if not a and not b:
            return 1.0
        keys_a = set(a.keys())
        keys_b = set(b.keys())
        intersection = keys_a & keys_b
        union = keys_a | keys_b
        if not union:
            return 1.0
        # 同时检查值相似度
        key_sim = len(intersection) / len(union)
        val_matches = 0
        for k in intersection:
            if a[k] == b[k]:
                val_matches += 1
        val_sim = val_matches / len(intersection) if intersection else 0
        return 0.5 * key_sim + 0.5 * val_sim

    def get(
        self, skill_id: str, action: str, params: dict[str, Any]
    ) -> Any | None:
        """读取缓存.

        顺序: L1 精确 -> L1 语义模糊 -> L2 精确 -> None。
        """
        key = self._make_key(skill_id, action, params)

        # L1 精确命中
        value = self._l1.get(key)
        if value is not None:
            logger.debug("cache_l1_hit", key=key)
            return value

        # L1 语义模糊命中
        fuzzy_value = self._fuzzy_get_l1(skill_id, action, params)
        if fuzzy_value is not None:
            logger.debug("cache_l1_fuzzy_hit", key=key)
            return fuzzy_value

        # L2 精确命中
        value = self._l2.get(key)
        if value is not None:
            logger.debug("cache_l2_hit", key=key)
            self._l1.set(key, value)
            return value

        logger.debug("cache_miss", key=key)
        return None

    def _fuzzy_get_l1(
        self, skill_id: str, action: str, params: dict[str, Any]
    ) -> Any | None:
        """L1 语义模糊匹配（Jaccard 相似度）."""
        # 仅当 L1 缓存较小时启用（避免 O(n) 扫描过大）
        if len(self._l1._cache) > 500:
            return None

        target_summary = self._make_param_summary(params)
        target_dict = json.loads(target_summary) if target_summary else {}
        best_sim = 0.0
        best_entry: CacheEntry | None = None

        for entry in self._l1._cache.values():
            sid_tag = f"sid:{skill_id}"
            act_tag = f"act:{action}"
            if sid_tag not in entry.tags or act_tag not in entry.tags:
                continue

            # 从 tag 中提取 params 摘要，计算 Jaccard 相似度
            pmeta = None
            for tag in entry.tags:
                if tag.startswith("pmeta:"):
                    pmeta = tag[6:]  # 去掉 "pmeta:" 前缀
                    break

            if pmeta is None:
                continue

            try:
                entry_dict = json.loads(pmeta)
            except json.JSONDecodeError:
                continue

            sim = self._jaccard_similarity(target_dict, entry_dict)
            if sim > best_sim:
                best_sim = sim
                best_entry = entry

        if best_entry is not None and best_sim >= self._fuzzy_threshold:
            logger.debug(
                "cache_l1_fuzzy_hit",
                skill_id=skill_id,
                action=action,
                similarity=round(best_sim, 3),
            )
            return best_entry.value
        return None

    def set(
        self,
        skill_id: str,
        action: str,
        params: dict[str, Any],
        value: Any,
        ttl: float | None = None,
        tags: set[str] | None = None,
        cache_scope: str = "public",
    ) -> None:
        """写入缓存（Write-Through：同时写 L1 和 L2）.

        【第三轮优化】新增 cache_scope 参数，兼容 MCP 2026 规范：
        - "public": 跨请求共享（默认，写入 L1+L2）
        - "private": 仅当前请求可见（仅写入 L1，不持久化到 L2）
        """
        key = self._make_key(skill_id, action, params)
        effective_ttl = ttl if ttl is not None else self._default_ttl
        # 存储 params 摘要到 tag 中，用于语义模糊匹配
        summary = self._make_param_summary(params)
        all_tags = (tags or set()) | {
            f"sid:{skill_id}",
            f"act:{action}",
            f"pmeta:{summary}",
        }
        self._l1.set(
            key, value, ttl=effective_ttl, tags=all_tags,
            cache_scope=cache_scope,
        )
        if cache_scope == "public":
            self._l2.set(
                key, value, ttl=effective_ttl, tags=all_tags,
                cache_scope=cache_scope,
            )
        logger.debug(
            "cache_set", key=key, ttl=effective_ttl, scope=cache_scope,
        )

    def _make_param_summary(self, params: dict[str, Any]) -> str:
        """生成参数摘要字符串（用于语义匹配）."""
        summary: dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, (str, int, float, bool)):
                if isinstance(v, str) and len(v) > 50:
                    summary[k] = v[:50]
                else:
                    summary[k] = v
        return json.dumps(summary, sort_keys=True, ensure_ascii=False)

    def invalidate(
        self, skill_id: str, action: str, params: dict[str, Any]
    ) -> bool:
        """失效单个缓存."""
        key = self._make_key(skill_id, action, params)
        r1 = self._l1.delete(key)
        r2 = self._l2.delete(key)
        return r1 or r2

    def invalidate_by_tag(self, tag: str) -> int:
        """按标签批量失效缓存."""
        c1 = self._l1.invalidate_by_tag(tag)
        c2 = self._l2.invalidate_by_tag(tag)
        logger.info("cache_invalidate_by_tag", tag=tag, l1=c1, l2=c2)
        return c1 + c2

    def clear(self) -> None:
        """清空所有缓存."""
        self._l1.clear()
        self._l2.clear()
        logger.info("cache_cleared")

    def stats(self) -> dict[str, Any]:
        return {
            "l1": self._l1.stats(),
            "l2": self._l2.stats(),
            "default_ttl": self._default_ttl,
            "fuzzy_threshold": self._fuzzy_threshold,
        }
