"""
M7 工作流 - 工作流执行测试
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class MockWorkflowExec:
    def __init__(self):
        self._execs = {}
        self._nid = 1
        self._handlers = {
            "start": lambda n, c: {"status": "completed", "output": {}},
            "task": lambda n, c: {"status": "completed", "output": {"result": "done"}},
            "end": lambda n, c: {"status": "completed", "output": {"final": True}},
        }
    def execute(self, workflow, inp=None):
        eid = f"exec_{self._nid}"
        self._nid += 1
        nodes = {n["id"]: n for n in workflow.get("nodes", [])}
        edges = workflow.get("edges", [])
        adj = {nid: [] for nid in nodes}
        for e in edges:
            adj[e["source"]].append(e["target"])
        starts = [nid for nid, n in nodes.items() if n["type"] == "start"]
        if not starts:
            return {"execution_id": eid, "status": "failed", "error": "无开始节点"}
        visited = set()
        results = {}
        queue = [starts[0]]
        while queue:
            cur = queue.pop(0)
            if cur in visited:
                continue
            visited.add(cur)
            node = nodes[cur]
            handler = self._handlers.get(node["type"], self._handlers["task"])
            r = handler(node, {})
            results[cur] = r
            if r["status"] == "completed":
                for nxt in adj.get(cur, []):
                    queue.append(nxt)
        status = "completed"
        exec_data = {"execution_id": eid, "workflow_id": workflow.get("id"),
                     "status": status, "node_results": results,
                     "input": inp or {}, "duration_ms": 100}
        self._execs[eid] = exec_data
        return exec_data
    def get_exec(self, eid):
        if eid not in self._execs:
            raise KeyError(eid)
        return self._execs[eid].copy()
    def list_execs(self, wfid=None, status=None):
        es = list(self._execs.values())
        if wfid:
            es = [e for e in es if e["workflow_id"] == wfid]
        if status:
            es = [e for e in es if e["status"] == status]
        return [e.copy() for e in es]
    def stats(self, wfid):
        es = [e for e in self._execs.values() if e["workflow_id"] == wfid]
        total = len(es)
        ok = sum(1 for e in es if e["status"] == "completed")
        return {"total": total, "completed": ok,
                "success_rate": round(ok/total*100, 2) if total else 0}

class TestWorkflowExec:
    @pytest.fixture
    def exec(self):
        return MockWorkflowExec()
    @pytest.fixture
    def sample_wf(self):
        return {"id": "wf_test", "name": "测试",
                "nodes": [{"id": "start", "type": "start"},
                          {"id": "t1", "type": "task"},
                          {"id": "t2", "type": "task"},
                          {"id": "end", "type": "end"}],
                "edges": [{"source": "start", "target": "t1"},
                          {"source": "t1", "target": "t2"},
                          {"source": "t2", "target": "end"}]}

    @pytest.mark.m7
    @pytest.mark.execution
    def test_execute(self, exec, sample_wf):
        r = exec.execute(sample_wf)
        assert r["status"] == "completed"

    @pytest.mark.m7
    @pytest.mark.execution
    def test_all_nodes_visited(self, exec, sample_wf):
        r = exec.execute(sample_wf)
        assert len(r["node_results"]) == 4

    @pytest.mark.m7
    @pytest.mark.execution
    def test_with_input(self, exec, sample_wf):
        r = exec.execute(sample_wf, {"x": 1})
        assert r["input"]["x"] == 1

    @pytest.mark.m7
    @pytest.mark.execution
    def test_no_start_fails(self, exec):
        wf = {"id": "bad", "nodes": [{"id": "t", "type": "task"}], "edges": []}
        r = exec.execute(wf)
        assert r["status"] == "failed"

    @pytest.mark.m7
    @pytest.mark.execution
    def test_get_exec(self, exec, sample_wf):
        r = exec.execute(sample_wf)
        e = exec.get_exec(r["execution_id"])
        assert e["status"] == "completed"

    @pytest.mark.m7
    @pytest.mark.execution
    def test_get_exec_notfound(self, exec):
        with pytest.raises(KeyError):
            exec.get_exec("no")

    @pytest.mark.m7
    @pytest.mark.execution
    def test_list_execs(self, exec, sample_wf):
        exec.execute(sample_wf)
        exec.execute(sample_wf)
        es = exec.list_execs(wfid="wf_test")
        assert len(es) == 2

    @pytest.mark.m7
    @pytest.mark.execution
    def test_list_by_status(self, exec, sample_wf):
        exec.execute(sample_wf)
        es = exec.list_execs(status="completed")
        assert len(es) >= 1

    @pytest.mark.m7
    @pytest.mark.execution
    def test_stats(self, exec, sample_wf):
        exec.execute(sample_wf)
        exec.execute(sample_wf)
        s = exec.stats("wf_test")
        assert s["total"] == 2
        assert s["completed"] == 2
        assert s["success_rate"] == 100.0

    @pytest.mark.m7
    @pytest.mark.execution
    def test_stats_no_data(self, exec):
        s = exec.stats("no_such")
        assert s["total"] == 0
        assert s["success_rate"] == 0

    @pytest.mark.m7
    @pytest.mark.execution
    def test_single_node_wf(self, exec):
        wf = {"id": "single", "nodes": [{"id": "s", "type": "start"}], "edges": []}
        r = exec.execute(wf)
        assert r["status"] == "completed"
        assert len(r["node_results"]) == 1
