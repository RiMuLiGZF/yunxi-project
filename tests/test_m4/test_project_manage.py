"""
M4 代码生成 - 项目管理测试
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class MockProjectMgr:
    def __init__(self):
        self._projects = {}
        self._files = {}
        self._nid = 1
    def create(self, name, desc="", lang="python"):
        pid = f"proj_{self._nid}"
        self._nid += 1
        p = {"id": pid, "name": name, "description": desc, "language": lang,
             "status": "active", "file_count": 0, "total_lines": 0,
             "config": {"version": "0.1.0", "deps": []}}
        self._projects[pid] = p
        self._files[pid] = {}
        return p
    def get(self, pid):
        if pid not in self._projects:
            raise KeyError(pid)
        return self._projects[pid].copy()
    def list(self, status=None):
        ps = list(self._projects.values())
        if status:
            ps = [p for p in ps if p["status"] == status]
        return [p.copy() for p in ps]
    def delete(self, pid):
        if pid not in self._projects:
            return False
        del self._projects[pid]
        del self._files[pid]
        return True
    def add_file(self, pid, fname, content):
        if pid not in self._projects:
            raise KeyError(pid)
        self._files[pid][fname] = content
        p = self._projects[pid]
        p["file_count"] = len(self._files[pid])
        p["total_lines"] = sum(f.count("\n") + 1 for f in self._files[pid].values())
        return {"filename": fname, "lines": content.count("\n") + 1}
    def get_file(self, pid, fname):
        if pid not in self._files or fname not in self._files[pid]:
            raise KeyError(fname)
        return self._files[pid][fname]
    def list_files(self, pid):
        if pid not in self._files:
            raise KeyError(pid)
        return list(self._files[pid].keys())
    def update_config(self, pid, **kwargs):
        if pid not in self._projects:
            raise KeyError(pid)
        self._projects[pid]["config"].update(kwargs)
        return self._projects[pid]["config"].copy()

class TestProjectManage:
    @pytest.fixture
    def pm(self):
        pm = MockProjectMgr()
        p1 = pm.create("WebApp", "web项目", "python")
        p2 = pm.create("Mobile", "mobile", "javascript")
        pm.add_file(p1["id"], "main.py", "print('hi')\n")
        pm.add_file(p1["id"], "util.py", "def f():\n    pass\n")
        return pm

    @pytest.mark.m4
    @pytest.mark.project
    def test_create(self, pm):
        p = pm.create("测试", "描述", "python")
        assert p["name"] == "测试"
        assert p["file_count"] == 0

    @pytest.mark.m4
    @pytest.mark.project
    def test_create_defaults(self, pm):
        p = pm.create("默认")
        assert p["language"] == "python"

    @pytest.mark.m4
    @pytest.mark.project
    def test_unique_id(self, pm):
        a = pm.create("a")
        b = pm.create("b")
        assert a["id"] != b["id"]

    @pytest.mark.m4
    @pytest.mark.project
    def test_get(self, pm):
        ps = pm.list()
        p = pm.get(ps[0]["id"])
        assert p["name"] == ps[0]["name"]

    @pytest.mark.m4
    @pytest.mark.project
    def test_get_notfound(self, pm):
        with pytest.raises(KeyError):
            pm.get("no")

    @pytest.mark.m4
    @pytest.mark.project
    def test_list_all(self, pm):
        assert len(pm.list()) == 2

    @pytest.mark.m4
    @pytest.mark.project
    def test_list_by_status(self, pm):
        assert len(pm.list("active")) == 2
        assert len(pm.list("archived")) == 0

    @pytest.mark.m4
    @pytest.mark.project
    def test_delete(self, pm):
        p = pm.create("del")
        assert pm.delete(p["id"])
        with pytest.raises(KeyError):
            pm.get(p["id"])

    @pytest.mark.m4
    @pytest.mark.project
    def test_delete_notfound(self, pm):
        assert not pm.delete("no")

    @pytest.mark.m4
    @pytest.mark.project
    def test_add_file(self, pm):
        p = pm.create("f")
        r = pm.add_file(p["id"], "a.py", "x=1")
        assert r["lines"] == 1

    @pytest.mark.m4
    @pytest.mark.project
    def test_file_count_updates(self, pm):
        p = pm.create("fc")
        pm.add_file(p["id"], "a.py", "1")
        pm.add_file(p["id"], "b.py", "2")
        assert pm.get(p["id"])["file_count"] == 2

    @pytest.mark.m4
    @pytest.mark.project
    def test_get_file(self, pm):
        ps = pm.list()
        c = pm.get_file(ps[0]["id"], "main.py")
        assert "hi" in c

    @pytest.mark.m4
    @pytest.mark.project
    def test_list_files(self, pm):
        ps = pm.list()
        fs = pm.list_files(ps[0]["id"])
        assert len(fs) == 2

    @pytest.mark.m4
    @pytest.mark.project
    def test_update_config(self, pm):
        ps = pm.list()
        c = pm.update_config(ps[0]["id"], version="1.0.0")
        assert c["version"] == "1.0.0"
