"""
成长系统 API 路由

提供六大游戏化模块的 HTTP API 接口。
所有接口以 /api/v1/growth/ 为前缀。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .database import GrowthDatabase
from .achievements import AchievementManager
from .talents import TalentManager
from .calendar import CalendarManager
from .chronicle import ChronicleManager
from .echo import EchoManager
from .season import SeasonManager


class GrowthAPIRouter:
    """
    成长系统 API 路由器

    提供六大游戏化模块的 API 接口：
    - 成就勋章殿堂 (achievements)
    - 心智天赋树 (talents)
    - 潮汐专属历法 (calendar)
    - 地球Online编年史 (chronicle)
    - 记忆回响对比 (echo)
    - 赛季征程系统 (season)
    """

    def __init__(self, app_context: dict = None, db: GrowthDatabase = None):
        """
        初始化成长系统 API 路由

        Args:
            app_context: 应用上下文字典
            db: 数据库实例，为 None 时自动创建
        """
        self._app = app_context or {}
        self._db = db or GrowthDatabase.get_instance()

        # 初始化各模块管理器
        self._talent_manager = TalentManager(self._db)
        self._achievement_manager = AchievementManager(self._db, self._talent_manager)
        self._calendar_manager = CalendarManager(self._db, self._achievement_manager)
        self._chronicle_manager = ChronicleManager(self._db)
        self._echo_manager = EchoManager(self._db)
        self._season_manager = SeasonManager(self._db)

        # 双向引用（成就管理器也需要知道天赋管理器）
        self._achievement_manager.set_talent_manager(self._talent_manager)
        self._calendar_manager.set_achievement_manager(self._achievement_manager)

        self._request_count = 0

    # ============================================================
    # 路由定义
    # ============================================================

    def get_routes(self) -> List[Dict]:
        """获取所有路由定义"""
        return [
            # 成就勋章
            {"method": "GET", "path": "/api/v1/growth/achievements", "handler": self.list_achievements},
            {"method": "GET", "path": "/api/v1/growth/achievements/stats", "handler": self.get_achievement_stats},
            {"method": "POST", "path": "/api/v1/growth/achievements/{achievement_id}/unlock",
             "handler": self.unlock_achievement},

            # 天赋树
            {"method": "GET", "path": "/api/v1/growth/talents", "handler": self.get_talent_tree},
            {"method": "POST", "path": "/api/v1/growth/talents/{nodeId}/upgrade",
             "handler": self.upgrade_talent},
            {"method": "POST", "path": "/api/v1/growth/talents/reset", "handler": self.reset_talents},
            {"method": "GET", "path": "/api/v1/growth/talents/points", "handler": self.get_talent_points},
            {"method": "GET", "path": "/api/v1/growth/talents/stats", "handler": self.get_talent_stats},

            # 潮汐历法
            {"method": "GET", "path": "/api/v1/growth/calendar/{year}/{month}",
             "handler": self.get_month_calendar},
            {"method": "POST", "path": "/api/v1/growth/calendar/checkin", "handler": self.checkin},
            {"method": "GET", "path": "/api/v1/growth/calendar/stats", "handler": self.get_calendar_stats},
            {"method": "GET", "path": "/api/v1/growth/calendar/day/{date}",
             "handler": self.get_day_data},

            # 编年史
            {"method": "GET", "path": "/api/v1/growth/chronicle", "handler": self.list_chronicles},
            {"method": "GET", "path": "/api/v1/growth/chronicle/{chronicle_id}", "handler": self.get_chronicle},
            {"method": "POST", "path": "/api/v1/growth/chronicle", "handler": self.create_chronicle},
            {"method": "PUT", "path": "/api/v1/growth/chronicle/{chronicle_id}", "handler": self.update_chronicle},
            {"method": "DELETE", "path": "/api/v1/growth/chronicle/{chronicle_id}", "handler": self.delete_chronicle},

            # 记忆回响
            {"method": "GET", "path": "/api/v1/growth/memories", "handler": self.list_echoes},
            {"method": "GET", "path": "/api/v1/growth/memories/{echo_id}", "handler": self.get_echo},
            {"method": "POST", "path": "/api/v1/growth/memories/generate", "handler": self.generate_echo},
            {"method": "DELETE", "path": "/api/v1/growth/memories/{echo_id}", "handler": self.delete_echo},

            # 赛季征程
            {"method": "GET", "path": "/api/v1/growth/season/current", "handler": self.get_current_season},
            {"method": "GET", "path": "/api/v1/growth/season/history", "handler": self.get_season_history},
            {"method": "GET", "path": "/api/v1/growth/season/tasks", "handler": self.list_season_tasks},
            {"method": "POST", "path": "/api/v1/growth/season/tasks/{task_id}/complete",
             "handler": self.complete_season_task},
            {"method": "POST", "path": "/api/v1/growth/season/tasks/{task_id_or_phase_id}/claim",
             "handler": self.claim_season_reward},
        ]

    # ============================================================
    # 成就勋章 API
    # ============================================================

    def list_achievements(self, request: Optional[Dict] = None) -> Dict:
        """
        获取成就列表

        查询参数：
        - category: 分类过滤（growth/skill/social/special）
        - status: 状态过滤（unlocked/locked）
        """
        request = request or {}
        category = request.get("category")
        status = request.get("status")

        achievements = self._achievement_manager.list_achievements(
            category=category,
            status=status,
        )

        return self._success({
            "items": achievements,
            "total": len(achievements),
        })

    def get_achievement_stats(self, request: Optional[Dict] = None) -> Dict:
        """获取成就统计"""
        stats = self._achievement_manager.get_stats()
        return self._success(stats)

    def unlock_achievement(self, achievement_id: str, request: Optional[Dict] = None) -> Dict:
        """
        解锁指定成就

        路径参数：
        - achievement_id: 成就ID
        """
        result = self._achievement_manager.unlock_achievement(achievement_id)
        if not result.get("success"):
            return self._error(400, result.get("message", "解锁失败"))
        return self._success(result)

    # ============================================================
    # 天赋树 API
    # ============================================================

    def get_talent_tree(self, request: Optional[Dict] = None) -> Dict:
        """
        获取天赋树

        查询参数：
        - tree: 指定分支（mind/emotion/creativity/experience），可选
        """
        request = request or {}
        tree = request.get("tree")

        tree_data = self._talent_manager.get_talent_tree(tree=tree)
        return self._success(tree_data)

    def upgrade_talent(self, nodeId: str, request: Optional[Dict] = None) -> Dict:
        """
        升级天赋节点

        路径参数：
        - nodeId: 节点ID
        """
        result = self._talent_manager.upgrade_node(nodeId)
        if not result.get("success"):
            error_code = 400
            error_type = result.get("error")
            if error_type == "not_found":
                error_code = 404
            elif error_type == "insufficient_points":
                error_code = 402
            return self._error(error_code, result.get("message", "升级失败"))
        return self._success(result)

    def reset_talents(self, request: Optional[Dict] = None) -> Dict:
        """重置天赋树，返还点数"""
        result = self._talent_manager.reset_talents()
        if not result.get("success"):
            return self._error(500, result.get("message", "重置失败"))
        return self._success(result)

    def get_talent_points(self, request: Optional[Dict] = None) -> Dict:
        """获取可用天赋点数"""
        points = self._talent_manager.get_available_points()
        history = self._talent_manager.get_points_history(10)
        return self._success({
            "available_points": points,
            "history": history,
        })

    def get_talent_stats(self, request: Optional[Dict] = None) -> Dict:
        """获取天赋统计"""
        stats = self._talent_manager.get_stats()
        return self._success(stats)

    # ============================================================
    # 潮汐历法 API
    # ============================================================

    def get_month_calendar(self, year: str, month: str, request: Optional[Dict] = None) -> Dict:
        """
        获取指定年月的日历数据

        路径参数：
        - year: 年份
        - month: 月份
        """
        try:
            year_int = int(year)
            month_int = int(month)
        except (ValueError, TypeError):
            return self._error(400, "年份或月份格式错误")

        result = self._calendar_manager.get_month_calendar(year_int, month_int)
        if not result.get("success", True):
            return self._error(400, result.get("message", "获取日历失败"))

        return self._success(result)

    def checkin(self, request: Optional[Dict] = None) -> Dict:
        """
        打卡

        请求体：
        - date: 日期（YYYY-MM-DD），可选，默认今天
        - mood: 心情值 1-10
        - energy: 精力值 1-10
        - summary: 当日总结
        - tags: 标签列表
        """
        request = request or {}
        mood = request.get("mood", 7)
        energy = request.get("energy", 7)
        target_date = request.get("date")
        summary = request.get("summary", "")
        tags = request.get("tags", [])

        result = self._calendar_manager.checkin(
            mood=mood,
            energy=energy,
            target_date=target_date,
            summary=summary,
            tags=tags,
        )

        if not result.get("success"):
            return self._error(400, result.get("message", "打卡失败"))

        return self._success(result)

    def get_calendar_stats(self, request: Optional[Dict] = None) -> Dict:
        """获取日历统计"""
        stats = self._calendar_manager.get_stats()
        return self._success(stats)

    def get_day_data(self, date: str, request: Optional[Dict] = None) -> Dict:
        """
        获取指定日期的数据

        路径参数：
        - date: 日期（YYYY-MM-DD）
        """
        day_data = self._calendar_manager.get_day_data(date)
        return self._success(day_data)

    # ============================================================
    # 编年史 API
    # ============================================================

    def list_chronicles(self, request: Optional[Dict] = None) -> Dict:
        """
        分页查询纪事列表

        查询参数：
        - page: 页码，默认 1
        - size: 每页数量，默认 20
        - category: 分类筛选
        - year: 年份筛选
        """
        request = request or {}
        page = request.get("page", 1)
        size = request.get("size", 20)
        category = request.get("category")
        year = request.get("year")

        result = self._chronicle_manager.list_chronicles(
            page=page, size=size, category=category, year=year
        )
        return self._success(result)

    def get_chronicle(self, chronicle_id: str, request: Optional[Dict] = None) -> Dict:
        """
        获取单条纪事详情

        路径参数：
        - chronicle_id: 纪事ID
        """
        item = self._chronicle_manager.get_chronicle(chronicle_id)
        if not item:
            return self._error(404, "纪事不存在")
        return self._success(item)

    def create_chronicle(self, request: Optional[Dict] = None) -> Dict:
        """
        创建纪事

        请求体：
        - date: 日期 YYYY.MM.DD
        - title: 标题
        - category: 类型
        - category_text: 类型中文
        - difficulty: 难度
        - content: 详细内容
        - tags: 标签数组
        - has_git: 是否关联 Git
        - git_commits: Git 提交数组
        """
        request = request or {}
        item = self._chronicle_manager.create_chronicle(request)
        return self._success(item)

    def update_chronicle(self, chronicle_id: str, request: Optional[Dict] = None) -> Dict:
        """
        更新纪事

        路径参数：
        - chronicle_id: 纪事ID
        """
        request = request or {}
        item = self._chronicle_manager.update_chronicle(chronicle_id, request)
        if not item:
            return self._error(404, "纪事不存在")
        return self._success(item)

    def delete_chronicle(self, chronicle_id: str, request: Optional[Dict] = None) -> Dict:
        """
        删除纪事

        路径参数：
        - chronicle_id: 纪事ID
        """
        result = self._chronicle_manager.delete_chronicle(chronicle_id)
        if not result:
            return self._error(404, "纪事不存在")
        return self._success({"deleted": True})

    # ============================================================
    # 记忆回响 API
    # ============================================================

    def list_echoes(self, request: Optional[Dict] = None) -> Dict:
        """
        分页查询记忆回响列表

        查询参数：
        - page: 页码，默认 1
        - size: 每页数量，默认 20
        - category: 分类筛选
        - keyword: 关键词搜索
        """
        request = request or {}
        page = request.get("page", 1)
        size = request.get("size", 20)
        category = request.get("category")
        keyword = request.get("keyword")

        result = self._echo_manager.list_echoes(
            page=page, size=size, category=category, keyword=keyword
        )
        return self._success(result)

    def get_echo(self, echo_id: str, request: Optional[Dict] = None) -> Dict:
        """
        获取单条回响详情

        路径参数：
        - echo_id: 回响ID
        """
        item = self._echo_manager.get_echo(echo_id)
        if not item:
            return self._error(404, "回响不存在")
        return self._success(item)

    def generate_echo(self, request: Optional[Dict] = None) -> Dict:
        """
        生成记忆回响

        请求体：
        - type: 类型
        - memory_id: 记忆ID（可选）
        - before: 过去状态
        - after: 现在状态
        """
        request = request or {}
        result = self._echo_manager.generate_echo(request)
        return self._success(result)

    def delete_echo(self, echo_id: str, request: Optional[Dict] = None) -> Dict:
        """
        删除回响

        路径参数：
        - echo_id: 回响ID
        """
        result = self._echo_manager.delete_echo(echo_id)
        if not result:
            return self._error(404, "回响不存在")
        return self._success({"deleted": True})

    # ============================================================
    # 赛季征程 API
    # ============================================================

    def get_current_season(self, request: Optional[Dict] = None) -> Dict:
        """获取当前赛季详情"""
        season = self._season_manager.get_current_season()
        if not season:
            return self._error(404, "当前无进行中的赛季")
        return self._success(season)

    def get_season_history(self, request: Optional[Dict] = None) -> Dict:
        """历史赛季列表"""
        seasons = self._season_manager.get_season_history()
        return self._success({"items": seasons, "total": len(seasons)})

    def list_season_tasks(self, request: Optional[Dict] = None) -> Dict:
        """
        任务列表

        查询参数：
        - type: 类型筛选（daily/weekly/seasonal）
        - phase_id: 阶段ID筛选
        - season_id: 赛季ID筛选
        - status: 状态筛选
        """
        request = request or {}
        task_type = request.get("type")
        phase_id = request.get("phase_id")
        season_id = request.get("season_id")
        status = request.get("status")

        tasks = self._season_manager.list_tasks(
            task_type=task_type,
            phase_id=phase_id,
            season_id=season_id,
            status=status,
        )
        return self._success({"items": tasks, "total": len(tasks)})

    def complete_season_task(self, task_id: str, request: Optional[Dict] = None) -> Dict:
        """
        完成任务

        路径参数：
        - task_id: 任务ID
        """
        result = self._season_manager.complete_task(task_id)
        if not result.get("success"):
            error_code = 404 if result.get("error") == "not_found" else 500
            return self._error(error_code, result.get("message", "任务完成失败"))
        return self._success(result.get("data", {}))

    def claim_season_reward(self, task_id_or_phase_id: str, request: Optional[Dict] = None) -> Dict:
        """
        领取奖励

        路径参数：
        - task_id_or_phase_id: 任务ID或阶段ID
        """
        result = self._season_manager.claim_reward(task_id_or_phase_id)
        if result is None:
            return self._error(404, "任务或阶段不存在")
        if not result.get("success"):
            error_code = 404 if result.get("error") == "not_found" else 400
            return self._error(error_code, result.get("message", "领取奖励失败"))
        return self._success(result)

    # ============================================================
    # 辅助方法
    # ============================================================

    def _success(self, data: Any) -> Dict:
        """成功响应"""
        self._request_count += 1
        return {
            "code": 0,
            "message": "success",
            "data": data,
            "request_id": f"req_{uuid.uuid4().hex[:12]}",
            "timestamp": datetime.now().isoformat(),
        }

    def _error(self, code: int, message: str) -> Dict:
        """错误响应"""
        self._request_count += 1
        return {
            "code": code,
            "message": message,
            "data": None,
            "request_id": f"req_{uuid.uuid4().hex[:12]}",
            "timestamp": datetime.now().isoformat(),
        }

    @property
    def achievement_manager(self) -> AchievementManager:
        """成就管理器"""
        return self._achievement_manager

    @property
    def talent_manager(self) -> TalentManager:
        """天赋管理器"""
        return self._talent_manager

    @property
    def calendar_manager(self) -> CalendarManager:
        """日历管理器"""
        return self._calendar_manager

    @property
    def chronicle_manager(self):
        """编年史管理器"""
        return self._chronicle_manager

    @property
    def echo_manager(self):
        """记忆回响管理器"""
        return self._echo_manager

    @property
    def season_manager(self):
        """赛季征程管理器"""
        return self._season_manager


# vim: set et ts=4 sw=4:
