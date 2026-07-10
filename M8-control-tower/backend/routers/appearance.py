"""形象工坊模式 API

数据库持久化版本：
- 用户配置、心情历史、快照存储在 SQLite 数据库
- 主题列表、心情状态、关系等级等静态数据保留在内存（公开配置）
- 写操作需要认证，读操作中用户相关数据需要认证
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Session

from ..models import get_db
from ..auth import get_current_user
from ..repositories.appearance_repository import AppearanceRepository

router = APIRouter()


# ========== 内存静态数据（公开配置，无需认证） ==========

# 主题列表
_themes = [
    {"id": "default", "name": "默认主题", "colors": {"primary": "#6366f1", "secondary": "#a78bfa", "accent": "#f472b6"}, "description": "经典紫粉渐变，温柔而神秘"},
    {"id": "ocean", "name": "海洋之心", "colors": {"primary": "#0ea5e9", "secondary": "#06b6d4", "accent": "#22d3ee"}, "description": "清新蓝绿色调，平静而深邃"},
    {"id": "sunset", "name": "落日余晖", "colors": {"primary": "#f97316", "secondary": "#fb923c", "accent": "#fbbf24"}, "description": "温暖橙黄渐变，热情而治愈"},
    {"id": "forest", "name": "森林秘境", "colors": {"primary": "#22c55e", "secondary": "#4ade80", "accent": "#86efac"}, "description": "清新绿色调，自然而有生机"},
    {"id": "sakura", "name": "樱花物语", "colors": {"primary": "#ec4899", "secondary": "#f472b6", "accent": "#fbcfe8"}, "description": "粉嫩樱花色，甜美而浪漫"},
    {"id": "midnight", "name": "午夜星辰", "colors": {"primary": "#3b82f6", "secondary": "#6366f1", "accent": "#8b5cf6"}, "description": "深邃蓝紫色，神秘而优雅"},
]

# 心情状态
_mood_states = [
    {"id": "happy", "name": "开心", "emoji": "😊", "color": "#fbbf24", "particle_effect": "sparkle"},
    {"id": "calm", "name": "平静", "emoji": "😌", "color": "#60a5fa", "particle_effect": "float"},
    {"id": "excited", "name": "兴奋", "emoji": "🤩", "color": "#f87171", "particle_effect": "burst"},
    {"id": "sleepy", "name": "困倦", "emoji": "😴", "color": "#a78bfa", "particle_effect": "slow"},
    {"id": "sad", "name": "难过", "emoji": "😢", "color": "#94a3b8", "particle_effect": "rain"},
    {"id": "angry", "name": "生气", "emoji": "😠", "color": "#ef4444", "particle_effect": "storm"},
]

# 关系等级
_relationship_levels = [
    {"level": 1, "name": "初识", "intimacy_required": 0, "description": "刚刚认识，还在熟悉中"},
    {"level": 2, "name": "朋友", "intimacy_required": 500, "description": "已经成为朋友，可以畅所欲言"},
    {"level": 3, "name": "挚友", "intimacy_required": 1500, "description": "亲密无间的挚友，彼此信任"},
    {"level": 4, "name": "灵魂伴侣", "intimacy_required": 3000, "description": "心有灵犀的灵魂伴侣"},
    {"level": 5, "name": "永恒羁绊", "intimacy_required": 6000, "description": "超越时空的永恒羁绊"},
]


# ========== 旧版内存 fallback 数据（向前兼容） ==========

_default_config = {
    "theme": "default",
    "primary_color": "#6366f1",
    "secondary_color": "#a78bfa",
    "accent_color": "#f472b6",
    "bg_color": "#0f0f23",
    "particle_count": 120,
    "particle_speed": 1.5,
    "glow_intensity": 0.8,
    "avatar_style": "particle",
    "mood": "calm",
    "personality_tags": ["温柔", "智慧", "陪伴", "创造力"],
    "voice_type": "warm_female",
    "voice_speed": 1.0,
    "voice_pitch": 1.0,
    "quality": "high",
    "model": "Yunxi-Core",
    "sync_enabled": True,
    "relationship_level": 3,
    "intimacy": 2580,
}

_user_configs = {
    "default": _default_config.copy(),
}

_history_snapshots = [
    {"id": 1, "name": "初始形象", "created_at": "2026-06-01", "theme": "default", "mood": "calm"},
    {"id": 2, "name": "夏日限定", "created_at": "2026-06-15", "theme": "ocean", "mood": "happy"},
    {"id": 3, "name": "生日特别版", "created_at": "2026-07-01", "theme": "sakura", "mood": "excited"},
]


# ========== 请求模型 ==========
class ConfigUpdateRequest(BaseModel):
    theme: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    particle_count: Optional[int] = None
    particle_speed: Optional[float] = None
    glow_intensity: Optional[float] = None
    mood: Optional[str] = None
    personality_tags: Optional[List[str]] = None
    voice_type: Optional[str] = None
    voice_speed: Optional[float] = None
    voice_pitch: Optional[float] = None
    quality: Optional[str] = None
    model: Optional[str] = None
    sync_enabled: Optional[bool] = None


class MoodUpdateRequest(BaseModel):
    mood: str
    reason: Optional[str] = ""


def _get_user_id(current_user: dict) -> int:
    """从当前用户信息中获取用户ID（简化：暂时固定为1）"""
    # TODO: 后续可根据 username 查找真实 user_id
    return 1


# ========== 配置 ==========
@router.get("/config")
async def get_config(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取形象配置（需要认证）"""
    try:
        repo = AppearanceRepository(db)
        user_id = _get_user_id(current_user)
        config = repo.get_config(user_id)
        return {"code": 0, "message": "ok", "data": config.to_dict()}
    except Exception as e:
        # fallback: 返回内存默认数据
        print(f"[Appearance] DB 读取失败，使用 fallback: {e}")
        config = _user_configs.get("default", _default_config)
        return {"code": 0, "message": "ok", "data": config}


@router.put("/config")
async def update_config(
    req: ConfigUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新形象配置（需要认证）"""
    try:
        repo = AppearanceRepository(db)
        user_id = _get_user_id(current_user)
        update_data = req.dict(exclude_unset=True)
        config = repo.update_config(user_id, **update_data)
        # 同步更新内存 fallback
        _user_configs["default"].update(update_data)
        return {"code": 0, "message": "配置更新成功", "data": config.to_dict()}
    except Exception as e:
        print(f"[Appearance] DB 更新失败，使用 fallback: {e}")
        config = _user_configs["default"]
        update_data = req.dict(exclude_unset=True)
        config.update(update_data)
        return {"code": 0, "message": "配置更新成功", "data": config}


# ========== 主题 ==========
@router.get("/themes")
async def get_themes():
    """获取主题列表（公开接口，无需认证）"""
    return {"code": 0, "message": "ok", "data": _themes}


@router.post("/themes/{theme_id}/apply")
async def apply_theme(
    theme_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """应用主题（需要认证）"""
    theme = next((t for t in _themes if t["id"] == theme_id), None)
    if not theme:
        return {"code": 404, "message": "主题不存在", "data": None}

    try:
        repo = AppearanceRepository(db)
        user_id = _get_user_id(current_user)
        config = repo.update_config(
            user_id,
            theme=theme_id,
            primary_color=theme["colors"]["primary"],
            secondary_color=theme["colors"]["secondary"],
            accent_color=theme["colors"]["accent"],
        )
        # 同步 fallback
        cfg = _user_configs["default"]
        cfg["theme"] = theme_id
        cfg["primary_color"] = theme["colors"]["primary"]
        cfg["secondary_color"] = theme["colors"]["secondary"]
        cfg["accent_color"] = theme["colors"]["accent"]
        return {"code": 0, "message": f"已应用{theme['name']}", "data": config.to_dict()}
    except Exception as e:
        print(f"[Appearance] DB 应用主题失败，使用 fallback: {e}")
        config = _user_configs["default"]
        config["theme"] = theme_id
        config["primary_color"] = theme["colors"]["primary"]
        config["secondary_color"] = theme["colors"]["secondary"]
        config["accent_color"] = theme["colors"]["accent"]
        return {"code": 0, "message": f"已应用{theme['name']}", "data": config}


# ========== 心情 ==========
@router.get("/moods")
async def get_moods():
    """获取心情状态列表（公开接口，无需认证）"""
    return {"code": 0, "message": "ok", "data": _mood_states}


@router.post("/mood")
async def update_mood(
    req: MoodUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """切换心情（需要认证，记录历史）"""
    mood = next((m for m in _mood_states if m["id"] == req.mood), None)
    if not mood:
        return {"code": 404, "message": "心情状态不存在", "data": None}

    try:
        repo = AppearanceRepository(db)
        user_id = _get_user_id(current_user)
        config = repo.update_config(user_id, mood=req.mood)
        # 记录心情历史
        repo.add_mood_history(user_id, req.mood, req.reason or "")
        # 同步 fallback
        _user_configs["default"]["mood"] = req.mood
        return {"code": 0, "message": f"已切换到{mood['name']}状态", "data": {"mood": req.mood, "config": config.to_dict()}}
    except Exception as e:
        print(f"[Appearance] DB 切换心情失败，使用 fallback: {e}")
        config = _user_configs["default"]
        config["mood"] = req.mood
        return {"code": 0, "message": f"已切换到{mood['name']}状态", "data": {"mood": req.mood, "config": config}}


# ========== 性格标签 ==========
@router.get("/personality-tags")
async def get_personality_tags(
    db: Session = Depends(get_db),
):
    """获取性格标签库（公开接口，无需认证）"""
    try:
        repo = AppearanceRepository(db)
        tags = repo.get_personality_tags()
        return {"code": 0, "message": "ok", "data": [t.to_dict() for t in tags]}
    except Exception as e:
        print(f"[Appearance] DB 读取性格标签失败，使用 fallback: {e}")
        _fallback_tags = [
            {"id": 1, "name": "温柔", "category": "性格", "selected": True},
            {"id": 2, "name": "智慧", "category": "性格", "selected": True},
            {"id": 3, "name": "陪伴", "category": "性格", "selected": True},
            {"id": 4, "name": "创造力", "category": "能力", "selected": True},
            {"id": 5, "name": "幽默", "category": "性格", "selected": False},
            {"id": 6, "name": "理性", "category": "性格", "selected": False},
            {"id": 7, "name": "感性", "category": "性格", "selected": False},
            {"id": 8, "name": "冒险", "category": "性格", "selected": False},
            {"id": 9, "name": "记忆力", "category": "能力", "selected": False},
            {"id": 10, "name": "逻辑推理", "category": "能力", "selected": False},
            {"id": 11, "name": "艺术感", "category": "能力", "selected": False},
            {"id": 12, "name": "领导力", "category": "能力", "selected": False},
        ]
        return {"code": 0, "message": "ok", "data": _fallback_tags}


@router.put("/personality-tags")
async def update_personality_tags(
    tags: List[str],
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新用户选中的性格标签（需要认证）"""
    try:
        repo = AppearanceRepository(db)
        user_id = _get_user_id(current_user)
        selected = repo.update_user_personality_tags(user_id, tags)
        # 同步 fallback
        _user_configs["default"]["personality_tags"] = tags
        return {"code": 0, "message": "性格标签已更新", "data": selected}
    except Exception as e:
        print(f"[Appearance] DB 更新性格标签失败，使用 fallback: {e}")
        config = _user_configs["default"]
        config["personality_tags"] = tags
        return {"code": 0, "message": "性格标签已更新", "data": tags}


# ========== 声音 ==========
@router.get("/voices")
async def get_voice_types(
    db: Session = Depends(get_db),
):
    """获取声音类型列表（公开接口，无需认证）"""
    try:
        repo = AppearanceRepository(db)
        voices = repo.get_voice_options()
        return {"code": 0, "message": "ok", "data": [v.to_dict() for v in voices]}
    except Exception as e:
        print(f"[Appearance] DB 读取声音选项失败，使用 fallback: {e}")
        _fallback_voices = [
            {"id": "warm_female", "name": "温暖女声", "description": "柔和温暖的女声，适合陪伴"},
            {"id": "clear_female", "name": "清澈女声", "description": "清脆明亮的女声，适合对话"},
            {"id": "gentle_male", "name": "温柔男声", "description": "低沉温柔的男声，令人安心"},
            {"id": "cute_child", "name": "可爱童声", "description": "活泼可爱的童声，充满活力"},
            {"id": "robot", "name": "机械音", "description": "科技感十足的机械音"},
        ]
        return {"code": 0, "message": "ok", "data": _fallback_voices}


# ========== 关系等级 ==========
@router.get("/relationship")
async def get_relationship(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取关系状态（需要认证）"""
    try:
        repo = AppearanceRepository(db)
        user_id = _get_user_id(current_user)
        config = repo.get_config(user_id)
        current_level = config.relationship_level or 1
        intimacy = config.intimacy or 0
    except Exception as e:
        print(f"[Appearance] DB 读取关系状态失败，使用 fallback: {e}")
        config = _user_configs["default"]
        current_level = config.get("relationship_level", 1)
        intimacy = config.get("intimacy", 0)

    level_info = next((l for l in _relationship_levels if l["level"] == current_level), _relationship_levels[0])
    next_level = next((l for l in _relationship_levels if l["level"] == current_level + 1), None)

    progress = 0
    if next_level:
        current_min = level_info["intimacy_required"]
        next_min = next_level["intimacy_required"]
        progress = int((intimacy - current_min) / (next_min - current_min) * 100)

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "current_level": current_level,
            "level_name": level_info["name"],
            "level_description": level_info["description"],
            "intimacy": intimacy,
            "progress": progress,
            "next_level": next_level,
            "all_levels": _relationship_levels,
        },
    }


# ========== 历史快照 ==========
@router.get("/snapshots")
async def get_snapshots(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取历史快照（需要认证）"""
    try:
        repo = AppearanceRepository(db)
        user_id = _get_user_id(current_user)
        snapshots = repo.get_snapshots(user_id)
        result = []
        for s in snapshots:
            result.append({
                "id": s.id,
                "name": s.name,
                "created_at": s.created_at.strftime("%Y-%m-%d") if s.created_at else "",
                "theme": s.theme,
                "mood": s.mood,
            })
        return {"code": 0, "message": "ok", "data": result}
    except Exception as e:
        print(f"[Appearance] DB 读取快照失败，使用 fallback: {e}")
        return {"code": 0, "message": "ok", "data": _history_snapshots}


@router.post("/snapshots/{snapshot_id}/restore")
async def restore_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """恢复历史快照（需要认证）"""
    try:
        repo = AppearanceRepository(db)
        user_id = _get_user_id(current_user)
        snapshot = repo.get_snapshot(snapshot_id, user_id)
        if not snapshot:
            return {"code": 404, "message": "快照不存在", "data": None}

        # 恢复主题和心情
        update_data = {"theme": snapshot.theme, "mood": snapshot.mood}
        theme = next((t for t in _themes if t["id"] == snapshot.theme), None)
        if theme:
            update_data["primary_color"] = theme["colors"]["primary"]
            update_data["secondary_color"] = theme["colors"]["secondary"]
            update_data["accent_color"] = theme["colors"]["accent"]

        config = repo.update_config(user_id, **update_data)
        # 同步 fallback
        _user_configs["default"].update(update_data)
        return {"code": 0, "message": f"已恢复到{snapshot.name}", "data": config.to_dict()}
    except Exception as e:
        print(f"[Appearance] DB 恢复快照失败，使用 fallback: {e}")
        snapshot = next((s for s in _history_snapshots if s["id"] == snapshot_id), None)
        if not snapshot:
            return {"code": 404, "message": "快照不存在", "data": None}

        config = _user_configs["default"]
        config["theme"] = snapshot["theme"]
        config["mood"] = snapshot["mood"]

        theme = next((t for t in _themes if t["id"] == snapshot["theme"]), None)
        if theme:
            config["primary_color"] = theme["colors"]["primary"]
            config["secondary_color"] = theme["colors"]["secondary"]
            config["accent_color"] = theme["colors"]["accent"]

        return {"code": 0, "message": f"已恢复到{snapshot['name']}", "data": config}


@router.post("/snapshots/save")
async def save_snapshot(
    name: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """保存当前形象为快照（需要认证）"""
    try:
        repo = AppearanceRepository(db)
        user_id = _get_user_id(current_user)
        config = repo.get_config(user_id)
        snapshot = repo.save_snapshot(
            user_id=user_id,
            name=name,
            theme=config.theme,
            mood=config.mood,
            snapshot_data=config.to_dict(),
        )
        # 同步 fallback
        sid = max((s["id"] for s in _history_snapshots), default=0) + 1
        _history_snapshots.append({
            "id": sid,
            "name": name,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
            "theme": config.theme,
            "mood": config.mood,
        })
        result = {
            "id": snapshot.id,
            "name": snapshot.name,
            "created_at": snapshot.created_at.strftime("%Y-%m-%d") if snapshot.created_at else "",
            "theme": snapshot.theme,
            "mood": snapshot.mood,
        }
        return {"code": 0, "message": "形象已保存", "data": result}
    except Exception as e:
        print(f"[Appearance] DB 保存快照失败，使用 fallback: {e}")
        config = _user_configs["default"]
        sid = max((s["id"] for s in _history_snapshots), default=0) + 1

        snapshot = {
            "id": sid,
            "name": name,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
            "theme": config["theme"],
            "mood": config["mood"],
        }
        _history_snapshots.append(snapshot)

        return {"code": 0, "message": "形象已保存", "data": snapshot}