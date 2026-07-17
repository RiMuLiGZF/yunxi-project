"""
联邦调度测试套件（按功能模块重组）

来源版本：
- test_v11_federation.py (v11.0 联邦调度系统：数据模型、注册表、适配器、调度器、
  对比器、成本控制器、隐私防护层、Orchestrator 集成、端到端测试)
- test_v11_1_fixes.py (v11.1 整改：API Key 加密存储、PII 风险分级、
  PII 检测正则增强、7 类 PII 脱敏补全、GPL 协议风险提示、审计摘要字段)

说明：
本文件从 v11 系列版本测试中提取联邦调度核心功能的测试，按子功能分类组织。
原始版本文件已移入 tests/_legacy/ 目录保存。
"""

from __future__ import annotations

import sys
import os

import pytest

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# 1. 联邦调度数据模型测试（来源：test_v11_federation.py）
# ============================================================================

class TestFederationModels:
    """联邦调度数据模型测试"""

    def test_external_agent_profile_defaults(self):
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
# 2. 外部 Agent 注册表测试（来源：test_v11_federation.py）
# ============================================================================

class TestExternalAgentRegistry:
    """外部 Agent 注册表测试"""

    def test_register_agent(self):
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
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        agent = registry.register_agent(display_name="A1", provider="P1")
        fetched = registry.get_agent(agent.agent_id)
        assert fetched is not None
        assert fetched.agent_id == agent.agent_id

    def test_get_nonexistent_agent(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        assert registry.get_agent("nonexistent") is None

    def test_list_agents(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        registry.register_agent(display_name="A1", provider="P1")
        registry.register_agent(display_name="A2", provider="P2")
        agents = registry.list_agents()
        assert len(agents) >= 2

    def test_unregister_agent(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        agent = registry.register_agent(display_name="A1", provider="P1")
        success = registry.unregister_agent(agent.agent_id)
        assert success is True
        assert registry.get_agent(agent.agent_id) is None

    def test_update_status(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        agent = registry.register_agent(display_name="A1", provider="P1")
        updated = registry.update_status(agent.agent_id, "degraded")
        assert updated is not None
        assert updated.status == "degraded"

    @pytest.mark.asyncio
    async def test_health_check(self):
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
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="GPT-4",
            provider="OpenAI",
        )
        adapter = registry.get_adapter(agent.agent_id)
        assert adapter is not None
        assert adapter.agent_id == agent.agent_id

    def test_stats_shows_encrypted_key_count(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        stats_before = registry.stats()
        initial_keys = stats_before.get("encrypted_keys", 0)
        for i in range(3):
            registry.register_agent(
                display_name=f"Agent{i}",
                provider=f"Provider{i}",
                api_key=f"sk-test-key-{i}-{1000 + i}",
            )
        stats_after = registry.stats()
        assert stats_after["encrypted_keys"] == initial_keys + 3
        assert "crypto_available" in stats_after


# ============================================================================
# 3. API Key 加密存储测试（来源：test_v11_1_fixes.py）
# ============================================================================

class TestApiKeyEncryption:
    """API Key 加密存储测试"""

    def test_encrypted_key_not_in_memory(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="测试Agent",
            provider="TestProvider",
            api_key="sk-real-secret-key-1234567890",
        )
        encrypted = registry._api_keys_encrypted.get(agent.agent_id, "")
        assert encrypted != "sk-real-secret-key-1234567890"
        assert len(encrypted) > 0
        assert "real-secret" not in encrypted

    def test_trusted_caller_gets_plaintext(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="测试Agent",
            provider="TestProvider",
            api_key="sk-trusted-caller-key-12345",
        )
        plaintext = registry.get_api_key(
            agent.agent_id,
            caller_id="federation.adapter.openai",
        )
        assert plaintext == "sk-trusted-caller-key-12345"

    def test_untrusted_caller_gets_masked(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="测试Agent",
            provider="TestProvider",
            api_key="sk-untrusted-secret-key-67890",
        )
        masked = registry.get_api_key(
            agent.agent_id,
            caller_id="some.external.service",
        )
        assert masked != "sk-untrusted-secret-key-67890"
        assert "****" in masked
        assert "untrusted-secret" not in masked

    def test_master_key_rotation(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        agent1 = registry.register_agent(
            display_name="Agent1",
            provider="ProviderA",
            api_key="sk-key-one-aaaa1111",
        )
        agent2 = registry.register_agent(
            display_name="Agent2",
            provider="ProviderB",
            api_key="sk-key-two-bbbb2222",
        )
        key1_before = registry.get_api_key(agent1.agent_id, caller_id="federation.registry")
        assert key1_before == "sk-key-one-aaaa1111"
        result = registry.rotate_all_keys()
        assert result["success"] is True
        assert result["rotated_keys_count"] == 2
        key1_after = registry.get_api_key(agent1.agent_id, caller_id="federation.registry")
        key2_after = registry.get_api_key(agent2.agent_id, caller_id="federation.registry")
        assert key1_after == "sk-key-one-aaaa1111"
        assert key2_after == "sk-key-two-bbbb2222"

    def test_empty_api_key_handling(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="无KeyAgent",
            provider="NoKeyProvider",
            api_key="",
        )
        assert agent.agent_id not in registry._api_keys_encrypted
        value = registry.get_api_key(agent.agent_id, caller_id="federation.registry")
        assert value == ""

    def test_unknown_agent_returns_empty(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        value = registry.get_api_key("nonexistent_agent_id")
        assert value == ""


# ============================================================================
# 4. 适配器测试（来源：test_v11_federation.py）
# ============================================================================

class TestBaseAdapter:
    """基础适配器测试"""

    @pytest.mark.asyncio
    async def test_invoke(self):
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

    @pytest.mark.asyncio
    async def test_health_check(self):
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
        from federation.adapters.openai import OpenAIAdapter
        from shared_models import CostModel
        cost_model = CostModel(input_per_1k=0.01, output_per_1k=0.03)
        adapter = OpenAIAdapter(
            agent_id="test-gpt",
            display_name="Test GPT",
            config={"api_key": "test-key", "cost_model": cost_model.model_dump()},
        )
        cost = adapter.calculate_cost(input_tokens=1000, output_tokens=500)
        assert abs(cost - 0.025) < 0.001


class TestAllAdapters:
    """所有适配器冒烟测试"""

    @pytest.mark.asyncio
    async def test_openai_adapter(self):
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
# 5. 联邦调度决策器测试（来源：test_v11_federation.py）
# ============================================================================

class TestFederatedScheduler:
    """联邦调度决策器测试"""

    def _make_scheduler(self):
        from federation.registry import ExternalAgentRegistry
        from federation.scheduler import FederatedScheduler
        registry = ExternalAgentRegistry()
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
        from shared_models import SecurityClassification
        scheduler = self._make_scheduler()
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.TOP_SECRET,
        )
        assert decision.use_external is False
        assert "强制内部" in decision.decision_reason

    def test_decide_quality_first(self):
        from shared_models import SecurityClassification, UserPreferenceMode
        scheduler = self._make_scheduler()
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.PUBLIC,
            user_preference=UserPreferenceMode.QUALITY_FIRST,
        )
        assert decision.quality_score > 0

    def test_decide_cost_first(self):
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
        from shared_models import SecurityClassification
        scheduler = self._make_scheduler()
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.PUBLIC,
            remaining_budget=0.0001,
        )
        assert decision.use_external is False or decision.estimated_cost <= 0.0001


# ============================================================================
# 6. 多 Agent 对比器测试（来源：test_v11_federation.py）
# ============================================================================

class TestMultiAgentComparator:
    """多 Agent 对比器测试"""

    def _make_adapters(self, n=2):
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
    async def test_single_adapter(self):
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

    def test_quality_scoring(self):
        from federation.comparator import MultiAgentComparator
        comparator = MultiAgentComparator()
        short_score = comparator._score_quality("好的", "general", "你好")
        long_score = comparator._score_quality(
            "这是一个详细的回答。\n\n1. 第一点：解释了基本概念\n2. 第二点：提供了具体示例\n3. 第三点：总结了注意事项\n\n以上就是完整的解答。",
            "general",
            "请详细介绍",
        )
        assert long_score >= short_score


# ============================================================================
# 7. 成本控制器测试（来源：test_v11_federation.py）
# ============================================================================

class TestCostController:
    """成本控制器测试"""

    def test_initial_budget(self):
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)
        budget = controller.get_budget()
        assert budget.monthly_budget == 10.0
        assert budget.spent_this_month == 0.0

    def test_remaining_budget(self):
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)
        assert controller.remaining_budget() == 10.0

    def test_record_cost(self):
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
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)
        controller.record_cost("t1", "a1", "A1", 100, 100, 0.01)
        controller.record_cost("t2", "a2", "A2", 200, 200, 0.02)
        controller.record_cost("t3", "a1", "A1", 300, 300, 0.03)
        assert controller.get_budget().spent_this_month == 0.06

    def test_budget_exceeded(self):
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=0.1)
        controller.record_cost("t1", "a1", "A1", 1000, 1000, 0.05)
        assert controller.budget_exceeded() is False
        controller.record_cost("t2", "a2", "A2", 2000, 2000, 0.06)
        assert controller.budget_exceeded() is True

    def test_alert_thresholds(self):
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)
        controller.record_cost("t1", "a1", "A1", 1000, 1000, 5.0)
        budget = controller.get_budget()
        assert budget.alert_threshold_50 is True
        controller.record_cost("t2", "a1", "A1", 1000, 1000, 3.1)
        budget = controller.get_budget()
        assert budget.alert_threshold_80 is True

    def test_set_budget(self):
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)
        result = controller.set_monthly_budget(50.0)
        assert result["success"] is True
        assert result["monthly_budget"] == 50.0

    def test_stats(self):
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)
        controller.record_cost("t1", "a1", "A1", 100, 100, 0.01, success=True)
        controller.record_cost("t2", "a2", "A2", 200, 200, 0.02, success=False)
        stats = controller.stats()
        assert stats["monthly_budget"] == 10.0
        assert stats["successful_calls"] == 1
        assert stats["total_records"] == 2

    def test_failed_call_not_counted(self):
        from federation.cost_controller import CostController
        controller = CostController(monthly_budget=10.0)
        controller.record_cost("t1", "a1", "A1", 100, 100, 0.05, success=False)
        assert controller.get_budget().spent_this_month == 0.0


# ============================================================================
# 8. 隐私防护层测试（来源：test_v11_federation.py + test_v11_1_fixes.py）
# ============================================================================

class TestFederationPrivacyGuard:
    """联邦调度隐私防护层测试"""

    def test_clean_content_passes(self):
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
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification
        guard = FederationPrivacyGuard()
        result = guard.scan(
            content="请联系 test@example.com 获取更多信息",
            security_level=SecurityClassification.PUBLIC,
        )
        pii_types = [d.get("pii_type") for d in result.detections if d.get("type") == "pii"]
        assert "email" in pii_types

    def test_phone_detection(self):
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
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification
        guard = FederationPrivacyGuard()
        result = guard.scan(
            content='api_key = "sk-1234567890abcdefghijklmnop"',
            security_level=SecurityClassification.PUBLIC,
        )
        secret_types = [d.get("secret_type") for d in result.detections if d.get("type") == "code_secret"]
        assert "api_key" in secret_types

    def test_top_secret_blocked(self):
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

    def test_add_remove_keyword(self):
        from federation.privacy_guard import FederationPrivacyGuard
        guard = FederationPrivacyGuard(custom_keywords=[])
        assert guard.add_blocked_keyword("敏感词A") is True
        assert guard.add_blocked_keyword("敏感词A") is False
        assert guard.remove_blocked_keyword("敏感词A") is True
        assert guard.remove_blocked_keyword("敏感词A") is False

    def test_audit_log(self):
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import SecurityClassification
        guard = FederationPrivacyGuard()
        guard.scan("测试内容1", SecurityClassification.PUBLIC)
        guard.scan("测试内容2", SecurityClassification.INTERNAL)
        logs = guard.get_audit_log()
        assert len(logs) >= 2


# ============================================================================
# 9. PII 风险分级测试（来源：test_v11_1_fixes.py）
# ============================================================================

class TestPiiRiskLevelFixes:
    """PII 风险分级修复测试"""

    def test_low_risk_also_sanitized(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        result = guard.sanitize_content(
            content="请联系 a@b.com 谢谢",
            security_level=SecurityClassification.PUBLIC,
        )
        assert result["was_modified"] is True
        assert "a@b.com" not in result["sanitized"]

    def test_medium_risk_sanitized(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        result = guard.sanitize_content(
            content="我的邮箱是 test_user@example.com",
            security_level=SecurityClassification.INTERNAL,
        )
        assert result["risk_level"] in ("medium", "low")
        assert result["was_modified"] is True
        assert "test_user" not in result["sanitized"]
        assert "example.com" in result["sanitized"]

    def test_high_risk_strong_sanitization(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        result = guard.sanitize_content(
            content="我的手机号是13812345678",
            security_level=SecurityClassification.CONFIDENTIAL,
        )
        assert result["risk_level"] in ("high", "critical")
        assert result["was_modified"] is True
        assert "13812345678" not in result["sanitized"]

    def test_critical_risk_full_replacement(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        result = guard.sanitize_content(
            content="身份证号 110101199003077758",
            security_level=SecurityClassification.INTERNAL,
        )
        assert result["risk_level"] == "critical"
        assert result["was_modified"] is True
        assert "110101199003077758" not in result["sanitized"]

    def test_none_risk_unchanged(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        original = "这是一段完全正常的文本，不包含任何敏感信息。"
        result = guard.sanitize_content(
            content=original,
            security_level=SecurityClassification.PUBLIC,
        )
        assert result["risk_level"] == "none"
        assert result["was_modified"] is False
        assert result["sanitized"] == original


# ============================================================================
# 10. PII 检测正则增强测试（来源：test_v11_1_fixes.py）
# ============================================================================

class TestPiiDetectionEnhancement:
    """PII 检测正则增强测试"""

    def test_zero_width_char_bypass(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        zw_email = "t\u200be\u200bs\u200bt@example.com"
        result = guard.scan_content(zw_email, SecurityClassification.PUBLIC)
        assert "email" in result["pii_types"]

    def test_fullwidth_char_bypass(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        fullwidth_email = "test@ｅｘａｍｐｌｅ．ｃｏｍ"
        result = guard.scan_content(fullwidth_email, SecurityClassification.PUBLIC)
        assert "email" in result["pii_types"]

    def test_at_dot_notation_bypass(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        obfuscated = "请联系 test [at] example [dot] com 获取信息"
        result = guard.scan_content(obfuscated, SecurityClassification.PUBLIC)
        assert "email" in result["pii_types"]

    def test_phone_with_spaces_detected(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        spaced_phone = "我的电话是 138 1234 5678"
        result = guard.scan_content(spaced_phone, SecurityClassification.PUBLIC)
        assert "phone_cn" in result["pii_types"]

    def test_id_card_checksum_valid(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        valid_id = "身份证号：110101199003077758"
        result = guard.scan_content(valid_id, SecurityClassification.PUBLIC)
        assert "id_card_cn" in result["pii_types"]

    def test_id_card_checksum_invalid(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        invalid_id = "身份证号：110101199003077759"
        result = guard.scan_content(invalid_id, SecurityClassification.PUBLIC)
        id_card_detections = [
            d for d in result["detections"] if d["pii_type"] == "id_card_cn"
        ]
        assert len(id_card_detections) == 0

    def test_bank_card_luhn_validation(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        valid_card = "卡号：4111111111111111"
        result_valid = guard.scan_content(valid_card, SecurityClassification.PUBLIC)
        bank_detections_valid = [
            d for d in result_valid["detections"] if d["pii_type"] == "bank_card"
        ]
        assert len(bank_detections_valid) >= 1
        invalid_card = "卡号：4111111111111112"
        result_invalid = guard.scan_content(invalid_card, SecurityClassification.PUBLIC)
        bank_detections_invalid = [
            d for d in result_invalid["detections"] if d["pii_type"] == "bank_card"
        ]
        assert len(bank_detections_invalid) == 0


# ============================================================================
# 11. 7 类 PII 脱敏补全测试（来源：test_v11_1_fixes.py）
# ============================================================================

class TestPiiSanitizationComplete:
    """7 类 PII 脱敏补全测试"""

    def test_id_card_sanitization(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        original = "请提供身份证 110101199003077758 用于验证"
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)
        assert result["was_modified"] is True
        assert "110101199003077758" not in result["sanitized"]

    def test_bank_card_sanitization(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        original = "银行卡号 4111111111111111 请妥善保管"
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)
        assert result["was_modified"] is True
        assert "4111111111111111" not in result["sanitized"]

    def test_api_key_sanitization(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        original = '配置文件内容：api_key = "sk-abcdefghijklmnopqrstuvwxyz123456"'
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)
        assert result["was_modified"] is True
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result["sanitized"]

    def test_password_sanitization(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        original = "配置信息：password = my_secret_password_123，请妥善保管"
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)
        assert result["was_modified"] is True
        assert "my_secret_password_123" not in result["sanitized"]

    def test_token_sanitization(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        original = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature12345"
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)
        assert result["was_modified"] is True
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result["sanitized"]

    def test_private_key_sanitization(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        original = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA0Z5+sampleprivatekeydata1234567890abcdefghij\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)
        assert result["was_modified"] is True
        assert "MIIEpAIBAAKCAQEA0Z5" not in result["sanitized"]

    def test_internal_url_sanitization(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        original = "请访问 http://192.168.1.100:8080/api/internal 获取数据"
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)
        assert result["was_modified"] is True
        assert "192.168.1.100" not in result["sanitized"]
        assert "url_internal" in result["pii_types"]


# ============================================================================
# 12. GPL 协议风险提示测试（来源：test_v11_1_fixes.py）
# ============================================================================

class TestGplLicenseRisk:
    """GPL 协议风险提示测试"""

    def test_gpl_license_without_confirmation_fails(self):
        from federation.registry import ExternalAgentRegistry
        registry = ExternalAgentRegistry()
        with pytest.raises(ValueError) as exc_info:
            registry.register_agent(
                display_name="GPL Agent",
                provider="GPLProvider",
                license="GPL-3.0",
                confirm_license_risk=False,
            )
        assert "GPL" in str(exc_info.value) or "传染性" in str(exc_info.value)

    def test_gpl_license_with_confirmation_succeeds(self):
        from federation.registry import ExternalAgentRegistry
        from shared_models import LicenseType
        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="GPL Agent",
            provider="GPLProvider",
            license="GPL-3.0",
            confirm_license_risk=True,
        )
        assert agent is not None
        assert agent.license == LicenseType.GPL_3

    def test_mit_apache_no_confirmation_needed(self):
        from federation.registry import ExternalAgentRegistry
        from shared_models import LicenseType
        registry = ExternalAgentRegistry()
        mit_agent = registry.register_agent(
            display_name="MIT Agent",
            provider="MITProvider",
            license="MIT",
            confirm_license_risk=False,
        )
        assert mit_agent.license == LicenseType.MIT
        apache_agent = registry.register_agent(
            display_name="Apache Agent",
            provider="ApacheProvider",
            license="Apache-2.0",
            confirm_license_risk=False,
        )
        assert apache_agent.license == LicenseType.APACHE

    def test_license_field_saved_correctly(self):
        from federation.registry import ExternalAgentRegistry
        from shared_models import LicenseType
        registry = ExternalAgentRegistry()
        test_cases = [
            ("MIT Agent", "MITProvider", "MIT", LicenseType.MIT),
            ("Apache Agent", "ApacheProvider", "Apache-2.0", LicenseType.APACHE),
            ("Proprietary Agent", "PropProvider", "Proprietary", LicenseType.PROPRIETARY),
            ("GPL Agent", "GPLProvider", "GPL-2.0", LicenseType.GPL_2),
        ]
        for name, provider, lic, expected in test_cases:
            agent = registry.register_agent(
                display_name=name,
                provider=provider,
                license=lic,
                confirm_license_risk=True,
            )
            assert agent.license == expected
        stats = registry.stats()
        assert "by_license" in stats
        assert len(stats["by_license"]) >= 4


# ============================================================================
# 13. 审计摘要字段测试（来源：test_v11_1_fixes.py）
# ============================================================================

class TestAuditSummaryFields:
    """审计摘要字段测试"""

    def test_scan_returns_content_hash_and_length(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        import hashlib
        guard = PrivacyGuard(custom_keywords=[])
        content = "这是一段测试内容，用于验证哈希和长度。"
        result = guard.scan_content(content, SecurityClassification.PUBLIC)
        assert "content_hash" in result
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert result["content_hash"] == expected_hash
        assert "content_length" in result
        assert result["content_length"] == len(content.encode("utf-8"))

    def test_sanitize_returns_sanitized_preview(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        content = "我的手机号是13812345678，邮箱是test@example.com"
        result = guard.sanitize_content(content, SecurityClassification.INTERNAL)
        assert "sanitized_preview" in result
        assert isinstance(result["sanitized_preview"], str)
        assert len(result["sanitized_preview"]) > 0

    def test_audit_log_contains_pii_types_detected(self):
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        guard = PrivacyGuard(custom_keywords=[])
        content = "手机号13812345678，邮箱test@example.com"
        guard.scan_content(content, SecurityClassification.PUBLIC)
        logs = guard.get_audit_log(limit=5)
        assert len(logs) >= 1
        latest = logs[0]
        assert "pii_types_detected" in latest
        assert isinstance(latest["pii_types_detected"], list)
        assert "phone_cn" in latest["pii_types_detected"]
        assert "email" in latest["pii_types_detected"]


# ============================================================================
# 14. Orchestrator 联邦集成测试（来源：test_v11_federation.py）
# ============================================================================

class TestOrchestratorFederationIntegration:
    """Orchestrator 联邦调度集成测试"""

    @pytest.mark.asyncio
    async def test_federation_decide_capability(self):
        from orchestrator.agent import OrchestratorAgent
        orch = OrchestratorAgent()
        assert "federation.decide" in orch.capabilities

    @pytest.mark.asyncio
    async def test_federation_invoke_capability(self):
        from orchestrator.agent import OrchestratorAgent
        orch = OrchestratorAgent()
        assert "federation.invoke" in orch.capabilities

    @pytest.mark.asyncio
    async def test_federation_compare_capability(self):
        from orchestrator.agent import OrchestratorAgent
        orch = OrchestratorAgent()
        assert "federation.compare" in orch.capabilities

    @pytest.mark.asyncio
    async def test_handle_fed_decide(self):
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
        from orchestrator.agent import OrchestratorAgent
        from interfaces import AgentTask
        orch = OrchestratorAgent()
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
    async def test_fed_invoke_privacy_blocked(self):
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
        assert result.status == "success"
        assert result.output.get("success") is False


# ============================================================================
# 15. 端到端联邦调度测试（来源：test_v11_federation.py）
# ============================================================================

class TestEndToEndFederation:
    """端到端联邦调度集成测试"""

    @pytest.mark.asyncio
    async def test_full_federation_flow(self):
        from federation.registry import ExternalAgentRegistry
        from federation.scheduler import FederatedScheduler
        from federation.cost_controller import CostController
        from federation.privacy_guard import FederationPrivacyGuard
        from shared_models import (
            SecurityClassification,
            UserPreferenceMode,
        )
        registry = ExternalAgentRegistry()
        scheduler = FederatedScheduler(registry=registry)
        cost_ctrl = CostController(monthly_budget=5.0)
        privacy = FederationPrivacyGuard()
        gpt = registry.register_agent(
            display_name="GPT-4",
            provider="OpenAI",
        )
        claude = registry.register_agent(
            display_name="Claude",
            provider="Anthropic",
        )
        decision = scheduler.decide(
            task_type="general",
            security_level=SecurityClassification.PUBLIC,
            user_preference=UserPreferenceMode.QUALITY_FIRST,
            remaining_budget=cost_ctrl.remaining_budget(),
        )
        assert decision.selected_agent_id != ""
        if decision.use_external:
            prompt = "请用Python写一个快速排序算法"
            scan = privacy.scan(prompt, SecurityClassification.PUBLIC)
            assert scan.passed is True
            adapter = registry.get_adapter(decision.selected_agent_id)
            assert adapter is not None
            result = await adapter.invoke(prompt=prompt)
            assert result.get("success", True)
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
            assert cost_ctrl.get_budget().spent_this_month > 0


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
