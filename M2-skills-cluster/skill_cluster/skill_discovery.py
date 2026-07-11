"""SkillDiscoveryEngine 技能发现引擎.

【v3.9.0 优化项1】技能发现与智能推荐引擎。
解决「用户不知道有哪些技能、该用哪个」的痛点。

三层发现能力：
1. 第一层：技能分类浏览（6大类，每类≥3个技能）
2. 第二层：智能推荐（5维信号源加权得分）
3. 第三层：自然语言触发（关键词+语义标签匹配）

信号源权重：
- 当前场景模式：30%
- 用户输入关键词：30%
- 历史使用频率：20%
- 最近使用时间：15%
- 时间/日程上下文：5%
"""

from __future__ import annotations

import math
import re
import time
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class SkillCategory(str, Enum):
    """技能分类体系（6大类）."""

    CODING = "coding"           # 代码开发
    DOCUMENT = "document"       # 文档处理
    DATA = "data"               # 数据分析
    LEARNING = "learning"       # 学习辅助
    LIFE = "life"               # 生活工具
    CREATIVE = "creative"       # 创意生成


class SceneType(str, Enum):
    """场景模式类型（与M4对齐）."""

    CODING = "CODING"           # 工作开发模式
    LEARNING = "LEARNING"       # 学业规划模式
    LIFE = "LIFE"               # 生活综合管理
    DESIGN = "DESIGN"           # 设计模式
    EMOTIONAL = "EMOTIONAL"     # 情绪陪伴模式
    REVIEW = "REVIEW"           # 复盘总结模式
    DEFAULT = "DEFAULT"


# 场景模式 → 推荐分类 权重映射
SCENE_CATEGORY_WEIGHTS: dict[SceneType, dict[SkillCategory, float]] = {
    SceneType.CODING: {
        SkillCategory.CODING: 1.0,
        SkillCategory.DOCUMENT: 0.6,
        SkillCategory.DATA: 0.7,
        SkillCategory.LEARNING: 0.3,
        SkillCategory.LIFE: 0.2,
        SkillCategory.CREATIVE: 0.4,
    },
    SceneType.LEARNING: {
        SkillCategory.CODING: 0.3,
        SkillCategory.DOCUMENT: 0.7,
        SkillCategory.DATA: 0.5,
        SkillCategory.LEARNING: 1.0,
        SkillCategory.LIFE: 0.4,
        SkillCategory.CREATIVE: 0.5,
    },
    SceneType.LIFE: {
        SkillCategory.CODING: 0.1,
        SkillCategory.DOCUMENT: 0.4,
        SkillCategory.DATA: 0.3,
        SkillCategory.LEARNING: 0.3,
        SkillCategory.LIFE: 1.0,
        SkillCategory.CREATIVE: 0.7,
    },
    SceneType.DESIGN: {
        SkillCategory.CODING: 0.5,
        SkillCategory.DOCUMENT: 0.6,
        SkillCategory.DATA: 0.3,
        SkillCategory.LEARNING: 0.2,
        SkillCategory.LIFE: 0.5,
        SkillCategory.CREATIVE: 1.0,
    },
    SceneType.EMOTIONAL: {
        # 情绪陪伴模式不推荐技能（以对话为主）
        SkillCategory.CODING: 0.0,
        SkillCategory.DOCUMENT: 0.1,
        SkillCategory.DATA: 0.0,
        SkillCategory.LEARNING: 0.1,
        SkillCategory.LIFE: 0.3,
        SkillCategory.CREATIVE: 0.2,
    },
    SceneType.REVIEW: {
        SkillCategory.CODING: 0.4,
        SkillCategory.DOCUMENT: 0.6,
        SkillCategory.DATA: 1.0,
        SkillCategory.LEARNING: 0.5,
        SkillCategory.LIFE: 0.3,
        SkillCategory.CREATIVE: 0.3,
    },
    SceneType.DEFAULT: {
        SkillCategory.CODING: 0.5,
        SkillCategory.DOCUMENT: 0.5,
        SkillCategory.DATA: 0.5,
        SkillCategory.LEARNING: 0.5,
        SkillCategory.LIFE: 0.5,
        SkillCategory.CREATIVE: 0.5,
    },
}


class SkillCategoryInfo(BaseModel):
    """分类信息."""

    category_id: str = Field(..., description="分类ID")
    name: str = Field(..., description="分类名称")
    description: str = Field(default="", description="分类描述")
    count: int = Field(default=0, description="该分类下技能数量")
    icon: str = Field(default="", description="分类图标标识")


class SkillDiscoveryItem(BaseModel):
    """技能发现结果项."""

    skill_id: str = Field(..., description="技能ID")
    skill_name: str = Field(..., description="技能名称")
    description: str = Field(default="", description="技能描述")
    category: str = Field(default="", description="所属分类")
    score: float = Field(default=0.0, description="推荐得分(0-100)")
    match_reason: str = Field(default="", description="匹配理由")
    confidence: str = Field(default="MEDIUM", description="置信度: HIGH/MEDIUM/LOW")
    usage_count: int = Field(default=0, description="使用次数")
    last_used_at: float | None = Field(default=None, description="最近使用时间戳")
    tags: list[str] = Field(default_factory=list, description="技能标签")


class UserProfile(BaseModel):
    """用户画像（用于个性化推荐）."""

    favorite_skills: list[str] = Field(default_factory=list, description="收藏的技能ID列表")
    recent_skills: list[dict[str, Any]] = Field(default_factory=list, description="最近使用的技能 [{skill_id, last_used}]")
    usage_frequency: dict[str, int] = Field(default_factory=dict, description="各技能使用次数")


class TimeContext(BaseModel):
    """时间上下文."""

    hour: int = Field(default=12, description="当前小时(0-23)")
    weekday: bool = Field(default=True, description="是否工作日")
    is_morning: bool = Field(default=False, description="是否早晨(6-10点)")
    is_night: bool = Field(default=False, description="是否深夜(23-6点)")


class SkillDiscoveryResult(BaseModel):
    """技能发现结果."""

    recommendations: list[SkillDiscoveryItem] = Field(default_factory=list, description="推荐技能列表（Top N）")
    categories: list[SkillCategoryInfo] = Field(default_factory=list, description="全部分类信息")
    total_available: int = Field(default=0, description="可用技能总数")
    response_time_ms: float = Field(default=0.0, description="响应时间(毫秒)")


# 分类元数据
CATEGORY_META: dict[SkillCategory, dict[str, str]] = {
    SkillCategory.CODING: {
        "name": "代码开发",
        "description": "代码生成、审查、重构、调试、测试",
        "icon": "code",
    },
    SkillCategory.DOCUMENT: {
        "name": "文档处理",
        "description": "摘要、翻译、格式转换、PPT大纲、对比",
        "icon": "document",
    },
    SkillCategory.DATA: {
        "name": "数据分析",
        "description": "可视化、趋势分析、异常检测、统计报告",
        "icon": "chart",
    },
    SkillCategory.LEARNING: {
        "name": "学习辅助",
        "description": "知识点讲解、题目解答、记忆卡片、学习路径",
        "icon": "book",
    },
    SkillCategory.LIFE: {
        "name": "生活工具",
        "description": "日程管理、待办、番茄钟、天气查询",
        "icon": "life",
    },
    SkillCategory.CREATIVE: {
        "name": "创意生成",
        "description": "文案写作、头脑风暴、起名、配色建议",
        "icon": "sparkles",
    },
}


# ============================================================
# 【v3.9.1 新增】关键词权重分级体系
# ============================================================

# 强关键词（高权重，决定性信号）— 直接指向特定技能类型
STRONG_KEYWORDS: dict[SkillCategory, list[str]] = {
    SkillCategory.CODING: [
        "python", "java", "javascript", "js", "c++", "c#", "go", "rust", "php", "ruby",
        "代码", "编程", "开发", "函数", "算法", "bug", "调试", "重构", "测试用例",
        "单元测试", "写代码", "写函数", "写脚本", "代码生成", "代码审查",
        "快速排序", "冒泡排序", "二分查找", "二叉树", "链表", "栈", "队列",
        "动态规划", "递归", "实现一个", "写一个",
    ],
    SkillCategory.DATA: [
        "折线图", "柱状图", "饼图", "图表", "画图", "绘图", "可视化", "数据分析",
        "趋势分析", "异常检测", "统计报告", "数据报表", "数据展示", "趋势图",
        "销售趋势", "数据分析报告", "数据统计", "报表", "趋势",
        "画折线", "画柱状", "画饼",
    ],
    SkillCategory.DOCUMENT: [
        "翻译", "摘要", "总结", "ppt", "大纲", "格式转换", "文档对比", "文档处理",
        "写ppt", "做ppt", "转格式", "总结一下", "翻译成", "对比文档", "对比两个文档",
        "文档差异", "比对",
        "周报", "月报", "日报", "会议纪要", "写报告", "写文档", "写周报",
        "校对", "纠错", "润色",
    ],
    SkillCategory.LEARNING: [
        "知识点", "讲解", "解题", "做题", "学习", "记忆卡片", "闪卡", "学习路径",
        "知识点讲解", "题目解答", "这个知识点", "出题", "几道题", "习题",
        "练习题", "答题",
    ],
    SkillCategory.LIFE: [
        "天气", "日程", "番茄钟", "待办", "提醒", "日历", "闹钟", "计时",
        "明天天气", "今天天气",
        "天气预报", "气温", "降雨", "待办事项", "日程安排", "设置提醒",
    ],
    SkillCategory.CREATIVE: [
        "起名", "文案", "头脑风暴", "配色", "创意", "取名", "产品名字",
        "想个名字", "写文案", "配色方案",
        "写诗", "诗歌", "写首诗", "一首诗", "作诗",
        "编故事", "写故事", "故事", "小说",
        "slogan", "广告语", "海报文案",
    ],
}

# 弱关键词（低权重，辅助信号）— 通用词，容易跨类
WEAK_KEYWORDS: list[str] = [
    "生成", "管理", "创建", "添加", "查看", "查询", "使用", "帮助",
    "一个", "一下", "这个", "那个", "我", "你", "他", "帮", "给",
    "做", "弄", "搞", "来", "去", "是", "的", "了", "吗", "呢",
]

# 停止词（不计分）— 完全无意义的词
STOP_WORDS: set[str] = {
    "帮我", "我想", "我要", "给我", "一下", "一个", "这个", "那个",
    "的", "了", "吗", "呢", "啊", "吧", "哦", "嗯",
    "是", "有", "在", "和", "与", "及", "等",
    "你好", "请问", "麻烦", "谢谢",
    "怎么", "如何", "什么", "为什么", "哪里",
}

# 同义词/近义词映射（用户输入词 → 技能标准关键词）
SYNONYM_MAP: dict[str, str] = {
    "画个图": "数据可视化",
    "画图": "数据可视化",
    "绘图": "数据可视化",
    "做图表": "数据可视化",
    "写代码": "代码生成",
    "写脚本": "代码生成",
    "写函数": "代码生成",
    "写程序": "代码生成",
    "开发": "代码生成",
    "编程": "代码生成",
    "找bug": "Bug定位",
    "查bug": "Bug定位",
    "排错": "Bug定位",
    "调试": "Bug定位",
    "review": "代码审查",
    "代码检查": "代码审查",
    "翻译一下": "翻译",
    "翻译成": "翻译",
    "总结一下": "摘要生成",
    "做ppt": "PPT大纲",
    "写ppt": "PPT大纲",
    "生成ppt": "PPT大纲",
    "番茄钟": "番茄钟",
    "倒计时": "番茄钟",
    "专注": "番茄钟",
    "待办事项": "待办清单",
    "todo": "待办清单",
    "起名字": "起名助手",
    "取名": "起名助手",
    "命名": "起名助手",
    "brainstorm": "头脑风暴",
    "脑暴": "头脑风暴",
    "配色方案": "配色建议",
    "颜色搭配": "配色建议",
}


def _calculate_keyword_weight(keyword: str, category: SkillCategory) -> float:
    """计算关键词的权重（强/弱/停止词）.

    Returns:
        1.0 - 强关键词
        0.3 - 弱关键词
        0.0 - 停止词
        0.5 - 普通关键词（默认）
    """
    kw_lower = keyword.lower()

    # 停止词
    if kw_lower in STOP_WORDS:
        return 0.0

    # 强关键词
    strong_list = STRONG_KEYWORDS.get(category, [])
    for sk in strong_list:
        if sk.lower() in kw_lower or kw_lower in sk.lower():
            return 1.0

    # 弱关键词
    for wk in WEAK_KEYWORDS:
        if wk == kw_lower:
            return 0.3

    return 0.5  # 普通关键词


class SkillDiscoveryEngine:
    """技能发现引擎.

    提供三层发现能力：
    1. 分类浏览：按6大类浏览所有技能
    2. 智能推荐：5维信号加权推荐Top N
    3. 自然语言触发：用户输入描述自动匹配

    设计目标：响应时间 < 50ms（本地轻量算法，不调用大模型）
    """

    def __init__(self) -> None:
        # 技能注册：skill_id -> {manifest, category, usage_count, last_used}
        self._skills: dict[str, dict[str, Any]] = {}
        # 用户画像
        self._user_profile = UserProfile()
        # 倒排索引（用于自然语言触发）
        self._keyword_index: dict[str, set[str]] = {}

    # ---- 技能注册 ----

    def register_skill(
        self,
        skill_id: str,
        skill_name: str,
        description: str,
        category: SkillCategory | str,
        tags: list[str] | None = None,
        keywords: list[str] | None = None,
    ) -> None:
        """注册一个可被发现的技能.

        Args:
            skill_id: 技能唯一标识
            skill_name: 技能名称
            description: 技能描述
            category: 所属分类
            tags: 技能标签
            keywords: 触发关键词（用于自然语言匹配）
        """
        cat = category if isinstance(category, SkillCategory) else SkillCategory(category)

        self._skills[skill_id] = {
            "skill_id": skill_id,
            "skill_name": skill_name,
            "description": description,
            "category": cat.value,
            "tags": tags or [],
            "keywords": keywords or [],
            "usage_count": 0,
            "last_used": None,
        }

        # 构建关键词倒排索引（含中文N-gram支持）
        index_text = (
            skill_name + " " + description + " " +
            " ".join(tags or []) + " " + " ".join(keywords or [])
        ).lower()
        # 英文单词级别索引
        for word in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", index_text):
            if len(word) >= 2:
                self._keyword_index.setdefault(word, set()).add(skill_id)
        # 中文 N-gram 索引（2-gram + 3-gram）
        chinese_chars = re.findall(r"[\u4e00-\u9fa5]", index_text)
        if len(chinese_chars) >= 2:
            # 2-gram
            for i in range(len(chinese_chars) - 1):
                bigram = chinese_chars[i] + chinese_chars[i + 1]
                self._keyword_index.setdefault(bigram, set()).add(skill_id)
            # 3-gram
            for i in range(len(chinese_chars) - 2):
                trigram = chinese_chars[i] + chinese_chars[i + 1] + chinese_chars[i + 2]
                self._keyword_index.setdefault(trigram, set()).add(skill_id)

    def record_usage(self, skill_id: str) -> None:
        """记录技能使用（用于频率和最近使用时间统计）."""
        if skill_id in self._skills:
            self._skills[skill_id]["usage_count"] += 1
            self._skills[skill_id]["last_used"] = time.time()
            self._user_profile.usage_frequency[skill_id] = (
                self._user_profile.usage_frequency.get(skill_id, 0) + 1
            )

    # ---- 第一层：分类浏览 ----

    def list_categories(self) -> list[SkillCategoryInfo]:
        """获取全部分类及各分类下的技能数量."""
        result: list[SkillCategoryInfo] = []
        for cat in SkillCategory:
            meta = CATEGORY_META[cat]
            count = sum(
                1 for s in self._skills.values()
                if s["category"] == cat.value
            )
            result.append(SkillCategoryInfo(
                category_id=cat.value,
                name=meta["name"],
                description=meta["description"],
                count=count,
                icon=meta["icon"],
            ))
        return result

    def list_skills_by_category(self, category: SkillCategory | str) -> list[SkillDiscoveryItem]:
        """按分类列出技能."""
        cat_val = category.value if isinstance(category, SkillCategory) else category
        items = []
        for sid, info in self._skills.items():
            if info["category"] == cat_val:
                items.append(self._make_discovery_item(info))
        # 按使用次数排序
        items.sort(key=lambda x: x.usage_count, reverse=True)
        return items

    # ---- 第二层：智能推荐 ----

    def recommend(
        self,
        scene_type: SceneType | str = SceneType.DEFAULT,
        user_input_preview: str = "",
        user_profile: UserProfile | None = None,
        time_context: TimeContext | None = None,
        top_k: int = 3,
    ) -> SkillDiscoveryResult:
        """智能推荐技能.

        5维信号加权得分：
        - 场景模式：30%
        - 用户输入关键词：30%
        - 历史使用频率：20%
        - 最近使用时间：15%
        - 时间上下文：5%

        Args:
            scene_type: 当前场景模式
            user_input_preview: 用户输入预览（用于关键词匹配）
            user_profile: 用户画像
            time_context: 时间上下文
            top_k: 返回Top N推荐

        Returns:
            SkillDiscoveryResult 推荐结果
        """
        start_time = time.time()

        scene = scene_type if isinstance(scene_type, SceneType) else SceneType(scene_type)
        profile = user_profile or self._user_profile
        tctx = time_context or self._default_time_context()

        scored_items: list[tuple[SkillDiscoveryItem, float, list[str]]] = []

        for sid, info in self._skills.items():
            score = 0.0
            reasons: list[str] = []

            # 维度1：场景模式匹配 (30%)
            scene_score = self._calc_scene_score(info["category"], scene)
            score += scene_score * 0.30
            if scene_score > 0.7:
                reasons.append("场景匹配")

            # 维度2：用户输入关键词 (30%)
            keyword_score = self._calc_keyword_score(sid, user_input_preview)
            score += keyword_score * 0.30
            if keyword_score > 0.5:
                reasons.append("关键词匹配")

            # 维度3：历史使用频率 (20%)
            freq_score = self._calc_frequency_score(sid, profile)
            score += freq_score * 0.20
            if freq_score > 0.6:
                reasons.append("高频使用")

            # 维度4：最近使用时间 (15%)
            recency_score = self._calc_recency_score(sid, info, profile)
            score += recency_score * 0.15
            if recency_score > 0.7:
                reasons.append("最近使用")

            # 维度5：时间上下文 (5%)
            time_score = self._calc_time_score(info["category"], tctx)
            score += time_score * 0.05

            # 归一化到 0-100 分
            final_score = round(score * 100, 1)

            item = self._make_discovery_item(info)
            item.score = final_score
            item.match_reason = "+".join(reasons) if reasons else "综合推荐"
            item.confidence = (
                "HIGH" if final_score >= 70
                else "MEDIUM" if final_score >= 40
                else "LOW"
            )

            scored_items.append((item, final_score, reasons))

        # 按得分排序
        scored_items.sort(key=lambda x: x[1], reverse=True)

        # 取 Top K
        recommendations = [item for item, _, _ in scored_items[:top_k]]
        categories = self.list_categories()
        total = len(self._skills)

        response_ms = (time.time() - start_time) * 1000

        return SkillDiscoveryResult(
            recommendations=recommendations,
            categories=categories,
            total_available=total,
            response_time_ms=round(response_ms, 2),
        )

    # ---- 各维度评分 ----

    def _calc_scene_score(self, category: str, scene: SceneType) -> float:
        """计算场景模式匹配得分."""
        cat_enum = SkillCategory(category)
        weights = SCENE_CATEGORY_WEIGHTS.get(scene, SCENE_CATEGORY_WEIGHTS[SceneType.DEFAULT])
        return weights.get(cat_enum, 0.3)

    def _calc_keyword_score(self, skill_id: str, user_input: str) -> float:
        """计算用户输入关键词匹配得分."""
        if not user_input or not user_input.strip():
            return 0.0

        input_lower = user_input.lower()

        # 提取所有匹配的索引token（英文单词 + 中文N-gram）
        input_tokens = self._tokenize_for_match(input_lower)
        if not input_tokens:
            return 0.0

        # 计算匹配度
        info = self._skills[skill_id]
        skill_text = (
            info["skill_name"] + " " + info["description"] +
            " " + " ".join(info["tags"]) + " " + " ".join(info["keywords"])
        ).lower()

        matched_count = sum(1 for token in input_tokens if token in skill_text)
        return min(1.0, matched_count / max(len(input_tokens), 1))

    def _tokenize_for_match(self, text: str) -> list[str]:
        """将文本切分为匹配用的token（英文单词 + 中文N-gram）."""
        tokens: list[str] = []

        # 英文单词
        english_words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())
        tokens.extend([w for w in english_words if len(w) >= 2])

        # 中文 N-gram（2-gram 为主）
        chinese_chars = re.findall(r"[\u4e00-\u9fa5]", text)
        if len(chinese_chars) >= 2:
            for i in range(len(chinese_chars) - 1):
                tokens.append(chinese_chars[i] + chinese_chars[i + 1])

        return list(set(tokens))  # 去重

    def _calc_frequency_score(self, skill_id: str, profile: UserProfile) -> float:
        """计算历史使用频率得分."""
        freq = profile.usage_frequency.get(skill_id, 0)
        if freq == 0:
            return 0.0
        # 归一化：使用对数函数压缩高频差距
        max_freq = max(profile.usage_frequency.values()) if profile.usage_frequency else 1
        return min(1.0, math.log(freq + 1) / math.log(max_freq + 1))

    def _calc_recency_score(self, skill_id: str, info: dict, profile: UserProfile) -> float:
        """计算最近使用时间得分."""
        last_used = info.get("last_used")
        if last_used is None:
            # 从profile中查找
            for recent in profile.recent_skills:
                if recent.get("skill_id") == skill_id:
                    last_used = recent.get("last_used")
                    break

        if last_used is None:
            return 0.0

        # 指数衰减：每过1小时衰减一半
        hours_passed = (time.time() - last_used) / 3600
        return max(0.0, 0.5 ** (hours_passed / 24))  # 24小时半衰期

    def _calc_time_score(self, category: str, tctx: TimeContext) -> float:
        """计算时间上下文得分."""
        cat = SkillCategory(category)

        # 早晨(6-10点)：生活工具加分
        if tctx.is_morning and cat == SkillCategory.LIFE:
            return 0.8

        # 深夜(23-6点)：不推荐高消耗技能（代码/数据分析）
        if tctx.is_night and cat in (SkillCategory.CODING, SkillCategory.DATA):
            return 0.2

        # 工作日：代码/文档/学习类加分
        if tctx.weekday and cat in (SkillCategory.CODING, SkillCategory.DOCUMENT, SkillCategory.LEARNING):
            return 0.6

        # 周末/非工作日：创意/生活类加分
        if not tctx.weekday and cat in (SkillCategory.CREATIVE, SkillCategory.LIFE):
            return 0.6

        return 0.4  # 中性分

    # ---- 第三层：自然语言触发 ----

    def trigger_by_natural_language(
        self,
        user_input: str,
        scene_type: SceneType | str = SceneType.DEFAULT,
        top_k: int = 3,
    ) -> list[SkillDiscoveryItem]:
        """自然语言触发：用户描述需求，自动匹配技能.

        【v3.9.1 重构】全新匹配算法：
        - 强关键词加权（决定性信号）
        - 同义词/近义词映射
        - 双向匹配（输入→技能 + 技能→输入）
        - 停止词过滤
        - 场景强信号叠加

        Args:
            user_input: 用户自然语言输入
            scene_type: 当前场景模式
            top_k: 返回Top N候选

        Returns:
            匹配的技能列表（按匹配度降序）
        """
        if not user_input or not user_input.strip():
            return []

        input_lower = user_input.lower().strip()
        scene = scene_type if isinstance(scene_type, SceneType) else SceneType(scene_type)
        scene_enum = SceneType(scene)

        # Step 1: 同义词扩展
        expanded_input = self._expand_with_synonyms(input_lower)

        # Step 2: 计算每个技能的匹配得分
        scored: list[tuple[str, float, list[str]]] = []
        for sid, info in self._skills.items():
            score = 0.0
            matched: list[str] = []
            cat = SkillCategory(info["category"])

            # 维度1：强关键词匹配（最高权重，决定性信号）
            strong_score = self._calc_strong_keyword_score(expanded_input, cat, info)
            if strong_score > 0:
                score += strong_score * 0.55  # 强关键词占55%权重
                matched.append("强关键词匹配")

            # 维度2：技能名称精确匹配
            if info["skill_name"] in user_input:
                score += 0.15
                matched.append("名称匹配")

            # 维度3：普通关键词匹配（N-gram）
            normal_score = self._calc_normal_keyword_score(expanded_input, info)
            if normal_score > 0.05:
                score += normal_score * 0.20
                matched.append("关键词匹配")

            # 维度4：场景信号（弱加成，避免场景喧宾夺主）
            scene_weight = self._calc_scene_score(info["category"], scene_enum)
            if scene_weight >= 0.7:
                score += scene_weight * 0.10  # 场景强匹配占10%
                matched.append("场景匹配")
            else:
                score += scene_weight * 0.03  # 弱场景加成

            if score > 0.05:
                scored.append((sid, score, matched))

        # Step 3: 排序
        scored.sort(key=lambda x: x[1], reverse=True)

        # Step 4: 构造结果
        result = []
        for sid, score, reasons in scored[:top_k]:
            info = self._skills[sid]
            item = self._make_discovery_item(info)
            item.score = round(score * 100, 1)
            item.match_reason = "+".join(reasons) if reasons else "综合推荐"
            item.confidence = (
                "HIGH" if score >= 0.5
                else "MEDIUM" if score >= 0.25
                else "LOW"
            )
            result.append(item)

        return result

    def _expand_with_synonyms(self, input_text: str) -> str:
        """用同义词扩展用户输入，增加匹配范围."""
        expanded = input_text
        for synonym, standard in SYNONYM_MAP.items():
            if synonym.lower() in input_text.lower():
                expanded += " " + standard.lower()
        return expanded

    def _calc_strong_keyword_score(
        self, input_text: str, category: SkillCategory, info: dict
    ) -> float:
        """计算强关键词匹配得分（0-1）.

        强关键词是决定性信号，命中一个就得高分。
        """
        strong_kw_list = STRONG_KEYWORDS.get(category, [])
        if not strong_kw_list:
            return 0.0

        hit_count = 0
        for kw in strong_kw_list:
            if kw.lower() in input_text.lower():
                hit_count += 1

        if hit_count == 0:
            return 0.0

        # 命中1个强关键词得0.6分，每多命中1个加0.1，最高1.0
        return min(1.0, 0.6 + (hit_count - 1) * 0.1)

    def _calc_normal_keyword_score(self, input_text: str, info: dict) -> float:
        """计算普通关键词匹配得分（N-gram方式）."""
        # 先过滤停止词
        input_tokens = self._tokenize_for_match(input_text)
        if not input_tokens:
            return 0.0

        # 过滤停止词
        filtered_tokens = [t for t in input_tokens if t.lower() not in STOP_WORDS]
        if not filtered_tokens:
            return 0.0

        skill_text = (
            info["skill_name"] + " " + info["description"] +
            " " + " ".join(info["tags"]) + " " + " ".join(info["keywords"])
        ).lower()

        matched = sum(1 for t in filtered_tokens if t in skill_text)
        return matched / len(filtered_tokens)

    # ---- 常用技能管理 ----

    def add_favorite(self, skill_id: str) -> bool:
        """添加到常用技能."""
        if skill_id in self._skills and skill_id not in self._user_profile.favorite_skills:
            self._user_profile.favorite_skills.append(skill_id)
            return True
        return False

    def remove_favorite(self, skill_id: str) -> bool:
        """从常用技能移除."""
        if skill_id in self._user_profile.favorite_skills:
            self._user_profile.favorite_skills.remove(skill_id)
            return True
        return False

    def get_favorites(self) -> list[SkillDiscoveryItem]:
        """获取常用技能列表."""
        result = []
        for sid in self._user_profile.favorite_skills:
            if sid in self._skills:
                result.append(self._make_discovery_item(self._skills[sid]))
        return result

    # ---- 辅助方法 ----

    def _make_discovery_item(self, info: dict[str, Any]) -> SkillDiscoveryItem:
        """构造技能发现项."""
        return SkillDiscoveryItem(
            skill_id=info["skill_id"],
            skill_name=info["skill_name"],
            description=info["description"],
            category=info["category"],
            usage_count=info.get("usage_count", 0),
            last_used_at=info.get("last_used"),
            tags=info.get("tags", []),
        )

    def _default_time_context(self) -> TimeContext:
        """获取默认时间上下文."""
        import datetime
        now = datetime.datetime.now()
        hour = now.hour
        return TimeContext(
            hour=hour,
            weekday=now.weekday() < 5,
            is_morning=6 <= hour <= 10,
            is_night=hour >= 23 or hour < 6,
        )

    # ---- 统计 ----

    def stats(self) -> dict[str, Any]:
        """发现引擎统计信息."""
        category_counts = {cat.value: 0 for cat in SkillCategory}
        for info in self._skills.values():
            cat = info["category"]
            if cat in category_counts:
                category_counts[cat] += 1

        return {
            "total_skills": len(self._skills),
            "category_counts": category_counts,
            "total_keywords_indexed": len(self._keyword_index),
            "favorite_count": len(self._user_profile.favorite_skills),
            "categories": [cat.value for cat in SkillCategory],
        }
