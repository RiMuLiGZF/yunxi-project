"""
云汐 M12 安全盾 - 通用响应模型
定义统一的 API 响应格式和分页模型

迁移说明：
    ApiResponse 已接入项目级统一响应标准 shared.unified_response。
    标准字段：code/message/data/trace_id/timestamp
    旧的 3 字段格式保留为 LegacyApiResponse（向后兼容）。
    新代码建议使用：from shared.unified_response import ApiResponse
"""

from typing import Generic, TypeVar, Optional, Any, List
from pydantic import BaseModel, Field

import sys
from pathlib import Path

# 确保能导入 shared 包
_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ===========================================================================
# 通用响应模型（已接入统一标准）
# ===========================================================================

T = TypeVar("T")

# 从项目权威标准导入 ApiResponse
try:
    from shared.unified_response import ApiResponse as _UnifiedApiResponse

    # 新版：使用权威标准 ApiResponse
    ApiResponse = _UnifiedApiResponse

    # 旧版兼容：保留 3 字段格式作为 LegacyApiResponse
    class LegacyApiResponse(BaseModel, Generic[T]):
        """
        旧版 API 响应格式（仅 3 字段，向后兼容）.

        .. deprecated:: 2.0.0
           请迁移到 shared.unified_response.ApiResponse。
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

except ImportError:
    # 回退：使用本地实现
    class ApiResponse(BaseModel, Generic[T]):
        """
        统一 API 响应格式（本地回退实现）.
        """

        code: int = Field(default=0, description="状态码，0 表示成功")
        message: str = Field(default="success", description="状态消息")
        data: Optional[T] = Field(default=None, description="响应数据")
        trace_id: Optional[str] = Field(default=None, description="链路追踪 ID")
        timestamp: float = Field(
            default_factory=__import__("time").time,
            description="Unix 时间戳（秒级）",
        )

        class Config:
            json_schema_extra = {
                "example": {
                    "code": 0,
                    "message": "success",
                    "data": {"key": "value"},
                    "trace_id": "abc123",
                    "timestamp": 1700000000.0,
                }
            }

    LegacyApiResponse = ApiResponse  # type: ignore


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
    """构造统一格式的 API 响应（已升级为 5 字段标准格式）.

    Args:
        data: 响应数据
        code: 状态码，0 表示成功
        message: 状态消息

    Returns:
        标准格式的响应字典 {code, message, data, trace_id, timestamp}
    """
    import time as _time
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": None,
        "timestamp": _time.time(),
    }


def make_error_response(message: str, code: int = -1, data: Any = None) -> dict:
    """构造错误响应（已升级为 5 字段标准格式）.

    Args:
        message: 错误消息
        code: 错误码
        data: 附加数据

    Returns:
        错误响应字典
    """
    return make_response(data=data, code=code, message=message)
