"""
M4 单元测试 - 情绪陪伴模式测试 (P1 质量债务)

覆盖: 模式基本信息、场景进入/退出、消息处理、配置管理、数据模型
运行: python -m pytest tests/test_mode_emotion_comfort.py -v
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.modes.emotion_comfort.mode import EmotionComfortMode
from src.modes.emotion_comfort.models import (
    EmotionRecordRequest, AssessmentSubmitRequest,
    MoodEntryRequest, EmotionStats, EmotionOverview,
)


def _run_async(coro):
    """辅助函数：同步运行异步代码."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def emotion_mode():
    """创建情绪陪伴模式实例."""
    return EmotionComfortMode()


@pytest.fixture
def mock_service():
    """创建模拟的 EmotionService."""
    service = MagicMock()
    service.get_overview.return_value = {
        "stats": {
            "total_records": 30,
            "dominant_emotion": "calm",
            "avg_level": 7,
        },
        "current_mood": {"emotion": "happy", "level": 8},
    }
    return service


class TestEmotionComfortModeInfo:
    """情绪陪伴模式基本信息测试"""

    def test_mode_id(self, emotion_mode):
        assert emotion_mode.mode_id == "emotion_comfort"

    def test_mode_name(self, emotion_mode):
        assert emotion_mode.mode_name == "情绪陪伴"

    def test_mode_description(self, emotion_mode):
        assert "心理健康" in emotion_mode.mode_description

    def test_mode_icon(self, emotion_mode):
        assert emotion_mode.icon == "💗"

    def test_mode_category(self, emotion_mode):
        assert emotion_mode.category == "emotion"

    def test_mode_priority(self, emotion_mode):
        assert emotion_mode.priority == 7

    def test_mode_enabled(self, emotion_mode):
        assert emotion_mode.is_enabled is True

    def test_get_info_complete(self, emotion_mode):
        info = emotion_mode.get_info()
        assert info["mode_id"] == "emotion_comfort"
        assert info["mode_name"] == "情绪陪伴"


class TestEmotionComfortModeLifecycle:
    """情绪陪伴模式生命周期测试"""

    def test_on_enter_handles_db_error_gracefully(self, emotion_mode):
        """进入模式时DB异常应优雅降级."""
        # 不mock DB，触发异常后应降级处理
        result = _run_async(emotion_mode.on_enter({"user_id": "test_user"}))
        assert result["success"] is True
        assert result["context_updates"]["current_mode"] == "emotion_comfort"

    def test_on_enter_contains_features(self, emotion_mode):
        """进入模式返回数据应包含功能列表."""
        result = _run_async(emotion_mode.on_enter({"user_id": "test_user"}))
        assert "features" in result["data"]
        assert len(result["data"]["features"]) >= 5

    def test_on_enter_contains_overview(self, emotion_mode):
        """进入模式返回数据应包含概览."""
        result = _run_async(emotion_mode.on_enter({"user_id": "test_user"}))
        assert "overview" in result["data"]
        assert "emotion_overview" in result["context_updates"]

    def test_on_leave_success(self, emotion_mode):
        result = _run_async(emotion_mode.on_leave({"user_id": "test_user"}))
        assert result["success"] is True
        assert result["context_updates"].get("previous_mode") == "emotion_comfort"

    def test_on_leave_warm_message(self, emotion_mode):
        result = _run_async(emotion_mode.on_leave({"user_id": "test_user"}))
        assert "照顾好自己" in result["message"] or "随时回来" in result["message"]


class TestEmotionComfortModeMessageHandling:
    """情绪陪伴模式消息处理测试"""

    def test_handle_sad_emotion(self, emotion_mode):
        """处理悲伤情绪."""
        result = _run_async(emotion_mode.handle_message("我今天好难过", {"user_id": "u1"}))
        assert result["success"] is True
        assert "心情" in result["reply"] or "难过" in result["reply"] or "说说" in result["reply"]

    def test_handle_anxious_emotion(self, emotion_mode):
        """处理焦虑情绪."""
        result = _run_async(emotion_mode.handle_message("最近很焦虑压力很大", {"user_id": "u1"}))
        assert result["success"] is True
        assert "深呼吸" in result["reply"] or "焦虑" in result["reply"] or "陪着你" in result["reply"]

    def test_handle_angry_emotion(self, emotion_mode):
        """处理愤怒情绪."""
        result = _run_async(emotion_mode.handle_message("我真的很生气", {"user_id": "u1"}))
        assert result["success"] is True
        assert "冷静" in result["reply"] or "生气" in result["reply"]

    def test_handle_tired_emotion(self, emotion_mode):
        """处理疲惫情绪."""
        result = _run_async(emotion_mode.handle_message("好累啊没精力", {"user_id": "u1"}))
        assert result["success"] is True
        assert "休息" in result["reply"] or "累" in result["reply"]

    def test_handle_happy_emotion(self, emotion_mode):
        """处理开心情绪."""
        result = _run_async(emotion_mode.handle_message("今天好开心", {"user_id": "u1"}))
        assert result["success"] is True
        assert "高兴" in result["reply"] or "开心" in result["reply"] or "分享" in result["reply"]

    def test_handle_sleep_problem(self, emotion_mode):
        """处理睡眠问题."""
        result = _run_async(emotion_mode.handle_message("最近失眠睡不着", {"user_id": "u1"}))
        assert result["success"] is True
        assert "睡眠" in result["reply"] or "放松" in result["reply"]

    def test_handle_relax_request(self, emotion_mode):
        """处理放松请求."""
        result = _run_async(emotion_mode.handle_message("我想放松一下", {"user_id": "u1"}))
        assert result["success"] is True
        assert "放松" in result["reply"]

    def test_handle_assessment_request(self, emotion_mode):
        """处理测评请求."""
        result = _run_async(emotion_mode.handle_message("我想做个心理测试", {"user_id": "u1"}))
        assert result["success"] is True
        assert "测评" in result["reply"]

    def test_handle_diary_request(self, emotion_mode):
        """处理日记请求."""
        result = _run_async(emotion_mode.handle_message("我想写心情日记", {"user_id": "u1"}))
        assert result["success"] is True
        assert "日记" in result["reply"]

    def test_handle_default_message(self, emotion_mode):
        """处理默认消息."""
        result = _run_async(emotion_mode.handle_message("随便聊聊", {"user_id": "u1"}))
        assert result["success"] is True
        assert "我在听" in result["reply"] or "感受" in result["reply"]

    def test_generate_reply_returns_string(self, emotion_mode):
        """_generate_reply 应返回字符串."""
        reply = emotion_mode._generate_reply("测试")
        assert isinstance(reply, str)
        assert len(reply) > 0

    def test_handle_message_structure(self, emotion_mode):
        """消息处理结果结构应完整."""
        result = _run_async(emotion_mode.handle_message("你好", {"user_id": "u1"}))
        assert "success" in result
        assert "reply" in result
        assert "data" in result
        assert "context_updates" in result


class TestEmotionComfortModeConfig:
    """情绪陪伴模式配置管理测试"""

    def test_get_config_returns_dict(self, emotion_mode):
        config = _run_async(emotion_mode.get_config())
        assert isinstance(config, dict)

    def test_config_has_daily_reminder(self, emotion_mode):
        config = _run_async(emotion_mode.get_config())
        assert "daily_reminder" in config
        assert config["daily_reminder"]["type"] == "boolean"

    def test_config_has_default_mood_view(self, emotion_mode):
        config = _run_async(emotion_mode.get_config())
        assert "default_mood_view" in config
        assert config["default_mood_view"]["type"] == "select"

    def test_config_item_structure(self, emotion_mode):
        config = _run_async(emotion_mode.get_config())
        for key, item in config.items():
            assert "name" in item
            assert "type" in item
            assert "value" in item


class TestEmotionComfortModels:
    """情绪陪伴模式数据模型测试"""

    def test_emotion_record_valid(self):
        req = EmotionRecordRequest(emotion="happy", level=8, trigger="完成项目")
        assert req.emotion == "happy"
        assert req.level == 8

    def test_emotion_record_level_out_of_range_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            EmotionRecordRequest(emotion="sad", level=11)

    def test_emotion_record_level_zero_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            EmotionRecordRequest(emotion="sad", level=0)

    def test_assessment_submit_valid(self):
        req = AssessmentSubmitRequest(assessment_id=1, answers={"q1": 0, "q2": 1})
        assert req.assessment_id == 1
        assert len(req.answers) == 2

    def test_mood_entry_valid(self):
        req = MoodEntryRequest(emotion="calm", content="今天很平静", tags=["平静", "工作"])
        assert req.emotion == "calm"
        assert len(req.tags) == 2

    def test_emotion_stats_defaults(self):
        stats = EmotionStats()
        assert stats.total_records == 0
        assert stats.dominant_emotion == ""

    def test_emotion_overview_defaults(self):
        overview = EmotionOverview()
        assert overview.current_mood is None
        assert isinstance(overview.stats, dict)
