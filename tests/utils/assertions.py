"""
云汐系统 - 自定义断言工具

提供项目中常用的自定义断言函数，提高测试可读性和一致性：
- API 响应断言
- 数据结构断言
- 性能断言
- 异常断言
- 时间相关断言
"""

import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union, Callable, ContextManager


# ============================================================
# API 响应断言
# ============================================================

def assert_api_success(response: Dict[str, Any], msg: str = ""):
    """
    断言 API 响应成功（code == 0）。

    Args:
        response: API 响应字典
        msg: 自定义错误消息前缀
    """
    prefix = f"{msg}: " if msg else ""
    assert response.get("code") == 0, \
        f"{prefix}API 返回错误: code={response.get('code')}, msg={response.get('message')}"
    assert "data" in response, f"{prefix}API 响应缺少 data 字段"


def assert_api_error(response: Dict[str, Any], expected_code: Optional[int] = None, msg: str = ""):
    """
    断言 API 响应错误（code != 0）。

    Args:
        response: API 响应字典
        expected_code: 期望的错误码（可选）
        msg: 自定义错误消息前缀
    """
    prefix = f"{msg}: " if msg else ""
    assert response.get("code") != 0, f"{prefix}API 应返回错误但返回了成功"
    if expected_code is not None:
        assert response.get("code") == expected_code, \
            f"{prefix}错误码不匹配: 期望 {expected_code}, 实际 {response.get('code')}"


def assert_api_pagination(data: Dict[str, Any], msg: str = ""):
    """
    断言分页响应结构完整。

    Args:
        data: 分页数据字典
        msg: 自定义错误消息前缀
    """
    prefix = f"{msg}: " if msg else ""
    required_keys = ["items", "total", "page", "page_size"]
    for key in required_keys:
        assert key in data, f"{prefix}分页响应缺少字段: {key}"
    assert isinstance(data["items"], list), f"{prefix}items 应为列表"
    assert isinstance(data["total"], int), f"{prefix}total 应为整数"
    assert isinstance(data["page"], int), f"{prefix}page 应为整数"
    assert isinstance(data["page_size"], int), f"{prefix}page_size 应为整数"
    assert data["page"] >= 1, f"{prefix}page 应 >= 1"
    assert data["page_size"] >= 1, f"{prefix}page_size 应 >= 1"


# ============================================================
# 数据结构断言
# ============================================================

def assert_has_keys(data: Dict[str, Any], keys: List[str], msg: str = ""):
    """
    断言字典包含指定的所有键。

    Args:
        data: 待检查的字典
        keys: 期望的键列表
        msg: 自定义错误消息前缀
    """
    prefix = f"{msg}: " if msg else ""
    missing = [k for k in keys if k not in data]
    assert not missing, f"{prefix}缺少键: {missing}"


def assert_dict_contains(subset: Dict[str, Any], full: Dict[str, Any], msg: str = ""):
    """
    断言 full 字典包含 subset 的所有键值对。

    Args:
        subset: 期望包含的子集
        full: 完整字典
        msg: 自定义错误消息前缀
    """
    prefix = f"{msg}: " if msg else ""
    for key, expected_value in subset.items():
        assert key in full, f"{prefix}缺少键: {key}"
        assert full[key] == expected_value, \
            f"{prefix}键 {key} 的值不匹配: 期望 {expected_value}, 实际 {full[key]}"


def assert_list_length(lst: List[Any], expected: int, msg: str = ""):
    """
    断言列表长度。

    Args:
        lst: 待检查的列表
        expected: 期望长度
        msg: 自定义错误消息前缀
    """
    prefix = f"{msg}: " if msg else ""
    assert len(lst) == expected, \
        f"{prefix}列表长度不匹配: 期望 {expected}, 实际 {len(lst)}"


def assert_list_contains(lst: List[Any], item: Any, msg: str = ""):
    """
    断言列表包含指定元素。

    Args:
        lst: 待检查的列表
        item: 期望存在的元素
        msg: 自定义错误消息前缀
    """
    prefix = f"{msg}: " if msg else ""
    assert item in lst, f"{prefix}列表中不包含元素: {item}"


def assert_list_all_match(lst: List[Any], predicate: Callable[[Any], bool], msg: str = ""):
    """
    断言列表中所有元素都满足谓词条件。

    Args:
        lst: 待检查的列表
        predicate: 判断函数
        msg: 自定义错误消息前缀
    """
    prefix = f"{msg}: " if msg else ""
    non_matching = [item for item in lst if not predicate(item)]
    assert not non_matching, \
        f"{prefix}有 {len(non_matching)} 个元素不满足条件: {non_matching[:3]}..."


# ============================================================
# 类型与格式断言
# ============================================================

def assert_is_valid_uuid(value: str, msg: str = ""):
    """断言字符串是有效的 UUID。"""
    prefix = f"{msg}: " if msg else ""
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    assert re.match(uuid_pattern, value, re.IGNORECASE), \
        f"{prefix}无效的 UUID: {value}"


def assert_is_valid_datetime(value: str, msg: str = ""):
    """断言字符串是合法的日期时间格式。"""
    prefix = f"{msg}: " if msg else ""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            datetime.strptime(value.replace("+00:00", "Z"), fmt)
            return
        except ValueError:
            continue
    # 也尝试 ISO 格式
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return
    except (ValueError, AttributeError):
        pass
    raise AssertionError(f"{prefix}无效的日期时间格式: {value}")


def assert_is_valid_email(value: str, msg: str = ""):
    """断言字符串是有效的邮箱格式。"""
    prefix = f"{msg}: " if msg else ""
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    assert re.match(email_pattern, value), f"{prefix}无效的邮箱: {value}"


def assert_is_valid_url(value: str, msg: str = ""):
    """断言字符串是有效的 URL。"""
    prefix = f"{msg}: " if msg else ""
    url_pattern = r'^https?://[^\s/$.?#].[^\s]*$'
    assert re.match(url_pattern, value, re.IGNORECASE), f"{prefix}无效的 URL: {value}"


# ============================================================
# 性能断言
# ============================================================

def assert_execution_time(
    func: Callable,
    max_seconds: float,
    args: Optional[Tuple] = None,
    kwargs: Optional[Dict] = None,
    msg: str = "",
) -> Any:
    """
    断言函数执行时间不超过阈值。

    Args:
        func: 待测试的函数
        max_seconds: 最大允许执行时间（秒）
        args: 位置参数
        kwargs: 关键字参数
        msg: 自定义错误消息前缀

    Returns:
        函数执行结果
    """
    prefix = f"{msg}: " if msg else ""
    args = args or ()
    kwargs = kwargs or {}

    start = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed = time.perf_counter() - start

    assert elapsed <= max_seconds, \
        f"{prefix}执行时间 {elapsed:.4f}s 超过阈值 {max_seconds}s"

    return result


async def assert_async_execution_time(
    coro_func: Callable,
    max_seconds: float,
    args: Optional[Tuple] = None,
    kwargs: Optional[Dict] = None,
    msg: str = "",
) -> Any:
    """
    断言异步函数执行时间不超过阈值。

    Args:
        coro_func: 待测试的异步函数
        max_seconds: 最大允许执行时间（秒）
        args: 位置参数
        kwargs: 关键字参数
        msg: 自定义错误消息前缀

    Returns:
        函数执行结果
    """
    import asyncio
    prefix = f"{msg}: " if msg else ""
    args = args or ()
    kwargs = kwargs or {}

    start = time.perf_counter()
    result = await coro_func(*args, **kwargs)
    elapsed = time.perf_counter() - start

    assert elapsed <= max_seconds, \
        f"{prefix}执行时间 {elapsed:.4f}s 超过阈值 {max_seconds}s"

    return result


# ============================================================
# 异常断言
# ============================================================

def assert_raises(
    exception_type: type,
    func: Callable,
    *args,
    match: Optional[str] = None,
    **kwargs,
):
    """
    断言函数抛出指定类型的异常。

    类似 pytest.raises 但作为函数式调用，更适合某些场景。

    Args:
        exception_type: 期望的异常类型
        func: 待测试的函数
        *args: 位置参数
        match: 异常消息匹配的正则（可选）
        **kwargs: 关键字参数
    """
    try:
        func(*args, **kwargs)
    except exception_type as e:
        if match:
            assert re.search(match, str(e)), \
                f"异常消息不匹配: 期望匹配 '{match}', 实际 '{e}'"
        return e
    except Exception as e:
        raise AssertionError(
            f"期望抛出 {exception_type.__name__}, 实际抛出 {type(e).__name__}: {e}"
        )
    raise AssertionError(f"期望抛出 {exception_type.__name__}, 但没有抛出任何异常")


# ============================================================
# 时间相关断言
# ============================================================

def assert_datetime_close(
    actual: datetime,
    expected: datetime,
    tolerance_seconds: float = 1.0,
    msg: str = "",
):
    """
    断言两个时间接近（在容差范围内）。

    Args:
        actual: 实际时间
        expected: 期望时间
        tolerance_seconds: 容差（秒）
        msg: 自定义错误消息前缀
    """
    prefix = f"{msg}: " if msg else ""
    diff = abs((actual - expected).total_seconds())
    assert diff <= tolerance_seconds, \
        f"{prefix}时间差 {diff:.2f}s 超过容差 {tolerance_seconds}s"


# ============================================================
# 安全相关断言
# ============================================================

def assert_not_in_response(text: str, sensitive: List[str], msg: str = ""):
    """
    断言响应文本中不包含敏感信息。

    Args:
        text: 响应文本
        sensitive: 敏感内容列表
        msg: 自定义错误消息前缀
    """
    prefix = f"{msg}: " if msg else ""
    found = [s for s in sensitive if s in text]
    assert not found, f"{prefix}响应中包含敏感信息: {found}"
