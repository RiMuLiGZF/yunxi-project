"""成长中心模式 - 模式类.

实现 BaseMode 基类接口，提供成长中心模式的生命周期管理、
消息处理和配置管理功能。
作为 M5 成长系统的业务壳层，不重复存储数据。
"""

from __future__ import annotations

from typing import Any

from src.modes.base_mode import BaseMode
from src.modes.growth.service import GrowthService

import structlog

logger = structlog.get_logger(__name__)


class GrowthMode(BaseMode):
    """成长中心模式类.

    记录成长轨迹、解锁成就天赋、追踪赛季进度，
    提供完整的游戏化成长体验。
    作为 M5 成长系统的业务壳层，封装 M5 API 并提供场景联动。

    功能模块:
        - 成就勋章殿堂：收集各种成就与勋章
        - 心智天赋树：四分支天赋升级系统
        - 潮汐专属历法：打卡记录心情精力
        - 地球Online编年史：记录人生重要纪事
        - 记忆回响对比：对比成长前后的变化
        - 赛季征程系统：赛季任务与奖励机制
    """

    # 模式基本信息
    mode_id = "growth"
    mode_name = "成长中心"
    mode_description = "记录成长轨迹，解锁成就天赋，见证每一步进步"
    icon = "🌱"
    category = "growth"
    priority = 1
    is_enabled = True

    # -----------------------------------------------------------------------
    # 生命周期方法
    # -----------------------------------------------------------------------

    async def on_enter(self, context: dict[str, Any]) -> dict[str, Any]:
        """进入成长中心模式.

        加载成长概览数据，展示欢迎信息和今日成长提醒。

        Args:
            context: 上下文字典，包含 user_id 等信息

        Returns:
            进入模式结果字典
        """
        user_id = context.get("user_id", "default")

        try:
            service = GrowthService(user_id=str(user_id))
            overview = await service.get_overview()

            achievement_stats = overview.get("achievement_stats", {})
            talent_points = overview.get("talent_points", {})
            calendar_stats = overview.get("calendar_stats", {})
            current_season = overview.get("current_season", {})
            today_checked = overview.get("today_checked_in", False)

            total_achievements = achievement_stats.get("total", 0)
            unlocked_achievements = achievement_stats.get("unlocked", 0)
            available_points = talent_points.get("available_points", 0)
            streak_days = calendar_stats.get("streak", 0)
            season_name = current_season.get("name", "当前赛季")
            season_progress = current_season.get("progress", 0)
            season_days_left = current_season.get("days_left", 0)

            checkin_hint = "✅ 今日已打卡" if today_checked else "📝 今日还未打卡"

            welcome_msg = (
                f"欢迎来到「成长中心」！🌱\n"
                f"{checkin_hint}\n\n"
                f"🏆 成就：{unlocked_achievements}/{total_achievements} 已解锁\n"
                f"✨ 天赋点：{available_points} 点可用\n"
                f"🔥 连续打卡：{streak_days} 天\n"
                f"⚔️ {season_name}：{season_progress}%（剩余 {season_days_left} 天）"
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
                    "growth_stats": {
                        "unlocked_achievements": unlocked_achievements,
                        "available_points": available_points,
                        "streak_days": streak_days,
                    },
                },
            }
        except Exception as e:
            logger.error("on_enter 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
            return {
                "success": True,
                "message": f"已进入「{self.mode_name}」模式",
                "data": {
                    "welcome_message": "欢迎来到「成长中心」模式！有什么我可以帮你的吗？",
                },
                "context_updates": {
                    "current_mode": self.mode_id,
                },
            }

    async def on_leave(self, context: dict[str, Any]) -> dict[str, Any]:
        """离开成长中心模式.

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

        根据用户输入进行意图识别和响应。
        支持的意图：概览、成就、天赋、打卡/日历、赛季、编年史、回响等。

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
            service = GrowthService(user_id=str(user_id))

            if any(kw in msg for kw in ["概览", "概况", "总览", "统计", "成长"]):
                overview = await service.get_overview()
                ach_stats = overview["achievement_stats"]
                tal_points = overview["talent_points"]
                cal_stats = overview["calendar_stats"]
                season = overview["current_season"]
                reply = (
                    f"📊 成长中心概览：\n"
                    f"• 成就：{ach_stats.get('unlocked', 0)}/{ach_stats.get('total', 0)} 已解锁\n"
                    f"• 天赋点：{tal_points.get('available_points', 0)} 点可用\n"
                    f"• 打卡率：{cal_stats.get('checkin_rate', 0):.1f}%\n"
                    f"• 连续打卡：{cal_stats.get('streak', 0)} 天\n"
                    f"• 当前赛季：{season.get('name', '无')}（{season.get('progress', 0)}%）"
                )
                action_data = {"type": "overview", "data": overview}

            elif any(kw in msg for kw in ["成就", "勋章", "achievement"]):
                achievements = await service.list_achievements()
                items = achievements.get("items", [])
                total = achievements.get("total", len(items))
                unlocked_count = sum(1 for a in items if a.get("unlocked"))
                reply = f"🏆 成就殿堂：已解锁 {unlocked_count}/{total} 个成就\n"
                for a in items[:6]:
                    status_icon = "✅" if a.get("unlocked") else "🔒"
                    rarity = a.get("rarity_text", "")
                    reply += f"  {status_icon} [{rarity}] {a.get('name', '')}\n"
                if total > 6:
                    reply += f"等 {total} 个成就"
                action_data = {"type": "achievements", "data": achievements}

            elif any(kw in msg for kw in ["天赋", "talent"]):
                tree_data = await service.get_talent_tree()
                points = tree_data.get("available_points", 0)
                spent = tree_data.get("spent_points", 0)
                branches = tree_data.get("stats", {})
                reply = f"🌳 天赋树：可用 {points} 点，已投入 {spent} 点\n"
                branch_names = {
                    "mind": "心智", "emotion": "稳态",
                    "creativity": "创造", "experience": "阅历",
                }
                for key, name in branch_names.items():
                    b = branches.get(key, {})
                    reply += f"  • {name}：{b.get('unlocked', 0)}/{b.get('total', 0)} 节点\n"
                action_data = {"type": "talents", "data": tree_data}

            elif any(kw in msg for kw in ["打卡", "日历", "calendar", "checkin", "签到"]):
                if "打卡" in msg and ("今日" in msg or "今天" in msg or msg.strip() == "打卡"):
                    # 执行打卡
                    result = await service.checkin(mood=8, energy=7)
                    if result.get("success"):
                        reply = (
                            f"✅ 打卡成功！\n"
                            f"📅 {result.get('date', '')}\n"
                            f"🔥 连续打卡第 {result.get('streak', 0)} 天\n"
                            f"✨ 获得 {result.get('points_earned', 0)} 天赋点"
                        )
                    else:
                        reply = f"打卡失败：{result.get('message', '未知错误')}"
                    action_data = {"type": "checkin", "data": result}
                else:
                    cal_stats = await service.get_calendar_stats()
                    reply = (
                        f"📅 潮汐历法统计：\n"
                        f"• 总打卡：{cal_stats.get('checked_days', 0)}/{cal_stats.get('total_days', 0)} 天\n"
                        f"• 打卡率：{cal_stats.get('checkin_rate', 0):.1f}%\n"
                        f"• 连续打卡：{cal_stats.get('streak', 0)} 天\n"
                        f"• 平均心情：{cal_stats.get('avg_mood', 0):.1f}/10\n"
                        f"• 平均精力：{cal_stats.get('avg_energy', 0):.1f}/10"
                    )
                    action_data = {"type": "calendar", "data": cal_stats}

            elif any(kw in msg for kw in ["赛季", "任务", "season", "task"]):
                season = await service.get_current_season()
                tasks = await service.list_season_tasks()
                task_items = tasks.get("items", [])
                reply = (
                    f"⚔️ {season.get('name', '当前赛季')}\n"
                    f"📈 进度：{season.get('progress', 0)}%（剩余 {season.get('days_left', 0)} 天）\n"
                    f"📋 任务：{len(task_items)} 个进行中\n"
                )
                for t in task_items[:5]:
                    status_map = {
                        "completed": "✅", "pending": "⬜",
                        "in-progress": "🔄", "claimed": "🎁",
                    }
                    icon = status_map.get(t.get("status", ""), "⬜")
                    reply += f"  {icon} {t.get('title', '')}（+{t.get('points', 0)}点）\n"
                action_data = {"type": "season", "data": {"season": season, "tasks": tasks}}

            elif any(kw in msg for kw in ["编年史", "纪事", "chronicle"]):
                chronicles = await service.list_chronicles()
                items = chronicles.get("items", [])
                total = chronicles.get("total", len(items))
                reply = f"📜 地球Online编年史：共 {total} 条纪事\n"
                for c in items[:5]:
                    cat = c.get("category_text", "")
                    diff = c.get("difficulty", "")
                    reply += f"  • [{cat}-{diff}] {c.get('title', '')}（{c.get('date', '')}）\n"
                if total > 5:
                    reply += f"等 {total} 条纪事"
                action_data = {"type": "chronicle", "data": chronicles}

            elif any(kw in msg for kw in ["回响", "echo", "对比"]):
                echoes = await service.list_echoes()
                items = echoes.get("items", [])
                total = echoes.get("total", len(items))
                reply = f"💭 记忆回响：共 {total} 篇\n"
                for e in items[:5]:
                    cat = e.get("category_text", "")
                    reply += f"  • [{cat}] {e.get('title', '')}\n"
                if total > 5:
                    reply += f"等 {total} 篇回响"
                action_data = {"type": "echo", "data": echoes}

            else:
                reply = (
                    f"我可以帮你管理成长系统哦！你可以试试：\n"
                    f"• 查看「概览」了解成长状态\n"
                    f"• 查看「成就」勋章殿堂\n"
                    f"• 查看「天赋」树进度\n"
                    f"• 「打卡」记录今日状态\n"
                    f"• 查看「赛季」任务进度\n"
                    f"• 查看「编年史」记录\n"
                    f"• 查看「回响」成长对比\n"
                    f"也可以直接说「今日打卡」来快速打卡～"
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
        """获取成长中心模式配置.

        Returns:
            配置项字典
        """
        return {
            "daily_checkin_reminder": {
                "name": "每日打卡提醒",
                "description": "是否开启每日打卡提醒",
                "type": "boolean",
                "value": True,
            },
            "achievement_notification": {
                "name": "成就解锁通知",
                "description": "解锁成就时是否弹出通知",
                "type": "boolean",
                "value": True,
            },
            "season_task_reminder": {
                "name": "赛季任务提醒",
                "description": "赛季任务更新时是否提醒",
                "type": "boolean",
                "value": True,
            },
            "default_view": {
                "name": "默认视图",
                "description": "进入成长中心时默认显示的页面",
                "type": "select",
                "value": "overview",
                "options": [
                    {"value": "overview", "label": "成长概览"},
                    {"value": "achievements", "label": "成就殿堂"},
                    {"value": "talents", "label": "天赋树"},
                    {"value": "calendar", "label": "潮汐历法"},
                    {"value": "season", "label": "赛季征程"},
                ],
            },
            "calendar_start_day": {
                "name": "日历起始日",
                "description": "月历每周从哪一天开始",
                "type": "select",
                "value": "monday",
                "options": [
                    {"value": "monday", "label": "周一"},
                    {"value": "sunday", "label": "周日"},
                ],
            },
            "checkin_reminder_time": {
                "name": "打卡提醒时间",
                "description": "每日打卡提醒的时间（小时）",
                "type": "number",
                "value": 21,
                "min": 6,
                "max": 23,
            },
        }
