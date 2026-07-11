"""
形象工坊数据仓库（Database 版）

封装形象工坊相关的数据库 CRUD 操作。
迁移过渡期：优先读 DB，DB 为空时自动从内存默认数据初始化。
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from ..models import (
    AppearanceConfig,
    MoodHistory,
    AppearanceSnapshot,
    PersonalityTag,
    VoiceOption,
)


# ========== 默认数据（用于首次初始化） ==========

_DEFAULT_PERSONALITY_TAGS = [
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

_DEFAULT_VOICE_OPTIONS = [
    {"voice_id": "warm_female", "name": "温暖女声", "description": "柔和温暖的女声，适合陪伴"},
    {"voice_id": "clear_female", "name": "清澈女声", "description": "清脆明亮的女声，适合对话"},
    {"voice_id": "gentle_male", "name": "温柔男声", "description": "低沉温柔的男声，令人安心"},
    {"voice_id": "cute_child", "name": "可爱童声", "description": "活泼可爱的童声，充满活力"},
    {"voice_id": "robot", "name": "机械音", "description": "科技感十足的机械音"},
]

_DEFAULT_SNAPSHOTS = [
    {"name": "初始形象", "theme": "default", "mood": "calm"},
    {"name": "夏日限定", "theme": "ocean", "mood": "happy"},
    {"name": "生日特别版", "theme": "sakura", "mood": "excited"},
]


def _seed_default_config(user_id: int = 1) -> AppearanceConfig:
    """创建默认形象配置"""
    return AppearanceConfig(
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


# ========== Repository ==========

class AppearanceRepository:
    """形象工坊数据仓库

    封装所有形象工坊相关的数据库操作。
    自动处理首次访问时的默认数据初始化。
    """

    def __init__(self, db: Session):
        self.db = db
        self._ensure_seeded()

    def _ensure_seeded(self):
        """确保默认数据已初始化（幂等）"""
        # 初始化性格标签库
        tag_count = self.db.query(PersonalityTag).count()
        if tag_count == 0:
            for tag_data in _DEFAULT_PERSONALITY_TAGS:
                tag = PersonalityTag(**tag_data)
                self.db.add(tag)
            self.db.commit()
            print("[Appearance] 性格标签库初始化完成")

        # 初始化声音选项库
        voice_count = self.db.query(VoiceOption).count()
        if voice_count == 0:
            for voice_data in _DEFAULT_VOICE_OPTIONS:
                voice = VoiceOption(**voice_data)
                self.db.add(voice)
            self.db.commit()
            print("[Appearance] 声音选项库初始化完成")

    # ---------- 形象配置 ----------

    def get_config(self, user_id: int = 1) -> AppearanceConfig:
        """获取用户形象配置，不存在则创建默认配置"""
        config = self.db.query(AppearanceConfig).filter(
            AppearanceConfig.user_id == user_id
        ).first()
        if not config:
            config = _seed_default_config(user_id)
            self.db.add(config)
            # 同时初始化默认快照
            for i, snap_data in enumerate(_DEFAULT_SNAPSHOTS, 1):
                snapshot = AppearanceSnapshot(
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
            self.db.commit()
            self.db.refresh(config)
        return config

    def update_config(self, user_id: int, **kwargs) -> Optional[AppearanceConfig]:
        """更新用户形象配置"""
        config = self.get_config(user_id)
        if not config:
            return None

        for key, value in kwargs.items():
            if hasattr(config, key) and value is not None:
                setattr(config, key, value)

        self.db.commit()
        self.db.refresh(config)
        return config

    # ---------- 心情历史 ----------

    def add_mood_history(self, user_id: int, mood_type: str, reason: str = "") -> MoodHistory:
        """添加心情切换记录"""
        record = MoodHistory(
            user_id=user_id,
            mood_type=mood_type,
            reason=reason,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_mood_history(self, user_id: int, limit: int = 20) -> List[MoodHistory]:
        """获取心情切换历史"""
        return self.db.query(MoodHistory).filter(
            MoodHistory.user_id == user_id
        ).order_by(MoodHistory.created_at.desc()).limit(limit).all()

    # ---------- 快照 ----------

    def get_snapshots(self, user_id: int) -> List[AppearanceSnapshot]:
        """获取用户所有快照"""
        # 确保配置已初始化（同时会初始化默认快照）
        self.get_config(user_id)
        return self.db.query(AppearanceSnapshot).filter(
            AppearanceSnapshot.user_id == user_id
        ).order_by(AppearanceSnapshot.created_at.desc()).all()

    def get_snapshot(self, snapshot_id: int, user_id: int) -> Optional[AppearanceSnapshot]:
        """按 ID 获取快照"""
        return self.db.query(AppearanceSnapshot).filter(
            AppearanceSnapshot.id == snapshot_id,
            AppearanceSnapshot.user_id == user_id,
        ).first()

    def save_snapshot(self, user_id: int, name: str, theme: str, mood: str,
                      snapshot_data: Dict[str, Any] = None) -> AppearanceSnapshot:
        """保存当前形象为快照"""
        snapshot = AppearanceSnapshot(
            user_id=user_id,
            name=name,
            theme=theme,
            mood=mood,
            snapshot_data=snapshot_data or {},
        )
        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)
        return snapshot

    def delete_snapshot(self, snapshot_id: int, user_id: int) -> bool:
        """删除快照"""
        snapshot = self.get_snapshot(snapshot_id, user_id)
        if not snapshot:
            return False
        self.db.delete(snapshot)
        self.db.commit()
        return True

    # ---------- 性格标签库 ----------

    def get_personality_tags(self) -> List[PersonalityTag]:
        """获取所有性格标签"""
        return self.db.query(PersonalityTag).order_by(PersonalityTag.tag_id).all()

    def get_user_selected_tags(self, user_id: int) -> List[str]:
        """获取用户选中的性格标签名称列表"""
        config = self.get_config(user_id)
        return config.personality_tags or []

    def update_user_personality_tags(self, user_id: int, tags: List[str]) -> List[str]:
        """更新用户选中的性格标签"""
        config = self.get_config(user_id)
        config.personality_tags = tags
        self.db.commit()
        self.db.refresh(config)
        return config.personality_tags or []

    # ---------- 声音选项库 ----------

    def get_voice_options(self) -> List[VoiceOption]:
        """获取所有声音选项"""
        return self.db.query(VoiceOption).order_by(VoiceOption.id).all()