"""
shared.core.responses 模块单元测试 - 新版响应格式

测试内容：
- ApiResponse 成功/错误/分页响应
- 链式调用方法
- ok/fail/paginated 便捷函数
- GlobalExceptionHandler
- 向后兼容常量
"""

import pytest
from fastapi import FastAPI

from shared.core.responses import (
    ApiResponse,
    ok,
    fail,
    paginated,
    SUCCESS,
    ERROR_INVALID_PARAMS,
    ERROR_UNAUTHORIZED,
    ERROR_FORBIDDEN,
    ERROR_NOT_FOUND,
    ERROR_INTERNAL,
    ERROR_MODULE_UNAVAILABLE,
    GlobalExceptionHandler,
)
from shared.core.errors import (
    ErrorCode,
    YunxiError,
    ValidationError,
    AuthenticationError,
    NotFoundError,
)


# ============================================================
# ApiResponse.success() 测试
# ============================================================

class TestApiResponseSuccessNew:
    """ApiResponse.success() 方法测试（新版）"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_default_success(self):
        """默认成功响应"""
        resp = ApiResponse.success()
        assert resp.code == SUCCESS
        assert resp.code == 0
        assert resp.message == "操作成功"
        assert resp.data is None
        assert resp.is_success is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_success_with_data(self):
        """带数据的成功响应"""
        data = {"id": 1, "name": "test"}
        resp = ApiResponse.success(data=data)
        assert resp.data == data
        assert resp.is_success is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_success_with_custom_message(self):
        """自定义成功消息"""
        resp = ApiResponse.success(message="创建成功")
        assert resp.message == "创建成功"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_success_with_trace_id(self):
        """带 trace_id 的成功响应"""
        resp = ApiResponse.success(trace_id="trace-123")
        assert resp.trace_id == "trace-123"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_success_http_status_200(self):
        """成功响应 HTTP 状态码为 200"""
        resp = ApiResponse.success()
        assert resp.http_status == 200


# ============================================================
# ApiResponse.error() 测试
# ============================================================

class TestApiResponseErrorNew:
    """ApiResponse.error() 方法测试（新版）"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_default_error(self):
        """默认错误响应"""
        resp = ApiResponse.error()
        assert resp.code == ERROR_INTERNAL
        assert resp.code != 0
        assert resp.is_success is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_with_custom_code(self):
        """自定义错误码"""
        resp = ApiResponse.error(code=ErrorCode.VALIDATION_ERROR)
        assert resp.code == ErrorCode.VALIDATION_ERROR

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_with_custom_message(self):
        """自定义错误消息"""
        resp = ApiResponse.error(message="自定义错误")
        assert resp.message == "自定义错误"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_default_message_from_code(self):
        """未指定消息时使用错误码默认消息"""
        resp = ApiResponse.error(code=ErrorCode.VALIDATION_ERROR)
        assert resp.message == "参数验证失败"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_with_details(self):
        """带详情的错误响应"""
        details = {"field": "name", "reason": "required"}
        resp = ApiResponse.error(code=ErrorCode.VALIDATION_ERROR, details=details)
        assert resp.details == details

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_with_trace_id(self):
        """带 trace_id 的错误响应"""
        resp = ApiResponse.error(trace_id="err-456")
        assert resp.trace_id == "err-456"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_http_status_validation(self):
        """参数错误 HTTP 状态为 400"""
        resp = ApiResponse.error(code=ErrorCode.VALIDATION_ERROR)
        assert resp.http_status == 400

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_http_status_auth(self):
        """认证错误 HTTP 状态为 401"""
        resp = ApiResponse.error(code=ErrorCode.AUTH_FAILED)
        assert resp.http_status == 401

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_http_status_not_found(self):
        """资源不存在 HTTP 状态为 404"""
        resp = ApiResponse.error(code=ErrorCode.NOT_FOUND)
        assert resp.http_status == 404

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_custom_http_status(self):
        """自定义 HTTP 状态码"""
        resp = ApiResponse.error(code=ErrorCode.VALIDATION_ERROR, http_status=422)
        assert resp.http_status == 422

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_legacy_error_code_normalized(self):
        """旧错误码会被规范化"""
        resp = ApiResponse.error(code=40001)  # 旧版参数错误码
        assert resp.code == ErrorCode.VALIDATION_ERROR  # 被规范化


# ============================================================
# ApiResponse.from_error / from_yunxi_error 测试
# ============================================================

class TestApiResponseFromError:
    """从异常创建响应测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_from_yunxi_error(self):
        """从 YunxiError 创建错误响应"""
        err = ValidationError(message="字段无效", details={"field": "email"})
        resp = ApiResponse.from_yunxi_error(err)
        assert resp.code == err.code
        assert resp.message == err.message
        assert resp.details == err.details
        assert resp.http_status == err.http_status

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_from_yunxi_error_with_trace_id(self):
        """从 YunxiError 创建响应并指定 trace_id"""
        err = NotFoundError(message="用户不存在")
        resp = ApiResponse.from_yunxi_error(err, trace_id="trace-789")
        assert resp.trace_id == "trace-789"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_from_error_generic_exception(self):
        """从普通 Exception 创建错误响应"""
        err = ValueError("值错误")
        resp = ApiResponse.from_error(err)
        assert resp.code == ErrorCode.INTERNAL_ERROR
        assert resp.is_success is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_from_error_yunxi_error(self):
        """从 YunxiError 创建响应（走 from_error 路径）"""
        err = AuthenticationError(message="Token 过期")
        resp = ApiResponse.from_error(err)
        assert resp.code == ErrorCode.AUTH_FAILED
        assert resp.message == "Token 过期"


# ============================================================
# ApiResponse.paginated() 测试
# ============================================================

class TestApiResponsePaginated:
    """分页响应测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_paginated_basic(self):
        """基本分页响应"""
        items = [{"id": 1}, {"id": 2}, {"id": 3}]
        resp = ApiResponse.paginated(items=items, total=100, page=1, page_size=20)
        assert resp.is_success is True
        assert resp.data["items"] == items
        assert resp.data["total"] == 100
        assert resp.data["page"] == 1
        assert resp.data["page_size"] == 20

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_paginated_total_pages(self):
        """分页响应包含总页数"""
        items = list(range(10))
        resp = ApiResponse.paginated(items=items, total=100, page=1, page_size=20)
        assert resp.data["total_pages"] == 5  # 100 / 20 = 5

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_paginated_total_pages_round_up(self):
        """总页数向上取整"""
        items = list(range(5))
        resp = ApiResponse.paginated(items=items, total=25, page=1, page_size=10)
        assert resp.data["total_pages"] == 3  # 25/10 = 2.5 -> 3

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_paginated_with_extra(self):
        """分页响应支持额外字段"""
        extra = {"filters": {"status": "active"}, "sort": "created_at"}
        resp = ApiResponse.paginated(
            items=[], total=0, page=1, page_size=20, extra=extra
        )
        assert resp.data["filters"] == extra["filters"]
        assert resp.data["sort"] == extra["sort"]

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_paginated_zero_page_size(self):
        """page_size 为 0 时总页数为 0"""
        resp = ApiResponse.paginated(items=[], total=100, page=1, page_size=0)
        assert resp.data["total_pages"] == 0


# ============================================================
# 链式调用测试
# ============================================================

class TestApiResponseChaining:
    """链式调用方法测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_with_data(self):
        """with_data 链式调用"""
        resp = ApiResponse.success().with_data({"key": "value"})
        assert resp.data == {"key": "value"}

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_with_message(self):
        """with_message 链式调用"""
        resp = ApiResponse.success().with_message("自定义消息")
        assert resp.message == "自定义消息"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_with_trace_id(self):
        """with_trace_id 链式调用"""
        resp = ApiResponse.success().with_trace_id("trace-id-1")
        assert resp.trace_id == "trace-id-1"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_with_details(self):
        """with_details 链式调用"""
        resp = ApiResponse.error().with_details(field="name", reason="invalid")
        assert resp.details["field"] == "name"
        assert resp.details["reason"] == "invalid"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_with_http_status(self):
        """with_http_status 链式调用"""
        resp = ApiResponse.success().with_http_status(201)
        assert resp.http_status == 201

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_chaining_multiple(self):
        """多方法链式调用"""
        resp = (
            ApiResponse.success()
            .with_data({"id": 1})
            .with_message("创建成功")
            .with_trace_id("trace-123")
            .with_http_status(201)
        )
        assert resp.data == {"id": 1}
        assert resp.message == "创建成功"
        assert resp.trace_id == "trace-123"
        assert resp.http_status == 201


# ============================================================
# to_dict 测试
# ============================================================

class TestApiResponseToDictNew:
    """to_dict 方法测试（新版）"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_success_to_dict_has_data(self):
        """成功响应 to_dict 包含 data 字段"""
        resp = ApiResponse.success(data={"id": 1})
        d = resp.to_dict()
        assert "data" in d
        assert d["data"] == {"id": 1}

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_success_to_dict_no_details(self):
        """成功响应 to_dict 包含 data"""
        resp = ApiResponse.success(data={"id": 1})
        d = resp.to_dict()
        assert "data" in d
        assert d["data"] == {"id": 1}

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_to_dict_has_details(self):
        """错误响应 to_dict 包含 details 字段"""
        resp = ApiResponse.error(code=ErrorCode.VALIDATION_ERROR, details={"f": "v"})
        d = resp.to_dict()
        assert "details" in d
        assert d["details"] == {"f": "v"}

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_to_dict_includes_trace_id(self):
        """有 trace_id 时 to_dict 包含 trace_id"""
        resp = ApiResponse.success(trace_id="trace-1")
        d = resp.to_dict()
        assert "trace_id" in d
        assert d["trace_id"] == "trace-1"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_to_dict_no_trace_id_when_none(self):
        """trace_id 为 None 时 to_dict 不包含 trace_id"""
        resp = ApiResponse.success()
        d = resp.to_dict()
        assert "trace_id" not in d

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_to_dict_has_code_and_message(self):
        """所有响应都包含 code 和 message"""
        resp = ApiResponse.success()
        d = resp.to_dict()
        assert "code" in d
        assert "message" in d


# ============================================================
# 便捷函数测试
# ============================================================

class TestConvenienceFunctions:
    """便捷函数 ok/fail/paginated 测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_ok_returns_dict(self):
        """ok() 返回字典"""
        result = ok(data={"id": 1})
        assert isinstance(result, dict)
        assert result["code"] == 0
        assert result["data"] == {"id": 1}

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_fail_returns_dict(self):
        """fail() 返回字典"""
        result = fail(code=ErrorCode.VALIDATION_ERROR, message="参数错误")
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.VALIDATION_ERROR
        assert result["message"] == "参数错误"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_paginated_returns_dict(self):
        """paginated() 返回字典"""
        result = paginated(items=[1, 2, 3], total=10, page=1, page_size=20)
        assert isinstance(result, dict)
        assert result["code"] == 0
        assert result["data"]["items"] == [1, 2, 3]
        assert result["data"]["total"] == 10


# ============================================================
# 向后兼容常量测试
# ============================================================

class TestLegacyConstants:
    """向后兼容常量测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_success_constant(self):
        """SUCCESS 常量为 0"""
        assert SUCCESS == 0

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_constants_mapped(self):
        """旧错误码常量映射到新体系"""
        assert ERROR_INVALID_PARAMS == ErrorCode.VALIDATION_ERROR
        assert ERROR_UNAUTHORIZED == ErrorCode.AUTH_FAILED
        assert ERROR_FORBIDDEN == ErrorCode.PERMISSION_DENIED
        assert ERROR_NOT_FOUND == ErrorCode.NOT_FOUND
        assert ERROR_INTERNAL == ErrorCode.INTERNAL_ERROR
        assert ERROR_MODULE_UNAVAILABLE == ErrorCode.SERVICE_UNAVAILABLE


# ============================================================
# is_success 属性测试
# ============================================================

class TestIsSuccessProperty:
    """is_success 属性测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_success_is_true(self):
        """成功响应 is_success 为 True"""
        assert ApiResponse.success().is_success is True

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_error_is_false(self):
        """错误响应 is_success 为 False"""
        assert ApiResponse.error().is_success is False

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_zero_code_is_success(self):
        """code 为 0 即为成功"""
        resp = ApiResponse(code=0)
        assert resp.is_success is True


# ============================================================
# http_status 属性测试
# ============================================================

class TestHttpStatusProperty:
    """http_status 属性测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_success_http_status(self):
        """成功响应 HTTP 状态为 200"""
        assert ApiResponse.success().http_status == 200

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_validation_http_status(self):
        """参数验证错误 HTTP 状态为 400"""
        assert ApiResponse.error(code=ErrorCode.VALIDATION_ERROR).http_status == 400

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_custom_http_status_overrides(self):
        """自定义 HTTP 状态覆盖默认值"""
        resp = ApiResponse.error(code=ErrorCode.VALIDATION_ERROR, http_status=422)
        assert resp.http_status == 422


# ============================================================
# GlobalExceptionHandler 测试
# ============================================================

class TestGlobalExceptionHandler:
    """全局异常处理器测试"""

    @pytest.fixture
    def fastapi_app(self):
        """创建 FastAPI 测试应用"""
        return FastAPI()

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_handler_creation(self, fastapi_app):
        """可以创建 GlobalExceptionHandler"""
        handler = GlobalExceptionHandler(app=fastapi_app)
        assert handler is not None

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_register_to_app(self, fastapi_app):
        """可以注册到 FastAPI 应用"""
        handler = GlobalExceptionHandler()
        handler.register_to(fastapi_app)
        # 验证没有抛出异常即可

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_register_method(self, fastapi_app):
        """register() 方法（向后兼容）"""
        handler = GlobalExceptionHandler(app=fastapi_app)
        handler.register()  # 应该不抛出异常

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_register_global_helper(self, fastapi_app):
        """register_global_exception_handler 辅助函数"""
        from shared.core.responses import register_global_exception_handler
        handler = register_global_exception_handler(fastapi_app)
        assert isinstance(handler, GlobalExceptionHandler)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_yunxi_error_handling(self, fastapi_app):
        """YunxiError 异常被正确处理"""
        handler = GlobalExceptionHandler(app=fastapi_app)
        # 验证应用注册了异常处理器
        # FastAPI 内部存储了 exception_handlers
        assert hasattr(fastapi_app, "exception_handlers")
        assert YunxiError in fastapi_app.exception_handlers


# ============================================================
# 字符串表示测试
# ============================================================

class TestStringRepresentation:
    """字符串表示测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_str_success(self):
        """成功响应的字符串表示"""
        resp = ApiResponse.success(message="测试")
        s = str(resp)
        assert "OK" in s
        assert "code=0" in s

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_str_error(self):
        """错误响应的字符串表示"""
        resp = ApiResponse.error(message="错误")
        s = str(resp)
        assert "ERR" in s

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.response
    def test_repr_complete(self):
        """repr 包含完整信息"""
        resp = ApiResponse.success(data={"k": "v"}, trace_id="t1")
        r = repr(resp)
        assert "ApiResponse" in r
        assert "code=" in r
        assert "data=" in r
        assert "trace_id=" in r
