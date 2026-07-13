"""
测试：全链路追踪上下文（Trace Context）
"""

import pytest
import sys
import os
import asyncio
import uuid
import time

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trace_context import (
    get_trace_id,
    set_trace_id,
    reset_trace_id,
    generate_trace_id,
    clear_trace_id,
    get_span_id,
    set_span_id,
    reset_span_id,
    generate_span_id,
    clear_span_id,
    get_request_start,
    set_request_start,
    reset_request_start,
    get_elapsed_ms,
    new_span,
    SpanContext,
    with_trace_id,
    with_trace_id_async,
    snapshot,
    restore,
    restore_safe,
    TraceSnapshot,
)


# ── trace_id 操作测试 ──────────────────────────────────────


def test_generate_trace_id_format():
    """测试 generate_trace_id 生成 UUID4 格式"""
    tid = generate_trace_id()
    # 验证是合法 UUID4
    parsed = uuid.UUID(tid)
    assert parsed.version == 4
    # 包含短横线
    assert "-" in tid
    # 长度正确（标准 UUID 字符串长度 36）
    assert len(tid) == 36


def test_generate_trace_id_unique():
    """测试生成的 trace_id 唯一"""
    ids = {generate_trace_id() for _ in range(100)}
    assert len(ids) == 100


def test_get_trace_id_auto_generates():
    """测试 get_trace_id 在没有设置时自动生成"""
    clear_trace_id()
    tid = get_trace_id()
    assert tid != ""
    # 验证是合法 UUID
    uuid.UUID(tid)  # 不抛异常即合法


def test_get_trace_id_returns_same():
    """测试多次调用 get_trace_id 返回同一个值"""
    clear_trace_id()
    tid1 = get_trace_id()
    tid2 = get_trace_id()
    assert tid1 == tid2


def test_set_trace_id_and_reset():
    """测试 set_trace_id 设置值，reset_trace_id 恢复"""
    clear_trace_id()
    original = get_trace_id()

    token = set_trace_id("custom-trace-id-123")
    assert get_trace_id() == "custom-trace-id-123"

    reset_trace_id(token)
    assert get_trace_id() == original


def test_clear_trace_id():
    """测试清除 trace_id"""
    set_trace_id("to-be-cleared")
    assert get_trace_id() == "to-be-cleared"

    clear_trace_id()
    # 清除后 get_trace_id 会重新生成新的
    tid = get_trace_id()
    assert tid != "to-be-cleared"
    assert tid != ""


# ── span_id 操作测试 ──────────────────────────────────────


def test_generate_span_id_format():
    """测试 generate_span_id 生成 16 位十六进制字符串"""
    sid = generate_span_id()
    assert len(sid) == 16
    # 验证是十六进制字符
    int(sid, 16)  # 不抛异常即合法


def test_get_span_id_auto_generates():
    """测试 get_span_id 自动生成"""
    clear_span_id()
    sid = get_span_id()
    assert len(sid) == 16


def test_set_span_id_and_reset():
    """测试 set_span_id 和 reset_span_id"""
    clear_span_id()
    original = get_span_id()

    token = set_span_id("custom-span-id")
    assert get_span_id() == "custom-span-id"

    reset_span_id(token)
    assert get_span_id() == original


# ── request_start 操作测试 ──────────────────────────────────


def test_set_request_start_default():
    """测试 set_request_start 默认使用当前时间"""
    token = set_request_start()
    start = get_request_start()
    assert start > 0
    # 应该接近当前时间
    assert abs(time.time() - start) < 1.0
    reset_request_start(token)


def test_set_request_start_custom():
    """测试 set_request_start 自定义时间"""
    custom_time = 1000000.0
    token = set_request_start(custom_time)
    assert get_request_start() == custom_time
    reset_request_start(token)


def test_get_elapsed_ms():
    """测试 get_elapsed_ms 计算耗时"""
    token = set_request_start()
    time.sleep(0.01)
    elapsed = get_elapsed_ms()
    assert elapsed >= 10  # 至少 10ms
    reset_request_start(token)


def test_get_elapsed_ms_zero_when_not_set():
    """测试未设置 request_start 时 elapsed 为 0"""
    # 默认值为 0.0
    assert get_request_start() == 0.0
    assert get_elapsed_ms() == 0.0


# ── new_span 上下文管理器测试 ───────────────────────────


def test_new_span_basic():
    """测试 new_span 基本功能"""
    clear_trace_id()
    clear_span_id()

    with new_span("test_operation") as span:
        assert isinstance(span, SpanContext)
        assert span.name == "test_operation"
        assert span.status == "ok"
        assert span.end_time is None
        assert span.parent_span_id is None  # 顶级 span
        time.sleep(0.001)

    # 退出上下文后 span 已结束
    assert span.end_time is not None
    assert span.status == "ok"
    assert span.duration_ms >= 0


def test_new_span_nested_parent_child():
    """测试嵌套 span 的父子关系"""
    clear_span_id()

    with new_span("parent") as parent:
        parent_id = parent.span_id
        with new_span("child") as child:
            assert child.parent_span_id == parent_id
            assert child.name == "child"

        # 退出 child 后，当前 span_id 应恢复为 parent
        assert get_span_id() == parent_id


def test_new_span_attributes():
    """测试 span 属性设置"""
    with new_span("db_query", table="users", operation="select") as span:
        assert span.attributes["table"] == "users"
        assert span.attributes["operation"] == "select"

        span.set_attribute("rows", 42)
        assert span.attributes["rows"] == 42

        span.set_attributes({"status": "success", "count": 10})
        assert span.attributes["status"] == "success"
        assert span.attributes["count"] == 10


def test_new_span_error():
    """测试 span 内抛出异常时记录错误"""
    with pytest.raises(ValueError, match="test error"):
        with new_span("failing_op") as span:
            raise ValueError("test error")

    assert span.status == "error"
    assert span.error_message == "test error"
    assert span.end_time is not None


def test_new_span_trace_id():
    """测试 span 自动关联当前 trace_id"""
    clear_trace_id()
    set_trace_id("trace-for-span")

    with new_span("op_with_trace") as span:
        assert span.trace_id == "trace-for-span"

    clear_trace_id()


def test_new_span_span_id_changes():
    """测试进入 new_span 后当前 span_id 变化，退出后恢复"""
    clear_span_id()
    original_span = get_span_id()

    with new_span("inner") as span:
        assert get_span_id() == span.span_id
        assert get_span_id() != original_span

    # 退出后恢复
    assert get_span_id() == original_span


# ── SpanContext 测试 ────────────────────────────────────────


def test_span_context_duration_ms():
    """测试 SpanContext.duration_ms 属性"""
    span = SpanContext(name="test")
    time.sleep(0.01)
    dur = span.duration_ms
    assert dur >= 10  # 至少 10ms

    span.finish()
    dur_after = span.duration_ms
    assert dur_after > 0
    # finish 后 duration 不再变化
    time.sleep(0.01)
    assert span.duration_ms == dur_after


def test_span_context_record_error():
    """测试 SpanContext.record_error"""
    span = SpanContext(name="test")
    assert span.status == "ok"
    assert span.error_message == ""

    span.record_error("something failed")
    assert span.status == "error"
    assert span.error_message == "something failed"


def test_span_context_finish_status():
    """测试 SpanContext.finish 状态设置"""
    span = SpanContext(name="test")
    span.finish(status="ok")
    assert span.end_time is not None
    assert span.status == "ok"

    span2 = SpanContext(name="test2")
    span2.record_error("err")
    span2.finish(status="ok")  # 已经是 error，不改变
    assert span2.status == "error"


# ── with_trace_id 工具函数测试 ─────────────────────────────


def test_with_trace_id_sync():
    """测试 with_trace_id 同步版本"""
    clear_trace_id()
    original = get_trace_id()

    captured = []

    def work():
        captured.append(get_trace_id())
        return "result"

    result = with_trace_id("new-trace-id", work)

    assert result == "result"
    assert captured[0] == "new-trace-id"
    # 恢复原 trace_id
    assert get_trace_id() == original


def test_with_trace_id_restores_on_exception():
    """测试 with_trace_id 异常时也恢复 trace_id"""
    clear_trace_id()
    original = get_trace_id()

    def failing_work():
        raise ValueError("fail")

    with pytest.raises(ValueError):
        with_trace_id("error-trace", failing_work)

    assert get_trace_id() == original


@pytest.mark.asyncio
async def test_with_trace_id_async():
    """测试 with_trace_id_async 异步版本"""
    clear_trace_id()
    original = get_trace_id()

    captured = []

    async def async_work():
        captured.append(get_trace_id())
        await asyncio.sleep(0.01)
        return "async_result"

    result = await with_trace_id_async("async-trace-id", async_work)

    assert result == "async_result"
    assert captured[0] == "async-trace-id"
    assert get_trace_id() == original


# ── snapshot / restore 快照恢复测试 ────────────────────────


def test_snapshot_and_restore():
    """测试快照和恢复"""
    clear_trace_id()
    clear_span_id()

    set_trace_id("snap-trace")
    set_span_id("snap-span")
    set_request_start(12345.0)

    snap = snapshot()
    assert isinstance(snap, TraceSnapshot)
    assert snap.trace_id == "snap-trace"
    assert snap.span_id == "snap-span"
    assert snap.request_start == 12345.0

    # 修改上下文
    set_trace_id("changed")
    set_span_id("changed-span")

    # 恢复
    tokens = restore(snap)
    assert get_trace_id() == "snap-trace"
    assert get_span_id() == "snap-span"
    assert get_request_start() == 12345.0

    # 清理
    clear_trace_id()
    clear_span_id()


def test_restore_safe():
    """测试 restore_safe 返回清理函数"""
    clear_trace_id()
    set_trace_id("original-trace")

    snap = TraceSnapshot(trace_id="restored-trace", span_id="restored-span", request_start=0.0)

    cleanup = restore_safe(snap)
    assert get_trace_id() == "restored-trace"

    cleanup()
    assert get_trace_id() == "original-trace"


# ── 异步安全性测试 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_coroutine_independent_trace():
    """测试不同协程有独立的 trace_id 上下文"""
    clear_trace_id()

    async def coro_with_trace(trace_val):
        set_trace_id(trace_val)
        await asyncio.sleep(0.01)
        return get_trace_id()

    # 同时启动多个协程，每个设置不同的 trace_id
    tasks = [
        asyncio.create_task(coro_with_trace(f"trace-{i}"))
        for i in range(5)
    ]
    results = await asyncio.gather(*tasks)

    # 每个协程都应该返回自己设置的 trace_id
    for i, result in enumerate(results):
        assert result == f"trace-{i}"

    # 主协程不受影响
    clear_trace_id()


@pytest.mark.asyncio
async def test_async_nested_span_independent():
    """测试不同协程的 span 上下文独立"""
    clear_span_id()

    async def coro_with_span(name):
        with new_span(name) as span:
            await asyncio.sleep(0.01)
            return span.span_id

    tasks = [asyncio.create_task(coro_with_span(f"span-{i}")) for i in range(3)]
    results = await asyncio.gather(*tasks)

    # 每个协程的 span_id 都不同
    assert len(set(results)) == 3


# ── 集成：与异常模块联动测试 ────────────────────────────────


def test_trace_id_in_exception():
    """测试 trace_id 与异常模块联动（通过 to_response）"""
    from exceptions import ValidationError

    set_trace_id("trace-in-exc")
    exc = ValidationError(detail="test", trace_id=get_trace_id())
    resp = exc.to_response()
    assert resp["trace_id"] == "trace-in-exc"
    clear_trace_id()
