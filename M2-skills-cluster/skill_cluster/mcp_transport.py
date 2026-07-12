from __future__ import annotations

"""MCP Transport - MCP JSON-RPC 2.0 HTTP 传输适配器.

【整改 R02 - 评审报告 REV-20250628-M2-001】
评审意见：MCP 2026 字段仅停留在数据模型层，缺少实际传输适配器。

实现 MCP JSON-RPC 2.0 over HTTP：
- POST /mcp/v1/tools/call    — 工具调用
- POST /mcp/v1/tools/list    — 工具列表
- 请求/响应严格遵循 JSON-RPC 2.0 规范
- 支持 MCP 2026 的 _meta._progress 进度通知（预留）
"""

import time
import uuid
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


# ---- MCP JSON-RPC 2.0 数据模型 ----

class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 请求."""
    jsonrpc: str = Field(default="2.0", description="协议版本")
    method: str = Field(..., description="方法名")
    params: dict[str, Any] = Field(default_factory=dict, description="参数")
    id: str | int | None = Field(default=None, description="请求ID")


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 响应."""
    jsonrpc: str = "2.0"
    result: Any = None
    error: dict[str, Any] | None = None
    id: str | int | None = None


class McpToolCallParams(BaseModel):
    """MCP tools/call 参数."""
    name: str = Field(..., description="工具名")
    arguments: dict[str, Any] = Field(default_factory=dict, description="参数")
    meta: dict[str, Any] | None = Field(default=None, description="MCP _meta metadata")


class McpToolInfo(BaseModel):
    """MCP 工具信息."""
    name: str
    description: str = ""
    inputSchema: dict[str, Any] = Field(default_factory=dict)


# ---- MCP 传输处理函数 ----

async def handle_mcp_tool_call(
    params: dict[str, Any],
    registry: Any = None,
    router: Any = None,
) -> dict[str, Any]:
    """处理 MCP tools/call 请求.

    Args:
        params: MCP tools/call 参数（name + arguments）.
        registry: SkillRegistry（用于查找技能schema）.
        router: SkillRouter（用于执行调用）.

    Returns:
        MCP 标准结果 content 数组.
    """
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if router is None:
        return _error_response(-32603, "Router not configured")

    # 从 tool_name 解析 skill_id 和 action（格式：skill_id:action 或 skill_id）
    skill_id = tool_name
    action = "default"
    if ":" in tool_name:
        skill_id, action = tool_name.split(":", 1)

    try:
        from skill_cluster.interfaces import SkillInvokeRequest
        request = SkillInvokeRequest(
            skill_id=skill_id,
            action=action,
            params=arguments,
            trace_id=f"mcp_{uuid.uuid4().hex[:12]}",
            cache_scope=params.get("_meta", {}).get("cacheScope", "public") if isinstance(params.get("_meta"), dict) else "public",
            ttl_ms=params.get("_meta", {}).get("ttlMs") if isinstance(params.get("_meta"), dict) else None,
        )
        result = await router.invoke(request, "mcp_client")

        # MCP 标准响应格式：content 数组
        content: list[dict[str, Any]] = []
        if result.data is not None:
            content.append({
                "type": "text",
                "text": str(result.data),
            })
        return {
            "content": content,
            "isError": result.status != "success",
        }
    except Exception as e:
        logger.error("mcp_tool_call_error", tool=tool_name, error=str(e))
        return _error_response(-32603, str(e))


def handle_mcp_tool_list(registry: Any = None) -> dict[str, Any]:
    """处理 MCP tools/list 请求.

    Returns:
        MCP 标准工具列表.
    """
    if registry is None:
        return _error_response(-32603, "Registry not configured")

    tools: list[dict[str, Any]] = []
    try:
        for manifest in registry.all_manifests():
            try:
                action = manifest.actions[0] if manifest.actions else "default"
                schema = registry.get_schema(manifest.skill_id, action)
                input_schema: dict[str, Any] = {}
                if schema is not None:
                    # 尝试将 schema 转为 dict（兼容 pydantic 模型等）
                    if hasattr(schema, 'parameters'):
                        params = schema.parameters
                        if hasattr(params, 'model_dump'):
                            input_schema = params.model_dump()
                        elif hasattr(params, 'dict'):
                            input_schema = params.dict()
                        elif isinstance(params, dict):
                            input_schema = params
                    elif isinstance(schema, dict):
                        input_schema = schema.get("parameters", {})

                tools.append({
                    "name": manifest.skill_id,
                    "description": manifest.description or "",
                    "inputSchema": input_schema,
                })
            except Exception as exc:
                logger.warning("mcp_tool_schema_failed", skill=manifest.skill_id, error=str(exc))
                # 即使 schema 获取失败，也加入工具列表（没有参数 schema）
                tools.append({
                    "name": manifest.skill_id,
                    "description": manifest.description or "",
                    "inputSchema": {},
                })
    except Exception as exc:
        logger.error("mcp_tool_list_error", error=str(exc))
        return _error_response(-32603, f"Failed to list tools: {exc}")

    return {"tools": tools}


def _error_response(code: int, message: str) -> dict[str, Any]:
    """构建 MCP 错误响应."""
    return {
        "content": [{"type": "text", "text": f"Error: {message}"}],
        "isError": True,
        "error": {"code": code, "message": message},
    }


def wrap_jsonrpc_response(result: Any, request_id: str | int | None = None) -> dict[str, Any]:
    """将结果包装为 JSON-RPC 2.0 响应."""
    return {
        "jsonrpc": "2.0",
        "result": result,
        "id": request_id,
    }
