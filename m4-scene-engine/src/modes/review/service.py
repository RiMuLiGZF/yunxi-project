"""复盘总结模式 - 业务逻辑层.

封装复盘总结模式的核心业务逻辑，包括概览统计、复盘生成与保存、
情绪追踪、决策回溯、认知偏差检测、私密日记等功能。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.modes.review.repository import ReviewRepository


# ---------------------------------------------------------------------------
# 复盘模板内容（LLM 不可用时的降级方案）
# ---------------------------------------------------------------------------

_TEMPLATE_CONTENTS: dict[str, str] = {
    "daily": """【今日完成】
1. 完成核心功能模块开发，代码质量良好
2. 修复 3 个线上 bug，用户反馈积极
3. 参与产品需求评审会议，确定下一阶段目标

【遇到的问题】
• 接口性能瓶颈，响应时间偏长
• 解决方案：引入缓存机制，优化数据库查询

【明日计划】
1. 继续推进功能开发
2. 编写技术文档
3. 代码评审

【心得感悟】
持续优化代码质量和架构设计，比快速堆功能更重要。
今天的小优化，是明天的大提升。""",
    "weekly": """【本周概述】
完成 3 个功能模块开发，修复 8 个 bug
代码提交 24 次，新增代码 1500+ 行

【重点成果】
✅ 用户系统重构完成
✅ 支付接口对接上线
✅ 性能优化 - 响应速度提升 40%

【问题挑战】
⚠️ 第三方接口不稳定 → 已做降级处理
⚠️ 需求变更频繁 → 加强沟通确认

【下周计划】
1. 完成订单模块开发
2. 开展代码评审
3. 推进测试覆盖

【成长收获】
学会了在压力下保持代码质量，
也更懂得了团队协作的重要性。""",
    "monthly": """【工作总览】
完成 2 个大版本迭代，交付 15 个功能点
代码提交 120 次，团队协作效率提升 25%

【目标达成】
🎯 核心目标完成率：92%
🎯 用户体系重构：已完成
🎯 支付系统上线：已完成
🎯 性能优化专项：进行中

【里程碑】
🏆 月活用户突破 10 万
🏆 系统稳定性达到 99.9%
🏆 团队 Code Review 覆盖率 100%

【反思与改进】
• 需求管理可以更规范
• 技术债务需要定期清理
• 知识沉淀和分享有待加强

【下月计划】
1. 启动新功能开发
2. 优化系统架构
3. 加强团队建设""",
}


# ---------------------------------------------------------------------------
# 认知偏差检测规则库
# ---------------------------------------------------------------------------

_BIAS_RULES: dict[str, dict[str, Any]] = {
    "确认偏误": {
        "keywords": ["我认为", "我觉得", "肯定是", "一定", "毫无疑问", "显然", "毋庸置疑"],
        "description": "在寻找信息时倾向于寻找支持自己观点的证据，忽略反面信息",
        "level": "high",
        "suggestions": [
            "主动寻找与自己观点相反的证据",
            "尝试站在对立面思考问题",
            "列出支持和反对的理由各 3 条",
        ],
    },
    "锚定效应": {
        "keywords": ["第一印象", "最初", "一开始", "首先想到", "第一感觉"],
        "description": "决策时过度依赖第一印象或最初获得的信息，难以调整判断",
        "level": "medium",
        "suggestions": [
            "收集多个参考点，避免单一信息源",
            "延迟决策，给自己足够的思考时间",
            "从不同角度重新评估信息",
        ],
    },
    "损失厌恶": {
        "keywords": ["亏了", "损失", "舍不得", "怕失去", "万一失败"],
        "description": "对损失的痛苦感受大于对同等收益的快乐感受，导致过于保守",
        "level": "medium",
        "suggestions": [
            "使用决策平衡表权衡利弊",
            "问自己：如果不做这件事，1年后会后悔吗",
            "区分可承受损失和不可承受损失",
        ],
    },
    "幸存者偏差": {
        "keywords": ["成功人士", "他们都", "别人都行", "大家都成功"],
        "description": "只关注成功案例而忽略失败案例，高估成功概率",
        "level": "low",
        "suggestions": [
            "主动了解失败案例和沉默数据",
            "分析成功背后的概率和条件",
            "考虑基础概率和样本偏差",
        ],
    },
    "从众效应": {
        "keywords": ["大家都", "别人都", "所有人都", "主流"],
        "description": "倾向于跟随大众的选择，忽视独立判断",
        "level": "medium",
        "suggestions": [
            "先独立思考再参考他人意见",
            "问自己：如果没有人这么做，我还会选吗",
            "区分事实判断和群体压力",
        ],
    },
    "过度自信": {
        "keywords": ["没问题", "肯定行", "很简单", "一定能", "小菜一碟"],
        "description": "高估自己的能力和判断的准确性，低估风险",
        "level": "high",
        "suggestions": [
            "事前预估风险，准备 Plan B",
            "参考外部视角和他人评价",
            "用数据验证而非凭感觉判断",
        ],
    },
    "情绪化决策": {
        "keywords": ["生气", "难过", "焦虑", "害怕", "激动", "兴奋"],
        "description": "在强烈情绪影响下做出决策，缺乏理性分析",
        "level": "high",
        "suggestions": [
            "高情绪状态下延迟重大决策",
            "情绪平复后重新评估选项",
            "使用决策框架辅助理性分析",
        ],
    },
}


# ---------------------------------------------------------------------------
# 复盘模板列表
# ---------------------------------------------------------------------------

_REVIEW_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "daily",
        "name": "日报模板",
        "description": "每日工作/学习复盘",
        "sections": ["今日完成", "遇到的问题", "解决方案", "明日计划", "心得感悟"],
        "icon": "📝",
    },
    {
        "id": "weekly",
        "name": "周报模板",
        "description": "每周总结与规划",
        "sections": ["本周概述", "重点成果", "问题挑战", "下周计划", "成长收获"],
        "icon": "📊",
    },
    {
        "id": "monthly",
        "name": "月报模板",
        "description": "月度深度复盘",
        "sections": ["工作总览", "目标达成", "里程碑", "反思改进", "下月计划"],
        "icon": "📅",
    },
    {
        "id": "kpt",
        "name": "KPT 复盘法",
        "description": "Keep / Problem / Try",
        "sections": ["Keep 保持", "Problem 问题", "Try 尝试"],
        "icon": "🔄",
    },
    {
        "id": "star",
        "name": "STAR 复盘法",
        "description": "情境 / 任务 / 行动 / 结果",
        "sections": ["Situation 情境", "Task 任务", "Action 行动", "Result 结果"],
        "icon": "⭐",
    },
    {
        "id": "growing",
        "name": "成长复盘",
        "description": "个人成长专项复盘",
        "sections": ["目标回顾", "进度评估", "学到了什么", "改进方向", "下一步行动"],
        "icon": "🌱",
    },
]


# ---------------------------------------------------------------------------
# 服务类
# ---------------------------------------------------------------------------


class ReviewService:
    """复盘总结业务服务类.

    提供复盘总结模式的所有业务逻辑，
    调用 ReviewRepository 进行数据访问。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化服务.

        Args:
            db: 数据库会话
            user_id: 用户 ID
        """
        self.repo = ReviewRepository(db, user_id=user_id)

    # -----------------------------------------------------------------------
    # 概览统计
    # -----------------------------------------------------------------------

    def get_overview(self) -> dict[str, Any]:
        """获取复盘总结概览数据.

        Returns:
            概览数据字典，包含 stats、emotion_distribution、
            recent_reviews、recent_diaries
        """
        reviews = self.repo.list_reviews(limit=100)
        diaries = self.repo.list_diaries(limit=100)
        decisions = self.repo.list_decisions(limit=100)
        emotions = self.repo.list_emotions(days=30)

        total_reviews = self.repo.count_reviews()
        total_diaries = self.repo.count_diaries()
        total_decisions = self.repo.count_decisions()
        total_emotions = self.repo.count_emotions()
        week_reviews = self.repo.count_week_reviews()
        streak_days = self.repo.get_streak_days()

        # 情绪统计
        emotion_counts: dict[str, int] = {}
        for e in emotions:
            emotion_counts[e.emotion] = emotion_counts.get(e.emotion, 0) + 1

        # 最近复盘（Top5）
        recent_reviews = [r.to_dict() for r in reviews[:5]]

        # 最近日记（Top3）
        recent_diaries = [d.to_dict() for d in diaries[:3]]

        return {
            "stats": {
                "total_reviews": total_reviews,
                "total_diaries": total_diaries,
                "total_decisions": total_decisions,
                "total_emotions": total_emotions,
                "week_reviews": week_reviews,
                "streak_days": streak_days,
            },
            "emotion_distribution": emotion_counts,
            "recent_reviews": recent_reviews,
            "recent_diaries": recent_diaries,
        }

    # -----------------------------------------------------------------------
    # 复盘生成与保存
    # -----------------------------------------------------------------------

    def generate_review(
        self,
        rtype: str,
        date: Optional[str] = None,
    ) -> dict[str, Any]:
        """生成复盘内容（模板降级方案）.

        优先尝试 LLM 生成（暂未接入），失败时降级使用模板生成。

        Args:
            rtype: 复盘类型 daily/weekly/monthly
            date: 日期字符串

        Returns:
            生成的复盘数据字典
        """
        review_types = {"daily": "日报", "weekly": "周报", "monthly": "月报"}
        rtype = rtype if rtype in review_types else "daily"
        type_name = review_types[rtype]
        date_str = date or datetime.now().strftime("%Y-%m-%d")

        # 使用模板生成（当前为降级方案，后续可接入 LLM）
        content = _TEMPLATE_CONTENTS.get(rtype, _TEMPLATE_CONTENTS["daily"])

        # 计算质量
        word_count = len(content)
        quality = "high" if word_count > 500 else "medium" if word_count > 200 else "low"

        return {
            "type": rtype,
            "date": date_str,
            "title": f"{type_name} - {date_str}",
            "content": content,
            "word_count": word_count,
            "quality": quality,
            "is_ai_generated": False,
        }

    def create_review(
        self,
        rtype: str,
        content: str,
        date: Optional[str] = None,
    ) -> dict[str, Any]:
        """创建/保存复盘记录.

        Args:
            rtype: 复盘类型 daily/weekly/monthly
            content: 复盘内容
            date: 日期字符串

        Returns:
            创建后的复盘记录字典
        """
        review_types = {"daily": "日报", "weekly": "周报", "monthly": "月报"}
        rtype = rtype if rtype in review_types else "daily"
        type_name = review_types[rtype]
        date_str = date or datetime.now().strftime("%Y-%m-%d")
        content = content or ""

        # 计算质量
        word_count = len(content)
        quality = "high" if word_count > 500 else "medium" if word_count > 200 else "low"

        title = f"{type_name} - {date_str}"
        review = self.repo.create_review(
            rtype=rtype,
            title=title,
            content=content,
            date=date_str,
            quality=quality,
        )
        return review.to_dict()

    def list_reviews(
        self,
        review_type: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """获取复盘记录列表.

        Args:
            review_type: 按类型筛选
            limit: 返回条数限制

        Returns:
            复盘记录字典列表
        """
        reviews = self.repo.list_reviews(review_type=review_type, limit=limit)
        return [r.to_dict() for r in reviews]

    def get_review_detail(self, review_id: int) -> Optional[dict[str, Any]]:
        """获取复盘详情.

        Args:
            review_id: 复盘业务 ID

        Returns:
            复盘详情字典，不存在返回 None
        """
        review = self.repo.get_review(review_id)
        return review.to_dict() if review else None

    def delete_review(self, review_id: int) -> bool:
        """删除复盘记录.

        Args:
            review_id: 复盘业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_review(review_id)

    # -----------------------------------------------------------------------
    # 情绪追踪
    # -----------------------------------------------------------------------

    def list_emotions(self, days: int = 30) -> list[dict[str, Any]]:
        """获取情绪记录列表.

        Args:
            days: 获取最近 N 天的记录

        Returns:
            情绪记录字典列表
        """
        emotions = self.repo.list_emotions(days=days)
        return [e.to_dict() for e in emotions]

    def record_emotion(
        self,
        emotion: str,
        level: int,
        trigger: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        """记录情绪.

        Args:
            emotion: 情绪类型
            level: 强度 1-10
            trigger: 触发因素
            note: 备注

        Returns:
            创建后的情绪记录字典
        """
        emotion_obj = self.repo.create_emotion(
            emotion=emotion,
            intensity=level,
            trigger=trigger,
            note=note,
        )
        return emotion_obj.to_dict()

    def get_emotion_stats(self, days: int = 30) -> dict[str, Any]:
        """获取情绪统计数据.

        Args:
            days: 统计天数

        Returns:
            情绪统计字典
        """
        return self.repo.get_emotion_stats(days=days)

    # -----------------------------------------------------------------------
    # 决策回溯
    # -----------------------------------------------------------------------

    def list_decisions(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取决策记录列表.

        Args:
            limit: 返回条数限制

        Returns:
            决策记录字典列表
        """
        decisions = self.repo.list_decisions(limit=limit)
        return [d.to_dict() for d in decisions]

    def get_decision_detail(self, decision_id: int) -> Optional[dict[str, Any]]:
        """获取决策详情.

        Args:
            decision_id: 决策业务 ID

        Returns:
            决策详情字典，不存在返回 None
        """
        decision = self.repo.get_decision(decision_id)
        return decision.to_dict() if decision else None

    def create_decision(
        self,
        title: str,
        description: str,
        options: list[str],
        final_choice: str = "",
        result: str = "",
        emotion_level: int = 5,
    ) -> dict[str, Any]:
        """创建决策记录.

        Args:
            title: 标题
            description: 描述
            options: 备选方案列表
            final_choice: 最终选择
            result: 结果描述
            emotion_level: 情绪强度 1-10

        Returns:
            创建后的决策记录字典
        """
        decision = self.repo.create_decision(
            title=title,
            description=description,
            options=options,
            final_choice=final_choice,
            result=result,
            emotion_level=emotion_level,
        )
        return decision.to_dict()

    def update_decision(
        self,
        decision_id: int,
        update_data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """更新决策记录.

        Args:
            decision_id: 决策业务 ID
            update_data: 更新数据字典

        Returns:
            更新后的决策记录字典，不存在返回 None
        """
        decision = self.repo.update_decision(decision_id, **update_data)
        return decision.to_dict() if decision else None

    def delete_decision(self, decision_id: int) -> bool:
        """删除决策记录.

        Args:
            decision_id: 决策业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_decision(decision_id)

    # -----------------------------------------------------------------------
    # 认知偏差检测
    # -----------------------------------------------------------------------

    def list_biases(self) -> list[dict[str, Any]]:
        """获取认知偏差列表.

        Returns:
            认知偏差字典列表
        """
        biases = self.repo.list_biases()
        return [b.to_dict() for b in biases]

    def analyze_bias(self, text: str) -> dict[str, Any]:
        """分析文本中的认知偏差.

        接收决策描述文本，检测其中可能存在的认知偏差，
        返回偏差名称、描述、风险等级和建议。

        Args:
            text: 待分析的文本

        Returns:
            分析结果字典
        """
        text = text or ""
        if not text.strip():
            return {
                "detected_biases": [],
                "bias_details": [],
                "bias_count": 0,
                "risk_level": "none",
                "suggestions": ["暂无文本可分析"],
            }

        # 检测偏差
        detected_names: list[str] = []
        bias_details: list[dict[str, Any]] = []

        for bias_name, rule in _BIAS_RULES.items():
            found = False
            for kw in rule["keywords"]:
                if kw in text:
                    found = True
                    break
            if found:
                detected_names.append(bias_name)
                bias_details.append({
                    "name": bias_name,
                    "description": rule["description"],
                    "level": rule["level"],
                    "suggestions": rule["suggestions"],
                })

        # 计算风险等级
        high_count = sum(1 for b in bias_details if b["level"] == "high")
        medium_count = sum(1 for b in bias_details if b["level"] == "medium")
        if high_count >= 2 or len(bias_details) >= 4:
            risk_level = "high"
        elif high_count >= 1 or medium_count >= 2 or len(bias_details) >= 2:
            risk_level = "medium"
        elif len(bias_details) >= 1:
            risk_level = "low"
        else:
            risk_level = "none"

        # 汇总建议
        all_suggestions: list[str] = []
        for bd in bias_details:
            all_suggestions.extend(bd["suggestions"])
        # 去重并限制数量
        unique_suggestions = list(dict.fromkeys(all_suggestions))[:8]

        if not bias_details:
            unique_suggestions = ["认知状态良好，继续保持理性思考"]

        # 更新检测计数
        for bias_name in detected_names:
            self.repo.increment_bias_detection(bias_name)
        if detected_names:
            self.repo.commit()

        return {
            "detected_biases": detected_names,
            "bias_details": bias_details,
            "bias_count": len(detected_names),
            "risk_level": risk_level,
            "suggestions": unique_suggestions,
        }

    # -----------------------------------------------------------------------
    # 私密日记
    # -----------------------------------------------------------------------

    def list_diaries(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取日记列表.

        Args:
            limit: 返回条数限制

        Returns:
            日记字典列表
        """
        diaries = self.repo.list_diaries(limit=limit)
        return [d.to_dict() for d in diaries]

    def get_diary_detail(self, diary_id: int) -> Optional[dict[str, Any]]:
        """获取日记详情.

        Args:
            diary_id: 日记业务 ID

        Returns:
            日记详情字典，不存在返回 None
        """
        diary = self.repo.get_diary(diary_id)
        return diary.to_dict() if diary else None

    def create_diary(
        self,
        title: str,
        content: str,
        mood: str = "neutral",
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """创建日记.

        Args:
            title: 标题
            content: 内容
            mood: 心情
            tags: 标签列表

        Returns:
            创建后的日记字典
        """
        diary = self.repo.create_diary(
            title=title,
            content=content,
            mood=mood,
            tags=tags,
        )
        return diary.to_dict()

    def delete_diary(self, diary_id: int) -> bool:
        """删除日记.

        Args:
            diary_id: 日记业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_diary(diary_id)

    # -----------------------------------------------------------------------
    # 复盘模板
    # -----------------------------------------------------------------------

    def get_templates(self) -> list[dict[str, Any]]:
        """获取复盘模板列表.

        Returns:
            模板列表
        """
        return _REVIEW_TEMPLATES

    # -----------------------------------------------------------------------
    # 数据统计
    # -----------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """获取复盘数据统计.

        Returns:
            统计数据字典
        """
        total_reviews = self.repo.count_reviews()
        total_diaries = self.repo.count_diaries()
        total_decisions = self.repo.count_decisions()
        total_words_reviews = self.repo.get_total_words_reviews()
        total_words_diaries = self.repo.get_total_words_diaries()
        monthly_stats = self.repo.get_monthly_stats(months=6)
        quality_distribution = self.repo.get_quality_distribution()

        return {
            "total_reviews": total_reviews,
            "total_diaries": total_diaries,
            "total_decisions": total_decisions,
            "total_words_reviews": total_words_reviews,
            "total_words_diaries": total_words_diaries,
            "total_words": total_words_reviews + total_words_diaries,
            "monthly_stats": monthly_stats,
            "quality_distribution": quality_distribution,
        }
