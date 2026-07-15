"""M11 MCP Bus - M6 硬件外设适配器.

将 M6 硬件外设的设备管理、配对、传感器数据采集、
设备控制与告警能力封装为 MCP 工具服务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class M6HardwareAdapter(BaseMcpAdapter):
    """M6 硬件外设 MCP 适配器.

    提供的 MCP 工具：
    - m6.list_device_types: 设备类型列表
    - m6.list_devices: 设备列表
    - m6.get_device_stats: 设备统计
    - m6.get_device: 设备详情
    - m6.pair_device: 配对设备
    - m6.unpair_device: 取消配对
    - m6.scan_devices: 扫描设备
    - m6.get_sensor_data: 传感器数据
    - m6.get_sensor_history: 传感器历史
    - m6.send_device_action: 设备动作
    - m6.push_notification: 推送通知
    - m6.get_device_alerts: 设备告警
    """

    adapter_name: str = "m6"
    adapter_description: str = "M6 硬件外设 - 设备管理、配对、传感器采集、控制与告警"

    def __init__(
        self,
        m6_base_url: str = "http://localhost:8006",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
    ) -> None:
        super().__init__(
            bus_url=bus_url,
            server_name="m6",
            server_endpoint=server_endpoint,
        )
        self.m6_base_url = m6_base_url.rstrip("/")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "m6.list_device_types",
                "description": "列出 M6 支持的所有设备类型。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m6.list_devices",
                "description": "列出 M6 中所有已连接的设备。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "按设备类型筛选（可选）",
                        },
                        "status": {
                            "type": "string",
                            "description": "按设备状态筛选（可选）",
                        },
                    },
                },
            },
            {
                "name": "m6.get_device_stats",
                "description": "获取 M6 设备的汇总统计数据。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m6.get_device",
                "description": "获取 M6 中指定设备的详细信息。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "device_id": {
                            "type": "string",
                            "description": "设备 ID",
                        },
                    },
                    "required": ["device_id"],
                },
            },
            {
                "name": "m6.pair_device",
                "description": "配对指定设备到 M6。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "device_id": {
                            "type": "string",
                            "description": "设备 ID",
                        },
                        "pin_code": {
                            "type": "string",
                            "description": "配对码（可选）",
                        },
                    },
                    "required": ["device_id"],
                },
            },
            {
                "name": "m6.unpair_device",
                "description": "取消 M6 中指定设备的配对。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "device_id": {
                            "type": "string",
                            "description": "设备 ID",
                        },
                    },
                    "required": ["device_id"],
                },
            },
            {
                "name": "m6.scan_devices",
                "description": "扫描附近可发现的硬件设备。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "timeout": {
                            "type": "integer",
                            "description": "扫描超时秒数（可选，默认 10）",
                        },
                        "device_type": {
                            "type": "string",
                            "description": "限定扫描的设备类型（可选）",
                        },
                    },
                },
            },
            {
                "name": "m6.get_sensor_data",
                "description": "获取指定设备的实时传感器数据。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "device_id": {
                            "type": "string",
                            "description": "设备 ID",
                        },
                    },
                    "required": ["device_id"],
                },
            },
            {
                "name": "m6.get_sensor_history",
                "description": "获取指定设备的传感器历史数据。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "device_id": {
                            "type": "string",
                            "description": "设备 ID",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "起始时间 ISO 格式（可选）",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "结束时间 ISO 格式（可选）",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回记录数上限（可选）",
                        },
                    },
                    "required": ["device_id"],
                },
            },
            {
                "name": "m6.send_device_action",
                "description": "向指定设备发送控制动作指令。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "device_id": {
                            "type": "string",
                            "description": "设备 ID",
                        },
                        "action": {
                            "type": "string",
                            "description": "动作名称",
                        },
                        "params": {
                            "type": "object",
                            "description": "动作参数（可选）",
                        },
                    },
                    "required": ["device_id", "action"],
                },
            },
            {
                "name": "m6.push_notification",
                "description": "向指定设备推送通知。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "device_id": {
                            "type": "string",
                            "description": "设备 ID",
                        },
                        "title": {
                            "type": "string",
                            "description": "通知标题",
                        },
                        "body": {
                            "type": "string",
                            "description": "通知内容",
                        },
                    },
                    "required": ["device_id", "title", "body"],
                },
            },
            {
                "name": "m6.get_device_alerts",
                "description": "获取指定设备的告警记录。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "device_id": {
                            "type": "string",
                            "description": "设备 ID",
                        },
                        "level": {
                            "type": "string",
                            "description": "按告警级别筛选（可选）",
                        },
                    },
                    "required": ["device_id"],
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool_map = {
            "m6.list_device_types": self._call_list_device_types,
            "m6.list_devices": self._call_list_devices,
            "m6.get_device_stats": self._call_get_device_stats,
            "m6.get_device": self._call_get_device,
            "m6.pair_device": self._call_pair_device,
            "m6.unpair_device": self._call_unpair_device,
            "m6.scan_devices": self._call_scan_devices,
            "m6.get_sensor_data": self._call_get_sensor_data,
            "m6.get_sensor_history": self._call_get_sensor_history,
            "m6.send_device_action": self._call_send_device_action,
            "m6.push_notification": self._call_push_notification,
            "m6.get_device_alerts": self._call_get_device_alerts,
        }
        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的 M6 工具: {name}")
        result = handler(args)
        return self._wrap_result(result)

    # ---- 工具调用实现 ----

    def _call_list_device_types(self, args: Dict[str, Any]) -> Any:
        return self._request_m6(method="GET", path="/api/v1/devices/types")

    def _call_list_devices(self, args: Dict[str, Any]) -> Any:
        params: Dict[str, Any] = {}
        if args.get("type"):
            params["type"] = args["type"]
        if args.get("status"):
            params["status"] = args["status"]
        return self._request_m6(method="GET", path="/api/v1/devices", params=params)

    def _call_get_device_stats(self, args: Dict[str, Any]) -> Any:
        return self._request_m6(method="GET", path="/api/v1/devices/stats")

    def _call_get_device(self, args: Dict[str, Any]) -> Any:
        device_id = args.get("device_id", "")
        if not device_id:
            raise ValueError("device_id 为必填参数")
        return self._request_m6(
            method="GET",
            path=f"/api/v1/devices/{device_id}",
        )

    def _call_pair_device(self, args: Dict[str, Any]) -> Any:
        device_id = args.get("device_id", "")
        if not device_id:
            raise ValueError("device_id 为必填参数")
        body: Dict[str, Any] = {}
        if args.get("pin_code"):
            body["pin_code"] = args["pin_code"]
        return self._request_m6(
            method="POST",
            path=f"/api/v1/devices/{device_id}/pair",
            json=body,
        )

    def _call_unpair_device(self, args: Dict[str, Any]) -> Any:
        device_id = args.get("device_id", "")
        if not device_id:
            raise ValueError("device_id 为必填参数")
        return self._request_m6(
            method="POST",
            path=f"/api/v1/devices/{device_id}/unpair",
        )

    def _call_scan_devices(self, args: Dict[str, Any]) -> Any:
        body: Dict[str, Any] = {}
        if args.get("timeout") is not None:
            body["timeout"] = args["timeout"]
        if args.get("device_type"):
            body["device_type"] = args["device_type"]
        return self._request_m6(
            method="POST",
            path="/api/v1/devices/scan",
            json=body,
        )

    def _call_get_sensor_data(self, args: Dict[str, Any]) -> Any:
        device_id = args.get("device_id", "")
        if not device_id:
            raise ValueError("device_id 为必填参数")
        return self._request_m6(
            method="GET",
            path=f"/api/v1/sensors/{device_id}",
        )

    def _call_get_sensor_history(self, args: Dict[str, Any]) -> Any:
        device_id = args.get("device_id", "")
        if not device_id:
            raise ValueError("device_id 为必填参数")
        params: Dict[str, Any] = {}
        if args.get("start_time"):
            params["start_time"] = args["start_time"]
        if args.get("end_time"):
            params["end_time"] = args["end_time"]
        if args.get("limit") is not None:
            params["limit"] = args["limit"]
        return self._request_m6(
            method="GET",
            path=f"/api/v1/sensors/{device_id}/history",
            params=params,
        )

    def _call_send_device_action(self, args: Dict[str, Any]) -> Any:
        device_id = args.get("device_id", "")
        action = args.get("action", "")
        if not device_id:
            raise ValueError("device_id 为必填参数")
        if not action:
            raise ValueError("action 为必填参数")
        body: Dict[str, Any] = {"action": action}
        if args.get("params"):
            body["params"] = args["params"]
        return self._request_m6(
            method="POST",
            path=f"/api/v1/control/{device_id}/action",
            json=body,
        )

    def _call_push_notification(self, args: Dict[str, Any]) -> Any:
        device_id = args.get("device_id", "")
        title = args.get("title", "")
        body = args.get("body", "")
        if not device_id:
            raise ValueError("device_id 为必填参数")
        if not title:
            raise ValueError("title 为必填参数")
        if not body:
            raise ValueError("body 为必填参数")
        return self._request_m6(
            method="POST",
            path=f"/api/v1/control/{device_id}/notify",
            json={"title": title, "body": body},
        )

    def _call_get_device_alerts(self, args: Dict[str, Any]) -> Any:
        device_id = args.get("device_id", "")
        if not device_id:
            raise ValueError("device_id 为必填参数")
        params: Dict[str, Any] = {}
        if args.get("level"):
            params["level"] = args["level"]
        return self._request_m6(
            method="GET",
            path=f"/api/v1/control/{device_id}/alerts",
            params=params,
        )

    # ---- HTTP 请求封装 ----

    def _request_m6(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.m6_base_url}{path}"
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
            raise RuntimeError(f"M6 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M6 API 网络错误: {e}") from e