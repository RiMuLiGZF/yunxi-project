"""形象工坊 - 数据访问层.

封装形象工坊相关的数据库 CRUD 操作。
首次访问时自动初始化默认数据。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session

from src.common.db_transaction import transactional_scope
from src.models.db import (
    AppearanceConfigDB,
    MoodHistoryDB,
    AppearanceSnapshotDB,
    PersonalityTagDB,
    VoiceOptionDB,
)

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 默认数据（用于首次初始化）
# ---------------------------------------------------------------------------

_DEFAULT_PERSONALITY_TAGS: list[dict[str, Any]] = [
    {"tag_id": 1, "name": "温柔", "category": "性格", "is_default": True},
    {"tag_id": 2, "name": "智慧", "category": "性格", "is_default": True},
    {"tag_id": 3, "name": "陪伴", "category": "性格", "is_default": True},
    {"tag_id": 4, "name": "创造力", "category": "能力", "is_default": True},
    {"tag_id": 5, "name": "幽默", "category": "性格", "is_default": False},
    {"tag_id": 6, "name": "理性", "category": "性格", "is_default": False},
    {"tag_id": 7, "name": "感性", "category": "性格", "is_default": False},
    {"tag_id": 8, "name": "冒险", "category": "性格", "is_default": False},
    {"tag_id": 9, "name": "记忆力", "category": "能力", "is_default": False},
    {"tag_id": 10, "name": "逻辑推理", "category": "能力", "is_default": False},
    {"tag_id": 11, "name": "艺术感", "category": "能力", "is_default": False},
    {"tag_id": 12, "name": "领导力", "category": "能力", "is_default": False},
]

_DEFAULT_VOICE_OPTIONS: list[dict[str, Any]] = [
    {"voice_id": "warm_female", "name": "温暖女声", "description": "柔和温暖的女声，适合陪伴"},
    {"voice_id": "clear_female", "name": "清澈女声", "description": "清脆明亮的女声，适合对话"},
    {"voice_id": "gentle_male", "name": "温柔男声", "description": "低沉温柔的男声，令人安心"},
    {"voice_id": "cute_child", "name": "可爱童声", "description": "活泼可爱的童声，充满活力"},
    {"voice_id": "robot", "name": "机械音", "description": "科技感十足的机械音"},
]

_DEFAULT_SNAPSHOTS: list[dict[str, Any]] = [
    {"name": "初始形象", "theme": "default", "mood": "calm"},
    {"name": "夏日限定", "theme": "ocean", "mood": "happy"},
    {"name": "生日特别版", "theme": "sakura", "mood": "excited"},
]


def _seed_default_config(user_id: str = "default") -> AppearanceConfigDB:
    """创建默认形象配置.

    Args:
        user_id: 用户ID

    Returns:
        默认配置 ORM 对象
    """
    return AppearanceConfigDB(
        user_id=user_id,
        theme="default",
        primary_color="#6366f1",
        secondary_color="#a78bfa",
        accent_color="#f472b6",
        bg_color="#0f0f23",
        particle_count=120,
        particle_speed=1.5,
        glow_intensity=0.8,
        avatar_style="particle",
        mood="calm",
        personality_tags=["温柔", "智慧", "陪伴", "创造力"],
        voice_type="warm_female",
        voice_speed=1.0,
        voice_pitch=1.0,
        quality="high",
        model="Yunxi-Core",
        sync_enabled=True,
        relationship_level=3,
        intimacy=2580,
    )


# ---------------------------------------------------------------------------
# Repository 类
# ---------------------------------------------------------------------------


class AppearanceRepository:
    """形象工坊数据仓库.

    封装所有形象工坊相关的数据库操作。
    自动处理首次访问时的默认数据初始化。
    """

    def __init__(self, db: Session) -> None:
        """初始化数据仓库.

        Args:
            db: SQLAlchemy 数据库会话
        """
        self.db = db
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        """确保默认数据已初始化（幂等）."""
        # 初始化性格标签库
        tag_count = self.db.query(PersonalityTagDB).count()
        if tag_count == 0:
            with transactional_scope(self.db):
                for tag_data in _DEFAULT_PERSONALITY_TAGS:
                    tag = PersonalityTagDB(**tag_data)
                    self.db.add(tag)
            logger.info("性格标签库初始化完成")

        # 初始化声音选项库
        voice_count = self.db.query(VoiceOptionDB).count()
        if voice_count == 0:
            with transactional_scope(self.db):
                for voice_data in _DEFAULT_VOICE_OPTIONS:
                    voice = VoiceOptionDB(**voice_data)
                    self.db.add(voice)
            logger.info("声音选项库初始化完成")

    # ------------------------------------------------------------------
    # 形象配置
    # ------------------------------------------------------------------

    def get_config(self, user_id: str = "default") -> AppearanceConfigDB:
        """获取用户形象配置，不存在则创建默认配置.

        Args:
            user_id: 用户ID

        Returns:
            形象配置 ORM 对象
        """
        config = self.db.query(AppearanceConfigDB).filter(
            AppearanceConfigDB.user_id == user_id
        ).first()
        if not config:
            with transactional_scope(self.db):
                config = _seed_default_config(user_id)
                self.db.add(config)
                # 同时初始化默认快照（配置+快照在同一事务中）
                for i, snap_data in enumerate(_DEFAULT_SNAPSHOTS, 1):
                    snapshot = AppearanceSnapshotDB(
                        user_id=user_id,
                        name=snap_data["name"],
                        theme=snap_data["theme"],
                        mood=snap_data["mood"],
                        snapshot_data={},
                        created_at=datetime(2026, 6, 1) if i == 1 else
                                   datetime(2026, 6, 15) if i == 2 else
                                   datetime(2026, 7, 1),
                    )
                    self.db.add(snapshot)
            self.db.refresh(config)
        return config

    def update_config(
        self,
        user_id: str,
        **kwargs: Any,
    ) -> Optional[AppearanceConfigDB]:
        """更新用户形象配置.

        Args:
            user_id: 用户ID
            **kwargs: 要更新的字段键值对

        Returns:
            更新后的配置对象，不存在返回 None
        """
        config = self.get_config(user_id)
        if not config:
            return None

        with transactional_scope(self.db):
            for key, value in kwargs.items():
                if hasattr(config, key) and value is not None:
                    setattr(config, key, value)
        self.db.refresh(config)
        return config

    # ------------------------------------------------------------------
    # 心情历史
    # ------------------------------------------------------------------

    def add_mood_history(
        self,
        user_id: str,
        mood_type: str,
        reason: str = "",
    ) -> MoodHistoryDB:
        """添加心情切换记录.

        Args:
            user_id: 用户ID
            mood_type: 心情类型
            reason: 切换原因

        Returns:
            心情历史记录 ORM 对象
        """
        record = MoodHistoryDB(
            user_id=user_id,
            mood_type=mood_type,
            reason=reason,
        )
        with transactional_scope(self.db):
            self.db.add(record)
        self.db.refresh(record)
        return record

    def get_mood_history(
        self,
        user_id: str,
        limit: int = 20,
    ) -> List[MoodHistoryDB]:
        """获取心情切换历史.

        Args:
            user_id: 用户ID
            limit: 返回条数限制

        Returns:
            心情历史记录列表
        """
        return self.db.query(MoodHistoryDB).filter(
            MoodHistoryDB.user_id == user_id
        ).order_by(MoodHistoryDB.created_at.desc()).limit(limit).all()

    # ------------------------------------------------------------------
    # 快照
    # ------------------------------------------------------------------

    def get_snapshots(self, user_id: str) -> List[AppearanceSnapshotDB]:
        """获取用户所有快照.

        Args:
            user_id: 用户ID

        Returns:
            快照列表
        """
        # 确保配置已初始化（同时会初始化默认快照）
        self.get_config(user_id)
        return self.db.query(AppearanceSnapshotDB).filter(
            AppearanceSnapshotDB.user_id == user_id
        ).order_by(AppearanceSnapshotDB.created_at.desc()).all()

    def get_snapshot(
        self,
        snapshot_id: int,
        user_id: str,
    ) -> Optional[AppearanceSnapshotDB]:
        """按 ID 获取快照.

        Args:
            snapshot_id: 快照ID
            user_id: 用户ID

        Returns:
            快照对象，不存在返回 None
        """
        return self.db.query(AppearanceSnapshotDB).filter(
            AppearanceSnapshotDB.id == snapshot_id,
            AppearanceSnapshotDB.user_id == user_id,
        ).first()

    def save_snapshot(
        self,
        user_id: str,
        name: str,
        theme: str,
        mood: str,
        snapshot_data: Dict[str, Any] | None = None,
    ) -> AppearanceSnapshotDB:
        """保存当前形象为快照.

        Args:
            user_id: 用户ID
            name: 快照名称
            theme: 主题ID
            mood: 心情
            snapshot_data: 快照完整数据

        Returns:
            新建的快照对象
        """
        snapshot = AppearanceSnapshotDB(
            user_id=user_id,
            name=name,
            theme=theme,
            mood=mood,
            snapshot_data=snapshot_data or {},
        )
        with transactional_scope(self.db):
            self.db.add(snapshot)
        self.db.refresh(snapshot)
        return snapshot

    def delete_snapshot(
        self,
        snapshot_id: int,
        user_id: str,
    ) -> bool:
        """删除快照.

        Args:
            snapshot_id: 快照ID
            user_id: 用户ID

        Returns:
            True 删除成功，False 快照不存在
        """
        snapshot = self.get_snapshot(snapshot_id, user_id)
        if not snapshot:
            return False
        with transactional_scope(self.db):
            self.db.delete(snapshot)
        return True

    # ------------------------------------------------------------------
    # 性格标签库
    # ------------------------------------------------------------------

    def get_personality_tags(self) -> List[PersonalityTagDB]:
        """获取所有性格标签.

        Returns:
            性格标签列表
        """
        return self.db.query(PersonalityTagDB).order_by(PersonalityTagDB.tag_id).all()

    def get_user_selected_tags(self, user_id: str) -> List[str]:
        """获取用户选中的性格标签名称列表.

        Args:
            user_id: 用户ID

        Returns:
            选中的标签名称列表
        """
        config = self.get_config(user_id)
        return config.personality_tags or []

    def update_user_personality_tags(
        self,
        user_id: str,
        tags: List[str],
    ) -> List[str]:
        """更新用户选中的性格标签.

        Args:
            user_id: 用户ID
            tags: 标签名称列表

        Returns:
            更新后的标签列表
        """
        config = self.get_config(user_id)
        with transactional_scope(self.db):
            config.personality_tags = tags
        self.db.refresh(config)
        return config.personality_tags or []

    # ------------------------------------------------------------------
    # 声音选项库
    # ------------------------------------------------------------------

    def get_voice_options(self) -> List[VoiceOptionDB]:
        """获取所有声音选项.

        Returns:
            声音选项列表
        """
        return self.db.query(VoiceOptionDB).order_by(VoiceOptionDB.id).all()
