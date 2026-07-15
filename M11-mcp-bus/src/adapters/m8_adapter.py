"""M11 MCP Bus - M8 控制塔适配器.

将 M8 控制塔的模块管理、健康检查、配置与部署能力封装为 MCP 工具服务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class M8ControlAdapter(BaseMcpAdapter):
    """M8 控制塔 MCP 适配器.

    提供的 MCP 工具：
    - m8.list_modules: 获取模块列表
    - m8.get_module: 获取模块详情
    - m8.get_health: 获取健康状态
    - m8.get_config: 获取配置信息
    - m8.deploy_module: 部署指定模块
    """

    adapter_name: str = "m8"
    adapter_description: str = "M8 控制塔 - 模块管理、健康检查、配置与部署"

    def __init__(
        self,
        m8_base_url: str = "http://localhost:8008",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
    ) -> None:
        super().__init__(
            bus_url=bus_url,
            server_name="m8",
            server_endpoint=server_endpoint,
        )
        self.m8_base_url = m8_base_url.rstrip("/")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "m8.list_modules",
                "description": "获取 M8 所有模块列表。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m8.get_module",
                "description": "获取指定模块的详细信息。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "module_id": {
                            "type": "string",
                            "description": "模块 ID",
                        },
                    },
                    "required": ["module_id"],
                },
            },
            {
                "name": "m8.get_health",
                "description": "获取 M8 控制塔健康状态。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m8.get_config",
                "description": "获取 M8 控制塔配置信息。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m8.deploy_module",
                "description": "部署指定模块到运行环境。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "module_id": {
                            "type": "string",
                            "description": "模块 ID",
                        },
                    },
                    "required": ["module_id"],
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool_map = {
            "m8.list_modules": self._call_list_modules,
            "m8.get_module": self._call_get_module,
            "m8.get_health": self._call_get_health,
            "m8.get_config": self._call_get_config,
            "m8.deploy_module": self._call_deploy_module,
        }
        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的 M8 工具: {name}")
        result = handler(args)
        return self._wrap_result(result)

    def _call_list_modules(self, args: Dict[str, Any]) -> Any:
        return self._request_m8(
            method="GET",
            path="/api/v1/modules",
        )

    def _call_get_module(self, args: Dict[str, Any]) -> Any:
        module_id = args.get("module_id", "")
        if not module_id:
            raise ValueError("module_id 为必填参数")
        return self._request_m8(
            method="GET",
            path=f"/api/v1/modules/{module_id}",
        )

    def _call_get_health(self, args: Dict[str, Any]) -> Any:
        return self._request_m8(
            method="GET",
            path="/api/v1/health",
        )

    def _call_get_config(self, args: Dict[str, Any]) -> Any:
        return self._request_m8(
            method="GET",
            path="/api/v1/config",
        )

    def _call_deploy_module(self, args: Dict[str, Any]) -> Any:
        module_id = args.get("module_id", "")
        if not module_id:
            raise ValueError("module_id 为必填参数")
        return self._request_m8(
            method="POST",
            path=f"/api/v1/modules/{module_id}/deploy",
        )

    def _request_m8(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.m8_base_url}{path}"
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
            raise RuntimeError(f"M8 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M8 API 网络错误: {e}") from e
