"""MCP 桥接单元测试 (>=15 用例)"""
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# 确保可以导入 backend 模块
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, MCPTool


@pytest.fixture
def db_engine(tmp_path):
    """创建临时内存 SQLite 引擎"""
    db_path = tmp_path / "test_mcp.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """创建数据库会话"""
    Session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def mock_settings():
    """模拟配置"""
    settings = MagicMock()
    settings.m8_control_tower_api = "http://localhost:8001/api"
    settings.m5_memory_api = "http://localhost:8002/api"
    settings.m4_scene_api = "http://localhost:8003/api"
    settings.m8_inspection_api = "http://localhost:8004/api"
    return settings


@pytest.fixture
def registry(db_session, mock_settings):
    """创建 MCP 工具注册中心（不注册内置工具）"""
    from mcp_bridge import MCPToolRegistry
    reg = MCPToolRegistry.__new__(MCPToolRegistry)
    reg.settings = mock_settings
    reg._tools = {}
    reg._db = db_session
    reg._lock = __import__("threading").RLock()
    return reg


def sample_handler(name: str, value: int = 0):
    """示例工具处理函数"""
    return {"name": name, "value": value}


class TestRegisterTool:
    """注册工具测试"""

    def test_register_new_tool(self, registry):
        """注册新工具"""
        result = registry.register_tool(
            name="test_tool",
            handler=sample_handler,
            description="A test tool",
            category="test"
        )
        assert result is True

    def test_register_duplicate_tool(self, registry):
        """重复注册返回 False"""
        registry.register_tool(name="dup_tool", handler=sample_handler)
        result = registry.register_tool(name="dup_tool", handler=sample_handler)
        assert result is False

    def test_register_tool_persists(self, registry, db_session):
        """注册后数据库中有记录"""
        registry.register_tool(name="persist_tool", handler=sample_handler)
        tool = db_session.query(MCPTool).filter(MCPTool.name == "persist_tool").first()
        assert tool is not None
        assert tool.enabled is True

    def test_register_multiple_tools(self, registry):
        """注册多个工具"""
        for i in range(5):
            registry.register_tool(name=f"tool_{i}", handler=sample_handler)
        assert len(registry._tools) == 5


class TestUnregisterTool:
    """注销工具测试"""

    def test_unregister_existing_tool(self, registry):
        """注销存在的工具"""
        registry.register_tool(name="to_remove", handler=sample_handler)
        result = registry.unregister_tool("to_remove")
        assert result is True
        assert "to_remove" not in registry._tools

    def test_unregister_nonexistent_tool(self, registry):
        """注销不存在的工具返回 False"""
        result = registry.unregister_tool("not_exists")
        assert result is False

    def test_unregister_disables_in_db(self, registry, db_session):
        """注销后数据库标记为禁用"""
        registry.register_tool(name="disable_tool", handler=sample_handler)
        registry.unregister_tool("disable_tool")
        tool = db_session.query(MCPTool).filter(MCPTool.name == "disable_tool").first()
        assert tool is not None
        assert tool.enabled is False


class TestListTools:
    """列出工具测试"""

    def test_list_all_tools(self, registry):
        """列出所有工具"""
        registry.register_tool(name="tool_a", handler=sample_handler, category="cat_a")
        registry.register_tool(name="tool_b", handler=sample_handler, category="cat_b")
        tools = registry.list_tools()
        assert len(tools) == 2

    def test_list_by_category(self, registry):
        """按分类过滤"""
        registry.register_tool(name="tool_a", handler=sample_handler, category="compute")
        registry.register_tool(name="tool_b", handler=sample_handler, category="memory")
        registry.register_tool(name="tool_c", handler=sample_handler, category="compute")
        tools = registry.list_tools(category="compute")
        assert len(tools) == 2
        assert all(t["category"] == "compute" for t in tools)

    def test_list_empty(self, registry):
        """空列表"""
        tools = registry.list_tools()
        assert tools == []

    def test_list_includes_disabled(self, registry):
        """包含禁用的工具"""
        registry.register_tool(name="enabled_tool", handler=sample_handler)
        registry.register_tool(name="disabled_tool", handler=sample_handler)
        registry.unregister_tool("disabled_tool")
        tools_enabled = registry.list_tools(enabled_only=True)
        assert len(tools_enabled) == 1
        tools_all = registry.list_tools(enabled_only=False)
        assert len(tools_all) == 2


class TestGetTool:
    """获取工具测试"""

    def test_get_existing_tool(self, registry):
        """获取存在的工具"""
        registry.register_tool(name="get_me", handler=sample_handler, description="Get test")
        tool = registry.get_tool("get_me")
        assert tool is not None
        assert tool["name"] == "get_me"
        assert tool["description"] == "Get test"

    def test_get_nonexistent_tool(self, registry):
        """获取不存在的工具"""
        tool = registry.get_tool("not_found")
        assert tool is None


class TestCallTool:
    """调用工具测试"""

    def test_call_existing_tool(self, registry):
        """调用存在的工具"""
        registry.register_tool(name="call_me", handler=sample_handler)
        response = registry.call_tool("call_me", {"name": "test", "value": 42})
        assert response.error is None
        assert response.result["name"] == "test"
        assert response.result["value"] == 42

    def test_call_nonexistent_tool(self, registry):
        """调用不存在的工具"""
        response = registry.call_tool("ghost_tool")
        assert response.error is not None
        assert response.error["code"] == -32601

    def test_call_disabled_tool(self, registry):
        """调用已禁用的工具"""
        registry.register_tool(name="disabled_call", handler=sample_handler)
        registry.unregister_tool("disabled_call")
        response = registry.call_tool("disabled_call")
        assert response.error is not None

    def test_call_with_wrong_args(self, registry):
        """调用参数错误"""
        registry.register_tool(name="strict_tool", handler=sample_handler)
        response = registry.call_tool("strict_tool", {"wrong_param": 1})
        assert response.error is not None
        assert response.error["code"] == -32602

    def test_call_no_args(self, registry):
        """调用无参数工具"""
        def no_args_handler():
            return {"ok": True}
        registry.register_tool(name="no_args", handler=no_args_handler)
        response = registry.call_tool("no_args")
        assert response.error is None
        assert response.result["ok"] is True


class TestHandleRequest:
    """MCP 协议请求处理测试"""

    def test_handle_tools_list(self, registry):
        """处理 tools/list 请求"""
        registry.register_tool(name="listed", handler=sample_handler)
        response = registry.handle_request({
            "method": "tools/list",
            "params": {},
            "id": "req-1"
        })
        assert response["result"] is not None
        assert "tools" in response["result"]

    def test_handle_tools_call(self, registry):
        """处理 tools/call 请求"""
        registry.register_tool(name="called", handler=sample_handler)
        response = registry.handle_request({
            "method": "tools/call",
            "params": {
                "name": "called",
                "arguments": {"name": "test", "value": 10}
            },
            "id": "req-2"
        })
        assert response["result"] is not None

    def test_handle_unsupported_method(self, registry):
        """不支持的方法"""
        response = registry.handle_request({
            "method": "invalid/method",
            "params": {},
            "id": "req-3"
        })
        assert response["error"] is not None
        assert "不支持" in response["error"]["message"]

    def test_handle_tools_list_with_category(self, registry):
        """tools/list 带分类过滤"""
        registry.register_tool(name="cat_a", handler=sample_handler, category="alpha")
        registry.register_tool(name="cat_b", handler=sample_handler, category="beta")
        response = registry.handle_request({
            "method": "tools/list",
            "params": {"category": "alpha"},
            "id": "req-4"
        })
        tools = response["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["category"] == "alpha"


class TestMCPResponse:
    """MCP 响应对象测试"""

    def test_to_dict_with_result(self):
        """带结果的响应转字典"""
        from mcp_bridge import MCPResponse
        resp = MCPResponse(id="123", result={"data": "ok"})
        d = resp.to_dict()
        assert d["jsonrpc"] == "2.0"
        assert d["id"] == "123"
        assert d["result"] == {"data": "ok"}
        assert "error" not in d

    def test_to_dict_with_error(self):
        """带错误的响应转字典"""
        from mcp_bridge import MCPResponse
        resp = MCPResponse(id="456", error={"code": -1, "message": "Error"})
        d = resp.to_dict()
        assert "error" in d
        assert d["error"]["code"] == -1
        assert "result" not in d
