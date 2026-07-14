"""
隐私卫士 — privacy 子包

重新导出所有符号，保持与原始 privacy_guard.py 完全兼容。
"""

from __future__ import annotations

from .types import (
    PII_PATTERNS,
    PII_SEVERITY,
    SEVERITY_WEIGHT,
    SECURITY_LEVEL_WEIGHT,
)
from .detector import PIIDetector
from .sanitizer import Sanitizer
from .classifier import RiskClassifier
from .guard import (
    PrivacyGuard,
    FederationPrivacyGuard,
    _LegacyScanResult,
    _patch_legacy_methods,
)

__all__ = [
    "PII_PATTERNS",
    "PII_SEVERITY",
    "SEVERITY_WEIGHT",
    "SECURITY_LEVEL_WEIGHT",
    "PIIDetector",
    "Sanitizer",
    "RiskClassifier",
    "PrivacyGuard",
    "FederationPrivacyGuard",
    "_LegacyScanResult",
    "_patch_legacy_methods",
]