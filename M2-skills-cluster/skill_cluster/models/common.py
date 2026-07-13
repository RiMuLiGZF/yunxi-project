"""M2 技能集群 - 通用 API 模型.

包含 v2 API 的请求/响应模型、统计模型、列表项模型等。
这些模型主要用于 HTTP API 层的入参校验和出参序列化。

注意：
    此处的 ``SkillInvokeRequest`` 是 API 层入参模型，
    与 ``skill_cluster.models.skill.SkillInvokeRequest``（内部调用模型）
    字段不同，不可混用。API 层会将其转换为内部调用模型。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from skill_cluster.models.base import M2BaseModel


# ---- 通用响应模型 ----

class ApiResponse(M2BaseModel):
    """标准API响应."""

    code: int = Field(..., description="状态码，20000表示成功")
    message: str = Field(..., description="消息")
    data: Any = Field(default=None, description="数据")
    trace_id: str = Field(default="", description="追踪ID")
    success: bool = Field(default=True, description="是否成功")


# ---- 请求模型 ----

class SkillInvokeRequest(M2BaseModel):
    """技能调用请求（API 层入参模型）.

    注意：这是 API 层的请求模型，与核心调用模型
    :class:`skill_cluster.models.skill.SkillInvokeRequest` 不同。
    API 层会将此模型转换为内部调用模型后再执行。
    """

    skill_id: str = Field(..., description="技能ID")
    action: str = Field(default="default", description="动作标识")
    params: dict[str, Any] = Field(default_factory=dict, description="参数")
    agent_id: str = Field(default="default_agent", description="Agent ID")
    device_type: str = Field(default="default", description="设备类型")
    timeout: int | None = Field(default=None, description="超时(秒)")


class BatchInvokeRequest(M2BaseModel):
    """批量调用请求."""

    requests: list[SkillInvokeRequest] = Field(..., description="调用请求列表")
    parallel: bool = Field(default=False, description="是否并行执行")


class RecommendTestRequest(M2BaseModel):
    """推荐测试请求."""

    query: str = Field(..., description="用户输入查询")
    scene_type: str = Field(default="DEFAULT", description="场景类型")
    top_k: int = Field(default=5, description="返回Top N")
    user_id: str = Field(default="", description="用户ID")


class SkillToggleRequest(M2BaseModel):
    """技能开关请求."""

    enabled: bool = Field(..., description="是否启用")


# ---- 响应数据模型 ----

class SkillItem(M2BaseModel):
    """技能列表项."""

    skill_id: str
    name: str
    description: str
    category: str
    tags: list[str] = Field(default_factory=list)
    version: str = ""
    enabled: bool = True
    usage_count: int = 0


class SkillDetail(SkillItem):
    """技能详情."""

    actions: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    author: str = ""
    complexity_score: float = 1.0
    created_at: float = 0.0
    last_used_at: float = 0.0


class RecommendResultItem(M2BaseModel):
    """推荐结果项."""

    skill_id: str
    skill_name: str
    description: str
    category: str
    confidence: str
    score: float
    match_reason: str


class AccuracyStats(M2BaseModel):
    """准确率统计."""

    top1_accuracy: float = 0.0
    top3_accuracy: float = 0.0
    top5_accuracy: float = 0.0
    total_tests: int = 0
    correct_top1: int = 0
    correct_top3: int = 0
    correct_top5: int = 0


class InvokeStats(M2BaseModel):
    """调用统计."""

    total_calls: int = 0
    success_count: int = 0
    failed_count: int = 0
    avg_latency_ms: float = 0.0
    today_calls: int = 0
    top_skills: list[dict[str, Any]] = Field(default_factory=list)


class SystemStats(M2BaseModel):
    """系统统计."""

    total_skills: int = 0
    enabled_skills: int = 0
    categories: list[dict[str, Any]] = Field(default_factory=list)
    active_sessions: int = 0
    uptime_seconds: float = 0.0
