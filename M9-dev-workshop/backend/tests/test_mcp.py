"""
M9 开发者工坊 - MCP 桥接测试
测试内容：
1. MCP 工具注册
2. 工具列表获取
3. 工具调用
4. 工具状态
5. 错误处理

使用方式：
    cd M9-dev-workshop/backend
    python -m pytest tests/test_mcp.py -v
    或
    python tests/test_mcp.py
"""

import sys
from pathlib import Path

# 添加项目路径
backend_dir = Path(__file__).parent.parent.resolve()
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest
from unittest.mock import patch, MagicMock

from mcp_bridge import MCPRegistry, MCPTool, MCPToolResponse, get_mcp_registry


# ==================== Fixtures ====================

@pytest.fixture
def registry():
    """创建 MCPRegistry 实例"""
    return MCPRegistry()


@pytest.fixture
def sample_tool():
    """创建示例工具"""
    return MCPTool(
        name="test_tool",
        description="测试工具",
        category="test",
        input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
    )


# ==================== MCPTool 测试 ====================

class TestMCPTool:
    """MCPTool 类测试"""

    def test_tool_creation(self):
        """测试工具创建"""
        tool = MCPTool(
            name="test",
            description="测试",
            category="general",
        )
        assert tool.name == "test"
        assert tool.description == "测试"
        assert tool.category == "general"

    def test_tool_to_dict(self):
        """测试工具序列化"""
        tool = MCPTool(
            name="test",
            description="测试",
            category="general",
            version="1.0.0",
        )
        d = tool.to_dict()
        assert d["name"] == "test"
        assert d["description"] == "测试"
        assert d["category"] == "general"
        assert d["version"] == "1.0.0"

    def test_tool_with_input_schema(self):
        """测试带输入模式的工具"""
        schema = {
            "type": "object",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["x", "y"],
        }
        tool = MCPTool(
            name="add",
            description="加法",
            category="math",
            input_schema=schema,
        )
        assert tool.input_schema == schema


# ==================== MCPToolResponse 测试 ====================

class TestMCPToolResponse:
    """MCPToolResponse 类测试"""

    def test_success_response(self):
        """测试成功响应"""
        resp = MCPToolResponse(success=True, result={"value": 42})
        assert resp.success is True
        assert resp.result == {"value": 42}
        assert resp.error is None

    def test_error_response(self):
        """测试错误响应"""
        resp = MCPToolResponse(success=False, error={"code": -1, "message": "失败"})
        assert resp.success is False
        assert resp.error["code"] == -1
        assert resp.result is None

    def test_response_to_dict(self):
        """测试响应序列化"""
        resp = MCPToolResponse(success=True, result={"ok": True})
        d = resp.to_dict()
        assert d["success"] is True
        assert d["result"] == {"ok": True}


# ==================== MCPRegistry 注册测试 ====================

class TestRegistryRegister:
    """注册功能测试"""

    def test_register_tool(self, registry, sample_tool):
        """测试注册工具"""
        result = registry.register_tool(sample_tool)
        assert result is True
        assert sample_tool.name in registry._tools

    def test_register_duplicate_tool(self, registry, sample_tool):
        """测试注册重复工具"""
        registry.register_tool(sample_tool)
        result = registry.register_tool(sample_tool)
        assert result is False  # 重复注册返回 False

    def test_unregister_tool(self, registry, sample_tool):
        """测试注销工具"""
        registry.register_tool(sample_tool)
        result = registry.unregister_tool("test_tool")
        assert result is True
        assert "test_tool" not in registry._tools

    def test_unregister_nonexistent_tool(self, registry):
        """测试注销不存在的工具"""
        result = registry.unregister_tool("nonexistent")
        assert result is False

    def test_list_tools_empty(self, registry):
        """测试空工具列表"""
        tools = registry.list_tools()
        assert isinstance(tools, list)
        assert len(tools) == 0

    def test_list_tools(self, registry, sample_tool):
        """测试工具列表"""
        registry.register_tool(sample_tool)
        tools = registry.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "test_tool"

    def test_list_tools_by_category(self, registry):
        """测试按分类列出工具"""
        tool1 = MCPTool(name="t1", description="t1", category="cat1")
        tool2 = MCPTool(name="t2", description="t2", category="cat2")
        tool3 = MCPTool(name="t3", description="t3", category="cat1")
        registry.register_tool(tool1)
        registry.register_tool(tool2)
        registry.register_tool(tool3)

        cat1_tools = registry.list_tools(category="cat1")
        assert len(cat1_tools) == 2

    def test_get_tool(self, registry, sample_tool):
        """测试获取工具"""
        registry.register_tool(sample_tool)
        tool = registry.get_tool("test_tool")
        assert tool is not None
        assert tool.name == "test_tool"

    def test_get_nonexistent_tool(self, registry):
        """测试获取不存在的工具"""
        tool = registry.get_tool("nonexistent")
        assert tool is None

    def test_get_categories(self, registry):
        """测试获取分类列表"""
        registry.register_tool(MCPTool(name="t1", description="t1", category="cat1"))
        registry.register_tool(MCPTool(name="t2", description="t2", category="cat2"))
        cats = registry.get_categories()
        assert "cat1" in cats
        assert "cat2" in cats


# ==================== MCPRegistry 调用测试 ====================

class TestRegistryCall:
    """工具调用功能测试"""

    def test_call_nonexistent_tool(self, registry):
        """测试调用不存在的工具"""
        resp = registry.call_tool("nonexistent", {})
        assert resp.success is False
        assert "不存在" in resp.error["message"]

    def test_call_tool_with_handler(self, registry):
        """测试调用带处理函数的工具"""
        def add_handler(args):
            return {"result": args.get("a", 0) + args.get("b", 0)}

        tool = MCPTool(
            name="add",
            description="加法",
            category="math",
            handler=add_handler,
        )
        registry.register_tool(tool)
        resp = registry.call_tool("add", {"a": 1, "b": 2})
        assert resp.success is True
        assert resp.result == {"result": 3}

    def test_call_tool_with_exception(self, registry):
        """测试调用抛出异常的工具"""
        def bad_handler(args):
            raise ValueError("测试错误")

        tool = MCPTool(
            name="bad_tool",
            description="坏工具",
            category="test",
            handler=bad_handler,
        )
        registry.register_tool(tool)
        resp = registry.call_tool("bad_tool", {})
        assert resp.success is False
        assert "测试错误" in resp.error["message"]


# ==================== 单例模式测试 ====================

class TestSingleton:
    """单例模式测试"""

    def test_same_instance(self):
        """测试单例模式返回同一实例"""
        r1 = get_mcp_registry()
        r2 = get_mcp_registry()
        assert r1 is r2


# ==================== 直接运行入口 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("M9 MCP 桥接测试")
    print("=" * 60)

    # 使用 pytest 运行
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    sys.exit(exit_code)
