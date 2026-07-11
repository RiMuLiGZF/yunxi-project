"""Tests for MCP Transport layer."""

import pytest

from skill_cluster.mcp_transport import (
    handle_mcp_tool_call,
    handle_mcp_tool_list,
    wrap_jsonrpc_response,
)


def test_wrap_jsonrpc_response():
    resp = wrap_jsonrpc_response({"content": [{"type": "text", "text": "ok"}], "isError": False}, "req-1")
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == "req-1"
    assert resp["result"]["isError"] is False


def test_wrap_jsonrpc_response_no_id():
    resp = wrap_jsonrpc_response({"content": []})
    assert resp["id"] is None


def test_handle_mcp_tool_list_no_registry():
    result = handle_mcp_tool_list(registry=None)
    assert result["isError"] is True
    assert "error" in result


def test_handle_mcp_tool_list_with_registry():
    class FakeRegistry:
        def all_manifests(self):
            class M:
                skill_id = "s1"; description = "Skill 1"; actions = ["run"]
            return [M()]
        def get_schema(self, sid, action):
            return None

    result = handle_mcp_tool_list(registry=FakeRegistry())
    assert "tools" in result
    assert len(result["tools"]) == 1
    assert result["tools"][0]["name"] == "s1"


@pytest.mark.asyncio
async def test_handle_mcp_tool_call_no_router():
    result = await handle_mcp_tool_call({"name": "s1:run"})
    assert result["isError"] is True


@pytest.mark.asyncio
async def test_handle_mcp_tool_call_with_colon():
    """测试 skill_id:action 格式解析."""

    class FakeRouter:
        async def invoke(self, req, agent_id):
            from skill_cluster.interfaces import SkillInvokeResult
            return SkillInvokeResult(
                skill_id=req.skill_id, action=req.action,
                status="success", data={"result": 42},
                latency_ms=10.0, trace_id=req.trace_id,
            )

    result = await handle_mcp_tool_call({"name": "skill.a:run", "arguments": {"x": 1}}, router=FakeRouter())
    assert result["isError"] is False
    assert result["content"][0]["type"] == "text"


@pytest.mark.asyncio
async def test_handle_mcp_tool_call_simple_name():
    """测试纯 skill_id 格式（无action）."""

    class FakeRouter:
        async def invoke(self, req, agent_id):
            from skill_cluster.interfaces import SkillInvokeResult
            return SkillInvokeResult(
                skill_id=req.skill_id, action=req.action,
                status="success", data={"result": "ok"},
                latency_ms=5.0, trace_id=req.trace_id,
            )

    result = await handle_mcp_tool_call({"name": "skill.b", "arguments": {}}, router=FakeRouter())
    assert result["isError"] is False
