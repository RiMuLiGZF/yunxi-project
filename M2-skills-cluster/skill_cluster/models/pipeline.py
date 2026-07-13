"""M2 技能集群 - 流水线模型.

包含流水线步骤、流水线定义、流水线执行上下文等模型。
支持声明式定义 Skill 之间的串联、并联、条件分支、循环执行模式。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import Field

from skill_cluster.models.base import M2BaseModel
from skill_cluster.models.skill import SkillInvokeResult


class PipelineStep(M2BaseModel):
    """流水线单步定义."""

    step_id: str = Field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    skill_id: str = Field(..., description="技能 ID")
    action: str = Field(..., description="动作标识")
    params: dict = Field(default_factory=dict, description="静态参数")
    params_mapping: dict[str, str] | None = Field(
        default=None,
        description="参数映射: {'上游step_id.output_key': '本step参数名'}",
    )
    condition: str | None = Field(
        default=None,
        description="执行条件表达式，如 'upstream.step_id.status == success'",
    )
    timeout: int | None = Field(default=None, description="超时（秒）")


class PipelineDefinition(M2BaseModel):
    """流水线定义."""

    pipeline_id: str = Field(..., description="流水线唯一标识")
    name: str = Field(..., description="名称")
    description: str = Field(default="", description="描述")
    steps: list[PipelineStep] = Field(default_factory=list, description="步骤列表")
    mode: Literal["sequential", "parallel", "dag"] = Field(
        default="sequential", description="执行模式"
    )
    max_parallelism: int = Field(default=5, description="最大并行度")


class PipelineContext(M2BaseModel):
    """流水线执行上下文."""

    pipeline_id: str = Field(..., description="流水线 ID")
    run_id: str = Field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")
    trace_id: str = Field(..., description="调用链路追踪 ID")
    agent_id: str = Field(..., description="Agent 标识")
    step_results: dict[str, SkillInvokeResult] = Field(
        default_factory=dict, description="各步骤执行结果"
    )
    variables: dict[str, Any] = Field(
        default_factory=dict, description="全局变量池"
    )
    status: Literal["running", "success", "failure", "cancelled"] = Field(
        default="running"
    )
    started_at: float = Field(default_factory=time.time)
    finished_at: float | None = Field(default=None)
