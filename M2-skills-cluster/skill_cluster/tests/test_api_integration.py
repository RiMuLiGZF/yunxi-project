"""M2 技能集群 API v2 集成测试.

使用 FastAPI TestClient 进行端到端 API 测试，覆盖：
1. 健康检查接口
2. 技能注册与发现
3. 技能调用
4. 权限相关
5. 幂等性测试
6. 限流测试
7. 流水线接口（如有）

测试之间完全隔离，不共享状态。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from skill_cluster.api_v2 import create_v2_app
from skill_cluster.config import IdempotencyConfig
from skill_cluster.resilience.rate_limiter import (
    get_global_registry,
)
from skill_cluster.error_codes import ErrorCode
from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)
from skill_cluster.skill_discovery import SkillDiscoveryEngine
from skill_cluster.skill_registry import SkillRegistry
from skill_cluster.skill_router import SkillRouter


# ============================================================
# Mock 技能定义
# ============================================================


class _MockSkillManifest(SkillManifest):
    """带 category 字段的 SkillManifest 子类，用于测试.

    SkillManifest 本身不包含 category 字段，
    但 API 层通过 getattr(manifest, "category", "") 读取，
    因此测试用的 mock manifest 需要额外提供此字段。
    """

    category: str = "test"
    model_config = {"extra": "allow"}


class MockEchoSkill(ISkill):
    """Mock Echo 技能，用于集成测试.

    将输入参数原样返回，支持延迟模拟和异常抛出。
    """

    def __init__(
        self,
        skill_id: str = "skill.mock_echo",
        name: str = "Mock Echo",
        category: str = "learning",
        delay: float = 0.0,
        should_fail: bool = False,
    ) -> None:
        manifest = _MockSkillManifest(
            skill_id=skill_id,
            name=name,
            version="1.0.0",
            description=f"Mock echo skill for testing: {skill_id}",
            author="test",
            tags=["test", "mock", "echo"],
            capabilities=["echo", "ping", "reverse"],
            permissions=["test:read"],
            entrypoint="MockEchoSkill",
            category=category,
        )
        super().__init__(manifest)
        self.delay = delay
        self.should_fail = should_fail
        self.call_count = 0

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """执行技能调用.

        Args:
            request: 调用请求.

        Returns:
            调用结果，包含回显的参数数据.
        """
        self.call_count += 1

        if self.delay > 0:
            await asyncio.sleep(self.delay)

        if self.should_fail:
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=request.action,
                status="failure",
                error="Mock failure",
                latency_ms=0.0,
                trace_id=request.trace_id,
            )

        # 根据 action 返回不同结果
        if request.action == "reverse":
            text = request.params.get("text", "")
            result_data = {"reversed": text[::-1], "original": text}
        elif request.action == "ping":
            result_data = {"pong": True, "timestamp": time.time()}
        else:
            result_data = {"echo": request.params, "action": request.action}

        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="success",
            data=result_data,
            latency_ms=0.0,
            trace_id=request.trace_id,
        )

    async def health(self) -> dict:
        """返回健康状态."""
        return {"healthy": True, "skill_id": self.manifest.skill_id}

    async def configure(self, config: dict) -> None:
        """配置技能."""
        pass


class MockSlowSkill(ISkill):
    """Mock 慢速技能，用于测试超时场景."""

    def __init__(self, skill_id: str = "skill.mock_slow") -> None:
        manifest = _MockSkillManifest(
            skill_id=skill_id,
            name="Mock Slow",
            version="1.0.0",
            description="Slow skill for timeout testing",
            author="test",
            tags=["test", "slow"],
            capabilities=["slow_action"],
            entrypoint="MockSlowSkill",
            category="learning",
        )
        super().__init__(manifest)

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """慢速执行，默认 5 秒."""
        await asyncio.sleep(5)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="success",
            data={"done": True},
            latency_ms=5000.0,
            trace_id=request.trace_id,
        )

    async def health(self) -> dict:
        return {"healthy": True}

    async def configure(self, config: dict) -> None:
        pass


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_echo_skill() -> MockEchoSkill:
    """创建一个基础的 Mock Echo 技能（learning 分类）."""
    return MockEchoSkill(skill_id="skill.mock_echo", name="Mock Echo", category="learning")


@pytest.fixture
def mock_echo_skill_2() -> MockEchoSkill:
    """创建第二个 Mock Echo 技能（coding 分类，用于列表/搜索测试）."""
    return MockEchoSkill(
        skill_id="skill.mock_calc",
        name="Mock Calculator",
        category="coding",
    )


@pytest.fixture
def mock_slow_skill() -> MockSlowSkill:
    """创建一个慢速 Mock 技能."""
    return MockSlowSkill(skill_id="skill.mock_slow")


def _build_test_app(
    skills: list[ISkill] | None = None,
    enable_rate_limit: bool = False,
    enable_idempotency: bool = False,
) -> tuple[TestClient, SkillRegistry, SkillRouter, SkillDiscoveryEngine]:
    """构建测试用的 API 应用及相关组件.

    Args:
        skills: 需要预注册的技能列表.
        enable_rate_limit: 是否启用限流（默认关闭以避免干扰测试）.
        enable_idempotency: 是否启用幂等性.

    Returns:
        (TestClient, SkillRegistry, SkillRouter, SkillDiscoveryEngine) 元组.
    """
    # 重置单例，确保测试隔离
    SkillRouter._instance = None  # type: ignore[attr-defined]

    registry = SkillRegistry()
    discovery = SkillDiscoveryEngine()

    # 注册技能
    if skills:
        for skill in skills:
            registry.register(skill)
            manifest = skill.manifest
            category = getattr(manifest, "category", "test")
            discovery.register_skill(
                skill_id=manifest.skill_id,
                skill_name=manifest.name,
                description=manifest.description,
                category=category,
                tags=manifest.tags,
            )

    # 构建限流配置（默认关闭，避免影响普通测试）
    # 注意：SkillRouter 使用 config.py 中的 RateLimitConfig（Pydantic 模型）
    from skill_cluster.config import RateLimitConfig as RouterRateLimitConfig
    rate_limit_config = RouterRateLimitConfig(
        enabled=enable_rate_limit,
        global_rate=10.0 if enable_rate_limit else 0.0,
        global_capacity=10.0 if enable_rate_limit else 0.0,
        per_skill_rate=0.0,
        per_skill_capacity=0.0,
        per_ip_rate=0.0,
        per_ip_capacity=0.0,
        per_user_rate=0.0,
        per_user_capacity=0.0,
    )

    # 如果启用限流，重置全局限流注册中心，确保测试隔离
    if enable_rate_limit:
        global_reg = get_global_registry()
        # 直接清空内部限流器字典，避免异步调用问题
        global_reg._limiters.clear()  # type: ignore[attr-defined]

    # 构建幂等性配置
    idempotency_config = IdempotencyConfig(
        enabled=enable_idempotency,
        ttl=3600,
        max_entries=1000,
    )

    router = SkillRouter(
        registry=registry,
        rate_limit_config=rate_limit_config,
        idempotency_config=idempotency_config,
    )

    app = create_v2_app(
        registry=registry,
        router=router,
        discovery_engine=discovery,
    )

    client = TestClient(app)
    return client, registry, router, discovery


@pytest.fixture
def app_client(mock_echo_skill: MockEchoSkill) -> TestClient:
    """创建带有一个预注册技能的 API 测试客户端."""
    client, _, _, _ = _build_test_app(skills=[mock_echo_skill])
    return client


@pytest.fixture
def app_client_multi(
    mock_echo_skill: MockEchoSkill,
    mock_echo_skill_2: MockEchoSkill,
) -> TestClient:
    """创建带有多个预注册技能的 API 测试客户端."""
    client, _, _, _ = _build_test_app(skills=[mock_echo_skill, mock_echo_skill_2])
    return client


@pytest.fixture
def app_client_with_router(
    mock_echo_skill: MockEchoSkill,
) -> tuple[TestClient, SkillRouter]:
    """创建测试客户端及对应的 SkillRouter 实例."""
    client, _, router, _ = _build_test_app(skills=[mock_echo_skill])
    return client, router


@pytest.fixture
def app_client_rate_limited(
    mock_echo_skill: MockEchoSkill,
) -> TestClient:
    """创建启用限流的测试客户端（全局 10 令牌/秒，容量 10）."""
    client, _, _, _ = _build_test_app(
        skills=[mock_echo_skill],
        enable_rate_limit=True,
    )
    return client


@pytest.fixture
def app_client_idempotent(
    mock_echo_skill: MockEchoSkill,
) -> TestClient:
    """创建启用幂等性的测试客户端."""
    client, _, _, _ = _build_test_app(
        skills=[mock_echo_skill],
        enable_idempotency=True,
    )
    return client


# ============================================================
# 1. 健康检查接口测试
# ============================================================


class TestHealthCheck:
    """健康检查接口测试."""

    def test_health_check_returns_200(self, app_client: TestClient) -> None:
        """GET /api/v2/health 正常返回 200."""
        response = app_client.get("/api/v2/health")
        assert response.status_code == 200

    def test_health_check_response_structure(self, app_client: TestClient) -> None:
        """健康检查响应包含标准字段."""
        response = app_client.get("/api/v2/health")
        data = response.json()

        assert data["success"] is True
        assert data["code"] == ErrorCode.SUCCESS
        assert "data" in data
        assert "message" in data
        assert "trace_id" in data
        assert data["message"] == "服务正常"

    def test_health_check_status_and_score(self, app_client: TestClient) -> None:
        """健康检查数据包含状态、评分和组件信息."""
        response = app_client.get("/api/v2/health")
        health_data = response.json()["data"]

        assert "status" in health_data
        assert health_data["status"] in ("healthy", "degraded", "unhealthy")
        assert "score" in health_data
        assert 0.0 <= health_data["score"] <= 1.0
        assert "components" in health_data
        assert isinstance(health_data["components"], list)
        assert "version" in health_data
        assert "uptime_seconds" in health_data

    def test_health_check_with_trace_id(self, app_client: TestClient) -> None:
        """健康检查支持自定义 X-Trace-Id."""
        trace_id = "test-trace-001"
        response = app_client.get(
            "/api/v2/health",
            headers={"X-Trace-Id": trace_id},
        )
        data = response.json()
        assert data["trace_id"] == trace_id


# ============================================================
# 2. 技能注册与发现测试
# ============================================================


class TestSkillDiscovery:
    """技能注册与发现接口测试."""

    def test_list_skills_returns_list(self, app_client: TestClient) -> None:
        """GET /api/v2/skills 返回技能列表."""
        response = app_client.get("/api/v2/skills")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["code"] == ErrorCode.SUCCESS

        result = data["data"]
        assert "items" in result
        assert "total" in result
        assert "page" in result
        assert "page_size" in result
        assert "total_pages" in result
        assert isinstance(result["items"], list)
        assert result["total"] >= 1

    def test_get_skill_by_id(self, app_client: TestClient) -> None:
        """GET /api/v2/skills/{skill_id} 按 ID 查询技能详情."""
        response = app_client.get("/api/v2/skills/skill.mock_echo")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        skill_data = data["data"]
        assert skill_data["skill_id"] == "skill.mock_echo"
        assert skill_data["name"] == "Mock Echo"
        assert skill_data["category"] == "learning"
        assert "actions" in skill_data
        assert "permissions" in skill_data
        assert "version" in skill_data
        assert "enabled" in skill_data

    def test_get_skill_not_found(self, app_client: TestClient) -> None:
        """查询不存在的技能返回 404 风格错误."""
        response = app_client.get("/api/v2/skills/skill.nonexistent")
        assert response.status_code == 200  # API 使用 200 + 错误码
        data = response.json()
        assert data["success"] is False
        assert data["code"] == ErrorCode.SKILL_NOT_FOUND

    def test_list_skills_pagination(self, app_client_multi: TestClient) -> None:
        """技能列表支持分页."""
        # 第一页，每页 1 条
        response = app_client_multi.get("/api/v2/skills?page=1&page_size=1")
        data = response.json()
        result = data["data"]
        assert len(result["items"]) == 1
        assert result["page"] == 1
        assert result["page_size"] == 1
        assert result["total"] == 2
        assert result["total_pages"] == 2

        # 第二页
        response2 = app_client_multi.get("/api/v2/skills?page=2&page_size=1")
        data2 = response2.json()
        assert len(data2["data"]["items"]) == 1
        assert data2["data"]["page"] == 2

    def test_list_skills_category_filter(self, app_client_multi: TestClient) -> None:
        """技能列表支持按分类过滤."""
        response = app_client_multi.get("/api/v2/skills?category=coding")
        data = response.json()
        result = data["data"]
        assert result["total"] == 1
        assert result["items"][0]["category"] == "coding"

    def test_recommend_test(self, app_client_multi: TestClient) -> None:
        """POST /api/v2/recommend/test 推荐测试接口."""
        response = app_client_multi.post(
            "/api/v2/recommend/test",
            json={"query": "echo test", "top_k": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        result = data["data"]
        assert "results" in result
        assert "query" in result
        assert "total" in result
        assert isinstance(result["results"], list)
        assert result["query"] == "echo test"

    def test_toggle_skill(self, app_client: TestClient) -> None:
        """POST /api/v2/skills/{skill_id}/toggle 技能开关."""
        # 禁用
        response = app_client.post(
            "/api/v2/skills/skill.mock_echo/toggle",
            json={"enabled": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["enabled"] is False

        # 验证状态已更新
        detail_resp = app_client.get("/api/v2/skills/skill.mock_echo")
        assert detail_resp.json()["data"]["enabled"] is False

        # 重新启用
        response2 = app_client.post(
            "/api/v2/skills/skill.mock_echo/toggle",
            json={"enabled": True},
        )
        assert response2.json()["data"]["enabled"] is True


# ============================================================
# 3. 技能调用测试
# ============================================================


class TestSkillInvoke:
    """技能调用接口测试."""

    def test_invoke_skill_success(self, app_client: TestClient) -> None:
        """正常调用 mock 技能返回成功."""
        response = app_client.post(
            "/api/v2/skills/invoke",
            json={
                "skill_id": "skill.mock_echo",
                "action": "echo",
                "params": {"message": "hello world"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        result = data["data"]
        assert result["skill_id"] == "skill.mock_echo"
        assert result["action"] == "echo"
        assert result["status"] == "success"
        assert result["data"]["echo"]["message"] == "hello world"
        assert "latency_ms" in result

    def test_invoke_skill_not_found(self, app_client: TestClient) -> None:
        """调用不存在的技能返回 not_found."""
        response = app_client.post(
            "/api/v2/skills/invoke",
            json={
                "skill_id": "skill.nonexistent",
                "action": "default",
                "params": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        # 路由器返回 not_found 状态
        assert data["success"] is True  # API 调用本身成功
        assert data["data"]["status"] == "not_found"
        assert data["data"]["error"] is not None

    def test_invoke_invalid_params_400(self, app_client: TestClient) -> None:
        """调用参数校验失败返回 400."""
        # 缺少必填字段 skill_id
        response = app_client.post(
            "/api/v2/skills/invoke",
            json={
                "action": "default",
                "params": {},
            },
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["code"] == ErrorCode.INVALID_PARAMS

    def test_invoke_with_trace_id(self, app_client: TestClient) -> None:
        """带 X-Trace-Id 头的调用，trace_id 被正确传递."""
        trace_id = "trace-invoke-001"
        response = app_client.post(
            "/api/v2/skills/invoke",
            json={
                "skill_id": "skill.mock_echo",
                "action": "ping",
                "params": {},
            },
            headers={"X-Trace-Id": trace_id},
        )
        data = response.json()
        assert data["trace_id"] == trace_id

    def test_invoke_with_timeout(self, app_client: TestClient) -> None:
        """调用超时场景（使用极短超时时间）."""
        # 注册一个慢速技能
        slow_skill = MockSlowSkill(skill_id="skill.test_slow")
        client, registry, router, _ = _build_test_app(skills=[slow_skill])

        response = client.post(
            "/api/v2/skills/invoke",
            json={
                "skill_id": "skill.test_slow",
                "action": "slow_action",
                "params": {},
                "timeout": 1,  # 1 秒超时
            },
        )
        data = response.json()
        assert data["success"] is True
        # 超时返回 timeout 状态
        assert data["data"]["status"] == "timeout"
        assert "timeout" in (data["data"].get("error") or "").lower()

    def test_batch_invoke(self, app_client_multi: TestClient) -> None:
        """批量调用技能接口."""
        response = app_client_multi.post(
            "/api/v2/skills/batch-invoke",
            json={
                "requests": [
                    {
                        "skill_id": "skill.mock_echo",
                        "action": "echo",
                        "params": {"msg": "first"},
                    },
                    {
                        "skill_id": "skill.mock_calc",
                        "action": "echo",
                        "params": {"msg": "second"},
                    },
                ],
                "parallel": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        result = data["data"]
        assert result["total"] == 2
        assert result["success_count"] == 2
        assert result["failed_count"] == 0
        assert len(result["results"]) == 2
        assert result["results"][0]["status"] == "success"
        assert result["results"][1]["status"] == "success"


# ============================================================
# 4. 权限相关测试
# ============================================================


class TestPermissions:
    """权限相关接口测试."""

    def test_auth_middleware_blocks_without_token(self) -> None:
        """无 Token 时受保护接口被鉴权中间件拦截（401）."""
        from skill_cluster.m8_auth_middleware import M8TokenAuthMiddleware
        from fastapi import FastAPI

        # 构建一个带鉴权的 app
        app = FastAPI()
        app.add_middleware(
            M8TokenAuthMiddleware,
            expected_token="test-secret-token",
            env="testing",
        )

        @app.get("/api/v2/test-protected")
        async def protected() -> dict:
            return {"data": "secret"}

        client = TestClient(app)

        # 不带 Token 应该返回 401
        response = client.get("/api/v2/test-protected")
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == ErrorCode.PERMISSION_TOKEN_INVALID
        assert data["success"] is False

    def test_auth_middleware_allows_with_valid_token(self) -> None:
        """有效 Token 可以正常访问受保护接口."""
        from skill_cluster.m8_auth_middleware import M8TokenAuthMiddleware
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(
            M8TokenAuthMiddleware,
            expected_token="valid-token-123",
            env="testing",
        )

        @app.get("/api/v2/test-protected")
        async def protected() -> dict:
            return {"data": "secret"}

        client = TestClient(app)

        response = client.get(
            "/api/v2/test-protected",
            headers={"X-M8-Token": "valid-token-123"},
        )
        assert response.status_code == 200
        assert response.json()["data"] == "secret"

    def test_health_endpoint_is_whitelisted(self) -> None:
        """健康检查接口在白名单中，不需要鉴权."""
        from skill_cluster.m8_auth_middleware import M8TokenAuthMiddleware, WHITE_LIST_PATHS

        assert "/api/v2/health" in WHITE_LIST_PATHS
        assert "/health" in WHITE_LIST_PATHS


# ============================================================
# 5. 幂等性测试
# ============================================================


class TestIdempotency:
    """幂等性测试."""

    def test_idempotency_header_present_on_response(
        self, app_client_idempotent: TestClient
    ) -> None:
        """带 X-Idempotency-Key 头的请求，响应中包含幂等性响应头."""
        idem_key = "idem-key-001"
        response = app_client_idempotent.post(
            "/api/v2/skills/invoke",
            json={
                "skill_id": "skill.mock_echo",
                "action": "echo",
                "params": {"value": 42},
            },
            headers={"X-Idempotency-Key": idem_key},
        )
        assert response.status_code == 200
        assert "X-Idempotency-Key" in response.headers
        assert response.headers["X-Idempotency-Key"] == idem_key
        assert "X-Idempotency-Hit" in response.headers

    def test_idempotency_first_request_not_hit(
        self, app_client_idempotent: TestClient
    ) -> None:
        """首次幂等请求，X-Idempotency-Hit 为 false."""
        response = app_client_idempotent.post(
            "/api/v2/skills/invoke",
            json={
                "skill_id": "skill.mock_echo",
                "action": "echo",
                "params": {"value": 100},
            },
            headers={"X-Idempotency-Key": "idem-first-request"},
        )
        assert response.headers["X-Idempotency-Hit"] == "false"

    def test_idempotency_duplicate_request_same_result(
        self, app_client_idempotent: TestClient
    ) -> None:
        """重复幂等请求返回相同业务结果，第二次命中缓存."""
        idem_key = "idem-duplicate-test"
        payload = {
            "skill_id": "skill.mock_echo",
            "action": "echo",
            "params": {"key": "unique_value_xyz"},
        }

        # 第一次请求
        resp1 = app_client_idempotent.post(
            "/api/v2/skills/invoke",
            json=payload,
            headers={"X-Idempotency-Key": idem_key},
        )
        data1 = resp1.json()

        # 第二次请求（相同幂等键）
        resp2 = app_client_idempotent.post(
            "/api/v2/skills/invoke",
            json=payload,
            headers={"X-Idempotency-Key": idem_key},
        )
        data2 = resp2.json()

        # 两次业务结果应该一致（第二次可能多了 idempotent_hit 标记字段）
        result1 = data1["data"]["data"]
        result2 = data2["data"]["data"]
        # 移除幂等命中标记后比较业务数据
        result2_clean = {k: v for k, v in result2.items() if k != "idempotent_hit"}
        assert result1 == result2_clean
        # 第二次应该命中缓存
        assert result2.get("idempotent_hit") is True
        assert resp2.headers["X-Idempotency-Hit"] == "true"


# ============================================================
# 6. 限流测试
# ============================================================


class TestRateLimiting:
    """限流测试."""

    def test_rate_limit_triggers_429(
        self, app_client_rate_limited: TestClient
    ) -> None:
        """触发限流后返回 429 状态码."""
        # 全局 10 令牌容量，快速发送 15 次请求触发限流
        rate_limited_hit = False
        for i in range(15):
            response = app_client_rate_limited.post(
                "/api/v2/skills/invoke",
                json={
                    "skill_id": "skill.mock_echo",
                    "action": "echo",
                    "params": {"n": i},
                },
            )
            if response.status_code == 429:
                rate_limited_hit = True
                break

        assert rate_limited_hit, "应该有请求触发限流返回 429"

    def test_rate_limit_response_headers(
        self, app_client_rate_limited: TestClient
    ) -> None:
        """限流响应包含标准限流响应头."""
        # 耗尽所有令牌
        for i in range(10):
            app_client_rate_limited.post(
                "/api/v2/skills/invoke",
                json={
                    "skill_id": "skill.mock_echo",
                    "action": "echo",
                    "params": {"n": i},
                },
            )

        # 第 11 次应该被限流
        response = app_client_rate_limited.post(
            "/api/v2/skills/invoke",
            json={
                "skill_id": "skill.mock_echo",
                "action": "echo",
                "params": {"n": 11},
            },
        )

        if response.status_code == 429:
            data = response.json()
            assert data["code"] == ErrorCode.RATE_LIMITED
            assert data["success"] is False

            # 验证响应头
            assert "X-RateLimit-Limit" in response.headers
            assert "X-RateLimit-Remaining" in response.headers
            assert "X-RateLimit-Reset" in response.headers
            assert "Retry-After" in response.headers
            assert response.headers["X-RateLimit-Remaining"] == "0"

    def test_rate_limit_recovery_after_wait(
        self, app_client_rate_limited: TestClient
    ) -> None:
        """限流后等待一段时间可以恢复（令牌补充）."""
        # 先耗尽令牌
        for i in range(10):
            app_client_rate_limited.post(
                "/api/v2/skills/invoke",
                json={
                    "skill_id": "skill.mock_echo",
                    "action": "echo",
                    "params": {"n": i},
                },
            )

        # 等待 0.5 秒（速率 10/s，0.5 秒补充 5 个令牌）
        import time
        time.sleep(0.5)

        # 应该可以成功调用至少一次
        response = app_client_rate_limited.post(
            "/api/v2/skills/invoke",
            json={
                "skill_id": "skill.mock_echo",
                "action": "echo",
                "params": {"n": "after_wait"},
            },
        )
        # 应该恢复了一些令牌，请求成功
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["status"] == "success"


# ============================================================
# 7. 统计与分类接口测试
# ============================================================


class TestStatsAndCategories:
    """统计与分类接口测试."""

    def test_invocation_stats(self, app_client: TestClient) -> None:
        """调用统计接口返回正确结构."""
        # 先调用几次以产生调用数据
        for i in range(3):
            app_client.post(
                "/api/v2/skills/invoke",
                json={
                    "skill_id": "skill.mock_echo",
                    "action": "echo",
                    "params": {"n": i},
                },
            )

        response = app_client.get("/api/v2/stats/invocations")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        stats = data["data"]
        assert "total_calls" in stats
        assert "success_count" in stats
        assert "failed_count" in stats
        assert "avg_latency_ms" in stats
        assert "top_skills" in stats

    def test_system_stats(self, app_client_multi: TestClient) -> None:
        """系统统计接口返回正确结构."""
        response = app_client_multi.get("/api/v2/stats/system")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        stats = data["data"]
        assert "total_skills" in stats
        assert stats["total_skills"] == 2
        assert "enabled_skills" in stats
        assert "categories" in stats
        assert "uptime_seconds" in stats

    def test_categories_list(self, app_client_multi: TestClient) -> None:
        """分类列表接口返回所有分类."""
        response = app_client_multi.get("/api/v2/categories")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        result = data["data"]
        assert "categories" in result
        assert "total" in result
        assert isinstance(result["categories"], list)
        assert result["total"] > 0

    def test_accuracy_stats(self, app_client: TestClient) -> None:
        """准确率统计接口返回正确结构."""
        response = app_client.get("/api/v2/stats/accuracy")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        stats = data["data"]
        assert "top1_accuracy" in stats
        assert "top3_accuracy" in stats
        assert "top5_accuracy" in stats
        assert "total_tests" in stats


# ============================================================
# 8. 流水线接口测试
# ============================================================


class TestPipelineEndpoints:
    """流水线接口测试.

    验证流水线相关的 API 端点。如果 API v2 中未包含流水线端点，
    则通过底层 PipelineEngine 验证其可用性。
    """

    def test_pipeline_engine_exists(self) -> None:
        """PipelineEngine 类存在且可实例化."""
        from skill_cluster.skill_pipeline import PipelineEngine, PipelineDefinition, PipelineStep

        engine = PipelineEngine()
        assert engine is not None

    def test_pipeline_definition_validation(self) -> None:
        """流水线定义可以正确验证."""
        from skill_cluster.skill_pipeline import PipelineDefinition, PipelineStep

        definition = PipelineDefinition(
            pipeline_id="pipeline.test",
            name="Test Pipeline",
            description="A test pipeline",
            steps=[
                PipelineStep(
                    skill_id="skill.mock_echo",
                    action="echo",
                    params={"msg": "step1"},
                ),
                PipelineStep(
                    skill_id="skill.mock_echo",
                    action="ping",
                    params={},
                ),
            ],
            mode="sequential",
        )

        assert definition.pipeline_id == "pipeline.test"
        assert len(definition.steps) == 2
        assert definition.mode == "sequential"

    def test_pipeline_store_exists(self) -> None:
        """PipelineStateStore 存在且可实例化."""
        from skill_cluster.pipeline_store import PipelineStateStore

        store = PipelineStateStore()
        assert store is not None
        assert hasattr(store, "save")
        assert hasattr(store, "get")


# ============================================================
# 9. 响应格式一致性测试
# ============================================================


class TestResponseConsistency:
    """响应格式一致性测试."""

    def test_all_success_responses_have_standard_fields(
        self, app_client: TestClient
    ) -> None:
        """所有成功响应都包含标准字段."""
        endpoints = [
            ("GET", "/api/v2/health", None),
            ("GET", "/api/v2/skills", None),
            ("GET", "/api/v2/skills/skill.mock_echo", None),
            ("GET", "/api/v2/stats/invocations", None),
            ("GET", "/api/v2/stats/system", None),
            ("GET", "/api/v2/categories", None),
            ("GET", "/api/v2/stats/accuracy", None),
        ]

        for method, path, _body in endpoints:
            response = app_client.get(path) if method == "GET" else app_client.post(path)
            data = response.json()

            assert "code" in data, f"{path} 缺少 code 字段"
            assert "message" in data, f"{path} 缺少 message 字段"
            assert "data" in data, f"{path} 缺少 data 字段"
            assert "trace_id" in data, f"{path} 缺少 trace_id 字段"
            assert "success" in data, f"{path} 缺少 success 字段"

    def test_error_codes_in_correct_range(
        self, app_client: TestClient
    ) -> None:
        """所有错误响应的错误码在 20000-29999 范围内."""
        # 触发各种错误
        error_cases = [
            # 技能不存在
            ("GET", "/api/v2/skills/skill.nonexistent", None),
            # 参数校验失败
            ("POST", "/api/v2/skills/invoke", {"action": "x"}),  # 缺少 skill_id
        ]

        for method, path, body in error_cases:
            if method == "GET":
                response = app_client.get(path)
            else:
                response = app_client.post(path, json=body or {})

            data = response.json()
            # 成功调用但业务失败，或直接 HTTP 错误
            if "code" in data and data.get("success") is False:
                code = data["code"]
                assert 20000 <= code < 30000, \
                    f"{method} {path} 错误码 {code} 不在 20000-29999 范围内"
