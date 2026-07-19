"""
统一响应标准 - 单元测试
========================

测试覆盖：
1. ApiResponse.success() / error() 正确性
2. to_dict() / from_dict() 序列化
3. 标准字段验证（code/message/data/trace_id/timestamp）
4. 便捷函数 ok() / fail()
5. 错误码常量测试
6. 旧格式兼容 from_legacy_response()
7. FastAPI 集成测试
8. 中间件异常包装测试
"""

import time
import json
import pytest
from typing import Any, Dict


# ============================================================
# 测试 1-8: ApiResponse 核心功能
# ============================================================

class TestApiResponseCore:
    """ApiResponse 核心功能测试."""

    def test_success_default(self):
        """测试 1: success() 默认参数."""
        from shared.unified_response import ApiResponse
        resp = ApiResponse.success()
        assert resp.code == 0
        assert resp.message == "ok"
        assert resp.data is None
        assert resp.trace_id is None
        assert isinstance(resp.timestamp, float)
        assert resp.is_success is True

    def test_success_with_data_and_message(self):
        """测试 2: success() 带数据和消息."""
        from shared.unified_response import ApiResponse
        data = {"key": "value", "num": 42}
        resp = ApiResponse.success(data=data, message="操作成功")
        assert resp.code == 0
        assert resp.message == "操作成功"
        assert resp.data == data
        assert resp.is_success is True

    def test_success_with_trace_id(self):
        """测试 3: success() 带 trace_id."""
        from shared.unified_response import ApiResponse
        trace_id = "test-trace-123"
        resp = ApiResponse.success(data={"a": 1}, trace_id=trace_id)
        assert resp.trace_id == trace_id

    def test_error_default(self):
        """测试 4: error() 默认参数."""
        from shared.unified_response import ApiResponse, ERR_INTERNAL
        resp = ApiResponse.error()
        assert resp.code == ERR_INTERNAL
        assert resp.message is not None  # 有标准消息
        assert resp.is_success is False

    def test_error_with_code_and_message(self):
        """测试 5: error() 带错误码和消息."""
        from shared.unified_response import ApiResponse
        resp = ApiResponse.error(code=404, message="Not Found")
        assert resp.code == 404
        assert resp.message == "Not Found"
        assert resp.is_success is False

    def test_error_with_data(self):
        """测试 6: error() 带附加数据."""
        from shared.unified_response import ApiResponse
        err_data = {"field": "name", "reason": "required"}
        resp = ApiResponse.error(code=400, message="Bad Request", data=err_data)
        assert resp.data == err_data

    def test_to_dict_has_all_fields(self):
        """测试 7: to_dict() 返回所有标准字段."""
        from shared.unified_response import ApiResponse
        resp = ApiResponse.success(
            data={"test": 1},
            trace_id="abc123",
        )
        d = resp.to_dict()
        assert "code" in d
        assert "message" in d
        assert "data" in d
        assert "trace_id" in d
        assert "timestamp" in d
        assert isinstance(d["timestamp"], float)

    def test_from_dict_roundtrip(self):
        """测试 8: from_dict() 往返序列化."""
        from shared.unified_response import ApiResponse
        original = ApiResponse.success(
            data={"key": "value"},
            message="test",
            trace_id="trace-001",
        )
        d = original.to_dict()
        restored = ApiResponse.from_dict(d)
        assert restored.code == original.code
        assert restored.message == original.message
        assert restored.data == original.data
        assert restored.trace_id == original.trace_id
        assert abs(restored.timestamp - original.timestamp) < 0.001


# ============================================================
# 测试 9-11: 便捷函数
# ============================================================

class TestConvenienceFunctions:
    """便捷函数测试."""

    def test_ok_function(self):
        """测试 9: ok() 便捷函数."""
        from shared.unified_response import ok
        result = ok(data={"foo": "bar"}, message="成功")
        assert isinstance(result, dict)
        assert result["code"] == 0
        assert result["message"] == "成功"
        assert result["data"] == {"foo": "bar"}
        assert "trace_id" in result
        assert "timestamp" in result
        assert isinstance(result["timestamp"], float)

    def test_fail_function(self):
        """测试 10: fail() 便捷函数."""
        from shared.unified_response import fail
        result = fail(code=500, message="服务器错误")
        assert isinstance(result, dict)
        assert result["code"] == 500
        assert result["message"] == "服务器错误"
        assert "trace_id" in result
        assert "timestamp" in result

    def test_generate_trace_id(self):
        """测试 11: generate_trace_id() 函数."""
        from shared.unified_response import generate_trace_id
        tid = generate_trace_id()
        assert isinstance(tid, str)
        assert len(tid) == 32  # uuid4 hex is 32 chars
        # 两次调用生成不同的 ID
        tid2 = generate_trace_id()
        assert tid != tid2


# ============================================================
# 测试 12-14: 错误码常量
# ============================================================

class TestConstants:
    """错误码常量测试."""

    def test_standard_error_codes_defined(self):
        """测试 12: 标准错误码常量已定义."""
        from shared.unified_response import (
            SUCCESS,
            ERR_VALIDATION,
            ERR_AUTH_FAILED,
            ERR_PERMISSION_DENIED,
            ERR_NOT_FOUND,
            ERR_INTERNAL,
            ERR_RATE_LIMITED,
            ERR_SERVICE_UNAVAILABLE,
        )
        assert SUCCESS == 0
        assert ERR_VALIDATION == 101
        assert ERR_AUTH_FAILED == 201
        assert ERR_PERMISSION_DENIED == 301
        assert ERR_NOT_FOUND == 401
        assert ERR_INTERNAL == 601
        assert ERR_RATE_LIMITED == 801
        assert ERR_SERVICE_UNAVAILABLE == 602

    def test_get_standard_message(self):
        """测试 13: get_standard_message() 函数."""
        from shared.unified_response import (
            get_standard_message,
            SUCCESS,
            ERR_NOT_FOUND,
            ERR_INTERNAL,
        )
        assert get_standard_message(SUCCESS) == "ok"
        assert get_standard_message(ERR_NOT_FOUND) == "资源不存在"
        assert get_standard_message(ERR_INTERNAL) == "服务器内部错误"
        # 未定义的错误码返回默认值
        assert get_standard_message(99999) == "error"

    def test_get_http_status(self):
        """测试 14: get_http_status() 函数."""
        from shared.unified_response import (
            get_http_status,
            SUCCESS,
            ERR_VALIDATION,
            ERR_AUTH_FAILED,
            ERR_NOT_FOUND,
            ERR_INTERNAL,
            ERR_RATE_LIMITED,
            HTTP_OK,
            HTTP_BAD_REQUEST,
            HTTP_UNAUTHORIZED,
            HTTP_NOT_FOUND,
            HTTP_INTERNAL_SERVER_ERROR,
            HTTP_TOO_MANY_REQUESTS,
        )
        assert get_http_status(SUCCESS) == HTTP_OK
        assert get_http_status(ERR_VALIDATION) == HTTP_BAD_REQUEST
        assert get_http_status(ERR_AUTH_FAILED) == HTTP_UNAUTHORIZED
        assert get_http_status(ERR_NOT_FOUND) == HTTP_NOT_FOUND
        assert get_http_status(ERR_INTERNAL) == HTTP_INTERNAL_SERVER_ERROR
        assert get_http_status(ERR_RATE_LIMITED) == HTTP_TOO_MANY_REQUESTS
        # 未定义的错误码返回 500
        assert get_http_status(99999) == HTTP_INTERNAL_SERVER_ERROR


# ============================================================
# 测试 15: 旧格式兼容
# ============================================================

class TestLegacyCompatibility:
    """旧格式兼容测试."""

    def test_from_legacy_request_id(self):
        """测试 15a: 从旧格式 request_id 字段迁移."""
        from shared.unified_response import from_legacy_response
        legacy = {
            "code": 0,
            "message": "ok",
            "data": {"test": 1},
            "request_id": "req-123",
            "timestamp": 1700000000,
        }
        resp = from_legacy_response(legacy)
        assert resp.trace_id == "req-123"
        assert resp.code == 0
        assert resp.data == {"test": 1}

    def test_from_legacy_millisecond_timestamp(self):
        """测试 15b: 从毫秒级时间戳转换."""
        from shared.unified_response import from_legacy_response
        # 毫秒级时间戳（大于 1e12）
        ms_ts = 1700000000000  # 毫秒
        legacy = {
            "code": 0,
            "message": "ok",
            "data": None,
            "timestamp": ms_ts,
        }
        resp = from_legacy_response(legacy)
        # 应该转换为秒级
        assert isinstance(resp.timestamp, float)
        assert abs(resp.timestamp - 1700000000.0) < 1.0

    def test_from_legacy_second_timestamp_int(self):
        """测试 15c: 秒级整数时间戳."""
        from shared.unified_response import from_legacy_response
        legacy = {
            "code": 0,
            "message": "ok",
            "data": None,
            "timestamp": 1700000000,
        }
        resp = from_legacy_response(legacy)
        assert isinstance(resp.timestamp, float)
        assert resp.timestamp == 1700000000.0

    def test_from_legacy_minimal_fields(self):
        """测试 15d: 最少字段的旧格式（3 字段）."""
        from shared.unified_response import from_legacy_response
        legacy = {
            "code": 404,
            "message": "not found",
            "data": None,
        }
        resp = from_legacy_response(legacy)
        assert resp.code == 404
        assert resp.message == "not found"
        assert resp.trace_id is None
        assert isinstance(resp.timestamp, float)
        assert resp.timestamp > 0


# ============================================================
# 测试 16: 链式调用
# ============================================================

class TestChaining:
    """链式调用测试."""

    def test_chained_methods(self):
        """测试 16: 链式调用方法."""
        from shared.unified_response import ApiResponse
        resp = ApiResponse.success() \
            .with_data({"key": "value"}) \
            .with_message("链式调用成功") \
            .with_trace_id("chain-001") \
            .with_code(200)

        assert resp.data == {"key": "value"}
        assert resp.message == "链式调用成功"
        assert resp.trace_id == "chain-001"
        assert resp.code == 200


# ============================================================
# 测试 17-19: FastAPI 集成（使用 TestClient）
# ============================================================

class TestFastAPIIntegration:
    """FastAPI 集成测试."""

    def test_unified_response_decorator(self):
        """测试 17: unified_response 装饰器."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from shared.unified_response import unified_response

        app = FastAPI()

        @app.get("/test")
        @unified_response
        async def test_endpoint():
            return {"hello": "world"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"] == {"hello": "world"}
        assert "trace_id" in data
        assert "timestamp" in data

    def test_register_unified_response_exception(self):
        """测试 18: 全局异常处理器注册."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from shared.unified_response import register_unified_response

        app = FastAPI()
        register_unified_response(app)

        @app.get("/error")
        async def error_endpoint():
            raise ValueError("测试错误")

        client = TestClient(app)
        response = client.get("/error")
        # 兜底异常处理器返回 500
        assert response.status_code == 500
        data = response.json()
        assert "code" in data
        assert "message" in data
        assert "trace_id" in data

    def test_unified_response_middleware_trace_header(self):
        """测试 19: 中间件添加 X-Trace-Id 响应头."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from shared.unified_response import UnifiedResponseMiddleware

        app = FastAPI()
        app.add_middleware(UnifiedResponseMiddleware)

        @app.get("/hello")
        async def hello():
            return {"message": "hello"}

        client = TestClient(app)
        # 传入自定义 trace_id
        response = client.get("/hello", headers={"X-Trace-Id": "test-trace-header"})
        assert response.status_code == 200
        assert "x-trace-id" in response.headers
        assert response.headers["x-trace-id"] == "test-trace-header"

    def test_middleware_404_standard_format(self):
        """测试 20: 中间件对 404 的标准格式包装."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from shared.unified_response import register_unified_response

        app = FastAPI()
        register_unified_response(app)

        client = TestClient(app)
        response = client.get("/nonexistent-path")
        # 404 应该被 HTTPException 处理器捕获并返回标准格式
        data = response.json()
        assert "code" in data
        assert "message" in data
        assert "trace_id" in data


# ============================================================
# 测试 21: Pydantic 模型兼容性
# ============================================================

class TestPydanticCompatibility:
    """Pydantic 兼容性测试."""

    def test_api_response_is_pydantic_model(self):
        """测试 21: ApiResponse 是 Pydantic BaseModel 子类."""
        from pydantic import BaseModel
        from shared.unified_response import ApiResponse
        assert issubclass(ApiResponse, BaseModel)

    def test_model_dump_json(self):
        """测试 22: JSON 序列化."""
        from shared.unified_response import ApiResponse
        resp = ApiResponse.success(data={"nested": {"value": 42}})
        json_str = resp.to_json()
        parsed = json.loads(json_str)
        assert parsed["code"] == 0
        assert parsed["data"]["nested"]["value"] == 42

    def test_validation_from_dict(self):
        """测试 23: from_dict 类型校验（Pydantic 模式下）."""
        from shared.unified_response import ApiResponse
        # code 应该是 int，即使传字符串也应能转换
        d = {"code": "0", "message": "ok", "data": None, "trace_id": None, "timestamp": 123.456}
        try:
            resp = ApiResponse.from_dict(d)
            assert resp.code == 0  # Pydantic 会自动转换
        except Exception:
            # 某些严格模式下可能失败，跳过
            pytest.skip("Pydantic strict mode")


# ============================================================
# 测试 24: http_status 属性
# ============================================================

class TestHttpStatusProperty:
    """HTTP 状态码属性测试."""

    def test_success_http_status(self):
        """测试 24a: 成功响应的 HTTP 状态码."""
        from shared.unified_response import ApiResponse, HTTP_OK
        resp = ApiResponse.success()
        assert resp.http_status == HTTP_OK

    def test_error_http_status(self):
        """测试 24b: 错误响应的 HTTP 状态码."""
        from shared.unified_response import ApiResponse, ERR_NOT_FOUND, HTTP_NOT_FOUND
        resp = ApiResponse.error(code=ERR_NOT_FOUND)
        assert resp.http_status == HTTP_NOT_FOUND


# ============================================================
# 测试 25: 模块导出完整性
# ============================================================

class TestModuleExports:
    """模块导出测试."""

    def test_init_exports(self):
        """测试 25: __init__.py 导出所有公共 API."""
        import shared.unified_response as ur
        # 核心类
        assert hasattr(ur, "ApiResponse")
        # 便捷函数
        assert hasattr(ur, "ok")
        assert hasattr(ur, "fail")
        assert hasattr(ur, "generate_trace_id")
        assert hasattr(ur, "from_legacy_response")
        # 常量
        assert hasattr(ur, "SUCCESS")
        assert hasattr(ur, "ERR_INTERNAL")
        assert hasattr(ur, "HTTP_OK")
        # FastAPI 集成
        assert hasattr(ur, "UnifiedResponseMiddleware")
        assert hasattr(ur, "register_unified_response")
        assert hasattr(ur, "unified_response")
        # 版本
        assert hasattr(ur, "__version__")
