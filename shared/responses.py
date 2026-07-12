"""
云汐系统统一 API 响应格式模块
提供标准化的成功/失败响应结构，以及常用错误码常量
"""

from typing import Any, Dict, Optional

# ==================== 标准错误码定义 ====================

SUCCESS = 0
"""成功"""

ERROR_INVALID_PARAMS = 40001
"""参数错误"""

ERROR_UNAUTHORIZED = 40101
"""未认证"""

ERROR_FORBIDDEN = 40301
"""无权限"""

ERROR_NOT_FOUND = 40401
"""资源不存在"""

ERROR_INTERNAL = 50001
"""服务器内部错误"""

ERROR_MODULE_UNAVAILABLE = 50301
"""模块不可用"""


class ApiResponse:
    """统一 API 响应类

    提供标准化的响应结构，所有模块的 API 响应应使用此类生成，
    以保证前后端交互格式的一致性。

    响应格式：
    {
        "code": 0,           # 状态码，0 表示成功，非 0 表示错误
        "message": "成功",   # 状态描述
        "data": {},          # 响应数据（成功时）
        "request_id": "xxx"  # 请求追踪 ID（可选）
    }

    Examples:
        >>> # 成功响应
        >>> resp = ApiResponse.success({"user": "alice"}, message="获取成功")
        >>> resp.to_dict()
        {'code': 0, 'message': '获取成功', 'data': {'user': 'alice'}, 'request_id': None}

        >>> # 错误响应
        >>> resp = ApiResponse.error(40001, "参数错误", details={"field": "name"})
        >>> resp.to_dict()
        {'code': 40001, 'message': '参数错误', 'data': None, 'details': {'field': 'name'}, 'request_id': None}
    """

    def __init__(
        self,
        code: int = SUCCESS,
        message: str = "成功",
        data: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ):
        self.code = code
        self.message = message
        self.data = data
        self.details = details or {}
        self.request_id = request_id

    @classmethod
    def success(
        cls,
        data: Optional[Any] = None,
        message: str = "操作成功",
        request_id: Optional[str] = None,
    ) -> "ApiResponse":
        """创建成功响应

        Args:
            data: 响应数据
            message: 成功描述信息
            request_id: 请求追踪 ID

        Returns:
            ApiResponse 实例，code 为 0
        """
        return cls(
            code=SUCCESS,
            message=message,
            data=data,
            request_id=request_id,
        )

    @classmethod
    def error(
        cls,
        code: int = ERROR_INTERNAL,
        message: str = "操作失败",
        details: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> "ApiResponse":
        """创建错误响应

        Args:
            code: 错误码
            message: 错误描述信息
            details: 错误详情字典
            request_id: 请求追踪 ID

        Returns:
            ApiResponse 实例，code 为非 0
        """
        return cls(
            code=code,
            message=message,
            details=details or {},
            request_id=request_id,
        )

    @property
    def is_success(self) -> bool:
        """判断是否为成功响应

        Returns:
            True 表示成功，False 表示失败
        """
        return self.code == SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式

        Returns:
            标准响应字典
        """
        result: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "data": self.data,
        }
        if self.details:
            result["details"] = self.details
        if self.request_id is not None:
            result["request_id"] = self.request_id
        return result

    def __str__(self) -> str:
        return f"ApiResponse(code={self.code}, message={self.message!r})"

    def __repr__(self) -> str:
        return (
            f"ApiResponse(code={self.code}, message={self.message!r}, "
            f"data={self.data!r}, details={self.details!r}, "
            f"request_id={self.request_id!r})"
        )
