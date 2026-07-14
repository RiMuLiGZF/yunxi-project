# -*- coding: utf-8 -*-
"""
M8 控制塔 - 健康检查端点测试

验证 /health 和 / 端点的可访问性与响应状态码。
"""


def test_health_endpoint(client):
    """GET /health 返回 200 且包含健康状态信息。"""
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    data = body["data"]
    assert data["status"] == "healthy"
    assert data["module"] == "m8"
    assert "version" in data


def test_root_endpoint(client):
    """GET / 返回 200 或重定向（3xx）。"""
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (200, 301, 302, 303, 307, 308)
