from __future__ import annotations

"""技能市场 - API 路由.

提供技能上架、浏览、搜索、安装、卸载、评分、统计等 RESTful 接口。
所有接口统一返回 {"code": 0, "message": "ok", "data": ...} 格式。

路由前缀：/api/v2/market
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from skill_cluster.market.models import (
    InstallRequest,
    MarketListing,
    MarketStats,
    PublishRequest,
    RatingRequest,
    SkillPackage,
)
from skill_cluster.market.registry import MarketRegistry

market_router = APIRouter(prefix="/api/v2/market", tags=["技能市场"])


# ------------------------------------------------------------------
# 静态路径（必须注册在 /{package_id} 之前，避免被路径参数捕获）
# ------------------------------------------------------------------


@market_router.post("/publish")
async def publish_skill(request: PublishRequest):
    """上架技能到市场."""
    registry = MarketRegistry.get_instance()
    try:
        pkg = registry.publish(request.skill_id, request)
        return {"code": 0, "message": "ok", "data": pkg.dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@market_router.get("/list")
async def list_packages(
    category: Optional[str] = None,
    tag: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    sort: str = "newest",
):
    """浏览技能市场."""
    registry = MarketRegistry.get_instance()
    items, total = registry.list_packages(category, tag, page, size, sort)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [i.dict() for i in items],
            "total": total,
            "page": page,
            "size": size,
        },
    }


@market_router.get("/search")
async def search_packages(q: str, page: int = 1, size: int = 20):
    """搜索技能."""
    registry = MarketRegistry.get_instance()
    items, total = registry.search(q, page, size)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [i.dict() for i in items],
            "total": total,
            "page": page,
            "size": size,
        },
    }


@market_router.get("/stats/summary")
async def get_stats():
    """市场统计."""
    registry = MarketRegistry.get_instance()
    return {"code": 0, "message": "ok", "data": registry.get_stats().dict()}


@market_router.get("/categories/list")
async def get_categories():
    """分类列表."""
    registry = MarketRegistry.get_instance()
    return {"code": 0, "message": "ok", "data": registry.get_categories()}


# ------------------------------------------------------------------
# 动态路径（/{package_id}）
# ------------------------------------------------------------------


@market_router.get("/{package_id}")
async def get_package(package_id: str):
    """技能包详情."""
    registry = MarketRegistry.get_instance()
    pkg = registry.get_package(package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="技能包不存在")
    return {"code": 0, "message": "ok", "data": pkg.dict()}


@market_router.post("/{package_id}/install")
async def install_package(package_id: str, request: InstallRequest):
    """安装技能."""
    registry = MarketRegistry.get_instance()
    try:
        result = registry.install(package_id, request.target_dir)
        return {"code": 0, "message": "ok", "data": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@market_router.delete("/{package_id}/uninstall")
async def uninstall_package(package_id: str):
    """卸载技能."""
    registry = MarketRegistry.get_instance()
    if not registry.uninstall(package_id):
        raise HTTPException(status_code=404, detail="技能未安装或不存在")
    return {"code": 0, "message": "ok"}


@market_router.post("/{package_id}/rate")
async def rate_package(package_id: str, request: RatingRequest):
    """评分."""
    registry = MarketRegistry.get_instance()
    if not registry.rate(package_id, "anonymous", request.rating, request.comment):
        raise HTTPException(status_code=404, detail="技能包不存在")
    return {"code": 0, "message": "ok"}
