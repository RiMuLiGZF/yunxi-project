"""M2 技能集群 - Pydantic 模型基类.

提供统一的 M2BaseModel 基类，所有领域模型均继承自此基类，
确保全局 model_config 配置一致，并预留扩展点（如自定义序列化、
字段别名、JSON schema 定制等）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class M2BaseModel(BaseModel):
    """M2 技能集群统一 Pydantic 基类.

    所有 Pydantic 模型均应继承此类，以获得一致的配置与行为：

    - ``populate_by_name``: 同时支持字段名和 alias 赋值
    - ``use_attribute_docstrings``: 使用属性 docstring 作为字段描述
    - 预留扩展点：可在此统一添加序列化钩子、字段校验等

    注意：
        为保持向后兼容，未启用 ``extra='forbid'``，允许额外字段透传。
        若后续需要严格模式，可在子类中覆盖 model_config。
    """

    model_config = ConfigDict(
        populate_by_name=True,
        use_attribute_docstrings=True,
        validate_assignment=False,
        extra="allow",
    )
