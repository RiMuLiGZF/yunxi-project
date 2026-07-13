"""成长中心模式 - API 路由.

提供成长中心模式的 RESTful API 接口，
包括概览统计、成就勋章、天赋树、潮汐历法、
编年史、记忆回响、赛季征程等功能。
大部分接口直接代理到 M5 成长系统，
少数聚合接口（如 overview）在 service 层组装。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from src.models import make_response
from src.modes.growth.models import (
    CheckinRequest,
    ChronicleCreateRequest,
    ChronicleUpdateRequest,
    EchoGenerateRequest,
)
from src.modes.growth.service import GrowthService

router = APIRouter(
    prefix="/api/v1/growth",
    tags=["成长中心模式"],
)


def _get_service(x_user_id: str = "default") -> GrowthService:
    """获取 GrowthService 实例.

    Args:
        x_user_id: 用户 ID（从请求头获取）

    Returns:
        GrowthService 实例
    """
    return GrowthService(user_id=x_user_id)


# ---------------------------------------------------------------------------
# 概览统计
# ---------------------------------------------------------------------------


@router.get("/overview")
async def get_overview(
    x_user_id: str = Header("default"),
) -> dict:
    """获取成长中心概览统计.

    聚合成就统计、天赋点数、日历统计、当前赛季等数据，
    用于成长中心首页展示。
    """
    service = _get_service(x_user_id)
    overview = await service.get_overview()
    return make_response(data=overview, message="获取概览成功")


# ---------------------------------------------------------------------------
# 成就勋章
# ---------------------------------------------------------------------------


@router.get("/achievements")
async def list_achievements(
    category: Optional[str] = Query(None, description="分类过滤（growth/skill/social/special）"),
    status: Optional[str] = Query(None, description="状态过滤（unlocked/locked）"),
    x_user_id: str = Header("default"),
) -> dict:
    """获取成就列表.

    支持按分类和状态筛选。
    """
    service = _get_service(x_user_id)
    achievements = await service.list_achievements(
        category=category, status=status,
    )
    return make_response(data=achievements, message="获取成就列表成功")


@router.get("/achievements/stats")
async def get_achievement_stats(
    x_user_id: str = Header("default"),
) -> dict:
    """获取成就统计.

    返回总成就数、已解锁数、按分类和稀有度统计等。
    """
    service = _get_service(x_user_id)
    stats = await service.get_achievement_stats()
    return make_response(data=stats, message="获取成就统计成功")


@router.post("/achievements/{achievement_id}/unlock")
async def unlock_achievement(
    achievement_id: str,
    x_user_id: str = Header("default"),
) -> dict:
    """解锁指定成就.

    Args:
        achievement_id: 成就 ID
    """
    service = _get_service(x_user_id)
    result = await service.unlock_achievement(achievement_id)
    return make_response(data=result, message="成就解锁成功")


# ---------------------------------------------------------------------------
# 天赋树
# ---------------------------------------------------------------------------


@router.get("/talents")
async def get_talent_tree(
    tree: Optional[str] = Query(None, description="指定分支（mind/emotion/creativity/experience）"),
    x_user_id: str = Header("default"),
) -> dict:
    """获取天赋树.

    返回完整的天赋树结构，包括节点、连线和点数信息。
    """
    service = _get_service(x_user_id)
    tree_data = await service.get_talent_tree(tree=tree)
    return make_response(data=tree_data, message="获取天赋树成功")


@router.get("/talents/points")
async def get_talent_points(
    x_user_id: str = Header("default"),
) -> dict:
    """获取可用天赋点数.

    返回当前可用点数和点数获取/消耗历史。
    """
    service = _get_service(x_user_id)
    points = await service.get_talent_points()
    return make_response(data=points, message="获取天赋点数成功")


@router.get("/talents/stats")
async def get_talent_stats(
    x_user_id: str = Header("default"),
) -> dict:
    """获取天赋统计.

    返回总节点数、已解锁数、各分支进度等统计信息。
    """
    service = _get_service(x_user_id)
    stats = await service.get_talent_stats()
    return make_response(data=stats, message="获取天赋统计成功")


@router.post("/talents/{node_id}/upgrade")
async def upgrade_talent(
    node_id: str,
    x_user_id: str = Header("default"),
) -> dict:
    """升级天赋节点.

    Args:
        node_id: 天赋节点 ID
    """
    service = _get_service(x_user_id)
    result = await service.upgrade_talent(node_id)
    return make_response(data=result, message="天赋升级成功")


@router.post("/talents/reset")
async def reset_talents(
    x_user_id: str = Header("default"),
) -> dict:
    """重置天赋树，返还点数."""
    service = _get_service(x_user_id)
    result = await service.reset_talents()
    return make_response(data=result, message="天赋树已重置")


# ---------------------------------------------------------------------------
# 潮汐历法
# ---------------------------------------------------------------------------


@router.get("/calendar/{year}/{month}")
async def get_month_calendar(
    year: int,
    month: int,
    x_user_id: str = Header("default"),
) -> dict:
    """获取指定年月的日历数据.

    Args:
        year: 年份
        month: 月份
    """
    service = _get_service(x_user_id)
    calendar = await service.get_month_calendar(year, month)
    return make_response(data=calendar, message="获取月历成功")


@router.get("/calendar/stats")
async def get_calendar_stats(
    x_user_id: str = Header("default"),
) -> dict:
    """获取日历统计.

    返回总打卡天数、连续打卡天数、平均心情精力等统计。
    """
    service = _get_service(x_user_id)
    stats = await service.get_calendar_stats()
    return make_response(data=stats, message="获取日历统计成功")


@router.get("/calendar/day/{date}")
async def get_day_data(
    date: str,
    x_user_id: str = Header("default"),
) -> dict:
    """获取指定日期的数据.

    Args:
        date: 日期（YYYY-MM-DD）
    """
    service = _get_service(x_user_id)
    day_data = await service.get_day_data(date)
    return make_response(data=day_data, message="获取单日数据成功")


@router.post("/calendar/checkin")
async def checkin(
    req: CheckinRequest,
    x_user_id: str = Header("default"),
) -> dict:
    """打卡.

    记录今日心情、精力和总结。
    """
    service = _get_service(x_user_id)
    result = await service.checkin(
        mood=req.mood,
        energy=req.energy,
        date=req.date,
        summary=req.summary,
        tags=req.tags,
    )
    return make_response(data=result, message="打卡成功")


# ---------------------------------------------------------------------------
# 地球Online编年史
# ---------------------------------------------------------------------------


@router.get("/chronicle")
async def list_chronicles(
    page: int = Query(1, description="页码", ge=1),
    size: int = Query(20, description="每页数量", ge=1, le=100),
    category: Optional[str] = Query(None, description="分类筛选"),
    year: Optional[int] = Query(None, description="年份筛选"),
    x_user_id: str = Header("default"),
) -> dict:
    """分页查询纪事列表.

    支持按分类和年份筛选。
    """
    service = _get_service(x_user_id)
    chronicles = await service.list_chronicles(
        page=page, size=size, category=category, year=year,
    )
    return make_response(data=chronicles, message="获取编年史列表成功")


@router.get("/chronicle/{chronicle_id}")
async def get_chronicle(
    chronicle_id: str,
    x_user_id: str = Header("default"),
) -> dict:
    """获取单条纪事详情.

    Args:
        chronicle_id: 纪事 ID
    """
    service = _get_service(x_user_id)
    chronicle = await service.get_chronicle(chronicle_id)
    if not chronicle:
        raise HTTPException(status_code=404, detail="纪事不存在")
    return make_response(data=chronicle, message="获取纪事详情成功")


@router.post("/chronicle")
async def create_chronicle(
    req: ChronicleCreateRequest,
    x_user_id: str = Header("default"),
) -> dict:
    """创建纪事."""
    service = _get_service(x_user_id)
    data = req.model_dump()
    chronicle = await service.create_chronicle(data)
    return make_response(data=chronicle, message="创建纪事成功")


@router.put("/chronicle/{chronicle_id}")
async def update_chronicle(
    chronicle_id: str,
    req: ChronicleUpdateRequest,
    x_user_id: str = Header("default"),
) -> dict:
    """更新纪事.

    Args:
        chronicle_id: 纪事 ID
    """
    service = _get_service(x_user_id)
    data = req.model_dump(exclude_none=True)
    chronicle = await service.update_chronicle(chronicle_id, data)
    if not chronicle:
        raise HTTPException(status_code=404, detail="纪事不存在")
    return make_response(data=chronicle, message="更新纪事成功")


@router.delete("/chronicle/{chronicle_id}")
async def delete_chronicle(
    chronicle_id: str,
    x_user_id: str = Header("default"),
) -> dict:
    """删除纪事.

    Args:
        chronicle_id: 纪事 ID
    """
    service = _get_service(x_user_id)
    result = await service.delete_chronicle(chronicle_id)
    deleted = result.get("deleted", False) if isinstance(result, dict) else False
    if not deleted:
        raise HTTPException(status_code=404, detail="纪事不存在")
    return make_response(data={"deleted": True}, message="删除纪事成功")


# ---------------------------------------------------------------------------
# 记忆回响
# ---------------------------------------------------------------------------


@router.get("/memories")
async def list_echoes(
    page: int = Query(1, description="页码", ge=1),
    size: int = Query(20, description="每页数量", ge=1, le=100),
    category: Optional[str] = Query(None, description="分类筛选"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    x_user_id: str = Header("default"),
) -> dict:
    """分页查询记忆回响列表.

    支持按分类筛选和关键词搜索。
    """
    service = _get_service(x_user_id)
    echoes = await service.list_echoes(
        page=page, size=size, category=category, keyword=keyword,
    )
    return make_response(data=echoes, message="获取回响列表成功")


@router.get("/memories/{echo_id}")
async def get_echo(
    echo_id: str,
    x_user_id: str = Header("default"),
) -> dict:
    """获取单条回响详情.

    Args:
        echo_id: 回响 ID
    """
    service = _get_service(x_user_id)
    echo = await service.get_echo(echo_id)
    if not echo:
        raise HTTPException(status_code=404, detail="回响不存在")
    return make_response(data=echo, message="获取回响详情成功")


@router.post("/memories/generate")
async def generate_echo(
    req: EchoGenerateRequest,
    x_user_id: str = Header("default"),
) -> dict:
    """生成记忆回响.

    根据提供的前后状态对比，生成成长回响。
    """
    service = _get_service(x_user_id)
    data = req.model_dump(exclude_none=True)
    echo = await service.generate_echo(data)
    return make_response(data=echo, message="生成回响成功")


@router.delete("/memories/{echo_id}")
async def delete_echo(
    echo_id: str,
    x_user_id: str = Header("default"),
) -> dict:
    """删除回响.

    Args:
        echo_id: 回响 ID
    """
    service = _get_service(x_user_id)
    result = await service.delete_echo(echo_id)
    deleted = result.get("deleted", False) if isinstance(result, dict) else False
    if not deleted:
        raise HTTPException(status_code=404, detail="回响不存在")
    return make_response(data={"deleted": True}, message="删除回响成功")


# ---------------------------------------------------------------------------
# 赛季征程
# ---------------------------------------------------------------------------


@router.get("/season/current")
async def get_current_season(
    x_user_id: str = Header("default"),
) -> dict:
    """获取当前赛季详情."""
    service = _get_service(x_user_id)
    season = await service.get_current_season()
    return make_response(data=season, message="获取当前赛季成功")


@router.get("/season/history")
async def get_season_history(
    x_user_id: str = Header("default"),
) -> dict:
    """获取历史赛季列表."""
    service = _get_service(x_user_id)
    history = await service.get_season_history()
    return make_response(data=history, message="获取赛季历史成功")


@router.get("/season/tasks")
async def list_season_tasks(
    task_type: Optional[str] = Query(None, description="类型筛选（daily/weekly/seasonal）"),
    phase_id: Optional[str] = Query(None, description="阶段 ID 筛选"),
    season_id: Optional[str] = Query(None, description="赛季 ID 筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    x_user_id: str = Header("default"),
) -> dict:
    """获取赛季任务列表.

    支持按类型、阶段、赛季、状态筛选。
    """
    service = _get_service(x_user_id)
    tasks = await service.list_season_tasks(
        task_type=task_type,
        phase_id=phase_id,
        season_id=season_id,
        status=status,
    )
    return make_response(data=tasks, message="获取赛季任务成功")


@router.post("/season/tasks/{task_id}/complete")
async def complete_season_task(
    task_id: str,
    x_user_id: str = Header("default"),
) -> dict:
    """完成赛季任务.

    Args:
        task_id: 任务 ID
    """
    service = _get_service(x_user_id)
    result = await service.complete_season_task(task_id)
    return make_response(data=result, message="任务完成")


@router.post("/season/tasks/{task_id_or_phase_id}/claim")
async def claim_season_reward(
    task_id_or_phase_id: str,
    x_user_id: str = Header("default"),
) -> dict:
    """领取赛季奖励.

    Args:
        task_id_or_phase_id: 任务 ID 或阶段 ID
    """
    service = _get_service(x_user_id)
    result = await service.claim_season_reward(task_id_or_phase_id)
    return make_response(data=result, message="奖励领取成功")


# ---------------------------------------------------------------------------
# 成长事件（供其他模式调用）
# ---------------------------------------------------------------------------


@router.post("/event")
async def trigger_growth_event(
    event: dict,
    x_user_id: str = Header("default"),
) -> dict:
    """触发生长事件.

    供其他业务模式调用，通知成长系统发生了相关事件。

    请求体:
        event_type: 事件类型
        event_data: 事件数据
    """
    service = _get_service(x_user_id)
    event_type = event.get("event_type", "")
    event_data = event.get("event_data", {})
    result = await service.trigger_growth_event(event_type, event_data)
    return make_response(data=result, message="事件处理完成")
