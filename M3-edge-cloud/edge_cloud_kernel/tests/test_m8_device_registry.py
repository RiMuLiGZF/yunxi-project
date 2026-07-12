"""M8 管理接口测试 — 设备注册表持久化.

测试类别：持久化测试(7) = 7个
"""

from __future__ import annotations

import os
import tempfile

import pytest

from edge_cloud_kernel.m8_api.device_registry import (
    DeviceInfo,
    DeviceRegistry,
    InMemoryDeviceRegistry,
    SqliteDeviceRegistry,
    create_device_registry,
)


# ---------------------------------------------------------------------------
# 内存设备注册表测试
# ---------------------------------------------------------------------------

class TestInMemoryDeviceRegistry:
    """内存设备注册表测试."""

    @pytest.mark.asyncio
    async def test_register_and_get(self):
        """测试注册和查询设备."""
        reg = InMemoryDeviceRegistry()
        device = DeviceInfo(device_id="dev_001", name="Test Device", device_type="desktop")
        result = await reg.register_device(device)
        assert result is True

        retrieved = await reg.get_device("dev_001")
        assert retrieved is not None
        assert retrieved.device_id == "dev_001"
        assert retrieved.name == "Test Device"
        assert retrieved.device_type == "desktop"

    @pytest.mark.asyncio
    async def test_list_devices(self):
        """测试列出设备."""
        reg = InMemoryDeviceRegistry()
        await reg.register_device(DeviceInfo(device_id="dev_001", status="online"))
        await reg.register_device(DeviceInfo(device_id="dev_002", status="offline"))
        await reg.register_device(DeviceInfo(device_id="dev_003", status="online"))

        all_devices = await reg.list_devices()
        assert len(all_devices) == 3

        online_devices = await reg.list_devices(status="online")
        assert len(online_devices) == 2

    @pytest.mark.asyncio
    async def test_unregister_device(self):
        """测试注销设备."""
        reg = InMemoryDeviceRegistry()
        await reg.register_device(DeviceInfo(device_id="dev_001"))
        assert await reg.get_device("dev_001") is not None

        result = await reg.unregister_device("dev_001")
        assert result is True
        assert await reg.get_device("dev_001") is None

        # 注销不存在的设备
        result = await reg.unregister_device("dev_nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_status(self):
        """测试更新设备状态."""
        reg = InMemoryDeviceRegistry()
        await reg.register_device(DeviceInfo(device_id="dev_001", status="online"))
        result = await reg.update_device_status("dev_001", "offline")
        assert result is True

        device = await reg.get_device("dev_001")
        assert device.status == "offline"

        # 更新不存在的设备
        result = await reg.update_device_status("dev_nonexistent", "offline")
        assert result is False

    @pytest.mark.asyncio
    async def test_clear_all(self):
        """测试清空所有设备."""
        reg = InMemoryDeviceRegistry()
        await reg.register_device(DeviceInfo(device_id="dev_001"))
        await reg.register_device(DeviceInfo(device_id="dev_002"))

        count = await reg.clear_all()
        assert count == 2
        assert len(await reg.list_devices()) == 0


# ---------------------------------------------------------------------------
# SQLite 设备注册表测试
# ---------------------------------------------------------------------------

class TestSqliteDeviceRegistry:
    """SQLite 设备注册表测试."""

    @pytest.mark.asyncio
    async def test_persistence(self):
        """测试持久化（重启后数据保留）."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # 第一次：注册设备
            reg = SqliteDeviceRegistry(db_path)
            await reg.initialize()
            await reg.register_device(DeviceInfo(
                device_id="dev_persist",
                name="Persistent Device",
                device_type="laptop",
            ))
            await reg.close()

            # 第二次：重新连接，验证数据保留
            reg2 = SqliteDeviceRegistry(db_path)
            await reg2.initialize()
            device = await reg2.get_device("dev_persist")
            assert device is not None
            assert device.name == "Persistent Device"
            assert device.device_type == "laptop"
            await reg2.close()
        finally:
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_concurrent_registration(self):
        """测试并发注册安全."""
        import asyncio
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            reg = SqliteDeviceRegistry(db_path)
            await reg.initialize()

            async def register(i):
                await reg.register_device(DeviceInfo(
                    device_id=f"dev_concurrent_{i}",
                    name=f"Device {i}",
                ))

            tasks = [register(i) for i in range(10)]
            await asyncio.gather(*tasks)

            devices = await reg.list_devices()
            assert len(devices) == 10
            await reg.close()
        finally:
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_factory_function(self):
        """测试工厂函数."""
        # 内存类型
        mem_reg = create_device_registry("memory")
        assert isinstance(mem_reg, InMemoryDeviceRegistry)

        # SQLite 类型
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            sqlite_reg = create_device_registry("sqlite", db_path=db_path)
            assert isinstance(sqlite_reg, SqliteDeviceRegistry)
        finally:
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_metadata_storage(self):
        """测试元数据存储（JSON）."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            reg = SqliteDeviceRegistry(db_path)
            await reg.initialize()

            metadata = {"os": "linux", "screen_size": "1920x1080", "tags": ["prod", "primary"]}
            await reg.register_device(DeviceInfo(
                device_id="dev_meta",
                metadata=metadata,
            ))

            device = await reg.get_device("dev_meta")
            assert device is not None
            assert device.metadata["os"] == "linux"
            assert device.metadata["tags"] == ["prod", "primary"]
            await reg.close()
        finally:
            os.unlink(db_path)
