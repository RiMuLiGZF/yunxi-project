"""模型基类.

定义 EdgeCloudBaseModel 作为所有 Pydantic 模型的统一基类，
提供一致的 model_config 配置和通用工具方法。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EdgeCloudBaseModel(BaseModel):
    """端云协同内核模型基类.

    所有数据模型统一继承此类，确保：
    - 统一的模型配置（model_config）
    - 一致的序列化/反序列化行为
    - 可扩展的通用工具方法

    Attributes:
        model_config: Pydantic 模型配置，启用 populate_by_name 等。
    """

    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=False,
        validate_assignment=False,
        extra="ignore",
        frozen=False,
    )
