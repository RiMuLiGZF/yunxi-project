"""
隐私卫士 — 数据类型定义

包含 PII 检测正则模式、严重程度分级、权重配置等常量定义。
"""

from __future__ import annotations

import re

from shared_models import SecurityClassification


# ══════════════════════════════════════════════════════════
# PII 检测正则模式（V11.1 增强版）
# ══════════════════════════════════════════════════════════

PII_PATTERNS: dict[str, re.Pattern] = {
    # 邮箱 — 支持大小写、子域名、+号
    "email": re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        re.IGNORECASE,
    ),

    # 中国大陆手机号 — 支持 +86 前缀、空格、-分隔
    # 使用边界断言防止误匹配身份证/银行卡中的数字段
    "phone_cn": re.compile(
        r"(?<!\d)(?:\+?86[\s\-]?)?1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4}(?!\d)",
    ),

    # 中国大陆身份证号 — 18位（含末位X）和 15位
    "id_card_cn": re.compile(
        r"(?:[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx])"
        r"|(?:[1-9]\d{7}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3})",
    ),

    # 银行卡号 — 13-19 位数字，支持空格分隔
    "bank_card": re.compile(
        r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{1,3}(?:[\s\-]?\d{3})?\b",
    ),

    # API Key — 常见格式（sk-、ak-、api_key= 等）
    "api_key": re.compile(
        r"(?:sk-|ak-|api[_-]?key\s*[:=]\s*|secret[_-]?key\s*[:=]\s*)"
        r"[A-Za-z0-9_\-]{16,}",
        re.IGNORECASE,
    ),

    # 密码 — password/passwd/pwd = xxx 形式
    "password": re.compile(
        r"(?:password|passwd|pwd)\s*[:=]\s*[^\s,;\"'`]{6,}",
        re.IGNORECASE,
    ),

    # Token — Bearer token、access_token 等
    "token": re.compile(
        r"(?:Bearer\s+|access[_-]?token\s*[:=]\s*|auth[_-]?token\s*[:=]\s*)"
        r"[A-Za-z0-9_\-\.]{16,}",
        re.IGNORECASE,
    ),

    # 私钥 — PEM 格式私钥头
    "private_key": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
        r"[\s\S]+?"
        r"-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        re.IGNORECASE,
    ),

    # 内网 URL — 10.x、172.16-31.x、192.168.x、localhost
    "url_internal": re.compile(
        r"https?://"
        r"(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|127\.0\.0\.1"
        r"|localhost"
        r"|internal[-\w]*\.local"
        r")"
        r"(?::\d{1,5})?"
        r"(?:[/?#][^\s]*)?",
        re.IGNORECASE,
    ),
}

# PII 严重程度分级（单类 PII 的基础风险）
PII_SEVERITY: dict[str, str] = {
    "email": "medium",
    "phone_cn": "high",
    "id_card_cn": "critical",
    "bank_card": "critical",
    "api_key": "critical",
    "password": "critical",
    "token": "high",
    "private_key": "critical",
    "url_internal": "medium",
    "custom_keyword": "medium",
}

# 严重程度权重（用于综合评分）
SEVERITY_WEIGHT: dict[str, float] = {
    "critical": 10.0,
    "high": 5.0,
    "medium": 2.0,
    "low": 1.0,
}

# 涉密等级权重
SECURITY_LEVEL_WEIGHT: dict[SecurityClassification, float] = {
    SecurityClassification.PUBLIC: 0.5,
    SecurityClassification.INTERNAL: 1.0,
    SecurityClassification.CONFIDENTIAL: 2.0,
    SecurityClassification.TOP_SECRET: 3.0,
}