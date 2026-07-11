"""M11 MCP Bus - 适配器基类.

定义所有外部系统适配器的通用接口和基础功能，
包括：注册到总线、心跳上报、工具列表维护、
MCP JSON-RPC 端点、FastAPI 服务启动等。
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware


class BaseMcpAdapter:
    """MCP 适配器基类.

    所有外部系统适配器都需要继承此类，实现以下核心方法：
    - get_tools(): 返回工具列表
    - call_tool(name, args): 调用指定工具

    基类提供以下通用功能：
    - register_to_bus(): 注册到 M11 总线
    - start_heartbeat(interval): 启动心跳线程
    - stop(): 停止心跳和服务
    - run_server(port, host): 启动 FastAPI MCP 服务
    """

    # 子类可覆盖的类属性
    adapter_name: str = "base"
    adapter_description: str = "MCP 适配器基类"

    def __init__(
        self,
        bus_url: str = "http://localhost:8011",
        server_name: str = "",
        server_endpoint: Optional[str] = None,
    ) -> None:
        """初始化适配器.

        Args:
            bus_url: M11 总线地址
            server_name: 注册到总线的服务名称（默认使用 adapter_name）
            server_endpoint: 本适配器的 MCP 端点地址（总线回调地址）
        """
        self.bus_url = bus_url.rstrip("/")
        self.server_name = server_name or self.adapter_name
        self.server_endpoint = server_endpoint or ""

        # 注册信息
        self._server_id: Optional[int] = None
        self._api_key: str = ""

        # 心跳相关
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_interval: int = 15  # 秒

        # FastAPI 应用（延迟构建）
        self._app: Optional[FastAPI] = None
        self._uvicorn_config: Optional[uvicorn.Config] = None
        self._uvicorn_server: Optional[uvicorn.Server] = None

    # ============================================================
    # 需要子类实现的方法
    # ============================================================

    def get_tools(self) -> List[Dict[str, Any]]:
        """获取工具列表.

        子类必须重写此方法，返回 MCP 标准格式的工具列表。
        每个工具包含：name, description, inputSchema。

        Returns:
            工具列表，每项格式：
            {
                "name": "tool_name",
                "description": "工具描述",
                "inputSchema": {"type": "object", "properties": {...}}
            }
        """
        raise NotImplementedError("子类必须实现 get_tools 方法")

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用指定工具.

        子类必须重写此方法，根据工具名执行对应操作。

        Args:
            name: 工具名称
            args: 工具参数

        Returns:
            调用结果字典，MCP 标准格式：
            {
                "content": [{"type": "text", "text": "..."}]
            }

        Raises:
            ValueError: 工具不存在或调用失败
            RuntimeError: 调用异常
        """
        raise NotImplementedError("子类必须实现 call_tool 方法")

    # ============================================================
    # 总线注册
    # ============================================================

    def register_to_bus(self) -> Dict[str, Any]:
        """注册到 M11 总线.

        调用总线的 /api/admin/servers/register 接口注册服务。

        Returns:
            注册结果，包含 server 和 api_key

        Raises:
            RuntimeError: 注册失败
        """
        if not self.server_endpoint:
            raise RuntimeError("server_endpoint 未设置，无法注册到总线")

        health_check_url = self.server_endpoint.replace("/mcp", "/health")

        payload = {
            "name": self.server_name,
            "description": self.adapter_description,
            "transport_type": "http",
            "endpoint": self.server_endpoint,
            "health_check_url": health_check_url,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{self.bus_url}/api/admin/servers/register",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                err_data = e.response.json()
                detail = err_data.get("detail", err_data.get("message", ""))
            except Exception:
                detail = e.response.text
            raise RuntimeError(f"注册到总线失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"注册到总线网络错误: {str(e)}") from e

        server_info = data.get("server", {})
        self._server_id = server_info.get("id")
        self._api_key = data.get("api_key", "")

        print(f"[{self.server_name}] 注册到总线成功，server_id={self._server_id}")
        return data

    # ============================================================
    # 心跳管理
    # ============================================================

    def start_heartbeat(self, interval: int = 15) -> None:
        """启动心跳线程.

        定期向总线上报心跳，维持 online 状态。

        Args:
            interval: 心跳间隔（秒）
        """
        if self._server_id is None:
            print(f"[{self.server_name}] 警告：未注册到总线，跳过心跳启动")
            return

        self._heartbeat_interval = interval
        self._heartbeat_stop.clear()

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name=f"{self.server_name}-heartbeat",
        )
        self._heartbeat_thread.start()
        print(f"[{self.server_name}] 心跳线程已启动，间隔 {interval}s")

    def _heartbeat_loop(self) -> None:
        """心跳循环（后台线程）."""
        while not self._heartbeat_stop.is_set():
            try:
                self._send_heartbeat()
            except Exception as e:
                print(f"[{self.server_name}] 心跳上报失败: {e}")

            # 等待间隔时间，可被 stop 中断
            self._heartbeat_stop.wait(self._heartbeat_interval)

    def _send_heartbeat(self) -> None:
        """发送单次心跳."""
        if not self.bus_url or self._server_id is None:
            return

        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{self.bus_url}/api/admin/servers/{self._server_id}/heartbeat",
                json={"status": "online"},
            )
            response.raise_for_status()

    # ============================================================
    # FastAPI 应用构建
    # ============================================================

    def _build_app(self) -> FastAPI:
        """构建 FastAPI 应用.

        创建包含 MCP JSON-RPC 端点和健康检查的 FastAPI 应用。

        Returns:
            FastAPI 应用实例
        """
        app = FastAPI(
            title=f"{self.server_name} MCP Adapter",
            description=self.adapter_description,
            version="0.1.0",
            docs_url="/docs",
        )

        # CORS
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # MCP JSON-RPC 端点
        @app.post("/mcp", summary="MCP JSON-RPC 2.0 端点")
        async def mcp_endpoint(request: Request) -> Dict[str, Any]:
            try:
                body = await request.json()
            except Exception:
                return _jsonrpc_error(None, -32700, "Parse error")

            jsonrpc = body.get("jsonrpc")
            method = body.get("method")
            params = body.get("params", {})
            request_id = body.get("id")

            if jsonrpc != "2.0":
                return _jsonrpc_error(request_id, -32600, "Invalid Request: jsonrpc must be 2.0")

            is_notification = request_id is None

            try:
                if method == "initialize":
                    result = self._handle_initialize(params)
                elif method == "notifications/initialized":
                    return {}
                elif method == "tools/list":
                    result = self._handle_tools_list(params)
                elif method == "tools/call":
                    result = self._handle_tools_call(params)
                else:
                    if is_notification:
                        return {}
                    return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")
            except Exception as e:
                if is_notification:
                    return {}
                return _jsonrpc_error(request_id, -32603, f"Internal error: {str(e)}")

            if is_notification:
                return {}

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }

        # 健康检查
        @app.get("/health", summary="健康检查")
        async def health() -> Dict[str, Any]:
            return {
                "status": "ok",
                "module": self.server_name,
                "version": "0.1.0",
                "timestamp": time.time(),
            }

        # 根路径
        @app.get("/", summary="服务信息")
        async def root() -> Dict[str, Any]:
            return {
                "status": "ok",
                "module": self.server_name,
                "description": self.adapter_description,
                "version": "0.1.0",
                "endpoints": {
                    "mcp": "/mcp",
                    "health": "/health",
                    "docs": "/docs",
                },
            }

        self._app = app
        return app

    # ============================================================
    # MCP 协议处理器
    # ============================================================

    def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理 initialize 方法.

        Args:
            params: 初始化参数

        Returns:
            初始化结果
        """
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {
                    "listChanges": True,
                },
            },
            "serverInfo": {
                "name": self.server_name,
                "version": "0.1.0",
            },
        }

    def _handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理 tools/list 方法.

        Args:
            params: 参数

        Returns:
            工具列表
        """
        tools = self.get_tools()
        return {"tools": tools}

    def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理 tools/call 方法.

        Args:
            params: 调用参数，包含 name 和 arguments

        Returns:
            调用结果
        """
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if not tool_name:
            raise ValueError("缺少工具名称参数")

        return self.call_tool(tool_name, arguments)

    # ============================================================
    # 结果包装辅助
    # ============================================================

    def _wrap_result(self, result: Any) -> Dict[str, Any]:
        """将结果包装为 MCP 标准 content 格式.

        Args:
            result: 原始结果数据

        Returns:
            MCP 标准格式的调用结果
        """
        if isinstance(result, dict) and "content" in result:
            return result

        result_text = (
            json.dumps(result, ensure_ascii=False)
            if not isinstance(result, str)
            else result
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": result_text,
                }
            ],
        }

    # ============================================================
    # 服务运行与停止
    # ============================================================

    def run_server(self, port: int = 8000, host: str = "0.0.0.0") -> None:
        """启动适配器的 MCP 服务（阻塞）.

        Args:
            port: 监听端口
            host: 监听地址
        """
        if self._app is None:
            self._build_app()

        assert self._app is not None

        print(f"[{self.server_name}] 启动 MCP 适配器服务，监听 {host}:{port}")

        config = uvicorn.Config(
            app=self._app,
            host=host,
            port=port,
            log_level="info",
        )
        self._uvicorn_config = config
        self._uvicorn_server = uvicorn.Server(config)
        self._uvicorn_server.run()

    def stop(self) -> None:
        """停止适配器（心跳 + 服务）."""
        # 停止心跳
        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)

        # 停止 uvicorn 服务
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True

        print(f"[{self.server_name}] 适配器已停止")


# ============================================================
# 辅助函数
# ============================================================

def _jsonrpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    """构建 JSON-RPC 错误响应.

    Args:
        request_id: 请求 ID
        code: 错误码
        message: 错误信息

    Returns:
        JSON-RPC 错误响应字典
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
