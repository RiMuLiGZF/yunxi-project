"""
云汐 M9 数据水晶 - 管道管理 API

P3 优化：数据采集管道 + 连接器生态
提供管道的 CRUD、执行、历史记录、取消等接口
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from pipelines.manager import get_pipeline_manager, PipelineStatus

router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])


# ============================================================
# 请求/响应模型
# ============================================================

class PipelineCreateRequest(BaseModel):
    name: str
    description: str = ""
    source_connector_id: Optional[str] = None
    target_connector_id: Optional[str] = None
    stages: List[Dict[str, Any]] = Field(default_factory=list)
    schedule_type: str = "manual"
    schedule_config: Dict[str, Any] = Field(default_factory=dict)


class PipelineUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    source_connector_id: Optional[str] = None
    target_connector_id: Optional[str] = None
    stages: Optional[List[Dict[str, Any]]] = None
    schedule_type: Optional[str] = None
    schedule_config: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None


class PipelineRunRequest(BaseModel):
    trigger_type: str = "manual"
    params: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# 阶段类型列表
# ============================================================

@router.get("/stage-types", summary="获取可用阶段类型")
async def get_stage_types():
    """获取所有可用的管道阶段类型"""
    try:
        from pipelines.base import StageRegistry
        types = []
        for name in StageRegistry.list_all():
            stage_class = StageRegistry.get(name)
            if stage_class:
                types.append({
                    "name": name,
                    "description": getattr(stage_class, "description", ""),
                })
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "types": types,
                "total": len(types),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 管道 CRUD
# ============================================================

@router.get("", summary="管道列表")
async def list_pipelines():
    """获取所有管道定义列表"""
    try:
        mgr = get_pipeline_manager()
        pipelines = mgr.list_pipelines()
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "pipelines": pipelines,
                "total": len(pipelines),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", summary="创建管道")
async def create_pipeline(request: PipelineCreateRequest):
    """创建新的数据管道"""
    try:
        mgr = get_pipeline_manager()
        pipeline_id = mgr.create_pipeline(
            name=request.name,
            stages=request.stages,
            description=request.description,
            source_connector_id=request.source_connector_id,
            target_connector_id=request.target_connector_id,
            schedule_type=request.schedule_type,
            schedule_config=request.schedule_config,
        )

        pipeline = mgr.get_pipeline(pipeline_id)
        return {
            "code": 0,
            "message": "ok",
            "data": pipeline.to_dict()
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pipeline_id}", summary="管道详情")
async def get_pipeline(pipeline_id: str):
    """获取管道详细信息"""
    try:
        mgr = get_pipeline_manager()
        pipeline = mgr.get_pipeline(pipeline_id)
        return {
            "code": 0,
            "message": "ok",
            "data": pipeline.to_dict()
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"管道不存在: {pipeline_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{pipeline_id}", summary="更新管道")
async def update_pipeline(pipeline_id: str, request: PipelineUpdateRequest):
    """更新管道配置"""
    try:
        mgr = get_pipeline_manager()
        updated = mgr.update_pipeline(
            pipeline_id,
            name=request.name,
            description=request.description,
            source_connector_id=request.source_connector_id,
            target_connector_id=request.target_connector_id,
            stages=request.stages,
            schedule_type=request.schedule_type,
            schedule_config=request.schedule_config,
            is_enabled=request.is_enabled,
        )

        pipeline = mgr.get_pipeline(pipeline_id)
        return {
            "code": 0,
            "message": "ok",
            "data": pipeline.to_dict()
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"管道不存在: {pipeline_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{pipeline_id}", summary="删除管道")
async def delete_pipeline(pipeline_id: str):
    """删除管道"""
    try:
        mgr = get_pipeline_manager()
        deleted = mgr.delete_pipeline(pipeline_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"管道不存在: {pipeline_id}")

        return {
            "code": 0,
            "message": "ok",
            "data": {"deleted": True}
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 管道执行
# ============================================================

@router.post("/{pipeline_id}/run", summary="同步执行管道")
async def run_pipeline(pipeline_id: str, request: PipelineRunRequest):
    """同步执行管道，等待执行完成后返回结果"""
    try:
        mgr = get_pipeline_manager()
        run_record = mgr.run_pipeline(
            pipeline_id,
            trigger_type=request.trigger_type,
            params=request.params,
        )

        return {
            "code": 0,
            "message": "ok",
            "data": run_record.to_dict()
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"管道不存在: {pipeline_id}")
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pipeline_id}/run/async", summary="异步执行管道")
async def run_pipeline_async(pipeline_id: str, request: PipelineRunRequest):
    """异步执行管道，立即返回运行 ID"""
    try:
        mgr = get_pipeline_manager()
        # 验证管道存在
        mgr.get_pipeline(pipeline_id)

        run_id = mgr.run_pipeline_async(
            pipeline_id,
            trigger_type=request.trigger_type,
            params=request.params,
        )

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "run_id": run_id,
                "status": "pending",
            }
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"管道不存在: {pipeline_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 运行历史
# ============================================================

@router.get("/{pipeline_id}/runs", summary="管道执行历史")
async def list_pipeline_runs(
    pipeline_id: str,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """获取指定管道的执行历史记录"""
    try:
        mgr = get_pipeline_manager()
        # 验证管道存在
        mgr.get_pipeline(pipeline_id)

        runs = mgr.list_runs(
            pipeline_id=pipeline_id,
            status=status,
            limit=limit,
            offset=offset,
        )

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "runs": runs,
                "total": len(runs),
                "limit": limit,
                "offset": offset,
            }
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"管道不存在: {pipeline_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}", summary="执行详情")
async def get_run_detail(run_id: str):
    """获取指定运行的详细信息"""
    try:
        mgr = get_pipeline_manager()
        run = mgr.get_run(run_id)
        return {
            "code": 0,
            "message": "ok",
            "data": run.to_dict()
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"运行记录不存在: {run_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/runs/{run_id}/cancel", summary="取消执行")
async def cancel_run(run_id: str):
    """取消正在运行的管道"""
    try:
        mgr = get_pipeline_manager()
        cancelled = mgr.cancel_run(run_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail=f"运行记录不存在: {run_id}")

        return {
            "code": 0,
            "message": "ok",
            "data": {"cancelled": True}
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 统计信息
# ============================================================

@router.get("/stats/summary", summary="管道统计摘要")
async def get_pipelines_stats():
    """获取管道管理器统计信息"""
    try:
        mgr = get_pipeline_manager()
        stats = mgr.get_stats()
        return {
            "code": 0,
            "message": "ok",
            "data": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
