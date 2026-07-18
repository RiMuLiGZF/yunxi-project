"""
M4 单元测试 - 人际关系模式测试 (P1 质量债务)

覆盖: 模式基本信息、场景进入/退出、消息处理、配置管理、数据模型
运行: python -m pytest tests/test_mode_social_relation.py -v
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.modes.social_relation.mode import SocialRelationMode
from src.modes.social_relation.models import (
    ContactCreateRequest, ContactUpdateRequest,
    InteractionCreateRequest, ReminderCreateRequest,
)


def _run_async(coro):
    """辅助函数：同步运行异步代码."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def social_mode():
    """创建人际关系模式实例."""
    return SocialRelationMode()


@pytest.fixture
def mock_service():
    """创建模拟的 SocialService."""
    service = MagicMock()
    service.get_overview.return_value = {
        "stats": {
            "total_contacts": 50,
            "total_interactions": 200,
            "avg_closeness": 65,
            "week_interactions": 15,
            "eq_score": 75,
        },
        "top_contacts": [
            {"name": "小明", "closeness": 95},
            {"name": "小红", "closeness": 90},
        ],
    }
    service.list_contacts.return_value = [
        {"name": "小明", "relation": "朋友"},
        {"name": "小红", "relation": "同事"},
        {"name": "小李", "relation": "家人"},
    ]
    service.list_reminders.return_value = [
        {"title": "小明生日", "date": "2026-08-01", "priority": "high", "status": "pending"},
        {"title": "周年纪念", "date": "2026-09-15", "priority": "medium", "status": "pending"},
    ]
    service.get_eq_score.return_value = {"score": 75, "level": "良好"}
    service.list_eq_courses.return_value = [
        {"title": "情绪管理入门", "progress": 80},
        {"title": "有效沟通技巧", "progress": 50},
    ]
    service.build_relation_graph.return_value = {
        "nodes": [{"id": "self"}, {"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
        "edges": [],
    }
    return service


class TestSocialRelationModeInfo:
    """人际关系模式基本信息测试"""

    def test_mode_id(self, social_mode):
        assert social_mode.mode_id == "social_relation"

    def test_mode_name(self, social_mode):
        assert social_mode.mode_name == "人际关系"

    def test_mode_icon(self, social_mode):
        assert social_mode.icon == "👥"

    def test_mode_category(self, social_mode):
        assert social_mode.category == "social"

    def test_mode_priority(self, social_mode):
        assert social_mode.priority == 6

    def test_mode_enabled(self, social_mode):
        assert social_mode.is_enabled is True

    def test_get_info_complete(self, social_mode):
        info = social_mode.get_info()
        assert info["mode_id"] == "social_relation"
        assert info["mode_name"] == "人际关系"


class TestSocialRelationModeLifecycle:
    """人际关系模式生命周期测试"""

    @patch('src.modes.social_relation.mode.get_session')
    @patch('src.modes.social_relation.mode.SocialService')
    def test_on_enter_success(self, mock_svc_cls, mock_session, social_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(social_mode.on_enter({"user_id": "test_user"}))

        assert result["success"] is True
        assert "人际关系" in result["message"]
        assert result["context_updates"]["current_mode"] == "social_relation"

    @patch('src.modes.social_relation.mode.get_session')
    @patch('src.modes.social_relation.mode.SocialService')
    def test_on_enter_welcome_contains_contacts(self, mock_svc_cls, mock_session, social_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(social_mode.on_enter({"user_id": "test_user"}))
        welcome = result["data"].get("welcome_message", "")
        assert "欢迎" in welcome
        assert "联系人" in welcome

    def test_on_leave_success(self, social_mode):
        result = _run_async(social_mode.on_leave({"user_id": "test_user"}))
        assert result["success"] is True
        assert "人际关系" in result["message"]

    @patch('src.modes.social_relation.mode.get_session')
    def test_on_enter_handles_exception(self, mock_session, social_mode):
        mock_session.side_effect = RuntimeError("DB error")
        result = _run_async(social_mode.on_enter({"user_id": "test_user"}))
        assert result["success"] is True


class TestSocialRelationModeMessageHandling:
    """人际关系模式消息处理测试"""

    @patch('src.modes.social_relation.mode.get_session')
    @patch('src.modes.social_relation.mode.SocialService')
    def test_handle_overview(self, mock_svc_cls, mock_session, social_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(social_mode.handle_message("社交概览", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "overview"

    @patch('src.modes.social_relation.mode.get_session')
    @patch('src.modes.social_relation.mode.SocialService')
    def test_handle_contacts(self, mock_svc_cls, mock_session, social_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(social_mode.handle_message("联系人列表", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "contacts"

    @patch('src.modes.social_relation.mode.get_session')
    @patch('src.modes.social_relation.mode.SocialService')
    def test_handle_reminders(self, mock_svc_cls, mock_session, social_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(social_mode.handle_message("生日提醒", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "reminders"

    @patch('src.modes.social_relation.mode.get_session')
    @patch('src.modes.social_relation.mode.SocialService')
    def test_handle_eq(self, mock_svc_cls, mock_session, social_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(social_mode.handle_message("情商测试", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "eq"

    @patch('src.modes.social_relation.mode.get_session')
    @patch('src.modes.social_relation.mode.SocialService')
    def test_handle_graph(self, mock_svc_cls, mock_session, social_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(social_mode.handle_message("关系图谱", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "graph"

    @patch('src.modes.social_relation.mode.get_session')
    @patch('src.modes.social_relation.mode.SocialService')
    def test_handle_default(self, mock_svc_cls, mock_session, social_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(social_mode.handle_message("你好", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "help"

    @patch('src.modes.social_relation.mode.get_session')
    def test_handle_exception(self, mock_session, social_mode):
        mock_session.side_effect = RuntimeError("DB error")
        result = _run_async(social_mode.handle_message("查看联系人", {"user_id": "u1"}))
        assert result["success"] is True
        assert "抱歉" in result["reply"]


class TestSocialRelationModeConfig:
    """人际关系模式配置管理测试"""

    def test_get_config_returns_dict(self, social_mode):
        config = _run_async(social_mode.get_config())
        assert isinstance(config, dict)

    def test_config_has_default_relation(self, social_mode):
        config = _run_async(social_mode.get_config())
        assert "default_relation" in config
        assert config["default_relation"]["type"] == "select"

    def test_config_has_reminder(self, social_mode):
        config = _run_async(social_mode.get_config())
        assert "reminder_enabled" in config
        assert config["reminder_enabled"]["type"] == "boolean"

    def test_config_item_structure(self, social_mode):
        config = _run_async(social_mode.get_config())
        for key, item in config.items():
            assert "name" in item
            assert "type" in item
            assert "value" in item


class TestSocialRelationModels:
    """人际关系模式数据模型测试"""

    def test_contact_create_valid(self):
        req = ContactCreateRequest(name="小明", relation="朋友")
        assert req.name == "小明"
        assert req.relation == "朋友"
        assert req.tags == []

    def test_contact_create_empty_name_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ContactCreateRequest(name="")

    def test_contact_update_valid(self):
        req = ContactUpdateRequest(closeness=80, note="好朋友")
        assert req.closeness == 80

    def test_contact_update_closeness_out_of_range_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ContactUpdateRequest(closeness=101)

    def test_interaction_create_valid(self):
        req = InteractionCreateRequest(
            contact_id=1, type="聊天", duration_minutes=30
        )
        assert req.contact_id == 1
        assert req.type == "聊天"

    def test_interaction_create_zero_contact_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            InteractionCreateRequest(contact_id=0, type="聊天")

    def test_reminder_create_valid(self):
        req = ReminderCreateRequest(title="生日提醒", date="2026-08-01")
        assert req.title == "生日提醒"
