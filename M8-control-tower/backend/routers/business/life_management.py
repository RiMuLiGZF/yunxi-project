"""
生活管理 路由 - M4 代理版

生活管理已迁移到 M4 场景引擎

原本地实现已迁移至 M4 场景引擎，当前文件为代理路由占位。
业务请求通过 m4_proxy_middleware 中间件转发到 M4。

代理路径映射：
  M8 /api/life-management/*  →  M4 /api/v1/life-management/*

回滚方式：
  从 _archive/m8_migrated/routers/ 恢复原文件即可

注意：
  本文件仅提供健康检查和代理状态端点，
  实际业务端点由 m4_proxy_middleware 中间件在请求层代理转发。
  M4 不可用时返回 503 错误。
"""

from fastapi import APIRouter, Depends
from typing import Optional

from ...auth import get_current_user
from ...schemas import ApiResponse

router = APIRouter()


@router.get("/health", summary=f"生活管理服务状态（M4代理）")
async def life_management_health(
    current_user: Optional[dict] = Depends(get_current_user),
):
    """检查 M4 中该服务的健康状态"""
    try:
        from ...m4_proxy_middleware import M4_BASE_URL, M4_PROXY_MODE
        return ApiResponse.success(data={
            "status": "proxied",
            "service": "life_management",
            "service_name": "生活管理",
            "target_module": "m4",
            "target_base_url": M4_BASE_URL,
            "target_prefix": "/api/v1/life-management",
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
        from ...m4_proxy_middleware import get_proxy_status
        status = get_proxy_status()
        return ApiResponse.success(data={
            **status,
            "service": "life_management",
            "service_name": "生活管理",
            "m8_prefix": "/api/life-management",
            "m4_prefix": "/api/v1/life-management",
            "migration_phase": "phase-1",
        })
    except Exception as e:
        return ApiResponse.error(message=f"获取代理状态失败: {e}", code=500)
