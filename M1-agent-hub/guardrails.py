"""
[兼容存根] guardrails 已迁移至 src/security/guardrail_pipeline.py

迁移说明：
- 原模块：guardrails.py（根目录，V1 护栏管线系统）
- 新位置：src/security/guardrail_pipeline.py
- 推荐导入：from src.security.guardrail_pipeline import GuardrailPipeline, create_default_pipeline
- 或从包导入：from src.security import GuardrailPipeline

本文件为向后兼容存根，保留旧导入路径的可用性，
后续版本将移除，请尽快迁移到新的导入路径。
"""

from __future__ import annotations

import warnings

# 发出弃用警告
warnings.warn(
    "guardrails 模块已迁移至 src.security.guardrail_pipeline，"
    "请更新导入路径为 'from src.security.guardrail_pipeline import ...'。"
    "当前存根将在未来版本中移除。",
    DeprecationWarning,
    stacklevel=2,
)

from src.security.guardrail_pipeline import (  # noqa: F401
    GuardrailResult,
    Guardrail,
    ContentLengthGuardrail,
    SensitiveInfoGuardrail,
    KeywordBlockGuardrail,
    EmotionalRiskGuardrail,
    RateLimitGuardrail,
    GuardrailPipeline,
    create_default_pipeline,
)

__all__ = [
    "GuardrailResult",
    "Guardrail",
    "ContentLengthGuardrail",
    "SensitiveInfoGuardrail",
    "KeywordBlockGuardrail",
    "EmotionalRiskGuardrail",
    "RateLimitGuardrail",
    "GuardrailPipeline",
    "create_default_pipeline",
]
