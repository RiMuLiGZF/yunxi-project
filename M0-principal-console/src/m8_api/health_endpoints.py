"""
M0 主理人管控台 - 健康检查端点

遵循 M8 标准健康检查接口规范，
提供 /health 和 /healthz 两个端点。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter

from ..config import settings
from ..models import ApiResponse, HealthStatus
from ..services.m8_client import m8_client

router = APIRouter()

# 记录启动时间
_start_time: float = time.time()


def get_uptime_seconds() -> float:
    """
    获取服务运行时长（秒）

    Returns:
        float: 运行时长（秒）
    """
    return time.time() - _start_time


@router.get("/health", summary="健康检查")
async def health_check() -> ApiResponse[HealthStatus]:
    """
    健康检查接口

    返回 M0 服务自身的健康状态，以及与 M8 的连接状态。
    """
    # 检查 M8 连接状态
    m8_connected = False
    try:
        m8_connected = await m8_client.check_health()
    except Exception:
        m8_connected = False

    status = HealthStatus(
        status="healthy",
        version=settings.version,
        timestamp=datetime.now(),
        m8_connected=m8_connected,
        uptime=get_uptime_seconds(),
    )

    return ApiResponse.success(data=status, message="M0 主理人管控台运行正常")


@router.get("/healthz", summary="Liveness Probe")
async def healthz() -> dict:
    """
    Kubernetes Liveness Probe 端点

    返回最简单的健康状态，不做任何复杂检查。
    """
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/ready", summary="Readiness Probe")
async def readiness() -> ApiResponse[dict]:
    """
    Kubernetes Readiness Probe 端点

    检查服务是否就绪可以接收流量（包括 M8 连接）。
    """
    m8_connected = False
    try:
        m8_connected = await m8_client.check_health()
    except Exception:
        pass

    ready = True  # M0 自身始终就绪，M8 断开不影响 M0 运行

    return ApiResponse.success(
        data={
            "ready": ready,
            "m8_connected": m8_connected,
            "version": settings.version,
        },
        message="就绪" if ready else "未就绪",
    )
