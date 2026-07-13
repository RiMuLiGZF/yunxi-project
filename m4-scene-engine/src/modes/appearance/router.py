"""形象工坊 - FastAPI 路由.

提供形象工坊模式的 REST API 接口。
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.models.db import get_session
from src.models import make_response
from src.modes.appearance.models import (
    ConfigUpdateRequest,
    MoodUpdateRequest,
    PersonalityTagsUpdateRequest,
    SnapshotSaveRequest,
)
from src.modes.appearance.service import AppearanceService


router = APIRouter(prefix="/api/v1/appearance", tags=["形象工坊"])


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------


def get_appearance_service(
    db: Session = Depends(get_session),
    user_id: str = Query("default", description="用户ID"),
) -> AppearanceService:
    """获取形象工坊服务实例.

    Args:
        db: 数据库会话
        user_id: 用户ID

    Returns:
        形象工坊服务实例
    """
    return AppearanceService(db, user_id=user_id)


# ---------------------------------------------------------------------------
# 配置管理
# ---------------------------------------------------------------------------


@router.get("/config", summary="获取形象配置")
async def get_config(
    service: AppearanceService = Depends(get_appearance_service),
):
    """获取用户的形象配置."""
    config = service.get_config()
    return make_response(data=config)


@router.put("/config", summary="更新形象配置")
async def update_config(
    req: ConfigUpdateRequest,
    service: AppearanceService = Depends(get_appearance_service),
):
    """更新用户的形象配置."""
    update_data = req.dict(exclude_unset=True)
    config = service.update_config(update_data)
    return make_response(message="配置更新成功", data=config)


# ---------------------------------------------------------------------------
# 主题管理
# ---------------------------------------------------------------------------


@router.get("/themes", summary="获取主题列表")
async def get_themes(
    service: AppearanceService = Depends(get_appearance_service),
):
    """获取所有可用主题."""
    themes = service.get_themes()
    return make_response(data=themes)


@router.post("/themes/{theme_id}/apply", summary="应用主题")
async def apply_theme(
    theme_id: str,
    service: AppearanceService = Depends(get_appearance_service),
):
    """应用指定主题到当前形象."""
    config = service.apply_theme(theme_id)
    if config is None:
        return make_response(code=404, message="主题不存在", data={})
    return make_response(message=f"主题已应用", data=config)


# ---------------------------------------------------------------------------
# 心情管理
# ---------------------------------------------------------------------------


@router.get("/moods", summary="获取心情状态列表")
async def get_moods(
    service: AppearanceService = Depends(get_appearance_service),
):
    """获取所有可用的心情状态."""
    moods = service.get_mood_states()
    return make_response(data=moods)


@router.post("/mood", summary="切换心情")
async def update_mood(
    req: MoodUpdateRequest,
    service: AppearanceService = Depends(get_appearance_service),
):
    """切换当前心情状态."""
    result = service.update_mood(req.mood)
    if result is None:
        return make_response(code=404, message="心情状态不存在", data={})
    return make_response(message="心情已切换", data=result)


# ---------------------------------------------------------------------------
# 性格标签
# ---------------------------------------------------------------------------


@router.get("/personality-tags", summary="获取性格标签")
async def get_personality_tags(
    service: AppearanceService = Depends(get_appearance_service),
):
    """获取所有性格标签及选中状态."""
    tags = service.get_personality_tags()
    return make_response(data=tags)


@router.put("/personality-tags", summary="更新性格标签")
async def update_personality_tags(
    req: PersonalityTagsUpdateRequest,
    service: AppearanceService = Depends(get_appearance_service),
):
    """更新用户选中的性格标签."""
    tags = service.update_personality_tags(req.tags)
    return make_response(message="性格标签已更新", data=tags)


# ---------------------------------------------------------------------------
# 声音选项
# ---------------------------------------------------------------------------


@router.get("/voices", summary="获取声音类型")
async def get_voice_types(
    service: AppearanceService = Depends(get_appearance_service),
):
    """获取所有可用的声音类型."""
    voices = service.get_voice_types()
    return make_response(data=voices)


# ---------------------------------------------------------------------------
# 关系等级
# ---------------------------------------------------------------------------


@router.get("/relationship", summary="获取关系状态")
async def get_relationship(
    service: AppearanceService = Depends(get_appearance_service),
):
    """获取当前关系等级和进度."""
    relationship = service.get_relationship()
    return make_response(data=relationship)


# ---------------------------------------------------------------------------
# 快照管理
# ---------------------------------------------------------------------------


@router.get("/snapshots", summary="获取历史快照")
async def get_snapshots(
    service: AppearanceService = Depends(get_appearance_service),
):
    """获取用户的所有形象快照."""
    snapshots = service.get_snapshots()
    return make_response(data=snapshots)


@router.post("/snapshots/{snapshot_id}/restore", summary="恢复历史快照")
async def restore_snapshot(
    snapshot_id: int,
    service: AppearanceService = Depends(get_appearance_service),
):
    """恢复指定的形象快照."""
    config = service.restore_snapshot(snapshot_id)
    if config is None:
        return make_response(code=404, message="快照不存在", data={})
    return make_response(message="快照已恢复", data=config)


@router.post("/snapshots/save", summary="保存当前形象为快照")
async def save_snapshot(
    req: SnapshotSaveRequest,
    service: AppearanceService = Depends(get_appearance_service),
):
    """将当前形象保存为新的快照."""
    snapshot = service.save_snapshot(req.name)
    return make_response(message="形象已保存", data=snapshot)
