"""
云汐系统统一错误处理模块
提供所有自定义异常的基类和常用异常类型，支持统一的错误码和详情信息
"""

from typing import Any, Dict, Optional


class YunxiError(Exception):
    """云汐系统自定义异常基类

    所有业务层自定义异常都应继承此类，便于统一捕获和处理。

    Attributes:
        code: 错误码，用于 API 响应和日志分析
        message: 错误描述信息
        details: 错误详情，可包含额外的上下文数据
    """

    def __init__(
        self,
        message: str = "系统内部错误",
        code: int = 50000,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code}, message={self.message!r}, details={self.details!r})"


class ConfigError(YunxiError):
    """配置错误

    当配置项缺失、格式不正确或加载失败时抛出。

    Attributes:
        code: 错误码，默认为 40002
    """

    def __init__(
        self,
        message: str = "配置错误",
        code: int = 40002,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details)


class ModuleNotFoundError(YunxiError):
    """模块不存在错误

    当请求的模块未在注册中心注册、或模块标识无效时抛出。

    Attributes:
        code: 错误码，默认为 40402
    """

    def __init__(
        self,
        message: str = "模块不存在",
        code: int = 40402,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details)


class ModuleCallError(YunxiError):
    """模块调用失败错误

    当跨模块 HTTP 调用失败、超时、或返回非预期结果时抛出。

    Attributes:
        code: 错误码，默认为 50302
    """

    def __init__(
        self,
        message: str = "模块调用失败",
        code: int = 50302,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details)


class ValidationError(YunxiError):
    """参数验证错误

    当输入参数格式不正确、缺少必填字段、或数据校验失败时抛出。

    Attributes:
        code: 错误码，默认为 40001
    """

    def __init__(
        self,
        message: str = "参数验证失败",
        code: int = 40001,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details)


class AuthenticationError(YunxiError):
    """认证错误

    当用户未认证、Token 无效或已过期时抛出。

    Attributes:
        code: 错误码，默认为 40101
    """

    def __init__(
        self,
        message: str = "认证失败",
        code: int = 40101,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details)


class AuthorizationError(YunxiError):
    """授权错误

    当用户已认证但无权访问请求的资源时抛出。

    Attributes:
        code: 错误码，默认为 40301
    """

    def __init__(
        self,
        message: str = "无访问权限",
        code: int = 40301,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details)


def error_to_dict(error: Exception) -> Dict[str, Any]:
    """将异常转换为字典格式，用于 API 响应

    对于 YunxiError 及其子类，会返回完整的 code、message、details 信息。
    对于普通 Exception，会返回通用内部错误格式。

    Args:
        error: 异常实例

    Returns:
        包含错误信息的字典，格式为：
        {
            "code": 错误码,
            "message": 错误描述,
            "details": 错误详情字典
        }

    Examples:
        >>> try:
        ...     raise ValidationError("用户名不能为空", details={"field": "username"})
        ... except Exception as e:
        ...     print(error_to_dict(e))
        {'code': 40001, 'message': '用户名不能为空', 'details': {'field': 'username'}}
    """
    if isinstance(error, YunxiError):
        return {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        }
    return {
        "code": 50000,
        "message": str(error) or "系统内部错误",
        "details": {},
    }
