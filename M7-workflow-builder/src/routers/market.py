"""M7 积木平台 - 模板与积木市场.

v0.9.0 内容生态：用户可以将工作流发布为市场模板，将自定义积木发布到市场，
其他用户可以浏览、搜索、安装这些共享内容。

安全说明：
- 发布自定义积木到市场前会进行代码安全校验
- 安装市场积木时也会进行代码安全校验
- 所有操作均记录安全审计日志

性能说明：
- 高频读接口接入三级缓存（L1内存 + L2文件 + L3 Redis预留）
- 写操作后自动失效相关缓存
- 缓存 key 统一命名：m7:market:*
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, Integer, JSON, String, Text, desc, func

from ..db import Base, get_engine
from ..m8_api.m8_auth_middleware import get_current_user
from ..utils.security import (
    validate_custom_block_code,
    sanitize_custom_block_name,
    _add_audit_log,
)

# ---------------------------------------------------------------------------
# 接入统一缓存框架 (shared.perf)
# 优先使用统一实现，失败则回退到模块内简单实现
# ---------------------------------------------------------------------------
try:
    _project_root = Path(__file__).resolve()
    for _ in range(10):
        _project_root = _project_root.parent
        if (_project_root / "shared" / "perf" / "cache_manager.py").exists():
            if str(_project_root) not in sys.path:
                sys.path.insert(0, str(_project_root))
            break
except Exception:
    pass

try:
    from shared.perf.cache_manager import (
        CacheManager,
        async_cache_result,
        async_cache_invalidate,
    )
    _market_cache = CacheManager.from_env(namespace="m7_market")
    _HAS_UNIFIED_CACHE = True
except ImportError:
    _HAS_UNIFIED_CACHE = False
    _market_cache = None  # type: ignore


# ============================================================
# 缓存 key 命名空间 (统一前缀：m7:market:)
# ============================================================
# m7:market:stats            - 市场统计
# m7:market:templates:list   - 模板列表
# m7:market:templates:detail - 模板详情
# m7:market:templates:search - 模板搜索
# m7:market:blocks:list      - 积木列表
# m7:market:blocks:detail    - 积木详情
# m7:market:blocks:search    - 积木搜索
# m7:market:categories       - 分类列表

# ============================================================
# Pydantic 请求/响应模型
# ============================================================


class PublishTemplateRequest(BaseModel):
    """发布模板到市场"""

    workflow_id: str
    description: str = ""
    category: str = "general"
    tags: List[str] = []
    is_public: bool = True


class PublishBlockRequest(BaseModel):
    """发布积木到市场"""

    block_id: str
    description: str = ""
    category: str = "general"
    tags: List[str] = []
    is_public: bool = True


class MarketTemplateItem(BaseModel):
    """市场模板列表项"""

    template_id: str
    name: str
    description: str
    author: str
    category: str
    tags: List[str] = []
    block_count: int = 0
    download_count: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0
    created_at: str = ""


class MarketBlockItem(BaseModel):
    """市场积木列表项"""

    block_id: str
    name: str
    description: str
    author: str
    category: str
    tags: List[str] = []
    download_count: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0
    created_at: str = ""


class RatingRequest(BaseModel):
    """评分请求"""

    rating: int = Field(ge=1, le=5)
    comment: str = ""


class MarketStats(BaseModel):
    """市场统计"""

    total_templates: int = 0
    total_blocks: int = 0
    total_downloads: int = 0
    avg_rating: float = 0.0
    categories: Dict[str, int] = {}


# ============================================================
# SQLAlchemy ORM 模型（市场表）
# ============================================================


class MarketTemplate(Base):
    """市场模板表"""

    __tablename__ = "market_templates"

    template_id = Column(String(64), primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    author = Column(String(50), default="anonymous", index=True)
    category = Column(String(50), default="general", index=True)
    tags = Column(JSON, default=list)

    blocks = Column(JSON, nullable=False)
    connections = Column(JSON, default=list)
    variables = Column(JSON, default=list)
    trigger = Column(JSON, default=dict)

    download_count = Column(Integer, default=0)
    rating_sum = Column(Float, default=0.0)
    rating_count = Column(Integer, default=0)

    source_workflow_id = Column(String(64), default="")
    status = Column(String(20), default="published", index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class MarketBlock(Base):
    """市场积木表"""

    __tablename__ = "market_blocks"

    block_id = Column(String(64), primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    author = Column(String(50), default="anonymous", index=True)
    category = Column(String(50), default="general", index=True)
    tags = Column(JSON, default=list)

    code = Column(Text, default="")
    icon = Column(String(50), default="puzzle")
    ports = Column(JSON, default=dict)

    download_count = Column(Integer, default=0)
    rating_sum = Column(Float, default=0.0)
    rating_count = Column(Integer, default=0)

    source_block_id = Column(String(64), default="")
    status = Column(String(20), default="published", index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class MarketRating(Base):
    """市场评分表"""

    __tablename__ = "market_ratings"

    id = Column(String(64), primary_key=True)
    item_type = Column(String(20), nullable=False, index=True)  # template / block
    item_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(50), default="anonymous")
    rating = Column(Integer, nullable=False)
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# 路由
# ============================================================

market_router = APIRouter(prefix="/api/v1/market", tags=["模板市场"])


def _get_session():
    """获取数据库会话."""
    from sqlalchemy.orm import Session

    engine = get_engine()
    return Session(engine)


def _ensure_tables():
    """确保市场表已创建."""
    try:
        engine = get_engine()
        MarketTemplate.__table__.create(engine, checkfirst=True)
        MarketBlock.__table__.create(engine, checkfirst=True)
        MarketRating.__table__.create(engine, checkfirst=True)
    except Exception:
        pass


def _calc_rating_avg(rating_sum: float, rating_count: int) -> float:
    """计算平均评分."""
    return round(rating_sum / rating_count, 1) if rating_count and rating_count > 0 else 0.0


def _paginate_result(items: list, total: int, page: int, page_size: int) -> Dict[str, Any]:
    """生成分页结果字典.

    Args:
        items: 当前页数据列表
        total: 总记录数
        page: 当前页码
        page_size: 每页数量

    Returns:
        标准分页结果字典
    """
    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "size": page_size,  # 向后兼容
        "total_pages": total_pages,
    }


def _apply_pagination(query, page: int, page_size: int, get_all: bool = False):
    """应用分页到查询.

    Args:
        query: SQLAlchemy 查询对象
        page: 页码
        page_size: 每页数量
        get_all: 是否返回全部（跳过分页）

    Returns:
        应用分页后的查询对象
    """
    if get_all:
        return query
    return query.offset((page - 1) * page_size).limit(page_size)


# === 模板市场 ===


@market_router.post("/templates/publish")
async def publish_template(request: PublishTemplateRequest):
    """将已有工作流发布为市场模板."""
    _ensure_tables()
    session = _get_session()
    try:
        from ..models_db import WorkflowDefinition

        wf = session.query(WorkflowDefinition).filter_by(id=request.workflow_id).first()
        if not wf:
            raise HTTPException(status_code=404, detail="工作流不存在")

        template_id = f"mkt_{uuid.uuid4().hex[:12]}"
        mt = MarketTemplate(
            template_id=template_id,
            name=wf.name,
            description=request.description or wf.description,
            author=wf.created_by or "anonymous",
            category=request.category,
            tags=request.tags or wf.tags or [],
            blocks=wf.blocks or [],
            connections=wf.connections or [],
            variables=wf.variables or [],
            trigger=wf.trigger or {},
            source_workflow_id=request.workflow_id,
            status="published" if request.is_public else "unpublished",
        )
        session.add(mt)
        session.commit()

        # 失效相关缓存（发布模板：清理列表、搜索、统计、分类）
        if _HAS_UNIFIED_CACHE:
            _market_cache.clear(pattern="m7:market:templates:list:*")
            _market_cache.clear(pattern="m7:market:templates:search:*")
            _market_cache.delete("m7:market:stats")
            _market_cache.delete("m7:market:categories")

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "template_id": mt.template_id,
                "name": mt.name,
                "status": mt.status,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.get("/templates")
async def list_market_templates(
    category: Optional[str] = None,
    tag: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    size: Optional[int] = Query(None, ge=1, le=100),
    sort: str = "newest",
    all: bool = Query(False, description="是否返回全部数据（跳过分页）"),
):
    """浏览模板市场（缓存 1 分钟）."""
    import hashlib
    # 生成缓存 key，包含所有过滤和分页参数
    cache_key = (
        f"m7:market:templates:list:cat={category or 'all'}:"
        f"tag={tag or 'all'}:p={page}:ps={page_size}:size={size or 'none'}:"
        f"sort={sort}:all={str(all).lower()}"
    )
    if len(cache_key) > 200:
        h = hashlib.md5(cache_key.encode()).hexdigest()
        cache_key = f"m7:market:templates:list:hash:{h}"

    if _HAS_UNIFIED_CACHE and _market_cache.exists(cache_key):
        return _market_cache.get(cache_key)

    _ensure_tables()
    session = _get_session()
    try:
        # 向后兼容：size 参数作为 page_size 的别名
        actual_page_size = size if size is not None else page_size
        # all 模式下使用一个很大的 limit 模拟全量
        get_all = all

        query = session.query(MarketTemplate).filter_by(status="published")

        if category:
            query = query.filter_by(category=category)
        if tag:
            query = query.filter(MarketTemplate.tags.contains(tag))

        total = query.count()

        if sort == "popular":
            query = query.order_by(desc(MarketTemplate.download_count))
        elif sort == "rating":
            query = query.order_by(desc(MarketTemplate.rating_count))
        else:
            query = query.order_by(desc(MarketTemplate.created_at))

        query = _apply_pagination(query, page, actual_page_size, get_all)
        items = query.all()
        result = []
        for mt in items:
            avg = _calc_rating_avg(mt.rating_sum or 0.0, mt.rating_count or 0)
            result.append(
                MarketTemplateItem(
                    template_id=mt.template_id,
                    name=mt.name,
                    description=mt.description,
                    author=mt.author,
                    category=mt.category,
                    tags=mt.tags or [],
                    block_count=len(mt.blocks or []),
                    download_count=mt.download_count or 0,
                    rating_avg=avg,
                    rating_count=mt.rating_count or 0,
                    created_at=mt.created_at.strftime("%Y-%m-%d %H:%M:%S") if mt.created_at else "",
                ).dict()
            )

        response = {
            "code": 0,
            "message": "ok",
            "data": _paginate_result(result, total, page, actual_page_size if not get_all else total),
        }

        if _HAS_UNIFIED_CACHE:
            _market_cache.set(cache_key, response, ttl=60)  # 1 分钟

        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.get("/templates/search")
async def search_templates(
    q: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    size: Optional[int] = Query(None, ge=1, le=100),
    all: bool = Query(False, description="是否返回全部数据（跳过分页）"),
):
    """搜索模板（缓存 30 秒）."""
    import hashlib
    cache_key = (
        f"m7:market:templates:search:q={q}:"
        f"p={page}:ps={page_size}:size={size or 'none'}:all={str(all).lower()}"
    )
    if len(cache_key) > 200:
        h = hashlib.md5(cache_key.encode()).hexdigest()
        cache_key = f"m7:market:templates:search:hash:{h}"

    if _HAS_UNIFIED_CACHE and _market_cache.exists(cache_key):
        return _market_cache.get(cache_key)

    _ensure_tables()
    session = _get_session()
    try:
        actual_page_size = size if size is not None else page_size
        get_all = all

        pattern = f"%{q}%"
        query = session.query(MarketTemplate).filter_by(status="published").filter(
            (MarketTemplate.name.ilike(pattern))
            | (MarketTemplate.description.ilike(pattern))
            | (MarketTemplate.author.ilike(pattern))
        )
        total = query.count()
        query = query.order_by(desc(MarketTemplate.created_at))
        query = _apply_pagination(query, page, actual_page_size, get_all)
        items = query.all()

        result = []
        for mt in items:
            avg = _calc_rating_avg(mt.rating_sum or 0.0, mt.rating_count or 0)
            result.append(
                MarketTemplateItem(
                    template_id=mt.template_id,
                    name=mt.name,
                    description=mt.description,
                    author=mt.author,
                    category=mt.category,
                    tags=mt.tags or [],
                    block_count=len(mt.blocks or []),
                    download_count=mt.download_count or 0,
                    rating_avg=avg,
                    rating_count=mt.rating_count or 0,
                    created_at=mt.created_at.strftime("%Y-%m-%d %H:%M:%S") if mt.created_at else "",
                ).dict()
            )

        response = {
            "code": 0,
            "message": "ok",
            "data": _paginate_result(result, total, page, actual_page_size if not get_all else total),
        }

        if _HAS_UNIFIED_CACHE:
            _market_cache.set(cache_key, response, ttl=30)  # 30 秒

        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.get("/templates/{template_id}")
async def get_template(template_id: str):
    """模板详情（缓存 5 分钟）."""
    cache_key = f"m7:market:templates:detail:{template_id}"
    if _HAS_UNIFIED_CACHE and _market_cache.exists(cache_key):
        return _market_cache.get(cache_key)

    _ensure_tables()
    session = _get_session()
    try:
        mt = session.query(MarketTemplate).filter_by(template_id=template_id).first()
        if not mt:
            raise HTTPException(status_code=404, detail="模板不存在")

        avg = round(mt.rating_sum / mt.rating_count, 1) if mt.rating_count and mt.rating_count > 0 else 0.0
        result = {
            "code": 0,
            "message": "ok",
            "data": {
                "template_id": mt.template_id,
                "name": mt.name,
                "description": mt.description,
                "author": mt.author,
                "category": mt.category,
                "tags": mt.tags or [],
                "blocks": mt.blocks or [],
                "connections": mt.connections or [],
                "variables": mt.variables or [],
                "trigger": mt.trigger or {},
                "download_count": mt.download_count or 0,
                "rating_avg": avg,
                "rating_count": mt.rating_count or 0,
                "source_workflow_id": mt.source_workflow_id,
                "status": mt.status,
                "created_at": mt.created_at.strftime("%Y-%m-%d %H:%M:%S") if mt.created_at else "",
            },
        }

        if _HAS_UNIFIED_CACHE:
            _market_cache.set(cache_key, result, ttl=300)  # 5 分钟

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.post("/templates/{template_id}/install")
async def install_template(template_id: str):
    """安装模板（创建新的 draft 工作流）."""
    _ensure_tables()
    session = _get_session()
    try:
        from ..models_db import WorkflowDefinition

        mt = session.query(MarketTemplate).filter_by(template_id=template_id).first()
        if not mt:
            raise HTTPException(status_code=404, detail="模板不存在")

        new_id = f"wf_{uuid.uuid4().hex[:12]}"
        wf = WorkflowDefinition(
            id=new_id,
            name=mt.name,
            description=mt.description,
            category=mt.category,
            status="draft",
            blocks=mt.blocks or [],
            connections=mt.connections or [],
            variables=mt.variables or [],
            trigger=mt.trigger or {},
            created_by="",
            tags=mt.tags or [],
        )
        session.add(wf)

        mt.download_count = (mt.download_count or 0) + 1
        session.commit()

        # 失效相关缓存（下载计数变化：清理详情、列表、搜索、统计）
        if _HAS_UNIFIED_CACHE:
            _market_cache.delete(f"m7:market:templates:detail:{template_id}")
            _market_cache.clear(pattern="m7:market:templates:list:*")
            _market_cache.clear(pattern="m7:market:templates:search:*")
            _market_cache.delete("m7:market:stats")

        return {
            "code": 0,
            "message": "ok",
            "data": {"workflow_id": new_id, "name": mt.name},
        }
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.post("/templates/{template_id}/rate")
async def rate_template(template_id: str, request: RatingRequest):
    """模板评分."""
    _ensure_tables()
    session = _get_session()
    try:
        mt = session.query(MarketTemplate).filter_by(template_id=template_id).first()
        if not mt:
            raise HTTPException(status_code=404, detail="模板不存在")

        existing = (
            session.query(MarketRating)
            .filter_by(item_type="template", item_id=template_id, user_id="anonymous")
            .first()
        )

        if existing:
            old_rating = existing.rating
            existing.rating = request.rating
            existing.comment = request.comment
            mt.rating_sum = (mt.rating_sum or 0) - old_rating + request.rating
        else:
            rating_id = f"rt_{uuid.uuid4().hex[:12]}"
            r = MarketRating(
                id=rating_id,
                item_type="template",
                item_id=template_id,
                user_id="anonymous",
                rating=request.rating,
                comment=request.comment,
            )
            session.add(r)
            mt.rating_sum = (mt.rating_sum or 0) + request.rating
            mt.rating_count = (mt.rating_count or 0) + 1

        mt.updated_at = datetime.utcnow()
        session.commit()

        # 失效相关缓存（评分变化：清理详情、列表、搜索、统计）
        if _HAS_UNIFIED_CACHE:
            _market_cache.delete(f"m7:market:templates:detail:{template_id}")
            _market_cache.clear(pattern="m7:market:templates:list:*")
            _market_cache.clear(pattern="m7:market:templates:search:*")
            _market_cache.delete("m7:market:stats")

        avg = round(mt.rating_sum / mt.rating_count, 1) if mt.rating_count and mt.rating_count > 0 else 0.0
        return {"code": 0, "message": "ok", "data": {"rating_avg": avg, "rating_count": mt.rating_count}}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.delete("/templates/{template_id}")
async def unpublish_template(template_id: str):
    """下架模板."""
    _ensure_tables()
    session = _get_session()
    try:
        mt = session.query(MarketTemplate).filter_by(template_id=template_id).first()
        if not mt:
            raise HTTPException(status_code=404, detail="模板不存在")
        mt.status = "unpublished"
        mt.updated_at = datetime.utcnow()
        session.commit()

        # 失效相关缓存（模板下架：清理详情、列表、搜索、统计、分类）
        if _HAS_UNIFIED_CACHE:
            _market_cache.delete(f"m7:market:templates:detail:{template_id}")
            _market_cache.clear(pattern="m7:market:templates:list:*")
            _market_cache.clear(pattern="m7:market:templates:search:*")
            _market_cache.delete("m7:market:stats")
            _market_cache.delete("m7:market:categories")

        return {"code": 0, "message": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


# === 积木市场 ===


@market_router.post("/blocks/publish")
async def publish_block(
    request: PublishBlockRequest,
    current_user: dict = Depends(get_current_user),
):
    """发布自定义积木到市场."""
    user_id = current_user.get("username", "")
    _ensure_tables()
    session = _get_session()
    try:
        from ..models_db import CustomBlock

        cb = session.query(CustomBlock).filter_by(id=request.block_id).first()
        if not cb:
            raise HTTPException(status_code=404, detail="积木不存在")

        # 所有权校验
        if cb.user_id != user_id and user_id != "admin":
            _add_audit_log(
                event_type="market_block_unauthorized_publish",
                severity="warning",
                user_id=user_id,
                block_id=request.block_id,
                details="无权限发布该积木到市场",
            )
            raise HTTPException(status_code=403, detail="无权限发布该积木")

        # 安全校验：代码安全检查（发布到市场前必须通过）
        is_safe, safe_reason = validate_custom_block_code(
            cb.code or "",
            user_id=user_id,
            block_id=request.block_id,
        )
        if not is_safe:
            _add_audit_log(
                event_type="market_block_publish_rejected",
                severity="warning",
                user_id=user_id,
                block_id=request.block_id,
                details=f"发布被拒：{safe_reason}",
            )
            raise HTTPException(status_code=400, detail=f"代码安全校验失败：{safe_reason}")

        # 名称清洗
        clean_name = sanitize_custom_block_name(cb.name or "", 200)
        if not clean_name:
            raise HTTPException(status_code=400, detail="积木名称无效")

        block_id = f"mkb_{uuid.uuid4().hex[:12]}"
        mb = MarketBlock(
            block_id=block_id,
            name=clean_name,
            description=(request.description or cb.description or "")[:2000],
            author=cb.user_id or "anonymous",
            category=request.category,
            tags=request.tags or [],
            code=cb.code or "",
            icon=cb.icon or "puzzle",
            ports=cb.ports or {},
            source_block_id=request.block_id,
            status="published" if request.is_public else "unpublished",
        )
        session.add(mb)
        session.commit()

        # 审计日志
        _add_audit_log(
            event_type="market_block_published",
            severity="info",
            user_id=user_id,
            block_id=block_id,
            details=f"发布积木到市场：{clean_name}（来源：{request.block_id}）",
        )

        # 失效相关缓存（发布积木：清理列表、搜索、统计、分类）
        if _HAS_UNIFIED_CACHE:
            _market_cache.clear(pattern="m7:market:blocks:list:*")
            _market_cache.clear(pattern="m7:market:blocks:search:*")
            _market_cache.delete("m7:market:stats")
            _market_cache.delete("m7:market:categories")

        return {"code": 0, "message": "ok", "data": {"block_id": mb.block_id, "name": mb.name, "status": mb.status}}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.get("/blocks")
async def list_market_blocks(
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    size: Optional[int] = Query(None, ge=1, le=100),
    all: bool = Query(False, description="是否返回全部数据（跳过分页）"),
):
    """浏览积木市场（缓存 1 分钟）."""
    import hashlib
    cache_key = (
        f"m7:market:blocks:list:cat={category or 'all'}:"
        f"p={page}:ps={page_size}:size={size or 'none'}:all={str(all).lower()}"
    )
    if len(cache_key) > 200:
        h = hashlib.md5(cache_key.encode()).hexdigest()
        cache_key = f"m7:market:blocks:list:hash:{h}"

    if _HAS_UNIFIED_CACHE and _market_cache.exists(cache_key):
        return _market_cache.get(cache_key)

    _ensure_tables()
    session = _get_session()
    try:
        actual_page_size = size if size is not None else page_size
        get_all = all

        query = session.query(MarketBlock).filter_by(status="published")
        if category:
            query = query.filter_by(category=category)

        total = query.count()
        query = query.order_by(desc(MarketBlock.created_at))
        query = _apply_pagination(query, page, actual_page_size, get_all)
        items = query.all()

        result = []
        for mb in items:
            avg = _calc_rating_avg(mb.rating_sum or 0.0, mb.rating_count or 0)
            result.append(
                MarketBlockItem(
                    block_id=mb.block_id,
                    name=mb.name,
                    description=mb.description,
                    author=mb.author,
                    category=mb.category,
                    tags=mb.tags or [],
                    download_count=mb.download_count or 0,
                    rating_avg=avg,
                    rating_count=mb.rating_count or 0,
                    created_at=mb.created_at.strftime("%Y-%m-%d %H:%M:%S") if mb.created_at else "",
                ).dict()
            )

        response = {
            "code": 0,
            "message": "ok",
            "data": _paginate_result(result, total, page, actual_page_size if not get_all else total),
        }

        if _HAS_UNIFIED_CACHE:
            _market_cache.set(cache_key, response, ttl=60)  # 1 分钟

        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.get("/blocks/search")
async def search_blocks(
    q: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    size: Optional[int] = Query(None, ge=1, le=100),
    all: bool = Query(False, description="是否返回全部数据（跳过分页）"),
):
    """搜索积木（缓存 30 秒）."""
    import hashlib
    cache_key = (
        f"m7:market:blocks:search:q={q}:"
        f"p={page}:ps={page_size}:size={size or 'none'}:all={str(all).lower()}"
    )
    if len(cache_key) > 200:
        h = hashlib.md5(cache_key.encode()).hexdigest()
        cache_key = f"m7:market:blocks:search:hash:{h}"

    if _HAS_UNIFIED_CACHE and _market_cache.exists(cache_key):
        return _market_cache.get(cache_key)

    _ensure_tables()
    session = _get_session()
    try:
        actual_page_size = size if size is not None else page_size
        get_all = all

        pattern = f"%{q}%"
        query = session.query(MarketBlock).filter_by(status="published").filter(
            (MarketBlock.name.ilike(pattern))
            | (MarketBlock.description.ilike(pattern))
            | (MarketBlock.author.ilike(pattern))
        )
        total = query.count()
        query = query.order_by(desc(MarketBlock.created_at))
        query = _apply_pagination(query, page, actual_page_size, get_all)
        items = query.all()

        result = []
        for mb in items:
            avg = _calc_rating_avg(mb.rating_sum or 0.0, mb.rating_count or 0)
            result.append(
                MarketBlockItem(
                    block_id=mb.block_id,
                    name=mb.name,
                    description=mb.description,
                    author=mb.author,
                    category=mb.category,
                    tags=mb.tags or [],
                    download_count=mb.download_count or 0,
                    rating_avg=avg,
                    rating_count=mb.rating_count or 0,
                    created_at=mb.created_at.strftime("%Y-%m-%d %H:%M:%S") if mb.created_at else "",
                ).dict()
            )

        response = {
            "code": 0,
            "message": "ok",
            "data": _paginate_result(result, total, page, actual_page_size if not get_all else total),
        }

        if _HAS_UNIFIED_CACHE:
            _market_cache.set(cache_key, response, ttl=30)  # 30 秒

        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.get("/blocks/{block_id}")
async def get_block(block_id: str):
    """积木详情（缓存 5 分钟）."""
    cache_key = f"m7:market:blocks:detail:{block_id}"
    if _HAS_UNIFIED_CACHE and _market_cache.exists(cache_key):
        return _market_cache.get(cache_key)

    _ensure_tables()
    session = _get_session()
    try:
        mb = session.query(MarketBlock).filter_by(block_id=block_id).first()
        if not mb:
            raise HTTPException(status_code=404, detail="积木不存在")

        avg = round(mb.rating_sum / mb.rating_count, 1) if mb.rating_count and mb.rating_count > 0 else 0.0
        result = {
            "code": 0,
            "message": "ok",
            "data": {
                "block_id": mb.block_id,
                "name": mb.name,
                "description": mb.description,
                "author": mb.author,
                "category": mb.category,
                "tags": mb.tags or [],
                "code": mb.code,
                "icon": mb.icon,
                "ports": mb.ports or {},
                "download_count": mb.download_count or 0,
                "rating_avg": avg,
                "rating_count": mb.rating_count or 0,
                "status": mb.status,
                "created_at": mb.created_at.strftime("%Y-%m-%d %H:%M:%S") if mb.created_at else "",
            },
        }

        if _HAS_UNIFIED_CACHE:
            _market_cache.set(cache_key, result, ttl=300)  # 5 分钟

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.post("/blocks/{block_id}/install")
async def install_block(
    block_id: str,
    current_user: dict = Depends(get_current_user),
):
    """安装积木（创建自定义积木副本）."""
    user_id = current_user.get("username", "")
    _ensure_tables()
    session = _get_session()
    try:
        from ..models_db import CustomBlock

        mb = session.query(MarketBlock).filter_by(block_id=block_id).first()
        if not mb:
            raise HTTPException(status_code=404, detail="积木不存在")

        # 安全校验：安装前再次检查代码安全性
        is_safe, safe_reason = validate_custom_block_code(
            mb.code or "",
            user_id=user_id,
            block_id=block_id,
        )
        if not is_safe:
            _add_audit_log(
                event_type="market_block_install_rejected",
                severity="warning",
                user_id=user_id,
                block_id=block_id,
                details=f"安装被拒：{safe_reason}",
            )
            raise HTTPException(status_code=400, detail=f"代码安全校验失败：{safe_reason}")

        new_id = f"cb_{uuid.uuid4().hex[:12]}"
        cb = CustomBlock(
            id=new_id,
            name=mb.name,
            category=mb.category,
            description=mb.description,
            code=mb.code or "",
            icon=mb.icon or "puzzle",
            ports=mb.ports or {},
            user_id=user_id,  # 修复：绑定到当前用户
        )
        session.add(cb)

        mb.download_count = (mb.download_count or 0) + 1
        session.commit()

        # 审计日志
        _add_audit_log(
            event_type="market_block_installed",
            severity="info",
            user_id=user_id,
            block_id=new_id,
            details=f"安装市场积木：{mb.name}（来源：{block_id}）",
        )

        # 失效相关缓存（下载计数变化：清理详情、列表、搜索、统计）
        if _HAS_UNIFIED_CACHE:
            _market_cache.delete(f"m7:market:blocks:detail:{block_id}")
            _market_cache.clear(pattern="m7:market:blocks:list:*")
            _market_cache.clear(pattern="m7:market:blocks:search:*")
            _market_cache.delete("m7:market:stats")

        return {"code": 0, "message": "ok", "data": {"block_id": new_id, "name": mb.name}}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.post("/blocks/{block_id}/rate")
async def rate_block(block_id: str, request: RatingRequest):
    """积木评分."""
    _ensure_tables()
    session = _get_session()
    try:
        mb = session.query(MarketBlock).filter_by(block_id=block_id).first()
        if not mb:
            raise HTTPException(status_code=404, detail="积木不存在")

        existing = (
            session.query(MarketRating)
            .filter_by(item_type="block", item_id=block_id, user_id="anonymous")
            .first()
        )

        if existing:
            old_rating = existing.rating
            existing.rating = request.rating
            existing.comment = request.comment
            mb.rating_sum = (mb.rating_sum or 0) - old_rating + request.rating
        else:
            rating_id = f"rt_{uuid.uuid4().hex[:12]}"
            r = MarketRating(
                id=rating_id,
                item_type="block",
                item_id=block_id,
                user_id="anonymous",
                rating=request.rating,
                comment=request.comment,
            )
            session.add(r)
            mb.rating_sum = (mb.rating_sum or 0) + request.rating
            mb.rating_count = (mb.rating_count or 0) + 1

        mb.updated_at = datetime.utcnow()
        session.commit()

        # 失效相关缓存（评分变化：清理详情、列表、搜索、统计）
        if _HAS_UNIFIED_CACHE:
            _market_cache.delete(f"m7:market:blocks:detail:{block_id}")
            _market_cache.clear(pattern="m7:market:blocks:list:*")
            _market_cache.clear(pattern="m7:market:blocks:search:*")
            _market_cache.delete("m7:market:stats")

        avg = round(mb.rating_sum / mb.rating_count, 1) if mb.rating_count and mb.rating_count > 0 else 0.0
        return {"code": 0, "message": "ok", "data": {"rating_avg": avg, "rating_count": mb.rating_count}}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.delete("/blocks/{block_id}")
async def unpublish_block(block_id: str):
    """下架积木."""
    _ensure_tables()
    session = _get_session()
    try:
        mb = session.query(MarketBlock).filter_by(block_id=block_id).first()
        if not mb:
            raise HTTPException(status_code=404, detail="积木不存在")
        mb.status = "unpublished"
        mb.updated_at = datetime.utcnow()
        session.commit()

        # 失效相关缓存（积木下架：清理详情、列表、搜索、统计、分类）
        if _HAS_UNIFIED_CACHE:
            _market_cache.delete(f"m7:market:blocks:detail:{block_id}")
            _market_cache.clear(pattern="m7:market:blocks:list:*")
            _market_cache.clear(pattern="m7:market:blocks:search:*")
            _market_cache.delete("m7:market:stats")
            _market_cache.delete("m7:market:categories")

        return {"code": 0, "message": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


# === 统计 ===


@market_router.get("/stats/summary")
async def get_market_stats():
    """市场统计（缓存 5 分钟）."""
    cache_key = "m7:market:stats"
    if _HAS_UNIFIED_CACHE and _market_cache.exists(cache_key):
        return _market_cache.get(cache_key)

    _ensure_tables()
    session = _get_session()
    try:
        # 模板总数（SQL count）
        tpl_count = session.query(MarketTemplate).filter_by(status="published").count()
        # 积木总数（SQL count）
        blk_count = session.query(MarketBlock).filter_by(status="published").count()

        # 模板下载总量（SQL sum 替代 Python 循环）
        tpl_dl_row = session.query(
            func.coalesce(func.sum(MarketTemplate.download_count), 0)
        ).filter_by(status="published").first()
        tpl_dl = int(tpl_dl_row[0]) if tpl_dl_row else 0

        # 积木下载总量（SQL sum 替代 Python 循环）
        blk_dl_row = session.query(
            func.coalesce(func.sum(MarketBlock.download_count), 0)
        ).filter_by(status="published").first()
        blk_dl = int(blk_dl_row[0]) if blk_dl_row else 0

        # 平均评分（SQL avg 替代 Python 循环）
        avg_rating_row = session.query(
            func.coalesce(func.avg(MarketRating.rating), 0.0)
        ).first()
        avg_rating = round(float(avg_rating_row[0]), 1) if avg_rating_row else 0.0

        # 分类统计（SQL group_by 替代 Python 循环）
        categories: Dict[str, int] = {}

        # 模板分类统计
        tpl_cat_rows = session.query(
            MarketTemplate.category,
            func.count(MarketTemplate.template_id)
        ).filter_by(status="published").group_by(MarketTemplate.category).all()
        for cat, count in tpl_cat_rows:
            cat_key = cat or "general"
            categories[cat_key] = categories.get(cat_key, 0) + count

        # 积木分类统计
        blk_cat_rows = session.query(
            MarketBlock.category,
            func.count(MarketBlock.block_id)
        ).filter_by(status="published").group_by(MarketBlock.category).all()
        for cat, count in blk_cat_rows:
            cat_key = cat or "general"
            categories[cat_key] = categories.get(cat_key, 0) + count

        result = {
            "code": 0,
            "message": "ok",
            "data": MarketStats(
                total_templates=tpl_count,
                total_blocks=blk_count,
                total_downloads=tpl_dl + blk_dl,
                avg_rating=avg_rating,
                categories=categories,
            ).dict(),
        }

        if _HAS_UNIFIED_CACHE:
            _market_cache.set(cache_key, result, ttl=300)  # 5 分钟

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@market_router.get("/categories/list")
async def get_categories():
    """分类列表（缓存 10 分钟）."""
    cache_key = "m7:market:categories"
    if _HAS_UNIFIED_CACHE and _market_cache.exists(cache_key):
        return _market_cache.get(cache_key)

    _ensure_tables()
    session = _get_session()
    try:
        cats = set()
        for mt in session.query(MarketTemplate).filter_by(status="published").all():
            if mt.category:
                cats.add(mt.category)
        for mb in session.query(MarketBlock).filter_by(status="published").all():
            if mb.category:
                cats.add(mb.category)

        result_data = sorted(cats) if cats else ["general"]
        result = {"code": 0, "message": "ok", "data": result_data}

        if _HAS_UNIFIED_CACHE:
            _market_cache.set(cache_key, result, ttl=600)  # 10 分钟

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
