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

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import uvicorn

# 导入 M5 核心
from main import create_app
from tide_memory.api.routes import MemoryAPIRouter
from tide_memory.api.m8_interface import M8Interface

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
    print("初始化 M5 潮汐记忆系统...")
    app_ctx = create_app()
    api_router = MemoryAPIRouter(app_ctx)
    m8_interface = M8Interface(app_ctx)

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

    print("✅ M5 潮汐记忆系统 FastAPI 服务已就绪")
    return app



def main():
    """主入口"""
    port = int(os.environ.get("M5_PORT", "8005"))
    app = create_fastapi_app()

    print("\n" + "=" * 60)
    print("  M5 潮汐记忆系统 - 启动完成")
    print("=" * 60)
    print(f"  服务地址: http://0.0.0.0:{port}")
    print(f"  健康检查: http://0.0.0.0:{port}/health")
    print(f"  API 文档: http://0.0.0.0:{port}/docs")
    print(f"  版本: v{M5_VERSION}")
    print(f"  密级: 高涉密 - 数据仅本地加密存储")
    print("=" * 60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
