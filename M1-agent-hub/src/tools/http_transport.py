"""
云汐内核 V9 - A2A HTTP 传输层

解决评审 P0-004：实现基于 aiohttp 的 A2A 跨进程通信传输。
支持 Agent Discovery 端点 `/.well-known/agent-card.json`。

设计约束：
- 轻量实现，适配本地 7B 部署
- 兼容 A2A Protocol v1.0 JSON-RPC over HTTP
- 支持 AgentCard 签名验证、请求重试、连接超时
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import structlog

from src.core.a2a_protocol import A2ATransport, Task, TaskUpdate, TaskStatus, AgentCard, sign_task, verify_task

logger = structlog.get_logger(__name__)

# 全链路追踪：惰性导入 trace_context，获取 trace_id 透传
_trace_ctx_available = False
_get_trace_headers = None

def _get_trace_headers_safe() -> dict[str, str]:
    """安全获取追踪 HTTP 头（惰性导入，避免循环依赖）。"""
    global _trace_ctx_available, _get_trace_headers
    if _get_trace_headers is not None:
        return _get_trace_headers()
    try:
        from src.observability.trace_context import get_trace_headers
        _get_trace_headers = get_trace_headers
        _trace_ctx_available = True
        return get_trace_headers()
    except ImportError:
        _trace_ctx_available = False
        _get_trace_headers = lambda: {}  # type: ignore[assignment]
        return {}

def _merge_trace_headers(base_headers: dict[str, str]) -> dict[str, str]:
    """将追踪头合并到基础头中。"""
    trace_headers = _get_trace_headers_safe()
    if trace_headers:
        merged = dict(base_headers)
        merged.update(trace_headers)
        return merged
    return base_headers


class HTTPTransport(A2ATransport):
    """A2A HTTP 传输实现

    基于 aiohttp 的异步 HTTP 客户端/服务器传输。
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        timeout: float = 30.0,
        max_retries: int = 3,
        poll_interval: float = 2.0,
        max_backoff: float = 10.0,
        secret: str = "",  # [V9.7] Task 签名密钥
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.poll_interval = poll_interval
        self.max_backoff = max_backoff
        self._secret = secret
        self._session: Any = None
        self._logger = logger.bind(service="http_transport")

    async def _get_session(self) -> Any:
        """惰性初始化 aiohttp ClientSession"""
        if self._session is None:
            try:
                import aiohttp
            except ImportError:
                raise ImportError(
                    "aiohttp is required for HTTPTransport. "
                    "Install it with: pip install aiohttp"
                )
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def send(self, target_url: str, task: Task) -> TaskUpdate:
        """通过 HTTP 发送 Task 到目标 Agent

        [V9.7] 若配置了 secret，自动对 Task 做 HMAC 签名并在接收响应时验签。
        """
        url = target_url if target_url.startswith("http") else f"{self.base_url}/a2a/task"

        # [V9.7] 发送前自动签名
        if self._secret and not task.signature:
            task.signature = sign_task(task, self._secret)
            self._logger.debug("task_signed", task_id=task.task_id)

        payload = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "params": task.to_dict(),
            "id": task.task_id,
        }

        for attempt in range(self.max_retries):
            try:
                session = await self._get_session()
                headers = _merge_trace_headers({"Content-Type": "application/json"})
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = data.get("result", {})
                        # [V9.7] 验签：若响应包含 signature 且配置了 secret
                        resp_signature = result.get("signature", "")
                        if self._secret and resp_signature:
                            resp_task = Task(
                                task_id=result.get("task_id", task.task_id),
                                status=TaskStatus(result.get("status", "completed")),
                                sender=result.get("sender", ""),
                                recipient=result.get("recipient", ""),
                                payload=result.get("payload", {}),
                                created_at=result.get("created_at", time.time()),
                                signature=resp_signature,
                            )
                            if not verify_task(resp_task, resp_signature, self._secret):
                                self._logger.error(
                                    "task_signature_verification_failed",
                                    task_id=resp_task.task_id,
                                )
                                return TaskUpdate(
                                    task_id=resp_task.task_id,
                                    status=TaskStatus.FAILED,
                                    error="Task signature verification failed",
                                    is_final=True,
                                )
                        return TaskUpdate(
                            task_id=result.get("task_id", task.task_id),
                            status=TaskStatus(result.get("status", "completed")),
                            error=result.get("error"),
                            is_final=result.get("status") in ("completed", "failed", "cancelled"),
                        )
                    else:
                        text = await resp.text()
                        self._logger.warning(
                            "http_send_error",
                            url=url,
                            status=resp.status,
                            attempt=attempt + 1,
                        )
                        if attempt == self.max_retries - 1:
                            return TaskUpdate(
                                task_id=task.task_id,
                                status=TaskStatus.FAILED,
                                error=f"HTTP {resp.status}: {text[:200]}",
                                is_final=True,
                            )
            except Exception as exc:
                self._logger.error(
                    "http_send_exception",
                    url=url,
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt == self.max_retries - 1:
                    return TaskUpdate(
                        task_id=task.task_id,
                        status=TaskStatus.FAILED,
                        error=str(exc),
                        is_final=True,
                    )
                await asyncio.sleep(0.5 * (attempt + 1))

        return TaskUpdate(
            task_id=task.task_id,
            status=TaskStatus.FAILED,
            error="max_retries_exceeded",
            is_final=True,
        )

    async def subscribe(self, agent_id: str) -> AsyncIterator[TaskUpdate]:
        """订阅 Task 更新（HTTP 轮询实现）

        [V9.5] 通过定期轮询 /a2a/tasks?agent_id=xxx 获取更新，
        间隔 2 秒，最多持续 5 分钟（150次轮询）。
        生产环境应使用 WebSocket 或 SSE 替代。
        """
        poll_url = f"{self.base_url}/a2a/tasks"
        params = {"agent_id": agent_id}
        max_polls = 150  # 5 minutes at 2s intervals

        for poll_count in range(max_polls):
            try:
                session = await self._get_session()
                headers = _merge_trace_headers({"Accept": "application/json"})
                async with session.get(
                    poll_url,
                    params=params,
                    headers=headers,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tasks = data.get("tasks", [])
                        for task_data in tasks:
                            yield TaskUpdate(
                                task_id=task_data.get("task_id", ""),
                                status=TaskStatus(task_data.get("status", "submitted")),
                                error=task_data.get("error"),
                                is_final=task_data.get("status") in (
                                    "completed", "failed", "cancelled"
                                ),
                            )
                    # No tasks or non-200: just wait and retry
            except Exception as exc:
                self._logger.debug(
                    "subscribe_poll_error",
                    agent_id=agent_id,
                    error=str(exc),
                )

            # [V9.5-R2] 指数退避：2s -> 4s -> 8s -> max_backoff
            backoff = min(self.poll_interval * (2 ** (poll_count // 5)), self.max_backoff)
            await asyncio.sleep(backoff)

        # Timeout: yield a final sentinel
        yield TaskUpdate(
            task_id="",
            status=TaskStatus.SUBMITTED,
            error="subscribe_timeout",
            is_final=True,
        )

    async def discover_agent(self, url: str) -> AgentCard | None:
        """发现远端 Agent 的能力卡片

        访问 `/.well-known/agent-card.json` 获取 AgentCard。
        """
        discovery_url = f"{url.rstrip('/')}/.well-known/agent-card.json"
        try:
            session = await self._get_session()
            headers = _merge_trace_headers({})
            async with session.get(discovery_url, timeout=self.timeout, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return AgentCard(
                        agent_id=data.get("agent_id", ""),
                        name=data.get("name", ""),
                        description=data.get("description", ""),
                        version=data.get("version", "1.0.0"),
                        url=url,
                        capabilities=data.get("capabilities", []),
                        skills=data.get("skills", []),
                    )
                else:
                    self._logger.warning(
                        "agent_discovery_failed",
                        url=discovery_url,
                        status=resp.status,
                    )
                    return None
        except Exception as exc:
            self._logger.error(
                "agent_discovery_exception",
                url=discovery_url,
                error=str(exc),
            )
            return None

    async def close(self) -> None:
        """关闭 HTTP 会话"""
        if self._session is not None:
            await self._session.close()
            self._session = None

    def stats(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "session_active": self._session is not None,
        }
