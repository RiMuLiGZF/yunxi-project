"""
M1 Agent 集群 - Pydantic 模型基类

所有 M1 模块的 Pydantic 模型统一继承自 M1BaseModel，
确保全局一致的配置、序列化行为与校验规则。
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


def _get_extra_behavior() -> str:
    """获取 extra 字段行为配置。

    通过环境变量 M1_MODELS_EXTRA 控制：
    - forbid: 严格模式，禁止额外字段（默认）
    - allow: 宽松模式，允许额外字段（向后兼容）
    - ignore: 忽略额外字段

    Returns:
        extra 配置值
    """
    value = os.environ.get("M1_MODELS_EXTRA", "forbid").lower()
    if value in ("forbid", "allow", "ignore"):
        return value
    return "forbid"


def _custom_json_encoder(obj: Any) -> Any:
    """自定义 JSON 编码器。

    处理 Pydantic 默认不支持的类型序列化。

    Args:
        obj: 待序列化的对象

    Returns:
        序列化后的值

    Raises:
        TypeError: 不支持的类型
    """
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class M1BaseModel(BaseModel):
    """M1 模块统一 Pydantic 模型基类。

    提供全局一致的模型配置：
    - 严格模式：默认禁止额外字段（可通过环境变量配置为 allow）
    - 别名支持：支持通过字段名或别名赋值
    - 枚举值序列化：序列化时使用枚举的 value 而非枚举对象
    - 自定义编码器：处理 datetime、Decimal、set 等特殊类型

    配置可通过环境变量调整：
    - M1_MODELS_EXTRA=forbid|allow|ignore  控制额外字段行为

    Attributes:
        model_config: Pydantic 模型配置字典
    """

    model_config = ConfigDict(
        extra=_get_extra_behavior(),
        populate_by_name=True,
        use_enum_values=True,
        json_encoders={
            datetime: _custom_json_encoder,
            date: _custom_json_encoder,
            Decimal: _custom_json_encoder,
            set: _custom_json_encoder,
            bytes: _custom_json_encoder,
        },
        validate_assignment=False,
        arbitrary_types_allowed=False,
    )

    def model_dump_safe(self, **kwargs: Any) -> dict[str, Any]:
        """安全地导出为字典（总是成功，失败时返回空字典）。

        用于日志、调试等容错场景，避免序列化异常导致程序崩溃。

        Args:
            **kwargs: 传递给 model_dump 的参数

        Returns:
            模型字段字典
        """
        try:
            return self.model_dump(**kwargs)
        except Exception:
            return {}

    def model_dump_json_safe(self, **kwargs: Any) -> str:
        """安全地导出为 JSON 字符串（总是成功，失败时返回空对象 JSON）。

        用于日志、调试等容错场景。

        Args:
            **kwargs: 传递给 model_dump_json 的参数

        Returns:
            JSON 字符串
        """
        try:
            return self.model_dump_json(**kwargs)
        except Exception:
            return "{}"
