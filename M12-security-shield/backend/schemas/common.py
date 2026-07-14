"""
云汐 M12 安全盾 - 通用响应模型
定义统一的 API 响应格式和分页模型
"""

from typing import Generic, TypeVar, Optional, Any, List
from pydantic import BaseModel, Field


# ===========================================================================
# 通用响应模型
# ===========================================================================

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """
    统一 API 响应格式

    所有接口返回数据都遵循 {code, message, data} 格式：
    - code: 状态码，0 表示成功，非 0 表示失败
    - message: 状态描述
    - data: 响应数据
    """

    code: int = Field(default=0, description="状态码，0 表示成功")
    message: str = Field(default="success", description="状态消息")
    data: Optional[T] = Field(default=None, description="响应数据")

    class Config:
        """Pydantic 配置"""
        json_schema_extra = {
            "example": {
                "code": 0,
                "message": "success",
                "data": {"key": "value"},
            }
        }


# ===========================================================================
# 分页模型
# ===========================================================================

class PageRequest(BaseModel):
    """分页请求参数"""

    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量，最大 100")

    @property
    def offset(self) -> int:
        """计算 SQL 查询偏移量"""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """获取查询限制数量"""
        return self.page_size


class PageResponse(BaseModel, Generic[T]):
    """分页响应数据"""

    items: List[T] = Field(default_factory=list, description="数据列表")
    total: int = Field(default=0, description="总记录数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页数量")
    total_pages: int = Field(default=0, description="总页数")

    @classmethod
    def create(cls, items: List[T], total: int, page: int, page_size: int) -> "PageResponse[T]":
        """创建分页响应

        Args:
            items: 数据列表
            total: 总记录数
            page: 当前页码
            page_size: 每页数量

        Returns:
            分页响应对象
        """
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


# ===========================================================================
# 通用操作响应
# ===========================================================================

class SuccessResponse(BaseModel):
    """通用成功响应"""
    success: bool = Field(default=True, description="是否成功")
    message: str = Field(default="操作成功", description="操作结果消息")


class ErrorResponse(BaseModel):
    """通用错误响应"""
    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误消息")
    details: Optional[dict] = Field(default=None, description="错误详情")


# ===========================================================================
# 路径遍历防护校验
# ===========================================================================

import re

_PATH_TRAVERSAL_PATTERN = re.compile(
    r"(\.\./|\.\.\\|%2e%2e%2f|%2e%2e/|\.%00/|\./|/\.\./|/\.\.\\|\\\.\.)"
)


def validate_no_path_traversal(value: str) -> str:
    """验证字符串不包含路径遍历攻击模式

    Args:
        value: 待验证的字符串

    Returns:
        原始字符串（验证通过时）

    Raises:
        ValueError: 检测到路径遍历攻击模式时
    """
    if _PATH_TRAVERSAL_PATTERN.search(value):
        raise ValueError("检测到路径遍历攻击特征")
    return value


# ===========================================================================
# 响应工具函数（从 models.py 迁移，避免路由层耦合 ORM）
# ===========================================================================

def make_response(data: Any = None, code: int = 0, message: str = "success") -> dict:
    """构造统一格式的 API 响应

    Args:
        data: 响应数据
        code: 状态码，0 表示成功
        message: 状态消息

    Returns:
        统一格式的响应字典 {code, message, data}
    """
    return {
        "code": code,
        "message": message,
        "data": data,
    }


def make_error_response(message: str, code: int = -1, data: Any = None) -> dict:
    """构造错误响应

    Args:
        message: 错误消息
        code: 错误码
        data: 附加数据

    Returns:
        错误响应字典
    """
    return make_response(data=data, code=code, message=message)
