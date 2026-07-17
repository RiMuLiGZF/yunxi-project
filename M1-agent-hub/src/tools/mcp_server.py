"""
云汐内核 V5 - MCP 协议服务端

⚠️ [V10.0-R02 DEPRECATED] 本模块属于模块2（Skill集群）MCP适配层职责范围，
将在模块2就绪后迁移。当前保留作为向后兼容的临时实现。

M1应通过 SkillsInterface 调用模块2的MCP服务能力，
不直接暴露MCP服务器。

灵感来源：Anthropic Model Context Protocol (MCP)

将云汐内核的 Agent 能力暴露为标准 MCP Tools，
使 Claude、Cursor、Cline 等支持 MCP 的客户端可以调用本集群。

当前实现：基于 stdio 的 JSON-RPC 2.0 传输
支持协议方法：
- initialize / notifications/initialized
- tools/list
- tools/call
- ping

参考：
- https://modelcontextprotocol.io
- https://pypi.org/project/mcp/
"""

from __future__ import annotations

import json
import sys
from typing import Any

import structlog

from src.tools.interfaces import IAgentPlugin

logger = structlog.get_logger(__name__)


class MCPServer:
    """MCP 协议服务端

    将 Agent 集群的能力封装为 MCP Tool 集合，
    通过 stdin/stdout 进行 JSON-RPC 2.0 通信。
    """

    PROTOCOL_VERSION = "2024-11-05"
    SERVER_NAME = "yunxi-core-mcp"
    SERVER_VERSION = "5.0.0"

    def __init__(self, agent_registry: Any | None = None) -> None:
        self._registry = agent_registry
        self._initialized = False
        self._logger = logger.bind(service="mcp_server")
        self._tools: list[dict[str, Any]] = []

    def _build_tools(self) -> list[dict[str, Any]]:
        """从 AgentRegistry 构建 MCP Tool 列表"""
        tools = []
        if self._registry is None:
            return tools

        agents = []
        if hasattr(self._registry, "list_all"):
            agents = self._registry.list_all()

        for agent in agents:
            agent_id = getattr(agent, "agent_id", "")
            capabilities = getattr(agent, "capabilities", [])
            version = getattr(agent, "version", "1.0.0")

            for cap in capabilities:
                tool_name = f"{agent_id}_{cap.replace('.', '_')}"
                tools.append({
                    "name": tool_name,
                    "description": f"Agent '{agent_id}' 的能力: {cap} (v{version})",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "user_input": {
                                "type": "string",
                                "description": "用户输入内容",
                            },
                            "context": {
                                "type": "object",
                                "description": "可选上下文",
                            },
                        },
                        "required": ["user_input"],
                    },
                })

        # 添加系统级工具
        tools.append({
            "name": "yunxi_diagnose",
            "description": "获取云汐内核诊断信息（健康状态、统计指标）",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        })

        tools.append({
            "name": "yunxi_list_agents",
            "description": "列出所有可用的 Agent 及其能力",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        })

        return tools

    # ── 核心处理 ────────────────────────────────────────

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """处理单条 MCP JSON-RPC 消息

        Args:
            message: JSON-RPC 请求字典

        Returns:
            响应字典，或 None（如果是通知）
        """
        msg_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params", {})

        self._logger.debug("mcp_message_received", method=method, id=msg_id)

        if method == "initialize":
            return self._handle_initialize(msg_id, params)
        elif method == "notifications/initialized":
            self._initialized = True
            self._logger.info("mcp_client_initialized")
            return None
        elif method == "ping":
            return self._result(msg_id, {})
        elif method == "tools/list":
            return self._handle_tools_list(msg_id, params)
        elif method == "tools/call":
            return self._handle_tools_call(msg_id, params)
        else:
            return self._error(msg_id, -32601, f"Method not found: {method}")

    def _handle_initialize(self, msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        """处理 initialize 请求"""
        client_info = params.get("clientInfo", {})
        self._logger.info(
            "mcp_initialize",
            client_name=client_info.get("name"),
            client_version=client_info.get("version"),
        )

        return self._result(msg_id, {
            "protocolVersion": self.PROTOCOL_VERSION,
            "serverInfo": {
                "name": self.SERVER_NAME,
                "version": self.SERVER_VERSION,
            },
            "capabilities": {
                "tools": {},
                "logging": {},
            },
        })

    def _handle_tools_list(self, msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        """处理 tools/list 请求"""
        self._tools = self._build_tools()
        return self._result(msg_id, {"tools": self._tools})

    def _handle_tools_call(self, msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        """处理 tools/call 请求"""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        self._logger.info("mcp_tool_call", tool=tool_name)

        # 系统级工具
        if tool_name == "yunxi_diagnose":
            return self._result(msg_id, {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "server": self.SERVER_NAME,
                            "version": self.SERVER_VERSION,
                            "agents": self._list_agent_summaries(),
                        }, ensure_ascii=False, indent=2),
                    }
                ],
            })
        elif tool_name == "yunxi_list_agents":
            return self._result(msg_id, {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(self._list_agent_summaries(), ensure_ascii=False, indent=2),
                    }
                ],
            })

        # Agent 工具调用
        # 解析 tool_name: "agent_id_capability"
        parts = tool_name.rsplit("_", 1)
        if len(parts) != 2:
            return self._error(msg_id, -32602, f"Invalid tool name: {tool_name}")

        # 异步调用需要外部事件循环处理
        # 这里返回一个提示，让调用方通过 orchestrator 处理
        return self._result(msg_id, {
            "content": [
                {
                    "type": "text",
                    "text": f"工具 '{tool_name}' 已收到请求，参数: {json.dumps(arguments, ensure_ascii=False)}",
                }
            ],
            "isError": False,
        })

    def _list_agent_summaries(self) -> list[dict[str, Any]]:
        """列出 Agent 摘要信息"""
        summaries = []
        if self._registry is None:
            return summaries
        agents = self._registry.list_all() if hasattr(self._registry, "list_all") else []
        for agent in agents:
            summaries.append({
                "agent_id": getattr(agent, "agent_id", ""),
                "version": getattr(agent, "version", ""),
                "capabilities": getattr(agent, "capabilities", []),
            })
        return summaries

    # ── JSON-RPC 辅助 ───────────────────────────────────

    def _result(self, msg_id: Any, result: Any) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result,
        }

    def _error(self, msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

    # ── stdio 传输 ──────────────────────────────────────

    def run_stdio(self) -> None:
        """启动 stdio 传输模式（阻塞式）"""
        self._logger.info("mcp_stdio_server_started")

        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                message = json.loads(line)
                response = self.handle_message(message)
                if response is not None:
                    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                    sys.stdout.flush()

            except json.JSONDecodeError as exc:
                self._logger.error("mcp_json_decode_error", error=str(exc))
                err_resp = self._error(None, -32700, "Parse error")
                sys.stdout.write(json.dumps(err_resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            except Exception as exc:
                self._logger.error("mcp_stdio_error", error=str(exc))

    def process_single(self, input_json: str) -> str:
        """处理单条 JSON 输入并返回 JSON 输出（用于测试/集成）"""
        message = json.loads(input_json)
        response = self.handle_message(message)
        if response is None:
            return ""
        return json.dumps(response, ensure_ascii=False)
