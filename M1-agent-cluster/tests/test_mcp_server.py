"""
测试：MCPServer MCP 协议服务端
"""

import pytest
import sys
import json

sys.path.insert(0, "/workspace/agent_cluster")

from mcp_server import MCPServer
from agent_registry import AgentRegistry
from interfaces import AgentTask, AgentResult, IAgentPlugin


class DummyMCPAgent(IAgentPlugin):
    agent_id: str = "agent.mcp_dummy"
    version: str = "1.0.0"
    capabilities: list[str] = ["note.create", "note.search"]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, agent_id=self.agent_id, status="success")


@pytest.fixture
def mcp_server():
    registry = AgentRegistry()
    registry.register_sync(DummyMCPAgent())
    return MCPServer(registry)


def test_initialize(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "test", "version": "1.0"}},
    }
    resp = mcp_server.handle_message(req)
    assert resp is not None
    assert resp["id"] == 1
    assert "protocolVersion" in resp["result"]
    assert resp["result"]["serverInfo"]["name"] == "yunxi-core-mcp"


def test_notifications_initialized(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }
    resp = mcp_server.handle_message(req)
    assert resp is None


def test_ping(mcp_server):
    req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    resp = mcp_server.handle_message(req)
    assert resp["id"] == 2
    assert "result" in resp


def test_tools_list(mcp_server):
    req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
    resp = mcp_server.handle_message(req)
    assert resp["id"] == 3
    tools = resp["result"]["tools"]
    assert len(tools) > 0
    # 应该有 Agent 工具 + 系统工具
    tool_names = [t["name"] for t in tools]
    assert "agent.mcp_dummy_note_create" in tool_names
    assert "agent.mcp_dummy_note_search" in tool_names
    assert "yunxi_diagnose" in tool_names
    assert "yunxi_list_agents" in tool_names


def test_tools_call_diagnose(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "yunxi_diagnose", "arguments": {}},
    }
    resp = mcp_server.handle_message(req)
    assert resp["id"] == 4
    content = resp["result"]["content"][0]["text"]
    data = json.loads(content)
    assert data["server"] == "yunxi-core-mcp"


def test_tools_call_list_agents(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "yunxi_list_agents", "arguments": {}},
    }
    resp = mcp_server.handle_message(req)
    assert resp["id"] == 5
    content = resp["result"]["content"][0]["text"]
    data = json.loads(content)
    assert len(data) > 0
    assert data[0]["agent_id"] == "agent.mcp_dummy"


def test_tools_call_agent_tool(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {"name": "agent.mcp_dummy_note_create", "arguments": {"user_input": "test"}},
    }
    resp = mcp_server.handle_message(req)
    assert resp["id"] == 6
    assert "content" in resp["result"]


def test_unknown_method(mcp_server):
    req = {"jsonrpc": "2.0", "id": 7, "method": "unknown/method"}
    resp = mcp_server.handle_message(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_process_single(mcp_server):
    req_json = json.dumps({
        "jsonrpc": "2.0",
        "id": 8,
        "method": "ping",
    })
    resp_json = mcp_server.process_single(req_json)
    resp = json.loads(resp_json)
    assert resp["id"] == 8
