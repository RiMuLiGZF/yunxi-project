"""复盘总结模式 - 模式类.

实现 BaseMode 基类接口，提供复盘总结模式的生命周期管理、
消息处理和配置管理功能。
"""

from __future__ import annotations

from typing import Any

from src.database import get_session
from src.modes.base_mode import BaseMode
from src.modes.review.service import ReviewService


class ReviewMode(BaseMode):
    """复盘总结模式类.

    提供日报/周报/月报生成、情绪追踪、决策回溯、
    认知偏差检测、私密日记等复盘总结相关功能。

    功能模块:
        - 复盘记录：日报、周报、月报的生成与管理
        - 情绪追踪：记录每日情绪，分析情绪趋势
        - 决策回溯：记录重要决策，复盘决策过程
        - 认知偏差：检测决策文本中的认知偏差
        - 私密日记：记录个人思考与感悟
    """

    # 模式基本信息
    mode_id = "review"
    mode_name = "复盘总结"
    mode_description = "每日复盘、周总结、目标回顾，沉淀经验持续成长"
    icon = "📝"
    category = "review"
    priority = 3
    is_enabled = True

    # -----------------------------------------------------------------------
    # 生命周期方法
    # -----------------------------------------------------------------------

    async def on_enter(self, context: dict[str, Any]) -> dict[str, Any]:
        """进入复盘总结模式.

        加载复盘概览数据，展示欢迎信息和今日复盘建议。

        Args:
            context: 上下文字典，包含 user_id 等信息

        Returns:
            进入模式结果字典
        """
        user_id = context.get("user_id", "default")

        try:
            db = get_session()
            service = ReviewService(db, user_id=str(user_id))
            overview = service.get_overview()
            stats = overview.get("stats", {})
            recent_reviews = overview.get("recent_reviews", [])

            # 生成欢迎语
            total_reviews = stats.get("total_reviews", 0)
            streak_days = stats.get("streak_days", 0)
            welcome_msg = (
                f"欢迎来到「复盘总结」模式！\n"
                f"你已累计完成 {total_reviews} 篇复盘，"
                f"连续打卡 {streak_days} 天。\n"
            )

            if recent_reviews:
                titles = "、".join([r["title"] for r in recent_reviews[:3]])
                welcome_msg += f"最近的复盘：{titles}。\n"

            welcome_msg += "今天想复盘些什么呢？"

            return {
                "success": True,
                "message": f"已进入「{self.mode_name}」模式",
                "data": {
                    "overview": overview,
                    "welcome_message": welcome_msg,
                },
                "context_updates": {
                    "current_mode": self.mode_id,
                    "review_stats": stats,
                },
            }
        except Exception as e:
            print(f"[Review] on_enter 异常: {e}")
            return {
                "success": True,
                "message": f"已进入「{self.mode_name}」模式",
                "data": {
                    "welcome_message": "欢迎来到「复盘总结」模式！有什么我可以帮你的吗？",
                },
                "context_updates": {
                    "current_mode": self.mode_id,
                },
            }

    async def on_leave(self, context: dict[str, Any]) -> dict[str, Any]:
        """离开复盘总结模式.

        保存当前状态，释放资源。

        Args:
            context: 上下文字典

        Returns:
            离开模式结果字典
        """
        return {
            "success": True,
            "message": f"已离开「{self.mode_name}」模式",
            "data": {},
        }

    # -----------------------------------------------------------------------
    # 消息处理方法
    # -----------------------------------------------------------------------

    async def handle_message(
        self,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理用户消息.

        根据用户输入进行简单的意图识别和响应。
        支持的意图：查看概览、写复盘、查看日记、情绪记录、决策记录等。

        Args:
            message: 用户输入的文本消息
            context: 当前上下文字典

        Returns:
            消息处理结果字典
        """
        user_id = context.get("user_id", "default")
        msg = message.strip()

        # 简单意图识别
        reply = ""
        action_data: dict[str, Any] = {}

        try:
            db = get_session()
            service = ReviewService(db, user_id=str(user_id))

            if any(kw in msg for kw in ["概览", "概况", "总览", "统计"]):
                overview = service.get_overview()
                stats = overview["stats"]
                reply = (
                    f"📊 复盘总结概览：\n"
                    f"• 复盘总数：{stats['total_reviews']} 篇\n"
                    f"• 日记总数：{stats['total_diaries']} 篇\n"
                    f"• 决策记录：{stats['total_decisions']} 条\n"
                    f"• 情绪记录：{stats['total_emotions']} 条\n"
                    f"• 本周复盘：{stats['week_reviews']} 篇\n"
                    f"• 连续打卡：{stats['streak_days']} 天"
                )
                action_data = {"type": "overview", "data": overview}

            elif any(kw in msg for kw in ["复盘", "日报", "周报", "月报", "总结"]):
                reviews = service.list_reviews(limit=10)
                if reviews:
                    reply = f"📝 你共有 {len(reviews)} 篇复盘记录：\n"
                    for r in reviews[:5]:
                        reply += f"• {r['title']}\n"
                    if len(reviews) > 5:
                        reply += f"... 还有 {len(reviews) - 5} 篇"
                else:
                    reply = "还没有复盘记录，开始写你的第一篇复盘吧！"
                action_data = {"type": "reviews", "data": reviews}

            elif any(kw in msg for kw in ["日记", "记录", "私密日记"]):
                diaries = service.list_diaries(limit=10)
                if diaries:
                    reply = f"📔 你共有 {len(diaries)} 篇日记：\n"
                    for d in diaries[:5]:
                        reply += f"• {d['title']}\n"
                    if len(diaries) > 5:
                        reply += f"... 还有 {len(diaries) - 5} 篇"
                else:
                    reply = "还没有日记记录，开始记录你的第一篇日记吧！"
                action_data = {"type": "diaries", "data": diaries}

            elif any(kw in msg for kw in ["情绪", "心情", "感受"]):
                emotion_stats = service.get_emotion_stats(days=30)
                dominant = emotion_stats.get("dominant_emotion", "neutral")
                avg_level = emotion_stats.get("avg_level", 0)
                reply = (
                    f"💗 最近 30 天情绪统计：\n"
                    f"• 总记录数：{emotion_stats['total_records']} 条\n"
                    f"• 主导情绪：{dominant}\n"
                    f"• 平均强度：{avg_level} 分\n"
                )
                action_data = {"type": "emotions", "data": emotion_stats}

            elif any(kw in msg for kw in ["决策", "选择", "决定"]):
                decisions = service.list_decisions(limit=10)
                if decisions:
                    reply = f"🤔 你共有 {len(decisions)} 条决策记录：\n"
                    for d in decisions[:5]:
                        reply += f"• {d['title']}（{d['status']}）\n"
                    if len(decisions) > 5:
                        reply += f"... 还有 {len(decisions) - 5} 条"
                else:
                    reply = "还没有决策记录，开始记录你的第一个重要决策吧！"
                action_data = {"type": "decisions", "data": decisions}

            elif any(kw in msg for kw in ["偏差", "认知", "分析"]):
                biases = service.list_biases()
                reply = f"🧠 已检测的认知偏差共 {len(biases)} 种，\n你可以发送一段决策描述，我来帮你分析其中可能存在的认知偏差。"
                action_data = {"type": "biases", "data": biases}

            elif any(kw in msg for kw in ["模板", "格式"]):
                templates = service.get_templates()
                reply = "📋 可用的复盘模板：\n"
                for t in templates:
                    reply += f"• {t['icon']} {t['name']}：{t['description']}\n"
                action_data = {"type": "templates", "data": templates}

            else:
                # 默认回复
                reply = (
                    f"我可以帮你进行复盘总结哦！你可以试试：\n"
                    f"• 查看「概览」了解复盘状态\n"
                    f"• 查看「复盘」记录列表\n"
                    f"• 查看「日记」记录\n"
                    f"• 记录「情绪」状态\n"
                    f"• 查看「决策」记录\n"
                    f"• 分析「认知偏差」\n"
                    f"• 查看「模板」列表\n"
                    f"也可以直接说「写日报」来开始今天的复盘～"
                )
                action_data = {"type": "help", "data": {}}

        except Exception as e:
            print(f"[Review] handle_message 异常: {e}")
            reply = "抱歉，处理你的消息时出现了问题，请稍后再试。"
            action_data = {"type": "error", "data": {"error": str(e)}}

        return {
            "success": True,
            "reply": reply,
            "data": action_data,
            "context_updates": {},
        }

    # -----------------------------------------------------------------------
    # 配置管理方法
    # -----------------------------------------------------------------------

    async def get_config(self) -> dict[str, Any]:
        """获取复盘总结模式配置.

        Returns:
            配置项字典
        """
        return {
            "default_review_type": {
                "name": "默认复盘类型",
                "description": "新建复盘时的默认类型",
                "type": "select",
                "value": "daily",
                "options": [
                    {"value": "daily", "label": "日报"},
                    {"value": "weekly", "label": "周报"},
                    {"value": "monthly", "label": "月报"},
                ],
            },
            "reminder_enabled": {
                "name": "启用复盘提醒",
                "description": "是否开启每日复盘提醒",
                "type": "boolean",
                "value": True,
            },
            "emotion_tracking_enabled": {
                "name": "启用情绪追踪",
                "description": "是否展示情绪追踪模块",
                "type": "boolean",
                "value": True,
            },
            "decision_review_enabled": {
                "name": "启用决策回溯",
                "description": "是否展示决策回溯模块",
                "type": "boolean",
                "value": True,
            },
            "bias_detection_enabled": {
                "name": "启用认知偏差检测",
                "description": "是否展示认知偏差检测模块",
                "type": "boolean",
                "value": True,
            },
            "diary_enabled": {
                "name": "启用私密日记",
                "description": "是否展示私密日记模块",
                "type": "boolean",
                "value": True,
            },
        }
