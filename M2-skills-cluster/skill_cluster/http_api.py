from __future__ import annotations

"""HTTP API - RESTful HTTP 封装层.

【整改 R01 - 评审报告 REV-20250628-M2-001】
评审意见：模块缺少对外 HTTP 接口，无法被外部系统/主控调用。

设计：基于 FastAPI 提供 4 个核心 REST 接口：
1. POST /api/v1/skills/invoke    — 技能调用
2. GET  /api/v1/skills/{id}       — 技能查询
3. GET  /api/v1/skills/search     — 技能搜索
4. GET  /api/v1/health            — 集群健康检查

FastAPI 为可选依赖，未安装时优雅降级（仅提供数据转换函数）。
"""

import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

# FastAPI 可选导入
_fastapi_available = False
try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import JSONResponse
    _fastapi_available = True
except ImportError:
    FastAPI = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]


# ---- 请求/响应模型 ----

class InvokeRequest(BaseModel):
    """技能调用 HTTP 请求."""
    skill_id: str = Field(..., description="技能ID")
    action: str = Field(default="default", description="动作标识")
    params: dict[str, Any] = Field(default_factory=dict, description="参数")
    agent_id: str = Field(default="default_agent", description="Agent ID")
    timeout: int | None = Field(default=None, description="超时(秒)")
    cache_scope: str = Field(default="public", description="缓存作用域")
    ttl_ms: int | None = Field(default=None, description="毫秒级TTL")


class SkillInfo(BaseModel):
    """技能信息 HTTP 响应."""
    skill_id: str
    name: str
    description: str
    category: str
    tags: list[str]
    actions: list[str]
    complexity_score: float


class SearchResponse(BaseModel):
    """搜索结果 HTTP 响应."""
    query: str
    results: list[SkillInfo]
    total: int


class HealthResponse(BaseModel):
    """健康检查 HTTP 响应."""
    status: str
    score: float
    components: list[dict[str, Any]]


# ---- 数据转换函数（不依赖 FastAPI，始终可用）----

def manifest_to_skill_info(manifest: Any) -> SkillInfo:
    """将 SkillManifest 转换为 SkillInfo HTTP 模型."""
    return SkillInfo(
        skill_id=manifest.skill_id,
        name=manifest.name,
        description=manifest.description,
        category=getattr(manifest, "category", ""),
        tags=getattr(manifest, "tags", []),
        actions=getattr(manifest, "actions", []),
        complexity_score=getattr(manifest, "complexity_score", 1.0),
    )


def result_to_dict(result: Any) -> dict[str, Any]:
    """将 SkillInvokeResult 转换为 HTTP 响应字典."""
    return {
        "skill_id": result.skill_id,
        "action": result.action,
        "status": result.status,
        "data": result.data,
        "error": result.error,
        "latency_ms": result.latency_ms,
        "trace_id": result.trace_id,
    }


# ---- FastAPI 应用工厂 ----

def create_app(
    registry: Any = None,
    router: Any = None,
    health_checker: Any = None,
) -> Any:
    """创建 FastAPI 应用实例.

    Args:
        registry: SkillRegistry 实例（技能查询/搜索）.
        router: SkillRouter 实例（技能调用）.
        health_checker: SkillClusterHealthChecker 实例（健康检查）.

    Returns:
        FastAPI 实例，若未安装则返回 None.
    """
    if not _fastapi_available:
        logger.warning("http_api_disabled", reason="fastapi not installed")
        return None

    app = FastAPI(
        title="云汐 Skills 集群 API",
        version="3.7.0",
        description="Skills技能集群系统 RESTful HTTP 接口",
    )

    # 存储依赖
    app.state.registry = registry
    app.state.router = router
    app.state.health_checker = health_checker

    @app.get("/api/v1/health", response_model=HealthResponse)
    async def health_check():
        """集群健康检查."""
        if health_checker is None:
            return HealthResponse(
                status="unknown", score=0.0, components=[]
            )
        report = health_checker.check()
        return HealthResponse(
            status=report.overall_status.value,
            score=report.overall_score,
            components=[
                {
                    "name": c.component_name,
                    "status": c.status.value,
                    "score": round(c.score, 3),
                }
                for c in report.components
            ],
        )

    @app.post("/api/v1/skills/invoke")
    async def invoke_skill(req: InvokeRequest):
        """调用技能."""
        if router is None:
            raise HTTPException(status_code=503, detail="Router not configured")
        try:
            from skill_cluster.interfaces import SkillInvokeRequest
            invoke_req = SkillInvokeRequest(
                skill_id=req.skill_id,
                action=req.action,
                params=req.params,
                trace_id=f"http_{int(time.time()*1000)}",
                timeout=req.timeout,
                cache_scope=req.cache_scope,
                ttl_ms=req.ttl_ms,
            )
            result = await router.invoke(invoke_req, req.agent_id)
            return result_to_dict(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/skills/{skill_id}")
    async def get_skill(skill_id: str):
        """查询技能详情."""
        if registry is None:
            raise HTTPException(status_code=503, detail="Registry not configured")
        manifest = registry.get_manifest(skill_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
        return manifest_to_skill_info(manifest)

    @app.get("/api/v1/skills/search")
    async def search_skills(
        q: str = Query(..., description="搜索关键词"),
        limit: int = Query(default=10, ge=1, le=50, description="返回数量"),
    ):
        """搜索技能."""
        if registry is None:
            raise HTTPException(status_code=503, detail="Registry not configured")
        try:
            from skill_cluster.interfaces import SkillQuery
            manifests = registry.discover(
                SkillQuery(semantic_query=q)
            )
            results = [
                manifest_to_skill_info(m) for m in manifests[:limit]
            ]
            return SearchResponse(
                query=q, results=results, total=len(results)
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return app
