"""
赛季征程系统

以游戏化赛季机制驱动成长，每个赛季包含多个阶段，
每个阶段有若干任务。完成任务获得天赋点，完成阶段
可领取阶段奖励，赛季结束结算总奖励。

预置两个赛季：
- S1 启程之春（历史/已完成）
- S2 觉醒之夏（当前进行中）
"""

from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from .database import GrowthDatabase


def _parse_date(date_str: str) -> date:
    """解析日期字符串，支持 YYYY-MM-DD 格式"""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return date.today()


def _calc_days_left(end_date_str: str) -> int:
    """计算距离结束日期还有多少天"""
    end = _parse_date(end_date_str)
    today = date.today()
    delta = end - today
    return max(0, delta.days)


def _calc_season_progress(phases: List[Dict[str, Any]]) -> int:
    """
    计算赛季整体进度百分比。
    基于阶段任务完成情况计算。
    """
    total = sum(p.get("tasks_total", 0) for p in phases)
    completed = sum(p.get("tasks_completed", 0) for p in phases)
    if total == 0:
        return 0
    return int(completed / total * 100)


def _find_active_phase_index(phases_data: List[Dict[str, Any]]) -> int:
    """
    找到当前活跃阶段的索引。
    活跃阶段是第一个未全部完成任务的阶段。
    """
    for i, p in enumerate(phases_data):
        total = p.get("tasks_total", 0)
        completed = p.get("tasks_completed", 0)
        if total == 0 or completed < total:
            return i
    return len(phases_data) - 1 if phases_data else 0


def _determine_phase_status(
    phase_index: int,
    tasks_total: int,
    tasks_completed: int,
    active_phase_idx: int,
) -> str:
    """
    判断阶段状态：completed / active / locked
    """
    if tasks_total > 0 and tasks_completed >= tasks_total:
        return "completed"
    if phase_index == active_phase_idx:
        return "active"
    if phase_index < active_phase_idx:
        return "completed" if tasks_completed >= tasks_total else "active"
    return "locked"


class SeasonManager:
    """
    赛季征程管理器

    负责赛季查询、任务管理、奖励领取等功能。
    """

    def __init__(self, db: GrowthDatabase = None, talent_manager=None):
        """
        初始化赛季管理器

        Args:
            db: 数据库实例，为 None 时使用默认单例
            talent_manager: 天赋管理器实例，用于发放天赋点奖励
        """
        self._db = db or GrowthDatabase.get_instance()
        self._talent_manager = talent_manager

    def set_talent_manager(self, talent_manager) -> None:
        """设置天赋管理器"""
        self._talent_manager = talent_manager

    # ============================================================
    # 赛季查询
    # ============================================================

    def get_current_season(self) -> Optional[Dict[str, Any]]:
        """
        获取当前进行中的赛季。

        优先返回 status=active 的赛季，如果没有则返回最近的赛季。

        Returns:
            赛季详情（含阶段信息），不存在返回 None
        """
        # 查找活跃赛季
        row = self._db.query_one(
            "SELECT * FROM growth_seasons WHERE status = 'active' ORDER BY start_date DESC LIMIT 1",
        )

        # 如果没有活跃赛季，找最近的
        if not row:
            row = self._db.query_one(
                "SELECT * FROM growth_seasons ORDER BY start_date DESC LIMIT 1",
            )

        if not row:
            return None

        return self._build_season_detail(row)

    def get_season_history(self) -> List[Dict[str, Any]]:
        """
        获取历史赛季列表。

        Returns:
            赛季列表（含基本信息和进度）
        """
        rows = self._db.query_all(
            "SELECT * FROM growth_seasons ORDER BY start_date DESC",
        )

        seasons = []
        for row in rows:
            season = self._build_season_basic(row)
            seasons.append(season)

        return seasons

    def _build_season_basic(self, season_row: Dict[str, Any]) -> Dict[str, Any]:
        """构建赛季基础信息（不含阶段详情）"""
        season_id = season_row["id"]

        task_row = self._db.query_one(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status IN ('completed', 'claimed') THEN 1 ELSE 0 END) as completed
            FROM growth_season_tasks
            WHERE season_id = ?
            """,
            (season_id,),
        )

        total_tasks = task_row["total"] if task_row else 0
        completed_tasks = task_row["completed"] if task_row else 0
        progress = int(completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

        return {
            "id": season_row["id"],
            "name": season_row["name"],
            "period": season_row["period"],
            "start_date": season_row["start_date"],
            "end_date": season_row["end_date"],
            "status": season_row["status"],
            "progress": progress,
            "days_left": _calc_days_left(season_row["end_date"]),
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
        }

    def _build_season_detail(self, season_row: Dict[str, Any]) -> Dict[str, Any]:
        """构建赛季详情（含阶段信息）"""
        season_id = season_row["id"]

        # 获取所有阶段
        phase_rows = self._db.query_all(
            "SELECT * FROM growth_season_phases WHERE season_id = ? ORDER BY phase_index",
            (season_id,),
        )

        phases = []
        for phase_row in phase_rows:
            phase_id = phase_row["id"]

            # 统计阶段任务
            task_row = self._db.query_one(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status IN ('completed', 'claimed') THEN 1 ELSE 0 END) as completed
                FROM growth_season_tasks
                WHERE phase_id = ?
                """,
                (phase_id,),
            )

            tasks_total = task_row["total"] if task_row else 0
            tasks_completed = task_row["completed"] if task_row else 0

            phases.append({
                "id": phase_row["id"],
                "name": phase_row["name"],
                "tasks_total": tasks_total,
                "tasks_completed": tasks_completed,
                "reward": phase_row["reward"],
                "reward_points": phase_row["reward_points"],
                "reward_claimed": bool(phase_row["reward_claimed"]),
            })

        # 确定活跃阶段
        active_idx = _find_active_phase_index(phases)

        # 更新阶段状态
        for i, phase in enumerate(phases):
            phase["status"] = _determine_phase_status(
                i + 1,
                phase["tasks_total"],
                phase["tasks_completed"],
                active_idx + 1,
            )

        progress = _calc_season_progress(phases)

        return {
            "id": season_row["id"],
            "name": season_row["name"],
            "period": season_row["period"],
            "start_date": season_row["start_date"],
            "end_date": season_row["end_date"],
            "status": season_row["status"],
            "progress": progress,
            "days_left": _calc_days_left(season_row["end_date"]),
            "phases": phases,
        }

    # ============================================================
    # 任务管理
    # ============================================================

    def list_tasks(
        self,
        season_id: Optional[str] = None,
        task_type: Optional[str] = None,
        phase_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取赛季任务列表。

        Args:
            season_id: 赛季ID，默认取当前赛季
            task_type: 任务类型筛选 daily/weekly/seasonal
            phase_id: 阶段ID筛选
            status: 状态筛选 pending/completed/claimed

        Returns:
            任务列表
        """
        # 如果没指定赛季，取当前赛季
        if not season_id:
            current = self.get_current_season()
            if not current:
                return []
            season_id = current["id"]

        conditions = ["season_id = ?"]
        params: List[Any] = [season_id]

        if task_type:
            conditions.append("type = ?")
            params.append(task_type)

        if phase_id:
            conditions.append("phase_id = ?")
            params.append(phase_id)

        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = "WHERE " + " AND ".join(conditions)

        rows = self._db.query_all(
            f"""
            SELECT * FROM growth_season_tasks
            {where_clause}
            ORDER BY phase_id, id
            """,
            tuple(params),
        )

        tasks = []
        for row in rows:
            tasks.append({
                "id": row["id"],
                "phase_id": row["phase_id"],
                "title": row["title"],
                "description": row["description"],
                "type": row["type"],
                "status": row["status"],
                "points": row["points"],
                "completed_at": row["completed_at"],
            })

        return tasks

    def complete_task(self, task_id: str) -> Dict[str, Any]:
        """
        完成任务。

        将任务状态从 pending 改为 completed，记录完成时间。

        Args:
            task_id: 任务ID

        Returns:
            包含 success、data 的结果字典
        """
        # 检查任务是否存在
        row = self._db.query_one(
            "SELECT * FROM growth_season_tasks WHERE id = ?",
            (task_id,),
        )

        if not row:
            return {
                "success": False,
                "error": "not_found",
                "message": "任务不存在",
            }

        # 如果已经完成或已领取，直接返回
        if row["status"] in ("completed", "claimed"):
            task_data = {
                "id": row["id"],
                "phase_id": row["phase_id"],
                "title": row["title"],
                "description": row["description"],
                "type": row["type"],
                "status": row["status"],
                "points": row["points"],
                "completed_at": row["completed_at"],
            }
            return {
                "success": True,
                "data": task_data,
                "message": "任务已完成",
            }

        now = datetime.now().isoformat()
        self._db.execute(
            "UPDATE growth_season_tasks SET status = 'completed', completed_at = ? WHERE id = ?",
            (now, task_id),
        )

        # 重新读取
        row = self._db.query_one(
            "SELECT * FROM growth_season_tasks WHERE id = ?",
            (task_id,),
        )

        task_data = {
            "id": row["id"],
            "phase_id": row["phase_id"],
            "title": row["title"],
            "description": row["description"],
            "type": row["type"],
            "status": row["status"],
            "points": row["points"],
            "completed_at": row["completed_at"],
        }

        return {
            "success": True,
            "data": task_data,
            "message": "任务完成成功",
        }

    def claim_reward(self, task_or_phase_id: str) -> Optional[Dict[str, Any]]:
        """
        领取奖励。

        支持领取任务奖励和阶段奖励：
        - 如果ID匹配任务：领取任务奖励（标记为 claimed）
        - 如果ID匹配阶段：领取阶段奖励（标记 reward_claimed=1）

        Args:
            task_or_phase_id: 任务ID或阶段ID

        Returns:
            奖励信息，包含获得的天赋点数
        """
        # 先尝试作为任务领取
        task_row = self._db.query_one(
            "SELECT * FROM growth_season_tasks WHERE id = ?",
            (task_or_phase_id,),
        )

        if task_row:
            return self._claim_task_reward(task_row)

        # 再尝试作为阶段领取
        phase_row = self._db.query_one(
            "SELECT * FROM growth_season_phases WHERE id = ?",
            (task_or_phase_id,),
        )

        if phase_row:
            return self._claim_phase_reward(phase_row)

        return None

    def _claim_task_reward(self, task_row: Dict[str, Any]) -> Dict[str, Any]:
        """领取任务奖励"""
        task_id = task_row["id"]

        if task_row["status"] == "pending":
            return {
                "success": False,
                "message": "任务未完成，无法领取奖励",
                "type": "task",
                "id": task_id,
                "points": 0,
            }

        if task_row["status"] == "claimed":
            return {
                "success": False,
                "message": "奖励已领取",
                "type": "task",
                "id": task_id,
                "points": 0,
            }

        # 领取奖励
        self._db.execute(
            "UPDATE growth_season_tasks SET status = 'claimed' WHERE id = ?",
            (task_id,),
        )

        # 如果有天赋管理器，发放天赋点
        points = task_row["points"]
        if self._talent_manager and points > 0:
            try:
                self._talent_manager.add_points(
                    amount=points,
                    source="season_task",
                    source_id=task_id,
                    reason=f"完成赛季任务：{task_row['title']}",
                )
            except Exception:
                pass  # 发放失败不影响主流程

        return {
            "success": True,
            "message": "任务奖励已领取",
            "type": "task",
            "id": task_id,
            "points": points,
        }

    def _claim_phase_reward(self, phase_row: Dict[str, Any]) -> Dict[str, Any]:
        """领取阶段奖励"""
        phase_id = phase_row["id"]

        if phase_row["reward_claimed"]:
            return {
                "success": False,
                "message": "阶段奖励已领取",
                "type": "phase",
                "id": phase_id,
                "points": 0,
                "reward_name": phase_row["reward"],
            }

        # 检查阶段所有任务是否都已完成
        task_row = self._db.query_one(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status IN ('completed', 'claimed') THEN 1 ELSE 0 END) as completed
            FROM growth_season_tasks
            WHERE phase_id = ?
            """,
            (phase_id,),
        )

        total = task_row["total"] if task_row else 0
        completed = task_row["completed"] if task_row else 0

        if total == 0 or completed < total:
            return {
                "success": False,
                "message": f"阶段任务未全部完成（{completed}/{total}）",
                "type": "phase",
                "id": phase_id,
                "points": 0,
                "reward_name": phase_row["reward"],
            }

        # 领取阶段奖励
        self._db.execute(
            "UPDATE growth_season_phases SET reward_claimed = 1 WHERE id = ?",
            (phase_id,),
        )

        # 如果有天赋管理器，发放天赋点
        points = phase_row["reward_points"]
        if self._talent_manager and points > 0:
            try:
                self._talent_manager.add_points(
                    amount=points,
                    source="season_phase",
                    source_id=phase_id,
                    reason=f"完成赛季阶段：{phase_row['name']}",
                )
            except Exception:
                pass

        return {
            "success": True,
            "message": f"阶段奖励「{phase_row['reward']}」已领取",
            "type": "phase",
            "id": phase_id,
            "points": points,
            "reward_name": phase_row["reward"],
        }


# vim: set et ts=4 sw=4:
