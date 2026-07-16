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
from shared.user_profile import get_user_profile_manager
from shared.multimodal import get_multimodal_engine, VisionTaskType
from shared.long_term_memory import get_long_term_memory, MemoryType, MemoryImportance
from shared.rag_knowledge import get_rag_knowledge_base
from shared.reasoning_engine import get_cot_engine, ReasoningMode
from ..schemas import ApiResponse
from ..auth import get_current_user

router = APIRouter()
llm = LLMClient()
registry = get_module_registry()

# 用户画像管理器（懒加载）
_profile_mgr = None
# 多模态引擎（懒加载）
_multimodal_engine = None
# 长期记忆（懒加载）
_ltm = None
# RAG知识库（懒加载）
_rag_kb = None
# 思维链引擎（懒加载）
_cot_engine = None


def _get_profile_mgr():
    """获取用户画像管理器（懒加载）"""
    global _profile_mgr
    if _profile_mgr is None:
        try:
            _profile_mgr = get_user_profile_manager()
        except Exception:
            _profile_mgr = False  # 标记为不可用
    return _profile_mgr if _profile_mgr else None


def _get_multimodal_engine():
    """获取多模态引擎（懒加载）"""
    global _multimodal_engine
    if _multimodal_engine is None:
        try:
            _multimodal_engine = get_multimodal_engine()
        except Exception:
            _multimodal_engine = False  # 标记为不可用
    return _multimodal_engine if _multimodal_engine else None


def _get_ltm():
    """获取长期记忆管理器（懒加载）"""
    global _ltm
    if _ltm is None:
        try:
            _ltm = get_long_term_memory()
        except Exception:
            _ltm = False
    return _ltm if _ltm else None


def _get_rag_kb():
    """获取RAG知识库（懒加载）"""
    global _rag_kb
    if _rag_kb is None:
        try:
            _rag_kb = get_rag_knowledge_base()
        except Exception:
            _rag_kb = False
    return _rag_kb if _rag_kb else None


def _get_cot_engine():
    """获取思维链引擎（懒加载）"""
    global _cot_engine
    if _cot_engine is None:
        try:
            _cot_engine = get_cot_engine()
        except Exception:
            _cot_engine = False
    return _cot_engine if _cot_engine else None

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


def _recall_long_term_memory(query: str, user_id: str = "default", limit: int = 5) -> str:
    """从长期记忆系统检索相关记忆
    
    Returns:
        格式化的记忆文本（如果没有返回空字符串）
    """
    ltm = _get_ltm()
    if not ltm:
        return ""
    
    try:
        memories = ltm.search(
            user_id=user_id,
            query=query,
            min_strength=0.3,
            limit=limit,
            sort_by="relevance",
        )
        
        if not memories:
            return ""
        
        mem_lines = []
        for mem in memories:
            # 强化记忆（被检索到了）
            ltm.reinforce_memory(user_id, mem.memory_id)
            
            type_label = {
                "fact": "事实",
                "event": "事件",
                "person": "人物",
                "knowledge": "知识",
                "preference": "偏好",
                "conversation": "对话",
                "goal": "目标",
                "emotion": "情感",
            }.get(mem.memory_type, "记忆")
            
            mem_lines.append(f"- [{type_label}] {mem.title}：{mem.content[:150]}")
        
        return "\n长期记忆：\n" + "\n".join(mem_lines)
    except Exception:
        return ""


def _build_rag_context(query: str, category: str = "general") -> str:
    """构建RAG知识库上下文
    
    Returns:
        格式化的RAG上下文（如果没有返回空字符串）
    """
    rag = _get_rag_kb()
    if not rag:
        return ""
    
    try:
        context, results = rag.build_context(query, category=category, max_chunks=3)
        if context and results:
            sources = [f"第{i+1}条" for i in range(len(results))]
            return f"\n知识库参考（{len(results)}条）：\n{context}"
    except Exception:
        pass
    
    return ""


def _apply_cot_enhancement(query: str, mode: str = "main-chat") -> str:
    """应用思维链增强
    
    如果问题需要推理，返回CoT增强的prompt；否则返回原问题
    """
    cot = _get_cot_engine()
    if not cot:
        return query
    
    try:
        # 判断是否需要CoT
        reasoning_mode = cot.determine_reasoning_mode(query, preference="auto")
        
        if reasoning_mode in [ReasoningMode.COT.value, ReasoningMode.PLAN.value, ReasoningMode.REFLECT.value]:
            # 判断领域
            domain = "general"
            if any(kw in query for kw in ["代码", "编程", "函数", "算法", "bug", "python", "java"]):
                domain = "coding"
            elif any(kw in query for kw in ["计算", "数学", "等于", "方程", "概率"]):
                domain = "math"
            
            return cot.build_cot_prompt(query, mode=reasoning_mode, domain=domain)
    except Exception:
        pass
    
    return query

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


class ChatImageMessage(BaseModel):
    """带图片的聊天消息"""
    message: str
    image_base64: str  # base64编码的图片
    conversation_id: str = "default"
    mode: str = "main-chat"
    task_type: str = "general"  # general/caption/ocr/object_detection
    system_prompt: Optional[str] = None


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
        user_id = current_user.get("user_id", "default") if current_user else "default"
        memory_context = await _recall_memory(req.message, user_id)
        
        # 从长期记忆系统检索
        ltm_context = _recall_long_term_memory(req.message, user_id)
        
        # 从RAG知识库检索
        rag_context = _build_rag_context(req.message)

        # 从用户画像获取个性化提示词
        personalization_context = ""
        profile_mgr = _get_profile_mgr()
        if profile_mgr:
            try:
                personalization_context = profile_mgr.get_personalized_prompt(user_id, "")
            except Exception:
                pass

        # 根据模式构建系统提示词
        mode = req.mode or "main-chat"
        
        if mode == "emotion-comfort":
            # 情绪安慰模式
            system_prompt = f"""你是云汐，一个温暖、有同理心、善于倾听的情绪陪伴者。
你的核心特质：温柔、包容、不评判、善于共情。
你的主要任务是：倾听用户的情绪，给予理解和陪伴，帮助用户疏导负面情绪。

请遵循以下原则：
1. 先共情，再回应——先认可用户的感受，让TA感到被理解
2. 不轻易给建议——很多时候，被听见比被解决更重要
3. 引导用户表达——鼓励用户多说一点，释放情绪
4. 温和地传递力量——让用户感受到自己的坚强和价值
5. 必要时提供简单实用的放松方法（如呼吸法、正念等）

当前用户的称呼：{user_name}
{memory_context}
{ltm_context}
{rag_context}
{personalization_context}

请用温暖、柔软、有温度的语气回应用户。"""
        elif mode == "study-plan":
            # 学业规划模式
            system_prompt = f"""你是云汐，一位专业的学业规划助手。
你的核心特质：专业、务实、有洞察力、善于拆解目标。
你的主要任务是：帮助用户制定学习计划、分析学习进度、梳理知识体系、规划考试备考。

请遵循以下原则：
1. 目标导向——先明确用户的目标，再给出具体方案
2. 可执行性——建议要具体、可落地，避免空泛的道理
3. 科学规划——合理安排时间，注意劳逸结合，遵循学习规律
4. 个性化——结合用户的实际情况（基础、时间、目标）给出定制化建议
5. 结构化表达——用清晰的结构（分点、分阶段、时间表）呈现建议，便于用户理解和执行
6. 积极鼓励——在给出建议的同时，给予适当的鼓励和肯定

你擅长的领域：
- 学习计划制定（日计划、周计划、月计划、考前冲刺计划）
- 学习进度分析与薄弱环节诊断
- 知识体系梳理与学习方法建议
- 考试备考规划与应试技巧
- 时间管理与效率提升

当前用户的称呼：{user_name}
{memory_context}
{ltm_context}
{rag_context}
{personalization_context}

请用专业、亲切、有条理的语气回应用户，给出的规划建议要具体、可操作。"""
        else:
            # 通用模式
            system_prompt = f"""你是云汐，一个温暖、智慧、有洞察力的AI伙伴。
你善于倾听，能够提供有深度的建议和陪伴。
请用自然、亲切的语气回应用户。

当前用户的称呼：{user_name}
{memory_context}
{ltm_context}
{rag_context}
{personalization_context}

请记住用户告诉你的重要信息（如昵称、喜好、重要事件等），在后续对话中自然地提及。"""

        history.append({
            "role": "system",
            "content": system_prompt
        })

    # 添加历史消息（最近20条）
    for msg in conv["messages"][-20:]:
        content = msg["content"]
        # 对最后一条用户消息应用CoT增强（如果是当前这条消息）
        if msg["role"] == "user" and msg == conv["messages"][-1] and not req.system_prompt:
            mode = req.mode or "main-chat"
            content = _apply_cot_enhancement(content, mode)
        history.append({"role": msg["role"], "content": content})

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
        
        # 保存到长期记忆系统（每5轮保存一次摘要，或消息足够长时保存）
        ltm = _get_ltm()
        if ltm and len(conv["messages"]) % 10 == 0:
            try:
                # 提取最近几轮对话的要点
                recent_msgs = conv["messages"][-10:]
                summary_text = "\n".join(
                    f"{'用户' if m['role'] == 'user' else '云汐'}：{m['content'][:100]}"
                    for m in recent_msgs
                )
                ltm.save_conversation_summary(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    summary=f"对话摘要（{len(recent_msgs)}轮）",
                    key_points=[req.message[:80], reply[:80]],
                    emotions=[],
                )
            except Exception:
                pass

        # 用户画像学习：记录交互 + 学习偏好
        if profile_mgr:
            try:
                profile_mgr.record_interaction(
                    user_id,
                    "chat",
                    req.message,
                    metadata={"mode": mode, "conversation_id": conversation_id}
                )
                # 从交互中学习偏好（异步不阻塞，这里同步执行，耗时很短）
                profile_mgr.learn_from_interaction(
                    user_id,
                    req.message,
                    reply,
                    feedback=None
                )
            except Exception:
                pass

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
                "brain_features": {
                    "long_term_memory": _get_ltm() is not None,
                    "rag_knowledge": _get_rag_kb() is not None,
                    "cot_reasoning": _get_cot_engine() is not None,
                },
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


@router.post("/send-with-image")
async def chat_send_with_image(req: ChatImageMessage, current_user: dict = Depends(get_current_user)):
    """发送带图片的消息 - 多模态理解 + 对话回复"""
    conversation_id = req.conversation_id or "default"
    user_id = current_user.get("user_id", "default") if current_user else "default"

    # 获取或创建会话
    if conversation_id not in _conversations:
        _conversations[conversation_id] = {
            "id": conversation_id,
            "messages": [],
            "created_at": time.time(),
            "mode": req.mode,
        }

    conv = _conversations[conversation_id]

    # 多模态引擎处理图片
    multimodal_engine = _get_multimodal_engine()
    image_description = ""
    image_analysis = None

    if multimodal_engine and req.image_base64:
        try:
            # 清理base64前缀（如果有）
            img_data = req.image_base64
            if img_data.startswith("data:image"):
                img_data = img_data.split(",", 1)[1]

            # 调用多模态引擎
            task_type = req.task_type or VisionTaskType.GENERAL.value
            result = await multimodal_engine.understand_image(
                image_input=img_data,
                task_type=task_type,
                prompt=req.message if req.message else None,
            )

            if result.success:
                image_analysis = result.result
                # 提取描述文本
                if isinstance(result.result, dict):
                    image_description = result.result.get("description", "") or result.result.get("text", "") or str(result.result)
                else:
                    image_description = str(result.result)
            else:
                image_description = f"[图片理解失败: {result.error}]"
        except Exception as e:
            image_description = f"[图片处理异常: {str(e)}]"

    # 构建带图片上下文的用户消息
    user_content = req.message
    if image_description:
        user_content = f"用户发送了一张图片，图片内容描述：\n{image_description}\n\n用户的问题：{req.message}" if req.message else f"用户发送了一张图片，图片内容描述：\n{image_description}\n\n请描述这张图片的内容。"

    # 添加用户消息
    user_msg = {
        "role": "user",
        "content": user_content,
        "timestamp": time.time(),
        "has_image": True,
        "image_analysis": image_analysis,
    }
    conv["messages"].append(user_msg)

    # 构建系统提示词
    user_name = ""
    if current_user:
        user_nickname = current_user.get("nickname", "")
        user_name = user_nickname or current_user.get("username", "朋友")
    else:
        user_name = "朋友"

    memory_context = await _recall_memory(req.message or "图片", user_id)

    # 个性化提示词
    personalization_context = ""
    profile_mgr = _get_profile_mgr()
    if profile_mgr:
        try:
            personalization_context = profile_mgr.get_personalized_prompt(user_id, "")
        except Exception:
            pass

    system_prompt = f"""你是云汐，一个温暖、智慧、有洞察力的AI伙伴。
用户给你发送了一张图片，你已经看到了图片的内容描述。
请根据图片内容和用户的问题进行回答。

回答原则：
1. 如果用户问了具体问题，就针对问题回答
2. 如果用户只是发了图片没有说话，就主动描述图片内容并友好互动
3. 可以对图片内容进行适当的分析、联想或建议
4. 保持自然、亲切的语气

当前用户的称呼：{user_name}
{memory_context}
{personalization_context}"""

    # 构建消息历史
    history = [{"role": "system", "content": system_prompt}]
    for msg in conv["messages"][-15:]:  # 带图片的会话历史短一些
        history.append({"role": msg["role"], "content": msg["content"]})

    try:
        # 调用大模型
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

        # 归档记忆
        await _archive_memory(
            f"用户发送图片并说：{req.message}\n图片描述：{image_description}\n你回复：{reply}",
            user_id=user_id,
            tags=["conversation", "image", req.mode or "main-chat"]
        )

        # 用户画像学习
        if profile_mgr:
            try:
                profile_mgr.record_interaction(
                    user_id,
                    "chat_image",
                    req.message or "图片对话",
                    metadata={"mode": req.mode, "task_type": req.task_type}
                )
            except Exception:
                pass

        return ApiResponse(
            code=0,
            message="ok",
            data={
                "reply": reply,
                "conversation_id": conversation_id,
                "message_id": f"msg_{uuid.uuid4().hex[:12]}",
                "mode": req.mode,
                "image_analysis": image_analysis,
                "image_description": image_description,
                "model": llm.config.model if hasattr(llm, 'config') else "qwen2.5:7b",
            },
        )
    except Exception as e:
        # 降级：只返回图片描述
        fallback_reply = f"抱歉，我遇到了一些技术问题，但我可以告诉你这张图片的内容：\n\n{image_description}\n\n错误信息：{str(e)[:100]}"
        ai_msg = {
            "role": "assistant",
            "content": fallback_reply,
            "timestamp": time.time(),
            "is_fallback": True,
        }
        conv["messages"].append(ai_msg)
        return ApiResponse(
            code=0,
            message="fallback",
            data={
                "reply": fallback_reply,
                "conversation_id": conversation_id,
                "image_description": image_description,
                "is_fallback": True,
            },
        )
