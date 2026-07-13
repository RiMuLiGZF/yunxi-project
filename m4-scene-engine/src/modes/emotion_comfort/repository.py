"""情绪陪伴 - 数据访问层.

封装情绪陪伴相关的数据库 CRUD 和查询操作。
首次访问时自动初始化默认内容库和示例数据。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.common.db_transaction import transactional_scope
from src.database import (
    EmotionRecordDB,
    RelaxContentDB,
    RelaxSessionDB,
    SleepContentDB,
    SleepRecordDB,
    PsychAssessmentDB,
    AssessmentResultDB,
    MoodDiaryDB,
)

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 默认数据
# ---------------------------------------------------------------------------

_DEFAULT_RELAX_CONTENTS: list[dict[str, Any]] = [
    {
        "title": "478 呼吸法",
        "category": "breathing",
        "content_type": "guide",
        "duration_seconds": 300,
        "difficulty": "easy",
        "description": "吸气4秒，屏息7秒，呼气8秒，快速平复情绪",
        "steps": [
            "找一个舒适的姿势坐下",
            "用鼻子吸气4秒",
            "屏息7秒",
            "用嘴呼气8秒",
            "重复5-10次",
        ],
    },
    {
        "title": "渐进式肌肉放松",
        "category": "muscle",
        "content_type": "guide",
        "duration_seconds": 600,
        "difficulty": "medium",
        "description": "从头到脚逐组肌肉紧张放松，释放身体压力",
        "steps": [
            "握紧拳头5秒然后放松",
            "手臂紧张5秒然后放松",
            "肩膀向上提5秒然后放松",
            "脸部表情紧张5秒然后放松",
            "全身放松感受平静",
        ],
    },
    {
        "title": "正念冥想",
        "category": "meditation",
        "content_type": "guide",
        "duration_seconds": 900,
        "difficulty": "medium",
        "description": "专注呼吸，观察思绪，不评判不抗拒",
        "steps": [
            "闭眼坐好，脊柱挺直",
            "注意力放在呼吸上",
            "思绪飘走时轻轻拉回",
            "感受身体的感觉",
            "慢慢睁开眼睛",
        ],
    },
    {
        "title": "身体扫描",
        "category": "body_scan",
        "content_type": "guide",
        "duration_seconds": 720,
        "difficulty": "easy",
        "description": "从头到脚逐一感受身体各部位，释放紧张",
        "steps": [
            "平躺或舒适坐下",
            "从头顶开始扫描",
            "感受每个部位的感觉",
            "发现紧张就深呼吸放松",
            "完成后感受全身",
        ],
    },
    {
        "title": "箱式呼吸",
        "category": "breathing",
        "content_type": "guide",
        "duration_seconds": 240,
        "difficulty": "easy",
        "description": "吸4-屏4-呼4-屏4，像画一个正方形",
        "steps": [
            "吸气4秒",
            "屏息4秒",
            "呼气4秒",
            "屏息4秒",
            "重复循环",
        ],
    },
]

_DEFAULT_SLEEP_CONTENTS: list[dict[str, Any]] = [
    {
        "title": "海浪声助眠",
        "category": "nature",
        "content_type": "audio",
        "duration_seconds": 1800,
        "description": "舒缓的海浪声，带你进入深度睡眠",
    },
    {
        "title": "雨声白噪音",
        "category": "rain",
        "content_type": "audio",
        "duration_seconds": 2700,
        "description": "轻柔的雨声，安神助眠好帮手",
    },
    {
        "title": "睡前故事：星空旅行",
        "category": "story",
        "content_type": "audio",
        "duration_seconds": 1200,
        "description": "温暖的睡前故事，伴随你入眠",
    },
    {
        "title": "深度睡眠冥想",
        "category": "meditation",
        "content_type": "audio",
        "duration_seconds": 1500,
        "description": "引导式冥想，快速进入深度睡眠状态",
    },
    {
        "title": "森林鸟鸣",
        "category": "nature",
        "content_type": "audio",
        "duration_seconds": 2100,
        "description": "清晨森林的声音，自然疗愈",
    },
]

_DEFAULT_ASSESSMENTS: list[dict[str, Any]] = [
    {
        "assessment_type": "stress",
        "title": "压力水平测评",
        "description": "评估当前的心理压力水平",
        "duration_minutes": 5,
        "questions": [
            {"id": 1, "text": "最近经常感到紧张或焦虑", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 2, "text": "睡眠质量下降，难以入睡", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 3, "text": "容易感到疲惫，精力不足", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 4, "text": "注意力难以集中", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 5, "text": "容易烦躁或发脾气", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 6, "text": "感到事情失去控制", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 7, "text": "肌肉紧张或头痛", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 8, "text": "食欲变化明显", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 9, "text": "对事情失去兴趣", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 10, "text": "感到孤独或无助", "options": ["从不", "偶尔", "经常", "总是"]},
        ],
    },
    {
        "assessment_type": "emotion",
        "title": "情绪状态测评",
        "description": "了解自己的情绪健康状况",
        "duration_minutes": 4,
        "questions": [
            {"id": 1, "text": "大部分时间感到愉快", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 2, "text": "能够很好地调节情绪", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 3, "text": "对未来充满希望", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 4, "text": "遇到挫折能快速恢复", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 5, "text": "经常感到焦虑或担忧", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 6, "text": "容易感到悲伤或低落", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 7, "text": "对自己感到满意", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 8, "text": "生活中有很多让我开心的事", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
        ],
    },
    {
        "assessment_type": "sleep",
        "title": "睡眠质量测评",
        "description": "评估你的睡眠质量",
        "duration_minutes": 3,
        "questions": [
            {"id": 1, "text": "入睡时间（关灯到睡着）", "options": ["15分钟内", "16-30分钟", "31-60分钟", "60分钟以上"]},
            {"id": 2, "text": "夜间醒来次数", "options": ["0次", "1-2次", "3-4次", "5次以上"]},
            {"id": 3, "text": "总睡眠时间", "options": ["7-9小时", "6-7小时", "5-6小时", "5小时以下"]},
            {"id": 4, "text": "早上起床后的精神状态", "options": ["精力充沛", "还可以", "有点累", "非常疲惫"]},
            {"id": 5, "text": "白天困倦程度", "options": ["完全不困", "偶尔犯困", "经常犯困", "总是很困"]},
            {"id": 6, "text": "睡眠规律性", "options": ["非常规律", "比较规律", "不太规律", "完全不规律"]},
            {"id": 7, "text": "对睡眠质量的满意度", "options": ["非常满意", "比较满意", "不太满意", "很不满意"]},
        ],
    },
]


# ---------------------------------------------------------------------------
# Repository 类
# ---------------------------------------------------------------------------


class EmotionRepository:
    """情绪陪伴数据仓库.

    封装情绪陪伴模块的所有数据库操作。
    自动处理首次访问时的默认数据初始化。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化数据仓库.

        Args:
            db: SQLAlchemy 数据库会话
            user_id: 用户ID
        """
        self.db = db
        self.user_id = user_id
        self._initialized = False
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        """确保默认数据已初始化."""
        if self._initialized:
            return
        try:
            self._seed_default_contents()
            self._initialized = True
        except Exception as e:
            logger.warning("初始化默认数据跳过", error=str(e), error_type=type(e).__name__)

    # ------------------------------------------------------------------
    # 初始化默认数据
    # ------------------------------------------------------------------

    def _seed_default_contents(self) -> None:
        """初始化默认内容库（幂等操作）."""
        # 放松内容
        relax_count = self.db.query(RelaxContentDB).count()
        if relax_count == 0:
            with transactional_scope(self.db):
                for item in _DEFAULT_RELAX_CONTENTS:
                    self.db.add(RelaxContentDB(**item))
            logger.info("初始化放松内容: {_default_relax_contents_count} 条", _default_relax_contents_count=len(_DEFAULT_RELAX_CONTENTS))

        # 助眠内容
        sleep_count = self.db.query(SleepContentDB).count()
        if sleep_count == 0:
            with transactional_scope(self.db):
                for item in _DEFAULT_SLEEP_CONTENTS:
                    self.db.add(SleepContentDB(**item))
            logger.info("初始化助眠内容: {_default_sleep_contents_count} 条", _default_sleep_contents_count=len(_DEFAULT_SLEEP_CONTENTS))

        # 心理测评
        assess_count = self.db.query(PsychAssessmentDB).count()
        if assess_count == 0:
            with transactional_scope(self.db):
                for item in _DEFAULT_ASSESSMENTS:
                    questions = item.pop("questions")
                    self.db.add(PsychAssessmentDB(
                        questions_json=questions,
                        questions_count=len(questions),
                        **item,
                    ))
            logger.info("初始化心理测评: {_default_assessments_count} 条", _default_assessments_count=len(_DEFAULT_ASSESSMENTS))

        # 示例情绪记录（仅当完全没有记录时）
        emotion_count = self.db.query(EmotionRecordDB).filter(
            EmotionRecordDB.user_id == self.user_id
        ).count()
        if emotion_count == 0:
            self._seed_sample_emotion_records()

        # 示例心情日记（仅当完全没有时）
        diary_count = self.db.query(MoodDiaryDB).filter(
            MoodDiaryDB.user_id == self.user_id
        ).count()
        if diary_count == 0:
            self._seed_sample_mood_diary()

    def _seed_sample_emotion_records(self) -> None:
        """生成示例情绪记录（30天）."""
        emotions = ["happy", "calm", "neutral", "anxious", "sad", "angry"]
        weights = [3, 3, 2, 1, 1, 0.5]
        triggers = ["工作压力", "人际关系", "健康状况", "天气", "睡眠", "运动", "阅读", "美食"]

        with transactional_scope(self.db):
            for i in range(30):
                d = datetime.now() - timedelta(days=29 - i)
                emo = random.choices(emotions, weights=weights, k=1)[0]
                self.db.add(EmotionRecordDB(
                    emotion_type=emo,
                    intensity=random.randint(3, 9),
                    trigger=random.choice(triggers),
                    note="",
                    date=d.strftime("%Y-%m-%d"),
                    user_id=self.user_id,
                    created_at=d,
                ))
        logger.info("初始化示例情绪记录: 30 条")

    def _seed_sample_mood_diary(self) -> None:
        """生成示例心情日记."""
        samples = [
            {"emotion": "happy", "content": "今天完成了一个重要项目，很有成就感。和朋友一起吃了好吃的，聊得很开心。", "tags": ["工作", "朋友"]},
            {"emotion": "calm", "content": "平静的一天，读了一本好书，喝了一杯茶。", "tags": ["阅读", "放松"]},
            {"emotion": "anxious", "content": "下周有个重要的汇报，有点紧张。准备了很久但还是担心不够好。", "tags": ["工作", "焦虑"]},
            {"emotion": "sad", "content": "和好朋友吵架了，心里很难受。不知道该不该主动联系。", "tags": ["人际关系", "难过"]},
            {"emotion": "happy", "content": "运动后心情特别好，全身都舒畅了。", "tags": ["运动", "开心"]},
        ]
        with transactional_scope(self.db):
            for i, s in enumerate(samples):
                d = datetime.now() - timedelta(days=4 - i)
                self.db.add(MoodDiaryDB(
                    mood=s["emotion"],
                    content=s["content"],
                    tags=s["tags"],
                    date=d.strftime("%Y-%m-%d"),
                    user_id=self.user_id,
                    created_at=d,
                ))
        logger.info("初始化示例心情日记: {samples_count} 条", samples_count=len(samples))

    # ------------------------------------------------------------------
    # 情绪记录
    # ------------------------------------------------------------------

    def get_emotion_records(self, days: int = 30) -> List[EmotionRecordDB]:
        """获取情绪记录（最近 N 天）.

        Args:
            days: 天数

        Returns:
            情绪记录列表
        """
        start_date = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        return (
            self.db.query(EmotionRecordDB)
            .filter(
                EmotionRecordDB.user_id == self.user_id,
                EmotionRecordDB.date >= start_date,
            )
            .order_by(EmotionRecordDB.date.asc())
            .all()
        )

    def get_emotion_stats(self, days: int = 30) -> Dict[str, Any]:
        """获取情绪统计数据.

        Args:
            days: 统计天数

        Returns:
            统计数据字典
        """
        records = self.get_emotion_records(days)

        # 分布
        distribution: Dict[str, int] = {}
        for r in records:
            distribution[r.emotion_type] = distribution.get(r.emotion_type, 0) + 1

        # 日趋势
        daily = [
            {
                "date": r.date,
                "emotion": r.emotion_type,
                "level": r.intensity,
            }
            for r in records
        ]

        # 触发因素统计
        triggers: Dict[str, int] = {}
        for r in records:
            if r.trigger:
                triggers[r.trigger] = triggers.get(r.trigger, 0) + 1

        dominant = max(distribution, key=distribution.get) if distribution else "calm"

        return {
            "total_records": len(records),
            "distribution": distribution,
            "daily_trend": daily,
            "triggers": triggers,
            "dominant_emotion": dominant,
        }

    def get_overview_stats(self) -> Dict[str, Any]:
        """获取情绪概览统计.

        Returns:
            概览数据字典
        """
        today = datetime.now().strftime("%Y-%m-%d")
        today_record = (
            self.db.query(EmotionRecordDB)
            .filter(
                EmotionRecordDB.user_id == self.user_id,
                EmotionRecordDB.date == today,
            )
            .first()
        )

        # 最近7天统计
        records_7d = self.get_emotion_records(7)
        emotion_counts: Dict[str, int] = {}
        for r in records_7d:
            emotion_counts[r.emotion_type] = emotion_counts.get(r.emotion_type, 0) + 1
        dominant = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "calm"
        avg_level = sum(r.intensity for r in records_7d) / max(len(records_7d), 1)

        # 总记录数
        total = (
            self.db.query(EmotionRecordDB)
            .filter(EmotionRecordDB.user_id == self.user_id)
            .count()
        )

        return {
            "stats": {
                "total_records": total,
                "streak_days": 25,
                "dominant_emotion": dominant,
                "avg_level": round(avg_level, 1),
                "today_recorded": today_record is not None,
                "today_emotion": today_record.emotion_type if today_record else None,
            },
            "current_mood": today_record.to_dict() if today_record else None,
        }

    def record_emotion(
        self,
        emotion: str,
        level: int,
        trigger: str = "",
        note: str = "",
    ) -> EmotionRecordDB:
        """记录情绪（今日已有则更新）.

        Args:
            emotion: 情绪类型
            level: 情绪强度
            trigger: 触发因素
            note: 备注

        Returns:
            情绪记录 ORM 对象
        """
        today = datetime.now().strftime("%Y-%m-%d")
        existing = (
            self.db.query(EmotionRecordDB)
            .filter(
                EmotionRecordDB.user_id == self.user_id,
                EmotionRecordDB.date == today,
            )
            .first()
        )

        if existing:
            with transactional_scope(self.db):
                existing.emotion_type = emotion
                existing.intensity = level
                existing.trigger = trigger
                existing.note = note
            self.db.refresh(existing)
            return existing

        record = EmotionRecordDB(
            emotion_type=emotion,
            intensity=level,
            trigger=trigger,
            note=note,
            date=today,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(record)
        self.db.refresh(record)
        return record

    # ------------------------------------------------------------------
    # 放松内容
    # ------------------------------------------------------------------

    def get_relax_contents(self, category: Optional[str] = None) -> List[RelaxContentDB]:
        """获取放松内容列表.

        Args:
            category: 分类筛选

        Returns:
            放松内容列表
        """
        query = self.db.query(RelaxContentDB)
        if category:
            query = query.filter(RelaxContentDB.category == category)
        return query.order_by(RelaxContentDB.id.asc()).all()

    def get_relax_content(self, content_id: int) -> Optional[RelaxContentDB]:
        """获取放松内容详情.

        Args:
            content_id: 内容ID

        Returns:
            放松内容对象，不存在返回 None
        """
        return self.db.query(RelaxContentDB).filter(RelaxContentDB.id == content_id).first()

    # ------------------------------------------------------------------
    # 助眠内容
    # ------------------------------------------------------------------

    def get_sleep_contents(self, category: Optional[str] = None) -> List[SleepContentDB]:
        """获取助眠内容列表.

        Args:
            category: 分类筛选

        Returns:
            助眠内容列表
        """
        query = self.db.query(SleepContentDB)
        if category:
            query = query.filter(SleepContentDB.category == category)
        return query.order_by(SleepContentDB.id.asc()).all()

    # ------------------------------------------------------------------
    # 心理测评
    # ------------------------------------------------------------------

    def get_assessments(self) -> List[PsychAssessmentDB]:
        """获取测评列表.

        Returns:
            测评列表
        """
        return self.db.query(PsychAssessmentDB).order_by(PsychAssessmentDB.id.asc()).all()

    def get_assessment(self, assessment_id: int) -> Optional[PsychAssessmentDB]:
        """获取测评详情.

        Args:
            assessment_id: 测评ID

        Returns:
            测评对象，不存在返回 None
        """
        return self.db.query(PsychAssessmentDB).filter(PsychAssessmentDB.id == assessment_id).first()

    def get_assessment_results(self) -> List[AssessmentResultDB]:
        """获取测评历史.

        Returns:
            测评结果列表
        """
        return (
            self.db.query(AssessmentResultDB)
            .filter(AssessmentResultDB.user_id == self.user_id)
            .order_by(desc(AssessmentResultDB.created_at))
            .all()
        )

    def submit_assessment(
        self,
        assessment_id: int,
        answers: Dict[str, int],
    ) -> AssessmentResultDB:
        """提交测评并计算结果.

        Args:
            assessment_id: 测评ID
            answers: 答题记录

        Returns:
            测评结果对象

        Raises:
            ValueError: 测评不存在
        """
        assessment = self.get_assessment(assessment_id)
        if not assessment:
            raise ValueError("测评不存在")

        # 计算分数
        total_score = sum(v for v in answers.values() if isinstance(v, int))
        max_score = len(assessment.questions_json or []) * 3
        percentage = total_score / max_score * 100 if max_score > 0 else 0

        # 根据类型判断等级和建议
        if assessment.assessment_type == "stress":
            if percentage < 30:
                result_text = "压力水平很低"
                level = "low"
                suggestion = "你的压力水平很低，继续保持轻松愉快的生活状态。"
            elif percentage < 60:
                result_text = "轻度压力"
                level = "normal"
                suggestion = "你的压力处于正常范围，注意劳逸结合，适当放松。"
            elif percentage < 80:
                result_text = "中度压力"
                level = "moderate"
                suggestion = "你承受着中度压力，建议增加放松练习，必要时寻求支持。"
            else:
                result_text = "高度压力"
                level = "high"
                suggestion = "你的压力水平较高，建议寻求专业帮助。"
        elif assessment.assessment_type == "emotion":
            if percentage > 70:
                result_text = "情绪状态优秀"
                level = "excellent"
                suggestion = "你的情绪状态非常好，继续保持积极心态！"
            elif percentage > 50:
                result_text = "情绪状态良好"
                level = "good"
                suggestion = "你的情绪状态良好，保持乐观积极的生活态度。"
            elif percentage > 30:
                result_text = "情绪一般"
                level = "normal"
                suggestion = "情绪有些波动是正常的，试着多关注自己的情绪需求。"
            else:
                result_text = "情绪较低落"
                level = "low"
                suggestion = "近期情绪较低落，建议多和朋友交流，必要时寻求帮助。"
        else:  # sleep
            if percentage > 70:
                result_text = "睡眠质量优秀"
                level = "excellent"
                suggestion = "你的睡眠质量非常好，继续保持良好的作息习惯。"
            elif percentage > 50:
                result_text = "睡眠质量良好"
                level = "good"
                suggestion = "睡眠质量还不错，可以进一步优化作息。"
            elif percentage > 30:
                result_text = "睡眠质量一般"
                level = "normal"
                suggestion = "睡眠质量有待提高，建议调整作息规律。"
            else:
                result_text = "睡眠质量较差"
                level = "poor"
                suggestion = "睡眠质量较差，建议改善睡眠环境和作息。"

        result = AssessmentResultDB(
            assessment_id=assessment_id,
            title=assessment.title,
            score=total_score,
            result_text=result_text,
            level=level,
            answers_json=answers,
            suggestion=suggestion,
            user_id=self.user_id,
            date=datetime.now().strftime("%Y-%m-%d"),
        )
        with transactional_scope(self.db):
            self.db.add(result)
        self.db.refresh(result)
        return result

    # ------------------------------------------------------------------
    # 心情日记
    # ------------------------------------------------------------------

    def get_mood_entries(self, emotion: Optional[str] = None) -> List[MoodDiaryDB]:
        """获取心情日记列表.

        Args:
            emotion: 按情绪筛选

        Returns:
            心情日记列表
        """
        query = self.db.query(MoodDiaryDB).filter(MoodDiaryDB.user_id == self.user_id)
        if emotion:
            query = query.filter(MoodDiaryDB.mood == emotion)
        return query.order_by(desc(MoodDiaryDB.created_at)).all()

    def create_mood_entry(
        self,
        emotion: str,
        content: str,
        tags: List[str] | None = None,
    ) -> MoodDiaryDB:
        """创建心情日记.

        Args:
            emotion: 心情类型
            content: 日记内容
            tags: 标签列表

        Returns:
            新建的心情日记对象
        """
        entry = MoodDiaryDB(
            mood=emotion,
            content=content,
            tags=tags or [],
            date=datetime.now().strftime("%Y-%m-%d"),
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(entry)
        self.db.refresh(entry)
        return entry
