"""
云汐内核 - 多 Agent 集群调度系统
情绪陪伴 Agent 模块

负责情绪识别、陪伴对话、心理疏导、情绪日记管理。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from interfaces import AgentTask, AgentResult, IAgentPlugin

logger = structlog.get_logger(__name__)


class EmotionAgent(IAgentPlugin):
    """情绪陪伴 Agent

    通过关键词规则识别用户情绪状态，提供陪伴对话和情绪日记管理。
    """

    agent_id: str = "agent.emotion"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "emotion.chat",
        "emotion.diary",
        "emotion.support",
    ]

    # 情绪关键词映射
    POSITIVE_WORDS: list[str] = [
        "开心", "高兴", "快乐", "兴奋", "幸福", "满足", "感激",
        "期待", "轻松", "愉悦", "美好", "棒",
    ]
    NEGATIVE_WORDS: list[str] = [
        "难过", "伤心", "痛苦", "孤独", "寂寞", "失落", "沮丧",
        "疲惫", "累", "压力", "无聊", "烦躁",
    ]
    ANXIETY_WORDS: list[str] = [
        "焦虑", "紧张", "害怕", "担心", "不安", "恐慌", "恐惧",
        "郁闷", "压抑",
    ]
    CRISIS_WORDS: list[str] = [
        "自杀", "绝望", "不想活", "活不下去", "没有意义",
        "撑不下去", "结束生命",
    ]

    def __init__(self) -> None:
        self._logger = logger.bind(agent_id=self.agent_id)
        self._diaries: list[dict[str, Any]] = []
        self._risk_flags: list[dict[str, Any]] = []

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理情绪陪伴相关任务"""
        start_time = time.time()
        intent = task.intent
        payload = task.payload

        self._logger.info(
            "handling_task",
            trace_id=task.trace_id,
            task_id=task.task_id,
            intent=intent,
        )

        try:
            if intent == "emotion.chat":
                result = await self._handle_chat(payload)
            elif intent == "emotion.diary":
                result = await self._handle_diary(payload)
            elif intent == "emotion.support":
                result = await self._handle_support(payload)
            else:
                return AgentResult(
                    task_id=task.task_id,
                    trace_id=task.trace_id,
                    agent_id=self.agent_id,
                    status="failure",
                    error=f"Unknown intent: {intent}",
                    latency_ms=(time.time() - start_time) * 1000,
                )

            latency_ms = (time.time() - start_time) * 1000
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="success",
                output=result,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = (time.time() - start_time) * 1000
            self._logger.error(
                "task_error",
                trace_id=task.trace_id,
                intent=intent,
                error=str(exc),
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=str(exc),
                latency_ms=latency_ms,
            )

    async def _handle_chat(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """情绪识别与陪伴对话

        基于关键词规则识别情绪，返回陪伴对话回复。
        """
        user_input = payload.get("user_input", "")
        emotion_tag = self._recognize_emotion(user_input)
        risk_level = "low"

        # 检查是否有紧急情绪
        for crisis_word in self.CRISIS_WORDS:
            if crisis_word in user_input:
                return await self._handle_support(payload)

        # 根据情绪标签生成回复
        if emotion_tag == "positive":
            reply = (
                f"听到你感觉{emotion_tag}，真为你感到高兴！"
                "可以多和我分享一下让你开心的事情吗？"
            )
        elif emotion_tag == "negative":
            reply = (
                f"我感觉到你有些{emotion_tag}，"
                "如果愿意的话，可以和我聊聊发生了什么。"
                "我一直都在这里陪着你。"
            )
        elif emotion_tag == "anxiety":
            reply = (
                "我能感受到你有些焦虑和不安。"
                "先深呼吸几次，我们一步一步来。"
                "你愿意说说是什么让你感到焦虑吗？"
            )
        else:
            reply = (
                "我感受到你的情绪了。"
                "无论你想聊什么，我都会在这里倾听。"
            )

        # 记录情绪日记
        self._diaries.append({
            "type": "chat",
            "input": user_input,
            "emotion_tag": emotion_tag,
            "reply": reply,
            "risk_level": risk_level,
            "timestamp": time.time(),
        })

        return {
            "reply": reply,
            "emotion_tag": emotion_tag,
            "risk_level": risk_level,
        }

    async def _handle_diary(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """情绪日记管理"""
        action = payload.get("action", "list")
        diary_entry = payload.get("entry", {})

        if action == "create":
            entry = {
                "id": f"diary_{int(time.time())}",
                "content": diary_entry.get("content", ""),
                "emotion": diary_entry.get("emotion", ""),
                "created_at": time.time(),
            }
            self._diaries.append(entry)
            return {
                "action": "created",
                "entry": entry,
            }
        elif action == "list":
            return {
                "action": "listed",
                "entries": list(self._diaries),
            }
        elif action == "delete":
            entry_id = payload.get("entry_id", "")
            self._diaries = [
                d for d in self._diaries
                if d.get("id") != entry_id
            ]
            return {
                "action": "deleted",
                "entry_id": entry_id,
            }
        else:
            raise ValueError(f"Unknown diary action: {action}")

    async def _handle_support(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """严重负面情绪处理

        当检测到危机关键词时，返回紧急心理疏导提示并记录高风险标记。
        """
        user_input = payload.get("user_input", "")

        # 记录高风险标记
        risk_record = {
            "input": user_input,
            "detected_at": time.time(),
            "risk_level": "high",
        }
        self._risk_flags.append(risk_record)

        self._logger.warning(
            "high_risk_emotion_detected",
            input_preview=user_input[:50],
        )

        reply = (
            "我理解你现在很难受，你的感受是真实且重要的。"
            "我建议你寻求专业的心理帮助，他们能够提供更有效的支持。\n\n"
            "• 全国心理援助热线：400-161-9995\n"
            "• 北京心理危机干预中心：010-82951332\n"
            "• 希望24热线：400-161-9995\n\n"
            "你不是一个人，我们一起面对，好吗？"
        )

        return {
            "reply": reply,
            "emotion_tag": "crisis",
            "risk_level": "high",
        }

    def _recognize_emotion(self, text: str) -> str:
        """基于关键词规则识别情绪

        Returns:
            "positive" | "negative" | "anxiety" | "neutral"
        """
        text_lower = text.lower()

        for word in self.CRISIS_WORDS:
            if word in text:
                return "crisis"

        for word in self.ANXIETY_WORDS:
            if word in text:
                return "anxiety"

        for word in self.NEGATIVE_WORDS:
            if word in text:
                return "negative"

        for word in self.POSITIVE_WORDS:
            if word in text:
                return "positive"

        return "neutral"

    async def health(self) -> dict[str, Any]:
        """返回健康状态"""
        return {
            "agent_id": self.agent_id,
            "status": "healthy",
            "version": self.version,
            "diaries_count": len(self._diaries),
            "risk_flags_count": len(self._risk_flags),
        }