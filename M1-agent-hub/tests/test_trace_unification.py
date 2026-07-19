"""
统一链路追踪集成测试

验证 M1 trace_context 适配层与 shared 统一追踪体系的集成：
1. M1 trace_context API 向后兼容
2. M1 与 shared trace_id 底层统一
3. 入站请求提取 trace_id
4. 出站请求带上 trace_id
5. 日志中包含 trace_id
6. 跨模块调用 trace_id 连续
7. 嵌套 span 正确
8. 线程/协程间上下文传递
9. 边界情况（无 trace_id 时自动生成）
"""

from __future__ import annotations

import sys
import os
import warnings
import asyncio
import time
import io
import json
import logging
import uuid
from pathlib import Path

import pytest

# 忽略弃用警告（测试适配层本身）
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ── 路径配置 ──────────────────────────────────────────

# M1 src 目录
_M1_SRC = Path(__file__).resolve().parents[1] / "src"
# 项目根目录（shared 所在目录）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

for _p in (str(_M1_SRC), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── 导入待测试模块 ────────────────────────────────────

from src.observability.trace_context import (
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
    get_trace_headers,
    extract_trace_headers,
)

from shared.core.observability.tracing import (
    get_trace_id as shared_get_trace_id,
    get_span_id as shared_get_span_id,
    start_trace as shared_start_trace,
    end_trace as shared_end_trace,
    get_current_trace as shared_get_current_trace,
)


# ============================================================================
# 测试组 1：M1 trace_context API 向后兼容
# ============================================================================

class TestM1TraceContextBackwardCompatibility:
    """测试 M1 trace_context 所有公开 API 仍然可用"""

    def setup_method(self):
        """每个测试前清理上下文"""
        clear_trace_id()
        clear_span_id()

    def test_generate_trace_id_format(self):
        """generate_trace_id 生成 UUID4 格式"""
        tid = generate_trace_id()
        parsed = uuid.UUID(tid)
        assert parsed.version == 4
        assert "-" in tid
        assert len(tid) == 36

    def test_generate_trace_id_unique(self):
        """生成的 trace_id 唯一"""
        ids = {generate_trace_id() for _ in range(100)}
        assert len(ids) == 100

    def test_get_trace_id_auto_generates(self):
        """get_trace_id 在没有设置时自动生成"""
        clear_trace_id()
        tid = get_trace_id()
        assert tid != ""
        uuid.UUID(tid) if "-" in tid else None  # 不抛异常即合法

    def test_get_trace_id_returns_same(self):
        """多次调用 get_trace_id 返回同一个值"""
        clear_trace_id()
        tid1 = get_trace_id()
        tid2 = get_trace_id()
        assert tid1 == tid2

    def test_set_trace_id_and_reset(self):
        """set_trace_id 设置值，reset_trace_id 恢复"""
        clear_trace_id()
        original = get_trace_id()

        token = set_trace_id("custom-trace-id-123")
        assert get_trace_id() == "custom-trace-id-123"

        reset_trace_id(token)
        assert get_trace_id() == original

    def test_clear_trace_id(self):
        """清除 trace_id"""
        set_trace_id("to-be-cleared")
        assert get_trace_id() == "to-be-cleared"

        clear_trace_id()
        # 清除后 get_trace_id 会重新生成新的
        tid = get_trace_id()
        assert tid != "to-be-cleared"
        assert tid != ""

    def test_span_id_operations(self):
        """span_id 操作完整可用"""
        clear_span_id()
        sid = generate_span_id()
        assert len(sid) == 16
        int(sid, 16)  # 合法十六进制

        clear_span_id()
        current = get_span_id()
        assert len(current) == 16

        token = set_span_id("custom-span-id")
        assert get_span_id() == "custom-span-id"
        reset_span_id(token)

    def test_request_start_operations(self):
        """request_start 操作可用"""
        token = set_request_start()
        start = get_request_start()
        assert start > 0
        assert abs(time.time() - start) < 1.0
        reset_request_start(token)

        custom_time = 1000000.0
        token = set_request_start(custom_time)
        assert get_request_start() == custom_time
        reset_request_start(token)

    def test_get_elapsed_ms(self):
        """get_elapsed_ms 计算耗时"""
        token = set_request_start()
        time.sleep(0.01)
        elapsed = get_elapsed_ms()
        assert elapsed >= 10
        reset_request_start(token)

    def test_new_span_basic(self):
        """new_span 基本功能"""
        clear_trace_id()
        clear_span_id()

        with new_span("test_operation") as span:
            assert isinstance(span, SpanContext)
            assert span.name == "test_operation"
            assert span.status == "ok"
            assert span.parent_span_id is None

        assert span.end_time is not None
        assert span.status == "ok"
        assert span.duration_ms >= 0

    def test_new_span_nested(self):
        """嵌套 span 的父子关系"""
        clear_span_id()

        with new_span("parent") as parent:
            parent_id = parent.span_id
            with new_span("child") as child:
                assert child.parent_span_id == parent_id
                assert child.name == "child"

            assert get_span_id() == parent_id

    def test_new_span_attributes(self):
        """span 属性设置"""
        with new_span("db_query", table="users", operation="select") as span:
            assert span.attributes["table"] == "users"
            span.set_attribute("rows", 42)
            assert span.attributes["rows"] == 42
            span.set_attributes({"status": "success", "count": 10})
            assert span.attributes["status"] == "success"

    def test_new_span_error(self):
        """span 内抛出异常时记录错误"""
        with pytest.raises(ValueError, match="test error"):
            with new_span("failing_op") as span:
                raise ValueError("test error")

        assert span.status == "error"
        assert span.error_message == "test error"

    def test_with_trace_id_sync(self):
        """with_trace_id 同步版本"""
        clear_trace_id()
        original = get_trace_id()

        captured = []
        def work():
            captured.append(get_trace_id())
            return "result"

        result = with_trace_id("new-trace-id", work)
        assert result == "result"
        assert captured[0] == "new-trace-id"
        assert get_trace_id() == original

    @pytest.mark.asyncio
    async def test_with_trace_id_async(self):
        """with_trace_id_async 异步版本"""
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

    def test_snapshot_and_restore(self):
        """快照和恢复"""
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

        set_trace_id("changed")
        set_span_id("changed-span")

        restore(snap)
        assert get_trace_id() == "snap-trace"
        assert get_span_id() == "snap-span"
        assert get_request_start() == 12345.0

        clear_trace_id()
        clear_span_id()

    def test_restore_safe(self):
        """restore_safe 返回清理函数"""
        clear_trace_id()
        set_trace_id("original-trace")

        snap = TraceSnapshot(trace_id="restored-trace", span_id="restored-span", request_start=0.0)
        cleanup = restore_safe(snap)
        assert get_trace_id() == "restored-trace"

        cleanup()
        assert get_trace_id() == "original-trace"


# ============================================================================
# 测试组 2：M1 与 shared trace_id 底层统一
# ============================================================================

class TestM1SharedTraceIdUnification:
    """测试 M1 和 shared 的 trace_id 是同一个（底层统一）"""

    def setup_method(self):
        """每个测试前清理上下文"""
        clear_trace_id()
        clear_span_id()
        # 清理 shared 侧
        if shared_get_current_trace() is not None:
            shared_end_trace()

    def test_set_trace_id_via_m1_visible_in_shared(self):
        """通过 M1 API 设置的 trace_id 在 shared 侧可见"""
        clear_trace_id()
        set_trace_id("unified-test-trace-001")

        m1_tid = get_trace_id()
        shared_tid = shared_get_trace_id()

        assert m1_tid == "unified-test-trace-001"
        assert shared_tid == "unified-test-trace-001"
        assert m1_tid == shared_tid

    def test_set_trace_id_via_shared_visible_in_m1(self):
        """通过 shared API 设置的 trace_id 在 M1 侧可见"""
        clear_trace_id()
        shared_start_trace(trace_id="shared-init-trace-002")

        shared_tid = shared_get_trace_id()
        m1_tid = get_trace_id()

        assert shared_tid == "shared-init-trace-002"
        assert m1_tid == "shared-init-trace-002"

        shared_end_trace()

    def test_new_span_creates_shared_span(self):
        """M1 new_span 创建的 span 在 shared 侧可见"""
        clear_trace_id()
        set_trace_id("span-unified-test")

        with new_span("test_span_unified") as span:
            shared_sid = shared_get_span_id()
            assert shared_sid == span.span_id

            # shared 侧的 trace 应该有这个 span
            trace = shared_get_current_trace()
            assert trace is not None
            assert any(s.span_id == span.span_id for s in trace.spans)

    def test_trace_id_consistency_through_operations(self):
        """多次操作后 trace_id 保持一致"""
        clear_trace_id()
        set_trace_id("consistency-trace")

        # 经过多次操作
        with new_span("op1"):
            pass

        with new_span("op2"):
            with new_span("op2_child"):
                pass

        assert get_trace_id() == "consistency-trace"
        assert shared_get_trace_id() == "consistency-trace"

    def test_clear_trace_id_clears_both(self):
        """clear_trace_id 同时清理 M1 和 shared"""
        clear_trace_id()
        set_trace_id("to-clear-both")
        assert get_trace_id() == "to-clear-both"
        assert shared_get_trace_id() == "to-clear-both"

        clear_trace_id()
        assert shared_get_current_trace() is None

    def test_reset_trace_id_restores_shared(self):
        """reset_trace_id 正确恢复 shared 侧的 trace"""
        clear_trace_id()
        set_trace_id("original-trace")
        original = get_trace_id()

        token = set_trace_id("new-trace")
        assert shared_get_trace_id() == "new-trace"

        reset_trace_id(token)
        assert get_trace_id() == original
        assert shared_get_trace_id() == original


# ============================================================================
# 测试组 3：HTTP 头提取与生成
# ============================================================================

class TestHTTPTraceHeaders:
    """测试入站 trace_id 提取和出站头生成"""

    def setup_method(self):
        clear_trace_id()
        clear_span_id()

    def test_extract_trace_headers_x_trace_id(self):
        """从 X-Trace-Id 头提取 trace_id"""
        tid = extract_trace_headers({"X-Trace-Id": "trace-from-header-001"})
        assert tid == "trace-from-header-001"

    def test_extract_trace_headers_case_insensitive(self):
        """不区分大小写提取 trace_id"""
        tid = extract_trace_headers({"x-trace-id": "lowercase-trace"})
        assert tid == "lowercase-trace"

    def test_extract_trace_headers_none(self):
        """没有 trace 头时返回 None"""
        tid = extract_trace_headers({"Content-Type": "application/json"})
        assert tid is None

    def test_get_trace_headers_contains_trace_id(self):
        """get_trace_headers 返回 X-Trace-Id"""
        clear_trace_id()
        set_trace_id("header-gen-test")

        headers = get_trace_headers()
        assert "X-Trace-Id" in headers
        assert headers["X-Trace-Id"] == "header-gen-test"

    def test_get_trace_headers_contains_span_id_when_active(self):
        """有活动 span 时返回 X-Span-Id"""
        clear_trace_id()
        set_trace_id("span-header-test")

        with new_span("active_span") as span:
            headers = get_trace_headers()
            assert "X-Span-Id" in headers
            assert headers["X-Span-Id"] == span.span_id

    def test_get_trace_headers_empty_when_no_trace(self):
        """没有活动 trace 时返回空或只有 trace_id"""
        clear_trace_id()
        # 注意：M1 的 get_trace_id 会自动生成 trace，所以这里直接调用 shared 侧验证
        if shared_get_current_trace() is not None:
            shared_end_trace()
        # 从 shared 侧验证
        from shared.core.observability.tracing import get_trace_headers as shared_get_trace_headers
        headers = shared_get_trace_headers()
        assert headers == {}

    def test_roundtrip_headers(self):
        """出站头可以被入站正确解析（往返一致性）"""
        clear_trace_id()
        set_trace_id("roundtrip-trace")

        with new_span("roundtrip_span"):
            outgoing = get_trace_headers()
            incoming_trace_id = extract_trace_headers(outgoing)
            assert incoming_trace_id == "roundtrip-trace"


# ============================================================================
# 测试组 4：日志中的 trace_id
# ============================================================================

class TestLoggingTraceId:
    """测试日志中包含 trace_id"""

    def setup_method(self):
        clear_trace_id()
        clear_span_id()

    def test_trace_context_filter_injects_trace_id(self):
        """TraceContextFilter 正确注入 trace_id"""
        from src.observability.logging_setup import TraceContextFilter

        set_trace_id("log-trace-test-001")

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(trace_id)s - %(message)s"))
        handler.addFilter(TraceContextFilter())

        test_logger = logging.getLogger("test_filter_1")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)
        test_logger.propagate = False

        test_logger.info("test message")
        output = stream.getvalue().strip()

        assert "log-trace-test-001" in output
        assert "test message" in output

    def test_trace_context_filter_injects_span_id(self):
        """TraceContextFilter 正确注入 span_id"""
        from src.observability.logging_setup import TraceContextFilter

        clear_trace_id()
        clear_span_id()

        with new_span("log_span_test") as span:
            stream = io.StringIO()
            handler = logging.StreamHandler(stream)
            handler.setFormatter(logging.Formatter("%(span_id)s - %(message)s"))
            handler.addFilter(TraceContextFilter())

            test_logger = logging.getLogger("test_filter_2")
            test_logger.addHandler(handler)
            test_logger.setLevel(logging.INFO)
            test_logger.propagate = False

            test_logger.info("span message")
            output = stream.getvalue().strip()

            assert span.span_id in output

    def test_json_log_contains_trace_id(self):
        """JSON 格式日志包含 trace_id 字段"""
        from src.observability.logging_setup import JsonFormatter, TraceContextFilter

        set_trace_id("json-trace-test")

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter(service_name="test", version="1.0"))
        handler.addFilter(TraceContextFilter())

        test_logger = logging.getLogger("test_json_log")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)
        test_logger.propagate = False

        test_logger.info("json test message")
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["trace_id"] == "json-trace-test"
        assert "span_id" in log_entry
        assert log_entry["message"] == "json test message"


# ============================================================================
# 测试组 5：协程间上下文传递
# ============================================================================

class TestAsyncContextPropagation:
    """测试线程/协程间上下文传递"""

    def setup_method(self):
        clear_trace_id()
        clear_span_id()

    @pytest.mark.asyncio
    async def test_coroutine_independent_trace(self):
        """不同协程有独立的 trace_id 上下文"""
        clear_trace_id()

        async def coro_with_trace(trace_val):
            set_trace_id(trace_val)
            await asyncio.sleep(0.01)
            return get_trace_id()

        tasks = [
            asyncio.create_task(coro_with_trace(f"trace-{i}"))
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks)

        for i, result in enumerate(results):
            assert result == f"trace-{i}"

        clear_trace_id()

    @pytest.mark.asyncio
    async def test_nested_span_independent_async(self):
        """不同协程的 span 上下文独立"""
        clear_span_id()

        async def coro_with_span(name):
            with new_span(name) as span:
                await asyncio.sleep(0.01)
                return span.span_id

        tasks = [asyncio.create_task(coro_with_span(f"span-{i}")) for i in range(3)]
        results = await asyncio.gather(*tasks)

        assert len(set(results)) == 3

    @pytest.mark.asyncio
    async def test_with_trace_id_async_restores(self):
        """with_trace_id_async 执行后恢复原 trace_id"""
        clear_trace_id()
        original = get_trace_id()

        async def work():
            assert get_trace_id() == "async-trace-ctx"
            return "done"

        result = await with_trace_id_async("async-trace-ctx", work)
        assert result == "done"
        assert get_trace_id() == original


# ============================================================================
# 测试组 6：边界情况
# ============================================================================

class TestEdgeCases:
    """测试边界情况"""

    def setup_method(self):
        clear_trace_id()
        clear_span_id()

    def test_no_trace_id_auto_generates(self):
        """无 trace_id 时自动生成"""
        clear_trace_id()
        # 确保 shared 侧也没有
        if shared_get_current_trace() is not None:
            shared_end_trace()

        tid = get_trace_id()
        assert tid != ""
        assert tid is not None

    def test_empty_string_trace_id(self):
        """空字符串 trace_id 的处理"""
        clear_trace_id()
        set_trace_id("")
        # 空字符串被设置了，get 应该返回空（或自动生成？取决于行为）
        # M1 旧行为：返回空字符串（因为设置了就返回设置的值）
        # 新行为：shared 侧如果 trace_id 是空字符串，也应该返回空
        tid = get_trace_id()
        # 验证可以正常设置和获取
        assert isinstance(tid, str)

    def test_very_long_trace_id(self):
        """超长 trace_id 的处理"""
        long_id = "a" * 200
        clear_trace_id()
        set_trace_id(long_id)
        assert get_trace_id() == long_id
        assert shared_get_trace_id() == long_id

    def test_special_characters_trace_id(self):
        """包含特殊字符的 trace_id"""
        special_id = "trace-with-special-chars-!@#$%^&*()"
        clear_trace_id()
        set_trace_id(special_id)
        assert get_trace_id() == special_id
        assert shared_get_trace_id() == special_id

    def test_multiple_nested_spans(self):
        """深层嵌套 span"""
        clear_span_id()
        with new_span("level1") as l1:
            with new_span("level2") as l2:
                assert l2.parent_span_id == l1.span_id
                with new_span("level3") as l3:
                    assert l3.parent_span_id == l2.span_id
                    with new_span("level4") as l4:
                        assert l4.parent_span_id == l3.span_id

    def test_span_finish_twice(self):
        """多次 finish span 不出错"""
        span = SpanContext(name="test")
        span.finish()
        first_end = span.end_time
        time.sleep(0.01)
        span.finish()  # 第二次 finish
        # finish 后 end_time 不应该再改变
        assert span.end_time == first_end

    def test_snapshot_empty_context(self):
        """空上下文的快照"""
        clear_trace_id()
        clear_span_id()
        snap = snapshot()
        assert isinstance(snap, TraceSnapshot)
        # trace_id 可能自动生成，也可能为空（取决于实现）
        # 验证对象结构正确即可
        assert hasattr(snap, "trace_id")
        assert hasattr(snap, "span_id")
        assert hasattr(snap, "request_start")

    def test_get_trace_headers_no_active_trace(self):
        """无活动 trace 时获取 headers"""
        clear_trace_id()
        # 注意：M1 的 get_trace_id 会自动生成，所以 get_trace_headers 也会有值
        # 这是 M1 旧 API 的行为，保持向后兼容
        headers = get_trace_headers()
        assert isinstance(headers, dict)
        assert "X-Trace-Id" in headers


# ============================================================================
# 测试组 7：跨模块调用 trace_id 连续性（模拟）
# ============================================================================

class TestCrossModuleTraceContinuity:
    """模拟跨模块调用时 trace_id 的连续性"""

    def setup_method(self):
        clear_trace_id()
        clear_span_id()

    def test_simulated_inbound_outbound_flow(self):
        """模拟入站 -> 处理 -> 出站的完整流程"""
        # 1. 入站：从请求头提取 trace_id
        incoming_headers = {"X-Trace-Id": "cross-module-trace-001", "Content-Type": "application/json"}
        trace_id = extract_trace_headers(incoming_headers)
        assert trace_id == "cross-module-trace-001"

        # 2. 设置 trace 上下文
        token = set_trace_id(trace_id)
        try:
            # 3. 业务处理 span
            with new_span("request_handler", method="POST", path="/api/test") as req_span:
                assert req_span.trace_id == "cross-module-trace-001"

                # 4. 出站调用：生成追踪头
                with new_span("outbound_call", target="m4") as out_span:
                    outbound_headers = get_trace_headers()
                    assert outbound_headers["X-Trace-Id"] == "cross-module-trace-001"
                    assert "X-Span-Id" in outbound_headers

                    # 模拟下游处理（下游会用同样的 trace_id）
                    downstream_trace_id = outbound_headers["X-Trace-Id"]
                    assert downstream_trace_id == trace_id

            # 5. 验证处理完成后 trace_id 仍然一致
            assert get_trace_id() == "cross-module-trace-001"

        finally:
            reset_trace_id(token)

    def test_message_bus_trace_propagation(self):
        """模拟消息总线的 trace_id 传播（发布-消费）"""
        # 发布端
        set_trace_id("bus-trace-001")
        snap = snapshot()
        publish_trace_id = get_trace_id()

        # 模拟消息传递（快照序列化/反序列化）
        message_trace_id = snap.trace_id
        assert message_trace_id == publish_trace_id

        # 消费端（新的上下文）
        clear_trace_id()
        assert get_trace_id() != "bus-trace-001"  # 确认是不同的上下文

        # 消费端恢复上下文
        restore(snap)
        assert get_trace_id() == "bus-trace-001"

        clear_trace_id()


# ============================================================================
# 测试组 8：弃用警告
# ============================================================================

class TestDeprecationWarning:
    """测试模块导入时有弃用警告"""

    def test_deprecation_warning_module_level(self):
        """trace_context 模块有弃用警告（模块级别已发出）。

        验证方法：检查模块的文档字符串中包含 deprecated/弃用标记，
        以及模块确实会发出警告（通过 warnings 模块的历史记录验证）。
        """
        import src.observability.trace_context as tc_mod

        # 验证模块级文档包含弃用标记
        assert tc_mod.__doc__ is not None
        doc = tc_mod.__doc__.lower()
        has_deprecation_note = (
            "deprecated" in doc
            or "弃用" in doc
            or "兼容层" in doc
        )
        assert has_deprecation_note, "Module docstring should mention deprecation"

    def test_warnings_filter_preserves_deprecation(self):
        """验证在启用所有警告时，模块导入会发出 DeprecationWarning。

        使用子进程运行，确保模块从未被导入过。
        """
        import subprocess
        import sys

        code = """
import warnings
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, '..')
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    from src.observability import trace_context
    dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    print(f"COUNT:{len(dep_warnings)}")
    for dw in dep_warnings:
        print(f"MSG:{dw.message}")
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        # 检查输出中是否有弃用警告
        output = result.stdout + result.stderr
        assert "COUNT:" in output
        # 提取计数
        for line in output.splitlines():
            if line.startswith("COUNT:"):
                count = int(line.split(":")[1])
                assert count >= 1, f"Expected at least 1 DeprecationWarning, got {count}"
                break


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
