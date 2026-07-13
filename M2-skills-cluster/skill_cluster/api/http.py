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
        category=getattr(manifest, "category", "general"),
        tags=getattr(manifest, "tags", []),
        actions=[a.name for a in manifest.actions] if hasattr(manifest, "actions") else [],
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

def create_http_app(router: Any = None, registry: Any = None) -> Any:
    """创建 HTTP API 应用.

    Args:
        router: SkillRouter 实例
        registry: SkillRegistry 实例

    Returns:
        FastAPI 实例，若未安装 fastapi 则返回 None
    """
    if not _fastapi_available:
        logger.warning("http_api_disabled", reason="fastapi not installed")
        return None

    from skill_cluster.core.router import SkillRouter
    from skill_cluster.core.registry import SkillRegistry

    app = FastAPI(
        title="M2 Skill技能集群 API",
        description="M2 技能集群系统 HTTP 接口",
        version="1.0.0",
    )

    _router = router or SkillRouter()
    _registry = registry or _router._registry

    @app.post("/api/v1/skills/invoke")
    async def invoke_skill(req: InvokeRequest) -> dict[str, Any]:
        """调用技能."""
        from skill_cluster.interfaces import SkillInvokeRequest as RouterRequest
        invoke_req = RouterRequest(
            skill_id=req.skill_id,
            action=req.action,
            params=req.params,
            agent_id=req.agent_id,
            timeout=req.timeout,
            trace_id=f"http_{int(time.time()*1000)}",
        )
        result = await _router.invoke(invoke_req, req.agent_id)
        return result_to_dict(result)

    @app.get("/api/v1/skills/{skill_id}")
    async def get_skill(skill_id: str) -> dict[str, Any]:
        """查询技能详情."""
        skill = _registry.get_skill(skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill {skill_id} not found")
        return manifest_to_skill_info(skill.manifest).model_dump()

    @app.get("/api/v1/skills/search")
    async def search_skills(
        q: str = Query(..., description="搜索关键词"),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> SearchResponse:
        """搜索技能."""
        results = _registry.discover(q, top_k=limit)
        skill_infos = [
            manifest_to_skill_info(skill.manifest)
            for skill, _ in results
        ]
        return SearchResponse(
            query=q,
            results=skill_infos,
            total=len(skill_infos),
        )

    @app.get("/api/v1/health")
    async def health_check() -> HealthResponse:
        """健康检查."""
        components = []
        overall_score = 0.0
        count = 0

        # 注册中心
        reg_score = 1.0 if hasattr(_registry, "_skills") else 0.5
        components.append({"name": "registry", "status": "healthy" if reg_score >= 1 else "degraded", "score": reg_score})
        overall_score += reg_score
        count += 1

        final_score = overall_score / max(count, 1)
        status = "healthy" if final_score >= 0.8 else "degraded"

        return HealthResponse(
            status=status,
            score=round(final_score, 2),
            components=components,
        )

    return app
