"""pytest 共享 fixtures.

为所有测试提供通用的 fixture 配置。
"""

from __future__ import annotations

from typing import Any

import pytest

from edge_cloud_kernel.gateway.circuit_breaker import CircuitBreaker


# ============================================================
# 核心组件 fixtures
# ============================================================


@pytest.fixture
def circuit_breaker() -> CircuitBreaker:
    """创建 CircuitBreaker 实例.

    Returns:
        CircuitBreaker 实例.
    """
    return CircuitBreaker(
        name="test_circuit",
        volume_threshold=5,
        error_threshold_pct=50.0,
        reset_timeout_s=2.0,
    )


# ============================================================
# 测试数据目录 fixture
# ============================================================


@pytest.fixture
def tmp_data_dir(tmp_path: Any) -> Any:
    """创建临时数据目录.

    Args:
        tmp_path: pytest 临时目录.

    Returns:
        临时数据目录 Path.
    """
    (tmp_path / "config").mkdir()
    (tmp_path / "cache").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "audit").mkdir()
    (tmp_path / "sessions").mkdir()
    (tmp_path / "models").mkdir()
    return tmp_path
