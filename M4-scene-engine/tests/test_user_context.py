"""用户上下文机制单元测试.

测试用户上下文基础设施的所有核心功能：
- user_context 模块基础功能
- 中间件从请求头提取用户 ID
- Schema 层上下文回退
- Service 层上下文回退
- 场景智能模块上下文使用
- 多用户隔离
- 向后兼容性
- 类型安全
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.common.user_context import (
    clear_current_user_id,
    get_current_user_id,
    has_user_context,
    set_current_user_id,
)
from src.common.constants import DEFAULT_USER_ID
from src.middleware.user_context import UserContextMiddleware
from src.schemas.common import ModeEnterRequest, ModeLeaveRequest
from src.services.switcher import SceneSwitchManager
from src.services.context_store import ContextStore


# ===========================================================================
# 1. user_context 模块基础测试
# ===========================================================================

class TestUserContextModule:
    """用户上下文模块核心功能测试."""

    def test_get_current_user_id_default(self):
        """未设置时返回 DEFAULT_USER_ID ('default')."""
        clear_current_user_id()
        assert get_current_user_id() == DEFAULT_USER_ID
        assert get_current_user_id() == "default"

    def test_set_and_get_user_id(self):
        """设置后能正确读取."""
        clear_current_user_id()
        set_current_user_id("user_123")
        assert get_current_user_id() == "user_123"
        # 再次设置
        set_current_user_id("user_456")
        assert get_current_user_id() == "user_456"
        # 清理
        clear_current_user_id()

    def test_clear_user_id(self):
        """清除后回到默认值."""
        set_current_user_id("user_test")
        assert get_current_user_id() == "user_test"
        clear_current_user_id()
        assert get_current_user_id() == "default"
        assert has_user_context() is False

    def test_has_user_context(self):
        """has_user_context 正确反映设置状态."""
        clear_current_user_id()
        assert has_user_context() is False
        set_current_user_id("user_x")
        assert has_user_context() is True
        clear_current_user_id()
        assert has_user_context() is False

    def test_context_isolation(self):
        """不同上下文互不干扰（用线程测试）."""
        results: dict[str, str] = {}
        barrier = threading.Barrier(2)

        def user_a_work():
            set_current_user_id("user_A")
            barrier.wait()  # 确保两个线程都设置了自己的 user_id
            time.sleep(0.01)  # 给另一个线程时间操作
            results["user_a"] = get_current_user_id()
            clear_current_user_id()

        def user_b_work():
            set_current_user_id("user_B")
            barrier.wait()
            time.sleep(0.01)
            results["user_b"] = get_current_user_id()
            clear_current_user_id()

        t1 = threading.Thread(target=user_a_work)
        t2 = threading.Thread(target=user_b_work)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results["user_a"] == "user_A"
        assert results["user_b"] == "user_B"

    def test_context_var_type_safety(self):
        """类型安全验证：返回值始终为 str."""
        clear_current_user_id()
        result = get_current_user_id()
        assert isinstance(result, str)

        set_current_user_id("type_test")
        result = get_current_user_id()
        assert isinstance(result, str)

        # 空字符串也返回 str 类型（但回退到 default）
        set_current_user_id("")
        result = get_current_user_id()
        assert isinstance(result, str)
        assert result == "default"  # 空字符串视为未设置

        clear_current_user_id()

    def test_empty_string_user_id_falls_back(self):
        """空字符串 user_id 视为未设置，回退到 default."""
        set_current_user_id("")
        assert get_current_user_id() == "default"
        clear_current_user_id()


# ===========================================================================
# 2. 中间件测试
# ===========================================================================

class TestUserContextMiddleware:
    """用户上下文中间件测试."""

    @pytest.fixture
    def app(self):
        """创建带中间件的测试应用."""
        app = FastAPI()
        app.add_middleware(UserContextMiddleware)

        @app.get("/test-user-id")
        async def test_endpoint():
            return {"user_id": get_current_user_id(), "has_context": has_user_context()}

        return app

    @pytest.fixture
    def client(self, app):
        """创建测试客户端."""
        return TestClient(app)

    def test_middleware_extracts_from_header(self, client):
        """中间件从 X-User-ID 头提取用户 ID."""
        response = client.get("/test-user-id", headers={"X-User-ID": "user_header_001"})
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "user_header_001"
        assert data["has_context"] is True

    def test_middleware_no_header_uses_default(self, client):
        """没有头时用 default."""
        response = client.get("/test-user-id")
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "default"
        assert data["has_context"] is False

    def test_middleware_clears_after_response(self, client):
        """响应后清理上下文."""
        # 先确认上下文干净
        clear_current_user_id()
        assert get_current_user_id() == "default"

        # 发送请求
        response = client.get("/test-user-id", headers={"X-User-ID": "leak_test"})
        assert response.status_code == 200

        # 请求结束后上下文应该被清理
        assert get_current_user_id() == "default"
        assert has_user_context() is False

    def test_middleware_whitespace_in_header(self, client):
        """头中带空白字符时应去除."""
        response = client.get("/test-user-id", headers={"X-User-ID": "  user_padded  "})
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "user_padded"

    def test_middleware_empty_header_falls_back(self, client):
        """空的 X-User-ID 头回退到 default."""
        response = client.get("/test-user-id", headers={"X-User-ID": ""})
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "default"
        assert data["has_context"] is False

    def test_backward_compatibility_no_header(self, client):
        """不带用户 ID 的请求正常工作（向后兼容）."""
        response = client.get("/test-user-id")
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "default"
        # 不抛异常，正常返回


# ===========================================================================
# 3. Schema 层测试
# ===========================================================================

class TestSchemaUserContext:
    """Schema 层用户 ID 上下文回退测试."""

    def test_schema_user_id_none_falls_back_to_context(self):
        """schema 中 user_id 为 None 时从上下文获取."""
        clear_current_user_id()
        set_current_user_id("schema_ctx_user")

        req = ModeEnterRequest(context={"key": "value"})
        assert req.user_id is None
        assert req.get_effective_user_id() == "schema_ctx_user"

        clear_current_user_id()

    def test_schema_user_id_explicit_takes_priority(self):
        """显式设置 user_id 优先于上下文."""
        set_current_user_id("context_user")
        req = ModeEnterRequest(user_id="explicit_user", context={})
        assert req.get_effective_user_id() == "explicit_user"
        clear_current_user_id()

    def test_mode_leave_request_context_fallback(self):
        """ModeLeaveRequest 也支持上下文回退."""
        clear_current_user_id()
        set_current_user_id("leave_ctx_user")

        req = ModeLeaveRequest(context={"reason": "timeout"})
        assert req.user_id is None
        assert req.get_effective_user_id() == "leave_ctx_user"

        clear_current_user_id()

    def test_schema_no_context_returns_default(self):
        """没有上下文且未设置 user_id 时返回 default."""
        clear_current_user_id()
        req = ModeEnterRequest(context={})
        assert req.get_effective_user_id() == "default"

    def test_schema_user_id_in_query_param_works(self):
        """显式传入 user_id 仍可用（模拟 query param 场景）."""
        clear_current_user_id()
        req = ModeEnterRequest(user_id="query_user", context={})
        assert req.get_effective_user_id() == "query_user"


# ===========================================================================
# 4. Service 层测试
# ===========================================================================

class TestServiceUserContext:
    """Service 层用户 ID 上下文回退测试."""

    def test_switcher_uses_context_user_id(self):
        """SceneSwitchManager 不传 user_id 时用上下文."""
        clear_current_user_id()
        set_current_user_id("switcher_ctx_user")

        switcher = SceneSwitchManager()
        current = switcher.get_current_scene()  # 不传 user_id
        assert current == switcher._default_scene

        # 切换场景
        result = switcher.switch_scene(to_scene="work_dev")
        assert result["success"] is True

        # 验证当前场景（从上下文获取用户）
        assert switcher.get_current_scene() == "work_dev"

        # 验证历史（从上下文获取用户）
        history = switcher.get_history()
        assert history["total"] == 1

        clear_current_user_id()

    def test_switcher_explicit_user_id_overrides_context(self):
        """显式传 user_id 优先于上下文."""
        set_current_user_id("context_user")
        switcher = SceneSwitchManager()

        # 用显式 user_id 切换
        switcher.switch_scene(to_scene="creative", user_id="explicit_user")

        # 显式用户的场景
        assert switcher.get_current_scene(user_id="explicit_user") == "creative"

        # 上下文用户的场景仍是默认（因为刚才切换的是 explicit_user）
        assert switcher.get_current_scene() == switcher._default_scene

        clear_current_user_id()

    def test_context_store_uses_context_user_id(self, tmp_path):
        """ContextStore 不传 user_id 时用上下文."""
        clear_current_user_id()
        set_current_user_id("store_ctx_user")

        persist_path = str(tmp_path / "test_store.json")
        store = ContextStore(persist_path=persist_path, auto_save=False)

        # 保存上下文（从上下文获取用户）
        result = store.save_context(
            scene_id="work_dev",
            context_data={"project": "test_project"},
        )
        assert result["success"] is True

        # 获取上下文（从上下文获取用户）
        ctx = store.get_context("work_dev")
        assert ctx["context_data"]["project"] == "test_project"
        assert ctx["exists"] is True

        # 状态概览
        status = store.get_status()
        assert status["user_id"] == "store_ctx_user"
        assert status["total_scenes"] == 1

        clear_current_user_id()

    def test_multi_user_isolation(self):
        """模拟两个用户请求，数据隔离（线程级）."""
        switcher = SceneSwitchManager()
        results: dict[str, str] = {}
        barrier = threading.Barrier(2)

        def user_alice():
            set_current_user_id("alice")
            barrier.wait()
            switcher.switch_scene(to_scene="work_dev")
            results["alice"] = switcher.get_current_scene()
            clear_current_user_id()

        def user_bob():
            set_current_user_id("bob")
            barrier.wait()
            switcher.switch_scene(to_scene="creative")
            results["bob"] = switcher.get_current_scene()
            clear_current_user_id()

        t1 = threading.Thread(target=user_alice)
        t2 = threading.Thread(target=user_bob)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results["alice"] == "work_dev"
        assert results["bob"] == "creative"

        # 验证数据完全隔离
        assert switcher.get_current_scene(user_id="alice") == "work_dev"
        assert switcher.get_current_scene(user_id="bob") == "creative"


# ===========================================================================
# 5. 场景智能模块测试
# ===========================================================================

class TestSceneIntelligenceContext:
    """场景智能模块使用上下文测试."""

    def test_scene_intelligence_uses_context(self):
        """场景智能模块中 get_current_user_id 正确工作."""
        clear_current_user_id()
        set_current_user_id("intel_user")

        # 验证 get_current_user_id 在场景智能模块的上下文中可用
        from src.common.user_context import get_current_user_id as gcid
        assert gcid() == "intel_user"

        clear_current_user_id()

    def test_scene_intelligence_default_fallback(self):
        """没有上下文时场景智能模块回退到 default."""
        clear_current_user_id()
        from src.common.user_context import get_current_user_id as gcid
        assert gcid() == "default"


# ===========================================================================
# 6. 端到端集成测试（中间件 + Service）
# ===========================================================================

class TestEndToEndContext:
    """端到端集成测试：中间件 -> Service 全链路."""

    @pytest.fixture
    def app_with_services(self, tmp_path):
        """创建带中间件和服务的测试应用."""
        app = FastAPI()
        app.add_middleware(UserContextMiddleware)

        persist_path = str(tmp_path / "e2e_store.json")
        context_store = ContextStore(persist_path=persist_path, auto_save=False)
        switcher = SceneSwitchManager()

        app.state.context_store = context_store
        app.state.switcher = switcher

        @app.get("/api/v1/context/{scene_id}")
        async def get_context(scene_id: str):
            store = app.state.context_store
            result = store.get_context(scene_id)  # 不传 user_id，从上下文获取
            return {"code": 0, "data": result}

        @app.post("/api/v1/context/{scene_id}")
        async def save_context(scene_id: str, body: dict):
            store = app.state.context_store
            result = store.save_context(
                scene_id=scene_id,
                context_data=body.get("context_data", {}),
            )
            return {"code": 0, "data": result}

        @app.get("/api/v1/scene/current")
        async def get_current_scene():
            sw = app.state.switcher
            scene = sw.get_current_scene()
            return {"code": 0, "data": {"scene_id": scene, "user_id": get_current_user_id()}}

        return app

    @pytest.fixture
    def e2e_client(self, app_with_services):
        return TestClient(app_with_services)

    def test_e2e_multi_user_data_isolation(self, e2e_client):
        """端到端：两个用户的数据完全隔离."""
        # 用户 alice 保存上下文
        e2e_client.post(
            "/api/v1/context/work_dev",
            json={"context_data": {"project": "alice_project"}},
            headers={"X-User-ID": "alice"},
        )

        # 用户 bob 保存上下文
        e2e_client.post(
            "/api/v1/context/work_dev",
            json={"context_data": {"project": "bob_project"}},
            headers={"X-User-ID": "bob"},
        )

        # alice 读取自己的数据
        resp_a = e2e_client.get(
            "/api/v1/context/work_dev",
            headers={"X-User-ID": "alice"},
        )
        assert resp_a.json()["data"]["context_data"]["project"] == "alice_project"

        # bob 读取自己的数据
        resp_b = e2e_client.get(
            "/api/v1/context/work_dev",
            headers={"X-User-ID": "bob"},
        )
        assert resp_b.json()["data"]["context_data"]["project"] == "bob_project"

    def test_e2e_default_user_works(self, e2e_client):
        """端到端：不带用户头的请求使用 default 用户."""
        response = e2e_client.get("/api/v1/scene/current")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["user_id"] == "default"

    def test_e2e_context_cleaned_between_requests(self, e2e_client):
        """端到端：请求之间上下文被正确清理."""
        # 第一个请求带用户头
        resp1 = e2e_client.get(
            "/api/v1/scene/current",
            headers={"X-User-ID": "user_first"},
        )
        assert resp1.json()["data"]["user_id"] == "user_first"

        # 第二个请求不带用户头，应该是 default，而不是 user_first
        resp2 = e2e_client.get("/api/v1/scene/current")
        assert resp2.json()["data"]["user_id"] == "default"
