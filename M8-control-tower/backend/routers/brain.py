"""
知识库管理接口 - 云汐大脑知识层API
文档管理 + 检索测试 + 知识库统计
"""

import os
import sys
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.rag_knowledge import get_rag_knowledge_base
from shared.long_term_memory import get_long_term_memory
from shared.autonomous_learning import get_autonomous_learning_engine
from shared.personality_engine import get_personality_engine
from shared.skill_evolution import get_skill_evolution_engine
from shared.tool_system import get_tool_registry
from shared.agent_engine import get_agent_engine
from ..schemas import ApiResponse
from ..auth import get_current_user

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


# ==================== Agent工具接口 ====================

_agent_engine_cache = None
_tool_registry_cache = None


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
            from shared.builtin_tools import _ensure_registered
            _ensure_registered()
            _tool_registry_cache = get_tool_registry()
        except Exception:
            _tool_registry_cache = False
    return _tool_registry_cache if _tool_registry_cache else None


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


class AgentRunRequest(BaseModel):
    query: str
    available_tools: Optional[List[str]] = None


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
