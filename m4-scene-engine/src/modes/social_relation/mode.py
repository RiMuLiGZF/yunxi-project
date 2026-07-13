"""人际关系模式 - 模式类.

实现 BaseMode 基类接口，提供人际关系模式的生命周期管理、
消息处理和配置管理功能。
"""

from __future__ import annotations

from typing import Any

from src.database import get_session
from src.modes.base_mode import BaseMode
from src.modes.social_relation.service import SocialService

import structlog

logger = structlog.get_logger(__name__)


class SocialRelationMode(BaseMode):
    """人际关系模式类.

    提供社交技巧建议、关系维护指导、沟通能力提升等人际关系相关功能。

    功能模块:
        - 联系人管理：增删改查联系人，记录关系类型和亲密度
        - 交往记录：记录与联系人的互动历史
        - 社交提醒：生日、纪念日、久未联系等提醒
        - 关系图谱：可视化人际关系网络
        - 情商提升：情商课程和评分系统
    """

    # 模式基本信息
    mode_id = "social_relation"
    mode_name = "人际关系"
    mode_description = "社交技巧、关系维护、沟通提升，经营美好人际关系"
    icon = "👥"
    category = "social"
    priority = 6
    is_enabled = True

    # -----------------------------------------------------------------------
    # 生命周期方法
    # -----------------------------------------------------------------------

    async def on_enter(self, context: dict[str, Any]) -> dict[str, Any]:
        """进入人际关系模式.

        加载社交概览数据，展示欢迎信息和今日社交建议。

        Args:
            context: 上下文字典，包含 user_id 等信息

        Returns:
            进入模式结果字典
        """
        user_id = context.get("user_id", "default")

        try:
            db = get_session()
            service = SocialService(db, user_id=str(user_id))
            overview = service.get_overview()
            stats = overview.get("stats", {})
            top_contacts = overview.get("top_contacts", [])

            # 生成欢迎语
            contact_count = stats.get("total_contacts", 0)
            week_interactions = stats.get("week_interactions", 0)
            welcome_msg = (
                f"欢迎来到「人际关系」模式！\n"
                f"你目前有 {contact_count} 位联系人，"
                f"本周已有 {week_interactions} 次社交互动。\n"
            )

            if top_contacts:
                names = "、".join([c["name"] for c in top_contacts])
                welcome_msg += f"你最亲密的好友是：{names}。\n"

            welcome_msg += "有什么我可以帮你的吗？"

            return {
                "success": True,
                "message": f"已进入「{self.mode_name}」模式",
                "data": {
                    "overview": overview,
                    "welcome_message": welcome_msg,
                },
                "context_updates": {
                    "current_mode": self.mode_id,
                    "social_stats": stats,
                },
            }
        except Exception as e:
            logger.error("on_enter 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
            return {
                "success": True,
                "message": f"已进入「{self.mode_name}」模式",
                "data": {
                    "welcome_message": "欢迎来到「人际关系」模式！有什么我可以帮你的吗？",
                },
                "context_updates": {
                    "current_mode": self.mode_id,
                },
            }

    async def on_leave(self, context: dict[str, Any]) -> dict[str, Any]:
        """离开人际关系模式.

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
        支持的意图：查看联系人、添加联系人、查看提醒、查看情商等。

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
            service = SocialService(db, user_id=str(user_id))

            if any(kw in msg for kw in ["概览", "概况", "总览", "统计"]):
                overview = service.get_overview()
                stats = overview["stats"]
                reply = (
                    f"📊 人际关系概览：\n"
                    f"• 联系人总数：{stats['total_contacts']} 位\n"
                    f"• 交往记录总数：{stats['total_interactions']} 次\n"
                    f"• 平均亲密度：{stats['avg_closeness']} 分\n"
                    f"• 本周互动：{stats['week_interactions']} 次\n"
                    f"• 情商得分：{stats['eq_score']} 分"
                )
                action_data = {"type": "overview", "data": overview}

            elif any(kw in msg for kw in ["联系人", "好友", "朋友"]):
                contacts = service.list_contacts()
                contact_list = "、".join([c["name"] for c in contacts[:10]])
                reply = f"👥 你共有 {len(contacts)} 位联系人：\n{contact_list}"
                if len(contacts) > 10:
                    reply += f"等 {len(contacts)} 人"
                action_data = {"type": "contacts", "data": contacts}

            elif any(kw in msg for kw in ["提醒", "生日", "纪念日"]):
                reminders = service.list_reminders()
                pending = [r for r in reminders if r["status"] == "pending"]
                if pending:
                    reply = f"⏰ 你有 {len(pending)} 条待办提醒：\n"
                    for r in pending[:5]:
                        reply += f"• [{r['priority']}] {r['title']}（{r['date']}）\n"
                else:
                    reply = "🎉 目前没有待办提醒，一切尽在掌握！"
                action_data = {"type": "reminders", "data": reminders}

            elif any(kw in msg for kw in ["情商", "EQ", "eq", "课程"]):
                eq_data = service.get_eq_score()
                courses = service.list_eq_courses()
                reply = (
                    f"🧠 你的情商得分为 {eq_data['score']} 分（{eq_data['level']}）\n"
                    f"当前正在学习 {len(courses)} 门情商课程"
                )
                action_data = {"type": "eq", "data": {"score": eq_data, "courses": courses}}

            elif any(kw in msg for kw in ["图谱", "关系图", "网络"]):
                graph = service.build_relation_graph()
                node_count = len(graph["nodes"]) - 1  # 减去中心节点
                reply = f"🕸️ 你的人际关系网络共有 {node_count} 个节点，关系图谱已生成。"
                action_data = {"type": "graph", "data": graph}

            else:
                # 默认回复
                reply = (
                    f"我可以帮你管理人际关系哦！你可以试试：\n"
                    f"• 查看「概览」了解社交状态\n"
                    f"• 查看「联系人」列表\n"
                    f"• 查看「提醒」事项\n"
                    f"• 查看「情商」评分和课程\n"
                    f"• 查看「关系图谱」\n"
                    f"也可以直接说「添加联系人」来新建联系人～"
                )
                action_data = {"type": "help", "data": {}}

        except Exception as e:
            logger.error("handle_message 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
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
        """获取人际关系模式配置.

        Returns:
            配置项字典
        """
        return {
            "default_relation": {
                "name": "默认关系类型",
                "description": "新建联系人时的默认关系类型",
                "type": "select",
                "value": "朋友",
                "options": [
                    "家人", "朋友", "同事", "同学",
                    "导师", "合作伙伴", "其他",
                ],
            },
            "reminder_enabled": {
                "name": "启用社交提醒",
                "description": "是否开启生日、纪念日等社交提醒",
                "type": "boolean",
                "value": True,
            },
            "eq_course_enabled": {
                "name": "启用情商课程",
                "description": "是否展示情商提升课程模块",
                "type": "boolean",
                "value": True,
            },
            "graph_visibility": {
                "name": "关系图谱可见性",
                "description": "是否在首页展示关系图谱",
                "type": "boolean",
                "value": True,
            },
        }
