"""M11 MCP Bus - 总线客户端 SDK.

一个轻量级的 M11 总线 Python 客户端，封装了所有 REST API 调用，
供其他模块（如 M7 积木平台）方便地与 M11 总线交互。

使用 httpx 做 HTTP 调用，支持同步和异步调用模式。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx


class McpBusClient:
    """M11 总线客户端 SDK.

    封装 M11 总线的所有 REST API，提供简洁的 Python 接口。
    支持工具列表查询、工具调用（同步/异步）、服务器管理、
    健康检查等功能。

    示例::

        client = McpBusClient("http://localhost:8011", api_key="m11_xxx")
        tools = client.list_tools(keyword="search")
        result = client.call_tool("server_name.tool_name", {"arg": "value"})
    """

    # 默认超时时间（秒）
    DEFAULT_TIMEOUT = 30.0
    # 异步调用默认轮询间隔（秒）
    DEFAULT_POLL_INTERVAL = 0.5

    def __init__(
        self,
        bus_url: str = "http://localhost:8011",
        api_key: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """初始化 M11 总线客户端.

        Args:
            bus_url: M11 总线服务地址
            api_key: API 密钥（可选，部分接口需要）
            timeout: 默认请求超时时间（秒）
        """
        self._bus_url = bus_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    # ============================================================
    # 工具管理
    # ============================================================

    def list_tools(
        self,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        server_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """获取工具列表.

        工具名格式：``{server_name}.{tool_name}``

        Args:
            category: 按分类过滤
            keyword: 关键词搜索（匹配名称和描述）
            server_id: 按服务器 ID 过滤
            page: 页码，从 1 开始
            page_size: 每页数量

        Returns:
            工具列表响应字典：
            {
                "items": [...],        # 工具列表
                "total": int,          # 总数
                "page": int,           # 当前页
                "page_size": int,      # 每页数量
                "categories": [...],   # 可用分类列表
            }

        Raises:
            httpx.HTTPError: HTTP 请求失败
            ValueError: 响应解析失败
        """
        params: Dict[str, Any] = {
            "page": page,
            "page_size": page_size,
        }
        if category:
            params["category"] = category
        if keyword:
            params["keyword"] = keyword
        if server_id is not None:
            params["server_id"] = server_id

        return self._request("GET", "/api/v1/tools", params=params)

    def get_tool(self, tool_name: str) -> Dict[str, Any]:
        """获取工具详情.

        Args:
            tool_name: 工具全名（格式：{server_name}.{tool_name}）

        Returns:
            工具详情字典：
            {
                "id": int,
                "server_id": int,
                "server_name": str,
                "name": str,
                "description": str,
                "category": str,
                "input_schema": {...},
                "cached_at": datetime,
            }

        Raises:
            httpx.HTTPStatusError: 工具不存在（404）或请求失败
        """
        return self._request("GET", f"/api/v1/tools/{tool_name}")

    def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        consumer: str = "sdk-client",
    ) -> Dict[str, Any]:
        """调用工具（同步）.

        阻塞等待工具执行完成，返回执行结果。

        Args:
            tool_name: 工具全名（格式：{server_name}.{tool_name}）
            arguments: 调用参数字典
            consumer: 调用方标识，用于日志统计

        Returns:
            调用结果字典：
            {
                "tool_name": str,
                "success": bool,
                "result": Any,          # 成功时的结果
                "duration_ms": int,     # 耗时（毫秒）
                "call_id": int,         # 调用记录 ID
                "from_cache": bool,     # 是否来自缓存
            }

        Raises:
            httpx.HTTPStatusError: HTTP 错误（如 502 调用失败）
            httpx.HTTPError: 网络错误
        """
        arguments = arguments or {}
        payload = {
            "arguments": arguments,
            "consumer": consumer,
        }
        return self._request(
            "POST",
            f"/api/v1/tools/{tool_name}/call",
            json=payload,
        )

    def call_tool_async(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        consumer: str = "sdk-client",
    ) -> Dict[str, Any]:
        """调用工具（异步，返回 call_id）.

        立即返回异步调用 ID，实际执行在后台进行。
        可通过 :meth:`get_async_result` 查询执行状态和结果。

        Args:
            tool_name: 工具全名（格式：{server_name}.{tool_name}）
            arguments: 调用参数字典
            consumer: 调用方标识

        Returns:
            异步调用信息：
            {
                "async_id": str,    # 异步调用 ID
                "status": str,      # "pending"
                "tool_name": str,
            }

        Raises:
            httpx.HTTPError: 请求失败
        """
        arguments = arguments or {}
        # 使用管理接口的异步调用
        payload = {
            "tool_name": tool_name,
            "arguments": arguments,
            "consumer": consumer,
        }
        return self._request(
            "POST",
            "/api/admin/calls/async",
            json=payload,
        )

    def get_async_result(self, call_id: str) -> Optional[Dict[str, Any]]:
        """获取异步调用结果.

        Args:
            call_id: 异步调用 ID（async_id）

        Returns:
            异步调用状态和结果，不存在则返回 None：
            {
                "async_id": str,
                "status": str,          # "pending" / "completed" / "failed"
                "tool_name": str,
                "result": Any,          # 成功时的结果
                "error": str,           # 失败时的错误信息
                "duration_ms": int,
                "call_id": int,
                "created_at": float,
                "completed_at": float,
            }
        """
        try:
            return self._request("GET", f"/api/admin/calls/async/{call_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    def wait_for_async_result(
        self,
        call_id: str,
        timeout: float = 60.0,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> Optional[Dict[str, Any]]:
        """等待异步调用完成.

        轮询查询异步调用结果，直到完成或超时。

        Args:
            call_id: 异步调用 ID
            timeout: 最大等待时间（秒）
            poll_interval: 轮询间隔（秒）

        Returns:
            最终调用结果，超时则返回最后一次查询状态
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            result = self.get_async_result(call_id)
            if result is None:
                return None
            if result.get("status") in ("completed", "failed"):
                return result
            time.sleep(poll_interval)
        # 超时，返回最后一次状态
        return self.get_async_result(call_id)

    # ============================================================
    # 服务器管理
    # ============================================================

    def list_servers(
        self,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """获取服务器列表.

        Args:
            status: 按状态过滤（online/offline）
            page: 页码
            page_size: 每页数量

        Returns:
            服务器列表响应：
            {
                "items": [...],
                "total": int,
                "page": int,
                "page_size": int,
            }
        """
        params: Dict[str, Any] = {
            "page": page,
            "page_size": page_size,
        }
        if status:
            params["status"] = status

        return self._request("GET", "/api/admin/servers", params=params)

    def get_server(self, server_id: int) -> Dict[str, Any]:
        """获取服务器详情.

        Args:
            server_id: 服务器 ID

        Returns:
            服务器详情字典
        """
        return self._request("GET", f"/api/admin/servers/{server_id}")

    def register_server(
        self,
        name: str,
        endpoint: str,
        description: str = "",
        transport_type: str = "http",
        health_check_url: str = "",
    ) -> Dict[str, Any]:
        """注册新的 MCP 服务器.

        Args:
            name: 服务器名称（唯一）
            endpoint: 服务端点地址
            description: 服务描述
            transport_type: 传输类型（http/sse/stdio）
            health_check_url: 健康检查地址

        Returns:
            注册结果，包含 server 和 api_key
        """
        payload = {
            "name": name,
            "description": description,
            "transport_type": transport_type,
            "endpoint": endpoint,
            "health_check_url": health_check_url,
        }
        return self._request("POST", "/api/admin/servers/register", json=payload)

    def delete_server(self, server_id: int) -> Dict[str, Any]:
        """删除服务器.

        Args:
            server_id: 服务器 ID

        Returns:
            删除结果
        """
        return self._request("DELETE", f"/api/admin/servers/{server_id}")

    def refresh_tools(self, force: bool = False) -> Dict[str, Any]:
        """手动刷新所有在线服务器的工具列表.

        Args:
            force: 是否强制刷新（忽略缓存间隔）

        Returns:
            刷新结果统计
        """
        payload = {"force": force}
        return self._request("POST", "/api/admin/tools/refresh", json=payload)

    # ============================================================
    # 健康检查
    # ============================================================

    def health(self) -> Dict[str, Any]:
        """健康检查.

        Returns:
            健康状态：
            {
                "status": str,         # "healthy"
                "module": str,         # "m11"
                "version": str,
                "timestamp": datetime,
                "details": {...},
            }
        """
        return self._request("GET", "/health")

    def metrics(self) -> Dict[str, Any]:
        """获取性能指标.

        Returns:
            性能指标字典，包含服务器数、工具数、调用统计等
        """
        return self._request("GET", "/metrics")

    # ============================================================
    # MCP JSON-RPC 直接调用
    # ============================================================

    def mcp_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """直接调用 MCP JSON-RPC 端点.

        可以用来调用 MCP 协议的标准方法，如 initialize、tools/list、tools/call。

        Args:
            method: MCP 方法名
            params: 方法参数
            request_id: 请求 ID（默认自动生成）

        Returns:
            MCP 响应的 result 部分

        Raises:
            Exception: MCP 协议错误
        """
        import secrets

        params = params or {}
        if request_id is None:
            request_id = secrets.randbelow(100000)

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        response = self._request("POST", "/mcp", json=payload)

        if "error" in response:
            error = response["error"]
            code = error.get("code", -1)
            message = error.get("message", "未知错误")
            raise Exception(f"MCP 错误 (code={code}): {message}")

        return response.get("result", {})

    # ============================================================
    # 内部方法
    # ============================================================

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """发送 HTTP 请求.

        Args:
            method: HTTP 方法
            path: API 路径
            params: URL 查询参数
            json: 请求体 JSON

        Returns:
            响应 JSON 字典

        Raises:
            httpx.HTTPError: HTTP 请求失败
            ValueError: 响应解析失败
        """
        url = f"{self._bus_url}{path}"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            response = self._client.request(
                method=method,
                url=url,
                params=params,
                json=json,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # 尝试提取错误详情
            try:
                err_data = e.response.json()
                detail = err_data.get("detail", err_data.get("message", str(e)))
            except Exception:
                detail = e.response.text
            raise httpx.HTTPStatusError(
                f"{method} {path} 失败（{e.response.status_code}）: {detail}",
                request=e.request,
                response=e.response,
            ) from e
        except httpx.TimeoutException as e:
            raise httpx.TimeoutException(
                f"{method} {path} 请求超时（>{self._timeout}s）",
                request=e.request if hasattr(e, "request") else None,
            ) from e

        try:
            return response.json()
        except Exception as e:
            raise ValueError(f"响应解析失败: {e}") from e

    def close(self) -> None:
        """关闭客户端，释放资源."""
        self._client.close()

    def __enter__(self) -> "McpBusClient":
        """上下文管理器入口."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器出口，自动关闭连接."""
        self.close()
