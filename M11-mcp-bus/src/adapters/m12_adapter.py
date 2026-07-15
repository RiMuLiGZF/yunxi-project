"""M11 MCP Bus - M12 安全网关适配器.

将 M12 安全网关的 WAF 检查、审计日志、IP 黑名单管理能力封装为 MCP 工具服务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class M12SecurityAdapter(BaseMcpAdapter):
    """M12 安全网关 MCP 适配器.

    提供的 MCP 工具：
    - m12.check_waf: WAF 网关安全检查
    - m12.list_audit_logs: 获取审计日志列表
    - m12.list_ip_blacklist: 获取 IP 黑名单
    - m12.add_ip_blacklist: 添加 IP 到黑名单
    """

    adapter_name: str = "m12"
    adapter_description: str = "M12 安全网关 - WAF 检查、审计日志、IP 黑名单管理"

    def __init__(
        self,
        m12_base_url: str = "http://localhost:8012",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
    ) -> None:
        super().__init__(
            bus_url=bus_url,
            server_name="m12",
            server_endpoint=server_endpoint,
        )
        self.m12_base_url = m12_base_url.rstrip("/")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "m12.check_waf",
                "description": "执行 WAF 网关安全检查，验证请求是否通过安全策略。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "检查目标地址或域名",
                            "default": "",
                        },
                    },
                },
            },
            {
                "name": "m12.list_audit_logs",
                "description": "获取 M12 审计日志列表，支持分页。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "页码，从 1 开始",
                            "default": 1,
                        },
                        "page_size": {
                            "type": "integer",
                            "description": "每页数量",
                            "default": 20,
                        },
                    },
                },
            },
            {
                "name": "m12.list_ip_blacklist",
                "description": "获取当前 IP 黑名单列表。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m12.add_ip_blacklist",
                "description": "将指定 IP 添加到黑名单。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ip": {
                            "type": "string",
                            "description": "要封禁的 IP 地址",
                        },
                        "reason": {
                            "type": "string",
                            "description": "封禁原因",
                            "default": "",
                        },
                        "duration": {
                            "type": "integer",
                            "description": "封禁时长（秒），0 表示永久封禁",
                            "default": 0,
                        },
                    },
                    "required": ["ip"],
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool_map = {
            "m12.check_waf": self._call_check_waf,
            "m12.list_audit_logs": self._call_list_audit_logs,
            "m12.list_ip_blacklist": self._call_list_ip_blacklist,
            "m12.add_ip_blacklist": self._call_add_ip_blacklist,
        }
        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的 M12 工具: {name}")
        result = handler(args)
        return self._wrap_result(result)

    def _call_check_waf(self, args: Dict[str, Any]) -> Any:
        payload: Dict[str, Any] = {}
        if args.get("target"):
            payload["target"] = args["target"]
        return self._request_m12(
            method="POST",
            path="/api/m12/waf/gateway-check",
            json=payload if payload else None,
        )

    def _call_list_audit_logs(self, args: Dict[str, Any]) -> Any:
        params: Dict[str, Any] = {}
        if "page" in args:
            params["page"] = args["page"]
        if "page_size" in args:
            params["page_size"] = args["page_size"]
        return self._request_m12(
            method="GET",
            path="/api/m12/audit/logs",
            params=params if params else None,
        )

    def _call_list_ip_blacklist(self, args: Dict[str, Any]) -> Any:
        return self._request_m12(
            method="GET",
            path="/api/m12/ip-filter/blacklist",
        )

    def _call_add_ip_blacklist(self, args: Dict[str, Any]) -> Any:
        ip = args.get("ip", "")
        if not ip:
            raise ValueError("ip 为必填参数")
        return self._request_m12(
            method="POST",
            path="/api/m12/ip-filter/blacklist",
            json={
                "ip": ip,
                "reason": args.get("reason", ""),
                "duration": args.get("duration", 0),
            },
        )

    def _request_m12(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.m12_base_url}{path}"
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
            raise RuntimeError(f"M12 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M12 API 网络错误: {e}") from e
