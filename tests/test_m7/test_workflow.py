"""
M7 工作流 - 工作流CRUD测试
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class MockWorkflowMgr:
    def __init__(self):
        self._wfs = {}
        self._nid = 1
    def create(self, name, desc="", nodes=None, edges=None):
        wid = f"wf_{self._nid}"
        self._nid += 1
        w = {"id": wid, "name": name, "description": desc,
             "status": "draft", "nodes": nodes or [], "edges": edges or [],
             "version": 1, "created_at": datetime.now().isoformat()}
        self._wfs[wid] = w
        return w
    def get(self, wid):
        if wid not in self._wfs:
            raise KeyError(wid)
        return self._wfs[wid].copy()
    def list(self, status=None, page=1, page_size=10):
        wfs = list(self._wfs.values())
        if status:
            wfs = [w for w in wfs if w["status"] == status]
        total = len(wfs)
        start = (page-1)*page_size
        return {"items": wfs[start:start+page_size], "total": total, "page": page}
    def update(self, wid, **kwargs):
        if wid not in self._wfs:
            raise KeyError(wid)
        w = self._wfs[wid]
        for k, v in kwargs.items():
            if k in ["name", "description", "status", "nodes", "edges"]:
                w[k] = v
        w["version"] += 1
        return w.copy()
    def delete(self, wid):
        if wid not in self._wfs:
            return False
        del self._wfs[wid]
        return True
    def add_node(self, wid, nid, ntype, config=None):
        if wid not in self._wfs:
            raise KeyError(wid)
        w = self._wfs[wid]
        node = {"id": nid, "type": ntype, "config": config or {}}
        w["nodes"].append(node)
        return node
    def add_edge(self, wid, src, tgt):
        if wid not in self._wfs:
            raise KeyError(wid)
        w = self._wfs[wid]
        nids = {n["id"] for n in w["nodes"]}
        if src not in nids or tgt not in nids:
            raise ValueError("节点不存在")
        edge = {"source": src, "target": tgt}
        w["edges"].append(edge)
        return edge
    def publish(self, wid):
        if wid not in self._wfs:
            raise KeyError(wid)
        w = self._wfs[wid]
        if not w["nodes"]:
            raise ValueError("无节点")
        w["status"] = "published"
        w["version"] += 1
        return w.copy()
    def validate(self, wid):
        if wid not in self._wfs:
            raise KeyError(wid)
        w = self._wfs[wid]
        errors = []
        if not w["nodes"]:
            errors.append("无节点")
        else:
            if not any(n["type"] == "start" for n in w["nodes"]):
                errors.append("缺少开始节点")
        return {"valid": len(errors) == 0, "errors": errors}

class TestWorkflow:
    @pytest.fixture
    def wfm(self):
        wfm = MockWorkflowMgr()
        wf = wfm.create("数据处理", "处理数据")
        wfm.add_node(wf["id"], "start", "start")
        wfm.add_node(wf["id"], "task1", "task")
        wfm.add_node(wf["id"], "end", "end")
        wfm.add_edge(wf["id"], "start", "task1")
        wfm.add_edge(wf["id"], "task1", "end")
        wfm.create("简单流程", "只有描述")
        return wfm

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_create(self, wfm):
        w = wfm.create("测试", "描述")
        assert w["name"] == "测试"
        assert w["status"] == "draft"

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_create_unique_id(self, wfm):
        a = wfm.create("a")
        b = wfm.create("b")
        assert a["id"] != b["id"]

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_get(self, wfm):
        ws = wfm.list()
        w = wfm.get(ws["items"][0]["id"])
        assert w["name"] == ws["items"][0]["name"]

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_get_notfound(self, wfm):
        with pytest.raises(KeyError):
            wfm.get("no")

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_list_all(self, wfm):
        r = wfm.list()
        assert r["total"] == 2

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_list_by_status(self, wfm):
        r = wfm.list(status="draft")
        assert r["total"] == 2

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_list_pagination(self, wfm):
        for i in range(15):
            wfm.create(f"wf{i}")
        r = wfm.list(page=1, page_size=10)
        assert r["total"] == 17
        assert len(r["items"]) == 10

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_update_name(self, wfm):
        w = wfm.create("原名")
        u = wfm.update(w["id"], name="新名")
        assert u["name"] == "新名"
        assert u["version"] == 2

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_delete(self, wfm):
        w = wfm.create("删")
        assert wfm.delete(w["id"])
        with pytest.raises(KeyError):
            wfm.get(w["id"])

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_delete_notfound(self, wfm):
        assert not wfm.delete("no")

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_add_node(self, wfm):
        w = wfm.create("节点测试")
        n = wfm.add_node(w["id"], "n1", "task")
        assert n["id"] == "n1"

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_add_edge(self, wfm):
        w = wfm.create("边测试")
        wfm.add_node(w["id"], "a", "start")
        wfm.add_node(w["id"], "b", "end")
        e = wfm.add_edge(w["id"], "a", "b")
        assert e["source"] == "a"

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_add_edge_bad_node(self, wfm):
        w = wfm.create("bad")
        wfm.add_node(w["id"], "a", "start")
        with pytest.raises(ValueError):
            wfm.add_edge(w["id"], "a", "no")

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_publish(self, wfm):
        w = wfm.create("发布测试")
        wfm.add_node(w["id"], "s", "start")
        p = wfm.publish(w["id"])
        assert p["status"] == "published"

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_validate_valid(self, wfm):
        w = wfm.create("验证")
        wfm.add_node(w["id"], "s", "start")
        v = wfm.validate(w["id"])
        assert v["valid"]

    @pytest.mark.m7
    @pytest.mark.workflow
    def test_validate_no_start(self, wfm):
        w = wfm.create("无开始")
        wfm.add_node(w["id"], "t", "task")
        v = wfm.validate(w["id"])
        assert not v["valid"]
