"""
云汐内核 V11.0 - FastAPI HTTP API 封装层

[R04+R05] 补全全局接口表缺失的4个标准接口，
解决与M3的submit_task命名冲突，
将核心Python API暴露为RESTful HTTP接口。

[V11.4] 全链路追踪增强：
- HTTP 请求入口从 X-Trace-Id 请求头读取 trace_id，无则生成
- 将 trace_id 设置到 contextvars 上下文，协程安全
- 所有响应头包含 X-Trace-Id
- 错误响应中自动注入 trace_id

新增端点：
- POST   /api/v1/tasks/submit           → OrchestratorV9.process()
- DELETE /api/v1/agents/{agent_id}      → AgentRegistry.unregister()
- GET    /api/v1/agents/{agent_id}/status → AgentRegistry.get_status()
- GET    /api/v1/tasks/{task_id}/status  → LedgerEngine.query_task()
- POST   /api/v1/bus/publish            → MessageBus.publish()
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Generic, Literal, TypeVar

import structlog

logger = structlog.get_logger(__name__)

# 惰性导入 FastAPI
_fastapi_available = False
try:
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
    from fastapi.responses import JSONResponse, StreamingResponse
    from pydantic import BaseModel, Field
    _fastapi_available = True
except ImportError:
    class BaseModel:  # type: ignore[no-redef]
        pass
    class Field:  # type: ignore[no-redef]
        @staticmethod
        def default_factory(*args, **kwargs):
            pass

# 全链路追踪上下文（基于 contextvars，异步安全）
try:
    from src.observability.trace_context import (
        get_trace_id as _get_trace_id,
        set_trace_id as _set_trace_id,
        reset_trace_id as _reset_trace_id,
        set_request_start as _set_request_start,
        reset_request_start as _reset_request_start,
        clear_trace_id as _clear_trace_id,
    )
    _trace_context_available = True
except ImportError:
    _trace_context_available = False

    def _get_trace_id() -> str:
        import uuid
        return uuid.uuid4().hex

    def _set_trace_id(trace_id: str) -> Any:
        return None

    def _reset_trace_id(token: Any) -> None:
        pass

    def _set_request_start(timestamp: float | None = None) -> Any:
        return None

    def _reset_request_start(token: Any) -> None:
        pass

    def _clear_trace_id() -> None:
        pass


# ── Pydantic 请求/响应模型 ──────────────────────────────
# [V12.0] 模型已迁移至 models/ 目录统一管理。
# 优先从 models 包导入，失败时回退到本地定义以保持向后兼容。

try:
    from src.models.task import (
        SubmitTaskRequest,
        SubmitTaskResponse,
        TaskStatusResponse,
        CloneRequest,
        CloneReleaseRequest,
    )
    from src.models.agent import AgentStatusResponse
    from src.models.message import BusPublishRequest
    _models_imported = True
except ImportError:
    _models_imported = False

    # deprecated: use models.task.SubmitTaskRequest instead
    class SubmitTaskRequest(BaseModel):  # type: ignore[no-redef]
        """[V10.0] 提交任务请求

        字段边界校验：
        - user_input: 1~10000 字符
        - task_id: 最长 64 字符，允许空字符串（服务端自动生成）
        - trace_id: 最长 64 字符
        - model: 最长 128 字符
        - priority: 1~10 整数
        """
        user_input: str = Field(..., min_length=1, max_length=10000)
        task_id: str = Field(default="", max_length=64)
        trace_id: str = Field(default="", max_length=64)
        model: str = Field(default="", max_length=128)
        budget: dict[str, Any] = Field(default_factory=dict)  # [v2.0-LINKAGE]
        input_tokens: int = Field(default=0, ge=0)
        output_tokens: int = Field(default=0, ge=0)
        priority: int = Field(default=5, ge=1, le=10)
        metadata: dict[str, Any] = Field(default_factory=dict)

    # deprecated: use models.task.SubmitTaskResponse instead
    class SubmitTaskResponse(BaseModel):  # type: ignore[no-redef]
        """[V10.0] 提交任务响应"""
        status: str
        task_id: str = ""
        result: dict[str, Any] = Field(default_factory=dict)
        trace_id: str = ""  # [v2.0-LINKAGE]
        agents_deployed: list[str] = Field(default_factory=list)  # [v2.0-LINKAGE]
        budget_consumed: float = 0.0  # [v2.0-LINKAGE]

    # deprecated: use models.message.BusPublishRequest instead
    class BusPublishRequest(BaseModel):  # type: ignore[no-redef]
        """[V10.0] 消息总线发布请求

        字段边界校验：
        - topic: 1~128 字符
        - sender: 最长 64 字符
        - msg_type: 最长 64 字符
        - priority: 1~10 整数
        - ttl: 0~3600 秒
        """
        topic: str = Field(..., min_length=1, max_length=128)
        payload: dict[str, Any] = Field(default_factory=dict)
        sender: str = Field(default="api_client", max_length=64)
        recipient: str | None = Field(default=None, max_length=64)
        msg_type: str = Field(default="user.input", max_length=64)
        priority: int = Field(default=5, ge=1, le=10)
        ttl: int = Field(default=300, ge=0, le=3600)
        trace_id: str = Field(default="", max_length=64)

    # deprecated: use models.task.CloneRequest instead
    class CloneRequest(BaseModel):  # type: ignore[no-redef]
        """[V10.0-P2-1] 分身申请请求

        字段边界校验：
        - parent_agent_id: 1~64 字符
        - clone_type: 枚举值（scout/planner/writer/reviewer）
        - ttl: 0~86400 秒（0表示使用默认TTL）
        """
        parent_agent_id: str = Field(..., min_length=1, max_length=64)
        clone_type: Literal["scout", "planner", "writer", "reviewer"] = "scout"
        task_id: str = Field(default="", max_length=64)
        capabilities: list[str] = Field(default_factory=list)
        context: dict[str, Any] = Field(default_factory=dict)
        ttl: int = Field(default=0, ge=0, le=86400)  # 0表示使用默认TTL

    # deprecated: use models.task.CloneReleaseRequest instead
    class CloneReleaseRequest(BaseModel):  # type: ignore[no-redef]
        """[V10.0-P2-1] 分身释放请求

        字段边界校验：
        - clone_id: 1~64 字符
        """
        clone_id: str = Field(..., min_length=1, max_length=64)

    # deprecated: use models.agent.AgentStatusResponse instead
    class AgentStatusResponse(BaseModel):  # type: ignore[no-redef]
        """[V10.0] Agent状态响应"""
        agent_id: str
        registered: bool
        version: str = ""
        capabilities: list[str] = Field(default_factory=list)
        health: dict[str, Any] = Field(default_factory=dict)

    # deprecated: use models.task.TaskStatusResponse instead
    class TaskStatusResponse(BaseModel):  # type: ignore[no-redef]
        """[V10.0] 任务状态响应"""
        task_id: str
        goal: str = ""
        status: str
        completion_rate: float = 0.0
        plans: list[dict[str, Any]] = Field(default_factory=list)
        agents: list[dict[str, Any]] = Field(default_factory=list)
        active: bool = False


# ── 联邦调度请求/响应模型 ──────────────────────────────
# [V12.0] 模型已迁移至 models/federation.py 统一管理。
# 优先从 models 包导入，失败时回退到本地定义以保持向后兼容。

if not _models_imported:
    # deprecated: use models.federation.FedRegisterRequest instead
    class FedRegisterRequest(BaseModel):  # type: ignore[no-redef]
        """[V11.0] 注册外部Agent请求

        字段边界校验：
        - display_name: 最长 128 字符
        - provider: 最长 64 字符
        - agent_type: 枚举值（llm/code/design/search/tool/custom）
        """
        display_name: str = Field(default="", max_length=128)
        provider: str = Field(default="", max_length=64)
        agent_type: Literal["llm", "code", "design", "search", "tool", "custom"] = "llm"
        capabilities: list[str] = []
        privacy_level: str = "standard"
        connection_type: str = "api_key"
        config: dict[str, Any] = {}
        api_key: str = ""

    # deprecated: use models.federation.FedInvokeRequest instead
    class FedInvokeRequest(BaseModel):  # type: ignore[no-redef]
        """[V11.0] 调用外部Agent请求

        字段边界校验：
        - agent_id: 最长 64 字符
        - prompt: 最长 100000 字符
        - system_prompt: 最长 50000 字符
        - temperature: 0~2 浮点数
        - max_tokens: 1~32768 整数
        """
        agent_id: str = Field(default="", max_length=64)
        prompt: str = Field(default="", max_length=100000)
        system_prompt: str = Field(default="", max_length=50000)
        temperature: float = Field(default=0.7, ge=0, le=2)
        max_tokens: int = Field(default=2048, ge=1, le=32768)
        security_level: str = "PUBLIC"

    # deprecated: use models.federation.FedDecideRequest instead
    class FedDecideRequest(BaseModel):  # type: ignore[no-redef]
        """[V11.0] 联邦调度决策请求

        字段边界校验：
        - remaining_budget: >= -1（-1表示不限制）
        - task_complexity: 0~1 浮点数
        """
        task_type: str = "general"
        security_level: str = "PUBLIC"
        user_preference: str = "balanced"
        remaining_budget: float = Field(default=-1.0, ge=-1.0)
        speed_requirement: str = "medium"
        task_complexity: float = Field(default=0.5, ge=0.0, le=1.0)

    # deprecated: use models.federation.FedCompareRequest instead
    class FedCompareRequest(BaseModel):  # type: ignore[no-redef]
        """[V11.0] Agent对比请求

        字段边界校验：
        - prompt: 最长 100000 字符
        - system_prompt: 最长 50000 字符
        - temperature: 0~2 浮点数
        - max_tokens: 1~32768 整数
        """
        agent_ids: list[str] = []
        prompt: str = Field(default="", max_length=100000)
        system_prompt: str = Field(default="", max_length=50000)
        temperature: float = Field(default=0.7, ge=0, le=2)
        max_tokens: int = Field(default=2048, ge=1, le=32768)
        output_mode: str = "best_only"
        task_type: str = "general"

    # deprecated: use models.federation.FedPrivacyScanRequest instead
    class FedPrivacyScanRequest(BaseModel):  # type: ignore[no-redef]
        """[V11.0] 隐私扫描请求

        字段边界校验：
        - content: 最长 100000 字符
        """
        content: str = Field(default="", max_length=100000)
        security_level: str = "PUBLIC"
        task_type: str = "general"

    # deprecated: use models.federation.FedBudgetRequest instead
    class FedBudgetRequest(BaseModel):  # type: ignore[no-redef]
        """[V11.0] 预算设置请求

        字段边界校验：
        - monthly_budget: 0~100000 浮点数
        """
        monthly_budget: float = Field(default=10.0, ge=0, le=100000)
else:
    from src.models.federation import (  # noqa: F401
        FedRegisterRequest,
        FedInvokeRequest,
        FedDecideRequest,
        FedCompareRequest,
        FedPrivacyScanRequest,
        FedBudgetRequest,
    )


# ── Chat 请求模型 ──────────────────────────────────
# [V12.0] 模型已迁移至 models/task.py 统一管理。

if not _models_imported:
    # deprecated: use models.task.ChatRequest instead
    class ChatRequest(BaseModel):  # type: ignore[no-redef]
        """[V11.3] 同步对话请求

        用于 /api/v1/chat 端点，替代直接读取 request.json() 的方式。
        字段边界校验：
        - user_input: 1~10000 字符
        - trace_id: 最长 64 字符
        - model: 最长 128 字符
        """
        user_input: str = Field(..., min_length=1, max_length=10000)
        trace_id: str = Field(default="", max_length=64)
        model: str = Field(default="", max_length=128)

    # deprecated: use models.task.ChatStreamRequest instead
    class ChatStreamRequest(BaseModel):  # type: ignore[no-redef]
        """[V11.3] 流式对话请求

        用于 /api/v1/chat/stream 端点，替代直接读取 request.json() 的方式。
        字段边界校验：
        - user_input: 1~10000 字符
        - trace_id: 最长 64 字符
        - voice_polish: 是否启用人格润色（默认 True）
        """
        user_input: str = Field(..., min_length=1, max_length=10000)
        trace_id: str = Field(default="", max_length=64)
        voice_polish: bool = True  # [V10.1] 流式润色开关
else:
    from src.models.task import ChatRequest, ChatStreamRequest  # noqa: F401


# ── 通用响应模型 ──────────────────────────────────
# [V12.0] 模型已迁移至 models/common.py 统一管理。
# 泛型类型变量 T 保持在本文件作用域内可用。

if not _models_imported:
    # 泛型类型变量，用于 ApiResponse 和 PaginatedResponse
    T = TypeVar("T")

    # deprecated: use models.common.ApiResponse instead
    class ApiResponse(BaseModel, Generic[T]):  # type: ignore[no-redef]
        """[V11.3] 通用成功响应模型

        统一 API 成功响应格式，包含状态标识、业务数据和提示信息。

        Attributes:
            success: 操作是否成功，固定为 True
            data: 响应数据，泛型类型，由具体接口决定
            message: 可选提示信息
        """
        success: bool = True
        data: T | None = None
        message: str = ""

    # deprecated: use models.common.ErrorResponse instead
    class ErrorResponse(BaseModel):  # type: ignore[no-redef]
        """[V11.3] 通用错误响应模型

        统一 API 错误响应格式，包含错误码、错误信息和追踪ID。

        Attributes:
            success: 操作是否成功，固定为 False
            error: 错误码标识
            message: 错误详细描述
            trace_id: 追踪ID，用于问题排查
        """
        success: bool = False
        error: str = ""
        message: str = ""
        trace_id: str = ""

    # deprecated: use models.common.PaginatedResponse instead
    class PaginatedResponse(BaseModel, Generic[T]):  # type: ignore[no-redef]
        """[V11.3] 分页响应模型

        统一分页查询响应格式，包含数据列表和分页信息。

        Attributes:
            success: 操作是否成功
            items: 当前页数据列表
            total: 总记录数
            page: 当前页码（从1开始）
            page_size: 每页记录数
            total_pages: 总页数
        """
        success: bool = True
        items: list[T] = Field(default_factory=list)
        total: int = 0
        page: int = Field(default=1, ge=1)
        page_size: int = Field(default=20, ge=1, le=500)
        total_pages: int = Field(default=0, ge=0)
else:
    from src.models.common import (  # noqa: F401
        ApiResponse,
        ErrorResponse,
        PaginatedResponse,
        T,
    )


# ── API 工厂 ────────────────────────────────────────────

def create_server(
    orchestrator: Any,
    registry: Any,
    ledger: Any,
    message_bus: Any,
    health_monitor: Any | None = None,
    clone_pool: Any | None = None,
    federation_registry: Any | None = None,  # [V11.0] 外部Agent注册表
    federation_scheduler: Any | None = None,  # [V11.0] 联邦调度器
    cost_controller: Any | None = None,       # [V11.0] 成本控制器
    privacy_guard: Any | None = None,          # [V11.0] 隐私防护层
    config_manager: Any | None = None,         # [V11.1] 配置管理器
) -> "FastAPI":
    """[V11.0] 创建FastAPI应用实例

    Args:
        orchestrator: OrchestratorV9 实例
        registry: AgentRegistry 实例
        ledger: LedgerEngine 实例
        message_bus: MessageBus 实例
        health_monitor: HealthMonitor 实例（可选）
        clone_pool: ClonePool 实例（可选）
        federation_registry: ExternalAgentRegistry 实例（可选，V11.0新增）
        federation_scheduler: FederatedScheduler 实例（可选，V11.0新增）
        cost_controller: CostController 实例（可选，V11.0新增）
        privacy_guard: FederationPrivacyGuard 实例（可选，V11.0新增）

    Returns:
        FastAPI 应用实例
    """
    if not _fastapi_available:
        raise ImportError(
            "FastAPI is required for API server. "
            "Install it with: pip install fastapi uvicorn"
        )

    app = FastAPI(
        title="云汐内核 API V10.0",
        description="云汐多Agent集群调度系统 RESTful HTTP API",
        version="10.0.0",
    )

    # [V11.4] 注册全链路追踪中间件（必须在所有业务中间件之前）
    _register_trace_middleware(app)

    # [V11.1] 鉴权中间件 — 保护联邦调度关键接口
    if federation_registry is not None:
        _register_auth_middleware(app)

    # [V11.2] 注册全局异常处理器
    _register_exception_handlers(app)

    _register_routes(
        app, orchestrator, registry, ledger, message_bus,
        health_monitor, clone_pool,
        federation_registry=federation_registry,
        federation_scheduler=federation_scheduler,
        cost_controller=cost_controller,
        privacy_guard=privacy_guard,
        config_manager=config_manager,
    )
    return app


class YunxiAPI:
    """[V10.0] HTTP API 封装器（兼容旧版APIServer的类接口）"""

    def __init__(
        self,
        orchestrator: Any,
        registry: Any,
        ledger: Any,
        message_bus: Any,
        health_monitor: Any | None = None,
        clone_pool: Any | None = None,
        config_manager: Any | None = None,
        federation_registry: Any | None = None,
        federation_scheduler: Any | None = None,
        cost_controller: Any | None = None,
        privacy_guard: Any | None = None,
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        self._orchestrator = orchestrator
        self._registry = registry
        self._ledger = ledger
        self._bus = message_bus
        self._health = health_monitor
        self._clone_pool = clone_pool
        self._config = config_manager
        self._federation_registry = federation_registry
        self._federation_scheduler = federation_scheduler
        self._cost_controller = cost_controller
        self._privacy_guard = privacy_guard
        self.host = host
        self.port = port
        self._logger = logger.bind(service="yunxi_api")
        self._app = create_server(
            orchestrator=orchestrator,
            registry=registry,
            ledger=ledger,
            message_bus=message_bus,
            health_monitor=health_monitor,
            clone_pool=clone_pool,
            federation_registry=federation_registry,
            federation_scheduler=federation_scheduler,
            cost_controller=cost_controller,
            privacy_guard=privacy_guard,
            config_manager=config_manager,
        )
        self._server_task: asyncio.Task[None] | None = None

    @property
    def app(self) -> "FastAPI":
        return self._app

    async def start(self) -> None:
        import uvicorn
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(server.serve())
        self._logger.info("yunxi_api_started", host=self.host, port=self.port)

    async def stop(self) -> None:
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        self._logger.info("yunxi_api_stopped")


# ── 全链路追踪中间件 ──────────────────────────────────────

def _register_trace_middleware(app: "FastAPI") -> None:
    """[V11.4] 注册全链路追踪中间件。

    职责：
    1. 从请求头 X-Trace-Id 读取 trace_id，没有则生成新的
    2. 将 trace_id 设置到 contextvars 上下文（协程安全）
    3. 记录请求开始时间
    4. 所有响应头包含 X-Trace-Id
    5. 请求处理完毕后清理上下文，避免污染

    此中间件必须在所有业务中间件之前注册，确保 trace_id 全程可用。
    """
    from fastapi import Request

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next: Any) -> Any:
        """全链路追踪中间件核心逻辑"""
        # 1. 从请求头读取 trace_id，没有则生成
        trace_id = request.headers.get("x-trace-id", "")
        if not trace_id:
            # 也尝试从请求体中读取（兼容旧版通过 body 传递 trace_id 的方式）
            trace_id = _get_trace_id() if _trace_context_available else _generate_trace_id_fallback()

        # 2. 设置到 contextvars 上下文
        trace_token = _set_trace_id(trace_id)
        start_token = _set_request_start(time.time())

        try:
            # 3. 执行业务逻辑
            response = await call_next(request)

            # 4. 响应头注入 X-Trace-Id
            response.headers["X-Trace-Id"] = _get_trace_id()
            return response
        finally:
            # 5. 恢复上下文，避免协程复用时的污染
            _reset_request_start(start_token)
            _reset_trace_id(trace_token)

    def _generate_trace_id_fallback() -> str:
        """trace_context 不可用时的降级 trace_id 生成"""
        import uuid
        return uuid.uuid4().hex


# ── 鉴权中间件 ────────────────────────────────────────

def _register_auth_middleware(app: "FastAPI") -> None:
    """[V11.1] 注册鉴权中间件

    保护联邦调度系统的关键接口：
    - Admin 级别：注册/删除 Agent、设置预算、查看审计日志
    - Write 级别：调用、对比
    - Read 级别：列表、查询、决策、扫描

    支持两种鉴权方式：
    1. Admin API Key：Authorization: Bearer <admin-key>
    2. 内部调用：X-Internal-Call: true + X-Signature
    """
    from fastapi import Request, HTTPException
    import time

    # 接口权限配置（method+path_prefix -> required_permission）
    PROTECTED_ENDPOINTS = [
        # admin 级别
        ("POST", "/v1/federation/agents/register", "admin"),
        ("DELETE", "/v1/federation/agents/", "admin"),
        ("POST", "/v1/federation/cost/budget", "admin"),
        ("GET", "/v1/federation/privacy/audit", "admin"),
        # write 级别
        ("POST", "/v1/federation/invoke", "write"),
        ("POST", "/v1/federation/compare", "write"),
        # read 级别（默认所有 GET 都需要至少 read）
    ]

    # 权限包含关系
    PERM_LEVELS = {"admin": 3, "write": 2, "read": 1}

    def _get_required_perm(method: str, path: str) -> str | None:
        """获取接口需要的权限"""
        # 精确/前缀匹配
        for ep_method, ep_path, perm in PROTECTED_ENDPOINTS:
            if method == ep_method and (
                path == ep_path or path.startswith(ep_path)
            ):
                return perm
        # 所有 /v1/federation/ 下的 GET 请求至少需要 read
        if method == "GET" and path.startswith("/v1/federation/"):
            return "read"
        if method == "POST" and path.startswith("/v1/federation/decide"):
            return "read"
        if method == "POST" and path.startswith("/v1/federation/privacy/scan"):
            return "read"
        if method == "POST" and path.startswith("/v1/federation/agents/") and path.endswith("/health-check"):
            return "read"
        return None

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next: Any) -> Any:
        """鉴权中间件"""
        method = request.method
        path = request.url.path

        # 跳过非联邦调度接口
        if not path.startswith("/v1/federation/"):
            return await call_next(request)

        required = _get_required_perm(method, path)
        if required is None:
            return await call_next(request)

        # 尝试鉴权
        auth_header = request.headers.get("authorization", "")
        internal_call = request.headers.get("x-internal-call", "").lower() == "true"
        signature = request.headers.get("x-signature", "")
        timestamp = request.headers.get("x-timestamp", "")

        user_perm = 0  # 0 = 未鉴权

        # Admin Key 鉴权
        if auth_header.startswith("Bearer "):
            import os
            import hmac
            token = auth_header[7:]
            admin_key = os.environ.get("FEDERATION_ADMIN_KEY", "")
            if admin_key and hmac.compare_digest(token, admin_key):
                user_perm = PERM_LEVELS["admin"]

        # 内部调用鉴权
        if internal_call and signature and timestamp:
            import os
            import hmac
            import hashlib
            secret = os.environ.get("FEDERATION_INTERNAL_SECRET", "")
            if secret:
                try:
                    ts = float(timestamp)
                    if abs(time.time() - ts) <= 300:  # 5 分钟窗口
                        msg = f"{method}|{path}|{timestamp}"
                        expected = hmac.new(
                            secret.encode(),
                            msg.encode(),
                            hashlib.sha256,
                        ).hexdigest()
                        if hmac.compare_digest(signature, expected):
                            user_perm = PERM_LEVELS["admin"]
                except (ValueError, TypeError):
                    pass

        # 权限检查
        if user_perm < PERM_LEVELS.get(required, 99):
            detail = "Authentication required"
            if auth_header or internal_call:
                detail = "Permission denied"
            raise HTTPException(status_code=403, detail=detail)

        return await call_next(request)


# ── 全局异常处理器 ──────────────────────────────────────

def _register_exception_handlers(app: "FastAPI") -> None:
    """[V11.2] 注册全局异常处理器

    统一捕获各类异常并转换为标准错误响应格式：
    - M1BaseException：业务异常，直接使用其结构化信息
    - RequestValidationError：FastAPI/Pydantic 参数校验异常
    - Exception：通用未知异常，返回内部错误

    所有异常均返回与 error_codes.build_error_response 一致的格式。
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from fastapi.exceptions import RequestValidationError

    # 导入统一异常基类与错误码
    try:
        from src.models.exceptions import M1BaseException
    except ImportError:
        M1BaseException = None  # type: ignore[assignment,misc]

    from src.models.error_codes import ERR_PARAM_INVALID, ERR_INTERNAL, build_error_response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """处理 FastAPI/Pydantic 参数校验异常

        将 Pydantic 的验证错误映射到统一的参数校验错误码，
        并在 detail 中包含字段级别的错误信息。
        """
        # 提取字段错误信息
        errors = exc.errors()
        detail_parts = []
        for err in errors:
            loc = " -> ".join(str(x) for x in err.get("loc", []))
            msg = err.get("msg", "")
            err_type = err.get("type", "")
            if loc:
                detail_parts.append(f"[{loc}] {msg} ({err_type})")
            else:
                detail_parts.append(f"{msg} ({err_type})")
        detail = "; ".join(detail_parts) if detail_parts else "参数校验失败"

        # 从 contextvars 获取当前 trace_id（V11.4 增强）
        trace_id = _get_trace_id()

        response = build_error_response(
            error_code=ERR_PARAM_INVALID,
            detail=detail,
            trace_id=trace_id,
            data={"errors": errors},
        )
        resp = JSONResponse(
            status_code=ERR_PARAM_INVALID.http_status,
            content=response,
        )
        # 响应头注入 trace_id
        resp.headers["X-Trace-Id"] = trace_id
        return resp

    if M1BaseException is not None:
        @app.exception_handler(M1BaseException)
        async def m1_base_exception_handler(
            request: Request, exc: M1BaseException
        ) -> JSONResponse:
            """处理 M1 统一业务异常

            直接使用异常对象的结构化信息生成标准错误响应。
            """
            # 从 contextvars 获取当前 trace_id（V11.4 增强）
            current_trace_id = _get_trace_id()
            logger.warning(
                "m1_exception_caught",
                code=exc.code,
                message=exc.error_code.message,
                detail=exc.detail,
                trace_id=exc.trace_id or current_trace_id,
                exc_type=exc.__class__.__name__,
            )
            resp = JSONResponse(
                status_code=exc.http_status,
                content=exc.to_response(),
            )
            # 响应头注入 trace_id
            resp.headers["X-Trace-Id"] = exc.trace_id or current_trace_id
            return resp

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """处理未捕获的通用异常

        返回内部错误响应，避免泄露敏感信息，同时记录错误日志。
        """
        # 从 contextvars 获取当前 trace_id（V11.4 增强）
        trace_id = _get_trace_id()
        logger.error(
            "unhandled_exception",
            error=str(exc),
            exc_type=exc.__class__.__name__,
            path=request.url.path,
            method=request.method,
            trace_id=trace_id,
        )
        response = build_error_response(
            error_code=ERR_INTERNAL,
            detail="服务器内部错误",
            trace_id=trace_id,
            data=None,
        )
        resp = JSONResponse(
            status_code=ERR_INTERNAL.http_status,
            content=response,
        )
        # 响应头注入 trace_id
        resp.headers["X-Trace-Id"] = trace_id
        return resp


# ── 辅助函数 ──────────────────────────────────────────

def _check_admin_auth(request: "Request") -> bool:
    """[V12.0] 检查管理员权限

    用于保护深度健康检查等敏感端点。
    支持两种鉴权方式：
    1. Admin API Key：Authorization: Bearer <admin-key>
    2. 内部调用：X-Internal-Call: true + 有效签名

    Args:
        request: FastAPI Request 对象

    Returns:
        是否具有管理员权限
    """
    import os
    import hmac
    import hashlib

    auth_header = request.headers.get("authorization", "")
    internal_call = request.headers.get("x-internal-call", "").lower() == "true"
    signature = request.headers.get("x-signature", "")
    timestamp = request.headers.get("x-timestamp", "")

    # Admin Key 鉴权
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        admin_key = os.environ.get("HEALTH_ADMIN_KEY", "") or os.environ.get("FEDERATION_ADMIN_KEY", "")
        if admin_key and hmac.compare_digest(token, admin_key):
            return True

    # 内部调用鉴权
    if internal_call and signature and timestamp:
        secret = os.environ.get("FEDERATION_INTERNAL_SECRET", "")
        if secret:
            try:
                ts = float(timestamp)
                if abs(time.time() - ts) <= 300:  # 5 分钟窗口
                    method = request.method
                    path = request.url.path
                    msg = f"{method}|{path}|{timestamp}"
                    expected = hmac.new(
                        secret.encode(),
                        msg.encode(),
                        hashlib.sha256,
                    ).hexdigest()
                    if hmac.compare_digest(signature, expected):
                        return True
            except (ValueError, TypeError):
                pass

    # 未配置任何密钥时，允许本地访问（127.0.0.1 / ::1）
    if not os.environ.get("HEALTH_ADMIN_KEY") and not os.environ.get("FEDERATION_ADMIN_KEY"):
        client_host = getattr(request.client, "host", "") if request.client else ""
        if client_host in ("127.0.0.1", "::1", "localhost"):
            return True

    return False


# ── 路由注册 ────────────────────────────────────────────

def _register_routes(
    app: "FastAPI",
    orchestrator: Any,
    registry: Any,
    ledger: Any,
    message_bus: Any,
    health_monitor: Any | None,
    clone_pool: Any | None,
    federation_registry: Any | None = None,  # [V11.0] 外部Agent注册表
    federation_scheduler: Any | None = None,  # [V11.0] 联邦调度器
    cost_controller: Any | None = None,       # [V11.0] 成本控制器
    privacy_guard: Any | None = None,          # [V11.0] 隐私防护层
    config_manager: Any | None = None,         # [V11.1] 配置管理器
) -> None:
    """注册所有API路由"""

    # ── [V10.0-R04+R05] 核心标准接口 ───────────────────

    @app.post("/api/v1/tasks/submit", response_model=SubmitTaskResponse)
    async def submit_task(request: SubmitTaskRequest) -> JSONResponse:
        """[V10.0] 提交任务（M1唯一入口，解决M3命名冲突）

        全局接口表中POST /api/v1/tasks/submit的唯一实现入口。
        M3的推理执行由M1内部委托，不对外暴露submit_task。
        [v2.0-LINKAGE] 输入增加 budget 参数，输出增加 trace_id/agents_deployed/budget_consumed。
        """
        try:
            result = await orchestrator.process(
                user_input=request.user_input,
                task_id=request.task_id,
                trace_id=request.trace_id,
                model=request.model,
                budget=request.budget,
                input_tokens=request.input_tokens,
                output_tokens=request.output_tokens,
                priority=request.priority,
                metadata=request.metadata,
            )
            return JSONResponse(content={
                "status": result.get("status", "success"),
                "task_id": request.task_id or result.get("task_id", ""),
                "result": result,
                "trace_id": request.trace_id or result.get("trace_id", ""),
                "agents_deployed": result.get("agents_deployed", []),
                "budget_consumed": result.get("budget_consumed", 0.0),
            })
        except Exception as exc:
            logger.error("submit_task_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))

    @app.delete("/api/v1/agents/{agent_id}")
    async def delete_agent(agent_id: str) -> JSONResponse:
        """[V10.0] 注销Agent"""
        try:
            await registry.unregister(agent_id)
            return JSONResponse(content={
                "status": "success",
                "agent_id": agent_id,
                "action": "unregistered",
            })
        except Exception as exc:
            logger.error("delete_agent_failed", agent_id=agent_id, error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/v1/agents/{agent_id}/status", response_model=AgentStatusResponse)
    async def get_agent_status(agent_id: str) -> JSONResponse:
        """[V10.0] 查询Agent状态"""
        status = await registry.get_status(agent_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        return JSONResponse(content=status)

    @app.get("/api/v1/tasks/{task_id}/status", response_model=TaskStatusResponse)
    async def get_task_status(task_id: str) -> JSONResponse:
        """[V10.0] 查询任务状态"""
        status = ledger.query_task(task_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        return JSONResponse(content=status)

    @app.post("/api/v1/bus/publish")
    async def bus_publish(request: BusPublishRequest) -> JSONResponse:
        """[V10.0] 消息总线发布（HTTP封装）"""
        try:
            from src.tools.interfaces import BusMessage
            msg = BusMessage(
                topic=request.topic,
                sender=request.sender,
                recipient=request.recipient,
                msg_type=request.msg_type,  # type: ignore[arg-type]
                payload=request.payload,
                priority=request.priority,
                ttl=request.ttl,
                trace_id=request.trace_id,
            )
            await message_bus.publish(msg)
            return JSONResponse(content={
                "status": "published",
                "msg_id": msg.msg_id,
                "topic": request.topic,
            })
        except Exception as exc:
            logger.error("bus_publish_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))

    # ── 兼容旧版接口 ──────────────────────────────────

    @app.post("/api/v1/chat")
    async def chat(request: ChatRequest) -> JSONResponse:
        """同步对话

        使用 ChatRequest Pydantic 模型进行输入校验，
        替代直接读取 request.json() 的方式。
        """
        result = await orchestrator.process(
            user_input=request.user_input,
            trace_id=request.trace_id,
        )
        return JSONResponse(content=result)

    @app.post("/api/v1/chat/stream")
    async def chat_stream(request: ChatStreamRequest) -> StreamingResponse:
        """SSE 流式对话

        使用 ChatStreamRequest Pydantic 模型进行输入校验，
        替代直接读取 request.json() 的方式。

        支持 voice_polish 参数控制人格润色：
        - true（默认）：流畅模式，按句子缓冲润色后流式输出
        - false：极速模式，跳过润色直接输出原始内容
        - YunxiVoice 响应 > 500ms 时自动降级为极速模式
        """
        user_input = request.user_input
        trace_id = request.trace_id
        voice_polish: bool = request.voice_polish  # [V10.1] 流式润色开关

        async def event_generator() -> AsyncIterator[str]:
            async for chunk in orchestrator.process_stream(
                user_input=user_input,
                trace_id=trace_id,
            ):
                if hasattr(chunk, "to_dict"):
                    data = json.dumps(chunk.to_dict(), ensure_ascii=False)
                elif hasattr(chunk, "model_dump"):
                    data = json.dumps(chunk.model_dump(), ensure_ascii=False)
                else:
                    data = json.dumps(chunk, ensure_ascii=False, default=str)
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

    @app.get("/health")
    async def health() -> JSONResponse:
        """存活检查（标准格式，兼容旧版）

        返回格式：
        {"code": 0, "message": "ok", "data": {"status": "healthy"}}
        """
        status = "healthy"
        if health_monitor:
            live = await health_monitor.liveness()
            raw_status = getattr(live, "status", "up")
            if raw_status == "up":
                status = "healthy"
            elif raw_status == "degraded":
                status = "degraded"
            else:
                status = "unhealthy"
        return JSONResponse(content={
            "code": 0,
            "message": "ok",
            "data": {"status": status},
        })

    # ── [V12.0] 三级健康检查端点 ────────────────────────

    @app.get("/health/liveness")
    async def health_liveness() -> JSONResponse:
        """存活检查：进程是否存活

        轻量级，响应时间 < 10ms，不依赖任何外部资源。
        对应 Kubernetes livenessProbe。
        """
        if health_monitor is None:
            return JSONResponse(
                content={"status": "up", "level": "liveness", "message": "no health monitor"},
                status_code=200,
            )
        live = await health_monitor.liveness()
        status_code = 200 if live.status == "up" else 503
        return JSONResponse(content=live.to_dict(), status_code=status_code)

    @app.get("/health/readiness")
    async def health_readiness() -> JSONResponse:
        """就绪检查：核心依赖是否可用

        中量级，响应时间 < 500ms，检查数据库、消息总线等核心依赖。
        对应 Kubernetes readinessProbe。
        返回聚合状态及各组件详情。
        """
        if health_monitor is None:
            return JSONResponse(
                content={"status": "up", "level": "readiness", "message": "no health monitor"},
                status_code=200,
            )
        overall = await health_monitor.overall_status()
        status_code = 200 if overall["status"] in ("up", "degraded") else 503
        return JSONResponse(content=overall, status_code=status_code)

    @app.get("/health/deep")
    async def health_deep(
        request: Request,
        force: bool = False,
    ) -> JSONResponse:
        """深度健康诊断：完整检查所有依赖

        重量级，响应时间 1-5 秒，包含数据库完整性检查、磁盘/内存/熔断器等。
        需管理员权限，默认使用 60s 缓存。

        Args:
            force: 是否强制刷新缓存（跳过缓存）
        """
        if health_monitor is None:
            return JSONResponse(
                content={"status": "unknown", "level": "deep", "message": "no health monitor"},
                status_code=503,
            )

        # 管理员权限校验（可选）
        if not _check_admin_auth(request):
            raise HTTPException(status_code=403, detail="Admin access required for deep health check")

        use_cache = not force
        results = await health_monitor.deep_check(use_cache=use_cache)

        # 计算聚合状态
        all_up = all(r.status == "up" for r in results.values())
        any_down = any(r.status == "down" for r in results.values())
        any_degraded = any(r.status == "degraded" for r in results.values())

        if any_down:
            overall = "down"
        elif any_degraded:
            overall = "degraded"
        elif all_up:
            overall = "up"
        else:
            overall = "unknown"

        status_code = 200 if overall in ("up", "degraded") else 503

        return JSONResponse(
            content={
                "status": overall,
                "level": "deep",
                "timestamp": time.time(),
                "total": len(results),
                "components": {name: s.to_dict() for name, s in results.items()},
            },
            status_code=status_code,
        )

    @app.get("/health/components")
    async def health_components() -> JSONResponse:
        """各组件详细健康状态

        返回所有已注册检查项的完整状态信息，包括组件类型、级别、延迟等。
        """
        if health_monitor is None:
            return JSONResponse(
                content={"total": 0, "components": {}, "summary": {"up": 0, "down": 0, "degraded": 0}},
                status_code=200,
            )
        result = await health_monitor.component_statuses()
        return JSONResponse(content=result)

    @app.get("/health/metrics")
    async def health_metrics() -> StreamingResponse:
        """Prometheus 格式健康指标

        与 /metrics 端点功能一致，作为 /health 命名空间下的别名。
        """
        if health_monitor:
            prom = await health_monitor.to_prometheus()
            return StreamingResponse(
                iter([prom]),
                media_type="text/plain; charset=utf-8",
            )
        return StreamingResponse(
            iter(["# no metrics\n"]),
            media_type="text/plain; charset=utf-8",
        )

    @app.get("/ready")
    async def ready() -> JSONResponse:
        """就绪检查（兼容旧版，映射到 readiness）"""
        if health_monitor:
            status = await health_monitor.overall_status()
            code = 200 if status["status"] in ("up", "degraded") else 503
            return JSONResponse(content=status, status_code=code)
        return JSONResponse(content={"status": "up"})

    @app.get("/metrics")
    async def metrics() -> StreamingResponse:
        """Prometheus 指标（兼容旧版）"""
        if health_monitor:
            prom = await health_monitor.to_prometheus()
            return StreamingResponse(
                iter([prom]),
                media_type="text/plain; charset=utf-8",
            )
        return StreamingResponse(
            iter(["# no metrics\n"]),
            media_type="text/plain; charset=utf-8",
        )

    @app.get("/diagnose")
    async def diagnose() -> JSONResponse:
        """全量诊断"""
        diag = orchestrator.diagnose()
        return JSONResponse(content=diag)

    @app.get("/agents")
    async def list_agents() -> JSONResponse:
        """列出所有Agent"""
        agents = registry.list_all()
        return JSONResponse(content={
            "agents": [
                {
                    "agent_id": getattr(a, "agent_id", str(a)),
                    "version": getattr(a, "version", ""),
                    "capabilities": getattr(a, "capabilities", []),
                }
                for a in agents
            ]
        })

    @app.get("/.well-known/agent-card.json")
    async def agent_discovery() -> JSONResponse:
        """A2A Protocol v1.0 Agent Discovery"""
        try:
            agents = registry.list_all()
            cards = []
            for a in agents:
                cards.append({
                    "agent_id": getattr(a, "agent_id", str(a)),
                    "capabilities": getattr(a, "capabilities", []),
                    "version": getattr(a, "version", ""),
                })
            return JSONResponse(content={
                "agent_cards": cards,
                "protocol_version": "1.0",
            })
        except Exception as exc:
            return JSONResponse(
                content={"error": str(exc)},
                status_code=500,
            )

    # ── [V10.0-P2-1] 分身池HTTP API ────────────────────

    @app.post("/v1/pool/request")
    async def pool_request(request: CloneRequest) -> JSONResponse:
        """申请临时分身"""
        if clone_pool is None:
            raise HTTPException(status_code=503, detail="Clone pool not available")
        try:
            from shared_models import CloneType
            ct = CloneType(request.clone_type)
            clone = await clone_pool.acquire(
                parent_agent_id=request.parent_agent_id,
                clone_type=ct,
                task_id=request.task_id,
                context=request.context,
            )
            return JSONResponse(content={
                "status": "acquired",
                "clone_id": clone.clone_id,
                "clone_type": clone.clone_type.value,
                "ttl": clone.ttl,
                "created_at": clone.created_at,
            })
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc))
        except Exception as exc:
            logger.error("pool_request_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/v1/pool/release")
    async def pool_release(request: CloneReleaseRequest) -> JSONResponse:
        """释放临时分身"""
        if clone_pool is None:
            raise HTTPException(status_code=503, detail="Clone pool not available")
        try:
            clone_pool.release(request.clone_id)
            return JSONResponse(content={
                "status": "released",
                "clone_id": request.clone_id,
            })
        except Exception as exc:
            logger.error("pool_release_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/v1/pool/status")
    async def pool_status() -> JSONResponse:
        """查询分身池状态"""
        if clone_pool is None:
            return JSONResponse(content={"status": "not_configured"})
        try:
            stats = clone_pool.stats()
            return JSONResponse(content={
                "status": "active",
                "stats": stats,
            })
        except Exception as exc:
            logger.error("pool_status_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/v1/pool/clones/{clone_id}")
    async def pool_clone_detail(clone_id: str) -> JSONResponse:
        """查询指定分身状态"""
        if clone_pool is None:
            raise HTTPException(status_code=503, detail="Clone pool not available")
        clone = clone_pool.get_clone(clone_id)
        if clone is None:
            raise HTTPException(status_code=404, detail=f"Clone '{clone_id}' not found")
        return JSONResponse(content={
            "clone_id": clone.clone_id,
            "parent_agent_id": clone.parent_agent_id,
            "clone_type": clone.clone_type.value,
            "task_id": clone.task_id,
            "ttl": clone.ttl,
            "created_at": clone.created_at,
        })

    # ── [V11.0] 联邦调度 HTTP API ──────────────────────

    # === 外部 Agent 管理 ===

    @app.get("/v1/federation/agents")
    async def fed_list_agents(status: str = "") -> JSONResponse:
        """列出外部 Agent"""
        if federation_registry is None:
            raise HTTPException(status_code=503, detail="Federation registry not available")
        agents = federation_registry.list_agents(status=status) if status else federation_registry.list_agents()
        return JSONResponse(content={
            "count": len(agents),
            "agents": [a.model_dump() for a in agents],
        })

    @app.post("/v1/federation/agents/register")
    async def fed_register_agent(request: FedRegisterRequest) -> JSONResponse:
        """注册外部 Agent"""
        if federation_registry is None:
            raise HTTPException(status_code=503, detail="Federation registry not available")
        from shared_models import ExternalAgentType, AgentPrivacyLevel, ConnectionType
        try:
            agent = federation_registry.register_agent(
                display_name=request.display_name,
                provider=request.provider,
                agent_type=ExternalAgentType(request.agent_type),
                capabilities=request.capabilities,
                privacy_level=AgentPrivacyLevel(request.privacy_level),
                connection_type=ConnectionType(request.connection_type),
                config=request.config,
                api_key=request.api_key,
            )
            return JSONResponse(content={
                "success": True,
                "agent": agent.model_dump(),
            })
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/v1/federation/agents/{agent_id}")
    async def fed_get_agent(agent_id: str) -> JSONResponse:
        """获取外部 Agent 详情"""
        if federation_registry is None:
            raise HTTPException(status_code=503, detail="Federation registry not available")
        agent = federation_registry.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"External agent '{agent_id}' not found")
        return JSONResponse(content={"agent": agent.model_dump()})

    @app.delete("/v1/federation/agents/{agent_id}")
    async def fed_unregister_agent(agent_id: str) -> JSONResponse:
        """注销外部 Agent"""
        if federation_registry is None:
            raise HTTPException(status_code=503, detail="Federation registry not available")
        success = federation_registry.unregister_agent(agent_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"External agent '{agent_id}' not found")
        return JSONResponse(content={"success": True, "agent_id": agent_id})

    @app.post("/v1/federation/agents/{agent_id}/health-check")
    async def fed_health_check(agent_id: str) -> JSONResponse:
        """外部 Agent 健康检查"""
        if federation_registry is None:
            raise HTTPException(status_code=503, detail="Federation registry not available")
        healthy, latency = await federation_registry.check_health(agent_id)
        return JSONResponse(content={
            "agent_id": agent_id,
            "healthy": healthy,
            "latency_ms": round(latency, 2),
        })

    # === 联邦调度决策 ===

    @app.post("/v1/federation/decide")
    async def fed_decide(request: FedDecideRequest) -> JSONResponse:
        """联邦调度决策：内部 vs 外部，选哪个外部 Agent"""
        if federation_scheduler is None:
            raise HTTPException(status_code=503, detail="Federation scheduler not available")
        from shared_models import SecurityClassification, UserPreferenceMode
        decision = federation_scheduler.decide(
            task_type=request.task_type,
            security_level=SecurityClassification(request.security_level),
            user_preference=UserPreferenceMode(request.user_preference),
            remaining_budget=request.remaining_budget,
            speed_requirement=request.speed_requirement,
            task_complexity=request.task_complexity,
        )
        return JSONResponse(content={"decision": decision.model_dump()})

    # === 外部 Agent 调用 ===

    @app.post("/v1/federation/invoke")
    async def fed_invoke(request: FedInvokeRequest) -> JSONResponse:
        """调用指定外部 Agent"""
        if federation_registry is None:
            raise HTTPException(status_code=503, detail="Federation registry not available")
        if privacy_guard:
            from shared_models import SecurityClassification
            scan_result = privacy_guard.scan(
                content=request.prompt + "\n" + request.system_prompt,
                security_level=SecurityClassification(request.security_level),
                task_type="general",
            )
            if scan_result.blocked:
                raise HTTPException(
                    status_code=403,
                    detail=f"Privacy check failed: {scan_result.summary}",
                )

        adapter = federation_registry.get_adapter(request.agent_id)
        if not adapter:
            raise HTTPException(status_code=404, detail=f"External agent '{request.agent_id}' not found")

        result = await adapter.invoke(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        # 记录成本
        if cost_controller:
            from shared_models import ExternalAgentProfile
            agent_info = federation_registry.get_agent(request.agent_id)
            cost = adapter.calculate_cost(
                result.get("input_tokens", 0),
                result.get("output_tokens", 0),
            )
            cost_controller.record_cost(
                task_id=result.get("request_id", ""),
                agent_id=request.agent_id,
                agent_name=agent_info.display_name if agent_info else request.agent_id,
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                cost=cost,
                success=result.get("success", True),
            )

        return JSONResponse(content={"result": result})

    # === 多 Agent 对比 ===

    @app.post("/v1/federation/compare")
    async def fed_compare(request: FedCompareRequest) -> JSONResponse:
        """多 Agent 并行对比"""
        if federation_registry is None:
            raise HTTPException(status_code=503, detail="Federation registry not available")

        from src.federation.comparator import MultiAgentComparator
        from shared_models import ComparisonOutputMode

        adapters = []
        for aid in request.agent_ids:
            adapter = federation_registry.get_adapter(aid)
            if adapter:
                adapters.append(adapter)

        if not adapters:
            raise HTTPException(status_code=404, detail="No valid external agents found")

        comparator = MultiAgentComparator()
        comparison = await comparator.execute_parallel(
            adapters=adapters,
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            output_mode=ComparisonOutputMode(request.output_mode),
            task_type=request.task_type,
        )

        # 记录成本
        if cost_controller:
            for r in comparison.results:
                cost_controller.record_cost(
                    task_id=f"compare_{id(comparison)}",
                    agent_id=r.agent_id,
                    agent_name=r.agent_name,
                    input_tokens=0,
                    output_tokens=0,
                    cost=r.cost,
                    task_type=request.task_type,
                    success=r.success,
                )

        return JSONResponse(content={"comparison": comparison.model_dump()})

    # === 隐私扫描 ===

    @app.post("/v1/federation/privacy/scan")
    async def fed_privacy_scan(request: FedPrivacyScanRequest) -> JSONResponse:
        """隐私内容扫描"""
        if privacy_guard is None:
            raise HTTPException(status_code=503, detail="Privacy guard not available")
        from shared_models import SecurityClassification
        result = privacy_guard.scan(
            content=request.content,
            security_level=SecurityClassification(request.security_level),
            task_type=request.task_type,
        )
        return JSONResponse(content={"scan_result": result.model_dump()})

    @app.get("/v1/federation/privacy/audit")
    async def fed_privacy_audit(limit: int = 100, blocked_only: bool = False) -> JSONResponse:
        """隐私审计日志"""
        if privacy_guard is None:
            raise HTTPException(status_code=503, detail="Privacy guard not available")
        logs = privacy_guard.get_audit_log(limit=limit, blocked_only=blocked_only)
        return JSONResponse(content={"audit_logs": logs, "count": len(logs)})

    # === 成本管控 ===

    @app.get("/v1/federation/cost/budget")
    async def fed_get_budget() -> JSONResponse:
        """获取预算状态"""
        if cost_controller is None:
            raise HTTPException(status_code=503, detail="Cost controller not available")
        budget = cost_controller.get_budget()
        stats = cost_controller.stats()
        return JSONResponse(content={"budget": budget.model_dump(), "stats": stats})

    @app.post("/v1/federation/cost/budget")
    async def fed_set_budget(request: FedBudgetRequest) -> JSONResponse:
        """设置月度预算"""
        if cost_controller is None:
            raise HTTPException(status_code=503, detail="Cost controller not available")
        result = cost_controller.set_monthly_budget(request.monthly_budget)
        return JSONResponse(content=result)

    @app.get("/v1/federation/cost/records")
    async def fed_cost_records(
        agent_id: str = "",
        task_type: str = "",
        limit: int = 100,
    ) -> JSONResponse:
        """查询费用明细"""
        if cost_controller is None:
            raise HTTPException(status_code=503, detail="Cost controller not available")
        records = cost_controller.get_records(
            agent_id=agent_id or None,
            task_type=task_type or None,
            limit=limit,
        )
        return JSONResponse(content={
            "records": [r.model_dump() for r in records],
            "count": len(records),
        })

    @app.get("/v1/federation/cost/daily")
    async def fed_cost_daily(days: int = 7) -> JSONResponse:
        """按日统计费用"""
        if cost_controller is None:
            raise HTTPException(status_code=503, detail="Cost controller not available")
        daily = cost_controller.get_daily_summary(days=days)
        return JSONResponse(content={"daily_summary": daily})

    # === M8 标准对接接口（V11.1 新增）===
    # 覆盖 /health 和 /metrics 为 M8 标准格式
    # 新增 /config、/upgrade、/test 等管理接口
    # /m8/health、/m8/metrics、/m8/config 为 M8 标准路径别名
    try:
        from src.api.m8_interface import register_m8_routes
        register_m8_routes(
            app,
            config_manager=config_manager,
            health_monitor=health_monitor,
            metrics_collector=None,
            orchestrator=orchestrator,
            registry=registry,
        )
        logger.info(
            "m8_routes_registered_ok",
            module="m1",
            has_registry=registry is not None,
        )
    except Exception as exc:
        logger.error(
            "m8_routes_register_failed",
            error=str(exc),
            exc_type=exc.__class__.__name__,
        )

    return app
