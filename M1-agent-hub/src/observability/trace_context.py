"""
M1 Agent 集群 - 全链路追踪上下文（Trace Context）

.. deprecated:: 12.0.0
   本模块已适配为 shared.core.observability.tracing 的兼容层。
   所有 API 底层委托给 shared 统一追踪实现，确保 trace_id 体系打通。
   新代码请直接使用 ``shared.core.observability`` 模块。

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

import warnings
import contextvars
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Generator

# ── 委托 shared 统一追踪实现 ──────────────────────────────
# 尝试从 shared.core.observability 导入统一追踪 API
# 如果不可用（如独立运行 M1 测试），则使用本地降级实现
try:
    from shared.core.observability.tracing import (
        get_trace_id as _shared_get_trace_id,
        get_span_id as _shared_get_span_id,
        start_trace as _shared_start_trace,
        end_trace as _shared_end_trace,
        start_span as _shared_start_span,
        end_span as _shared_end_span,
        get_current_trace as _shared_get_current_trace,
        get_trace_headers as _shared_get_trace_headers,
        extract_trace_headers as _shared_extract_trace_headers,
        TraceContext as _SharedTraceContext,
        Span as _SharedSpan,
    )
    _SHARED_TRACING_AVAILABLE = True
except ImportError:
    _SHARED_TRACING_AVAILABLE = False

# 发出弃用警告（模块级别，导入时提示一次）
warnings.warn(
    "src.observability.trace_context 已弃用，"
    "请迁移到 shared.core.observability.tracing。"
    "当前模块为兼容层，底层委托给 shared 统一实现。",
    DeprecationWarning,
    stacklevel=2,
)


# ── 上下文变量定义（用于兼容层状态追踪） ──────────────────
# 注意：trace_id 的真实存储在 shared 的 ContextVar 中
# span_id 有独立的兼容层 ContextVar（因为 shared 的 span 是栈式管理，
# 而旧 API 支持 set_span_id 设置任意值）
# request_start 保留独立 ContextVar（shared 中无对应概念）

# 请求开始时间戳（秒级浮点数），用于计算请求耗时
_request_start_var: contextvars.ContextVar[float] = contextvars.ContextVar(
    "request_start", default=0.0
)

# span_id 兼容层变量：用于支持 set_span_id 设置任意值的旧 API 语义
# 当用户调用 set_span_id 时写入此变量，get_span_id 时优先返回
# new_span 也会同步更新此变量
_manual_span_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "manual_span_id", default=""
)


# ── 内部辅助函数 ──────────────────────────────────────────

def _ensure_trace() -> None:
    """确保当前有活动的 trace，没有则自动创建。

    M1 的旧 API 中 get_trace_id() 在没有 trace 时会自动生成，
    而 shared 版本返回 None。此函数用于桥接行为差异。
    """
    if _SHARED_TRACING_AVAILABLE:
        if _shared_get_current_trace() is None:
            _shared_start_trace()


# ── trace_id 操作 ──────────────────────────────────────────

def get_trace_id() -> str:
    """获取当前 trace_id，如不存在则生成新的并设置到上下文。

    Returns:
        当前 trace_id 字符串（UUID4 格式，短横线分隔或 32 位十六进制）
    """
    if _SHARED_TRACING_AVAILABLE:
        _ensure_trace()
        tid = _shared_get_trace_id()
        return tid if tid else ""
    # 降级实现
    tid = _trace_id_var_fallback.get()
    if not tid:
        tid = generate_trace_id()
        _trace_id_var_fallback.set(tid)
    return tid


def set_trace_id(trace_id: str) -> contextvars.Token:
    """设置当前 trace_id，返回 token 用于后续恢复。

    Args:
        trace_id: 要设置的 trace_id 字符串

    Returns:
        contextvars.Token 对象，可传入 reset_trace_id 恢复之前的值
    """
    if _SHARED_TRACING_AVAILABLE:
        # 保存旧值（用于 reset）
        old_trace = _shared_get_current_trace()
        old_trace_id = old_trace.trace_id if old_trace else ""

        # 结束当前 trace（如果有）
        if old_trace is not None:
            _shared_end_trace()

        # 开始新的 trace
        _shared_start_trace(trace_id=trace_id)

        # 创建一个自定义 Token 对象，封装旧值以便恢复
        return _CompatToken(old_trace_id=old_trace_id)

    # 降级实现
    return _trace_id_var_fallback.set(trace_id)


def reset_trace_id(token: contextvars.Token | _CompatToken) -> None:
    """根据 token 恢复 trace_id 到之前的值。

    Args:
        token: set_trace_id 返回的 Token 对象
    """
    if _SHARED_TRACING_AVAILABLE:
        # 结束当前 trace
        current = _shared_get_current_trace()
        if current is not None:
            _shared_end_trace()

        # 恢复旧 trace_id
        if isinstance(token, _CompatToken):
            if token.old_trace_id:
                _shared_start_trace(trace_id=token.old_trace_id)
        return

    # 降级实现
    _trace_id_var_fallback.reset(token)  # type: ignore[arg-type]


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
    if _SHARED_TRACING_AVAILABLE:
        current = _shared_get_current_trace()
        if current is not None:
            _shared_end_trace()
        return

    # 降级实现
    _trace_id_var_fallback.set("")


# ── span_id 操作 ──────────────────────────────────────────

def get_span_id() -> str:
    """获取当前 span_id，如不存在则生成新的并设置到上下文。

    Returns:
        当前 span_id 字符串（UUID4 前 16 位十六进制字符）
    """
    if _SHARED_TRACING_AVAILABLE:
        # 优先返回手动设置的 span_id（兼容旧 API）
        manual_sid = _manual_span_id_var.get()
        if manual_sid:
            return manual_sid
        # 否则从 shared 获取
        _ensure_trace()
        sid = _shared_get_span_id()
        if not sid:
            # 没有活动 span 时，自动生成一个（保持旧 API 行为）
            new_sid = generate_span_id()
            _manual_span_id_var.set(new_sid)
            return new_sid
        return sid
    # 降级实现
    sid = _span_id_var_fallback.get()
    if not sid:
        sid = generate_span_id()
        _span_id_var_fallback.set(sid)
    return sid


def set_span_id(span_id: str) -> contextvars.Token:
    """设置当前 span_id，返回 token 用于后续恢复。

    Args:
        span_id: 要设置的 span_id 字符串

    Returns:
        contextvars.Token 对象
    """
    if _SHARED_TRACING_AVAILABLE:
        # 使用兼容层变量存储手动设置的 span_id
        return _manual_span_id_var.set(span_id)
    # 降级实现
    return _span_id_var_fallback.set(span_id)


def reset_span_id(token: contextvars.Token) -> None:
    """根据 token 恢复 span_id 到之前的值。

    Args:
        token: set_span_id 返回的 Token 对象
    """
    if _SHARED_TRACING_AVAILABLE:
        _manual_span_id_var.reset(token)
        return
    # 降级实现
    _span_id_var_fallback.reset(token)


def generate_span_id() -> str:
    """生成新的 span_id（UUID4 前 16 位十六进制字符）。

    Returns:
        16 位十六进制字符串
    """
    return uuid.uuid4().hex[:16]


def clear_span_id() -> None:
    """清除当前 span_id（置空字符串）。"""
    if _SHARED_TRACING_AVAILABLE:
        _manual_span_id_var.set("")
        return

    # 降级实现
    _span_id_var_fallback.set("")


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

    注意：此为兼容层类，底层委托给 shared 的 Span。

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

    # 内部引用：关联的 shared Span 对象（如果有）
    _shared_span: Any = field(default=None, repr=False, compare=False)

    @property
    def duration_ms(self) -> float:
        """span 持续时间（毫秒）。

        若 span 未结束，返回从开始到当前的耗时。
        """
        if self._shared_span is not None:
            return self._shared_span.duration_ms
        end = self.end_time if self.end_time is not None else time.time()
        return (end - self.start_time) * 1000.0

    def set_attribute(self, key: str, value: Any) -> None:
        """设置 span 属性。

        Args:
            key: 属性名
            value: 属性值
        """
        self.attributes[key] = value
        if self._shared_span is not None:
            self._shared_span.set_attribute(key, value)

    def set_attributes(self, attrs: dict[str, Any]) -> None:
        """批量设置 span 属性。

        Args:
            attrs: 属性字典
        """
        self.attributes.update(attrs)
        if self._shared_span is not None:
            self._shared_span.set_attributes(attrs)

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
        # 已结束则不重复修改
        if self.end_time is not None:
            return

        self.end_time = time.time()
        if self.status == "ok":
            self.status = status

        # 同步到 shared span
        if self._shared_span is not None and _SHARED_TRACING_AVAILABLE:
            _shared_end_span(
                self._shared_span,
                status=status,
                error_message=self.error_message if status == "error" else None,
            )


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
    if _SHARED_TRACING_AVAILABLE:
        _ensure_trace()

        # 使用 shared 的 span
        shared_span = _shared_start_span(name, **attributes)
        parent_span_id = None
        current_trace = _shared_get_current_trace()
        if current_trace:
            # 找到父 span（栈中倒数第二个）
            if len(current_trace._span_stack) >= 2:
                parent_span_id = current_trace._span_stack[-2].span_id

        # 创建兼容层 SpanContext
        span = SpanContext(
            name=name,
            span_id=shared_span.span_id,
            parent_span_id=parent_span_id,
            trace_id=shared_span.trace_id,
            start_time=shared_span.start_time,
            attributes=dict(shared_span.attributes),
            _shared_span=shared_span,
        )

        # 同步更新兼容层 span_id 变量
        old_manual_span = _manual_span_id_var.get()
        span_token = _manual_span_id_var.set(span.span_id)

        try:
            yield span
        except Exception as exc:
            span.record_error(str(exc))
            span.finish(status="error")
            raise
        else:
            span.finish(status="ok")
        finally:
            # 恢复兼容层 span_id
            _manual_span_id_var.reset(span_token)
        return  # 防止继续执行到降级实现分支

    # ── 降级实现（无 shared 时） ──
    # 保存父 span_id
    parent_span_id = _span_id_var_fallback.get() or None

    # 创建新 span
    span = SpanContext(
        name=name,
        parent_span_id=parent_span_id,
        trace_id=get_trace_id(),
    )
    if attributes:
        span.set_attributes(attributes)

    # 设置当前 span_id
    span_token = _span_id_var_fallback.set(span.span_id)

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
        _span_id_var_fallback.reset(span_token)


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
    if _SHARED_TRACING_AVAILABLE:
        return TraceSnapshot(
            trace_id=_shared_get_trace_id() or "",
            span_id=get_span_id(),  # 使用兼容层的 get_span_id（优先手动值）
            request_start=_request_start_var.get(),
        )
    return TraceSnapshot(
        trace_id=_trace_id_var_fallback.get(),
        span_id=_span_id_var_fallback.get(),
        request_start=_request_start_var.get(),
    )


def restore(snapshot_obj: TraceSnapshot) -> tuple[Any, Any, Any]:
    """从快照恢复 trace 上下文。

    Args:
        snapshot_obj: TraceSnapshot 对象

    Returns:
        (trace_token, span_token, start_token) 三个 Token 的元组，
        用于后续恢复原值
    """
    trace_token = set_trace_id(snapshot_obj.trace_id) if snapshot_obj.trace_id else _CompatToken(old_trace_id="")
    span_token = set_span_id(snapshot_obj.span_id) if snapshot_obj.span_id else _manual_span_id_var.set("")
    start_token = set_request_start(snapshot_obj.request_start)
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
        reset_trace_id(trace_token)
        reset_span_id(span_token)
        reset_request_start(start_token)

    return _cleanup


# ── 兼容层 Token 封装 ──────────────────────────────────────

@dataclass
class _CompatToken:
    """兼容层 Token，用于封装旧 trace_id 以便 reset 时恢复。

    由于 shared 的 trace 管理是基于 TraceContext 对象的，
    而 M1 旧 API 使用 contextvars.Token，我们需要自定义
    Token 对象来保存旧状态。
    """
    old_trace_id: str = ""


@dataclass
class _CompatSpanToken:
    """兼容层 Span Token，用于封装旧 span_id 以便 reset 时恢复。"""
    old_span_id: str = ""


# ── 降级实现的 ContextVar（当 shared 不可用时使用） ──────
# 这些变量仅在 _SHARED_TRACING_AVAILABLE = False 时使用

if not _SHARED_TRACING_AVAILABLE:
    _trace_id_var_fallback: contextvars.ContextVar[str] = contextvars.ContextVar(
        "trace_id_fallback", default=""
    )
    _span_id_var_fallback: contextvars.ContextVar[str] = contextvars.ContextVar(
        "span_id_fallback", default=""
    )
else:
    # 仅用于类型提示，实际不使用
    _trace_id_var_fallback: contextvars.ContextVar[str] = contextvars.ContextVar(
        "trace_id_fallback_unused", default=""
    )
    _span_id_var_fallback: contextvars.ContextVar[str] = contextvars.ContextVar(
        "span_id_fallback_unused", default=""
    )


# ── 额外的 shared API 透传（方便渐进式迁移） ────────────

def get_trace_headers() -> dict[str, str]:
    """获取追踪传播头（用于跨模块 HTTP 调用）。

    在发起 HTTP 调用时，将返回的 headers 合并到请求头中，
    即可实现 trace_id 跨服务传递。

    Returns:
        追踪 HTTP 头字典，如 {"X-Trace-Id": "...", "X-Span-Id": "..."}
    """
    if _SHARED_TRACING_AVAILABLE:
        # 确保有 trace（M1 旧行为：自动生成）
        _ensure_trace()
        return _shared_get_trace_headers()
    return {"X-Trace-Id": get_trace_id(), "X-Span-Id": get_span_id()}


def extract_trace_headers(headers: dict[str, str]) -> str | None:
    """从请求头中提取 Trace ID。

    Args:
        headers: 请求头字典

    Returns:
        Trace ID 或 None
    """
    if _SHARED_TRACING_AVAILABLE:
        return _shared_extract_trace_headers(headers)
    # 降级实现
    for key in headers:
        if key.lower() in ("x-trace-id", "trace-id"):
            return headers[key]
    return None
