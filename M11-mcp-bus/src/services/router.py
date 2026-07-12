"""M11 MCP Bus - 请求路由转发服务.

负责将工具调用请求路由到对应的 MCP 服务器执行，
支持同步调用和异步调用，包含超时控制、错误重试、
熔断机制等可靠性保障。
"""

from __future__ import annotations

import json
import secrets
import time
from threading import Lock
from typing import Any, Dict, Optional, Tuple

import httpx

from ..config import get_settings
from .audit import audit_logger
from .cache import mcp_cache
from .monitor import mcp_monitor
from .registry import mcp_registry


# ============================================================
# 熔断器
# ============================================================

class CircuitBreaker:
    """熔断器 - 单服务粒度.

    实现经典的熔断器模式：Closed → Open → Half-Open
    - Closed: 正常状态，所有请求放行
    - Open: 熔断状态，所有请求快速失败
    - Half-Open: 半开状态，放行少量请求探测服务是否恢复

    每个 MCP 服务器独立维护一个熔断器状态。
    """

    # 状态枚举
    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"

    def __init__(
        self,
        server_id: int,
        fail_threshold: int = 5,
        open_duration: float = 30.0,
        half_open_limit: int = 1,
    ) -> None:
        """初始化熔断器.

        Args:
            server_id: 所属服务器 ID
            fail_threshold: 连续失败阈值，达到后熔断
            open_duration: 熔断持续时间（秒）
            half_open_limit: 半开状态放行请求数
        """
        self.server_id = server_id
        self._fail_threshold = fail_threshold
        self._open_duration = open_duration
        self._half_open_limit = half_open_limit

        self._state = self.STATE_CLOSED
        self._consecutive_failures = 0
        self._open_at: float = 0.0
        self._half_open_count = 0
        self._lock = Lock()

    # --------------------------------------------------------
    # 状态查询
    # --------------------------------------------------------

    @property
    def state(self) -> str:
        """当前熔断器状态."""
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    @property
    def consecutive_failures(self) -> int:
        """连续失败次数."""
        with self._lock:
            return self._consecutive_failures

    def can_execute(self) -> bool:
        """判断是否允许执行请求.

        Returns:
            True 表示可以执行，False 表示被熔断
        """
        with self._lock:
            if self._state == self.STATE_CLOSED:
                return True

            if self._state == self.STATE_OPEN:
                # 检查是否到了半开时间
                if self._maybe_transition_to_half_open():
                    self._half_open_count = 0

            if self._state == self.STATE_HALF_OPEN:
                # 半开状态下限制请求数
                if self._half_open_count < self._half_open_limit:
                    self._half_open_count += 1
                    return True
                return False

            return False

    # --------------------------------------------------------
    # 结果反馈
    # --------------------------------------------------------

    def record_success(self) -> None:
        """记录一次成功调用."""
        with self._lock:
            if self._state == self.STATE_HALF_OPEN:
                # 半开状态下成功，恢复到关闭状态
                self._state = self.STATE_CLOSED
                self._consecutive_failures = 0
                self._half_open_count = 0
            elif self._state == self.STATE_CLOSED:
                # 正常状态下成功，重置连续失败计数
                self._consecutive_failures = 0

    def record_failure(self) -> None:
        """记录一次失败调用."""
        with self._lock:
            self._consecutive_failures += 1

            if self._state == self.STATE_HALF_OPEN:
                # 半开状态下失败，重新进入熔断
                self._state = self.STATE_OPEN
                self._open_at = time.time()
                self._half_open_count = 0
            elif (
                self._state == self.STATE_CLOSED
                and self._consecutive_failures >= self._fail_threshold
            ):
                # 达到失败阈值，触发熔断
                self._state = self.STATE_OPEN
                self._open_at = time.time()

    # --------------------------------------------------------
    # 内部方法
    # --------------------------------------------------------

    def _maybe_transition_to_half_open(self) -> bool:
        """检查是否应该从 Open 转入 Half-Open 状态.

        注意：调用前需要持有 _lock。

        Returns:
            是否发生了状态转换
        """
        if self._state != self.STATE_OPEN:
            return False

        if time.time() - self._open_at >= self._open_duration:
            self._state = self.STATE_HALF_OPEN
            return True

        return False

    def get_status_dict(self) -> Dict[str, Any]:
        """获取熔断器状态字典.

        Returns:
            状态信息字典
        """
        with self._lock:
            self._maybe_transition_to_half_open()
            return {
                "server_id": self.server_id,
                "state": self._state,
                "consecutive_failures": self._consecutive_failures,
                "open_at": self._open_at if self._state != self.STATE_CLOSED else None,
                "fail_threshold": self._fail_threshold,
                "open_duration": self._open_duration,
            }


# ============================================================
# 熔断器管理器
# ============================================================

class CircuitBreakerManager:
    """熔断器管理器.

    为每个 MCP 服务器维护独立的熔断器实例。
    """

    def __init__(self) -> None:
        """初始化熔断器管理器."""
        self._settings = get_settings()
        self._breakers: Dict[int, CircuitBreaker] = {}
        self._lock = Lock()

    def get_breaker(self, server_id: int) -> CircuitBreaker:
        """获取指定服务器的熔断器.

        Args:
            server_id: 服务器 ID

        Returns:
            熔断器实例
        """
        with self._lock:
            if server_id not in self._breakers:
                self._breakers[server_id] = CircuitBreaker(
                    server_id=server_id,
                    fail_threshold=self._settings.circuit_breaker_fail_threshold,
                    open_duration=self._settings.circuit_breaker_open_duration,
                    half_open_limit=self._settings.circuit_breaker_half_open_limit,
                )
            return self._breakers[server_id]

    def get_all_status(self) -> list[Dict[str, Any]]:
        """获取所有熔断器状态.

        Returns:
            所有熔断器状态列表
        """
        with self._lock:
            return [b.get_status_dict() for b in self._breakers.values()]

    def reset(self, server_id: int) -> None:
        """重置指定服务器的熔断器.

        Args:
            server_id: 服务器 ID
        """
        with self._lock:
            self._breakers.pop(server_id, None)


# ============================================================
# 路由转发器
# ============================================================

class McpRouter:
    """MCP 请求路由转发器.

    根据工具名找到目标服务器，转发 MCP 协议请求，
    处理超时、错误重试、熔断等可靠性保障。
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
        self._settings = get_settings()
        self._circuit_breakers = CircuitBreakerManager()

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
        支持熔断和自动重试机制。

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
                "retried": int,         # 重试次数
                "circuit_breaker": str, # 熔断器状态
            }
        """
        arguments = arguments or {}
        call_timeout = timeout or self._default_timeout
        start_time = time.time()
        from_cache = False
        retried = 0

        # 1. 检查结果缓存
        if use_cache:
            args_hash = mcp_cache.make_args_hash(arguments)
            cached_result = mcp_cache.get_tool_result_cache(tool_name, args_hash)
            if cached_result is not None:
                duration_ms = int((time.time() - start_time) * 1000)
                # 审计日志：缓存命中的工具调用
                audit_logger.log_event(
                    event_type="tool.call",
                    actor=consumer or "api",
                    action="call",
                    resource=f"tool:{tool_name}",
                    metadata={
                        "tool_name": tool_name,
                        "status": "success",
                        "duration_ms": duration_ms,
                        "from_cache": True,
                        "consumer": consumer,
                    },
                    description=f"工具调用（缓存命中）: {tool_name}",
                )
                # 记录缓存命中（不写入数据库，避免干扰统计）
                return {
                    "success": True,
                    "result": cached_result,
                    "error": None,
                    "duration_ms": duration_ms,
                    "tool_name": tool_name,
                    "call_id": 0,
                    "from_cache": True,
                    "retried": 0,
                    "circuit_breaker": "n/a",
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
                "retried": 0,
                "circuit_breaker": "n/a",
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
                "retried": 0,
                "circuit_breaker": "n/a",
            }

        # 4. 检查熔断器状态
        breaker = self._circuit_breakers.get_breaker(server.id)
        if not breaker.can_execute():
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"服务器 {server.name} 已熔断 (状态: {breaker.state})，请稍后再试"
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
                "retried": 0,
                "circuit_breaker": breaker.state,
            }

        # 5. 提取原始工具名（去除服务器前缀）
        raw_tool_name = self._extract_raw_tool_name(tool_name, server.name)

        # 6. 发送 MCP 请求（带重试）
        max_attempts = self._settings.retry_max_attempts + 1  # 首次 + 重试次数
        base_delay_ms = self._settings.retry_base_delay_ms
        last_error: Optional[Exception] = None
        result_data = None
        is_retryable_error = False

        for attempt in range(max_attempts):
            try:
                result_data = self._send_mcp_call(
                    server=server,
                    tool_name=raw_tool_name,
                    arguments=arguments,
                    timeout=call_timeout,
                )
                # 成功，重置熔断器
                breaker.record_success()
                break
            except Exception as e:
                last_error = e
                # 判断是否可重试（网络错误或 5xx）
                is_retryable = self._is_retryable_error(e)
                is_retryable_error = is_retryable

                if is_retryable and attempt < max_attempts - 1:
                    # 指数退避等待
                    delay_ms = base_delay_ms * (2 ** attempt)
                    time.sleep(delay_ms / 1000.0)
                    retried += 1
                    continue
                else:
                    # 不可重试或已达最大重试次数
                    if is_retryable:
                        # 达到重试上限，记录失败并触发熔断器
                        breaker.record_failure()
                    break

        duration_ms = int((time.time() - start_time) * 1000)

        # 7. 处理结果
        if result_data is not None:
            # 写入缓存
            if use_cache:
                args_hash = mcp_cache.make_args_hash(arguments)
                mcp_cache.set_tool_result_cache(tool_name, args_hash, result_data)

            # 记录成功调用
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

            # 审计日志：工具调用成功
            audit_logger.log_event(
                event_type="tool.call",
                actor=consumer or "api",
                action="call",
                resource=f"tool:{tool_name}",
                metadata={
                    "tool_name": tool_name,
                    "status": "success",
                    "duration_ms": duration_ms,
                    "server_id": server.id,
                    "server_name": server.name,
                    "retried": retried,
                    "consumer": consumer,
                    "call_id": call_id,
                },
                description=f"工具调用成功: {tool_name}",
            )

            return {
                "success": True,
                "result": result_data,
                "error": None,
                "duration_ms": duration_ms,
                "tool_name": tool_name,
                "call_id": call_id,
                "from_cache": False,
                "retried": retried,
                "circuit_breaker": breaker.state,
            }
        else:
            # 调用失败
            error_msg = str(last_error) if last_error else "未知错误"
            call_id = mcp_monitor.record_call(
                tool_name=tool_name,
                status="failed",
                duration_ms=duration_ms,
                error=error_msg,
                server_id=server.id,
                consumer=consumer,
            )

            # 审计日志：工具调用失败
            audit_logger.log_event(
                event_type="tool.call",
                actor=consumer or "api",
                action="call",
                resource=f"tool:{tool_name}",
                metadata={
                    "tool_name": tool_name,
                    "status": "failed",
                    "duration_ms": duration_ms,
                    "server_id": server.id,
                    "server_name": server.name,
                    "retried": retried,
                    "consumer": consumer,
                    "call_id": call_id,
                    "error": error_msg[:500],
                },
                description=f"工具调用失败: {tool_name} - {error_msg[:100]}",
            )

            return {
                "success": False,
                "result": None,
                "error": error_msg,
                "duration_ms": duration_ms,
                "tool_name": tool_name,
                "call_id": call_id,
                "from_cache": False,
                "retried": retried,
                "circuit_breaker": breaker.state,
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
    # 熔断器访问
    # --------------------------------------------------------

    def get_circuit_breaker_status(self, server_id: Optional[int] = None) -> Any:
        """获取熔断器状态.

        Args:
            server_id: 可选，指定服务器 ID；为 None 则返回所有

        Returns:
            熔断器状态字典或列表
        """
        if server_id is not None:
            breaker = self._circuit_breakers.get_breaker(server_id)
            return breaker.get_status_dict()
        return self._circuit_breakers.get_all_status()

    def reset_circuit_breaker(self, server_id: int) -> None:
        """重置指定服务器的熔断器.

        Args:
            server_id: 服务器 ID
        """
        self._circuit_breakers.reset(server_id)

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

    def _is_retryable_error(self, error: Exception) -> bool:
        """判断错误是否可重试.

        仅对网络错误和 5xx 错误重试，业务错误不重试。

        Args:
            error: 异常对象

        Returns:
            True 表示可以重试
        """
        error_str = str(error).lower()

        # 网络相关错误
        if isinstance(error, httpx.TimeoutException):
            return True
        if isinstance(error, httpx.ConnectError):
            return True
        if isinstance(error, httpx.NetworkError):
            return True
        if isinstance(error, httpx.RemoteProtocolError):
            return True

        # HTTP 5xx 错误
        if isinstance(error, httpx.HTTPStatusError):
            if error.response.status_code >= 500:
                return True
            # 429 Too Many Requests 也可以重试
            if error.response.status_code == 429:
                return True

        # 常见网络错误关键词
        retryable_keywords = [
            "timeout",
            "timed out",
            "connection",
            "network",
            "temporary",
            "unavailable",
            "bad gateway",
            "gateway timeout",
            "service unavailable",
        ]
        for keyword in retryable_keywords:
            if keyword in error_str:
                return True

        return False

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
