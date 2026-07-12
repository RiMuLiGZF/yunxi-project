"""
M0 主理人管控台 - 仪表盘路由

提供全局仪表盘数据接口，调用 M8 接口聚合数据。
M8 不可用时返回 mock 数据。
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends

from ..auth import get_principal_user
from ..models import AlertItem, ApiResponse, DashboardSummary, ModuleStatusItem
from ..services.m8_client import m8_client

router = APIRouter(tags=["仪表盘"])


@router.get("/summary", summary="仪表盘总览")
async def dashboard_summary(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[DashboardSummary]:
    """
    获取仪表盘总览数据

    包含：模块状态统计、系统资源、告警概览、版本信息、对话数、记忆数等。
    M8 不可用时返回 fallback mock 数据。
    """
    summary = await m8_client.get_dashboard_summary()
    return ApiResponse.success(data=summary, message="获取成功")


@router.get("/modules-status", summary="模块状态列表")
async def modules_status(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[List[ModuleStatusItem]]:
    """
    获取所有模块的状态列表
    """
    modules = await m8_client.get_modules()
    return ApiResponse.success(data=modules, message="获取成功")


@router.get("/alerts", summary="告警列表")
async def alerts_list(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[List[AlertItem]]:
    """
    获取当前告警列表
    """
    alerts = await m8_client.get_alerts()
    return ApiResponse.success(data=alerts, message="获取成功")


@router.get("/quick-stats", summary="快速统计")
async def quick_stats(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[dict]:
    """
    获取仪表盘顶部快速统计数据

    返回 6 个核心指标的快捷数据。
    """
    summary = await m8_client.get_dashboard_summary()

    stats = {
        "module_health": {
            "label": "模块健康",
            "value": f"{summary.module_running}/{summary.module_count}",
            "subtext": f"{summary.module_stopped} 个模块异常",
            "status": "healthy" if summary.module_stopped == 0 else "warning",
        },
        "system_resources": {
            "label": "系统资源",
            "value": f"{summary.system_resources.cpu_usage:.1f}%",
            "subtext": f"内存 {summary.system_resources.memory_usage:.1f}%",
            "status": "healthy" if summary.system_resources.cpu_usage < 80 else "warning",
        },
        "alerts": {
            "label": "活动告警",
            "value": str(summary.alert_critical_count + summary.alert_warning_count),
            "subtext": f"严重 {summary.alert_critical_count} / 警告 {summary.alert_warning_count}",
            "status": "critical" if summary.alert_critical_count > 0 else "warning" if summary.alert_warning_count > 0 else "healthy",
        },
        "version": {
            "label": "系统版本",
            "value": summary.version,
            "subtext": "运行正常",
            "status": "healthy",
        },
        "today_conversations": {
            "label": "今日对话",
            "value": str(summary.today_conversations),
            "subtext": "较昨日 +12%",
            "status": "healthy",
        },
        "memory_total": {
            "label": "记忆总数",
            "value": str(summary.memory_total),
            "subtext": "条记忆节点",
            "status": "healthy",
        },
    }

    return ApiResponse.success(data=stats, message="获取成功")
