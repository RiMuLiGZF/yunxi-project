"""生活管理模式 - 模式类.

实现 BaseMode 基类接口，提供生活管理模式的生命周期管理、
消息处理和配置管理功能。
"""

from __future__ import annotations

from typing import Any

from src.models.db import get_session
from src.modes.base_mode import BaseMode
from src.modes.life_management.service import LifeService

import structlog

logger = structlog.get_logger(__name__)


class LifeManagementMode(BaseMode):
    """生活管理模式类.

    提供日程安排、待办事项、习惯打卡、财务管理、场景控制等
    生活管理相关功能。

    功能模块:
        - 日程管理：增删改查日程，支持按日期筛选
        - 待办事项：待办清单管理，状态跟踪
        - 习惯打卡：习惯养成，连续打卡记录
        - 场景模式：生活场景切换（居家/工作/运动/睡眠等）
        - 自动化规则：条件触发的自动化规则
        - 财务管理：收支记录，分类统计，预算管理
        - 生活助手：天气、出行、健康等实用工具
    """

    # 模式基本信息
    mode_id = "life_management"
    mode_name = "生活管理"
    mode_description = "日程安排、待办事项、习惯养成，管理生活方方面面"
    icon = "🏠"
    category = "life"
    priority = 4
    is_enabled = True

    # -----------------------------------------------------------------------
    # 生命周期方法
    # -----------------------------------------------------------------------

    async def on_enter(self, context: dict[str, Any]) -> dict[str, Any]:
        """进入生活管理模式.

        加载生活概览数据，展示欢迎信息和今日提醒。

        Args:
            context: 上下文字典，包含 user_id 等信息

        Returns:
            进入模式结果字典
        """
        user_id = context.get("user_id", "default")

        try:
            db = get_session()
            service = LifeService(db, user_id=str(user_id))
            overview = service.get_overview()
            stats = overview.get("stats", {})
            current_scene = overview.get("current_scene", {})

            # 生成欢迎语
            todo_total = stats.get("todo_total", 0)
            todo_done = stats.get("todo_done", 0)
            habit_done = stats.get("habit_done", 0)
            habit_total = stats.get("habit_total", 0)
            scene_name = current_scene.get("name", "居家模式") if current_scene else "居家模式"

            welcome_msg = (
                f"欢迎来到「生活管理」模式！\n"
                f"当前场景：{scene_name}\n"
                f"今日待办：已完成 {todo_done}/{todo_total} 项\n"
                f"今日习惯：已打卡 {habit_done}/{habit_total} 个\n"
            )

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
                    "life_stats": stats,
                },
            }
        except Exception as e:
            logger.error("on_enter 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
            return {
                "success": True,
                "message": f"已进入「{self.mode_name}」模式",
                "data": {
                    "welcome_message": "欢迎来到「生活管理」模式！有什么我可以帮你的吗？",
                },
                "context_updates": {
                    "current_mode": self.mode_id,
                },
            }

    async def on_leave(self, context: dict[str, Any]) -> dict[str, Any]:
        """离开生活管理模式.

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
        支持的意图：查看日程、查看待办、查看习惯、查看财务、切换场景等。

        Args:
            message: 用户输入的文本消息
            context: 当前上下文字典

        Returns:
            消息处理结果字典
        """
        user_id = context.get("user_id", "default")
        msg = message.strip()

        reply = ""
        action_data: dict[str, Any] = {}

        try:
            db = get_session()
            service = LifeService(db, user_id=str(user_id))

            if any(kw in msg for kw in ["概览", "概况", "总览", "统计"]):
                overview = service.get_overview()
                stats = overview["stats"]
                reply = (
                    f"📊 生活管理概览：\n"
                    f"• 待办事项：{stats['todo_done']}/{stats['todo_total']} 已完成\n"
                    f"• 习惯打卡：{stats['habit_done']}/{stats['habit_total']} 已完成\n"
                    f"• 今日日程：{stats['schedule_total']} 项\n"
                    f"• 今日支出：¥{stats['today_spending']}"
                )
                action_data = {"type": "overview", "data": overview}

            elif any(kw in msg for kw in ["日程", "安排", "时间表"]):
                schedules = service.list_schedules()
                schedule_list = "\n".join(
                    [f"  • [{s['tag']}] {s['time']} {s['title']}" for s in schedules[:5]]
                )
                reply = f"📅 你今日有 {len(schedules)} 个日程：\n{schedule_list}"
                if len(schedules) > 5:
                    reply += f"\n等 {len(schedules)} 项"
                action_data = {"type": "schedules", "data": schedules}

            elif any(kw in msg for kw in ["待办", "todo", "任务", "清单"]):
                todos = service.list_todos()
                todo_list = "\n".join(
                    [f"  • [{'✓' if t['status'] == 'done' else ' '}] {t['title']}"
                     for t in todos[:5]]
                )
                reply = f"✅ 你共有 {len(todos)} 个待办：\n{todo_list}"
                if len(todos) > 5:
                    reply += f"\n等 {len(todos)} 项"
                action_data = {"type": "todos", "data": todos}

            elif any(kw in msg for kw in ["习惯", "打卡", "坚持"]):
                habits = service.list_habits()
                habit_list = "\n".join(
                    [f"  • {'✅' if h['done'] else '⬜'} {h['icon']} {h['name']}（连续{h['streak']}天）"
                     for h in habits]
                )
                reply = f"🔥 你的习惯列表：\n{habit_list}"
                action_data = {"type": "habits", "data": habits}

            elif any(kw in msg for kw in ["财务", "钱", "支出", "消费", "预算"]):
                finance = service.get_finance_overview()
                reply = (
                    f"💰 财务概览：\n"
                    f"• 本月支出：¥{finance['total_expense']}\n"
                    f"• 本月收入：¥{finance['total_income']}\n"
                    f"• 预算使用：{finance['month_progress']}%\n"
                    f"• 今日支出：¥{finance['today_spending']}"
                )
                action_data = {"type": "finance", "data": finance}

            elif any(kw in msg for kw in ["场景", "模式"]):
                scenes = service.list_scenes()
                scene_list = "\n".join(
                    [f"  • {'🔴' if s['active'] else '⚪'} {s['icon']} {s['label']}"
                     for s in scenes]
                )
                reply = f"🏠 你的生活场景：\n{scene_list}\n你可以说「切换到工作模式」来切换场景～"
                action_data = {"type": "scenes", "data": scenes}

            elif any(kw in msg for kw in ["规则", "自动化"]):
                rules = service.list_rules()
                rule_list = "\n".join(
                    [f"  • {'✅' if r['enabled'] else '⬜'} {r['condition']} → {r['action']}"
                     for r in rules]
                )
                reply = f"⚙️ 你的自动化规则：\n{rule_list}"
                action_data = {"type": "rules", "data": rules}

            else:
                # 默认回复
                reply = (
                    f"我可以帮你管理生活哦！你可以试试：\n"
                    f"• 查看「概览」了解生活状态\n"
                    f"• 查看「日程」安排\n"
                    f"• 查看「待办」清单\n"
                    f"• 查看「习惯」打卡\n"
                    f"• 查看「财务」状况\n"
                    f"• 查看「场景」模式\n"
                    f"也可以直接说「添加待办」来新建任务～"
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
        """获取生活管理模式配置.

        Returns:
            配置项字典
        """
        return {
            "default_category": {
                "name": "默认待办分类",
                "description": "新建待办时的默认分类",
                "type": "select",
                "value": "今日待办",
                "options": [
                    "今日待办", "进行中", "已完成", "重要事项", "长期目标",
                ],
            },
            "habit_reminder_enabled": {
                "name": "习惯打卡提醒",
                "description": "是否开启习惯打卡提醒",
                "type": "boolean",
                "value": True,
            },
            "finance_budget_enabled": {
                "name": "预算管理",
                "description": "是否启用财务预算管理功能",
                "type": "boolean",
                "value": True,
            },
            "scene_auto_switch": {
                "name": "场景自动切换",
                "description": "是否根据时间自动切换场景",
                "type": "boolean",
                "value": False,
            },
            "week_start_day": {
                "name": "每周起始日",
                "description": "周视图的起始日期",
                "type": "select",
                "value": "周一",
                "options": ["周一", "周日"],
            },
        }
