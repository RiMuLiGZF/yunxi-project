"""
M1 Agent 集群 - 通用响应模型

统一的 API 响应格式、分页参数、错误响应等通用模型。
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import Field

from models.base import M1BaseModel

# 泛型类型变量，用于 ApiResponse 和 PaginatedResponse
T = TypeVar("T")


class ApiResponse(M1BaseModel, Generic[T]):
    """通用成功响应模型。

    统一 API 成功响应格式，包含状态标识、业务数据和提示信息。

    Attributes:
        success: 操作是否成功，固定为 True
        data: 响应数据，泛型类型，由具体接口决定
        message: 可选提示信息
    """

    success: bool = True
    data: T | None = None
    message: str = ""


class ErrorResponse(M1BaseModel):
    """通用错误响应模型。

    统一 API 错误响应格式，包含错误码、错误信息和追踪 ID。

    Attributes:
        success: 操作是否成功，固定为 False
        error: 错误码标识
        message: 错误详细描述
        trace_id: 追踪 ID，用于问题排查
    """

    success: bool = False
    error: str = ""
    message: str = ""
    trace_id: str = ""


class PaginationParams(M1BaseModel):
    """分页查询参数。

    统一分页查询的输入参数格式，提供合理的边界校验。

    Attributes:
        page: 页码，从 1 开始
        page_size: 每页记录数，1~500
        sort_by: 排序字段名（可选）
        sort_order: 排序方向，asc 或 desc
    """

    page: int = Field(default=1, ge=1, description="页码，从1开始")
    page_size: int = Field(default=20, ge=1, le=500, description="每页记录数")
    sort_by: str = Field(default="", description="排序字段名")
    sort_order: str = Field(default="desc", description="排序方向：asc 或 desc")

    @property
    def offset(self) -> int:
        """计算 SQL/LIST 偏移量。

        Returns:
            偏移量 = (page - 1) * page_size
        """
        return (self.page - 1) * self.page_size

    @property
    def is_asc(self) -> bool:
        """是否升序排列。

        Returns:
            True 表示升序，False 表示降序
        """
        return self.sort_order.lower() == "asc"


class PaginatedResponse(M1BaseModel, Generic[T]):
    """分页响应模型。

    统一分页查询响应格式，包含数据列表和分页信息。

    Attributes:
        success: 操作是否成功
        items: 当前页数据列表
        total: 总记录数
        page: 当前页码（从 1 开始）
        page_size: 每页记录数
        total_pages: 总页数
    """

    success: bool = True
    items: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)
    total_pages: int = Field(default=0, ge=0)
