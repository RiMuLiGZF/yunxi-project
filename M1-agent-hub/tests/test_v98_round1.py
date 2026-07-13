"""
V9.8 第一轮增量优化测试

覆盖：
- V8-001 [P1]: CancelToken 任务取消传播
- V8-002 [P1]: ModelRotationManager OOM 降级链
- V8-003 [创新]: SemanticRouter 语义路由
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest

from interfaces import CancelToken
from semantic_router import SemanticRouter
from swarm_and_innovation import ModelRotationManager, ModelInfo


# ── V8-001: CancelToken ──────────────────────────────────


class TestCancelToken:
    """验证 CancelToken 协作式取消"""

    def test_initial_not_cancelled(self):
        token = CancelToken()
        assert not token.is_cancelled()

    def test_cancel_sets_flag(self):
        token = CancelToken()
        token.cancel("user_abort")
        assert token.is_cancelled()
        assert token.reason == "user_abort"

    @pytest.mark.asyncio
    async def test_wait_cancelled_returns_true(self):
        token = CancelToken()
        token.cancel()
        result = await token.wait_cancelled(timeout=0.1)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_cancelled_timeout(self):
        token = CancelToken()
        result = await token.wait_cancelled(timeout=0.01)
        assert result is False


class TestDispatcherCancellation:
    """验证 TaskDispatcher 集成 CancelToken"""

    @pytest.mark.asyncio
    async def test_cancel_task_before_dispatch(self):
        from task_dispatcher import TaskDispatcher
        from agent_registry import AgentRegistry
        from interfaces import AgentTask

        registry = AgentRegistry()
        mock_bus = AsyncMock()
        dispatcher = TaskDispatcher(registry, mock_bus)

        # 未分发的任务无法取消
        result = dispatcher.cancel_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_token_passed_to_agent(self):
        from task_dispatcher import TaskDispatcher
        from agent_registry import AgentRegistry
        from interfaces import AgentTask, IAgentPlugin

        registry = AgentRegistry()

        # 创建一个支持 cancel_token 的 Agent
        class CancelAwareAgent(IAgentPlugin):
            agent_id = "ca1"
            capabilities = ["test"]

            async def handle_task(self, task, cancel_token=None):
                return MagicMock(
                    task_id=task.task_id, trace_id=task.trace_id,
                    agent_id="ca1", status="success", latency_ms=1,
                )

            async def initialize(self):
                pass

            async def shutdown(self):
                pass

        agent = CancelAwareAgent()
        await registry.register(agent)

        mock_bus = AsyncMock()
        dispatcher = TaskDispatcher(registry, mock_bus)
        task = AgentTask(task_id="t1", target="ca1", intent="test")
        result = await dispatcher.dispatch(task)
        assert result.status == "success"

    def test_cancel_task_method_exists(self):
        from task_dispatcher import TaskDispatcher
        from agent_registry import AgentRegistry

        dispatcher = TaskDispatcher(AgentRegistry(), AsyncMock())
        assert hasattr(dispatcher, "cancel_task")


# ── V8-002: ModelRotationManager 降级链 ──────────────────


@pytest.mark.asyncio
async def test_acquire_returns_model_name():
    mgr = ModelRotationManager(max_vram_mb=6000)
    mgr.register_model(ModelInfo(name="qwen2-7b", size_mb=5000, capabilities=["chat"]))
    result = await mgr.acquire("qwen2-7b")
    assert result == "qwen2-7b"


@pytest.mark.asyncio
async def test_acquire_oom_fallback():
    """首选模型超显存时自动降级到次选"""
    mgr = ModelRotationManager(max_vram_mb=3000)
    mgr.register_model(ModelInfo(name="huge", size_mb=10000, capabilities=["chat"]))
    mgr.register_model(ModelInfo(name="tiny", size_mb=1000, capabilities=["chat"]))
    # 配置降级链
    mgr._fallback_chain["huge"] = ["tiny"]
    result = await mgr.acquire("huge")
    assert result == "tiny"


@pytest.mark.asyncio
async def test_acquire_all_unavailable_returns_none():
    mgr = ModelRotationManager(max_vram_mb=1000)
    mgr.register_model(ModelInfo(name="big1", size_mb=2000))
    mgr.register_model(ModelInfo(name="big2", size_mb=3000))
    mgr._fallback_chain["big1"] = ["big2"]
    result = await mgr.acquire("big1")
    assert result is None


@pytest.mark.asyncio
async def test_degradation_log_recorded():
    mgr = ModelRotationManager(max_vram_mb=3000)
    mgr.register_model(ModelInfo(name="large", size_mb=5000))
    mgr.register_model(ModelInfo(name="small", size_mb=1000))
    mgr._fallback_chain["large"] = ["small"]
    await mgr.acquire("large")
    assert len(mgr._degradation_log) == 1
    assert mgr._degradation_log[0]["requested"] == "large"
    assert mgr._degradation_log[0]["allocated"] == "small"


# ── V8-003: SemanticRouter 语义路由 ──────────────────────


class TestSemanticRouter:
    """验证轻量级语义 Agent 路由"""

    def test_register_and_route(self):
        router = SemanticRouter(n=2)
        router.register_agent(
            "code_agent",
            "擅长编写 Python 代码，处理算法问题和数据结构",
        )
        router.register_agent(
            "writing_agent",
            "擅长撰写文章、邮件、报告等中文写作任务",
        )

        results = router.route("帮我写一个排序算法", top_k=1)
        assert len(results) == 1
        assert results[0][0] == "code_agent"
        assert results[0][1] > 0.0

    def test_route_returns_sorted(self):
        router = SemanticRouter(n=2)
        router.register_agent("a1", "处理数学计算和统计")
        router.register_agent("a2", "处理图像识别和视觉")
        router.register_agent("a3", "处理数学建模和数值分析")

        results = router.route("计算一组数据的平均值", top_k=3)
        assert len(results) == 3
        # a1 应该比 a2 更相关（a3 可能也是0，取决于n-gram重叠）
        scores = {aid: score for aid, score in results}
        assert scores["a1"] > scores["a2"]

    def test_empty_router_returns_empty(self):
        router = SemanticRouter()
        assert router.route("anything") == []

    def test_unregister_removes_agent(self):
        router = SemanticRouter()
        router.register_agent("a1", "擅长代码")
        router.unregister_agent("a1")
        assert router.route("代码") == []

    def test_cosine_similarity_range(self):
        router = SemanticRouter()
        emb_a = router._embed("hello world")
        emb_b = router._embed("hello world")
        sim = router._cosine_similarity(emb_a, emb_b)
        assert abs(sim - 1.0) < 0.001

    def test_stats(self):
        router = SemanticRouter()
        router.register_agent("a1", "desc1")
        stats = router.stats()
        assert stats["registered_agents"] == 1
        assert "a1" in stats["agent_ids"]
