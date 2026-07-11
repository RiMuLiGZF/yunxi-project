"""推理执行子包.

包含端云协同三大核心组件：
- LocalInferenceExecutor: 本地推理执行器（对接 Ollama）
- CloudInferenceExecutor: 云端推理执行器（对接 OpenAI 兼容 API）
- RouteDecisionEngine: 路由决策引擎（多因子加权评分）
"""

from __future__ import annotations

from edge_cloud_kernel.execution.cloud_executor import CloudInferenceExecutor
from edge_cloud_kernel.execution.local_executor import LocalInferenceExecutor
from edge_cloud_kernel.execution.route_engine import (
    PrivacyLevel,
    RouteDecisionEngine,
    TaskComplexity,
    UrgencyLevel,
)

__all__ = [
    "LocalInferenceExecutor",
    "CloudInferenceExecutor",
    "RouteDecisionEngine",
    "PrivacyLevel",
    "TaskComplexity",
    "UrgencyLevel",
]
