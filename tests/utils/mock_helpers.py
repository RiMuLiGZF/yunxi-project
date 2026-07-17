"""
云汐系统 - Mock 辅助函数

提供常用的 Mock 工具，简化测试中的外部依赖模拟：
- HTTP 响应 Mock
- 异步函数 Mock
- 数据库会话 Mock
- 文件系统 Mock
- 时间 Mock
- 日志 Mock
"""

import json
import time
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from typing import Any, Dict, List, Optional, Union, Callable
from datetime import datetime, timedelta


# ============================================================
# HTTP 响应 Mock
# ============================================================

def mock_http_response(
    status_code: int = 200,
    json_data: Optional[Dict[str, Any]] = None,
    text: str = "",
    headers: Optional[Dict[str, str]] = None,
    content: Optional[bytes] = None,
) -> Mock:
    """
    创建 Mock HTTP 响应对象（同步 requests 风格）。

    Args:
        status_code: HTTP 状态码
        json_data: JSON 响应数据（会自动序列化）
        text: 文本响应内容
        headers: 响应头
        content: 二进制响应内容

    Returns:
        Mock 对象，模拟 requests.Response 接口
    """
    mock_resp = Mock()
    mock_resp.status_code = status_code
    mock_resp.ok = 200 <= status_code < 300
    mock_resp.headers = headers or {}
    mock_resp.text = text or (json.dumps(json_data, ensure_ascii=False) if json_data else "")
    mock_resp.content = content or mock_resp.text.encode("utf-8")

    # json() 方法
    if json_data is not None:
        mock_resp.json.return_value = json_data
    else:
        def _json_raises():
            raise ValueError("No JSON data")
        mock_resp.json.side_effect = _json_raises

    # raise_for_status() 方法
    def _raise_for_status():
        if not mock_resp.ok:
            raise Exception(f"HTTP {status_code}")
    mock_resp.raise_for_status = _raise_for_status

    return mock_resp


def mock_async_http_response(
    status_code: int = 200,
    json_data: Optional[Dict[str, Any]] = None,
    text: str = "",
    headers: Optional[Dict[str, str]] = None,
) -> MagicMock:
    """
    创建 Mock 异步 HTTP 响应对象（httpx 风格）。

    Args:
        status_code: HTTP 状态码
        json_data: JSON 响应数据
        text: 文本响应内容
        headers: 响应头

    Returns:
        MagicMock 对象，模拟 httpx.Response 接口
    """
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.is_success = 200 <= status_code < 300
    mock_resp.headers = headers or {}
    mock_resp.text = text or (json.dumps(json_data, ensure_ascii=False) if json_data else "")

    # 异步 json() 方法
    if json_data is not None:
        mock_resp.json = AsyncMock(return_value=json_data)
    else:
        mock_resp.json = AsyncMock(side_effect=ValueError("No JSON data"))

    # aread() 方法
    mock_resp.aread = AsyncMock(return_value=mock_resp.text.encode("utf-8"))

    return mock_resp


def mock_httpx_client(
    default_status: int = 200,
    default_json: Optional[Dict[str, Any]] = None,
    responses: Optional[Dict[str, Dict[str, Any]]] = None,
) -> MagicMock:
    """
    创建 Mock httpx.AsyncClient。

    Args:
        default_status: 默认响应状态码
        default_json: 默认响应 JSON
        responses: 按 URL 路径匹配的响应字典，key 为路径，value 为响应配置

    Returns:
        MagicMock 对象，模拟 httpx.AsyncClient 接口
    """
    mock_client = MagicMock()

    def _make_response(method: str, url: str, **kwargs):
        # 查找匹配的响应配置
        if responses:
            for path_pattern, resp_config in responses.items():
                if path_pattern in url:
                    return mock_async_http_response(
                        status_code=resp_config.get("status", default_status),
                        json_data=resp_config.get("json", default_json),
                        text=resp_config.get("text", ""),
                        headers=resp_config.get("headers"),
                    )
        return mock_async_http_response(
            status_code=default_status,
            json_data=default_json,
        )

    # 配置 HTTP 方法
    for method in ["get", "post", "put", "delete", "patch", "head", "options"]:
        mock_method = AsyncMock(side_effect=lambda *args, _method=method, **kwargs: _make_response(_method, args[0] if args else "", **kwargs))
        setattr(mock_client, method, mock_method)

    # 上下文管理器支持
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    return mock_client


# ============================================================
# 数据库 Mock
# ============================================================

def mock_db_session(query_results: Optional[List[Any]] = None) -> MagicMock:
    """
    创建 Mock 数据库会话（SQLAlchemy 风格）。

    Args:
        query_results: query().all() 返回的结果列表

    Returns:
        MagicMock 对象，模拟 SQLAlchemy Session 接口
    """
    mock_session = MagicMock()

    # query 链式调用
    mock_query = MagicMock()
    mock_query.all.return_value = query_results or []
    mock_query.first.return_value = (query_results or [None])[0]
    mock_query.one_or_none.return_value = (query_results or [None])[0]
    mock_query.count.return_value = len(query_results or [])
    mock_query.filter.return_value = mock_query
    mock_query.filter_by.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.offset.return_value = mock_query
    mock_query.join.return_value = mock_query

    mock_session.query.return_value = mock_query
    mock_session.execute.return_value = mock_query

    return mock_session


# ============================================================
# 时间 Mock
# ============================================================

class MockTimeController:
    """
    时间控制器 - 用于测试中模拟时间流逝。

    使用示例:
        with patch_time() as time_ctrl:
            time_ctrl.advance(seconds=30)
            assert time.time() == initial + 30
    """

    def __init__(self, start_time: Optional[float] = None):
        self._current_time = start_time or time.time()
        self._original_time = time.time
        self._original_datetime_now = datetime.now

    def advance(self, seconds: float = 0, minutes: float = 0, hours: float = 0):
        """推进时间"""
        total = seconds + minutes * 60 + hours * 3600
        self._current_time += total

    def set_time(self, new_time: float):
        """设置绝对时间"""
        self._current_time = new_time

    def time(self) -> float:
        return self._current_time

    def datetime_now(self) -> datetime:
        return datetime.fromtimestamp(self._current_time)

    @property
    def now(self) -> float:
        return self._current_time


def patch_time(start_time: Optional[float] = None) -> MockTimeController:
    """
    上下文管理器/装饰器：patch 时间相关函数。

    Args:
        start_time: 起始时间戳，默认使用当前时间

    Returns:
        MockTimeController 实例，可用于控制时间流逝
    """
    controller = MockTimeController(start_time)

    # 创建 patch 对象
    time_patch = patch("time.time", side_effect=controller.time)
    time_patch.start()

    return controller


# ============================================================
# 日志 Mock
# ============================================================

def capture_logs(logger_name: str = "", level: int = 20):
    """
    上下文管理器：捕获日志输出用于断言。

    使用示例:
        with capture_logs("my_module") as logs:
            do_something()
            assert any("error" in log.message.lower() for log in logs)
    """
    import logging

    class LogCapture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records: List[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord):
            self.records.append(record)

        @property
        def messages(self) -> List[str]:
            return [record.getMessage() for record in self.records]

    handler = LogCapture()
    handler.setLevel(level)

    logger = logging.getLogger(logger_name)
    original_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(level)

    # 返回 handler 给调用者
    return _LogCaptureContext(handler, logger, original_level)


class _LogCaptureContext:
    def __init__(self, handler, logger, original_level):
        self.handler = handler
        self.logger = logger
        self.original_level = original_level

    def __enter__(self):
        return self.handler

    def __exit__(self, *args):
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.original_level)
        return False


# ============================================================
# 环境变量 Mock
# ============================================================

def patch_env_vars(vars_dict: Dict[str, str]):
    """
    上下文管理器：临时设置环境变量。

    使用示例:
        with patch_env_vars({"DB_HOST": "localhost"}):
            assert os.environ["DB_HOST"] == "localhost"
    """
    return patch.dict("os.environ", vars_dict, clear=False)


# ============================================================
# 异步 Mock 辅助
# ============================================================

def async_return(value: Any = None) -> AsyncMock:
    """
    创建一个返回指定值的异步 Mock。

    使用示例:
        mock_obj.method = async_return(42)
        result = await mock_obj.method()  # 42
    """
    return AsyncMock(return_value=value)


def async_raise(exception: BaseException) -> AsyncMock:
    """
    创建一个抛出指定异常的异步 Mock。

    使用示例:
        mock_obj.method = async_raise(ValueError("test error"))
    """
    return AsyncMock(side_effect=exception)


# ============================================================
# 配置 Mock
# ============================================================

def mock_config(values: Dict[str, Any]) -> MagicMock:
    """
    创建 Mock 配置对象，支持属性访问。

    Args:
        values: 配置键值对

    Returns:
        MagicMock 配置对象
    """
    config = MagicMock()
    for key, value in values.items():
        setattr(config, key, value)
        # 也支持 dict 风格访问
        config.__setitem__(key, value)
    config.__getitem__.side_effect = lambda k: values[k]
    config.get.side_effect = lambda k, default=None: values.get(k, default)
    return config
