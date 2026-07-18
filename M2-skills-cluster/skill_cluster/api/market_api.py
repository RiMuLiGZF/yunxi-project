"""技能市场 - 增强版 API 路由.

在原有 market_router 基础上，提供更丰富的市场 API 端点：
- 增强版技能列表（多维度过滤）
- 增强版搜索
- 用户维度安装管理
- 评论分页与点赞
- 评分统计（分布）
- 技能上架信息更新
- 分类元数据

所有端点前缀：/api/v2/market
与原有 router 共存，不修改原有接口行为。
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from skill_cluster.market.skill_market import (
    CategoryInfo,
    InstalledSkill,
    SearchFilters,
    SkillListing,
    SkillMarket,
    SkillRatingStats,
    SkillReview,
)

market_v2_router = APIRouter(prefix="/api/v2/market", tags=["技能市场-增强版"])


# ===========================================================================
# 请求/响应模型
# ===========================================================================


class PublishSkillRequest(BaseModel):
    """发布技能请求（增强版）."""

    skill_id: str
    name: str = ""
    description: str = ""
    category: str = "general"
    tags: List[str] = []
    author: str = ""
    icon_url: str = ""
    price_type: str = "free"
    price_amount: float = 0.0
    is_official: bool = False
    is_verified: bool = False
    is_public: bool = True


class UpdateListingRequest(BaseModel):
    """更新上架信息请求."""

    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    icon_url: Optional[str] = None
    price_type: Optional[str] = None
    price_amount: Optional[float] = None


class RateRequest(BaseModel):
    """评分请求（增强版）."""

    rating: int = Field(..., ge=1, le=5)
    comment: str = ""
    user_name: str = ""


class PaginatedResponse(BaseModel):
    """分页响应."""

    items: list
    total: int
    page: int
    page_size: int


# ===========================================================================
# 浏览与搜索
# ===========================================================================


@market_v2_router.get("/skills", response_model=dict)
async def list_skills(
    category: Optional[str] = None,
    tags: Optional[str] = None,  # 逗号分隔
    sort: str = "newest",
    page: int = 1,
    page_size: int = 20,
    price_type: Optional[str] = None,
    is_official: Optional[bool] = None,
    is_verified: Optional[bool] = None,
    min_rating: Optional[float] = None,
):
    """技能列表（增强版，支持多维度过滤）."""
    market = SkillMarket.get_instance()
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    items, total = market.list_skills(
        category=category,
        tags=tag_list,
        sort=sort,
        page=page,
        page_size=page_size,
        price_type=price_type,
        is_official=is_official,
        is_verified=is_verified,
        min_rating=min_rating,
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [i.model_dump() for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@market_v2_router.get("/skills/search", response_model=dict)
async def search_skills(
    q: str,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    price_type: Optional[str] = None,
    is_official: Optional[bool] = None,
    is_verified: Optional[bool] = None,
    min_rating: Optional[float] = None,
    author: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    """搜索技能（增强版，支持多维度过滤）."""
    market = SkillMarket.get_instance()
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    filters = SearchFilters(
        category=category,
        tags=tag_list,
        price_type=price_type,
        is_official=is_official,
        is_verified=is_verified,
        min_rating=min_rating,
        author=author,
    )
    items, total = market.search_skills(q, filters=filters, page=page, page_size=page_size)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [i.model_dump() for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@market_v2_router.get("/skills/{skill_id}", response_model=dict)
async def get_skill_detail(skill_id: str):
    """技能详情（增强版，含扩展信息）."""
    market = SkillMarket.get_instance()
    detail = market.get_skill_detail(skill_id)
    if not detail:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {"code": 0, "message": "ok", "data": detail.model_dump()}


@market_v2_router.get("/categories", response_model=dict)
async def get_categories():
    """分类列表（含技能数量）."""
    market = SkillMarket.get_instance()
    categories = market.get_categories()
    return {
        "code": 0,
        "message": "ok",
        "data": [c.model_dump() for c in categories],
    }


# ===========================================================================
# 安装与卸载（用户维度）
# ===========================================================================


@market_v2_router.post("/skills/{skill_id}/install", response_model=dict)
async def install_skill(skill_id: str, user_id: str = Query(default="anonymous")):
    """安装技能（用户维度）."""
    market = SkillMarket.get_instance()
    try:
        result = market.install_skill(skill_id, user_id)
        return {"code": 0, "message": "ok", "data": result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@market_v2_router.delete("/skills/{skill_id}/install", response_model=dict)
async def uninstall_skill(skill_id: str, user_id: str = Query(default="anonymous")):
    """卸载技能（用户维度）."""
    market = SkillMarket.get_instance()
    success = market.uninstall_skill(skill_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="技能未安装或不存在")
    return {"code": 0, "message": "ok"}


@market_v2_router.post("/skills/{skill_id}/update", response_model=dict)
async def update_skill(skill_id: str, user_id: str = Query(default="anonymous")):
    """更新技能到最新版本."""
    market = SkillMarket.get_instance()
    try:
        result = market.update_skill(skill_id, user_id)
        return {"code": 0, "message": "ok", "data": result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@market_v2_router.get("/installed", response_model=dict)
async def get_installed_skills(user_id: str = Query(default="anonymous")):
    """获取用户已安装技能列表."""
    market = SkillMarket.get_instance()
    skills = market.get_installed_skills(user_id)
    return {
        "code": 0,
        "message": "ok",
        "data": [s.model_dump() for s in skills],
    }


# ===========================================================================
# 评分与评论
# ===========================================================================


@market_v2_router.get("/skills/{skill_id}/reviews", response_model=dict)
async def get_reviews(
    skill_id: str,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "newest",
):
    """获取评论列表（分页）."""
    market = SkillMarket.get_instance()
    reviews, total = market.get_reviews(skill_id, page, page_size, sort_by)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [r.model_dump() for r in reviews],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@market_v2_router.post("/skills/{skill_id}/reviews", response_model=dict)
async def post_review(
    skill_id: str,
    request: RateRequest,
    user_id: str = Query(default="anonymous"),
):
    """发表评论（评分+评论）."""
    market = SkillMarket.get_instance()
    success = market.rate_skill(
        skill_id,
        user_id,
        request.rating,
        request.comment,
        request.user_name,
    )
    if not success:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {"code": 0, "message": "ok"}


@market_v2_router.get("/skills/{skill_id}/rating", response_model=dict)
async def get_skill_rating(skill_id: str):
    """获取技能评分统计（含分布）."""
    market = SkillMarket.get_instance()
    stats = market.get_skill_rating(skill_id)
    return {"code": 0, "message": "ok", "data": stats.model_dump()}


@market_v2_router.post("/reviews/{review_id}/like", response_model=dict)
async def like_review(review_id: int, user_id: str = Query(default="anonymous")):
    """点赞评论."""
    market = SkillMarket.get_instance()
    success = market.like_review(review_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="评论不存在")
    return {"code": 0, "message": "ok"}


# ===========================================================================
# 技能上架管理
# ===========================================================================


@market_v2_router.post("/publish", response_model=dict)
async def publish_skill(
    request: PublishSkillRequest,
    author_id: str = Query(default="anonymous"),
):
    """发布技能到市场（增强版）."""
    market = SkillMarket.get_instance()
    try:
        pkg = market.publish_skill(request.model_dump(), author_id)
        return {"code": 0, "message": "ok", "data": pkg.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@market_v2_router.patch("/skills/{skill_id}/listing", response_model=dict)
async def update_listing(skill_id: str, request: UpdateListingRequest):
    """更新上架信息."""
    market = SkillMarket.get_instance()
    data = {k: v for k, v in request.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    success = market.update_listing(skill_id, data)
    if not success:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {"code": 0, "message": "ok"}


@market_v2_router.delete("/skills/{skill_id}/listing", response_model=dict)
async def unpublish_skill(skill_id: str):
    """下架技能."""
    market = SkillMarket.get_instance()
    success = market.unpublish_skill(skill_id)
    if not success:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {"code": 0, "message": "ok"}
