"""
E2E 测试 - 辅助函数

提供 E2E 测试常用的辅助工具：
- 等待条件满足
- 重试机制
- 断言辅助
- 性能测量
- ID 生成
"""

import time
import uuid
import functools
from typing import Callable, Any, Optional, Dict, Tuple
from datetime import datetime


# ============================================================
# 等待与重试
# ============================================================

def wait_for_condition(
    condition_fn: Callable[[], bool],
    timeout: float = 30.0,
    interval: float = 0.5,
    description: str = "condition",
) -> bool:
    """
    等待条件满足

    Args:
        condition_fn: 条件判断函数，返回 True 表示条件满足
        timeout: 超时时间（秒）
        interval: 检查间隔（秒）
        description: 条件描述（用于错误信息）

    Returns:
        条件是否在超时前满足
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            if condition_fn():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def retry_on_failure(
    func: Callable,
    max_retries: int = 3,
    retry_interval: float = 1.0,
    retry_on_exceptions: Tuple = (Exception,),
) -> Any:
    """
    重试函数执行

    Args:
        func: 要执行的函数
        max_retries: 最大重试次数
        retry_interval: 重试间隔（秒）
        retry_on_exceptions: 需要重试的异常类型

    Returns:
        函数执行结果

    Raises:
        最后一次执行的异常
    """
    last_exception = None
    for attempt in range(max_retries):
        try:
            return func()
        except retry_on_exceptions as e:
            last_exception = e
            if attempt < max_retries - 1:
                time.sleep(retry_interval)
    if last_exception:
        raise last_exception


def retry_decorator(
    max_retries: int = 3,
    retry_interval: float = 1.0,
    retry_on_exceptions: Tuple = (Exception,),
):
    """
    重试装饰器

    使用示例：
        @retry_decorator(max_retries=3)
        def my_function():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return retry_on_failure(
                lambda: func(*args, **kwargs),
                max_retries=max_retries,
                retry_interval=retry_interval,
                retry_on_exceptions=retry_on_exceptions,
            )
        return wrapper
    return decorator


# ============================================================
# 断言辅助
# ============================================================

def assert_api_success(response: Dict[str, Any], msg: str = ""):
    """
    断言 API 响应成功

    Args:
        response: API 响应字典
        msg: 额外的错误信息
    """
    assert response.get("code") == 0, \
        f"API 返回失败: code={response.get('code')}, " \
        f"message={response.get('message')}. {msg}"
    assert "data" in response, f"响应缺少 data 字段. {msg}"


def assert_api_error(
    response: Dict[str, Any],
    expected_code: Optional[int] = None,
    msg: str = "",
):
    """
    断言 API 响应错误

    Args:
        response: API 响应字典
        expected_code: 期望的错误码（可选）
        msg: 额外的错误信息
    """
    assert response.get("code") != 0, f"API 应该返回错误但返回了成功. {msg}"
    if expected_code is not None:
        assert response.get("code") == expected_code, \
            f"错误码不匹配: 期望 {expected_code}, 实际 {response.get('code')}. {msg}"


def assert_has_keys(data: Dict[str, Any], keys: list, msg: str = ""):
    """
    断言字典包含指定 key

    Args:
        data: 字典数据
        keys: 期望的 key 列表
        msg: 额外的错误信息
    """
    missing = [k for k in keys if k not in data]
    assert not missing, f"缺少 key: {missing}. {msg}"


def assert_paginated_response(data: Dict[str, Any], msg: str = ""):
    """
    断言分页响应结构

    Args:
        data: 分页响应数据
        msg: 额外的错误信息
    """
    assert_has_keys(data, ["items", "total", "page", "page_size"], msg)
    assert isinstance(data["items"], list), f"items 应该是列表. {msg}"
    assert isinstance(data["total"], int), f"total 应该是整数. {msg}"
    assert isinstance(data["page"], int), f"page 应该是整数. {msg}"
    assert isinstance(data["page_size"], int), f"page_size 应该是整数. {msg}"


def assert_valid_uuid(value: str, msg: str = ""):
    """
    断言字符串是有效的 UUID

    Args:
        value: 待验证的字符串
        msg: 额外的错误信息
    """
    import re
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    assert bool(re.match(uuid_pattern, value, re.IGNORECASE)), \
        f"'{value}' 不是有效的 UUID. {msg}"


def assert_valid_datetime(date_str: str, msg: str = ""):
    """
    断言字符串是合法的日期时间格式

    Args:
        date_str: 日期时间字符串
        msg: 额外的错误信息
    """
    try:
        datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return
    except (ValueError, AttributeError):
        pass

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in formats:
        try:
            datetime.strptime(date_str, fmt)
            return
        except ValueError:
            continue

    raise AssertionError(f"'{date_str}' 不是有效的日期时间格式. {msg}")


# ============================================================
# 性能测量
# ============================================================

class measure_time:
    """
    代码块执行时间测量（上下文管理器）

    使用示例：
        with measure_time() as t:
            do_something()
        print(f"耗时: {t.elapsed_ms}ms")
    """

    def __init__(self, name: str = ""):
        self.name = name
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.elapsed: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        self.elapsed = self.end_time - self.start_time
        self.elapsed_ms = self.elapsed * 1000
        return False


def time_function(func: Callable) -> Callable:
    """
    函数执行时间装饰器

    使用示例：
        @time_function
        def my_function():
            ...
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = (time.time() - start) * 1000
        print(f"[Time] {func.__name__}: {elapsed:.2f}ms")
        return result
    return wrapper


# ============================================================
# ID 生成
# ============================================================

def generate_test_id(prefix: str = "e2e") -> str:
    """
    生成测试用唯一 ID

    Args:
        prefix: ID 前缀

    Returns:
        唯一 ID 字符串
    """
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def generate_timestamp_id(prefix: str = "e2e") -> str:
    """
    生成带时间戳的测试 ID

    Args:
        prefix: ID 前缀

    Returns:
        带时间戳的唯一 ID
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}_{uuid.uuid4().hex[:6]}"


# ============================================================
# 数据处理
# ============================================================

def flatten_dict(d: Dict[str, Any], parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
    """
    扁平化嵌套字典

    Args:
        d: 嵌套字典
        parent_key: 父级 key
        sep: 分隔符

    Returns:
        扁平化后的字典
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def compare_dicts(
    expected: Dict[str, Any],
    actual: Dict[str, Any],
    ignore_keys: Optional[list] = None,
) -> Tuple[bool, str]:
    """
    比较两个字典

    Args:
        expected: 期望的字典
        actual: 实际的字典
        ignore_keys: 忽略的 key 列表

    Returns:
        (是否匹配, 差异描述)
    """
    ignore_keys = ignore_keys or []

    exp_filtered = {k: v for k, v in expected.items() if k not in ignore_keys}
    act_filtered = {k: v for k, v in actual.items() if k not in ignore_keys}

    if exp_filtered == act_filtered:
        return True, ""

    diffs = []
    for key in set(list(exp_filtered.keys()) + list(act_filtered.keys())):
        if key not in exp_filtered:
            diffs.append(f"缺少字段: {key} (实际值: {act_filtered[key]})")
        elif key not in act_filtered:
            diffs.append(f"多余字段: {key} (期望值: {exp_filtered[key]})")
        elif exp_filtered[key] != act_filtered[key]:
            diffs.append(
                f"字段 '{key}' 值不同: 期望 {exp_filtered[key]}, 实际 {act_filtered[key]}"
            )

    return False, "; ".join(diffs)


# ============================================================
# 测试数据验证
# ============================================================

def validate_user_data(user: Dict[str, Any], require_password: bool = False) -> Tuple[bool, str]:
    """
    验证用户数据结构

    Args:
        user: 用户数据
        require_password: 是否要求包含密码字段

    Returns:
        (是否有效, 错误描述)
    """
    required = ["id", "username", "email", "role"]
    if require_password:
        required.append("password")

    for field in required:
        if field not in user:
            return False, f"缺少字段: {field}"

    if not isinstance(user.get("id"), (int, str)):
        return False, "id 类型错误"
    if not isinstance(user.get("username"), str):
        return False, "username 类型错误"

    return True, ""


def validate_module_status(status: Dict[str, Any]) -> Tuple[bool, str]:
    """
    验证模块状态数据结构

    Args:
        status: 模块状态数据

    Returns:
        (是否有效, 错误描述)
    """
    required = ["key", "name", "status"]
    for field in required:
        if field not in status:
            return False, f"缺少字段: {field}"

    valid_statuses = ["running", "stopped", "error", "degraded", "unknown"]
    if status.get("status") not in valid_statuses:
        return False, f"无效的状态值: {status.get('status')}"

    return True, ""
