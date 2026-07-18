"""
M3 知识图谱 - 图谱查询测试
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, List, Any
from collections import deque

PROJECT_ROOT = Path(__file__).parent.parent.parent
class MockGraph:
    def __init__(self):
        self.nodes = {}
        self.edges = []
    def add_node(self, nid, label, props=None):
        n = {"id": nid, "label": label, "properties": props or {}}
        self.nodes[nid] = n
        return n
    def add_edge(self, src, tgt, relation):
        if src not in self.nodes or tgt not in self.nodes:
            raise ValueError("节点不存在")
        e = {"source": src, "target": tgt, "relation": relation}
        self.edges.append(e)
        return e
    def get_node(self, nid):
        if nid not in self.nodes:
            raise KeyError(nid)
        return self.nodes[nid].copy()
    def get_neighbors(self, nid, relation=None):
        if nid not in self.nodes:
            raise KeyError(nid)
        result = []
        for e in self.edges:
            if e["source"] == nid and (not relation or e["relation"] == relation):
                nb = self.nodes[e["target"]].copy()
                nb["_dir"] = "out"
                result.append(nb)
            if e["target"] == nid and (not relation or e["relation"] == relation):
                nb = self.nodes[e["source"]].copy()
                nb["_dir"] = "in"
                result.append(nb)
        return result
    def find_path(self, start, end, max_depth=5):
        if start not in self.nodes or end not in self.nodes:
            return []
        if start == end:
            return [start]
        visited = {start}
        q = deque([(start, [start])])
        while q:
            cur, path = q.popleft()
            if len(path) > max_depth:
                continue
            for nb in self.get_neighbors(cur):
                nid = nb["id"]
                if nid == end:
                    return path + [nid]
                if nid not in visited:
                    visited.add(nid)
                    q.append((nid, path + [nid]))
        return []

class TestGraphQuery:
    @pytest.fixture
    def graph(self):
        g = MockGraph()
        g.add_node("python", "Language", {"name": "Python"})
        g.add_node("java", "Language", {"name": "Java"})
        g.add_node("django", "Framework", {"name": "Django"})
        g.add_node("spring", "Framework", {"name": "Spring"})
        g.add_node("ai", "Domain", {"name": "AI"})
        g.add_node("web", "Domain", {"name": "Web"})
        g.add_edge("django", "python", "uses")
        g.add_edge("spring", "java", "uses")
        g.add_edge("django", "web", "belongs_to")
        g.add_edge("python", "ai", "used_in")
        return g

    @pytest.mark.m3
    @pytest.mark.graph
    def test_get_node(self, graph):
        n = graph.get_node("python")
        assert n["label"] == "Language"

    @pytest.mark.m3
    @pytest.mark.graph
    def test_get_node_notfound(self, graph):
        with pytest.raises(KeyError):
            graph.get_node("no")

    @pytest.mark.m3
    @pytest.mark.graph
    def test_get_neighbors(self, graph):
        nbs = graph.get_neighbors("django")
        assert len(nbs) == 2

    @pytest.mark.m3
    @pytest.mark.graph
    def test_get_neighbors_by_relation(self, graph):
        nbs = graph.get_neighbors("django", "uses")
        assert len(nbs) == 1
        assert nbs[0]["id"] == "python"

    @pytest.mark.m3
    @pytest.mark.graph
    def test_find_direct_path(self, graph):
        p = graph.find_path("django", "python")
        assert len(p) == 2

    @pytest.mark.m3
    @pytest.mark.graph
    def test_find_indirect_path(self, graph):
        p = graph.find_path("django", "ai")
        assert len(p) >= 3
        assert p[0] == "django"
        assert p[-1] == "ai"

    @pytest.mark.m3
    @pytest.mark.graph
    def test_find_no_path(self, graph):
        graph.add_node("iso", "Lang", {"name": "Iso"})
        p = graph.find_path("python", "iso")
        assert len(p) == 0

    @pytest.mark.m3
    @pytest.mark.graph
    def test_find_same_node(self, graph):
        p = graph.find_path("python", "python")
        assert p == ["python"]

    @pytest.mark.m3
    @pytest.mark.graph
    def test_add_edge_bad_node(self, graph):
        with pytest.raises(ValueError):
            graph.add_edge("python", "no_node", "test")

    @pytest.mark.m3
    @pytest.mark.graph
    def test_neighbor_direction(self, graph):
        nbs = graph.get_neighbors("python")
        dirs = {n["_dir"] for n in nbs}
        assert "in" in dirs
        assert "out" in dirs
