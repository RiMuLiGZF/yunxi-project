"""P1-6: 错误码体系测试覆盖扩展"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from m6_hardware.models.errors import ErrorCode, M6Exception


class TestErrorCodeUniqueness:
    """错误码唯一性测试"""

    def test_error_code_values_unique(self):
        """所有 ErrorCode 枚举值唯一"""
        values = [e.value for e in ErrorCode]
        assert len(values) == len(set(values)), "存在重复的错误码值"

    def test_error_code_members(self):
        """错误码包含预期成员"""
        assert hasattr(ErrorCode, "SUCCESS")
        assert hasattr(ErrorCode, "DEVICE_NOT_FOUND")
        assert hasattr(ErrorCode, "SENSOR_NOT_FOUND")
        assert hasattr(ErrorCode, "SSE_TOKEN_INVALID")


class TestM6Exception:
    """M6Exception 测试"""

    def test_exception_creation(self):
        """M6Exception 创建和属性"""
        exc = M6Exception(ErrorCode.DEVICE_NOT_FOUND, "设备未找到")
        assert exc.code == ErrorCode.DEVICE_NOT_FOUND
        assert exc.message == "设备未找到"
        assert exc.http_status == 404
        assert exc.details == {}

    def test_exception_with_details(self):
        """M6Exception 支持 details"""
        exc = M6Exception(
            ErrorCode.BAD_REQUEST,
            "参数错误",
            details={"field": "device_id", "reason": "missing"},
        )
        assert exc.details["field"] == "device_id"

    def test_exception_custom_http_status(self):
        """M6Exception 支持自定义 HTTP 状态码"""
        exc = M6Exception(ErrorCode.INTERNAL_ERROR, "错误", http_status=503)
        assert exc.http_status == 503

    def test_exception_str(self):
        """M6Exception 可被 str()"""
        exc = M6Exception(ErrorCode.SUCCESS, "成功")
        assert str(exc) == "成功"

    def test_exception_is_exception(self):
        """M6Exception 是 Exception 子类"""
        exc = M6Exception(ErrorCode.NOT_FOUND, "未找到")
        assert isinstance(exc, Exception)


class TestM6ExceptionToJsonResponse:
    """JSONResponse 测试"""

    def test_to_json_response_status_code(self):
        """to_json_response 返回正确的状态码"""
        exc = M6Exception(ErrorCode.UNAUTHORIZED, "未授权")
        response = exc.to_json_response()
        assert response.status_code == 401

    def test_to_json_response_content(self):
        """to_json_response 返回正确的内容"""
        exc = M6Exception(
            ErrorCode.DEVICE_OFFLINE,
            "设备离线",
            details={"device_id": "d1"},
        )
        response = exc.to_json_response()
        body = response.body.decode("utf-8")
        import json
        content = json.loads(body)
        assert content["code"] == ErrorCode.DEVICE_OFFLINE.value
        assert content["message"] == "设备离线"
        assert content["details"]["device_id"] == "d1"

    def test_to_dict(self):
        """to_dict 返回标准错误字典"""
        exc = M6Exception(ErrorCode.SENSOR_DATA_INVALID, "数据无效")
        d = exc.to_dict()
        assert d["code"] == ErrorCode.SENSOR_DATA_INVALID.value
        assert d["message"] == "数据无效"
        assert "details" in d


class TestErrorCodeCategories:
    """错误码分类测试"""

    def test_general_errors(self):
        """通用 HTTP 语义错误 0xx"""
        assert ErrorCode.BAD_REQUEST.value == 400
        assert ErrorCode.UNAUTHORIZED.value == 401
        assert ErrorCode.FORBIDDEN.value == 403
        assert ErrorCode.NOT_FOUND.value == 404
        assert ErrorCode.INTERNAL_ERROR.value == 500

    def test_device_errors(self):
        """设备域错误 1xx"""
        assert ErrorCode.DEVICE_NOT_FOUND.value == 100
        assert ErrorCode.DEVICE_OFFLINE.value == 101
        assert ErrorCode.DEVICE_ALREADY_PAIRED.value == 102
        assert ErrorCode.DEVICE_NOT_PAIRED.value == 103
        assert ErrorCode.ACTION_NOT_SUPPORTED.value == 104
        assert ErrorCode.ACTION_EXECUTION_ERROR.value == 105

    def test_sensor_errors(self):
        """传感器域错误 2xx"""
        assert ErrorCode.SENSOR_NOT_FOUND.value == 200
        assert ErrorCode.SENSOR_DATA_INVALID.value == 201

    def test_sse_errors(self):
        """SSE 实时推送域错误 3xx"""
        assert ErrorCode.SSE_TOKEN_INVALID.value == 300
        assert ErrorCode.SSE_TOKEN_EXPIRED.value == 301
        assert ErrorCode.SSE_LIMIT_EXCEEDED.value == 302

    def test_http_status_inference(self):
        """HTTP 状态码推断正确"""
        assert M6Exception._infer_http_status(ErrorCode.SUCCESS) == 200
        assert M6Exception._infer_http_status(ErrorCode.BAD_REQUEST) == 400
        assert M6Exception._infer_http_status(ErrorCode.UNAUTHORIZED) == 401
        assert M6Exception._infer_http_status(ErrorCode.FORBIDDEN) == 403
        assert M6Exception._infer_http_status(ErrorCode.NOT_FOUND) == 404
        assert M6Exception._infer_http_status(ErrorCode.DEVICE_NOT_FOUND) == 404
        assert M6Exception._infer_http_status(ErrorCode.DEVICE_OFFLINE) == 409
        assert M6Exception._infer_http_status(ErrorCode.SSE_LIMIT_EXCEEDED) == 409
        assert M6Exception._infer_http_status(ErrorCode.INTERNAL_ERROR) == 500


class TestErrorCodeIntEnum:
    """IntEnum 特性测试"""

    def test_error_code_is_int(self):
        """ErrorCode 成员可当作 int 使用"""
        assert isinstance(ErrorCode.BAD_REQUEST, int)
        assert ErrorCode.BAD_REQUEST + 1 == 401

    def test_error_code_comparison(self):
        """ErrorCode 成员可比较"""
        assert ErrorCode.BAD_REQUEST < ErrorCode.INTERNAL_ERROR
        assert ErrorCode.DEVICE_NOT_FOUND < ErrorCode.SENSOR_NOT_FOUND
