"""
隐私卫士 — PII 检测器

职责：内容预处理归一化、PII 正则匹配、有效性验证、自定义关键词检测。
"""

from __future__ import annotations

import re
from typing import Any

from .types import PII_PATTERNS, PII_SEVERITY


class PIIDetector:
    """PII 检测器

    负责内容预处理归一化（防绕过）和 PII 正则匹配检测。
    """

    def __init__(self, custom_keywords: list[str] | None = None) -> None:
        self._custom_keywords: list[str] = custom_keywords or []

    # ════════════════════════════════════════════════════
    #  属性
    # ════════════════════════════════════════════════════

    @property
    def custom_keywords(self) -> list[str]:
        return self._custom_keywords

    # ════════════════════════════════════════════════════
    #  预处理
    # ════════════════════════════════════════════════════

    def normalize_content(self, content: str) -> str:
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

    # ════════════════════════════════════════════════════
    #  检测主逻辑
    # ════════════════════════════════════════════════════

    def detect_all_pii(self, content: str) -> list[dict[str, Any]]:
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
    #  关键词管理
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