"""M11 MCP Bus - 请求路由转发服务.

负责将工具调用请求路由到对应的 MCP 服务器执行，
支持同步调用和异步调用，包含超时控制和错误处理。
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from .cache import mcp_cache
from .monitor import mcp_monitor
from .registry import mcp_registry


class McpRouter:
    """MCP 请求路由转发器.

    根据工具名找到目标服务器，转发 MCP 协议请求，
    处理超时、错误重试等逻辑。
    """

    # 默认超时时间（秒）
    DEFAULT_TIMEOUT = 30.0
    # 异步调用状态存储
    _async_calls: Dict[str, Dict[str, Any]] = {}

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """初始化路由转发器.

        Args:
            timeout: 默认超时时间（秒）
        """
        self._default_timeout = timeout

    # --------------------------------------------------------
    # 同步调用
    # --------------------------------------------------------

    def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        consumer: str = "",
        use_cache: bool = True,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """调用工具（同步）.

        根据工具名找到目标服务器，发送 MCP tools/call 请求，
        记录调用日志，返回执行结果。

        Args:
            tool_name: 工具全名（格式：{server_name}.{tool_name}）
            arguments: 调用参数
            consumer: 调用方标识
            use_cache: 是否使用结果缓存
            timeout: 超时时间（秒），None 则使用默认值

        Returns:
            调用结果字典：
            {
                "success": bool,
                "result": Any,          # 成功时的结果
                "error": str,           # 失败时的错误信息
                "duration_ms": int,     # 耗时（毫秒）
                "tool_name": str,
                "call_id": int,         # 数据库记录 ID
                "from_cache": bool,     # 是否来自缓存
            }
        """
        arguments = arguments or {}
        call_timeout = timeout or self._default_timeout
        start_time = time.time()
        from_cache = False

        # 1. 检查结果缓存
        if use_cache:
            args_hash = mcp_cache.make_args_hash(arguments)
            cached_result = mcp_cache.get_tool_result_cache(tool_name, args_hash)
            if cached_result is not None:
                duration_ms = int((time.time() - start_time) * 1000)
                # 记录缓存命中（不写入数据库，避免干扰统计）
                return {
                    "success": True,
                    "result": cached_result,
                    "error": None,
                    "duration_ms": duration_ms,
                    "tool_name": tool_name,
                    "call_id": 0,
                    "from_cache": True,
                }

        # 2. 查找工具和所属服务器
        tool_info = mcp_registry.get_tool_by_name(tool_name)
        if not tool_info:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"工具不存在: {tool_name}"
            call_id = mcp_monitor.record_call(
                tool_name=tool_name,
                status="failed",
                duration_ms=duration_ms,
                error=error_msg,
                consumer=consumer,
            )
            return {
                "success": False,
                "result": None,
                "error": error_msg,
                "duration_ms": duration_ms,
                "tool_name": tool_name,
                "call_id": call_id,
                "from_cache": False,
            }

        tool, server = tool_info

        # 3. 检查服务器状态
        if server.status != "online":
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"服务器不在线: {server.name} (状态: {server.status})"
            call_id = mcp_monitor.record_call(
                tool_name=tool_name,
                status="failed",
                duration_ms=duration_ms,
                error=error_msg,
                server_id=server.id,
                consumer=consumer,
            )
            return {
                "success": False,
                "result": None,
                "error": error_msg,
                "duration_ms": duration_ms,
                "tool_name": tool_name,
                "call_id": call_id,
                "from_cache": False,
            }

        # 4. 提取原始工具名（去除服务器前缀）
        raw_tool_name = self._extract_raw_tool_name(tool_name, server.name)

        # 5. 发送 MCP 请求
        try:
            result_data = self._send_mcp_call(
                server=server,
                tool_name=raw_tool_name,
                arguments=arguments,
                timeout=call_timeout,
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # 6. 写入缓存
            if use_cache:
                args_hash = mcp_cache.make_args_hash(arguments)
                mcp_cache.set_tool_result_cache(tool_name, args_hash, result_data)

            # 7. 记录成功调用
            response_snippet = json.dumps(result_data, ensure_ascii=False)[:1000]
            request_snippet = json.dumps(arguments, ensure_ascii=False)[:500]
            call_id = mcp_monitor.record_call(
                tool_name=tool_name,
                status="success",
                duration_ms=duration_ms,
                server_id=server.id,
                consumer=consumer,
                request_snippet=request_snippet,
                response_snippet=response_snippet,
            )

            return {
                "success": True,
                "result": result_data,
                "error": None,
                "duration_ms": duration_ms,
                "tool_name": tool_name,
                "call_id": call_id,
                "from_cache": False,
            }

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            call_id = mcp_monitor.record_call(
                tool_name=tool_name,
                status="failed",
                duration_ms=duration_ms,
                error=error_msg,
                server_id=server.id,
                consumer=consumer,
            )
            return {
                "success": False,
                "result": None,
                "error": error_msg,
                "duration_ms": duration_ms,
                "tool_name": tool_name,
                "call_id": call_id,
                "from_cache": False,
            }

    # --------------------------------------------------------
    # 异步调用
    # --------------------------------------------------------

    def call_tool_async(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        consumer: str = "",
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """异步调用工具.

        立即返回 call_id，实际执行在后台进行。
        可通过 get_async_result 查询执行状态。

        注意：简单实现使用内存存储异步调用状态，
        生产环境建议使用消息队列。

        Args:
            tool_name: 工具全名
            arguments: 调用参数
            consumer: 调用方标识
            use_cache: 是否使用结果缓存

        Returns:
            {
                "async_id": str,     # 异步调用 ID
                "status": str,       # "pending"
                "tool_name": str,
            }
        """
        arguments = arguments or {}
        async_id = "async_" + secrets.token_hex(12)

        # 初始状态
        self._async_calls[async_id] = {
            "status": "pending",
            "tool_name": tool_name,
            "arguments": arguments,
            "consumer": consumer,
            "use_cache": use_cache,
            "result": None,
            "error": None,
            "duration_ms": 0,
            "created_at": time.time(),
        }

        # 在后台线程中执行（简单实现）
        import threading

        def _execute():
            start = time.time()
            try:
                result = self.call_tool(
                    tool_name=tool_name,
                    arguments=arguments,
                    consumer=consumer,
                    use_cache=use_cache,
                )
                self._async_calls[async_id]["status"] = (
                    "completed" if result["success"] else "failed"
                )
                self._async_calls[async_id]["result"] = result.get("result")
                self._async_calls[async_id]["error"] = result.get("error")
                self._async_calls[async_id]["call_id"] = result.get("call_id")
            except Exception as e:
                self._async_calls[async_id]["status"] = "failed"
                self._async_calls[async_id]["error"] = str(e)
            finally:
                self._async_calls[async_id]["duration_ms"] = int(
                    (time.time() - start) * 1000
                )
                self._async_calls[async_id]["completed_at"] = time.time()

        thread = threading.Thread(target=_execute, daemon=True)
        thread.start()

        return {
            "async_id": async_id,
            "status": "pending",
            "tool_name": tool_name,
        }

    def get_async_result(self, async_id: str) -> Optional[Dict[str, Any]]:
        """获取异步调用结果.

        Args:
            async_id: 异步调用 ID

        Returns:
            异步调用状态和结果，不存在则返回 None
        """
        call = self._async_calls.get(async_id)
        if not call:
            return None

        return {
            "async_id": async_id,
            "status": call["status"],
            "tool_name": call["tool_name"],
            "result": call.get("result"),
            "error": call.get("error"),
            "duration_ms": call.get("duration_ms", 0),
            "call_id": call.get("call_id", 0),
            "created_at": call.get("created_at"),
            "completed_at": call.get("completed_at"),
        }

    def cleanup_async_calls(self, max_age: int = 3600) -> int:
        """清理过期的异步调用记录.

        Args:
            max_age: 最大保留时间（秒）

        Returns:
            清理的记录数
        """
        now = time.time()
        expired_ids = [
            aid
            for aid, call in self._async_calls.items()
            if now - call.get("created_at", 0) > max_age
            and call["status"] in ("completed", "failed")
        ]
        for aid in expired_ids:
            del self._async_calls[aid]
        return len(expired_ids)

    # --------------------------------------------------------
    # 内部方法
    # --------------------------------------------------------

    def _extract_raw_tool_name(self, full_name: str, server_name: str) -> str:
        """从完整工具名中提取原始工具名.

        工具名格式：{server_name}.{tool_name}
        如果没有服务器前缀，直接返回原名。

        Args:
            full_name: 完整工具名
            server_name: 服务器名称

        Returns:
            原始工具名
        """
        prefix = f"{server_name}."
        if full_name.startswith(prefix):
            return full_name[len(prefix):]
        return full_name

    def _send_mcp_call(
        self,
        server: Any,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: float,
    ) -> Any:
        """发送 MCP tools/call 请求到目标服务器.

        Args:
            server: 服务器对象
            tool_name: 工具名称
            arguments: 调用参数
            timeout: 超时时间（秒）

        Returns:
            工具执行结果

        Raises:
            ValueError: 服务器配置错误
            httpx.HTTPError: HTTP 请求失败
            Exception: MCP 协议错误
        """
        if not server.endpoint:
            raise ValueError("服务器未配置端点地址")

        if server.transport_type != "http":
            raise ValueError(f"不支持的传输类型: {server.transport_type}")

        # 构建 MCP JSON-RPC 请求
        request_id = secrets.randbelow(100000)
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        headers = {"Content-Type": "application/json"}
        if server.api_key:
            headers["Authorization"] = f"Bearer {server.api_key}"

        with httpx.Client(timeout=timeout) as client:
            try:
                response = client.post(
                    server.endpoint,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.TimeoutException:
                raise Exception(f"调用超时: {tool_name} (服务器: {server.name})")
            except httpx.HTTPError as e:
                raise Exception(f"HTTP 请求失败: {str(e)}")

            try:
                data = response.json()
            except json.JSONDecodeError:
                raise Exception("响应解析失败: 无效的 JSON 格式")

        # 处理 MCP 响应
        if "error" in data:
            error = data["error"]
            code = error.get("code", -1)
            message = error.get("message", "未知错误")
            raise Exception(f"MCP 调用错误 (code={code}): {message}")

        if "result" not in data:
            raise Exception("响应格式错误: 缺少 result 字段")

        # MCP tools/call 的 result 可能是 {content: [...]} 格式
        result = data["result"]
        return self._normalize_mcp_result(result)

    def _normalize_mcp_result(self, result: Any) -> Any:
        """标准化 MCP 调用结果.

        MCP 协议中 tools/call 的返回格式为：
        {
            "content": [
                {"type": "text", "text": "..."}
            ]
        }

        这里提取实际内容，便于上层使用。

        Args:
            result: 原始 MCP 结果

        Returns:
            标准化后的结果
        """
        # 如果是字典且包含 content 数组，提取文本内容
        if isinstance(result, dict) and "content" in result:
            content = result["content"]
            if isinstance(content, list):
                # 提取所有 text 类型的内容
                texts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text" and "text" in item:
                            texts.append(item["text"])
                        elif "text" in item:
                            texts.append(item["text"])
                if len(texts) == 1:
                    # 尝试解析为 JSON
                    try:
                        return json.loads(texts[0])
                    except (json.JSONDecodeError, TypeError):
                        return texts[0]
                elif len(texts) > 1:
                    return texts

        # 其他情况直接返回
        return result


# ============================================================
# 单例实例
# ============================================================

mcp_router = McpRouter()
