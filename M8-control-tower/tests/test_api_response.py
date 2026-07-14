# -*- coding: utf-8 -*-
"""
M8 控制塔 - API 响应格式测试

验证 ApiResponse 的 success() 和 error() 工厂方法输出格式正确。
"""

from backend.schemas import ApiResponse


def test_api_response_success():
    """ApiResponse.success() 格式正确。"""
    payload = {"id": 1, "name": "测试"}
    resp = ApiResponse.success(data=payload)

    assert resp.code == 0
    assert resp.message == "ok"
    assert resp.data == payload
    assert resp.request_id is None
    # timestamp 应为数值类型
    assert isinstance(resp.timestamp, (int, float))
    assert resp.timestamp > 0


def test_api_response_success_custom_message():
    """ApiResponse.success() 支持自定义消息。"""
    resp = ApiResponse.success(data=None, message="created")
    assert resp.code == 0
    assert resp.message == "created"
    assert resp.data is None


def test_api_response_error():
    """ApiResponse.error() 格式正确。"""
    resp = ApiResponse.error(code=500, message="内部错误")

    assert resp.code == 500
    assert resp.message == "内部错误"
    assert resp.data is None
    assert resp.request_id is None
    assert isinstance(resp.timestamp, (int, float))
    assert resp.timestamp > 0


def test_api_response_error_with_data():
    """ApiResponse.error() 支持附带数据。"""
    detail = {"field": "username", "issue": "required"}
    resp = ApiResponse.error(code=422, message="验证失败", data=detail)

    assert resp.code == 422
    assert resp.message == "验证失败"
    assert resp.data == detail
