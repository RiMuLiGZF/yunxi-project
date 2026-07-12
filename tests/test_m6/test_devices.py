"""
M6 硬件外设 - 设备管理测试
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class MockDeviceMgr:
    def __init__(self):
        self._devs = {}
    def register(self, did, name, dtype, features=None):
        if did in self._devs:
            raise ValueError(f"已存在: {did}")
        d = {"device_id": did, "name": name, "device_type": dtype,
             "status": "offline", "battery": 100, "firmware": "v1.0.0",
             "features": features or [], "paired": False,
             "created_at": datetime.now(), "last_sync": None}
        self._devs[did] = d
        return d
    def get(self, did):
        if did not in self._devs:
            raise KeyError(did)
        return self._devs[did].copy()
    def list(self, status=None, dtype=None):
        ds = list(self._devs.values())
        if status:
            ds = [d for d in ds if d["status"] == status]
        if dtype:
            ds = [d for d in ds if d["device_type"] == dtype]
        return [d.copy() for d in ds]
    def set_status(self, did, status):
        if did not in self._devs:
            raise KeyError(did)
        if status not in ["online", "offline", "warning", "charging"]:
            raise ValueError(f"无效状态: {status}")
        self._devs[did]["status"] = status
        if status == "online":
            self._devs[did]["last_sync"] = datetime.now()
        return self._devs[did].copy()
    def pair(self, did):
        if did not in self._devs:
            raise KeyError(did)
        self._devs[did]["paired"] = True
        self._devs[did]["status"] = "online"
        return {"device_id": did, "paired": True}
    def unpair(self, did):
        if did not in self._devs:
            raise KeyError(did)
        self._devs[did]["paired"] = False
        self._devs[did]["status"] = "offline"
        return {"device_id": did, "paired": False}
    def set_battery(self, did, level):
        if did not in self._devs:
            raise KeyError(did)
        level = max(0, min(100, level))
        self._devs[did]["battery"] = level
        if level <= 20:
            self._devs[did]["status"] = "warning"
        return {"device_id": did, "battery": level}
    def stats(self):
        t = len(self._devs)
        on = sum(1 for d in self._devs.values() if d["status"] == "online")
        off = sum(1 for d in self._devs.values() if d["status"] == "offline")
        p = sum(1 for d in self._devs.values() if d["paired"])
        return {"total": t, "online": on, "offline": off, "paired": p}

class TestDevices:
    @pytest.fixture
    def dm(self):
        dm = MockDeviceMgr()
        dm.register("w1", "智能手表", "watch", ["heart_rate", "steps"])
        dm.register("r1", "智能戒指", "ring", ["heart_rate", "temp"])
        dm.register("g1", "AR眼镜", "ar", ["display"])
        dm.pair("w1")
        dm.set_status("w1", "online")
        return dm

    @pytest.mark.m6
    @pytest.mark.device
    def test_register(self, dm):
        d = dm.register("n1", "新设备", "watch")
        assert d["name"] == "新设备"
        assert d["status"] == "offline"

    @pytest.mark.m6
    @pytest.mark.device
    def test_register_duplicate(self, dm):
        with pytest.raises(ValueError):
            dm.register("w1", "重复", "watch")

    @pytest.mark.m6
    @pytest.mark.device
    def test_get(self, dm):
        d = dm.get("w1")
        assert d["name"] == "智能手表"

    @pytest.mark.m6
    @pytest.mark.device
    def test_get_notfound(self, dm):
        with pytest.raises(KeyError):
            dm.get("no")

    @pytest.mark.m6
    @pytest.mark.device
    def test_list_all(self, dm):
        assert len(dm.list()) == 3

    @pytest.mark.m6
    @pytest.mark.device
    def test_list_by_status(self, dm):
        assert len(dm.list(status="online")) >= 1

    @pytest.mark.m6
    @pytest.mark.device
    def test_list_by_type(self, dm):
        ws = dm.list(dtype="watch")
        assert len(ws) == 1

    @pytest.mark.m6
    @pytest.mark.device
    def test_set_status_online(self, dm):
        dm.set_status("r1", "online")
        assert dm.get("r1")["status"] == "online"

    @pytest.mark.m6
    @pytest.mark.device
    def test_set_status_invalid(self, dm):
        with pytest.raises(ValueError):
            dm.set_status("w1", "bad")

    @pytest.mark.m6
    @pytest.mark.device
    def test_pair(self, dm):
        r = dm.pair("r1")
        assert r["paired"]
        assert dm.get("r1")["paired"]

    @pytest.mark.m6
    @pytest.mark.device
    def test_unpair(self, dm):
        r = dm.unpair("w1")
        assert not r["paired"]

    @pytest.mark.m6
    @pytest.mark.device
    def test_set_battery(self, dm):
        dm.set_battery("w1", 75)
        assert dm.get("w1")["battery"] == 75

    @pytest.mark.m6
    @pytest.mark.device
    def test_low_battery_warning(self, dm):
        dm.set_battery("w1", 15)
        assert dm.get("w1")["status"] == "warning"

    @pytest.mark.m6
    @pytest.mark.device
    def test_battery_clamped(self, dm):
        dm.set_battery("w1", 150)
        assert dm.get("w1")["battery"] == 100

    @pytest.mark.m6
    @pytest.mark.device
    def test_stats(self, dm):
        s = dm.stats()
        assert s["total"] == 3
        assert s["online"] >= 1
