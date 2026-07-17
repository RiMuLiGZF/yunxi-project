"""
M1 Agent 集群 - 全链路追踪上下文（Trace Context）

基于 contextvars 实现异步安全的 trace_id / span_id 传递，
确保跨协程、跨消息总线、跨API调用的全链路日志可关联。

设计原则：
- 异步安全：使用 contextvars 而非 threading.local，协程切换时自动隔离
- 零依赖：仅使用 Python 标准库，不引入 OpenTelemetry 等第三方依赖
- 向后兼容：没有 trace_id 时不影响正常运行，自动生成兜底
- 轻量级：SpanContext 为简化版，仅记录必要信息，不做采样/导出

典型用法：
    from src.observability.trace_context import get_trace_id, set_trace_id, new_span

    # 获取/生成 trace_id
    trace_id = get_trace_id()

    # 跨上下文传递
    token = set_trace_id(external_trace_id)
    try:
        ...  # 业务逻辑
    finally:
        reset_trace_id(token)

    # 使用 new_span 上下文管理器
    with new_span("db_query") as span:
        span.set_attribute("table", "users")
        ...  # 业务逻辑
"""

from __future__ import annotations

import contextvars
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Generator


# ── 上下文变量定义 ──────────────────────────────────────────

# 当前请求/链路的 trace_id（全局唯一，贯穿整条调用链）
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)

# 当前操作的 span_id（局部唯一，标识链路中的某个操作节点）
_span_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "span_id", default=""
)

# 请求开始时间戳（秒级浮点数），用于计算请求耗时
_request_start_var: contextvars.ContextVar[float] = contextvars.ContextVar(
    "request_start", default=0.0
)


# ── trace_id 操作 ──────────────────────────────────────────

def get_trace_id() -> str:
    """获取当前 trace_id，如不存在则生成新的并设置到上下文。

    Returns:
        当前 trace_id 字符串（UUID4 格式，含短横线）
    """
    tid = _trace_id_var.get()
    if not tid:
        tid = generate_trace_id()
        _trace_id_var.set(tid)
    return tid


def set_trace_id(trace_id: str) -> contextvars.Token:
    """设置当前 trace_id，返回 token 用于后续恢复。

    Args:
        trace_id: 要设置的 trace_id 字符串

    Returns:
        contextvars.Token 对象，可传入 reset_trace_id 恢复之前的值
    """
    return _trace_id_var.set(trace_id)


def reset_trace_id(token: contextvars.Token) -> None:
    """根据 token 恢复 trace_id 到之前的值。

    Args:
        token: set_trace_id 返回的 Token 对象
    """
    _trace_id_var.reset(token)


def generate_trace_id() -> str:
    """生成新的 trace_id（UUID4 格式，短横线分隔）。

    Returns:
        形如 '550e8400-e29b-41d4-a716-446655440000' 的 trace_id
    """
    return str(uuid.uuid4())


def clear_trace_id() -> None:
    """清除当前 trace_id（置空字符串）。

    通常在请求处理完毕后调用，避免上下文污染。
    """
    _trace_id_var.set("")


# ── span_id 操作 ──────────────────────────────────────────

def get_span_id() -> str:
    """获取当前 span_id，如不存在则生成新的并设置到上下文。

    Returns:
        当前 span_id 字符串（UUID4 前 16 位十六进制字符）
    """
    sid = _span_id_var.get()
    if not sid:
        sid = generate_span_id()
        _span_id_var.set(sid)
    return sid


def set_span_id(span_id: str) -> contextvars.Token:
    """设置当前 span_id，返回 token 用于后续恢复。

    Args:
        span_id: 要设置的 span_id 字符串

    Returns:
        contextvars.Token 对象
    """
    return _span_id_var.set(span_id)


def reset_span_id(token: contextvars.Token) -> None:
    """根据 token 恢复 span_id 到之前的值。

    Args:
        token: set_span_id 返回的 Token 对象
    """
    _span_id_var.reset(token)


def generate_span_id() -> str:
    """生成新的 span_id（UUID4 前 16 位十六进制字符）。

    Returns:
        16 位十六进制字符串
    """
    return uuid.uuid4().hex[:16]


def clear_span_id() -> None:
    """清除当前 span_id（置空字符串）。"""
    _span_id_var.set("")


# ── request_start 操作 ──────────────────────────────────────

def get_request_start() -> float:
    """获取请求开始时间戳。

    Returns:
        请求开始时间（秒级浮点数，Unix 时间戳），未设置则返回 0.0
    """
    return _request_start_var.get()


def set_request_start(timestamp: float | None = None) -> contextvars.Token:
    """设置请求开始时间戳。

    Args:
        timestamp: 请求开始时间，None 则使用当前时间

    Returns:
        contextvars.Token 对象
    """
    if timestamp is None:
        timestamp = time.time()
    return _request_start_var.set(timestamp)


def reset_request_start(token: contextvars.Token) -> None:
    """根据 token 恢复 request_start 到之前的值。

    Args:
        token: set_request_start 返回的 Token 对象
    """
    _request_start_var.reset(token)


def get_elapsed_ms() -> float:
    """获取从请求开始到现在的耗时（毫秒）。

    Returns:
        耗时毫秒数，未设置开始时间则返回 0.0
    """
    start = _request_start_var.get()
    if start <= 0:
        return 0.0
    return (time.time() - start) * 1000.0


# ── SpanContext 简化版 Span ──────────────────────────────────

@dataclass
class SpanContext:
    """简化版 Span 上下文（不依赖 OpenTelemetry）。

    用于在代码块中标记一个操作的开始和结束，记录耗时与属性。
    配合 new_span() 上下文管理器使用。

    Attributes:
        name: span 名称，描述操作内容
        span_id: 当前 span 的唯一标识
        parent_span_id: 父 span 的 id，顶级 span 则为 None
        trace_id: 所属链路的 trace_id
        start_time: 开始时间戳（秒）
        end_time: 结束时间戳（秒），未结束则为 None
        attributes: span 属性字典，用于附加业务信息
        status: 状态，'ok' / 'error'
        error_message: 错误信息，status 为 'error' 时填充
    """

    name: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_span_id: str | None = None
    trace_id: str = field(default_factory=get_trace_id)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error_message: str = ""

    @property
    def duration_ms(self) -> float:
        """span 持续时间（毫秒）。

        若 span 未结束，返回从开始到当前的耗时。
        """
        end = self.end_time if self.end_time is not None else time.time()
        return (end - self.start_time) * 1000.0

    def set_attribute(self, key: str, value: Any) -> None:
        """设置 span 属性。

        Args:
            key: 属性名
            value: 属性值
        """
        self.attributes[key] = value

    def set_attributes(self, attrs: dict[str, Any]) -> None:
        """批量设置 span 属性。

        Args:
            attrs: 属性字典
        """
        self.attributes.update(attrs)

    def record_error(self, message: str) -> None:
        """标记 span 为错误状态并记录错误信息。

        Args:
            message: 错误描述信息
        """
        self.status = "error"
        self.error_message = message

    def finish(self, status: str = "ok") -> None:
        """结束 span，记录结束时间。

        Args:
            status: 结束状态，'ok' 或 'error'
        """
        self.end_time = time.time()
        if self.status == "ok":
            self.status = status


@contextmanager
def new_span(name: str, **attributes: Any) -> Generator[SpanContext, None, None]:
    """创建新 span 的上下文管理器。

    进入上下文时创建 SpanContext 并设置为当前 span_id，
    退出时自动结束 span 并恢复父 span_id。

    典型用法：
        with new_span("db_query", table="users", operation="select") as span:
            result = db.execute(...)
            span.set_attribute("rows", len(result))

    Args:
        name: span 名称
        **attributes: 初始属性键值对

    Yields:
        SpanContext 对象，可在上下文中设置属性、记录错误
    """
    # 保存父 span_id
    parent_span_id = _span_id_var.get() or None

    # 创建新 span
    span = SpanContext(
        name=name,
        parent_span_id=parent_span_id,
        trace_id=get_trace_id(),
    )
    if attributes:
        span.set_attributes(attributes)

    # 设置当前 span_id
    span_token = _span_id_var.set(span.span_id)

    try:
        yield span
    except Exception as exc:
        span.record_error(str(exc))
        span.finish(status="error")
        raise
    else:
        span.finish(status="ok")
    finally:
        # 恢复父 span_id
        _span_id_var.reset(span_token)


# ── 带 trace_id 执行工具 ────────────────────────────────────

def with_trace_id(trace_id: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """在指定 trace_id 上下文中执行函数。

    执行前设置 trace_id，执行后恢复原 trace_id。
    适用于需要在不同 trace 上下文中调用函数的场景。

    Args:
        trace_id: 要使用的 trace_id
        func: 要执行的函数
        *args: 传递给 func 的位置参数
        **kwargs: 传递给 func 的关键字参数

    Returns:
        func 的返回值
    """
    token = set_trace_id(trace_id)
    try:
        return func(*args, **kwargs)
    finally:
        reset_trace_id(token)


async def with_trace_id_async(
    trace_id: str, func: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    """在指定 trace_id 上下文中执行异步函数。

    异步版本的 with_trace_id，适用于 async 函数。

    Args:
        trace_id: 要使用的 trace_id
        func: 要执行的异步函数
        *args: 传递给 func 的位置参数
        **kwargs: 传递给 func 的关键字参数

    Returns:
        func 的返回值
    """
    token = set_trace_id(trace_id)
    try:
        return await func(*args, **kwargs)
    finally:
        reset_trace_id(token)


# ── 上下文快照与恢复 ────────────────────────────────────────

@dataclass
class TraceSnapshot:
    """trace 上下文快照，用于跨线程/跨边界传递上下文。

    典型场景：将上下文从主线程传递到线程池、
    或从消息发布端传递到消费端。
    """

    trace_id: str = ""
    span_id: str = ""
    request_start: float = 0.0


def snapshot() -> TraceSnapshot:
    """获取当前 trace 上下文的快照。

    Returns:
        TraceSnapshot 对象，包含当前 trace_id、span_id、request_start
    """
    return TraceSnapshot(
        trace_id=_trace_id_var.get(),
        span_id=_span_id_var.get(),
        request_start=_request_start_var.get(),
    )


def restore(snapshot_obj: TraceSnapshot) -> tuple[contextvars.Token, contextvars.Token, contextvars.Token]:
    """从快照恢复 trace 上下文。

    Args:
        snapshot_obj: TraceSnapshot 对象

    Returns:
        (trace_token, span_token, start_token) 三个 Token 的元组，
        用于后续恢复原值
    """
    trace_token = _trace_id_var.set(snapshot_obj.trace_id)
    span_token = _span_id_var.set(snapshot_obj.span_id)
    start_token = _request_start_var.set(snapshot_obj.request_start)
    return trace_token, span_token, start_token


def restore_safe(snapshot_obj: TraceSnapshot) -> Callable[[], None]:
    """从快照恢复上下文，返回一个清理函数。

    与 restore() 不同，此函数返回一个可调用的清理函数，
    调用后恢复到快照前的状态。更适合 with 块外使用。

    Args:
        snapshot_obj: TraceSnapshot 对象

    Returns:
        清理函数，调用后恢复原始上下文
    """
    tokens = restore(snapshot_obj)

    def _cleanup() -> None:
        trace_token, span_token, start_token = tokens
        _trace_id_var.reset(trace_token)
        _span_id_var.reset(span_token)
        _request_start_var.reset(start_token)

    return _cleanup
