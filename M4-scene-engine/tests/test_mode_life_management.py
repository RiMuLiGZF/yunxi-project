"""
M4 单元测试 - 生活管理模式测试 (P1 质量债务)

覆盖: 模式基本信息、场景进入/退出、消息处理、配置管理、数据模型
运行: python -m pytest tests/test_mode_life_management.py -v
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.modes.life_management.mode import LifeManagementMode
from src.modes.life_management.models import (
    ScheduleCreateRequest, TodoCreateRequest, HabitCreateRequest,
    FinanceRecordCreateRequest, HabitCheckinRequest,
)


def _run_async(coro):
    """辅助函数：同步运行异步代码."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def life_mode():
    """创建生活管理模式实例."""
    return LifeManagementMode()


@pytest.fixture
def mock_service():
    """创建模拟的 LifeService."""
    service = MagicMock()
    service.get_overview.return_value = {
        "stats": {
            "todo_total": 10,
            "todo_done": 6,
            "habit_total": 5,
            "habit_done": 3,
            "schedule_total": 4,
            "today_spending": 50.0,
        },
        "current_scene": {"name": "居家模式", "icon": "🏠"},
    }
    service.list_schedules.return_value = [
        {"title": "晨跑", "time": "07:00", "tag": "运动"},
        {"title": "会议", "time": "10:00", "tag": "工作"},
    ]
    service.list_todos.return_value = [
        {"title": "买菜", "status": "todo"},
        {"title": "健身", "status": "done"},
    ]
    service.list_habits.return_value = [
        {"name": "早起", "icon": "🌅", "done": True, "streak": 30},
        {"name": "阅读", "icon": "📖", "done": False, "streak": 15},
    ]
    service.get_finance_overview.return_value = {
        "total_expense": 3000,
        "total_income": 8000,
        "month_progress": 37.5,
        "today_spending": 50.0,
    }
    service.list_scenes.return_value = [
        {"label": "居家模式", "icon": "🏠", "active": True},
        {"label": "工作模式", "icon": "💼", "active": False},
    ]
    service.list_rules.return_value = [
        {"condition": "早上7点", "action": "打开窗帘", "enabled": True},
    ]
    return service


class TestLifeManagementModeInfo:
    """生活管理模式基本信息测试"""

    def test_mode_id(self, life_mode):
        assert life_mode.mode_id == "life_management"

    def test_mode_name(self, life_mode):
        assert life_mode.mode_name == "生活管理"

    def test_mode_icon(self, life_mode):
        assert life_mode.icon == "🏠"

    def test_mode_category(self, life_mode):
        assert life_mode.category == "life"

    def test_mode_priority(self, life_mode):
        assert life_mode.priority == 4

    def test_mode_enabled(self, life_mode):
        assert life_mode.is_enabled is True

    def test_get_info_complete(self, life_mode):
        info = life_mode.get_info()
        assert info["mode_id"] == "life_management"
        assert info["mode_name"] == "生活管理"
        assert info["category"] == "life"


class TestLifeManagementModeLifecycle:
    """生活管理模式生命周期测试"""

    @patch('src.modes.life_management.mode.get_session')
    @patch('src.modes.life_management.mode.LifeService')
    def test_on_enter_success(self, mock_svc_cls, mock_session, life_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(life_mode.on_enter({"user_id": "test_user"}))

        assert result["success"] is True
        assert "生活管理" in result["message"]
        assert result["context_updates"]["current_mode"] == "life_management"

    @patch('src.modes.life_management.mode.get_session')
    @patch('src.modes.life_management.mode.LifeService')
    def test_on_enter_welcome_contains_scene(self, mock_svc_cls, mock_session, life_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(life_mode.on_enter({"user_id": "test_user"}))
        welcome = result["data"].get("welcome_message", "")
        assert "欢迎" in welcome
        assert "场景" in welcome

    def test_on_leave_success(self, life_mode):
        result = _run_async(life_mode.on_leave({"user_id": "test_user"}))
        assert result["success"] is True
        assert "生活管理" in result["message"]

    @patch('src.modes.life_management.mode.get_session')
    def test_on_enter_handles_exception(self, mock_session, life_mode):
        mock_session.side_effect = RuntimeError("DB error")
        result = _run_async(life_mode.on_enter({"user_id": "test_user"}))
        assert result["success"] is True


class TestLifeManagementModeMessageHandling:
    """生活管理模式消息处理测试"""

    @patch('src.modes.life_management.mode.get_session')
    @patch('src.modes.life_management.mode.LifeService')
    def test_handle_overview(self, mock_svc_cls, mock_session, life_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(life_mode.handle_message("生活概览", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "overview"

    @patch('src.modes.life_management.mode.get_session')
    @patch('src.modes.life_management.mode.LifeService')
    def test_handle_schedule(self, mock_svc_cls, mock_session, life_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(life_mode.handle_message("今天的日程", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "schedules"

    @patch('src.modes.life_management.mode.get_session')
    @patch('src.modes.life_management.mode.LifeService')
    def test_handle_todo(self, mock_svc_cls, mock_session, life_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(life_mode.handle_message("我的待办", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "todos"

    @patch('src.modes.life_management.mode.get_session')
    @patch('src.modes.life_management.mode.LifeService')
    def test_handle_habit(self, mock_svc_cls, mock_session, life_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(life_mode.handle_message("习惯打卡", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "habits"

    @patch('src.modes.life_management.mode.get_session')
    @patch('src.modes.life_management.mode.LifeService')
    def test_handle_finance(self, mock_svc_cls, mock_session, life_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(life_mode.handle_message("财务状况", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "finance"

    @patch('src.modes.life_management.mode.get_session')
    @patch('src.modes.life_management.mode.LifeService')
    def test_handle_scenes(self, mock_svc_cls, mock_session, life_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(life_mode.handle_message("生活场景", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "scenes"

    @patch('src.modes.life_management.mode.get_session')
    @patch('src.modes.life_management.mode.LifeService')
    def test_handle_default(self, mock_svc_cls, mock_session, life_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(life_mode.handle_message("随便说说", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "help"

    @patch('src.modes.life_management.mode.get_session')
    def test_handle_exception(self, mock_session, life_mode):
        mock_session.side_effect = RuntimeError("DB error")
        result = _run_async(life_mode.handle_message("查看日程", {"user_id": "u1"}))
        assert result["success"] is True
        assert "抱歉" in result["reply"]


class TestLifeManagementModeConfig:
    """生活管理模式配置管理测试"""

    def test_get_config_returns_dict(self, life_mode):
        config = _run_async(life_mode.get_config())
        assert isinstance(config, dict)

    def test_config_has_habit_reminder(self, life_mode):
        config = _run_async(life_mode.get_config())
        assert "habit_reminder_enabled" in config
        assert config["habit_reminder_enabled"]["type"] == "boolean"

    def test_config_has_finance_budget(self, life_mode):
        config = _run_async(life_mode.get_config())
        assert "finance_budget_enabled" in config

    def test_config_item_structure(self, life_mode):
        config = _run_async(life_mode.get_config())
        for key, item in config.items():
            assert "name" in item
            assert "type" in item
            assert "value" in item


class TestLifeManagementModels:
    """生活管理模式数据模型测试"""

    def test_schedule_create_valid(self):
        req = ScheduleCreateRequest(title="晨跑", time="07:00-08:00", tag="运动")
        assert req.title == "晨跑"
        assert req.tag == "运动"

    def test_schedule_create_empty_title_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ScheduleCreateRequest(title="")

    def test_todo_create_valid(self):
        req = TodoCreateRequest(title="买菜", category="今日待办", priority="high")
        assert req.title == "买菜"
        assert req.status == "todo"

    def test_habit_create_valid(self):
        req = HabitCreateRequest(name="早起", icon="🌅")
        assert req.name == "早起"
        assert req.icon == "🌅"

    def test_habit_checkin_valid(self):
        req = HabitCheckinRequest(note="今天也坚持了！")
        assert req.note == "今天也坚持了！"

    def test_finance_record_create_valid(self):
        req = FinanceRecordCreateRequest(
            amount=50.0, type="expense", category="餐饮"
        )
        assert req.amount == 50.0
        assert req.type == "expense"
