"""
M8 标准接口路由定义

使用 FastAPI APIRouter 将 M8Interface 的方法挂载为 HTTP 路由。
所有端点遵循 M8 标准响应格式，包含 module、version、timestamp 等字段。

认证说明：
    本模块仅声明 x-m8-token Header 参数以完善 OpenAPI 文档，
    实际认证逻辑由 FastAPIAuthMiddleware 中间件统一处理。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
import structlog

from tide_memory.api.m8_interface import M8Interface

logger = structlog.get_logger(__name__)


# ============ Pydantic 模型 ============

class M8RecallRequest(BaseModel):
    """M8 标准记忆检索请求（兼容 V1 字段格式）"""
    query: str
    top_k: int = 10
    layers: List[str] = ["l1_shallow", "l2_deep"]
    domain: str = "private"
    agent_id: str = "unknown"
    emotion_context: Optional[Dict] = None


class M8ArchiveRequest(BaseModel):
    """M8 标准记忆归档请求（兼容 V1 字段格式）"""
    content: str
    domain: str = "private"
    agent_id: str = "system"
    tags: List[str] = []
    emotion_context: Optional[Dict] = None
    metadata: Dict[str, Any] = {}
    source: str = "conversation"


# ============ Router 工厂 ============


def create_m8_router(m8_interface: M8Interface) -> APIRouter:
    """
    创建 M8 标准接口 APIRouter

    Args:
        m8_interface: M8 接口适配层实例

    Returns:
        配置好的 FastAPI APIRouter（前缀为 /m8）
    """
    router = APIRouter(prefix="/m8", tags=["M8 Standard Interface"])

    @router.get(
        "/health",
        summary="M8 标准健康检查",
    )
    async def m8_health(
        request: Request,
        x_m8_token: str = Header(default="", description="M8 内部调用 Token"),
    ):
        """
        M8 标准健康检查接口

        需要 x-m8-token 头部进行认证（当 M5_AUTH_ENABLED=true 时）。
        认证由 FastAPIAuthMiddleware 中间件统一处理。
        """
        logger.debug(
            "m8_health_check_called",
            path="/m8/health",
            client=request.client.host if request.client else "unknown",
        )
        result = m8_interface.m8_health_check()
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @router.get(
        "/metrics",
        summary="M8 标准性能指标",
    )
    async def m8_metrics(
        request: Request,
        x_m8_token: str = Header(default="", description="M8 内部调用 Token"),
    ):
        """
        M8 标准性能指标接口

        返回潮汐系统的运行指标：记忆条数、各层数量、EI模型状态、潮汐相位等。
        """
        logger.debug(
            "m8_metrics_called",
            path="/m8/metrics",
            client=request.client.host if request.client else "unknown",
        )
        result = m8_interface.m8_metrics()
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @router.get(
        "/config",
        summary="M8 标准配置查询",
    )
    async def m8_config(
        request: Request,
        x_m8_token: str = Header(default="", description="M8 内部调用 Token"),
    ):
        """
        M8 标准配置查询接口

        返回潮汐系统的完整配置信息（已脱敏）。
        """
        logger.debug(
            "m8_config_called",
            path="/m8/config",
            client=request.client.host if request.client else "unknown",
        )
        result = m8_interface.m8_config()
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @router.post(
        "/memory/recall",
        summary="M8 标准记忆检索",
    )
    async def m8_memory_recall(req: M8RecallRequest):
        """M8标准记忆检索接口（兼容V1字段格式）"""
        params = {
            "query": req.query,
            "top_k": req.top_k,
            "filters": {
                "domain": req.domain,
                "layers": req.layers,
            },
            "context": {
                "agent_id": req.agent_id,
                "emotion": req.emotion_context,
            },
        }
        result = m8_interface.m8_recall(params)
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @router.post(
        "/memory/archive",
        summary="M8 标准记忆归档",
    )
    async def m8_memory_archive(req: M8ArchiveRequest):
        """M8标准记忆归档接口（兼容V1字段格式）"""
        params = {
            "content": req.content,
            "source": req.source,
            "metadata": {
                "domain": req.domain,
                "tags": req.tags,
                "emotion": req.emotion_context,
                "extra": req.metadata,
            },
            "context": {
                "agent_id": req.agent_id,
            },
        }
        result = m8_interface.m8_archive(params)
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @router.get(
        "/memory/stats",
        summary="M8 标准记忆统计",
    )
    async def m8_memory_stats():
        """M8标准记忆统计接口"""
        return m8_interface.m8_get_stats()

    return router
# vim: set et ts=4 sw=4:
