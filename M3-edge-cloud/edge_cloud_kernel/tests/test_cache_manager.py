"""缓存管理器单元测试.

验证 LRU + TTL 混合缓存的 get/set、过期清理、命中率统计及并发安全。

目标：提升 edge_cloud_kernel.resource.cache_manager 覆盖率。
"""

from __future__ import annotations

import asyncio

import pytest

from edge_cloud_kernel.resource.cache_manager import CacheManager


class TestCacheManager:
    """CacheManager 核心测试集."""

    @pytest.fixture
    def cache(self):
        """创建 CacheManager 实例."""
        return CacheManager(max_size=100, default_ttl_s=300.0)

    @pytest.mark.asyncio
    async def test_get_set(self, cache):
        """设置并获取缓存值应返回正确结果."""
        await cache.set("k1", "v1", ttl_s=3600)
        assert await cache.get("k1") == "v1"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, cache):
        """获取不存在的键应返回 None."""
        assert await cache.get("missing") is None

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, cache):
        """TTL 到期后缓存值应被清除."""
        await cache.set("k2", "v2", ttl_s=0.1)
        assert await cache.get("k2") == "v2"
        await asyncio.sleep(0.2)
        assert await cache.get("k2") is None

    @pytest.mark.asyncio
    async def test_delete(self, cache):
        """删除后再次获取应返回 None."""
        await cache.set("k3", "v3")
        deleted = await cache.delete("k3")
        assert deleted is True
        assert await cache.get("k3") is None

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self, cache):
        """删除不存在的键应返回 False."""
        assert await cache.delete("missing") is False

    @pytest.mark.asyncio
    async def test_clear(self, cache):
        """清空缓存后所有键应不可访问."""
        await cache.set("k4", "v4")
        await cache.set("k5", "v5")
        count = await cache.clear()
        assert count == 2
        assert await cache.get("k4") is None
        assert await cache.get("k5") is None

    @pytest.mark.asyncio
    async def test_has_existing_key(self, cache):
        """has 对存在的键应返回 True."""
        await cache.set("k6", "v6")
        assert await cache.has("k6") is True

    @pytest.mark.asyncio
    async def test_has_missing_key(self, cache):
        """has 对不存在的键应返回 False."""
        assert await cache.has("missing") is False

    @pytest.mark.asyncio
    async def test_has_expired_key(self, cache):
        """has 对已过期键应返回 False."""
        await cache.set("k7", "v7", ttl_s=0.1)
        await asyncio.sleep(0.2)
        assert await cache.has("k7") is False

    @pytest.mark.asyncio
    async def test_get_stats(self, cache):
        """get_stats 应返回包含基本统计字段的字典."""
        stats = cache.get_stats()
        assert "size" in stats
        assert "max_size" in stats
        assert "hit_rate" in stats
        assert "total_hits" in stats
        assert "total_misses" in stats

    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self, cache):
        """命中与未命中次数应正确统计."""
        await cache.set("hit_key", "value")
        await cache.get("hit_key")  # hit
        await cache.get("hit_key")  # hit
        await cache.get("miss_key")  # miss
        stats = cache.get_stats()
        assert stats["total_hits"] == 2
        assert stats["total_misses"] == 1

    @pytest.mark.asyncio
    async def test_lru_eviction(self, cache):
        """超出最大容量时应淘汰最久未使用的条目."""
        small_cache = CacheManager(max_size=2, default_ttl_s=300.0)
        await small_cache.set("a", 1)
        await small_cache.set("b", 2)
        await small_cache.set("c", 3)  # evicts "a"
        assert await small_cache.get("a") is None
        assert await small_cache.get("b") == 2
        assert await small_cache.get("c") == 3

    @pytest.mark.asyncio
    async def test_size_property(self, cache):
        """size 属性应反映当前缓存条目数."""
        assert cache.size == 0
        await cache.set("x", 1)
        assert cache.size == 1

    @pytest.mark.asyncio
    async def test_start_stop_cleanup_task(self, cache):
        """start/stop 应能正常管理后台清理任务."""
        await cache.start()
        assert cache._running is True
        await cache.stop()
        assert cache._running is False
