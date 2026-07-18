"""
M8 控制塔 - 服务注册中心 API 路由
====================================

提供服务注册、注销、心跳、发现等 API。

API 清单：
| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /registry/register | 注册服务 |
| POST | /registry/deregister | 注销服务 |
| POST | /registry/heartbeat | 心跳 |
| GET  | /registry/services | 服务列表 |
| GET  | /registry/services/{name} | 服务实例列表 |
| GET  | /registry/health | 注册中心健康状态 |
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Body

# 将项目根目录加入 path，以便导入 shared 模块
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from ..services.service_registry import get_service_registry_service

import logging
logger = logging.getLogger("m8.routers.registry")

router = APIRouter()

_service = None


def _get_service():
    """延迟获取服务实例"""
    global _service
    if _service is None:
        _service = get_service_registry_service()
    return _service


# ============================================================
#  注册/注销/心跳
# ============================================================

@router.post("/register")
async def register_service(
    service_name: str = Body(..., embed=True, description="服务名"),
    instance_id: str = Body(..., embed=True, description="实例 ID"),
    address: str = Body("127.0.0.1", embed=True, description="服务地址"),
    port: int = Body(..., embed=True, description="服务端口"),
    version: str = Body("1.0.0", embed=True, description="版本号"),
    weight: int = Body(1, embed=True, description="权重"),
    metadata: Optional[Dict[str, Any]] = Body(default=None, embed=True, description="元数据"),
):
    """注册服务实例"""
    try:
        result = _get_service().register_instance(
            service_name=service_name,
            instance_id=instance_id,
            address=address,
            port=port,
            version=version,
            weight=weight,
            metadata=metadata,
        )
        return result.to_dict()
    except Exception as e:
        logger.error("Register error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deregister")
async def deregister_service(
    service_name: str = Body(..., embed=True, description="服务名"),
    instance_id: str = Body(..., embed=True, description="实例 ID"),
):
    """注销服务实例"""
    try:
        result = _get_service().deregister_instance(
            service_name=service_name,
            instance_id=instance_id,
        )
        return result.to_dict()
    except Exception as e:
        logger.error("Deregister error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/heartbeat")
async def heartbeat(
    service_name: str = Body(..., embed=True, description="服务名"),
    instance_id: str = Body(..., embed=True, description="实例 ID"),
    status: Optional[str] = Body(default=None, embed=True, description="状态"),
):
    """服务实例心跳上报"""
    try:
        result = _get_service().heartbeat(
            service_name=service_name,
            instance_id=instance_id,
            status=status,
        )
        return result.to_dict()
    except Exception as e:
        logger.error("Heartbeat error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
#  服务发现
# ============================================================

@router.get("/services")
async def list_services():
    """获取所有服务列表"""
    try:
        result = _get_service().get_all_services()
        return result.to_dict()
    except Exception as e:
        logger.error("List services error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/services/{service_name}")
async def discover_service(
    service_name: str,
    healthy_only: bool = Query(True, description="是否只返回健康实例"),
):
    """发现指定服务的实例列表"""
    try:
        result = _get_service().discover(
            service_name=service_name,
            healthy_only=healthy_only,
        )
        return result.to_dict()
    except Exception as e:
        logger.error("Discover service error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/services/{service_name}/{instance_id}")
async def get_instance(
    service_name: str,
    instance_id: str,
):
    """获取指定服务实例详情"""
    try:
        result = _get_service().get_instance(
            service_name=service_name,
            instance_id=instance_id,
        )
        return result.to_dict()
    except Exception as e:
        logger.error("Get instance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
#  健康检查
# ============================================================

@router.get("/health")
async def registry_health():
    """注册中心健康状态"""
    try:
        result = _get_service().health_check()
        return result.to_dict()
    except Exception as e:
        logger.error("Health check error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
#  依赖管理
# ============================================================

@router.get("/dependencies/{service_name}")
async def get_service_dependencies(service_name: str):
    """获取服务依赖关系"""
    try:
        result = _get_service().get_dependencies(service_name)
        return result.to_dict()
    except Exception as e:
        logger.error("Get dependencies error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dependents/{service_name}")
async def get_service_dependents(service_name: str):
    """获取依赖于该服务的服务列表"""
    try:
        result = _get_service().get_dependents(service_name)
        return result.to_dict()
    except Exception as e:
        logger.error("Get dependents error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
#  统计
# ============================================================

@router.get("/stats")
async def get_stats():
    """获取注册中心统计信息"""
    try:
        from shared.module_sdk.models import ApiResponse
        stats = _get_service().get_stats()
        return ApiResponse.success(data=stats).to_dict()
    except Exception as e:
        logger.error("Get stats error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
