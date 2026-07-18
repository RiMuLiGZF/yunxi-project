"""边缘函数即服务 (Edge FaaS).

提供边缘函数的注册、版本管理、执行和资源限制能力。
支持冷启动/热启动、执行沙箱、资源限制等 FaaS 特性。

可插拔设计：不影响现有功能，按需启用。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------


class FunctionStatus(str, Enum):
    """函数状态枚举.

    Attributes:
        ACTIVE: 活跃可用.
        DEPRECATED: 已弃用.
        DISABLED: 已禁用.
        ERROR: 错误状态.
    """

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"
    ERROR = "error"


class FunctionRuntime(str, Enum):
    """函数运行时枚举.

    Attributes:
        PYTHON: Python 函数.
        JAVASCRIPT: JavaScript 函数.
        SHELL: Shell 脚本.
        CUSTOM: 自定义运行时.
    """

    PYTHON = "python"
    JAVASCRIPT = "javascript"
    SHELL = "shell"
    CUSTOM = "custom"


class InvocationMode(str, Enum):
    """调用模式枚举.

    Attributes:
        SYNC: 同步调用（等待结果）.
        ASYNC: 异步调用（不等待结果）.
    """

    SYNC = "sync"
    ASYNC = "async"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class FunctionVersion:
    """函数版本.

    Attributes:
        version: 版本号（语义化版本）.
        code: 函数代码或可调用对象.
        runtime: 运行时类型.
        handler: 入口函数名.
        description: 版本描述.
        created_at: 创建时间.
        is_default: 是否为默认版本.
        invocation_count: 调用次数.
        last_invoked_at: 最后调用时间.
    """

    version: str
    code: Any = None  # 可调用对象或代码字符串
    runtime: FunctionRuntime = FunctionRuntime.PYTHON
    handler: str = "handler"
    description: str = ""
    created_at: float = field(default_factory=time.time)
    is_default: bool = False
    invocation_count: int = 0
    last_invoked_at: float = 0.0


@dataclass
class EdgeFunction:
    """边缘函数定义.

    Attributes:
        function_id: 函数唯一标识.
        name: 函数名称.
        description: 函数描述.
        tags: 标签列表.
        versions: 版本列表.
        default_version: 默认版本号.
        timeout_seconds: 超时时间（秒）.
        memory_limit_mb: 内存限制（MB）.
        cpu_limit: CPU 限制（核数，0 表示不限制）.
        max_concurrent_invocations: 最大并发调用数.
        environment: 环境变量.
        created_at: 创建时间.
        updated_at: 最后更新时间.
        status: 函数状态.
        warm_pool_size: 热启动池大小.
    """

    function_id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    versions: dict[str, FunctionVersion] = field(default_factory=dict)
    default_version: str = "latest"
    timeout_seconds: int = 30
    memory_limit_mb: int = 256
    cpu_limit: float = 0.0
    max_concurrent_invocations: int = 10
    environment: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: FunctionStatus = FunctionStatus.ACTIVE
    warm_pool_size: int = 1


@dataclass
class FunctionExecutionResult:
    """函数执行结果.

    Attributes:
        function_id: 函数 ID.
        version: 执行的版本.
        invocation_id: 调用 ID.
        success: 是否成功.
        result: 返回结果.
        error: 错误信息.
        start_time: 开始时间.
        end_time: 结束时间.
        duration_ms: 执行时长（毫秒）.
        cold_start: 是否冷启动.
        memory_used_mb: 内存使用（MB）.
    """

    function_id: str
    version: str
    invocation_id: str
    success: bool = False
    result: Any = None
    error: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    cold_start: bool = False
    memory_used_mb: float = 0.0


@dataclass
class FunctionSandboxConfig:
    """函数沙箱配置.

    Attributes:
        allow_network: 是否允许网络访问.
        allow_file_system: 是否允许文件系统访问.
        allowed_modules: 允许导入的模块列表.
        max_memory_mb: 最大内存（MB）.
        timeout_seconds: 超时时间（秒）.
        max_cpu_percent: 最大 CPU 使用率.
    """

    allow_network: bool = False
    allow_file_system: bool = False
    allowed_modules: list[str] = field(default_factory=list)
    max_memory_mb: int = 256
    timeout_seconds: int = 30
    max_cpu_percent: float = 50.0


# ---------------------------------------------------------------------------
# 函数执行沙箱
# ---------------------------------------------------------------------------


class EdgeFunctionSandbox:
    """边缘函数执行沙箱.

    提供受限的执行环境，确保函数执行不会影响系统其他部分。
    当前实现为轻量级沙箱（基于超时和异常捕获），
    生产环境可扩展为基于 subprocess / Docker 的隔离。

    Attributes:
        _config: 沙箱配置.
        _warm_instances: 热启动实例缓存 {function_id: [callable, ...]}.
    """

    def __init__(
        self,
        config: FunctionSandboxConfig | None = None,
    ) -> None:
        """初始化函数沙箱.

        Args:
            config: 沙箱配置，None 使用默认配置.
        """
        self._config = config or FunctionSandboxConfig()
        self._warm_instances: dict[str, list[Callable[..., Any]]] = {}

        logger.info(
            "edge_function_sandbox.init",
            max_memory=self._config.max_memory_mb,
            timeout=self._config.timeout_seconds,
            allow_network=self._config.allow_network,
        )

    async def execute(
        self,
        function: EdgeFunction,
        version: FunctionVersion,
        event: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> FunctionExecutionResult:
        """在沙箱中执行函数.

        Args:
            function: 函数定义.
            version: 函数版本.
            event: 事件数据（函数输入）.
            context: 上下文信息.

        Returns:
            执行结果.
        """
        invocation_id = str(uuid.uuid4())
        result = FunctionExecutionResult(
            function_id=function.function_id,
            version=version.version,
            invocation_id=invocation_id,
            start_time=time.time(),
        )

        # 获取可调用对象（冷启动或热启动）
        handler, is_cold = await self._get_handler(function, version)
        result.cold_start = is_cold

        if handler is None:
            result.success = False
            result.error = "Function handler not available"
            result.end_time = time.time()
            result.duration_ms = (result.end_time - result.start_time) * 1000
            return result

        try:
            # 执行函数（带超时控制）
            exec_result = await asyncio.wait_for(
                self._invoke_handler(handler, event, context or {}),
                timeout=function.timeout_seconds,
            )
            result.result = exec_result
            result.success = True

        except asyncio.TimeoutError:
            result.success = False
            result.error = f"Function timed out after {function.timeout_seconds}s"
            logger.warning(
                "edge_function_sandbox.timeout",
                function_id=function.function_id,
                version=version.version,
                timeout=function.timeout_seconds,
            )

        except Exception as e:
            result.success = False
            result.error = str(e)
            logger.error(
                "edge_function_sandbox.execution_error",
                function_id=function.function_id,
                version=version.version,
                error=str(e),
            )

        result.end_time = time.time()
        result.duration_ms = (result.end_time - result.start_time) * 1000

        # 更新版本统计
        version.invocation_count += 1
        version.last_invoked_at = result.end_time

        return result

    async def _get_handler(
        self,
        function: EdgeFunction,
        version: FunctionVersion,
    ) -> tuple[Callable[..., Any] | None, bool]:
        """获取函数处理器（热启动优先）.

        Returns:
            (handler, is_cold_start) 元组.
        """
        cache_key = f"{function.function_id}:{version.version}"

        # 检查热启动池
        if cache_key in self._warm_instances and self._warm_instances[cache_key]:
            handler = self._warm_instances[cache_key].pop(0)
            return handler, False

        # 冷启动：创建新实例
        handler = self._create_handler(version)
        if handler is not None:
            # 预热：放入热启动池（异步补充）
            asyncio.create_task(self._prewarm(function, version))
            return handler, True

        return None, True

    def _create_handler(self, version: FunctionVersion) -> Callable[..., Any] | None:
        """创建函数处理器实例.

        Args:
            version: 函数版本.

        Returns:
            可调用对象，失败返回 None.
        """
        if version.runtime == FunctionRuntime.PYTHON:
            # 如果 code 已经是可调用对象，直接使用
            if callable(version.code):
                return version.code

            # 如果是字符串代码，动态编译
            if isinstance(version.code, str):
                try:
                    namespace: dict[str, Any] = {}
                    exec(version.code, namespace)
                    handler = namespace.get(version.handler)
                    if callable(handler):
                        return handler
                except Exception as e:
                    logger.error(
                        "edge_function_sandbox.compile_error",
                        error=str(e),
                    )
                    return None

        # 其他运行时暂不支持代码字符串执行
        return None

    async def _invoke_handler(
        self,
        handler: Callable[..., Any],
        event: dict[str, Any],
        context: dict[str, Any],
    ) -> Any:
        """调用函数处理器.

        支持同步和异步函数。
        """
        result = handler(event, context)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    async def _prewarm(
        self,
        function: EdgeFunction,
        version: FunctionVersion,
    ) -> None:
        """预热函数实例（补充热启动池）."""
        cache_key = f"{function.function_id}:{version.version}"

        if cache_key not in self._warm_instances:
            self._warm_instances[cache_key] = []

        current_pool = len(self._warm_instances[cache_key])
        needed = max(0, function.warm_pool_size - current_pool - 1)

        for _ in range(needed):
            handler = self._create_handler(version)
            if handler:
                self._warm_instances[cache_key].append(handler)

        logger.debug(
            "edge_function_sandbox.prewarmed",
            function_id=function.function_id,
            version=version.version,
            pool_size=len(self._warm_instances[cache_key]),
        )

    def clear_warm_pool(self, function_id: str | None = None) -> int:
        """清空热启动池.

        Args:
            function_id: 指定函数，None 清空全部.

        Returns:
            清理的实例数.
        """
        count = 0
        if function_id:
            for key in list(self._warm_instances.keys()):
                if key.startswith(f"{function_id}:"):
                    count += len(self._warm_instances[key])
                    del self._warm_instances[key]
        else:
            for instances in self._warm_instances.values():
                count += len(instances)
            self._warm_instances.clear()

        logger.info("edge_function_sandbox.warm_pool_cleared", count=count)
        return count


# ---------------------------------------------------------------------------
# EdgeFunctionService
# ---------------------------------------------------------------------------


class EdgeFunctionService:
    """边缘函数服务 (Edge FaaS).

    提供边缘函数的完整生命周期管理：
    - 函数注册与注销
    - 版本管理（多版本并存、灰度发布）
    - 函数调用（同步/异步）
    - 执行沙箱
    - 资源限制
    - 热启动/冷启动

    Attributes:
        _functions: 函数字典 {function_id: EdgeFunction}.
        _sandbox: 执行沙箱.
        _concurrent_count: 当前并发调用数 {function_id: count}.
        _invocation_history: 调用历史记录.
    """

    def __init__(
        self,
        sandbox_config: FunctionSandboxConfig | None = None,
    ) -> None:
        """初始化边缘函数服务.

        Args:
            sandbox_config: 沙箱配置.
        """
        self._functions: dict[str, EdgeFunction] = {}
        self._sandbox = EdgeFunctionSandbox(sandbox_config)
        self._concurrent_count: dict[str, int] = {}
        self._invocation_history: list[FunctionExecutionResult] = []
        self._max_history = 1000

        logger.info("edge_function_service.init")

    # ------------------------------------------------------------------
    # 函数注册与管理
    # ------------------------------------------------------------------

    def register_function(
        self,
        name: str,
        code: Any,
        runtime: FunctionRuntime = FunctionRuntime.PYTHON,
        handler: str = "handler",
        description: str = "",
        version: str = "1.0.0",
        tags: list[str] | None = None,
        timeout_seconds: int = 30,
        memory_limit_mb: int = 256,
        environment: dict[str, str] | None = None,
        warm_pool_size: int = 1,
    ) -> str:
        """注册边缘函数.

        如果函数名已存在，则新增版本。

        Args:
            name: 函数名称.
            code: 函数代码（可调用对象或代码字符串）.
            runtime: 运行时类型.
            handler: 入口函数名.
            description: 函数描述.
            version: 版本号.
            tags: 标签列表.
            timeout_seconds: 超时时间.
            memory_limit_mb: 内存限制（MB）.
            environment: 环境变量.
            warm_pool_size: 热启动池大小.

        Returns:
            函数 ID.
        """
        # 检查同名函数
        existing_id = None
        for fid, func in self._functions.items():
            if func.name == name:
                existing_id = fid
                break

        if existing_id:
            # 已有函数，添加新版本
            return self.add_version(
                function_id=existing_id,
                version=version,
                code=code,
                runtime=runtime,
                handler=handler,
                description=description,
                set_as_default=False,
            )

        # 新函数
        function_id = str(uuid.uuid4())
        func_version = FunctionVersion(
            version=version,
            code=code,
            runtime=runtime,
            handler=handler,
            description=description,
            is_default=True,
        )

        function = EdgeFunction(
            function_id=function_id,
            name=name,
            description=description,
            tags=tags or [],
            versions={version: func_version},
            default_version=version,
            timeout_seconds=timeout_seconds,
            memory_limit_mb=memory_limit_mb,
            environment=environment or {},
            warm_pool_size=warm_pool_size,
        )

        self._functions[function_id] = function
        self._concurrent_count[function_id] = 0

        logger.info(
            "edge_function_service.registered",
            function_id=function_id,
            name=name,
            version=version,
            runtime=runtime.value,
        )
        return function_id

    def add_version(
        self,
        function_id: str,
        version: str,
        code: Any,
        runtime: FunctionRuntime = FunctionRuntime.PYTHON,
        handler: str = "handler",
        description: str = "",
        set_as_default: bool = False,
    ) -> str:
        """添加函数版本.

        Args:
            function_id: 函数 ID.
            version: 版本号.
            code: 函数代码.
            runtime: 运行时.
            handler: 入口函数.
            description: 版本描述.
            set_as_default: 是否设为默认版本.

        Returns:
            函数 ID.

        Raises:
            ValueError: 函数不存在.
        """
        func = self._functions.get(function_id)
        if not func:
            raise ValueError(f"Function '{function_id}' not found")

        func_version = FunctionVersion(
            version=version,
            code=code,
            runtime=runtime,
            handler=handler,
            description=description,
            is_default=set_as_default,
        )

        func.versions[version] = func_version
        func.updated_at = time.time()

        if set_as_default:
            func.default_version = version
            # 取消其他版本的默认标记
            for v in func.versions.values():
                if v.version != version:
                    v.is_default = False

        logger.info(
            "edge_function_service.version_added",
            function_id=function_id,
            version=version,
            set_as_default=set_as_default,
        )
        return function_id

    def get_function(self, function_id: str) -> EdgeFunction | None:
        """获取函数定义.

        Args:
            function_id: 函数 ID.

        Returns:
            函数对象，不存在返回 None.
        """
        return self._functions.get(function_id)

    def get_function_by_name(self, name: str) -> EdgeFunction | None:
        """按名称获取函数.

        Args:
            name: 函数名称.

        Returns:
            函数对象，不存在返回 None.
        """
        for func in self._functions.values():
            if func.name == name:
                return func
        return None

    def list_functions(
        self,
        tag: str | None = None,
        status: FunctionStatus | None = None,
        limit: int = 100,
    ) -> list[EdgeFunction]:
        """列出函数.

        Args:
            tag: 按标签过滤.
            status: 按状态过滤.
            limit: 最大返回数.

        Returns:
            函数列表.
        """
        functions = list(self._functions.values())

        if tag:
            functions = [f for f in functions if tag in f.tags]

        if status:
            functions = [f for f in functions if f.status == status]

        functions.sort(key=lambda f: f.created_at, reverse=True)
        return functions[:limit]

    def delete_function(self, function_id: str) -> bool:
        """删除函数.

        Args:
            function_id: 函数 ID.

        Returns:
            是否成功删除.
        """
        if function_id not in self._functions:
            return False

        del self._functions[function_id]
        self._concurrent_count.pop(function_id, None)
        self._sandbox.clear_warm_pool(function_id)

        logger.info("edge_function_service.deleted", function_id=function_id)
        return True

    def disable_function(self, function_id: str) -> bool:
        """禁用函数.

        Args:
            function_id: 函数 ID.

        Returns:
            是否成功.
        """
        func = self._functions.get(function_id)
        if not func:
            return False

        func.status = FunctionStatus.DISABLED
        func.updated_at = time.time()
        logger.info("edge_function_service.disabled", function_id=function_id)
        return True

    def enable_function(self, function_id: str) -> bool:
        """启用函数.

        Args:
            function_id: 函数 ID.

        Returns:
            是否成功.
        """
        func = self._functions.get(function_id)
        if not func:
            return False

        func.status = FunctionStatus.ACTIVE
        func.updated_at = time.time()
        logger.info("edge_function_service.enabled", function_id=function_id)
        return True

    # ------------------------------------------------------------------
    # 版本管理
    # ------------------------------------------------------------------

    def list_versions(self, function_id: str) -> list[FunctionVersion]:
        """列出函数的所有版本.

        Args:
            function_id: 函数 ID.

        Returns:
            版本列表.
        """
        func = self._functions.get(function_id)
        if not func:
            return []
        return sorted(
            list(func.versions.values()),
            key=lambda v: v.created_at,
            reverse=True,
        )

    def set_default_version(self, function_id: str, version: str) -> bool:
        """设置默认版本.

        Args:
            function_id: 函数 ID.
            version: 版本号.

        Returns:
            是否成功.
        """
        func = self._functions.get(function_id)
        if not func or version not in func.versions:
            return False

        for v in func.versions.values():
            v.is_default = False
        func.versions[version].is_default = True
        func.default_version = version
        func.updated_at = time.time()

        logger.info(
            "edge_function_service.default_version_set",
            function_id=function_id,
            version=version,
        )
        return True

    # ------------------------------------------------------------------
    # 函数调用
    # ------------------------------------------------------------------

    async def invoke(
        self,
        function_id: str,
        event: dict[str, Any],
        version: str | None = None,
        context: dict[str, Any] | None = None,
        mode: InvocationMode = InvocationMode.SYNC,
    ) -> FunctionExecutionResult:
        """调用边缘函数.

        Args:
            function_id: 函数 ID.
            event: 事件数据.
            version: 版本号，None 使用默认版本.
            context: 上下文信息.
            mode: 调用模式（同步/异步）.

        Returns:
            执行结果（异步模式返回的是已提交的结果占位）.

        Raises:
            ValueError: 函数不存在或已禁用.
        """
        func = self._functions.get(function_id)
        if not func:
            raise ValueError(f"Function '{function_id}' not found")

        if func.status != FunctionStatus.ACTIVE:
            raise ValueError(
                f"Function '{function_id}' is not active (status: {func.status.value})"
            )

        # 检查并发限制
        current = self._concurrent_count.get(function_id, 0)
        if current >= func.max_concurrent_invocations:
            invocation_id = str(uuid.uuid4())
            return FunctionExecutionResult(
                function_id=function_id,
                version=version or func.default_version,
                invocation_id=invocation_id,
                success=False,
                error="Max concurrent invocations exceeded",
                start_time=time.time(),
                end_time=time.time(),
                duration_ms=0.0,
            )

        # 获取版本
        target_version = version or func.default_version
        func_version = func.versions.get(target_version)
        if not func_version:
            raise ValueError(
                f"Version '{target_version}' not found for function '{function_id}'"
            )

        # 构建上下文
        exec_context = {
            "function_id": function_id,
            "function_name": func.name,
            "version": target_version,
            "memory_limit_mb": func.memory_limit_mb,
            "timeout_seconds": func.timeout_seconds,
            "environment": func.environment,
        }
        if context:
            exec_context.update(context)

        if mode == InvocationMode.ASYNC:
            # 异步调用：立即返回，后台执行
            invocation_id = str(uuid.uuid4())
            asyncio.create_task(self._invoke_async(
                func, func_version, event, exec_context, invocation_id
            ))
            return FunctionExecutionResult(
                function_id=function_id,
                version=target_version,
                invocation_id=invocation_id,
                success=True,
                result={"status": "queued", "invocation_id": invocation_id},
                start_time=time.time(),
                end_time=time.time(),
                duration_ms=0.0,
            )

        # 同步调用
        self._concurrent_count[function_id] = current + 1
        try:
            result = await self._sandbox.execute(
                function=func,
                version=func_version,
                event=event,
                context=exec_context,
            )
            self._record_invocation(result)
            return result
        finally:
            self._concurrent_count[function_id] = max(
                0, self._concurrent_count[function_id] - 1
            )

    async def _invoke_async(
        self,
        func: EdgeFunction,
        version: FunctionVersion,
        event: dict[str, Any],
        context: dict[str, Any],
        invocation_id: str,
    ) -> None:
        """异步调用执行."""
        current = self._concurrent_count.get(func.function_id, 0)
        if current >= func.max_concurrent_invocations:
            # 并发超限，稍后重试
            await asyncio.sleep(1.0)
            current = self._concurrent_count.get(func.function_id, 0)
            if current >= func.max_concurrent_invocations:
                logger.warning(
                    "edge_function_service.async_concurrency_exceeded",
                    function_id=func.function_id,
                    invocation_id=invocation_id,
                )
                return

        self._concurrent_count[func.function_id] = current + 1
        try:
            result = await self._sandbox.execute(
                function=func,
                version=version,
                event=event,
                context=context,
            )
            # 修正 invocation_id
            result.invocation_id = invocation_id
            self._record_invocation(result)
        finally:
            self._concurrent_count[func.function_id] = max(
                0, self._concurrent_count[func.function_id] - 1
            )

    def _record_invocation(self, result: FunctionExecutionResult) -> None:
        """记录调用历史."""
        self._invocation_history.append(result)
        if len(self._invocation_history) > self._max_history:
            self._invocation_history = self._invocation_history[-self._max_history:]

    # ------------------------------------------------------------------
    # 统计与指标
    # ------------------------------------------------------------------

    def get_metrics(self) -> dict[str, Any]:
        """获取服务统计指标.

        Returns:
            指标字典.
        """
        total_functions = len(self._functions)
        active_functions = sum(
            1 for f in self._functions.values() if f.status == FunctionStatus.ACTIVE
        )
        total_versions = sum(len(f.versions) for f in self._functions.values())
        total_invocations = len(self._invocation_history)
        success_count = sum(1 for r in self._invocation_history if r.success)
        cold_start_count = sum(1 for r in self._invocation_history if r.cold_start)

        avg_duration = 0.0
        if self._invocation_history:
            avg_duration = sum(r.duration_ms for r in self._invocation_history) / len(
                self._invocation_history
            )

        return {
            "total_functions": total_functions,
            "active_functions": active_functions,
            "total_versions": total_versions,
            "total_invocations": total_invocations,
            "success_count": success_count,
            "failure_count": total_invocations - success_count,
            "cold_start_count": cold_start_count,
            "average_duration_ms": round(avg_duration, 2),
            "concurrent_invocations": sum(self._concurrent_count.values()),
        }

    def get_invocation_history(
        self,
        function_id: str | None = None,
        limit: int = 50,
    ) -> list[FunctionExecutionResult]:
        """获取调用历史.

        Args:
            function_id: 按函数过滤，None 表示全部.
            limit: 返回条数.

        Returns:
            调用结果列表（按时间倒序）.
        """
        history = self._invocation_history
        if function_id:
            history = [h for h in history if h.function_id == function_id]
        history = sorted(history, key=lambda r: r.start_time, reverse=True)
        return history[:limit]

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（用于 API 响应）."""
        return {
            "functions": [
                {
                    "function_id": f.function_id,
                    "name": f.name,
                    "description": f.description,
                    "tags": f.tags,
                    "status": f.status.value,
                    "default_version": f.default_version,
                    "version_count": len(f.versions),
                    "timeout_seconds": f.timeout_seconds,
                    "memory_limit_mb": f.memory_limit_mb,
                    "warm_pool_size": f.warm_pool_size,
                    "created_at": f.created_at,
                    "updated_at": f.updated_at,
                }
                for f in self._functions.values()
            ],
            "metrics": self.get_metrics(),
        }
