"""P2-11: 传感器数据模型测试"""
import sys
from pathlib import Path
import pytest
from m6_hardware.models.sensor_data import SensorData, SensorReading


class TestSensorReading:
    def test_create_reading(self):
        sr = SensorReading(
            sensor_type="heart_rate",
            value=72.5,
            unit="bpm",
        )
        assert sr.sensor_type == "heart_rate"
        assert sr.value == 72.5
        assert sr.unit == "bpm"
        assert sr.timestamp is not None
        assert sr.quality == 100

    def test_reading_quality(self):
        sr = SensorReading(sensor_type="temp", value=36.5, quality=80)
        assert sr.quality == 80

    def test_reading_to_dict(self):
        sr = SensorReading(sensor_type="steps", value=1000, unit="步")
        d = sr.to_dict()
        assert d["sensor_type"] == "steps"
        assert d["value"] == 1000
        assert "timestamp" in d


class TestSensorData:
    def test_create_sensor_data(self):
        sd = SensorData(device_id="watch-001")
        assert sd.device_id == "watch-001"
        assert isinstance(sd.readings, dict)
        assert len(sd.readings) == 0

    def test_add_reading(self):
        sd = SensorData(device_id="ring-001")
        sr = SensorReading(sensor_type="heart_rate", value=65.0, unit="bpm")
        sd.readings["heart_rate"] = sr
        assert len(sd.readings) == 1
        assert sd.readings["heart_rate"].value == 65.0

    def test_get_reading(self):
        sd = SensorData(device_id="w1")
        sd.readings["steps"] = SensorReading(sensor_type="steps", value=500)
        result = sd.get_reading("steps")
        assert result is not None
        assert result.value == 500

    def test_get_reading_nonexistent(self):
        sd = SensorData(device_id="w1")
        assert sd.get_reading("nonexistent") is None

    def test_to_dict(self):
        sd = SensorData(device_id="dev-001")
        sd.readings["hr"] = SensorReading(sensor_type="hr", value=70, unit="bpm")
        d = sd.to_dict()
        assert d["device_id"] == "dev-001"
        assert "collected_at" in d
        assert "hr" in d["readings"]
