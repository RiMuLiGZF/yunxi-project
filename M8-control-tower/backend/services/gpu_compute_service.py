"""
GPU 算力源服务

负责：
1. 对接 M10 系统卫士的 GPU 监控 API
2. 管理本地/远程 GPU 算力源的注册和状态同步
3. GPU 任务的分配、排队和状态追踪
4. GPU 显存/算力的配额管理

GPU 算力源类型：
- gpu_local: 本机 GPU（通过 M10 监控）
- gpu_remote: 远程 GPU 节点（通过 API 调用）
"""

from __future__ import annotations

import time
import uuid
import threading
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

import httpx


# ============================================================
# 数据模型
# ============================================================

@dataclass
class GPUDeviceStatus:
    """GPU 设备实时状态"""
    gpu_id: int = 0
    name: str = ""
    uuid: str = ""
    usage_percent: float = 0.0
    memory_total_mb: float = 0.0
    memory_used_mb: float = 0.0
    memory_free_mb: float = 0.0
    memory_percent: float = 0.0
    temperature_celsius: float = 0.0
    power_watt: float = 0.0
    power_limit_watt: float = 0.0
    fan_speed_percent: float = 0.0
    processes: List[Dict[str, Any]] = field(default_factory=list)
    last_update: float = 0.0


@dataclass
class GPUTask:
    """GPU 计算任务"""
    task_id: str = ""
    name: str = ""
    source_id: str = ""  # 所属算力源 ID
    gpu_id: int = -1  # 分配的 GPU ID，-1 表示未分配
    status: str = "pending"  # pending/running/completed/failed/cancelled
    task_type: str = "inference"  # inference/training/embedding/vector_search
    estimated_memory_mb: float = 0.0
    estimated_duration_sec: float = 0.0
    priority: int = 5  # 1-10
    submit_time: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    progress: float = 0.0  # 0-100
    result: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    caller_module: str = ""
    callback_url: str = ""
    task_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GPUComputeSource:
    """GPU 算力源配置"""
    source_id: str = ""
    name: str = ""
    type: str = "gpu_local"  # gpu_local / gpu_remote
    m10_base_url: str = "http://localhost:8700"  # M10 API 地址
    m10_api_token: str = ""  # M10 认证 Token
    status: str = "inactive"  # active/inactive/error
    total_gpu_count: int = 0
    total_memory_mb: float = 0.0
    available_memory_mb: float = 0.0
    devices: List[GPUDeviceStatus] = field(default_factory=list)
    last_sync_time: float = 0.0
    max_concurrent_tasks: int = 10
    supported_task_types: List[str] = field(default_factory=lambda: ["inference", "embedding"])
    config: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# GPU 算力管理器
# ============================================================

class GPUComputeManager:
    """GPU 算力管理器

    单例模式，管理所有 GPU 算力源和任务调度。
    """

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "GPUComputeManager":
        """获取单例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._sources: Dict[str, GPUComputeSource] = {}
        self._tasks: Dict[str, GPUTask] = {}
        self._pending_tasks: List[GPUTask] = []
        self._running_tasks: List[GPUTask] = []
        self._sync_interval = 30.0  # 状态同步间隔（秒）
        self._last_sync = 0.0
        self._enabled = False
        self._lock = threading.Lock()

    # ============================================================
    # 算力源管理
    # ============================================================

    def register_source(self, source: GPUComputeSource) -> bool:
        """注册 GPU 算力源"""
        with self._lock:
            self._sources[source.source_id] = source
            return True

    def unregister_source(self, source_id: str) -> bool:
        """注销 GPU 算力源"""
        with self._lock:
            return self._sources.pop(source_id, None) is not None

    def get_source(self, source_id: str) -> Optional[GPUComputeSource]:
        """获取算力源"""
        return self._sources.get(source_id)

    def list_sources(self) -> List[GPUComputeSource]:
        """列出所有算力源"""
        return list(self._sources.values())

    def list_active_sources(self) -> List[GPUComputeSource]:
        """列出活跃算力源"""
        return [s for s in self._sources.values() if s.status == "active"]

    # ============================================================
    # 状态同步（调用 M10 API）
    # ============================================================

    async def sync_source_status(self, source_id: str) -> bool:
        """从 M10 同步算力源状态

        Args:
            source_id: 算力源 ID

        Returns:
            是否同步成功
        """
        source = self._sources.get(source_id)
        if not source:
            return False

        try:
            headers = {}
            if source.m10_api_token:
                headers["Authorization"] = f"Bearer {source.m10_api_token}"

            async with httpx.AsyncClient(timeout=5.0) as client:
                # 获取 GPU 设备列表
                resp = await client.get(
                    f"{source.m10_base_url}/api/v1/status/gpu/devices",
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        devices_data = data.get("data", {}).get("devices", [])
                        source.devices = [
                            GPUDeviceStatus(
                                gpu_id=d.get("gpu_id", 0),
                                name=d.get("name", ""),
                                uuid=d.get("uuid", ""),
                                usage_percent=d.get("usage_percent", 0.0),
                                memory_total_mb=d.get("memory_total_mb", 0.0),
                                memory_used_mb=d.get("memory_used_mb", 0.0),
                                memory_free_mb=d.get("memory_free_mb", 0.0),
                                memory_percent=d.get("memory_percent", 0.0),
                                temperature_celsius=d.get("temperature_celsius", 0.0),
                                power_watt=d.get("power_watt", 0.0),
                                power_limit_watt=d.get("power_limit_watt", 0.0),
                                fan_speed_percent=d.get("fan_speed_percent", 0.0),
                                processes=d.get("processes", []),
                                last_update=time.time(),
                            )
                            for d in devices_data
                        ]
                        source.total_gpu_count = len(source.devices)
                        source.total_memory_mb = sum(d.memory_total_mb for d in source.devices)
                        source.available_memory_mb = sum(d.memory_free_mb for d in source.devices)
                        source.last_sync_time = time.time()
                        source.status = "active"
                        return True

                source.status = "error"
                return False

        except Exception as e:
            source.status = "error"
            return False

    async def sync_all_sources(self) -> int:
        """同步所有算力源状态

        Returns:
            成功同步的数量
        """
        success_count = 0
        for source_id in list(self._sources.keys()):
            if await self.sync_source_status(source_id):
                success_count += 1
        self._last_sync = time.time()
        return success_count

    # ============================================================
    # 任务调度
    # ============================================================

    def submit_task(self, task: GPUTask) -> str:
        """提交 GPU 任务

        Args:
            task: 任务对象

        Returns:
            任务 ID
        """
        if not task.task_id:
            task.task_id = f"gpu_task_{uuid.uuid4().hex[:16]}"

        task.submit_time = time.time()
        task.status = "pending"

        with self._lock:
            self._tasks[task.task_id] = task
            self._pending_tasks.append(task)
            # 按优先级排序（数字越小优先级越高）
            self._pending_tasks.sort(key=lambda t: (t.priority, t.submit_time))

        # 尝试立即调度
        self._try_schedule()

        return task.task_id

    def _try_schedule(self):
        """尝试调度待执行任务到可用 GPU"""
        with self._lock:
            if not self._pending_tasks:
                return

            # 找到有空闲资源的算力源
            available_sources = [s for s in self._sources.values() if s.status == "active"]
            if not available_sources:
                return

            # 简单调度：从高优先级任务开始，找显存足够的 GPU
            remaining = []
            for task in self._pending_tasks:
                assigned = False
                for source in available_sources:
                    for device in source.devices:
                        if device.memory_free_mb >= task.estimated_memory_mb:
                            # 分配
                            task.gpu_id = device.gpu_id
                            task.source_id = source.source_id
                            task.status = "running"
                            task.start_time = time.time()
                            self._running_tasks.append(task)
                            # 预扣显存（模拟）
                            device.memory_free_mb -= task.estimated_memory_mb
                            device.memory_used_mb += task.estimated_memory_mb
                            device.memory_percent = (
                                device.memory_used_mb / device.memory_total_mb * 100
                                if device.memory_total_mb > 0 else 0
                            )
                            assigned = True
                            break
                    if assigned:
                        break

                if not assigned:
                    remaining.append(task)

            self._pending_tasks = remaining

    def complete_task(self, task_id: str, success: bool = True, result: Dict = None, error: str = ""):
        """标记任务完成

        Args:
            task_id: 任务 ID
            success: 是否成功
            result: 结果数据
            error: 错误信息
        """
        task = self._tasks.get(task_id)
        if not task:
            return

        task.status = "completed" if success else "failed"
        task.end_time = time.time()
        task.result = result or {}
        task.error_message = error
        task.progress = 100.0 if success else task.progress

        # 释放 GPU 资源（归还预扣的显存）
        with self._lock:
            if task in self._running_tasks:
                self._running_tasks.remove(task)

            # 归还显存
            source = self._sources.get(task.source_id)
            if source and task.gpu_id >= 0:
                for device in source.devices:
                    if device.gpu_id == task.gpu_id:
                        device.memory_free_mb += task.estimated_memory_mb
                        device.memory_used_mb -= task.estimated_memory_mb
                        device.memory_used_mb = max(0, device.memory_used_mb)
                        device.memory_percent = (
                            device.memory_used_mb / device.memory_total_mb * 100
                            if device.memory_total_mb > 0 else 0
                        )
                        break

        # 调度下一个任务
        self._try_schedule()

    def get_task(self, task_id: str) -> Optional[GPUTask]:
        """获取任务状态"""
        return self._tasks.get(task_id)

    def list_tasks(self, status: str = None, limit: int = 50) -> List[GPUTask]:
        """列出任务"""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        tasks.sort(key=lambda t: t.submit_time, reverse=True)
        return tasks[:limit]

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        task = self._tasks.get(task_id)
        if not task or task.status in ("completed", "failed", "cancelled"):
            return False

        if task.status == "pending":
            with self._lock:
                if task in self._pending_tasks:
                    self._pending_tasks.remove(task)
            task.status = "cancelled"
            task.end_time = time.time()
            return True

        # running 状态的任务，标记取消
        task.status = "cancelled"
        self.complete_task(task_id, success=False, error="cancelled by user")
        return True

    # ============================================================
    # 统计信息
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取 GPU 算力统计"""
        active_sources = self.list_active_sources()
        total_gpus = sum(s.total_gpu_count for s in active_sources)
        total_mem = sum(s.total_memory_mb for s in active_sources)
        avail_mem = sum(s.available_memory_mb for s in active_sources)

        return {
            "sources_total": len(self._sources),
            "sources_active": len(active_sources),
            "total_gpu_count": total_gpus,
            "total_memory_mb": round(total_mem, 1),
            "available_memory_mb": round(avail_mem, 1),
            "memory_used_percent": round((1 - avail_mem / total_mem) * 100, 1) if total_mem > 0 else 0,
            "pending_tasks": len(self._pending_tasks),
            "running_tasks": len(self._running_tasks),
            "completed_tasks": len([t for t in self._tasks.values() if t.status == "completed"]),
            "failed_tasks": len([t for t in self._tasks.values() if t.status == "failed"]),
            "last_sync_time": self._last_sync,
        }


def get_gpu_compute_manager() -> GPUComputeManager:
    """获取 GPU 算力管理器单例"""
    return GPUComputeManager.get_instance()
