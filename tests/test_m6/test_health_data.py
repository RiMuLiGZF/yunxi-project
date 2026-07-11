"""
M6 硬件外设 - 健康数据测试
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class MockHealthMgr:
    NORMAL = {"heart_rate": (60, 100), "spo2": (95, 100),
              "temperature": (36.0, 37.5), "steps": (0, 50000)}
    def __init__(self):
        self._data = []
    def add_hr(self, did, hr, ts=None):
        if hr < 0 or hr > 250:
            raise ValueError("心率不合理")
        r = {"device_id": did, "type": "heart_rate", "value": hr,
             "timestamp": ts or datetime.now(), "unit": "bpm"}
        self._data.append(r)
        return r
    def add_spo2(self, did, spo2, ts=None):
        if spo2 < 0 or spo2 > 100:
            raise ValueError("血氧不合理")
        r = {"device_id": did, "type": "spo2", "value": spo2,
             "timestamp": ts or datetime.now(), "unit": "%"}
        self._data.append(r)
        return r
    def add_steps(self, did, steps, ts=None):
        if steps < 0:
            raise ValueError("步数不能为负")
        r = {"device_id": did, "type": "steps", "value": steps,
             "timestamp": ts or datetime.now(), "unit": "steps"}
        self._data.append(r)
        return r
    def add_sleep(self, did, hours, ts=None):
        if hours < 0 or hours > 24:
            raise ValueError("睡眠不合理")
        r = {"device_id": did, "type": "sleep", "value": hours,
             "timestamp": ts or datetime.now(), "unit": "hours"}
        self._data.append(r)
        return r
    def get_recent(self, did, dtype=None, limit=10):
        ds = [d for d in self._data if d["device_id"] == did]
        if dtype:
            ds = [d for d in ds if d["type"] == dtype]
        ds.sort(key=lambda x: x["timestamp"], reverse=True)
        return [d.copy() for d in ds[:limit]]
    def get_stats(self, did, dtype, hours=24):
        now = datetime.now()
        start = now - timedelta(hours=hours)
        vs = [d["value"] for d in self._data
              if d["device_id"] == did and d["type"] == dtype
              and d["timestamp"] >= start]
        if not vs:
            return {"count": 0, "avg": 0, "min": 0, "max": 0}
        return {"count": len(vs), "avg": round(sum(vs)/len(vs), 2),
                "min": min(vs), "max": max(vs)}
    def check_abnormal(self, did, dtype):
        nr = self.NORMAL.get(dtype)
        if not nr:
            return []
        lo, hi = nr
        return [d.copy() for d in self._data
                if d["device_id"] == did and d["type"] == dtype
                and (d["value"] < lo or d["value"] > hi)]
    def daily_summary(self, did, date=None):
        if date is None:
            date = datetime.now().date()
        start = datetime.combine(date, datetime.min.time())
        end = start + timedelta(days=1)
        day_data = [d for d in self._data
                    if d["device_id"] == did and start <= d["timestamp"] < end]
        summary = {}
        for dt in ["heart_rate", "spo2", "steps", "sleep"]:
            vs = [d["value"] for d in day_data if d["type"] == dt]
            if vs:
                summary[dt] = sum(vs) if dt == "steps" else round(sum(vs)/len(vs), 2)
            else:
                summary[dt] = 0
        return summary

class TestHealthData:
    @pytest.fixture
    def hm(self):
        hm = MockHealthMgr()
        now = datetime.now()
        for i in range(10):
            hm.add_hr("w1", 70 + i*2, now - timedelta(minutes=i*5))
        for i in range(5):
            hm.add_spo2("w1", 97.5 + i*0.1, now - timedelta(minutes=i*10))
        hm.add_steps("w1", 5000, now - timedelta(hours=1))
        hm.add_steps("w1", 3000, now - timedelta(hours=5))
        hm.add_sleep("w1", 7.5, now - timedelta(hours=20))
        return hm

    @pytest.mark.m6
    @pytest.mark.health
    def test_add_hr(self, hm):
        r = hm.add_hr("w1", 75)
        assert r["value"] == 75
        assert r["unit"] == "bpm"

    @pytest.mark.m6
    @pytest.mark.health
    def test_add_spo2(self, hm):
        r = hm.add_spo2("w1", 98.0)
        assert r["value"] == 98.0

    @pytest.mark.m6
    @pytest.mark.health
    def test_add_steps(self, hm):
        r = hm.add_steps("w1", 10000)
        assert r["value"] == 10000

    @pytest.mark.m6
    @pytest.mark.health
    def test_add_sleep(self, hm):
        r = hm.add_sleep("w1", 8.0)
        assert r["value"] == 8.0

    @pytest.mark.m6
    @pytest.mark.health
    def test_invalid_hr(self, hm):
        with pytest.raises(ValueError):
            hm.add_hr("w1", -1)

    @pytest.mark.m6
    @pytest.mark.health
    def test_negative_steps(self, hm):
        with pytest.raises(ValueError):
            hm.add_steps("w1", -100)

    @pytest.mark.m6
    @pytest.mark.health
    def test_get_recent(self, hm):
        r = hm.get_recent("w1", limit=5)
        assert len(r) == 5
        assert r[0]["timestamp"] >= r[-1]["timestamp"]

    @pytest.mark.m6
    @pytest.mark.health
    def test_get_recent_by_type(self, hm):
        r = hm.get_recent("w1", dtype="heart_rate", limit=3)
        assert len(r) == 3
        assert all(d["type"] == "heart_rate" for d in r)

    @pytest.mark.m6
    @pytest.mark.health
    def test_stats_avg(self, hm):
        s = hm.get_stats("w1", "heart_rate")
        assert s["count"] == 10
        assert s["min"] == 70
        assert s["max"] == 88

    @pytest.mark.m6
    @pytest.mark.health
    def test_stats_no_data(self, hm):
        s = hm.get_stats("no", "heart_rate")
        assert s["count"] == 0

    @pytest.mark.m6
    @pytest.mark.health
    def test_abnormal_hr(self, hm):
        hm.add_hr("w1", 45)
        ab = hm.check_abnormal("w1", "heart_rate")
        assert len(ab) >= 1

    @pytest.mark.m6
    @pytest.mark.health
    def test_normal_not_abnormal(self, hm):
        ab = hm.check_abnormal("w1", "heart_rate")
        assert len(ab) == 0

    @pytest.mark.m6
    @pytest.mark.health
    def test_daily_summary(self, hm):
        s = hm.daily_summary("w1")
        assert "heart_rate" in s
        assert "steps" in s

    @pytest.mark.m6
    @pytest.mark.health
    def test_daily_steps_total(self, hm):
        s = hm.daily_summary("w1")
        assert s["steps"] >= 8000
