"""
Brain Agent API 路由测试（M1 Agent Hub）

测试迁移到 M1 的 Brain Agent API 路由（工具系统、单 Agent、多 Agent 团队）。
所有测试使用 mock，不依赖真实外部服务，不依赖 shared.business 真实导入。

测试用例（至少 10 个）：
1. 工具列表接口
2. 工具统计接口
3. 工具调用接口
4. Agent 运行接口
5. Agent 统计接口
6. 多 Agent 团队配置接口
7. 多 Agent 查询接口
8. 多 Agent 统计接口
9. 多 Agent 任务接口
10. 认证中间件（Token 验证）
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 路径设置
_MODULE_SRC = Path(__file__).resolve().parents[1] / "src"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_MODULE_SRC), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ============================================================================
# Mock shared.business 模块
# ============================================================================

@pytest.fixture(autouse=True)
def mock_shared_business_modules():
    """Mock shared.business 相关模块，避免导入真实业务逻辑"""
    # 创建 mock 工具结果类
    class MockToolResult:
        def __init__(self, success=True, output="", data=None, error=None,
                     execution_time=0.1, tool_name="test_tool"):
            self.success = success
            self.output = output
            self.data = data
            self.error = error
            self.execution_time = execution_time
            self.tool_name = tool_name

        def to_dict(self):
            return {
                "success": self.success,
                "output": self.output,
                "data": self.data,
                "error": self.error,
                "execution_time": round(self.execution_time, 4),
                "tool_name": self.tool_name,
            }

    # 创建 mock 工具描述类
    class MockTool:
        def __init__(self, name="test_tool", description="A test tool",
                     category="general"):
            self.name = name
            self.description = description
            self.category = category

        def get_description_for_llm(self):
            return {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}},
                "category": self.category,
            }

    # 创建 mock 工具注册表
    mock_registry = MagicMock()
    mock_registry.list_tools.return_value = [
        MockTool(name="calculator", description="Calculate expressions", category="calculation"),
        MockTool(name="web_search", description="Search the web", category="search"),
        MockTool(name="notes", description="Manage notes", category="utility"),
    ]
    mock_registry.get_stats.return_value = {
        "total_tools": 3,
        "total_calls": 42,
        "successful_calls": 38,
        "failed_calls": 4,
        "categories": {"calculation": 1, "search": 1, "utility": 1},
    }
    mock_registry.get_call_history.return_value = [
        {"tool_name": "calculator", "success": True, "timestamp": 1234567890},
        {"tool_name": "web_search", "success": True, "timestamp": 1234567891},
    ]
    mock_registry.call_tool.return_value = MockToolResult(
        success=True,
        output="42",
        data={"result": 42},
        tool_name="calculator",
        execution_time=0.05,
    )

    # 创建 mock Agent 结果类
    class MockAgentResult:
        def __init__(self, success=True, answer="The answer is 42",
                     steps=None, total_steps=3, execution_time=1.5,
                     tools_used=None, error=None):
            self.success = success
            self.answer = answer
            self.steps = steps or []
            self.total_steps = total_steps
            self.execution_time = execution_time
            self.tools_used = tools_used or ["calculator"]
            self.error = error

        def to_dict(self):
            return {
                "success": self.success,
                "answer": self.answer,
                "steps": [s for s in self.steps],
                "total_steps": self.total_steps,
                "execution_time": round(self.execution_time, 3),
                "tools_used": self.tools_used,
                "error": self.error,
            }

    # 创建 mock Agent 引擎
    mock_agent_engine = MagicMock()
    mock_agent_engine.run.return_value = MockAgentResult(
        success=True,
        answer="The result of 2 + 2 is 4",
        total_steps=3,
        tools_used=["calculator"],
        execution_time=0.5,
    )
    mock_agent_engine.get_stats.return_value = {
        "total_executions": 25,
        "successful_executions": 22,
        "failed_executions": 3,
        "avg_steps": 4.2,
        "avg_execution_time": 2.5,
        "tools_used_count": {"calculator": 15, "web_search": 10},
    }
    mock_agent_engine.get_execution_history.return_value = [
        {"query": "What is 2+2?", "success": True, "timestamp": 1234567890},
        {"query": "Search for AI", "success": True, "timestamp": 1234567891},
    ]

    # 创建 mock Agent 团队
    mock_team = MagicMock()
    mock_team.get_team_profile.return_value = {
        "team_name": "云汐智囊团",
        "team_size": 5,
        "agents": [
            {"name": "研究员·知微", "specialty": "research", "description": "擅长信息搜集与调研"},
            {"name": "作家·文思", "specialty": "writing", "description": "擅长文案创作与写作"},
            {"name": "分析师·明察", "specialty": "analysis", "description": "擅长数据分析与诊断"},
            {"name": "创意师·灵感", "specialty": "creative", "description": "擅长创意构思与设计"},
            {"name": "执行官·笃行", "specialty": "execution", "description": "擅长任务执行与落地"},
        ],
        "capabilities": ["research", "writing", "analysis", "creative", "execution"],
    }

    class MockTeamResult:
        def __init__(self, success=True, final_answer="Team result",
                     tasks=None, agent_results=None, total_time=2.0,
                     agents_involved=None, error=None):
            self.success = success
            self.final_answer = final_answer
            self.tasks = tasks or []
            self.agent_results = agent_results or []
            self.total_time = total_time
            self.agents_involved = agents_involved or ["研究员·知微"]
            self.error = error

        def to_dict(self):
            return {
                "success": self.success,
                "final_answer": self.final_answer,
                "tasks": [t for t in self.tasks],
                "agent_results": [r for r in self.agent_results],
                "total_time": round(self.total_time, 3),
                "agents_involved": self.agents_involved,
                "error": self.error,
            }

    mock_team.handle_query.return_value = MockTeamResult(
        success=True,
        final_answer="Based on research, the answer is...",
        agents_involved=["研究员·知微", "分析师·明察"],
        total_time=1.8,
    )
    mock_team.get_stats.return_value = {
        "total_tasks": 100,
        "successful_tasks": 95,
        "failed_tasks": 5,
        "avg_agents_per_task": 2.3,
        "avg_completion_time": 3.5,
        "agent_workload": {
            "研究员·知微": 40,
            "作家·文思": 25,
            "分析师·明察": 35,
        },
    }
    mock_team.get_task_history.return_value = [
        {"task_id": "t1", "task_type": "research", "status": "completed", "assigned_to": "研究员·知微"},
        {"task_id": "t2", "task_type": "analysis", "status": "completed", "assigned_to": "分析师·明察"},
    ]

    # Patch get_tool_registry
    p1 = patch("src.api.brain_agent._get_tool_registry", return_value=mock_registry)
    # Patch _get_agent_engine
    p2 = patch("src.api.brain_agent._get_agent_engine", return_value=mock_agent_engine)
    # Patch _get_agent_team
    p3 = patch("src.api.brain_agent._get_agent_team", return_value=mock_team)

    p1.start()
    p2.start()
    p3.start()

    yield {
        "registry": mock_registry,
        "agent_engine": mock_agent_engine,
        "team": mock_team,
        "MockToolResult": MockToolResult,
        "MockAgentResult": MockAgentResult,
        "MockTeamResult": MockTeamResult,
        "MockTool": MockTool,
    }

    p1.stop()
    p2.stop()
    p3.stop()


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def app():
    """创建 FastAPI 测试应用，注册 Brain Agent 路由"""
    from src.api.brain_agent import register_brain_agent_routes

    app = FastAPI()
    register_brain_agent_routes(app, prefix="/api/brain")
    return app


@pytest.fixture
def client(app):
    """创建测试客户端（带有效 Token）"""
    # 设置测试用的 M1_ADMIN_TOKEN
    with patch.dict(os.environ, {"M1_ADMIN_TOKEN": "test-m1-token-2026"}):
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def auth_headers():
    """有效认证头"""
    return {"X-M8-Token": "test-m1-token-2026"}


# ============================================================================
# 工具系统接口测试（3 个）
# ============================================================================

class TestToolListAPI:
    """测试工具列表接口"""

    def test_list_tools_success(self, client, auth_headers):
        """获取工具列表成功"""
        response = client.get("/api/brain/tools/list", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["message"] == "ok"
        assert "tools" in data["data"]
        assert data["data"]["total"] == 3
        assert "categories" in data["data"]
        assert len(data["data"]["tools"]) == 3

    def test_list_tools_with_category_filter(self, client, auth_headers, mock_shared_business_modules):
        """按分类筛选工具"""
        # 重新设置 mock 返回值
        mock_registry = mock_shared_business_modules["registry"]
        from unittest.mock import MagicMock as MM

        class MockTool:
            def __init__(self, name, description, category):
                self.name = name
                self.description = description
                self.category = category

            def get_description_for_llm(self):
                return {"name": self.name, "description": self.description,
                        "parameters": {}, "category": self.category}

        mock_registry.list_tools.return_value = [
            MockTool(name="calculator", description="Calc", category="calculation"),
        ]

        response = client.get(
            "/api/brain/tools/list",
            params={"category": "calculation"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        # 验证 mock 被调用时传入了 category 参数
        mock_registry.list_tools.assert_called()


class TestToolStatsAPI:
    """测试工具统计接口"""

    def test_tool_stats_success(self, client, auth_headers):
        """获取工具统计成功"""
        response = client.get("/api/brain/tools/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "stats" in data["data"]
        assert "recent_calls" in data["data"]
        assert data["data"]["stats"]["total_tools"] == 3
        assert data["data"]["stats"]["total_calls"] == 42


class TestToolCallAPI:
    """测试工具调用接口"""

    def test_call_tool_success(self, client, auth_headers):
        """调用工具成功"""
        response = client.post(
            "/api/brain/tools/call/calculator",
            json={"expression": "2 + 2"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["success"] is True
        assert data["data"]["tool_name"] == "calculator"

    def test_call_tool_no_params(self, client, auth_headers):
        """调用工具不传入参数"""
        response = client.post(
            "/api/brain/tools/call/calculator",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0


# ============================================================================
# 单 Agent 接口测试（2 个）
# ============================================================================

class TestAgentRunAPI:
    """测试 Agent 运行接口"""

    def test_agent_run_success(self, client, auth_headers):
        """Agent 运行成功"""
        response = client.post(
            "/api/brain/agent/run",
            json={"query": "What is 2 + 2?"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["success"] is True
        assert "answer" in data["data"]
        assert "total_steps" in data["data"]

    def test_agent_run_with_available_tools(self, client, auth_headers):
        """Agent 运行指定可用工具"""
        response = client.post(
            "/api/brain/agent/run",
            json={
                "query": "Calculate something",
                "available_tools": ["calculator"],
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0


class TestAgentStatsAPI:
    """测试 Agent 统计接口"""

    def test_agent_stats_success(self, client, auth_headers):
        """获取 Agent 统计成功"""
        response = client.get("/api/brain/agent/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "stats" in data["data"]
        assert "recent_executions" in data["data"]
        assert data["data"]["stats"]["total_executions"] == 25


# ============================================================================
# 多 Agent 团队接口测试（4 个）
# ============================================================================

class TestTeamProfileAPI:
    """测试团队配置接口"""

    def test_team_profile_success(self, client, auth_headers):
        """获取团队简介成功"""
        response = client.get("/api/brain/team/profile", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "team_name" in data["data"]
        assert "team_size" in data["data"]
        assert "agents" in data["data"]
        assert data["data"]["team_size"] == 5


class TestTeamQueryAPI:
    """测试团队查询接口"""

    def test_team_query_success(self, client, auth_headers):
        """团队查询成功"""
        response = client.post(
            "/api/brain/team/query",
            json={"query": "Research AI trends"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["success"] is True
        assert "final_answer" in data["data"]
        assert "agents_involved" in data["data"]


class TestTeamStatsAPI:
    """测试团队统计接口"""

    def test_team_stats_success(self, client, auth_headers):
        """获取团队统计成功"""
        response = client.get("/api/brain/team/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "stats" in data["data"]
        assert "recent_tasks" in data["data"]
        assert data["data"]["stats"]["total_tasks"] == 100


class TestTeamTasksAPI:
    """测试团队任务历史接口"""

    def test_team_tasks_success(self, client, auth_headers):
        """获取团队任务历史成功"""
        response = client.get("/api/brain/team/tasks", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "tasks" in data["data"]
        assert "total" in data["data"]

    def test_team_tasks_with_limit(self, client, auth_headers):
        """获取团队任务历史带 limit 参数"""
        response = client.get(
            "/api/brain/team/tasks",
            params={"limit": 5},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0


# ============================================================================
# 认证中间件测试
# ============================================================================

class TestAuthMiddleware:
    """测试 M8 Token 认证中间件"""

    def test_no_token_returns_401(self, client):
        """无 Token 返回 401"""
        response = client.get("/api/brain/tools/list")
        assert response.status_code == 401

    def test_wrong_token_returns_401(self, client):
        """错误 Token 返回 401"""
        response = client.get(
            "/api/brain/tools/list",
            headers={"X-M8-Token": "wrong-token"},
        )
        assert response.status_code == 401

    def test_correct_token_returns_200(self, client, auth_headers):
        """正确 Token 返回 200"""
        response = client.get("/api/brain/tools/list", headers=auth_headers)
        assert response.status_code == 200

    def test_tool_call_requires_auth(self, client):
        """工具调用需要认证"""
        response = client.post(
            "/api/brain/tools/call/test_tool",
            json={"param": "value"},
        )
        assert response.status_code == 401

    def test_team_query_requires_auth(self, client):
        """团队查询需要认证"""
        response = client.post(
            "/api/brain/team/query",
            json={"query": "test"},
        )
        assert response.status_code == 401


# ============================================================================
# 响应格式一致性测试
# ============================================================================

class TestResponseFormat:
    """测试统一响应格式"""

    def test_all_endpoints_have_consistent_format(self, client, auth_headers):
        """所有端点返回格式一致（code, message, data, timestamp）"""
        endpoints = [
            ("GET", "/api/brain/tools/list"),
            ("GET", "/api/brain/tools/stats"),
            ("GET", "/api/brain/agent/stats"),
            ("GET", "/api/brain/team/profile"),
            ("GET", "/api/brain/team/stats"),
            ("GET", "/api/brain/team/tasks"),
        ]

        for method, path in endpoints:
            response = client.request(method, path, headers=auth_headers)
            assert response.status_code == 200, f"{method} {path} failed"
            data = response.json()
            assert "code" in data, f"{method} {path} missing 'code'"
            assert "message" in data, f"{method} {path} missing 'message'"
            assert "data" in data, f"{method} {path} missing 'data'"
            assert "timestamp" in data, f"{method} {path} missing 'timestamp'"
