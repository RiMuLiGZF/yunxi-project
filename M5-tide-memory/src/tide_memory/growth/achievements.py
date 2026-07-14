"""
成就勋章殿堂模块

管理成就的定义、解锁、统计等功能。
支持按分类、状态筛选成就列表，提供成就统计数据。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .database import GrowthDatabase
from .models import (
    Achievement,
    AchievementStats,
    RARITY_POINT_REWARD,
)


class AchievementManager:
    """
    成就管理器

    负责成就的查询、解锁、统计等核心逻辑。
    与天赋点系统联动：解锁成就奖励天赋点数。
    """

    def __init__(self, db: GrowthDatabase = None, talent_manager=None) -> None:
        """
        初始化成就管理器

        Args:
            db: 数据库实例，为 None 时使用默认单例
            talent_manager: 天赋管理器实例，用于成就解锁时奖励点数
        """
        self._db = db or GrowthDatabase.get_instance()
        self._talent_manager = talent_manager

    # ============================================================
    # 成就列表查询
    # ============================================================

    def list_achievements(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取成就列表，支持分类和状态过滤

        Args:
            category: 分类过滤（growth/skill/social/special）
            status: 状态过滤（unlocked/locked）

        Returns:
            成就列表
        """
        # 构建查询 SQL
        sql = """
            SELECT a.*,
                   COALESCE(ua.unlocked, 0) as unlocked,
                   COALESCE(ua.unlock_date, '') as unlock_date
            FROM growth_achievements a
            LEFT JOIN growth_user_achievements ua ON a.id = ua.achievement_id
        """
        params: list = []
        conditions = []

        if category:
            conditions.append("a.category = ?")
            params.append(category)

        if status == "unlocked":
            conditions.append("COALESCE(ua.unlocked, 0) = 1")
        elif status == "locked":
            conditions.append("COALESCE(ua.unlocked, 0) = 0")

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY a.category, a.sort_order, a.id"

        rows = self._db.query_all(sql, tuple(params))

        result = []
        for row in rows:
            result.append({
                "id": row["id"],
                "name": row["name"],
                "category": row["category"],
                "rarity": row["rarity"],
                "rarity_text": row["rarity_text"],
                "unlocked": bool(row["unlocked"]),
                "unlock_date": row["unlock_date"] or "",
                "condition": row["condition"],
                "description": row["description"],
                "point_reward": row["point_reward"],
            })

        return result

    def get_achievement(self, achievement_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个成就详情

        Args:
            achievement_id: 成就ID

        Returns:
            成就详情，不存在返回 None
        """
        sql = """
            SELECT a.*,
                   COALESCE(ua.unlocked, 0) as unlocked,
                   COALESCE(ua.unlock_date, '') as unlock_date
            FROM growth_achievements a
            LEFT JOIN growth_user_achievements ua ON a.id = ua.achievement_id
            WHERE a.id = ?
        """
        row = self._db.query_one(sql, (achievement_id,))
        if not row:
            return None

        return {
            "id": row["id"],
            "name": row["name"],
            "category": row["category"],
            "rarity": row["rarity"],
            "rarity_text": row["rarity_text"],
            "unlocked": bool(row["unlocked"]),
            "unlock_date": row["unlock_date"] or "",
            "condition": row["condition"],
            "description": row["description"],
            "point_reward": row["point_reward"],
        }

    # ============================================================
    # 成就解锁
    # ============================================================

    def unlock_achievement(self, achievement_id: str) -> Dict[str, Any]:
        """
        解锁指定成就

        Args:
            achievement_id: 成就ID

        Returns:
            解锁结果，包含是否成功、成就信息、奖励点数
        """
        # 检查成就是否存在
        ach = self.get_achievement(achievement_id)
        if not ach:
            return {"success": False, "error": "achievement_not_found", "message": "成就不存在"}

        # 检查是否已解锁
        if ach["unlocked"]:
            return {
                "success": True,
                "already_unlocked": True,
                "achievement": ach,
                "points_awarded": 0,
            }

        # 执行解锁
        now = datetime.now()
        unlock_date = now.strftime("%Y.%m.%d")
        unlocked_at = now.isoformat()

        sql = """
            INSERT OR REPLACE INTO growth_user_achievements
            (achievement_id, unlocked, unlock_date, unlocked_at)
            VALUES (?, 1, ?, ?)
        """
        self._db.execute(sql, (achievement_id, unlock_date, unlocked_at))

        # 奖励天赋点数
        points_awarded = 0
        rarity = ach["rarity"]
        point_reward = ach.get("point_reward", RARITY_POINT_REWARD.get(rarity, 1))

        if self._talent_manager and point_reward > 0:
            self._talent_manager.add_points(
                amount=point_reward,
                source="achievement",
                source_id=achievement_id,
                reason=f"成就解锁：{ach['name']}",
            )
            points_awarded = point_reward

        # 更新成就状态
        ach["unlocked"] = True
        ach["unlock_date"] = unlock_date

        return {
            "success": True,
            "already_unlocked": False,
            "achievement": ach,
            "points_awarded": points_awarded,
        }

    # ============================================================
    # 成就统计
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        获取成就统计数据

        Returns:
            成就统计信息
        """
        # 总数
        total_row = self._db.query_one("SELECT COUNT(*) as cnt FROM growth_achievements")
        total = total_row["cnt"] if total_row else 0

        # 已解锁数
        unlocked_row = self._db.query_one(
            "SELECT COUNT(*) as cnt FROM growth_user_achievements WHERE unlocked = 1"
        )
        unlocked = unlocked_row["cnt"] if unlocked_row else 0

        locked = total - unlocked
        unlock_rate = round(unlocked / total * 100, 1) if total > 0 else 0.0

        # 按分类统计
        by_category = {}
        cat_rows = self._db.query_all("""
            SELECT a.category,
                   COUNT(*) as total,
                   SUM(CASE WHEN COALESCE(ua.unlocked, 0) = 1 THEN 1 ELSE 0 END) as unlocked
            FROM growth_achievements a
            LEFT JOIN growth_user_achievements ua ON a.id = ua.achievement_id
            GROUP BY a.category
            ORDER BY a.category
        """)
        for row in cat_rows:
            by_category[row["category"]] = {
                "total": row["total"],
                "unlocked": row["unlocked"],
                "locked": row["total"] - row["unlocked"],
            }

        # 按稀有度统计
        by_rarity = {}
        rarity_rows = self._db.query_all("""
            SELECT a.rarity,
                   COUNT(*) as total,
                   SUM(CASE WHEN COALESCE(ua.unlocked, 0) = 1 THEN 1 ELSE 0 END) as unlocked
            FROM growth_achievements a
            LEFT JOIN growth_user_achievements ua ON a.id = ua.achievement_id
            GROUP BY a.rarity
            ORDER BY a.rarity
        """)
        for row in rarity_rows:
            by_rarity[row["rarity"]] = {
                "total": row["total"],
                "unlocked": row["unlocked"],
            }

        return {
            "total": total,
            "unlocked": unlocked,
            "locked": locked,
            "unlock_rate": unlock_rate,
            "by_category": by_category,
            "by_rarity": by_rarity,
        }

    # ============================================================
    # 自动检测解锁（基于行为数据）
    # ============================================================

    def check_memory_achievements(self, memory_count: int) -> List[Dict[str, Any]]:
        """
        检查并解锁基于记忆数量的成长类成就

        Args:
            memory_count: 当前记忆总数

        Returns:
            本次新解锁的成就列表
        """
        newly_unlocked = []

        # 成长类成就的记忆数量阈值
        thresholds = [
            ("ach_growth_1", 1),      # 初识记忆
            ("ach_growth_2", 10),     # 时光旅人
            ("ach_growth_3", 50),     # 深海探索者
            ("ach_growth_4", 200),    # 万象归一者
        ]

        for ach_id, threshold in thresholds:
            if memory_count >= threshold:
                result = self.unlock_achievement(ach_id)
                if result.get("success") and not result.get("already_unlocked"):
                    newly_unlocked.append(result.get("achievement"))

        return newly_unlocked

    def check_search_achievements(self, search_count: int) -> List[Dict[str, Any]]:
        """
        检查并解锁基于搜索次数的技能类成就

        Args:
            search_count: 累计搜索次数

        Returns:
            本次新解锁的成就列表
        """
        newly_unlocked = []

        thresholds = [
            ("ach_skill_1", 1),       # 灵感火花
            ("ach_skill_2", 20),      # 织梦者
            ("ach_skill_3", 100),     # 炼金术士
            ("ach_skill_4", 500),     # 创世之笔
        ]

        for ach_id, threshold in thresholds:
            if search_count >= threshold:
                result = self.unlock_achievement(ach_id)
                if result.get("success") and not result.get("already_unlocked"):
                    newly_unlocked.append(result.get("achievement"))

        return newly_unlocked

    def check_checkin_achievements(self, streak: int, total_days: int) -> List[Dict[str, Any]]:
        """
        检查并解锁基于打卡的特殊类成就

        Args:
            streak: 连续打卡天数
            total_days: 累计打卡天数

        Returns:
            本次新解锁的成就列表
        """
        newly_unlocked = []

        # 第一天
        if total_days >= 1:
            result = self.unlock_achievement("ach_special_1")
            if result.get("success") and not result.get("already_unlocked"):
                newly_unlocked.append(result.get("achievement"))

        # 连续七天
        if streak >= 7:
            result = self.unlock_achievement("ach_special_2")
            if result.get("success") and not result.get("already_unlocked"):
                newly_unlocked.append(result.get("achievement"))

        # 赛季先锋（30天）
        if streak >= 30:
            result = self.unlock_achievement("ach_special_3")
            if result.get("success") and not result.get("already_unlocked"):
                newly_unlocked.append(result.get("achievement"))

        # 传奇守护者（100天）
        if streak >= 100:
            result = self.unlock_achievement("ach_special_4")
            if result.get("success") and not result.get("already_unlocked"):
                newly_unlocked.append(result.get("achievement"))

        return newly_unlocked

    def set_talent_manager(self, talent_manager) -> None:
        """设置天赋管理器，用于成就解锁时奖励点数"""
        self._talent_manager = talent_manager


# vim: set et ts=4 sw=4:
