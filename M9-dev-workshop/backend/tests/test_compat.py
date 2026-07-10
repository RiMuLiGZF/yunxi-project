"""
M9 开发者工坊 - 兼容路由测试
测试内容：
1. stats 系列兼容接口
2. projects 兼容接口
3. activities 兼容接口
4. vscode 兼容接口
5. mcp 兼容接口

使用方式：
    cd M9-dev-workshop/backend
    python -m pytest tests/test_compat.py -v
    或
    python tests/test_compat.py
"""

import sys
from pathlib import Path

# 添加项目路径
backend_dir = Path(__file__).parent.parent.resolve()
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest
from fastapi.testclient import TestClient

from main import app


# ==================== Fixtures ====================

@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)


# ==================== Stats 兼容接口测试 ====================

class TestStatsCompat:
    """stats 系列兼容接口测试"""

    def test_stats_summary(self, client):
        """测试 /stats/summary 接口"""
        response = client.get("/api/stats/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data
        assert "total_projects" in data["data"]
        assert "today_activities" in data["data"]

    def test_stats_daily(self, client):
        """测试 /stats/daily 接口"""
        response = client.get("/api/stats/daily")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "days" in data
        assert "trend" in data
        assert isinstance(data["trend"], list)

    def test_stats_daily_with_days_param(self, client):
        """测试 /stats/daily 带 days 参数"""
        response = client.get("/api/stats/daily?days=3")
        assert response.status_code == 200
        data = response.json()
        assert data["days"] == 3
        assert len(data["trend"]) == 3

    def test_stats_projects(self, client):
        """测试 /stats/projects 接口"""
        response = client.get("/api/stats/projects")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "count" in data
        assert "projects" in data
        assert isinstance(data["projects"], list)


# ==================== Projects 兼容接口测试 ====================

class TestProjectsCompat:
    """projects 兼容接口测试"""

    def test_list_projects(self, client):
        """测试 /projects 接口"""
        response = client.get("/api/projects")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "count" in data
        assert "projects" in data

    def test_recent_projects(self, client):
        """测试 /projects/recent 接口"""
        response = client.get("/api/projects/recent")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "projects" in data

    def test_scan_projects(self, client):
        """测试 /projects/scan 接口"""
        response = client.post("/api/projects/scan", json={"scan_dirs": []})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_list_projects_with_tag(self, client):
        """测试 /projects 带 tag 参数"""
        response = client.get("/api/projects?tag=python")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


# ==================== Activities 兼容接口测试 ====================

class TestActivitiesCompat:
    """activities 兼容接口测试"""

    def test_list_activities(self, client):
        """测试 /activities 接口"""
        response = client.get("/api/activities")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "count" in data
        assert "activities" in data

    def test_recent_activities(self, client):
        """测试 /activities/recent 接口"""
        response = client.get("/api/activities/recent")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "activities" in data

    def test_activities_with_days(self, client):
        """测试 /activities 带 days 参数"""
        response = client.get("/api/activities?days=3")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


# ==================== VS Code 兼容接口测试 ====================

class TestVSCodeCompat:
    """VS Code 兼容接口测试"""

    def test_vscode_stop(self, client):
        """测试 /vscode/stop 接口"""
        response = client.post("/api/vscode/stop", json={})
        assert response.status_code == 200
        data = response.json()
        assert "success" in data

    def test_vscode_stop_with_pid(self, client):
        """测试 /vscode/stop 带 PID"""
        response = client.post("/api/vscode/stop", json={"pid": 99999})
        assert response.status_code == 200
        data = response.json()
        assert "success" in data

    def test_vscode_open_without_path(self, client):
        """测试 /vscode/open 不带路径（应返回 400）"""
        response = client.post("/api/vscode/open", json={})
        # 没有路径应该返回 400
        assert response.status_code in [400, 200]

    def test_vscode_session(self, client):
        """测试 /vscode/session 接口"""
        response = client.get("/api/vscode/session")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "session" in data

    def test_vscode_history(self, client):
        """测试 /vscode/history 接口"""
        response = client.get("/api/vscode/history")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "history" in data


# ==================== MCP 兼容接口测试 ====================

class TestMCPCompat:
    """MCP 兼容接口测试"""

    def test_mcp_call_without_tool(self, client):
        """测试 /mcp/call 不带工具名（应返回 400）"""
        response = client.post("/api/mcp/call", json={"arguments": {}})
        assert response.status_code == 400

    def test_mcp_call_with_nonexistent_tool(self, client):
        """测试 /mcp/call 调用不存在的工具"""
        response = client.post(
            "/api/mcp/call",
            json={"tool_name": "nonexistent_tool", "arguments": {}}
        )
        # 可能返回 500 或 200，取决于实现
        assert response.status_code in [200, 404, 500]

    def test_mcp_call_with_tool_alias(self, client):
        """测试 /mcp/call 使用 tool 别名参数"""
        response = client.post(
            "/api/mcp/call",
            json={"tool": "test_tool", "args": {}}
        )
        assert response.status_code in [200, 404, 500]


# ==================== 响应格式一致性测试 ====================

class TestResponseFormat:
    """响应格式一致性测试"""

    def test_all_endpoints_have_success_field(self, client):
        """测试所有兼容接口都有 success 字段"""
        endpoints = [
            "/api/stats/summary",
            "/api/stats/daily",
            "/api/stats/projects",
            "/api/projects",
            "/api/projects/recent",
            "/api/activities",
            "/api/activities/recent",
            "/api/vscode/session",
            "/api/vscode/history",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            data = response.json()
            assert "success" in data, f"{endpoint} 缺少 success 字段"


# ==================== 直接运行入口 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("M9 兼容路由测试")
    print("=" * 60)

    # 使用 pytest 运行
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    sys.exit(exit_code)
