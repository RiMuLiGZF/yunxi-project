"""
M0 主理人管控台 - 全局配置中心路由

管理系统全局配置的读取和更新。
MVP 版本存储在本地 JSON 文件中。
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends

from ..auth import get_principal_user
from ..models import ApiResponse, ConfigUpdateRequest, GlobalConfig
from ..services.config_service import config_service

router = APIRouter(tags=["配置中心"])


@router.get("", summary="获取全局配置")
async def get_global_config(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[GlobalConfig]:
    """
    获取所有全局配置

    返回完整的配置树，包含所有分类和配置项。
    """
    config_data = config_service.get_all_config()
    categories = list(config_data.get("categories", {}).keys())

    global_config = GlobalConfig(
        configs=config_data.get("categories", {}),
        categories=categories,
        updated_at=config_data.get("meta", {}).get("updated_at"),
    )

    return ApiResponse.success(data=global_config, message="获取成功")


@router.get("/categories", summary="获取配置分类列表")
async def get_categories(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[List[Dict[str, Any]]]:
    """
    获取所有配置分类
    """
    categories = config_service.get_categories()
    return ApiResponse.success(data=categories, message="获取成功")


@router.get("/{category}", summary="获取分类下的配置")
async def get_category_config(
    category: str,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[Dict[str, Any]]:
    """
    获取指定分类的所有配置项

    Args:
        category: 分类键名
    """
    items = config_service.get_config_by_category(category)
    return ApiResponse.success(data=items, message="获取成功")


@router.put("", summary="更新配置项")
async def update_config(
    request: ConfigUpdateRequest,
    category: str = "system",
    user: dict = Depends(get_principal_user),
) -> ApiResponse[Dict[str, Any]]:
    """
    更新单个配置项的值

    Args:
        category: 配置分类
        request: 配置更新请求（key + value）
    """
    success = config_service.update_config(
        category=category,
        key=request.key,
        value=request.value,
        operator=user["username"],
    )

    if success:
        return ApiResponse.success(
            data={"key": request.key, "value": request.value, "category": category},
            message="配置更新成功",
        )
    else:
        return ApiResponse.error(message="配置更新失败")


@router.post("/batch", summary="批量更新配置")
async def batch_update_config(
    updates: Dict[str, Dict[str, Any]] = Body(..., description="格式: {category: {key: value}}"),
    user: dict = Depends(get_principal_user),
) -> ApiResponse[Dict[str, Any]]:
    """
    批量更新多个配置项

    请求体格式：
    {
      "system": {"log_level": "debug", "env": "production"},
      "security": {"session_timeout": 720}
    }
    """
    count = config_service.batch_update_config(updates, operator=user["username"])
    return ApiResponse.success(
        data={"updated_count": count},
        message=f"成功更新 {count} 个配置项",
    )


@router.post("/reset", summary="重置所有配置")
async def reset_config(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[Dict[str, Any]]:
    """
    重置所有配置为默认值

    危险操作：将清除所有自定义配置，恢复出厂默认值。
    """
    success = config_service.reset_config(operator=user["username"])
    if success:
        return ApiResponse.success(message="配置已重置为默认值")
    else:
        return ApiResponse.error(message="配置重置失败")
