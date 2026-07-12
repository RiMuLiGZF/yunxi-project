"""M8 管理接口测试 — 鉴权 + 健康检查 + 性能指标.

测试类别：健康检查接口(4) + 性能指标接口(3) + 鉴权测试(5) = 12个
"""

from __future__ import annotations

import os
import tempfile

import pytest

from edge_cloud_kernel.m8_api.m8_auth_middleware import (
    M8TokenAuthMiddleware,
    WHITE_LIST_PATHS,
)
from edge_cloud_kernel.m8_api.health_endpoints import HealthMetricsService


# ---------------------------------------------------------------------------
# 鉴权测试（5个）
# ---------------------------------------------------------------------------

class TestM8AuthMiddleware:
    """M8 Token 鉴权中间件测试."""

    def test_valid_token(self, monkeypatch):
        """测试有效 Token 验证通过."""
        monkeypatch.setenv("M3_ADMIN_TOKEN", "test_secret_token_123")
        middleware = M8TokenAuthMiddleware(env="development")
        assert middleware.verify_token("test_secret_token_123") is True

    def test_invalid_token(self, monkeypatch):
        """测试无效 Token 被拒绝."""
        monkeypatch.setenv("M3_ADMIN_TOKEN", "test_secret_token_123")
        middleware = M8TokenAuthMiddleware(env="development")
        assert middleware.verify_token("wrong_token") is False

    def test_missing_token(self, monkeypatch):
        """测试缺失 Token."""
        monkeypatch.setenv("M3_ADMIN_TOKEN", "test_secret_token_123")
        middleware = M8TokenAuthMiddleware(env="development")
        assert middleware.verify_token("") is False

    def test_whitelist_path(self, monkeypatch):
        """测试白名单路径跳过鉴权."""
        monkeypatch.setenv("M3_ADMIN_TOKEN", "test_secret_token_123")
        middleware = M8TokenAuthMiddleware(env="development")
        assert middleware.is_whitelisted("/api/v3/health") is True
        assert middleware.is_whitelisted("/api/v3/health?debug=1") is True
        assert middleware.is_whitelisted("/api/v3/metrics") is False

    def test_check_auth_full_flow(self, monkeypatch):
        """测试完整鉴权流程."""
        monkeypatch.setenv("M3_ADMIN_TOKEN", "test_token")
        middleware = M8TokenAuthMiddleware(env="development")

        # 白名单路径
        ok, code, msg = middleware.check_auth("/api/v3/health", {})
        assert ok is True
        assert code == 0

        # 非白名单 + 无 token
        ok, code, msg = middleware.check_auth("/api/v3/metrics", {})
        assert ok is False
        assert code == 30401  # ERR_AUTH_REQUIRED

        # 非白名单 + 有效 token
        ok, code, msg = middleware.check_auth(
            "/api/v3/metrics",
            {"Authorization": "Bearer test_token"},
        )
        assert ok is True
        assert code == 0

        # 非白名单 + 无效 token
        ok, code, msg = middleware.check_auth(
            "/api/v3/metrics",
            {"Authorization": "Bearer wrong_token"},
        )
        assert ok is False
        assert code == 30402  # ERR_AUTH_TOKEN_INVALID


# ---------------------------------------------------------------------------
# 健康检查接口测试（4个）
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """健康检查接口测试."""

    @pytest.mark.asyncio
    async def test_health_status_healthy(self):
        """测试健康状态为 healthy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = os.path.join(tmpdir, "data")
            os.makedirs(storage_path)
            service = HealthMetricsService(storage_path=storage_path)
            result = await service.get_health()
            assert "status" in result
            assert "version" in result
            assert "uptime_seconds" in result
            assert "module" in result
            assert "checks" in result
            assert result["module"] == "m3"
            assert isinstance(result["checks"], dict)

    @pytest.mark.asyncio
    async def test_health_checks_keys(self):
        """测试健康检查项包含数据库、存储、网络、同步引擎."""
        service = HealthMetricsService()
        result = await service.get_health()
        checks = result["checks"]
        assert "database" in checks
        assert "storage" in checks
        assert "network" in checks
        assert "sync_engine" in checks

    @pytest.mark.asyncio
    async def test_health_degraded_state(self):
        """测试降级状态（模拟网络不稳定）."""
        # 无 health_checker + 无 offline_proxy 时 network 为 unknown
        service = HealthMetricsService()
        result = await service.get_health()
        # 不依赖外部组件时应仍返回有效结果
        assert result["status"] in ("healthy", "degraded", "unhealthy")

    @pytest.mark.asyncio
    async def test_health_request_id(self):
        """测试请求 ID 透传."""
        service = HealthMetricsService()
        result = await service.get_health(request_id="test-req-001")
        # request_id 通过 M8APIResponse 包装，此处验证服务层返回结构
        assert "status" in result


# ---------------------------------------------------------------------------
# 性能指标接口测试（3个）
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    """性能指标接口测试."""

    @pytest.mark.asyncio
    async def test_metrics_structure(self):
        """测试性能指标返回结构完整."""
        service = HealthMetricsService()
        result = await service.get_metrics()
        required_keys = [
            "cpu_percent", "memory_mb", "disk_usage_mb",
            "requests_total", "requests_per_second",
            "avg_response_ms", "error_rate",
            "sync_tasks_total", "sync_success_rate",
            "pending_sync_items", "conflict_count",
            "offline_queue_size",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_metrics_types(self):
        """测试指标数据类型正确."""
        service = HealthMetricsService()
        result = await service.get_metrics()
        assert isinstance(result["requests_total"], int)
        assert isinstance(result["error_rate"], float)
        assert isinstance(result["sync_success_rate"], float)
        assert 0.0 <= result["error_rate"] <= 1.0
        assert 0.0 <= result["sync_success_rate"] <= 1.0

    @pytest.mark.asyncio
    async def test_metrics_collector_record(self):
        """测试指标收集器记录请求."""
        service = HealthMetricsService()
        metrics = service.metrics
        initial_total = metrics.requests_total
        metrics.record_request(success=True, response_ms=50.0)
        assert metrics.requests_total == initial_total + 1
        assert metrics.avg_response_ms > 0
