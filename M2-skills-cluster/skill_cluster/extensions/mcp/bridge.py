"""MCP (Model Context Protocol) 桥接层.

将 Skill Router 暴露为 MCP Server，或将外部 MCP Server
接入为 Skill 技能。支持双向桥接。
"""

from __future__ import annotations

from typing import Any

import structlog

from skill_cluster.core.middleware import MiddlewarePipeline, event_middleware
from skill_cluster.interfaces import ISkill, SkillInvokeRequest, SkillInvokeResult
from skill_cluster.core.router import SkillRouter
from skill_cluster.core.registry import SkillRegistry
from skill_cluster.extensions.mcp.transport import (
    MCPNotification,
    MCPRequest,
    MCPResponse,
    MCPTransport,
)
from skill_cluster.infrastructure.event_bus import EventBus

logger = structlog.get_logger()


class MCPServerBridge:
    """MCP Server 桥接.

    将 Skill Router 封装为 MCP Server，
    处理 tools/list、tools/call 等 MCP 方法。
    """

    def __init__(
        self,
        router: SkillRouter | None = None,
        transport: MCPTransport | None = None,
    ) -> None:
        self._router = router or SkillRouter()
        self._transport = transport or MCPTransport()
        self._initialized = False
        self._client_capabilities: dict[str, Any] = {}
        self._server_capabilities = {
            "tools": {},
            "logging": {},
        }

    async def handle_message(self, raw: str | dict) -> MCPResponse | None:
        """处理 MCP 消息.

        Args:
            raw: 原始消息.

        Returns:
            MCPResponse（通知类消息返回 None）.
        """
        msg = self._transport.parse_message(raw)

        if isinstance(msg, MCPNotification):
            await self._handle_notification(msg)
            return None

        if isinstance(msg, MCPResponse):
            # Server 端通常不接收 Response（除非是 Client 发的）
            logger.warning("mcp_unexpected_response", id=msg.id)
            return None

        return await self._handle_request(msg)

    async def _handle_request(self, request: MCPRequest) -> MCPResponse:
        """处理 MCP 请求."""
        handler = {
            "initialize": self._handle_initialize,
            "notifications/initialized": self._handle_initialized,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "ping": self._handle_ping,
        }.get(request.method)

        if handler is None:
            return self._transport.build_response(
                request.id,
                error={"code": -32601, "message": f"Method not found: {request.method}"},
            )

        try:
            result = await handler(request.params)
            return self._transport.build_response(request.id, result=result)
        except Exception as e:
            logger.error("mcp_handler_error", method=request.method, error=str(e))
            return self._transport.build_response(
                request.id,
                error={"code": -32603, "message": str(e)},
            )

    async def _handle_notification(self, notification: MCPNotification) -> None:
        """处理 MCP 通知."""
        if notification.method == "notifications/initialized":
            self._initialized = True
            logger.info("mcp_client_initialized")
        else:
            logger.debug("mcp_notification", method=notification.method)

    async def _handle_initialize(self, params: dict) -> dict:
        """处理 initialize 请求."""
        self._client_capabilities = params.get("capabilities", {})
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": self._server_capabilities,
            "serverInfo": {"name": "yunxi-skill-cluster", "version": "1.0.0"},
        }

    async def _handle_initialized(self, params: dict) -> None:
        """处理 initialized 通知."""
        self._initialized = True

    async def _handle_tools_list(self, params: dict) -> dict:
        """处理 tools/list 请求."""
        tools = []
        for sid in self._router._registry.list_skills():
            skill = self._router._registry.get_skill(sid)
            if skill is None:
                continue
            manifest = skill.manifest
            for action in manifest.actions:
                tool_name = f"{sid}.{action.name}"
                tools.append({
                    "name": tool_name,
                    "description": action.description or manifest.description,
                    "inputSchema": action.input_schema or {"type": "object", "properties": {}},
                })
        return {"tools": tools}

    async def _handle_tools_call(self, params: dict) -> dict:
        """处理 tools/call 请求."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if "." not in tool_name:
            raise ValueError(f"Invalid tool name format: {tool_name}")

        skill_id, action = tool_name.rsplit(".", 1)

        request = SkillInvokeRequest(
            skill_id=skill_id,
            action=action,
            params=arguments,
            trace_id=f"mcp-{id(params)}",
        )

        result = await self._router.invoke(request, "mcp-client")

        if result.status == "success":
            content = []
            if result.data is not None:
                if isinstance(result.data, str):
                    content.append({"type": "text", "text": result.data})
                else:
                    content.append({"type": "text", "text": str(result.data)})
            return {"content": content}
        else:
            return {
                "content": [{"type": "text", "text": result.error or "Unknown error"}],
                "isError": True,
            }

    async def _handle_ping(self, params: dict) -> dict:
        """处理 ping 请求."""
        return {}


class MCPClientBridge:
    """MCP Client 桥接.

    将外部 MCP Server 接入为 Skill。
    通过自定义的 send_fn 与外部 MCP Server 通信。
    """

    def __init__(
        self,
        send_fn: Any,  # Callable[[dict], Awaitable[dict]]
        transport: MCPTransport | None = None,
    ) -> None:
        self._send_fn = send_fn
        self._transport = transport or MCPTransport()
        self._tools: list[dict] = []

    async def initialize(self) -> None:
        """初始化连接."""
        init_req = self._transport.build_response(
            None,  # 用 request
        )
        # 发送 initialize
        req = MCPRequest(
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "yunxi-skill-cluster", "version": "1.0.0"},
            },
            request_id=1,
        )
        resp_dict = await self._send_fn(req.to_dict())
        resp = MCPResponse.from_dict(resp_dict)
        if resp.is_error:
            raise RuntimeError(f"MCP initialize failed: {resp.error}")
        logger.info("mcp_client_initialized", server_info=resp.result.get("serverInfo"))

        # 发送 initialized 通知
        notif = MCPNotification(method="notifications/initialized")
        await self._send_fn(notif.to_dict())

        # 获取工具列表
        tools_req = MCPRequest(method="tools/list", request_id=2)
        tools_resp_dict = await self._send_fn(tools_req.to_dict())
        tools_resp = MCPResponse.from_dict(tools_resp_dict)
        if not tools_resp.is_error:
            self._tools = tools_resp.result.get("tools", [])
            logger.info("mcp_tools_loaded", count=len(self._tools))

    @property
    def tools(self) -> list[dict]:
        """获取工具列表."""
        return self._tools

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """调用工具.

        Args:
            name: 工具名称.
            arguments: 参数.

        Returns:
            工具调用结果.
        """
        req = MCPRequest(
            method="tools/call",
            params={"name": name, "arguments": arguments or {}},
            request_id=None,  # 会自动生成
        )
        resp_dict = await self._send_fn(req.to_dict())
        resp = MCPResponse.from_dict(resp_dict)
        if resp.is_error:
            raise RuntimeError(f"Tool call failed: {resp.error}")
        return resp.result or {}
