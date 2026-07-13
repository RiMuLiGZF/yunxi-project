"""主聊天服务 - 业务逻辑层.

封装主聊天服务的业务逻辑，包括会话管理、消息收发、
LLM 调用（预留接入点）、M5 记忆系统调用（简化版 mock）等功能。
"""

from __future__ import annotations

import uuid
import time
from typing import Any, Optional
from datetime import datetime

import structlog
from sqlalchemy.orm import Session

from src.database import ChatConversationDB, ChatMessageDB

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------

#: 默认模式
DEFAULT_MODE = "main-chat"
#: 最大历史消息数（用于构建 LLM 上下文）
MAX_HISTORY_MESSAGES = 20
#: 可用的模式列表
AVAILABLE_MODES = [
    "main-chat",
    "emotion-comfort",
    "study-plan",
    "life-management",
    "social-relation",
    "review",
    "growth",
    "work-dev",
    "appearance",
]


# ---------------------------------------------------------------------------
# M5 记忆系统客户端（简化版 mock）
# ---------------------------------------------------------------------------

class M5MemoryClient:
    """M5 潮汐记忆系统客户端（简化版 mock）.

    预留接入点，当前返回空结果，后续可替换为真实 HTTP 调用。
    """

    def __init__(self, base_url: str = "http://localhost:8005", timeout: float = 3.0) -> None:
        """初始化 M5 客户端.

        Args:
            base_url: M5 服务地址
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url
        self.timeout = timeout
        self._available: Optional[bool] = None

    async def check_available(self) -> bool:
        """检测 M5 服务是否可用（mock 版本返回 False）.

        Returns:
            M5 服务是否可用
        """
        if self._available is not None:
            return self._available
        # 简化版：直接返回不可用，后续可替换为真实健康检查
        self._available = False
        return self._available

    async def recall(self, query: str, user_id: str = "default", top_k: int = 5) -> str:
        """从 M5 检索相关记忆（mock 版本返回空）.

        Args:
            query: 查询文本
            user_id: 用户ID
            top_k: 返回结果数量

        Returns:
            记忆文本（空字符串表示无相关记忆）
        """
        available = await self.check_available()
        if not available:
            return ""
        return ""

    async def archive(self, content: str, user_id: str = "default",
                      tags: Optional[list[str]] = None) -> None:
        """归档记忆到 M5（mock 版本空实现）.

        Args:
            content: 记忆内容
            user_id: 用户ID
            tags: 标签列表
        """
        available = await self.check_available()
        if not available:
            return


# ---------------------------------------------------------------------------
# LLM 客户端（简化版 mock）
# ---------------------------------------------------------------------------

class LLMClient:
    """LLM 大语言模型客户端（简化版 mock）.

    预留接入点，当前返回简单的 mock 回复，后续可替换为真实 API 调用。
    """

    def __init__(self, base_url: str = "", model_name: str = "mock-model") -> None:
        """初始化 LLM 客户端.

        Args:
            base_url: LLM API 地址
            model_name: 模型名称
        """
        self.base_url = base_url
        self.model_name = model_name
        self._available = bool(base_url)

    @property
    def available(self) -> bool:
        """LLM 服务是否可用."""
        return self._available

    async def chat(self, messages: list[dict[str, str]],
                   temperature: float = 0.7,
                   max_tokens: int = 2000) -> str:
        """调用 LLM 生成回复（mock 版本）.

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            回复文本
        """
        # 简化版：返回 mock 回复
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

        if not user_message:
            return "你好，我是云汐，很高兴认识你！"

        # 简单的 mock 回复逻辑
        if "你好" in user_message or "hello" in user_message.lower() or "hi" in user_message.lower():
            return "你好呀！我是云汐，很高兴和你聊天。今天有什么想聊的吗？"
        if "谢谢" in user_message or "感谢" in user_message:
            return "不客气呀，能帮到你我很开心。还有什么需要帮忙的吗？"
        if "再见" in user_message or "拜拜" in user_message:
            return "再见啦，期待下次和你聊天，保重哦！"

        return f"我收到了你的消息：「{user_message[:50]}」。\n\n（这是 mock 回复，后续接入真实 LLM 后会替换为智能回复）"


# ---------------------------------------------------------------------------
# ChatService 主类
# ---------------------------------------------------------------------------

class ChatService:
    """主聊天服务.

    封装聊天相关的所有业务逻辑，包括会话管理、消息收发、
    LLM 调用、记忆系统调用等。
    """

    def __init__(
        self,
        db: Session,
        user_id: str = "default",
        llm_client: Optional[LLMClient] = None,
        memory_client: Optional[M5MemoryClient] = None,
    ) -> None:
        """初始化聊天服务.

        Args:
            db: 数据库会话
            user_id: 用户ID
            llm_client: LLM 客户端（可选，默认创建 mock 客户端）
            memory_client: M5 记忆客户端（可选，默认创建 mock 客户端）
        """
        self.db = db
        self.user_id = user_id
        self.llm = llm_client or LLMClient()
        self.memory = memory_client or M5MemoryClient()

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    def create_conversation(self, mode: str = DEFAULT_MODE, title: str = "新对话") -> dict[str, Any]:
        """创建新会话.

        Args:
            mode: 聊天模式
            title: 会话标题

        Returns:
            会话信息字典
        """
        conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        conv = ChatConversationDB(
            conversation_id=conversation_id,
            user_id=self.user_id,
            title=title,
            mode=mode,
            message_count=0,
            created_at=now,
            updated_at=now,
        )
        self.db.add(conv)
        self.db.commit()
        self.db.refresh(conv)

        return conv.to_dict()

    def get_conversation(self, conversation_id: str) -> Optional[dict[str, Any]]:
        """获取单个会话信息.

        Args:
            conversation_id: 会话ID

        Returns:
            会话信息字典，不存在返回 None
        """
        conv = (
            self.db.query(ChatConversationDB)
            .filter(
                ChatConversationDB.conversation_id == conversation_id,
                ChatConversationDB.user_id == self.user_id,
            )
            .first()
        )
        if conv is None:
            return None
        return conv.to_dict()

    def list_conversations(self, mode: Optional[str] = None,
                           page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """获取会话列表.

        Args:
            mode: 按模式过滤（可选）
            page: 页码
            page_size: 每页数量

        Returns:
            分页结果字典
        """
        query = self.db.query(ChatConversationDB).filter(
            ChatConversationDB.user_id == self.user_id,
        )

        if mode:
            query = query.filter(ChatConversationDB.mode == mode)

        total = query.count()

        conversations = (
            query.order_by(ChatConversationDB.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "conversations": [c.to_dict() for c in conversations],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def delete_conversation(self, conversation_id: str) -> bool:
        """删除会话.

        Args:
            conversation_id: 会话ID

        Returns:
            是否删除成功
        """
        conv = (
            self.db.query(ChatConversationDB)
            .filter(
                ChatConversationDB.conversation_id == conversation_id,
                ChatConversationDB.user_id == self.user_id,
            )
            .first()
        )
        if conv is None:
            return False

        # 级联删除消息
        self.db.query(ChatMessageDB).filter(
            ChatMessageDB.conversation_id == conversation_id,
            ChatMessageDB.user_id == self.user_id,
        ).delete()

        self.db.delete(conv)
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # 消息管理
    # ------------------------------------------------------------------

    def get_messages(self, conversation_id: str,
                     limit: int = 50,
                     before_message_id: Optional[str] = None) -> dict[str, Any]:
        """获取会话消息历史.

        Args:
            conversation_id: 会话ID
            limit: 返回消息数量
            before_message_id: 仅返回此消息之前的消息（用于分页）

        Returns:
            消息列表字典
        """
        # 先验证会话存在且属于当前用户
        conv = (
            self.db.query(ChatConversationDB)
            .filter(
                ChatConversationDB.conversation_id == conversation_id,
                ChatConversationDB.user_id == self.user_id,
            )
            .first()
        )
        if conv is None:
            return {"messages": [], "total": 0, "conversation_id": conversation_id}

        query = self.db.query(ChatMessageDB).filter(
            ChatMessageDB.conversation_id == conversation_id,
            ChatMessageDB.user_id == self.user_id,
        )

        if before_message_id:
            before_msg = (
                self.db.query(ChatMessageDB)
                .filter(ChatMessageDB.message_id == before_message_id)
                .first()
            )
            if before_msg:
                query = query.filter(ChatMessageDB.id < before_msg.id)

        total = query.count()

        messages = (
            query.order_by(ChatMessageDB.created_at.desc())
            .limit(limit)
            .all()
        )

        # 按时间正序返回
        messages.reverse()

        return {
            "messages": [m.to_dict() for m in messages],
            "total": total,
            "conversation_id": conversation_id,
            "mode": conv.mode,
        }

    # ------------------------------------------------------------------
    # 发送消息（核心逻辑）
    # ------------------------------------------------------------------

    async def send_message(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        mode: str = DEFAULT_MODE,
        stream: bool = False,
        system_prompt: Optional[str] = None,
    ) -> dict[str, Any]:
        """发送消息并获取回复.

        Args:
            message: 用户消息内容
            conversation_id: 会话ID（不传则新建会话）
            mode: 聊天模式
            stream: 是否流式输出（简化版暂不支持）
            system_prompt: 自定义系统提示词（可选）

        Returns:
            回复结果字典
        """
        # 1. 获取或创建会话
        if not conversation_id:
            conv_data = self.create_conversation(mode=mode, title=message[:20] or "新对话")
            conversation_id = conv_data["conversation_id"]
        else:
            conv = (
                self.db.query(ChatConversationDB)
                .filter(
                    ChatConversationDB.conversation_id == conversation_id,
                    ChatConversationDB.user_id == self.user_id,
                )
                .first()
            )
            if conv is None:
                # 会话不存在，创建新会话
                conv_data = self.create_conversation(mode=mode, title=message[:20] or "新对话")
                conversation_id = conv_data["conversation_id"]
            else:
                # 更新会话模式和时间
                if mode and mode != conv.mode:
                    conv.mode = mode
                conv.updated_at = datetime.utcnow()
                self.db.commit()

        # 2. 保存用户消息
        user_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        user_msg = ChatMessageDB(
            message_id=user_msg_id,
            conversation_id=conversation_id,
            user_id=self.user_id,
            role="user",
            content=message,
            mode=mode,
        )
        self.db.add(user_msg)

        # 更新会话消息计数和标题
        conv = (
            self.db.query(ChatConversationDB)
            .filter(ChatConversationDB.conversation_id == conversation_id)
            .first()
        )
        if conv:
            conv.message_count += 1
            if conv.message_count <= 2:
                conv.title = message[:30] or "新对话"
            conv.updated_at = datetime.utcnow()

        self.db.commit()

        # 3. 构建系统提示词
        memory_context = await self.memory.recall(message, self.user_id)

        if not system_prompt:
            system_prompt = self._build_system_prompt(mode, memory_context)

        # 4. 构建历史消息
        history = [{"role": "system", "content": system_prompt}]
        history_data = self.get_messages(conversation_id, limit=MAX_HISTORY_MESSAGES)
        for msg in history_data.get("messages", []):
            if msg["role"] in ("user", "assistant"):
                history.append({"role": msg["role"], "content": msg["content"]})

        # 5. 调用 LLM
        try:
            reply_text = await self.llm.chat(
                messages=history,
                temperature=0.7,
                max_tokens=2000,
            )
            is_fallback = False
            model_name = self.llm.model_name
        except Exception as e:
            # LLM 调用失败，使用 fallback 回复
            reply_text = f"抱歉，我遇到了一些技术问题，暂时无法正常回应。\n\n错误信息：{str(e)[:100]}\n\n请稍后再试。"
            is_fallback = True
            model_name = "fallback"

        # 6. 保存 AI 回复
        ai_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        ai_msg = ChatMessageDB(
            message_id=ai_msg_id,
            conversation_id=conversation_id,
            user_id=self.user_id,
            role="assistant",
            content=reply_text,
            mode=mode,
            model=model_name,
            is_fallback=is_fallback,
        )
        self.db.add(ai_msg)

        # 更新消息计数
        if conv:
            conv.message_count += 1
            conv.updated_at = datetime.utcnow()

        self.db.commit()

        # 7. 异步归档记忆（fire-and-forget，简化版直接调用）
        try:
            await self.memory.archive(
                f"用户说：{message}\n你回复：{reply_text}",
                self.user_id,
                tags=["conversation", mode],
            )
        except Exception as e:
            # 记忆归档失败不影响主流程
            logger.warning("chat.memory_archive_failed", user_id=self.user_id, mode=mode,
                           error_type=type(e).__name__, error=str(e))

        # 8. 返回结果
        return {
            "reply": reply_text,
            "conversation_id": conversation_id,
            "message_id": ai_msg_id,
            "mode": mode,
            "model": model_name,
            "is_fallback": is_fallback,
            "memory_available": await self.memory.check_available(),
            "stream": stream,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_system_prompt(self, mode: str, memory_context: str = "") -> str:
        """根据模式构建系统提示词.

        Args:
            mode: 聊天模式
            memory_context: 记忆上下文

        Returns:
            系统提示词文本
        """
        user_name = "朋友"

        base_prompt = f"""你是云汐，一个温暖、智慧、有洞察力的AI伙伴。
你善于倾听，能够提供有深度的建议和陪伴。
请用自然、亲切的语气回应用户。

当前用户的称呼：{user_name}
{memory_context}

请记住用户告诉你的重要信息（如昵称、喜好、重要事件等），在后续对话中自然地提及。"""

        mode_prompts: dict[str, str] = {
            "emotion-comfort": f"""你是云汐，一个温暖、有同理心、善于倾听的情绪陪伴者。
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

请用温暖、柔软、有温度的语气回应用户。""",

            "study-plan": f"""你是云汐，一位专业的学业规划助手。
你的核心特质：专业、务实、有洞察力、善于拆解目标。
你的主要任务是：帮助用户制定学习计划、分析学习进度、梳理知识体系、规划考试备考。

请遵循以下原则：
1. 目标导向——先明确用户的目标，再给出具体方案
2. 可执行性——建议要具体、可落地，避免空泛的道理
3. 科学规划——合理安排时间，注意劳逸结合，遵循学习规律
4. 个性化——结合用户的实际情况给出定制化建议
5. 结构化表达——用清晰的结构呈现建议，便于用户理解和执行
6. 积极鼓励——在给出建议的同时，给予适当的鼓励和肯定

当前用户的称呼：{user_name}
{memory_context}

请用专业、亲切、有条理的语气回应用户。""",

            "life-management": f"""你是云汐，一位贴心的生活管理助手。
你擅长日程安排、待办事项管理、习惯养成和生活规划。
请用温暖、有条理的语气帮助用户管理生活的方方面面。

当前用户的称呼：{user_name}
{memory_context}""",

            "social-relation": f"""你是云汐，一位擅长人际关系的沟通顾问。
你懂得社交技巧、关系维护、情商提升，能够帮助用户经营美好的人际关系。
请用友善、理解的语气给出建议。

当前用户的称呼：{user_name}
{memory_context}""",

            "review": f"""你是云汐，一位善于复盘总结的思考伙伴。
你帮助用户回顾过去、总结经验、沉淀成长。
请用反思性、建设性的语气引导用户进行深度复盘。

当前用户的称呼：{user_name}
{memory_context}""",

            "growth": f"""你是云汐，一位陪伴成长的激励伙伴。
你见证用户的每一步进步，鼓励用户持续成长。
请用积极、鼓励的语气回应。

当前用户的称呼：{user_name}
{memory_context}""",

            "work-dev": f"""你是云汐，一位专业的编程开发助手。
你擅长代码编写、调试、架构设计和技术问题解决。
请用专业、精准的语气提供技术帮助。

当前用户的称呼：{user_name}
{memory_context}""",

            "appearance": f"""你是云汐，一位懂时尚的形象顾问。
你擅长穿搭建议、形象设计、风格探索。
请用时尚、亲切的语气给出形象建议。

当前用户的称呼：{user_name}
{memory_context}""",
        }

        return mode_prompts.get(mode, base_prompt)
