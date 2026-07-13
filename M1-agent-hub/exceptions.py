"""
M1 统一异常体系

提供分层异常基类与各业务域异常，与 error_codes.py 中的 ErrorCode 体系打通。
所有异常均继承自 M1BaseException，自动携带结构化错误信息，便于 API 层统一处理。

异常分层：
- M1BaseException：基础异常基类
  - ValidationError：参数校验异常
  - AuthenticationError：认证异常
  - PermissionDeniedError：权限异常
  - ResourceNotFoundError：资源不存在
  - ResourceExhaustedError：资源耗尽
  - ExternalServiceError：外部服务异常
  - CircuitBreakerOpenError：熔断器打开
  - ConfigurationError：配置错误
  - TaskError：任务调度异常基类
  - AgentError：Agent 管理异常基类
  - FederationError：联邦调度异常基类
  - PrivacyError：隐私安全异常基类
  - BudgetError：预算/成本异常基类
"""

from __future__ import annotations

from typing import Any

from error_codes import (
    ErrorCode,
    build_error_response,
    # 通用错误
    ERR_UNKNOWN,
    ERR_SERVICE_UNAVAILABLE,
    # 认证/授权错误
    ERR_AUTH_REQUIRED,
    ERR_PERMISSION_DENIED,
    # 参数校验错误
    ERR_PARAM_INVALID,
    # 调度引擎错误
    ERR_SCHEDULER_BUSY,
    # Agent 管理错误
    ERR_AGENT_OFFLINE,
    # 联邦调度错误
    ERR_FEDERATION_DISABLED,
    ERR_FED_INVOKE_FAILED,
    # 隐私/安全错误
    ERR_PRIVACY_BLOCKED,
    # 配置错误
    ERR_CONFIG_INVALID,
    # 资源/成本错误
    ERR_RESOURCE_INSUFFICIENT,
    ERR_BUDGET_EXCEEDED,
)


class M1BaseException(Exception):
    """M1 统一异常基类

    所有业务异常均应继承此类，自动携带结构化错误信息，
    便于 API 层统一处理与日志记录。

    Attributes:
        error_code: 错误码对象（来自 error_codes.py）
        detail: 详细错误描述
        trace_id: 链路追踪 ID
        data: 附加数据字典
    """

    error_code: ErrorCode
    detail: str
    trace_id: str
    data: dict[str, Any] | None

    def __init__(
        self,
        error_code: ErrorCode,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        """初始化基础异常

        Args:
            error_code: 错误码对象
            detail: 详细错误描述，为空时使用 error_code.message
            trace_id: 链路追踪 ID
            data: 附加数据字典
        """
        self.error_code = error_code
        self.detail = detail or error_code.message
        self.trace_id = trace_id
        self.data = data
        super().__init__(self.detail)

    def to_response(self) -> dict[str, Any]:
        """生成标准错误响应

        调用 error_codes.build_error_response 构建统一格式的错误响应。

        Returns:
            标准错误响应字典，格式为：
            {
                "success": false,
                "error": {
                    "code": 10100,
                    "message": "需要认证",
                    "detail": "详细说明",
                    "level": "warning"
                },
                "trace_id": "xxx",
                "data": null
            }
        """
        return build_error_response(
            error_code=self.error_code,
            detail=self.detail,
            trace_id=self.trace_id,
            data=self.data,
        )

    @property
    def http_status(self) -> int:
        """获取对应的 HTTP 状态码"""
        return self.error_code.http_status

    @property
    def code(self) -> int:
        """获取错误码数值"""
        return self.error_code.code

    @property
    def level(self) -> str:
        """获取错误级别"""
        return self.error_code.level

    def __str__(self) -> str:
        """可读的错误描述

        Returns:
            格式化的错误字符串，格式为：
            "[{code}] {message} - {detail}"
        """
        if self.detail and self.detail != self.error_code.message:
            return f"[{self.error_code.code}] {self.error_code.message} - {self.detail}"
        return f"[{self.error_code.code}] {self.error_code.message}"

    def __repr__(self) -> str:
        """异常对象的字符串表示"""
        return (
            f"{self.__class__.__name__}("
            f"error_code={self.error_code!r}, "
            f"detail={self.detail!r}, "
            f"trace_id={self.trace_id!r}, "
            f"data={self.data!r})"
        )


# ═══════════════════════════════════════════════════════
# 参数校验异常
# ═══════════════════════════════════════════════════════

class ValidationError(M1BaseException):
    """参数校验异常

    用于请求参数格式错误、类型不匹配、范围超限等场景。

    默认错误码：ERR_PARAM_INVALID (10201)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化参数校验异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典（可包含字段错误详情）
            error_code: 自定义错误码，默认使用 ERR_PARAM_INVALID
        """
        super().__init__(
            error_code=error_code or ERR_PARAM_INVALID,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


# ═══════════════════════════════════════════════════════
# 认证/授权异常
# ═══════════════════════════════════════════════════════

class AuthenticationError(M1BaseException):
    """认证异常

    用于未认证、凭证无效、Token 过期等场景。

    默认错误码：ERR_AUTH_REQUIRED (10100)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化认证异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_AUTH_REQUIRED
        """
        super().__init__(
            error_code=error_code or ERR_AUTH_REQUIRED,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


class PermissionDeniedError(M1BaseException):
    """权限异常

    用于已认证但权限不足、操作被禁止等场景。

    默认错误码：ERR_PERMISSION_DENIED (10104)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化权限异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_PERMISSION_DENIED
        """
        super().__init__(
            error_code=error_code or ERR_PERMISSION_DENIED,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


# ═══════════════════════════════════════════════════════
# 资源相关异常
# ═══════════════════════════════════════════════════════

class ResourceNotFoundError(M1BaseException):
    """资源不存在异常

    用于查询的任务、Agent、配置等资源不存在的场景。

    默认错误码：ERR_UNKNOWN (10000)，可根据场景定制为具体的资源不存在错误码
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化资源不存在异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_UNKNOWN
                       推荐根据场景使用具体错误码，如：
                       - ERR_TASK_NOT_FOUND：任务不存在
                       - ERR_AGENT_NOT_FOUND：Agent 不存在
                       - ERR_KEY_NOT_FOUND：密钥不存在
        """
        super().__init__(
            error_code=error_code or ERR_UNKNOWN,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


class ResourceExhaustedError(M1BaseException):
    """资源耗尽异常

    用于系统资源不足、分身池耗尽、队列已满等场景。

    默认错误码：ERR_RESOURCE_INSUFFICIENT (10803)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化资源耗尽异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_RESOURCE_INSUFFICIENT
        """
        super().__init__(
            error_code=error_code or ERR_RESOURCE_INSUFFICIENT,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


# ═══════════════════════════════════════════════════════
# 外部服务/熔断器异常
# ═══════════════════════════════════════════════════════

class ExternalServiceError(M1BaseException):
    """外部服务异常

    用于调用外部服务失败、第三方接口异常等场景。

    默认错误码：ERR_FED_INVOKE_FAILED (10503)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化外部服务异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_FED_INVOKE_FAILED
        """
        super().__init__(
            error_code=error_code or ERR_FED_INVOKE_FAILED,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


class CircuitBreakerOpenError(M1BaseException):
    """熔断器打开异常

    用于熔断器处于打开状态、请求被快速拒绝的场景。

    默认错误码：ERR_SERVICE_UNAVAILABLE (10003)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化熔断器打开异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_SERVICE_UNAVAILABLE
        """
        super().__init__(
            error_code=error_code or ERR_SERVICE_UNAVAILABLE,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


# ═══════════════════════════════════════════════════════
# 配置错误
# ═══════════════════════════════════════════════════════

class ConfigurationError(M1BaseException):
    """配置错误异常

    用于配置文件缺失、格式错误、缺少必要配置项等场景。

    默认错误码：ERR_CONFIG_INVALID (10701)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化配置错误异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_CONFIG_INVALID
        """
        super().__init__(
            error_code=error_code or ERR_CONFIG_INVALID,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


# ═══════════════════════════════════════════════════════
# 任务调度异常基类
# ═══════════════════════════════════════════════════════

class TaskError(M1BaseException):
    """任务调度异常基类

    所有任务调度相关异常的基类，包括任务不存在、队列已满、超时等。

    默认错误码：ERR_SCHEDULER_BUSY (10308)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化任务调度异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_SCHEDULER_BUSY
        """
        super().__init__(
            error_code=error_code or ERR_SCHEDULER_BUSY,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


# ═══════════════════════════════════════════════════════
# Agent 管理异常基类
# ═══════════════════════════════════════════════════════

class AgentError(M1BaseException):
    """Agent 管理异常基类

    所有 Agent 管理相关异常的基类，包括 Agent 不存在、离线、类型无效等。

    默认错误码：ERR_AGENT_OFFLINE (10402)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化 Agent 管理异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_AGENT_OFFLINE
        """
        super().__init__(
            error_code=error_code or ERR_AGENT_OFFLINE,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


# ═══════════════════════════════════════════════════════
# 联邦调度异常基类
# ═══════════════════════════════════════════════════════

class FederationError(M1BaseException):
    """联邦调度异常基类

    所有联邦调度相关异常的基类，包括联邦未启用、注册失败、调用失败等。

    默认错误码：ERR_FEDERATION_DISABLED (10500)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化联邦调度异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_FEDERATION_DISABLED
        """
        super().__init__(
            error_code=error_code or ERR_FEDERATION_DISABLED,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


# ═══════════════════════════════════════════════════════
# 隐私安全异常基类
# ═══════════════════════════════════════════════════════

class PrivacyError(M1BaseException):
    """隐私安全异常基类

    所有隐私安全相关异常的基类，包括内容被拦截、检测到敏感信息、加密失败等。

    默认错误码：ERR_PRIVACY_BLOCKED (10600)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化隐私安全异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_PRIVACY_BLOCKED
        """
        super().__init__(
            error_code=error_code or ERR_PRIVACY_BLOCKED,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


# ═══════════════════════════════════════════════════════
# 预算/成本异常基类
# ═══════════════════════════════════════════════════════

class BudgetError(M1BaseException):
    """预算/成本异常基类

    所有预算成本相关异常的基类，包括预算超限、预算未设置等。

    默认错误码：ERR_BUDGET_EXCEEDED (10800)
    """

    def __init__(
        self,
        detail: str = "",
        trace_id: str = "",
        data: dict[str, Any] | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        """初始化预算/成本异常

        Args:
            detail: 详细错误描述
            trace_id: 链路追踪 ID
            data: 附加数据字典
            error_code: 自定义错误码，默认使用 ERR_BUDGET_EXCEEDED
        """
        super().__init__(
            error_code=error_code or ERR_BUDGET_EXCEEDED,
            detail=detail,
            trace_id=trace_id,
            data=data,
        )


# ═══════════════════════════════════════════════════════
# 异常导出列表
# ═══════════════════════════════════════════════════════

__all__ = [
    # 基类
    "M1BaseException",
    # 参数校验
    "ValidationError",
    # 认证/授权
    "AuthenticationError",
    "PermissionDeniedError",
    # 资源相关
    "ResourceNotFoundError",
    "ResourceExhaustedError",
    # 外部服务/熔断器
    "ExternalServiceError",
    "CircuitBreakerOpenError",
    # 配置
    "ConfigurationError",
    # 任务调度
    "TaskError",
    # Agent 管理
    "AgentError",
    # 联邦调度
    "FederationError",
    # 隐私安全
    "PrivacyError",
    # 预算成本
    "BudgetError",
]
