"""
M4 单元测试 - 成长中心模式测试 (P1 质量债务)

覆盖: 模式基本信息、场景进入/退出、消息处理、配置管理、数据模型
运行: python -m pytest tests/test_mode_growth.py -v
"""
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from src.modes.growth.mode import GrowthMode
from src.modes.growth.models import (
    CheckinRequest, ChronicleCreateRequest, ChronicleUpdateRequest,
)


def _run_async(coro):
    """辅助函数：同步运行异步代码."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def growth_mode():
    """创建成长中心模式实例."""
    return GrowthMode()


@pytest.fixture
def mock_service():
    """创建模拟的 GrowthService."""
    service = MagicMock()
    service.get_overview = AsyncMock(return_value={
        "achievement_stats": {"total": 100, "unlocked": 45},
        "talent_points": {"available_points": 12, "spent_points": 20},
        "calendar_stats": {"streak": 30, "checkin_rate": 85.5, "checked_days": 90, "total_days": 105, "avg_mood": 7.5, "avg_energy": 7.0},
        "current_season": {"name": "夏日成长季", "progress": 60, "days_left": 15},
        "today_checked_in": True,
    })
    service.list_achievements = AsyncMock(return_value={
        "items": [
            {"name": "初次打卡", "unlocked": True, "rarity_text": "普通"},
            {"name": "连续7天", "unlocked": True, "rarity_text": "稀有"},
            {"name": "百日成就", "unlocked": False, "rarity_text": "史诗"},
        ],
        "total": 100,
    })
    service.get_talent_tree = AsyncMock(return_value={
        "available_points": 12,
        "spent_points": 20,
        "stats": {
            "mind": {"unlocked": 5, "total": 10},
            "emotion": {"unlocked": 4, "total": 8},
            "creativity": {"unlocked": 3, "total": 7},
            "experience": {"unlocked": 2, "total": 6},
        },
    })
    service.get_calendar_stats = AsyncMock(return_value={
        "checked_days": 90, "total_days": 105, "checkin_rate": 85.5,
        "streak": 30, "avg_mood": 7.5, "avg_energy": 7.0,
    })
    service.checkin = AsyncMock(return_value={
        "success": True, "date": "2026-07-19", "streak": 31, "points_earned": 5,
    })
    service.get_current_season = AsyncMock(return_value={
        "name": "夏日成长季", "progress": 60, "days_left": 15,
    })
    service.list_season_tasks = AsyncMock(return_value={
        "items": [
            {"title": "连续打卡7天", "status": "completed", "points": 50},
            {"title": "解锁10个成就", "status": "in-progress", "points": 100},
        ],
    })
    service.list_chronicles = AsyncMock(return_value={
        "items": [
            {"title": "第一个项目上线", "category_text": "主线任务", "difficulty": "普通", "date": "2026.01.01"},
        ],
        "total": 10,
    })
    service.list_echoes = AsyncMock(return_value={
        "items": [
            {"title": "三月成长对比", "category_text": "技能提升"},
        ],
        "total": 5,
    })
    return service


class TestGrowthModeInfo:
    """成长中心模式基本信息测试"""

    def test_mode_id(self, growth_mode):
        assert growth_mode.mode_id == "growth"

    def test_mode_name(self, growth_mode):
        assert growth_mode.mode_name == "成长中心"

    def test_mode_icon(self, growth_mode):
        assert growth_mode.icon == "🌱"

    def test_mode_category(self, growth_mode):
        assert growth_mode.category == "growth"

    def test_mode_priority(self, growth_mode):
        assert growth_mode.priority == 1

    def test_mode_enabled(self, growth_mode):
        assert growth_mode.is_enabled is True

    def test_get_info_complete(self, growth_mode):
        info = growth_mode.get_info()
        assert info["mode_id"] == "growth"
        assert info["mode_name"] == "成长中心"
        assert info["category"] == "growth"


class TestGrowthModeLifecycle:
    """成长中心模式生命周期测试"""

    @patch('src.modes.growth.mode.GrowthService')
    def test_on_enter_success(self, mock_svc_cls, growth_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        result = _run_async(growth_mode.on_enter({"user_id": "test_user"}))

        assert result["success"] is True
        assert "成长中心" in result["message"]
        assert result["context_updates"]["current_mode"] == "growth"

    @patch('src.modes.growth.mode.GrowthService')
    def test_on_enter_welcome_message(self, mock_svc_cls, growth_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        result = _run_async(growth_mode.on_enter({"user_id": "test_user"}))
        welcome = result["data"].get("welcome_message", "")
        assert "成长中心" in welcome
        assert "成就" in welcome

    def test_on_leave_success(self, growth_mode):
        result = _run_async(growth_mode.on_leave({"user_id": "test_user"}))
        assert result["success"] is True
        assert "成长中心" in result["message"]

    @patch('src.modes.growth.mode.GrowthService')
    def test_on_enter_handles_exception(self, mock_svc_cls, growth_mode):
        mock_svc_cls.side_effect = RuntimeError("service error")
        result = _run_async(growth_mode.on_enter({"user_id": "test_user"}))
        assert result["success"] is True
        assert "欢迎" in result["data"].get("welcome_message", "")


class TestGrowthModeMessageHandling:
    """成长中心模式消息处理测试"""

    @patch('src.modes.growth.mode.GrowthService')
    def test_handle_overview(self, mock_svc_cls, growth_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        result = _run_async(growth_mode.handle_message("成长概览", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "overview"

    @patch('src.modes.growth.mode.GrowthService')
    def test_handle_achievements(self, mock_svc_cls, growth_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        result = _run_async(growth_mode.handle_message("成就勋章", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "achievements"

    @patch('src.modes.growth.mode.GrowthService')
    def test_handle_talents(self, mock_svc_cls, growth_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        result = _run_async(growth_mode.handle_message("天赋树", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "talents"

    @patch('src.modes.growth.mode.GrowthService')
    def test_handle_checkin(self, mock_svc_cls, growth_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        result = _run_async(growth_mode.handle_message("今日打卡", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "checkin"

    @patch('src.modes.growth.mode.GrowthService')
    def test_handle_calendar_stats(self, mock_svc_cls, growth_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        # 使用不含"成长"关键词的输入，避免被概览分支先匹配
        result = _run_async(growth_mode.handle_message("日历打卡情况", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "calendar"

    @patch('src.modes.growth.mode.GrowthService')
    def test_handle_season(self, mock_svc_cls, growth_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        result = _run_async(growth_mode.handle_message("赛季任务", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "season"

    @patch('src.modes.growth.mode.GrowthService')
    def test_handle_chronicle(self, mock_svc_cls, growth_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        result = _run_async(growth_mode.handle_message("编年史", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "chronicle"

    @patch('src.modes.growth.mode.GrowthService')
    def test_handle_default(self, mock_svc_cls, growth_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        result = _run_async(growth_mode.handle_message("你好", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "help"

    @patch('src.modes.growth.mode.GrowthService')
    def test_handle_exception(self, mock_svc_cls, growth_mode):
        mock_svc_cls.side_effect = RuntimeError("service error")
        result = _run_async(growth_mode.handle_message("查看成就", {"user_id": "u1"}))
        assert result["success"] is True
        assert "抱歉" in result["reply"]


class TestGrowthModeConfig:
    """成长中心模式配置管理测试"""

    def test_get_config_returns_dict(self, growth_mode):
        config = _run_async(growth_mode.get_config())
        assert isinstance(config, dict)

    def test_config_has_daily_checkin_reminder(self, growth_mode):
        config = _run_async(growth_mode.get_config())
        assert "daily_checkin_reminder" in config
        assert config["daily_checkin_reminder"]["type"] == "boolean"

    def test_config_has_default_view(self, growth_mode):
        config = _run_async(growth_mode.get_config())
        assert "default_view" in config
        assert config["default_view"]["type"] == "select"

    def test_config_item_structure(self, growth_mode):
        config = _run_async(growth_mode.get_config())
        for key, item in config.items():
            assert "name" in item
            assert "type" in item
            assert "value" in item


class TestGrowthModels:
    """成长中心模式数据模型测试"""

    def test_checkin_request_valid(self):
        req = CheckinRequest(mood=8, energy=7, summary="今天很棒")
        assert req.mood == 8
        assert req.energy == 7
        assert req.tags == []

    def test_checkin_request_mood_out_of_range_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CheckinRequest(mood=11, energy=5)

    def test_checkin_request_energy_out_of_range_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CheckinRequest(mood=5, energy=0)

    def test_chronicle_create_valid(self):
        req = ChronicleCreateRequest(
            date="2026.07.19",
            title="项目上线",
            category="main-quest",
            difficulty="普通",
        )
        assert req.title == "项目上线"
        assert req.category == "main-quest"

    def test_chronicle_create_empty_title_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ChronicleCreateRequest(date="2026.07.19", title="")

    def test_chronicle_update_valid(self):
        req = ChronicleUpdateRequest(title="新标题", difficulty="困难")
        assert req.title == "新标题"
        assert req.difficulty == "困难"
