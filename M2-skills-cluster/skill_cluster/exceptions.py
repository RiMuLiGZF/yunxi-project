"""M2 技能集群统一异常体系.

提供分层的异常类体系，与 error_codes.py 中的错误码打通，
支持标准错误响应生成、trace_id 透传、结构化日志记录。

异常继承关系：
    Exception
    └── M2BaseException
        ├── ValidationError          # 参数校验异常
        ├── AuthenticationError      # 认证异常
        ├── PermissionDeniedError    # 权限异常
        ├── ResourceNotFoundError    # 资源不存在
        ├── ResourceExhaustedError   # 资源耗尽
        ├── SkillInvokeError         # 技能调用异常
        ├── CircuitBreakerOpenError  # 熔断器打开
        ├── ConfigurationError       # 配置错误
        ├── RateLimitError           # 限流异常
        ├── CacheError               # 缓存异常
        ├── PipelineError            # 流水线异常
        ├── SandboxError             # 沙箱执行异常
        └── PluginError              # 插件加载异常
"""

from __future__ import annotations

from typing import Any

from skill_cluster.error_codes import ErrorCode, get_error_message, make_error_response


class M2BaseException(Exception):
    """M2 技能集群统一异常基类.

    所有业务异常均应继承此类，便于在 API 层统一捕获和处理。
    异常实例携带完整的错误上下文（错误码、详情、追踪ID、附加数据），
    可直接转换为标准错误响应格式。

    Attributes:
        error_code: 错误码数值（对应 ErrorCode 中的常量）
        detail: 错误详情描述，覆盖默认消息
        trace_id: 调用链路追踪 ID
        data: 附加数据字典，用于返回更多上下文
    """

    #: 默认错误码，子类可覆盖
    default_code: int = ErrorCode.UNKNOWN_ERROR

    #: 默认 HTTP 状态码映射
    _http_status_map: dict[int, int] = {
        ErrorCode.SUCCESS: 200,
        ErrorCode.UNKNOWN_ERROR: 500,
        ErrorCode.INVALID_PARAMS: 400,
        ErrorCode.UNAUTHORIZED: 401,
        ErrorCode.FORBIDDEN: 403,
        ErrorCode.NOT_FOUND: 404,
        ErrorCode.RATE_LIMITED: 429,
        ErrorCode.SERVICE_UNAVAILABLE: 503,
        ErrorCode.TIMEOUT: 504,
        ErrorCode.INTERNAL_ERROR: 500,
        ErrorCode.CONFIG_ERROR: 500,
        ErrorCode.SKILL_NOT_FOUND: 404,
        ErrorCode.SKILL_DISABLED: 403,
        ErrorCode.SKILL_LOAD_FAILED: 500,
        ErrorCode.SKILL_VERSION_MISMATCH: 400,
        ErrorCode.SKILL_DEPENDENCY_MISSING: 500,
        ErrorCode.SKILL_ALREADY_EXISTS: 409,
        ErrorCode.SKILL_INVALID_MANIFEST: 400,
        ErrorCode.SKILL_ACTION_NOT_FOUND: 404,
        ErrorCode.SKILL_CATEGORY_NOT_FOUND: 404,
        ErrorCode.EXECUTION_FAILED: 500,
        ErrorCode.EXECUTION_TIMEOUT: 504,
        ErrorCode.EXECUTION_CANCELLED: 499,
        ErrorCode.EXECUTION_RETRY_EXHAUSTED: 500,
        ErrorCode.EXECUTION_PARAMS_INVALID: 400,
        ErrorCode.EXECUTION_RESULT_INVALID: 500,
        ErrorCode.PERMISSION_DENIED: 403,
        ErrorCode.PERMISSION_LEVEL_INSUFFICIENT: 403,
        ErrorCode.PERMISSION_SCOPE_INVALID: 400,
        ErrorCode.PERMISSION_TOKEN_INVALID: 401,
        ErrorCode.PERMISSION_ROLE_NOT_FOUND: 404,
        ErrorCode.MCP_SERVER_NOT_FOUND: 404,
        ErrorCode.MCP_SERVER_UNAVAILABLE: 503,
        ErrorCode.MCP_TOOL_NOT_FOUND: 404,
        ErrorCode.MCP_CALL_FAILED: 500,
        ErrorCode.MCP_PROTOCOL_ERROR: 400,
        ErrorCode.MCP_CONNECTION_FAILED: 503,
        ErrorCode.CODE_EXEC_FAILED: 500,
        ErrorCode.CODE_SYNTAX_ERROR: 400,
        ErrorCode.CODE_TIMEOUT: 504,
        ErrorCode.CODE_MEMORY_LIMIT: 500,
        ErrorCode.CODE_SECURITY_BLOCKED: 403,
        ErrorCode.CODE_DEPENDENCY_MISSING: 500,
        ErrorCode.CODE_LANGUAGE_UNSUPPORTED: 400,
        ErrorCode.CODE_REPL_NOT_FOUND: 404,
        ErrorCode.CODE_REPL_LIMIT_EXCEEDED: 429,
        ErrorCode.CODE_INSTALL_FAILED: 500,
        ErrorCode.RECOMMEND_NO_RESULT: 200,
        ErrorCode.RECOMMEND_QUERY_EMPTY: 400,
        ErrorCode.RECOMMEND_SCENE_INVALID: 400,
        ErrorCode.RECOMMEND_CACHE_ERROR: 500,
    }

    def __init__(
        self,
        detail: str = "",
        *,
        error_code: int | None = None,
        trace_id: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        """初始化异常.

        Args:
            detail: 错误详情描述，不传则使用错误码默认消息
            error_code: 错误码，不传则使用子类的 default_code
            trace_id: 调用链路追踪 ID
            data: 附加数据字典
        """
        self.error_code: int = error_code if error_code is not None else self.default_code
        self.detail: str = detail
        self.trace_id: str = trace_id
        self.data: dict[str, Any] | None = data

        # 使用 detail 或默认消息作为异常消息
        message = detail or get_error_message(self.error_code)
        super().__init__(message)

    # ---- 便捷属性 ----

    @property
    def http_status(self) -> int:
        """获取对应的 HTTP 状态码."""
        return self._http_status_map.get(self.error_code, 500)

    @property
    def code(self) -> int:
        """错误码数值，便捷访问."""
        return self.error_code

    @property
    def message(self) -> str:
        """错误消息，优先使用 detail，否则使用默认消息."""
        return self.detail or get_error_message(self.error_code)

    # ---- 方法 ----

    def to_response(self) -> dict[str, Any]:
        """生成标准错误响应字典.

        Returns:
            符合 make_error_response 格式的标准响应字典
        """
        return make_error_response(
            code=self.error_code,
            message=self.detail or None,
            data=self.data,
            trace_id=self.trace_id,
        )

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"code={self.error_code} "
            f"message={self.message!r} "
            f"trace_id={self.trace_id!r}>"
        )


# =============================================================================
# 分层异常类
# =============================================================================


class ValidationError(M2BaseException):
    """参数校验异常.

    当请求参数不合法、格式错误、缺失必填字段时抛出。

    默认错误码：INVALID_PARAMS (20002)
    HTTP 状态码：400
    """

    default_code: int = ErrorCode.INVALID_PARAMS


class AuthenticationError(M2BaseException):
    """认证异常.

    当用户未认证、Token 无效、会话过期时抛出。

    默认错误码：UNAUTHORIZED (20003)
    HTTP 状态码：401
    """

    default_code: int = ErrorCode.UNAUTHORIZED


class PermissionDeniedError(M2BaseException):
    """权限异常.

    当用户已认证但缺乏操作所需权限时抛出。

    默认错误码：PERMISSION_DENIED (23001)
    HTTP 状态码：403
    """

    default_code: int = ErrorCode.PERMISSION_DENIED


class ResourceNotFoundError(M2BaseException):
    """资源不存在异常.

    当请求的资源（技能、分类、会话等）不存在时抛出。

    默认错误码：NOT_FOUND (20005)
    HTTP 状态码：404
    """

    default_code: int = ErrorCode.NOT_FOUND


class ResourceExhaustedError(M2BaseException):
    """资源耗尽异常.

    当系统资源（连接数、内存、配额等）耗尽时抛出。

    默认错误码：RATE_LIMITED (20006)
    HTTP 状态码：429
    """

    default_code: int = ErrorCode.RATE_LIMITED


class SkillInvokeError(M2BaseException):
    """技能调用异常.

    当技能执行过程中发生业务错误时抛出。

    默认错误码：EXECUTION_FAILED (22001)
    HTTP 状态码：500
    """

    default_code: int = ErrorCode.EXECUTION_FAILED


class CircuitBreakerOpenError(M2BaseException):
    """熔断器打开异常.

    当熔断器处于打开状态，请求被直接拒绝时抛出。

    默认错误码：SERVICE_UNAVAILABLE (20007)
    HTTP 状态码：503
    """

    default_code: int = ErrorCode.SERVICE_UNAVAILABLE


class ConfigurationError(M2BaseException):
    """配置错误异常.

    当系统配置不合法、缺失关键配置项时抛出。

    默认错误码：CONFIG_ERROR (20010)
    HTTP 状态码：500
    """

    default_code: int = ErrorCode.CONFIG_ERROR


class RateLimitError(M2BaseException):
    """限流异常.

    当请求频率超过限制时抛出。

    默认错误码：RATE_LIMITED (20006)
    HTTP 状态码：429
    """

    default_code: int = ErrorCode.RATE_LIMITED


class CacheError(M2BaseException):
    """缓存异常.

    当缓存读写操作失败时抛出。

    默认错误码：INTERNAL_ERROR (20009)
    HTTP 状态码：500
    """

    default_code: int = ErrorCode.INTERNAL_ERROR


class PipelineError(M2BaseException):
    """流水线异常.

    当技能流水线执行过程中发生错误时抛出。

    默认错误码：EXECUTION_FAILED (22001)
    HTTP 状态码：500
    """

    default_code: int = ErrorCode.EXECUTION_FAILED


class SandboxError(M2BaseException):
    """沙箱执行异常.

    当沙箱环境中的代码执行失败时抛出。

    默认错误码：CODE_EXEC_FAILED (25001)
    HTTP 状态码：500
    """

    default_code: int = ErrorCode.CODE_EXEC_FAILED


class PluginError(M2BaseException):
    """插件加载异常.

    当插件加载、初始化失败时抛出。

    默认错误码：SKILL_LOAD_FAILED (21003)
    HTTP 状态码：500
    """

    default_code: int = ErrorCode.SKILL_LOAD_FAILED


# =============================================================================
# 向后兼容别名
# =============================================================================

# 旧版 CircuitBreakerOpenError 在 circuit_breaker.py 中定义为简单 Exception 子类，
# 此处提供同名类以保证 import 路径兼容。
# 注意：circuit_breaker.py 中的类已更新为继承自本模块的 CircuitBreakerOpenError。

__all__ = [
    "M2BaseException",
    "ValidationError",
    "AuthenticationError",
    "PermissionDeniedError",
    "ResourceNotFoundError",
    "ResourceExhaustedError",
    "SkillInvokeError",
    "CircuitBreakerOpenError",
    "ConfigurationError",
    "RateLimitError",
    "CacheError",
    "PipelineError",
    "SandboxError",
    "PluginError",
]
