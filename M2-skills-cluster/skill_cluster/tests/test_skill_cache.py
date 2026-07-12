from __future__ import annotations

"""Skill Cache 单元测试."""

import time

import pytest

from skill_cluster.skill_cache import L1MemoryCache, L2DiskCache, SkillCache


def test_l1_cache_basic() -> None:
    cache = L1MemoryCache(max_size=3)
    cache.set("k1", "v1")
    assert cache.get("k1") == "v1"
    assert cache.get("missing") is None


def test_l1_cache_ttl() -> None:
    cache = L1MemoryCache()
    cache.set("k1", "v1", ttl=0.01)
    assert cache.get("k1") == "v1"
    time.sleep(0.02)
    assert cache.get("k1") is None


def test_l1_cache_lru_eviction() -> None:
    cache = L1MemoryCache(max_size=2)
    cache.set("k1", "v1")
    cache.set("k2", "v2")
    cache.set("k3", "v3")
    assert cache.get("k1") is None
    assert cache.get("k2") == "v2"
    assert cache.get("k3") == "v3"


def test_l1_cache_invalidate_by_tag() -> None:
    cache = L1MemoryCache()
    cache.set("k1", "v1", tags={"tag_a"})
    cache.set("k2", "v2", tags={"tag_a", "tag_b"})
    cache.set("k3", "v3", tags={"tag_c"})
    count = cache.invalidate_by_tag("tag_a")
    assert count == 2
    assert cache.get("k1") is None
    assert cache.get("k2") is None
    assert cache.get("k3") == "v3"


def test_l2_disk_cache(tmp_path) -> None:
    cache = L2DiskCache(cache_dir=str(tmp_path / "cache"))
    cache.set("k1", {"data": "v1"})
    assert cache.get("k1") == {"data": "v1"}
    cache.delete("k1")
    assert cache.get("k1") is None


def test_l2_disk_cache_ttl(tmp_path) -> None:
    cache = L2DiskCache(cache_dir=str(tmp_path / "cache"))
    cache.set("k1", "v1", ttl=0.01)
    assert cache.get("k1") == "v1"
    time.sleep(0.02)
    assert cache.get("k1") is None


def test_skill_cache_two_tiers(tmp_path) -> None:
    cache = SkillCache(l2_dir=str(tmp_path / "cache"))
    cache.set("skill.test", "action1", {"x": 1}, {"result": "ok"})

    # L1 hit
    assert cache.get("skill.test", "action1", {"x": 1}) == {"result": "ok"}

    # Clear L1, L2 hit
    cache._l1.clear()
    assert cache.get("skill.test", "action1", {"x": 1}) == {"result": "ok"}

    # Clear all, miss
    cache.clear()
    assert cache.get("skill.test", "action1", {"x": 1}) is None


def test_skill_cache_invalidate(tmp_path) -> None:
    cache = SkillCache(l2_dir=str(tmp_path / "cache"))
    cache.set("skill.test", "action1", {"x": 1}, {"result": "ok"})
    assert cache.invalidate("skill.test", "action1", {"x": 1}) is True
    assert cache.get("skill.test", "action1", {"x": 1}) is None


def test_skill_cache_tag_invalidation(tmp_path) -> None:
    cache = SkillCache(l2_dir=str(tmp_path / "cache"))
    cache.set("skill.a", "act", {"x": 1}, {"r": 1}, tags={"group_a"})
    cache.set("skill.b", "act", {"x": 2}, {"r": 2}, tags={"group_a"})
    cache.set("skill.c", "act", {"x": 3}, {"r": 3}, tags={"group_b"})

    count = cache.invalidate_by_tag("group_a")
    # L1 和 L2 各命中 2 个，总计 4
    assert count == 4
    assert cache.get("skill.a", "act", {"x": 1}) is None
    assert cache.get("skill.b", "act", {"x": 2}) is None
    assert cache.get("skill.c", "act", {"x": 3}) == {"r": 3}


def test_skill_cache_stats(tmp_path) -> None:
    cache = SkillCache(l2_dir=str(tmp_path / "cache"))
    cache.set("skill.test", "action1", {"x": 1}, {"result": "ok"})
    stats = cache.stats()
    assert stats["l1"]["size"] == 1
    assert stats["l2"]["size"] == 1
