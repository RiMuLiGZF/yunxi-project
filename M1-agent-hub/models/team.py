"""
云汐内核 V10.0 — 组队与仲裁模型

组队方案、负载评分、仲裁请求/结果等模型。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from models.enums import ArbitrationLevel, SecurityClassification


@dataclass
class LoadScore:
    """
    负载评分（综合VRAM/CPU/电量/网络）

    评分算法为技术秘密，具体权重参数不在代码注释中暴露。
    """
    agent_id: str = ""
    vram_score: float = 0.0
    cpu_score: float = 0.0
    battery_score: float = 0.0
    network_score: float = 0.0
    composite: float = 0.0  # 综合评分（内部聚合）
    timestamp: float = field(default_factory=time.time)


class TeamComposition(BaseModel):
    """动态组队方案"""
    team_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    members: list[str] = Field(default_factory=list)  # agent_id列表
    roles: dict[str, str] = Field(default_factory=dict)  # agent_id -> role
    formation_reason: str = ""
    security_level: SecurityClassification = SecurityClassification.INTERNAL
    created_at: float = Field(default_factory=time.time)


class ArbitrationRequest(BaseModel):
    """仲裁请求"""
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    conflict_type: str = ""  # resource_deadlock | priority_conflict | dependency_cycle | timeout
    involved_agents: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class ArbitrationResult(BaseModel):
    """仲裁结果"""
    request_id: str = ""
    level: ArbitrationLevel = ArbitrationLevel.AUTO_RESOLVE
    decision: str = ""  # retry | abort | reroute | escalate | negotiate
    assigned_agent: str = ""
    reason: str = ""
    actions: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)


class HealthStatusDict(TypedDict):
    """健康状态 TypedDict

    用于健康监控系统的状态结构化字典表示。
    """
    status: str                    # up / down / degraded / unknown
    timestamp: float
    latency_ms: float
    details: dict[str, Any]
    error: str | None
    level: str                     # liveness / readiness / deep
    component_type: str            # database / message_bus / memory / disk / circuit_breaker / custom
    threshold: dict[str, Any]