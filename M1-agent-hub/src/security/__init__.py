"""
安全审计与涉密拦截子Agent（Security-Agent）

集成 GuardrailsV2 + SecurityClassifier + AuditLog，
提供输入安检、内容分级、权限预检、审计留痕等安全能力。
"""

from src.security.agent import SecurityAgent
from src.security.classifier import SecurityClassifier
from src.security.audit_log import AuditLog, AuditEntry
from src.security.guardrails import GuardrailsV2, GuardrailsResult, PromptInjectionDetector, PIISanitizer
from src.security.guardrail_pipeline import (
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
    # Security Agent
    "SecurityAgent",
    "SecurityClassifier",
    "AuditLog",
    "AuditEntry",
    # Guardrails V2 (输入护栏)
    "GuardrailsV2",
    "GuardrailsResult",
    "PromptInjectionDetector",
    "PIISanitizer",
    # Guardrails V1 (护栏管线)
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
