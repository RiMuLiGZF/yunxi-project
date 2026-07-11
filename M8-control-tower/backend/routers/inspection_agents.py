"""
巡检Agent路由 - 启动检查与主理人调度Agent API

提供以下接口：
- GET /api/inspection/startup-check - 触发启动快速检查
- GET /api/inspection/startup-check/result - 获取最近检查结果
- POST /api/inspection/principal/chat - 与主理人调度Agent对话
- GET /api/inspection/principal/models - 获取可用模型列表
- POST /api/inspection/principal/route - 手动路由测试
"""

import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field

# 导入上级模块
from ..schemas import ApiResponse
from ..auth import get_current_user
from ..agents import get_startup_check_agent, get_principal_scheduler_agent

router = APIRouter()

# Agent 单例
startup_agent = get_startup_check_agent()
principal_agent = get_principal_scheduler_agent()


# ═══════════════════════════════════════════════════════
# 请求 / 响应 模型
# ═══════════════════════════════════════════════════════

class StartupCheckTriggerRequest(BaseModel):
    """启动检查触发请求"""
    triggered_by: str = Field("manual", description="触发方式: system/manual")


class PrincipalChatRequest(BaseModel):
    """主理人对话请求"""
    message: str = Field(..., description="用户消息", min_length=1)
    session_id: Optional[str] = Field(None, description="会话ID（用于多轮对话）")
    preference: str = Field("balanced", description="模型偏好: speed/quality/cost/balanced")
    system_prompt: Optional[str] = Field(None, description="自定义系统提示词")


class PrincipalRouteTestRequest(BaseModel):
    """手动路由测试请求"""
    message: str = Field(..., description="测试消息", min_length=1)
    model_key: Optional[str] = Field(None, description="指定模型key（可选）")
    preference: str = Field("balanced", description="模型偏好: speed/quality/cost/balanced")


# ═══════════════════════════════════════════════════════
# 启动快速检查接口
# ═══════════════════════════════════════════════════════

@router.get("/startup-check")
async def trigger_startup_check(
    triggered_by: str = Query("manual", description="触发方式: system/manual"),
    current_user: dict = Depends(get_current_user),
):
    """
    触发启动快速检查

    执行系统启动时的快速健康巡检，包括：
    - 数据库连接状态
    - 八大模块（M1-M8）健康检查
    - Ollama大模型服务状态
    - 算力调度平台状态
    - 磁盘空间/内存等基础资源
    - 配置文件完整性
    """
    try:
        result = await startup_agent.run_check(triggered_by=triggered_by)
        return ApiResponse.success(
            data=result.to_dict(),
            message="启动快速检查完成",
        )
    except Exception as exc:
        return ApiResponse.error(
            code=500,
            message=f"启动快速检查失败: {exc}",
        )


@router.get("/startup-check/result")
async def get_startup_check_result(
    current_user: dict = Depends(get_current_user),
):
    """
    获取最近一次启动检查结果
    """
    try:
        result = startup_agent.get_last_result()
        if result is None:
            return ApiResponse.success(
                data=None,
                message="暂无检查记录，请先触发检查",
            )
        return ApiResponse.success(
            data=result.to_dict(),
            message="获取成功",
        )
    except Exception as exc:
        return ApiResponse.error(
            code=500,
            message=f"获取检查结果失败: {exc}",
        )


@router.get("/startup-check/history")
async def get_startup_check_history(
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    current_user: dict = Depends(get_current_user),
):
    """
    获取启动检查历史记录
    """
    try:
        from ..models import SessionLocal, StartupCheckRecord

        db = SessionLocal()
        records = (
            db.query(StartupCheckRecord)
            .order_by(StartupCheckRecord.id.desc())
            .limit(limit)
            .all()
        )
        db.close()

        items = [r.to_dict() for r in records]
        return ApiResponse.success(
            data={
                "total": len(items),
                "items": items,
            },
            message="获取成功",
        )
    except Exception as exc:
        return ApiResponse.error(
            code=500,
            message=f"获取历史记录失败: {exc}",
        )


# ═══════════════════════════════════════════════════════
# 主理人调度Agent接口
# ═══════════════════════════════════════════════════════

@router.post("/principal/chat")
async def principal_chat(
    req: PrincipalChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    与主理人调度Agent对话

    主理人调度Agent会智能选择最合适的大模型来回答您的问题。
    支持代码生成、分析、对话、创意写作等多种场景。
    对于复杂任务，会自动拆分为多个子任务，调用不同模型协作完成。
    """
    try:
        if not req.message.strip():
            return ApiResponse.error(
                code=400,
                message="消息内容不能为空",
            )

        result = await principal_agent.chat(
            message=req.message,
            session_id=req.session_id,
            preference=req.preference,
            system_prompt=req.system_prompt,
        )

        return ApiResponse.success(
            data={
                "response": result.response,
                "model_key": result.model_key,
                "model_name": result.model_name,
                "source_id": result.source_id,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.input_tokens + result.output_tokens,
                "cost": result.cost,
                "latency_ms": result.latency_ms,
                "route_id": result.route_id,
                "task_type": result.task_type,
                "sub_tasks": result.sub_tasks,
                "metadata": result.metadata,
            },
            message="对话完成",
        )
    except Exception as exc:
        return ApiResponse.error(
            code=500,
            message=f"对话失败: {exc}",
        )


@router.get("/principal/models")
async def get_principal_models(
    current_user: dict = Depends(get_current_user),
):
    """
    获取主理人调度Agent可用模型列表

    返回通过算力调度平台可访问的所有模型，包括模型key、名称、用途等信息。
    """
    try:
        models = principal_agent.list_available_models()
        return ApiResponse.success(
            data={
                "total": len(models),
                "items": models,
            },
            message="获取模型列表成功",
        )
    except Exception as exc:
        return ApiResponse.error(
            code=500,
            message=f"获取模型列表失败: {exc}",
        )


@router.post("/principal/route")
async def principal_route_test(
    req: PrincipalRouteTestRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    手动路由测试

    测试给定消息会被路由到哪个模型，以及路由决策的详细信息。
    可用于调试路由策略和验证模型选择逻辑。
    """
    try:
        if not req.message.strip():
            return ApiResponse.error(
                code=400,
                message="测试消息不能为空",
            )

        result = await principal_agent.manual_route_test(
            message=req.message,
            model_key=req.model_key,
            preference=req.preference,
        )

        return ApiResponse.success(
            data=result,
            message="路由测试完成",
        )
    except Exception as exc:
        return ApiResponse.error(
            code=500,
            message=f"路由测试失败: {exc}",
        )


@router.get("/principal/sessions")
async def get_principal_sessions(
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    current_user: dict = Depends(get_current_user),
):
    """
    获取主理人对话会话列表
    """
    try:
        from ..models import SessionLocal, PrincipalChatSession

        db = SessionLocal()
        sessions = (
            db.query(PrincipalChatSession)
            .order_by(PrincipalChatSession.updated_at.desc())
            .limit(limit)
            .all()
        )
        db.close()

        items = [s.to_dict() for s in sessions]
        return ApiResponse.success(
            data={
                "total": len(items),
                "items": items,
            },
            message="获取会话列表成功",
        )
    except Exception as exc:
        return ApiResponse.error(
            code=500,
            message=f"获取会话列表失败: {exc}",
        )


@router.get("/principal/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    current_user: dict = Depends(get_current_user),
):
    """
    获取指定会话的消息历史
    """
    try:
        messages = principal_agent.get_session_history(session_id, limit=limit)
        return ApiResponse.success(
            data={
                "session_id": session_id,
                "total": len(messages),
                "items": messages,
            },
            message="获取消息历史成功",
        )
    except Exception as exc:
        return ApiResponse.error(
            code=500,
            message=f"获取消息历史失败: {exc}",
        )
