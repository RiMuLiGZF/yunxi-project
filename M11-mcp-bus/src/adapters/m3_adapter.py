"""M11 MCP Bus - M3 端云协同适配器.

将 M3 端云协同的设备管理、同步管理、配置管理与监控能力封装为 MCP 工具服务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class M3EdgeCloudAdapter(BaseMcpAdapter):
    """M3 端云协同 MCP 适配器.

    提供的 MCP 工具：
    - m3.list_devices: 设备列表
    - m3.remove_device: 移除设备
    - m3.get_sync_status: 同步状态
    - m3.trigger_sync: 触发同步
    - m3.list_conflicts: 冲突列表
    - m3.resolve_conflict: 解决冲突
    - m3.get_config: 获取配置
    - m3.update_config: 更新配置
    - m3.health_check: 健康检查
    - m3.metrics: 性能指标
    """

    adapter_name: str = "m3"
    adapter_description: str = "M3 端云协同 - 设备管理、数据同步、配置与监控"

    def __init__(
        self,
        m3_base_url: str = "http://localhost:8003",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
    ) -> None:
        super().__init__(
            bus_url=bus_url,
            server_name="m3",
            server_endpoint=server_endpoint,
        )
        self.m3_base_url = m3_base_url.rstrip("/")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "m3.list_devices",
                "description": "列出 M3 中所有已注册的设备。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "按设备状态筛选（可选）",
                        },
                    },
                },
            },
            {
                "name": "m3.remove_device",
                "description": "从 M3 中移除指定设备。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "设备 ID",
                        },
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "m3.get_sync_status",
                "description": "获取 M3 端云同步的当前状态。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m3.trigger_sync",
                "description": "手动触发 M3 端云同步。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "description": "同步方向：upload / download / bidirectional（可选）",
                        },
                        "device_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "指定同步的设备 ID 列表（可选）",
                        },
                    },
                },
            },
            {
                "name": "m3.list_conflicts",
                "description": "列出 M3 端云同步中的冲突记录。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "resolved": {
                            "type": "boolean",
                            "description": "是否只看已解决的冲突（可选）",
                        },
                    },
                },
            },
            {
                "name": "m3.resolve_conflict",
                "description": "解决 M3 端云同步中的指定冲突。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "冲突记录 ID",
                        },
                        "resolution": {
                            "type": "string",
                            "description": "解决方案：local / remote / merge",
                        },
                    },
                    "required": ["id", "resolution"],
                },
            },
            {
                "name": "m3.get_config",
                "description": "获取 M3 端云协同的配置信息。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m3.update_config",
                "description": "更新 M3 端云协同的配置。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "config": {
                            "type": "object",
                            "description": "要更新的配置键值对",
                        },
                    },
                    "required": ["config"],
                },
            },
            {
                "name": "m3.health_check",
                "description": "获取 M3 端云协同的健康检查结果。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m3.metrics",
                "description": "获取 M3 端云协同的性能指标数据。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool_map = {
            "m3.list_devices": self._call_list_devices,
            "m3.remove_device": self._call_remove_device,
            "m3.get_sync_status": self._call_get_sync_status,
            "m3.trigger_sync": self._call_trigger_sync,
            "m3.list_conflicts": self._call_list_conflicts,
            "m3.resolve_conflict": self._call_resolve_conflict,
            "m3.get_config": self._call_get_config,
            "m3.update_config": self._call_update_config,
            "m3.health_check": self._call_health_check,
            "m3.metrics": self._call_metrics,
        }
        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的 M3 工具: {name}")
        result = handler(args)
        return self._wrap_result(result)

    # ---- 工具调用实现 ----

    def _call_list_devices(self, args: Dict[str, Any]) -> Any:
        params: Dict[str, Any] = {}
        if args.get("status"):
            params["status"] = args["status"]
        return self._request_m3(method="GET", path="/api/v3/devices", params=params)

    def _call_remove_device(self, args: Dict[str, Any]) -> Any:
        device_id = args.get("id", "")
        if not device_id:
            raise ValueError("id 为必填参数")
        return self._request_m3(
            method="POST",
            path=f"/api/v3/devices/{device_id}/remove",
        )

    def _call_get_sync_status(self, args: Dict[str, Any]) -> Any:
        return self._request_m3(method="GET", path="/api/v3/sync/status")

    def _call_trigger_sync(self, args: Dict[str, Any]) -> Any:
        body: Dict[str, Any] = {}
        if args.get("direction"):
            body["direction"] = args["direction"]
        if args.get("device_ids"):
            body["device_ids"] = args["device_ids"]
        return self._request_m3(method="POST", path="/api/v3/sync/trigger", json=body)

    def _call_list_conflicts(self, args: Dict[str, Any]) -> Any:
        params: Dict[str, Any] = {}
        if args.get("resolved") is not None:
            params["resolved"] = args["resolved"]
        return self._request_m3(method="GET", path="/api/v3/sync/conflicts", params=params)

    def _call_resolve_conflict(self, args: Dict[str, Any]) -> Any:
        conflict_id = args.get("id", "")
        resolution = args.get("resolution", "")
        if not conflict_id:
            raise ValueError("id 为必填参数")
        if not resolution:
            raise ValueError("resolution 为必填参数")
        return self._request_m3(
            method="POST",
            path=f"/api/v3/sync/conflicts/{conflict_id}/resolve",
            json={"resolution": resolution},
        )

    def _call_get_config(self, args: Dict[str, Any]) -> Any:
        return self._request_m3(method="GET", path="/api/v3/config")

    def _call_update_config(self, args: Dict[str, Any]) -> Any:
        config = args.get("config")
        if not config:
            raise ValueError("config 为必填参数")
        return self._request_m3(
            method="POST",
            path="/api/v3/config/update",
            json={"config": config},
        )

    def _call_health_check(self, args: Dict[str, Any]) -> Any:
        return self._request_m3(method="GET", path="/api/v3/health")

    def _call_metrics(self, args: Dict[str, Any]) -> Any:
        return self._request_m3(method="GET", path="/api/v3/metrics")

    # ---- HTTP 请求封装 ----

    def _request_m3(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.m3_base_url}{path}"
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(
                    method=method,
                    url=url,
                    json=json,
                    params=params,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", e.response.text)
            except Exception:
                detail = e.response.text or str(e)
            raise RuntimeError(f"M3 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M3 API 网络错误: {e}") from e