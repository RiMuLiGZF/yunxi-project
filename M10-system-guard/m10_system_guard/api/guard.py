"""
M10 系统卫士 - 防护策略 API

防护检查、策略管理、告警记录、限流状态等接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..errors import M10ErrorCode
from ..models import make_response, GuardPolicyUpdateRequest, MetricType
from ..guard_engine import get_guard_engine
from ..i18n import t

from .response import success as _success

router = APIRouter()




@router.get("", summary="防护状态")
async def guard_status():
    """获取防护引擎当前状态."""
    engine = get_guard_engine()
    status = engine.get_status_summary()
    return _success(status)


@router.get("/check", summary="执行防护检查")
async def guard_check():
    """执行一次完整的防护检查."""
    engine = get_guard_engine()
    result = engine.check_all()
    return _success(result)


@router.get("/policies", summary="防护策略列表")
async def guard_policies():
    """获取所有防护策略."""
    engine = get_guard_engine()
    policies = engine.get_all_policies()
    return _success({
        "count": len(policies),
        "policies": {
            k.value: {
                "name": v.name,
                "description": v.description,
                "metric_type": v.metric_type.value,
                "info_threshold": v.info_threshold,
                "warning_threshold": v.warning_threshold,
                "critical_threshold": v.critical_threshold,
                "emergency_threshold": v.emergency_threshold,
                "enabled": v.enabled,
                "action_on_warning": v.action_on_warning,
                "action_on_critical": v.action_on_critical,
                "action_on_emergency": v.action_on_emergency,
            }
            for k, v in policies.items()
        },
    })


@router.get("/policies/{metric_type}", summary="获取单个策略")
async def get_policy(metric_type: str):
    """获取指定指标的防护策略."""
    engine = get_guard_engine()
    try:
        mtype = MetricType(metric_type.lower())
    except ValueError:
        return make_response(
            code=M10ErrorCode.METRIC_TYPE_INVALID,
            message=t("m10_api.guard.invalid_metric_type", metric_type=metric_type),
        )

    policy = engine.get_policy(mtype)
    if policy is None:
        return make_response(
            code=M10ErrorCode.POLICY_NOT_FOUND,
            message=t("m10_api.guard.policy_not_found", metric_type=metric_type),
        )

    return _success({
        "name": policy.name,
        "description": policy.description,
        "metric_type": policy.metric_type.value,
        "info_threshold": policy.info_threshold,
        "warning_threshold": policy.warning_threshold,
        "critical_threshold": policy.critical_threshold,
        "emergency_threshold": policy.emergency_threshold,
        "enabled": policy.enabled,
        "action_on_warning": policy.action_on_warning,
        "action_on_critical": policy.action_on_critical,
        "action_on_emergency": policy.action_on_emergency,
    })


@router.put("/policies/{metric_type}", summary="更新防护策略")
async def update_policy(metric_type: str, request: GuardPolicyUpdateRequest):
    """更新指定指标的防护策略."""
    engine = get_guard_engine()
    try:
        mtype = MetricType(metric_type.lower())
    except ValueError:
        return make_response(
            code=M10ErrorCode.METRIC_TYPE_INVALID,
            message=t("m10_api.guard.invalid_metric_type", metric_type=metric_type),
        )

    success = engine.update_policy(
        mtype,
        info_threshold=request.info_threshold,
        warning_threshold=request.warning_threshold,
        critical_threshold=request.critical_threshold,
        emergency_threshold=request.emergency_threshold,
        enabled=request.enabled,
    )

    if not success:
        return make_response(
            code=M10ErrorCode.POLICY_NOT_FOUND,
            message=t("m10_api.guard.policy_not_found", metric_type=metric_type),
        )

    return _success({"updated": True, "metric_type": metric_type})


@router.get("/alerts", summary="告警记录")
async def guard_alerts(
    limit: int = Query(50, ge=1, le=500, description="返回数量"),
    level: str = Query(None, description="按级别过滤: info/warning/critical/emergency"),
):
    """获取告警记录列表."""
    engine = get_guard_engine()
    alerts = engine.get_alerts(limit=limit, level=level)
    return _success({
        "total": len(alerts),
        "alerts": [a.to_dict() for a in alerts],
    })


@router.post("/alerts/{alert_id}/acknowledge", summary="确认告警")
async def acknowledge_alert(alert_id: str):
    """确认指定告警."""
    engine = get_guard_engine()
    success = engine.acknowledge_alert(alert_id)
    if not success:
        return make_response(
            code=M10ErrorCode.ALERT_NOT_FOUND,
            message=t("m10_api.guard.alert_not_found", alert_id=alert_id),
        )
    return _success({"acknowledged": True, "alert_id": alert_id})


@router.get("/throttling", summary="限流状态")
async def throttling_status():
    """获取当前限流状态."""
    engine = get_guard_engine()
    status = engine.get_status_summary()
    return _success({
        "throttling_active": status["throttling_active"],
        "heavy_tasks_paused": status["heavy_tasks_paused"],
        "current_concurrency_limit": status["current_concurrency_limit"],
        "base_concurrency": status["base_concurrency"],
        "can_run_heavy_task": engine.can_run_heavy_task(),
    })
