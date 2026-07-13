"""
M1 Agent 集群 - 联邦调度模型

联邦调度系统相关的 Pydantic 请求/响应模型。
迁移自 api/server.py 中的联邦调度模型定义。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from models.base import M1BaseModel


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
