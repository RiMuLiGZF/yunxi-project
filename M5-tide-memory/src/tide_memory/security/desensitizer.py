"""
数据脱敏器

对敏感数据进行脱敏处理，确保输出安全
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional


class DataDesensitizer:
    """
    数据脱敏器
    
    支持的脱敏类型：
    - 手机号、身份证、邮箱、银行卡号
    - IP地址、MAC地址
    - 姓名、地址
    - 密钥、Token、密码
    - 自定义敏感字段
    """

    # 预定义脱敏规则
    _RULES = [
        # 手机号
        (r'1[3-9]\d{9}', r'1*******$0', 3),
        # 身份证号
        (r'\d{17}[\dXx]', r'****************', 0),
        # 邮箱
        (r'[\w.+-]+@[\w-]+\.[\w.-]+', r'***@***.com', 0),
        # 银行卡号
        (r'\d{16,19}', r'**** **** **** ****', 0),
        # IPv4地址
        (r'\b(?:\d{1,3}\.){3}\d{1,3}\b', r'***.***.***.***', 0),
        # MAC地址
        (r'([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}', r'**:**:**:**:**:**', 0),
        # API Key / Token
        (r'(?:api[_-]?key|token|secret|password)\s*[:=]\s*["\']?[\w\-]+["\']?',
         r'***MASKED***', 0),
        # Bearer Token
        (r'Bearer\s+[\w\-\.]+', r'Bearer ***', 0),
    ]

    # 中文姓名模式（粗略）
    _CHINESE_NAME_PATTERN = re.compile(
        r'([\u4e00-\u9fa5]{2,4})(先生|女士|同学|老师|博士|教授)?'
    )

    def __init__(self, custom_rules: List[Dict] = None,
                 mask_character: str = "*",
                 enable_name_masking: bool = True):
        self._mask_char = mask_character
        self._enable_name_masking = enable_name_masking
        self._custom_rules = custom_rules or []
        self._compiled_rules = self._compile_rules()

    def _compile_rules(self) -> list:
        """编译所有脱敏规则"""
        compiled = []
        for pattern, replacement, _ in self._RULES:
            compiled.append((re.compile(pattern, re.IGNORECASE), replacement))
        
        for rule in self._custom_rules:
            pattern = rule.get("pattern", "")
            replacement = rule.get("replacement", "***")
            compiled.append((re.compile(pattern), replacement))
        
        return compiled

    def desensitize(self, text: str) -> str:
        """
        对文本进行脱敏处理
        
        Args:
            text: 原始文本
        
        Returns:
            脱敏后的文本
        """
        if not text:
            return text

        result = text

        # 应用预定义规则
        for pattern, replacement in self._compiled_rules:
            result = pattern.sub(replacement, result)

        # 中文姓名脱敏（可选）
        if self._enable_name_masking:
            result = self._mask_chinese_names(result)

        return result

    def _mask_chinese_names(self, text: str) -> str:
        """中文姓名脱敏（保留姓氏）"""
        def _replace(match):
            name = match.group(1)
            suffix = match.group(2) or ""
            if len(name) >= 2:
                return name[0] + self._mask_char * (len(name) - 1) + suffix
            return match.group(0)

        return self._CHINESE_NAME_PATTERN.sub(_replace, text)

    def desensitize_dict(self, data: Dict, sensitive_fields: List[str] = None) -> Dict:
        """
        对字典中的敏感字段进行脱敏
        
        Args:
            data: 原始字典
            sensitive_fields: 敏感字段名列表，None时自动检测
        
        Returns:
            脱敏后的字典
        """
        if not isinstance(data, dict):
            return data

        result = {}
        sensitive_keys = set(sensitive_fields or [
            "password", "token", "api_key", "secret", "private_key",
            "phone", "mobile", "email", "id_card", "address", "name",
            "content", "body", "text", "memory_content",
        ])

        for key, value in data.items():
            key_lower = key.lower()
            
            if key_lower in sensitive_keys:
                if isinstance(value, str):
                    result[key] = self.desensitize(value)
                elif isinstance(value, dict):
                    result[key] = self.desensitize_dict(value)
                elif isinstance(value, list):
                    result[key] = [
                        self.desensitize(item) if isinstance(item, str)
                        else self.desensitize_dict(item) if isinstance(item, dict)
                        else item
                        for item in value
                    ]
                else:
                    result[key] = "***MASKED***"
            elif isinstance(value, dict):
                result[key] = self.desensitize_dict(value, sensitive_fields)
            elif isinstance(value, list):
                result[key] = [
                    self.desensitize_dict(item, sensitive_fields) if isinstance(item, dict)
                    else self.desensitize(item) if isinstance(item, str)
                    else item
                    for item in value
                ]
            elif isinstance(value, str) and len(value) > 50:
                # 长文本也进行脱敏
                result[key] = self.desensitize(value)
            else:
                result[key] = value

        return result

    def mask_memory_content(self, content: str, level: str = "full") -> str:
        """
        对记忆内容进行脱敏（根据密级）
        
        Args:
            content: 原始内容
            level: 脱敏级别 (full / partial / metadata_only)
        
        Returns:
            脱敏后的内容
        """
        if level == "full":
            return "[CONTENT_REDACTED]"
        elif level == "partial":
            # 保留前20%和后10%的字符
            if len(content) <= 10:
                return self._mask_char * len(content)
            keep_start = max(1, int(len(content) * 0.2))
            keep_end = max(1, int(len(content) * 0.1))
            return content[:keep_start] + self._mask_char * (len(content) - keep_start - keep_end) + content[-keep_end:]
        elif level == "metadata_only":
            return "[METADATA_ONLY]"
        else:
            return self.desensitize(content)

    def get_sensitive_score(self, text: str) -> float:
        """
        评估文本的敏感程度（0-1）
        
        Returns:
            敏感分数，越高越敏感
        """
        if not text:
            return 0.0

        score = 0.0
        total_patterns = len(self._compiled_rules)

        for pattern, _ in self._compiled_rules:
            matches = pattern.findall(text)
            if matches:
                score += len(matches) / total_patterns * 0.5

        # 长文本额外加分
        if len(text) > 500:
            score += 0.2
        elif len(text) > 200:
            score += 0.1

        return min(1.0, score)
# vim: set et ts=4 sw=4:
