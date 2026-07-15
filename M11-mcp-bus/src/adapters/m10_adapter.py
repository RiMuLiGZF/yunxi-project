"""M11 MCP Bus - M10 硬件策略适配器.

将 M10 硬件策略模块的指标监控、状态汇总能力封装为 MCP 工具服务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class M10MetricsAdapter(BaseMcpAdapter):
    """M10 硬件策略 MCP 适配器.

    提供的 MCP 工具：
    - m10.get_metrics: 获取所有指标数据
    - m10.get_metric_type: 获取指定类型指标
    - m10.get_summary: 获取状态摘要
    - m10.get_gpu_summary: 获取 GPU 状态摘要
    """

    adapter_name: str = "m10"
    adapter_description: str = "M10 硬件策略 - 指标监控与状态汇总"

    def __init__(
        self,
        m10_base_url: str = "http://localhost:8010",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
    ) -> None:
        super().__init__(
            bus_url=bus_url,
            server_name="m10",
            server_endpoint=server_endpoint,
        )
        self.m10_base_url = m10_base_url.rstrip("/")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "m10.get_metrics",
                "description": "获取 M10 所有硬件指标数据（CPU、内存、GPU、网络等）。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m10.get_metric_type",
                "description": "获取指定类型的硬件指标数据。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "metric_type": {
                            "type": "string",
                            "description": "指标类型，如 cpu、memory、gpu、network、disk",
                        },
                    },
                    "required": ["metric_type"],
                },
            },
            {
                "name": "m10.get_summary",
                "description": "获取 M10 硬件状态总体摘要。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m10.get_gpu_summary",
                "description": "获取 M10 GPU 状态摘要，包括利用率、显存、温度等。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool_map = {
            "m10.get_metrics": self._call_get_metrics,
            "m10.get_metric_type": self._call_get_metric_type,
            "m10.get_summary": self._call_get_summary,
            "m10.get_gpu_summary": self._call_get_gpu_summary,
        }
        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的 M10 工具: {name}")
        result = handler(args)
        return self._wrap_result(result)

    def _call_get_metrics(self, args: Dict[str, Any]) -> Any:
        return self._request_m10(
            method="GET",
            path="/api/v1/status/metrics",
        )

    def _call_get_metric_type(self, args: Dict[str, Any]) -> Any:
        metric_type = args.get("metric_type", "")
        if not metric_type:
            raise ValueError("metric_type 为必填参数")
        return self._request_m10(
            method="GET",
            path=f"/api/v1/status/metrics/{metric_type}",
        )

    def _call_get_summary(self, args: Dict[str, Any]) -> Any:
        return self._request_m10(
            method="GET",
            path="/api/v1/status/summary",
        )

    def _call_get_gpu_summary(self, args: Dict[str, Any]) -> Any:
        return self._request_m10(
            method="GET",
            path="/api/v1/status/gpu/summary",
        )

    def _request_m10(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.m10_base_url}{path}"
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
            raise RuntimeError(f"M10 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M10 API 网络错误: {e}") from e
