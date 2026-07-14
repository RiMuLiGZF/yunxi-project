"""
成长系统测试（成就 / 天赋 / 日历）

运行: python -m pytest tests/test_growth.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from tide_memory.growth.database import GrowthDatabase, GROWTH_CREATE_TABLE_SQL
from tide_memory.growth.achievements import AchievementManager
from tide_memory.growth.talents import TalentManager
from tide_memory.growth.calendar import CalendarManager


@pytest.fixture
def growth_db(tmp_path):
    """创建独立的成长数据库实例（非单例），用于测试"""
    db_path = str(tmp_path / "growth_test.db")
    db = GrowthDatabase(db_path=db_path, use_migration=False)
    yield db


class TestGrowthDatabaseInit:
    """GrowthDatabase 初始化测试"""

    def test_init_creates_database_file(self, tmp_path):
        """初始化时创建数据库文件"""
        db_path = str(tmp_path / "growth_test.db")
        db = GrowthDatabase(db_path=db_path, use_migration=False)
        assert os.path.exists(db_path)
        assert db.db_path == db_path

    def test_init_creates_tables(self, growth_db):
        """初始化后核心表存在"""
        import sqlite3
        conn = sqlite3.connect(growth_db.db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='growth_achievements'"
        )
        assert cursor.fetchone() is not None

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='growth_talents'"
        )
        assert cursor.fetchone() is not None

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='growth_calendar'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_init_seeds_achievements(self, growth_db):
        """初始化后预置成就数据存在"""
        rows = growth_db.query_all("SELECT COUNT(*) as cnt FROM growth_achievements")
        assert rows[0]["cnt"] == 16  # 4类 x 4级 = 16

    def test_init_seeds_talents(self, growth_db):
        """初始化后预置天赋数据存在"""
        rows = growth_db.query_all("SELECT COUNT(*) as cnt FROM growth_talents")
        assert rows[0]["cnt"] == 32  # 4分支 x 8节点 = 32

    def test_init_seeds_initial_points(self, growth_db):
        """初始化后初始天赋点数为 5"""
        rows = growth_db.query_all(
            "SELECT COALESCE(SUM(amount), 0) as total FROM growth_points"
        )
        assert rows[0]["total"] == 5


class TestAchievementSystem:
    """成就系统测试"""

    def test_list_achievements_all(self, growth_db):
        """获取全部成就列表"""
        mgr = AchievementManager(db=growth_db)
        achievements = mgr.list_achievements()
        assert len(achievements) == 16

    def test_list_achievements_by_category(self, growth_db):
        """按分类过滤成就"""
        mgr = AchievementManager(db=growth_db)
        growth_achs = mgr.list_achievements(category="growth")
        assert len(growth_achs) == 4
        for a in growth_achs:
            assert a["category"] == "growth"

    def test_get_achievement_detail(self, growth_db):
        """获取单个成就详情"""
        mgr = AchievementManager(db=growth_db)
        ach = mgr.get_achievement("ach_growth_1")
        assert ach is not None
        assert ach["name"] == "初识记忆"
        assert ach["rarity"] == "common"
        assert ach["unlocked"] is False

    def test_unlock_achievement(self, growth_db):
        """解锁成就"""
        mgr = AchievementManager(db=growth_db)
        result = mgr.unlock_achievement("ach_growth_1")

        assert result["success"] is True
        assert result["already_unlocked"] is False
        assert result["achievement"]["unlocked"] is True

        # 重复解锁
        result2 = mgr.unlock_achievement("ach_growth_1")
        assert result2["already_unlocked"] is True

    def test_unlock_nonexistent_achievement(self, growth_db):
        """解锁不存在的成就"""
        mgr = AchievementManager(db=growth_db)
        result = mgr.unlock_achievement("nonexistent")
        assert result["success"] is False
        assert result["error"] == "achievement_not_found"

    def test_get_stats(self, growth_db):
        """成就统计"""
        mgr = AchievementManager(db=growth_db)
        stats = mgr.get_stats()

        assert stats["total"] == 16
        assert stats["unlocked"] == 0
        assert stats["locked"] == 16
        assert "by_category" in stats
        assert "by_rarity" in stats


class TestTalentSystem:
    """天赋系统测试"""

    def test_get_talent_tree(self, growth_db):
        """获取完整天赋树"""
        mgr = TalentManager(db=growth_db)
        tree = mgr.get_talent_tree()

        assert len(tree["nodes"]) == 32
        assert tree["available_points"] == 5
        assert tree["spent_points"] == 0
        assert "connections" in tree
        assert "stats" in tree

    def test_get_talent_tree_by_branch(self, growth_db):
        """按分支获取天赋树"""
        mgr = TalentManager(db=growth_db)
        tree = mgr.get_talent_tree(tree="mind")

        assert len(tree["nodes"]) == 8
        for node in tree["nodes"]:
            assert node["branch"] == "mind"

    def test_get_talent_node(self, growth_db):
        """获取单个天赋节点"""
        mgr = TalentManager(db=growth_db)
        node = mgr.get_talent_node("tal_mind_1_1")

        assert node is not None
        assert node["name"] == "逻辑萌芽"
        assert node["level"] == 0
        assert node["status"] == "locked"
        assert node["max_level"] == 3

    def test_upgrade_node_success(self, growth_db):
        """成功升级天赋节点"""
        mgr = TalentManager(db=growth_db)
        result = mgr.upgrade_node("tal_mind_1_1")

        assert result["success"] is True
        assert result["new_level"] == 1
        assert result["remaining_points"] == 4  # 5 - 1 cost

    def test_upgrade_node_insufficient_points(self, growth_db):
        """点数不足时升级失败"""
        mgr = TalentManager(db=growth_db)

        # 尝试升级一个 layer=3 的节点（需要父节点已解锁）
        # 直接用升级多个 layer=1 节点来消耗初始 5 点
        mgr.upgrade_node("tal_mind_1_1")  # -1, 剩余 4
        mgr.upgrade_node("tal_mind_1_2")  # -1, 剩余 3
        mgr.upgrade_node("tal_mind_1_3")  # -1, 剩余 2
        mgr.upgrade_node("tal_mind_1_4")  # -1, 剩余 1
        mgr.upgrade_node("tal_emotion_1_1")  # -1, 剩余 0

        result = mgr.upgrade_node("tal_emotion_1_2")
        assert result["success"] is False
        assert result["error"] == "insufficient_points"

    def test_get_available_points(self, growth_db):
        """获取可用点数"""
        mgr = TalentManager(db=growth_db)
        points = mgr.get_available_points()
        assert points == 5


class TestCalendarSystem:
    """日历系统测试"""

    def test_checkin_success(self, growth_db):
        """打卡成功"""
        mgr = CalendarManager(db=growth_db)
        result = mgr.checkin(mood=7, energy=8)

        assert result["success"] is True
        assert result["is_first_checkin"] is True
        assert result["day_data"]["mood"] == 7
        assert result["day_data"]["energy"] == 8
        assert result["day_data"]["checked_in"] is True

    def test_checkin_invalid_mood(self, growth_db):
        """心情值越界"""
        mgr = CalendarManager(db=growth_db)
        result = mgr.checkin(mood=0, energy=5)
        assert result["success"] is False
        assert result["error"] == "invalid_mood"

    def test_checkin_invalid_energy(self, growth_db):
        """精力值越界"""
        mgr = CalendarManager(db=growth_db)
        result = mgr.checkin(mood=5, energy=11)
        assert result["success"] is False
        assert result["error"] == "invalid_energy"

    def test_checkin_update_existing(self, growth_db):
        """重复打卡更新记录"""
        mgr = CalendarManager(db=growth_db)
        mgr.checkin(mood=5, energy=5)
        result = mgr.checkin(mood=9, energy=9)

        assert result["success"] is True
        assert result["is_first_checkin"] is False
        assert result["day_data"]["mood"] == 9

    def test_get_day_data(self, growth_db):
        """获取日数据"""
        mgr = CalendarManager(db=growth_db)
        today_str = date.today().isoformat()
        mgr.checkin(mood=6, energy=7)

        day_data = mgr.get_day_data(today_str)
        assert day_data["mood"] == 6
        assert day_data["energy"] == 7
        assert day_data["checked_in"] is True

    def test_get_day_data_default(self, growth_db):
        """未打卡日期返回默认数据"""
        mgr = CalendarManager(db=growth_db)
        day_data = mgr.get_day_data("2099-01-01")

        assert day_data["mood"] == 0
        assert day_data["checked_in"] is False
        assert day_data["tide_phase"] in ("小潮", "大潮", "天文潮")

    def test_get_month_calendar(self, growth_db):
        """获取月度日历数据"""
        mgr = CalendarManager(db=growth_db)
        today = date.today()

        result = mgr.get_month_calendar(today.year, today.month)

        assert result["year"] == today.year
        assert result["month"] == today.month
        assert "days" in result
        assert "checked_days" in result
        assert result["total_days"] > 0

    def test_get_stats(self, growth_db):
        """获取日历统计"""
        mgr = CalendarManager(db=growth_db)
        mgr.checkin(mood=8, energy=9)

        stats = mgr.get_stats()

        assert stats["checked_days"] == 1
        assert stats["streak"] == 1
        assert "avg_mood" in stats
        assert "avg_energy" in stats

    def test_calculate_tide_phase(self, growth_db):
        """潮汐相位计算返回有效值"""
        mgr = CalendarManager(db=growth_db)
        for d in [date(2024, 1, 15), date(2024, 7, 15), date(2025, 1, 1)]:
            phase = mgr.calculate_tide_phase(d)
            assert phase in ("小潮", "大潮", "天文潮")