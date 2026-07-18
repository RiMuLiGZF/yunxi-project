"""
M4 单元测试 - 学业规划模式测试 (P1 质量债务)

覆盖: 模式基本信息、场景进入/退出、消息处理、配置管理、数据模型
运行: python -m pytest tests/test_mode_study_plan.py -v
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.modes.study_plan.mode import StudyPlanMode
from src.modes.study_plan.models import (
    GoalCreateRequest, PlanCreateRequest, NoteCreateRequest,
    ExamCreateRequest,
)


def _run_async(coro):
    """辅助函数：同步运行异步代码."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def study_mode():
    """创建学业规划模式实例."""
    return StudyPlanMode()


@pytest.fixture
def mock_service():
    """创建模拟的 StudyService."""
    service = MagicMock()
    service.get_overview.return_value = {
        "stats": {
            "total_goals": 10,
            "total_plans": 15,
            "total_notes": 25,
            "total_exams": 3,
            "today_tasks": 5,
            "today_done": 3,
            "streak_days": 7,
        },
        "banner": {
            "exam_name": "期末考试",
            "days_left": 30,
        },
    }
    service.get_goal_tree.return_value = [
        {"label": "数学进阶", "progress": 60, "icon": "📐"},
        {"label": "英语提升", "progress": 80, "icon": "📖"},
    ]
    service.list_plans.return_value = [
        {"title": "晨读英语", "start_time": "07:00", "end_time": "08:00", "completed": True},
        {"title": "数学练习", "start_time": "09:00", "end_time": "11:00", "completed": False},
    ]
    service.list_notes.return_value = [
        {"title": "微积分笔记", "category": "数学", "date_label": "今天"},
        {"title": "英语语法", "category": "英语", "date_label": "昨天"},
    ]
    service.get_subject_progress.return_value = [
        {"subject": "数学", "progress": 70},
        {"subject": "英语", "progress": 85},
    ]
    service.list_exams.return_value = [
        {"name": "数学期末", "exam_date": "2026-07-30", "urgency": "紧急"},
        {"name": "英语期末", "exam_date": "2026-07-31", "urgency": "紧急"},
    ]
    service.get_weekly_goals.return_value = [
        {"category": "数学", "current": 3, "total": 5, "unit": "章", "progress": 60, "completed": False},
    ]
    return service


# ============================================================================
# 模式基本信息测试
# ============================================================================

class TestStudyPlanModeInfo:
    """学业规划模式基本信息测试"""

    def test_mode_id(self, study_mode):
        """模式 ID 应正确."""
        assert study_mode.mode_id == "study_plan"

    def test_mode_name(self, study_mode):
        """模式名称应正确."""
        assert study_mode.mode_name == "学业规划"

    def test_mode_description(self, study_mode):
        """模式描述应正确."""
        assert "学习目标" in study_mode.mode_description

    def test_mode_icon(self, study_mode):
        """模式图标应为 📚."""
        assert study_mode.icon == "📚"

    def test_mode_category(self, study_mode):
        """模式分类应为 study."""
        assert study_mode.category == "study"

    def test_mode_priority(self, study_mode):
        """模式优先级应为 5."""
        assert study_mode.priority == 5

    def test_mode_enabled(self, study_mode):
        """模式应默认启用."""
        assert study_mode.is_enabled is True

    def test_get_info_complete(self, study_mode):
        """get_info 应返回完整信息."""
        info = study_mode.get_info()
        assert info["mode_id"] == "study_plan"
        assert info["mode_name"] == "学业规划"
        assert info["category"] == "study"


# ============================================================================
# 模式生命周期测试
# ============================================================================

class TestStudyPlanModeLifecycle:
    """学业规划模式生命周期测试"""

    @patch('src.modes.study_plan.mode.get_session')
    @patch('src.modes.study_plan.mode.StudyService')
    def test_on_enter_success(self, mock_svc_cls, mock_session, study_mode, mock_service):
        """进入模式应成功."""
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(study_mode.on_enter({"user_id": "test_user"}))

        assert result["success"] is True
        assert "学业规划" in result["message"]
        assert result["context_updates"]["current_mode"] == "study_plan"

    @patch('src.modes.study_plan.mode.get_session')
    @patch('src.modes.study_plan.mode.StudyService')
    def test_on_enter_contains_welcome(self, mock_svc_cls, mock_session, study_mode, mock_service):
        """进入模式应包含欢迎语."""
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(study_mode.on_enter({"user_id": "test_user"}))
        welcome = result["data"].get("welcome_message", "")

        assert "欢迎" in welcome
        assert "学业规划" in welcome

    @patch('src.modes.study_plan.mode.get_session')
    @patch('src.modes.study_plan.mode.StudyService')
    def test_on_enter_contains_stats(self, mock_svc_cls, mock_session, study_mode, mock_service):
        """进入模式应包含统计数据."""
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(study_mode.on_enter({"user_id": "test_user"}))
        assert "overview" in result["data"]
        assert "study_stats" in result["context_updates"]

    def test_on_leave_success(self, study_mode):
        """离开模式应成功."""
        result = _run_async(study_mode.on_leave({"user_id": "test_user"}))
        assert result["success"] is True
        assert "学业规划" in result["message"]

    @patch('src.modes.study_plan.mode.get_session')
    def test_on_enter_handles_exception(self, mock_session, study_mode):
        """进入模式异常时应降级处理."""
        mock_session.side_effect = RuntimeError("DB error")

        result = _run_async(study_mode.on_enter({"user_id": "test_user"}))
        assert result["success"] is True
        assert "欢迎" in result["data"].get("welcome_message", "")


# ============================================================================
# 消息处理测试
# ============================================================================

class TestStudyPlanModeMessageHandling:
    """学业规划模式消息处理测试"""

    @patch('src.modes.study_plan.mode.get_session')
    @patch('src.modes.study_plan.mode.StudyService')
    def test_handle_overview(self, mock_svc_cls, mock_session, study_mode, mock_service):
        """处理概览查询."""
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(study_mode.handle_message(
            "学习概览", {"user_id": "test_user"}
        ))
        assert result["success"] is True
        assert result["data"].get("type") == "overview"

    @patch('src.modes.study_plan.mode.get_session')
    @patch('src.modes.study_plan.mode.StudyService')
    def test_handle_goals(self, mock_svc_cls, mock_session, study_mode, mock_service):
        """处理目标查询."""
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(study_mode.handle_message(
            "查看学习目标", {"user_id": "test_user"}
        ))
        assert result["success"] is True
        assert result["data"].get("type") == "goals"

    @patch('src.modes.study_plan.mode.get_session')
    @patch('src.modes.study_plan.mode.StudyService')
    def test_handle_plans(self, mock_svc_cls, mock_session, study_mode, mock_service):
        """处理计划查询."""
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(study_mode.handle_message(
            "今日学习计划", {"user_id": "test_user"}
        ))
        assert result["success"] is True
        assert result["data"].get("type") == "plans"

    @patch('src.modes.study_plan.mode.get_session')
    @patch('src.modes.study_plan.mode.StudyService')
    def test_handle_notes(self, mock_svc_cls, mock_session, study_mode, mock_service):
        """处理笔记查询."""
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(study_mode.handle_message(
            "我的学习笔记", {"user_id": "test_user"}
        ))
        assert result["success"] is True
        assert result["data"].get("type") == "notes"

    @patch('src.modes.study_plan.mode.get_session')
    @patch('src.modes.study_plan.mode.StudyService')
    def test_handle_progress(self, mock_svc_cls, mock_session, study_mode, mock_service):
        """处理进度查询."""
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(study_mode.handle_message(
            "学习进度", {"user_id": "test_user"}
        ))
        assert result["success"] is True
        assert result["data"].get("type") == "progress"

    @patch('src.modes.study_plan.mode.get_session')
    @patch('src.modes.study_plan.mode.StudyService')
    def test_handle_exams(self, mock_svc_cls, mock_session, study_mode, mock_service):
        """处理考试查询."""
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(study_mode.handle_message(
            "考试安排", {"user_id": "test_user"}
        ))
        assert result["success"] is True
        assert result["data"].get("type") == "exams"

    @patch('src.modes.study_plan.mode.get_session')
    @patch('src.modes.study_plan.mode.StudyService')
    def test_handle_default(self, mock_svc_cls, mock_session, study_mode, mock_service):
        """处理默认消息."""
        mock_svc_cls.return_value = mock_service
        mock_session.return_value = MagicMock()

        result = _run_async(study_mode.handle_message(
            "你好", {"user_id": "test_user"}
        ))
        assert result["success"] is True
        assert result["data"].get("type") == "help"

    @patch('src.modes.study_plan.mode.get_session')
    def test_handle_exception(self, mock_session, study_mode):
        """消息处理异常时应返回错误."""
        mock_session.side_effect = RuntimeError("DB error")

        result = _run_async(study_mode.handle_message(
            "查看目标", {"user_id": "test_user"}
        ))
        assert result["success"] is True
        assert "抱歉" in result["reply"]


# ============================================================================
# 配置管理测试
# ============================================================================

class TestStudyPlanModeConfig:
    """学业规划模式配置管理测试"""

    def test_get_config_returns_dict(self, study_mode):
        """get_config 应返回配置字典."""
        config = _run_async(study_mode.get_config())
        assert isinstance(config, dict)

    def test_config_has_pomodoro(self, study_mode):
        """配置应包含番茄钟设置."""
        config = _run_async(study_mode.get_config())
        assert "pomodoro_duration" in config
        assert config["pomodoro_duration"]["value"] == 25

    def test_config_has_weekly_review(self, study_mode):
        """配置应包含周复盘提醒开关."""
        config = _run_async(study_mode.get_config())
        assert "weekly_review_enabled" in config
        assert config["weekly_review_enabled"]["type"] == "boolean"

    def test_config_item_structure(self, study_mode):
        """配置项结构应完整."""
        config = _run_async(study_mode.get_config())
        for key, item in config.items():
            assert "name" in item
            assert "type" in item
            assert "value" in item


# ============================================================================
# 数据模型测试
# ============================================================================

class TestStudyPlanModels:
    """学业规划模式数据模型测试"""

    def test_goal_create_request_valid(self):
        """目标创建请求 - 有效数据."""
        req = GoalCreateRequest(label="数学提升", icon="📐")
        assert req.label == "数学提升"
        assert req.icon == "📐"

    def test_goal_create_empty_label_raises(self):
        """目标创建 - 空标签应抛出验证错误."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GoalCreateRequest(label="")

    def test_plan_create_request_valid(self):
        """计划创建请求 - 有效数据."""
        req = PlanCreateRequest(title="晨读", subject="英语")
        assert req.title == "晨读"
        assert req.subject == "英语"

    def test_note_create_request_valid(self):
        """笔记创建请求 - 有效数据."""
        req = NoteCreateRequest(title="微积分笔记", subject="数学", content="导数定义")
        assert req.title == "微积分笔记"
        assert req.subject == "数学"

    def test_exam_create_request_valid(self):
        """考试创建请求 - 有效数据."""
        req = ExamCreateRequest(name="期末考试", subject="数学", exam_date="2026-07-30")
        assert req.name == "期末考试"
