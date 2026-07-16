"""情绪陪伴 - FastAPI 路由.

提供情绪陪伴模式的 REST API 接口。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.models.db import get_session
from src.models import make_response
from src.modes.emotion_comfort.models import (
    EmotionRecordRequest,
    AssessmentSubmitRequest,
    MoodEntryRequest,
)
from src.modes.emotion_comfort.service import EmotionService


router = APIRouter(prefix="/api/v1/emotion-comfort", tags=["情绪陪伴"])


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------


def get_emotion_service(
    db: Session = Depends(get_session),
    user_id: str = Query("default", description="用户ID"),
) -> EmotionService:
    """获取情绪陪伴服务实例.

    Args:
        db: 数据库会话
        user_id: 用户ID

    Returns:
        情绪陪伴服务实例
    """
    return EmotionService(db, user_id=user_id)


# ---------------------------------------------------------------------------
# 概览
# ---------------------------------------------------------------------------


@router.get("/overview", summary="情绪陪伴概览")
async def get_overview(
    service: EmotionService = Depends(get_emotion_service),
):
    """获取情绪陪伴概览数据."""
    overview = service.get_overview()
    return make_response(data=overview)


# ---------------------------------------------------------------------------
# 情绪记录
# ---------------------------------------------------------------------------


@router.get("/emotions", summary="获取情绪记录")
async def get_emotions(
    days: int = Query(30, description="最近 N 天", ge=1, le=365),
    service: EmotionService = Depends(get_emotion_service),
):
    """获取用户的情绪记录."""
    records = service.get_emotions(days)
    return make_response(data=records)


@router.get("/emotions/stats", summary="情绪统计")
async def get_emotion_stats(
    days: int = Query(30, description="统计天数", ge=1, le=365),
    service: EmotionService = Depends(get_emotion_service),
):
    """获取情绪统计数据."""
    stats = service.get_emotion_stats(days)
    return make_response(data=stats)


@router.post("/emotions", summary="记录情绪")
async def record_emotion(
    req: EmotionRecordRequest,
    service: EmotionService = Depends(get_emotion_service),
):
    """记录今日的情绪状态."""
    record = service.record_emotion(
        emotion=req.emotion,
        level=req.level,
        trigger=req.trigger,
        note=req.note,
    )
    return make_response(message="情绪记录成功", data=record)


# ---------------------------------------------------------------------------
# 放松引导
# ---------------------------------------------------------------------------


@router.get("/relaxations", summary="获取放松引导列表")
async def get_relaxations(
    rtype: Optional[str] = Query(None, description="类型筛选"),
    service: EmotionService = Depends(get_emotion_service),
):
    """获取放松引导内容列表."""
    items = service.get_relaxations(rtype)
    return make_response(data=items)


@router.get("/relaxations/{rid}", summary="获取放松引导详情")
async def get_relaxation_detail(
    rid: int,
    service: EmotionService = Depends(get_emotion_service),
):
    """获取放松引导内容详情."""
    item = service.get_relaxation_detail(rid)
    if item is None:
        return make_response(code=404, message="内容不存在", data={})
    return make_response(data=item)


# ---------------------------------------------------------------------------
# 助眠内容
# ---------------------------------------------------------------------------


@router.get("/sleep", summary="获取助眠内容列表")
async def get_sleep_contents(
    stype: Optional[str] = Query(None, description="类型筛选"),
    service: EmotionService = Depends(get_emotion_service),
):
    """获取助眠内容列表."""
    items = service.get_sleep_contents(stype)
    return make_response(data=items)


# ---------------------------------------------------------------------------
# 心理测评
# ---------------------------------------------------------------------------


@router.get("/assessments", summary="获取测评列表")
async def get_assessments(
    service: EmotionService = Depends(get_emotion_service),
):
    """获取心理测评列表（不含题目）."""
    assessments = service.get_assessments()
    return make_response(data=assessments)


@router.get("/assessments/results", summary="获取测评历史")
async def get_assessment_results(
    service: EmotionService = Depends(get_emotion_service),
):
    """获取用户的测评历史记录."""
    results = service.get_assessment_results()
    return make_response(data=results)


@router.get("/assessments/{aid}", summary="获取测评详情")
async def get_assessment_detail(
    aid: int,
    service: EmotionService = Depends(get_emotion_service),
):
    """获取测评详情（含题目）."""
    assessment = service.get_assessment_detail(aid)
    if assessment is None:
        return make_response(code=404, message="测评不存在", data={})
    return make_response(data=assessment)


@router.post("/assessments/submit", summary="提交测评")
async def submit_assessment(
    req: AssessmentSubmitRequest,
    service: EmotionService = Depends(get_emotion_service),
):
    """提交测评答案并计算结果."""
    result = service.submit_assessment(req.assessment_id, req.answers)
    if result is None:
        return make_response(code=404, message="测评不存在", data={})
    return make_response(message="测评完成", data=result)


# ---------------------------------------------------------------------------
# 心情日记
# ---------------------------------------------------------------------------


@router.get("/mood-entries", summary="获取心情日记")
async def get_mood_entries(
    emotion: Optional[str] = Query(None, description="按情绪筛选"),
    service: EmotionService = Depends(get_emotion_service),
):
    """获取心情日记列表."""
    entries = service.get_mood_entries(emotion)
    return make_response(data=entries)


@router.post("/mood-entries", summary="创建心情日记")
async def create_mood_entry(
    req: MoodEntryRequest,
    service: EmotionService = Depends(get_emotion_service),
):
    """创建一篇新的心情日记."""
    entry = service.create_mood_entry(
        emotion=req.emotion,
        content=req.content,
        tags=req.tags,
    )
    return make_response(message="日记保存成功", data=entry)
