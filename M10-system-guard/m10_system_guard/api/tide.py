"""
M10 潮汐引擎 API
前缀：/api/v1/tide

提供潮汐状态查询、任务管理、策略配置、预测数据等接口。
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field

from ..models import make_response
from ..tide_engine import (
    get_tide_engine,
    TideStrategy,
    GPUMission,
    MissionPriority,
    TidePhase,
)

router = APIRouter()


# ============================================================
# 请求/响应模型
# ============================================================

class GPUMissionSubmitRequest(BaseModel):
    """GPU 任务提交请求"""
    name: str = Field(..., description="任务名称")
    description: str = Field("", description="任务描述")
    priority: str = Field("normal", description="优先级: critical/high/normal/low/batch")
    mission_type: str = Field("general", description="任务类型: inference/training/embedding/vector_search/render")
    estimated_gpu_memory_mb: float = Field(1024.0, description="预估显存占用(MB)")
    estimated_duration_sec: float = Field(60.0, description="预估时长(秒)")
    preferred_gpu_id: Optional[int] = Field(None, description="首选 GPU ID")
    caller_module: str = Field("", description="调用模块")
    callback_url: str = Field("", description="回调 URL")
    tide_preemptible: bool = Field(False, description="是否可被潮汐调度抢占")
    payload: Dict[str, Any] = Field(default_factory=dict, description="任务数据")


class TideStrategyUpdateRequest(BaseModel):
    """潮汐策略更新请求"""
    primary_metric: Optional[str] = Field(None, description="主指标: gpu_memory/gpu_util/combined")
    flood_threshold: Optional[float] = Field(None, description="涨潮阈值(%)")
    ebb_threshold: Optional[float] = Field(None, description="退潮阈值(%)")
    low_threshold: Optional[float] = Field(None, description="枯潮阈值(%)")
    flood_concurrency_multiplier: Optional[float] = Field(None, description="涨潮并发系数")
    slack_concurrency_multiplier: Optional[float] = Field(None, description="平潮并发系数")
    ebb_concurrency_multiplier: Optional[float] = Field(None, description="退潮并发系数")
    low_concurrency_multiplier: Optional[float] = Field(None, description="枯潮并发系数")
    hysteresis_percent: Optional[float] = Field(None, description="滞回区间(%)")
    min_phase_duration_sec: Optional[int] = Field(None, description="最小阶段持续时间(秒)")
    prediction_enabled: Optional[bool] = Field(None, description="是否启用预测")
    prediction_window_minutes: Optional[int] = Field(None, description="预测窗口(分钟)")


class ManualPhaseRequest(BaseModel):
    """手动设置潮汐阶段（调试用）"""
    phase: str = Field(..., description="潮汐阶段: flood/slack/ebb/low")


# ============================================================
# 工具函数
# ============================================================

def _success(data=None, message: str = "ok"):
    return make_response(data=data, message=message)


def _get_engine():
    """获取潮汐引擎实例"""
    engine = get_tide_engine()
    if not engine.initialized:
        # 未初始化时尝试初始化
        try:
            from ..system_monitor import get_system_monitor
            monitor = get_system_monitor()
            engine.initialize(system_monitor=monitor)
        except Exception:
            engine.initialize()
    return engine


# ============================================================
# 潮汐状态接口
# ============================================================

@router.get("/status", summary="潮汐状态")
async def tide_status():
    """获取当前潮汐状态"""
    engine = _get_engine()
    snapshot = engine.scheduler.get_snapshot()
    return _success(data=snapshot.to_dict())


@router.get("/history", summary="潮汐历史")
async def tide_history(limit: int = Query(30, ge=1, le=300, description="返回条数")):
    """获取潮汐历史数据"""
    engine = _get_engine()
    history = engine.scheduler.get_history(limit=limit)
    return _success(data={
        "count": len(history),
        "data": [s.to_dict() for s in history],
    })


@router.get("/prediction", summary="潮汐预测")
async def tide_prediction():
    """获取潮汐预测数据"""
    engine = _get_engine()
    prediction = engine.scheduler.get_prediction()
    if prediction is None:
        return _success(data={"enabled": False})
    return _success(data=prediction.to_dict())


@router.get("/stats", summary="潮汐统计")
async def tide_stats():
    """获取潮汐引擎统计信息"""
    engine = _get_engine()
    stats = engine.scheduler.get_stats()
    return _success(data=stats)


# ============================================================
# 任务管理接口
# ============================================================

@router.post("/missions", summary="提交 GPU 任务")
async def submit_mission(req: GPUMissionSubmitRequest):
    """提交一个 GPU 计算任务到潮汐调度器"""
    engine = _get_engine()

    try:
        priority = MissionPriority(req.priority)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的优先级: {req.priority}")

    mission = GPUMission(
        name=req.name,
        description=req.description,
        priority=priority,
        mission_type=req.mission_type,
        estimated_gpu_memory_mb=req.estimated_gpu_memory_mb,
        estimated_duration_sec=req.estimated_duration_sec,
        preferred_gpu_id=req.preferred_gpu_id,
        caller_module=req.caller_module,
        callback_url=req.callback_url,
        tide_preemptible=req.tide_preemptible,
        payload=req.payload,
    )

    mission_id = engine.scheduler.submit_mission(mission)
    mission = engine.scheduler.get_mission(mission_id)

    return _success(
        data=mission.to_dict() if mission else {"mission_id": mission_id},
        message="任务提交成功",
    )


@router.get("/missions", summary="任务列表")
async def list_missions(
    status: Optional[str] = Query(None, description="状态: pending/running/completed/failed"),
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
):
    """获取 GPU 任务列表"""
    engine = _get_engine()
    missions = engine.scheduler.list_missions(status=status, limit=limit)
    return _success(data={
        "total": len(missions),
        "missions": [m.to_dict() for m in missions],
    })


@router.get("/missions/{mission_id}", summary="任务详情")
async def get_mission(mission_id: str):
    """获取单个任务详情"""
    engine = _get_engine()
    mission = engine.scheduler.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _success(data=mission.to_dict())


@router.post("/missions/{mission_id}/complete", summary="完成任务")
async def complete_mission(
    mission_id: str,
    success: bool = Query(True, description="是否成功"),
):
    """标记任务完成"""
    engine = _get_engine()
    mission = engine.scheduler.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="任务不存在")

    engine.scheduler.complete_mission(mission_id, success=success)
    mission = engine.scheduler.get_mission(mission_id)
    return _success(
        data=mission.to_dict() if mission else {},
        message="任务已完成",
    )


@router.post("/missions/{mission_id}/cancel", summary="取消任务")
async def cancel_mission(mission_id: str):
    """取消 GPU 任务"""
    engine = _get_engine()
    result = engine.scheduler.cancel_mission(mission_id)
    if not result:
        raise HTTPException(status_code=400, detail="任务无法取消")
    mission = engine.scheduler.get_mission(mission_id)
    return _success(
        data=mission.to_dict() if mission else {},
        message="任务已取消",
    )


# ============================================================
# 策略管理接口
# ============================================================

@router.get("/strategy", summary="获取潮汐策略")
async def get_strategy():
    """获取当前潮汐策略配置"""
    engine = _get_engine()
    strategy = engine.scheduler.get_strategy()
    return _success(data=strategy.to_dict())


@router.put("/strategy", summary="更新潮汐策略")
async def update_strategy(req: TideStrategyUpdateRequest):
    """更新潮汐策略配置"""
    engine = _get_engine()
    strategy = engine.scheduler.get_strategy()

    # 更新字段
    if req.primary_metric is not None:
        strategy.primary_metric = req.primary_metric
    if req.flood_threshold is not None:
        strategy.flood_threshold = req.flood_threshold
    if req.ebb_threshold is not None:
        strategy.ebb_threshold = req.ebb_threshold
    if req.low_threshold is not None:
        strategy.low_threshold = req.low_threshold
    if req.flood_concurrency_multiplier is not None:
        strategy.flood_concurrency_multiplier = req.flood_concurrency_multiplier
    if req.slack_concurrency_multiplier is not None:
        strategy.slack_concurrency_multiplier = req.slack_concurrency_multiplier
    if req.ebb_concurrency_multiplier is not None:
        strategy.ebb_concurrency_multiplier = req.ebb_concurrency_multiplier
    if req.low_concurrency_multiplier is not None:
        strategy.low_concurrency_multiplier = req.low_concurrency_multiplier
    if req.hysteresis_percent is not None:
        strategy.hysteresis_percent = req.hysteresis_percent
    if req.min_phase_duration_sec is not None:
        strategy.min_phase_duration_sec = req.min_phase_duration_sec
    if req.prediction_enabled is not None:
        strategy.prediction_enabled = req.prediction_enabled
    if req.prediction_window_minutes is not None:
        strategy.prediction_window_minutes = req.prediction_window_minutes

    # 应用新策略
    engine.scheduler.update_strategy(strategy)

    return _success(data=strategy.to_dict(), message="策略已更新")


@router.post("/strategy/reset", summary="重置策略")
async def reset_strategy():
    """重置为默认潮汐策略"""
    engine = _get_engine()
    default = TideStrategy()
    engine.scheduler.update_strategy(default)
    return _success(data=default.to_dict(), message="已重置为默认策略")


# ============================================================
# 调试接口
# ============================================================

@router.post("/debug/set-phase", summary="手动设置潮汐阶段（调试）")
async def manual_set_phase(req: ManualPhaseRequest):
    """手动设置潮汐阶段（仅用于调试测试）"""
    engine = _get_engine()

    try:
        phase = TidePhase(req.phase)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的阶段: {req.phase}")

    engine.scheduler.manual_set_phase(phase)
    snapshot = engine.scheduler.get_snapshot()
    return _success(data=snapshot.to_dict(), message=f"已设置为 {phase.value}")


@router.get("/phases", summary="潮汐阶段说明")
async def tide_phases():
    """获取所有潮汐阶段的说明"""
    phases = [
        {
            "phase": "flood",
            "name": "涨潮",
            "description": "资源充裕，GPU 显存使用率低，提升并发，放行批量任务",
            "concurrency_multiplier": "2.0x",
            "allowed_priority": "batch+",
        },
        {
            "phase": "slack",
            "name": "平潮",
            "description": "资源平稳，标准并发运行",
            "concurrency_multiplier": "1.0x",
            "allowed_priority": "normal+",
        },
        {
            "phase": "ebb",
            "name": "退潮",
            "description": "资源紧张，降低并发，仅放行高优先级任务",
            "concurrency_multiplier": "0.5x",
            "allowed_priority": "high+",
        },
        {
            "phase": "low",
            "name": "枯潮",
            "description": "资源严重不足，最低并发，仅关键任务运行",
            "concurrency_multiplier": "0.2x",
            "allowed_priority": "critical+",
        },
    ]
    return _success(data={"phases": phases})
