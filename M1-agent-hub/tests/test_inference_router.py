"""
测试：V10.0-R03 InferenceRouter

验证M1保留的"本地/云端路由决策"逻辑。
"""

import pytest
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, "/workspace/agent_cluster")

from llm_provider import InferenceRouter


@pytest.fixture
def router():
    return InferenceRouter(
        default_local_model="mock-model",
        default_cloud_model="gpt-4o",
    )


def test_select_provider_local_when_no_network(router):
    decision = router.select_provider(network_available=False)
    assert decision["provider_type"] == "local"
    assert decision["model"] == "mock-model"


def test_select_provider_local_when_low_budget(router):
    decision = router.select_provider(budget_remaining=0.05)
    assert decision["provider_type"] == "local"


def test_select_provider_local_for_low_complexity(router):
    decision = router.select_provider(task_complexity="low")
    assert decision["provider_type"] == "local"


def test_select_provider_cloud_for_high_complexity(router):
    decision = router.select_provider(task_complexity="high", budget_remaining=0.5)
    assert decision["provider_type"] == "cloud"
    assert decision["model"] == "gpt-4o"


def test_select_provider_default_medium(router):
    decision = router.select_provider()
    assert decision["provider_type"] == "cloud"


@pytest.mark.asyncio
async def test_route_inference_with_interface():
    mock_inf = MagicMock()
    mock_inf.chat = AsyncMock(return_value={"content": "hello from m3"})

    router = InferenceRouter(inference_interface=mock_inf)
    result = await router.route_inference([{"role": "user", "content": "hi"}])

    assert result["content"] == "hello from m3"
    mock_inf.chat.assert_called_once()


def test_stats(router):
    stats = router.stats()
    assert stats["default_local"] == "mock-model"
    assert stats["default_cloud"] == "gpt-4o"
    assert stats["inference_interface_connected"] is False
