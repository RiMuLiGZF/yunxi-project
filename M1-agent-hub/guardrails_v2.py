"""
[兼容存根] guardrails_v2 已迁移至 src/security/guardrails.py

迁移说明：
- 原模块：guardrails_v2.py（根目录）
- 新位置：src/security/guardrails.py
- 推荐导入：from src.security.guardrails import GuardrailsV2
- 或从包导入：from src.security import GuardrailsV2

本文件为向后兼容存根，保留旧导入路径的可用性，
后续版本将移除，请尽快迁移到新的导入路径。
"""

from __future__ import annotations

import warnings

# 发出弃用警告
warnings.warn(
    "guardrails_v2 模块已迁移至 src.security.guardrails，"
    "请更新导入路径为 'from src.security.guardrails import ...'。"
    "当前存根将在未来版本中移除。",
    DeprecationWarning,
    stacklevel=2,
)

from src.security.guardrails import (  # noqa: F401
    GuardrailsV2,
    GuardrailsResult,
    PromptInjectionDetector,
    PIISanitizer,
)

__all__ = [
    "GuardrailsV2",
    "GuardrailsResult",
    "PromptInjectionDetector",
    "PIISanitizer",
]
