"""
任务管理路由 - 数据库持久化版本
支持任务提交、查询、列表、取消等操作
"""

import sys
import uuid
import json
import asyncio
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.business.module_client import get_module_registry
from shared.business.llm_client import LLMClient
from ..schemas import ApiResponse
from ..auth import get_current_user
from ..models import get_db, TaskRecord, SessionLocal

router = APIRouter()
registry = get_module_registry()
llm = LLMClient()


class SubmitTaskRequest(BaseModel):
    title: str
    input: str = ""
    description: Optional[str] = ""
    module: str = "m1"
    priority: str = "normal"
    agent_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


def _task_to_dict(task: TaskRecord) -> dict:
    """将数据库任务记录转为字典"""
    return {
        "id": str(task.id),
        "task_id": task.task_id,
        "title": task.title,
        "input": task.input_data or "",
        "description": task.input_data or "",
        "status": task.status,
        "priority": "normal",
        "module": task.module,
        "module_key": task.module,
        "agent_id": None,
        "progress": 100 if task.status == "completed" else (50 if task.status == "running" else 0),
        "result": task.output_data,
        "output_data": task.output_data,
        "error_message": task.error_msg,
        "error_msg": task.error_msg,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


async def _execute_task_async(task_db_id: int, title: str, input_text: str, module: str = "m1"):
    """后台异步执行任务"""
    try:
        db = SessionLocal()
        task = db.query(TaskRecord).filter(TaskRecord.id == task_db_id).first()
        if not task:
            db.close()
            return
        
        # 更新状态为运行中
        task.status = "running"
        db.commit()
        
        # 尝试调用 M1
        result_text = ""
        try:
            m1_client = registry.get_client("m1")
            is_running = await m1_client.health_check()
            if is_running:
                m1_response = await m1_client.post(
                    "/api/v1/chat",
                    json_data={
                        "user_input": input_text or title,
                        "stream": False,
                        "task_id": task.task_id,
                    },
                    use_auth=False,
                )
                result_text = json.dumps(m1_response, ensure_ascii=False, indent=2)
            else:
                # M1 不可用，尝试本地 LLM
                try:
                    llm_reply = await llm.chat([{"role": "user", "content": input_text or title}])
                    result_text = llm_reply
                except Exception as llm_err:
                    result_text = f"任务已接收（执行服务暂不可用）"
        except Exception as e:
            try:
                llm_reply = await llm.chat([{"role": "user", "content": input_text or title}])
                result_text = llm_reply
            except Exception as llm_err:
                result_text = f"任务已接收（执行服务暂不可用）"
        
        # 更新任务状态为完成
        task.status = "completed"
        task.output_data = result_text
        task.completed_at = datetime.utcnow()
        db.commit()
        db.close()
        
    except Exception as e:
        try:
            db = SessionLocal()
            task = db.query(TaskRecord).filter(TaskRecord.id == task_db_id).first()
            if task:
                task.status = "failed"
                task.error_msg = str(e)
                task.completed_at = datetime.utcnow()
                db.commit()
            db.close()
        except Exception:
            pass


@router.post("/submit")
async def submit_task(
    req: SubmitTaskRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交任务（持久化到数据库）"""
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    
    input_text = req.input or req.description or ""
    
    # 创建数据库记录
    db_task = TaskRecord(
        task_id=task_id,
        title=req.title,
        status="pending",
        module=req.module or "m1",
        input_data=input_text,
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    
    # 启动后台异步执行
    asyncio.create_task(_execute_task_async(
        task_db_id=db_task.id,
        title=req.title,
        input_text=input_text,
        module=req.module or "m1",
    ))
    
    return ApiResponse.success(
        message="任务已提交",
        data=_task_to_dict(db_task),
    )


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取任务详情"""
    # 先按 task_id 查，再按 id 查
    task = db.query(TaskRecord).filter(TaskRecord.task_id == task_id).first()
    if not task:
        try:
            task = db.query(TaskRecord).filter(TaskRecord.id == int(task_id)).first()
        except (ValueError, TypeError):
            pass
    
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    
    return ApiResponse.success(data=_task_to_dict(task))


@router.get("/")
async def list_tasks(
    status: Optional[str] = None,
    module_key: Optional[str] = None,
    module: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取任务列表"""
    query = db.query(TaskRecord)
    
    if status:
        query = query.filter(TaskRecord.status == status)
    if module_key:
        query = query.filter(TaskRecord.module == module_key)
    elif module:
        query = query.filter(TaskRecord.module == module)
    
    total = query.count()
    tasks = query.order_by(TaskRecord.created_at.desc()).offset(offset).limit(limit).all()
    
    items = [_task_to_dict(t) for t in tasks]
    
    return ApiResponse.success(data={
        "total": total,
        "items": items,
    })


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取消任务"""
    task = db.query(TaskRecord).filter(TaskRecord.task_id == task_id).first()
    if not task:
        try:
            task = db.query(TaskRecord).filter(TaskRecord.id == int(task_id)).first()
        except (ValueError, TypeError):
            pass
    
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    
    if task.status in ["completed", "failed", "cancelled"]:
        return ApiResponse.error(
            message=f"任务状态为 {task.status}，无法取消",
            code=400,
        )
    
    task.status = "failed"  # 用 failed 代替 cancelled（数据库字段限制）
    task.error_msg = "用户取消"
    task.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    
    return ApiResponse.success(
        message="任务已取消",
        data=_task_to_dict(task),
    )


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除任务"""
    task = db.query(TaskRecord).filter(TaskRecord.task_id == task_id).first()
    if not task:
        try:
            task = db.query(TaskRecord).filter(TaskRecord.id == int(task_id)).first()
        except (ValueError, TypeError):
            pass
    
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    
    db.delete(task)
    db.commit()
    
    return ApiResponse.success(message="任务已删除")
