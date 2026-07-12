"""
潮汐专属历法模块

管理日历打卡、潮汐相位计算、统计等功能。
支持每日打卡记录心情和精力，计算潮汐相位。
"""

from __future__ import annotations

import json
import math
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .database import GrowthDatabase


class CalendarManager:
    """
    潮汐历法管理器

    负责日历打卡、潮汐相位计算、统计等核心逻辑。
    与成就系统联动：打卡时自动检测连续打卡成就。
    """

    # 潮汐周期（简化模型）
    # 7天小潮周期 + 30天大潮周期的组合
    NEAP_TIDE_PERIOD = 7  # 小潮周期（天）
    SPRING_TIDE_PERIOD = 30  # 大潮周期（天）
    ASTRONOMICAL_INTERVAL = 90  # 天文潮间隔（天）

    def __init__(self, db: GrowthDatabase = None, achievement_manager=None):
        """
        初始化日历管理器

        Args:
            db: 数据库实例，为 None 时使用默认单例
            achievement_manager: 成就管理器实例，用于打卡时检测成就
        """
        self._db = db or GrowthDatabase.get_instance()
        self._achievement_manager = achievement_manager

    # ============================================================
    # 潮汐相位计算
    # ============================================================

    def calculate_tide_phase(self, target_date: date) -> str:
        """
        计算指定日期的潮汐相位

        使用简化的潮汐模型：
        - 基于 7 天小潮周期和 30 天大潮周期的叠加
        - 每 90 天出现一次天文潮（特殊潮汐）

        Args:
            target_date: 目标日期

        Returns:
            潮汐相位：小潮 / 大潮 / 天文潮
        """
        # 以 2024-01-01 作为基准日（朔日）
        base_date = date(2024, 1, 1)
        days_diff = (target_date - base_date).days

        # 大潮周期（30天）：计算潮汐强度
        spring_tide = math.sin(2 * math.pi * days_diff / self.SPRING_TIDE_PERIOD)
        # 小潮周期（7天）：计算短期波动
        neap_tide = 0.3 * math.sin(2 * math.pi * days_diff / self.NEAP_TIDE_PERIOD)

        # 组合潮汐强度（-1 到 1）
        tide_intensity = spring_tide + neap_tide

        # 天文潮：每 90 天出现一次（叠加一个更长的周期）
        astronomical = math.cos(2 * math.pi * days_diff / self.ASTRONOMICAL_INTERVAL)

        # 判断相位
        if astronomical > 0.9 and abs(tide_intensity) > 0.7:
            return "天文潮"
        elif abs(tide_intensity) > 0.6:
            return "大潮"
        else:
            return "小潮"

    # ============================================================
    # 打卡功能
    # ============================================================

    def checkin(
        self,
        mood: int,
        energy: int,
        target_date: Optional[str] = None,
        summary: str = "",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        每日打卡

        Args:
            mood: 心情值 1-10
            energy: 精力值 1-10
            target_date: 打卡日期（YYYY-MM-DD），默认为今天
            summary: 当日总结
            tags: 标签列表

        Returns:
            打卡结果
        """
        # 参数校验
        if not (1 <= mood <= 10):
            return {"success": False, "error": "invalid_mood", "message": "心情值必须在 1-10 之间"}
        if not (1 <= energy <= 10):
            return {"success": False, "error": "invalid_energy", "message": "精力值必须在 1-10 之间"}

        # 确定日期
        if target_date:
            try:
                d = datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                return {"success": False, "error": "invalid_date", "message": "日期格式错误，应为 YYYY-MM-DD"}
        else:
            d = date.today()

        date_str = d.isoformat()
        tide_phase = self.calculate_tide_phase(d)
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        # 检查当天是否已打卡
        existing = self._db.query_one(
            "SELECT * FROM growth_calendar WHERE date = ?", (date_str,)
        )

        if existing:
            # 更新打卡记录
            sql = """
                UPDATE growth_calendar
                SET mood = ?, energy = ?, checked_in = 1,
                    summary = ?, tags = ?, tide_phase = ?,
                    updated_at = datetime('now')
                WHERE date = ?
            """
            self._db.execute(sql, (mood, energy, summary, tags_json, tide_phase, date_str))
            is_first_checkin = False
        else:
            # 新建打卡记录
            sql = """
                INSERT INTO growth_calendar
                (date, mood, energy, checked_in, summary, tags, tide_phase)
                VALUES (?, ?, ?, 1, ?, ?, ?)
            """
            self._db.execute(sql, (date_str, mood, energy, summary, tags_json, tide_phase))
            is_first_checkin = True

        # 获取当日数据
        day_data = self.get_day_data(date_str)

        # 计算连续打卡天数
        stats = self.get_stats()
        streak = stats["streak"]

        # 联动成就系统
        newly_unlocked = []
        if self._achievement_manager:
            newly_unlocked = self._achievement_manager.check_checkin_achievements(
                streak=streak,
                total_days=stats["checked_days"],
            )

        return {
            "success": True,
            "day_data": day_data,
            "is_first_checkin": is_first_checkin,
            "streak": streak,
            "newly_unlocked_achievements": newly_unlocked,
        }

    def get_day_data(self, target_date: str) -> Dict[str, Any]:
        """
        获取指定日期的数据

        Args:
            target_date: 日期（YYYY-MM-DD）

        Returns:
            当日数据
        """
        row = self._db.query_one(
            "SELECT * FROM growth_calendar WHERE date = ?", (target_date,)
        )

        if row:
            return self._row_to_day_data(row)

        # 如果没有记录，返回默认数据（含潮汐相位）
        try:
            d = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            d = date.today()

        return {
            "date": target_date,
            "mood": 0,
            "energy": 0,
            "checked_in": False,
            "summary": "",
            "tags": [],
            "tide_phase": self.calculate_tide_phase(d),
        }

    # ============================================================
    # 月历查询
    # ============================================================

    def get_month_calendar(self, year: int, month: int) -> Dict[str, Any]:
        """
        获取指定年月的日历数据

        Args:
            year: 年份
            month: 月份（1-12）

        Returns:
            月历数据，包含每日数据和月度统计
        """
        # 参数校验
        if not (1 <= month <= 12):
            return {"success": False, "error": "invalid_month", "message": "月份必须在 1-12 之间"}

        try:
            # 获取该月的天数
            _, num_days = monthrange(year, month)
            start_date = date(year, month, 1)
            end_date = date(year, month, num_days)
        except ValueError as e:
            return {"success": False, "error": "invalid_date", "message": str(e)}

        # 查询该月的打卡记录
        sql = """
            SELECT * FROM growth_calendar
            WHERE date >= ? AND date <= ?
            ORDER BY date
        """
        rows = self._db.query_all(sql, (start_date.isoformat(), end_date.isoformat()))

        # 构建日期 -> 数据映射
        data_map = {}
        for row in rows:
            data_map[row["date"]] = self._row_to_day_data(row)

        # 生成完整月份的每一天数据
        days = []
        for day in range(1, num_days + 1):
            d = date(year, month, day)
            date_str = d.isoformat()
            if date_str in data_map:
                days.append(data_map[date_str])
            else:
                days.append({
                    "date": date_str,
                    "mood": 0,
                    "energy": 0,
                    "checked_in": False,
                    "summary": "",
                    "tags": [],
                    "tide_phase": self.calculate_tide_phase(d),
                })

        # 月度统计
        checked_days = sum(1 for d in days if d["checked_in"])
        mood_values = [d["mood"] for d in days if d["checked_in"] and d["mood"] > 0]
        energy_values = [d["energy"] for d in days if d["checked_in"] and d["energy"] > 0]

        avg_mood = round(sum(mood_values) / len(mood_values), 1) if mood_values else 0.0
        avg_energy = round(sum(energy_values) / len(energy_values), 1) if energy_values else 0.0

        # 计算该月内的连续打卡天数（到月末为止）
        streak = self._calculate_streak(end_date)

        return {
            "year": year,
            "month": month,
            "days": days,
            "total_days": num_days,
            "checked_days": checked_days,
            "streak": streak,
            "avg_mood": avg_mood,
            "avg_energy": avg_energy,
            "checkin_rate": round(checked_days / num_days * 100, 1) if num_days > 0 else 0.0,
        }

    # ============================================================
    # 统计功能
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        获取日历统计数据

        Returns:
            日历统计信息
        """
        # 总打卡天数
        row = self._db.query_one(
            "SELECT COUNT(*) as cnt FROM growth_calendar WHERE checked_in = 1"
        )
        checked_days = row["cnt"] if row else 0

        # 平均心情和精力
        stats_row = self._db.query_one("""
            SELECT AVG(mood) as avg_mood, AVG(energy) as avg_energy,
                   MIN(date) as first_date
            FROM growth_calendar
            WHERE checked_in = 1
        """)

        avg_mood = round(stats_row["avg_mood"], 1) if stats_row and stats_row["avg_mood"] else 0.0
        avg_energy = round(stats_row["avg_energy"], 1) if stats_row and stats_row["avg_energy"] else 0.0

        # 计算总天数（从第一天打卡到今天）
        first_date = stats_row["first_date"] if stats_row else None
        if first_date:
            try:
                first = datetime.strptime(first_date, "%Y-%m-%d").date()
                total_days = (date.today() - first).days + 1
            except ValueError:
                total_days = checked_days
        else:
            total_days = checked_days if checked_days > 0 else 0

        # 连续打卡天数
        streak = self._calculate_streak(date.today())

        return {
            "total_days": total_days,
            "checked_days": checked_days,
            "streak": streak,
            "avg_mood": avg_mood,
            "avg_energy": avg_energy,
            "checkin_rate": round(checked_days / total_days * 100, 1) if total_days > 0 else 0.0,
        }

    def _calculate_streak(self, end_date: date) -> int:
        """
        计算到指定日期为止的连续打卡天数

        Args:
            end_date: 截止日期

        Returns:
            连续打卡天数
        """
        streak = 0
        current = end_date

        # 从截止日期往前数，直到遇到未打卡的一天
        while True:
            date_str = current.isoformat()
            row = self._db.query_one(
                "SELECT checked_in FROM growth_calendar WHERE date = ?",
                (date_str,),
            )
            if row and row["checked_in"]:
                streak += 1
                current = current - timedelta(days=1)
            else:
                break

            # 防止无限循环（最多查 1000 天）
            if streak > 1000:
                break

        return streak

    # ============================================================
    # 工具方法
    # ============================================================

    def _row_to_day_data(self, row: Any) -> Dict[str, Any]:
        """将数据库行转换为日数据字典"""
        tags = json.loads(row["tags"]) if row["tags"] else []
        return {
            "date": row["date"],
            "mood": row["mood"],
            "energy": row["energy"],
            "checked_in": bool(row["checked_in"]),
            "summary": row["summary"] or "",
            "tags": tags,
            "tide_phase": row["tide_phase"] or "小潮",
        }

    def set_achievement_manager(self, achievement_manager) -> None:
        """设置成就管理器，用于打卡时检测成就"""
        self._achievement_manager = achievement_manager


# vim: set et ts=4 sw=4:
