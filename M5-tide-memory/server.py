"""
M5 潮汐记忆系统 - FastAPI 服务入口
将 MemoryAPIRouter 包装为 FastAPI HTTP 服务
"""

import os
import sys
from pathlib import Path

# 确保 src 目录在路径中
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import structlog
from tide_memory.utils.logging_setup import setup_logging

# 初始化结构化日志系统（尽早初始化）
setup_logging()
logger = structlog.get_logger(__name__)

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import uvicorn

# 导入 M5 核心
from main import create_app
from tide_memory.api.routes import MemoryAPIRouter
from tide_memory.api.m8_interface import M8Interface

# 导入成长系统
from tide_memory.growth.router import GrowthAPIRouter

# 导入全局异常处理器和认证中间件
from tide_memory.middleware.exception_handler import register_exception_handlers
from tide_memory.middleware.auth import FastAPIAuthMiddleware
from tide_memory.middleware.rate_limit import RateLimitMiddleware
from tide_memory.middleware.circuit_breaker import CircuitBreakerMiddleware
from tide_memory.middleware.idempotency import IdempotencyMiddleware

# 导入版本号
from tide_memory import __version__ as M5_VERSION

# ============ Pydantic 模型 ============

class RecallRequest(BaseModel):
    query: str
    top_k: int = 10
    layers: List[str] = ["l1_shallow", "l2_deep"]
    domain: str = "private"
    agent_id: str = "unknown"
    emotion_context: Optional[Dict] = None

class ArchiveRequest(BaseModel):
    content: str
    domain: str = "private"
    agent_id: str = "system"
    tags: List[str] = []
    emotion_context: Optional[Dict] = None
    metadata: Dict[str, Any] = {}
    source: str = "conversation"

class ConsolidateRequest(BaseModel):
    mode: str = "normal"

class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    layers: List[str] = ["l1_shallow", "l2_deep"]
    domain: str = "private"
    agent_id: str = "unknown"
    emotion_context: Optional[Dict] = None

class BatchArchiveRequest(BaseModel):
    items: List[Dict[str, Any]]

class BatchDeleteRequest(BaseModel):
    memory_ids: List[str]

# ============ 创建应用 ============


def create_fastapi_app() -> FastAPI:
    """创建 FastAPI 应用并挂载 M5 路由"""

    # 初始化 M5 应用上下文
    logger.info("初始化 M5 潮汐记忆系统...")
    app_ctx = create_app()
    api_router = MemoryAPIRouter(app_ctx)
    m8_interface = M8Interface(app_ctx)

    # 初始化成长系统
    logger.info("初始化成长系统（成就/天赋/历法/编年史/记忆回响/赛季征程）...")
    growth_router = GrowthAPIRouter(app_ctx)
    logger.info("成长系统初始化完成")

    # 创建 FastAPI 应用
    app = FastAPI(
        title="M5 潮汐记忆系统 API",
        description=f"云汐系统 - 潮汐分层记忆系统 v{M5_VERSION}",
        version=M5_VERSION,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 幂等性中间件（通过 M5_IDEMPOTENCY_ENABLED 环境变量控制，默认开启）
    # 注意：FastAPI/Starlette 中间件为栈式结构，先注册的在外层（请求时先经过）
    # 此处按逆序注册，确保请求执行顺序为：认证 → 限流 → 熔断 → 幂等性
    app.add_middleware(IdempotencyMiddleware)
    logger.info(
        "idempotency_middleware_registered",
        idempotency_enabled=os.environ.get("M5_IDEMPOTENCY_ENABLED", "true").lower() in ("true", "1", "yes", "on"),
    )

    # 熔断中间件（监控全局错误率，通过 M5_CIRCUIT_BREAKER_ENABLED 控制，默认开启）
    app.add_middleware(CircuitBreakerMiddleware)
    circuit_breaker_enabled = os.environ.get("M5_CIRCUIT_BREAKER_ENABLED", "true").lower() in ("true", "1", "yes", "on")
    logger.info(
        "circuit_breaker_middleware_registered",
        circuit_breaker_enabled=circuit_breaker_enabled,
    )

    # 限流中间件（认证之后，幂等性之前；通过 M5_RATE_LIMIT_ENABLED 控制，默认开启）
    app.add_middleware(RateLimitMiddleware)
    rate_limit_enabled = os.environ.get("M5_RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes", "on")
    rate_limit_per_minute = int(os.environ.get("M5_RATE_LIMIT_PER_MINUTE", "100"))
    logger.info(
        "rate_limit_middleware_registered",
        rate_limit_enabled=rate_limit_enabled,
        rate_limit_per_minute=rate_limit_per_minute,
    )

    # 认证中间件（通过 M5_AUTH_ENABLED 环境变量控制，默认关闭）
    app.add_middleware(FastAPIAuthMiddleware)
    logger.info(
        "auth_middleware_registered",
        auth_enabled=os.environ.get("M5_AUTH_ENABLED", "false").lower() in ("true", "1", "yes", "on"),
    )

    # 注册全局异常处理器
    register_exception_handlers(app)

    # ============ V1 API 路由 ============

    @app.get("/health", summary="健康检查")
    async def health():
        result = api_router.health_check()
        return result

    @app.get("/api/v1/health", summary="V1 API 健康检查")
    async def api_health():
        result = api_router.health_check()
        return result

    @app.post("/api/v1/memory/recall", summary="记忆检索")
    async def memory_recall(req: RecallRequest):
        result = api_router.recall(req.dict())
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.post("/api/v1/memory/archive", summary="记忆归档")
    async def memory_archive(req: ArchiveRequest):
        result = api_router.archive(req.dict())
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.post("/api/v1/memory/store", summary="记忆存储（写入）")
    async def memory_store(req: ArchiveRequest):
        """记忆存储接口，与 archive 等价，提供更直观的命名"""
        result = api_router.archive(req.dict())
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/memory/stats", summary="记忆统计")
    async def memory_stats():
        result = api_router.get_stats()
        return result

    @app.get("/api/v1/memory/layers", summary="记忆层级信息")
    async def memory_layers():
        result = api_router.get_layers()
        return result

    @app.post("/api/v1/memory/consolidate", summary="触发记忆巩固")
    async def memory_consolidate(req: ConsolidateRequest):
        result = api_router.consolidate(req.dict())
        return result

    @app.post("/api/v1/memory/search", summary="高级搜索")
    async def memory_search(req: SearchRequest):
        result = api_router.search(req.dict())
        return result

    @app.post("/api/v1/memory/batch_archive", summary="批量写入记忆")
    async def memory_batch_archive(req: BatchArchiveRequest):
        """批量写入记忆"""
        result = api_router.batch_archive(req.dict())
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.delete("/api/v1/memory/batch_delete", summary="批量删除记忆")
    async def memory_batch_delete(req: BatchDeleteRequest):
        """批量删除记忆"""
        result = api_router.batch_delete(req.dict())
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/memory/list", summary="分页查询记忆列表")
    async def memory_list(
        page_size: int = 20,
        cursor: Optional[str] = None,
        domain: Optional[str] = None,
        sort_by: str = "created_at",
        order: str = "desc",
    ):
        """分页查询记忆列表（游标分页）"""
        result = api_router.list_memories({
            "page_size": page_size,
            "cursor": cursor,
            "domain": domain,
            "sort_by": sort_by,
            "order": order,
        })
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    # 注意：路径参数路由必须放在静态路径路由之后，避免抢先匹配
    @app.get("/api/v1/memory/{memory_id}", summary="获取单条记忆")
    async def get_memory(memory_id: str, domain: str = "private", agent_id: str = "unknown"):
        result = api_router.get_memory(memory_id, {"domain": domain, "agent_id": agent_id})
        if result.get("code") != 0:
            status_code = 404 if result.get("code") == 404 else 403
            raise HTTPException(status_code=status_code, detail=result.get("message", "error"))
        return result

    @app.delete("/api/v1/memory/{memory_id}", summary="删除记忆")
    async def delete_memory(memory_id: str, domain: str = "private", agent_id: str = "unknown"):
        result = api_router.delete_memory(memory_id, {"domain": domain, "agent_id": agent_id})
        if result.get("code") != 0:
            status_code = 404 if result.get("code") == 404 else 403
            raise HTTPException(status_code=status_code, detail=result.get("message", "error"))
        return result

    # ============ 成长系统 API 路由 ============

    @app.get("/api/v1/growth/achievements", summary="获取成就列表")
    async def growth_achievements(category: Optional[str] = None, status: Optional[str] = None):
        result = growth_router.list_achievements({"category": category, "status": status})
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/growth/achievements/stats", summary="获取成就统计")
    async def growth_achievement_stats():
        result = growth_router.get_achievement_stats()
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.post("/api/v1/growth/achievements/{achievement_id}/unlock", summary="解锁成就")
    async def growth_unlock_achievement(achievement_id: str):
        result = growth_router.unlock_achievement(achievement_id)
        if result.get("code") != 0:
            raise HTTPException(status_code=400, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/growth/talents", summary="获取天赋树")
    async def growth_talents(tree: Optional[str] = None):
        result = growth_router.get_talent_tree({"tree": tree})
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.post("/api/v1/growth/talents/{nodeId}/upgrade", summary="升级天赋节点")
    async def growth_upgrade_talent(nodeId: str):
        result = growth_router.upgrade_talent(nodeId)
        if result.get("code") != 0:
            raise HTTPException(status_code=400, detail=result.get("message", "error"))
        return result

    @app.post("/api/v1/growth/talents/reset", summary="重置天赋树")
    async def growth_reset_talents():
        result = growth_router.reset_talents()
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/growth/talents/points", summary="获取可用天赋点数")
    async def growth_talent_points():
        result = growth_router.get_talent_points()
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/growth/talents/stats", summary="获取天赋统计")
    async def growth_talent_stats():
        result = growth_router.get_talent_stats()
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/growth/calendar/{year}/{month}", summary="获取指定年月日历")
    async def growth_calendar_month(year: int, month: int):
        result = growth_router.get_month_calendar(str(year), str(month))
        if result.get("code") != 0:
            raise HTTPException(status_code=400, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/growth/calendar/day/{date}", summary="获取指定日期数据")
    async def growth_calendar_day(date: str):
        result = growth_router.get_day_data(date)
        if result.get("code") != 0:
            raise HTTPException(status_code=400, detail=result.get("message", "error"))
        return result

    class CheckinRequest(BaseModel):
        date: Optional[str] = None
        mood: int = 7
        energy: int = 7
        summary: str = ""
        tags: List[str] = []

    @app.post("/api/v1/growth/calendar/checkin", summary="打卡")
    async def growth_calendar_checkin(req: CheckinRequest):
        result = growth_router.checkin(req.dict())
        if result.get("code") != 0:
            raise HTTPException(status_code=400, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/growth/calendar/stats", summary="获取日历统计")
    async def growth_calendar_stats():
        result = growth_router.get_calendar_stats()
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    # ============ 编年史 API ============

    @app.get("/api/v1/growth/chronicle", summary="分页查询纪事列表")
    async def growth_chronicle_list(
        page: int = 1,
        size: int = 20,
        category: Optional[str] = None,
        year: Optional[str] = None,
    ):
        result = growth_router.list_chronicles({
            "page": page, "size": size, "category": category, "year": year
        })
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/growth/chronicle/{chronicle_id}", summary="获取单条纪事详情")
    async def growth_chronicle_get(chronicle_id: str):
        result = growth_router.get_chronicle(chronicle_id)
        if result.get("code") != 0:
            status_code = 404 if result.get("code") == 404 else 500
            raise HTTPException(status_code=status_code, detail=result.get("message", "error"))
        return result

    class ChronicleCreateRequest(BaseModel):
        date: str
        title: str
        category: str = "main-quest"
        category_text: str = "主线任务"
        difficulty: str = "普通"
        content: str = ""
        tags: List[str] = []
        has_git: bool = False
        git_commits: List[Dict[str, Any]] = []

    @app.post("/api/v1/growth/chronicle", summary="创建纪事")
    async def growth_chronicle_create(req: ChronicleCreateRequest):
        result = growth_router.create_chronicle(req.dict())
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    class ChronicleUpdateRequest(BaseModel):
        date: Optional[str] = None
        title: Optional[str] = None
        category: Optional[str] = None
        category_text: Optional[str] = None
        difficulty: Optional[str] = None
        content: Optional[str] = None
        tags: Optional[List[str]] = None
        has_git: Optional[bool] = None
        git_commits: Optional[List[Dict[str, Any]]] = None

    @app.put("/api/v1/growth/chronicle/{chronicle_id}", summary="更新纪事")
    async def growth_chronicle_update(chronicle_id: str, req: ChronicleUpdateRequest):
        result = growth_router.update_chronicle(chronicle_id, req.dict(exclude_none=True))
        if result.get("code") != 0:
            status_code = 404 if result.get("code") == 404 else 500
            raise HTTPException(status_code=status_code, detail=result.get("message", "error"))
        return result

    @app.delete("/api/v1/growth/chronicle/{chronicle_id}", summary="删除纪事")
    async def growth_chronicle_delete(chronicle_id: str):
        result = growth_router.delete_chronicle(chronicle_id)
        if result.get("code") != 0:
            status_code = 404 if result.get("code") == 404 else 500
            raise HTTPException(status_code=status_code, detail=result.get("message", "error"))
        return result

    # ============ 记忆回响 API ============

    @app.get("/api/v1/growth/memories", summary="分页查询记忆回响列表")
    async def growth_memories_list(
        page: int = 1,
        size: int = 20,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
    ):
        result = growth_router.list_echoes({
            "page": page, "size": size, "category": category, "keyword": keyword
        })
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/growth/memories/{echo_id}", summary="获取单条回响详情")
    async def growth_memories_get(echo_id: str):
        result = growth_router.get_echo(echo_id)
        if result.get("code") != 0:
            status_code = 404 if result.get("code") == 404 else 500
            raise HTTPException(status_code=status_code, detail=result.get("message", "error"))
        return result

    class EchoGenerateRequest(BaseModel):
        type: str = "growth"
        memory_id: Optional[str] = None
        before: Optional[Dict[str, Any]] = None
        after: Optional[Dict[str, Any]] = None

    @app.post("/api/v1/growth/memories/generate", summary="生成记忆回响")
    async def growth_memories_generate(req: EchoGenerateRequest):
        result = growth_router.generate_echo(req.dict())
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.delete("/api/v1/growth/memories/{echo_id}", summary="删除回响")
    async def growth_memories_delete(echo_id: str):
        result = growth_router.delete_echo(echo_id)
        if result.get("code") != 0:
            status_code = 404 if result.get("code") == 404 else 500
            raise HTTPException(status_code=status_code, detail=result.get("message", "error"))
        return result

    # ============ 赛季征程 API ============

    @app.get("/api/v1/growth/season/current", summary="获取当前赛季详情")
    async def growth_season_current():
        result = growth_router.get_current_season()
        if result.get("code") != 0:
            status_code = 404 if result.get("code") == 404 else 500
            raise HTTPException(status_code=status_code, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/growth/season/history", summary="历史赛季列表")
    async def growth_season_history():
        result = growth_router.get_season_history()
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.get("/api/v1/growth/season/tasks", summary="任务列表")
    async def growth_season_tasks(
        type: Optional[str] = None,
        phase_id: Optional[str] = None,
        season_id: Optional[str] = None,
        status: Optional[str] = None,
    ):
        result = growth_router.list_season_tasks({
            "type": type, "phase_id": phase_id,
            "season_id": season_id, "status": status,
        })
        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "error"))
        return result

    @app.post("/api/v1/growth/season/tasks/{task_id}/complete", summary="完成任务")
    async def growth_season_task_complete(task_id: str):
        result = growth_router.complete_season_task(task_id)
        if result.get("code") != 0:
            status_code = 404 if result.get("code") == 404 else 500
            raise HTTPException(status_code=status_code, detail=result.get("message", "error"))
        return result

    @app.post("/api/v1/growth/season/tasks/{task_id_or_phase_id}/claim", summary="领取奖励")
    async def growth_season_task_claim(task_id_or_phase_id: str):
        result = growth_router.claim_season_reward(task_id_or_phase_id)
        if result.get("code") != 0:
            status_code = 404 if result.get("code") == 404 else 400
            raise HTTPException(status_code=status_code, detail=result.get("message", "error"))
        return result

    # ============ M8 标准接口路由（委托给 M8Interface） ============

    @app.get("/m8/health", summary="M8 标准健康检查")
    async def m8_health():
        return m8_interface.m8_health_check()

    @app.get("/m8/metrics", summary="M8 标准性能指标")
    async def m8_metrics(x_m8_token: str = Header(default="")):
        return m8_interface.m8_metrics()

    @app.get("/m8/config", summary="M8 标准配置查询")
    async def m8_config(x_m8_token: str = Header(default="")):
        return m8_interface.m8_config()

    @app.post("/m8/memory/recall", summary="M8 标准记忆检索")
    async def m8_memory_recall(req: RecallRequest):
        """M8标准记忆检索接口"""
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

    @app.post("/m8/memory/archive", summary="M8 标准记忆归档")
    async def m8_memory_archive(req: ArchiveRequest):
        """M8标准记忆归档接口"""
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

    @app.get("/m8/memory/stats", summary="M8 标准记忆统计")
    async def m8_memory_stats():
        """M8标准记忆统计接口"""
        return m8_interface.m8_get_stats()

    logger.info("M5 潮汐记忆系统 FastAPI 服务已就绪")
    return app



def main():
    """主入口"""
    port = int(os.environ.get("M5_PORT", "8005"))
    app = create_fastapi_app()

    auth_enabled = os.environ.get("M5_AUTH_ENABLED", "false").lower() in ("true", "1", "yes", "on")
    rate_limit_enabled = os.environ.get("M5_RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes", "on")
    circuit_breaker_enabled = os.environ.get("M5_CIRCUIT_BREAKER_ENABLED", "true").lower() in ("true", "1", "yes", "on")
    logger.info(
        "M5 潮汐记忆系统 - 启动完成",
        service_url=f"http://0.0.0.0:{port}",
        health_check=f"http://0.0.0.0:{port}/health",
        api_docs=f"http://0.0.0.0:{port}/docs",
        version=f"v{M5_VERSION}",
        auth_enabled=auth_enabled,
        rate_limit_enabled=rate_limit_enabled,
        rate_limit_per_minute=int(os.environ.get("M5_RATE_LIMIT_PER_MINUTE", "100")),
        circuit_breaker_enabled=circuit_breaker_enabled,
        classification="高涉密 - 数据仅本地加密存储",
    )

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
