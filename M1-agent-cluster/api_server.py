"""
云汐内核 V6 - HTTP API 服务网关

灵感来源：OpenAI API / LangServe / FastAPI

提供 RESTful + WebSocket + SSE 三种接口：
- POST /api/v1/chat           同步对话
- POST /api/v1/chat/stream    SSE 流式对话
- WS   /api/v1/ws             WebSocket 实时对话
- GET  /health                存活检查
- GET  /ready                 就绪检查
- GET  /metrics               Prometheus 指标
- GET  /diagnose              全量诊断
- POST /feedback              提交反馈
- GET  /agents                列出 Agent
- GET  /config                获取配置

技术栈：FastAPI + Uvicorn
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

import structlog

logger = structlog.get_logger(__name__)

# 惰性导入 FastAPI，避免未安装时导入错误
_fastapi_available = False
try:
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse, StreamingResponse
    _fastapi_available = True
except ImportError:
    pass


class APIServer:
    """API 服务网关"""

    def __init__(
        self,
        orchestrator: Any,
        health_monitor: Any | None = None,
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        if not _fastapi_available:
            raise ImportError(
                "FastAPI is required for APIServer. "
                "Install it with: pip install fastapi uvicorn"
            )

        self._orchestrator = orchestrator
        self._health = health_monitor
        self.host = host
        self.port = port
        self._logger = logger.bind(service="api_server")
        self._app = self._build_app()
        self._server_task: asyncio.Task[None] | None = None

    def _build_app(self) -> "FastAPI":
        """构建 FastAPI 应用"""
        app = FastAPI(
            title="云汐内核 API",
            description="云汐多 Agent 集群调度系统 HTTP API",
            version="6.0.0",
        )

        # ── 对话接口 ────────────────────────────────────

        @app.post("/api/v1/chat")
        async def chat(request: Request) -> JSONResponse:
            """同步对话"""
            body = await request.json()
            user_input = body.get("user_input", "")
            trace_id = body.get("trace_id")
            use_llm = body.get("use_llm", False)
            use_vector_memory = body.get("use_vector_memory", True)

            result = await self._orchestrator.process(
                user_input=user_input,
                trace_id=trace_id,
                use_llm=use_llm,
                use_vector_memory=use_vector_memory,
            )
            return JSONResponse(content=result)

        @app.post("/api/v1/chat/stream")
        async def chat_stream(request: Request) -> StreamingResponse:
            """SSE 流式对话"""
            body = await request.json()
            user_input = body.get("user_input", "")
            trace_id = body.get("trace_id")
            use_llm = body.get("use_llm", False)
            use_vector_memory = body.get("use_vector_memory", True)

            async def event_generator() -> AsyncIterator[str]:
                async for chunk in self._orchestrator.process_stream(
                    user_input=user_input,
                    trace_id=trace_id,
                    use_llm=use_llm,
                    use_vector_memory=use_vector_memory,
                ):
                    data = json.dumps(chunk.to_dict(), ensure_ascii=False)
                    yield f"data: {data}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
            )

        # ── WebSocket ───────────────────────────────────

        @app.websocket("/api/v1/ws")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            """WebSocket 实时对话"""
            await websocket.accept()
            self._logger.info("websocket_connected", client=websocket.client)

            try:
                while True:
                    message = await websocket.receive_text()
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        await websocket.send_json({"error": "Invalid JSON"})
                        continue

                    user_input = data.get("user_input", "")
                    trace_id = data.get("trace_id")

                    async for chunk in self._orchestrator.process_stream(
                        user_input=user_input,
                        trace_id=trace_id,
                    ):
                        await websocket.send_json(chunk.to_dict())

                    await websocket.send_json({"chunk_type": "done", "done": True})
            except WebSocketDisconnect:
                self._logger.info("websocket_disconnected")
            except Exception as exc:
                self._logger.error("websocket_error", error=str(exc))
                await websocket.close()

        # ── 健康与监控 ──────────────────────────────────

        @app.get("/health")
        async def health() -> JSONResponse:
            """存活检查（标准格式）

            返回格式：
            {"code": 0, "message": "ok", "data": {"status": "healthy"}}
            """
            status = "healthy"
            if self._health:
                live = await self._health.liveness()
                if live.status == "up":
                    status = "healthy"
                elif live.status == "degraded":
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
            if self._health:
                status = await self._health.overall_status()
                code = 200 if status["status"] in ("up", "degraded") else 503
                return JSONResponse(content=status, status_code=code)
            return JSONResponse(content={"status": "up"})

        @app.get("/metrics")
        async def metrics() -> StreamingResponse:
            """Prometheus 指标"""
            if self._health:
                prom = await self._health.to_prometheus()
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
            diag = self._orchestrator.diagnose()
            return JSONResponse(content=diag)

        # ── 反馈与配置 ──────────────────────────────────

        @app.post("/feedback")
        async def feedback(request: Request) -> JSONResponse:
            """提交反馈"""
            body = await request.json()
            self._orchestrator.submit_feedback(
                trace_id=body.get("trace_id", ""),
                agent_id=body.get("agent_id", ""),
                intent=body.get("intent", ""),
                rating=body.get("rating", 0),
                comment=body.get("comment", ""),
            )
            return JSONResponse(content={"status": "feedback_received"})

        @app.get("/agents")
        async def list_agents() -> JSONResponse:
            """列出 Agent"""
            agents = self._orchestrator.discover_agents("", top_k=100)
            return JSONResponse(content={
                "agents": [
                    {
                        "agent_id": a.agent_id if hasattr(a, "agent_id") else str(a),
                        "capabilities": a.capabilities if hasattr(a, "capabilities") else [],
                    }
                    for a in agents
                ]
            })

        @app.get("/config")
        async def get_config() -> JSONResponse:
            """获取配置"""
            return JSONResponse(content=self._orchestrator._config.to_dict())

        # ── A2A Agent Discovery ─────────────────────────

        @app.get("/.well-known/agent-card.json")
        async def agent_discovery() -> JSONResponse:
            """A2A Protocol v1.0 Agent Discovery 端点

            返回当前节点暴露的所有 AgentCard。
            """
            try:
                agents = self._orchestrator.discover_agents("", top_k=100)
                cards = []
                for a in agents:
                    if hasattr(a, "to_dict"):
                        cards.append(a.to_dict())
                    else:
                        cards.append({
                            "agent_id": getattr(a, "agent_id", str(a)),
                            "capabilities": getattr(a, "capabilities", []),
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

        return app

    # ── 启动与关闭 ──────────────────────────────────────

    async def start(self) -> None:
        """启动 HTTP 服务器"""
        import uvicorn
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(server.serve())
        self._logger.info("api_server_started", host=self.host, port=self.port)

    async def stop(self) -> None:
        """关闭 HTTP 服务器"""
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        self._logger.info("api_server_stopped")
