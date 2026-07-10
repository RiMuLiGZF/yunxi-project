"""
隐私卫士 — PrivacyGuard

[V11.1 改进]
- 修复 P0-001：风险分级逻辑重写，low/medium 风险也会进入脱敏分支
- 修复 P1-001：PII 检测正则增强（预处理归一化 + 多策略检测），防绕过
- 修复 P1-002：补全 7 类 PII 脱敏（身份证、银行卡、API Key、密码、Token、私钥、内网 URL）
- 新增：审计日志摘要字段（content_hash, content_length, sanitized_preview, pii_types_detected）

支持 10 类 PII 检测与脱敏：
1.  email        - 邮箱地址
2.  phone_cn     - 中国大陆手机号
3.  id_card_cn   - 中国大陆身份证号
4.  bank_card    - 银行卡号
5.  api_key      - API Key / Secret
6.  password     - 密码 / 口令
7.  token        - Token / Bearer
8.  private_key  - 私钥
9.  url_internal - 内网 URL
10. custom_keyword - 自定义敏感词
"""

from __future__ import annotations

import re
import hashlib
import time
from typing import Any

import structlog

from shared_models import SecurityClassification

logger = structlog.get_logger(__name__)


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


class PrivacyGuard:
    """隐私卫士

    职责：
    - PII（个人可识别信息）检测
    - 风险等级评估
    - 内容脱敏/清洗
    - 审计日志
    - 内网 URL 识别与拦截
    """

    def __init__(self, custom_keywords: list[str] | None = None) -> None:
        self._custom_keywords: list[str] = custom_keywords or []
        self._audit_log: list[dict[str, Any]] = []
        self._scan_count: int = 0
        self._sanitize_count: int = 0
        self._block_count: int = 0
        self._logger = logger.bind(component="privacy_guard")

    # ════════════════════════════════════════════════════
    #  公共方法
    # ════════════════════════════════════════════════════

    def scan_content(
        self,
        content: str,
        security_level: SecurityClassification = SecurityClassification.INTERNAL,
        context: str = "",
    ) -> dict[str, Any]:
        """扫描内容中的 PII

        Args:
            content: 待扫描的内容
            security_level: 涉密等级
            context: 扫描上下文说明

        Returns:
            扫描结果字典
        """
        self._scan_count += 1

        # Step 1: 预处理归一化（防绕过）
        normalized = self._normalize_content(content)

        # Step 2: 检测各类 PII
        detections = self._detect_all_pii(normalized)

        # Step 3: 评估风险等级
        risk_level, risk_score = self._assess_risk_level(detections, security_level)

        # Step 4: 生成审计摘要
        audit_entry = self._build_audit_entry(
            content=content,
            detections=detections,
            risk_level=risk_level,
            risk_score=risk_score,
            security_level=security_level,
            context=context,
            action="scan",
        )
        self._audit_log.append(audit_entry)

        result = {
            "has_pii": len(detections) > 0,
            "detections": detections,
            "pii_types": list({d["pii_type"] for d in detections}),
            "pii_count": len(detections),
            "risk_level": risk_level,
            "risk_score": risk_score,
            "security_level": security_level.value,
            "audit_id": audit_entry["audit_id"],
            "content_hash": audit_entry["content_hash"],
            "content_length": audit_entry["content_length"],
        }

        if detections:
            self._logger.info(
                "pii_detected",
                pii_count=len(detections),
                pii_types=result["pii_types"],
                risk_level=risk_level,
                risk_score=round(risk_score, 2),
                context=context,
            )

        return result

    def sanitize_content(
        self,
        content: str,
        security_level: SecurityClassification = SecurityClassification.INTERNAL,
        target_risk: str = "low",
        context: str = "",
    ) -> dict[str, Any]:
        """对内容进行脱敏处理

        [V11.1 修复] 不再以 high 为唯一阈值，所有检测到 PII 的内容都进入脱敏分支。
        根据风险等级采用不同脱敏强度：
        - critical: 完全替换为 [已脱敏]
        - high: 强脱敏（只保留极少特征）
        - medium: 中等脱敏（保留部分特征）
        - low: 轻脱敏（保留大部分特征）

        Args:
            content: 待脱敏内容
            security_level: 涉密等级
            target_risk: 目标风险等级（low/medium/high）
            context: 上下文说明

        Returns:
            脱敏结果字典
        """
        self._sanitize_count += 1

        # Step 1: 扫描检测
        scan_result = self.scan_content(content, security_level, context)
        detections = scan_result["detections"]
        risk_level = scan_result["risk_level"]

        # Step 2: 执行脱敏（所有检测到 PII 的都执行，只是强度不同）
        sanitized = content
        if detections:
            sanitized = self._sanitize(content, detections, risk_level, target_risk)

        # Step 3: 审计记录
        audit_entry = self._build_audit_entry(
            content=sanitized,
            detections=detections,
            risk_level=risk_level,
            risk_score=scan_result["risk_score"],
            security_level=security_level,
            context=context,
            action="sanitize",
            original_hash=scan_result["content_hash"],
        )
        self._audit_log.append(audit_entry)

        return {
            "original": content,
            "sanitized": sanitized,
            "sanitized_preview": self._make_preview(sanitized),
            "was_modified": content != sanitized,
            "pii_count": len(detections),
            "pii_types": scan_result["pii_types"],
            "risk_level": risk_level,
            "risk_score": scan_result["risk_score"],
            "audit_id": audit_entry["audit_id"],
            "content_hash": audit_entry["content_hash"],
            "content_length": audit_entry["content_length"],
            "sanitized_preview_length": len(audit_entry.get("sanitized_preview", "")),
        }

    def check_external_transfer(
        self,
        content: str,
        target_agent_id: str,
        agent_privacy_level: str = "standard",
        security_level: SecurityClassification = SecurityClassification.INTERNAL,
    ) -> dict[str, Any]:
        """检查内容是否可以传输给外部 Agent

        Args:
            content: 待传输内容
            target_agent_id: 目标 Agent ID
            agent_privacy_level: 目标 Agent 隐私等级
            security_level: 内容涉密等级

        Returns:
            检查结果
        """
        scan_result = self.scan_content(content, security_level, f"transfer:{target_agent_id}")
        risk_level = scan_result["risk_level"]

        can_transfer = True
        block_reason = ""

        # TOP_SECRET 涉密内容 + high/critical 风险 = 阻止
        if security_level >= SecurityClassification.TOP_SECRET and risk_level in ("high", "critical"):
            can_transfer = False
            block_reason = "最高涉密内容包含高风险 PII，禁止外传"
            self._block_count += 1

        # CONFIDENTIAL 涉密 + critical 风险 + 标准隐私 Agent = 阻止
        elif (
            security_level >= SecurityClassification.CONFIDENTIAL
            and risk_level == "critical"
            and agent_privacy_level == "standard"
        ):
            can_transfer = False
            block_reason = "涉密内容包含关键 PII，目标 Agent 隐私等级不足"
            self._block_count += 1

        # 含私钥内容一律阻止外传
        elif any(d["pii_type"] == "private_key" for d in scan_result["detections"]):
            can_transfer = False
            block_reason = "内容包含私钥，禁止外传"
            self._block_count += 1

        result = {
            "can_transfer": can_transfer,
            "block_reason": block_reason,
            "risk_level": risk_level,
            "pii_count": scan_result["pii_count"],
            "pii_types": scan_result["pii_types"],
            "recommendation": "sanitize_before_transfer" if (scan_result["pii_count"] > 0 and can_transfer) else "",
            "audit_id": scan_result["audit_id"],
        }

        if not can_transfer:
            self._logger.warning(
                "transfer_blocked",
                target_agent=target_agent_id,
                reason=block_reason,
                risk_level=risk_level,
            )

        return result

    # ════════════════════════════════════════════════════
    #  内部方法 — 预处理与检测
    # ════════════════════════════════════════════════════

    def _normalize_content(self, content: str) -> str:
        """内容预处理归一化（防绕过）

        处理常见的绕过手法：
        - 零宽字符（U+200B, U+FEFF 等）
        - 全角/半角字符混合
        - 大小写混合（针对特定模式）
        - 多余空格和换行
        - 常见替换手法（如 @ → at，. → dot）
        """
        if not content:
            return content

        normalized = content

        # 1. 移除零宽字符和不可见字符
        zero_width_chars = [
            "\u200b", "\u200c", "\u200d", "\u2060",  # 零宽
            "\ufeff", "\u202a", "\u202b", "\u202c",  # BOM 和方向控制
            "\u202d", "\u202e",
        ]
        for zw in zero_width_chars:
            normalized = normalized.replace(zw, "")

        # 2. 全角数字/字母转半角
        normalized = self._fullwidth_to_halfwidth(normalized)

        # 3. 常见替换手法还原（用于检测，不修改原文）
        # 注意：这一步只用于检测匹配，脱敏仍基于原文位置
        # 这里我们创建一个检测用的镜像版本
        detect_version = normalized
        # email 常见绕过
        detect_version = detect_version.replace(" [at] ", "@")
        detect_version = detect_version.replace("(at)", "@")
        detect_version = detect_version.replace(" [dot] ", ".")
        detect_version = detect_version.replace("(dot)", ".")
        # 手机号常见绕过
        detect_version = re.sub(r"(\d)\s*-\s*(\d)", r"\1\2", detect_version)
        detect_version = re.sub(r"(\d)\s+(\d)", r"\1\2", detect_version)

        return detect_version

    def _fullwidth_to_halfwidth(self, text: str) -> str:
        """全角转半角"""
        result = []
        for char in text:
            code = ord(char)
            # 全角空格
            if code == 0x3000:
                result.append(" ")
            # 全角字符（0xFF01-0xFF5E 对应半角 0x21-0x7E）
            elif 0xFF01 <= code <= 0xFF5E:
                result.append(chr(code - 0xFEE0))
            else:
                result.append(char)
        return "".join(result)

    def _detect_all_pii(self, content: str) -> list[dict[str, Any]]:
        """检测所有类型的 PII

        Args:
            content: 归一化后的内容

        Returns:
            检测结果列表，每项包含 pii_type, value, position, severity
        """
        detections: list[dict[str, Any]] = []
        seen_positions: set[tuple[str, int, int]] = set()  # 去重

        for pii_type, pattern in PII_PATTERNS.items():
            severity = PII_SEVERITY.get(pii_type, "medium")
            for match in pattern.finditer(content):
                value = match.group()
                start, end = match.start(), match.end()

                # 跳过重复（同位置同类型）
                key = (pii_type, start, end)
                if key in seen_positions:
                    continue
                seen_positions.add(key)

                # 额外验证（减少误报）
                if not self._validate_pii(pii_type, value):
                    continue

                detections.append({
                    "pii_type": pii_type,
                    "value": value,
                    "start": start,
                    "end": end,
                    "severity": severity,
                })

        # 自定义关键词检测
        for kw in self._custom_keywords:
            if kw and kw in content:
                start = 0
                while True:
                    idx = content.find(kw, start)
                    if idx == -1:
                        break
                    detections.append({
                        "pii_type": "custom_keyword",
                        "value": kw,
                        "start": idx,
                        "end": idx + len(kw),
                        "severity": "medium",
                    })
                    start = idx + 1

        return detections

    def _validate_pii(self, pii_type: str, value: str) -> bool:
        """额外验证 PII 有效性（减少误报）

        Args:
            pii_type: PII 类型
            value: 检测到的值

        Returns:
            是否为有效 PII
        """
        if pii_type == "id_card_cn":
            # 18 位身份证校验码验证
            digits = re.sub(r"[^\dXx]", "", value)
            if len(digits) == 18:
                return self._validate_id_card_checksum(digits)
            return len(digits) == 15

        if pii_type == "bank_card":
            # Luhn 算法验证
            digits = re.sub(r"\D", "", value)
            if 13 <= len(digits) <= 19:
                return self._luhn_check(digits)
            return False

        if pii_type == "phone_cn":
            # 确保去掉前缀后是 11 位
            digits = re.sub(r"[^\d]", "", value)
            if len(digits) == 13 and digits.startswith("86"):
                digits = digits[2:]
            return len(digits) == 11 and digits.startswith("1")

        if pii_type == "email":
            # 简单长度检查
            local = value.split("@")[0]
            return len(local) >= 1

        return True

    @staticmethod
    def _validate_id_card_checksum(id_number: str) -> bool:
        """18 位身份证校验码验证"""
        if len(id_number) != 18:
            return False
        weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        check_codes = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]
        total = sum(int(id_number[i]) * weights[i] for i in range(17))
        expected = check_codes[total % 11]
        return id_number[17].upper() == expected

    @staticmethod
    def _luhn_check(number: str) -> bool:
        """Luhn 算法（银行卡号校验）"""
        digits = [int(d) for d in number]
        total = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        return total % 10 == 0

    # ════════════════════════════════════════════════════
    #  内部方法 — 风险评估
    # ════════════════════════════════════════════════════

    def _assess_risk_level(
        self,
        detections: list[dict[str, Any]],
        security_level: SecurityClassification,
    ) -> tuple[str, float]:
        """评估综合风险等级

        [V11.1 修复] 采用加权评分制：
        风险分 = Σ(单类 PII 权重 × 数量) × 涉密等级权重

        风险等级：
        - critical: 风险分 >= 20 或存在 critical 类 PII
        - high: 风险分 >= 10
        - medium: 风险分 >= 3
        - low: 风险分 < 3 或无 PII
        - none: 完全无 PII

        Args:
            detections: 检测到的 PII 列表
            security_level: 涉密等级

        Returns:
            (风险等级, 风险分值)
        """
        if not detections:
            return "none", 0.0

        # 计算加权总分
        base_score = 0.0
        has_critical = False
        has_high = False

        for d in detections:
            severity = d.get("severity", "medium")
            weight = SEVERITY_WEIGHT.get(severity, 1.0)
            base_score += weight
            if severity == "critical":
                has_critical = True
            elif severity == "high":
                has_high = True

        # 涉密等级加权
        sec_weight = SECURITY_LEVEL_WEIGHT.get(security_level, 1.0)
        total_score = base_score * sec_weight

        # 判定风险等级
        if has_critical or total_score >= 20:
            risk_level = "critical"
        elif has_high and total_score >= 8 or total_score >= 10:
            risk_level = "high"
        elif total_score >= 3:
            risk_level = "medium"
        else:
            risk_level = "low"

        return risk_level, total_score

    # ════════════════════════════════════════════════════
    #  内部方法 — 脱敏执行
    # ════════════════════════════════════════════════════

    def _sanitize(
        self,
        content: str,
        detections: list[dict[str, Any]],
        risk_level: str,
        target_risk: str,
    ) -> str:
        """执行脱敏

        [V11.1 修复] 补全所有 10 类 PII 的脱敏逻辑。

        Args:
            content: 原始内容
            detections: PII 检测结果
            risk_level: 当前风险等级
            target_risk: 目标风险等级

        Returns:
            脱敏后的内容
        """
        result = content

        # 按 PII 类型分组脱敏
        pii_types = {d["pii_type"] for d in detections}

        # 1. 邮箱脱敏
        if "email" in pii_types:
            result = self._sanitize_email(result, risk_level)

        # 2. 手机号脱敏
        if "phone_cn" in pii_types:
            result = self._sanitize_phone(result, risk_level)

        # 3. 身份证脱敏
        if "id_card_cn" in pii_types:
            result = self._sanitize_id_card(result, risk_level)

        # 4. 银行卡脱敏
        if "bank_card" in pii_types:
            result = self._sanitize_bank_card(result, risk_level)

        # 5. API Key 脱敏
        if "api_key" in pii_types:
            result = self._sanitize_api_key(result, risk_level)

        # 6. 密码脱敏
        if "password" in pii_types:
            result = self._sanitize_password(result, risk_level)

        # 7. Token 脱敏
        if "token" in pii_types:
            result = self._sanitize_token(result, risk_level)

        # 8. 私钥脱敏
        if "private_key" in pii_types:
            result = self._sanitize_private_key(result, risk_level)

        # 9. 内网 URL 脱敏
        if "url_internal" in pii_types:
            result = self._sanitize_internal_url(result, risk_level)

        # 10. 自定义关键词
        if "custom_keyword" in pii_types:
            for kw in self._custom_keywords:
                if kw in result:
                    result = result.replace(kw, "[已脱敏]")

        return result

    # ── 各类 PII 脱敏方法 ────────────────────────────

    def _sanitize_email(self, content: str, risk_level: str) -> str:
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

    def _sanitize_phone(self, content: str, risk_level: str) -> str:
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

    def _sanitize_id_card(self, content: str, risk_level: str) -> str:
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

    def _sanitize_bank_card(self, content: str, risk_level: str) -> str:
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

    def _sanitize_api_key(self, content: str, risk_level: str) -> str:
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

    def _sanitize_password(self, content: str, risk_level: str) -> str:
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

    def _sanitize_token(self, content: str, risk_level: str) -> str:
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

    def _sanitize_private_key(self, content: str, risk_level: str) -> str:
        """私钥脱敏（一律完全替换）"""
        return PII_PATTERNS["private_key"].sub(
            "-----BEGIN REDACTED PRIVATE KEY-----\n[REDACTED]\n-----END REDACTED PRIVATE KEY-----",
            content,
        )

    def _sanitize_internal_url(self, content: str, risk_level: str) -> str:
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

    # ════════════════════════════════════════════════════
    #  内部方法 — 审计与工具
    # ════════════════════════════════════════════════════

    def _build_audit_entry(
        self,
        content: str,
        detections: list[dict[str, Any]],
        risk_level: str,
        risk_score: float,
        security_level: SecurityClassification,
        context: str,
        action: str,
        original_hash: str = "",
    ) -> dict[str, Any]:
        """构建审计条目（V11.1 增加摘要字段）"""
        content_bytes = content.encode("utf-8")
        return {
            "audit_id": f"priv_{int(time.time()*1000)}_{abs(hash(context+action)) % 10000:04d}",
            "timestamp": time.time(),
            "action": action,
            "context": context,
            "risk_level": risk_level,
            "risk_score": round(risk_score, 2),
            "security_level": security_level.value,
            "pii_count": len(detections),
            "pii_types_detected": list({d["pii_type"] for d in detections}),
            "content_hash": hashlib.sha256(content_bytes).hexdigest(),
            "content_length": len(content_bytes),
            "sanitized_preview": self._make_preview(content),
            "original_hash": original_hash,
        }

    @staticmethod
    def _make_preview(content: str, max_len: int = 200) -> str:
        """生成内容预览（脱敏后安全的短文本）"""
        if not content:
            return ""
        if len(content) <= max_len:
            return content
        return content[:max_len] + "..."

    # ════════════════════════════════════════════════════
    #  配置与统计
    # ════════════════════════════════════════════════════

    def add_custom_keyword(self, keyword: str) -> None:
        """添加自定义敏感词"""
        if keyword and keyword not in self._custom_keywords:
            self._custom_keywords.append(keyword)

    def remove_custom_keyword(self, keyword: str) -> bool:
        """移除自定义敏感词"""
        if keyword in self._custom_keywords:
            self._custom_keywords.remove(keyword)
            return True
        return False

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """获取审计日志"""
        return list(reversed(self._audit_log[-limit:]))

    def stats(self) -> dict[str, Any]:
        """统计信息"""
        return {
            "total_scans": self._scan_count,
            "total_sanitizations": self._sanitize_count,
            "total_blocks": self._block_count,
            "custom_keywords_count": len(self._custom_keywords),
            "audit_log_size": len(self._audit_log),
        }


# 兼容别名（V11.0 命名）
FederationPrivacyGuard = PrivacyGuard


# ══════════════════════════════════════════════════════════
# V11.0 兼容层 — 适配旧 API 签名
# ══════════════════════════════════════════════════════════

class _LegacyScanResult:
    """V11.0 风格的扫描结果对象（带属性访问）"""

    def __init__(self, scan_result: dict[str, Any], auto_sanitize: bool = False, guard: Any = None, content: str = "", security_level: Any = None) -> None:
        self._raw = scan_result
        self.passed = not scan_result.get("has_pii", False)
        self.blocked = False
        self.risk_level = scan_result.get("risk_level", "none")
        self.risk_score = scan_result.get("risk_score", 0.0)
        self.sanitized_content = ""

        # 转换 detections 格式（兼容旧的多 type 体系）
        self.detections = []
        for d in scan_result.get("detections", []):
            pii_type = d.get("pii_type", "")
            if pii_type in ("api_key", "password", "token", "private_key"):
                # 代码密钥类
                det = dict(d)
                det["type"] = "code_secret"
                det["secret_type"] = pii_type
                self.detections.append(det)
            elif pii_type == "custom_keyword":
                det = dict(d)
                det["type"] = "custom_keyword"
                self.detections.append(det)
            else:
                # 普通 PII
                det = dict(d)
                det["type"] = "pii"
                self.detections.append(det)

        self.pii_count = scan_result.get("pii_count", 0)
        self.pii_types = scan_result.get("pii_types", [])
        self.content_hash = scan_result.get("content_hash", "")
        self.content_length = scan_result.get("content_length", 0)

        # V11.0 行为：TOP_SECRET 和 CONFIDENTIAL 级别即使无 PII 也拦截
        if security_level is not None:
            try:
                # 支持 enum 或 int 或 string
                if hasattr(security_level, 'value'):
                    sec_val = security_level.value
                else:
                    sec_val = security_level

                # TOP_SECRET = 3
                if sec_val == 3 or str(sec_val).lower() in ("top_secret", "topsecret"):
                    self.blocked = True
                    self.passed = False
                    if self.risk_level == "none":
                        self.risk_level = "high"
                # CONFIDENTIAL = 2
                elif sec_val == 2 or str(sec_val).lower() in ("confidential", "secret"):
                    self.blocked = True
                    if self.risk_level == "none":
                        self.risk_level = "medium"
            except Exception:
                pass

        # auto_sanitize 模式：自动脱敏
        if auto_sanitize and guard is not None and content:
            san_result = guard.sanitize_content(
                content,
                security_level if security_level is not None else SecurityClassification.INTERNAL,
            )
            self.sanitized_content = san_result["sanitized"]

    def __getattr__(self, name: str) -> Any:
        if name in self._raw:
            return self._raw[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def model_dump(self) -> dict[str, Any]:
        """兼容 Pydantic model_dump 方法"""
        return {
            "passed": self.passed,
            "blocked": self.blocked,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "detections": self.detections,
            "pii_count": self.pii_count,
            "pii_types": self.pii_types,
            "sanitized_content": self.sanitized_content,
            "content_hash": self.content_hash,
            "content_length": self.content_length,
        }

    def dict(self) -> dict[str, Any]:
        """兼容 Pydantic dict 方法"""
        return self.model_dump()

    @property
    def summary(self) -> str:
        """结果摘要（兼容 V11.0）"""
        if self.blocked:
            return f"内容被拦截（风险等级：{self.risk_level}，检测到 {self.pii_count} 项敏感信息）"
        if self.pii_count > 0:
            return f"检测到 {self.pii_count} 项敏感信息（风险等级：{self.risk_level}）"
        return "内容安全，未检测到敏感信息"


def _patch_legacy_methods() -> None:
    """为 PrivacyGuard 打补丁，添加 V11.0 兼容方法"""

    def scan(self, content: str, security_level: Any = None, **kwargs: Any) -> _LegacyScanResult:
        """V11.0 兼容：scan 方法"""
        if security_level is None:
            security_level = SecurityClassification.INTERNAL
        result = self.scan_content(content, security_level, context=kwargs.get("context", ""))
        return _LegacyScanResult(
            result,
            auto_sanitize=getattr(self, 'auto_sanitize', False),
            guard=self,
            content=content,
            security_level=security_level,
        )

    def sanitize(self, content: str, security_level: Any = None, **kwargs: Any) -> dict[str, Any]:
        """V11.0 兼容：sanitize 方法"""
        if security_level is None:
            security_level = SecurityClassification.INTERNAL
        return self.sanitize_content(content, security_level, context=kwargs.get("context", ""))

    def add_blocked_keyword(self, keyword: str) -> bool:
        """V11.0 兼容：添加拦截关键词"""
        if keyword and keyword not in self._custom_keywords:
            self._custom_keywords.append(keyword)
            return True
        return False

    def remove_blocked_keyword(self, keyword: str) -> bool:
        """V11.0 兼容：移除拦截关键词"""
        return self.remove_custom_keyword(keyword)

    # 绑定方法
    PrivacyGuard.scan = scan
    PrivacyGuard.sanitize = sanitize
    PrivacyGuard.add_blocked_keyword = add_blocked_keyword
    PrivacyGuard.remove_blocked_keyword = remove_blocked_keyword

    # 处理 auto_sanitize 参数和默认关键词
    _orig_init = PrivacyGuard.__init__

    def _new_init(self, custom_keywords: list[str] | None = None, auto_sanitize: bool = False, blocked_keywords: list[str] | None = None) -> None:
        _orig_init(self, custom_keywords=custom_keywords)
        self.auto_sanitize = auto_sanitize
        # V11.0 兼容：默认内置关键词（当 custom_keywords 为 None 时添加）
        if custom_keywords is None and blocked_keywords is None:
            default_keywords = ["内部机密", "绝密", "机密文件", "请勿外传"]
            for kw in default_keywords:
                if kw not in self._custom_keywords:
                    self._custom_keywords.append(kw)
        if blocked_keywords:
            for kw in blocked_keywords:
                if kw not in self._custom_keywords:
                    self._custom_keywords.append(kw)

    PrivacyGuard.__init__ = _new_init


# 自动打补丁
_patch_legacy_methods()
