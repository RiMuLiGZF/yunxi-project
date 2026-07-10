"""
云汐聊天接口 - 对接千问大模型
提供主聊天界面的对话能力
"""

import os
import sys
import time
import uuid
import httpx
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.llm_client import LLMClient
from shared.module_client import get_module_registry
from ..schemas import ApiResponse
from ..auth import get_current_user

router = APIRouter()
llm = LLMClient()
registry = get_module_registry()

# M5 记忆服务配置
M5_BASE_URL = os.environ.get("M5_BASE_URL", "http://localhost:8005")
_m5_available = None  # 缓存检测结果


async def _check_m5_available():
    """检测 M5 记忆服务是否可用"""
    global _m5_available
    if _m5_available is not None:
        return _m5_available
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{M5_BASE_URL}/health")
            _m5_available = resp.status_code == 200
    except Exception:
        _m5_available = False
    return _m5_available


async def _recall_memory(query: str, user_id: str = "default"):
    """从 M5 检索相关记忆"""
    available = await _check_m5_available()
    if not available:
        return ""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{M5_BASE_URL}/api/v1/memory/recall",
                json={
                    "query": query,
                    "top_k": 5,
                    "layers": ["l1_shallow", "l2_deep"],
                    "domain": "private",
                    "agent_id": f"user_{user_id}",
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                memories = data.get("data", {}).get("results", [])
                if memories:
                    mem_texts = [f"- {m.get('content', '')}" for m in memories[:5]]
                    return "\n相关记忆：\n" + "\n".join(mem_texts)
    except Exception:
        pass
    return ""


async def _archive_memory(content: str, user_id: str = "default", tags: list = None):
    """归档记忆到 M5"""
    available = await _check_m5_available()
    if not available:
        return
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(
                f"{M5_BASE_URL}/api/v1/memory/archive",
                json={
                    "content": content,
                    "domain": "private",
                    "agent_id": f"user_{user_id}",
                    "tags": tags or [],
                    "source": "conversation",
                }
            )
    except Exception:
        pass

# 内存中的会话存储（MVP）
_conversations = {}


class ChatSendRequest(BaseModel):
    message: str
    conversation_id: str = "default"
    mode: str = "main-chat"
    stream: bool = False
    system_prompt: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[float] = None


@router.post("/send")
async def chat_send(req: ChatSendRequest, current_user: dict = Depends(get_current_user)):
    """发送消息到千问大模型"""
    conversation_id = req.conversation_id or "default"

    # 获取或创建会话
    if conversation_id not in _conversations:
        _conversations[conversation_id] = {
            "id": conversation_id,
            "messages": [],
            "created_at": time.time(),
            "mode": req.mode,
        }

    conv = _conversations[conversation_id]

    # 添加用户消息
    user_msg = {
        "role": "user",
        "content": req.message,
        "timestamp": time.time(),
    }
    conv["messages"].append(user_msg)

    # 构建消息历史（最近10轮，节省token）
    history = []
    if req.system_prompt:
        history.append({"role": "system", "content": req.system_prompt})
    else:
        # 获取用户信息（昵称等）
        user_nickname = current_user.get("nickname", "") if current_user else ""
        user_name = user_nickname or current_user.get("username", "朋友") if current_user else "朋友"

        # 从 M5 检索相关记忆
        memory_context = await _recall_memory(req.message, current_user.get("user_id", "default") if current_user else "default")

        # 构建系统提示词
        system_prompt = f"""你是云汐，一个温暖、智慧、有洞察力的AI伙伴。
你善于倾听，能够提供有深度的建议和陪伴。
请用自然、亲切的语气回应用户。

当前用户的称呼：{user_name}
{memory_context}

请记住用户告诉你的重要信息（如昵称、喜好、重要事件等），在后续对话中自然地提及。"""

        history.append({
            "role": "system",
            "content": system_prompt
        })

    # 添加历史消息（最近20条）
    for msg in conv["messages"][-20:]:
        history.append({"role": msg["role"], "content": msg["content"]})

    try:
        # 调用千问大模型
        reply = await llm.chat(
            messages=history,
            temperature=0.7,
            max_tokens=2000,
        )

        # 添加AI回复
        ai_msg = {
            "role": "assistant",
            "content": reply,
            "timestamp": time.time(),
        }
        conv["messages"].append(ai_msg)

        # 归档对话到 M5 记忆系统
        user_id = current_user.get("user_id", "default") if current_user else "default"
        await _archive_memory(
            f"用户说：{req.message}\n你回复：{reply}",
            user_id=user_id,
            tags=["conversation", req.mode or "main-chat"]
        )

        return ApiResponse(
            code=0,
            message="ok",
            data={
                "reply": reply,
                "conversation_id": conversation_id,
                "message_id": f"msg_{uuid.uuid4().hex[:12]}",
                "mode": req.mode,
                "model": llm.config.model if hasattr(llm, 'config') else "qwen2.5:7b",
                "memory_available": await _check_m5_available(),
            },
        )
    except Exception as e:
        # LLM调用失败，尝试通过M1调度
        try:
            m1_client = registry.get_client("m1")
            is_running = await m1_client.health_check()
            if is_running:
                m1_response = await m1_client.post(
                    "/api/v1/chat",
                    json_data={
                        "user_input": req.message,
                        "stream": False,
                        "conversation_id": conversation_id,
                    },
                    use_auth=False,
                )
                reply = m1_response.get("reply", "抱歉，我暂时无法回答这个问题。")
                ai_msg = {
                    "role": "assistant",
                    "content": reply,
                    "timestamp": time.time(),
                }
                conv["messages"].append(ai_msg)
                return ApiResponse(
                    code=0,
                    message="ok",
                    data={
                        "reply": reply,
                        "conversation_id": conversation_id,
                        "mode": req.mode,
                        "model": "m1-federation",
                    },
                )
        except Exception as m1_error:
            pass

        # 都失败了，返回友好提示
        fallback_reply = f"抱歉，我遇到了一些技术问题，暂时无法正常回应。\n\n错误信息：{str(e)[:100]}\n\n请稍后再试，或者检查大模型服务是否正常运行。"
        ai_msg = {
            "role": "assistant",
            "content": fallback_reply,
            "timestamp": time.time(),
        }
        conv["messages"].append(ai_msg)

        return ApiResponse(
            code=0,  # 不返回错误码，前端显示消息即可
            message="fallback",
            data={
                "reply": fallback_reply,
                "conversation_id": conversation_id,
                "mode": req.mode,
                "is_fallback": True,
            },
        )


@router.get("/conversations")
async def list_conversations(current_user: dict = Depends(get_current_user)):
    """获取会话列表"""
    conv_list = []
    for cid, conv in _conversations.items():
        last_msg = conv["messages"][-1] if conv["messages"] else None
        conv_list.append({
            "id": cid,
            "title": last_msg["content"][:30] + "..." if last_msg else "新对话",
            "mode": conv.get("mode", "main-chat"),
            "message_count": len(conv["messages"]),
            "created_at": conv["created_at"],
            "updated_at": last_msg["timestamp"] if last_msg else conv["created_at"],
        })

    # 按更新时间倒序
    conv_list.sort(key=lambda x: x["updated_at"], reverse=True)

    return ApiResponse(
        code=0,
        message="ok",
        data={
            "conversations": conv_list,
            "total": len(conv_list),
        },
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)):
    """获取单个会话的消息历史"""
    conv = _conversations.get(conversation_id)
    if not conv:
        # 返回空会话
        return ApiResponse(
            code=0,
            message="ok",
            data={
                "id": conversation_id,
                "messages": [],
                "mode": "main-chat",
                "created_at": time.time(),
            },
        )

    return ApiResponse(
        code=0,
        message="ok",
        data={
            "id": conv["id"],
            "messages": conv["messages"],
            "mode": conv.get("mode", "main-chat"),
            "created_at": conv["created_at"],
            "message_count": len(conv["messages"]),
        },
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)):
    """删除会话"""
    if conversation_id in _conversations:
        del _conversations[conversation_id]

    return ApiResponse(
        code=0,
        message="会话已删除",
        data={"deleted": True},
    )


@router.post("/conversations/new")
async def create_conversation(current_user: dict = Depends(get_current_user)):
    """创建新会话"""
    conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
    _conversations[conversation_id] = {
        "id": conversation_id,
        "messages": [],
        "created_at": time.time(),
        "mode": "main-chat",
    }

    return ApiResponse(
        code=0,
        message="ok",
        data={
            "id": conversation_id,
            "messages": [],
            "mode": "main-chat",
            "created_at": time.time(),
        },
    )
