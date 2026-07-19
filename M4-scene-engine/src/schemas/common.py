"""通用响应模型模块.

定义通用的 Pydantic 响应模型，用于 API 接口的标准化返回。

迁移说明：
    ApiResponse 已接入项目级统一响应标准 shared.unified_response。
    标准字段：code/message/data/trace_id/timestamp
    旧的 3 字段格式保留为 LegacyApiResponse（向后兼容）。
    新代码建议使用：from shared.unified_response import ApiResponse
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

# 确保能导入 shared 包
_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 泛型类型变量，用于响应数据
T = TypeVar("T")


# ---------------------------------------------------------------------------
# 通用响应模型（已接入统一标准）
# ---------------------------------------------------------------------------

# 从项目权威标准导入 ApiResponse
try:
    from shared.unified_response import ApiResponse as _UnifiedApiResponse

    # 新版：使用权威标准 ApiResponse
    ApiResponse = _UnifiedApiResponse

    # 旧版兼容：保留 3 字段格式
    class LegacyApiResponse(BaseModel, Generic[T]):
        """旧版通用 API 响应模型（3 字段，向后兼容）.

        .. deprecated:: 2.0.0
           请迁移到 shared.unified_response.ApiResponse。
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

except ImportError:
    # 回退：本地实现
    class ApiResponse(BaseModel, Generic[T]):
        """通用 API 响应模型（本地回退实现）."""
        code: int = Field(0, description="状态码，0 表示成功")
        message: str = Field("success", description="状态消息")
        data: T = Field(default_factory=dict, description="响应数据")
        trace_id: Optional[str] = Field(None, description="链路追踪 ID")
        timestamp: float = Field(
            default_factory=__import__("time").time,
            description="Unix 时间戳（秒级）",
        )

        class Config:
            json_schema_extra = {
                "example": {
                    "code": 0,
                    "message": "success",
                    "data": {},
                    "trace_id": "abc123",
                    "timestamp": 1700000000.0,
                }
            }

    LegacyApiResponse = ApiResponse  # type: ignore


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
    user_id: Optional[str] = Field(None, description="用户ID，不传则从请求上下文获取")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="进入模式时的上下文",
    )

    def get_effective_user_id(self) -> str:
        """获取有效的用户 ID.

        如果 user_id 为 None，则从请求上下文中获取。
        保证向后兼容：没有上下文时返回 "default"。

        Returns:
            有效的用户 ID 字符串
        """
        if self.user_id:
            return self.user_id
        from src.common.user_context import get_current_user_id
        return get_current_user_id()


class ModeLeaveRequest(BaseModel):
    """离开模式请求体."""
    user_id: Optional[str] = Field(None, description="用户ID，不传则从请求上下文获取")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="离开模式时的上下文",
    )

    def get_effective_user_id(self) -> str:
        """获取有效的用户 ID.

        如果 user_id 为 None，则从请求上下文中获取。
        保证向后兼容：没有上下文时返回 "default"。

        Returns:
            有效的用户 ID 字符串
        """
        if self.user_id:
            return self.user_id
        from src.common.user_context import get_current_user_id
        return get_current_user_id()


class ModeEnterResponse(BaseModel):
    """进入模式响应模型."""
    success: bool = Field(True, description="是否成功进入")
    message: str = Field("", description="进入消息")
    data: dict[str, Any] = Field(default_factory=dict, description="模式数据")
    context_updates: dict[str, Any] = Field(
        default_factory=dict,
        description="需要更新的上下文",
    )
