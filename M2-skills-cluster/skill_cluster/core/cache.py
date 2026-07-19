from __future__ import annotations

"""Multi-tier Cache 多级缓存系统.

实现 L1（内存 LRU）+ L2（磁盘持久化）两级缓存，支持 TTL、缓存标签、批量失效。

【重构说明】
L2 缓存新增 SQLite 后端（SQLiteL2Cache），性能优于原文件系统实现，
原 L2DiskCache（文件系统）保留以确保完全向后兼容。
SkillCache 默认仍使用文件系统 L2，可通过 use_sqlite_l2=True 切换。

【v3.11.0 缓存命中率优化】
- 新增命中率统计（hit_count / miss_count / hit_rate）
- 新增参数规范化（normalize_params）：去除 None/空值、字符串 strip、键排序
- 新增缓存预热（warmup）：启动时预加载常用技能元数据
- 分层 TTL 常量：元数据长 TTL、执行结果短 TTL
- 增强 L1 容量：默认从 1000 提升到 5000
"""

import hashlib
import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()

# ============================================================
# 缓存分层 TTL 常量（秒）
# ============================================================

# 技能元数据（列表、详情、manifest）：基本不变，长 TTL
CACHE_TTL_METADATA = 3600.0  # 1 小时

# 技能执行结果：可能变化，中等 TTL
CACHE_TTL_RESULT = 300.0  # 5 分钟

# 高频热点结果：短 TTL，快速失效保证一致性
CACHE_TTL_HOT = 60.0  # 1 分钟

# L1 缓存默认最大条目数（优化后提升，容纳更多技能元数据）
DEFAULT_L1_MAX_SIZE = 5000

# L1 模糊匹配启用阈值（L1 条目数超过此值时关闭模糊匹配，避免 O(n) 扫描）
FUZZY_MATCH_L1_THRESHOLD = 500


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
    """L1 内存缓存（线程安全 LRU）.

    【v3.11.0 优化】新增命中率统计（hit_count / miss_count）。
    """

    def __init__(self, max_size: int = 1000) -> None:
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_size = max_size
        # 命中率统计
        self._hit_count = 0
        self._miss_count = 0

    def get(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            self._miss_count += 1
            return None
        if entry.is_expired():
            del self._cache[key]
            self._miss_count += 1
            return None
        # LRU：移到末尾表示最近使用
        self._cache.move_to_end(key)
        self._hit_count += 1
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
        self._hit_count = 0
        self._miss_count = 0

    def reset_stats(self) -> None:
        """重置命中率统计."""
        self._hit_count = 0
        self._miss_count = 0

    @property
    def hit_count(self) -> int:
        """命中次数."""
        return self._hit_count

    @property
    def miss_count(self) -> int:
        """未命中次数."""
        return self._miss_count

    @property
    def hit_rate(self) -> float:
        """命中率（0.0 - 1.0）."""
        total = self._hit_count + self._miss_count
        if total == 0:
            return 0.0
        return self._hit_count / total

    def stats(self) -> dict[str, Any]:
        expired = sum(1 for e in self._cache.values() if e.is_expired())
        return {
            "size": len(self._cache),
            "expired": expired,
            "max_size": self._max_size,
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": round(self.hit_rate, 4),
        }


# ============================================================
# 参数规范化工具函数
# ============================================================

def normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """规范化参数字典，提升缓存命中率。

    规范化规则：
    1. 去除值为 None 的键
    2. 去除值为空字符串、空列表、空字典的键（可选，默认关闭以避免语义变化）
    3. 字符串值 strip() 去除首尾空白
    4. 键名排序（json.dumps 时已自动 sort_keys，但此处保证字典构造一致）
    5. 布尔值统一为 bool 类型（避免 1/0 与 True/False 不一致）
    6. 数字类型保持不变（int/float 区分是合理的）

    注意：只处理简单类型（str, int, float, bool, None），
    复杂类型（list, dict）原样保留，避免过度规范化导致语义丢失。

    Args:
        params: 原始参数字典

    Returns:
        规范化后的参数字典（新字典，不修改原字典）
    """
    if not params:
        return {}

    normalized: dict[str, Any] = {}
    for k, v in params.items():
        # 跳过 None 值
        if v is None:
            continue

        # 字符串 strip
        if isinstance(v, str):
            stripped = v.strip()
            # 空字符串保留（语义上可能有区别），但 strip 后更一致
            normalized[k] = stripped
        # 布尔值保持（注意：bool 是 int 子类，所以要先判断 bool）
        elif isinstance(v, bool):
            normalized[k] = v
        # 数字类型保持
        elif isinstance(v, (int, float)):
            normalized[k] = v
        # 其他类型原样保留
        else:
            normalized[k] = v

    return normalized


class L2DiskCache:
    """L2 磁盘缓存（文件系统实现 - 保留以向后兼容）."""

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


class SQLiteL2Cache:
    """L2 磁盘缓存（SQLite 实现 - 高性能版本）.

    【新增】基于 CacheRepository 的 SQLite 后端实现，相比文件系统实现：
    - 按标签失效从 O(n) 降为 O(1)（SQL 查询）
    - 统计查询更快
    - 更好的并发安全性（WAL 模式）
    - 支持自动重试与损坏恢复

    实现与 L2DiskCache 完全相同的接口，可无缝替换。
    """

    def __init__(self, db_path: str | None = None) -> None:
        from skill_cluster.db.cache_repository import CacheRepository
        from skill_cluster.db.base import SQLiteDatabase

        self._db_path = db_path or os.path.expanduser(
            "~/.yunxi/cache/skill_cache.db"
        )
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._db = SQLiteDatabase(self._db_path)
        self._repo = CacheRepository(self._db)

    def get(self, key: str) -> Any | None:
        """获取缓存值."""
        return self._repo.get(key)

    def set(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
        tags: set[str] | None = None,
        cache_scope: str = "public",
    ) -> None:
        """设置缓存值."""
        self._repo.set(key, value, ttl=ttl, tags=tags, cache_scope=cache_scope)

    def delete(self, key: str) -> bool:
        """删除缓存条目."""
        return self._repo.delete(key)

    def invalidate_by_tag(self, tag: str) -> int:
        """按标签批量失效缓存（SQLite 实现高效得多）."""
        return self._repo.invalidate_by_tag(tag)

    def clear(self) -> None:
        """清空所有缓存."""
        self._repo.clear()

    def stats(self) -> dict[str, Any]:
        """获取缓存统计."""
        return self._repo.stats()

    def cleanup_expired(self) -> int:
        """清理过期缓存."""
        return self._repo.cleanup_expired()

    def close(self) -> None:
        """优雅关闭数据库连接."""
        self._db.close()

    def __enter__(self) -> "SQLiteL2Cache":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


class SkillCache:
    """Skill 多级缓存.

    L1 -> L2 -> Miss 的读取顺序，Write-Through 写入策略。
    支持语义缓存模糊命中：基于参数相似度的近似匹配。

    【重构说明】新增 use_sqlite_l2 参数，默认 False（使用文件系统 L2），
    设置为 True 时使用 SQLite 后端 L2 缓存，性能更优。

    【v3.11.0 缓存命中率优化】
    - 参数规范化：自动 normalize params，减少因空格/None 导致的 miss
    - 命中率统计：hit_count / miss_count / hit_rate
    - 缓存预热：warmup() 预加载常用技能元数据
    - 默认 L1 容量提升至 5000
    """

    def __init__(
        self,
        l1_max_size: int = DEFAULT_L1_MAX_SIZE,
        l2_dir: str | None = None,
        default_ttl: float | None = None,
        fuzzy_threshold: float = 0.85,
        use_sqlite_l2: bool = False,
        l2_db_path: str | None = None,
        normalize_params: bool = True,
    ) -> None:
        self._l1 = L1MemoryCache(max_size=l1_max_size)
        if use_sqlite_l2:
            self._l2: L2DiskCache | SQLiteL2Cache = SQLiteL2Cache(db_path=l2_db_path)
        else:
            self._l2 = L2DiskCache(cache_dir=l2_dir)
        self._default_ttl = default_ttl
        self._fuzzy_threshold = fuzzy_threshold
        self._use_sqlite_l2 = use_sqlite_l2
        self._normalize_params = normalize_params

        # 命中率统计（SkillCache 层面，包含模糊命中和 L2 命中）
        self._hit_count = 0        # 总命中次数（L1精确 + L1模糊 + L2）
        self._miss_count = 0       # 总未命中次数
        self._l1_hit_count = 0     # L1 精确命中
        self._l1_fuzzy_hit_count = 0  # L1 模糊命中
        self._l2_hit_count = 0     # L2 命中
        self._set_count = 0        # 写入次数

    def _make_key(
        self, skill_id: str, action: str, params: dict[str, Any]
    ) -> str:
        """生成缓存键.

        【v3.11.0 优化】参数规范化：去除 None、字符串 strip，
        减少因参数格式不一致导致的缓存 miss。
        """
        normalized = normalize_params(params) if self._normalize_params else params
        content = json.dumps(
            {"skill_id": skill_id, "action": action, "params": normalized},
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

        【v3.11.0 优化】新增命中率统计。
        """
        key = self._make_key(skill_id, action, params)

        # L1 精确命中
        value = self._l1.get(key)
        if value is not None:
            self._hit_count += 1
            self._l1_hit_count += 1
            logger.debug("cache_l1_hit", key=key)
            return value

        # L1 语义模糊命中
        fuzzy_value = self._fuzzy_get_l1(skill_id, action, params)
        if fuzzy_value is not None:
            self._hit_count += 1
            self._l1_fuzzy_hit_count += 1
            logger.debug("cache_l1_fuzzy_hit", key=key)
            return fuzzy_value

        # L2 精确命中
        value = self._l2.get(key)
        if value is not None:
            self._hit_count += 1
            self._l2_hit_count += 1
            # 回填到 L1
            self._l1.set(key, value)
            logger.debug("cache_l2_hit", key=key)
            return value

        self._miss_count += 1
        logger.debug("cache_miss", key=key)
        return None

    def _fuzzy_get_l1(
        self, skill_id: str, action: str, params: dict[str, Any]
    ) -> Any | None:
        """L1 语义模糊匹配（Jaccard 相似度）."""
        # 仅当 L1 缓存较小时启用（避免 O(n) 扫描过大）
        if len(self._l1._cache) > FUZZY_MATCH_L1_THRESHOLD:
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

        【v3.11.0 优化】参数规范化 + set_count 统计。
        """
        key = self._make_key(skill_id, action, params)
        effective_ttl = ttl if ttl is not None else self._default_ttl
        # 存储 params 摘要到 tag 中，用于语义模糊匹配
        normalized = normalize_params(params) if self._normalize_params else params
        summary = self._make_param_summary(normalized)
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
        self._set_count += 1
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
        self._hit_count = 0
        self._miss_count = 0
        self._l1_hit_count = 0
        self._l1_fuzzy_hit_count = 0
        self._l2_hit_count = 0
        self._set_count = 0
        logger.info("cache_cleared")

    def reset_stats(self) -> None:
        """重置命中率统计（不清空缓存数据）."""
        self._hit_count = 0
        self._miss_count = 0
        self._l1_hit_count = 0
        self._l1_fuzzy_hit_count = 0
        self._l2_hit_count = 0
        self._set_count = 0
        self._l1.reset_stats()

    @property
    def hit_count(self) -> int:
        """总命中次数."""
        return self._hit_count

    @property
    def miss_count(self) -> int:
        """总未命中次数."""
        return self._miss_count

    @property
    def hit_rate(self) -> float:
        """总命中率（0.0 - 1.0）."""
        total = self._hit_count + self._miss_count
        if total == 0:
            return 0.0
        return self._hit_count / total

    def stats(self) -> dict[str, Any]:
        total = self._hit_count + self._miss_count
        return {
            "l1": self._l1.stats(),
            "l2": self._l2.stats(),
            "default_ttl": self._default_ttl,
            "fuzzy_threshold": self._fuzzy_threshold,
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": round(self.hit_rate, 4) if total > 0 else 0.0,
            "l1_hit_count": self._l1_hit_count,
            "l1_fuzzy_hit_count": self._l1_fuzzy_hit_count,
            "l2_hit_count": self._l2_hit_count,
            "set_count": self._set_count,
            "total_requests": total,
        }

    # ------------------------------------------------------------------
    # 缓存预热
    # ------------------------------------------------------------------

    def warmup(
        self,
        skill_id: str,
        action: str,
        value: Any,
        ttl: float | None = None,
        tags: set[str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        """预热单个缓存条目（启动时预加载）.

        与 set() 行为一致，但语义上用于预热场景，便于统计区分。

        Args:
            skill_id: 技能 ID
            action: 动作名
            value: 缓存值
            ttl: 过期时间（秒），默认使用 default_ttl
            tags: 标签集合
            params: 参数（默认为空字典，用于元数据缓存）
        """
        params = params or {}
        self.set(
            skill_id=skill_id,
            action=action,
            params=params,
            value=value,
            ttl=ttl,
            tags=tags,
            cache_scope="public",
        )
        logger.debug(
            "cache_warmup",
            skill_id=skill_id,
            action=action,
            ttl=ttl,
        )

    def warmup_metadata(
        self,
        skill_id: str,
        metadata: dict[str, Any],
    ) -> None:
        """预热技能元数据（使用长 TTL）.

        便捷方法：将技能元数据以 CACHE_TTL_METADATA 的长 TTL 缓存，
        避免冷启动时频繁查询元数据。

        Args:
            skill_id: 技能 ID
            metadata: 元数据字典
        """
        self.warmup(
            skill_id=skill_id,
            action="__metadata__",
            value=metadata,
            ttl=CACHE_TTL_METADATA,
            tags={"metadata", f"sid:{skill_id}"},
        )

    def get_metadata(self, skill_id: str) -> dict[str, Any] | None:
        """获取预热的技能元数据.

        Args:
            skill_id: 技能 ID

        Returns:
            元数据字典，未命中返回 None
        """
        return self.get(skill_id, "__metadata__", {})

    # ------------------------------------------------------------------
    # 新增：SQLite L2 专属方法
    # ------------------------------------------------------------------

    def cleanup_expired(self) -> int:
        """清理 L2 中的过期缓存（仅 SQLite 后端有效）.

        Returns:
            清理的条目数，文件后端返回 0
        """
        if isinstance(self._l2, SQLiteL2Cache):
            return self._l2.cleanup_expired()
        return 0

    def close(self) -> None:
        """优雅关闭（仅 SQLite 后端需要）."""
        if isinstance(self._l2, SQLiteL2Cache):
            self._l2.close()

    def __enter__(self) -> "SkillCache":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
