"""
V11.0 Agent 联邦调度系统 - 单元测试与集成测试

测试范围：
1. 数据模型
2. 外部 Agent 注册表
3. 适配器（基础+4家）
4. 联邦调度决策器
5. 多 Agent 对比器
6. 成本控制器
7. 隐私防护层
8. Orchestrator 集成
"""

from __future__ import annotations

import asyncio
import sys
import os
import time

import pytest

# ============================================================================
# 1. 数据模型测试
# ============================================================================

class TestFederationModels:
    """联邦调度数据模型测试"""

    def test_external_agent_profile_defaults(self):
        """ExternalAgentProfile 默认值测试"""
        from shared_models import ExternalAgentProfile, ExternalAgentType, AgentPrivacyLevel
        profile = ExternalAgentProfile(
            display_name="Test Agent",
            provider="TestProvider",
        )
        assert profile.display_name == "Test Agent"
        assert profile.provider == "TestProvider"
        assert profile.agent_type == ExternalAgentType.LLM
        assert profile.privacy_level == AgentPrivacyLevel.STANDARD
        assert profile.status == "active"
        assert profile.quality_rating == 4.0

    def test_federation_decision_internal(self):
        """FederationDecision 内部决策测试"""
        from shared_models import FederationDecision
        decision = FederationDecision(
            use_external=False,
            selected_agent_id="internal",
            selected_agent_name="内部 Agent 集群",
            decision_reason="测试内部决策",
        )
        assert decision.use_external is False
        assert decision.selected_agent_id == "internal"
        assert decision.estimated_cost == 0.0
        assert decision.quality_score == 0.0

    def test_federation_decision_external(self):
        """FederationDecision 外部决策测试"""
        from shared_models import FederationDecision
        decision = FederationDecision(
            use_external=True,
            selected_agent_id="gpt-4",
            selected_agent_name="GPT-4",
            decision_reason="质量优先模式",
            estimated_cost=0.045,
            estimated_latency="medium",
            quality_score=85.5,
        )
        assert decision.use_external is True
        assert decision.selected_agent_id == "gpt-4"
        assert decision.estimated_cost == 0.045
        assert decision.quality_score == 85.5

    def test_cost_record(self):
        """CostRecord 测试"""
        from shared_models import CostRecord
        record = CostRecord(
            task_id="task-001",
            agent_id="gpt-4",
            agent_name="GPT-4",
            input_tokens=1000,
            output_tokens=500,
            cost=0.045,
        )
        assert record.cost == 0.045
        assert record.currency == "USD"
        assert record.success is True
        assert record.timestamp > 0

    def test_privacy_scan_result(self):
        """PrivacyScanResult 测试"""
        from shared_models import PrivacyScanResult
        result = PrivacyScanResult(
            passed=True,
            risk_level="none",
            detections=[],
        )
        assert result.passed is True
        assert result.risk_level == "none"
        assert result.blocked is False


# ============================================================================
# 2. 外部 Agent 注册表测试
# ============================================================================

class TestExternalAgentRegistry:
    """外部 Agent 注册表测试"""

    def test_register_agent(self):
        """注册外部 Agent"""
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()

        agent = registry.register_agent(
            display_name="测试Agent",
            provider="TestProvider",
        )
        assert agent.agent_id != ""
        assert agent.display_name == "测试Agent"
        assert agent.status == "active"

    def test_register_with_type(self):
        """按类型注册"""
        from federation.registry import ExternalAgentRegistry
        from shared_models import ExternalAgentType

        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="代码助手",
            provider="CodeProvider",
            agent_type=ExternalAgentType.CODE,
        )
        assert agent.agent_type == ExternalAgentType.CODE

    def test_get_agent(self):
        """获取 Agent 详情"""
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()

        agent = registry.register_agent(display_name="A1", provider="P1")
        fetched = registry.get_agent(agent.agent_id)
        assert fetched is not None
        assert fetched.agent_id == agent.agent_id

    def test_get_nonexistent_agent(self):
        """获取不存在的 Agent"""
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        assert registry.get_agent("nonexistent") is None

    def test_list_agents(self):
        """列出 Agent"""
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()

        registry.register_agent(display_name="A1", provider="P1")
        registry.register_agent(display_name="A2", provider="P2")
        agents = registry.list_agents()
        # 默认注册1个本地模型 + 2个新注册 = 3
        assert len(agents) >= 2

    def test_list_agents_by_status(self):
        """按状态筛选 Agent"""
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()

        a1 = registry.register_agent(display_name="A1", provider="P1")
        a2 = registry.register_agent(display_name="A2", provider="P2")
        registry.update_status(a2.agent_id, "inactive")

        active = registry.list_agents(status="active")
        # 默认有1个本地模型 active + a1 active = 至少1个
        assert len(active) >= 1
        # a2 不在 active 列表中
        active_ids = [a.agent_id for a in active]
        assert a2.agent_id not in active_ids

    def test_unregister_agent(self):
        """注销 Agent"""
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()

        agent = registry.register_agent(display_name="A1", provider="P1")
        success = registry.unregister_agent(agent.agent_id)
        assert success is True
        assert registry.get_agent(agent.agent_id) is None

    def test_update_status(self):
        """更新 Agent 状态"""
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()

        agent = registry.register_agent(display_name="A1", provider="P1")
        updated = registry.update_status(agent.agent_id, "degraded")
        assert updated is not None
        assert updated.status == "degraded"

    @pytest.mark.asyncio
    async def test_health_check(self):
        """健康检查"""
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()

        agent = registry.register_agent(
            display_name="测试Agent",
            provider="OpenAI",
        )
        result = await registry.check_health(agent.agent_id)
        assert isinstance(result, dict)
        assert "healthy" in result
        assert "latency_ms" in result

    def test_get_adapter(self):
        """获取适配器"""
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()

        agent = registry.register_agent(
            display_name="GPT-4",
            provider="OpenAI",
        )
        adapter = registry.get_adapter(agent.agent_id)
        assert adapter is not None
        assert adapter.agent_id == agent.agent_id


# ============================================================================
# 3. 适配器测试
# ============================================================================

class TestBaseAdapter:
    """基础适配器测试"""

    @pytest.mark.asyncio
    async def test_invoke(self):
        """基础调用测试"""
        from federation.adapters.openai import OpenAIAdapter
        from shared_models import CostModel

        adapter = OpenAIAdapter(
            agent_id="test-gpt",
            display_name="Test GPT",
            config={"api_key": "test-key", "cost_model": CostModel().model_dump()},
        )
        result = await adapter.invoke(prompt="你好")
        assert "output" in result
        assert "input_tokens" in result
        assert "output_tokens" in result
        assert result.get("success", True) is True

    @pytest.mark.asyncio
    async def test_health_check(self):
        """健康检查测试"""
        from federation.adapters.openai import OpenAIAdapter
        from shared_models import CostModel

        adapter = OpenAIAdapter(
            agent_id="test-gpt",
            display_name="Test GPT",
            config={"api_key": "test-key", "cost_model": CostModel().model_dump()},
        )
        result = await adapter.health_check()
        assert result.get("healthy") is True
        assert "latency_ms" in result

    def test_calculate_cost(self):
        """成本计算测试"""
        from federation.adapters.openai import OpenAIAdapter
        from shared_models import CostModel

        cost_model = CostModel(input_per_1k=0.01, output_per_1k=0.03)
        adapter = OpenAIAdapter(
            agent_id="test-gpt",
            display_name="Test GPT",
            config={"api_key": "test-key", "cost_model": cost_model.model_dump()},
        )
        cost = adapter.calculate_cost(input_tokens=1000, output_tokens=500)
        # 1000 input * 0.01/1000 + 500 output * 0.03/1000 = 0.01 + 0.015 = 0.025
        assert abs(cost - 0.025) < 0.001


class TestAllAdapters:
    """所有适配器冒烟测试"""

    @pytest.mark.asyncio
    async def test_openai_adapter(self):
        """OpenAI 适配器"""
        from federation.adapters.openai import OpenAIAdapter
        from shared_models import CostModel
        adapter = OpenAIAdapter(
            agent_id="test-openai",
            display_name="Test OpenAI",
            config={"api_key": "test", "cost_model": CostModel().model_dump()},
        )
        result = await adapter.invoke(prompt="Hello")
        assert result.get("success", True)

    @pytest.mark.asyncio
    async def test_anthropic_adapter(self):
        """Anthropic 适配器"""
        from federation.adapters.anthropic import AnthropicAdapter
        from shared_models import CostModel
        adapter = AnthropicAdapter(
            agent_id="test-anthropic",
            display_name="Test Claude",
            config={"api_key": "test", "cost_model": CostModel().model_dump()},
        )
        result = await adapter.invoke(prompt="Hello")
        assert result.get("success", True)

    @pytest.mark.asyncio
    async def test_gemini_adapter(self):
        """Gemini 适配器"""
        from federation.adapters.gemini import GeminiAdapter
        from shared_models import CostModel
        adapter = GeminiAdapter(
            agent_id="test-gemini",
            display_name="Test Gemini",
            config={"api_key": "test", "cost_model": CostModel().model_dump()},
        )
        result = await adapter.invoke(prompt="Hello")
        assert result.get("success", True)

    @pytest.mark.asyncio
    async def test_local_adapter(self):
        """本地模型适配器"""
        from federation.adapters.local_model import LocalModelAdapter
        from shared_models import CostModel
        adapter = LocalModelAdapter(
            agent_id="test-local",
            display_name="Test Local",
            config={"model_path": "/tmp/test", "cost_model": CostModel().model_dump()},
        )
        result = await adapter.invoke(prompt="Hello")
        assert result.get("success", True)


# ============================================================================
# 4. 联邦调度决策器测试
# ============================================================================

class TestFederatedScheduler:
    """联邦调度决策器测试"""

    def _make_scheduler(self):
        from federation.registry import ExternalAgentRegistry
        from federation.scheduler import FederatedScheduler

        registry = ExternalAgentRegistry()
        # 注册几个测试 Agent
        registry.register_agent(
            display_name="GPT-4",
            provider="OpenAI",
            capabilities=["general", "code", "reasoning"],
        )
        registry.register_agent(
            display_name="Claude",
            provider="Anthropic",
            capabilities=["general", "analysis"],
        )
        scheduler = FederatedScheduler(registry=registry)
        return scheduler

    def test_decide_public_balanced(self):
        """公开等级+平衡模式"""
        from shared_models import SecurityClassification
        scheduler = self._make_scheduler()
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.PUBLIC,
        )
        assert isinstance(decision.use_external, bool)
        assert decision.selected_agent_id != ""
        assert decision.decision_reason != ""

    def test_decide_top_secret_forced_internal(self):
        """绝密强制内部执行"""
        from shared_models import SecurityClassification
        scheduler = self._make_scheduler()
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.TOP_SECRET,
        )
        assert decision.use_external is False
        assert "强制内部" in decision.decision_reason

    def test_decide_quality_first(self):
        """质量优先模式"""
        from shared_models import SecurityClassification, UserPreferenceMode
        scheduler = self._make_scheduler()
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.PUBLIC,
            user_preference=UserPreferenceMode.QUALITY_FIRST,
        )
        # 质量优先应该倾向于选择外部 Agent
        assert decision.quality_score > 0

    def test_decide_cost_first(self):
        """成本优先模式"""
        from shared_models import SecurityClassification, UserPreferenceMode
        scheduler = self._make_scheduler()
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.PUBLIC,
            user_preference=UserPreferenceMode.COST_FIRST,
        )
        assert isinstance(decision.estimated_cost, float)
        assert decision.estimated_cost >= 0

    def test_decide_budget_exceeded_fallback(self):
        """预算不足降级到内部"""
        from shared_models import SecurityClassification
        scheduler = self._make_scheduler()
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.PUBLIC,
            remaining_budget=0.0001,  # 极低预算
        )
        # 预算极低，应该降级到内部
        assert decision.use_external is False or decision.estimated_cost <= 0.0001

    def test_decide_speed_first(self):
        """速度优先模式"""
        from shared_models import SecurityClassification, UserPreferenceMode
        scheduler = self._make_scheduler()
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.PUBLIC,
            user_preference=UserPreferenceMode.SPEED_FIRST,
            speed_requirement="fast",
        )
        # 速度优先+极速要求 → 通常内部更快
        assert isinstance(decision.use_external, bool)

    def test_fallback_agent(self):
        """备选 Agent 存在"""
        from shared_models import SecurityClassification
        scheduler = self._make_scheduler()
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.PUBLIC,
        )
        if decision.use_external:
            # 注册了2个Agent，应该有备选
            assert decision.fallback_agent_id != ""


# ============================================================================
# 5. 多 Agent 对比器测试
# ============================================================================

class TestMultiAgentComparator:
    """多 Agent 对比器测试"""

    def _make_adapters(self, n: int = 2):
        from federation.adapters.openai import OpenAIAdapter
        from federation.adapters.anthropic import AnthropicAdapter
        from shared_models import CostModel

        cost_model_dict = CostModel().model_dump()
        adapters = []
        adapters.append(OpenAIAdapter(
            agent_id="gpt-test",
            display_name="GPT-Test",
            config={"api_key": "test", "cost_model": cost_model_dict},
        ))
        if n >= 2:
            adapters.append(AnthropicAdapter(
                agent_id="claude-test",
                display_name="Claude-Test",
                config={"api_key": "test", "cost_model": cost_model_dict},
            ))
        return adapters

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        """并行执行测试"""
        from federation.comparator import MultiAgentComparator
        from shared_models import ComparisonOutputMode

        comparator = MultiAgentComparator()
        adapters = self._make_adapters(2)

        comparison = await comparator.execute_parallel(
            adapters=adapters,
            prompt="写一个Python函数",
            output_mode=ComparisonOutputMode.BEST_ONLY,
            task_type="code_generation",
        )
        assert len(comparison.results) == 2
        assert comparison.best_result_index in (0, 1)
        assert comparison.total_cost >= 0

    @pytest.mark.asyncio
    async def test_best_only_mode(self):
        """单优输出模式"""
        from federation.comparator import MultiAgentComparator
        from shared_models import ComparisonOutputMode

        comparator = MultiAgentComparator()
        adapters = self._make_adapters(2)

        comparison = await comparator.execute_parallel(
            adapters=adapters,
            prompt="你好",
            output_mode=ComparisonOutputMode.BEST_ONLY,
        )
        assert comparison.output_mode == ComparisonOutputMode.BEST_ONLY
        assert comparison.best_result_index >= 0

    @pytest.mark.asyncio
    async def test_fusion_mode(self):
        """融合输出模式"""
        from federation.comparator import MultiAgentComparator
        from shared_models import ComparisonOutputMode

        comparator = MultiAgentComparator()
        adapters = self._make_adapters(2)

        comparison = await comparator.execute_parallel(
            adapters=adapters,
            prompt="介绍一下Python",
            output_mode=ComparisonOutputMode.FUSION,
        )
        assert comparison.output_mode == ComparisonOutputMode.FUSION
        assert comparison.fusion_output != ""

    @pytest.mark.asyncio
    async def test_comparison_mode(self):
        """对比输出模式"""
        from federation.comparator import MultiAgentComparator
        from shared_models import ComparisonOutputMode

        comparator = MultiAgentComparator()
        adapters = self._make_adapters(2)

        comparison = await comparator.execute_parallel(
            adapters=adapters,
            prompt="你好",
            output_mode=ComparisonOutputMode.SIDE_BY_SIDE,
        )
        assert comparison.output_mode == ComparisonOutputMode.SIDE_BY_SIDE
        assert len(comparison.results) == 2

    def test_quality_scoring(self):
        """质量评分测试"""
        from federation.comparator import MultiAgentComparator
        comparator = MultiAgentComparator()

        # 测试不同长度内容的评分
        short_score = comparator._score_quality("好的", "general", "你好")
        long_score = comparator._score_quality(
            "这是一个详细的回答。\n\n"
            "1. 第一点：解释了基本概念\n"
            "2. 第二点：提供了具体示例\n"
            "3. 第三点：总结了注意事项\n\n"
            "以上就是完整的解答。",
            "general",
            "请详细介绍",
        )
        # 长且结构化的回答应该分数更高
        assert long_score >= short_score

    @pytest.mark.asyncio
    async def test_single_adapter(self):
        """单 Agent 对比（边缘情况）"""
        from federation.comparator import MultiAgentComparator
        from shared_models import ComparisonOutputMode

        comparator = MultiAgentComparator()
        adapters = self._make_adapters(1)

        comparison = await comparator.execute_parallel(
            adapters=adapters,
            prompt="你好",
            output_mode=ComparisonOutputMode.BEST_ONLY,
        )
        assert len(comparison.results) == 1
        assert comparison.best_result_index == 0

    @pytest.mark.asyncio
    async def test_empty_adapters(self):
        """空适配器列表（边缘情况）"""
        from federation.comparator import MultiAgentComparator
        from shared_models import ComparisonOutputMode

        comparator = MultiAgentComparator()
        comparison = await comparator.execute_parallel(
            adapters=[],
            prompt="你好",
        )
        assert len(comparison.results) == 0


# ============================================================================
# 6. 成本控制器测试
# ============================================================================

class TestCostController:
    """成本控制器测试"""

    def test_initial_budget(self):
        """初始预算"""
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)
        budget = controller.get_budget()
        assert budget.monthly_budget == 10.0
        assert budget.spent_this_month == 0.0

    def test_remaining_budget(self):
        """剩余预算"""
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)
        assert controller.remaining_budget() == 10.0

    def test_record_cost(self):
        """记录费用"""
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)

        record = controller.record_cost(
            task_id="task-001",
            agent_id="gpt-4",
            agent_name="GPT-4",
            input_tokens=1000,
            output_tokens=500,
            cost=0.045,
        )
        assert record.cost == 0.045
        assert controller.remaining_budget() == 9.955

    def test_multiple_records(self):
        """多笔费用记录"""
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)

        controller.record_cost("t1", "a1", "A1", 100, 100, 0.01)
        controller.record_cost("t2", "a2", "A2", 200, 200, 0.02)
        controller.record_cost("t3", "a1", "A1", 300, 300, 0.03)

        assert controller.get_budget().spent_this_month == 0.06

    def test_budget_exceeded(self):
        """超预算检测"""
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=0.1)

        controller.record_cost("t1", "a1", "A1", 1000, 1000, 0.05)
        assert controller.budget_exceeded() is False

        controller.record_cost("t2", "a2", "A2", 2000, 2000, 0.06)
        assert controller.budget_exceeded() is True

    def test_alert_thresholds(self):
        """三级告警测试"""
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)

        # 50% 告警
        controller.record_cost("t1", "a1", "A1", 1000, 1000, 5.0)
        budget = controller.get_budget()
        assert budget.alert_threshold_50 is True

        # 80% 告警
        controller.record_cost("t2", "a1", "A1", 1000, 1000, 3.1)
        budget = controller.get_budget()
        assert budget.alert_threshold_80 is True

        # 100% 告警
        controller.record_cost("t3", "a1", "A1", 1000, 1000, 2.0)
        budget = controller.get_budget()
        assert budget.alert_threshold_100 is True

    def test_set_budget(self):
        """设置预算"""
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)

        result = controller.set_monthly_budget(50.0)
        assert result["success"] is True
        assert result["monthly_budget"] == 50.0

    def test_get_records(self):
        """查询费用记录"""
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)

        controller.record_cost("t1", "a1", "A1", 100, 100, 0.01, task_type="general")
        controller.record_cost("t2", "a2", "A2", 200, 200, 0.02, task_type="code")
        controller.record_cost("t3", "a1", "A1", 300, 300, 0.03, task_type="general")

        # 按 Agent 筛选
        a1_records = controller.get_records(agent_id="a1")
        assert len(a1_records) == 2

        # 按任务类型筛选
        code_records = controller.get_records(task_type="code")
        assert len(code_records) == 1

        # limit
        limited = controller.get_records(limit=2)
        assert len(limited) == 2

    def test_stats(self):
        """统计信息"""
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)

        controller.record_cost("t1", "a1", "A1", 100, 100, 0.01, success=True)
        controller.record_cost("t2", "a2", "A2", 200, 200, 0.02, success=False)

        stats = controller.stats()
        assert stats["monthly_budget"] == 10.0
        assert stats["successful_calls"] == 1
        assert stats["total_records"] == 2

    def test_failed_call_not_counted(self):
        """失败调用不计入已花费"""
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)

        controller.record_cost("t1", "a1", "A1", 100, 100, 0.05, success=False)
        assert controller.get_budget().spent_this_month == 0.0


# ============================================================================
# 7. 隐私防护层测试
# ============================================================================

class TestPrivacyGuard:
    """隐私防护层测试"""

    def test_clean_content_passes(self):
        """干净内容通过"""
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification

        guard = FederationPrivacyGuard()
        result = guard.scan(
            content="这是一段普通的文本内容，没有敏感信息。",
            security_level=SecurityClassification.PUBLIC,
        )
        assert result.passed is True
        assert result.risk_level == "none"
        assert result.blocked is False

    def test_email_detection(self):
        """邮箱检测"""
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification

        guard = FederationPrivacyGuard()
        result = guard.scan(
            content="请联系 test@example.com 获取更多信息",
            security_level=SecurityClassification.PUBLIC,
        )
        # 有 PII 应该被检测到
        pii_types = [d.get("pii_type") for d in result.detections if d.get("type") == "pii"]
        assert "email" in pii_types

    def test_phone_detection(self):
        """手机号检测"""
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification

        guard = FederationPrivacyGuard()
        result = guard.scan(
            content="我的手机号是13812345678",
            security_level=SecurityClassification.PUBLIC,
        )
        pii_types = [d.get("pii_type") for d in result.detections if d.get("type") == "pii"]
        assert "phone_cn" in pii_types

    def test_api_key_detection(self):
        """API Key 检测"""
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification

        guard = FederationPrivacyGuard()
        result = guard.scan(
            content='api_key = "sk-1234567890abcdefghijklmnop"',
            security_level=SecurityClassification.PUBLIC,
        )
        secret_types = [d.get("secret_type") for d in result.detections if d.get("type") == "code_secret"]
        assert "api_key" in secret_types

    def test_custom_keyword_detection(self):
        """自定义关键词检测"""
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification

        guard = FederationPrivacyGuard()
        result = guard.scan(
            content="这是内部机密文件，请妥善保管",
            security_level=SecurityClassification.PUBLIC,
        )
        keyword_detections = [d for d in result.detections if d.get("type") == "custom_keyword"]
        assert len(keyword_detections) > 0

    def test_top_secret_blocked(self):
        """绝密内容直接拦截"""
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification

        guard = FederationPrivacyGuard()
        result = guard.scan(
            content="普通内容",
            security_level=SecurityClassification.TOP_SECRET,
        )
        assert result.blocked is True
        assert result.passed is False
        assert result.risk_level == "high"

    def test_confidential_warning(self):
        """机密内容警告"""
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification

        guard = FederationPrivacyGuard()
        result = guard.scan(
            content="普通内容",
            security_level=SecurityClassification.CONFIDENTIAL,
        )
        assert result.blocked is True  # 概念级实现：机密也拦截
        assert result.risk_level in ("high", "medium")

    def test_sanitization(self):
        """自动脱敏"""
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification

        guard = FederationPrivacyGuard(auto_sanitize=True)
        result = guard.scan(
            content="我的邮箱是 test@example.com，请联系我",
            security_level=SecurityClassification.PUBLIC,
        )
        # 轻度敏感应该被脱敏
        if result.risk_level == "low":
            assert "test@example.com" not in result.sanitized_content

    def test_add_remove_keyword(self):
        """添加/移除关键词"""
        from federation.privacy_guard import FederationPrivacyGuard

        guard = FederationPrivacyGuard(custom_keywords=[])
        assert guard.add_blocked_keyword("敏感词A") is True
        # 重复添加应该返回 False
        assert guard.add_blocked_keyword("敏感词A") is False

        assert guard.remove_blocked_keyword("敏感词A") is True
        assert guard.remove_blocked_keyword("敏感词A") is False

    def test_audit_log(self):
        """审计日志"""
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification

        guard = FederationPrivacyGuard()
        guard.scan("测试内容1", SecurityClassification.PUBLIC)
        guard.scan("测试内容2", SecurityClassification.INTERNAL)

        logs = guard.get_audit_log()
        assert len(logs) >= 2


# ============================================================================
# 8. Orchestrator 集成测试
# ============================================================================

class TestOrchestratorFederationIntegration:
    """Orchestrator 联邦调度集成测试"""

    @pytest.mark.asyncio
    async def test_federation_decide_capability(self):
        """Orchestrator 支持联邦决策能力"""
        from orchestrator.agent import OrchestratorAgent
        orch = OrchestratorAgent()
        assert "federation.decide" in orch.capabilities

    @pytest.mark.asyncio
    async def test_federation_invoke_capability(self):
        """Orchestrator 支持联邦调用能力"""
        from orchestrator.agent import OrchestratorAgent
        orch = OrchestratorAgent()
        assert "federation.invoke" in orch.capabilities

    @pytest.mark.asyncio
    async def test_federation_compare_capability(self):
        """Orchestrator 支持联邦对比能力"""
        from orchestrator.agent import OrchestratorAgent
        orch = OrchestratorAgent()
        assert "federation.compare" in orch.capabilities

    @pytest.mark.asyncio
    async def test_handle_fed_decide(self):
        """处理联邦决策请求"""
        from orchestrator.agent import OrchestratorAgent
        from interfaces import AgentTask

        orch = OrchestratorAgent()
        task = AgentTask(
            task_id="test-fed-decide",
            intent="federation.decide",
            payload={
                "task_type": "general",
                "security_level": "PUBLIC",
                "user_preference": "balanced",
            },
        )
        result = await orch.handle_task(task)
        assert result.status == "success"
        assert "decision" in result.output
        assert "use_external" in result.output["decision"]

    @pytest.mark.asyncio
    async def test_handle_fed_invoke(self):
        """处理联邦调用请求"""
        from orchestrator.agent import OrchestratorAgent
        from interfaces import AgentTask

        orch = OrchestratorAgent()
        # 先注册一个测试 Agent
        registry = orch._get_fed_registry()
        agent = registry.register_agent(
            display_name="测试Agent",
            provider="OpenAI",
        )

        task = AgentTask(
            task_id="test-fed-invoke",
            intent="federation.invoke",
            payload={
                "agent_id": agent.agent_id,
                "prompt": "你好，请介绍一下自己",
                "security_level": "PUBLIC",
            },
        )
        result = await orch.handle_task(task)
        assert result.status == "success"
        assert "result" in result.output

    @pytest.mark.asyncio
    async def test_handle_fed_compare(self):
        """处理联邦对比请求"""
        from orchestrator.agent import OrchestratorAgent
        from interfaces import AgentTask

        orch = OrchestratorAgent()
        registry = orch._get_fed_registry()
        a1 = registry.register_agent(display_name="Agent1", provider="OpenAI")
        a2 = registry.register_agent(display_name="Agent2", provider="Anthropic")

        task = AgentTask(
            task_id="test-fed-compare",
            intent="federation.compare",
            payload={
                "agent_ids": [a1.agent_id, a2.agent_id],
                "prompt": "写一个Python函数",
                "output_mode": "best_only",
                "task_type": "code_generation",
            },
        )
        result = await orch.handle_task(task)
        assert result.status == "success"
        assert "comparison" in result.output
        assert len(result.output["comparison"]["results"]) == 2

    @pytest.mark.asyncio
    async def test_fed_invoke_privacy_blocked(self):
        """高涉密内容调用被隐私层拦截"""
        from orchestrator.agent import OrchestratorAgent
        from interfaces import AgentTask

        orch = OrchestratorAgent()
        registry = orch._get_fed_registry()
        agent = registry.register_agent(display_name="测试Agent", provider="OpenAI")

        task = AgentTask(
            task_id="test-privacy-block",
            intent="federation.invoke",
            payload={
                "agent_id": agent.agent_id,
                "prompt": "普通内容",
                "security_level": "TOP_SECRET",
            },
        )
        result = await orch.handle_task(task)
        # 应该被隐私检查拦截，返回失败但不抛异常
        assert result.status == "success"
        assert result.output.get("success") is False


# ============================================================================
# 9. 端到端集成测试
# ============================================================================

class TestEndToEndFederation:
    """端到端联邦调度集成测试"""

    @pytest.mark.asyncio
    async def test_full_federation_flow(self):
        """完整联邦调度流程：决策→调用→成本记录"""
        from federation.registry import ExternalAgentRegistry
        from federation.scheduler import FederatedScheduler
        from federation.cost_controller import CostController
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import (
            SecurityClassification,
            UserPreferenceMode,
        )

        # 初始化组件
        registry = ExternalAgentRegistry()
        scheduler = FederatedScheduler(registry=registry)
        cost_ctrl = CostController(monthly_budget=5.0)
        privacy = FederationPrivacyGuard()

        # 注册外部 Agent
        gpt = registry.register_agent(
            display_name="GPT-4",
            provider="OpenAI",
        )
        claude = registry.register_agent(
            display_name="Claude",
            provider="Anthropic",
        )

        # Step 1: 决策
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.PUBLIC,
            user_preference=UserPreferenceMode.QUALITY_FIRST,
            remaining_budget=cost_ctrl.remaining_budget(),
        )

        assert decision.selected_agent_id != ""
        if decision.use_external:
            # Step 2: 隐私检查
            prompt = "请用Python写一个快速排序算法"
            scan = privacy.scan(prompt, SecurityClassification.PUBLIC)
            assert scan.passed is True

            # Step 3: 调用
            adapter = registry.get_adapter(decision.selected_agent_id)
            assert adapter is not None

            result = await adapter.invoke(prompt=prompt)
            assert result.get("success", True)

            # Step 4: 记录成本
            cost = adapter.calculate_cost(
                result.get("input_tokens", 0),
                result.get("output_tokens", 0),
            )
            cost_ctrl.record_cost(
                task_id="e2e-test-001",
                agent_id=decision.selected_agent_id,
                agent_name=decision.selected_agent_name,
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                cost=cost,
            )

            # 验证成本被正确记录
            assert cost_ctrl.get_budget().spent_this_month > 0

    @pytest.mark.asyncio
    async def test_privacy_then_invoke_flow(self):
        """隐私检查→调用 流程"""
        from federation.registry import ExternalAgentRegistry
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification

        registry = ExternalAgentRegistry()
        privacy = FederationPrivacyGuard()

        agent = registry.register_agent(display_name="测试Agent", provider="OpenAI")
        adapter = registry.get_adapter(agent.agent_id)

        # 包含邮箱的内容
        prompt = "请回复到 test@example.com"
        scan = privacy.scan(prompt, SecurityClassification.PUBLIC)

        # 有 PII，但风险等级不高的情况下使用脱敏后内容调用
        content_to_send = scan.sanitized_content if scan.risk_level != "none" and not scan.blocked else prompt

        if not scan.blocked:
            result = await adapter.invoke(prompt=content_to_send)
            assert result.get("success", True)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
