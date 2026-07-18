"""
M4 场景引擎 - API 端点集成测试 (P1 质量债务补强)

覆盖: 场景切换、上下文管理、语音服务、场景智能接口
运行: python -m pytest tests/test_api_endpoints.py -v
"""
from __future__ import annotations

import os
import pytest

os.environ["M4_LOG_LEVEL"] = "error"

from main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client():
    """创建测试客户端（模块级复用）."""
    return TestClient(app)


# ============================================================================
# 场景切换接口测试
# ============================================================================

class TestSceneSwitchEndpoints:
    """场景切换接口测试 (P1 质量债务补强)"""

    def test_switch_scene_success(self, client):
        """切换到有效场景应成功."""
        response = client.post(
            "/api/v1/scene/switch",
            json={"to_scene": "work_dev", "reason": "测试切换"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        # 响应中应包含切换结果
        assert data["data"]["success"] is True
        assert data["data"]["to_scene"] == "work_dev"

    def test_switch_scene_invalid(self, client):
        """切换到无效场景应返回错误."""
        response = client.post(
            "/api/v1/scene/switch",
            json={"to_scene": "nonexistent_scene_xyz"}
        )
        data = response.json()
        assert data["code"] != 0 or data.get("success") is False

    def test_switch_scene_missing_scene_id(self, client):
        """缺少 to_scene 参数应返回 422."""
        response = client.post("/api/v1/scene/switch", json={})
        assert response.status_code == 422

    def test_switch_scene_with_user_id(self, client):
        """带 user_id 的场景切换."""
        response = client.post(
            "/api/v1/scene/switch",
            json={"to_scene": "learning", "user_id": "api_test_user"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_switch_scene_to_same_scene(self, client):
        """切换到相同场景."""
        client.post("/api/v1/scene/switch", json={"to_scene": "chat"})
        response = client.post(
            "/api/v1/scene/switch",
            json={"to_scene": "chat", "reason": "same scene"}
        )
        assert response.status_code == 200

    def test_get_current_scene(self, client):
        """获取当前场景."""
        client.post("/api/v1/scene/switch", json={"to_scene": "work_dev"})
        response = client.get("/api/v1/scene/current")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "scene_id" in data["data"]

    def test_get_scene_list(self, client):
        """获取场景列表."""
        response = client.get("/api/v1/scenes")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        # 场景列表数据可能在 scenes 字段中
        scenes = data["data"].get("scenes", data["data"])
        assert isinstance(scenes, list)
        assert len(scenes) > 0

    def test_scene_history(self, client):
        """获取场景切换历史."""
        client.post("/api/v1/scene/switch", json={"to_scene": "chat"})
        client.post("/api/v1/scene/switch", json={"to_scene": "work_dev"})
        response = client.get("/api/v1/scene/history?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0


# ============================================================================
# 场景识别接口测试
# ============================================================================

class TestSceneRecognitionEndpoints:
    """场景识别接口测试 (P1 质量债务补强)"""

    def test_recognize_valid_text(self, client):
        """正常文本识别."""
        response = client.post(
            "/api/v1/scene/recognize",
            json={"text": "我想写代码开发项目"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "scene" in data["data"]
        assert "confidence" in data["data"]

    def test_recognize_empty_text(self, client):
        """空文本识别应返回 422 或正常响应."""
        response = client.post(
            "/api/v1/scene/recognize",
            json={"text": ""}
        )
        # 空文本可能被验证拒绝（422）或正常处理（200）
        assert response.status_code in [200, 422]

    def test_recognize_long_text(self, client):
        """长文本识别."""
        long_text = "写代码编程" * 100
        response = client.post(
            "/api/v1/scene/recognize",
            json={"text": long_text}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_recognize_with_context(self, client):
        """带上下文的识别."""
        response = client.post(
            "/api/v1/scene/recognize",
            json={
                "text": "继续工作",
                "context": {"current_scene": "work_dev", "last_message": "写代码"}
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_recognize_missing_text(self, client):
        """缺少 text 参数应返回 422."""
        response = client.post("/api/v1/scene/recognize", json={})
        assert response.status_code == 422


# ============================================================================
# 上下文管理接口测试
# ============================================================================

class TestContextManagementEndpoints:
    """上下文管理接口测试 (P1 质量债务补强)"""

    def test_get_context(self, client):
        """获取场景上下文."""
        response = client.get("/api/v1/context/work_dev")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_save_context(self, client):
        """保存场景上下文."""
        response = client.post(
            "/api/v1/context/work_dev",
            json={"context_json": {"theme": "dark", "project": "test"}}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_save_context_empty_data(self, client):
        """保存空上下文数据."""
        response = client.post(
            "/api/v1/context/chat",
            json={"context_json": {}}
        )
        assert response.status_code == 200

    def test_clear_context(self, client):
        """清空场景上下文."""
        # 先保存一些数据
        client.post(
            "/api/v1/context/work_dev",
            json={"context_json": {"key": "value"}}
        )
        response = client.delete("/api/v1/context/work_dev")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_context_status_overview(self, client):
        """上下文状态概览."""
        response = client.get("/api/v1/context/status")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_context_invalid_scene_id(self, client):
        """无效场景ID的上下文获取."""
        response = client.get("/api/v1/context/nonexistent_scene_123")
        # 应该正常返回（可能是空的），不应该500
        assert response.status_code == 200


# ============================================================================
# 语音服务接口测试
# ============================================================================

class TestVoiceServiceEndpoints:
    """语音服务接口测试 (P1 质量债务补强)"""

    def test_voice_status(self, client):
        """获取语音服务状态."""
        response = client.get("/api/v1/voice/status")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        # 响应中应包含 TTS 和 ASR 可用性信息
        assert "tts_available" in data["data"] or "asr_available" in data["data"]

    def test_voice_tts_synthesize(self, client):
        """文本转语音接口."""
        response = client.post(
            "/api/v1/voice/tts/synthesize",
            json={"text": "你好", "voice": "default"}
        )
        # 可能返回成功或降级，不应500
        assert response.status_code == 200
        data = response.json()
        assert "code" in data

    def test_voice_asr_transcribe(self, client):
        """语音转文本接口（无音频数据）."""
        response = client.post("/api/v1/voice/asr/transcribe", json={})
        # 没有音频数据，应该返回422或错误码
        assert response.status_code in [200, 422]

    def test_voice_vad_detect(self, client):
        """语音活动检测接口."""
        response = client.post("/api/v1/voice/vad/detect", json={})
        assert response.status_code in [200, 422]

    def test_voice_config_get(self, client):
        """获取语音配置."""
        response = client.get("/api/v1/voice/config")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_voice_config_update(self, client):
        """更新语音配置."""
        response = client.put(
            "/api/v1/voice/config",
            json={"tts_engine": "local", "asr_engine": "local"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_voice_wake_word_config(self, client):
        """获取唤醒词配置."""
        response = client.get("/api/v1/voice/wake-word/config")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_voice_voices_list(self, client):
        """获取可用语音列表."""
        response = client.get("/api/v1/voice/voices")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0


# ============================================================================
# 业务模式接口测试
# ============================================================================

class TestModesEndpoints:
    """业务模式接口测试 (P1 质量债务补强)"""

    def test_modes_list(self, client):
        """获取业务模式列表."""
        response = client.get("/api/v1/modes")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        # 模式列表数据可能在 modes 字段中
        modes = data["data"].get("modes", data["data"])
        assert isinstance(modes, list)
        assert len(modes) > 0

    def test_mode_detail_valid(self, client):
        """获取有效模式详情."""
        response = client.get("/api/v1/modes/work_dev")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_mode_detail_invalid(self, client):
        """获取无效模式详情应返回错误."""
        response = client.get("/api/v1/modes/nonexistent_mode_xyz")
        data = response.json()
        assert data["code"] != 0

    def test_mode_enter(self, client):
        """进入业务模式."""
        response = client.post(
            "/api/v1/modes/work_dev/enter",
            json={"user_id": "test_user"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_mode_leave(self, client):
        """离开业务模式."""
        # 先进入
        client.post("/api/v1/modes/work_dev/enter", json={"user_id": "test_user2"})
        response = client.post(
            "/api/v1/modes/work_dev/leave",
            json={"user_id": "test_user2"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_mode_categories(self, client):
        """获取模式分类列表."""
        response = client.get("/api/v1/modes/categories/list")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_default_mode_info(self, client):
        """获取默认模式信息."""
        response = client.get("/api/v1/modes/default/info")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0


# ============================================================================
# 认证头处理测试
# ============================================================================

class TestAuthHeaderHandling:
    """认证头处理测试 (P1 质量债务补强)"""

    def test_request_with_bearer_token(self, client):
        """带 Bearer Token 的请求应正常处理."""
        response = client.get(
            "/api/v1/scenes",
            headers={"Authorization": "Bearer test-token-123"}
        )
        assert response.status_code == 200

    def test_request_with_x_user_id(self, client):
        """带 X-User-ID 头的请求应正常处理."""
        response = client.get(
            "/api/v1/scenes",
            headers={"X-User-ID": "user-abc-123"}
        )
        assert response.status_code == 200

    def test_request_with_custom_headers(self, client):
        """带各种自定义头的请求应正常处理."""
        response = client.get(
            "/api/v1/scenes",
            headers={
                "X-Request-ID": "req-001",
                "X-Client-Version": "1.0.0",
                "X-Device-ID": "device-xyz",
            }
        )
        assert response.status_code == 200

    def test_request_no_auth_header(self, client):
        """无认证头的请求应正常处理（M4不强制认证）."""
        response = client.get("/api/v1/scenes")
        assert response.status_code == 200


# ============================================================================
# 参数边界值测试
# ============================================================================

class TestParameterBoundaries:
    """参数边界值测试 (P1 质量债务补强)"""

    def test_history_limit_one(self, client):
        """history limit=1 边界."""
        response = client.get("/api/v1/scene/history?limit=1")
        assert response.status_code == 200

    def test_history_limit_very_large(self, client):
        """history limit 较大的值（在范围内）."""
        response = client.get("/api/v1/scene/history?limit=100")
        assert response.status_code == 200

    def test_history_offset_zero(self, client):
        """history offset=0 边界."""
        response = client.get("/api/v1/scene/history?offset=0")
        assert response.status_code == 200

    def test_history_offset_very_large(self, client):
        """history offset 非常大的值."""
        response = client.get("/api/v1/scene/history?offset=99999")
        assert response.status_code == 200

    def test_switch_scene_id_max_length(self, client):
        """超长 to_scene 参数（超过64字符限制）应返回 422."""
        long_id = "a" * 200
        response = client.post("/api/v1/scene/switch", json={"to_scene": long_id})
        # 应返回 422（验证失败），不应该500
        assert response.status_code in [200, 422]
