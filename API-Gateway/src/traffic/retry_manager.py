"""
云汐 API 网关 - 重试机制

特性：
1. 网关层自动重试（可配置重试次数、间隔、状态码）
2. 幂等性检查（只对 GET/HEAD/PUT/DELETE 等幂等方法重试）
3. 重试抖动（exponential backoff with jitter）
4. 重试统计
"""
import asyncio
import random
import time
import logging
from typing import Optional, Set, Callable, Awaitable, Tuple, Any, Dict
from dataclasses import dataclass, field


logger = logging.getLogger("yunxi-gateway.retry")


# 幂等 HTTP 方法
IDEMPOTENT_METHODS = {"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"}

# 默认可重试的状态码
DEFAULT_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


@dataclass
class RetryConfig:
    """重试配置

    Attributes:
        max_retries: 最大重试次数（0 表示不重试）
        base_delay: 基础延迟时间（秒）
        max_delay: 最大延迟时间（秒）
        backoff_factor: 退避因子（指数退避的底数）
        jitter: 是否添加抖动
        retryable_status_codes: 可重试的 HTTP 状态码集合
        retry_on_timeout: 超时是否重试
        retry_on_connection_error: 连接错误是否重试
        only_idempotent: 只对幂等方法重试
    """
    max_retries: int = 2
    base_delay: float = 0.1  # 100ms
    max_delay: float = 5.0   # 5s
    backoff_factor: float = 2.0
    jitter: bool = True
    retryable_status_codes: Set[int] = field(
        default_factory=lambda: set(DEFAULT_RETRYABLE_STATUS_CODES)
    )
    retry_on_timeout: bool = True
    retry_on_connection_error: bool = True
    only_idempotent: bool = True


class RetryManager:
    """重试管理器

    负责执行带重试的请求，支持指数退避和抖动。
    """

    def __init__(self, config: Optional[RetryConfig] = None):
        self._config = config or RetryConfig()
        self._stats = {
            "total_requests": 0,
            "retried_requests": 0,
            "total_retries": 0,
            "successful_after_retry": 0,
            "failed_after_retry": 0,
            "retries_by_status": {},
        }

    def update_config(self, config: RetryConfig):
        """更新重试配置"""
        self._config = config

    def get_config(self) -> RetryConfig:
        """获取当前配置"""
        return self._config

    def is_method_retryable(self, method: str) -> bool:
        """判断方法是否可重试"""
        if not self._config.only_idempotent:
            return True
        return method.upper() in IDEMPOTENT_METHODS

    def is_status_retryable(self, status_code: int) -> bool:
        """判断状态码是否可重试"""
        return status_code in self._config.retryable_status_codes

    def _calculate_delay(self, attempt: int) -> float:
        """计算第 attempt 次重试的延迟时间

        使用指数退避 + 抖动：
        delay = min(max_delay, base_delay * backoff_factor^attempt) * random(0.5, 1.0)
        """
        base = self._config.base_delay * (self._config.backoff_factor ** attempt)
        delay = min(self._config.max_delay, base)

        if self._config.jitter:
            # 添加 50%-100% 的随机抖动
            delay = delay * (0.5 + random.random() * 0.5)

        return delay

    async def execute_with_retry(
        self,
        method: str,
        request_func: Callable[[], Awaitable[Tuple[int, Dict[str, str], bytes]]],
        on_retry: Optional[Callable[[int, int, float], Awaitable[None]]] = None,
    ) -> Tuple[int, Dict[str, str], bytes]:
        """执行带重试的请求

        Args:
            method: HTTP 方法（用于幂等性检查）
            request_func: 异步请求函数，返回 (status_code, headers, body)
            on_retry: 重试回调，参数为 (attempt, status_code, delay)

        Returns:
            (status_code, headers, body)
        """
        self._stats["total_requests"] += 1

        # 如果方法不可重试或配置为不重试，直接执行
        if self._config.max_retries <= 0 or not self.is_method_retryable(method):
            return await request_func()

        last_result: Optional[Tuple[int, Dict[str, str], bytes]] = None
        retries = 0

        for attempt in range(self._config.max_retries + 1):
            try:
                result = await request_func()
                status_code, headers, body = result
                last_result = result

                if attempt == 0:
                    # 首次请求成功，直接返回
                    if not self.is_status_retryable(status_code):
                        return result
                else:
                    # 重试后成功或不可重试状态码
                    if not self.is_status_retryable(status_code):
                        if 200 <= status_code < 500:
                            self._stats["successful_after_retry"] += 1
                        return result

                # 状态码可重试
                if attempt >= self._config.max_retries:
                    self._stats["failed_after_retry"] += 1
                    return result

                # 记录重试状态码统计
                status_key = str(status_code)
                self._stats["retries_by_status"][status_key] = (
                    self._stats["retries_by_status"].get(status_key, 0) + 1
                )

            except (asyncio.TimeoutError, TimeoutError):
                if not self._config.retry_on_timeout:
                    raise
                if attempt >= self._config.max_retries:
                    self._stats["failed_after_retry"] += 1
                    raise
                last_result = (504, {}, b'{"code": 504, "message": "Gateway timeout", "data": null}')

            except (ConnectionError, OSError):
                if not self._config.retry_on_connection_error:
                    raise
                if attempt >= self._config.max_retries:
                    self._stats["failed_after_retry"] += 1
                    raise
                last_result = (502, {}, b'{"code": 502, "message": "Bad gateway", "data": null}')

            # 准备重试
            retries += 1
            self._stats["retried_requests"] += 1 if attempt == 0 else 0
            self._stats["total_retries"] += 1

            delay = self._calculate_delay(attempt)

            if on_retry:
                status = last_result[0] if last_result else 0
                await on_retry(attempt + 1, status, delay)

            logger.debug(
                f"Retrying request (attempt {attempt + 1}/{self._config.max_retries}, "
                f"delay={delay:.3f}s)"
            )

            await asyncio.sleep(delay)

        return last_result or (500, {}, b'{"code": 500, "message": "Unknown error", "data": null}')

    def get_stats(self) -> Dict[str, Any]:
        """获取重试统计"""
        retry_rate = (
            self._stats["retried_requests"] / self._stats["total_requests"] * 100
            if self._stats["total_requests"] > 0 else 0
        )
        return {
            **self._stats,
            "retry_rate_percent": round(retry_rate, 2),
            "avg_retries_per_request": round(
                self._stats["total_retries"] / self._stats["total_requests"], 3
            ) if self._stats["total_requests"] > 0 else 0,
            "config": {
                "max_retries": self._config.max_retries,
                "base_delay": self._config.base_delay,
                "max_delay": self._config.max_delay,
                "backoff_factor": self._config.backoff_factor,
                "jitter": self._config.jitter,
                "only_idempotent": self._config.only_idempotent,
            },
        }

    def reset_stats(self):
        """重置统计"""
        self._stats = {
            "total_requests": 0,
            "retried_requests": 0,
            "total_retries": 0,
            "successful_after_retry": 0,
            "failed_after_retry": 0,
            "retries_by_status": {},
        }
