"""
记忆共享 API 路由

挂载在 /api/v1/memory/share 下，提供：
- POST /export          导出记忆为共享包
- POST /import          导入共享记忆包
- GET  /pool            浏览共享池
- GET  /search          搜索共享包
- GET  /stats/summary   共享统计
- GET  /{share_id}      共享包详情
- POST /{share_id}/rate 评分
- DELETE /{share_id}    删除共享包

上下文注入：
通过 configure_share_router(app_ctx) 注入 recall_engine、desensitizer、
domain_manager。未配置时使用独立实例降级运行。

注意路由注册顺序：静态路径（/pool、/search、/stats/summary）必须
在路径参数路由 /{share_id} 之前注册，否则会被抢先匹配。
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, HTTPException, Query

from .models import (
    ExportRequest,
    ImportRequest,
    RatingRequest,
    ShareListing,
    SharePackage,
    ShareStats,
)

logger = structlog.get_logger(__name__)

# ============================================================
# 全局上下文（通过 configure_share_router 注入）
# ============================================================

_share_context: Dict[str, Any] = {}


def configure_share_router(app_ctx: Optional[dict] = None) -> None:
    """配置共享路由的应用上下文

    从 app_ctx 中提取 recall_engine、desensitizer、domain_manager，
    存入全局 _share_context 供路由端点使用。

    Args:
        app_ctx: create_app() 返回的上下文字典，可包含以下键：
            - "recall": RecallEngine 实例
            - "domain_manager": DomainManager 实例
            - "secret_marker": SecretMarker 实例
    """
    global _share_context
    if app_ctx is None:
        _share_context = {}
        return

    _share_context = {
        "recall_engine": app_ctx.get("recall"),
        "domain_manager": app_ctx.get("domain_manager"),
        "secret_marker": app_ctx.get("secret_marker"),
    }

    # 尝试导入并实例化 DataDesensitizer
    try:
        from ..security.desensitizer import DataDesensitizer

        _share_context["desensitizer"] = DataDesensitizer()
    except Exception as e:
        logger.warning("share_router_desensitizer_init_failed", error=str(e))
        _share_context["desensitizer"] = None

    logger.info(
        "share_router_configured",
        has_recall=_share_context.get("recall_engine") is not None,
        has_desensitizer=_share_context.get("desensitizer") is not None,
        has_domain_manager=_share_context.get("domain_manager") is not None,
    )


def _get_exporter():
    """获取 MemoryExporter 实例（基于当前上下文）"""
    from .exporter import MemoryExporter

    return MemoryExporter(
        recall_engine=_share_context.get("recall_engine"),
        desensitizer=_share_context.get("desensitizer"),
    )


def _get_importer():
    """获取 MemoryImporter 实例（基于当前上下文）"""
    from .importer import MemoryImporter

    return MemoryImporter(
        recall_engine=_share_context.get("recall_engine"),
        domain_manager=_share_context.get("domain_manager"),
    )


def _get_pool() -> "SharePoolManager":
    """获取共享池管理器单例"""
    from .share_pool import SharePoolManager

    return SharePoolManager.get_instance()


def _success(data: Any = None, message: str = "success") -> Dict[str, Any]:
    """构建成功响应"""
    return {"code": 0, "message": message, "data": data}


def _error(message: str, code: int = 500) -> Dict[str, Any]:
    """构建错误响应"""
    return {"code": code, "message": message, "data": None}


# ============================================================
# 路由定义
# ============================================================

share_router = APIRouter(prefix="/api/v1/memory/share", tags=["记忆共享"])


@share_router.post("/export", summary="导出记忆为共享包")
async def export_memories(request: ExportRequest):
    """导出记忆为共享包

    将指定记忆的元数据脱敏打包，保存到共享池。
    导出的记忆不包含原文，密级最高为 INTERNAL。
    """
    try:
        exporter = _get_exporter()
        package = exporter.export_memories(
            memory_ids=request.memory_ids,
            title=request.title,
            description=request.description,
            tags=request.tags,
            domain=request.domain,
            limit=request.limit,
        )

        # 保存到共享池
        pool = _get_pool()
        saved = pool.save_package(package)
        if not saved:
            logger.warning("export_save_failed", share_id=package.get("share_id"))

        logger.info(
            "share_export_ok",
            share_id=package.get("share_id"),
            item_count=package.get("item_count"),
        )
        return _success(package, "导出成功")
    except Exception as e:
        logger.error("share_export_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


@share_router.post("/import", summary="导入共享记忆包")
async def import_memories(request: ImportRequest):
    """导入共享记忆包

    从共享池读取指定包，将记忆导入到 shared 域。
    导入时生成新的 memory_id，不会覆盖已有记忆。
    """
    # 安全约束：目标域只能是 shared
    if request.target_domain != "shared":
        raise HTTPException(
            status_code=403,
            detail="安全约束：导入目标域只能是 shared，不能写入 private 或 core",
        )

    try:
        pool = _get_pool()
        package = pool.get_package(request.share_id)
        if package is None:
            raise HTTPException(status_code=404, detail="共享包不存在")

        importer = _get_importer()
        result = importer.import_package(
            package=package,
            target_domain=request.target_domain,
            overwrite=request.overwrite,
        )

        # 记录导入日志
        if result.get("success"):
            try:
                pool.record_import(
                    share_id=request.share_id,
                    importer="anonymous",
                    imported_count=result.get("imported_count", 0),
                    failed_count=result.get("failed_count", 0),
                )
            except Exception as e:
                logger.warning("share_import_record_failed", error=str(e))

        return _success(result, "导入完成")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("share_import_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@share_router.get("/pool", summary="浏览共享池")
async def list_share_pool(
    tag: Optional[str] = Query(None, description="按标签过滤"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """浏览共享池"""
    try:
        pool = _get_pool()
        listings, total = pool.list_packages(tag=tag, page=page, size=size)
        return _success(
            {
                "items": listings,
                "page": page,
                "size": size,
                "total": total,
            },
            "查询成功",
        )
    except Exception as e:
        logger.error("share_list_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@share_router.get("/search", summary="搜索共享包")
async def search_share(
    q: str = Query(..., description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """搜索共享包（在标题、描述、标签中搜索）"""
    try:
        pool = _get_pool()
        listings, total = pool.search(query=q, page=page, size=size)
        return _success(
            {
                "items": listings,
                "query": q,
                "page": page,
                "size": size,
                "total": total,
            },
            "搜索完成",
        )
    except Exception as e:
        logger.error("share_search_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@share_router.get("/stats/summary", summary="共享统计")
async def get_share_stats():
    """获取共享池统计信息"""
    try:
        pool = _get_pool()
        stats = pool.get_stats()
        return _success(stats, "统计成功")
    except Exception as e:
        logger.error("share_stats_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"统计失败: {str(e)}")


# ---- 路径参数路由（必须放在静态路径之后） ----


@share_router.get("/{share_id}", summary="共享包详情")
async def get_share_package(share_id: str):
    """获取共享包详情（含记忆条目）"""
    try:
        pool = _get_pool()
        package = pool.get_package(share_id)
        if package is None:
            raise HTTPException(status_code=404, detail="共享包不存在")
        return _success(package, "获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("share_get_failed", share_id=share_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@share_router.post("/{share_id}/rate", summary="评分")
async def rate_share(share_id: str, request: RatingRequest):
    """对共享包评分（1-5 分，每个用户仅一次，重复则更新）"""
    try:
        pool = _get_pool()
        # 检查包是否存在
        package = pool.get_package(share_id)
        if package is None:
            raise HTTPException(status_code=404, detail="共享包不存在")

        # 使用随机 user_id（无认证系统时的降级方案）
        user_id = f"usr_{uuid.uuid4().hex[:8]}"
        success = pool.rate(
            share_id=share_id,
            user_id=user_id,
            rating=request.rating,
            comment=request.comment,
        )
        if not success:
            raise HTTPException(status_code=400, detail="评分失败")
        return _success({"rated": True, "rating": request.rating}, "评分成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("share_rate_failed", share_id=share_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"评分失败: {str(e)}")


@share_router.delete("/{share_id}", summary="删除共享包")
async def delete_share(share_id: str):
    """删除共享包"""
    try:
        pool = _get_pool()
        deleted = pool.delete_package(share_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="共享包不存在或已删除")
        return _success({"deleted": True}, "删除成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("share_delete_failed", share_id=share_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# vim: set et ts=4 sw=4:
