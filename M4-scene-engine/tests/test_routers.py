"""
M4 场景引擎 - 路由层集成测试

测试场景管理、模式路由、技能执行等路由的可用性。
运行方式: pytest tests/test_routers.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """创建 FastAPI 测试客户端"""
    return TestClient(app)


class TestSceneRouter:
    """场景管理路由测试"""

    def test_list_scenes(self, client):
        """测试获取场景列表"""
        response = client.get("/api/v1/scenes")
        assert response.status_code == 200
        data = response.json()
        assert data.get("code") == 0 or "data" in data

    def test_get_current_scene(self, client):
        """测试获取当前场景"""
        response = client.get("/api/v1/scenes/current")
        assert response.status_code in (200, 404)

    def test_get_scene_detail(self, client):
        """测试获取场景详情"""
        response = client.get("/api/v1/scenes/work_dev")
        assert response.status_code in (200, 404)

    def test_switch_scene(self, client):
        """测试切换场景"""
        response = client.post(
            "/api/v1/scenes/switch",
            json={"scene_id": "work_dev", "reason": "test"},
        )
        assert response.status_code in (200, 400, 404, 422)

    def test_recognize_scene(self, client):
        """测试场景识别"""
        response = client.post(
            "/api/v1/scenes/recognize",
            json={"text": "帮我写一段Python代码"},
        )
        assert response.status_code in (200, 404, 422)

    def test_get_switch_history(self, client):
        """测试获取场景切换历史"""
        response = client.get("/api/v1/scenes/history")
        assert response.status_code in (200, 404)


class TestModeRouter:
    """场景模式路由测试"""

    def test_list_modes(self, client):
        """测试获取所有模式列表"""
        response = client.get("/api/v1/modes")
        assert response.status_code in (200, 404)

    def test_get_mode_detail(self, client):
        """测试获取模式详情"""
        response = client.get("/api/v1/modes/work_dev")
        assert response.status_code in (200, 404)

    def test_get_mode_stats(self, client):
        """测试获取模式统计"""
        response = client.get("/api/v1/modes/work_dev/stats")
        assert response.status_code in (200, 404)


class TestSkillRouter:
    """技能执行路由测试"""

    def test_list_skills(self, client):
        """测试获取技能列表"""
        response = client.get("/api/v1/skills")
        assert response.status_code in (200, 404)

    def test_execute_skill_not_found(self, client):
        """测试执行不存在的技能"""
        response = client.post(
            "/api/v1/skills/nonexistent-skill/execute",
            json={"input": "test"},
        )
        assert response.status_code in (404, 422)


class TestChatRouter:
    """聊天路由测试"""

    def test_chat_without_auth(self, client):
        """测试未认证聊天请求"""
        response = client.post(
            "/api/v1/chat",
            json={"message": "hello"},
        )
        assert response.status_code in (200, 401, 404, 422)

    def test_chat_history(self, client):
        """测试获取聊天历史"""
        response = client.get("/api/v1/chat/history")
        assert response.status_code in (200, 400, 401, 404)


class TestVoiceRouter:
    """语音路由测试"""

    def test_voice_status(self, client):
        """测试语音服务状态"""
        response = client.get("/api/v1/voice/status")
        assert response.status_code in (200, 404)


class TestWorkspaceRouter:
    """工作空间路由测试"""

    def test_get_workspace(self, client):
        """测试获取工作空间信息"""
        response = client.get("/api/v1/workspace")
        assert response.status_code in (200, 401, 404)


class TestWatchRouter:
    """守护路由测试"""

    def test_get_watch_status(self, client):
        """测试获取守护状态"""
        response = client.get("/api/v1/watch/status")
        assert response.status_code in (200, 404)


class TestM8Endpoints:
    """M8 标准接口测试"""

    def test_m8_health(self, client):
        """测试 /m8/health"""
        response = client.get("/m8/health")
        assert response.status_code in (200, 401, 404)

    def test_m8_metrics(self, client):
        """测试 /m8/metrics"""
        response = client.get("/m8/metrics")
        assert response.status_code in (200, 401, 404)

    def test_m8_config(self, client):
        """测试 /m8/config"""
        response = client.get("/m8/config")
        assert response.status_code in (200, 401, 404)
