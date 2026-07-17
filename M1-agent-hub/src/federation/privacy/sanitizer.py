"""
隐私卫士 — 脱敏器

职责：根据检测到的 PII 类型和风险等级执行不同强度的脱敏策略。
"""

from __future__ import annotations

import re
from typing import Any

from .types import PII_PATTERNS


class Sanitizer:
    """脱敏器

    根据风险等级采用不同脱敏强度：
    - critical: 完全替换为 [已脱敏]
    - high: 强脱敏（只保留极少特征）
    - medium: 中等脱敏（保留部分特征）
    - low: 轻脱敏（保留大部分特征）
    """

    # ════════════════════════════════════════════════════
    #  脱敏主入口
    # ════════════════════════════════════════════════════

    @staticmethod
    def sanitize(
        content: str,
        detections: list[dict[str, Any]],
        risk_level: str,
        target_risk: str,
        custom_keywords: list[str] | None = None,
    ) -> str:
        """执行脱敏

        [V11.1 修复] 补全所有 10 类 PII 的脱敏逻辑。

        Args:
            content: 原始内容
            detections: PII 检测结果
            risk_level: 当前风险等级
            target_risk: 目标风险等级
            custom_keywords: 自定义敏感词列表

        Returns:
            脱敏后的内容
        """
        result = content

        # 按 PII 类型分组脱敏
        pii_types = {d["pii_type"] for d in detections}

        # 1. 邮箱脱敏
        if "email" in pii_types:
            result = Sanitizer._sanitize_email(result, risk_level)

        # 2. 手机号脱敏
        if "phone_cn" in pii_types:
            result = Sanitizer._sanitize_phone(result, risk_level)

        # 3. 身份证脱敏
        if "id_card_cn" in pii_types:
            result = Sanitizer._sanitize_id_card(result, risk_level)

        # 4. 银行卡脱敏
        if "bank_card" in pii_types:
            result = Sanitizer._sanitize_bank_card(result, risk_level)

        # 5. API Key 脱敏
        if "api_key" in pii_types:
            result = Sanitizer._sanitize_api_key(result, risk_level)

        # 6. 密码脱敏
        if "password" in pii_types:
            result = Sanitizer._sanitize_password(result, risk_level)

        # 7. Token 脱敏
        if "token" in pii_types:
            result = Sanitizer._sanitize_token(result, risk_level)

        # 8. 私钥脱敏
        if "private_key" in pii_types:
            result = Sanitizer._sanitize_private_key(result, risk_level)

        # 9. 内网 URL 脱敏
        if "url_internal" in pii_types:
            result = Sanitizer._sanitize_internal_url(result, risk_level)

        # 10. 自定义关键词
        if "custom_keyword" in pii_types and custom_keywords:
            for kw in custom_keywords:
                if kw in result:
                    result = result.replace(kw, "[已脱敏]")

        return result

    # ── 各类 PII 脱敏方法 ────────────────────────────

    @staticmethod
    def _sanitize_email(content: str, risk_level: str) -> str:
        """邮箱脱敏"""
        pattern = PII_PATTERNS["email"]

        def _replace(m: re.Match) -> str:
            email = m.group()
            local, domain = email.split("@", 1)
            if risk_level in ("critical", "high"):
                # 强脱敏：只保留首字母 + *** + 顶级域名
                return f"{local[0]}***@***.{domain.split('.')[-1]}"
            elif risk_level == "medium":
                # 中脱敏：保留域名
                return f"{local[0]}***@{domain}"
            else:
                # 轻脱敏：保留前半部分本地名
                keep = max(1, len(local) // 3)
                return f"{local[:keep]}***@{domain}"

        return pattern.sub(_replace, content)

    @staticmethod
    def _sanitize_phone(content: str, risk_level: str) -> str:
        """手机号脱敏"""
        pattern = PII_PATTERNS["phone_cn"]

        def _replace(m: re.Match) -> str:
            phone = re.sub(r"[^\d]", "", m.group())
            # 处理 +86 前缀
            prefix = ""
            if phone.startswith("86") and len(phone) == 13:
                prefix = "86"
                phone = phone[2:]
            if risk_level in ("critical", "high"):
                return f"{prefix}1**********" if prefix else "1**********"
            elif risk_level == "medium":
                return f"{prefix}{phone[:3]}****{phone[-4:]}" if prefix else f"{phone[:3]}****{phone[-4:]}"
            else:
                return f"{prefix}{phone[:3]}***{phone[-3:]}" if prefix else f"{phone[:3]}***{phone[-3:]}"

        return pattern.sub(_replace, content)

    @staticmethod
    def _sanitize_id_card(content: str, risk_level: str) -> str:
        """身份证脱敏"""
        pattern = PII_PATTERNS["id_card_cn"]

        def _replace(m: re.Match) -> str:
            id_num = m.group()
            if risk_level in ("critical", "high"):
                return "******************"
            elif risk_level == "medium":
                # 保留前 6 位和后 4 位
                return f"{id_num[:6]}********{id_num[-4:]}"
            else:
                # 保留前 6 位、出生日期年、后 4 位
                return f"{id_num[:6]}****{id_num[-4:]}"

        return pattern.sub(_replace, content)

    @staticmethod
    def _sanitize_bank_card(content: str, risk_level: str) -> str:
        """银行卡脱敏"""
        pattern = PII_PATTERNS["bank_card"]

        def _replace(m: re.Match) -> str:
            card = re.sub(r"[^\d]", "", m.group())
            if risk_level in ("critical", "high"):
                return "**** **** **** ****"
            elif risk_level == "medium":
                # 保留前 4 后 4
                return f"{card[:4]} **** **** {card[-4:]}"
            else:
                return f"{card[:6]} **** ** {card[-4:]}"

        return pattern.sub(_replace, content)

    @staticmethod
    def _sanitize_api_key(content: str, risk_level: str) -> str:
        """API Key 脱敏"""
        pattern = PII_PATTERNS["api_key"]

        def _replace(m: re.Match) -> str:
            key = m.group()
            if risk_level in ("critical", "high"):
                return "sk-****[REDACTED]****"
            elif risk_level == "medium":
                # 保留前缀和后 4 位
                # 找到值的部分（冒号或等号后）
                if ":" in key or "=" in key:
                    sep_idx = max(key.rfind(":"), key.rfind("="))
                    prefix = key[:sep_idx + 1]
                    val = key[sep_idx + 1:].lstrip()
                    return f"{prefix} {val[:4]}****{val[-4:]}"
                return f"{key[:6]}****{key[-4:]}"
            else:
                # 轻脱敏
                if ":" in key or "=" in key:
                    sep_idx = max(key.rfind(":"), key.rfind("="))
                    prefix = key[:sep_idx + 1]
                    val = key[sep_idx + 1:].lstrip()
                    keep = max(4, len(val) // 4)
                    return f"{prefix} {val[:keep]}****{val[-keep:]}"
                return f"{key[:8]}****{key[-4:]}"

        return pattern.sub(_replace, content)

    @staticmethod
    def _sanitize_password(content: str, risk_level: str) -> str:
        """密码脱敏"""
        pattern = PII_PATTERNS["password"]

        def _replace(m: re.Match) -> str:
            pwd_str = m.group()
            # 找到键名部分
            sep_match = re.search(r"[:=]\s*", pwd_str)
            if sep_match:
                key_part = pwd_str[:sep_match.start()]
                return f"{key_part}: ****[PASSWORD]****"
            return "****[PASSWORD]****"

        return pattern.sub(_replace, content)

    @staticmethod
    def _sanitize_token(content: str, risk_level: str) -> str:
        """Token 脱敏"""
        pattern = PII_PATTERNS["token"]

        def _replace(m: re.Match) -> str:
            token_str = m.group()
            if risk_level in ("critical", "high"):
                # 检查是否是 Bearer 形式
                if token_str.lower().startswith("bearer"):
                    return "Bearer ****[REDACTED]****"
                return "****[TOKEN]****"
            elif risk_level == "medium":
                # 保留前缀和后 4 位
                if token_str.lower().startswith("bearer "):
                    val = token_str[7:]
                    return f"Bearer {val[:4]}****{val[-4:]}"
                sep_match = re.search(r"[:=]\s*", token_str)
                if sep_match:
                    key_part = token_str[:sep_match.start()]
                    val = token_str[sep_match.end():]
                    return f"{key_part}: {val[:4]}****{val[-4:]}"
                return f"{token_str[:4]}****{token_str[-4:]}"
            else:
                if token_str.lower().startswith("bearer "):
                    val = token_str[7:]
                    return f"Bearer {val[:6]}***{val[-4:]}"
                return f"{token_str[:6]}***{token_str[-4:]}"

        return pattern.sub(_replace, content)

    @staticmethod
    def _sanitize_private_key(content: str, risk_level: str) -> str:
        """私钥脱敏（一律完全替换）"""
        return PII_PATTERNS["private_key"].sub(
            "-----BEGIN REDACTED PRIVATE KEY-----\n[REDACTED]\n-----END REDACTED PRIVATE KEY-----",
            content,
        )

    @staticmethod
    def _sanitize_internal_url(content: str, risk_level: str) -> str:
        """内网 URL 脱敏"""
        pattern = PII_PATTERNS["url_internal"]

        def _replace(m: re.Match) -> str:
            url = m.group()
            if risk_level in ("critical", "high"):
                return "[INTERNAL_URL_REDACTED]"
            elif risk_level == "medium":
                # 保留路径，隐藏 IP
                # 提取路径部分
                path_match = re.match(r"https?://[^/]+(/.*)?", url)
                path = path_match.group(1) or "" if path_match else ""
                return f"http://internal-host{path}"
            else:
                # 轻脱敏：只隐藏 IP 段
                return re.sub(
                    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
                    "***.***.***.***",
                    url,
                )

        return pattern.sub(_replace, content)