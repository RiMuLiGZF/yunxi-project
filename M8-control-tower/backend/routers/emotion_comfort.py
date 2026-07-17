"""
情绪陪伴 路由 - M4 代理版

情绪陪伴已迁移到 M4 场景引擎（迁移脚本：migrate_emotion_appearance_m8_to_m4.py）

原本地实现已迁移至 M4 场景引擎，当前文件为代理路由占位。
业务请求通过 m4_proxy_middleware 中间件转发到 M4。

代理路径映射：
  M8 /api/emotion-comfort/*  →  M4 /api/v1/emotion-comfort/*

回滚方式：
  从 _archive/m8_migrated/routers/ 恢复原文件即可

注意：
  本文件仅提供健康检查和代理状态端点，
  实际业务端点由 m4_proxy_middleware 中间件在请求层代理转发。
  M4 不可用时返回 503 错误。
"""

from fastapi import APIRouter, Depends
from typing import Optional

from ..auth import get_current_user
from ..schemas import ApiResponse

router = APIRouter()


@router.get("/health", summary=f"情绪陪伴服务状态（M4代理）")
async def emotion_comfort_health(
    current_user: Optional[dict] = Depends(get_current_user),
):
    """检查 M4 中该服务的健康状态"""
    try:
        from ..m4_proxy_middleware import M4_BASE_URL, M4_PROXY_MODE
        return ApiResponse.success(data={
            "status": "proxied",
            "service": "emotion_comfort",
            "service_name": "情绪陪伴",
            "target_module": "m4",
            "target_base_url": M4_BASE_URL,
            "target_prefix": "/api/v1/emotion-comfort",
            "proxy_mode": M4_PROXY_MODE,
            "migrated": True,
        })
    except Exception as e:
        return ApiResponse.error(message=f"状态查询失败: {e}", code=503)


@router.get("/proxy-info", summary="代理转发信息")
async def proxy_info(
    current_user: Optional[dict] = Depends(get_current_user),
):
    """获取代理转发的详细配置信息"""
    try:
        from ..m4_proxy_middleware import get_proxy_status
        status = get_proxy_status()
        return ApiResponse.success(data={
            **status,
            "service": "emotion_comfort",
            "service_name": "情绪陪伴",
            "m8_prefix": "/api/emotion-comfort",
            "m4_prefix": "/api/v1/emotion-comfort",
            "migration_phase": "phase-1",
        })
    except Exception as e:
        return ApiResponse.error(message=f"获取代理状态失败: {e}", code=500)
