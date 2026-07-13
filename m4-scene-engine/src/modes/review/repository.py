"""复盘总结模式 - 数据访问层.

封装复盘记录、日记、决策记录、情绪记录、认知偏差的数据库 CRUD 操作。
首次使用时自动初始化种子数据，确保开箱即用。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from src.common.db_transaction import transactional_scope
from src.database import (
    ReviewBiasDB,
    ReviewDecisionDB,
    ReviewDiaryDB,
    ReviewEmotionDB,
    ReviewReviewDB,
)


# ---------------------------------------------------------------------------
# 种子数据
# ---------------------------------------------------------------------------


def _get_default_reviews(user_id: str = "default") -> list[ReviewReviewDB]:
    """获取默认复盘记录种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认复盘记录列表
    """
    now = datetime.utcnow()
    templates = [
        ("daily", "完成用户模块接口开发，修复3个bug", "high"),
        ("daily", "参与产品需求评审，确定Q3规划", "medium"),
        ("daily", "系统性能优化，响应速度提升40%", "high"),
        ("weekly", "本周完成3个功能模块，修复8个bug", "high"),
        ("monthly", "本月完成2个大版本迭代，交付15个功能点", "high"),
    ]
    type_names = ["日", "日", "日", "周", "月"]
    result = []
    for i, (rtype, summary, quality) in enumerate(templates):
        rid = i + 1
        date = now - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        content = f"""【完成工作】
1. {summary}

【问题与解决】
遇到接口性能问题，通过缓存优化解决

【明日计划】
1. 继续推进功能开发
2. 编写技术文档

【心得】
持续优化代码质量很重要"""
        result.append(ReviewReviewDB(
            review_id=rid,
            type=rtype,
            title=f"{type_names[i]}报 - {date_str}",
            content=content,
            quality=quality,
            date=date_str,
            word_count=200 + i * 50,
            insights=[],
            actions=[],
            created_at=date,
            updated_at=date,
            user_id=user_id,
        ))
    return result


def _get_default_diaries(user_id: str = "default") -> list[ReviewDiaryDB]:
    """获取默认日记种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认日记列表
    """
    now = datetime.utcnow()
    titles = [
        "关于职业规划的思考",
        "今天的学习收获",
        "一次重要的决策",
        "读书笔记：深度工作",
        "周末的反思",
    ]
    moods = ["happy", "calm", "neutral", "thoughtful", "excited"]
    result = []
    for i, title in enumerate(titles):
        did = i + 1
        date = now - timedelta(days=i * 3)
        content = (
            f"今天想了很多关于{title}的事情...\n\n"
            "记录一下当下的想法和感受。\n\n"
            "希望未来的自己看到这些文字时，能够有所感悟。"
        )
        result.append(ReviewDiaryDB(
            diary_id=did,
            title=title,
            content=content,
            mood=moods[i % 5],
            weather="",
            tags=["思考", "成长", "记录"][: (i % 3) + 1],
            word_count=150 + i * 30,
            encrypted=True,
            created_at=date,
            updated_at=date,
            user_id=user_id,
        ))
    return result


def _get_default_decisions(user_id: str = "default") -> list[ReviewDecisionDB]:
    """获取默认决策记录种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认决策记录列表
    """
    now = datetime.utcnow()
    titles = [
        "是否跳槽到新公司",
        "技术选型：React vs Vue",
        "是否读研深造",
        "买房还是租房",
    ]
    final_choices = ["选项A", "选项B", "选项A", ""]
    results = ["已执行，效果良好", "执行中", "已执行，需要观察", "待决策"]
    statuses = ["completed", "executing", "completed", "pending"]
    result = []
    for i, title in enumerate(titles):
        did = i + 1
        date = now - timedelta(days=i * 7)
        result.append(ReviewDecisionDB(
            decision_id=did,
            title=title,
            description=f"关于{title}的决策过程记录",
            alternatives=["选项A：积极推进", "选项B：保守观望", "选项C：暂缓决策"],
            outcome=results[i],
            lessons="",
            status=statuses[i],
            final_choice=final_choices[i],
            result=results[i],
            emotion_level=6 + i,
            created_at=date,
            updated_at=date,
            user_id=user_id,
        ))
    return result


def _get_default_emotions(user_id: str = "default") -> list[ReviewEmotionDB]:
    """获取默认情绪记录种子数据（最近 30 天）.

    Args:
        user_id: 用户 ID

    Returns:
        默认情绪记录列表
    """
    now = datetime.utcnow()
    emotions_list = [
        "happy", "calm", "neutral", "happy", "calm", "anxious", "calm",
        "happy", "happy", "neutral", "sad", "calm", "happy", "calm",
        "neutral", "happy", "calm", "happy", "anxious", "calm",
        "happy", "happy", "neutral", "calm", "happy", "calm",
        "happy", "calm", "neutral", "happy",
    ]
    result = []
    for i, emo in enumerate(emotions_list):
        date = now - timedelta(days=29 - i)
        date_str = date.strftime("%Y-%m-%d")
        result.append(ReviewEmotionDB(
            date=date_str,
            emotion=emo,
            intensity=5 + (i % 5),
            trigger="",
            note="",
            created_at=date,
            user_id=user_id,
        ))
    return result


def _get_default_biases(user_id: str = "default") -> list[ReviewBiasDB]:
    """获取默认认知偏差种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认认知偏差列表
    """
    now = datetime.utcnow()
    templates = [
        ("确认偏误", "在寻找信息时倾向于寻找支持自己观点的证据", "high", 3),
        ("锚定效应", "决策时过度依赖第一印象", "medium", 2),
        ("损失厌恶", "对损失的痛苦大于对收益的快乐", "medium", 1),
        ("幸存者偏差", "只关注成功案例而忽略失败案例", "low", 0),
    ]
    result = []
    for i, (name, desc, level, count) in enumerate(templates):
        bid = i + 1
        result.append(ReviewBiasDB(
            bias_id=bid,
            name=name,
            description=desc,
            category="",
            level=level,
            detected_count=count,
            last_detected=now - timedelta(days=i * 5) if count > 0 else None,
            suggestions=[
                "主动寻找反面证据",
                "考虑多个参考点",
                "使用决策平衡表",
            ],
            user_id=user_id,
        ))
    return result


def seed_review_data(db: Session, user_id: str = "default") -> bool:
    """初始化复盘总结模式的默认种子数据（幂等）.

    仅在复盘记录表为空时执行初始化。

    Args:
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        True 表示执行了初始化，False 表示已有数据跳过
    """
    review_count = (
        db.query(ReviewReviewDB)
        .filter(ReviewReviewDB.user_id == user_id)
        .count()
    )
    if review_count > 0:
        return False

    with transactional_scope(db):
        # 插入默认复盘记录
        for review in _get_default_reviews(user_id):
            db.add(review)

        # 插入默认日记
        for diary in _get_default_diaries(user_id):
            db.add(diary)

        # 插入默认决策记录
        for decision in _get_default_decisions(user_id):
            db.add(decision)

        # 插入默认情绪记录
        for emotion in _get_default_emotions(user_id):
            db.add(emotion)

        # 插入默认认知偏差
        for bias in _get_default_biases(user_id):
            db.add(bias)

    print(f"[Seed] 复盘总结模式默认数据初始化完成 (user_id={user_id})")
    return True


# ---------------------------------------------------------------------------
# Repository 类
# ---------------------------------------------------------------------------


class ReviewRepository:
    """复盘总结数据仓库.

    提供复盘记录、日记、决策记录、情绪记录、认知偏差的数据库操作。
    首次实例化时自动初始化种子数据。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化数据仓库.

        Args:
            db: 数据库会话
            user_id: 用户 ID
        """
        self.db = db
        self.user_id = user_id
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        """确保种子数据已初始化."""
        try:
            seed_review_data(self.db, self.user_id)
        except Exception as e:
            print(f"[Seed] 复盘总结数据初始化跳过: {e}")

    # -----------------------------------------------------------------------
    # 复盘记录相关方法
    # -----------------------------------------------------------------------

    def list_reviews(
        self,
        review_type: Optional[str] = None,
        limit: int = 20,
    ) -> list[ReviewReviewDB]:
        """获取复盘记录列表（支持筛选）.

        Args:
            review_type: 按类型筛选 daily/weekly/monthly
            limit: 返回条数限制

        Returns:
            复盘记录列表，按创建时间倒序
        """
        query = (
            self.db.query(ReviewReviewDB)
            .filter(ReviewReviewDB.user_id == self.user_id)
        )
        if review_type:
            query = query.filter(ReviewReviewDB.type == review_type)
        return query.order_by(desc(ReviewReviewDB.created_at)).limit(limit).all()

    def get_review(self, review_id: int) -> Optional[ReviewReviewDB]:
        """按业务 ID 获取复盘记录.

        Args:
            review_id: 复盘业务 ID

        Returns:
            复盘记录对象，不存在返回 None
        """
        return (
            self.db.query(ReviewReviewDB)
            .filter(
                ReviewReviewDB.review_id == review_id,
                ReviewReviewDB.user_id == self.user_id,
            )
            .first()
        )

    def create_review(
        self,
        rtype: str,
        title: str,
        content: str,
        date: str,
        quality: str = "medium",
    ) -> ReviewReviewDB:
        """创建复盘记录.

        Args:
            rtype: 类型 daily/weekly/monthly
            title: 标题
            content: 内容
            date: 日期字符串
            quality: 质量等级

        Returns:
            创建后的复盘记录对象
        """
        # 找最大的 review_id
        max_result = (
            self.db.query(func.max(ReviewReviewDB.review_id))
            .filter(ReviewReviewDB.user_id == self.user_id)
            .scalar()
        )
        rid = (max_result or 0) + 1

        now = datetime.utcnow()
        review = ReviewReviewDB(
            review_id=rid,
            type=rtype,
            title=title,
            content=content,
            quality=quality,
            date=date,
            word_count=len(content),
            insights=[],
            actions=[],
            created_at=now,
            updated_at=now,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(review)
        self.db.refresh(review)
        return review

    def delete_review(self, review_id: int) -> bool:
        """删除复盘记录.

        Args:
            review_id: 复盘业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        review = self.get_review(review_id)
        if not review:
            return False
        with transactional_scope(self.db):
            self.db.delete(review)
        return True

    def count_reviews(self) -> int:
        """统计复盘总数.

        Returns:
            复盘记录总数
        """
        return (
            self.db.query(ReviewReviewDB)
            .filter(ReviewReviewDB.user_id == self.user_id)
            .count()
        )

    def count_week_reviews(self) -> int:
        """统计本周复盘数.

        Returns:
            近 7 天的复盘数量
        """
        week_ago = datetime.utcnow() - timedelta(days=7)
        return (
            self.db.query(ReviewReviewDB)
            .filter(
                ReviewReviewDB.user_id == self.user_id,
                ReviewReviewDB.created_at >= week_ago,
            )
            .count()
        )

    # -----------------------------------------------------------------------
    # 日记相关方法
    # -----------------------------------------------------------------------

    def list_diaries(self, limit: int = 20) -> list[ReviewDiaryDB]:
        """获取日记列表.

        Args:
            limit: 返回条数限制

        Returns:
            日记列表，按创建时间倒序
        """
        return (
            self.db.query(ReviewDiaryDB)
            .filter(ReviewDiaryDB.user_id == self.user_id)
            .order_by(desc(ReviewDiaryDB.created_at))
            .limit(limit)
            .all()
        )

    def get_diary(self, diary_id: int) -> Optional[ReviewDiaryDB]:
        """按业务 ID 获取日记.

        Args:
            diary_id: 日记业务 ID

        Returns:
            日记对象，不存在返回 None
        """
        return (
            self.db.query(ReviewDiaryDB)
            .filter(
                ReviewDiaryDB.diary_id == diary_id,
                ReviewDiaryDB.user_id == self.user_id,
            )
            .first()
        )

    def create_diary(
        self,
        title: str,
        content: str,
        mood: str = "neutral",
        tags: Optional[list[str]] = None,
    ) -> ReviewDiaryDB:
        """创建日记.

        Args:
            title: 标题
            content: 内容
            mood: 心情
            tags: 标签列表

        Returns:
            创建后的日记对象
        """
        # 找最大的 diary_id
        max_result = (
            self.db.query(func.max(ReviewDiaryDB.diary_id))
            .filter(ReviewDiaryDB.user_id == self.user_id)
            .scalar()
        )
        did = (max_result or 0) + 1

        now = datetime.utcnow()
        diary = ReviewDiaryDB(
            diary_id=did,
            title=title,
            content=content,
            mood=mood,
            weather="",
            tags=tags or [],
            word_count=len(content),
            encrypted=True,
            created_at=now,
            updated_at=now,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(diary)
        self.db.refresh(diary)
        return diary

    def delete_diary(self, diary_id: int) -> bool:
        """删除日记.

        Args:
            diary_id: 日记业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        diary = self.get_diary(diary_id)
        if not diary:
            return False
        with transactional_scope(self.db):
            self.db.delete(diary)
        return True

    def count_diaries(self) -> int:
        """统计日记总数.

        Returns:
            日记总数
        """
        return (
            self.db.query(ReviewDiaryDB)
            .filter(ReviewDiaryDB.user_id == self.user_id)
            .count()
        )

    # -----------------------------------------------------------------------
    # 决策记录相关方法
    # -----------------------------------------------------------------------

    def list_decisions(self, limit: int = 20) -> list[ReviewDecisionDB]:
        """获取决策记录列表.

        Args:
            limit: 返回条数限制

        Returns:
            决策记录列表，按创建时间倒序
        """
        return (
            self.db.query(ReviewDecisionDB)
            .filter(ReviewDecisionDB.user_id == self.user_id)
            .order_by(desc(ReviewDecisionDB.created_at))
            .limit(limit)
            .all()
        )

    def get_decision(self, decision_id: int) -> Optional[ReviewDecisionDB]:
        """按业务 ID 获取决策记录.

        Args:
            decision_id: 决策业务 ID

        Returns:
            决策记录对象，不存在返回 None
        """
        return (
            self.db.query(ReviewDecisionDB)
            .filter(
                ReviewDecisionDB.decision_id == decision_id,
                ReviewDecisionDB.user_id == self.user_id,
            )
            .first()
        )

    def create_decision(
        self,
        title: str,
        description: str,
        options: list[str],
        final_choice: str = "",
        result: str = "",
        emotion_level: int = 5,
    ) -> ReviewDecisionDB:
        """创建决策记录.

        Args:
            title: 标题
            description: 描述
            options: 备选方案列表
            final_choice: 最终选择
            result: 结果描述
            emotion_level: 情绪强度 1-10

        Returns:
            创建后的决策记录对象
        """
        # 找最大的 decision_id
        max_result = (
            self.db.query(func.max(ReviewDecisionDB.decision_id))
            .filter(ReviewDecisionDB.user_id == self.user_id)
            .scalar()
        )
        did = (max_result or 0) + 1

        now = datetime.utcnow()
        status = "pending" if not final_choice else "completed"
        decision = ReviewDecisionDB(
            decision_id=did,
            title=title,
            description=description,
            alternatives=options,
            outcome=result,
            lessons="",
            status=status,
            final_choice=final_choice,
            result=result,
            emotion_level=emotion_level,
            created_at=now,
            updated_at=now,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(decision)
        self.db.refresh(decision)
        return decision

    def update_decision(
        self,
        decision_id: int,
        **kwargs: Any,
    ) -> Optional[ReviewDecisionDB]:
        """更新决策记录.

        支持字段名映射（兼容前端字段）：
        - options → alternatives

        Args:
            decision_id: 决策业务 ID
            **kwargs: 待更新的字段

        Returns:
            更新后的决策记录对象，不存在返回 None
        """
        decision = self.get_decision(decision_id)
        if not decision:
            return None

        # 字段名映射
        field_map = {
            "title": "title",
            "description": "description",
            "status": "status",
            "final_choice": "final_choice",
            "result": "result",
            "emotion_level": "emotion_level",
            "alternatives": "alternatives",
            "options": "alternatives",
        }

        with transactional_scope(self.db):
            # 特殊处理：设置 final_choice 自动标记状态
            if "final_choice" in kwargs and kwargs["final_choice"] and "status" not in kwargs:
                decision.status = "completed"

            for key, value in kwargs.items():
                if value is None:
                    continue
                attr = field_map.get(key)
                if attr and hasattr(decision, attr):
                    setattr(decision, attr, value)
                    # 同步更新 outcome
                    if key == "result":
                        decision.outcome = value

            decision.updated_at = datetime.utcnow()
        self.db.refresh(decision)
        return decision

    def delete_decision(self, decision_id: int) -> bool:
        """删除决策记录.

        Args:
            decision_id: 决策业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        decision = self.get_decision(decision_id)
        if not decision:
            return False
        with transactional_scope(self.db):
            self.db.delete(decision)
        return True

    def count_decisions(self) -> int:
        """统计决策总数.

        Returns:
            决策记录总数
        """
        return (
            self.db.query(ReviewDecisionDB)
            .filter(ReviewDecisionDB.user_id == self.user_id)
            .count()
        )

    # -----------------------------------------------------------------------
    # 情绪记录相关方法
    # -----------------------------------------------------------------------

    def list_emotions(self, days: int = 30) -> list[ReviewEmotionDB]:
        """获取情绪记录列表.

        Args:
            days: 获取最近 N 天的记录

        Returns:
            情绪记录列表，按日期倒序
        """
        return (
            self.db.query(ReviewEmotionDB)
            .filter(ReviewEmotionDB.user_id == self.user_id)
            .order_by(desc(ReviewEmotionDB.date))
            .limit(days)
            .all()
        )

    def create_emotion(
        self,
        emotion: str,
        intensity: int,
        trigger: str = "",
        note: str = "",
    ) -> ReviewEmotionDB:
        """记录情绪.

        Args:
            emotion: 情绪类型
            intensity: 强度 1-10
            trigger: 触发因素
            note: 备注

        Returns:
            创建后的情绪记录对象
        """
        now = datetime.utcnow()
        date_str = now.strftime("%Y-%m-%d")
        emotion_obj = ReviewEmotionDB(
            date=date_str,
            emotion=emotion,
            intensity=intensity,
            trigger=trigger,
            note=note,
            created_at=now,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(emotion_obj)
        self.db.refresh(emotion_obj)
        return emotion_obj

    def count_emotions(self) -> int:
        """统计情绪记录总数.

        Returns:
            情绪记录总数
        """
        return (
            self.db.query(ReviewEmotionDB)
            .filter(ReviewEmotionDB.user_id == self.user_id)
            .count()
        )

    def get_emotion_stats(self, days: int = 30) -> dict[str, Any]:
        """获取情绪统计数据.

        Args:
            days: 统计天数

        Returns:
            情绪统计字典
        """
        now = datetime.utcnow()
        start_date = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        recent = (
            self.db.query(ReviewEmotionDB)
            .filter(
                ReviewEmotionDB.user_id == self.user_id,
                ReviewEmotionDB.date >= start_date,
            )
            .order_by(ReviewEmotionDB.date.asc())
            .all()
        )

        # 按情绪类型统计
        emotion_counts: dict[str, int] = {}
        for e in recent:
            emotion_counts[e.emotion] = emotion_counts.get(e.emotion, 0) + 1

        # 情绪趋势（按天）
        daily: list[dict[str, Any]] = []
        for i in range(days - 1, -1, -1):
            date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            day_emotions = [e for e in recent if e.date == date]
            if day_emotions:
                avg_level = sum(e.intensity for e in day_emotions) / len(day_emotions)
                daily.append({
                    "date": date,
                    "avg_level": round(avg_level, 1),
                    "count": len(day_emotions),
                })
            else:
                daily.append({"date": date, "avg_level": 0, "count": 0})

        # 主导情绪
        dominant = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "neutral"

        avg_level = round(
            sum(e.intensity for e in recent) / len(recent), 1
        ) if recent else 0

        return {
            "total_records": len(recent),
            "emotion_distribution": emotion_counts,
            "dominant_emotion": dominant,
            "daily_trend": daily,
            "avg_level": avg_level,
        }

    # -----------------------------------------------------------------------
    # 认知偏差相关方法
    # -----------------------------------------------------------------------

    def list_biases(self) -> list[ReviewBiasDB]:
        """获取认知偏差列表.

        Returns:
            认知偏差列表
        """
        return (
            self.db.query(ReviewBiasDB)
            .filter(ReviewBiasDB.user_id == self.user_id)
            .all()
        )

    def increment_bias_detection(self, bias_name: str) -> None:
        """增加偏差检测计数.

        Args:
            bias_name: 偏差名称
        """
        bias = (
            self.db.query(ReviewBiasDB)
            .filter(
                ReviewBiasDB.name == bias_name,
                ReviewBiasDB.user_id == self.user_id,
            )
            .first()
        )
        if bias:
            with transactional_scope(self.db):
                bias.detected_count = (bias.detected_count or 0) + 1
                bias.last_detected = datetime.utcnow()

    def commit(self) -> None:
        """提交当前会话的更改（兼容旧代码）.

        注意：各写操作方法已使用 transactional_scope 自动管理事务，
        通常不需要手动调用此方法。保留此方法以保持向后兼容。
        """
        self.db.commit()

    # -----------------------------------------------------------------------
    # 连续打卡天数统计
    # -----------------------------------------------------------------------

    def get_streak_days(self) -> int:
        """计算连续打卡天数.

        从今天往回数，有复盘记录或情绪记录即算打卡。

        Returns:
            连续打卡天数
        """
        now = datetime.utcnow()
        reviews = (
            self.db.query(ReviewReviewDB)
            .filter(ReviewReviewDB.user_id == self.user_id)
            .all()
        )
        emotions = (
            self.db.query(ReviewEmotionDB)
            .filter(ReviewEmotionDB.user_id == self.user_id)
            .all()
        )
        streak = 0
        for i in range(30):
            date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            has_review = any(r.date == date for r in reviews)
            has_emotion = any(e.date == date for e in emotions)
            if has_review or has_emotion:
                streak += 1
            else:
                break
        return streak

    # -----------------------------------------------------------------------
    # 字数统计
    # -----------------------------------------------------------------------

    def get_total_words_reviews(self) -> int:
        """统计复盘总字数.

        Returns:
            复盘总字数
        """
        result = (
            self.db.query(func.sum(ReviewReviewDB.word_count))
            .filter(ReviewReviewDB.user_id == self.user_id)
            .scalar()
        )
        return int(result or 0)

    def get_total_words_diaries(self) -> int:
        """统计日记总字数.

        Returns:
            日记总字数
        """
        result = (
            self.db.query(func.sum(ReviewDiaryDB.word_count))
            .filter(ReviewDiaryDB.user_id == self.user_id)
            .scalar()
        )
        return int(result or 0)

    def get_quality_distribution(self) -> dict[str, int]:
        """获取复盘质量分布.

        Returns:
            质量分布字典 {high: n, medium: n, low: n}
        """
        distribution = {"high": 0, "medium": 0, "low": 0}
        reviews = (
            self.db.query(ReviewReviewDB)
            .filter(ReviewReviewDB.user_id == self.user_id)
            .all()
        )
        for r in reviews:
            if r.quality in distribution:
                distribution[r.quality] += 1
        return distribution

    def get_monthly_stats(self, months: int = 6) -> list[dict[str, Any]]:
        """获取月度统计数据.

        Args:
            months: 统计最近 N 个月

        Returns:
            月度统计列表
        """
        now = datetime.utcnow()
        reviews = (
            self.db.query(ReviewReviewDB)
            .filter(ReviewReviewDB.user_id == self.user_id)
            .all()
        )
        monthly_stats = []
        for i in range(months - 1, -1, -1):
            month_date = now - timedelta(days=i * 30)
            month_start = month_date.replace(day=1).strftime("%Y-%m")
            month_reviews = [
                r for r in reviews
                if r.created_at and r.created_at.strftime("%Y-%m") == month_start
            ]
            monthly_stats.append({
                "month": month_start,
                "review_count": len(month_reviews),
                "word_count": sum(r.word_count or 0 for r in month_reviews),
            })
        return monthly_stats
