"""
云汐系统 - 统一响应标准核心类
==============================

权威 ApiResponse 基类，同时支持 Pydantic v1/v2 和 dataclass 两种使用方式。

标准字段定义（项目级权威规范）：
  - code: int       - 状态码，0 表示成功，非 0 表示错误
  - message: str    - 状态描述
  - data: Any       - 响应数据（可选）
  - trace_id: str   - 链路追踪 ID（可选，统一使用 trace_id 而非 request_id）
  - timestamp: float - Unix 时间戳（秒级浮点数）

设计原则：
  1. 向后兼容：支持从各模块旧版本的响应格式平滑迁移
  2. Pydantic 兼容：优先使用 Pydantic v2，v1 也可工作；无 Pydantic 时回退到 dataclass
  3. 零依赖：核心类可独立使用，不依赖 FastAPI 等框架
  4. 与 6 位错误码体系兼容（shared/core/errors.py）
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Generic, Optional, TypeVar

from .constants import SUCCESS, ERR_INTERNAL, get_standard_message, get_http_status


# ============================================================
# Pydantic 版本检测与兼容层
# ============================================================

_pydantic_available = False
_pydantic_version = 0  # 1 或 2

try:
    import pydantic
    _pydantic_available = True
    _pydantic_version = int(pydantic.VERSION.split(".")[0])
except ImportError:
    pass


T = TypeVar("T")


# ============================================================
# 核心 ApiResponse 类（Pydantic 优先，无 Pydantic 时用 dataclass）
# ============================================================

if _pydantic_available and _pydantic_version >= 2:
    # ---- Pydantic v2 实现 ----
    from pydantic import BaseModel, Field, field_serializer

    class ApiResponse(BaseModel, Generic[T]):
        """项目级权威统一 API 响应格式（Pydantic v2 实现）.

        所有模块的 API 响应都应使用此格式，保持前后端契约一致。

        标准字段：
            code: 状态码，0 表示成功
            message: 状态描述
            data: 响应数据（成功时为业务数据，错误时可选）
            trace_id: 链路追踪 ID
            timestamp: Unix 时间戳（秒级浮点数）
        """

        code: int = Field(default=SUCCESS, description="状态码，0 表示成功")
        message: str = Field(default="ok", description="状态消息")
        data: Optional[T] = Field(default=None, description="响应数据")
        trace_id: Optional[str] = Field(default=None, description="链路追踪 ID")
        timestamp: float = Field(
            default_factory=time.time,
            description="Unix 时间戳（秒级）",
        )

        model_config = {
            "json_schema_extra": {
                "example": {
                    "code": 0,
                    "message": "ok",
                    "data": {"key": "value"},
                    "trace_id": "abc123",
                    "timestamp": 1700000000.0,
                }
            }
        }

        # ---- 工厂方法 ----

        @classmethod
        def success(
            cls,
            data: Any = None,
            message: str = "ok",
            trace_id: Optional[str] = None,
        ) -> "ApiResponse[T]":
            """创建成功响应.

            Args:
                data: 响应数据
                message: 成功描述（默认 "ok"）
                trace_id: 链路追踪 ID

            Returns:
                ApiResponse 实例，code 为 0
            """
            return cls(
                code=SUCCESS,
                message=message,
                data=data,
                trace_id=trace_id,
            )

        @classmethod
        def error(
            cls,
            code: int = ERR_INTERNAL,
            message: Optional[str] = None,
            data: Any = None,
            trace_id: Optional[str] = None,
        ) -> "ApiResponse[T]":
            """创建错误响应.

            Args:
                code: 错误码（默认 ERR_INTERNAL）
                message: 错误描述（为 None 时使用标准消息）
                data: 附加数据（可选）
                trace_id: 链路追踪 ID

            Returns:
                ApiResponse 实例
            """
            return cls(
                code=code,
                message=message if message is not None else get_standard_message(code),
                data=data,
                trace_id=trace_id,
            )

        # ---- 属性 ----

        @property
        def is_success(self) -> bool:
            """是否为成功响应."""
            return self.code == SUCCESS

        @property
        def http_status(self) -> int:
            """获取对应的 HTTP 状态码."""
            return get_http_status(self.code)

        # ---- 序列化方法 ----

        def to_dict(self) -> Dict[str, Any]:
            """转换为标准字典格式.

            Returns:
                包含所有字段的字典
            """
            return self.model_dump()

        @classmethod
        def from_dict(cls, d: Dict[str, Any]) -> "ApiResponse[T]":
            """从字典反序列化.

            Args:
                d: 源字典

            Returns:
                ApiResponse 实例
            """
            return cls.model_validate(d)

        def to_json(self, **kwargs) -> str:
            """序列化为 JSON 字符串.

            Args:
                **kwargs: 传递给 model_dump_json 的参数

            Returns:
                JSON 字符串
            """
            return self.model_dump_json(**kwargs)

        # ---- 链式方法 ----

        def with_data(self, data: Any) -> "ApiResponse[T]":
            """设置 data（链式调用）."""
            self.data = data
            return self

        def with_message(self, message: str) -> "ApiResponse[T]":
            """设置 message（链式调用）."""
            self.message = message
            return self

        def with_trace_id(self, trace_id: str) -> "ApiResponse[T]":
            """设置 trace_id（链式调用）."""
            self.trace_id = trace_id
            return self

        def with_code(self, code: int) -> "ApiResponse[T]":
            """设置 code（链式调用）."""
            self.code = code
            return self

elif _pydantic_available and _pydantic_version == 1:
    # ---- Pydantic v1 实现 ----
    from pydantic import BaseModel, Field  # type: ignore

    class ApiResponse(BaseModel, Generic[T]):  # type: ignore
        """项目级权威统一 API 响应格式（Pydantic v1 实现）.

        标准字段同 v2 版。
        """

        code: int = Field(default=SUCCESS, description="状态码，0 表示成功")
        message: str = Field(default="ok", description="状态消息")
        data: Optional[T] = Field(default=None, description="响应数据")
        trace_id: Optional[str] = Field(default=None, description="链路追踪 ID")
        timestamp: float = Field(
            default_factory=time.time,
            description="Unix 时间戳（秒级）",
        )

        class Config:
            schema_extra = {
                "example": {
                    "code": 0,
                    "message": "ok",
                    "data": {"key": "value"},
                    "trace_id": "abc123",
                    "timestamp": 1700000000.0,
                }
            }

        @classmethod
        def success(
            cls,
            data: Any = None,
            message: str = "ok",
            trace_id: Optional[str] = None,
        ) -> "ApiResponse[T]":
            """创建成功响应."""
            return cls(code=SUCCESS, message=message, data=data, trace_id=trace_id)

        @classmethod
        def error(
            cls,
            code: int = ERR_INTERNAL,
            message: Optional[str] = None,
            data: Any = None,
            trace_id: Optional[str] = None,
        ) -> "ApiResponse[T]":
            """创建错误响应."""
            return cls(
                code=code,
                message=message if message is not None else get_standard_message(code),
                data=data,
                trace_id=trace_id,
            )

        @property
        def is_success(self) -> bool:
            """是否为成功响应."""
            return self.code == SUCCESS

        @property
        def http_status(self) -> int:
            """获取对应的 HTTP 状态码."""
            return get_http_status(self.code)

        def to_dict(self) -> Dict[str, Any]:
            """转换为标准字典格式."""
            return self.dict()

        @classmethod
        def from_dict(cls, d: Dict[str, Any]) -> "ApiResponse[T]":
            """从字典反序列化."""
            return cls(**d)

        def to_json(self, **kwargs) -> str:
            """序列化为 JSON 字符串."""
            return self.json(**kwargs)

        def with_data(self, data: Any) -> "ApiResponse[T]":
            """设置 data（链式调用）."""
            self.data = data
            return self

        def with_message(self, message: str) -> "ApiResponse[T]":
            """设置 message（链式调用）."""
            self.message = message
            return self

        def with_trace_id(self, trace_id: str) -> "ApiResponse[T]":
            """设置 trace_id（链式调用）."""
            self.trace_id = trace_id
            return self

        def with_code(self, code: int) -> "ApiResponse[T]":
            """设置 code（链式调用）."""
            self.code = code
            return self

else:
    # ---- 无 Pydantic 时的 dataclass 回退实现 ----
    from dataclasses import dataclass, field

    @dataclass
    class ApiResponse(Generic[T]):
        """项目级权威统一 API 响应格式（dataclass 实现）.

        无 Pydantic 环境时的回退版本，保持完全相同的 API 接口。
        """

        code: int = SUCCESS
        message: str = "ok"
        data: Optional[T] = None
        trace_id: Optional[str] = None
        timestamp: float = field(default_factory=time.time)

        @classmethod
        def success(
            cls,
            data: Any = None,
            message: str = "ok",
            trace_id: Optional[str] = None,
        ) -> "ApiResponse[T]":
            """创建成功响应."""
            return cls(code=SUCCESS, message=message, data=data, trace_id=trace_id)

        @classmethod
        def error(
            cls,
            code: int = ERR_INTERNAL,
            message: Optional[str] = None,
            data: Any = None,
            trace_id: Optional[str] = None,
        ) -> "ApiResponse[T]":
            """创建错误响应."""
            return cls(
                code=code,
                message=message if message is not None else get_standard_message(code),
                data=data,
                trace_id=trace_id,
            )

        @property
        def is_success(self) -> bool:
            """是否为成功响应."""
            return self.code == SUCCESS

        @property
        def http_status(self) -> int:
            """获取对应的 HTTP 状态码."""
            return get_http_status(self.code)

        def to_dict(self) -> Dict[str, Any]:
            """转换为标准字典格式."""
            return {
                "code": self.code,
                "message": self.message,
                "data": self.data,
                "trace_id": self.trace_id,
                "timestamp": self.timestamp,
            }

        @classmethod
        def from_dict(cls, d: Dict[str, Any]) -> "ApiResponse[T]":
            """从字典反序列化."""
            return cls(
                code=d.get("code", SUCCESS),
                message=d.get("message", "ok"),
                data=d.get("data"),
                trace_id=d.get("trace_id"),
                timestamp=d.get("timestamp", time.time()),
            )

        def to_json(self, **kwargs) -> str:
            """序列化为 JSON 字符串."""
            import json
            return json.dumps(self.to_dict(), **kwargs)

        def with_data(self, data: Any) -> "ApiResponse[T]":
            """设置 data（链式调用）."""
            self.data = data
            return self

        def with_message(self, message: str) -> "ApiResponse[T]":
            """设置 message（链式调用）."""
            self.message = message
            return self

        def with_trace_id(self, trace_id: str) -> "ApiResponse[T]":
            """设置 trace_id（链式调用）."""
            self.trace_id = trace_id
            return self

        def with_code(self, code: int) -> "ApiResponse[T]":
            """设置 code（链式调用）."""
            self.code = code
            return self


# ============================================================
# 便捷工具函数
# ============================================================

def ok(
    data: Any = None,
    message: str = "ok",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """快速创建成功响应字典.

    Args:
        data: 响应数据
        message: 成功描述
        trace_id: 链路追踪 ID

    Returns:
        标准成功响应字典
    """
    return ApiResponse.success(data=data, message=message, trace_id=trace_id).to_dict()


def fail(
    code: int = ERR_INTERNAL,
    message: Optional[str] = None,
    data: Any = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """快速创建错误响应字典.

    Args:
        code: 错误码
        message: 错误描述（为 None 时使用标准消息）
        data: 附加数据
        trace_id: 链路追踪 ID

    Returns:
        标准错误响应字典
    """
    return ApiResponse.error(code=code, message=message, data=data, trace_id=trace_id).to_dict()


def generate_trace_id() -> str:
    """生成新的链路追踪 ID.

    Returns:
        32 位十六进制 trace_id 字符串
    """
    return uuid.uuid4().hex


# ============================================================
# 兼容性辅助：从旧格式迁移
# ============================================================

def from_legacy_response(d: Dict[str, Any]) -> ApiResponse:
    """从旧版响应格式转换为标准 ApiResponse.

    支持以下旧格式的自动适配：
    - 字段名 request_id -> trace_id
    - timestamp 为毫秒级整数 -> 转换为秒级浮点数
    - 缺少 trace_id/timestamp 字段 -> 自动补全

    Args:
        d: 旧版响应字典

    Returns:
        标准化的 ApiResponse 实例
    """
    result: Dict[str, Any] = {}

    # 标准字段映射
    result["code"] = d.get("code", 0)
    result["message"] = d.get("message", "ok")
    result["data"] = d.get("data")

    # trace_id 兼容：支持 trace_id 和 request_id
    trace_id = d.get("trace_id")
    if trace_id is None:
        trace_id = d.get("request_id")
    result["trace_id"] = trace_id

    # timestamp 兼容：支持秒级浮点数、秒级整数、毫秒级整数
    ts = d.get("timestamp")
    if ts is None:
        result["timestamp"] = time.time()
    elif isinstance(ts, float):
        result["timestamp"] = ts
    elif isinstance(ts, int):
        # 大于 1e12 认为是毫秒级，转换为秒级
        if ts > 1_000_000_000_000:
            result["timestamp"] = ts / 1000.0
        else:
            result["timestamp"] = float(ts)
    else:
        result["timestamp"] = time.time()

    return ApiResponse.from_dict(result)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ApiResponse",
    "ok",
    "fail",
    "generate_trace_id",
    "from_legacy_response",
    "T",
]
