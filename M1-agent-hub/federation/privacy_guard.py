"""
隐私卫士 — PrivacyGuard 兼容层

此文件是 federation.privacy 子包的兼容导入层。
所有实际逻辑已迁移至 federation/privacy/ 子包。
此处仅做符号重导出，保持 `from federation.privacy_guard import ...` 继续可用。
"""

from __future__ import annotations

# 从 privacy 子包重新导出所有公开符号
from .privacy import *

__all__ = [
    "PII_PATTERNS",
    "PII_SEVERITY",
    "SEVERITY_WEIGHT",
    "SECURITY_LEVEL_WEIGHT",
    "PrivacyGuard",
    "FederationPrivacyGuard",
    "_LegacyScanResult",
    "_patch_legacy_methods",
]