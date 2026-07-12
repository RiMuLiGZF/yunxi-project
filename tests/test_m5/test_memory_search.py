"""
M5 潮汐记忆 - 记忆搜索测试
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class MockMemorySearch:
    def __init__(self):
        self._mems = []
    def add(self, content, mtype, tags, importance, days_ago=0):
        created = datetime.now() - timedelta(days=days_ago)
        self._mems.append({"id": f"m{len(self._mems)+1}",
                           "content": content, "type": mtype,
                           "tags": tags, "importance": importance,
                           "created_at": created})
    def search(self, query, mtype=None, min_imp=None, sort_by="relevance"):
        results = []
        ql = query.lower() if query else ""
        for m in self._mems:
            rel = 0.0
            if ql:
                if ql in m["content"].lower():
                    rel += 1.0
                for t in m["tags"]:
                    if ql in t.lower():
                        rel += 0.5
                if rel == 0:
                    continue
            if mtype and m["type"] != mtype:
                continue
            if min_imp is not None and m["importance"] < min_imp:
                continue
            r = m.copy()
            r["_relevance"] = rel
            results.append(r)
        if sort_by == "relevance":
            results.sort(key=lambda x: x["_relevance"], reverse=True)
        elif sort_by == "time":
            results.sort(key=lambda x: x["created_at"], reverse=True)
        elif sort_by == "importance":
            results.sort(key=lambda x: x["importance"], reverse=True)
        return results
    def search_by_date(self, start_days, end_days=0):
        now = datetime.now()
        start = now - timedelta(days=start_days)
        end = now - timedelta(days=end_days)
        return [m.copy() for m in self._mems if start <= m["created_at"] <= end]
    def stats(self):
        tc = {}
        for m in self._mems:
            tc[m["type"]] = tc.get(m["type"], 0) + 1
        avg_imp = sum(m["importance"] for m in self._mems) / len(self._mems) if self._mems else 0
        return {"total": len(self._mems), "by_type": tc, "avg_importance": round(avg_imp, 2)}
    def tag_cloud(self, limit=10):
        tc = {}
        for m in self._mems:
            for t in m["tags"]:
                tc[t] = tc.get(t, 0) + 1
        st = sorted(tc.items(), key=lambda x: x[1], reverse=True)
        return [{"tag": t, "count": c} for t, c in st[:limit]]

class TestMemorySearch:
    @pytest.fixture
    def ms(self):
        ms = MockMemorySearch()
        ms.add("喜欢喝美式咖啡", "preference", ["咖啡", "饮品"], 0.9, 0)
        ms.add("上周去上海出差", "event", ["旅行", "上海", "工作"], 0.7, 7)
        ms.add("生日是3月15日", "fact", ["生日", "日期"], 0.8, 30)
        ms.add("心情很愉快", "emotion", ["心情", "开心"], 0.5, 1)
        ms.add("偏好深色主题", "preference", ["设置", "主题"], 0.6, 10)
        ms.add("吃了火锅", "event", ["美食", "火锅"], 0.4, 3)
        return ms

    @pytest.mark.m5
    @pytest.mark.search
    def test_search_content(self, ms):
        r = ms.search("咖啡")
        assert len(r) >= 1
        assert "咖啡" in r[0]["content"]

    @pytest.mark.m5
    @pytest.mark.search
    def test_search_tag(self, ms):
        r = ms.search("旅行")
        assert len(r) >= 1

    @pytest.mark.m5
    @pytest.mark.search
    def test_search_no_result(self, ms):
        r = ms.search("xyz123不存在")
        assert len(r) == 0

    @pytest.mark.m5
    @pytest.mark.search
    def test_filter_type(self, ms):
        r = ms.search("", mtype="preference")
        for m in r:
            assert m["type"] == "preference"

    @pytest.mark.m5
    @pytest.mark.search
    def test_filter_importance(self, ms):
        r = ms.search("", min_imp=0.7)
        for m in r:
            assert m["importance"] >= 0.7

    @pytest.mark.m5
    @pytest.mark.search
    def test_sort_by_time(self, ms):
        r = ms.search("", sort_by="time")
        for i in range(len(r)-1):
            assert r[i]["created_at"] >= r[i+1]["created_at"]

    @pytest.mark.m5
    @pytest.mark.search
    def test_sort_by_importance(self, ms):
        r = ms.search("", sort_by="importance")
        for i in range(len(r)-1):
            assert r[i]["importance"] >= r[i+1]["importance"]

    @pytest.mark.m5
    @pytest.mark.search
    def test_search_by_date(self, ms):
        r = ms.search_by_date(5)
        assert len(r) >= 2

    @pytest.mark.m5
    @pytest.mark.search
    def test_search_old_date(self, ms):
        r = ms.search_by_date(40, 20)
        assert len(r) >= 1

    @pytest.mark.m5
    @pytest.mark.search
    def test_stats_total(self, ms):
        s = ms.stats()
        assert s["total"] == 6

    @pytest.mark.m5
    @pytest.mark.search
    def test_stats_by_type(self, ms):
        s = ms.stats()
        assert s["by_type"]["preference"] == 2

    @pytest.mark.m5
    @pytest.mark.search
    def test_tag_cloud(self, ms):
        tags = ms.tag_cloud()
        assert len(tags) > 0
        for i in range(len(tags)-1):
            assert tags[i]["count"] >= tags[i+1]["count"]
