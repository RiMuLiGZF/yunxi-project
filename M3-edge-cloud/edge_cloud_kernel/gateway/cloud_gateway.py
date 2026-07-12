"""端云通信网关.

管理端云之间的网络连接、连接池和请求转发。
支持指数退避重试（仅对 429/5xx 重试，401/403 不重试）。
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import structlog

from edge_cloud_kernel.gateway.circuit_breaker import (
    CircuitBreaker,
    classify_http_error,
)
from edge_cloud_kernel.models.exceptions import CircuitBreakerError, ProviderError

logger = structlog.get_logger(__name__)

# 默认连接池配置
DEFAULT_CONNECT_TIMEOUT: float = 10.0
DEFAULT_READ_TIMEOUT: float = 60.0
DEFAULT_POOL_SIZE: int = 10
DEFAULT_POOL_PER_HOST: int = 5

# 重试配置
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BASE_DELAY_S: float = 1.0
DEFAULT_RETRY_MAX_DELAY_S: float = 30.0
DEFAULT_RETRY_BACKOFF_FACTOR: float = 2.0


class CloudGateway:
    """端云通信网关.

    管理与云端服务的 HTTP 连接池，支持熔断保护和指数退避重试。
    对 429（限流）和 5xx（服务端错误）自动重试，
    对 401/403（认证/授权错误）不重试，直接抛出自定义异常。

    Attributes:
        _base_url: 云端 API 基础 URL.
        _api_key: 云端 API 密钥.
        _session: aiohttp ClientSession.
        _circuit_breakers: 按服务名称索引的熔断器.
        _closed: 网关是否已关闭.
    """

    def __init__(
        self,
        base_url: str = "https://api.openai.com",
        api_key: str = "",
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        pool_size: int = DEFAULT_POOL_SIZE,
        pool_per_host: int = DEFAULT_POOL_PER_HOST,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base_delay_s: float = DEFAULT_RETRY_BASE_DELAY_S,
        retry_max_delay_s: float = DEFAULT_RETRY_MAX_DELAY_S,
    ) -> None:
        """初始化 CloudGateway.

        Args:
            base_url: 云端 API 基础 URL.
            api_key: API 密钥.
            connect_timeout: 连接超时（秒）.
            read_timeout: 读取超时（秒）.
            pool_size: 连接池总大小.
            pool_per_host: 每主机最大连接数.
            max_retries: 最大重试次数.
            retry_base_delay_s: 重试初始延迟（秒）.
            retry_max_delay_s: 重试最大延迟（秒）.
        """
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._connect_timeout = aiohttp.ClientTimeout(
            total=read_timeout,
            connect=connect_timeout,
        )
        self._pool_size = pool_size
        self._pool_per_host = pool_per_host
        self._session: aiohttp.ClientSession | None = None
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._closed = False
        self._max_retries = max_retries
        self._retry_base_delay_s = retry_base_delay_s
        self._retry_max_delay_s = retry_max_delay_s
        logger.info(
            "cloud_gateway.init",
            base_url=self._base_url,
            max_retries=max_retries,
        )

    async def start(self) -> None:
        """启动网关，创建 aiohttp 连接池."""
        if self._session is not None:
            return
        connector = aiohttp.TCPConnector(
            limit=self._pool_size,
            limit_per_host=self._pool_per_host,
        )
        self._session = aiohttp.ClientSession(
            base_url=self._base_url,
            timeout=self._connect_timeout,
            connector=connector,
            headers=self._default_headers(),
        )
        logger.info("cloud_gateway.started")

    async def close(self) -> None:
        """关闭网关，释放连接池资源."""
        if self._session and not self._closed:
            await self._session.close()
            self._closed = True
            logger.info("cloud_gateway.closed")

    def _default_headers(self) -> dict[str, str]:
        """构建默认请求头.

        Returns:
            默认 HTTP 头字典.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "Yunxi-EdgeCloudKernel/0.1.0",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def get_circuit_breaker(
        self,
        service_name: str,
        volume_threshold: int = 20,
        error_threshold_pct: float = 50.0,
        reset_timeout_s: float = 10.0,
    ) -> CircuitBreaker:
        """获取或创建指定服务的熔断器.

        Args:
            service_name: 服务名称.
            volume_threshold: 熔断触发最小请求数.
            error_threshold_pct: 错误率阈值百分比.
            reset_timeout_s: 熔断恢复超时（秒）.

        Returns:
            CircuitBreaker 实例.
        """
        if service_name not in self._circuit_breakers:
            self._circuit_breakers[service_name] = CircuitBreaker(
                name=service_name,
                volume_threshold=volume_threshold,
                error_threshold_pct=error_threshold_pct,
                reset_timeout_s=reset_timeout_s,
            )
        return self._circuit_breakers[service_name]

    def _should_retry(self, status_code: int) -> bool:
        """判断是否应该重试.

        对 429（限流）和 5xx（服务端错误）重试，
        对 401/403（认证/授权错误）不重试。

        Args:
            status_code: HTTP 状态码.

        Returns:
            是否应该重试.
        """
        return status_code == 429 or status_code >= 500

    async def _retry_with_backoff(
        self,
        method: str,
        path: str,
        service_name: str,
        cb: CircuitBreaker,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """带指数退避重试的请求执行.

        Args:
            method: HTTP 方法（POST/GET）.
            path: API 路径.
            service_name: 熔断器服务名.
            cb: 熔断器实例.
            **kwargs: 传递给 aiohttp 的参数.

        Returns:
            响应 JSON 字典.

        Raises:
            CircuitBreakerError: 熔断器开启.
            ProviderError: 请求失败（含自定义错误码和状态码）.
        """
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            if not cb.allow_request():
                raise CircuitBreakerError(
                    message=f"Circuit breaker '{service_name}' is open",
                    error_code="CIRCUIT_OPEN",
                    circuit_name=service_name,
                    reset_in=cb._reset_timeout_s - (asyncio.get_running_loop().time() - cb._opened_at) if cb.state.value == "open" else 0.0,
                )

            if self._session is None:
                raise ProviderError(
                    message="CloudGateway session not started",
                    error_code="GATEWAY_NOT_STARTED",
                )

            start_time = asyncio.get_running_loop().time()
            try:
                async with self._session.request(method, path, **kwargs) as resp:
                    data = await resp.json()
                    elapsed = (asyncio.get_running_loop().time() - start_time) * 1000

                    if resp.status >= 400:
                        error_type = classify_http_error(resp.status)
                        cb.record_failure(elapsed, error_type=error_type)

                        if not self._should_retry(resp.status) or attempt >= self._max_retries - 1:
                            raise ProviderError(
                                message=f"Cloud API error: status={resp.status}, body={data}",
                                error_code=f"CLOUD_API_{resp.status}",
                                status_code=resp.status,
                                context={"body": data},
                            )

                        # 指数退避
                        delay = min(
                            self._retry_base_delay_s * (DEFAULT_RETRY_BACKOFF_FACTOR ** attempt),
                            self._retry_max_delay_s,
                        )
                        logger.warning(
                            "cloud_gateway.retry",
                            method=method,
                            path=path,
                            status=resp.status,
                            attempt=attempt + 1,
                            delay_s=delay,
                        )
                        await asyncio.sleep(delay)
                        continue

                    cb.record_success(elapsed)
                    return data

            except ProviderError:
                raise
            except Exception as e:
                elapsed = (asyncio.get_running_loop().time() - start_time) * 1000
                cb.record_failure(elapsed, error_type="retryable")
                last_error = e

                if attempt < self._max_retries - 1:
                    delay = min(
                        self._retry_base_delay_s * (DEFAULT_RETRY_BACKOFF_FACTOR ** attempt),
                        self._retry_max_delay_s,
                    )
                    logger.warning(
                        "cloud_gateway.retry_exception",
                        method=method,
                        path=path,
                        attempt=attempt + 1,
                        delay_s=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)

        # 所有重试耗尽
        raise ProviderError(
            message=f"Cloud request failed after {self._max_retries} retries: {last_error}",
            error_code="CLOUD_RETRY_EXHAUSTED",
            context={"last_error": str(last_error)},
        ) from last_error

    async def post(
        self,
        path: str,
        payload: dict[str, Any],
        service_name: str = "default",
    ) -> dict[str, Any]:
        """发送 POST 请求到云端（带指数退避重试）.

        对 429/5xx 自动重试，对 401/403 不重试直接抛出异常。

        Args:
            path: API 路径（不含 base_url）.
            payload: 请求体 JSON.
            service_name: 熔断器服务名.

        Returns:
            响应 JSON 字典.

        Raises:
            CircuitBreakerError: 熔断器开启.
            ProviderError: 请求失败.
        """
        cb = self.get_circuit_breaker(service_name)
        return await self._retry_with_backoff(
            method="POST",
            path=path,
            service_name=service_name,
            cb=cb,
            json=payload,
        )

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        service_name: str = "default",
    ) -> dict[str, Any]:
        """发送 GET 请求到云端（带指数退避重试）.

        对 429/5xx 自动重试，对 401/403 不重试直接抛出异常。

        Args:
            path: API 路径.
            params: 查询参数.
            service_name: 熔断器服务名.

        Returns:
            响应 JSON 字典.

        Raises:
            CircuitBreakerError: 熔断器开启.
            ProviderError: 请求失败.
        """
        cb = self.get_circuit_breaker(service_name)
        return await self._retry_with_backoff(
            method="GET",
            path=path,
            service_name=service_name,
            cb=cb,
            params=params,
        )
