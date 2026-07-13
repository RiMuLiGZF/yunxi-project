"""生活管理模式 - 业务逻辑层.

封装生活管理模式的核心业务逻辑，包括概览统计、日程管理、
待办管理、习惯打卡、场景管理、自动化规则、财务管理等功能。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import structlog
from sqlalchemy.orm import Session

from src.modes.life_management.repository import LifeRepository

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 服务类
# ---------------------------------------------------------------------------


class LifeService:
    """生活管理业务服务类.

    提供生活管理模式的所有业务逻辑，
    调用 LifeRepository 进行数据访问。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化服务.

        Args:
            db: 数据库会话
            user_id: 用户 ID
        """
        self.repo = LifeRepository(db, user_id=user_id)

    # -----------------------------------------------------------------------
    # 概览统计
    # -----------------------------------------------------------------------

    def get_overview(self) -> dict[str, Any]:
        """获取生活管理概览数据.

        Returns:
            概览数据字典，包含 stats、current_scene 等
        """
        stats = self.repo.get_overview_stats()
        current_scene = stats.get("current_scene")
        scene_dict = current_scene.to_dict() if current_scene else None

        life_stats = self.repo.get_meta("life_stats") or {}
        finance_summary = stats.get("finance", {})

        return {
            "stats": {
                "todo_total": stats["todo_total"],
                "todo_done": stats["todo_done"],
                "habit_total": stats["habit_total"],
                "habit_done": stats["habit_done"],
                "schedule_total": stats["schedule_total"],
                "today_spending": finance_summary.get("today_spending", 0),
            },
            "life_stats": life_stats,
            "current_scene": scene_dict,
            "finance_summary": finance_summary,
        }

    # -----------------------------------------------------------------------
    # 周视图
    # -----------------------------------------------------------------------

    def get_week_view(self) -> dict[str, Any]:
        """获取周视图数据.

        Returns:
            周视图数据，包含一周每天的日期和事件点
        """
        today = datetime.now()
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        week_days: list[dict[str, Any]] = []
        for i in range(7):
            d = today - timedelta(days=today.weekday()) + timedelta(days=i)
            is_active = d.date() == today.date()
            date_str = d.strftime("%Y-%m-%d")
            # 统计当天日程数
            schedule_count = self.repo.count_schedules(date=date_str)
            dots: list[str] = []
            if schedule_count > 0:
                dots.append("green")
            if i % 3 == 0:
                dots.append("blue")
            week_days.append({
                "label": weekdays[i],
                "day_num": d.day,
                "date": date_str,
                "event_dots": dots,
                "active": is_active,
            })
        return {"week_days": week_days}

    # -----------------------------------------------------------------------
    # 日程管理
    # -----------------------------------------------------------------------

    def list_schedules(self, date: Optional[str] = None) -> list[dict[str, Any]]:
        """获取日程列表.

        Args:
            date: 按日期筛选

        Returns:
            日程字典列表
        """
        schedules = self.repo.list_schedules(date=date)
        return [s.to_dict() for s in schedules]

    def create_schedule(
        self,
        title: str,
        time: str = "09:00 - 10:00",
        tag: str = "固定",
        tag_color: str = "green",
        date: Optional[str] = None,
        description: str = "",
        all_day: bool = False,
        priority: str = "normal",
    ) -> dict[str, Any]:
        """创建日程.

        Args:
            title: 标题
            time: 时间范围
            tag: 分类标签
            tag_color: 标签颜色
            date: 日期
            description: 描述
            all_day: 是否全天
            priority: 优先级

        Returns:
            创建后的日程字典
        """
        # 解析时间范围
        time_range = time
        start_time = "09:00"
        end_time = "10:00"
        try:
            parts = time_range.replace(" ", "").split("-")
            if len(parts) == 2:
                start_time = parts[0]
                end_time = parts[1]
        except Exception as e:
            logger.debug("life_service.time_range_parse_failed", time_range=time_range,
                         error_type=type(e).__name__, error=str(e))
            pass

        schedule = self.repo.create_schedule(
            title=title,
            time_range=time_range,
            start_time=start_time,
            end_time=end_time,
            category=tag,
            tag_color=tag_color,
            date=date,
            description=description,
            all_day=all_day,
            priority=priority,
        )
        return schedule.to_dict()

    def delete_schedule(self, schedule_id: int) -> bool:
        """删除日程.

        Args:
            schedule_id: 日程业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_schedule(schedule_id)

    # -----------------------------------------------------------------------
    # 待办管理
    # -----------------------------------------------------------------------

    def list_todos(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """获取待办列表.

        Args:
            status: 按状态筛选
            category: 按分类筛选

        Returns:
            待办字典列表
        """
        todos = self.repo.list_todos(status=status, category=category)
        return [t.to_dict() for t in todos]

    def create_todo(
        self,
        title: str,
        status: str = "todo",
        category: str = "今日待办",
        priority: str = "normal",
        description: str = "",
        due_date: Optional[str] = None,
    ) -> dict[str, Any]:
        """创建待办.

        Args:
            title: 标题
            status: 状态
            category: 分类
            priority: 优先级
            description: 描述
            due_date: 截止日期

        Returns:
            创建后的待办字典
        """
        todo = self.repo.create_todo(
            title=title,
            status=status,
            category=category,
            priority=priority,
            description=description,
            due_date=due_date,
        )
        return todo.to_dict()

    def update_todo_status(
        self, todo_id: int, status: str,
    ) -> Optional[dict[str, Any]]:
        """更新待办状态.

        Args:
            todo_id: 待办业务 ID
            status: 新状态

        Returns:
            更新后的待办字典，不存在返回 None
        """
        todo = self.repo.update_todo_status(todo_id, status)
        return todo.to_dict() if todo else None

    def delete_todo(self, todo_id: int) -> bool:
        """删除待办.

        Args:
            todo_id: 待办业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_todo(todo_id)

    # -----------------------------------------------------------------------
    # 习惯打卡
    # -----------------------------------------------------------------------

    def list_habits(self) -> list[dict[str, Any]]:
        """获取习惯列表.

        Returns:
            习惯字典列表
        """
        habits = self.repo.list_habits()
        return [h.to_dict() for h in habits]

    def create_habit(
        self,
        name: str,
        icon: str = "✅",
        category: str = "",
        frequency: str = "daily",
        description: str = "",
    ) -> dict[str, Any]:
        """创建习惯.

        Args:
            name: 习惯名称
            icon: 图标
            category: 分类
            frequency: 频率
            description: 描述

        Returns:
            创建后的习惯字典
        """
        habit = self.repo.create_habit(
            name=name,
            icon=icon,
            category=category,
            frequency=frequency,
            description=description,
        )
        return habit.to_dict()

    def checkin_habit(self, habit_id: int) -> Optional[dict[str, Any]]:
        """习惯打卡.

        Args:
            habit_id: 习惯业务 ID

        Returns:
            更新后的习惯字典，不存在返回 None
        """
        habit = self.repo.checkin_habit(habit_id)
        return habit.to_dict() if habit else None

    def delete_habit(self, habit_id: int) -> bool:
        """删除习惯.

        Args:
            habit_id: 习惯业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_habit(habit_id)

    # -----------------------------------------------------------------------
    # 习惯打卡记录
    # -----------------------------------------------------------------------

    def list_habit_records(
        self,
        habit_id: Optional[int] = None,
        date: Optional[str] = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """获取习惯打卡记录列表.

        Args:
            habit_id: 按习惯筛选
            date: 按日期筛选
            limit: 返回条数限制

        Returns:
            打卡记录字典列表
        """
        records = self.repo.list_habit_records(
            habit_id=habit_id, date=date, limit=limit,
        )
        return [r.to_dict() for r in records]

    # -----------------------------------------------------------------------
    # 场景管理
    # -----------------------------------------------------------------------

    def list_scenes(self) -> list[dict[str, Any]]:
        """获取场景列表.

        Returns:
            场景字典列表
        """
        scenes = self.repo.list_scenes()
        return [s.to_dict() for s in scenes]

    def switch_scene(self, scene_key: str) -> Optional[dict[str, Any]]:
        """切换场景.

        Args:
            scene_key: 目标场景 key

        Returns:
            切换后的场景字典，不存在返回 None
        """
        scene = self.repo.switch_scene(scene_key)
        return scene.to_dict() if scene else None

    # -----------------------------------------------------------------------
    # 自动化规则
    # -----------------------------------------------------------------------

    def list_rules(self) -> list[dict[str, Any]]:
        """获取自动化规则列表.

        Returns:
            规则字典列表
        """
        rules = self.repo.list_rules()
        return [r.to_dict() for r in rules]

    def create_rule(
        self,
        condition: str,
        action: str,
        title: str = "",
        category: str = "",
    ) -> dict[str, Any]:
        """创建自动化规则.

        Args:
            condition: 触发条件
            action: 执行动作
            title: 规则标题
            category: 分类

        Returns:
            创建后的规则字典
        """
        rule = self.repo.create_rule(
            condition=condition,
            action=action,
            title=title,
            category=category,
        )
        return rule.to_dict()

    def toggle_rule(self, rule_id: int) -> Optional[dict[str, Any]]:
        """切换规则开关.

        Args:
            rule_id: 规则业务 ID

        Returns:
            更新后的规则字典，不存在返回 None
        """
        rule = self.repo.toggle_rule(rule_id)
        return rule.to_dict() if rule else None

    def delete_rule(self, rule_id: int) -> bool:
        """删除规则.

        Args:
            rule_id: 规则业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_rule(rule_id)

    # -----------------------------------------------------------------------
    # 财务管理
    # -----------------------------------------------------------------------

    def get_finance_overview(self) -> dict[str, Any]:
        """获取财务概览.

        Returns:
            财务概览数据字典
        """
        summary = self.repo.get_finance_summary()
        meta_overview = self.repo.get_meta("finance_overview") or {}

        # 合并数据，实际记录优先
        return {
            "total_expense": summary.get(
                "total_expense", meta_overview.get("total_expense", 0),
            ),
            "total_income": summary.get("total_income", 0),
            "budget": summary.get(
                "budget", meta_overview.get("budget", 0),
            ),
            "today_spending": summary.get(
                "today_spending", meta_overview.get("today_spending", 0),
            ),
            "month_progress": summary.get(
                "month_progress", meta_overview.get("month_progress", 0),
            ),
        }

    def list_finance_categories(
        self, type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """获取财务分类列表.

        Args:
            type: 按类型筛选

        Returns:
            财务分类字典列表
        """
        categories = self.repo.list_finance_categories(type=type)
        return [c.to_dict() for c in categories]

    def list_finance_records(
        self,
        type: Optional[str] = None,
        category: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """获取财务记录列表.

        Args:
            type: 按类型筛选
            category: 按分类筛选
            start_date: 起始日期
            end_date: 结束日期
            limit: 返回条数限制

        Returns:
            财务记录字典列表
        """
        records = self.repo.list_finance_records(
            type=type, category=category,
            start_date=start_date, end_date=end_date,
            limit=limit,
        )
        return [r.to_dict() for r in records]

    def create_finance_record(
        self,
        type: str,
        amount: float,
        category: str,
        description: str = "",
        transaction_date: Optional[str] = None,
    ) -> dict[str, Any]:
        """创建财务记录.

        Args:
            type: 类型（income/expense）
            amount: 金额
            category: 分类
            description: 描述
            transaction_date: 交易日期

        Returns:
            创建后的财务记录字典
        """
        record = self.repo.create_finance_record(
            type=type,
            amount=amount,
            category=category,
            description=description,
            transaction_date=transaction_date,
        )
        return record.to_dict()

    # -----------------------------------------------------------------------
    # 生活助手工具
    # -----------------------------------------------------------------------

    def get_assistant_tools(self) -> list[dict[str, Any]]:
        """获取助手工具列表.

        Returns:
            助手工具列表
        """
        return self.repo.get_meta("assistant_tools") or []

    # -----------------------------------------------------------------------
    # 能耗数据
    # -----------------------------------------------------------------------

    def get_energy_data(self) -> dict[str, Any]:
        """获取能耗数据.

        Returns:
            能耗数据字典，包含 categories 和 total
        """
        categories = self.repo.get_meta("energy_data") or []
        total = self.repo.get_meta("energy_total") or {}
        return {
            "categories": categories,
            "total": total,
        }
