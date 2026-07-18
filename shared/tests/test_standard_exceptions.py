"""
标准异常类型测试
================

测试 shared.core.errors 中的所有标准异常类型，
验证创建、属性、继承关系、错误码、HTTP 状态码映射等。
"""

import sys
import os
from pathlib import Path

import pytest

# 将项目根目录加入 path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.core.errors import (
    # 基类
    YunxiError,
    # 常用异常
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    BusinessError,
    SystemError,
    ConfigError,
    ServiceUnavailableError,
    TimeoutError,
    YunxiTimeoutError,
    RateLimitError,
    ThirdPartyError,
    DependencyError,
    DataError,
    ModuleNotFoundError,
    ModuleCallError,
    # 工具
    ErrorCode,
    ErrorCategory,
    ModuleCode,
    build_error_code,
    parse_error_code,
    get_http_status,
    get_default_message,
    error_to_dict,
    from_exception,
    CATEGORY_HTTP_STATUS,
)


# ============================================================
# 测试：异常创建与基本属性
# ============================================================

class TestYunxiErrorBase:
    """测试 YunxiError 基类"""

    def test_create_default(self):
        """测试默认创建 YunxiError"""
        err = YunxiError()
        assert err.code == ErrorCode.INTERNAL_ERROR
        assert err.message == "服务器内部错误"
        assert err.details == {}
        assert err.http_status == 500

    def test_create_with_message(self):
        """测试带自定义消息"""
        err = YunxiError(message="自定义错误")
        assert err.message == "自定义错误"

    def test_create_with_code(self):
        """测试带自定义错误码"""
        err = YunxiError(code=ErrorCode.NOT_FOUND)
        assert err.code == ErrorCode.NOT_FOUND
        assert err.http_status == 404

    def test_create_with_details(self):
        """测试带详情"""
        err = YunxiError(details={"user_id": 123, "reason": "test"})
        assert err.details["user_id"] == 123
        assert err.details["reason"] == "test"

    def test_str_format(self):
        """测试 __str__ 格式"""
        err = YunxiError(message="测试错误", code=ErrorCode.NOT_FOUND)
        s = str(err)
        assert "测试错误" in s
        assert f"{ErrorCode.NOT_FOUND:06d}" in s

    def test_repr_format(self):
        """测试 __repr__ 格式"""
        err = YunxiError(message="测试", code=ErrorCode.VALIDATION_ERROR)
        r = repr(err)
        assert "YunxiError" in r
        assert "code=" in r
        assert "message=" in r

    def test_to_dict(self):
        """测试 to_dict 方法"""
        err = YunxiError(message="测试", code=ErrorCode.NOT_FOUND, details={"key": "val"})
        d = err.to_dict()
        assert d["code"] == ErrorCode.NOT_FOUND
        assert d["message"] == "测试"
        assert d["details"]["key"] == "val"

    def test_is_exception_subclass(self):
        """测试 YunxiError 是 Exception 的子类"""
        assert issubclass(YunxiError, Exception)
        err = YunxiError()
        assert isinstance(err, Exception)


# ============================================================
# 测试：各种标准异常类型
# ============================================================

class TestValidationError:
    """测试 ValidationError"""

    def test_default_code_and_status(self):
        err = ValidationError()
        assert err.code == ErrorCode.VALIDATION_ERROR
        assert err.http_status == 400
        assert "参数验证失败" in err.message

    def test_inheritance(self):
        err = ValidationError()
        assert isinstance(err, YunxiError)
        assert isinstance(err, Exception)


class TestAuthenticationError:
    """测试 AuthenticationError"""

    def test_default_code_and_status(self):
        err = AuthenticationError()
        assert err.code == ErrorCode.AUTH_FAILED
        assert err.http_status == 401
        assert "认证失败" in err.message

    def test_inheritance(self):
        err = AuthenticationError()
        assert isinstance(err, YunxiError)


class TestAuthorizationError:
    """测试 AuthorizationError"""

    def test_default_code_and_status(self):
        err = AuthorizationError()
        assert err.code == ErrorCode.PERMISSION_DENIED
        assert err.http_status == 403
        assert "无访问权限" in err.message


class TestNotFoundError:
    """测试 NotFoundError"""

    def test_default_code_and_status(self):
        err = NotFoundError()
        assert err.code == ErrorCode.NOT_FOUND
        assert err.http_status == 404
        assert "资源不存在" in err.message


class TestBusinessError:
    """测试 BusinessError"""

    def test_default_code_and_status(self):
        err = BusinessError()
        assert err.code == ErrorCode.BUSINESS_ERROR
        assert err.http_status == 409


class TestSystemError:
    """测试 SystemError"""

    def test_default_code_and_status(self):
        err = SystemError()
        assert err.code == ErrorCode.INTERNAL_ERROR
        assert err.http_status == 500


class TestConfigError:
    """测试 ConfigError"""

    def test_default_code_and_status(self):
        err = ConfigError()
        assert err.code == ErrorCode.CONFIG_ERROR
        assert err.http_status == 500
        assert "配置错误" in err.message


class TestServiceUnavailableError:
    """测试 ServiceUnavailableError"""

    def test_default_code_and_status(self):
        err = ServiceUnavailableError()
        assert err.code == ErrorCode.SERVICE_UNAVAILABLE
        assert err.http_status == 503
        assert "服务暂不可用" in err.message

    def test_retry_after(self):
        """测试 retry_after 参数"""
        err = ServiceUnavailableError(retry_after=30)
        assert err.details.get("retry_after") == 30


class TestTimeoutError:
    """测试 TimeoutError（自定义）"""

    def test_default_code_and_status(self):
        err = TimeoutError()
        assert err.code == ErrorCode.TIMEOUT
        assert err.http_status == 504
        assert "超时" in err.message

    def test_timeout_seconds_param(self):
        """测试 timeout_seconds 参数"""
        err = TimeoutError(timeout_seconds=30.0)
        assert err.details.get("timeout_seconds") == 30.0

    def test_alias_yunxi_timeout(self):
        """测试 YunxiTimeoutError 别名"""
        assert YunxiTimeoutError is TimeoutError

    def test_inheritance(self):
        err = TimeoutError()
        assert isinstance(err, YunxiError)


class TestRateLimitError:
    """测试 RateLimitError"""

    def test_default_code_and_status(self):
        err = RateLimitError()
        assert err.code == ErrorCode.RATE_LIMITED
        assert err.http_status == 429
        assert "频率" in err.message or "超限" in err.message


class TestThirdPartyError:
    """测试 ThirdPartyError"""

    def test_default_code_and_status(self):
        err = ThirdPartyError()
        assert err.code == ErrorCode.THIRD_PARTY_ERROR
        assert err.http_status == 502


class TestDependencyError:
    """测试 DependencyError"""

    def test_default_code_and_status(self):
        err = DependencyError()
        assert err.code == ErrorCode.DEPENDENCY_ERROR
        assert err.http_status == 502
        assert "依赖" in err.message

    def test_dependency_param(self):
        """测试 dependency 参数"""
        err = DependencyError(dependency="redis")
        assert err.details.get("dependency") == "redis"


class TestDataError:
    """测试 DataError"""

    def test_default_code_and_status(self):
        err = DataError()
        assert err.code == ErrorCode.DATA_ERROR
        assert err.http_status == 409


class TestModuleNotFoundError:
    """测试 ModuleNotFoundError"""

    def test_default_code_and_status(self):
        err = ModuleNotFoundError()
        assert err.code == ErrorCode.MODULE_NOT_FOUND
        assert err.http_status == 404
        assert "模块" in err.message


class TestModuleCallError:
    """测试 ModuleCallError"""

    def test_default_code_and_status(self):
        err = ModuleCallError()
        assert err.code == ErrorCode.MODULE_CALL_FAILED
        assert err.http_status == 502


# ============================================================
# 测试：继承关系
# ============================================================

class TestInheritance:
    """测试异常继承关系"""

    @pytest.mark.parametrize("exc_cls", [
        ValidationError,
        AuthenticationError,
        AuthorizationError,
        NotFoundError,
        BusinessError,
        SystemError,
        ConfigError,
        ServiceUnavailableError,
        TimeoutError,
        RateLimitError,
        ThirdPartyError,
        DependencyError,
        DataError,
        ModuleNotFoundError,
        ModuleCallError,
    ])
    def test_all_standard_exceptions_inherit_yunxi(self, exc_cls):
        """测试所有标准异常都继承自 YunxiError"""
        assert issubclass(exc_cls, YunxiError)
        err = exc_cls()
        assert isinstance(err, YunxiError)
        assert isinstance(err, Exception)

    def test_module_not_found_is_not_found(self):
        """测试 ModuleNotFoundError 可以作为 NotFoundError 捕获吗？
        注意：当前设计中 ModuleNotFoundError 不继承 NotFoundError，
        但都继承自 YunxiError，code 不同。"""
        err = ModuleNotFoundError()
        assert isinstance(err, YunxiError)
        # ModuleNotFoundError 不直接继承 NotFoundError（当前设计）
        # 但它们都是 YunxiError 的子类


# ============================================================
# 测试：错误码工具函数
# ============================================================

class TestErrorCodeUtils:
    """测试错误码工具函数"""

    def test_build_error_code(self):
        """测试构建错误码"""
        code = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 1)
        assert code == 80501  # 08 05 01

    def test_build_error_code_system(self):
        """测试系统级错误码"""
        code = build_error_code(ModuleCode.SYSTEM, ErrorCategory.VALIDATION, 1)
        assert code == 101  # 00 01 01

    def test_parse_error_code(self):
        """测试解析错误码"""
        parsed = parse_error_code(80501)
        assert parsed["module"] == 8
        assert parsed["category"] == 5
        assert parsed["seq"] == 1

    def test_parse_error_code_system(self):
        """测试解析系统级错误码"""
        parsed = parse_error_code(101)
        assert parsed["module"] == 0
        assert parsed["category"] == 1
        assert parsed["seq"] == 1

    def test_get_http_status_validation(self):
        """测试获取 HTTP 状态码 - 参数错误"""
        assert get_http_status(ErrorCode.VALIDATION_ERROR) == 400

    def test_get_http_status_not_found(self):
        """测试获取 HTTP 状态码 - 未找到"""
        assert get_http_status(ErrorCode.NOT_FOUND) == 404

    def test_get_http_status_internal(self):
        """测试获取 HTTP 状态码 - 内部错误"""
        assert get_http_status(ErrorCode.INTERNAL_ERROR) == 500

    def test_get_http_status_rate_limit(self):
        """测试获取 HTTP 状态码 - 限流"""
        assert get_http_status(ErrorCode.RATE_LIMITED) == 429

    def test_get_default_message(self):
        """测试获取默认消息"""
        msg = get_default_message(ErrorCode.NOT_FOUND)
        assert "不存在" in msg

    def test_get_default_message_unknown(self):
        """测试未知错误码的默认消息"""
        msg = get_default_message(999999)
        assert "未知" in msg


# ============================================================
# 测试：异常转换工具
# ============================================================

class TestErrorConversion:
    """测试异常转换工具函数"""

    def test_error_to_dict_yunxi(self):
        """测试 YunxiError 转字典"""
        err = NotFoundError(message="测试不存在", details={"id": "123"})
        d = error_to_dict(err)
        assert d["code"] == ErrorCode.NOT_FOUND
        assert d["message"] == "测试不存在"
        assert d["details"]["id"] == "123"

    def test_error_to_dict_regular_exception(self):
        """测试普通 Exception 转字典"""
        err = ValueError("普通错误")
        d = error_to_dict(err)
        assert d["code"] == ErrorCode.INTERNAL_ERROR
        assert "内部错误" in d["message"]
        assert d["details"]["error_type"] == "ValueError"

    def test_from_exception_yunxi(self):
        """测试从 YunxiError 转换（原样返回）"""
        err = ValidationError(message="测试")
        result = from_exception(err)
        assert result is err
        assert isinstance(result, YunxiError)

    def test_from_exception_regular(self):
        """测试从普通 Exception 转换"""
        err = ValueError("普通错误")
        result = from_exception(err)
        assert isinstance(result, YunxiError)
        assert "普通错误" in result.message
        assert result.details.get("original_type") == "ValueError"

    def test_from_exception_default_code(self):
        """测试自定义默认错误码"""
        err = RuntimeError("测试")
        result = from_exception(err, default_code=ErrorCode.DEPENDENCY_ERROR)
        assert result.code == ErrorCode.DEPENDENCY_ERROR


# ============================================================
# 测试：HTTP 状态码映射完整性
# ============================================================

class TestHttpStatusMapping:
    """测试 HTTP 状态码映射完整性"""

    def test_all_categories_have_http_status(self):
        """测试所有错误类别都有 HTTP 状态码映射"""
        for cat in ErrorCategory:
            if cat == ErrorCategory.SUCCESS:
                continue
            assert cat in CATEGORY_HTTP_STATUS
            status = CATEGORY_HTTP_STATUS[cat]
            assert isinstance(status, int)
            assert 400 <= status <= 599  # 都是错误状态码

    def test_http_status_values(self):
        """测试关键 HTTP 状态码值"""
        assert CATEGORY_HTTP_STATUS[ErrorCategory.VALIDATION] == 400
        assert CATEGORY_HTTP_STATUS[ErrorCategory.AUTHENTICATION] == 401
        assert CATEGORY_HTTP_STATUS[ErrorCategory.AUTHORIZATION] == 403
        assert CATEGORY_HTTP_STATUS[ErrorCategory.NOT_FOUND] == 404
        assert CATEGORY_HTTP_STATUS[ErrorCategory.SYSTEM] == 500
        assert CATEGORY_HTTP_STATUS[ErrorCategory.RATE_LIMIT] == 429
