"""
M4 单元测试 - 核心数据模型测试 (P1 质量债务)

覆盖: 场景状态模型、上下文模型、用户配置模型、数据库模型、请求/响应模型
运行: python -m pytest tests/test_data_models.py -v
"""
import json
import time

import pytest

from src.models import (
    SCENE_DEFINITIONS, DEFAULT_SCENE,
    SceneSwitchRecord, SceneContext,
    make_response,
)
from src.models.db import (
    SceneContextDB, SceneSwitchHistoryDB, SceneConfigDB,
    CurrentSceneDB, GlobalConfigDB,
)
from src.models.api_requests import (
    SceneSwitchRequest, SceneRecognizeRequest,
    ContextSaveRequest, ChatSendRequest,
)
from src.models.scene_definitions import ACTION_TYPES


# ============================================================================
# 场景定义数据模型测试
# ============================================================================

class TestSceneDefinitions:
    """场景定义数据模型测试"""

    def test_default_scene_exists(self):
        """默认场景应存在于定义中."""
        assert DEFAULT_SCENE in SCENE_DEFINITIONS

    def test_all_scenes_have_required_fields(self):
        """所有场景定义应包含必要字段."""
        required_fields = ["id", "name", "icon", "description", "tone", "keywords"]
        for scene_id, scene_def in SCENE_DEFINITIONS.items():
            for field in required_fields:
                assert field in scene_def, f"{scene_id} 缺少 {field}"

    def test_all_scenes_have_keywords_list(self):
        """所有场景应有关键词列表且非空."""
        for scene_id, scene_def in SCENE_DEFINITIONS.items():
            keywords = scene_def.get("keywords", [])
            assert isinstance(keywords, list), f"{scene_id} 关键词不是列表"
            assert len(keywords) > 0, f"{scene_id} 关键词列表为空"

    def test_scene_id_matches_definition_id(self):
        """场景ID应与定义中的id一致."""
        for scene_id, scene_def in SCENE_DEFINITIONS.items():
            assert scene_id == scene_def["id"], f"{scene_id} 与定义id不一致"

    def test_action_types_is_list(self):
        """ACTION_TYPES 应为列表."""
        assert isinstance(ACTION_TYPES, list)
        assert len(ACTION_TYPES) > 0

    def test_scene_count(self):
        """场景数量应 >= 12."""
        assert len(SCENE_DEFINITIONS) >= 12

    def test_business_mode_flag(self):
        """业务模式场景应有 is_business_mode 标识."""
        business_modes = ["growth", "review", "study_plan", "life_management",
                          "social_relation", "emotion_comfort", "appearance", "work_dev"]
        for mode in business_modes:
            if mode in SCENE_DEFINITIONS:
                assert SCENE_DEFINITIONS[mode].get("is_business_mode") is True


# ============================================================================
# 场景切换记录数据类测试
# ============================================================================

class TestSceneSwitchRecord:
    """场景切换记录数据类测试"""

    def test_create_default_record(self):
        """创建默认切换记录."""
        record = SceneSwitchRecord()
        assert record.id == ""
        assert record.from_scene == ""
        assert record.to_scene == ""
        assert record.trigger_type == "manual"
        assert record.user_id == "default"
        assert record.timestamp == 0.0
        assert record.reason == ""

    def test_create_record_with_values(self):
        """创建带值的切换记录."""
        record = SceneSwitchRecord(
            id="rec123",
            from_scene="chat",
            to_scene="work_dev",
            trigger_type="recognize",
            user_id="user1",
            timestamp=1234567890.0,
            reason="用户请求切换",
        )
        assert record.id == "rec123"
        assert record.from_scene == "chat"
        assert record.to_scene == "work_dev"
        assert record.trigger_type == "recognize"
        assert record.user_id == "user1"
        assert record.timestamp == 1234567890.0
        assert record.reason == "用户请求切换"

    def test_record_is_dataclass(self):
        """SceneSwitchRecord 应可作为数据类使用."""
        record = SceneSwitchRecord(to_scene="learning")
        assert record.to_scene == "learning"
        # 可以修改属性
        record.from_scene = "chat"
        assert record.from_scene == "chat"


# ============================================================================
# 场景上下文数据类测试
# ============================================================================

class TestSceneContext:
    """场景上下文数据类测试"""

    def test_create_default_context(self):
        """创建默认上下文."""
        ctx = SceneContext()
        assert ctx.scene_id == ""
        assert ctx.context_data == {}
        assert ctx.last_updated == 0.0
        assert ctx.update_count == 0

    def test_create_context_with_data(self):
        """创建带数据的上下文."""
        data = {"theme": "dark", "language": "zh"}
        ctx = SceneContext(
            scene_id="work_dev",
            context_data=data,
            last_updated=time.time(),
            update_count=5,
        )
        assert ctx.scene_id == "work_dev"
        assert ctx.context_data["theme"] == "dark"
        assert ctx.update_count == 5

    def test_context_data_is_mutable(self):
        """上下文数据应可修改."""
        ctx = SceneContext(scene_id="chat", context_data={"key": "value"})
        ctx.context_data["new_key"] = "new_value"
        assert ctx.context_data["new_key"] == "new_value"
        ctx.update_count += 1
        assert ctx.update_count == 1


# ============================================================================
# 数据库 ORM 模型测试
# ============================================================================

class TestSceneContextDBModel:
    """场景上下文数据库模型测试"""

    def test_to_dict_returns_dict(self):
        """to_dict 应返回字典."""
        db_obj = SceneContextDB(
            user_id="user1",
            scene_id="work_dev",
            context_data=json.dumps({"theme": "dark"}),
            update_count=3,
        )
        result = db_obj.to_dict()
        assert isinstance(result, dict)
        assert result["user_id"] == "user1"
        assert result["scene_id"] == "work_dev"
        assert result["context_data"]["theme"] == "dark"
        assert result["update_count"] == 3

    def test_to_dict_empty_json(self):
        """空 JSON 字符串应解析为空字典."""
        db_obj = SceneContextDB(
            user_id="user1",
            scene_id="chat",
            context_data="{}",
        )
        result = db_obj.to_dict()
        assert result["context_data"] == {}

    def test_table_name(self):
        """表名应正确."""
        assert SceneContextDB.__tablename__ == "scene_contexts"


class TestSceneSwitchHistoryDBModel:
    """场景切换历史数据库模型测试"""

    def test_to_dict_returns_dict(self):
        """to_dict 应返回字典."""
        db_obj = SceneSwitchHistoryDB(
            record_id="rec001",
            user_id="user1",
            from_scene="chat",
            to_scene="work_dev",
            trigger_type="manual",
            reason="测试",
        )
        result = db_obj.to_dict()
        assert isinstance(result, dict)
        assert result["id"] == "rec001"
        assert result["from_scene"] == "chat"
        assert result["to_scene"] == "work_dev"
        assert result["trigger_type"] == "manual"

    def test_table_name(self):
        """表名应正确."""
        assert SceneSwitchHistoryDB.__tablename__ == "scene_switch_history"


class TestSceneConfigDBModel:
    """场景配置数据库模型测试"""

    def test_to_dict_returns_dict(self):
        """to_dict 应返回字典."""
        config = {"theme": "dark", "notifications": True}
        db_obj = SceneConfigDB(
            scene_id="work_dev",
            config=json.dumps(config),
        )
        result = db_obj.to_dict()
        assert result["scene_id"] == "work_dev"
        assert result["config"]["theme"] == "dark"

    def test_table_name(self):
        """表名应正确."""
        assert SceneConfigDB.__tablename__ == "scene_configs"


class TestCurrentSceneDBModel:
    """当前场景状态数据库模型测试"""

    def test_to_dict_returns_dict(self):
        """to_dict 应返回字典."""
        db_obj = CurrentSceneDB(
            user_id="user1",
            current_scene="work_dev",
            switch_count=10,
        )
        result = db_obj.to_dict()
        assert result["user_id"] == "user1"
        assert result["current_scene"] == "work_dev"
        assert result["switch_count"] == 10

    def test_table_name(self):
        """表名应正确."""
        assert CurrentSceneDB.__tablename__ == "current_scenes"


class TestGlobalConfigDBModel:
    """全局配置数据库模型测试"""

    def test_to_dict_returns_dict(self):
        """to_dict 应返回字典."""
        db_obj = GlobalConfigDB(
            config_key="default_scene",
            config_value=json.dumps("chat"),
        )
        result = db_obj.to_dict()
        assert result["config_key"] == "default_scene"
        assert result["config_value"] == "chat"

    def test_table_name(self):
        """表名应正确."""
        assert GlobalConfigDB.__tablename__ == "global_configs"


# ============================================================================
# API 请求模型测试
# ============================================================================

class TestSceneSwitchRequestModel:
    """场景切换请求模型测试"""

    def test_valid_request(self):
        """有效请求."""
        req = SceneSwitchRequest(to_scene="work_dev", reason="测试")
        assert req.to_scene == "work_dev"
        assert req.reason == "测试"

    def test_request_with_user_id(self):
        """带 user_id 的请求."""
        req = SceneSwitchRequest(to_scene="work_dev", user_id="user123")
        assert req.user_id == "user123"

    def test_scene_id_required(self):
        """to_scene 是必填的."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SceneSwitchRequest()


class TestSceneRecognizeRequestModel:
    """场景识别请求模型测试"""

    def test_valid_request(self):
        """有效请求."""
        req = SceneRecognizeRequest(text="我想写代码")
        assert req.text == "我想写代码"

    def test_request_with_context(self):
        """带上下文的请求."""
        req = SceneRecognizeRequest(
            text="继续开发",
            context={"current_scene": "work_dev"}
        )
        assert req.context is not None
        assert req.context["current_scene"] == "work_dev"


class TestContextSaveRequestModel:
    """上下文保存请求模型测试"""

    def test_valid_request(self):
        """有效请求."""
        req = ContextSaveRequest(
            context_json={"theme": "dark"}
        )
        assert req.context_json["theme"] == "dark"

    def test_empty_request(self):
        """空上下文请求（默认值）."""
        req = ContextSaveRequest()
        assert req.context_json == {}


class TestChatSendRequestModel:
    """聊天发送请求模型测试"""

    def test_valid_request(self):
        """有效请求."""
        req = ChatSendRequest(message="你好")
        assert req.message == "你好"


# ============================================================================
# 响应工具函数测试
# ============================================================================

class TestMakeResponse:
    """make_response 响应工具函数测试"""

    def test_response_with_data(self):
        """带数据的响应."""
        resp = make_response(data={"key": "value"})
        assert resp["code"] == 0
        assert resp["data"]["key"] == "value"
        assert "message" in resp

    def test_response_with_message(self):
        """带消息的响应."""
        resp = make_response(message="操作成功")
        assert resp["code"] == 0
        assert "操作成功" in resp["message"]

    def test_response_with_error_code(self):
        """带错误码的响应."""
        resp = make_response(code=400, message="参数错误")
        assert resp["code"] == 400
        assert "参数错误" in resp["message"]

    def test_response_structure(self):
        """响应结构应完整."""
        resp = make_response(data={})
        assert "code" in resp
        assert "message" in resp
        assert "data" in resp
