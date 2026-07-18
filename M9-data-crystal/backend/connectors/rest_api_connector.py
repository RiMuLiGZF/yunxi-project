"""
云汐 M9 数据水晶 - REST API 连接器

P3 优化：数据采集管道 + 连接器生态
REST API 连接器，支持多种认证、分页、速率限制、重试机制
"""

from __future__ import annotations

import time
import logging
from typing import Iterator, List, Dict, Any, Optional
from urllib.parse import urljoin, urlencode

from .base import (
    BaseConnector,
    ConnectorMeta,
    ConnectorRegistry,
    ConnectorType,
    ConnectionStatus,
)

logger = logging.getLogger(__name__)


@ConnectorRegistry.register
class RESTAPIConnector(BaseConnector):
    """
    REST API 连接器

    特性：
    - GET/POST 支持
    - 多种认证方式：Bearer Token / API Key / Basic Auth / 无认证
    - 多种分页方式：offset / cursor / link header
    - 速率限制
    - 重试机制（指数退避）
    - 自定义 Headers
    """

    meta = ConnectorMeta(
        name="rest_api",
        connector_type=ConnectorType.API,
        description="REST API 连接器，支持多种认证、分页、速率限制、重试",
        version="1.0.0",
        supported_operations=["read", "batch_read", "stream_read"],
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._base_url: str = ""
        self._session = None
        self._rate_limit_remaining: int = 0
        self._rate_limit_reset: float = 0
        self._last_request_time: float = 0
        self._min_request_interval: float = 0.0  # 最小请求间隔（秒）

    def connect(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        建立 API 连接（配置认证、初始化 session）

        config 参数：
        - base_url: API 基础 URL
        - auth_type: none / bearer / api_key / basic（默认 none）
        - token: Bearer Token
        - api_key: API Key
        - api_key_header: API Key 头名（默认 X-API-Key）
        - username: Basic Auth 用户名
        - password: Basic Auth 密码
        - default_headers: 默认请求头 dict
        - timeout: 请求超时（秒，默认 30）
        - rate_limit_per_minute: 每分钟请求数限制（0 表示不限制）
        - retry_max_attempts: 最大重试次数（默认 3）
        - retry_backoff_factor: 重试退避因子（默认 2）
        - verify_ssl: 是否验证 SSL（默认 True）
        """
        if config:
            self._config.update(config)

        self._status = ConnectionStatus.CONNECTING
        try:
            try:
                import requests
            except ImportError:
                self._status = ConnectionStatus.ERROR
                self._last_error = "requests 未安装，请执行 pip install requests"
                logger.warning(self._last_error)
                return False

            self._base_url = self._config.get("base_url", "")
            if not self._base_url:
                raise ValueError("必须指定 base_url")

            # 确保 base_url 以 / 结尾
            if not self._base_url.endswith("/"):
                self._base_url += "/"

            # 创建 session
            self._session = requests.Session()

            # 配置认证
            auth_type = self._config.get("auth_type", "none")
            if auth_type == "bearer":
                token = self._config.get("token", "")
                self._session.headers["Authorization"] = f"Bearer {token}"
            elif auth_type == "api_key":
                api_key = self._config.get("api_key", "")
                key_header = self._config.get("api_key_header", "X-API-Key")
                self._session.headers[key_header] = api_key
            elif auth_type == "basic":
                username = self._config.get("username", "")
                password = self._config.get("password", "")
                self._session.auth = (username, password)

            # 默认请求头
            default_headers = self._config.get("default_headers", {})
            if default_headers:
                self._session.headers.update(default_headers)

            # SSL 验证
            verify_ssl = self._config.get("verify_ssl", True)
            self._session.verify = verify_ssl

            # 速率限制
            rate_limit = self._config.get("rate_limit_per_minute", 0)
            if rate_limit > 0:
                self._min_request_interval = 60.0 / rate_limit

            self._status = ConnectionStatus.CONNECTED
            self._stats.connection_count += 1
            logger.info(f"REST API 连接成功: {self._base_url}")
            return True

        except Exception as e:
            self._status = ConnectionStatus.ERROR
            self._last_error = str(e)
            self._record_error()
            logger.error(f"REST API 连接失败: {e}")
            return False

    def disconnect(self) -> bool:
        """断开 API 连接"""
        try:
            if self._session:
                self._session.close()
                self._session = None
            self._status = ConnectionStatus.DISCONNECTED
            logger.info("REST API 连接已关闭")
            return True
        except Exception as e:
            self._last_error = str(e)
            self._record_error()
            return False

    def _request_with_retry(self, method: str, url: str, **kwargs) -> Any:
        """带重试的请求"""
        import requests

        max_attempts = self._config.get("retry_max_attempts", 3)
        backoff_factor = self._config.get("retry_backoff_factor", 2)
        timeout = self._config.get("timeout", 30)

        kwargs.setdefault("timeout", timeout)

        last_exception = None
        for attempt in range(max_attempts):
            try:
                # 速率限制
                if self._min_request_interval > 0:
                    elapsed = time.time() - self._last_request_time
                    if elapsed < self._min_request_interval:
                        time.sleep(self._min_request_interval - elapsed)

                self._last_request_time = time.time()

                response = self._session.request(method, url, **kwargs)

                # 更新速率限制信息
                if "X-RateLimit-Remaining" in response.headers:
                    self._rate_limit_remaining = int(response.headers["X-RateLimit-Remaining"])
                if "X-RateLimit-Reset" in response.headers:
                    self._rate_limit_reset = float(response.headers["X-RateLimit-Reset"])

                # 处理 429 速率限制
                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", backoff_factor ** attempt))
                    logger.warning(f"速率限制，等待 {retry_after}s 后重试 ({attempt + 1}/{max_attempts})")
                    time.sleep(retry_after)
                    continue

                # 5xx 错误重试
                if response.status_code >= 500 and attempt < max_attempts - 1:
                    wait_time = backoff_factor ** attempt
                    logger.warning(f"服务器错误 {response.status_code}，等待 {wait_time}s 后重试 ({attempt + 1}/{max_attempts})")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response

            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < max_attempts - 1:
                    wait_time = backoff_factor ** attempt
                    logger.warning(f"请求失败，等待 {wait_time}s 后重试 ({attempt + 1}/{max_attempts}): {e}")
                    time.sleep(wait_time)
                else:
                    raise

        raise last_exception  # type: ignore

    def _build_url(self, endpoint: str) -> str:
        """构建完整 URL"""
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        return urljoin(self._base_url, endpoint.lstrip("/"))

    def read(self, query: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        """
        流式读取 API 数据

        query 参数：
        - endpoint: API 端点路径
        - method: GET / POST（默认 GET）
        - params: URL 查询参数
        - data: POST 请求体
        - json: JSON 请求体
        - pagination: 分页配置
            - type: offset / cursor / link_header / none（默认 none）
            - limit_param: 页大小参数名（默认 limit）
            - offset_param: 偏移量参数名（默认 offset）
            - cursor_param: 游标参数名（默认 cursor）
            - page_size: 每页大小（默认 100）
            - max_pages: 最大页数（0 表示不限制）
            - data_path: 数据在响应中的路径（如 data.items）
            - next_cursor_path: 下一页游标在响应中的路径
        """
        self._ensure_connected()
        query = query or {}

        try:
            endpoint = query.get("endpoint", "")
            method = query.get("method", "GET").upper()
            params = dict(query.get("params", {}))
            data = query.get("data")
            json_body = query.get("json")

            pagination = query.get("pagination", {})
            pag_type = pagination.get("type", "none")
            page_size = pagination.get("page_size", 100)
            max_pages = pagination.get("max_pages", 0)
            data_path = pagination.get("data_path", "")
            limit_param = pagination.get("limit_param", "limit")
            offset_param = pagination.get("offset_param", "offset")
            cursor_param = pagination.get("cursor_param", "cursor")
            next_cursor_path = pagination.get("next_cursor_path", "")

            count = 0
            page_count = 0
            current_offset = 0
            current_cursor = None

            while True:
                # 构建请求参数
                request_params = dict(params)

                if pag_type == "offset":
                    request_params[limit_param] = page_size
                    request_params[offset_param] = current_offset
                elif pag_type == "cursor" and current_cursor:
                    request_params[cursor_param] = current_cursor
                    request_params[limit_param] = page_size

                # 发送请求
                url = self._build_url(endpoint)
                kwargs = {"params": request_params}
                if method == "POST":
                    if json_body:
                        kwargs["json"] = json_body
                    if data:
                        kwargs["data"] = data

                response = self._request_with_retry(method, url, **kwargs)
                response_data = response.json()

                # 提取数据
                items = response_data
                if data_path:
                    items = self._extract_by_path(response_data, data_path)

                if items is None:
                    items = []

                if not isinstance(items, list):
                    items = [items] if items else []

                # 产出数据
                for item in items:
                    if isinstance(item, dict):
                        yield item
                    else:
                        yield {"value": item}
                    count += 1

                page_count += 1

                # 检查是否继续分页
                if pag_type == "none":
                    break

                if max_pages > 0 and page_count >= max_pages:
                    break

                if not items or len(items) < page_size:
                    break

                # 更新分页游标
                if pag_type == "offset":
                    current_offset += page_size
                elif pag_type == "cursor":
                    if next_cursor_path:
                        current_cursor = self._extract_by_path(response_data, next_cursor_path)
                        if not current_cursor:
                            break
                    else:
                        break
                elif pag_type == "link_header":
                    # Link header 分页
                    link_header = response.headers.get("Link", "")
                    next_url = self._parse_link_header(link_header, "next")
                    if not next_url:
                        break
                    # 使用 next_url 替代 endpoint 和 params
                    endpoint = next_url
                    params = {}
                else:
                    break

            self._record_read(count=count, bytes_read=count * 200)

        except Exception as e:
            self._record_error()
            logger.error(f"REST API 读取失败: {e}")
            raise

    def _extract_by_path(self, data: Any, path: str) -> Any:
        """按路径提取数据"""
        if not path:
            return data
        keys = path.strip(".").split(".")
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            elif isinstance(current, list) and key.isdigit():
                idx = int(key)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                return None
        return current

    def _parse_link_header(self, link_header: str, rel: str) -> Optional[str]:
        """解析 Link header，返回指定 rel 的 URL"""
        import re
        pattern = r'<([^>]+)>;\s*rel="([^"]+)"'
        for match in re.finditer(pattern, link_header):
            if match.group(2) == rel:
                return match.group(1)
        return None

    def read_batch(self, batch_size: int = 100, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """批量读取"""
        query = query or {}
        query.setdefault("pagination", {})
        query["pagination"]["page_size"] = batch_size
        query["pagination"]["max_pages"] = 1
        return super().read_batch(batch_size, query)

    def list_tables(self) -> List[str]:
        """列出可用的 API 端点（尝试从 base URL 获取）"""
        self._ensure_connected()
        try:
            # 尝试请求根路径获取端点列表
            response = self._request_with_retry("GET", self._base_url)
            data = response.json()

            # 尝试从常见字段中提取端点
            endpoints = []
            if isinstance(data, dict):
                for key in ["endpoints", "routes", "apis", "resources"]:
                    if key in data and isinstance(data[key], list):
                        endpoints.extend(str(e) for e in data[key])
                        break
                if not endpoints:
                    endpoints = list(data.keys())

            return endpoints[:50]  # 限制返回数量
        except Exception:
            return []

    def _health_probe(self) -> None:
        """健康探针：请求基础 URL"""
        if self._session:
            try:
                response = self._session.get(self._base_url, timeout=5)
                response.raise_for_status()
            except Exception:
                # 尝试简单的连接测试
                import requests
                requests.get(self._base_url, timeout=5)
