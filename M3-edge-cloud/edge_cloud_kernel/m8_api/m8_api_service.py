"""M8 标准对接接口服务.

提供 M3 对外暴露的 M8 标准接口：
- GET  /api/v3/sync/status          # 同步状态
- POST /api/v3/sync/trigger         # 手动触发同步
- GET  /api/v3/sync/conflicts       # 冲突列表
- POST /api/v3/sync/conflicts/{id}/resolve  # 解决冲突
- GET  /api/v3/devices              # 设备列表
- POST /api/v3/devices/{id}/remove  # 移除设备
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from edge_cloud_kernel.m8_api.error_codes import (
    ERR_CONFLICT_INVALID_RESOLUTION,
    ERR_CONFLICT_NOT_FOUND,
    ERR_DEVICE_NOT_FOUND,
    ERR_INVALID_PARAM,
    ERR_SYNC_IN_PROGRESS,
    ERR_SYNC_SESSION_NOT_FOUND,
    ErrorCode,
)
from edge_cloud_kernel.m8_api.device_registry import DeviceRegistry

logger = structlog.get_logger(__name__)


@dataclass
class M8APIResponse:
    """M8 标准响应格式."""
    code: int = 0
    message: str = "Success"
    data: dict | list | None = None
    trace_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "data": self.data,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
        }


class M8APIService:
    """M8 标准对接服务.

    封装 M3 核心能力，对外暴露 M8 标准接口。
    不直接处理 HTTP，由上层 aiohttp/FastAPI 适配器调用。
    """

    def __init__(
        self,
        sync_controller: Any = None,
        conflict_resolver: Any = None,
        offline_proxy: Any = None,
        health_checker: Any = None,
        device_registry: DeviceRegistry | None = None,
    ) -> None:
        """初始化 M8 API 服务.

        Args:
            sync_controller: 上下文同步控制器
            conflict_resolver: 冲突解决器
            offline_proxy: 离线影子代理
            health_checker: 健康探测器
            device_registry: 设备注册表
        """
        self._sync_controller = sync_controller
        self._conflict_resolver = conflict_resolver
        self._offline_proxy = offline_proxy
        self._health_checker = health_checker
        self._device_registry = device_registry
        self._syncing = False
        self._last_sync_at: float | None = None

    # -----------------------------------------------------------------------
    # GET /api/v3/sync/status
    # -----------------------------------------------------------------------

    async def get_sync_status(self, trace_id: str = "") -> M8APIResponse:
        """获取同步状态.

        Args:
            trace_id: 全链路追踪ID.

        Returns:
            M8APIResponse 包含同步状态信息.
        """
        if not trace_id:
            trace_id = uuid.uuid4().hex[:16]

        status_data: dict[str, Any] = {
            "status": "idle" if not self._syncing else "syncing",
            "last_sync_at": self._last_sync_at,
            "last_sync_result": None,
            "pending_changes": 0,
            "conflict_count": 0,
            "queue_depth": 0,
            "network_state": "unknown",
            "health_endpoints": [],
        }

        # 离线队列深度
        if self._offline_proxy is not None:
            try:
                status_data["queue_depth"] = await self._offline_proxy.get_queue_size()
                status_data["network_state"] = self._offline_proxy._state.value
            except Exception:
                pass

        # 冲突数量
        if self._conflict_resolver is not None:
            try:
                conflicts = self._conflict_resolver.get_manual_conflicts()
                status_data["conflict_count"] = len(conflicts)
            except Exception:
                pass

        # 健康端点状态
        if self._health_checker is not None:
            try:
                endpoints = self._health_checker.get_all_status()
                status_data["health_endpoints"] = [
                    {
                        "url": ep.url,
                        "status": ep.last_status.value if ep.last_status else "unknown",
                        "priority": ep.priority,
                        "last_check": ep.last_check_time,
                    }
                    for ep in endpoints
                ]
            except Exception:
                pass

        return M8APIResponse(data=status_data, trace_id=trace_id)

    # -----------------------------------------------------------------------
    # POST /api/v3/sync/trigger
    # -----------------------------------------------------------------------

    async def trigger_sync(
        self,
        scope: list[str] | None = None,
        conflict_strategy: str = "newest_wins",
        trace_id: str = "",
    ) -> M8APIResponse:
        """手动触发同步.

        Args:
            scope: 同步范围，如 ["conversation", "memory", "config"].
            conflict_strategy: 冲突解决策略.
            trace_id: 全链路追踪ID.

        Returns:
            M8APIResponse 包含触发结果.
        """
        if not trace_id:
            trace_id = uuid.uuid4().hex[:16]

        if self._syncing:
            return _error_response(ERR_SYNC_IN_PROGRESS, trace_id)

        valid_strategies = {"server_wins", "client_wins", "manual", "newest_wins"}
        if conflict_strategy not in valid_strategies:
            return _error_response(ERR_CONFLICT_INVALID_RESOLUTION, trace_id)

        self._syncing = True
        self._last_sync_at = time.time()

        sync_result = {
            "sync_id": uuid.uuid4().hex[:16],
            "scope": scope or ["all"],
            "conflict_strategy": conflict_strategy,
            "status": "triggered",
            "triggered_at": self._last_sync_at,
        }

        # 如果有同步控制器，尝试执行实际同步
        if self._sync_controller is not None:
            try:
                import asyncio
                asyncio.create_task(self._run_sync(scope, conflict_strategy, trace_id))
            except Exception as e:
                self._syncing = False
                logger.error("m8_api.trigger_sync.failed", error=str(e))

        return M8APIResponse(data=sync_result, trace_id=trace_id)

    async def _run_sync(
        self,
        scope: list[str] | None,
        conflict_strategy: str,
        trace_id: str,
    ) -> None:
        """后台执行同步（非阻塞）."""
        try:
            if hasattr(self._sync_controller, "sync_all"):
                await self._sync_controller.sync_all()
        except Exception:
            logger.exception("m8_api.background_sync.failed", trace_id=trace_id)
        finally:
            self._syncing = False

    # -----------------------------------------------------------------------
    # GET /api/v3/sync/conflicts
    # -----------------------------------------------------------------------

    async def list_conflicts(
        self,
        page: int = 1,
        page_size: int = 20,
        trace_id: str = "",
    ) -> M8APIResponse:
        """获取冲突列表.

        Args:
            page: 页码（从1开始）.
            page_size: 每页条数.
            trace_id: 全链路追踪ID.

        Returns:
            M8APIResponse 包含冲突列表.
        """
        if not trace_id:
            trace_id = uuid.uuid4().hex[:16]

        if page < 1 or page_size < 1 or page_size > 100:
            return _error_response(ERR_INVALID_PARAM, trace_id)

        conflicts: list[dict[str, Any]] = []

        if self._conflict_resolver is not None:
            try:
                manual_conflicts = self._conflict_resolver.get_manual_conflicts()
                for idx, c in enumerate(manual_conflicts):
                    conflicts.append({
                        "conflict_id": c.get("item_id", f"conflict_{idx}"),
                        "item_type": "unknown",
                        "created_at": c.get("created_at", 0.0),
                        "local_version": c.get("local", {}).get("version", 0),
                        "remote_version": c.get("remote", {}).get("version", 0),
                        "status": "pending",
                    })
            except Exception:
                pass

        # 分页
        total = len(conflicts)
        start = (page - 1) * page_size
        end = start + page_size
        page_conflicts = conflicts[start:end]

        data = {
            "total": total,
            "page": page,
            "page_size": page_size,
            "conflicts": page_conflicts,
        }

        return M8APIResponse(data=data, trace_id=trace_id)

    # -----------------------------------------------------------------------
    # POST /api/v3/sync/conflicts/{id}/resolve
    # -----------------------------------------------------------------------

    async def resolve_conflict(
        self,
        conflict_id: str,
        resolution: str,
        trace_id: str = "",
    ) -> M8APIResponse:
        """解决冲突.

        Args:
            conflict_id: 冲突ID.
            resolution: 解决策略 (local/remote/merge).
            trace_id: 全链路追踪ID.

        Returns:
            M8APIResponse 包含解决结果.
        """
        if not trace_id:
            trace_id = uuid.uuid4().hex[:16]

        valid_resolutions = {"local", "remote", "merge", "manual"}
        if resolution not in valid_resolutions:
            return _error_response(ERR_CONFLICT_INVALID_RESOLUTION, trace_id)

        if not conflict_id:
            return _error_response(ERR_CONFLICT_NOT_FOUND, trace_id)

        resolved = False
        if self._conflict_resolver is not None:
            try:
                keep = "local" if resolution == "local" else "remote"
                resolved = self._conflict_resolver.resolve_manual(conflict_id, keep)
            except Exception:
                pass

        if not resolved:
            # 冲突不在队列中（可能已解决或不存在），仍返回成功（幂等）
            return M8APIResponse(
                data={
                    "conflict_id": conflict_id,
                    "resolution": resolution,
                    "status": "not_found_or_resolved",
                },
                trace_id=trace_id,
            )

        return M8APIResponse(
            data={
                "conflict_id": conflict_id,
                "resolution": resolution,
                "status": "resolved",
                "resolved_at": time.time(),
            },
            trace_id=trace_id,
        )

    # -----------------------------------------------------------------------
    # GET /api/v3/devices
    # -----------------------------------------------------------------------

    async def list_devices(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        trace_id: str = "",
    ) -> M8APIResponse:
        """获取设备列表.

        Args:
            page: 页码.
            page_size: 每页条数.
            status: 按状态过滤.
            trace_id: 全链路追踪ID.

        Returns:
            M8APIResponse 包含设备列表.
        """
        if not trace_id:
            trace_id = uuid.uuid4().hex[:16]

        if page < 1 or page_size < 1 or page_size > 100:
            return _error_response(ERR_INVALID_PARAM, trace_id)

        if self._device_registry is None:
            return M8APIResponse(
                data={"total": 0, "page": page, "page_size": page_size, "devices": []},
                trace_id=trace_id,
            )

        devices = await self._device_registry.list_devices(status=status)
        total = len(devices)
        start = (page - 1) * page_size
        end = start + page_size
        page_devices = devices[start:end]

        data = {
            "total": total,
            "page": page,
            "page_size": page_size,
            "devices": [d.__dict__ for d in page_devices],
        }

        return M8APIResponse(data=data, trace_id=trace_id)

    # -----------------------------------------------------------------------
    # POST /api/v3/devices/{id}/remove
    # -----------------------------------------------------------------------

    async def remove_device(
        self,
        device_id: str,
        trace_id: str = "",
    ) -> M8APIResponse:
        """移除设备.

        Args:
            device_id: 设备ID.
            trace_id: 全链路追踪ID.

        Returns:
            M8APIResponse 包含移除结果.
        """
        if not trace_id:
            trace_id = uuid.uuid4().hex[:16]

        if not device_id:
            return _error_response(ERR_DEVICE_NOT_FOUND, trace_id)

        if self._device_registry is None:
            return _error_response(ERR_DEVICE_NOT_FOUND, trace_id)

        removed = await self._device_registry.unregister_device(device_id)
        if not removed:
            return _error_response(ERR_DEVICE_NOT_FOUND, trace_id)

        return M8APIResponse(
            data={
                "device_id": device_id,
                "status": "removed",
                "removed_at": time.time(),
            },
            trace_id=trace_id,
        )


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _error_response(error: ErrorCode, trace_id: str = "") -> M8APIResponse:
    """构造错误响应."""
    return M8APIResponse(
        code=error.code,
        message=error.message,
        data=None,
        trace_id=trace_id,
    )
