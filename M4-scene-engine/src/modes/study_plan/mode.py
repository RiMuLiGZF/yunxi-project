"""学业规划模式 - 模式类.

实现 BaseMode 基类接口，提供学业规划模式的生命周期管理、
消息处理和配置管理功能。
"""

from __future__ import annotations

from typing import Any

from src.models.db import get_session
from src.modes.base_mode import BaseMode
from src.modes.study_plan.service import StudyService

import structlog

logger = structlog.get_logger(__name__)


class StudyPlanMode(BaseMode):
    """学业规划模式类.

    提供学习目标管理、学习计划安排、知识笔记整理、
    进度追踪、考试提醒等学业规划相关功能。

    功能模块:
        - 目标树管理：层级化学习目标，进度追踪
        - 学习计划：每日/每周学习计划安排
        - 知识笔记：分类整理学习笔记
        - 进度追踪：各科学习进度可视化
        - 考试提醒：考试倒计时和备考提醒
        - 风险矩阵：学习风险评估和管理
        - 方案对比：多种学习方案对比选择
        - 甘特图：学习计划时间线可视化
    """

    # 模式基本信息
    mode_id = "study_plan"
    mode_name = "学业规划"
    mode_description = "学习目标、知识笔记、进度追踪，打造高效学习系统"
    icon = "📚"
    category = "study"
    priority = 5
    is_enabled = True

    # -----------------------------------------------------------------------
    # 生命周期方法
    # -----------------------------------------------------------------------

    async def on_enter(self, context: dict[str, Any]) -> dict[str, Any]:
        """进入学业规划模式.

        加载学业概览数据，展示欢迎信息和今日学习提醒。

        Args:
            context: 上下文字典，包含 user_id 等信息

        Returns:
            进入模式结果字典
        """
        user_id = context.get("user_id", "default")

        try:
            db = get_session()
            service = StudyService(db, user_id=str(user_id))
            overview = service.get_overview()
            stats = overview.get("stats", {})
            banner = overview.get("banner", {})

            total_goals = stats.get("total_goals", 0)
            total_plans = stats.get("total_plans", 0)
            today_tasks = stats.get("today_tasks", 0)
            today_done = stats.get("today_done", 0)
            streak_days = stats.get("streak_days", 0)
            days_left = banner.get("days_left", 0)
            exam_name = banner.get("exam_name", "期末考试")

            welcome_msg = (
                f"欢迎来到「学业规划」模式！\n"
                f"📅 {exam_name}还有 {days_left} 天\n"
                f"📊 今日学习计划：已完成 {today_done}/{today_tasks} 项\n"
                f"🔥 连续学习：{streak_days} 天\n"
                f"🎯 目标总数：{total_goals} 个"
            )

            welcome_msg += "\n\n有什么我可以帮你的吗？"

            return {
                "success": True,
                "message": f"已进入「{self.mode_name}」模式",
                "data": {
                    "overview": overview,
                    "welcome_message": welcome_msg,
                },
                "context_updates": {
                    "current_mode": self.mode_id,
                    "study_stats": stats,
                },
            }
        except Exception as e:
            logger.error("on_enter 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
            return {
                "success": True,
                "message": f"已进入「{self.mode_name}」模式",
                "data": {
                    "welcome_message": "欢迎来到「学业规划」模式！有什么我可以帮你的吗？",
                },
                "context_updates": {
                    "current_mode": self.mode_id,
                },
            }

    async def on_leave(self, context: dict[str, Any]) -> dict[str, Any]:
        """离开学业规划模式.

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
        支持的意图：查看目标、查看计划、查看笔记、查看进度、查看考试等。

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
            service = StudyService(db, user_id=str(user_id))

            if any(kw in msg for kw in ["概览", "概况", "总览", "统计"]):
                overview = service.get_overview()
                stats = overview["stats"]
                banner = overview.get("banner", {})
                reply = (
                    f"📊 学业规划概览：\n"
                    f"• 学习目标：{stats['total_goals']} 个\n"
                    f"• 学习计划：{stats['total_plans']} 个\n"
                    f"• 学习笔记：{stats['total_notes']} 篇\n"
                    f"• 考试提醒：{stats['total_exams']} 个\n"
                    f"• 今日任务：{stats['today_done']}/{stats['today_tasks']} 已完成\n"
                    f"• 连续学习：{stats['streak_days']} 天"
                )
                if banner:
                    reply += f"\n• {banner.get('exam_name', '考试')}还有 {banner.get('days_left', 0)} 天"
                action_data = {"type": "overview", "data": overview}

            elif any(kw in msg for kw in ["目标", "goal"]):
                goals = service.get_goal_tree()
                goal_count = len(goals)
                reply = f"🎯 你共有 {goal_count} 个一级学习目标。\n"
                for g in goals[:5]:
                    progress = g.get("progress", 0)
                    status_icon = "✅" if progress >= 100 else "📈" if progress > 0 else "⏳"
                    reply += f"  {status_icon} {g.get('icon', '📚')} {g.get('label', '')}（{progress}%）\n"
                action_data = {"type": "goals", "data": goals}

            elif any(kw in msg for kw in ["计划", "schedule", "今日学习"]):
                plans = service.list_plans()
                plan_count = len(plans)
                done_count = sum(1 for p in plans if p.get("completed"))
                reply = f"📅 你今日有 {plan_count} 个学习计划，已完成 {done_count} 个：\n"
                for p in plans[:5]:
                    status = "✅" if p.get("completed") else "⬜"
                    reply += f"  {status} {p.get('start_time')}-{p.get('end_time')} {p.get('title')}\n"
                if plan_count > 5:
                    reply += f"等 {plan_count} 项"
                action_data = {"type": "plans", "data": plans}

            elif any(kw in msg for kw in ["笔记", "note"]):
                notes = service.list_notes()
                reply = f"📝 你共有 {len(notes)} 篇学习笔记：\n"
                for n in notes[:5]:
                    reply += f"  • [{n.get('category', '')}] {n.get('title', '')}（{n.get('date_label', '')}）\n"
                if len(notes) > 5:
                    reply += f"等 {len(notes)} 篇"
                action_data = {"type": "notes", "data": notes}

            elif any(kw in msg for kw in ["进度", "学习情况"]):
                progress = service.get_subject_progress()
                reply = "📈 各科学习进度：\n"
                for p in progress:
                    bar_len = int(p.get("progress", 0) / 10)
                    bar = "█" * bar_len + "░" * (10 - bar_len)
                    reply += f"  • {p.get('subject', '')}: [{bar}] {p.get('progress', 0)}%\n"
                action_data = {"type": "progress", "data": progress}

            elif any(kw in msg for kw in ["考试", "exam", "期末", "备考"]):
                exams = service.list_exams()
                reply = f"📝 你的考试安排：\n"
                for e in exams:
                    urgency = e.get("urgency", "")
                    exam_date = e.get("exam_date", "")
                    reply += f"  • [{urgency}] {e.get('name', '')} - {exam_date}\n"
                action_data = {"type": "exams", "data": exams}

            elif any(kw in msg for kw in ["周目标", "本周"]):
                weekly = service.get_weekly_goals()
                reply = "🎯 本周目标：\n"
                for g in weekly:
                    status = "✅" if g.get("completed") else "⬜"
                    reply += (
                        f"  {status} {g.get('category', '')}: "
                        f"{g.get('current', 0)}/{g.get('total', 0)} {g.get('unit', '')} "
                        f"({g.get('progress', 0)}%)\n"
                    )
                action_data = {"type": "weekly_goals", "data": weekly}

            else:
                reply = (
                    f"我可以帮你规划学业哦！你可以试试：\n"
                    f"• 查看「概览」了解学习状态\n"
                    f"• 查看「目标」树\n"
                    f"• 查看「计划」安排\n"
                    f"• 查看「笔记」知识库\n"
                    f"• 查看「进度」追踪\n"
                    f"• 查看「考试」提醒\n"
                    f"也可以直接说「添加学习计划」来新建计划～"
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
        """获取学业规划模式配置.

        Returns:
            配置项字典
        """
        return {
            "pomodoro_duration": {
                "name": "番茄钟时长",
                "description": "单个番茄钟的时长（分钟）",
                "type": "number",
                "value": 25,
                "min": 15,
                "max": 60,
            },
            "break_duration": {
                "name": "休息时长",
                "description": "番茄钟之间的休息时长（分钟）",
                "type": "number",
                "value": 5,
                "min": 3,
                "max": 15,
            },
            "daily_goal_hours": {
                "name": "每日学习目标",
                "description": "每日学习时长目标（小时）",
                "type": "number",
                "value": 6,
                "min": 1,
                "max": 16,
            },
            "exam_reminder_days": {
                "name": "考试提前提醒",
                "description": "考试前多少天开始提醒",
                "type": "number",
                "value": 30,
                "min": 7,
                "max": 90,
            },
            "weekly_review_enabled": {
                "name": "周复盘提醒",
                "description": "是否开启每周学习复盘提醒",
                "type": "boolean",
                "value": True,
            },
            "default_subject": {
                "name": "默认科目",
                "description": "新建计划时的默认科目",
                "type": "select",
                "value": "数学",
                "options": ["数学", "英语", "语文", "物理", "化学", "计算机", "其他"],
            },
        }
