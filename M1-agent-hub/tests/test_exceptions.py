"""
测试：M1 统一异常体系
"""

import pytest
import sys
import os

# 将项目根目录加入路径
from exceptions import (
    M1BaseException,
    ValidationError,
    AuthenticationError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ResourceExhaustedError,
    ExternalServiceError,
    CircuitBreakerOpenError,
    ConfigurationError,
    TaskError,
    AgentError,
    FederationError,
    PrivacyError,
    BudgetError,
)
from error_codes import (
    ERR_PARAM_INVALID,
    ERR_AUTH_REQUIRED,
    ERR_PERMISSION_DENIED,
    ERR_UNKNOWN,
    ERR_RESOURCE_INSUFFICIENT,
    ERR_FED_INVOKE_FAILED,
    ERR_SERVICE_UNAVAILABLE,
    ERR_CONFIG_INVALID,
    ERR_SCHEDULER_BUSY,
    ERR_AGENT_OFFLINE,
    ERR_FEDERATION_DISABLED,
    ERR_PRIVACY_BLOCKED,
    ERR_BUDGET_EXCEEDED,
    build_error_response,
)


# ── M1BaseException 基类测试 ──────────────────────────────


def test_base_exception_init_defaults():
    """测试基类初始化时默认值"""
    exc = M1BaseException(error_code=ERR_UNKNOWN)
    assert exc.error_code == ERR_UNKNOWN
    assert exc.detail == ERR_UNKNOWN.message
    assert exc.trace_id == ""
    assert exc.data is None


def test_base_exception_init_with_params():
    """测试基类初始化时传入所有参数"""
    exc = M1BaseException(
        error_code=ERR_PARAM_INVALID,
        detail="用户名不能为空",
        trace_id="trace-123",
        data={"field": "username"},
    )
    assert exc.error_code == ERR_PARAM_INVALID
    assert exc.detail == "用户名不能为空"
    assert exc.trace_id == "trace-123"
    assert exc.data == {"field": "username"}


def test_base_exception_str_with_detail():
    """测试 __str__ 方法，有自定义 detail 时的格式"""
    exc = M1BaseException(
        error_code=ERR_PARAM_INVALID,
        detail="用户名不能为空",
    )
    expected = f"[{ERR_PARAM_INVALID.code}] {ERR_PARAM_INVALID.message} - 用户名不能为空"
    assert str(exc) == expected


def test_base_exception_str_without_detail():
    """测试 __str__ 方法，无自定义 detail 时的格式"""
    exc = M1BaseException(error_code=ERR_UNKNOWN)
    expected = f"[{ERR_UNKNOWN.code}] {ERR_UNKNOWN.message}"
    assert str(exc) == expected


def test_base_exception_properties():
    """测试 http_status / code / level 属性"""
    exc = M1BaseException(error_code=ERR_AUTH_REQUIRED)
    assert exc.http_status == ERR_AUTH_REQUIRED.http_status
    assert exc.code == ERR_AUTH_REQUIRED.code
    assert exc.level == ERR_AUTH_REQUIRED.level


def test_base_exception_to_response():
    """测试 to_response 方法生成标准错误响应"""
    exc = M1BaseException(
        error_code=ERR_PARAM_INVALID,
        detail="密码太短",
        trace_id="trace-abc",
        data={"field": "password"},
    )
    resp = exc.to_response()

    assert resp["success"] is False
    assert resp["error"]["code"] == ERR_PARAM_INVALID.code
    assert resp["error"]["message"] == ERR_PARAM_INVALID.message
    assert resp["error"]["detail"] == "密码太短"
    assert resp["error"]["level"] == ERR_PARAM_INVALID.level
    assert resp["trace_id"] == "trace-abc"
    assert resp["data"] == {"field": "password"}


def test_base_exception_to_response_empty_data():
    """测试 to_response 中 data 为 None 的情况"""
    exc = M1BaseException(error_code=ERR_UNKNOWN)
    resp = exc.to_response()
    assert resp["data"] is None


def test_base_exception_repr():
    """测试 __repr__ 方法格式"""
    exc = M1BaseException(error_code=ERR_UNKNOWN, detail="test", trace_id="t1")
    repr_str = repr(exc)
    assert "M1BaseException" in repr_str
    assert "error_code=" in repr_str
    assert "trace_id='t1'" in repr_str


def test_base_exception_is_exception():
    """测试基类继承自 Exception"""
    exc = M1BaseException(error_code=ERR_UNKNOWN)
    assert isinstance(exc, Exception)


# ── 各分层异常类默认错误码测试 ──────────────────────────────


def test_validation_error_default_code():
    """测试 ValidationError 默认错误码"""
    exc = ValidationError()
    assert exc.code == ERR_PARAM_INVALID.code


def test_authentication_error_default_code():
    """测试 AuthenticationError 默认错误码"""
    exc = AuthenticationError()
    assert exc.code == ERR_AUTH_REQUIRED.code


def test_permission_denied_error_default_code():
    """测试 PermissionDeniedError 默认错误码"""
    exc = PermissionDeniedError()
    assert exc.code == ERR_PERMISSION_DENIED.code


def test_resource_not_found_error_default_code():
    """测试 ResourceNotFoundError 默认错误码"""
    exc = ResourceNotFoundError()
    assert exc.code == ERR_UNKNOWN.code


def test_resource_exhausted_error_default_code():
    """测试 ResourceExhaustedError 默认错误码"""
    exc = ResourceExhaustedError()
    assert exc.code == ERR_RESOURCE_INSUFFICIENT.code


def test_external_service_error_default_code():
    """测试 ExternalServiceError 默认错误码"""
    exc = ExternalServiceError()
    assert exc.code == ERR_FED_INVOKE_FAILED.code


def test_circuit_breaker_open_error_default_code():
    """测试 CircuitBreakerOpenError 默认错误码"""
    exc = CircuitBreakerOpenError()
    assert exc.code == ERR_SERVICE_UNAVAILABLE.code


def test_configuration_error_default_code():
    """测试 ConfigurationError 默认错误码"""
    exc = ConfigurationError()
    assert exc.code == ERR_CONFIG_INVALID.code


def test_task_error_default_code():
    """测试 TaskError 默认错误码"""
    exc = TaskError()
    assert exc.code == ERR_SCHEDULER_BUSY.code


def test_agent_error_default_code():
    """测试 AgentError 默认错误码"""
    exc = AgentError()
    assert exc.code == ERR_AGENT_OFFLINE.code


def test_federation_error_default_code():
    """测试 FederationError 默认错误码"""
    exc = FederationError()
    assert exc.code == ERR_FEDERATION_DISABLED.code


def test_privacy_error_default_code():
    """测试 PrivacyError 默认错误码"""
    exc = PrivacyError()
    assert exc.code == ERR_PRIVACY_BLOCKED.code


def test_budget_error_default_code():
    """测试 BudgetError 默认错误码"""
    exc = BudgetError()
    assert exc.code == ERR_BUDGET_EXCEEDED.code


# ── 异常继承关系测试 ──────────────────────────────────────


def test_all_exceptions_inherit_from_base():
    """测试所有分层异常都继承自 M1BaseException"""
    exception_classes = [
        ValidationError,
        AuthenticationError,
        PermissionDeniedError,
        ResourceNotFoundError,
        ResourceExhaustedError,
        ExternalServiceError,
        CircuitBreakerOpenError,
        ConfigurationError,
        TaskError,
        AgentError,
        FederationError,
        PrivacyError,
        BudgetError,
    ]
    for cls in exception_classes:
        assert issubclass(cls, M1BaseException), f"{cls.__name__} 应继承自 M1BaseException"


def test_all_exceptions_are_throwable():
    """测试所有异常都可以被抛出和捕获"""
    exception_classes = [
        ValidationError("test"),
        AuthenticationError("test"),
        PermissionDeniedError("test"),
        ResourceNotFoundError("test"),
        ResourceExhaustedError("test"),
        ExternalServiceError("test"),
        CircuitBreakerOpenError("test"),
        ConfigurationError("test"),
        TaskError("test"),
        AgentError("test"),
        FederationError("test"),
        PrivacyError("test"),
        BudgetError("test"),
    ]
    for exc in exception_classes:
        try:
            raise exc
        except M1BaseException:
            pass  # 预期被捕获


# ── trace_id 传递测试 ─────────────────────────────────────


def test_trace_id_passed_through_exception():
    """测试 trace_id 在异常中正确传递"""
    exc = ValidationError(detail="参数错误", trace_id="trace-xyz-789")
    assert exc.trace_id == "trace-xyz-789"
    resp = exc.to_response()
    assert resp["trace_id"] == "trace-xyz-789"


def test_exception_with_custom_error_code():
    """测试异常支持自定义 error_code"""
    from error_codes import ERR_PARAM_MISSING
    exc = ValidationError(detail="缺少 user_id", error_code=ERR_PARAM_MISSING)
    assert exc.code == ERR_PARAM_MISSING.code
    assert exc.detail == "缺少 user_id"


# ── 与 build_error_response 集成测试 ──────────────────────


def test_to_response_matches_build_error_response():
    """测试 to_response 的输出与直接调用 build_error_response 一致"""
    detail = "测试详情"
    trace_id = "trace-match-001"
    data = {"key": "value"}

    exc = M1BaseException(
        error_code=ERR_UNKNOWN,
        detail=detail,
        trace_id=trace_id,
        data=data,
    )

    direct_resp = build_error_response(
        error_code=ERR_UNKNOWN,
        detail=detail,
        trace_id=trace_id,
        data=data,
    )

    exc_resp = exc.to_response()
    assert exc_resp == direct_resp


def test_exception_data_dict_in_response():
    """测试 data 字典完整出现在响应中"""
    data = {"field": "email", "constraint": "unique", "value": "a@b.com"}
    exc = ValidationError(detail="邮箱已注册", data=data)
    resp = exc.to_response()
    assert resp["data"] == data


# ── 异常 detail 为空时使用默认 message ─────────────────────


def test_empty_detail_uses_error_code_message():
    """测试 detail 为空时使用 error_code 的 message"""
    exc = M1BaseException(error_code=ERR_UNKNOWN, detail="")
    assert exc.detail == ERR_UNKNOWN.message
