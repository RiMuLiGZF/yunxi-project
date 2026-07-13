"""MCP (Model Context Protocol) 传输层.

负责 MCP 协议的序列化/反序列化、消息路由、以及与 Skill 系统的桥接。
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult

logger = structlog.get_logger()

# MCP 协议版本
MCP_VERSION = "2024-11-05"


class MCPTransportError(Exception):
    """MCP 传输错误."""
    pass


class MCPRequest:
    """MCP 请求消息."""

    def __init__(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        request_id: str | int | None = None,
        jsonrpc: str = "2.0",
    ) -> None:
        self.jsonrpc = jsonrpc
        self.id = request_id
        self.method = method
        self.params = params or {}

    @classmethod
    def from_dict(cls, data: dict) -> "MCPRequest":
        if "method" not in data:
            raise MCPTransportError("Missing 'method' in MCP request")
        return cls(
            method=data["method"],
            params=data.get("params"),
            request_id=data.get("id"),
            jsonrpc=data.get("jsonrpc", "2.0"),
        )

    def to_dict(self) -> dict:
        result = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.id is not None:
            result["id"] = self.id
        if self.params:
            result["params"] = self.params
        return result


class MCPResponse:
    """MCP 响应消息."""

    def __init__(
        self,
        request_id: str | int | None = None,
        result: dict | list | None = None,
        error: dict | None = None,
        jsonrpc: str = "2.0",
    ) -> None:
        self.jsonrpc = jsonrpc
        self.id = request_id
        self.result = result
        self.error = error

    @classmethod
    def from_dict(cls, data: dict) -> "MCPResponse":
        return cls(
            request_id=data.get("id"),
            result=data.get("result"),
            error=data.get("error"),
            jsonrpc=data.get("jsonrpc", "2.0"),
        )

    def to_dict(self) -> dict:
        result_data = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            result_data["error"] = self.error
        else:
            result_data["result"] = self.result or {}
        return result_data

    @property
    def is_error(self) -> bool:
        return self.error is not None


class MCPNotification:
    """MCP 通知消息（无 id）."""

    def __init__(self, method: str, params: dict | None = None) -> None:
        self.method = method
        self.params = params or {}

    def to_dict(self) -> dict:
        return {"method": self.method, "params": self.params}


class MCPTransport:
    """MCP 协议传输层.

    负责 JSON-RPC 消息的解析与构造，
    以及 Skill 调用请求/结果与 MCP 消息的互相转换。
    """

    def __init__(self) -> None:
        self._request_counter: int = 0

    def parse_message(self, raw: str | dict) -> MCPRequest | MCPResponse | MCPNotification:
        """解析原始消息.

        Args:
            raw: 原始消息（JSON 字符串或 dict）.

        Returns:
            MCPRequest / MCPResponse / MCPNotification.
        """
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise MCPTransportError(f"Invalid JSON: {e}")
        else:
            data = raw

        if not isinstance(data, dict):
            raise MCPTransportError("Message must be a JSON object")

        if "method" in data:
            if "id" in data:
                return MCPRequest.from_dict(data)
            else:
                return MCPNotification(
                    method=data["method"],
                    params=data.get("params"),
                )
        elif "result" in data or "error" in data:
            return MCPResponse.from_dict(data)
        else:
            raise MCPTransportError("Unrecognized message format")

    def build_response(
        self,
        request_id: str | int | None,
        result: dict | list | None = None,
        error: dict | None = None,
    ) -> MCPResponse:
        """构建响应."""
        return MCPResponse(request_id=request_id, result=result, error=error)

    def skill_request_to_mcp(
        self,
        request: SkillInvokeRequest,
        request_id: str | int | None = None,
    ) -> MCPRequest:
        """将 SkillInvokeRequest 转换为 MCP tools/call 调用."""
        rid = request_id or self._next_id()
        return MCPRequest(
            method="tools/call",
            params={
                "name": f"{request.skill_id}.{request.action}",
                "arguments": request.params,
            },
            request_id=rid,
        )

    def mcp_to_skill_result(self, response: MCPResponse, request: SkillInvokeRequest) -> SkillInvokeResult:
        """将 MCP 响应转换为 SkillInvokeResult."""
        if response.is_error:
            err = response.error or {}
            return SkillInvokeResult(
                skill_id=request.skill_id,
                action=request.action,
                status="failure",
                error=err.get("message", "MCP error"),
                error_code=err.get("code"),
                trace_id=request.trace_id,
            )

        result_data = response.result or {}
        # MCP content 数组中提取文本
        content = result_data.get("content", [])
        data = None
        if content:
            if len(content) == 1 and content[0].get("type") == "text":
                data = content[0].get("text")
            else:
                data = content

        return SkillInvokeResult(
            skill_id=request.skill_id,
            action=request.action,
            status="success",
            data=data,
            trace_id=request.trace_id,
        )

    def _next_id(self) -> int:
        self._request_counter += 1
        return self._request_counter
