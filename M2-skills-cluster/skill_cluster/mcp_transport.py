from __future__ import annotations

"""【DEPRECATED】MCP 传输层已迁移.

本模块已迁移至 :mod:`skill_cluster.extensions.mcp.transport`，
请使用 ``from skill_cluster.extensions.mcp import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出主要符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.mcp_transport 已迁移至 skill_cluster.extensions.mcp.transport，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.extensions.mcp.transport import (
    MCPNotification,
    MCPRequest,
    MCPResponse,
    MCPTransport,
    MCPTransportError,
)

# 向后兼容的便捷函数
def handle_mcp_tool_list(registry=None) -> dict:
    """MCP 工具列表处理函数（向后兼容）."""
    tools = []
    if registry:
        sids = registry.list_skills() if hasattr(registry, "list_skills") else []
        for sid in sids:
            skill = registry.get_skill(sid) if hasattr(registry, "get_skill") else None
            if skill is None:
                continue
            manifest = getattr(skill, "manifest", skill)
            actions = getattr(manifest, "actions", [])
            for action in actions:
                action_name = getattr(action, "name", "default")
                tools.append({
                    "name": f"{sid}.{action_name}",
                    "description": getattr(action, "description", "") or getattr(manifest, "description", ""),
                    "inputSchema": getattr(action, "input_schema", {"type": "object", "properties": {}}),
                })
    return {"tools": tools}


async def handle_mcp_tool_call(params: dict, registry=None, router=None) -> dict:
    """MCP 工具调用处理函数（向后兼容）."""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if "." in tool_name and router:
        skill_id, action = tool_name.rsplit(".", 1)
        from skill_cluster.interfaces import SkillInvokeRequest as RouterInvokeRequest
        import uuid
        invoke_req = RouterInvokeRequest(
            skill_id=skill_id,
            action=action,
            params=arguments,
            trace_id=f"mcp-{uuid.uuid4().hex[:8]}",
        )
        result = await router.invoke(invoke_req, "mcp-client")
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
    return {"content": [], "isError": True}


def wrap_jsonrpc_response(request: dict, result: dict) -> dict:
    """包装 JSON-RPC 响应（向后兼容）."""
    req_id = request.get("id") if isinstance(request, dict) else None
    if req_id is not None:
        return {
            "jsonrpc": "2.0",
            "result": result,
            "id": req_id,
        }
    return result


__all__ = [
    "MCPTransport",
    "MCPRequest",
    "MCPResponse",
    "MCPNotification",
    "MCPTransportError",
    "handle_mcp_tool_list",
    "handle_mcp_tool_call",
    "wrap_jsonrpc_response",
]
