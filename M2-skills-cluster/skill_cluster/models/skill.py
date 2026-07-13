"""M2 技能集群 - 技能领域模型.

包含技能清单、查询条件、调用请求/结果、集群配置等核心数据模型。
所有模型均继承自 M2BaseModel，保持全局配置一致。
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator  # noqa: F401

from skill_cluster.models.base import M2BaseModel


class SkillManifest(M2BaseModel):
    """技能清单，描述技能的元数据."""

    skill_id: str = Field(..., description="全局唯一标识，如 skill.doc_proc")
    name: str = Field(..., description="人类可读名称")
    version: str = Field(..., description="语义化版本，如 1.0.0")
    description: str = Field(..., description="能力描述")
    author: str = Field(..., description="作者")
    tags: list[str] = Field(default_factory=list, description="技能标签")
    capabilities: list[str] = Field(default_factory=list, description="细粒度能力列表")
    dependencies: list[str] = Field(default_factory=list, description="依赖的其他 skill_id")
    permissions: list[str] = Field(default_factory=list, description="需要的权限标识")
    entrypoint: str = Field(..., description="技能入口类名")
    config_schema: dict | None = Field(default=None, description="JSON Schema 配置校验模板")

    @field_validator("skill_id")
    @classmethod
    def _validate_skill_id(cls, v: str) -> str:
        if not v.startswith("skill."):
            raise ValueError("skill_id 必须以 'skill.' 开头")
        return v

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        pattern = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
        if not re.match(pattern, v):
            raise ValueError(f"version 必须符合语义化版本规范: {v}")
        return v


class SkillQuery(M2BaseModel):
    """技能查询条件."""

    name: str | None = Field(default=None, description="按名称模糊匹配")
    tags: list[str] | None = Field(default=None, description="按标签过滤")
    capability: str | None = Field(default=None, description="按能力描述匹配")
    semantic_query: str | None = Field(default=None, description="语义查询字符串")


class SkillInvokeRequest(M2BaseModel):
    """技能调用请求.

    【第四轮优化】新增 MCP 2026 兼容字段：
    - cache_scope: 缓存作用域（"public"/"private"）
    - ttl_ms: 毫秒级 TTL
    - metadata: 扩展元数据
    """

    skill_id: str = Field(..., description="目标技能 ID")
    action: str = Field(..., description="技能内部动作标识")
    params: dict[str, Any] = Field(default_factory=dict, description="动作参数")
    trace_id: str = Field(..., description="调用链路追踪 ID")
    timeout: int | None = Field(default=None, description="调用超时（秒）")
    # MCP 2026 兼容字段
    cache_scope: str = Field(default="public", description="缓存作用域: public/private")
    ttl_ms: int | None = Field(default=None, description="毫秒级 TTL（MCP 2026 标准）")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")
    device_type: str = Field(default="desktop", description="设备类型: watch/ring/desktop/drone")


class SkillInvokeResult(M2BaseModel):
    """技能调用结果."""

    skill_id: str = Field(..., description="技能 ID")
    action: str = Field(..., description="动作标识")
    status: Literal["success", "failure", "unauthorized", "not_found", "timeout"] = Field(
        ..., description="调用状态"
    )
    data: dict | None = Field(default=None, description="返回数据")
    error: str | None = Field(default=None, description="错误信息")
    latency_ms: float = Field(..., description="调用延迟（毫秒）")
    trace_id: str = Field(..., description="调用链路追踪 ID")


class SkillConfig(M2BaseModel):
    """技能集群配置."""

    default_timeout: int = Field(default=30, description="默认调用超时（秒）")
    max_batch_size: int = Field(default=100, description="最大批量调用数量")
    cache_ttl_days: int = Field(default=7, description="缓存 TTL（天）")
    data_row_limit: int = Field(default=100000, description="数据量限制")
    response_size_limit_mb: int = Field(default=10, description="响应大小限制（MB）")
