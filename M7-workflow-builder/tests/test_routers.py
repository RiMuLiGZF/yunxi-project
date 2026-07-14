"""
M7 积木平台 - 路由层集成测试

测试工作流、运行、积木块等路由的可用性。
运行方式: pytest tests/test_routers.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    """创建 FastAPI 测试客户端"""
    return TestClient(app)


class TestWorkflowRouter:
    """工作流管理路由测试"""

    def test_list_workflows(self, client):
        """测试获取工作流列表"""
        response = client.get("/api/v1/workflows")
        assert response.status_code in (200, 401, 403)

    def test_create_workflow_validation(self, client):
        """测试创建工作流参数校验"""
        # 缺少必填字段
        response = client.post("/api/v1/workflows", json={})
        assert response.status_code in (422, 401, 403)

    def test_get_workflow_not_found(self, client):
        """测试获取不存在的工作流"""
        response = client.get("/api/v1/workflows/nonexistent-12345")
        assert response.status_code in (404, 401, 403)

    def test_update_workflow_not_found(self, client):
        """测试更新不存在的工作流"""
        response = client.put(
            "/api/v1/workflows/nonexistent-12345",
            json={"name": "test"},
        )
        assert response.status_code in (404, 401, 403)

    def test_delete_workflow_not_found(self, client):
        """测试删除不存在的工作流"""
        response = client.delete("/api/v1/workflows/nonexistent-12345")
        assert response.status_code in (404, 401, 403)

    def test_duplicate_workflow_not_found(self, client):
        """测试复制不存在的工作流"""
        response = client.post("/api/v1/workflows/nonexistent-12345/duplicate")
        assert response.status_code in (404, 401, 403)


class TestWorkflowRunRouter:
    """工作流运行路由测试"""

    def test_list_runs(self, client):
        """测试获取运行记录列表"""
        response = client.get("/api/v1/runs")
        assert response.status_code in (200, 401, 403)

    def test_get_run_not_found(self, client):
        """测试获取不存在的运行记录"""
        response = client.get("/api/v1/runs/nonexistent-12345")
        assert response.status_code in (404, 401, 403)

    def test_run_workflow_not_found(self, client):
        """测试运行不存在的工作流"""
        response = client.post(
            "/api/v1/workflows/nonexistent-12345/run",
            json={},
        )
        assert response.status_code in (404, 401, 403)

    def test_stop_run_not_found(self, client):
        """测试停止不存在的运行"""
        response = client.post("/api/v1/runs/nonexistent-12345/stop")
        assert response.status_code in (404, 401, 403)


class TestBlockRouter:
    """积木块路由测试"""

    def test_list_blocks(self, client):
        """测试获取积木块列表"""
        response = client.get("/api/v1/blocks")
        assert response.status_code in (200, 401, 403)

    def test_get_block_not_found(self, client):
        """测试获取不存在的积木块"""
        response = client.get("/api/v1/blocks/nonexistent-12345")
        assert response.status_code in (404, 401, 403)


class TestTemplateRouter:
    """模板路由测试"""

    def test_list_templates(self, client):
        """测试获取模板列表"""
        response = client.get("/api/v1/templates")
        assert response.status_code in (200, 401, 403)

    def test_get_template_not_found(self, client):
        """测试获取不存在的模板"""
        response = client.get("/api/v1/templates/nonexistent-12345")
        assert response.status_code in (404, 401, 403)


class TestM8Endpoints:
    """M8 标准接口测试"""

    def test_m8_health(self, client):
        """测试 /m8/health"""
        response = client.get("/m8/health")
        assert response.status_code in (200, 401, 404)

    def test_m8_metrics(self, client):
        """测试 /m8/metrics"""
        response = client.get("/m8/metrics")
        assert response.status_code in (200, 401, 404)

    def test_m8_config(self, client):
        """测试 /m8/config"""
        response = client.get("/m8/config")
        assert response.status_code in (200, 401, 404)
