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
from ..schemas import ApiResponse
from ..auth import get_current_user

router = APIRouter()

# 懒加载
_rag_kb = None
_ltm = None


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
    
    return ApiResponse(code=0, message="ok", data=overview)
