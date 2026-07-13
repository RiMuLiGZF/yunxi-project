"""形象工坊 - 模式类.

实现 BaseMode 基类接口，提供形象工坊模式的生命周期管理
和消息处理功能。
"""

from __future__ import annotations

from typing import Any

import structlog

from src.modes.base_mode import BaseMode

logger = structlog.get_logger(__name__)


class AppearanceMode(BaseMode):
    """形象工坊模式类.

    提供穿搭建议、形象设计、风格探索、
    美妆护肤等个人形象相关功能。

    继承自 BaseMode，实现模式的生命周期管理、
    消息处理和配置管理。
    """

    mode_id = "appearance"
    mode_name = "形象工坊"
    mode_description = "穿搭建议、形象设计、风格探索，打造个人独特形象"
    icon = "👗"
    category = "appearance"
    priority = 8
    is_enabled = True

    # ------------------------------------------------------------------
    # 生命周期方法
    # ------------------------------------------------------------------

    async def on_enter(self, context: dict[str, Any]) -> dict[str, Any]:
        """进入形象工坊模式.

        加载用户形象配置，展示当前形象状态，
        提供形象工坊的功能入口。

        Args:
            context: 进入模式时的上下文字典

        Returns:
            进入模式的结果字典
        """
        user_id = context.get("user_id", "default")

        # 延迟导入，避免循环依赖
        from src.models.db import get_session
        from src.modes.appearance.service import AppearanceService

        try:
            db = get_session()
            service = AppearanceService(db, user_id=user_id)
            config = service.get_config()
            relationship = service.get_relationship()
            db.close()
        except Exception as e:
            logger.warning("appearance_mode.load_config_failed", user_id=user_id,
                           error_type=type(e).__name__, error=str(e))
            config = {}
            relationship = {}

        return {
            "success": True,
            "message": "欢迎来到形象工坊，让我们一起打造专属于你的独特形象吧！",
            "data": {
                "config": config,
                "relationship": relationship,
                "features": [
                    {"id": "theme", "name": "主题切换", "icon": "🎨"},
                    {"id": "mood", "name": "心情状态", "icon": "😊"},
                    {"id": "personality", "name": "性格标签", "icon": "✨"},
                    {"id": "voice", "name": "声音设置", "icon": "🔊"},
                    {"id": "snapshot", "name": "形象快照", "icon": "📸"},
                ],
            },
            "context_updates": {
                "current_mode": "appearance",
                "appearance_config": config,
            },
        }

    async def on_leave(self, context: dict[str, Any]) -> dict[str, Any]:
        """离开形象工坊模式.

        保存形象配置状态，准备切换到其他模式。

        Args:
            context: 离开模式时的上下文字典

        Returns:
            离开模式的结果字典
        """
        return {
            "success": True,
            "message": "已离开形象工坊，你的形象设置已保存。",
            "data": {},
            "context_updates": {
                "previous_mode": "appearance",
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
        """处理用户在形象工坊模式下的消息.

        根据用户输入提供形象相关的建议和互动。

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
                "mode": "appearance",
                "message_type": "chat",
            },
            "context_updates": {},
        }

    def _generate_reply(self, message: str) -> str:
        """根据用户消息生成回复.

        Args:
            message: 用户输入的消息

        Returns:
            回复文本
        """
        msg = message.lower()

        if any(keyword in msg for keyword in ["主题", "换个主题", "theme"]):
            return "我们有多种精美主题可供选择：默认主题、海洋之心、落日余晖、森林秘境、樱花物语、午夜星辰。你可以在主题设置中一键切换哦！"

        if any(keyword in msg for keyword in ["心情", "mood", "情绪"]):
            return "我能感知到你的心情变化~ 当前支持的心情状态有：开心、平静、兴奋、困倦、难过、生气。不同心情会呈现不同的粒子效果呢！"

        if any(keyword in msg for keyword in ["性格", "标签", "人格"]):
            return "每个人都有独特的性格魅力！你可以在性格标签中选择最符合你的特质，比如温柔、智慧、幽默、理性等等。"

        if any(keyword in msg for keyword in ["声音", "语音", "voice"]):
            return "我有多种声音类型可以切换：温暖女声、清澈女声、温柔男声、可爱童声、机械音。你喜欢哪一种呢？"

        if any(keyword in msg for keyword in ["关系", "亲密", "羁绊", "好感"]):
            return "我们的关系会随着陪伴逐渐加深哦！从初识到朋友、挚友、灵魂伴侣，最后达到永恒羁绊。多多互动就能提升亲密度~"

        if any(keyword in msg for keyword in ["穿搭", "穿什么", "搭配"]):
            return "穿搭是表达自我的好方式！根据场合和心情选择合适的风格会让你更自信。需要我帮你参考今天的穿搭吗？"

        return "我在形象工坊随时为你服务~ 你可以尝试切换主题、调整心情、设置性格标签，或者保存喜欢的形象快照。有什么想调整的吗？"

    # ------------------------------------------------------------------
    # 配置管理方法
    # ------------------------------------------------------------------

    async def get_config(self) -> dict[str, Any]:
        """获取形象工坊模式的可配置项.

        Returns:
            配置字典
        """
        return {
            "default_theme": {
                "name": "默认主题",
                "description": "进入模式时默认使用的主题",
                "type": "select",
                "value": "default",
                "options": [
                    {"value": "default", "label": "默认主题"},
                    {"value": "ocean", "label": "海洋之心"},
                    {"value": "sunset", "label": "落日余晖"},
                    {"value": "forest", "label": "森林秘境"},
                    {"value": "sakura", "label": "樱花物语"},
                    {"value": "midnight", "label": "午夜星辰"},
                ],
            },
            "particle_count": {
                "name": "粒子数量",
                "description": "形象粒子效果的数量",
                "type": "number",
                "value": 120,
            },
            "glow_intensity": {
                "name": "光晕强度",
                "description": "形象光晕效果的强度",
                "type": "number",
                "value": 0.8,
            },
            "voice_type": {
                "name": "默认声音",
                "description": "默认使用的声音类型",
                "type": "select",
                "value": "warm_female",
                "options": [
                    {"value": "warm_female", "label": "温暖女声"},
                    {"value": "clear_female", "label": "清澈女声"},
                    {"value": "gentle_male", "label": "温柔男声"},
                    {"value": "cute_child", "label": "可爱童声"},
                    {"value": "robot", "label": "机械音"},
                ],
            },
        }
