"""通用响应模型模块.

定义通用的 Pydantic 响应模型，用于 API 接口的标准化返回。
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

# 泛型类型变量，用于响应数据
T = TypeVar("T")


# ---------------------------------------------------------------------------
# 通用响应模型
# ---------------------------------------------------------------------------

class ApiResponse(BaseModel, Generic[T]):
    """通用 API 响应模型.

    所有 API 接口的返回值都应遵循此格式。
    """
    code: int = Field(0, description="状态码，0 表示成功")
    message: str = Field("success", description="状态消息")
    data: T = Field(default_factory=dict, description="响应数据")

    class Config:
        """Pydantic 配置."""
        json_schema_extra = {
            "example": {
                "code": 0,
                "message": "success",
                "data": {},
            }
        }


# ---------------------------------------------------------------------------
# 分页响应模型
# ---------------------------------------------------------------------------

class PaginationData(BaseModel, Generic[T]):
    """分页数据模型."""
    items: list[T] = Field(default_factory=list, description="数据列表")
    total: int = Field(0, description="总条数")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(20, description="每页条数")
    total_pages: int = Field(0, description="总页数")


class PaginatedResponse(ApiResponse[PaginationData[T]], Generic[T]):
    """分页响应模型."""
    pass


# ---------------------------------------------------------------------------
# 错误响应模型
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """错误响应模型."""
    code: int = Field(..., description="错误码")
    message: str = Field(..., description="错误消息")
    data: dict[str, Any] = Field(default_factory=dict, description="错误详情")
    trace_id: Optional[str] = Field(None, description="请求追踪 ID")


# ---------------------------------------------------------------------------
# 模式相关模型
# ---------------------------------------------------------------------------

class ModeInfo(BaseModel):
    """业务模式信息模型."""
    mode_id: str = Field(..., description="模式唯一标识")
    mode_name: str = Field(..., description="模式名称")
    mode_description: str = Field("", description="模式描述")
    icon: str = Field("📦", description="模式图标（emoji）")
    category: str = Field("general", description="模式分类")
    priority: int = Field(100, description="优先级")
    is_enabled: bool = Field(True, description="是否启用")


class ModeEnterRequest(BaseModel):
    """进入模式请求体."""
    user_id: str = Field("default", description="用户ID")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="进入模式时的上下文",
    )


class ModeLeaveRequest(BaseModel):
    """离开模式请求体."""
    user_id: str = Field("default", description="用户ID")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="离开模式时的上下文",
    )


class ModeEnterResponse(BaseModel):
    """进入模式响应模型."""
    success: bool = Field(True, description="是否成功进入")
    message: str = Field("", description="进入消息")
    data: dict[str, Any] = Field(default_factory=dict, description="模式数据")
    context_updates: dict[str, Any] = Field(
        default_factory=dict,
        description="需要更新的上下文",
    )
