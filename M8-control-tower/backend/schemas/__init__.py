"""
M8 管理工作台 - 统一响应格式
"""

from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应格式"""
    code: int = Field(default=0, description="状态码，0表示成功")
    message: str = Field(default="ok", description="状态消息")
    data: Optional[T] = Field(default=None, description="响应数据")
    request_id: Optional[str] = Field(default=None, description="请求ID")
    timestamp: int = Field(default_factory=lambda: __import__("time").time() * 1000 // 1)

    @classmethod
    def success(cls, data: Any = None, message: str = "ok") -> "ApiResponse":
        return cls(code=0, message=message, data=data)

    @classmethod
    def error(cls, code: int, message: str, data: Any = None) -> "ApiResponse":
        return cls(code=code, message=message, data=data)
