"""
GPU 算力管理测试
"""
import sys
import os
import pytest
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestGPUComputeModels:
    """GPU 数据模型测试"""

    def test_gpu_device_status(self):
        """GPUDeviceStatus 数据类"""
        from backend.services.gpu_compute_service import GPUDeviceStatus
        dev = GPUDeviceStatus(
            gpu_id=0,
            name="NVIDIA RTX 4090",
            uuid="GPU-abc123",
            usage_percent=75.0,
            memory_total_mb=24576.0,
            memory_used_mb=12288.0,
            memory_free_mb=12288.0,
            memory_percent=50.0,
            temperature_celsius=72.0,
            power_watt=320.0,
        )
        assert dev.gpu_id == 0
        assert dev.name == "NVIDIA RTX 4090"
        assert dev.memory_free_mb == 12288.0

    def test_gpu_task(self):
        """GPUTask 数据类"""
        from backend.services.gpu_compute_service import GPUTask
        task = GPUTask(
            name="test_inference",
            task_type="inference",
            estimated_memory_mb=2048.0,
            priority=3,
            caller_module="M2",
        )
        assert task.name == "test_inference"
        assert task.status == "pending"
        assert task.priority == 3

    def test_gpu_compute_source(self):
        """GPUComputeSource 数据类"""
        from backend.services.gpu_compute_service import GPUComputeSource
        source = GPUComputeSource(
            source_id="local-gpu-01",
            name="本地 GPU 节点 1",
            type="gpu_local",
            m10_base_url="http://localhost:8700",
        )
        assert source.source_id == "local-gpu-01"
        assert source.type == "gpu_local"
        assert source.status == "inactive"


class TestGPUComputeManager:
    """GPU 算力管理器测试"""

    def test_singleton(self):
        """单例模式"""
        from backend.services.gpu_compute_service import (
            GPUComputeManager, get_gpu_compute_manager
        )
        mgr1 = get_gpu_compute_manager()
        mgr2 = GPUComputeManager.get_instance()
        assert mgr1 is mgr2

    def test_register_and_list_sources(self):
        """注册和列出算力源"""
        from backend.services.gpu_compute_service import (
            GPUComputeManager, GPUComputeSource, GPUDeviceStatus
        )
        mgr = GPUComputeManager()

        # 注册两个算力源
        source1 = GPUComputeSource(
            source_id="test-gpu-01",
            name="测试 GPU 1",
            type="gpu_local",
            status="active",
            total_gpu_count=2,
            total_memory_mb=49152.0,
            available_memory_mb=24576.0,
            devices=[
                GPUDeviceStatus(gpu_id=0, memory_total_mb=24576, memory_free_mb=12288),
                GPUDeviceStatus(gpu_id=1, memory_total_mb=24576, memory_free_mb=12288),
            ],
        )
        source2 = GPUComputeSource(
            source_id="test-gpu-02",
            name="测试 GPU 2",
            type="gpu_remote",
            status="inactive",
        )

        mgr.register_source(source1)
        mgr.register_source(source2)

        assert len(mgr.list_sources()) == 2
        assert len(mgr.list_active_sources()) == 1
        assert mgr.get_source("test-gpu-01").name == "测试 GPU 1"

    def test_unregister_source(self):
        """注销算力源"""
        from backend.services.gpu_compute_service import (
            GPUComputeManager, GPUComputeSource
        )
        mgr = GPUComputeManager()
        source = GPUComputeSource(source_id="to-delete", name="待删除")
        mgr.register_source(source)

        assert mgr.unregister_source("to-delete") is True
        assert mgr.get_source("to-delete") is None
        assert mgr.unregister_source("not-exist") is False

    def test_submit_and_schedule_task(self):
        """任务提交和调度"""
        from backend.services.gpu_compute_service import (
            GPUComputeManager, GPUComputeSource, GPUDeviceStatus, GPUTask
        )
        mgr = GPUComputeManager()

        # 注册一个有 2 块 GPU 的算力源
        source = GPUComputeSource(
            source_id="sched-test",
            name="调度测试",
            status="active",
            devices=[
                GPUDeviceStatus(
                    gpu_id=0, memory_total_mb=24576, memory_free_mb=24576,
                    memory_used_mb=0, memory_percent=0,
                ),
                GPUDeviceStatus(
                    gpu_id=1, memory_total_mb=24576, memory_free_mb=24576,
                    memory_used_mb=0, memory_percent=0,
                ),
            ],
        )
        mgr.register_source(source)

        # 提交任务
        task = GPUTask(
            name="test_task",
            task_type="inference",
            estimated_memory_mb=8192.0,
            priority=5,
        )
        task_id = mgr.submit_task(task)

        assert task_id == task.task_id
        assert task.status in ("pending", "running")

        # 如果调度成功，应该分配了 GPU
        if task.status == "running":
            assert task.gpu_id >= 0
            assert task.source_id == "sched-test"

    def test_complete_task_frees_memory(self):
        """任务完成后释放显存"""
        from backend.services.gpu_compute_service import (
            GPUComputeManager, GPUComputeSource, GPUDeviceStatus, GPUTask
        )
        mgr = GPUComputeManager()

        source = GPUComputeSource(
            source_id="mem-test",
            name="显存测试",
            status="active",
            devices=[
                GPUDeviceStatus(
                    gpu_id=0, memory_total_mb=24576, memory_free_mb=24576,
                    memory_used_mb=0, memory_percent=0,
                ),
            ],
        )
        mgr.register_source(source)

        # 提交并运行任务
        task = GPUTask(
            name="mem_test",
            estimated_memory_mb=4096.0,
        )
        mgr.submit_task(task)

        if task.status == "running":
            free_before = source.devices[0].memory_free_mb
            mgr.complete_task(task.task_id, success=True, result={"output": "test"})
            free_after = source.devices[0].memory_free_mb

            assert task.status == "completed"
            assert free_after > free_before  # 显存应该归还了

    def test_cancel_pending_task(self):
        """取消待执行任务"""
        from backend.services.gpu_compute_service import (
            GPUComputeManager, GPUComputeSource, GPUDeviceStatus, GPUTask
        )
        mgr = GPUComputeManager()

        source = GPUComputeSource(
            source_id="cancel-test",
            name="取消测试",
            status="active",
            devices=[
                GPUDeviceStatus(
                    gpu_id=0, memory_total_mb=1024, memory_free_mb=1024,
                    memory_used_mb=0, memory_percent=0,
                ),
            ],
        )
        mgr.register_source(source)

        # 提交一个超显存任务（会停留在 pending）
        task = GPUTask(
            name="big_task",
            estimated_memory_mb=99999.0,  # 超大，无法分配
            priority=1,
        )
        task_id = mgr.submit_task(task)
        assert task.status == "pending"

        # 取消
        assert mgr.cancel_task(task_id) is True
        assert task.status == "cancelled"

    def test_get_stats(self):
        """获取统计信息"""
        from backend.services.gpu_compute_service import (
            GPUComputeManager, GPUComputeSource, GPUDeviceStatus
        )
        mgr = GPUComputeManager()

        source = GPUComputeSource(
            source_id="stats-test",
            name="统计测试",
            status="active",
            total_gpu_count=2,
            total_memory_mb=49152.0,
            available_memory_mb=49152.0,
            devices=[
                GPUDeviceStatus(gpu_id=0, memory_total_mb=24576, memory_free_mb=24576),
                GPUDeviceStatus(gpu_id=1, memory_total_mb=24576, memory_free_mb=24576),
            ],
        )
        mgr.register_source(source)

        stats = mgr.get_stats()
        assert stats["sources_active"] == 1
        assert stats["total_gpu_count"] == 2
        assert stats["total_memory_mb"] == 49152.0
        assert "pending_tasks" in stats
        assert "running_tasks" in stats

    def test_priority_ordering(self):
        """任务按优先级排序"""
        from backend.services.gpu_compute_service import (
            GPUComputeManager, GPUComputeSource, GPUDeviceStatus, GPUTask
        )
        mgr = GPUComputeManager()

        # 用一个空设备的算力源，让任务都停留在 pending
        source = GPUComputeSource(
            source_id="priority-test",
            name="优先级测试",
            status="active",
            devices=[],  # 无设备，任务全部 pending
        )
        mgr.register_source(source)

        # 提交不同优先级的任务
        for i, (name, prio) in enumerate([
            ("low_prio", 10),
            ("high_prio", 1),
            ("mid_prio", 5),
        ]):
            task = GPUTask(name=name, priority=prio, estimated_memory_mb=1000)
            mgr.submit_task(task)

        # 待执行队列应该按优先级排序（1 最高）
        pending = mgr._pending_tasks
        assert len(pending) == 3
        # 第一个应该是最高优先级
        assert pending[0].priority <= pending[1].priority <= pending[2].priority


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
