"""
M1 Agent 集群 - 联邦调度模型

联邦调度系统相关的 Pydantic 请求/响应模型。
包含从 shared_models 迁移的联邦调度核心模型。
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from models.base import M1BaseModel
from models.enums import (
    ComparisonOutputMode,
    ConnectionType,
    ExternalAgentType,
    AgentPrivacyLevel,
    LicenseType,
    UserPreferenceMode,
    SecurityClassification,
)


class FedRegisterRequest(M1BaseModel):
    """注册外部 Agent 请求。

    字段边界校验：
    - display_name: 最长 128 字符
    - provider: 最长 64 字符
    - agent_type: 枚举值（llm/code/design/search/tool/custom）
    """

    display_name: str = Field(default="", max_length=128)
    provider: str = Field(default="", max_length=64)
    agent_type: Literal["llm", "code", "design", "search", "tool", "custom"] = "llm"
    capabilities: list[str] = []
    privacy_level: str = "standard"
    connection_type: str = "api_key"
    config: dict[str, Any] = {}
    api_key: str = ""


class FedInvokeRequest(M1BaseModel):
    """调用外部 Agent 请求。

    字段边界校验：
    - agent_id: 最长 64 字符
    - prompt: 最长 100000 字符
    - system_prompt: 最长 50000 字符
    - temperature: 0~2 浮点数
    - max_tokens: 1~32768 整数
    """

    agent_id: str = Field(default="", max_length=64)
    prompt: str = Field(default="", max_length=100000)
    system_prompt: str = Field(default="", max_length=50000)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=32768)
    security_level: str = "PUBLIC"


class FedDecideRequest(M1BaseModel):
    """联邦调度决策请求。

    字段边界校验：
    - remaining_budget: >= -1（-1 表示不限制）
    - task_complexity: 0~1 浮点数
    """

    task_type: str = "general"
    security_level: str = "PUBLIC"
    user_preference: str = "balanced"
    remaining_budget: float = Field(default=-1.0, ge=-1.0)
    speed_requirement: str = "medium"
    task_complexity: float = Field(default=0.5, ge=0.0, le=1.0)


class FedCompareRequest(M1BaseModel):
    """Agent 对比请求。

    字段边界校验：
    - prompt: 最长 100000 字符
    - system_prompt: 最长 50000 字符
    - temperature: 0~2 浮点数
    - max_tokens: 1~32768 整数
    """

    agent_ids: list[str] = []
    prompt: str = Field(default="", max_length=100000)
    system_prompt: str = Field(default="", max_length=50000)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=32768)
    output_mode: str = "best_only"
    task_type: str = "general"


class FedPrivacyScanRequest(M1BaseModel):
    """隐私扫描请求。

    字段边界校验：
    - content: 最长 100000 字符
    """

    content: str = Field(default="", max_length=100000)
    security_level: str = "PUBLIC"
    task_type: str = "general"


class FedBudgetRequest(M1BaseModel):
    """预算设置请求。

    字段边界校验：
    - monthly_budget: 0~100000 浮点数
    """

    monthly_budget: float = Field(default=10.0, ge=0, le=100000)


# ══════════════════════════════════════════════════════════
# 联邦调度核心模型（从 shared_models 迁移）
# ══════════════════════════════════════════════════════════


class CostModel(BaseModel):
    """外部 Agent 成本模型"""
    input_per_1k: float = 0.0     # 输入单价（美元/1K tokens）
    output_per_1k: float = 0.0    # 输出单价（美元/1K tokens）
    currency: str = "USD"
    per_request: float = 0.0      # 每次请求固定费用


class ExternalAgentProfile(BaseModel):
    """外部 Agent 能力画像"""
    agent_id: str = ""
    display_name: str = ""
    provider: str = ""              # 服务商名称
    agent_type: ExternalAgentType = ExternalAgentType.LLM
    capabilities: list[str] = Field(default_factory=list)  # 能力标签
    languages: list[str] = Field(default_factory=lambda: ["zh", "en"])
    response_speed: str = "medium"  # fast / medium / slow
    quality_rating: float = 4.0     # 1-5 质量评分
    cost_model: CostModel = Field(default_factory=CostModel)
    privacy_level: AgentPrivacyLevel = AgentPrivacyLevel.STANDARD
    connection_type: ConnectionType = ConnectionType.API_KEY
    license: LicenseType = LicenseType.OTHER
    status: str = "active"          # active / inactive / error
    config: dict[str, Any] = Field(default_factory=dict)  # 连接配置（不含密钥）
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    last_health_check: float | None = None


class FederationDecision(BaseModel):
    """联邦调度决策结果"""
    use_external: bool = False
    selected_agent_id: str = ""
    selected_agent_name: str = ""
    decision_reason: str = ""
    estimated_cost: float = 0.0     # 预估费用（美元）
    estimated_latency: str = "medium"
    privacy_check: str = "passed"   # passed / warning / blocked
    quality_score: float = 0.0      # 综合评分 0-100
    fallback_agent_id: str = ""     # 备选 Agent


class AgentResultItem(BaseModel):
    """单 Agent 结果条目"""
    agent_id: str = ""
    agent_name: str = ""
    output: str = ""
    quality_score: float = 0.0      # 0-100
    cost: float = 0.0
    latency_ms: float = 0.0
    success: bool = True
    error: str = ""


class MultiAgentComparison(BaseModel):
    """多 Agent 对比结果"""
    task_id: str = ""
    results: list[AgentResultItem] = Field(default_factory=list)
    best_result_index: int = 0
    fusion_output: str = ""         # 融合输出（可选）
    output_mode: ComparisonOutputMode = ComparisonOutputMode.BEST_ONLY
    comparison_summary: str = ""
    total_cost: float = 0.0


class CostRecord(BaseModel):
    """成本记录"""
    record_id: str = ""
    task_id: str = ""
    agent_id: str = ""
    agent_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    currency: str = "USD"
    timestamp: float = Field(default_factory=time.time)
    task_type: str = ""
    success: bool = True


class FederationBudget(BaseModel):
    """联邦调度预算"""
    monthly_budget: float = 10.0    # 月度预算（美元）
    spent_this_month: float = 0.0   # 本月已花费
    alert_threshold_50: bool = False
    alert_threshold_80: bool = False
    alert_threshold_100: bool = False
    currency: str = "USD"
    last_reset_month: str = ""      # YYYY-MM


class PrivacyScanResult(BaseModel):
    """隐私扫描结果"""
    passed: bool = True
    risk_level: str = "none"        # none / low / medium / high
    detections: list[dict[str, Any]] = Field(default_factory=list)
    sanitized_content: str = ""     # 脱敏后的内容
    blocked: bool = False
    block_reason: str = ""
    summary: str = ""
