"""
shared.core.errors 模块单元测试 - 新 6 位错误码体系

测试内容：
- 错误码构建与解析
- 错误类别枚举
- 模块编号枚举
- HTTP 状态码映射
- YunxiError 新版异常类
- 错误消息映射
- 旧错误码兼容
- 快捷工厂函数
"""

import pytest

from shared.core.errors import (
    ErrorCategory,
    ModuleCode,
    build_error_code,
    parse_error_code,
    module_error_range,
    ErrorCode,
    ERROR_MESSAGES,
    CATEGORY_HTTP_STATUS,
    get_default_message,
    get_http_status,
    normalize_error_code,
    ERROR_CODE_LEGACY_MAP,
    YunxiError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    BusinessError,
    SystemError,
    ConfigError,
    ModuleNotFoundError,
    ModuleCallError,
    RateLimitError,
    ThirdPartyError,
    DataError,
    error_to_dict,
    from_exception,
    raise_validation,
    raise_not_found,
    raise_auth,
    raise_permission,
    ModuleErrorCode,
)


# ============================================================
# 错误码构建与解析测试
# ============================================================

class TestBuildAndParseErrorCode:
    """错误码构建与解析测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_build_system_validation_error(self):
        """构建系统级参数验证错误码"""
        code = build_error_code(ModuleCode.SYSTEM, ErrorCategory.VALIDATION, 1)
        assert code == 101  # 00 01 01

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_build_m8_business_error(self):
        """构建 M8 业务错误码"""
        code = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 1)
        assert code == 80501  # 08 05 01

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_build_m11_third_party_error(self):
        """构建 M11 第三方错误码"""
        code = build_error_code(ModuleCode.M11, ErrorCategory.THIRD_PARTY, 1)
        assert code == 110701  # 11 07 01

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_build_with_int_params(self):
        """使用整数参数构建错误码"""
        code = build_error_code(8, 5, 3)
        assert code == 80503

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_build_invalid_module_raises(self):
        """模块编号超出范围抛出异常"""
        with pytest.raises(ValueError):
            build_error_code(13, 1, 1)
        with pytest.raises(ValueError):
            build_error_code(-1, 1, 1)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_build_invalid_category_raises(self):
        """错误类别超出范围抛出异常"""
        with pytest.raises(ValueError):
            build_error_code(0, 10, 1)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_build_invalid_seq_raises(self):
        """错误序号超出范围抛出异常"""
        with pytest.raises(ValueError):
            build_error_code(0, 1, 100)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_parse_system_error(self):
        """解析系统级错误码"""
        result = parse_error_code(101)
        assert result["module"] == 0
        assert result["category"] == 1
        assert result["seq"] == 1

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_parse_m8_error(self):
        """解析 M8 错误码"""
        result = parse_error_code(80501)
        assert result["module"] == 8
        assert result["category"] == 5
        assert result["seq"] == 1

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_parse_m11_error(self):
        """解析 M11 错误码"""
        result = parse_error_code(110701)
        assert result["module"] == 11
        assert result["category"] == 7
        assert result["seq"] == 1

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_parse_negative_code(self):
        """解析负数错误码（M11 JSON-RPC 风格）"""
        result = parse_error_code(-101)
        assert result["module"] == 0
        assert result["category"] == 1
        assert result["seq"] == 1

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_build_and_parse_roundtrip(self):
        """构建再解析结果一致"""
        test_cases = [
            (ModuleCode.SYSTEM, ErrorCategory.SUCCESS, 0),
            (ModuleCode.M1, ErrorCategory.AUTHENTICATION, 5),
            (ModuleCode.M12, ErrorCategory.DATA, 99),
        ]
        for module, category, seq in test_cases:
            code = build_error_code(module, category, seq)
            parsed = parse_error_code(code)
            assert parsed["module"] == int(module)
            assert parsed["category"] == int(category)
            assert parsed["seq"] == seq


# ============================================================
# 错误类别枚举测试
# ============================================================

class TestErrorCategory:
    """错误类别枚举测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_all_categories_exist(self):
        """所有错误类别都存在"""
        assert ErrorCategory.SUCCESS == 0
        assert ErrorCategory.VALIDATION == 1
        assert ErrorCategory.AUTHENTICATION == 2
        assert ErrorCategory.AUTHORIZATION == 3
        assert ErrorCategory.NOT_FOUND == 4
        assert ErrorCategory.BUSINESS == 5
        assert ErrorCategory.SYSTEM == 6
        assert ErrorCategory.THIRD_PARTY == 7
        assert ErrorCategory.RATE_LIMIT == 8
        assert ErrorCategory.DATA == 9

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_category_count(self):
        """错误类别数量正确"""
        assert len(ErrorCategory) == 10


# ============================================================
# 模块编号枚举测试
# ============================================================

class TestModuleCode:
    """模块编号枚举测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_system_module(self):
        """系统通用模块编号为 0"""
        assert ModuleCode.SYSTEM == 0

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_m8_module(self):
        """M8 模块编号为 8"""
        assert ModuleCode.M8 == 8

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_m11_module(self):
        """M11 模块编号为 11"""
        assert ModuleCode.M11 == 11

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_module_count(self):
        """模块数量正确（系统 + 12 个模块）"""
        assert len(ModuleCode) == 13


# ============================================================
# HTTP 状态码映射测试
# ============================================================

class TestHttpStatusMapping:
    """HTTP 状态码映射测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_success_maps_to_200(self):
        """成功映射到 200"""
        assert CATEGORY_HTTP_STATUS[ErrorCategory.SUCCESS] == 200

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_validation_maps_to_400(self):
        """参数错误映射到 400"""
        assert CATEGORY_HTTP_STATUS[ErrorCategory.VALIDATION] == 400

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_auth_maps_to_401(self):
        """认证错误映射到 401"""
        assert CATEGORY_HTTP_STATUS[ErrorCategory.AUTHENTICATION] == 401

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_not_found_maps_to_404(self):
        """资源不存在映射到 404"""
        assert CATEGORY_HTTP_STATUS[ErrorCategory.NOT_FOUND] == 404

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_system_maps_to_500(self):
        """系统错误映射到 500"""
        assert CATEGORY_HTTP_STATUS[ErrorCategory.SYSTEM] == 500

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_rate_limit_maps_to_429(self):
        """限流错误映射到 429"""
        assert CATEGORY_HTTP_STATUS[ErrorCategory.RATE_LIMIT] == 429

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_get_http_status_success(self):
        """get_http_status 成功码返回 200"""
        assert get_http_status(0) == 200

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_get_http_status_validation(self):
        """get_http_status 参数错误返回 400"""
        assert get_http_status(ErrorCode.VALIDATION_ERROR) == 400

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_get_http_status_unknown_category(self):
        """未知错误类别返回 500"""
        # 构造一个类别为 99 的错误码
        code = build_error_code(ModuleCode.SYSTEM, 9, 1)  # 9 = DATA
        assert get_http_status(code) == 409  # DATA -> 409


# ============================================================
# 通用错误码常量测试
# ============================================================

class TestErrorCodeConstants:
    """通用错误码常量测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_success_is_zero(self):
        """SUCCESS 错误码为 0"""
        assert ErrorCode.SUCCESS == 0

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_validation_error_code(self):
        """参数验证错误码结构正确"""
        parsed = parse_error_code(ErrorCode.VALIDATION_ERROR)
        assert parsed["module"] == 0
        assert parsed["category"] == 1

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_auth_failed_code(self):
        """认证失败错误码结构正确"""
        parsed = parse_error_code(ErrorCode.AUTH_FAILED)
        assert parsed["module"] == 0
        assert parsed["category"] == 2

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_not_found_code(self):
        """资源不存在错误码结构正确"""
        parsed = parse_error_code(ErrorCode.NOT_FOUND)
        assert parsed["module"] == 0
        assert parsed["category"] == 4

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_internal_error_code(self):
        """内部错误码结构正确"""
        parsed = parse_error_code(ErrorCode.INTERNAL_ERROR)
        assert parsed["module"] == 0
        assert parsed["category"] == 6

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_error_messages_cover_codes(self):
        """ERROR_MESSAGES 覆盖主要错误码"""
        important_codes = [
            ErrorCode.SUCCESS,
            ErrorCode.VALIDATION_ERROR,
            ErrorCode.AUTH_FAILED,
            ErrorCode.PERMISSION_DENIED,
            ErrorCode.NOT_FOUND,
            ErrorCode.INTERNAL_ERROR,
        ]
        for code in important_codes:
            assert code in ERROR_MESSAGES, f"缺少错误码 {code} 的消息"


# ============================================================
# 默认错误消息测试
# ============================================================

class TestDefaultMessage:
    """默认错误消息测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_success_message(self):
        """成功消息正确"""
        assert get_default_message(ErrorCode.SUCCESS) == "操作成功"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_validation_message(self):
        """参数验证错误消息正确"""
        assert get_default_message(ErrorCode.VALIDATION_ERROR) == "参数验证失败"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_unknown_code_returns_default(self):
        """未知错误码返回默认消息"""
        msg = get_default_message(999999)
        assert isinstance(msg, str)
        assert len(msg) > 0


# ============================================================
# YunxiError 异常类测试
# ============================================================

class TestYunxiErrorNew:
    """新版 YunxiError 异常类测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_default_error_is_internal(self):
        """默认错误为内部错误"""
        err = YunxiError()
        assert err.code == ErrorCode.INTERNAL_ERROR
        assert err.http_status == 500

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_custom_message(self):
        """自定义错误消息"""
        err = YunxiError(message="自定义错误")
        assert err.message == "自定义错误"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_default_message_from_code(self):
        """未指定消息时使用默认消息"""
        err = YunxiError(code=ErrorCode.VALIDATION_ERROR)
        assert err.message == "参数验证失败"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_details_default_empty(self):
        """details 默认为空字典"""
        err = YunxiError()
        assert err.details == {}

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_to_dict_structure(self):
        """to_dict 返回结构正确"""
        err = YunxiError(
            message="测试错误",
            code=ErrorCode.VALIDATION_ERROR,
            details={"field": "name"},
        )
        d = err.to_dict()
        assert d["code"] == ErrorCode.VALIDATION_ERROR
        assert d["message"] == "测试错误"
        assert d["details"] == {"field": "name"}

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_str_format(self):
        """__str__ 格式正确（6 位错误码）"""
        err = YunxiError(message="测试", code=ErrorCode.VALIDATION_ERROR)
        s = str(err)
        assert "000101" in s  # 6 位格式
        assert "测试" in s

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_repr_format(self):
        """__repr__ 包含完整信息"""
        err = YunxiError(message="test", code=101)
        r = repr(err)
        assert "YunxiError" in r
        assert "code=" in r
        assert "http_status=" in r


# ============================================================
# 各异常子类测试
# ============================================================

class TestExceptionSubclasses:
    """各异常子类测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_validation_error_status(self):
        """ValidationError HTTP 状态为 400"""
        err = ValidationError()
        assert err.http_status == 400
        assert err.code == ErrorCode.VALIDATION_ERROR

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_authentication_error_status(self):
        """AuthenticationError HTTP 状态为 401"""
        err = AuthenticationError()
        assert err.http_status == 401
        assert err.code == ErrorCode.AUTH_FAILED

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_authorization_error_status(self):
        """AuthorizationError HTTP 状态为 403"""
        err = AuthorizationError()
        assert err.http_status == 403
        assert err.code == ErrorCode.PERMISSION_DENIED

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_not_found_error_status(self):
        """NotFoundError HTTP 状态为 404"""
        err = NotFoundError()
        assert err.http_status == 404
        assert err.code == ErrorCode.NOT_FOUND

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_system_error_status(self):
        """SystemError HTTP 状态为 500"""
        err = SystemError()
        assert err.http_status == 500

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_rate_limit_error_status(self):
        """RateLimitError HTTP 状态为 429"""
        err = RateLimitError()
        assert err.http_status == 429

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_all_subclasses_inherit_yunxi_error(self):
        """所有异常子类都继承自 YunxiError"""
        subclasses = [
            ValidationError, AuthenticationError, AuthorizationError,
            NotFoundError, BusinessError, SystemError, ConfigError,
            ModuleNotFoundError, ModuleCallError, RateLimitError,
            ThirdPartyError, DataError,
        ]
        for cls in subclasses:
            assert issubclass(cls, YunxiError), f"{cls.__name__} 不继承自 YunxiError"


# ============================================================
# error_to_dict 函数测试（新版）
# ============================================================

class TestErrorToDictNew:
    """error_to_dict 函数测试（新版）"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_yunxi_error_conversion(self):
        """YunxiError 转换正确"""
        err = YunxiError(message="测试", code=ErrorCode.VALIDATION_ERROR, details={"k": "v"})
        result = error_to_dict(err)
        assert result["code"] == ErrorCode.VALIDATION_ERROR
        assert result["message"] == "测试"
        assert result["details"] == {"k": "v"}

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_generic_exception_conversion(self):
        """普通 Exception 转换为内部错误"""
        err = ValueError("值错误")
        result = error_to_dict(err)
        assert result["code"] == ErrorCode.INTERNAL_ERROR
        assert "error_type" in result["details"]

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_legacy_code_normalization(self):
        """带有旧版 code 属性的异常会被规范化"""
        class OldStyleError(Exception):
            def __init__(self):
                super().__init__("旧版错误")
                self.code = 40001  # 旧版错误码
                self.message = "旧版消息"
                self.details = {"old": True}

        err = OldStyleError()
        result = error_to_dict(err)
        # 旧的 40001 应该映射到新的 VALIDATION_ERROR
        assert result["code"] == ErrorCode.VALIDATION_ERROR


# ============================================================
# from_exception 函数测试
# ============================================================

class TestFromException:
    """from_exception 函数测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_yunxi_error_passthrough(self):
        """YunxiError 直接返回"""
        original = ValidationError(message="测试")
        result = from_exception(original)
        assert result is original

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_generic_exception_wrapping(self):
        """普通异常包装为 SystemError"""
        err = ValueError("测试错误")
        result = from_exception(err)
        assert isinstance(result, YunxiError)
        assert result.code == ErrorCode.INTERNAL_ERROR
        assert "测试错误" in result.message

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_custom_default_code(self):
        """支持自定义默认错误码"""
        err = RuntimeError("运行时错误")
        result = from_exception(err, default_code=ErrorCode.CONFIG_ERROR)
        assert result.code == ErrorCode.CONFIG_ERROR


# ============================================================
# 快捷工厂函数测试
# ============================================================

class TestRaiseFunctions:
    """快捷工厂函数测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_raise_validation(self):
        """raise_validation 抛出 ValidationError"""
        with pytest.raises(ValidationError) as exc_info:
            raise_validation(message="字段错误", field="username")
        assert exc_info.value.details.get("field") == "username"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_raise_not_found(self):
        """raise_not_found 抛出 NotFoundError"""
        with pytest.raises(NotFoundError) as exc_info:
            raise_not_found(resource="用户", resource_id="123")
        assert "用户" in exc_info.value.message
        assert exc_info.value.details.get("resource") == "用户"
        assert exc_info.value.details.get("id") == "123"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_raise_auth(self):
        """raise_auth 抛出 AuthenticationError"""
        with pytest.raises(AuthenticationError):
            raise_auth(message="Token 无效")

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_raise_permission(self):
        """raise_permission 抛出 AuthorizationError"""
        with pytest.raises(AuthorizationError):
            raise_permission(message="需要管理员权限")


# ============================================================
# 模块错误码范围测试
# ============================================================

class TestModuleErrorRange:
    """模块错误码范围测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_system_module_range(self):
        """系统模块错误码范围"""
        r = module_error_range(ModuleCode.SYSTEM)
        assert r["start"] == 100  # 000100
        assert r["end"] == 999    # 000999

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_m8_module_range(self):
        """M8 模块错误码范围"""
        r = module_error_range(ModuleCode.M8)
        assert r["start"] == 80100  # 080100
        assert r["end"] == 80999    # 080999

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_module_error_code_base_class(self):
        """ModuleErrorCode 基类"""
        assert ModuleErrorCode.MODULE == ModuleCode.SYSTEM
        r = ModuleErrorCode.range()
        assert "start" in r
        assert "end" in r


# ============================================================
# 旧错误码兼容测试
# ============================================================

class TestLegacyErrorCode:
    """旧错误码兼容测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_legacy_map_not_empty(self):
        """旧错误码映射表不为空"""
        assert len(ERROR_CODE_LEGACY_MAP) > 0

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_normalize_known_legacy_code(self):
        """规范化已知的旧错误码"""
        # 旧的 40001 应该映射到新的 VALIDATION_ERROR
        new_code = normalize_error_code(40001)
        assert new_code == ErrorCode.VALIDATION_ERROR

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_normalize_unknown_code_unchanged(self):
        """未知错误码保持不变"""
        assert normalize_error_code(12345) == 12345

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.error
    def test_yunxi_error_normalizes_legacy_code(self):
        """YunxiError 自动规范化旧错误码"""
        err = YunxiError(code=40001)  # 旧的参数错误码
        assert err.code == ErrorCode.VALIDATION_ERROR
