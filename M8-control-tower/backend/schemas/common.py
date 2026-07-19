"""
M8 控制塔 - 通用 Schema 模型

包含通用响应、分页、排序、过滤等通用 Pydantic 模型。
所有模块共用的基础模型都放在这里。

迁移说明：
    ApiResponse 已迁移至 shared.unified_response 作为项目级权威标准。
    本模块保留向后兼容，旧 ApiResponse 仍可用但建议迁移。
    新代码请使用：from shared.unified_response import ApiResponse
"""

from typing import Generic, TypeVar, Optional, Any, List, Dict
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")


# ═══════════════════════════════════════════════════════
# 通用响应模型（已接入统一标准）
# ═══════════════════════════════════════════════════════
# 从项目权威标准导入 ApiResponse，同时保留旧版作为兼容别名
# 旧版字段差异：request_id -> trace_id，timestamp 毫秒 -> 秒级
# 迁移方式：新代码直接用 ApiResponse（来自 unified_response）
#           旧代码继续用 LegacyApiResponse 或 ApiResponseCompat

try:
    import sys
    from pathlib import Path
    # 确保能导入 shared 包
    _project_root = Path(__file__).resolve().parents[3]
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    from shared.unified_response import ApiResponse as _UnifiedApiResponse

    # 新版：直接使用权威标准（推荐路径）
    ApiResponse = _UnifiedApiResponse

    # 向后兼容：保留旧版 ApiResponse 类名和接口
    class ApiResponseCompat(BaseModel, Generic[T]):
        """旧版兼容响应模型（保留 request_id 字段和毫秒级时间戳）.

        .. deprecated:: 2.0.0
           请迁移到 shared.unified_response.ApiResponse。
           字段差异：request_id -> trace_id，timestamp（毫秒）-> timestamp（秒）
        """
        code: int = Field(default=0, description="状态码，0表示成功，非0表示错误")
        message: str = Field(default="ok", description="状态消息")
        data: Optional[T] = Field(default=None, description="响应数据")
        request_id: Optional[str] = Field(default=None, description="请求ID（链路追踪用）")
        timestamp: int = Field(
            default_factory=lambda: int(__import__("time").time() * 1000),
            description="响应时间戳（毫秒）"
        )

        @classmethod
        def success(cls, data: Any = None, message: str = "ok") -> "ApiResponseCompat":
            """成功响应"""
            return cls(code=0, message=message, data=data)

        @classmethod
        def error(cls, code: int, message: str, data: Any = None) -> "ApiResponseCompat":
            """错误响应"""
            return cls(code=code, message=message, data=data)

        def to_unified(self) -> Any:
            """转换为权威统一响应格式."""
            import time as _time
            return _UnifiedApiResponse(
                code=self.code,
                message=self.message,
                data=self.data,
                trace_id=self.request_id,
                timestamp=self.timestamp / 1000.0 if self.timestamp else _time.time(),
            )

    # 旧版别名（保持向后兼容）
    LegacyApiResponse = ApiResponseCompat

except ImportError:
    # 回退：使用原实现
    class ApiResponse(BaseModel, Generic[T]):
        """统一 API 响应格式

        所有 M8 API 接口都应返回此格式，保持前后端契约一致。
        """
        code: int = Field(default=0, description="状态码，0表示成功，非0表示错误")
        message: str = Field(default="ok", description="状态消息")
        data: Optional[T] = Field(default=None, description="响应数据")
        request_id: Optional[str] = Field(default=None, description="请求ID（链路追踪用）")
        timestamp: int = Field(
            default_factory=lambda: int(__import__("time").time() * 1000),
            description="响应时间戳（毫秒）"
        )

        @classmethod
        def success(cls, data: Any = None, message: str = "ok") -> "ApiResponse":
            """成功响应"""
            return cls(code=0, message=message, data=data)

        @classmethod
        def error(cls, code: int, message: str, data: Any = None) -> "ApiResponse":
            """错误响应"""
            return cls(code=code, message=message, data=data)

    ApiResponseCompat = ApiResponse  # type: ignore
    LegacyApiResponse = ApiResponse  # type: ignore


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应数据结构"""
    items: List[T] = Field(default_factory=list, description="数据列表")
    total: int = Field(default=0, description="总记录数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页条数")
    total_pages: int = Field(default=0, description="总页数")
    has_next: bool = Field(default=False, description="是否有下一页")
    has_prev: bool = Field(default=False, description="是否有上一页")


# ═══════════════════════════════════════════════════════
# 分页/排序/过滤请求参数
# ═══════════════════════════════════════════════════════

class PaginationParams(BaseModel):
    """分页查询参数"""
    page: int = Field(default=1, ge=1, description="页码，从1开始")
    page_size: int = Field(default=20, ge=1, le=500, description="每页条数，最大500")

    @property
    def offset(self) -> int:
        """数据库查询偏移量"""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """数据库查询限制条数"""
        return self.page_size


class SortParams(BaseModel):
    """排序查询参数"""
    sort_by: str = Field(default="created_at", description="排序字段")
    sort_order: str = Field(default="desc", description="排序方向：asc/desc")

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, v: str) -> str:
        v = v.lower()
        if v not in ("asc", "desc"):
            raise ValueError("sort_order 必须是 asc 或 desc")
        return v

    @property
    def is_asc(self) -> bool:
        return self.sort_order == "asc"


class FilterParams(BaseModel):
    """通用过滤参数"""
    keyword: Optional[str] = Field(default=None, description="关键词搜索")
    status: Optional[str] = Field(default=None, description="状态过滤")
    start_date: Optional[str] = Field(default=None, description="开始日期 (YYYY-MM-DD)")
    end_date: Optional[str] = Field(default=None, description="结束日期 (YYYY-MM-DD)")


class ListQueryParams(PaginationParams, SortParams, FilterParams):
    """列表查询综合参数（分页 + 排序 + 过滤）"""
    pass


# ═══════════════════════════════════════════════════════
# 通用操作结果
# ═══════════════════════════════════════════════════════

class OperationResult(BaseModel):
    """通用操作结果"""
    success: bool = Field(default=True, description="是否成功")
    message: str = Field(default="操作成功", description="结果消息")
    affected_count: int = Field(default=0, description="影响的记录数")
    details: Optional[Dict[str, Any]] = Field(default=None, description="详细信息")


class BulkOperationResult(BaseModel):
    """批量操作结果"""
    success: bool = Field(default=True, description="整体是否成功")
    total: int = Field(default=0, description="总操作数")
    succeeded: int = Field(default=0, description="成功数")
    failed: int = Field(default=0, description="失败数")
    failed_items: List[Dict[str, Any]] = Field(default_factory=list, description="失败项详情")


# ═══════════════════════════════════════════════════════
# 健康检查相关
# ═══════════════════════════════════════════════════════

class HealthStatus(BaseModel):
    """健康检查状态"""
    status: str = Field(default="healthy", description="健康状态: healthy/degraded/unhealthy")
    version: str = Field(default="", description="版本号")
    uptime_seconds: float = Field(default=0.0, description="运行时长（秒）")
    timestamp: datetime = Field(default_factory=datetime.now)


class ModuleHealthInfo(BaseModel):
    """模块健康信息"""
    module_key: str = Field(description="模块标识")
    module_name: str = Field(description="模块名称")
    status: str = Field(description="运行状态: running/stopped/error")
    health: str = Field(default="unknown", description="健康状态: healthy/degraded/unhealthy/unknown")
    port: Optional[int] = Field(default=None, description="服务端口")
    base_url: Optional[str] = Field(default=None, description="服务地址")
    last_health_check: Optional[datetime] = Field(default=None, description="上次健康检查时间")
    latency_ms: Optional[float] = Field(default=None, description="响应延迟（毫秒）")
    error_message: Optional[str] = Field(default=None, description="错误信息")


# ═══════════════════════════════════════════════════════
# 代理/降级相关
# ═══════════════════════════════════════════════════════

class ProxyStatusInfo(BaseModel):
    """代理状态信息"""
    mode: str = Field(description="代理模式: off/fallback/on")
    target_module: str = Field(description="目标模块")
    target_base_url: str = Field(description="目标服务地址")
    timeout: float = Field(description="超时时间（秒）")
    enabled: bool = Field(description="是否启用代理")
    health_status: str = Field(default="unknown", description="目标模块健康状态")
    last_check_time: Optional[datetime] = Field(default=None, description="上次健康检查时间")


class DegradedResponse(BaseModel):
    """降级响应信息"""
    degraded: bool = Field(default=True, description="是否为降级响应")
    reason: str = Field(description="降级原因")
    fallback_source: str = Field(description="降级数据来源")
    original_error: Optional[str] = Field(default=None, description="原始错误信息")
    timestamp: datetime = Field(default_factory=datetime.now)
