"""M2 技能集群 - 扩展领域模型.

包含钩子注册、技能图谱、函数模式、Token 预算等扩展机制相关的
Pydantic 数据模型。这些模型用于支撑技能集群的扩展能力，
包括插件化、图谱分析、LLM function calling、预算控制等。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Awaitable

from pydantic import Field

from skill_cluster.models.base import M2BaseModel


# ---- 钩子相关 ----

class HookRegistration(M2BaseModel):
    """钩子注册信息."""

    hook_name: str = Field(..., description="钩子点名称")
    handler: Callable[[dict[str, Any]], Awaitable[Any]]
    priority: int = Field(default=100, description="优先级，数字越小优先级越高")
    description: str = Field(default="", description="钩子描述")

    model_config = {"arbitrary_types_allowed": True}


# ---- 技能图谱相关 ----

class GraphEdge(M2BaseModel):
    """图谱边（依赖关系）."""

    source: str = Field(..., description="源技能 ID")
    target: str = Field(..., description="目标技能 ID")
    edge_type: str = Field(
        default="depends_on",
        description="边类型: depends_on / composed_of / provides_to",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")


class ComposableChain(M2BaseModel):
    """可组合技能链.

    由图谱自动发现的一条技能执行路径。
    """

    chain_id: str = Field(..., description="链唯一标识")
    skills: list[str] = Field(..., description="技能 ID 序列（有序）")
    total_steps: int = Field(..., description="总步骤数")
    description: str = Field(default="", description="链描述")
    confidence: float = Field(
        default=1.0, description="组合置信度 (0-1)"
    )


# ---- 函数模式相关 ----

class FunctionParameter(M2BaseModel):
    """函数参数定义."""

    name: str = Field(..., description="参数名")
    type: str = Field(..., description="JSON Schema 类型")
    description: str = Field(default="", description="参数描述")
    required: bool = Field(default=True, description="是否必填")
    default: Any = Field(default=None, description="默认值")
    enum: list[Any] | None = Field(default=None, description="枚举值")


class FunctionSchema(M2BaseModel):
    """符合 OpenAI function calling 规范的函数模式."""

    name: str = Field(..., description="函数名，格式: skill_id__action")
    description: str = Field(..., description="函数描述")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema 参数定义"
    )

    def to_openai_format(
        self, strict: bool = False, additional_properties: bool = True
    ) -> dict[str, Any]:
        """转换为 OpenAI tools 格式.

        Args:
            strict: 是否启用 OpenAI Structured Outputs 严格模式（2025+）.
            additional_properties: parameters 中是否允许额外属性.

        Returns:
            OpenAI tools 格式字典.
        """
        parameters = dict(self.parameters)
        if not additional_properties:
            parameters["additionalProperties"] = False
        if strict:
            parameters.setdefault("additionalProperties", False)

        result = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }
        if strict:
            result["function"]["strict"] = True
        return result

    def to_anthropic_format(self) -> dict[str, Any]:
        """转换为 Anthropic tool_use 格式."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


class ActionSignature(M2BaseModel):
    """Action 签名描述."""

    action: str = Field(..., description="动作标识")
    description: str = Field(..., description="动作描述")
    parameters: list[FunctionParameter] = Field(
        default_factory=list, description="参数列表"
    )
    returns: dict[str, Any] = Field(
        default_factory=dict, description="返回值 JSON Schema"
    )


# ---- Token 预算相关 ----

class BudgetEntry(M2BaseModel):
    """预算条目."""

    category: str = Field(..., description="消耗类别: input/output/tool/think")
    tokens: int = Field(..., description="Token 数量")
    timestamp: float = Field(default_factory=time.time, description="时间")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")


class BudgetAlert(M2BaseModel):
    """预算告警."""

    alert_type: str = Field(..., description="告警类型: warning/exceeded/exhausted")
    message: str = Field(..., description="告警消息")
    total_tokens: int = Field(..., description="当前总消耗")
    budget_limit: int = Field(..., description="预算上限")
    remaining: int = Field(..., description="剩余 Token")
    timestamp: float = Field(default_factory=time.time, description="时间")
