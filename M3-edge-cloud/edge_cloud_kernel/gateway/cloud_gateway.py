"""端云通信网关.

管理端云之间的网络连接、连接池和请求转发。
支持指数退避重试（仅对 429/5xx 重试，401/403 不重试）。

重构说明：
- 内部重试逻辑已迁移至 RetryCoordinator（common/retry.py）
- 对外 API 保持 100% 兼容（构造参数、post/get 方法签名不变）
- 熔断器协同通过 RetryCoordinator.set_circuit_breaker 实现
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import structlog

from edge_cloud_kernel.common.retry import RetryCoordinator, RetryPolicy
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

# 重试配置（保持原有默认值不变，用于向后兼容）
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BASE_DELAY_S: float = 1.0
DEFAULT_RETRY_MAX_DELAY_S: float = 30.0
DEFAULT_RETRY_BACKOFF_FACTOR: float = 2.0

# 策略名称常量
CLOUD_GATEWAY_POLICY = "cloud_gateway"


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
        _retry_coordinator: 全局重试协调器.
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

        # 重试相关参数（保留实例属性，用于向后兼容和统计查询）
        self._max_retries = max_retries
        self._retry_base_delay_s = retry_base_delay_s
        self._retry_max_delay_s = retry_max_delay_s

        # 初始化重试协调器并注册 cloud_gateway 策略
        # 策略参数与原有重试逻辑保持一致
        self._retry_coordinator = RetryCoordinator()
        gateway_policy = RetryPolicy(
            max_retries=max_retries,
            base_delay=retry_base_delay_s,
            max_delay=retry_max_delay_s,
            backoff_factor=DEFAULT_RETRY_BACKOFF_FACTOR,
            jitter=True,
            retryable_exceptions=(
                ConnectionError,
                TimeoutError,
                OSError,
                aiohttp.ClientError,
                asyncio.TimeoutError,
            ),
            retryable_status_codes=(429, 500, 502, 503, 504),
            retryable_error_codes=(),
        )
        self._retry_coordinator.register_policy(CLOUD_GATEWAY_POLICY, gateway_policy)

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

    async def _execute_request(
        self,
        method: str,
        path: str,
        cb: CircuitBreaker,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """执行单次 HTTP 请求（不含重试）.

        负责熔断器状态检查、请求执行和结果记录。
        这是 RetryCoordinator 调用的核心执行函数。

        Args:
            method: HTTP 方法（POST/GET）.
            path: API 路径.
            cb: 熔断器实例.
            **kwargs: 传递给 aiohttp 的参数.

        Returns:
            响应 JSON 字典.

        Raises:
            CircuitBreakerError: 熔断器开启.
            ProviderError: 请求失败（含状态码和响应体）.
            aiohttp.ClientError: 网络层错误（可重试，由外层捕获）.
        """
        if not cb.allow_request():
            raise CircuitBreakerError(
                message=f"Circuit breaker '{cb.name}' is open",
                error_code="CIRCUIT_OPEN",
                circuit_name=cb.name,
                reset_in=(
                    cb._reset_timeout_s - (asyncio.get_running_loop().time() - cb._opened_at)
                    if cb.state.value == "open"
                    else 0.0
                ),
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

                    # 非重试错误直接抛出 ProviderError（status_code 属性供重试协调器判断）
                    raise ProviderError(
                        message=f"Cloud API error: status={resp.status}, body={data}",
                        error_code=f"CLOUD_API_{resp.status}",
                        status_code=resp.status,
                        context={"body": data},
                    )

                cb.record_success(elapsed)
                return data

        except ProviderError:
            # ProviderError 已经过处理（含熔断器记录），直接抛出
            raise
        except Exception as e:
            # 网络异常等，记录熔断器失败，抛出供外层重试
            elapsed = (asyncio.get_running_loop().time() - start_time) * 1000
            cb.record_failure(elapsed, error_type="retryable")
            raise

    async def _retry_with_backoff(
        self,
        method: str,
        path: str,
        service_name: str,
        cb: CircuitBreaker,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """带指数退避重试的请求执行.

        使用 RetryCoordinator 统一管理重试逻辑。
        熔断器通过闭包绑定到单次请求执行中，
        由 _execute_request 负责每次请求前的熔断检查。

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

        async def _do_request() -> dict[str, Any]:
            """闭包：单次请求执行，供重试协调器调用."""
            return await self._execute_request(method, path, cb, **kwargs)

        try:
            return await self._retry_coordinator.execute(
                _do_request,
                policy_name=CLOUD_GATEWAY_POLICY,
            )
        except CircuitBreakerError:
            raise
        except ProviderError as e:
            # ProviderError 直接抛出（已包含状态码和错误信息）
            raise
        except Exception as e:
            # 其他异常（重试耗尽后的网络异常等）包装为 ProviderError
            last_error = e
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
