"""
A2A (Agent-to-Agent) 通用调用客户端

基于 Google A2A 协议草案实现，支持：
- AgentCard 发现 (discover)
- 任务发送 (send_task)
- 消息发送 (send_message)
- SSE 实时订阅 (subscribe)

使用 httpx 进行 HTTP 调用，内置 JSON-RPC 格式支持与重试逻辑。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

# 默认超时与重试配置
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0


class A2AError(Exception):
    """A2A 客户端基础异常"""
    pass


class A2AConnectionError(A2AError):
    """连接外部 Agent 失败"""
    pass


class A2AResponseError(A2AError):
    """外部 Agent 返回错误响应"""
    pass


class A2AClient:
    """
    A2A 协议客户端，用于云汐系统调用外部 AI Agent。

    支持 JSON-RPC 2.0 格式的消息交互，并提供指数退避重试机制。
    """

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> None:
        """
        初始化 A2A 客户端。

        Args:
            timeout: HTTP 请求超时秒数。
            retries: 请求失败时的最大重试次数。
            retry_delay: 重试间隔基准秒数（实际延迟会随重试次数指数增长）。
        """
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self._client = httpx.Client(timeout=timeout)

    def _request(
        self,
        method: str,
        url: str,
        json_payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        stream: bool = False,
    ) -> httpx.Response:
        """
        带重试逻辑的 HTTP 请求封装。

        Args:
            method: HTTP 方法，如 "GET", "POST"。
            url: 请求地址。
            json_payload: JSON 请求体。
            headers: 自定义请求头。
            stream: 是否使用流式响应（用于 SSE）。

        Returns:
            httpx.Response 对象。

        Raises:
            A2AConnectionError: 连接失败且重试耗尽。
            A2AResponseError: 收到非 2xx 响应。
        """
        _headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if headers:
            _headers.update(headers)

        last_exception: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                response = self._client.request(
                    method=method,
                    url=url,
                    json=json_payload,
                    headers=_headers,
                    stream=stream,
                )
                if not stream:
                    response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "A2A HTTP error on %s (attempt %d/%d): %s %s",
                    url,
                    attempt,
                    self.retries,
                    exc.response.status_code,
                    exc.response.text[:200],
                )
                if attempt == self.retries:
                    raise A2AResponseError(
                        f"HTTP {exc.response.status_code}: {exc.response.text[:500]}"
                    ) from exc
                time.sleep(self.retry_delay * (2 ** (attempt - 1)))
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exception = exc
                logger.warning(
                    "A2A connection error on %s (attempt %d/%d): %s",
                    url,
                    attempt,
                    self.retries,
                    exc,
                )
                if attempt == self.retries:
                    raise A2AConnectionError(
                        f"Failed to connect to {url} after {self.retries} attempts"
                    ) from exc
                time.sleep(self.retry_delay * (2 ** (attempt - 1)))
            except Exception as exc:
                last_exception = exc
                logger.warning(
                    "A2A unexpected error on %s (attempt %d/%d): %s",
                    url,
                    attempt,
                    self.retries,
                    exc,
                )
                if attempt == self.retries:
                    raise A2AError(f"Unexpected error during request to {url}: {exc}") from exc
                time.sleep(self.retry_delay * (2 ** (attempt - 1)))

        # 理论上不会到达此处，但类型检查需要
        raise A2AError(f"Request to {url} failed: {last_exception}")

    def discover(self, agent_url: str) -> dict[str, Any]:
        """
        获取外部 Agent 的 AgentCard。

        AgentCard 通常发布在 Agent 根路径下的 `.well-known/agent.json`，
        或直接通过根路径 GET 请求获取。

        Args:
            agent_url: 外部 Agent 的基础 URL，例如 "http://localhost:9000"。

        Returns:
            AgentCard JSON 字典，包含 name、description、capabilities、endpoints 等字段。

        Raises:
            A2AConnectionError: 无法连接到目标 Agent。
            A2AResponseError: 目标 Agent 返回错误。
        """
        # 优先尝试标准 well-known 路径
        well_known_url = agent_url.rstrip("/") + "/.well-known/agent.json"
        try:
            response = self._request("GET", well_known_url)
            return response.json()
        except A2AResponseError as exc:
            # 若 well-known 返回 404，尝试直接 GET 根路径
            if "404" in str(exc) or "Not Found" in str(exc):
                logger.info("Well-known AgentCard not found, trying root URL: %s", agent_url)
                response = self._request("GET", agent_url.rstrip("/") + "/")
                return response.json()
            raise

    def _build_jsonrpc_payload(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """构建 JSON-RPC 2.0 请求体。"""
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": int(time.time() * 1000),
        }

    def send_task(self, agent_url: str, task: dict[str, Any]) -> dict[str, Any]:
        """
        向外部 Agent 发送任务。

        Args:
            agent_url: 外部 Agent 的任务接收端点，例如 "http://localhost:9000/tasks/send"。
            task: 任务描述字典，至少包含 task 的基本信息，例如：
                {
                    "id": "task-001",
                    "sessionId": "session-001",
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "请分析这段代码"}]
                    }
                }

        Returns:
            JSON-RPC 响应字典，result 字段包含任务处理结果或任务状态。

        Raises:
            A2AConnectionError: 连接失败。
            A2AResponseError: 响应错误。
        """
        payload = self._build_jsonrpc_payload("tasks/send", task)
        response = self._request("POST", agent_url, json_payload=payload)
        data = response.json()

        if "error" in data:
            error = data["error"]
            raise A2AResponseError(
                f"JSON-RPC error {error.get('code')}: {error.get('message')}"
            )
        return data

    def send_message(self, agent_url: str, message: dict[str, Any]) -> dict[str, Any]:
        """
        向外部 Agent 发送单条消息（非任务上下文）。

        Args:
            agent_url: 外部 Agent 的消息接收端点，例如 "http://localhost:9000/message"。
            message: 消息字典，例如：
                {
                    "role": "user",
                    "parts": [{"type": "text", "text": "你好"}]
                }

        Returns:
            响应字典，通常包含 Agent 的回复消息。

        Raises:
            A2AConnectionError: 连接失败。
            A2AResponseError: 响应错误。
        """
        payload = self._build_jsonrpc_payload("message", {"message": message})
        response = self._request("POST", agent_url, json_payload=payload)
        data = response.json()

        if isinstance(data, dict) and "error" in data:
            error = data["error"]
            raise A2AResponseError(
                f"JSON-RPC error {error.get('code')}: {error.get('message')}"
            )
        return data

    def subscribe(self, agent_url: str, callback: Callable[[dict[str, Any]], None]) -> None:
        """
        通过 SSE (Server-Sent Events) 订阅外部 Agent 的实时推送。

        Args:
            agent_url: SSE 端点地址，例如 "http://localhost:9000/tasks/subscribe"。
            callback: 回调函数，接收每条解析后的事件字典作为参数。

        Raises:
            A2AConnectionError: 连接 SSE 端点失败。
            A2AError: 解析事件流时发生错误。
        """
        try:
            response = self._request("GET", agent_url, headers={"Accept": "text/event-stream"}, stream=True)
            for line in response.iter_lines():
                if line:
                    decoded = line.decode("utf-8")
                    # SSE 格式: data: {...}
                    if decoded.startswith("data:"):
                        json_str = decoded[len("data:"):].strip()
                        try:
                            event_data = json.loads(json_str)
                            callback(event_data)
                        except json.JSONDecodeError as exc:
                            logger.warning("Failed to parse SSE event data: %s", exc)
                            raise A2AError(f"Invalid SSE event JSON: {json_str}") from exc
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise A2AConnectionError(f"SSE subscription failed for {agent_url}: {exc}") from exc

    def close(self) -> None:
        """关闭底层 HTTP 客户端，释放连接资源。"""
        self._client.close()

    def __enter__(self) -> A2AClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


# ------------------------------------------------------------------------------
# 使用示例
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    # 示例 1：发现外部 Agent 的能力
    def example_discover() -> None:
        client = A2AClient()
        try:
            card = client.discover("http://localhost:9000")
            print("AgentCard:", json.dumps(card, indent=2, ensure_ascii=False))
        except A2AError as exc:
            print("Discover failed:", exc)
        finally:
            client.close()

    # 示例 2：发送任务
    def example_send_task() -> None:
        client = A2AClient()
        try:
            result = client.send_task(
                "http://localhost:9000/tasks/send",
                task={
                    "id": "task-demo-001",
                    "sessionId": "session-demo-001",
                    "message": {
                        "role": "user",
                        "parts": [
                            {"type": "text", "text": "请帮我总结这段文字的核心观点"}
                        ],
                    },
                },
            )
            print("Task result:", json.dumps(result, indent=2, ensure_ascii=False))
        except A2AError as exc:
            print("Send task failed:", exc)
        finally:
            client.close()

    # 示例 3：发送消息
    def example_send_message() -> None:
        client = A2AClient()
        try:
            result = client.send_message(
                "http://localhost:9000/message",
                message={
                    "role": "user",
                    "parts": [{"type": "text", "text": "你好，请介绍一下你自己"}],
                },
            )
            print("Message result:", json.dumps(result, indent=2, ensure_ascii=False))
        except A2AError as exc:
            print("Send message failed:", exc)
        finally:
            client.close()

    # 示例 4：SSE 订阅（需外部 Agent 支持 SSE 推送）
    def example_subscribe() -> None:
        client = A2AClient()

        def on_event(event: dict[str, Any]) -> None:
            print("Received SSE event:", json.dumps(event, indent=2, ensure_ascii=False))

        try:
            # 此调用会阻塞，直到连接关闭
            client.subscribe("http://localhost:9000/tasks/subscribe", callback=on_event)
        except A2AError as exc:
            print("Subscribe failed:", exc)
        finally:
            client.close()

    # 示例 5：使用上下文管理器
    def example_context_manager() -> None:
        with A2AClient(timeout=10.0, retries=2) as client:
            try:
                card = client.discover("http://localhost:9000")
                print("Agent name:", card.get("name"))
            except A2AError as exc:
                print("Error:", exc)

    print("=" * 60)
    print("A2AClient 示例函数已定义，可根据需要取消注释调用：")
    print("  example_discover()")
    print("  example_send_task()")
    print("  example_send_message()")
    print("  example_subscribe()")
    print("  example_context_manager()")
    print("=" * 60)
