"""
服务间调用 SDK (ServiceCaller)

封装带 API Key 的 HTTP 调用，提供：
- 自动附加 Key 到请求头
- 自动重试和错误处理
- 调用统计
- 超时控制
- 统一的响应解析

用法：
    from shared.core.auth.service_caller import ServiceCaller

    caller = ServiceCaller(
        api_key="yx-xxxxxxx",
        base_url="http://localhost:8000",
    )

    # GET 请求
    result = caller.get("/api/data")

    # POST 请求
    result = caller.post("/api/create", json={"name": "test"})

    # 查看统计
    stats = caller.get_stats()
"""

import time
import json
import logging
import threading
from typing import Optional, Dict, Any, List, Tuple, Union
from urllib.parse import urljoin
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import httpx
    _httpx_available = True
except ImportError:  # pragma: no cover
    _httpx_available = False
    httpx = None  # type: ignore


def is_httpx_available() -> bool:
    """检查 httpx 是否可用"""
    return _httpx_available


# ===========================================================================
# 调用统计
# ===========================================================================

@dataclass
class CallStats:
    """调用统计"""
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_time_ms: float = 0.0
    last_call_time: Optional[float] = None
    status_counts: Dict[int, int] = field(default_factory=dict)
    error_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        avg_time = self.total_time_ms / self.total_calls if self.total_calls > 0 else 0.0
        success_rate = self.success_calls / self.total_calls if self.total_calls > 0 else 0.0
        return {
            "total_calls": self.total_calls,
            "success_calls": self.success_calls,
            "failed_calls": self.failed_calls,
            "success_rate": round(success_rate, 4),
            "avg_time_ms": round(avg_time, 2),
            "total_time_ms": round(self.total_time_ms, 2),
            "last_call_time": self.last_call_time,
            "status_counts": self.status_counts,
            "error_counts": self.error_counts,
        }


# ===========================================================================
# 重试配置
# ===========================================================================

@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3                    # 最大重试次数
    base_delay: float = 0.5                 # 基础延迟（秒）
    max_delay: float = 10.0                 # 最大延迟（秒）
    backoff_factor: float = 2.0             # 退避因子
    retry_on_status: List[int] = field(    # 触发重试的 HTTP 状态码
        default_factory=lambda: [429, 500, 502, 503, 504]
    )
    retry_on_exception: bool = True         # 网络异常时是否重试


# ===========================================================================
# ServiceCaller 主类
# ===========================================================================

class ServiceCaller:
    """服务间调用客户端

    封装带 API Key 认证的 HTTP 调用，支持自动重试、超时、统计。

    Args:
        api_key: API Key 明文
        base_url: 服务基础 URL
        timeout: 请求超时（秒）
        retry_config: 重试配置
        header_name: API Key 请求头名称
        use_https: 是否强制使用 HTTPS（生产环境建议）
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        timeout: float = 30.0,
        retry_config: Optional[RetryConfig] = None,
        header_name: str = "X-API-Key",
        use_https: bool = False,
    ):
        if not api_key:
            raise ValueError("api_key 不能为空")

        self._api_key = api_key
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._timeout = timeout
        self._retry_config = retry_config or RetryConfig()
        self._header_name = header_name
        self._use_https = use_https

        # 统计
        self._stats = CallStats()
        self._stats_lock = threading.Lock()

        # httpx 客户端（延迟创建）
        self._client = None
    def _get_client(self):
        """获取或创建 httpx 客户端"""
        if not _httpx_available:
            raise RuntimeError("httpx 不可用，请先安装: pip install httpx")

        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                headers={
                    self._header_name: self._api_key,
                    "Content-Type": "application/json",
                    "User-Agent": "Yunxi-ServiceCaller/1.0",
                },
            )
        return self._client

    def _build_url(self, path: str) -> str:
        """构建完整 URL"""
        if not self._base_url:
            return path
        if path.startswith(("http://", "https://")):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._base_url}{path}"

    def _record_success(self, status_code: int, duration_ms: float) -> None:
        """记录成功调用"""
        with self._stats_lock:
            self._stats.total_calls += 1
            self._stats.success_calls += 1
            self._stats.total_time_ms += duration_ms
            self._stats.last_call_time = time.time()
            self._stats.status_counts[status_code] = (
                self._stats.status_counts.get(status_code, 0) + 1
            )

    def _record_failure(self, error_type: str, duration_ms: float) -> None:
        """记录失败调用"""
        with self._stats_lock:
            self._stats.total_calls += 1
            self._stats.failed_calls += 1
            self._stats.total_time_ms += duration_ms
            self._stats.last_call_time = time.time()
            self._stats.error_counts[error_type] = (
                self._stats.error_counts.get(error_type, 0) + 1
            )

    def _should_retry(self, response=None, exception: Optional[Exception] = None) -> bool:
        """判断是否应该重试"""
        if exception and self._retry_config.retry_on_exception:
            return True
        if response is not None and hasattr(response, 'status_code'):
            return response.status_code in self._retry_config.retry_on_status
        return False

    def _calculate_delay(self, attempt: int) -> float:
        """计算重试延迟（指数退避）"""
        delay = self._retry_config.base_delay * (self._retry_config.backoff_factor ** attempt)
        return min(delay, self._retry_config.max_delay)

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> Tuple[bool, Any, Optional[int], Optional[str]]:
        """带重试的请求

        Returns:
            (是否成功, 响应/异常对象, 状态码, 错误类型)
        """
        last_exception = None
        last_response = None

        for attempt in range(self._retry_config.max_retries + 1):
            start_time = time.time()
            duration_ms = 0.0

            try:
                client = self._get_client()
                response = client.request(method, url, **kwargs)
                duration_ms = (time.time() - start_time) * 1000

                if response.status_code < 400 or not self._should_retry(response=response):
                    # 成功或不可重试的错误
                    if response.status_code < 400:
                        self._record_success(response.status_code, duration_ms)
                    else:
                        self._record_failure(f"http_{response.status_code}", duration_ms)
                    return True, response, response.status_code, None

                last_response = response

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                last_exception = e

                if not self._should_retry(exception=e):
                    self._record_failure(type(e).__name__, duration_ms)
                    return False, e, None, type(e).__name__

            # 需要重试
            if attempt < self._retry_config.max_retries:
                delay = self._calculate_delay(attempt)
                logger.debug(
                    "请求失败，第 %d/%d 次重试，延迟 %.2fs: %s %s",
                    attempt + 1, self._retry_config.max_retries, delay, method, url,
                )
                time.sleep(delay)

        # 所有重试都失败了
        duration_ms = 0
        if last_response is not None:
            self._record_failure(f"http_{last_response.status_code}", duration_ms)
            return False, last_response, last_response.status_code, "max_retries_exceeded"
        else:
            error_type = type(last_exception).__name__ if last_exception else "unknown"
            self._record_failure(error_type, duration_ms)
            return False, last_exception, None, "max_retries_exceeded"

    # -------------------------------------------------------------------
    # 便捷方法
    # -------------------------------------------------------------------

    def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        parse_json: bool = True,
    ) -> Any:
        """发送 GET 请求

        Args:
            path: 请求路径
            params: URL 查询参数
            headers: 额外请求头
            parse_json: 是否解析 JSON 响应

        Returns:
            解析后的响应数据（默认 JSON），失败抛出异常

        Raises:
            RuntimeError: 请求失败
        """
        url = self._build_url(path)
        success, result, status_code, error_type = self._request_with_retry(
            "GET", url, params=params, headers=headers,
        )

        if not success:
            raise RuntimeError(f"GET {url} 失败: {error_type}")

        if parse_json and hasattr(result, 'json'):
            try:
                return result.json()
            except Exception:
                return result.text
        return result

    def post(
        self,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        data: Any = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        parse_json: bool = True,
    ) -> Any:
        """发送 POST 请求

        Args:
            path: 请求路径
            json_data: JSON 请求体
            data: 表单/原始数据
            params: URL 查询参数
            headers: 额外请求头
            parse_json: 是否解析 JSON 响应

        Returns:
            解析后的响应数据

        Raises:
            RuntimeError: 请求失败
        """
        url = self._build_url(path)
        success, result, status_code, error_type = self._request_with_retry(
            "POST", url, json=json_data, data=data, params=params, headers=headers,
        )

        if not success:
            raise RuntimeError(f"POST {url} 失败: {error_type}")

        if parse_json and hasattr(result, 'json'):
            try:
                return result.json()
            except Exception:
                return result.text
        return result

    def put(
        self,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        data: Any = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        parse_json: bool = True,
    ) -> Any:
        """发送 PUT 请求"""
        url = self._build_url(path)
        success, result, status_code, error_type = self._request_with_retry(
            "PUT", url, json=json_data, data=data, params=params, headers=headers,
        )

        if not success:
            raise RuntimeError(f"PUT {url} 失败: {error_type}")

        if parse_json and hasattr(result, 'json'):
            try:
                return result.json()
            except Exception:
                return result.text
        return result

    def delete(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        parse_json: bool = True,
    ) -> Any:
        """发送 DELETE 请求"""
        url = self._build_url(path)
        success, result, status_code, error_type = self._request_with_retry(
            "DELETE", url, params=params, headers=headers,
        )

        if not success:
            raise RuntimeError(f"DELETE {url} 失败: {error_type}")

        if parse_json and hasattr(result, 'json'):
            try:
                return result.json()
            except Exception:
                return result.text
        return result

    def patch(
        self,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        data: Any = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        parse_json: bool = True,
    ) -> Any:
        """发送 PATCH 请求"""
        url = self._build_url(path)
        success, result, status_code, error_type = self._request_with_retry(
            "PATCH", url, json=json_data, data=data, params=params, headers=headers,
        )

        if not success:
            raise RuntimeError(f"PATCH {url} 失败: {error_type}")

        if parse_json and hasattr(result, 'json'):
            try:
                return result.json()
            except Exception:
                return result.text
        return result

    def request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> Any:
        """通用请求方法

        Args:
            method: HTTP 方法
            path: 请求路径
            **kwargs: 传递给 httpx 的参数

        Returns:
            httpx Response 对象

        Raises:
            RuntimeError: 请求失败
        """
        url = self._build_url(path)
        success, result, status_code, error_type = self._request_with_retry(
            method.upper(), url, **kwargs,
        )

        if not success:
            raise RuntimeError(f"{method.upper()} {url} 失败: {error_type}")

        return result

    # -------------------------------------------------------------------
    # 统计
    # -------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取调用统计"""
        with self._stats_lock:
            return self._stats.to_dict()

    def reset_stats(self) -> None:
        """重置统计"""
        with self._stats_lock:
            self._stats = CallStats()

    # -------------------------------------------------------------------
    # 上下文管理器支持
    # -------------------------------------------------------------------

    def close(self) -> None:
        """关闭客户端"""
        if hasattr(self, '_client') and self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __del__(self):
        self.close()


# ===========================================================================
# 便捷工厂函数
# ===========================================================================

def create_service_caller(
    api_key: str,
    base_url: str = "",
    max_retries: int = 3,
    timeout: float = 30.0,
) -> ServiceCaller:
    """便捷创建 ServiceCaller

    Args:
        api_key: API Key
        base_url: 基础 URL
        max_retries: 最大重试次数
        timeout: 超时时间（秒）

    Returns:
        ServiceCaller 实例
    """
    return ServiceCaller(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        retry_config=RetryConfig(max_retries=max_retries),
    )
