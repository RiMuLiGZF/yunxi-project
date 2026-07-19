"""
知识库管理接口 - 云汐大脑知识层API
文档管理 + 检索测试 + 知识库统计
"""

import os
import sys
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.business.rag_knowledge import get_rag_knowledge_base
from shared.business.long_term_memory import get_long_term_memory
from shared.business.autonomous_learning import get_autonomous_learning_engine
from shared.business.personality_engine import get_personality_engine
from shared.business.skill_evolution import get_skill_evolution_engine
from shared.business.tool_system import get_tool_registry
from shared.business.agent_engine import get_agent_engine
from ...schemas import ApiResponse
from ...auth import get_current_user
from shared.core.observability import get_logger

logger = get_logger("brain_router_proxy")

router = APIRouter()

# 懒加载
_rag_kb = None
_ltm = None
_learning_engine = None
_personality_engine = None
_skill_evo_engine = None


def _get_rag():
    global _rag_kb
    if _rag_kb is None:
        try:
            _rag_kb = get_rag_knowledge_base()
        except Exception:
            _rag_kb = False
    return _rag_kb if _rag_kb else None


def _get_ltm():
    global _ltm
    if _ltm is None:
        try:
            _ltm = get_long_term_memory()
        except Exception:
            _ltm = False
    return _ltm if _ltm else None


def _get_learning_engine():
    global _learning_engine
    if _learning_engine is None:
        try:
            _learning_engine = get_autonomous_learning_engine()
        except Exception:
            _learning_engine = False
    return _learning_engine if _learning_engine else None


def _get_personality_engine():
    global _personality_engine
    if _personality_engine is None:
        try:
            _personality_engine = get_personality_engine()
        except Exception:
            _personality_engine = False
    return _personality_engine if _personality_engine else None


def _get_skill_evo_engine():
    global _skill_evo_engine
    if _skill_evo_engine is None:
        try:
            _skill_evo_engine = get_skill_evolution_engine()
        except Exception:
            _skill_evo_engine = False
    return _skill_evo_engine if _skill_evo_engine else None


# ==================== 请求模型 ====================

class AddDocumentRequest(BaseModel):
    title: str
    content: str
    category: str = "general"
    source: str = ""
    metadata: Optional[Dict[str, Any]] = None


class SearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    limit: int = 5


# ==================== 知识库管理 ====================

@router.get("/knowledge/stats")
async def knowledge_stats(current_user: dict = Depends(get_current_user)):
    """获取知识库统计"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")
    
    stats = rag.get_stats()
    return ApiResponse(code=0, message="ok", data=stats)


@router.get("/knowledge/documents")
async def list_documents(
    category: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """列出知识库文档"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")
    
    docs = rag.list_documents(category=category)
    doc_list = [d.to_dict() for d in docs]
    
    return ApiResponse(code=0, message="ok", data={
        "documents": doc_list,
        "total": len(doc_list),
    })


@router.post("/knowledge/documents")
async def add_document(
    req: AddDocumentRequest,
    current_user: dict = Depends(get_current_user),
):
    """添加文档到知识库"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")
    
    doc = rag.add_document(
        title=req.title,
        content=req.content,
        source=req.source,
        source_type="manual",
        category=req.category,
        metadata=req.metadata,
    )
    
    return ApiResponse(code=0, message="ok", data=doc.to_dict())


@router.post("/knowledge/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: str = "general",
    current_user: dict = Depends(get_current_user),
):
    """上传文件到知识库"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")
    
    # 保存临时文件
    import tempfile
    suffix = Path(file.filename).suffix if file.filename else ".txt"
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        doc = rag.add_file(
            file_path=tmp_path,
            category=category,
            title=file.filename,
        )
        
        if not doc:
            raise HTTPException(status_code=400, detail="文件处理失败")
        
        return ApiResponse(code=0, message="ok", data=doc.to_dict())
    finally:
        # 清理临时文件
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/knowledge/documents/{doc_id}")
async def get_document(doc_id: str, current_user: dict = Depends(get_current_user)):
    """获取文档详情"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")
    
    doc = rag.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    
    return ApiResponse(code=0, message="ok", data=doc.to_dict())


@router.delete("/knowledge/documents/{doc_id}")
async def delete_document(doc_id: str, current_user: dict = Depends(get_current_user)):
    """删除文档"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")
    
    success = rag.delete_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="文档不存在")
    
    return ApiResponse(code=0, message="删除成功")


@router.post("/knowledge/search")
async def search_knowledge(
    req: SearchRequest,
    current_user: dict = Depends(get_current_user),
):
    """检索知识库"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")
    
    results = rag.search(
        query=req.query,
        category=req.category,
        limit=req.limit,
    )
    
    result_list = []
    for r in results:
        result_list.append({
            "chunk_id": r.chunk.chunk_id,
            "doc_id": r.chunk.doc_id,
            "text": r.chunk.text,
            "score": round(r.score, 4),
            "rank": r.rank,
            "keywords": r.chunk.keywords,
        })
    
    return ApiResponse(code=0, message="ok", data={
        "results": result_list,
        "total": len(result_list),
        "query": req.query,
    })


# ==================== P3 增强：知识库高级 API ====================

class HybridSearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    top_k: int = 10
    enable_hybrid: Optional[bool] = None
    enable_rerank: Optional[bool] = None


class ChunkSearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    top_k: int = 10
    strategy: Optional[str] = None  # 混合检索策略


class QueryRewriteRequest(BaseModel):
    query: str
    strategy: str = "expansion"
    history: Optional[List[Dict[str, str]]] = None


class ChunkingTestRequest(BaseModel):
    text: str
    strategy: str = "fixed"
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None


class RetrievalConfigUpdate(BaseModel):
    config: Dict[str, Any]


@router.post("/knowledge/{doc_id}/reindex")
async def reindex_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    """重建指定文档的索引"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")

    result = rag.reindex(doc_id=doc_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return ApiResponse(code=0, message="重建索引完成", data=result)


@router.post("/knowledge/reindex")
async def reindex_all(
    current_user: dict = Depends(get_current_user),
):
    """重建全部知识库索引"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")

    result = rag.reindex(doc_id=None)
    return ApiResponse(code=0, message="重建索引完成", data=result)


@router.get("/knowledge/stats/detailed")
async def knowledge_detailed_stats(
    current_user: dict = Depends(get_current_user),
):
    """获取知识库详细统计（P3 增强）"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")

    if hasattr(rag, 'get_detailed_stats'):
        stats = rag.get_detailed_stats()
    else:
        stats = rag.get_stats()

    return ApiResponse(code=0, message="ok", data=stats)


@router.post("/knowledge/chunks/search")
async def search_chunks_hybrid(
    req: ChunkSearchRequest,
    current_user: dict = Depends(get_current_user),
):
    """混合检索测试接口（P3 增强）"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")

    # 使用混合检索
    if hasattr(rag, 'hybrid_search'):
        results = rag.hybrid_search(
            query=req.query,
            category=req.category,
            top_k=req.top_k,
        )
    else:
        results = rag.search(
            query=req.query,
            category=req.category,
            limit=req.top_k,
        )

    result_list = []
    for r in results:
        result_list.append({
            "chunk_id": r.chunk.chunk_id,
            "doc_id": r.chunk.doc_id,
            "text": r.chunk.text,
            "score": round(r.score, 4),
            "rank": r.rank,
            "keywords": r.chunk.keywords,
            "section": r.chunk.section,
        })

    return ApiResponse(code=0, message="ok", data={
        "results": result_list,
        "total": len(result_list),
        "query": req.query,
        "search_type": "hybrid" if hasattr(rag, 'hybrid_search') else "basic",
    })


@router.get("/knowledge/chunks/{chunk_id}")
async def get_chunk_detail(
    chunk_id: str,
    current_user: dict = Depends(get_current_user),
):
    """查看单个 chunk 详情（P3 增强）"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")

    if hasattr(rag, 'get_chunk_detail'):
        detail = rag.get_chunk_detail(chunk_id)
    else:
        # 降级模式：通过检索结果查找
        detail = None

    if not detail:
        raise HTTPException(status_code=404, detail="Chunk 不存在")

    return ApiResponse(code=0, message="ok", data=detail)


@router.get("/knowledge/chunks/{chunk_id}/context")
async def get_chunk_context(
    chunk_id: str,
    chars_before: int = 100,
    chars_after: int = 100,
    current_user: dict = Depends(get_current_user),
):
    """获取 chunk 的上下文扩展（P3 增强）"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")

    if hasattr(rag, 'get_context_expanded'):
        result = rag.get_context_expanded(chunk_id, chars_before, chars_after)
    else:
        result = None

    if not result:
        raise HTTPException(status_code=404, detail="Chunk 不存在")

    return ApiResponse(code=0, message="ok", data=result)


@router.post("/knowledge/chunk/test")
async def test_chunking(
    req: ChunkingTestRequest,
    current_user: dict = Depends(get_current_user),
):
    """分块策略测试接口（P3 增强）"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")

    if hasattr(rag, 'chunk_with_strategy'):
        chunks = rag.chunk_with_strategy(
            text=req.text,
            strategy=req.strategy,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
        )
    else:
        # 降级：使用内部分块方法
        chunks = [{"text": req.text, "chunk_id": "test_0000"}]

    return ApiResponse(code=0, message="ok", data={
        "strategy": req.strategy,
        "chunks": chunks,
        "total_chunks": len(chunks),
    })


@router.post("/query/rewrite")
async def rewrite_query(
    req: QueryRewriteRequest,
    current_user: dict = Depends(get_current_user),
):
    """查询改写测试接口（P3 增强）"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")

    if hasattr(rag, 'rewrite_query'):
        result = rag.rewrite_query(
            query=req.query,
            strategy=req.strategy,
            history=req.history,
        )
    else:
        result = {
            "original_query": req.query,
            "rewritten_queries": [req.query],
            "strategy": req.strategy,
            "enhanced": False,
        }

    return ApiResponse(code=0, message="ok", data=result)


@router.get("/retrieval/config")
async def get_retrieval_config(
    current_user: dict = Depends(get_current_user),
):
    """获取检索配置（P3 增强）"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")

    if hasattr(rag, 'get_retrieval_config'):
        config = rag.get_retrieval_config()
    else:
        config = {"enhanced": False}

    return ApiResponse(code=0, message="ok", data=config)


@router.put("/retrieval/config")
async def update_retrieval_config(
    req: RetrievalConfigUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新检索配置（动态生效，P3 增强）"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")

    if hasattr(rag, 'update_retrieval_config'):
        try:
            changed = rag.update_retrieval_config(req.config)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        changed = {}

    return ApiResponse(code=0, message="配置已更新", data={
        "changed": changed,
        "count": len(changed),
    })


@router.post("/knowledge/search/debug")
async def search_debug(
    req: SearchRequest,
    current_user: dict = Depends(get_current_user),
):
    """检索调试接口（P3 增强）- 返回各阶段详细信息"""
    rag = _get_rag()
    if not rag:
        raise HTTPException(status_code=500, detail="知识库服务不可用")

    if hasattr(rag, 'search_with_debug'):
        debug_info = rag.search_with_debug(
            query=req.query,
            category=req.category,
        )
    else:
        results = rag.search(query=req.query, category=req.category, limit=req.limit)
        debug_info = {
            "query": req.query,
            "enhanced": False,
            "results": [
                {"chunk_id": r.chunk.chunk_id, "score": r.score, "rank": r.rank}
                for r in results
            ],
        }

    return ApiResponse(code=0, message="ok", data=debug_info)


# ==================== 长期记忆管理 ====================

@router.get("/memory/stats")
async def memory_stats(current_user: dict = Depends(get_current_user)):
    """获取长期记忆统计"""
    ltm = _get_ltm()
    if not ltm:
        raise HTTPException(status_code=500, detail="记忆服务不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    stats = ltm.get_stats(user_id)
    
    return ApiResponse(code=0, message="ok", data=stats)


@router.get("/memory/forgetting")
async def memory_forgetting(current_user: dict = Depends(get_current_user)):
    """获取即将遗忘的记忆（复习提醒）"""
    ltm = _get_ltm()
    if not ltm:
        raise HTTPException(status_code=500, detail="记忆服务不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    fading = ltm.get_daily_forgetting(user_id)
    
    mem_list = [m.to_dict() for m in fading]
    return ApiResponse(code=0, message="ok", data={
        "fading_memories": mem_list,
        "count": len(mem_list),
    })


@router.post("/memory/search")
async def search_memory(
    req: SearchRequest,
    current_user: dict = Depends(get_current_user),
):
    """搜索长期记忆"""
    ltm = _get_ltm()
    if not ltm:
        raise HTTPException(status_code=500, detail="记忆服务不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    memories = ltm.search(
        user_id=user_id,
        query=req.query,
        limit=req.limit,
        sort_by="relevance",
    )
    
    mem_list = [m.to_dict() for m in memories]
    return ApiResponse(code=0, message="ok", data={
        "memories": mem_list,
        "total": len(mem_list),
    })


@router.post("/memory/{memory_id}/reinforce")
async def reinforce_memory(
    memory_id: str,
    current_user: dict = Depends(get_current_user),
):
    """强化记忆（复习）"""
    ltm = _get_ltm()
    if not ltm:
        raise HTTPException(status_code=500, detail="记忆服务不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    success = ltm.reinforce_memory(user_id, memory_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="记忆不存在")
    
    return ApiResponse(code=0, message="记忆已强化")


# ==================== 大脑总览 ====================

@router.get("/overview")
async def brain_overview(current_user: dict = Depends(get_current_user)):
    """云汐大脑总览 - 所有能力状态"""
    user_id = current_user.get("user_id", "default") if current_user else "default"
    
    overview = {
        "features": {
            "long_term_memory": False,
            "rag_knowledge": False,
            "cot_reasoning": True,  # 纯Python实现，总是可用
        },
        "memory_stats": None,
        "knowledge_stats": None,
    }
    
    # 长期记忆状态
    ltm = _get_ltm()
    if ltm:
        overview["features"]["long_term_memory"] = True
        overview["memory_stats"] = ltm.get_stats(user_id)
    
    # 知识库状态
    rag = _get_rag()
    if rag:
        overview["features"]["rag_knowledge"] = True
        overview["knowledge_stats"] = rag.get_stats()
    
    # 自我进化状态
    learning = _get_learning_engine()
    if learning:
        overview["features"]["autonomous_learning"] = True
        overview["learning_stats"] = learning.get_stats(user_id)
    
    personality = _get_personality_engine()
    if personality:
        overview["features"]["personality"] = True
        overview["personality_stats"] = personality.get_growth_stats(user_id)
    
    skill_evo = _get_skill_evo_engine()
    if skill_evo:
        overview["features"]["skill_evolution"] = True
        overview["features"]["agent_tools"] = True
        overview["features"]["multi_agent_team"] = True
        overview["skill_stats"] = skill_evo.get_growth_report(user_id)
    
    return ApiResponse(code=0, message="ok", data=overview)


# ==================== 自主学习 ====================

@router.get("/learning/stats")
async def learning_stats(current_user: dict = Depends(get_current_user)):
    """获取自主学习统计"""
    engine = _get_learning_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="学习引擎不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    stats = engine.get_stats(user_id)
    
    return ApiResponse(code=0, message="ok", data=stats)


@router.get("/learning/items")
async def learning_items(
    status: Optional[str] = None,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """获取学习条目列表"""
    engine = _get_learning_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="学习引擎不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    items = engine.get_items(user_id, status=status, limit=limit)
    
    return ApiResponse(code=0, message="ok", data={
        "items": [i.to_dict() for i in items],
        "total": len(items),
    })


@router.post("/learning/{item_id}/verify")
async def verify_learning_item(
    item_id: str,
    is_correct: bool = True,
    feedback: str = "",
    current_user: dict = Depends(get_current_user),
):
    """验证学习条目"""
    engine = _get_learning_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="学习引擎不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    success = engine.verify_item(user_id, item_id, is_correct, feedback)
    
    if not success:
        raise HTTPException(status_code=404, detail="学习条目不存在")
    
    return ApiResponse(code=0, message="验证完成")


@router.get("/learning/pending")
async def pending_review(
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """获取待审核的学习条目"""
    engine = _get_learning_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="学习引擎不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    items = engine.get_pending_review(user_id, limit=limit)
    
    return ApiResponse(code=0, message="ok", data={
        "items": [i.to_dict() for i in items],
        "total": len(items),
    })


# ==================== 人格成长 ====================

@router.get("/personality/profile")
async def personality_profile(current_user: dict = Depends(get_current_user)):
    """获取人格画像"""
    engine = _get_personality_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="人格引擎不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    profile = engine.generate_personality_description(user_id)
    
    return ApiResponse(code=0, message="ok", data=profile)


@router.get("/personality/growth")
async def personality_growth(current_user: dict = Depends(get_current_user)):
    """获取人格成长统计"""
    engine = _get_personality_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="人格引擎不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    stats = engine.get_growth_stats(user_id)
    
    return ApiResponse(code=0, message="ok", data=stats)


# ==================== 技能进化 ====================

@router.get("/skills/radar")
async def skill_radar(current_user: dict = Depends(get_current_user)):
    """获取能力雷达图数据"""
    engine = _get_skill_evo_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="技能进化引擎不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    radar = engine.get_skill_radar(user_id)
    
    return ApiResponse(code=0, message="ok", data=radar)


@router.get("/skills/growth")
async def skill_growth_report(current_user: dict = Depends(get_current_user)):
    """获取技能成长报告"""
    engine = _get_skill_evo_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="技能进化引擎不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    report = engine.get_growth_report(user_id)
    
    return ApiResponse(code=0, message="ok", data=report)


@router.get("/skills/plans")
async def skill_improvement_plans(
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """获取改进计划列表"""
    engine = _get_skill_evo_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="技能进化引擎不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    plans = engine.get_improvement_plans(user_id, status=status)
    
    return ApiResponse(code=0, message="ok", data={
        "plans": [p.to_dict() for p in plans],
        "total": len(plans),
    })


@router.post("/skills/plans/{plan_id}/progress")
async def update_plan_progress(
    plan_id: str,
    progress: float,
    current_user: dict = Depends(get_current_user),
):
    """更新改进计划进度"""
    engine = _get_skill_evo_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="技能进化引擎不可用")
    
    user_id = current_user.get("user_id", "default") if current_user else "default"
    success = engine.update_plan_progress(user_id, plan_id, progress)
    
    if not success:
        raise HTTPException(status_code=404, detail="计划不存在")
    
    return ApiResponse(code=0, message="进度已更新")


# ==================== Agent/工具/多Agent团队接口（代理模式）====================
#
# [V12.0] Agent/工具/多Agent团队接口已迁移至 M1-agent-hub
# M8 端保留代理路由，向后兼容。
#
# 代理配置：
#   BRAIN_AGENT_PROXY_MODE=proxy  (默认，转发到 M1)
#   BRAIN_AGENT_PROXY_MODE=local  (降级，使用本地实现)
#
# 接口清单（共 9 个，全部代理到 M1）：
# 工具系统（3 个）：
#   1. GET    /api/brain/tools/list
#   2. GET    /api/brain/tools/stats
#   3. POST   /api/brain/tools/call/{tool_name}
# 单 Agent（2 个）：
#   4. POST   /api/brain/agent/run
#   5. GET    /api/brain/agent/stats
# 多 Agent 团队（4 个）：
#   6. GET    /api/brain/team/profile
#   7. POST   /api/brain/team/query
#   8. GET    /api/brain/team/stats
#   9. GET    /api/brain/team/tasks

# ── 代理配置 ──────────────────────────────────────────

BRAIN_AGENT_PROXY_MODE = os.getenv("BRAIN_AGENT_PROXY_MODE", "proxy").lower()

# M1 服务地址
M1_BASE_URL = os.getenv("M1_BASE_URL", "http://localhost:8001")

# M1 Admin Token（用于 M8 -> M1 鉴权）
M1_ADMIN_TOKEN = os.getenv("M1_ADMIN_TOKEN", "yunxi-m1-admin-token-2026")

# 代理超时时间（秒）
BRAIN_AGENT_PROXY_TIMEOUT = float(os.getenv("BRAIN_AGENT_PROXY_TIMEOUT", "30.0"))

# HTTP 客户端（懒加载）
_brain_agent_client: Any = None


def _get_brain_agent_client() -> Any:
    """获取 HTTP 客户端（懒加载 httpx）"""
    global _brain_agent_client
    if _brain_agent_client is None:
        import httpx
        _brain_agent_client = httpx.AsyncClient(
            base_url=M1_BASE_URL,
            timeout=BRAIN_AGENT_PROXY_TIMEOUT,
            headers={
                "X-M8-Token": M1_ADMIN_TOKEN,
                "Content-Type": "application/json",
            },
        )
    return _brain_agent_client


async def _proxy_brain_agent_to_m1(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    代理 Brain Agent 请求到 M1 Agent Hub

    Args:
        method: HTTP 方法 (GET/POST/DELETE/PUT)
        path: 目标路径（含 /api/brain 前缀）
        params: 查询参数
        json_data: 请求体 JSON
        trace_id: 链路追踪 ID

    Returns:
        M1 返回的 JSON 数据（已解析为 dict）

    Raises:
        HTTPException: 代理失败时抛出
    """
    client = _get_brain_agent_client()
    headers = {}
    if trace_id:
        headers["X-Trace-Id"] = trace_id

    try:
        response = await client.request(
            method=method.upper(),
            url=path,
            params=params,
            json=json_data,
            headers=headers if headers else None,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        # 区分错误类型，提供友好提示
        error_msg = str(exc)
        if hasattr(exc, "response") and exc.response is not None:
            status_code = exc.response.status_code
            try:
                err_body = exc.response.json()
                detail = err_body.get("detail", err_body.get("message", error_msg))
            except Exception:
                detail = error_msg
            raise HTTPException(
                status_code=502,
                detail=f"M1 Brain Agent 返回错误 ({status_code}): {detail}",
            )
        else:
            raise HTTPException(
                status_code=502,
                detail=f"M1 Brain Agent 连接失败: {error_msg}",
            )


def _get_trace_id_from_request(request) -> Optional[str]:
    """从请求中提取 trace_id"""
    return request.headers.get("X-Trace-Id") or request.headers.get("x-trace-id")


# ── 请求模型（保留 Pydantic 校验，代理层仍然验证输入）──────────

class AgentRunRequest(BaseModel):
    query: str
    available_tools: Optional[List[str]] = None


class TeamQueryRequest(BaseModel):
    query: str


# ═══════════════════════════════════════════════════════
# 代理模式：9 个接口全部转发到 M1
# ═══════════════════════════════════════════════════════

if BRAIN_AGENT_PROXY_MODE == "proxy":
    logger.info("BRAIN_AGENT_PROXY_MODE=proxy，Agent/工具/团队接口代理到 M1")

    @router.get("/tools/list")
    async def list_tools(
        request: Request,
        category: Optional[str] = None,
        current_user: dict = Depends(get_current_user),
    ):
        """获取可用工具列表（代理到 M1）"""
        try:
            params = {}
            if category:
                params["category"] = category
            result = await _proxy_brain_agent_to_m1(
                method="GET",
                path="/api/brain/tools/list",
                params=params if params else None,
                trace_id=_get_trace_id_from_request(request),
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("list_tools_proxy_failed", error=str(exc))
            return ApiResponse.error(code=502, message=f"获取工具列表失败: {exc}")


    @router.get("/tools/stats")
    async def tool_stats(
        request: Request,
        current_user: dict = Depends(get_current_user),
    ):
        """获取工具调用统计（代理到 M1）"""
        try:
            result = await _proxy_brain_agent_to_m1(
                method="GET",
                path="/api/brain/tools/stats",
                trace_id=_get_trace_id_from_request(request),
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("tool_stats_proxy_failed", error=str(exc))
            return ApiResponse.error(code=502, message=f"获取工具统计失败: {exc}")


    @router.post("/tools/call/{tool_name}")
    async def call_tool(
        request: Request,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        current_user: dict = Depends(get_current_user),
    ):
        """调用指定工具（代理到 M1）"""
        try:
            result = await _proxy_brain_agent_to_m1(
                method="POST",
                path=f"/api/brain/tools/call/{tool_name}",
                json_data=params,
                trace_id=_get_trace_id_from_request(request),
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("call_tool_proxy_failed", tool_name=tool_name, error=str(exc))
            return ApiResponse.error(code=502, message=f"工具调用失败: {exc}")


    @router.post("/agent/run")
    async def agent_run(
        request: Request,
        req: AgentRunRequest,
        current_user: dict = Depends(get_current_user),
    ):
        """执行Agent任务（代理到 M1）"""
        try:
            result = await _proxy_brain_agent_to_m1(
                method="POST",
                path="/api/brain/agent/run",
                json_data=req.model_dump(),
                trace_id=_get_trace_id_from_request(request),
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("agent_run_proxy_failed", error=str(exc))
            return ApiResponse.error(code=502, message=f"Agent 执行失败: {exc}")


    @router.get("/agent/stats")
    async def agent_stats(
        request: Request,
        current_user: dict = Depends(get_current_user),
    ):
        """获取Agent统计信息（代理到 M1）"""
        try:
            result = await _proxy_brain_agent_to_m1(
                method="GET",
                path="/api/brain/agent/stats",
                trace_id=_get_trace_id_from_request(request),
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("agent_stats_proxy_failed", error=str(exc))
            return ApiResponse.error(code=502, message=f"获取 Agent 统计失败: {exc}")


    @router.get("/team/profile")
    async def team_profile(
        request: Request,
        current_user: dict = Depends(get_current_user),
    ):
        """获取Agent团队简介（代理到 M1）"""
        try:
            result = await _proxy_brain_agent_to_m1(
                method="GET",
                path="/api/brain/team/profile",
                trace_id=_get_trace_id_from_request(request),
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("team_profile_proxy_failed", error=str(exc))
            return ApiResponse.error(code=502, message=f"获取团队简介失败: {exc}")


    @router.post("/team/query")
    async def team_query(
        request: Request,
        req: TeamQueryRequest,
        current_user: dict = Depends(get_current_user),
    ):
        """团队协作处理查询（代理到 M1）"""
        try:
            result = await _proxy_brain_agent_to_m1(
                method="POST",
                path="/api/brain/team/query",
                json_data=req.model_dump(),
                trace_id=_get_trace_id_from_request(request),
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("team_query_proxy_failed", error=str(exc))
            return ApiResponse.error(code=502, message=f"团队查询失败: {exc}")


    @router.get("/team/stats")
    async def team_stats(
        request: Request,
        current_user: dict = Depends(get_current_user),
    ):
        """获取团队统计信息（代理到 M1）"""
        try:
            result = await _proxy_brain_agent_to_m1(
                method="GET",
                path="/api/brain/team/stats",
                trace_id=_get_trace_id_from_request(request),
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("team_stats_proxy_failed", error=str(exc))
            return ApiResponse.error(code=502, message=f"获取团队统计失败: {exc}")


    @router.get("/team/tasks")
    async def team_tasks(
        request: Request,
        limit: int = 20,
        current_user: dict = Depends(get_current_user),
    ):
        """获取团队任务历史（代理到 M1）"""
        try:
            params = {"limit": limit}
            result = await _proxy_brain_agent_to_m1(
                method="GET",
                path="/api/brain/team/tasks",
                params=params,
                trace_id=_get_trace_id_from_request(request),
            )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("team_tasks_proxy_failed", error=str(exc))
            return ApiResponse.error(code=502, message=f"获取团队任务失败: {exc}")


# ═══════════════════════════════════════════════════════
# 降级模式：本地实现（当 BRAIN_AGENT_PROXY_MODE=local 时启用）
# ═══════════════════════════════════════════════════════

else:
    logger.warning("BRAIN_AGENT_PROXY_MODE=local，使用本地 Agent/工具/团队实现（降级模式）")

    _agent_engine_cache = None
    _tool_registry_cache = None
    _agent_team_cache = None


    def _get_agent_engine_api():
        """获取Agent引擎（API用懒加载）"""
        global _agent_engine_cache
        if _agent_engine_cache is None:
            try:
                _agent_engine_cache = get_agent_engine()
            except Exception:
                _agent_engine_cache = False
        return _agent_engine_cache if _agent_engine_cache else None


    def _get_tool_registry_api():
        """获取工具注册表（API用懒加载）"""
        global _tool_registry_cache
        if _tool_registry_cache is None:
            try:
                # 确保内置工具已注册
                from shared.business.builtin_tools import _ensure_registered
                _ensure_registered()
                _tool_registry_cache = get_tool_registry()
            except Exception:
                _tool_registry_cache = False
        return _tool_registry_cache if _tool_registry_cache else None


    def _get_agent_team_api():
        """获取多Agent团队（API用懒加载）"""
        global _agent_team_cache
        if _agent_team_cache is None:
            try:
                from shared.business.agent_team import _ensure_team_registered
                _ensure_team_registered()
                from shared.business.multi_agent import get_agent_team
                _agent_team_cache = get_agent_team()
            except Exception:
                _agent_team_cache = False
        return _agent_team_cache if _agent_team_cache else None


    @router.get("/tools/list")
    async def list_tools(
        category: Optional[str] = None,
        current_user: dict = Depends(get_current_user),
    ):
        """获取可用工具列表"""
        registry = _get_tool_registry_api()
        if not registry:
            raise HTTPException(status_code=500, detail="工具系统不可用")

        tools = registry.list_tools(category=category)

        return ApiResponse(code=0, message="ok", data={
            "tools": [t.get_description_for_llm() for t in tools],
            "total": len(tools),
            "categories": list(set(t.category for t in tools)),
        })


    @router.get("/tools/stats")
    async def tool_stats(current_user: dict = Depends(get_current_user)):
        """获取工具调用统计"""
        registry = _get_tool_registry_api()
        if not registry:
            raise HTTPException(status_code=500, detail="工具系统不可用")

        stats = registry.get_stats()
        history = registry.get_call_history(limit=20)

        return ApiResponse(code=0, message="ok", data={
            "stats": stats,
            "recent_calls": history,
        })


    @router.post("/tools/call/{tool_name}")
    async def call_tool(
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        current_user: dict = Depends(get_current_user),
    ):
        """调用指定工具"""
        registry = _get_tool_registry_api()
        if not registry:
            raise HTTPException(status_code=500, detail="工具系统不可用")

        user_id = current_user.get("user_id", "default") if current_user else "default"
        context = {"user_id": user_id}

        result = registry.call_tool(tool_name, params or {}, context=context)

        return ApiResponse(code=0 if result.success else 1,
                           message="ok" if result.success else result.error or "调用失败",
                           data=result.to_dict())


    @router.post("/agent/run")
    async def agent_run(
        req: AgentRunRequest,
        current_user: dict = Depends(get_current_user),
    ):
        """执行Agent任务"""
        engine = _get_agent_engine_api()
        if not engine:
            raise HTTPException(status_code=500, detail="Agent引擎不可用")

        user_id = current_user.get("user_id", "default") if current_user else "default"
        context = {"user_id": user_id}

        result = engine.run(
            query=req.query,
            context=context,
            available_tools=req.available_tools,
        )

        return ApiResponse(code=0 if result.success else 1,
                           message="ok" if result.success else result.error or "执行失败",
                           data=result.to_dict())


    @router.get("/agent/stats")
    async def agent_stats(current_user: dict = Depends(get_current_user)):
        """获取Agent统计信息"""
        engine = _get_agent_engine_api()
        if not engine:
            raise HTTPException(status_code=500, detail="Agent引擎不可用")

        stats = engine.get_stats()
        history = engine.get_execution_history(limit=10)

        return ApiResponse(code=0, message="ok", data={
            "stats": stats,
            "recent_executions": history,
        })


    @router.get("/team/profile")
    async def team_profile(current_user: dict = Depends(get_current_user)):
        """获取Agent团队简介"""
        team = _get_agent_team_api()
        if not team:
            raise HTTPException(status_code=500, detail="Agent团队不可用")

        profile = team.get_team_profile()
        return ApiResponse(code=0, message="ok", data=profile)


    @router.post("/team/query")
    async def team_query(
        req: TeamQueryRequest,
        current_user: dict = Depends(get_current_user),
    ):
        """团队协作处理查询"""
        team = _get_agent_team_api()
        if not team:
            raise HTTPException(status_code=500, detail="Agent团队不可用")

        user_id = current_user.get("user_id", "default") if current_user else "default"
        context = {"user_id": user_id}

        result = team.handle_query(req.query, context=context)

        return ApiResponse(code=0 if result.success else 1,
                           message="ok" if result.success else result.error or "执行失败",
                           data=result.to_dict())


    @router.get("/team/stats")
    async def team_stats(current_user: dict = Depends(get_current_user)):
        """获取团队统计信息"""
        team = _get_agent_team_api()
        if not team:
            raise HTTPException(status_code=500, detail="Agent团队不可用")

        stats = team.get_stats()
        history = team.get_task_history(limit=20)

        return ApiResponse(code=0, message="ok", data={
            "stats": stats,
            "recent_tasks": history,
        })


    @router.get("/team/tasks")
    async def team_tasks(
        limit: int = 20,
        current_user: dict = Depends(get_current_user),
    ):
        """获取团队任务历史"""
        team = _get_agent_team_api()
        if not team:
            raise HTTPException(status_code=500, detail="Agent团队不可用")

        tasks = team.get_task_history(limit=limit)

        return ApiResponse(code=0, message="ok", data={
            "tasks": tasks,
            "total": len(tasks),
        })
