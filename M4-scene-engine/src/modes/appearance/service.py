"""形象工坊 - 业务逻辑层.

封装形象工坊的业务逻辑，包括主题管理、心情切换、
性格标签、关系等级、快照管理等功能。
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from src.modes.appearance.repository import AppearanceRepository


# ---------------------------------------------------------------------------
# 常量数据
# ---------------------------------------------------------------------------

# 主题列表
THEMES: list[dict[str, Any]] = [
    {"id": "default", "name": "默认主题", "colors": {"primary": "#6366f1", "secondary": "#a78bfa", "accent": "#f472b6"}, "description": "经典紫粉渐变，温柔而神秘"},
    {"id": "ocean", "name": "海洋之心", "colors": {"primary": "#0ea5e9", "secondary": "#06b6d4", "accent": "#22d3ee"}, "description": "清新蓝绿色调，平静而深邃"},
    {"id": "sunset", "name": "落日余晖", "colors": {"primary": "#f97316", "secondary": "#fb923c", "accent": "#fbbf24"}, "description": "温暖橙黄渐变，热情而治愈"},
    {"id": "forest", "name": "森林秘境", "colors": {"primary": "#22c55e", "secondary": "#4ade80", "accent": "#86efac"}, "description": "清新绿色调，自然而有生机"},
    {"id": "sakura", "name": "樱花物语", "colors": {"primary": "#ec4899", "secondary": "#f472b6", "accent": "#fbcfe8"}, "description": "粉嫩樱花色，甜美而浪漫"},
    {"id": "midnight", "name": "午夜星辰", "colors": {"primary": "#3b82f6", "secondary": "#6366f1", "accent": "#8b5cf6"}, "description": "深邃蓝紫色，神秘而优雅"},
]

# 心情状态
MOOD_STATES: list[dict[str, Any]] = [
    {"id": "happy", "name": "开心", "emoji": "😊", "color": "#fbbf24", "particle_effect": "sparkle"},
    {"id": "calm", "name": "平静", "emoji": "😌", "color": "#60a5fa", "particle_effect": "float"},
    {"id": "excited", "name": "兴奋", "emoji": "🤩", "color": "#f87171", "particle_effect": "burst"},
    {"id": "sleepy", "name": "困倦", "emoji": "😴", "color": "#a78bfa", "particle_effect": "slow"},
    {"id": "sad", "name": "难过", "emoji": "😢", "color": "#94a3b8", "particle_effect": "rain"},
    {"id": "angry", "name": "生气", "emoji": "😠", "color": "#ef4444", "particle_effect": "storm"},
]

# 关系等级
RELATIONSHIP_LEVELS: list[dict[str, Any]] = [
    {"level": 1, "name": "初识", "intimacy_required": 0, "description": "刚刚认识，还在熟悉中"},
    {"level": 2, "name": "朋友", "intimacy_required": 500, "description": "已经成为朋友，可以畅所欲言"},
    {"level": 3, "name": "挚友", "intimacy_required": 1500, "description": "亲密无间的挚友，彼此信任"},
    {"level": 4, "name": "灵魂伴侣", "intimacy_required": 3000, "description": "心有灵犀的灵魂伴侣"},
    {"level": 5, "name": "永恒羁绊", "intimacy_required": 6000, "description": "超越时空的永恒羁绊"},
]


# ---------------------------------------------------------------------------
# Service 类
# ---------------------------------------------------------------------------


class AppearanceService:
    """形象工坊业务逻辑服务.

    封装形象工坊的所有业务逻辑，调用 Repository 层进行数据持久化。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化服务.

        Args:
            db: SQLAlchemy 数据库会话
            user_id: 用户ID
        """
        self.repository = AppearanceRepository(db)
        self.user_id = user_id

    # ------------------------------------------------------------------
    # 配置管理
    # ------------------------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        """获取用户形象配置.

        Returns:
            形象配置字典
        """
        config = self.repository.get_config(self.user_id)
        return config.to_dict()

    def update_config(self, update_data: dict[str, Any]) -> dict[str, Any]:
        """更新用户形象配置.

        Args:
            update_data: 要更新的配置字段字典

        Returns:
            更新后的配置字典
        """
        config = self.repository.update_config(self.user_id, **update_data)
        if config is None:
            return {}
        return config.to_dict()

    # ------------------------------------------------------------------
    # 主题管理
    # ------------------------------------------------------------------

    def get_themes(self) -> list[dict[str, Any]]:
        """获取主题列表.

        Returns:
            主题列表
        """
        return THEMES

    def apply_theme(self, theme_id: str) -> Optional[dict[str, Any]]:
        """应用指定主题.

        Args:
            theme_id: 主题ID

        Returns:
            更新后的配置字典，主题不存在返回 None
        """
        theme = next((t for t in THEMES if t["id"] == theme_id), None)
        if not theme:
            return None

        update_data = {
            "theme": theme_id,
            "primary_color": theme["colors"]["primary"],
            "secondary_color": theme["colors"]["secondary"],
            "accent_color": theme["colors"]["accent"],
        }
        return self.update_config(update_data)

    # ------------------------------------------------------------------
    # 心情管理
    # ------------------------------------------------------------------

    def get_mood_states(self) -> list[dict[str, Any]]:
        """获取心情状态列表.

        Returns:
            心情状态列表
        """
        return MOOD_STATES

    def update_mood(self, mood: str, reason: str = "") -> Optional[dict[str, Any]]:
        """切换心情.

        Args:
            mood: 心情类型ID
            reason: 切换原因

        Returns:
            包含心情和配置的结果字典，心情不存在返回 None
        """
        mood_state = next((m for m in MOOD_STATES if m["id"] == mood), None)
        if not mood_state:
            return None

        config = self.repository.update_config(self.user_id, mood=mood)
        if config is None:
            return None

        # 记录心情历史
        self.repository.add_mood_history(self.user_id, mood, reason)

        return {
            "mood": mood,
            "config": config.to_dict(),
        }

    # ------------------------------------------------------------------
    # 性格标签
    # ------------------------------------------------------------------

    def get_personality_tags(self) -> list[dict[str, Any]]:
        """获取性格标签列表（含选中状态）.

        Returns:
            性格标签列表
        """
        tags_db = self.repository.get_personality_tags()
        selected_tags = self.repository.get_user_selected_tags(self.user_id)

        result = []
        for tag in tags_db:
            tag_dict = tag.to_dict()
            tag_dict["selected"] = tag.name in selected_tags
            result.append(tag_dict)
        return result

    def update_personality_tags(self, tags: List[str]) -> List[str]:
        """更新用户选中的性格标签.

        Args:
            tags: 选中的标签名称列表

        Returns:
            更新后的标签列表
        """
        return self.repository.update_user_personality_tags(self.user_id, tags)

    # ------------------------------------------------------------------
    # 声音选项
    # ------------------------------------------------------------------

    def get_voice_types(self) -> list[dict[str, Any]]:
        """获取声音类型列表.

        Returns:
            声音类型列表
        """
        voices = self.repository.get_voice_options()
        return [v.to_dict() for v in voices]

    # ------------------------------------------------------------------
    # 关系等级
    # ------------------------------------------------------------------

    def get_relationship(self) -> dict[str, Any]:
        """获取关系状态.

        Returns:
            关系状态字典
        """
        config = self.repository.get_config(self.user_id)
        current_level = config.relationship_level or 1
        intimacy = config.intimacy or 0

        level_info = next(
            (l for l in RELATIONSHIP_LEVELS if l["level"] == current_level),
            RELATIONSHIP_LEVELS[0],
        )
        next_level = next(
            (l for l in RELATIONSHIP_LEVELS if l["level"] == current_level + 1),
            None,
        )

        progress = 0
        if next_level:
            current_min = level_info["intimacy_required"]
            next_min = next_level["intimacy_required"]
            if next_min > current_min:
                progress = int((intimacy - current_min) / (next_min - current_min) * 100)

        return {
            "current_level": current_level,
            "level_name": level_info["name"],
            "level_description": level_info["description"],
            "intimacy": intimacy,
            "progress": progress,
            "next_level": next_level,
            "all_levels": RELATIONSHIP_LEVELS,
        }

    # ------------------------------------------------------------------
    # 快照管理
    # ------------------------------------------------------------------

    def get_snapshots(self) -> list[dict[str, Any]]:
        """获取历史快照列表.

        Returns:
            快照列表
        """
        snapshots = self.repository.get_snapshots(self.user_id)
        return [s.to_dict() for s in snapshots]

    def restore_snapshot(self, snapshot_id: int) -> Optional[dict[str, Any]]:
        """恢复历史快照.

        Args:
            snapshot_id: 快照ID

        Returns:
            更新后的配置字典，快照不存在返回 None
        """
        snapshot = self.repository.get_snapshot(snapshot_id, self.user_id)
        if not snapshot:
            return None

        update_data: dict[str, Any] = {
            "theme": snapshot.theme,
            "mood": snapshot.mood,
        }

        # 如果快照有完整数据，也应用主题颜色
        theme = next((t for t in THEMES if t["id"] == snapshot.theme), None)
        if theme:
            update_data["primary_color"] = theme["colors"]["primary"]
            update_data["secondary_color"] = theme["colors"]["secondary"]
            update_data["accent_color"] = theme["colors"]["accent"]

        return self.update_config(update_data)

    def save_snapshot(self, name: str) -> dict[str, Any]:
        """保存当前形象为快照.

        Args:
            name: 快照名称

        Returns:
            新建的快照字典
        """
        config = self.repository.get_config(self.user_id)
        snapshot = self.repository.save_snapshot(
            user_id=self.user_id,
            name=name,
            theme=config.theme,
            mood=config.mood,
            snapshot_data=config.to_dict(),
        )
        return snapshot.to_dict()
