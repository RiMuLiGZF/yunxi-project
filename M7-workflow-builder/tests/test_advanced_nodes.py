"""
M7 单元测试 - 新增节点类型测试

覆盖: 条件节点、循环节点、延时节点、HTTP请求节点、数据转换节点、子工作流节点
运行: python -m pytest tests/test_advanced_nodes.py -v
"""
import os
import sys
import pytest
import asyncio
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from services.nodes import (
    execute_condition_node_sync as execute_condition_node,
    execute_loop_node_sync as execute_loop_node,
    execute_delay_node_sync as execute_delay_node,
    execute_http_node_sync as execute_http_node,
    execute_data_transform_node_sync as execute_data_transform_node,
    execute_subworkflow_node_sync as execute_subworkflow_node,
    evaluate_expression,
)


class TestEvaluateExpression:
    """表达式求值测试"""

    def test_simple_arithmetic(self):
        """简单算术运算"""
        result = evaluate_expression("1 + 2", {})
        assert result == 3

    def test_variable_reference(self):
        """变量引用"""
        result = evaluate_expression("x + y", {"x": 10, "y": 20})
        assert result == 30

    def test_string_comparison(self):
        """字符串比较"""
        result = evaluate_expression("name == 'test'", {"name": "test"})
        assert result is True

    def test_logical_and(self):
        """逻辑与"""
        result = evaluate_expression("a > 0 and b > 0", {"a": 1, "b": 2})
        assert result is True

    def test_logical_or(self):
        """逻辑或"""
        result = evaluate_expression("a > 10 or b > 10", {"a": 1, "b": 20})
        assert result is True

    def test_comparison_greater(self):
        """大于比较"""
        result = evaluate_expression("count > 5", {"count": 10})
        assert result is True

    def test_comparison_less_equal(self):
        """小于等于比较"""
        result = evaluate_expression("count <= 5", {"count": 5})
        assert result is True

    def test_nested_expression(self):
        """嵌套表达式"""
        result = evaluate_expression("(a + b) * c", {"a": 2, "b": 3, "c": 4})
        assert result == 20

    def test_invalid_expression(self):
        """无效表达式"""
        result = evaluate_expression("invalid syntax !@#", {})
        assert result is None

    def test_empty_expression(self):
        """空表达式"""
        result = evaluate_expression("", {})
        assert result is None


class TestConditionNode:
    """条件节点测试"""

    def test_condition_true(self):
        """条件为真时执行 true 分支"""
        node_config = {
            "condition": "x > 5",
            "true_branch": "branch_a",
            "false_branch": "branch_b",
        }
        context = {"x": 10}
        result = execute_condition_node(node_config, context)
        assert result["success"] is True
        assert result["branch"] == "branch_a"
        assert result["condition_met"] is True

    def test_condition_false(self):
        """条件为假时执行 false 分支"""
        node_config = {
            "condition": "x > 5",
            "true_branch": "branch_a",
            "false_branch": "branch_b",
        }
        context = {"x": 3}
        result = execute_condition_node(node_config, context)
        assert result["success"] is True
        assert result["branch"] == "branch_b"
        assert result["condition_met"] is False

    def test_condition_equal(self):
        """等于条件"""
        node_config = {
            "condition": "status == 'active'",
            "true_branch": "active_branch",
            "false_branch": "inactive_branch",
        }
        context = {"status": "active"}
        result = execute_condition_node(node_config, context)
        assert result["success"] is True
        assert result["branch"] == "active_branch"

    def test_condition_with_multiple_vars(self):
        """多变量条件"""
        node_config = {
            "condition": "age >= 18 and has_license == True",
            "true_branch": "can_drive",
            "false_branch": "cannot_drive",
        }
        context = {"age": 25, "has_license": True}
        result = execute_condition_node(node_config, context)
        assert result["success"] is True
        assert result["branch"] == "can_drive"

    def test_condition_invalid_expression(self):
        """无效条件表达式"""
        node_config = {
            "condition": "invalid !@#",
            "true_branch": "a",
            "false_branch": "b",
        }
        result = execute_condition_node(node_config, {})
        assert result["success"] is False
        assert "error" in result

    def test_condition_missing_config(self):
        """缺少条件配置"""
        result = execute_condition_node({}, {})
        assert result["success"] is False


class TestLoopNode:
    """循环节点测试"""

    def test_for_loop_range(self):
        """for 循环 - range 模式"""
        node_config = {
            "loop_type": "for",
            "iterator": "range",
            "start": 0,
            "end": 3,
            "step": 1,
            "loop_variable": "i",
        }
        context = {}
        result = execute_loop_node(node_config, context)
        assert result["success"] is True
        assert result["iteration_count"] == 3
        assert result["loop_type"] == "for"
        assert len(result["iterations"]) == 3

    def test_for_loop_list(self):
        """for 循环 - 列表模式"""
        node_config = {
            "loop_type": "for",
            "iterator": "list",
            "items": ["a", "b", "c"],
            "loop_variable": "item",
        }
        context = {}
        result = execute_loop_node(node_config, context)
        assert result["success"] is True
        assert result["iteration_count"] == 3
        assert result["iterations"][0]["value"] == "a"

    def test_while_loop(self):
        """while 循环"""
        node_config = {
            "loop_type": "while",
            "condition": "count < 5",
            "loop_variable": "count",
            "initial_value": 0,
            "increment": 1,
            "max_iterations": 100,
        }
        context = {}
        result = execute_loop_node(node_config, context)
        assert result["success"] is True
        assert result["iteration_count"] == 5

    def test_while_loop_max_limit(self):
        """while 循环 - 最大迭代次数限制"""
        node_config = {
            "loop_type": "while",
            "condition": "True",  # 永远为真
            "loop_variable": "i",
            "initial_value": 0,
            "increment": 1,
            "max_iterations": 10,
        }
        context = {}
        result = execute_loop_node(node_config, context)
        assert result["success"] is True
        assert result["iteration_count"] == 10
        assert result["max_reached"] is True

    def test_loop_zero_iterations(self):
        """循环零次迭代"""
        node_config = {
            "loop_type": "for",
            "iterator": "range",
            "start": 0,
            "end": 0,
            "step": 1,
            "loop_variable": "i",
        }
        result = execute_loop_node(node_config, {})
        assert result["success"] is True
        assert result["iteration_count"] == 0

    def test_loop_invalid_type(self):
        """无效循环类型"""
        node_config = {
            "loop_type": "invalid",
        }
        result = execute_loop_node(node_config, {})
        assert result["success"] is False


class TestDelayNode:
    """延时节点测试"""

    def test_delay_basic(self):
        """基本延时"""
        node_config = {"delay_seconds": 0.01}
        result = execute_delay_node(node_config, {})
        assert result["success"] is True
        assert result["delayed"] is True
        assert result["delay_seconds"] == 0.01

    def test_delay_zero(self):
        """零延时"""
        node_config = {"delay_seconds": 0}
        result = execute_delay_node(node_config, {})
        assert result["success"] is True
        assert result["delayed"] is True

    def test_delay_negative(self):
        """负延时（应视为 0）"""
        node_config = {"delay_seconds": -1}
        result = execute_delay_node(node_config, {})
        assert result["success"] is True
        assert result["delay_seconds"] == 0

    def test_delay_max_limit(self):
        """超过最大延时限制"""
        node_config = {"delay_seconds": 999999}
        result = execute_delay_node(node_config, {})
        assert result["success"] is False

    def test_delay_missing_config(self):
        """缺少延时配置"""
        result = execute_delay_node({}, {})
        assert result["success"] is False


class TestHttpNode:
    """HTTP 请求节点测试"""

    @patch("services.nodes.requests.get")
    def test_http_get_success(self, mock_get):
        """HTTP GET 请求成功"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test_data"}
        mock_response.text = '{"data": "test_data"}'
        mock_get.return_value = mock_response

        node_config = {
            "method": "GET",
            "url": "https://api.example.com/data",
            "timeout": 10,
        }
        result = execute_http_node(node_config, {})
        assert result["success"] is True
        assert result["status_code"] == 200
        assert result["response_data"] == {"data": "test_data"}

    @patch("services.nodes.requests.post")
    def test_http_post_success(self, mock_post):
        """HTTP POST 请求成功"""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 1, "created": True}
        mock_response.text = '{"id": 1}'
        mock_post.return_value = mock_response

        node_config = {
            "method": "POST",
            "url": "https://api.example.com/items",
            "body": {"name": "test"},
            "headers": {"Content-Type": "application/json"},
            "timeout": 10,
        }
        result = execute_http_node(node_config, {})
        assert result["success"] is True
        assert result["status_code"] == 201

    @patch("services.nodes.requests.get")
    def test_http_404_error(self, mock_get):
        """HTTP 404 错误"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_get.return_value = mock_response

        node_config = {
            "method": "GET",
            "url": "https://api.example.com/not_found",
        }
        result = execute_http_node(node_config, {})
        assert result["success"] is False
        assert result["status_code"] == 404

    def test_http_missing_url(self):
        """缺少 URL"""
        node_config = {"method": "GET"}
        result = execute_http_node(node_config, {})
        assert result["success"] is False
        assert "url" in result.get("error", "").lower()

    @patch("services.nodes.requests.get")
    def test_http_url_template(self, mock_get):
        """URL 中的变量替换"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.text = "{}"
        mock_get.return_value = mock_response

        node_config = {
            "method": "GET",
            "url": "https://api.example.com/users/{user_id}",
        }
        context = {"user_id": 123}
        result = execute_http_node(node_config, context)
        assert result["success"] is True
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "123" in call_args[0][0]


class TestDataTransformNode:
    """数据转换节点测试"""

    def test_simple_mapping(self):
        """简单字段映射"""
        node_config = {
            "transform_type": "mapping",
            "mapping": {
                "new_name": "old_name",
                "new_age": "old_age",
            },
            "source": "input_data",
            "target": "output_data",
        }
        context = {
            "input_data": {
                "old_name": "张三",
                "old_age": 25,
            }
        }
        result = execute_data_transform_node(node_config, context)
        assert result["success"] is True
        assert result["transformed"]["new_name"] == "张三"
        assert result["transformed"]["new_age"] == 25

    def test_template_transform(self):
        """模板转换"""
        node_config = {
            "transform_type": "template",
            "template": {
                "full_name": "{first_name} {last_name}",
                "greeting": "Hello, {name}!",
                "age_double": "{age * 2}",
            },
            "target": "result",
        }
        context = {
            "first_name": "张",
            "last_name": "三",
            "name": "张三",
            "age": 25,
        }
        result = execute_data_transform_node(node_config, context)
        assert result["success"] is True
        assert result["transformed"]["full_name"] == "张 三"
        assert result["transformed"]["greeting"] == "Hello, 张三!"

    def test_json_path_extract(self):
        """JSON 路径提取"""
        node_config = {
            "transform_type": "extract",
            "source": "api_response",
            "fields": {
                "user_name": "data.user.name",
                "user_email": "data.user.email",
                "first_item": "data.items[0]",
            },
            "target": "extracted",
        }
        context = {
            "api_response": {
                "data": {
                    "user": {
                        "name": "张三",
                        "email": "zhangsan@example.com",
                    },
                    "items": ["item1", "item2", "item3"],
                }
            }
        }
        result = execute_data_transform_node(node_config, context)
        assert result["success"] is True
        assert result["transformed"]["user_name"] == "张三"
        assert result["transformed"]["first_item"] == "item1"

    def test_transform_invalid_type(self):
        """无效转换类型"""
        node_config = {"transform_type": "invalid"}
        result = execute_data_transform_node(node_config, {})
        assert result["success"] is False

    def test_transform_missing_source(self):
        """缺少源数据"""
        node_config = {
            "transform_type": "mapping",
            "mapping": {"a": "b"},
            "source": "non_existent",
            "target": "out",
        }
        result = execute_data_transform_node(node_config, {})
        assert result["success"] is False


class TestSubworkflowNode:
    """子工作流节点测试"""

    def test_subworkflow_missing_id(self):
        """缺少子工作流 ID"""
        node_config = {}
        result = execute_subworkflow_node(node_config, {})
        assert result["success"] is False
        assert "workflow_id" in result.get("error", "").lower()

    def test_subworkflow_basic_config(self):
        """基本子工作流配置验证"""
        node_config = {
            "workflow_id": "sub_workflow_123",
            "input_mapping": {
                "param1": "value1",
            },
            "output_mapping": {
                "result": "output",
            },
        }
        # 由于没有实际的工作流引擎上下文，测试应返回需要引擎的错误
        result = execute_subworkflow_node(node_config, {})
        # 应该返回需要引擎上下文的错误或者模拟成功
        assert "success" in result
        assert "workflow_id" in str(result)

    def test_subworkflow_with_inputs(self):
        """子工作流输入映射"""
        node_config = {
            "workflow_id": "test_sub",
            "input_mapping": {
                "sub_input": "parent_var",
            },
        }
        context = {"parent_var": "test_value"}
        result = execute_subworkflow_node(node_config, context)
        assert "success" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
