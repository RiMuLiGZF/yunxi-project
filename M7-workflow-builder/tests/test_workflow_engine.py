"""
M7 单元测试 - 工作流引擎核心逻辑

覆盖: 拓扑排序、邻接表构建、线性判断、变量解析
运行: python -m pytest tests/test_workflow_engine.py -v
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from services.engine import (
    build_adjacency_list,
    topological_sort,
    is_linear_workflow,
)


class TestBuildAdjacencyList:
    """邻接表构建测试"""

    def test_single_block(self):
        """单个积木块"""
        blocks = [{"id": "a", "name": "开始"}]
        adj, indeg = build_adjacency_list(blocks)
        assert "a" in adj
        assert adj["a"] == []
        assert indeg["a"] == 0

    def test_linear_chain(self):
        """线性链: a -> b -> c"""
        blocks = [
            {"id": "a", "next": ["b"]},
            {"id": "b", "next": ["c"]},
            {"id": "c", "next": []},
        ]
        adj, indeg = build_adjacency_list(blocks)
        assert adj["a"] == ["b"]
        assert adj["b"] == ["c"]
        assert adj["c"] == []
        assert indeg["a"] == 0
        assert indeg["b"] == 1
        assert indeg["c"] == 1

    def test_fork_dag(self):
        """分叉 DAG: a -> b, a -> c, b -> d, c -> d"""
        blocks = [
            {"id": "a", "next": ["b", "c"]},
            {"id": "b", "next": ["d"]},
            {"id": "c", "next": ["d"]},
            {"id": "d", "next": []},
        ]
        adj, indeg = build_adjacency_list(blocks)
        assert set(adj["a"]) == {"b", "c"}
        assert adj["b"] == ["d"]
        assert adj["c"] == ["d"]
        assert adj["d"] == []
        assert indeg["a"] == 0
        assert indeg["b"] == 1
        assert indeg["c"] == 1
        assert indeg["d"] == 2

    def test_empty_blocks(self):
        """空积木列表"""
        adj, indeg = build_adjacency_list([])
        assert adj == {}
        assert indeg == {}

    def test_no_next_field(self):
        """积木没有 next 字段"""
        blocks = [{"id": "a", "name": "测试"}]
        adj, indeg = build_adjacency_list(blocks)
        assert adj["a"] == []
        assert indeg["a"] == 0


class TestTopologicalSort:
    """拓扑排序测试"""

    def test_linear_chain(self):
        """线性链排序"""
        blocks = [
            {"id": "a", "next": ["b"]},
            {"id": "b", "next": ["c"]},
            {"id": "c", "next": []},
        ]
        order = topological_sort(blocks)
        assert len(order) == 3
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_fork_dag(self):
        """分叉 DAG 排序"""
        blocks = [
            {"id": "a", "next": ["b", "c"]},
            {"id": "b", "next": ["d"]},
            {"id": "c", "next": ["d"]},
            {"id": "d", "next": []},
        ]
        order = topological_sort(blocks)
        assert len(order) == 4
        # a 必须在最前，d 必须在最后
        assert order[0] == "a"
        assert order[-1] == "d"
        # b 和 c 都必须在 d 之前
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_single_block(self):
        """单个积木"""
        blocks = [{"id": "a"}]
        order = topological_sort(blocks)
        assert order == ["a"]

    def test_empty_blocks(self):
        """空列表"""
        order = topological_sort([])
        assert order == []

    def test_start_block_specified(self):
        """指定起始积木"""
        blocks = [
            {"id": "a", "next": ["b"]},
            {"id": "b", "next": ["c"]},
            {"id": "c", "next": []},
        ]
        order = topological_sort(blocks, start_block="b")
        # 从 b 开始，应包含 b 和 c
        assert "b" in order
        assert "c" in order
        assert "a" not in order
        assert order.index("b") < order.index("c")


class TestIsLinearWorkflow:
    """线性工作流判断测试"""

    def test_linear_chain(self):
        """线性链应为线性"""
        blocks = [
            {"id": "a", "next": ["b"]},
            {"id": "b", "next": ["c"]},
            {"id": "c", "next": []},
        ]
        assert is_linear_workflow(blocks) is True

    def test_single_block(self):
        """单个积木应为线性"""
        blocks = [{"id": "a"}]
        assert is_linear_workflow(blocks) is True

    def test_empty(self):
        """空列表应为线性"""
        assert is_linear_workflow([]) is True

    def test_fork_not_linear(self):
        """分叉 DAG 不应为线性"""
        blocks = [
            {"id": "a", "next": ["b", "c"]},
            {"id": "b", "next": ["d"]},
            {"id": "c", "next": ["d"]},
            {"id": "d", "next": []},
        ]
        assert is_linear_workflow(blocks) is False

    def test_multiple_start_not_linear(self):
        """多个起点不应为线性"""
        blocks = [
            {"id": "a", "next": []},
            {"id": "b", "next": []},
        ]
        assert is_linear_workflow(blocks) is False


class TestResolveVariables:
    """变量解析测试"""

    def setup_method(self):
        """导入 WorkflowEngine"""
        from services.engine import WorkflowEngine
        self.engine = WorkflowEngine()

    def test_default_values(self):
        """默认值应被解析"""
        variables_config = [
            {"name": "greeting", "default": "hello"},
            {"name": "count", "default": 10},
        ]
        result = self.engine._resolve_variables(variables_config, {}, {})
        assert result["greeting"] == "hello"
        assert result["count"] == 10

    def test_input_overrides_default(self):
        """输入值应覆盖默认值"""
        variables_config = [
            {"name": "greeting", "default": "hello"},
        ]
        result = self.engine._resolve_variables(
            variables_config, {}, {"greeting": "hi"}
        )
        assert result["greeting"] == "hi"

    def test_runtime_overrides_input(self):
        """运行时变量应覆盖输入"""
        variables_config = [
            {"name": "greeting", "default": "hello"},
        ]
        result = self.engine._resolve_variables(
            variables_config, {"greeting": "runtime"}, {"greeting": "input"}
        )
        assert result["greeting"] == "runtime"

    def test_empty_variables(self):
        """空变量配置应返回空字典"""
        result = self.engine._resolve_variables([], {}, {})
        assert result == {}

    def test_variable_type_preserved(self):
        """变量类型应保持不变"""
        variables_config = [
            {"name": "num", "default": 42},
            {"name": "flag", "default": True},
            {"name": "items", "default": [1, 2, 3]},
        ]
        result = self.engine._resolve_variables(variables_config, {}, {})
        assert isinstance(result["num"], int)
        assert isinstance(result["flag"], bool)
        assert isinstance(result["items"], list)
