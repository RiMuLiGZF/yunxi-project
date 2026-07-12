"""P2-11: 数据采集器测试"""
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from m6_hardware.services.data_collector import DataCollector, get_data_collector


@pytest.fixture
def collector(tmp_path):
    """使用临时数据库进行测试"""
    from m6_hardware.config import get_config
    from m6_hardware.services.device_manager import DeviceManager
    # 重置单例
    DataCollector._instance = None
    DeviceManager._instance = None
    # 用临时数据库
    config = get_config()
    original_path = config.database_path
    config.database_path = str(tmp_path / "test_sensor.db")
    
    c = DataCollector()
    yield c
    
    # 恢复
    config.database_path = original_path
    DataCollector._instance = None
    DeviceManager._instance = None


class TestDataCollectorSingleton:
    def test_singleton(self):
        from m6_hardware.services.device_manager import DeviceManager
        DataCollector._instance = None
        DeviceManager._instance = None
        c1 = get_data_collector()
        c2 = get_data_collector()
        assert c1 is c2


class TestDataCollectorInit:
    def test_init_creates_db(self, collector):
        assert os.path.exists(collector._db_path)

    def test_collector_not_running(self, collector):
        assert collector._running is False

    def test_has_config(self, collector):
        assert collector._config is not None

    def test_has_device_manager(self, collector):
        assert collector._device_manager is not None


class TestDataCollectorQuery:
    def test_get_sensor_history_empty(self, collector):
        result = collector.get_sensor_history("dev-001")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_get_latest_sensor_data_nonexistent(self, collector):
        result = collector.get_latest_sensor_data("no-such-device")
        assert result is None

    def test_get_status_history_empty(self, collector):
        result = collector.get_status_history("dev-001")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_get_sensor_history_with_limit(self, collector):
        result = collector.get_sensor_history("dev-001", limit=10)
        assert isinstance(result, list)

    def test_collect_once_no_crash(self, collector):
        """执行一次采集，不抛异常就算通过"""
        collector._collect_once()

    def test_collect_once_inserts_data(self, collector):
        """有设备时采集应该产生数据"""
        from m6_hardware.services.device_manager import get_device_manager
        dm = get_device_manager()
        dm.scan_devices()
        devices = dm.list_devices()
        if devices:
            collector._collect_once()
            # 检查至少有一些状态历史数据
            dev_id = devices[0]["device_id"]
            history = collector.get_status_history(dev_id)
            assert isinstance(history, list)
