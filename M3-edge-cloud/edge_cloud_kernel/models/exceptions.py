"""异常层次定义.

定义端云协同调度内核的完整异常体系。
"""

from __future__ import annotations


class SyncKernelError(Exception):
    """调度内核基础异常.

    所有内核异常的父类，提供统一的错误码和上下文信息。

    Attributes:
        message: 错误描述.
        error_code: 错误码.
        context: 附加上下文信息.
    """

    def __init__(
        self,
        message: str = "",
        error_code: str = "KERNEL_ERROR",
        context: dict | None = None,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.context = context or {}
        super().__init__(self.message)


class RouteError(SyncKernelError):
    """路由决策异常.

    路由引擎在决策过程中发生的错误。

    Attributes:
        message: 错误描述.
        error_code: 默认 ROUTE_ERROR.
        context: 附加上下文.
    """

    def __init__(
        self,
        message: str = "Route decision failed",
        error_code: str = "ROUTE_ERROR",
        context: dict | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, context=context)


class InferenceError(SyncKernelError):
    """推理执行异常.

    本地或云端推理过程中发生的错误。

    Attributes:
        message: 错误描述.
        error_code: 默认 INFERENCE_ERROR.
        context: 附加上下文.
    """

    def __init__(
        self,
        message: str = "Inference execution failed",
        error_code: str = "INFERENCE_ERROR",
        context: dict | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, context=context)


class SyncError(SyncKernelError):
    """数据同步异常.

    端云上下文同步或日志回写过程中发生的错误。

    Attributes:
        message: 错误描述.
        error_code: 默认 SYNC_ERROR.
        context: 附加上下文.
    """

    def __init__(
        self,
        message: str = "Synchronization failed",
        error_code: str = "SYNC_ERROR",
        context: dict | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, context=context)


class CircuitBreakerError(SyncKernelError):
    """熔断器异常.

    当熔断器处于 Open 状态时拒绝请求。

    Attributes:
        message: 错误描述.
        error_code: 默认 CIRCUIT_OPEN.
        context: 附加上下文.
        circuit_name: 熔断器名称.
        reset_in: 预估恢复时间（秒）.
    """

    def __init__(
        self,
        message: str = "Circuit breaker is open",
        error_code: str = "CIRCUIT_OPEN",
        context: dict | None = None,
        circuit_name: str = "",
        reset_in: float = 0.0,
    ) -> None:
        super().__init__(message=message, error_code=error_code, context=context)
        self.circuit_name = circuit_name
        self.reset_in = reset_in


class VRAMOverflowError(SyncKernelError):
    """显存溢出异常.

    当显存水位线达到 CRITICAL 且无法通过卸载模型释放时抛出。

    Attributes:
        message: 错误描述.
        error_code: 默认 VRAM_OVERFLOW.
        context: 附加上下文.
        required_mb: 需要的显存（MB）.
        available_mb: 可用显存（MB）.
    """

    def __init__(
        self,
        message: str = "VRAM overflow detected",
        error_code: str = "VRAM_OVERFLOW",
        context: dict | None = None,
        required_mb: float = 0.0,
        available_mb: float = 0.0,
    ) -> None:
        super().__init__(message=message, error_code=error_code, context=context)
        self.required_mb = required_mb
        self.available_mb = available_mb


class ProviderError(SyncKernelError):
    """LLM Provider 异常.

    Provider 调用失败或格式不兼容。

    Attributes:
        message: 错误描述.
        error_code: 默认 PROVIDER_ERROR.
        context: 附加上下文.
        provider_name: 出错的 Provider 名称.
        status_code: HTTP 状态码（网络错误时）.
    """

    def __init__(
        self,
        message: str = "LLM provider error",
        error_code: str = "PROVIDER_ERROR",
        context: dict | None = None,
        provider_name: str = "",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, context=context)
        self.provider_name = provider_name
        self.status_code = status_code
