# -*- coding: utf-8 -*-
"""
M8 运维监控调用路径统一 - 测试脚本

验证 OpsStatusAggregator 的健康检查调用策略：
1. 标准路径 /m8/health 调用成功
2. 404 降级到 /health
3. 连接失败降级到 /health
4. 非标准模块标记（is_standard_m8=False）
5. 降级路径标记（used_fallback=True）
6. data 包裹格式响应解析
7. 裸字段格式响应解析
8. get_module_detail 返回标准标记

运行方式: python test_ops_aggregator_m8_path.py
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# 设置环境变量（必须在导入前）
os.environ.setdefault("YUNXI_ENV", "testing")

# 路径设置
M8_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = M8_ROOT.parent
for _p in (str(PROJECT_ROOT), str(M8_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 导入被测模块
from backend.services.ops_status_aggregator import (
    OpsStatusAggregator,
    ModuleHealthSnapshot,
)
from shared.health.health_checker import HealthStatus


def _make_mock_response(status_code, json_data=None):
    """创建模拟 httpx.Response 对象"""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data or {}
    return mock_resp


def test_standard_m8_health_success():
    """测试用例1：标准路径 /m8/health 调用成功"""
    agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    mock_client.get.return_value = _make_mock_response(
        200,
        {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "healthy",
                "score": 95,
                "uptime_seconds": 3600,
                "checks": {"cpu": "ok"},
            },
        },
    )

    with patch("httpx.Client", return_value=mock_client):
        agg._refresh_module("m7")

    snap = agg._snapshots["m7"]
    assert snap.status == HealthStatus.HEALTHY, f"期望 HEALTHY，实际 {snap.status}"
    assert snap.score == 95
    assert snap.is_standard_m8 is True
    assert snap.used_fallback is False
    assert snap.error is None
    mock_client.get.assert_called_once()
    call_url = mock_client.get.call_args[0][0]
    assert "/m8/health" in call_url
    return True


def test_fallback_on_404():
    """测试用例2：/m8/health 返回 404，降级到 /health"""
    agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
    call_order = []
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    def mock_get(url, **kwargs):
        call_order.append(url)
        if "/m8/health" in url:
            return _make_mock_response(404)
        elif "/health" in url and "/m8/" not in url:
            return _make_mock_response(
                200, {"status": "healthy", "score": 80, "uptime_seconds": 1800}
            )
        return _make_mock_response(404)

    mock_client.get.side_effect = mock_get

    with patch("httpx.Client", return_value=mock_client):
        agg._refresh_module("m6")

    snap = agg._snapshots["m6"]
    assert snap.status == HealthStatus.HEALTHY
    assert snap.score == 80
    assert snap.is_standard_m8 is False
    assert snap.used_fallback is True
    assert len(call_order) == 2
    assert "/m8/health" in call_order[0]
    return True


def test_fallback_on_connection_error():
    """测试用例3：/m8/health 连接失败，降级到 /health"""
    agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
    call_order = []

    first_client = MagicMock()
    first_client.__enter__ = MagicMock(return_value=first_client)
    first_client.__exit__ = MagicMock(return_value=False)

    def first_get(url, **kwargs):
        call_order.append(("first", url))
        raise ConnectionError("Connection refused")

    first_client.get.side_effect = first_get

    second_client = MagicMock()
    second_client.__enter__ = MagicMock(return_value=second_client)
    second_client.__exit__ = MagicMock(return_value=False)

    def second_get(url, **kwargs):
        call_order.append(("second", url))
        return _make_mock_response(
            200,
            {"code": 0, "message": "ok", "data": {"status": "degraded", "score": 65, "uptime_seconds": 900}},
        )

    second_client.get.side_effect = second_get

    client_instances = [first_client, second_client]
    idx = [0]

    def mock_client_class(*args, **kwargs):
        i = idx[0]
        idx[0] += 1
        return client_instances[i]

    with patch("httpx.Client", side_effect=mock_client_class):
        agg._refresh_module("m5")

    snap = agg._snapshots["m5"]
    assert snap.status == HealthStatus.DEGRADED
    assert snap.score == 65
    assert snap.is_standard_m8 is False
    assert snap.used_fallback is True
    assert len(call_order) >= 2
    return True


def test_non_standard_module_flag_in_list():
    """测试用例4：非标准接入模块在 get_module_list 中正确标记"""
    agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    def mock_get(url, **kwargs):
        if "/m8/health" in url:
            return _make_mock_response(404)
        return _make_mock_response(200, {"status": "healthy", "score": 70, "uptime_seconds": 100})

    mock_client.get.side_effect = mock_get

    with patch("httpx.Client", return_value=mock_client):
        agg._refresh_module("m6")

    module_list = agg.get_module_list()
    m6_info = next(m for m in module_list if m["name"] == "m6")
    assert m6_info["is_standard_m8"] is False
    assert m6_info["used_fallback"] is True
    assert m6_info["status"] == "healthy"
    return True


def test_both_paths_fail():
    """测试用例5：两个路径都失败，模块标记为不健康"""
    agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
    call_order = []
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    def mock_get(url, **kwargs):
        call_order.append(url)
        if "/m8/health" in url:
            return _make_mock_response(404)
        return _make_mock_response(500)

    mock_client.get.side_effect = mock_get

    with patch("httpx.Client", return_value=mock_client):
        agg._refresh_module("m4")

    snap = agg._snapshots["m4"]
    assert snap.status == HealthStatus.UNHEALTHY
    assert snap.score == 0
    assert snap.error is not None
    assert "HTTP 500" in snap.error
    assert len(call_order) == 2
    return True


def test_raw_data_format_compatibility():
    """测试用例6：兼容裸字段格式响应"""
    agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    mock_client.get.return_value = _make_mock_response(
        200, {"status": "healthy", "score": 90, "uptime_seconds": 7200, "checks": {"db": "connected"}}
    )

    with patch("httpx.Client", return_value=mock_client):
        agg._refresh_module("m3")

    snap = agg._snapshots["m3"]
    assert snap.status == HealthStatus.HEALTHY
    assert snap.score == 90
    assert snap.checks == {"db": "connected"}
    assert snap.is_standard_m8 is True
    return True


def test_data_wrapped_format_compatibility():
    """测试用例7：兼容 data 包裹格式响应"""
    agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    mock_client.get.return_value = _make_mock_response(
        200,
        {"code": 0, "message": "ok", "data": {"status": "degraded", "score": 75, "uptime_seconds": 5400}},
    )

    with patch("httpx.Client", return_value=mock_client):
        agg._refresh_module("m2")

    snap = agg._snapshots["m2"]
    assert snap.status == HealthStatus.DEGRADED
    assert snap.score == 75
    assert snap.is_standard_m8 is True
    return True


def test_module_detail_includes_standard_flag():
    """测试用例8：get_module_detail 返回标准接入标记"""
    agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    mock_client.get.return_value = _make_mock_response(
        200, {"status": "healthy", "score": 88, "uptime_seconds": 1000}
    )

    with patch("httpx.Client", return_value=mock_client):
        agg._refresh_module("m1")

    detail = agg.get_module_detail("m1")
    assert detail is not None
    assert "is_standard_m8" in detail
    assert "used_fallback" in detail
    assert detail["is_standard_m8"] is True
    assert detail["used_fallback"] is False
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("M8 运维监控调用路径统一 - 测试运行")
    print("=" * 60)

    tests = [
        test_standard_m8_health_success,
        test_fallback_on_404,
        test_fallback_on_connection_error,
        test_non_standard_module_flag_in_list,
        test_both_paths_fail,
        test_raw_data_format_compatibility,
        test_data_wrapped_format_compatibility,
        test_module_detail_includes_standard_flag,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASSED: {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAILED: {test.__name__}")
            print(f"    Error: {e}")
            import traceback
            traceback.print_exc()

    print("=" * 60)
    print(f"结果: {passed} passed, {failed} failed, 共 {len(tests)} 个测试")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
