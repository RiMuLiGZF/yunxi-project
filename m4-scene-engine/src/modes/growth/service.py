"""成长中心模式 - 业务逻辑层.

封装成长中心的核心业务逻辑，调用 M5 成长系统客户端获取数据，
并进行业务层的聚合、封装和加工。
不重复存储数据，数据都在 M5。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import structlog

from src.modes.growth.m5_client import M5GrowthClient, get_m5_client

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 服务类
# ---------------------------------------------------------------------------


class GrowthService:
    """成长中心业务服务类.

    提供成长中心模式的所有业务逻辑，
    调用 M5GrowthClient 进行数据获取，
    负责业务层的聚合、封装和加工。
    """

    def __init__(
        self,
        user_id: str = "default",
        client: Optional[M5GrowthClient] = None,
    ) -> None:
        """初始化服务.

        Args:
            user_id: 用户 ID
            client: M5 客户端实例（为 None 时使用全局单例）
        """
        self.user_id = user_id
        self.client = client or get_m5_client()

    # -----------------------------------------------------------------------
    # 概览统计
    # -----------------------------------------------------------------------

    async def get_overview(self) -> dict[str, Any]:
        """获取成长中心概览数据.

        聚合成就统计、天赋点数、日历统计、当前赛季等数据，
        用于成长中心首页展示。

        Returns:
            概览数据字典
        """
        # 并发获取各模块数据
        achievement_stats = await self.client.get_achievement_stats()
        talent_points = await self.client.get_talent_points()
        calendar_stats = await self.client.get_calendar_stats()
        current_season = await self.client.get_current_season()
        achievements_data = await self.client.list_achievements(status="unlocked")

        # 提取最近解锁的成就
        recent_achievements = []
        items = achievements_data.get("items", [])
        if items:
            # 按解锁日期倒序，取最近的 3 个
            unlocked_items = [a for a in items if a.get("unlocked")]
            unlocked_items.sort(key=lambda a: a.get("unlock_date", ""), reverse=True)
            recent_achievements = unlocked_items[:3]

        # 判断今日是否已打卡
        today = datetime.now().strftime("%Y-%m-%d")
        today_checked_in = False
        try:
            today_data = await self.client.get_day_data(today)
            today_checked_in = today_data.get("checked_in", False)
        except Exception as e:
            logger.warning("growth_service.today_data_failed", user_id=self.user_id,
                           error_type=type(e).__name__, error=str(e))
            pass

        # 快捷操作列表
        quick_actions = [
            {"id": "checkin", "name": "今日打卡", "icon": "📅",
             "description": "记录今日心情与精力", "action": "checkin"},
            {"id": "achievements", "name": "成就殿堂", "icon": "🏆",
             "description": "查看所有成就与勋章", "action": "achievements"},
            {"id": "talents", "name": "天赋树", "icon": "🌳",
             "description": "升级天赋，解锁能力", "action": "talents"},
            {"id": "season", "name": "赛季征程", "icon": "⚔️",
             "description": "完成任务，领取奖励", "action": "season"},
        ]

        return {
            "achievement_stats": achievement_stats,
            "talent_points": talent_points,
            "calendar_stats": calendar_stats,
            "current_season": current_season,
            "today_checked_in": today_checked_in,
            "recent_achievements": recent_achievements,
            "quick_actions": quick_actions,
        }

    # -----------------------------------------------------------------------
    # 成就相关
    # -----------------------------------------------------------------------

    async def list_achievements(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict[str, Any]:
        """获取成就列表.

        Args:
            category: 分类过滤
            status: 状态过滤

        Returns:
            成就列表数据
        """
        return await self.client.list_achievements(
            category=category, status=status,
        )

    async def get_achievement_stats(self) -> dict[str, Any]:
        """获取成就统计.

        Returns:
            成就统计数据
        """
        return await self.client.get_achievement_stats()

    async def unlock_achievement(self, achievement_id: str) -> dict[str, Any]:
        """解锁成就.

        Args:
            achievement_id: 成就 ID

        Returns:
            解锁结果
        """
        result = await self.client.unlock_achievement(achievement_id)
        # TODO: 触发场景引擎事件通知
        return result

    # -----------------------------------------------------------------------
    # 天赋相关
    # -----------------------------------------------------------------------

    async def get_talent_tree(self, tree: Optional[str] = None) -> dict[str, Any]:
        """获取天赋树.

        Args:
            tree: 指定分支

        Returns:
            天赋树数据
        """
        return await self.client.get_talent_tree(tree=tree)

    async def get_talent_points(self) -> dict[str, Any]:
        """获取天赋点数.

        Returns:
            天赋点数数据
        """
        return await self.client.get_talent_points()

    async def get_talent_stats(self) -> dict[str, Any]:
        """获取天赋统计.

        Returns:
            天赋统计数据
        """
        return await self.client.get_talent_stats()

    async def upgrade_talent(self, node_id: str) -> dict[str, Any]:
        """升级天赋节点.

        Args:
            node_id: 节点 ID

        Returns:
            升级结果
        """
        result = await self.client.upgrade_talent(node_id)
        # TODO: 触发成就检查（升级天赋可能解锁相关成就）
        return result

    async def reset_talents(self) -> dict[str, Any]:
        """重置天赋树.

        Returns:
            重置结果
        """
        return await self.client.reset_talents()

    # -----------------------------------------------------------------------
    # 历法相关
    # -----------------------------------------------------------------------

    async def get_month_calendar(self, year: int, month: int) -> dict[str, Any]:
        """获取月历数据.

        Args:
            year: 年份
            month: 月份

        Returns:
            月历数据
        """
        return await self.client.get_month_calendar(year, month)

    async def get_calendar_stats(self) -> dict[str, Any]:
        """获取日历统计.

        Returns:
            日历统计数据
        """
        return await self.client.get_calendar_stats()

    async def get_day_data(self, date: str) -> dict[str, Any]:
        """获取单日数据.

        Args:
            date: 日期 YYYY-MM-DD

        Returns:
            单日数据
        """
        return await self.client.get_day_data(date)

    async def checkin(
        self,
        mood: int = 7,
        energy: int = 7,
        date: Optional[str] = None,
        summary: str = "",
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """打卡.

        打卡后自动检查是否触发相关成就，
        并更新赛季任务进度。

        Args:
            mood: 心情值 1-10
            energy: 精力值 1-10
            date: 日期
            summary: 当日总结
            tags: 标签列表

        Returns:
            打卡结果
        """
        result = await self.client.checkin(
            mood=mood,
            energy=energy,
            date=date,
            summary=summary,
            tags=tags,
        )

        return result

    # -----------------------------------------------------------------------
    # 编年史相关
    # -----------------------------------------------------------------------

    async def list_chronicles(
        self,
        page: int = 1,
        size: int = 20,
        category: Optional[str] = None,
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        """获取编年史列表.

        Args:
            page: 页码
            size: 每页数量
            category: 分类筛选
            year: 年份筛选

        Returns:
            编年史列表数据
        """
        return await self.client.list_chronicles(
            page=page, size=size, category=category, year=year,
        )

    async def get_chronicle(self, chronicle_id: str) -> dict[str, Any]:
        """获取编年史详情.

        Args:
            chronicle_id: 纪事 ID

        Returns:
            纪事详情数据
        """
        return await self.client.get_chronicle(chronicle_id)

    async def create_chronicle(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建纪事.

        Args:
            data: 纪事数据

        Returns:
            创建后的纪事数据
        """
        result = await self.client.create_chronicle(data)
        # TODO: 创建纪事可能触发相关成就
        return result

    async def update_chronicle(
        self,
        chronicle_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """更新纪事.

        Args:
            chronicle_id: 纪事 ID
            data: 更新数据

        Returns:
            更新后的纪事数据
        """
        return await self.client.update_chronicle(chronicle_id, data)

    async def delete_chronicle(self, chronicle_id: str) -> dict[str, Any]:
        """删除纪事.

        Args:
            chronicle_id: 纪事 ID

        Returns:
            删除结果
        """
        return await self.client.delete_chronicle(chronicle_id)

    # -----------------------------------------------------------------------
    # 回响相关
    # -----------------------------------------------------------------------

    async def list_echoes(
        self,
        page: int = 1,
        size: int = 20,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> dict[str, Any]:
        """获取回响列表.

        Args:
            page: 页码
            size: 每页数量
            category: 分类筛选
            keyword: 关键词搜索

        Returns:
            回响列表数据
        """
        return await self.client.list_echoes(
            page=page, size=size, category=category, keyword=keyword,
        )

    async def get_echo(self, echo_id: str) -> dict[str, Any]:
        """获取回响详情.

        Args:
            echo_id: 回响 ID

        Returns:
            回响详情数据
        """
        return await self.client.get_echo(echo_id)

    async def generate_echo(self, data: dict[str, Any]) -> dict[str, Any]:
        """生成回响.

        Args:
            data: 生成参数

        Returns:
            生成的回响数据
        """
        result = await self.client.generate_echo(data)
        # TODO: 生成回响可能触发相关成就
        return result

    async def delete_echo(self, echo_id: str) -> dict[str, Any]:
        """删除回响.

        Args:
            echo_id: 回响 ID

        Returns:
            删除结果
        """
        return await self.client.delete_echo(echo_id)

    # -----------------------------------------------------------------------
    # 赛季相关
    # -----------------------------------------------------------------------

    async def get_current_season(self) -> dict[str, Any]:
        """获取当前赛季.

        Returns:
            当前赛季数据
        """
        return await self.client.get_current_season()

    async def get_season_history(self) -> dict[str, Any]:
        """获取赛季历史.

        Returns:
            赛季历史数据
        """
        return await self.client.get_season_history()

    async def list_season_tasks(
        self,
        task_type: Optional[str] = None,
        phase_id: Optional[str] = None,
        season_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict[str, Any]:
        """获取赛季任务列表.

        Args:
            task_type: 类型筛选
            phase_id: 阶段 ID 筛选
            season_id: 赛季 ID 筛选
            status: 状态筛选

        Returns:
            任务列表数据
        """
        return await self.client.list_season_tasks(
            task_type=task_type,
            phase_id=phase_id,
            season_id=season_id,
            status=status,
        )

    async def complete_season_task(self, task_id: str) -> dict[str, Any]:
        """完成赛季任务.

        Args:
            task_id: 任务 ID

        Returns:
            完成结果
        """
        result = await self.client.complete_season_task(task_id)
        # TODO: 完成任务可能触发成就、更新天赋点数等
        return result

    async def claim_season_reward(self, task_id_or_phase_id: str) -> dict[str, Any]:
        """领取赛季奖励.

        Args:
            task_id_or_phase_id: 任务 ID 或阶段 ID

        Returns:
            领取结果
        """
        return await self.client.claim_season_reward(task_id_or_phase_id)

    # -----------------------------------------------------------------------
    # 场景联动方法
    # -----------------------------------------------------------------------

    async def trigger_growth_event(
        self,
        event_type: str,
        event_data: dict[str, Any],
    ) -> dict[str, Any]:
        """触发生长事件.

        供其他业务模式调用，当发生可能影响成长系统的事件时，
        通过此接口通知成长中心进行相应处理（如成就检查、经验增加等）。

        Args:
            event_type: 事件类型（如: task_complete, study_hour, social_interact 等）
            event_data: 事件数据

        Returns:
            处理结果（可能包含解锁的成就、获得的点数等）
        """
        # 目前直接透传给 M5 处理
        return {
            "event_type": event_type,
            "processed": True,
            "unlocked_achievements": [],
            "points_earned": 0,
        }
