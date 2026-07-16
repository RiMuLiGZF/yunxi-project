"""主聊天服务 - FastAPI 路由.

提供主聊天服务的 REST API 接口，包括消息发送、会话管理、聊天历史等。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.models.db import get_session
from src.models import make_response
from src.services.chat_service import ChatService


router = APIRouter(prefix="/api/v1/chat", tags=["主聊天服务"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class ChatSendRequest(BaseModel):
    """发送消息请求体."""

    message: str = Field(..., description="用户消息内容")
    conversation_id: Optional[str] = Field(None, description="会话ID，不传则新建会话")
    mode: str = Field("main-chat", description="聊天模式")
    stream: bool = Field(False, description="是否流式输出（简化版暂不支持）")
    system_prompt: Optional[str] = Field(None, description="自定义系统提示词")


class ChatNewConversationRequest(BaseModel):
    """新建会话请求体."""

    mode: str = Field("main-chat", description="聊天模式")
    title: Optional[str] = Field(None, description="会话标题")


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------


def get_chat_service(
    db: Session = Depends(get_session),
    user_id: str = Query("default", description="用户ID"),
) -> ChatService:
    """获取聊天服务实例.

    Args:
        db: 数据库会话
        user_id: 用户ID

    Returns:
        聊天服务实例
    """
    return ChatService(db, user_id=user_id)


# ---------------------------------------------------------------------------
# 消息发送
# ---------------------------------------------------------------------------


@router.post("/send", summary="发送消息")
async def chat_send(
    req: ChatSendRequest,
    service: ChatService = Depends(get_chat_service),
):
    """发送用户消息并获取 AI 回复.

    - 根据会话ID获取或创建会话
    - 根据模式构建系统提示词
    - 调用 LLM 生成回复（简化版 mock）
    - 调用 M5 记忆系统（简化版 mock）
    - 返回回复结果
    """
    result = await service.send_message(
        message=req.message,
        conversation_id=req.conversation_id,
        mode=req.mode,
        stream=req.stream,
        system_prompt=req.system_prompt,
    )
    return make_response(data=result, message="ok")


# ---------------------------------------------------------------------------
# 聊天历史
# ---------------------------------------------------------------------------


@router.get("/history", summary="获取聊天历史")
async def chat_history(
    conversation_id: str = Query(..., description="会话ID"),
    limit: int = Query(50, ge=1, le=200, description="返回消息数量"),
    before_message_id: Optional[str] = Query(None, description="仅返回此消息之前的消息（用于分页）"),
    service: ChatService = Depends(get_chat_service),
):
    """获取指定会话的消息历史."""
    result = service.get_messages(
        conversation_id=conversation_id,
        limit=limit,
        before_message_id=before_message_id,
    )
    return make_response(data=result, message="ok")


# ---------------------------------------------------------------------------
# 会话列表
# ---------------------------------------------------------------------------


@router.get("/conversations", summary="获取会话列表")
async def list_conversations(
    mode: Optional[str] = Query(None, description="按模式过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    service: ChatService = Depends(get_chat_service),
):
    """获取用户的所有会话列表，按更新时间倒序排列."""
    result = service.list_conversations(
        mode=mode,
        page=page,
        page_size=page_size,
    )
    return make_response(data=result, message="ok")


# ---------------------------------------------------------------------------
# 新建会话
# ---------------------------------------------------------------------------


@router.post("/new", summary="新建会话")
async def new_conversation(
    req: ChatNewConversationRequest,
    service: ChatService = Depends(get_chat_service),
):
    """创建一个新的聊天会话."""
    result = service.create_conversation(
        mode=req.mode,
        title=req.title or "新对话",
    )
    return make_response(data=result, message="会话创建成功")


# ---------------------------------------------------------------------------
# 获取单个会话
# ---------------------------------------------------------------------------


@router.get("/conversations/{conversation_id}", summary="获取会话详情")
async def get_conversation(
    conversation_id: str,
    service: ChatService = Depends(get_chat_service),
):
    """获取单个会话的详细信息."""
    result = service.get_conversation(conversation_id)
    if result is None:
        return make_response(code=404, message="会话不存在", data={})
    return make_response(data=result, message="ok")


# ---------------------------------------------------------------------------
# 删除会话
# ---------------------------------------------------------------------------


@router.delete("/conversations/{conversation_id}", summary="删除会话")
async def delete_conversation(
    conversation_id: str,
    service: ChatService = Depends(get_chat_service),
):
    """删除指定会话及其所有消息."""
    success = service.delete_conversation(conversation_id)
    if not success:
        return make_response(code=404, message="会话不存在", data={})
    return make_response(data={"deleted": True}, message="会话已删除")
