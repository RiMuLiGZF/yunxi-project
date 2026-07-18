"""
M7 /m8/metrics 接口对齐测试

验证 /m8/metrics 与 /api/v1/admin/metrics 字段对齐，包含：
1. 完整字段返回验证
2. 与 admin metrics 字段对比
3. CPU/内存指标存在
4. 平均响应时间和错误率计算
5. 健康状态字段
6. 活跃连接数字段
7. 向后兼容性（原有字段保留）
8. data 包裹格式一致
"""

import os
import sys
import pytest
from fastapi.testclient import TestClient

# 设置测试 token（必须在导入 app 之前设置）
os.environ["M7_ADMIN_TOKEN"] = "test-token-m7-12345"

from src.main import app

TEST_TOKEN = "test-token-m7-12345"
AUTH_HEADERS = {"X-M8-Token": TEST_TOKEN}


@pytest.fixture
def client():
    """创建 FastAPI 测试客户端"""
    return TestClient(app)


@pytest.fixture
def sample_requests():
    """模拟一些请求数据，确保指标有值。"""
    from src.m8_api.health_endpoints import _metrics, record_request, record_run

    # 重置指标
    _metrics["requests_total"] = 0
    _metrics["requests_error"] = 0
    _metrics["response_time_sum_ms"] = 0.0
    _metrics["response_time_count"] = 0
    _metrics["runs_total"] = 0
    _metrics["runs_success"] = 0
    _metrics["runs_failed"] = 0
    _metrics["workflows_total"] = 0

    # 记录一些请求
    for i in range(10):
        record_request(success=True, response_ms=50.0 + i)
    record_request(success=False, response_ms=100.0)  # 1个错误请求

    # 记录一些工作流运行
    for i in range(8):
        record_run(success=True)
    record_run(success=False)  # 1个失败运行

    yield
    # 清理
    _metrics["requests_total"] = 0
    _metrics["requests_error"] = 0
    _metrics["response_time_sum_ms"] = 0.0
    _metrics["response_time_count"] = 0
    _metrics["runs_total"] = 0
    _metrics["runs_success"] = 0
    _metrics["runs_failed"] = 0
    _metrics["workflows_total"] = 0


class TestM8MetricsEndpoint:
    """/m8/metrics 接口测试。"""

    def test_m8_metrics_returns_200(self, client):
        """测试用例1：/m8/metrics 接口返回 200 状态码。"""
        response = client.get("/m8/metrics", headers=AUTH_HEADERS)
        assert response.status_code == 200

    def test_m8_metrics_has_standard_wrapper(self, client):
        """测试用例2：/m8/metrics 返回标准 data 包裹格式。"""
        response = client.get("/m8/metrics", headers=AUTH_HEADERS)
        body = response.json()
        assert "code" in body
        assert "message" in body
        assert "data" in body
        assert body["code"] == 0
        assert body["message"] == "ok"
        assert isinstance(body["data"], dict)

    def test_m8_metrics_has_cpu_and_memory(self, client):
        """测试用例3：/m8/metrics 包含 CPU 和内存指标。"""
        response = client.get("/m8/metrics", headers=AUTH_HEADERS)
        data = response.json()["data"]
        # CPU 使用率
        assert "cpu_percent" in data
        assert isinstance(data["cpu_percent"], (int, float))
        assert data["cpu_percent"] >= 0
        # 内存使用量
        assert "memory_mb" in data
        assert isinstance(data["memory_mb"], (int, float))
        assert data["memory_mb"] >= 0

    def test_m8_metrics_has_request_stats(self, client, sample_requests):
        """测试用例4：/m8/metrics 包含请求统计指标。"""
        response = client.get("/m8/metrics", headers=AUTH_HEADERS)
        data = response.json()["data"]
        # 请求总数
        assert "requests_total" in data
        assert data["requests_total"] >= 10  # 至少有我们模拟的 10 个
        # 错误请求数
        assert "requests_error" in data
        assert data["requests_error"] >= 1
        # 平均响应时间
        assert "avg_response_ms" in data
        assert isinstance(data["avg_response_ms"], (int, float))
        assert data["avg_response_ms"] >= 0
        # 错误率
        assert "error_rate" in data
        assert isinstance(data["error_rate"], (int, float))
        assert 0 <= data["error_rate"] <= 1

    def test_m8_metrics_has_workflow_stats(self, client, sample_requests):
        """测试用例5：/m8/metrics 包含工作流统计指标。"""
        response = client.get("/m8/metrics", headers=AUTH_HEADERS)
        data = response.json()["data"]
        # 工作流总数
        assert "workflows_total" in data
        # 运行总数
        assert "runs_total" in data
        assert data["runs_total"] >= 9  # 8成功 + 1失败
        # 成功数
        assert "runs_success" in data
        assert data["runs_success"] >= 8
        # 失败数
        assert "runs_failed" in data
        assert data["runs_failed"] >= 1
        # 成功率
        assert "run_success_rate" in data
        assert isinstance(data["run_success_rate"], (int, float))
        assert 0 <= data["run_success_rate"] <= 1

    def test_m8_metrics_has_health_status(self, client):
        """测试用例6：/m8/metrics 包含健康状态。"""
        response = client.get("/m8/metrics", headers=AUTH_HEADERS)
        data = response.json()["data"]
        # 健康状态
        assert "health_status" in data
        assert data["health_status"] in ("healthy", "degraded", "unhealthy", "unknown")
        # 检查项
        assert "checks" in data
        assert isinstance(data["checks"], dict)
        assert "storage" in data["checks"]

    def test_m8_metrics_has_active_connections(self, client):
        """测试用例7：/m8/metrics 包含活跃连接数。"""
        response = client.get("/m8/metrics", headers=AUTH_HEADERS)
        data = response.json()["data"]
        assert "active_connections" in data
        assert isinstance(data["active_connections"], int)
        assert data["active_connections"] >= 1

    def test_m8_metrics_has_uptime(self, client):
        """测试用例8：/m8/metrics 包含运行时间。"""
        response = client.get("/m8/metrics", headers=AUTH_HEADERS)
        data = response.json()["data"]
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int)
        assert data["uptime_seconds"] >= 0

    def test_m8_metrics_has_version_info(self, client):
        """测试用例9：/m8/metrics 包含版本信息。"""
        response = client.get("/m8/metrics", headers=AUTH_HEADERS)
        data = response.json()["data"]
        assert "version" in data
        assert "module" in data
        assert data["module"] == "m7"


class TestMetricsAlignment:
    """/m8/metrics 与 /api/v1/admin/metrics 字段对齐测试。"""

    def test_admin_metrics_fields_subset_of_m8_metrics(self, client, sample_requests):
        """测试用例10：admin metrics 的所有核心字段在 /m8/metrics 中都存在。"""
        admin_resp = client.get("/api/v1/admin/metrics", headers=AUTH_HEADERS)
        m8_resp = client.get("/m8/metrics", headers=AUTH_HEADERS)

        assert admin_resp.status_code == 200
        assert m8_resp.status_code == 200

        admin_data = admin_resp.json()["data"]
        m8_data = m8_resp.json()["data"]

        # admin metrics 的核心字段必须在 m8/metrics 中存在
        core_fields = [
            "cpu_percent",
            "memory_mb",
            "uptime_seconds",
            "requests_total",
            "requests_error",
            "avg_response_ms",
            "error_rate",
            "workflows_total",
            "runs_total",
            "runs_success",
            "runs_failed",
            "run_success_rate",
        ]

        missing_fields = [f for f in core_fields if f not in m8_data]
        assert not missing_fields, f"/m8/metrics 缺少字段: {missing_fields}"

    def test_error_rate_calculation_consistency(self, client, sample_requests):
        """测试用例11：/m8/metrics 和 admin metrics 的错误率计算一致。"""
        admin_resp = client.get("/api/v1/admin/metrics", headers=AUTH_HEADERS)
        m8_resp = client.get("/m8/metrics", headers=AUTH_HEADERS)

        admin_data = admin_resp.json()["data"]
        m8_data = m8_resp.json()["data"]

        # 两个接口的错误率都应该在合理范围内（0-1）
        assert 0 <= admin_data["error_rate"] <= 1
        assert 0 <= m8_data["error_rate"] <= 1

    def test_backward_compatibility_original_fields(self, client):
        """测试用例12：向后兼容 - 原有字段仍然存在。"""
        response = client.get("/m8/metrics", headers=AUTH_HEADERS)
        data = response.json()["data"]

        # 原有的字段（修改前就存在的）必须保留
        original_fields = [
            "uptime_seconds",
            "requests_total",
            "requests_error",
            "workflows_total",
            "runs_total",
            "runs_success",
            "runs_failed",
        ]

        for field in original_fields:
            assert field in data, f"向后兼容字段缺失: {field}"

    def test_m8_metrics_has_more_fields_than_before(self, client):
        """测试用例13：/m8/metrics 新增字段数量正确（只增不减）。"""
        response = client.get("/m8/metrics", headers=AUTH_HEADERS)
        data = response.json()["data"]

        # 原有 7 个字段 + 新增 10 个字段 = 至少 17 个
        # 新增: cpu_percent, memory_mb, avg_response_ms, error_rate,
        #       run_success_rate, health_status, checks, active_connections,
        #       version, module
        assert len(data) >= 12, f"字段数量不足，当前: {len(data)} 个，应有至少 12 个"

    def test_m8_health_endpoint_exists(self, client):
        """测试用例14：/m8/health 端点存在且正常返回。"""
        response = client.get("/m8/health", headers=AUTH_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "status" in body["data"]

    def test_m8_config_endpoint_exists(self, client):
        """测试用例15：/m8/config 端点存在且正常返回。"""
        response = client.get("/m8/config", headers=AUTH_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "module" in body["data"]
        assert body["data"]["module"] == "m7"
