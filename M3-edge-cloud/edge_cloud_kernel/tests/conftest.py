
pytest 配置 - 测试路径统一注入 (ARC-006 修复)
统一管理 sys.path 注入，避免每个测试文件重复 sys.path.insert。
如需新增路径依赖，请在此处添加，不要在单个测试文件中使用 sys.path.insert。
# 项目根目录（用于导入 shared 等公共包）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
# 模块源码目录（用于导入本模块源码）
_MODULE_SRC = Path(__file__).resolve().parents[2]
# 统一注入路径（模块源码优先，然后项目根目录）
for _p in (str(_MODULE_SRC), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

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
