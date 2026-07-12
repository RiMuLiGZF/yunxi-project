"""
M3 知识图谱 - 知识库CRUD测试
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class MockKB:
    def __init__(self):
        self._items = {}
        self._nid = 1
    def create(self, title, content, category="general", tags=None):
        iid = f"kb_{self._nid}"
        self._nid += 1
        now = datetime.now().isoformat()
        item = {"id": iid, "title": title, "content": content,
                "category": category, "tags": tags or [],
                "created_at": now, "updated_at": now, "version": 1}
        self._items[iid] = item
        return item
    def get(self, iid):
        if iid not in self._items:
            raise KeyError(f"不存在: {iid}")
        return self._items[iid].copy()
    def update(self, iid, **kwargs):
        if iid not in self._items:
            raise KeyError(f"不存在: {iid}")
        item = self._items[iid]
        for k, v in kwargs.items():
            if k in ["title", "content", "category", "tags"]:
                item[k] = v
        item["version"] += 1
        item["updated_at"] = datetime.now().isoformat()
        return item.copy()
    def delete(self, iid):
        if iid not in self._items:
            return False
        del self._items[iid]
        return True
    def list(self, category=None, page=1, page_size=10):
        items = list(self._items.values())
        if category:
            items = [i for i in items if i["category"] == category]
        total = len(items)
        start = (page-1)*page_size
        return {"items": items[start:start+page_size], "total": total, "page": page}
    def search(self, keyword):
        kw = keyword.lower()
        return [i for i in self._items.values()
                if kw in i["title"].lower() or kw in i["content"].lower()]

class TestKnowledgeBase:
    @pytest.fixture
    def kb(self):
        kb = MockKB()
        kb.create("Python基础", "Python编程语言...", "programming", ["python"])
        kb.create("数据结构", "数组链表树图...", "programming", ["algorithm"])
        kb.create("机器学习", "AI分支...", "ai", ["ml", "ai"])
        return kb

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_create(self, kb):
        item = kb.create("测试", "内容", "test", ["t"])
        assert item["title"] == "测试"
        assert item["version"] == 1

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_create_unique_id(self, kb):
        i1 = kb.create("a", "1")
        i2 = kb.create("b", "2")
        assert i1["id"] != i2["id"]

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_get(self, kb):
        c = kb.create("获取", "内容")
        r = kb.get(c["id"])
        assert r["title"] == "获取"

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_get_notfound(self, kb):
        with pytest.raises(KeyError):
            kb.get("no_such")

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_list_all(self, kb):
        r = kb.list()
        assert r["total"] == 3

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_list_by_category(self, kb):
        r = kb.list(category="programming")
        assert r["total"] == 2

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_list_pagination(self, kb):
        for i in range(15):
            kb.create(f"条目{i}", f"c{i}")
        r = kb.list(page=1, page_size=10)
        assert r["total"] == 18
        assert len(r["items"]) == 10

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_update_title(self, kb):
        c = kb.create("原", "c")
        u = kb.update(c["id"], title="新")
        assert u["title"] == "新"
        assert u["version"] == 2

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_update_content(self, kb):
        c = kb.create("t", "原内容")
        u = kb.update(c["id"], content="新内容")
        assert u["content"] == "新内容"

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_delete(self, kb):
        c = kb.create("删", "c")
        assert kb.delete(c["id"]) is True
        with pytest.raises(KeyError):
            kb.get(c["id"])

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_delete_notfound(self, kb):
        assert kb.delete("no") is False

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_search_title(self, kb):
        r = kb.search("Python")
        assert len(r) >= 1

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_search_content(self, kb):
        r = kb.search("AI")
        assert len(r) >= 1

    @pytest.mark.m3
    @pytest.mark.knowledge
    def test_search_noresult(self, kb):
        r = kb.search("xyz不存在123")
        assert len(r) == 0
