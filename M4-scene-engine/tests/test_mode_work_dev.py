"""
M4 单元测试 - 工作开发模式测试 (P1 质量债务)

覆盖: 模式基本信息、场景进入/退出、核心服务方法、消息处理、配置管理
运行: python -m pytest tests/test_mode_work_dev.py -v
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.modes.work_dev.mode import WorkDevMode
from src.modes.work_dev.models import (
    ProjectCreateRequest, TaskCreateRequest, TaskStatusUpdateRequest,
    CodeExecuteRequest, CodeGenerateRequest,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def work_mode():
    """创建工作开发模式实例."""
    return WorkDevMode()


@pytest.fixture
def mock_service():
    """创建模拟的 WorkDevService."""
    service = MagicMock()
    service.get_overview.return_value = {
        "stats": {
            "total_projects": 5,
            "active_projects": 3,
            "total_tasks": 20,
            "todo_tasks": 8,
            "total_commits": 150,
            "week_commits": 12,
            "total_lines": 50000,
            "task_completion_rate": 60.0,
        },
        "recent_tasks": [
            {"title": "完成用户模块", "status": "in_progress"},
            {"title": "修复登录bug", "status": "todo"},
        ],
        "recent_commits": [
            {"message": "feat: add user module"},
            {"message": "fix: login bug"},
        ],
    }
    service.list_projects.return_value = [
        {"project_id": 1, "name": "项目A", "status": "active"},
        {"project_id": 2, "name": "项目B", "status": "active"},
        {"project_id": 3, "name": "项目C", "status": "completed"},
    ]
    service.get_project_detail.return_value = {
        "project_id": 1,
        "name": "项目A",
        "status": "active",
        "progress": 75,
        "task_count": 10,
        "line_count": 2000,
    }
    service.get_task_board.return_value = {
        "todo": [{"id": 1, "title": "任务1"}],
        "in_progress": [{"id": 2, "title": "任务2"}],
        "done": [{"id": 3, "title": "任务3"}],
    }
    service.list_tasks.return_value = [
        {"title": "任务1", "status": "todo"},
        {"title": "任务2", "status": "in_progress"},
        {"title": "任务3", "status": "done"},
    ]
    service.list_commits.return_value = [
        {"message": "feat: add feature A"},
        {"message": "fix: bug B"},
        {"message": "refactor: module C"},
    ]
    return service


def _run_async(coro):
    """辅助函数：同步运行异步代码."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================================
# 模式基本信息测试
# ============================================================================

class TestWorkDevModeInfo:
    """工作开发模式基本信息测试"""

    def test_mode_id(self, work_mode):
        """模式 ID 应正确."""
        assert work_mode.mode_id == "work_dev"

    def test_mode_name(self, work_mode):
        """模式名称应正确."""
        assert work_mode.mode_name == "工作开发"

    def test_mode_description(self, work_mode):
        """模式描述应正确."""
        assert "工作效率" in work_mode.mode_description

    def test_mode_icon(self, work_mode):
        """模式图标应为 💻."""
        assert work_mode.icon == "💻"

    def test_mode_category(self, work_mode):
        """模式分类应为 work."""
        assert work_mode.category == "work"

    def test_mode_priority(self, work_mode):
        """模式优先级应为 2."""
        assert work_mode.priority == 2

    def test_mode_enabled(self, work_mode):
        """模式应默认启用."""
        assert work_mode.is_enabled is True

    def test_get_info_returns_complete_dict(self, work_mode):
        """get_info 应返回完整的信息字典."""
        info = work_mode.get_info()
        assert info["mode_id"] == "work_dev"
        assert info["mode_name"] == "工作开发"
        assert info["category"] == "work"
        assert info["priority"] == 2
        assert info["is_enabled"] is True


# ============================================================================
# 模式生命周期测试
# ============================================================================

class TestWorkDevModeLifecycle:
    """工作开发模式生命周期测试"""

    @patch('src.modes.work_dev.mode.get_session')
    @patch('src.modes.work_dev.mode.WorkDevService')
    def test_on_enter_success(self, mock_service_cls, mock_get_session, work_mode, mock_service):
        """进入模式应成功并返回正确结构."""
        mock_service_cls.return_value = mock_service
        mock_get_session.return_value = MagicMock()

        result = _run_async(work_mode.on_enter({"user_id": "test_user"}))

        assert result["success"] is True
        assert "工作开发" in result["message"]
        assert "data" in result
        assert "context_updates" in result
        assert result["context_updates"]["current_mode"] == "work_dev"

    @patch('src.modes.work_dev.mode.get_session')
    @patch('src.modes.work_dev.mode.WorkDevService')
    def test_on_enter_welcome_message(self, mock_service_cls, mock_get_session, work_mode, mock_service):
        """进入模式应包含欢迎语."""
        mock_service_cls.return_value = mock_service
        mock_get_session.return_value = MagicMock()

        result = _run_async(work_mode.on_enter({"user_id": "test_user"}))

        welcome = result["data"].get("welcome_message", "")
        assert "工作开发" in welcome
        assert "项目" in welcome

    @patch('src.modes.work_dev.mode.get_session')
    @patch('src.modes.work_dev.mode.WorkDevService')
    def test_on_enter_contains_stats(self, mock_service_cls, mock_get_session, work_mode, mock_service):
        """进入模式返回数据应包含统计信息."""
        mock_service_cls.return_value = mock_service
        mock_get_session.return_value = MagicMock()

        result = _run_async(work_mode.on_enter({"user_id": "test_user"}))

        assert "overview" in result["data"]
        assert "stats" in result["data"]["overview"]
        assert result["context_updates"].get("work_dev_stats") is not None

    def test_on_leave_success(self, work_mode):
        """离开模式应成功."""
        result = _run_async(work_mode.on_leave({"user_id": "test_user"}))

        assert result["success"] is True
        assert "工作开发" in result["message"]
        assert "data" in result

    @patch('src.modes.work_dev.mode.get_session')
    def test_on_enter_handles_exception(self, mock_get_session, work_mode):
        """进入模式异常时应降级处理."""
        mock_get_session.side_effect = RuntimeError("DB connection failed")

        result = _run_async(work_mode.on_enter({"user_id": "test_user"}))

        # 异常时仍应返回 success=True（降级处理）
        assert result["success"] is True
        assert "欢迎" in result["data"].get("welcome_message", "")


# ============================================================================
# 消息处理测试
# ============================================================================

class TestWorkDevModeMessageHandling:
    """工作开发模式消息处理测试"""

    @patch('src.modes.work_dev.mode.get_session')
    @patch('src.modes.work_dev.mode.WorkDevService')
    def test_handle_message_project_list(self, mock_service_cls, mock_get_session, work_mode, mock_service):
        """处理项目列表查询消息."""
        mock_service_cls.return_value = mock_service
        mock_get_session.return_value = MagicMock()

        result = _run_async(work_mode.handle_message(
            "查看项目列表", {"user_id": "test_user"}
        ))

        assert result["success"] is True
        assert "项目" in result["reply"]
        assert result["data"].get("type") == "project_list"

    @patch('src.modes.work_dev.mode.get_session')
    @patch('src.modes.work_dev.mode.WorkDevService')
    def test_handle_message_task_board(self, mock_service_cls, mock_get_session, work_mode, mock_service):
        """处理任务看板查询消息."""
        mock_service_cls.return_value = mock_service
        mock_get_session.return_value = MagicMock()

        result = _run_async(work_mode.handle_message(
            "任务看板", {"user_id": "test_user"}
        ))

        assert result["success"] is True
        assert "看板" in result["reply"]
        assert result["data"].get("type") == "task_board"

    @patch('src.modes.work_dev.mode.get_session')
    @patch('src.modes.work_dev.mode.WorkDevService')
    def test_handle_message_code_help(self, mock_service_cls, mock_get_session, work_mode, mock_service):
        """处理代码帮助消息."""
        mock_service_cls.return_value = mock_service
        mock_get_session.return_value = MagicMock()

        result = _run_async(work_mode.handle_message(
            "写代码", {"user_id": "test_user"}
        ))

        assert result["success"] is True
        assert result["data"].get("type") == "code_help"

    @patch('src.modes.work_dev.mode.get_session')
    @patch('src.modes.work_dev.mode.WorkDevService')
    def test_handle_message_git_commits(self, mock_service_cls, mock_get_session, work_mode, mock_service):
        """处理 Git 提交查询消息."""
        mock_service_cls.return_value = mock_service
        mock_get_session.return_value = MagicMock()

        result = _run_async(work_mode.handle_message(
            "最近的git提交", {"user_id": "test_user"}
        ))

        assert result["success"] is True
        assert result["data"].get("type") == "git_commits"

    @patch('src.modes.work_dev.mode.get_session')
    @patch('src.modes.work_dev.mode.WorkDevService')
    def test_handle_message_stats(self, mock_service_cls, mock_get_session, work_mode, mock_service):
        """处理统计查询消息."""
        mock_service_cls.return_value = mock_service
        mock_get_session.return_value = MagicMock()

        result = _run_async(work_mode.handle_message(
            "查看统计", {"user_id": "test_user"}
        ))

        assert result["success"] is True
        assert result["data"].get("type") == "stats"

    @patch('src.modes.work_dev.mode.get_session')
    @patch('src.modes.work_dev.mode.WorkDevService')
    def test_handle_message_help(self, mock_service_cls, mock_get_session, work_mode, mock_service):
        """处理帮助消息."""
        mock_service_cls.return_value = mock_service
        mock_get_session.return_value = MagicMock()

        result = _run_async(work_mode.handle_message(
            "帮助", {"user_id": "test_user"}
        ))

        assert result["success"] is True
        assert result["data"].get("type") == "help"
        assert "项目管理" in result["reply"]

    @patch('src.modes.work_dev.mode.get_session')
    @patch('src.modes.work_dev.mode.WorkDevService')
    def test_handle_message_default(self, mock_service_cls, mock_get_session, work_mode, mock_service):
        """处理默认（未识别）消息."""
        mock_service_cls.return_value = mock_service
        mock_get_session.return_value = MagicMock()

        result = _run_async(work_mode.handle_message(
            "随便聊聊", {"user_id": "test_user"}
        ))

        assert result["success"] is True
        assert result["data"].get("type") == "default"

    @patch('src.modes.work_dev.mode.get_session')
    def test_handle_message_exception_handling(self, mock_get_session, work_mode):
        """消息处理异常时应返回错误消息."""
        mock_get_session.side_effect = RuntimeError("DB error")

        result = _run_async(work_mode.handle_message(
            "查看项目", {"user_id": "test_user"}
        ))

        assert result["success"] is True
        assert "抱歉" in result["reply"]
        assert result["data"].get("type") == "error"

    def test_init_handle_context_extracts_user_id(self, work_mode):
        """_init_handle_context 应正确提取用户ID和消息."""
        ctx = work_mode._init_handle_context("  测试消息  ", {"user_id": "user123"})
        assert ctx["user_id"] == "user123"
        assert ctx["msg"] == "测试消息"

    def test_init_handle_context_default_user(self, work_mode):
        """_init_handle_context 无 user_id 时使用 default."""
        ctx = work_mode._init_handle_context("测试", {})
        assert ctx["user_id"] == "default"

    def test_build_response_structure(self, work_mode):
        """_build_response 应构造正确的响应结构."""
        response = work_mode._build_response(
            "测试回复",
            {"type": "test", "data": {"key": "value"}},
            {"key": "update"},
        )
        assert response["success"] is True
        assert response["reply"] == "测试回复"
        assert response["data"]["type"] == "test"
        assert response["context_updates"]["key"] == "update"


# ============================================================================
# 配置管理测试
# ============================================================================

class TestWorkDevModeConfig:
    """工作开发模式配置管理测试"""

    def test_get_config_returns_dict(self, work_mode):
        """get_config 应返回配置字典."""
        config = _run_async(work_mode.get_config())
        assert isinstance(config, dict)

    def test_config_has_default_language(self, work_mode):
        """配置应包含默认编程语言选项."""
        config = _run_async(work_mode.get_config())
        assert "default_language" in config
        assert config["default_language"]["type"] == "select"
        assert "python" in config["default_language"]["options"]

    def test_config_has_code_assistant(self, work_mode):
        """配置应包含 AI 代码助手开关."""
        config = _run_async(work_mode.get_config())
        assert "code_assistant_enabled" in config
        assert config["code_assistant_enabled"]["type"] == "boolean"
        assert config["code_assistant_enabled"]["value"] is True

    def test_config_has_sandbox_timeout(self, work_mode):
        """配置应包含沙箱超时时间."""
        config = _run_async(work_mode.get_config())
        assert "sandbox_timeout" in config
        assert config["sandbox_timeout"]["type"] == "number"
        assert config["sandbox_timeout"]["value"] == 10

    def test_config_item_structure(self, work_mode):
        """每个配置项应具有标准结构."""
        config = _run_async(work_mode.get_config())
        for key, item in config.items():
            assert "name" in item, f"{key} 缺少 name"
            assert "description" in item, f"{key} 缺少 description"
            assert "type" in item, f"{key} 缺少 type"
            assert "value" in item, f"{key} 缺少 value"


# ============================================================================
# 数据模型测试
# ============================================================================

class TestWorkDevModels:
    """工作开发模式数据模型测试"""

    def test_project_create_request_valid(self):
        """项目创建请求模型验证 - 有效数据."""
        req = ProjectCreateRequest(
            name="测试项目",
            description="这是一个测试项目",
            language="python",
            status="planning",
        )
        assert req.name == "测试项目"
        assert req.language == "python"
        assert req.status == "planning"

    def test_project_create_request_empty_name_raises(self):
        """项目创建请求 - 空名称应抛出验证错误."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ProjectCreateRequest(name="")

    def test_task_create_request_valid(self):
        """任务创建请求模型验证 - 有效数据."""
        req = TaskCreateRequest(
            title="测试任务",
            description="任务描述",
            status="todo",
            priority="high",
            project_id=1,
        )
        assert req.title == "测试任务"
        assert req.priority == "high"
        assert req.project_id == 1

    def test_task_create_request_default_values(self):
        """任务创建请求 - 默认值测试."""
        req = TaskCreateRequest(title="测试任务")
        assert req.status == "todo"
        assert req.priority == "medium"
        assert req.project_id == 0
        assert req.tags == []

    def test_task_status_update_request(self):
        """任务状态更新请求模型测试."""
        req = TaskStatusUpdateRequest(status="done")
        assert req.status == "done"

    def test_code_execute_request_valid(self):
        """代码执行请求模型验证 - 有效数据."""
        req = CodeExecuteRequest(
            language="python",
            code="print('hello')",
            stdin="",
        )
        assert req.language == "python"
        assert "print" in req.code

    def test_code_generate_request_valid(self):
        """代码生成请求模型验证 - 有效数据."""
        req = CodeGenerateRequest(
            prompt="写一个排序算法",
            language="python",
        )
        assert req.prompt == "写一个排序算法"
        assert req.language == "python"

    def test_task_create_request_negative_project_id(self):
        """任务创建请求 - 负的项目ID应抛出验证错误."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TaskCreateRequest(title="测试", project_id=-1)

    def test_task_create_request_negative_estimate(self):
        """任务创建请求 - 负的预估工时应抛出验证错误."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TaskCreateRequest(title="测试", estimate_hours=-5)
