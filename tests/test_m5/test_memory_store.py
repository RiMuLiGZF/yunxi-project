"""
M5 潮汐记忆 - 记忆存储与检索测试
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class MockMemoryStore:
    TYPES = ["conversation", "fact", "event", "preference", "emotion"]
    def __init__(self):
        self._mems = {}
        self._nid = 1
    def store(self, content, mtype="fact", tags=None, importance=0.5):
        if mtype not in self.TYPES:
            raise ValueError(f"无效类型: {mtype}")
        importance = max(0.0, min(1.0, importance))
        mid = f"mem_{self._nid}"
        self._nid += 1
        now = datetime.now()
        m = {"id": mid, "content": content, "type": mtype,
             "tags": tags or [], "importance": importance,
             "created_at": now, "updated_at": now,
             "access_count": 0, "last_accessed": now}
        self._mems[mid] = m
        return m
    def retrieve(self, mid):
        if mid not in self._mems:
            raise KeyError(mid)
        m = self._mems[mid]
        m["access_count"] += 1
        m["last_accessed"] = datetime.now()
        return m.copy()
    def update(self, mid, **kwargs):
        if mid not in self._mems:
            raise KeyError(mid)
        m = self._mems[mid]
        for k, v in kwargs.items():
            if k in ["content", "tags", "importance"]:
                m[k] = v
        m["updated_at"] = datetime.now()
        return m.copy()
    def delete(self, mid):
        if mid not in self._mems:
            return False
        del self._mems[mid]
        return True
    def list_by_type(self, mtype):
        return [m.copy() for m in self._mems.values() if m["type"] == mtype]
    def list_by_tag(self, tag):
        return [m.copy() for m in self._mems.values() if tag in m["tags"]]
    def get_recent(self, limit=10):
        sorted_m = sorted(self._mems.values(), key=lambda x: x["created_at"], reverse=True)
        return [m.copy() for m in sorted_m[:limit]]
    def calc_strength(self, mid):
        if mid not in self._mems:
            raise KeyError(mid)
        m = self._mems[mid]
        days = (datetime.now() - m["created_at"]).total_seconds() / 86400
        base = m["importance"] * (1 - 0.01 * days)
        bonus = min(0.5, m["access_count"] * 0.05)
        return max(0.0, min(1.0, base + bonus))

class TestMemoryStore:
    @pytest.fixture
    def store(self):
        s = MockMemoryStore()
        s.store("喜欢喝咖啡", "preference", ["食物"], 0.8)
        s.store("春节是龙年", "fact", ["节日"], 0.6)
        s.store("去了北京", "event", ["旅行"], 0.7)
        s.store("心情很好", "emotion", ["开心"], 0.5)
        return s

    @pytest.mark.m5
    @pytest.mark.memory
    def test_store(self, store):
        m = store.store("测试", "fact", ["t"])
        assert m["content"] == "测试"
        assert m["importance"] == 0.5

    @pytest.mark.m5
    @pytest.mark.memory
    def test_store_invalid_type(self, store):
        with pytest.raises(ValueError):
            store.store("t", "bad_type")

    @pytest.mark.m5
    @pytest.mark.memory
    def test_importance_clamped(self, store):
        m = store.store("t", "fact", importance=1.5)
        assert m["importance"] == 1.0
        m2 = store.store("t2", "fact", importance=-0.5)
        assert m2["importance"] == 0.0

    @pytest.mark.m5
    @pytest.mark.memory
    def test_retrieve(self, store):
        s = store.store("检索", "fact")
        r = store.retrieve(s["id"])
        assert r["content"] == "检索"

    @pytest.mark.m5
    @pytest.mark.memory
    def test_retrieve_increments_access(self, store):
        s = store.store("访问", "fact")
        store.retrieve(s["id"])
        store.retrieve(s["id"])
        r = store.retrieve(s["id"])
        assert r["access_count"] == 3

    @pytest.mark.m5
    @pytest.mark.memory
    def test_retrieve_notfound(self, store):
        with pytest.raises(KeyError):
            store.retrieve("no")

    @pytest.mark.m5
    @pytest.mark.memory
    def test_update_content(self, store):
        s = store.store("原", "fact")
        u = store.update(s["id"], content="新")
        assert u["content"] == "新"

    @pytest.mark.m5
    @pytest.mark.memory
    def test_update_tags(self, store):
        s = store.store("t", "fact", tags=["old"])
        u = store.update(s["id"], tags=["new"])
        assert "new" in u["tags"]

    @pytest.mark.m5
    @pytest.mark.memory
    def test_delete(self, store):
        s = store.store("删", "fact")
        assert store.delete(s["id"])
        with pytest.raises(KeyError):
            store.retrieve(s["id"])

    @pytest.mark.m5
    @pytest.mark.memory
    def test_delete_notfound(self, store):
        assert not store.delete("no")

    @pytest.mark.m5
    @pytest.mark.memory
    def test_list_by_type(self, store):
        facts = store.list_by_type("fact")
        assert len(facts) >= 1

    @pytest.mark.m5
    @pytest.mark.memory
    def test_list_by_tag(self, store):
        r = store.list_by_tag("食物")
        assert len(r) >= 1

    @pytest.mark.m5
    @pytest.mark.memory
    def test_get_recent(self, store):
        r = store.get_recent(2)
        assert len(r) == 2
        assert r[0]["created_at"] >= r[1]["created_at"]

    @pytest.mark.m5
    @pytest.mark.memory
    def test_calc_strength(self, store):
        s = store.store("强度", "fact", importance=0.8)
        st = store.calc_strength(s["id"])
        assert 0.0 <= st <= 1.0

    @pytest.mark.m5
    @pytest.mark.memory
    def test_strength_increases_with_access(self, store):
        s = store.store("访问增强", "fact", importance=0.5)
        s1 = store.calc_strength(s["id"])
        for _ in range(5):
            store.retrieve(s["id"])
        s2 = store.calc_strength(s["id"])
        assert s2 >= s1
