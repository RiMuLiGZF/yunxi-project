"""
涉密内容自动分级 — SecurityClassifier

基于关键词规则 + 正则模式的四级涉密分级引擎：
- 公开（PUBLIC）
- 内部（INTERNAL）
- 机密（CONFIDENTIAL）
- 绝密（TOP_SECRET）

支持内容自动分级、权限预检、按级别脱敏。
"""

from __future__ import annotations

import re
from enum import IntEnum
from typing import Any

import structlog

from shared_models import SecurityClassification

logger = structlog.get_logger(__name__)


class SecurityClassifier:
    """涉密内容自动分级器

    采用多级规则引擎进行内容分级：
    1. 正则模式匹配（最高优先级）
    2. 关键词密度分析
    3. 默认降级策略
    """

    def __init__(self) -> None:
        self._logger = logger.bind(component="security_classifier")

        # 关键词规则：每个关键词关联一个分级
        self._keyword_rules: dict[str, SecurityClassification] = {
            # 绝密关键词
            "核心算法源码": SecurityClassification.TOP_SECRET,
            "密钥种子": SecurityClassification.TOP_SECRET,
            "root密码": SecurityClassification.TOP_SECRET,
            "军事部署": SecurityClassification.TOP_SECRET,
            "核武": SecurityClassification.TOP_SECRET,
            "战略预案": SecurityClassification.TOP_SECRET,
            # 机密关键词
            "商业秘密": SecurityClassification.CONFIDENTIAL,
            "客户名单": SecurityClassification.CONFIDENTIAL,
            "财务报表": SecurityClassification.CONFIDENTIAL,
            "薪酬数据": SecurityClassification.CONFIDENTIAL,
            "收购计划": SecurityClassification.CONFIDENTIAL,
            "架构设计文档": SecurityClassification.CONFIDENTIAL,
            # 内部关键词
            "内部通讯录": SecurityClassification.INTERNAL,
            "会议纪要": SecurityClassification.INTERNAL,
            "项目进度": SecurityClassification.INTERNAL,
            "内部流程": SecurityClassification.INTERNAL,
            "组内讨论": SecurityClassification.INTERNAL,
        }

        # 正则模式规则：(pattern, classification, description)
        self._pattern_rules: list[tuple[re.Pattern[str], SecurityClassification, str]] = [
            # 绝密模式
            (
                re.compile(
                    r"(?:绝密|TOP[\s_-]?SECRET|TS[/-]\d)",
                    re.IGNORECASE,
                ),
                SecurityClassification.TOP_SECRET,
                "绝密标识匹配",
            ),
            (
                re.compile(
                    r"(?:private[_\s]?key|私钥|seed[_\s]?key)",
                    re.IGNORECASE,
                ),
                SecurityClassification.TOP_SECRET,
                "密钥材料匹配",
            ),
            (
                re.compile(
                    r"(?:核武器|核弹头|导弹发射|战略核)",
                ),
                SecurityClassification.TOP_SECRET,
                "军事情报匹配",
            ),
            # 机密模式
            (
                re.compile(
                    r"(?:机密|CONFIDENTIAL| Secret)",
                    re.IGNORECASE,
                ),
                SecurityClassification.CONFIDENTIAL,
                "机密标识匹配",
            ),
            (
                re.compile(
                    r"(?:SSN|社会安全号)\s*[:：]?\s*\d",
                ),
                SecurityClassification.CONFIDENTIAL,
                "社会安全号匹配",
            ),
            (
                re.compile(
                    r"(?:银行账户|bank[_\s]?account)\s*[:：]?\s*\d",
                    re.IGNORECASE,
                ),
                SecurityClassification.CONFIDENTIAL,
                "银行账户匹配",
            ),
            # 内部模式
            (
                re.compile(
                    r"(?:内部|INTERNAL|内部编号)\s*[:：]?\s*\w+",
                    re.IGNORECASE,
                ),
                SecurityClassification.INTERNAL,
                "内部标识匹配",
            ),
        ]

    def classify_content(self, content: str) -> SecurityClassification:
        """对内容进行自动涉密分级

        分级策略（取最高等级）：
        1. 正则模式匹配 → 取最高命中的分级
        2. 关键词密度分析 → 基于命中数量和分级加权
        3. 无匹配 → 默认 PUBLIC

        Args:
            content: 待分级的内容文本

        Returns:
            SecurityClassification 分级结果
        """
        if not content:
            return SecurityClassification.PUBLIC

        max_level = SecurityClassification.PUBLIC

        # 第一阶段：正则模式匹配（高优先级）
        for pattern, level, desc in self._pattern_rules:
            if pattern.search(content):
                if level > max_level:
                    max_level = level
                self._logger.debug(
                    "pattern_matched",
                    description=desc,
                    level=level.name,
                )

        # 第二阶段：关键词密度分析
        keyword_levels: list[SecurityClassification] = []
        for keyword, level in self._keyword_rules.items():
            if keyword in content:
                keyword_levels.append(level)

        if keyword_levels:
            # 取关键词中最高的分级
            keyword_max = max(keyword_levels)
            # 如果关键词命中数量 >= 3，且最高级为INTERNAL，则升级为CONFIDENTIAL
            if len(keyword_levels) >= 3 and keyword_max == SecurityClassification.INTERNAL:
                keyword_max = SecurityClassification.CONFIDENTIAL
            # 如果关键词命中数量 >= 5，直接升级为TOP_SECRET
            if len(keyword_levels) >= 5:
                keyword_max = SecurityClassification.TOP_SECRET

            if keyword_max > max_level:
                max_level = keyword_max

        self._logger.info(
            "content_classified",
            level=max_level.name,
            keyword_hits=len(keyword_levels),
            content_length=len(content),
        )
        return max_level

    def check_clearance(
        self,
        agent_clearance: SecurityClassification,
        content_level: SecurityClassification,
    ) -> bool:
        """权限预检

        检查 Agent 的涉密等级是否满足访问内容所需的等级。

        规则：Agent clearance >= content level 时允许访问。

        Args:
            agent_clearance: Agent的安全许可等级
            content_level: 内容的涉密等级

        Returns:
            True 表示有权限访问，False 表示权限不足
        """
        is_cleared = agent_clearance >= content_level

        if not is_cleared:
            self._logger.warning(
                "clearance_check_failed",
                agent_clearance=agent_clearance.name,
                content_level=content_level.name,
            )
        else:
            self._logger.debug(
                "clearance_check_passed",
                agent_clearance=agent_clearance.name,
                content_level=content_level.name,
            )

        return is_cleared

    def strip_for_level(
        self,
        content: str,
        target_level: SecurityClassification,
    ) -> str:
        """按目标涉密等级脱敏内容

        脱敏规则：
        - target_level=PUBLIC：移除所有涉密关键词和模式匹配片段
        - target_level=INTERNAL：移除机密和绝密相关内容
        - target_level=CONFIDENTIAL：移除绝密相关内容
        - target_level=TOP_SECRET：不做脱敏

        Args:
            content: 原始内容
            target_level: 目标涉密等级

        Returns:
            脱敏后的内容
        """
        if not content:
            return content

        # TOP_SECRET不需要脱敏
        if target_level >= SecurityClassification.TOP_SECRET:
            return content

        stripped = content

        # 构建需要脱敏的关键词列表（分级 > target_level 的关键词）
        keywords_to_strip: list[str] = []
        for keyword, level in self._keyword_rules.items():
            if level > target_level:
                keywords_to_strip.append(keyword)

        # 按关键词长度降序排列，避免短词先替换导致长词匹配失败
        keywords_to_strip.sort(key=len, reverse=True)

        for keyword in keywords_to_strip:
            # 将关键词替换为 [已脱敏-N] 标记
            stripped = stripped.replace(keyword, f"[已脱敏-{keyword[0]}{'*' * (len(keyword) - 1)}]")

        # 正则模式脱敏
        for pattern, level, desc in self._pattern_rules:
            if level > target_level:
                stripped = pattern.sub(f"[已脱敏-{level.name}]", stripped)

        self._logger.info(
            "content_stripped",
            target_level=target_level.name,
            original_length=len(content),
            stripped_length=len(stripped),
        )
        return stripped
