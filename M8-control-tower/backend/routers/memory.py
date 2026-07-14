"""
M5 潮汐记忆 - 代理路由
M8 作为代理，将记忆相关请求转发到 M5
"""

import sys
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.module_client import get_module_registry
from ..schemas import ApiResponse
from ..auth import get_current_user

router = APIRouter()
registry = get_module_registry()


class RecallRequest(BaseModel):
    query: str
    domain: str = "private"
    agent_id: Optional[str] = None
    layer_range: Optional[List[str]] = None
    top_k: int = 10
    emotion_context: Optional[Dict[str, Any]] = None


class ArchiveRequest(BaseModel):
    content: str
    domain: str = "private"
    agent_id: Optional[str] = None
    tags: Optional[List[str]] = None
    emotion_tags: Optional[Dict[str, Any]] = None


@router.get("/health")
async def memory_health(current_user: dict = Depends(get_current_user)):
    """检查 M5 记忆系统健康状态"""
    try:
        m5_client = registry.get_client("m5")
        result = await m5_client.health_check()
        return ApiResponse.success(
            data={
                "status": "healthy" if result else "unhealthy",
                "module": "m5",
            }
        )
    except Exception as e:
        return ApiResponse.success(
            data={
                "status": "error",
                "module": "m5",
                "error": str(e),
            }
        )


@router.post("/recall")
async def memory_recall(
    req: RecallRequest, current_user: dict = Depends(get_current_user)
):
    """记忆检索 - 代理到 M5"""
    try:
        m5_client = registry.get_client("m5")

        # 检查 M5 是否健康
        is_healthy = await m5_client.health_check()
        if not is_healthy:
            raise HTTPException(status_code=503, detail="记忆系统不可用")

        # 转发请求到 M5
        result = await m5_client.post(
            "/api/v1/memory/recall",
            json_data={
                "query": req.query,
                "domain": req.domain,
                "agent_id": req.agent_id or current_user.get("username", "system"),
                "layer_range": req.layer_range,
                "top_k": req.top_k,
                "emotion_context": req.emotion_context,
            },
            use_auth=True,
        )

        return ApiResponse.success(data=result.get("data", result))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"记忆检索失败: {str(e)}")


@router.post("/archive")
async def memory_archive(
    req: ArchiveRequest, current_user: dict = Depends(get_current_user)
):
    """记忆归档 - 代理到 M5"""
    try:
        m5_client = registry.get_client("m5")

        # 检查 M5 是否健康
        is_healthy = await m5_client.health_check()
        if not is_healthy:
            raise HTTPException(status_code=503, detail="记忆系统不可用")

        # 转发请求到 M5
        result = await m5_client.post(
            "/api/v1/memory/archive",
            json_data={
                "content": req.content,
                "domain": req.domain,
                "agent_id": req.agent_id or current_user.get("username", "system"),
                "tags": req.tags,
                "emotion_tags": req.emotion_tags,
            },
            use_auth=True,
        )

        return ApiResponse.success(
            message="记忆归档成功", data=result.get("data", result)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"记忆归档失败: {str(e)}")


@router.get("/stats")
async def memory_stats(current_user: dict = Depends(get_current_user)):
    """获取记忆统计信息"""
    try:
        m5_client = registry.get_client("m5")
        is_healthy = await m5_client.health_check()

        if not is_healthy:
            return ApiResponse.success(
                data={
                    "total_memories": 0,
                    "layers": {},
                    "status": "unavailable",
                }
            )

        result = await m5_client.get(
            "/api/v1/memory/stats",
            use_auth=True,
        )

        return ApiResponse.success(data=result.get("data", result))
    except Exception as e:
        return ApiResponse.success(
            data={
                "total_memories": 0,
                "layers": {},
                "status": "error",
                "error": str(e),
            }
        )


@router.get("/layers")
async def memory_layers(current_user: dict = Depends(get_current_user)):
    """获取记忆层级信息"""
    try:
        m5_client = registry.get_client("m5")
        is_healthy = await m5_client.health_check()

        if not is_healthy:
            return ApiResponse.success(
                data={
                    "layers": [
                        {
                            "name": "L0 滩涂层",
                            "description": "短期工作记忆，秒级衰减",
                            "status": "unavailable",
                        },
                        {
                            "name": "L1 浅海层",
                            "description": "近期记忆，小时级存储",
                            "status": "unavailable",
                        },
                        {
                            "name": "L2 深海层",
                            "description": "长期记忆，天级存储",
                            "status": "unavailable",
                        },
                        {
                            "name": "L3 深渊层",
                            "description": "核心永久记忆，永不删除",
                            "status": "unavailable",
                        },
                    ]
                }
            )

        result = await m5_client.get(
            "/api/v1/memory/layers",
            use_auth=True,
        )

        return ApiResponse.success(data=result.get("data", result))
    except Exception as e:
        return ApiResponse.success(
            data={
                "layers": [],
                "error": str(e),
            }
        )
