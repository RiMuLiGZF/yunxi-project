"""情绪陪伴 - 模式类.

实现 BaseMode 基类接口，提供情绪陪伴模式的生命周期管理
和消息处理功能。
"""

from __future__ import annotations

from typing import Any

import structlog

from src.modes.base_mode import BaseMode

logger = structlog.get_logger(__name__)


class EmotionComfortMode(BaseMode):
    """情绪陪伴模式类.

    提供情绪疏导、心理支持、温暖陪伴、
    心理健康建议等情绪相关功能。

    继承自 BaseMode，实现模式的生命周期管理、
    消息处理和配置管理。
    """

    mode_id = "emotion_comfort"
    mode_name = "情绪陪伴"
    mode_description = "情绪疏导、心理支持、温暖陪伴，守护心理健康"
    icon = "💗"
    category = "emotion"
    priority = 7
    is_enabled = True

    # ------------------------------------------------------------------
    # 生命周期方法
    # ------------------------------------------------------------------

    async def on_enter(self, context: dict[str, Any]) -> dict[str, Any]:
        """进入情绪陪伴模式.

        加载用户情绪状态，展示情绪概览，
        提供温暖的问候和陪伴。

        Args:
            context: 进入模式时的上下文字典

        Returns:
            进入模式的结果字典
        """
        user_id = context.get("user_id", "default")

        # 延迟导入，避免循环依赖
        from src.models.db import get_session
        from src.modes.emotion_comfort.service import EmotionService

        try:
            db = get_session()
            service = EmotionService(db, user_id=user_id)
            overview = service.get_overview()
            db.close()
        except Exception as e:
            logger.warning("emotion_mode.overview_load_failed", user_id=user_id,
                           error_type=type(e).__name__, error=str(e))
            overview = {"stats": {}, "current_mood": None}

        return {
            "success": True,
            "message": "欢迎来到情绪陪伴空间~ 无论今天心情如何，我都会在这里陪着你。",
            "data": {
                "overview": overview,
                "features": [
                    {"id": "emotion_record", "name": "情绪记录", "icon": "📊"},
                    {"id": "relaxation", "name": "放松引导", "icon": "🧘"},
                    {"id": "sleep", "name": "助眠内容", "icon": "🌙"},
                    {"id": "assessment", "name": "心理测评", "icon": "📝"},
                    {"id": "mood_diary", "name": "心情日记", "icon": "📔"},
                ],
            },
            "context_updates": {
                "current_mode": "emotion_comfort",
                "emotion_overview": overview,
            },
        }

    async def on_leave(self, context: dict[str, Any]) -> dict[str, Any]:
        """离开情绪陪伴模式.

        保存情绪状态，准备切换到其他模式。

        Args:
            context: 离开模式时的上下文字典

        Returns:
            离开模式的结果字典
        """
        return {
            "success": True,
            "message": "感谢你的分享，记得照顾好自己。随时回来找我聊聊~",
            "data": {},
            "context_updates": {
                "previous_mode": "emotion_comfort",
            },
        }

    # ------------------------------------------------------------------
    # 消息处理方法
    # ------------------------------------------------------------------

    async def handle_message(
        self,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理用户在情绪陪伴模式下的消息.

        根据用户输入提供情绪支持和相关建议。

        Args:
            message: 用户输入的文本消息
            context: 当前上下文字典

        Returns:
            消息处理结果字典
        """
        reply = self._generate_reply(message)

        return {
            "success": True,
            "reply": reply,
            "data": {
                "mode": "emotion_comfort",
                "message_type": "chat",
            },
            "context_updates": {},
        }

    def _generate_reply(self, message: str) -> str:
        """根据用户消息生成温暖的回复.

        Args:
            message: 用户输入的消息

        Returns:
            回复文本
        """
        msg = message.lower()

        # 负面情绪
        if any(keyword in msg for keyword in ["难过", "伤心", "痛苦", "沮丧", "失落", "sad"]):
            return "我感受到你现在心情不太好，这很正常。难过的时候，允许自己哭一会儿也没关系。想和我说说发生了什么吗？我会认真听的。"

        if any(keyword in msg for keyword in ["焦虑", "紧张", "担心", "压力", "anxious", "stress"]):
            return "听起来你现在感到有些焦虑。让我们一起做几个深呼吸吧——慢慢吸气，再慢慢呼气。你不是一个人在面对这些，我陪着你。"

        if any(keyword in msg for keyword in ["生气", "愤怒", "恼火", "气", "angry"]):
            return "我理解你现在的感受，生气是很正常的情绪。可以先试着让自己冷静下来，比如数到十，或者去喝杯水。等你准备好了，我们再聊聊发生了什么。"

        if any(keyword in msg for keyword in ["累", "疲惫", "没精力", "tired"]):
            return "辛苦了，你一定很累了吧。记得给自己一些休息的时间，身体和心情都需要充充电。哪怕只是静静地坐一会儿，也是在照顾自己哦。"

        if any(keyword in msg for keyword in ["睡不好", "失眠", "睡不着", "sleep"]):
            return "睡眠不好真的很辛苦。你可以试试睡前做一些放松的事情，比如听舒缓的音乐、泡个脚、或者做几组深呼吸。我们还有专门的助眠内容，需要我推荐吗？"

        # 正面情绪
        if any(keyword in msg for keyword in ["开心", "高兴", "快乐", "幸福", "happy"]):
            return "太好了！看到你开心我也很高兴~ 是什么让你今天心情这么好呢？分享一下你的快乐吧，让我也沾沾喜气！"

        if any(keyword in msg for keyword in ["平静", "放松", "舒服", "calm"]):
            return "这种平静的感觉真好~ 保持这份内心的安宁，珍惜当下的每一刻。需要的话，我们也可以一起做一组放松练习。"

        # 功能相关
        if any(keyword in msg for keyword in ["放松", "冥想", "呼吸", "relax"]):
            return "放松一下吧~ 我们有多种放松方式可以选择：478呼吸法、渐进式肌肉放松、正念冥想、身体扫描等等。你想尝试哪一种呢？"

        if any(keyword in msg for keyword in ["测评", "测试", "评估", "assessment"]):
            return "我们有几种心理测评可以帮助你更好地了解自己：压力水平测评、情绪状态测评、睡眠质量测评。想试试哪一个？"

        if any(keyword in msg for keyword in ["日记", "记录", "写点", "diary"]):
            return "写心情日记是一个很好的习惯，可以帮助你梳理情绪、发现规律。今天想记录些什么呢？无论是开心的事还是烦恼的事，都可以写下来。"

        # 默认温暖回复
        return "我在听，你可以慢慢说。无论今天遇到了什么，你的感受都是重要的。想聊聊让你印象最深的一件事吗？"

    # ------------------------------------------------------------------
    # 配置管理方法
    # ------------------------------------------------------------------

    async def get_config(self) -> dict[str, Any]:
        """获取情绪陪伴模式的可配置项.

        Returns:
            配置字典
        """
        return {
            "default_mood_view": {
                "name": "默认情绪视图",
                "description": "进入模式时默认显示的情绪视图",
                "type": "select",
                "value": "overview",
                "options": [
                    {"value": "overview", "label": "概览"},
                    {"value": "week", "label": "本周情绪"},
                    {"value": "month", "label": "本月趋势"},
                ],
            },
            "daily_reminder": {
                "name": "每日情绪提醒",
                "description": "是否开启每日情绪记录提醒",
                "type": "boolean",
                "value": True,
            },
            "reminder_time": {
                "name": "提醒时间",
                "description": "每日情绪记录提醒的时间",
                "type": "string",
                "value": "21:00",
            },
            "relax_auto_play": {
                "name": "放松内容自动播放",
                "description": "进入放松引导时是否自动播放",
                "type": "boolean",
                "value": False,
            },
        }
