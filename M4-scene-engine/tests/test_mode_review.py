"""
M4 单元测试 - 复盘总结模式测试 (P1 质量债务)

覆盖: 模式基本信息、场景进入/退出、消息处理、配置管理、数据模型
运行: python -m pytest tests/test_mode_review.py -v
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.modes.review.mode import ReviewMode
from src.modes.review.models import (
    ReviewCreateRequest, ReviewGenerateRequest,
    DiaryCreateRequest, DecisionCreateRequest,
    EmotionRecordRequest, BiasAnalyzeRequest,
)


def _run_async(coro):
    """辅助函数：同步运行异步代码."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def review_mode():
    """创建复盘总结模式实例."""
    return ReviewMode()


@pytest.fixture
def mock_service():
    """创建模拟的 ReviewService."""
    service = MagicMock()
    service.get_overview.return_value = {
        "stats": {
            "total_reviews": 30,
            "total_diaries": 50,
            "total_decisions": 10,
            "total_emotions": 100,
            "week_reviews": 5,
            "streak_days": 7,
        },
        "recent_reviews": [
            {"title": "7月18日复盘"},
            {"title": "7月17日复盘"},
        ],
    }
    service.list_reviews.return_value = [
        {"title": "7月18日复盘"},
        {"title": "7月17日复盘"},
        {"title": "7月第三周周报"},
    ]
    service.list_diaries.return_value = [
        {"title": "关于成长的思考"},
        {"title": "今日心情"},
    ]
    service.get_emotion_stats.return_value = {
        "total_records": 100,
        "dominant_emotion": "happy",
        "avg_level": 7.5,
    }
    service.list_decisions.return_value = [
        {"title": "是否换工作", "status": "pending"},
        {"title": "选择技术栈", "status": "decided"},
    ]
    service.list_biases.return_value = [
        {"name": "确认偏误", "description": "只寻找支持自己观点的信息"},
        {"name": "锚定效应", "description": "过度依赖第一印象"},
    ]
    service.get_templates.return_value = [
        {"icon": "📝", "name": "每日复盘", "description": "简单的每日回顾模板"},
        {"icon": "📊", "name": "KPT复盘", "description": "Keep/Problem/Try 三段式"},
    ]
    return service


class TestReviewModeInfo:
    """复盘总结模式基本信息测试"""

    def test_mode_id(self, review_mode):
        assert review_mode.mode_id == "review"

    def test_mode_name(self, review_mode):
        assert review_mode.mode_name == "复盘总结"

    def test_mode_icon(self, review_mode):
        assert review_mode.icon == "📝"

    def test_mode_category(self, review_mode):
        assert review_mode.category == "review"

    def test_mode_priority(self, review_mode):
        assert review_mode.priority == 3

    def test_mode_enabled(self, review_mode):
        assert review_mode.is_enabled is True

    def test_get_info_complete(self, review_mode):
        info = review_mode.get_info()
        assert info["mode_id"] == "review"
        assert info["mode_name"] == "复盘总结"


class TestReviewModeLifecycle:
    """复盘总结模式生命周期测试"""

    @patch('src.modes.review.mode.get_session')
    @patch('src.modes.review.mode.ReviewService')
    def test_on_enter_success(self, mock_svc_cls, mock_session, review_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(review_mode.on_enter({"user_id": "test_user"}))

        assert result["success"] is True
        assert "复盘总结" in result["message"]
        assert result["context_updates"]["current_mode"] == "review"

    @patch('src.modes.review.mode.get_session')
    @patch('src.modes.review.mode.ReviewService')
    def test_on_enter_welcome_contains_streak(self, mock_svc_cls, mock_session, review_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(review_mode.on_enter({"user_id": "test_user"}))
        welcome = result["data"].get("welcome_message", "")
        assert "欢迎" in welcome
        assert "复盘" in welcome

    def test_on_leave_success(self, review_mode):
        result = _run_async(review_mode.on_leave({"user_id": "test_user"}))
        assert result["success"] is True
        assert "复盘总结" in result["message"]

    @patch('src.modes.review.mode.get_session')
    def test_on_enter_handles_exception(self, mock_session, review_mode):
        mock_session.side_effect = RuntimeError("DB error")
        result = _run_async(review_mode.on_enter({"user_id": "test_user"}))
        assert result["success"] is True


class TestReviewModeMessageHandling:
    """复盘总结模式消息处理测试"""

    @patch('src.modes.review.mode.get_session')
    @patch('src.modes.review.mode.ReviewService')
    def test_handle_overview(self, mock_svc_cls, mock_session, review_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(review_mode.handle_message("复盘统计", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "overview"

    @patch('src.modes.review.mode.get_session')
    @patch('src.modes.review.mode.ReviewService')
    def test_handle_reviews(self, mock_svc_cls, mock_session, review_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(review_mode.handle_message("查看复盘记录", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "reviews"

    @patch('src.modes.review.mode.get_session')
    @patch('src.modes.review.mode.ReviewService')
    def test_handle_diaries(self, mock_svc_cls, mock_session, review_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(review_mode.handle_message("我的日记", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "diaries"

    @patch('src.modes.review.mode.get_session')
    @patch('src.modes.review.mode.ReviewService')
    def test_handle_emotion(self, mock_svc_cls, mock_session, review_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        # "情绪心情" 直接匹配情绪分支
        result = _run_async(review_mode.handle_message("情绪心情", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "emotions"

    @patch('src.modes.review.mode.get_session')
    @patch('src.modes.review.mode.ReviewService')
    def test_handle_decisions(self, mock_svc_cls, mock_session, review_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        # "决策选择" 直接匹配决策分支
        result = _run_async(review_mode.handle_message("决策选择", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "decisions"

    @patch('src.modes.review.mode.get_session')
    @patch('src.modes.review.mode.ReviewService')
    def test_handle_biases(self, mock_svc_cls, mock_session, review_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(review_mode.handle_message("认知偏差分析", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "biases"

    @patch('src.modes.review.mode.get_session')
    @patch('src.modes.review.mode.ReviewService')
    def test_handle_templates(self, mock_svc_cls, mock_session, review_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(review_mode.handle_message("模板格式", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "templates"

    @patch('src.modes.review.mode.get_session')
    @patch('src.modes.review.mode.ReviewService')
    def test_handle_default(self, mock_svc_cls, mock_session, review_mode, mock_service):
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()
        result = _run_async(review_mode.handle_message("你好", {"user_id": "u1"}))
        assert result["success"] is True
        assert result["data"].get("type") == "help"

    @patch('src.modes.review.mode.get_session')
    def test_handle_exception(self, mock_session, review_mode):
        mock_session.side_effect = RuntimeError("DB error")
        result = _run_async(review_mode.handle_message("查看复盘", {"user_id": "u1"}))
        assert result["success"] is True
        assert "抱歉" in result["reply"]


class TestReviewModeConfig:
    """复盘总结模式配置管理测试"""

    def test_get_config_returns_dict(self, review_mode):
        config = _run_async(review_mode.get_config())
        assert isinstance(config, dict)

    def test_config_has_default_review_type(self, review_mode):
        config = _run_async(review_mode.get_config())
        assert "default_review_type" in config
        assert config["default_review_type"]["type"] == "select"

    def test_config_has_reminder(self, review_mode):
        config = _run_async(review_mode.get_config())
        assert "reminder_enabled" in config
        assert config["reminder_enabled"]["type"] == "boolean"

    def test_config_item_structure(self, review_mode):
        config = _run_async(review_mode.get_config())
        for key, item in config.items():
            assert "name" in item
            assert "type" in item
            assert "value" in item


class TestReviewModels:
    """复盘总结模式数据模型测试"""

    def test_review_create_valid(self):
        req = ReviewCreateRequest(type="daily", content="今天做了很多事")
        assert req.type == "daily"

    def test_review_generate_valid(self):
        req = ReviewGenerateRequest(type="weekly", date="2026-07-19")
        assert req.type == "weekly"

    def test_diary_create_valid(self):
        req = DiaryCreateRequest(title="今天的思考", content="很充实的一天", mood="happy")
        assert req.title == "今天的思考"
        assert req.mood == "happy"

    def test_diary_create_empty_title_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DiaryCreateRequest(title="")

    def test_decision_create_valid(self):
        req = DecisionCreateRequest(title="是否学习新技术", status="pending")
        assert req.title == "是否学习新技术"

    def test_emotion_record_valid(self):
        req = EmotionRecordRequest(emotion="happy", level=8, trigger="完成项目")
        assert req.emotion == "happy"
        assert req.level == 8

    def test_emotion_record_level_out_of_range_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            EmotionRecordRequest(emotion="sad", level=0)

    def test_bias_analyze_valid(self):
        req = BiasAnalyzeRequest(text="我觉得这个方案最好，因为我一直这么做")
        assert "方案" in req.text
