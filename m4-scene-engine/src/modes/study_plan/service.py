"""学业规划模式 - 业务逻辑层.

封装学业规划模式的核心业务逻辑，包括概览统计、目标树管理、
学习计划管理、知识笔记管理、进度追踪、考试提醒等功能。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.modes.study_plan.repository import StudyRepository


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _calc_duration(start: str, end: str) -> float:
    """计算时长（小时）.

    Args:
        start: 开始时间 HH:MM
        end: 结束时间 HH:MM

    Returns:
        时长（小时），保留一位小数
    """
    try:
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        return round((eh * 60 + em - sh * 60 - sm) / 60, 1)
    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# 服务类
# ---------------------------------------------------------------------------


class StudyService:
    """学业规划业务服务类.

    提供学业规划模式的所有业务逻辑，
    调用 StudyRepository 进行数据访问。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化服务.

        Args:
            db: 数据库会话
            user_id: 用户 ID
        """
        self.repo = StudyRepository(db, user_id=user_id)

    # -----------------------------------------------------------------------
    # 概览统计
    # -----------------------------------------------------------------------

    def get_overview(self) -> dict[str, Any]:
        """获取学业规划概览数据.

        Returns:
            概览数据字典，包含 stats 和 banner
        """
        return self.repo.get_overview_stats()

    # -----------------------------------------------------------------------
    # 目标树
    # -----------------------------------------------------------------------

    def get_goal_tree(self) -> list[dict[str, Any]]:
        """获取目标树结构.

        Returns:
            目标树（嵌套结构）
        """
        goals = self.repo.list_goals()
        goal_map = {g.goal_id: g.to_dict() for g in goals}

        def build_tree(parent_id: Optional[int] = None) -> list[dict[str, Any]]:
            nodes = [g for g in goal_map.values() if g["parent_id"] == parent_id]
            result: list[dict[str, Any]] = []
            for node in nodes:
                children = build_tree(node["id"])
                node_data = {
                    **node,
                    "has_children": len(children) > 0,
                    "children": children,
                }
                result.append(node_data)
            return result

        return build_tree(None)

    def create_goal(
        self,
        label: str,
        icon: str = "📚",
        parent_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """创建目标.

        Args:
            label: 目标名称
            icon: 图标
            parent_id: 父目标 ID

        Returns:
            创建后的目标字典
        """
        goal = self.repo.create_goal(title=label, icon=icon, parent_id=parent_id)
        return goal.to_dict()

    def update_goal(
        self,
        goal_id: int,
        **kwargs: Any,
    ) -> Optional[dict[str, Any]]:
        """更新目标.

        Args:
            goal_id: 目标业务 ID
            **kwargs: 待更新的字段

        Returns:
            更新后的目标字典，不存在返回 None
        """
        goal = self.repo.update_goal(goal_id, **kwargs)
        return goal.to_dict() if goal else None

    def delete_goal(self, goal_id: int) -> bool:
        """删除目标（递归删除子节点）.

        Args:
            goal_id: 目标业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_goal(goal_id)

    # -----------------------------------------------------------------------
    # 学习计划
    # -----------------------------------------------------------------------

    def list_plans(self, date: Optional[str] = None) -> list[dict[str, Any]]:
        """获取学习计划列表.

        Args:
            date: 按日期筛选

        Returns:
            计划字典列表
        """
        plans = self.repo.list_plans(date=date)
        return [p.to_dict() for p in plans]

    def create_plan(
        self,
        title: str,
        start_time: str,
        end_time: str,
        priority: str = "常规",
        subject: str = "",
        date: Optional[str] = None,
    ) -> dict[str, Any]:
        """创建学习计划.

        Args:
            title: 标题
            start_time: 开始时间
            end_time: 结束时间
            priority: 优先级
            subject: 科目
            date: 日期

        Returns:
            创建后的计划字典
        """
        duration = _calc_duration(start_time, end_time)
        plan = self.repo.create_plan(
            title=title,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            priority=priority,
            subject=subject,
            date=date,
        )
        return plan.to_dict()

    def toggle_plan(self, plan_id: int) -> Optional[dict[str, Any]]:
        """切换计划完成状态.

        Args:
            plan_id: 计划业务 ID

        Returns:
            更新后的计划字典，不存在返回 None
        """
        plan = self.repo.toggle_plan(plan_id)
        return plan.to_dict() if plan else None

    def delete_plan(self, plan_id: int) -> bool:
        """删除学习计划.

        Args:
            plan_id: 计划业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_plan(plan_id)

    # -----------------------------------------------------------------------
    # 周目标
    # -----------------------------------------------------------------------

    def get_weekly_goals(self) -> list[dict[str, Any]]:
        """获取本周目标.

        Returns:
            周目标列表
        """
        return self.repo.get_meta("weekly_goals") or []

    def update_weekly_goals(
        self, goals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """更新周目标列表.

        Args:
            goals: 周目标列表

        Returns:
            更新后的周目标列表
        """
        result: list[dict[str, Any]] = []
        next_id = 1
        max_existing_id = max(
            (g.get("id", 0) for g in goals if g.get("id") is not None),
            default=0,
        )

        for g in goals:
            goal_dict = dict(g)
            # 如果没有 id，分配新 id
            if goal_dict.get("id") is None:
                goal_dict["id"] = max_existing_id + next_id
                next_id += 1
            # 重新计算 progress
            total = goal_dict.get("total", 0)
            current = goal_dict.get("current", 0)
            if total > 0:
                goal_dict["progress"] = min(100, int(current / total * 100))
            else:
                goal_dict["progress"] = 0
            # current >= total 时标记完成
            if current >= total and total > 0:
                goal_dict["completed"] = True
            result.append(goal_dict)

        self.repo.set_meta("weekly_goals", result)
        return result

    def toggle_weekly_goal(self, goal_id: int) -> Optional[list[dict[str, Any]]]:
        """切换某个周目标的完成状态.

        Args:
            goal_id: 周目标 ID

        Returns:
            更新后的周目标列表，不存在返回 None
        """
        goals = self.repo.get_meta("weekly_goals") or []
        found = False
        for g in goals:
            if g.get("id") == goal_id:
                g["completed"] = not g.get("completed", False)
                # 如果勾选完成，自动把 current 设为 total
                if g["completed"] and g.get("total", 0) > 0:
                    g["current"] = g["total"]
                    g["progress"] = 100
                found = True
                break

        if not found:
            return None

        self.repo.set_meta("weekly_goals", goals)
        return goals

    # -----------------------------------------------------------------------
    # 知识库
    # -----------------------------------------------------------------------

    def list_knowledge_categories(self) -> list[dict[str, Any]]:
        """获取知识分类.

        Returns:
            知识分类字典列表
        """
        categories = self.repo.list_knowledge_categories()
        return [c.to_dict() for c in categories]

    def list_notes(
        self, subject: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """获取学习笔记列表.

        Args:
            subject: 按科目筛选

        Returns:
            笔记字典列表
        """
        notes = self.repo.list_notes(subject=subject)
        return [n.to_dict() for n in notes]

    def get_note_detail(self, note_id: int) -> Optional[dict[str, Any]]:
        """获取笔记详情.

        Args:
            note_id: 笔记业务 ID

        Returns:
            笔记详情字典，不存在返回 None
        """
        note = self.repo.get_note(note_id)
        return note.to_dict() if note else None

    def create_note(
        self,
        title: str,
        subject: str,
        content: str = "",
    ) -> dict[str, Any]:
        """创建学习笔记.

        Args:
            title: 标题
            subject: 科目
            content: 内容

        Returns:
            创建后的笔记字典
        """
        note = self.repo.create_note(
            title=title, category=subject, content=content,
        )
        return note.to_dict()

    def update_note(
        self,
        note_id: int,
        **kwargs: Any,
    ) -> Optional[dict[str, Any]]:
        """更新笔记.

        Args:
            note_id: 笔记业务 ID
            **kwargs: 待更新的字段

        Returns:
            更新后的笔记字典，不存在返回 None
        """
        note = self.repo.update_note(note_id, **kwargs)
        return note.to_dict() if note else None

    def delete_note(self, note_id: int) -> bool:
        """删除笔记.

        Args:
            note_id: 笔记业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_note(note_id)

    # -----------------------------------------------------------------------
    # 进度追踪
    # -----------------------------------------------------------------------

    def get_subject_progress(self) -> list[dict[str, Any]]:
        """获取科目进度.

        Returns:
            科目进度字典列表
        """
        progs = self.repo.list_progress()
        return [p.to_dict() for p in progs]

    def get_study_stats(self) -> dict[str, Any]:
        """获取学习统计.

        Returns:
            学习统计数据字典
        """
        today = datetime.now().strftime("%Y-%m-%d")
        today_plans = self.repo.list_plans(date=today)
        done_count = sum(1 for p in today_plans if p.completed)
        total_count = len(today_plans)

        study_stats = self.repo.get_meta("study_stats") or {}

        return {
            **study_stats,
            "today_tasks_done": done_count,
            "today_tasks_total": total_count,
        }

    # -----------------------------------------------------------------------
    # 考试提醒
    # -----------------------------------------------------------------------

    def list_exams(self) -> list[dict[str, Any]]:
        """获取考试列表.

        Returns:
            考试字典列表，按日期升序
        """
        exams = self.repo.list_exams()
        return [e.to_dict() for e in exams]

    def create_exam(
        self,
        name: str,
        exam_date: str,
        location: str = "",
        urgency: str = "备考中",
    ) -> dict[str, Any]:
        """创建考试提醒.

        Args:
            name: 考试名称
            exam_date: 考试日期时间
            location: 考试地点
            urgency: 紧急程度

        Returns:
            创建后的考试字典
        """
        exam = self.repo.create_exam(
            name=name,
            exam_date=exam_date,
            location=location,
            urgency=urgency,
        )
        return exam.to_dict()

    def delete_exam(self, exam_id: int) -> bool:
        """删除考试提醒.

        Args:
            exam_id: 考试业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_exam(exam_id)

    # -----------------------------------------------------------------------
    # 风险矩阵
    # -----------------------------------------------------------------------

    def get_risk_matrix(self) -> dict[str, Any]:
        """获取风险矩阵.

        Returns:
            风险矩阵数据，包含 matrix 和 items
        """
        matrix = self.repo.get_meta("risk_matrix") or []
        items = self.repo.get_meta("risk_items") or []
        return {"matrix": matrix, "items": items}

    # -----------------------------------------------------------------------
    # 方案对比
    # -----------------------------------------------------------------------

    def get_scenarios(self) -> list[dict[str, Any]]:
        """获取方案对比.

        Returns:
            方案列表
        """
        return self.repo.get_meta("scenarios") or []

    # -----------------------------------------------------------------------
    # 甘特图
    # -----------------------------------------------------------------------

    def get_gantt_phases(self) -> dict[str, Any]:
        """获取甘特图阶段.

        Returns:
            甘特图数据，包含 phases 和 total_weeks
        """
        phases = self.repo.get_meta("gantt_phases") or []
        return {"phases": phases, "total_weeks": 13}
