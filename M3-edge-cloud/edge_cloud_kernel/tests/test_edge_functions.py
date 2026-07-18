"""边缘函数即服务 (Edge FaaS) 测试.

覆盖：
- 函数注册
- 函数版本管理
- 函数调用（同步/异步）
- 函数冷启动/热启动
- 函数执行沙箱
- 函数资源限制
"""

from __future__ import annotations

import asyncio

import pytest

from edge_cloud_kernel.services.edge_functions import (
    EdgeFunction,
    EdgeFunctionSandbox,
    EdgeFunctionService,
    FunctionExecutionResult,
    FunctionRuntime,
    FunctionSandboxConfig,
    FunctionStatus,
    FunctionVersion,
    InvocationMode,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def function_service():
    """创建 EdgeFunctionService 测试实例."""
    service = EdgeFunctionService()
    yield service


@pytest.fixture
def simple_function():
    """简单函数代码."""
    def handler(event, context):
        return {"result": event.get("value", 0) * 2}
    return handler


@pytest.fixture
def async_function():
    """异步函数代码."""
    async def handler(event, context):
        await asyncio.sleep(0.01)
        return {"result": event.get("value", 0) + 10}
    return handler


@pytest.fixture
def error_function():
    """会抛出异常的函数."""
    def handler(event, context):
        raise ValueError("test error")
    return handler


# ============================================================
# 枚举值测试
# ============================================================

class TestEnums:
    """枚举值测试."""

    def test_function_status_values(self):
        """测试函数状态枚举值."""
        assert FunctionStatus.ACTIVE == "active"
        assert FunctionStatus.DEPRECATED == "deprecated"
        assert FunctionStatus.DISABLED == "disabled"
        assert FunctionStatus.ERROR == "error"

    def test_function_runtime_values(self):
        """测试运行时枚举值."""
        assert FunctionRuntime.PYTHON == "python"
        assert FunctionRuntime.JAVASCRIPT == "javascript"
        assert FunctionRuntime.SHELL == "shell"
        assert FunctionRuntime.CUSTOM == "custom"

    def test_invocation_mode_values(self):
        """测试调用模式枚举值."""
        assert InvocationMode.SYNC == "sync"
        assert InvocationMode.ASYNC == "async"


# ============================================================
# 函数注册测试
# ============================================================

class TestFunctionRegistration:
    """函数注册测试."""

    def test_register_function(self, function_service, simple_function):
        """测试注册函数."""
        func_id = function_service.register_function(
            name="double",
            code=simple_function,
            description="Double the value",
        )
        assert func_id is not None
        assert isinstance(func_id, str)

    def test_register_function_returns_id(self, function_service, simple_function):
        """测试注册函数返回有效 ID."""
        func_id = function_service.register_function(
            name="test-func",
            code=simple_function,
        )
        assert len(func_id) > 0

    def test_get_function(self, function_service, simple_function):
        """测试获取函数."""
        func_id = function_service.register_function(
            name="get-test",
            code=simple_function,
        )
        func = function_service.get_function(func_id)
        assert func is not None
        assert isinstance(func, EdgeFunction)
        assert func.name == "get-test"

    def test_get_nonexistent_function(self, function_service):
        """测试获取不存在的函数."""
        func = function_service.get_function("nonexistent-id")
        assert func is None

    def test_get_function_by_name(self, function_service, simple_function):
        """测试按名称获取函数."""
        function_service.register_function(
            name="by-name",
            code=simple_function,
        )
        func = function_service.get_function_by_name("by-name")
        assert func is not None
        assert func.name == "by-name"

    def test_list_functions(self, function_service, simple_function):
        """测试列出函数."""
        for i in range(3):
            function_service.register_function(
                name=f"list-func-{i}",
                code=simple_function,
            )
        funcs = function_service.list_functions()
        assert len(funcs) >= 3
        assert all(isinstance(f, EdgeFunction) for f in funcs)

    def test_register_with_tags(self, function_service, simple_function):
        """测试带标签注册函数."""
        func_id = function_service.register_function(
            name="tagged-func",
            code=simple_function,
            tags=["math", "utility"],
        )
        func = function_service.get_function(func_id)
        assert "math" in func.tags
        assert "utility" in func.tags

    def test_register_with_timeout(self, function_service, simple_function):
        """测试注册带超时的函数."""
        func_id = function_service.register_function(
            name="timeout-func",
            code=simple_function,
            timeout_seconds=60,
        )
        func = function_service.get_function(func_id)
        assert func.timeout_seconds == 60

    def test_register_with_memory_limit(self, function_service, simple_function):
        """测试注册带内存限制的函数."""
        func_id = function_service.register_function(
            name="mem-limit-func",
            code=simple_function,
            memory_limit_mb=512,
        )
        func = function_service.get_function(func_id)
        assert func.memory_limit_mb == 512


# ============================================================
# 函数版本管理测试
# ============================================================

class TestFunctionVersioning:
    """函数版本管理测试."""

    def test_add_version(self, function_service, simple_function):
        """测试添加函数版本."""
        func_id = function_service.register_function(
            name="versioned",
            code=simple_function,
            version="1.0.0",
        )
        new_id = function_service.add_version(
            function_id=func_id,
            version="2.0.0",
            code=simple_function,
            description="v2",
        )
        assert new_id == func_id  # 同一个函数

    def test_list_versions(self, function_service, simple_function):
        """测试列出版本."""
        func_id = function_service.register_function(
            name="multi-version",
            code=simple_function,
            version="1.0.0",
        )
        function_service.add_version(
            function_id=func_id,
            version="2.0.0",
            code=simple_function,
        )
        versions = function_service.list_versions(func_id)
        assert len(versions) >= 2
        assert all(isinstance(v, FunctionVersion) for v in versions)

    def test_set_default_version(self, function_service, simple_function):
        """测试设置默认版本."""
        func_id = function_service.register_function(
            name="default-version",
            code=simple_function,
            version="1.0.0",
        )
        function_service.add_version(
            function_id=func_id,
            version="2.0.0",
            code=simple_function,
        )
        result = function_service.set_default_version(func_id, "2.0.0")
        assert result is True
        func = function_service.get_function(func_id)
        assert func.default_version == "2.0.0"

    def test_version_has_invocation_count(self, function_service, simple_function):
        """测试版本有调用计数."""
        func_id = function_service.register_function(
            name="invocation-count",
            code=simple_function,
            version="1.0.0",
        )
        versions = function_service.list_versions(func_id)
        assert versions[0].invocation_count == 0


# ============================================================
# 函数调用测试
# ============================================================

class TestFunctionInvocation:
    """函数调用测试."""

    def test_invoke_sync(self, function_service, simple_function):
        """测试同步调用函数."""
        func_id = function_service.register_function(
            name="sync-test",
            code=simple_function,
        )
        result = asyncio.run(function_service.invoke(
            function_id=func_id,
            event={"value": 21},
            mode=InvocationMode.SYNC,
        ))
        assert isinstance(result, FunctionExecutionResult)
        assert result.success is True
        assert result.result == {"result": 42}

    def test_invoke_async(self, function_service, simple_function):
        """测试异步调用函数."""
        func_id = function_service.register_function(
            name="async-test",
            code=simple_function,
        )
        result = asyncio.run(function_service.invoke(
            function_id=func_id,
            event={"value": 5},
            mode=InvocationMode.ASYNC,
        ))
        # 异步调用应立即返回
        assert result is not None

    def test_invoke_async_function(self, function_service, async_function):
        """测试调用异步函数."""
        func_id = function_service.register_function(
            name="async-func-test",
            code=async_function,
        )
        result = asyncio.run(function_service.invoke(
            function_id=func_id,
            event={"value": 32},
            mode=InvocationMode.SYNC,
        ))
        assert isinstance(result, FunctionExecutionResult)
        assert result.success is True
        assert result.result == {"result": 42}

    def test_invoke_error_function(self, function_service, error_function):
        """测试调用出错的函数."""
        func_id = function_service.register_function(
            name="error-test",
            code=error_function,
        )
        result = asyncio.run(function_service.invoke(
            function_id=func_id,
            event={},
            mode=InvocationMode.SYNC,
        ))
        assert isinstance(result, FunctionExecutionResult)
        assert result.success is False
        assert "test error" in result.error

    def test_invoke_nonexistent_function(self, function_service):
        """测试调用不存在的函数."""
        with pytest.raises(ValueError, match="not found"):
            asyncio.run(function_service.invoke(
                function_id="no-such-function",
                event={},
                mode=InvocationMode.SYNC,
            ))

    def test_invoke_with_specific_version(self, function_service, simple_function):
        """测试调用指定版本的函数."""
        func_id = function_service.register_function(
            name="version-invoke",
            code=simple_function,
            version="1.0.0",
        )
        result = asyncio.run(function_service.invoke(
            function_id=func_id,
            event={"value": 10},
            version="1.0.0",
            mode=InvocationMode.SYNC,
        ))
        assert result.success is True

    def test_invocation_has_duration(self, function_service, simple_function):
        """测试调用结果包含执行时长."""
        func_id = function_service.register_function(
            name="duration-test",
            code=simple_function,
        )
        result = asyncio.run(function_service.invoke(
            function_id=func_id,
            event={"value": 1},
            mode=InvocationMode.SYNC,
        ))
        assert result.duration_ms >= 0

    def test_invocation_has_id(self, function_service, simple_function):
        """测试调用结果有调用 ID."""
        func_id = function_service.register_function(
            name="invocation-id-test",
            code=simple_function,
        )
        result = asyncio.run(function_service.invoke(
            function_id=func_id,
            event={"value": 1},
            mode=InvocationMode.SYNC,
        ))
        assert result.invocation_id != ""
        assert result.function_id == func_id


# ============================================================
# 函数禁用/启用测试
# ============================================================

class TestFunctionEnableDisable:
    """函数禁用/启用测试."""

    def test_disable_function(self, function_service, simple_function):
        """测试禁用函数."""
        func_id = function_service.register_function(
            name="disable-test",
            code=simple_function,
        )
        result = function_service.disable_function(func_id)
        assert result is True
        func = function_service.get_function(func_id)
        assert func.status == FunctionStatus.DISABLED

    def test_enable_function(self, function_service, simple_function):
        """测试启用函数."""
        func_id = function_service.register_function(
            name="enable-test",
            code=simple_function,
        )
        function_service.disable_function(func_id)
        result = function_service.enable_function(func_id)
        assert result is True
        func = function_service.get_function(func_id)
        assert func.status == FunctionStatus.ACTIVE

    def test_delete_function(self, function_service, simple_function):
        """测试删除函数."""
        func_id = function_service.register_function(
            name="delete-test",
            code=simple_function,
        )
        result = function_service.delete_function(func_id)
        assert result is True
        assert function_service.get_function(func_id) is None

    def test_delete_nonexistent_function(self, function_service):
        """测试删除不存在的函数."""
        result = function_service.delete_function("nonexistent")
        assert result is False


# ============================================================
# 沙箱配置测试
# ============================================================

class TestSandboxConfig:
    """沙箱配置测试."""

    def test_default_sandbox_config(self):
        """测试默认沙箱配置."""
        config = FunctionSandboxConfig()
        assert config.allow_network is False
        assert config.allow_file_system is False
        assert config.timeout_seconds == 30
        assert config.max_memory_mb == 256

    def test_custom_sandbox_config(self):
        """测试自定义沙箱配置."""
        config = FunctionSandboxConfig(
            allow_network=True,
            timeout_seconds=60,
            max_memory_mb=512,
        )
        assert config.allow_network is True
        assert config.timeout_seconds == 60
        assert config.max_memory_mb == 512

    def test_sandbox_init(self):
        """测试沙箱初始化."""
        sandbox = EdgeFunctionSandbox()
        assert sandbox is not None

    def test_sandbox_with_config(self):
        """测试带配置的沙箱初始化."""
        config = FunctionSandboxConfig(timeout_seconds=10)
        sandbox = EdgeFunctionSandbox(config=config)
        assert sandbox is not None


# ============================================================
# 热启动池测试
# ============================================================

class TestWarmPool:
    """热启动池测试."""

    def test_clear_warm_pool(self, function_service, simple_function):
        """测试清空热启动池."""
        function_service.register_function(
            name="warm-pool-test",
            code=simple_function,
            warm_pool_size=2,
        )
        # 先调用一次，让函数进入热启动池
        func_id = function_service.get_function_by_name("warm-pool-test").function_id
        asyncio.run(function_service.invoke(
            function_id=func_id, event={}, mode=InvocationMode.SYNC
        ))
        # 清空热启动池
        count = function_service._sandbox.clear_warm_pool()
        assert count >= 0


# ============================================================
# 指标与历史测试
# ============================================================

class TestMetricsAndHistory:
    """指标与历史测试."""

    def test_get_metrics(self, function_service, simple_function):
        """测试获取指标."""
        function_service.register_function(
            name="metrics-test",
            code=simple_function,
        )
        metrics = function_service.get_metrics()
        assert isinstance(metrics, dict)

    def test_invocation_history(self, function_service, simple_function):
        """测试调用历史."""
        func_id = function_service.register_function(
            name="history-test",
            code=simple_function,
        )
        asyncio.run(function_service.invoke(
            function_id=func_id, event={"v": 1}, mode=InvocationMode.SYNC
        ))
        history = function_service.get_invocation_history(func_id)
        assert len(history) >= 1
        assert all(isinstance(r, FunctionExecutionResult) for r in history)


# ============================================================
# 数据结构测试
# ============================================================

class TestDataStructures:
    """数据结构测试."""

    def test_edge_function_defaults(self):
        """测试 EdgeFunction 默认值."""
        func = EdgeFunction(function_id="test", name="test-func")
        assert func.function_id == "test"
        assert func.name == "test-func"
        assert func.status == FunctionStatus.ACTIVE
        assert func.timeout_seconds == 30
        assert func.memory_limit_mb == 256

    def test_function_version_defaults(self):
        """测试 FunctionVersion 默认值."""
        version = FunctionVersion(version="1.0.0")
        assert version.version == "1.0.0"
        assert version.runtime == FunctionRuntime.PYTHON
        assert version.invocation_count == 0
        assert version.is_default is False

    def test_execution_result_defaults(self):
        """测试 FunctionExecutionResult 默认值."""
        result = FunctionExecutionResult(
            function_id="f1",
            version="1.0.0",
            invocation_id="inv-1",
        )
        assert result.success is False
        assert result.result is None
        assert result.duration_ms == 0.0
        assert result.cold_start is False
