"""
云汐全链路追踪系统

支持：
- Trace ID 生成与传播（UUID 格式，32 位十六进制）
- Span 管理（开始/结束/嵌套/父子关系）
- 请求级上下文存储（基于 ContextVar，协程安全）
- 跨模块追踪头传播（X-Trace-Id, X-Span-Id）
- 与统一日志系统深度集成（trace_id 自动注入日志上下文）
- 追踪数据采集与查询

使用方式：
    from shared.core.observability import start_trace, end_trace, start_span, get_trace_id

    # 自动从请求头提取或生成 trace_id
    trace_id = extract_trace_headers(request.headers)
    ctx = start_trace(trace_id=trace_id)

    # 子调用追踪
    with start_span("db_query") as span:
        result = do_db_query()
        span.set_attribute("rows", len(result))

    # 跨模块调用
    headers = get_trace_headers()
    response = httpx.get(url, headers=headers)
"""
import uuid
import time
import threading
from typing import Optional, Dict, Any, List
from contextvars import ContextVar

# 导入统一日志的上下文函数，实现自动注入
try:
    from .unified_logger import set_log_context, clear_log_context, get_log_context
    _LOG_INTEGRATION = True
except ImportError:
    _LOG_INTEGRATION = False

    # 如果 unified_logger 不可用，提供空实现
    def set_log_context(**kwargs):
        pass

    def clear_log_context():
        pass

    def get_log_context():
        return {}


def _remove_log_context_keys(*keys: str) -> None:
    """从日志上下文中移除指定的 key"""
    if not _LOG_INTEGRATION:
        return
    ctx = get_log_context()
    for key in keys:
        ctx.pop(key, None)
    # 重新设置（因为 get_log_context 返回的是副本）
    if _LOG_INTEGRATION:
        try:
            from .unified_logger import _log_context_var
            _log_context_var.set(ctx)
        except ImportError:
            pass


# ============================================================================
# Span 类
# ============================================================================

class Span:
    """追踪跨度（Span）

    表示一次操作的时间跨度，包含：
    - trace_id: 全链路追踪 ID
    - span_id: 当前 Span ID
    - parent_span_id: 父 Span ID（顶层 Span 为 None）
    - name: Span 名称
    - attributes: 附加属性
    - status: 状态 (running/ok/error)
    """

    def __init__(
        self,
        name: str,
        trace_id: str,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.trace_id = trace_id
        self.span_id = span_id or self._generate_id()
        self.parent_span_id = parent_span_id
        self.attributes: Dict[str, Any] = attributes or {}
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status: str = "running"  # running, ok, error
        self.error_message: Optional[str] = None
        self._logs: List[Dict[str, Any]] = []

    @staticmethod
    def _generate_id() -> str:
        """生成 16 位十六进制 Span ID"""
        return uuid.uuid4().hex[:16]

    def set_attribute(self, key: str, value: Any):
        """设置属性"""
        self.attributes[key] = value

    def set_attributes(self, attributes: Dict[str, Any]):
        """批量设置属性"""
        self.attributes.update(attributes)

    def add_event(self, name: str, **attributes):
        """添加事件日志"""
        self._logs.append({
            "timestamp": time.time(),
            "name": name,
            "attributes": attributes,
        })

    def end(self, status: str = "ok", error_message: Optional[str] = None):
        """结束 Span

        Args:
            status: 状态 (ok/error)
            error_message: 错误信息（status=error 时）
        """
        self.end_time = time.time()
        self.status = status
        self.error_message = error_message

    @property
    def duration_ms(self) -> float:
        """持续时间（毫秒）"""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    @property
    def is_finished(self) -> bool:
        """是否已结束"""
        return self.end_time is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "error_message": self.error_message,
            "attributes": self.attributes,
            "events": self._logs,
        }

    # 支持 with 语句
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.end(status="error", error_message=str(exc_val))
        else:
            self.end(status="ok")
        return False  # 不吞异常


# ============================================================================
# TraceContext 类
# ============================================================================

class TraceContext:
    """追踪上下文

    管理一条完整的追踪链路，包含多个 Span。
    """

    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or self._generate_trace_id()
        self.spans: List[Span] = []
        self._span_stack: List[Span] = []
        self._lock = threading.Lock()
        self._start_time = time.time()

    @staticmethod
    def _generate_trace_id() -> str:
        """生成 32 位十六进制 Trace ID"""
        return uuid.uuid4().hex

    def start_span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Span:
        """
        开始一个新的 Span

        Args:
            name: Span 名称
            attributes: 附加属性

        Returns:
            Span 对象
        """
        parent_span = self._span_stack[-1] if self._span_stack else None

        span = Span(
            name=name,
            trace_id=self.trace_id,
            parent_span_id=parent_span.span_id if parent_span else None,
            attributes=attributes,
        )

        with self._lock:
            self.spans.append(span)
            self._span_stack.append(span)

        # 将 span_id 注入日志上下文
        if _LOG_INTEGRATION:
            set_log_context(span_id=span.span_id)

        return span

    def end_span(self, span: Span, status: str = "ok", error_message: Optional[str] = None):
        """
        结束 Span

        Args:
            span: 要结束的 Span
            status: 状态 (ok/error)
            error_message: 错误信息
        """
        span.end(status=status, error_message=error_message)

        with self._lock:
            if self._span_stack and self._span_stack[-1] == span:
                self._span_stack.pop()
                # 恢复父 span 的 span_id 到日志上下文
                if self._span_stack:
                    if _LOG_INTEGRATION:
                        set_log_context(span_id=self._span_stack[-1].span_id)
                else:
                    # 没有父 span，清除 span_id
                    if _LOG_INTEGRATION:
                        _remove_log_context_keys("span_id")

    def current_span(self) -> Optional[Span]:
        """获取当前活动的 Span（栈顶）"""
        return self._span_stack[-1] if self._span_stack else None

    def current_span_id(self) -> Optional[str]:
        """获取当前活动 Span 的 ID"""
        span = self.current_span()
        return span.span_id if span else None

    def get_trace_summary(self) -> Dict[str, Any]:
        """获取追踪摘要"""
        completed_spans = [s for s in self.spans if s.end_time is not None]
        total_duration = sum(s.duration_ms for s in completed_spans)
        error_count = sum(1 for s in self.spans if s.status == "error")

        return {
            "trace_id": self.trace_id,
            "span_count": len(self.spans),
            "completed_count": len(completed_spans),
            "error_count": error_count,
            "total_duration_ms": round(total_duration, 2),
            "root_span": self.spans[0].to_dict() if self.spans else None,
            "spans": [s.to_dict() for s in self.spans],
        }

    @property
    def duration_ms(self) -> float:
        """链路总耗时（毫秒）"""
        return (time.time() - self._start_time) * 1000


# ============================================================================
# 全局上下文变量（基于 ContextVar，支持异步/协程）
# ============================================================================

_trace_context_var: ContextVar[Optional[TraceContext]] = ContextVar(
    "trace_context",
    default=None,
)


# ============================================================================
# 公共 API 函数
# ============================================================================

def get_current_trace() -> Optional[TraceContext]:
    """获取当前追踪上下文"""
    return _trace_context_var.get()


def get_trace_id() -> Optional[str]:
    """获取当前 Trace ID

    Returns:
        Trace ID 字符串，如果没有活动追踪则返回 None
    """
    ctx = _trace_context_var.get()
    return ctx.trace_id if ctx else None


def get_span_id() -> Optional[str]:
    """获取当前 Span ID

    Returns:
        Span ID 字符串，如果没有活动 Span 则返回 None
    """
    ctx = _trace_context_var.get()
    if ctx is None:
        return None
    span = ctx.current_span()
    return span.span_id if span else None


def start_trace(trace_id: Optional[str] = None, **context_kwargs) -> TraceContext:
    """
    开始一个新的追踪

    Args:
        trace_id: 可选的 Trace ID（用于从上游传播）
        **context_kwargs: 附加到日志上下文的字段（如 user_id, module_key）

    Returns:
        TraceContext 对象
    """
    ctx = TraceContext(trace_id=trace_id)
    _trace_context_var.set(ctx)

    # 注入 trace_id 到日志上下文
    if _LOG_INTEGRATION:
        log_ctx = {"trace_id": ctx.trace_id}
        if context_kwargs:
            log_ctx.update(context_kwargs)
        set_log_context(**log_ctx)

    return ctx


def end_trace() -> Optional[Dict[str, Any]]:
    """
    结束当前追踪

    Returns:
        追踪摘要字典，如果没有活动追踪则返回 None
    """
    ctx = _trace_context_var.get()
    if ctx is None:
        return None

    summary = ctx.get_trace_summary()
    _trace_context_var.set(None)

    # 清除日志上下文
    if _LOG_INTEGRATION:
        clear_log_context()

    return summary


def start_span(name: str, **attributes) -> Span:
    """
    在当前追踪中开始一个 Span（便捷方法）

    如果没有活动追踪，会自动创建一个。

    Args:
        name: Span 名称
        **attributes: 附加属性

    Returns:
        Span 对象（支持 with 语句）
    """
    ctx = _trace_context_var.get()
    if ctx is None:
        ctx = start_trace()

    return ctx.start_span(name, attributes=attributes)


def end_span(span: Span, status: str = "ok", error_message: Optional[str] = None):
    """结束 Span（便捷方法）

    Args:
        span: 要结束的 Span
        status: 状态 (ok/error)
        error_message: 错误信息
    """
    ctx = _trace_context_var.get()
    if ctx:
        ctx.end_span(span, status=status, error_message=error_message)


def get_trace_headers() -> Dict[str, str]:
    """
    获取追踪传播头（用于跨模块调用）

    在发起 HTTP 调用时，将返回的 headers 合并到请求头中，
    即可实现 trace_id 跨服务传递。

    Returns:
        追踪 HTTP 头字典
    """
    ctx = _trace_context_var.get()
    if ctx is None:
        return {}

    headers = {"X-Trace-Id": ctx.trace_id}

    current = ctx.current_span()
    if current:
        headers["X-Span-Id"] = current.span_id

    return headers


def extract_trace_headers(headers: Dict[str, str]) -> Optional[str]:
    """
    从请求头中提取 Trace ID

    Args:
        headers: 请求头字典

    Returns:
        Trace ID 或 None
    """
    # 不区分大小写查找
    trace_headers = ("x-trace-id", "trace-id", "X-Trace-Id", "Trace-Id")
    for key in headers:
        if key.lower() in ("x-trace-id", "trace-id"):
            return headers[key]
    return None


def extract_span_headers(headers: Dict[str, str]) -> Optional[str]:
    """
    从请求头中提取 Span ID（父 Span ID）

    Args:
        headers: 请求头字典

    Returns:
        Span ID 或 None
    """
    for key in headers:
        if key.lower() in ("x-span-id", "span-id", "x-parent-span-id"):
            return headers[key]
    return None


def set_trace_attribute(key: str, value: Any):
    """
    为当前 Span 设置属性（便捷方法）

    Args:
        key: 属性名
        value: 属性值
    """
    ctx = _trace_context_var.get()
    if ctx:
        span = ctx.current_span()
        if span:
            span.set_attribute(key, value)
