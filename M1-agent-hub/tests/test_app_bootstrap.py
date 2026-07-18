"""
测试：YunxiApplication 应用启动器
"""

import pytest
import sys
from src.core.bootstrap import YunxiApplication


@pytest.mark.asyncio
async def test_build_app():
    app = YunxiApplication()
    v5 = await app.build()
    assert v5 is not None
    assert app.orchestrator is not None
    assert app.lifecycle is not None
    assert app.health is not None


@pytest.mark.asyncio
async def test_lifecycle_integration():
    app = YunxiApplication()
    await app.build()

    # 启动
    await app.lifecycle.startup()
    assert app.lifecycle.is_running() is True

    # 健康检查
    health = await app.health.overall_status()
    assert "status" in health

    # 关闭
    await app.shutdown()
    assert app.lifecycle.is_running() is False


@pytest.mark.asyncio
async def test_config_injection():
    app = YunxiApplication()
    await app.build()

    # 确认配置已被注入
    assert app.config.get("llm.model") == "gpt-4o-mini"
    assert app.config.get_int("vector_memory.dimension") == 128


@pytest.mark.asyncio
async def test_diagnostic():
    app = YunxiApplication()
    await app.build()
    diag = app.orchestrator.diagnose()
    assert "v5" in diag
    assert "v4" in diag
