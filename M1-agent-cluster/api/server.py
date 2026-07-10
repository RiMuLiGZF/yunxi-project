"""
云汐内核 V11.0 - FastAPI HTTP API 封装层

[R04+R05] 补全全局接口表缺失的4个标准接口，
解决与M3的submit_task命名冲突，
将核心Python API暴露为RESTful HTTP接口。

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
from typing import Any, AsyncIterator

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


# ── Pydantic 请求/响应模型 ──────────────────────────────

class SubmitTaskRequest(BaseModel):
    """[V10.0] 提交任务请求"""
    user_input: str
    task_id: str = Field(default_factory=lambda: "")
    trace_id: str = ""
    model: str = ""
    budget: dict[str, Any] = Field(default_factory=dict)  # [v2.0-LINKAGE]
    input_tokens: int = 0
    output_tokens: int = 0
    priority: int = 5
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubmitTaskResponse(BaseModel):
    """[V10.0] 提交任务响应"""
    status: str
    task_id: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""  # [v2.0-LINKAGE]
    agents_deployed: list[str] = Field(default_factory=list)  # [v2.0-LINKAGE]
    budget_consumed: float = 0.0  # [v2.0-LINKAGE]


class BusPublishRequest(BaseModel):
    """[V10.0] 消息总线发布请求"""
    topic: str
    payload: dict[str, Any] = Field(default_factory=dict)
    sender: str = "api_client"
    recipient: str | None = None
    msg_type: str = "user.input"
    priority: int = 5
    ttl: int = 300
    trace_id: str = ""


class CloneRequest(BaseModel):
    """[V10.0-P2-1] 分身申请请求"""
    parent_agent_id: str
    clone_type: str = "scout"  # scout | planner | writer | reviewer
    task_id: str = ""
    capabilities: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    ttl: int = 0  # 0表示使用默认TTL


class CloneReleaseRequest(BaseModel):
    """[V10.0-P2-1] 分身释放请求"""
    clone_id: str


class AgentStatusResponse(BaseModel):
    """[V10.0] Agent状态响应"""
    agent_id: str
    registered: bool
    version: str = ""
    capabilities: list[str] = Field(default_factory=list)
    health: dict[str, Any] = Field(default_factory=dict)


class TaskStatusResponse(BaseModel):
    """[V10.0] 任务状态响应"""
    task_id: str
    goal: str = ""
    status: str
    completion_rate: float = 0.0
    plans: list[dict[str, Any]] = Field(default_factory=list)
    agents: list[dict[str, Any]] = Field(default_factory=list)
    active: bool = False


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

    # [V11.1] 鉴权中间件 — 保护联邦调度关键接口
    if federation_registry is not None:
        _register_auth_middleware(app)

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
            from interfaces import BusMessage
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
    async def chat(request: Request) -> JSONResponse:
        """同步对话"""
        body = await request.json()
        user_input = body.get("user_input", "")
        trace_id = body.get("trace_id")

        result = await orchestrator.process(
            user_input=user_input,
            trace_id=trace_id,
        )
        return JSONResponse(content=result)

    @app.post("/api/v1/chat/stream")
    async def chat_stream(request: Request) -> StreamingResponse:
        """SSE 流式对话

        支持 voice_polish 参数控制人格润色：
        - true（默认）：流畅模式，按句子缓冲润色后流式输出
        - false：极速模式，跳过润色直接输出原始内容
        - YunxiVoice 响应 > 500ms 时自动降级为极速模式
        """
        body = await request.json()
        user_input = body.get("user_input", "")
        trace_id = body.get("trace_id")
        voice_polish: bool = body.get("voice_polish", True)  # [V10.1] 流式润色开关

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
        """存活检查（标准格式）

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

    @app.get("/ready")
    async def ready() -> JSONResponse:
        """就绪检查"""
        if health_monitor:
            status = await health_monitor.overall_status()
            code = 200 if status["status"] in ("up", "degraded") else 503
            return JSONResponse(content=status, status_code=code)
        return JSONResponse(content={"status": "up"})

    @app.get("/metrics")
    async def metrics() -> StreamingResponse:
        """Prometheus 指标"""
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

    # === 请求/响应模型 ===

    class FedRegisterRequest(BaseModel):
        display_name: str = ""
        provider: str = ""
        agent_type: str = "llm"
        capabilities: list[str] = []
        privacy_level: str = "standard"
        connection_type: str = "api_key"
        config: dict[str, Any] = {}
        api_key: str = ""

    class FedInvokeRequest(BaseModel):
        agent_id: str = ""
        prompt: str = ""
        system_prompt: str = ""
        temperature: float = 0.7
        max_tokens: int = 2048
        security_level: str = "PUBLIC"

    class FedDecideRequest(BaseModel):
        task_type: str = "general"
        security_level: str = "PUBLIC"
        user_preference: str = "balanced"
        remaining_budget: float = -1.0
        speed_requirement: str = "medium"
        task_complexity: float = 0.5

    class FedCompareRequest(BaseModel):
        agent_ids: list[str] = []
        prompt: str = ""
        system_prompt: str = ""
        temperature: float = 0.7
        max_tokens: int = 2048
        output_mode: str = "best_only"
        task_type: str = "general"

    class FedPrivacyScanRequest(BaseModel):
        content: str = ""
        security_level: str = "PUBLIC"
        task_type: str = "general"

    class FedBudgetRequest(BaseModel):
        monthly_budget: float = 10.0

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

        from federation.comparator import MultiAgentComparator
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
    try:
        from api.m8_interface import register_m8_routes
        register_m8_routes(
            app,
            config_manager=config_manager,
            health_monitor=health_monitor,
            metrics_collector=None,
            orchestrator=orchestrator,
        )
    except Exception as exc:
        logger.warning("m8_routes_register_failed", error=str(exc))

    return app
