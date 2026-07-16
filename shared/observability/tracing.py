"""
云汐全链路追踪系统

支持：
- Trace ID 生成与传播
- Span 管理（开始/结束/嵌套）
- 请求级上下文存储
- 跨模块追踪头传播
- 追踪数据采集与查询
"""
import uuid
import time
import threading
from typing import Optional, Dict, Any, List
from contextvars import ContextVar


class Span:
    """追踪跨度（Span）"""
    
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
        self.attributes = attributes or {}
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status: str = "running"  # running, ok, error
        self.error_message: Optional[str] = None
    
    def _generate_id(self) -> str:
        return uuid.uuid4().hex[:16]
    
    def set_attribute(self, key: str, value: Any):
        """设置属性"""
        self.attributes[key] = value
    
    def end(self, status: str = "ok", error_message: Optional[str] = None):
        """结束Span"""
        self.end_time = time.time()
        self.status = status
        self.error_message = error_message
    
    @property
    def duration_ms(self) -> float:
        """持续时间（毫秒）"""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000
    
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
        }


class TraceContext:
    """追踪上下文"""
    
    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or self._generate_trace_id()
        self.spans: List[Span] = []
        self._span_stack: List[Span] = []
        self._lock = threading.Lock()
    
    def _generate_trace_id(self) -> str:
        return uuid.uuid4().hex
    
    def start_span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Span:
        """
        开始一个新的Span
        
        Args:
            name: Span名称
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
        
        return span
    
    def end_span(self, span: Span, status: str = "ok", error_message: Optional[str] = None):
        """
        结束Span
        
        Args:
            span: 要结束的Span
            status: 状态 (ok/error)
            error_message: 错误信息
        """
        span.end(status=status, error_message=error_message)
        
        with self._lock:
            if self._span_stack and self._span_stack[-1] == span:
                self._span_stack.pop()
    
    def current_span(self) -> Optional[Span]:
        """获取当前活动的Span"""
        return self._span_stack[-1] if self._span_stack else None
    
    def get_trace_summary(self) -> Dict[str, Any]:
        """获取追踪摘要"""
        completed_spans = [s for s in self.spans if s.end_time is not None]
        total_duration = sum(s.duration_ms for s in completed_spans)
        
        return {
            "trace_id": self.trace_id,
            "span_count": len(self.spans),
            "completed_count": len(completed_spans),
            "total_duration_ms": round(total_duration, 2),
            "spans": [s.to_dict() for s in self.spans],
        }


# 全局上下文变量（支持异步）
_trace_context_var: ContextVar[Optional[TraceContext]] = ContextVar(
    "trace_context",
    default=None,
)


def get_current_trace() -> Optional[TraceContext]:
    """获取当前追踪上下文"""
    return _trace_context_var.get()


def get_trace_id() -> Optional[str]:
    """获取当前Trace ID"""
    ctx = _trace_context_var.get()
    return ctx.trace_id if ctx else None


def start_trace(trace_id: Optional[str] = None) -> TraceContext:
    """
    开始一个新的追踪
    
    Args:
        trace_id: 可选的Trace ID（用于从上游传播）
    
    Returns:
        TraceContext 对象
    """
    ctx = TraceContext(trace_id=trace_id)
    _trace_context_var.set(ctx)
    return ctx


def end_trace() -> Optional[Dict[str, Any]]:
    """
    结束当前追踪
    
    Returns:
        追踪摘要字典
    """
    ctx = _trace_context_var.get()
    if ctx is None:
        return None
    
    summary = ctx.get_trace_summary()
    _trace_context_var.set(None)
    return summary


def start_span(name: str, **attributes) -> Span:
    """
    在当前追踪中开始一个Span（便捷方法）
    
    如果没有活动追踪，会自动创建一个。
    """
    ctx = _trace_context_var.get()
    if ctx is None:
        ctx = start_trace()
    
    return ctx.start_span(name, attributes=attributes)


def end_span(span: Span, status: str = "ok", error_message: Optional[str] = None):
    """结束Span（便捷方法）"""
    ctx = _trace_context_var.get()
    if ctx:
        ctx.end_span(span, status=status, error_message=error_message)


def get_trace_headers() -> Dict[str, str]:
    """
    获取追踪传播头（用于跨模块调用）
    
    Returns:
        追踪HTTP头字典
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
    从请求头中提取Trace ID
    
    Args:
        headers: 请求头字典
    
    Returns:
        Trace ID 或 None
    """
    # 不区分大小写查找
    for key, value in headers.items():
        if key.lower() in ("x-trace-id", "trace-id"):
            return value
    return None
