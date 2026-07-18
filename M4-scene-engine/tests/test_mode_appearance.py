"""
M4 单元测试 - 形象工坊模式测试 (P1 质量债务)

覆盖: 模式基本信息、场景进入/退出、消息处理、配置管理、数据模型
运行: python -m pytest tests/test_mode_appearance.py -v
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.modes.appearance.mode import AppearanceMode
from src.modes.appearance.models import (
    ConfigUpdateRequest, MoodUpdateRequest,
    PersonalityTagsUpdateRequest, SnapshotSaveRequest,
    ThemeInfo,
)


def _run_async(coro):
    """辅助函数：同步运行异步代码."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def appearance_mode():
    """创建形象工坊模式实例."""
    return AppearanceMode()


@pytest.fixture
def mock_service():
    """创建模拟的 AppearanceService."""
    service = MagicMock()
    service.get_config.return_value = {
        "theme": "default",
        "particle_count": 120,
        "glow_intensity": 0.8,
        "voice_type": "warm_female",
    }
    service.get_relationship.return_value = {
        "level": 3,
        "name": "挚友",
        "intimacy": 750,
        "next_level": 1000,
    }
    return service


class TestAppearanceModeInfo:
    """形象工坊模式基本信息测试"""

    def test_mode_id(self, appearance_mode):
        assert appearance_mode.mode_id == "appearance"

    def test_mode_name(self, appearance_mode):
        assert appearance_mode.mode_name == "形象工坊"

    def test_mode_description(self, appearance_mode):
        assert "形象" in appearance_mode.mode_description

    def test_mode_icon(self, appearance_mode):
        assert appearance_mode.icon == "👗"

    def test_mode_category(self, appearance_mode):
        assert appearance_mode.category == "appearance"

    def test_mode_priority(self, appearance_mode):
        assert appearance_mode.priority == 8

    def test_mode_enabled(self, appearance_mode):
        assert appearance_mode.is_enabled is True

    def test_get_info_complete(self, appearance_mode):
        info = appearance_mode.get_info()
        assert info["mode_id"] == "appearance"
        assert info["mode_name"] == "形象工坊"


class TestAppearanceModeLifecycle:
    """形象工坊模式生命周期测试"""

    def test_on_enter_handles_db_error_gracefully(self, appearance_mode):
        """进入模式时DB异常应优雅降级."""
        result = _run_async(appearance_mode.on_enter({"user_id": "test_user"}))
        assert result["success"] is True
        assert result["context_updates"]["current_mode"] == "appearance"

    def test_on_enter_contains_features(self, appearance_mode):
        """进入模式返回数据应包含功能列表."""
        result = _run_async(appearance_mode.on_enter({"user_id": "test_user"}))
        assert "features" in result["data"]
        assert len(result["data"]["features"]) >= 5

    def test_on_enter_contains_config(self, appearance_mode):
        """进入模式返回数据应包含配置."""
        result = _run_async(appearance_mode.on_enter({"user_id": "test_user"}))
        assert "config" in result["data"]
        assert "appearance_config" in result["context_updates"]

    def test_on_leave_success(self, appearance_mode):
        result = _run_async(appearance_mode.on_leave({"user_id": "test_user"}))
        assert result["success"] is True
        assert result["context_updates"].get("previous_mode") == "appearance"

    def test_on_leave_message(self, appearance_mode):
        result = _run_async(appearance_mode.on_leave({"user_id": "test_user"}))
        assert "形象" in result["message"] or "保存" in result["message"]


class TestAppearanceModeMessageHandling:
    """形象工坊模式消息处理测试"""

    def test_handle_theme(self, appearance_mode):
        """处理主题切换请求."""
        result = _run_async(appearance_mode.handle_message("我想换个主题", {"user_id": "u1"}))
        assert result["success"] is True
        assert "主题" in result["reply"]

    def test_handle_mood(self, appearance_mode):
        """处理心情切换请求."""
        result = _run_async(appearance_mode.handle_message("我的心情怎么样", {"user_id": "u1"}))
        assert result["success"] is True
        assert "心情" in result["reply"]

    def test_handle_personality(self, appearance_mode):
        """处理性格标签请求."""
        result = _run_async(appearance_mode.handle_message("我的性格标签", {"user_id": "u1"}))
        assert result["success"] is True
        assert "性格" in result["reply"]

    def test_handle_voice(self, appearance_mode):
        """处理声音设置请求."""
        result = _run_async(appearance_mode.handle_message("切换声音", {"user_id": "u1"}))
        assert result["success"] is True
        assert "声音" in result["reply"]

    def test_handle_relationship(self, appearance_mode):
        """处理关系/亲密度请求."""
        result = _run_async(appearance_mode.handle_message("我们的关系", {"user_id": "u1"}))
        assert result["success"] is True
        assert "关系" in result["reply"] or "陪伴" in result["reply"] or "亲密度" in result["reply"]

    def test_handle_fashion(self, appearance_mode):
        """处理穿搭请求."""
        result = _run_async(appearance_mode.handle_message("今天穿什么搭配", {"user_id": "u1"}))
        assert result["success"] is True
        assert "穿搭" in result["reply"] or "风格" in result["reply"]

    def test_handle_default(self, appearance_mode):
        """处理默认消息."""
        result = _run_async(appearance_mode.handle_message("随便看看", {"user_id": "u1"}))
        assert result["success"] is True
        assert "形象工坊" in result["reply"] or "主题" in result["reply"] or "调整" in result["reply"]

    def test_generate_reply_returns_string(self, appearance_mode):
        """_generate_reply 应返回字符串."""
        reply = appearance_mode._generate_reply("测试")
        assert isinstance(reply, str)
        assert len(reply) > 0

    def test_handle_message_structure(self, appearance_mode):
        """消息处理结果结构应完整."""
        result = _run_async(appearance_mode.handle_message("你好", {"user_id": "u1"}))
        assert "success" in result
        assert "reply" in result
        assert "data" in result
        assert result["data"].get("mode") == "appearance"


class TestAppearanceModeConfig:
    """形象工坊模式配置管理测试"""

    def test_get_config_returns_dict(self, appearance_mode):
        config = _run_async(appearance_mode.get_config())
        assert isinstance(config, dict)

    def test_config_has_default_theme(self, appearance_mode):
        config = _run_async(appearance_mode.get_config())
        assert "default_theme" in config
        assert config["default_theme"]["type"] == "select"

    def test_config_has_particle_count(self, appearance_mode):
        config = _run_async(appearance_mode.get_config())
        assert "particle_count" in config
        assert config["particle_count"]["type"] == "number"

    def test_config_has_voice_type(self, appearance_mode):
        config = _run_async(appearance_mode.get_config())
        assert "voice_type" in config
        assert config["voice_type"]["type"] == "select"

    def test_config_item_structure(self, appearance_mode):
        config = _run_async(appearance_mode.get_config())
        for key, item in config.items():
            assert "name" in item
            assert "type" in item
            assert "value" in item


class TestAppearanceModels:
    """形象工坊模式数据模型测试"""

    def test_config_update_theme(self):
        req = ConfigUpdateRequest(theme="ocean", particle_count=100)
        assert req.theme == "ocean"
        assert req.particle_count == 100

    def test_config_update_voice(self):
        req = ConfigUpdateRequest(voice_type="gentle_male", voice_speed=1.0)
        assert req.voice_type == "gentle_male"
        assert req.voice_speed == 1.0

    def test_mood_update_valid(self):
        req = MoodUpdateRequest(mood="happy")
        assert req.mood == "happy"

    def test_personality_tags_update_valid(self):
        req = PersonalityTagsUpdateRequest(tags=["温柔", "智慧", "幽默"])
        assert len(req.tags) == 3
        assert "温柔" in req.tags

    def test_snapshot_save_valid(self):
        req = SnapshotSaveRequest(name="我的日常形象")
        assert req.name == "我的日常形象"

    def test_theme_info_defaults(self):
        theme = ThemeInfo(id="sunset", name="落日余晖")
        assert theme.id == "sunset"
        assert theme.name == "落日余晖"

    def test_config_update_all_optional(self):
        """ConfigUpdateRequest 所有字段都是可选的."""
        req = ConfigUpdateRequest()
        assert req.theme is None
        assert req.particle_count is None
        assert req.voice_type is None
