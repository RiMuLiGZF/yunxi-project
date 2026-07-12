"""
M0 主理人管控台 - 主理人专属工具路由

提供仅主理人可用的专属工具和功能。
MVP 版本：提供工具列表和骨架接口。
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends

from ..auth import get_principal_user
from ..models import ApiResponse

router = APIRouter(tags=["主理人工具"])


# 主理人专属工具列表
PRINCIPAL_TOOLS: List[dict] = [
    {
        "key": "system_insight",
        "name": "系统洞察",
        "description": "一键生成系统运行状态深度分析报告",
        "icon": "chart",
        "category": "分析",
    },
    {
        "key": "data_export",
        "name": "全量数据导出",
        "description": "导出系统所有数据（用户、配置、日志等）",
        "icon": "download",
        "category": "数据",
    },
    {
        "key": "password_reset",
        "name": "主理人密码修改",
        "description": "修改主理人账号的登录密码",
        "icon": "key",
        "category": "安全",
    },
    {
        "key": "activity_summary",
        "name": "活动总览",
        "description": "查看系统所有用户的活动统计",
        "icon": "users",
        "category": "分析",
    },
    {
        "key": "api_test",
        "name": "API 调试台",
        "description": "直接调用各模块 API 进行调试",
        "icon": "code",
        "category": "开发",
    },
    {
        "key": "shell_access",
        "name": "系统终端",
        "description": "访问系统命令行终端（受限命令）",
        "icon": "terminal",
        "category": "开发",
    },
]


@router.get("/tools", summary="获取主理人工具列表")
async def list_tools(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[List[dict]]:
    """
    获取所有主理人专属工具列表
    """
    return ApiResponse.success(data=PRINCIPAL_TOOLS, message=f"共 {len(PRINCIPAL_TOOLS)} 个工具")


@router.get("/activity-summary", summary="获取活动总览")
async def get_activity_summary(
    days: int = 7,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[dict]:
    """
    获取系统活动总览数据（MVP 版本：mock 数据）

    Args:
        days: 统计天数，默认 7 天
    """
    # MVP 版本：模拟数据
    summary = {
        "period_days": days,
        "total_logins": 128,
        "total_actions": 1024,
        "active_users": 8,
        "top_actions": [
            {"action": "login", "count": 128},
            {"action": "config_view", "count": 89},
            {"action": "module_view", "count": 67},
            {"action": "chat", "count": 256},
        ],
        "daily_activity": [
            {"date": f"2026-07-{12-i}", "actions": 100 + i * 10}
            for i in range(min(days, 7))
        ],
    }

    return ApiResponse.success(data=summary, message="获取成功")


@router.post("/insight-report", summary="生成系统洞察报告")
async def generate_insight_report(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[dict]:
    """
    生成系统运行状态深度分析报告（MVP 版本：模拟）
    """
    report = {
        "generated_at": datetime.now().isoformat(),
        "generated_by": user["username"],
        "summary": "系统整体运行良好，M4 模块存在性能下降需关注",
        "sections": [
            {
                "title": "模块健康度",
                "score": 85,
                "details": "11 个模块中 9 个正常运行，1 个降级（M4），1 个停止（M6）",
            },
            {
                "title": "资源利用率",
                "score": 72,
                "details": "CPU 平均使用率 32%，内存 58%，磁盘 45%",
            },
            {
                "title": "安全状态",
                "score": 95,
                "details": "无异常登录，审计日志完整，权限配置合理",
            },
            {
                "title": "建议",
                "score": 0,
                "details": "1. 排查 M4 场景引擎性能问题 2. 检查 M6 硬件外设停止原因",
            },
        ],
    }

    return ApiResponse.success(data=report, message="报告生成成功")


@router.post("/change-password", summary="修改主理人密码")
async def change_principal_password(
    old_password: str,
    new_password: str,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[dict]:
    """
    修改主理人账号密码（MVP 版本：模拟操作）

    Args:
        old_password: 旧密码
        new_password: 新密码
    """
    # MVP 版本：仅做简单校验，实际应更新配置文件
    if len(new_password) < 8:
        return ApiResponse.error(message="新密码长度不能少于 8 位", code=40000)

    return ApiResponse.success(
        data={"username": user["username"]},
        message="密码修改成功",
    )
