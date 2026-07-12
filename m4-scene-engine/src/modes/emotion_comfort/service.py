"""情绪陪伴 - 业务逻辑层.

封装情绪陪伴的业务逻辑，包括情绪记录、放松引导、
助眠内容、心理测评、心情日记等功能。
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from src.modes.emotion_comfort.repository import EmotionRepository


# ---------------------------------------------------------------------------
# Service 类
# ---------------------------------------------------------------------------


class EmotionService:
    """情绪陪伴业务逻辑服务.

    封装情绪陪伴的所有业务逻辑，调用 Repository 层进行数据持久化。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化服务.

        Args:
            db: SQLAlchemy 数据库会话
            user_id: 用户ID
        """
        self.repository = EmotionRepository(db, user_id=user_id)
        self.user_id = user_id

    # ------------------------------------------------------------------
    # 概览
    # ------------------------------------------------------------------

    def get_overview(self) -> dict[str, Any]:
        """获取情绪陪伴概览.

        Returns:
            概览数据字典
        """
        return self.repository.get_overview_stats()

    # ------------------------------------------------------------------
    # 情绪记录
    # ------------------------------------------------------------------

    def get_emotions(self, days: int = 30) -> list[dict[str, Any]]:
        """获取情绪记录.

        Args:
            days: 最近 N 天

        Returns:
            情绪记录列表
        """
        records = self.repository.get_emotion_records(days)
        return [r.to_dict() for r in records]

    def get_emotion_stats(self, days: int = 30) -> dict[str, Any]:
        """获取情绪统计数据.

        Args:
            days: 统计天数

        Returns:
            统计数据字典
        """
        return self.repository.get_emotion_stats(days)

    def record_emotion(
        self,
        emotion: str,
        level: int,
        trigger: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        """记录情绪（今日已有则更新）.

        Args:
            emotion: 情绪类型
            level: 情绪强度
            trigger: 触发因素
            note: 备注

        Returns:
            情绪记录字典
        """
        record = self.repository.record_emotion(emotion, level, trigger, note)
        return record.to_dict()

    # ------------------------------------------------------------------
    # 放松引导
    # ------------------------------------------------------------------

    def get_relaxations(self, rtype: Optional[str] = None) -> list[dict[str, Any]]:
        """获取放松引导列表.

        Args:
            rtype: 类型筛选

        Returns:
            放松引导列表
        """
        items = self.repository.get_relax_contents(rtype)
        return [item.to_dict() for item in items]

    def get_relaxation_detail(self, rid: int) -> Optional[dict[str, Any]]:
        """获取放松引导详情.

        Args:
            rid: 内容ID

        Returns:
            放松引导详情，不存在返回 None
        """
        item = self.repository.get_relax_content(rid)
        if not item:
            return None
        return item.to_dict()

    # ------------------------------------------------------------------
    # 助眠内容
    # ------------------------------------------------------------------

    def get_sleep_contents(self, stype: Optional[str] = None) -> list[dict[str, Any]]:
        """获取助眠内容列表.

        Args:
            stype: 类型筛选

        Returns:
            助眠内容列表
        """
        items = self.repository.get_sleep_contents(stype)
        return [item.to_dict() for item in items]

    # ------------------------------------------------------------------
    # 心理测评
    # ------------------------------------------------------------------

    def get_assessments(self) -> list[dict[str, Any]]:
        """获取测评列表（不含题目）.

        Returns:
            测评列表
        """
        assessments = self.repository.get_assessments()
        return [a.to_simple_dict() for a in assessments]

    def get_assessment_results(self) -> list[dict[str, Any]]:
        """获取测评历史.

        Returns:
            测评结果列表
        """
        results = self.repository.get_assessment_results()
        return [r.to_dict() for r in results]

    def get_assessment_detail(self, aid: int) -> Optional[dict[str, Any]]:
        """获取测评详情（含题目）.

        Args:
            aid: 测评ID

        Returns:
            测评详情，不存在返回 None
        """
        assessment = self.repository.get_assessment(aid)
        if not assessment:
            return None
        return assessment.to_full_dict()

    def submit_assessment(
        self,
        assessment_id: int,
        answers: Dict[str, int],
    ) -> Optional[dict[str, Any]]:
        """提交测评并计算结果.

        Args:
            assessment_id: 测评ID
            answers: 答题记录

        Returns:
            测评结果字典，测评不存在返回 None
        """
        try:
            result = self.repository.submit_assessment(assessment_id, answers)
            return result.to_dict()
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # 心情日记
    # ------------------------------------------------------------------

    def get_mood_entries(self, emotion: Optional[str] = None) -> list[dict[str, Any]]:
        """获取心情日记列表.

        Args:
            emotion: 按情绪筛选

        Returns:
            心情日记列表
        """
        entries = self.repository.get_mood_entries(emotion)
        return [e.to_dict() for e in entries]

    def create_mood_entry(
        self,
        emotion: str,
        content: str,
        tags: List[str] | None = None,
    ) -> dict[str, Any]:
        """创建心情日记.

        Args:
            emotion: 心情类型
            content: 日记内容
            tags: 标签列表

        Returns:
            新建的日记字典
        """
        entry = self.repository.create_mood_entry(emotion, content, tags)
        return entry.to_dict()
