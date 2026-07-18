"""
SDK 模型测试 - ApiResponse, ServiceInstance, Event, 模式匹配
"""

import sys
import time
from pathlib import Path

import pytest

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from shared.module_sdk.models import (
    ApiResponse,
    ServiceInstance,
    ServiceStatus,
    Event,
    SdkErrorCode,
    LoadBalanceStrategy,
    CircuitState,
    _match_event_pattern,
)


# ============================================================
# ApiResponse 测试
# ============================================================

class TestApiResponse:
    """ApiResponse 测试"""

    def test_default_values(self):
        """测试默认值"""
        resp = ApiResponse()
        assert resp.code == 0
        assert resp.message == "success"
        assert resp.data is None
        assert resp.trace_id == ""
        assert resp.timestamp > 0

    def test_is_success(self):
        """测试 is_success 属性"""
        assert ApiResponse.success().is_success is True
        assert ApiResponse.error(code=1).is_success is False
        assert ApiResponse(code=0).is_success is True
        assert ApiResponse(code=500).is_success is False

    def test_success_factory(self):
        """测试 success 工厂方法"""
        resp = ApiResponse.success(data={"key": "value"}, message="ok", trace_id="abc123")
        assert resp.code == 0
        assert resp.message == "ok"
        assert resp.data == {"key": "value"}
        assert resp.trace_id == "abc123"
        assert resp.is_success is True

    def test_error_factory(self):
        """测试 error 工厂方法"""
        resp = ApiResponse.error(code=500, message="internal error", data={"detail": "oops"})
        assert resp.code == 500
        assert resp.message == "internal error"
        assert resp.data == {"detail": "oops"}
        assert resp.is_success is False

    def test_to_dict(self):
        """测试 to_dict 方法"""
        resp = ApiResponse.success(data={"foo": "bar"}, trace_id="t1")
        d = resp.to_dict()
        assert isinstance(d, dict)
        assert d["code"] == 0
        assert d["message"] == "success"
        assert d["data"] == {"foo": "bar"}
        assert d["trace_id"] == "t1"
        assert "timestamp" in d

    def test_from_dict(self):
        """测试 from_dict 方法"""
        d = {
            "code": 404,
            "message": "not found",
            "data": {"resource": "user"},
            "trace_id": "t2",
            "timestamp": 1234567890.0,
        }
        resp = ApiResponse.from_dict(d)
        assert resp.code == 404
        assert resp.message == "not found"
        assert resp.data == {"resource": "user"}
        assert resp.trace_id == "t2"
        assert resp.timestamp == 1234567890.0

    def test_from_dict_missing_fields(self):
        """测试 from_dict 缺失字段时使用默认值"""
        resp = ApiResponse.from_dict({})
        assert resp.code == -1
        assert resp.message == ""
        assert resp.data is None
        assert resp.trace_id == ""
        assert resp.timestamp > 0


# ============================================================
# ServiceInstance 测试
# ============================================================

class TestServiceInstance:
    """ServiceInstance 测试"""

    def test_creation(self):
        """测试基本创建"""
        inst = ServiceInstance(
            service_name="m1",
            instance_id="m1-1",
            address="127.0.0.1",
            port=8001,
        )
        assert inst.service_name == "m1"
        assert inst.instance_id == "m1-1"
        assert inst.address == "127.0.0.1"
        assert inst.port == 8001
        assert inst.version == "1.0.0"
        assert inst.weight == 1
        assert inst.status == ServiceStatus.HEALTHY
        assert inst.is_healthy is True

    def test_base_url(self):
        """测试 base_url 属性"""
        inst = ServiceInstance(
            service_name="m8",
            instance_id="m8-1",
            address="192.168.1.100",
            port=8008,
        )
        assert inst.base_url == "http://192.168.1.100:8008"

    def test_is_healthy(self):
        """测试 is_healthy 属性"""
        inst = ServiceInstance(
            service_name="m1",
            instance_id="m1-1",
            address="127.0.0.1",
            port=8001,
            status=ServiceStatus.HEALTHY,
        )
        assert inst.is_healthy is True

        inst.status = ServiceStatus.UNHEALTHY
        assert inst.is_healthy is False

        inst.status = ServiceStatus.STARTING
        assert inst.is_healthy is False

    def test_to_dict(self):
        """测试 to_dict 方法"""
        inst = ServiceInstance(
            service_name="m1",
            instance_id="m1-1",
            address="127.0.0.1",
            port=8001,
            version="2.0.0",
            weight=3,
            metadata={"zone": "east"},
        )
        d = inst.to_dict()
        assert d["service_name"] == "m1"
        assert d["instance_id"] == "m1-1"
        assert d["address"] == "127.0.0.1"
        assert d["port"] == 8001
        assert d["base_url"] == "http://127.0.0.1:8001"
        assert d["version"] == "2.0.0"
        assert d["weight"] == 3
        assert d["status"] == "healthy"
        assert d["metadata"] == {"zone": "east"}

    def test_from_dict(self):
        """测试 from_dict 方法"""
        d = {
            "service_name": "m2",
            "instance_id": "m2-3",
            "address": "10.0.0.5",
            "port": 8002,
            "version": "1.5.0",
            "weight": 2,
            "status": "unhealthy",
            "metadata": {"env": "prod"},
        }
        inst = ServiceInstance.from_dict(d)
        assert inst.service_name == "m2"
        assert inst.instance_id == "m2-3"
        assert inst.address == "10.0.0.5"
        assert inst.port == 8002
        assert inst.version == "1.5.0"
        assert inst.weight == 2
        assert inst.status == ServiceStatus.UNHEALTHY
        assert inst.metadata == {"env": "prod"}

    def test_from_dict_with_host(self):
        """测试 from_dict 使用 host 字段（兼容旧格式）"""
        d = {
            "service_name": "m3",
            "instance_id": "m3-1",
            "host": "192.168.1.1",
            "port": 8003,
        }
        inst = ServiceInstance.from_dict(d)
        assert inst.address == "192.168.1.1"
        assert inst.port == 8003


# ============================================================
# Event 测试
# ============================================================

class TestEvent:
    """Event 测试"""

    def test_creation(self):
        """测试基本创建"""
        event = Event(
            event_type="user.created",
            data={"user_id": "123", "name": "test"},
            source="m1",
        )
        assert event.event_type == "user.created"
        assert event.data == {"user_id": "123", "name": "test"}
        assert event.source == "m1"
        assert event.event_id != ""
        assert event.timestamp > 0
        assert event.trace_id == ""

    def test_auto_event_id(self):
        """测试自动生成 event_id"""
        e1 = Event(event_type="a", data={})
        e2 = Event(event_type="a", data={})
        assert e1.event_id != e2.event_id

    def test_to_dict(self):
        """测试 to_dict 方法"""
        event = Event(
            event_type="order.placed",
            data={"order_id": "O001"},
            source="m4",
            trace_id="trace-001",
            metadata={"priority": "high"},
        )
        d = event.to_dict()
        assert d["event_type"] == "order.placed"
        assert d["data"] == {"order_id": "O001"}
        assert d["source"] == "m4"
        assert d["trace_id"] == "trace-001"
        assert d["metadata"] == {"priority": "high"}
        assert "event_id" in d
        assert "timestamp" in d

    def test_from_dict(self):
        """测试 from_dict 方法"""
        d = {
            "event_type": "payment.received",
            "data": {"amount": 100},
            "source": "m5",
            "event_id": "evt-123",
            "timestamp": 1234567890.0,
            "trace_id": "t-abc",
            "metadata": {"currency": "CNY"},
        }
        event = Event.from_dict(d)
        assert event.event_type == "payment.received"
        assert event.data == {"amount": 100}
        assert event.source == "m5"
        assert event.event_id == "evt-123"
        assert event.timestamp == 1234567890.0
        assert event.trace_id == "t-abc"
        assert event.metadata == {"currency": "CNY"}

    def test_matches_exact(self):
        """测试精确匹配"""
        event = Event(event_type="user.created", data={})
        assert event.matches("user.created") is True
        assert event.matches("user.deleted") is False

    def test_matches_single_wildcard(self):
        """测试单级通配符 *"""
        event = Event(event_type="user.created", data={})
        assert event.matches("user.*") is True
        assert event.matches("*.created") is True
        assert event.matches("*.*") is True
        assert event.matches("user.*.error") is False
        assert event.matches("*.deleted") is False

    def test_matches_multi_wildcard(self):
        """测试多级通配符 #"""
        event = Event(event_type="module.started.error", data={})
        assert event.matches("#") is True
        assert event.matches("module.#") is True
        assert event.matches("module.started.#") is True
        assert event.matches("other.#") is False

    def test_matches_mixed(self):
        """测试混合通配符"""
        event = Event(event_type="a.b.c.d", data={})
        assert event.matches("a.#") is True
        assert event.matches("a.b.#") is True
        assert event.matches("a.*.c.*") is True
        assert event.matches("a.*.d") is False


# ============================================================
# 事件模式匹配测试
# ============================================================

class TestEventPatternMatching:
    """事件模式匹配测试"""

    def test_exact_match(self):
        """精确匹配"""
        assert _match_event_pattern("a.b.c", "a.b.c") is True
        assert _match_event_pattern("a.b", "a.b.c") is False

    def test_hash_wildcard(self):
        """# 通配符"""
        assert _match_event_pattern("a.b.c", "#") is True
        assert _match_event_pattern("a.b.c", "a.#") is True
        assert _match_event_pattern("a.b.c", "a.b.#") is True
        assert _match_event_pattern("a.b.c", "b.#") is False

    def test_star_wildcard(self):
        """* 通配符"""
        assert _match_event_pattern("a.b.c", "a.*.c") is True
        assert _match_event_pattern("a.b.c", "a.b.*") is True
        assert _match_event_pattern("a.b.c", "*.b.c") is True
        assert _match_event_pattern("a.b.c", "*.*.*") is True
        assert _match_event_pattern("a.b.c", "a.b.c.d") is False
        assert _match_event_pattern("a.b.c", "*.*") is False

    def test_edge_cases(self):
        """边界情况"""
        assert _match_event_pattern("", "") is True
        assert _match_event_pattern("a", "") is False
        assert _match_event_pattern("", "a") is False


# ============================================================
# 枚举测试
# ============================================================

class TestEnums:
    """枚举测试"""

    def test_service_status_values(self):
        """测试 ServiceStatus 枚举值"""
        assert ServiceStatus.HEALTHY.value == "healthy"
        assert ServiceStatus.UNHEALTHY.value == "unhealthy"
        assert ServiceStatus.STARTING.value == "starting"
        assert ServiceStatus.STOPPING.value == "stopping"
        assert ServiceStatus.UNKNOWN.value == "unknown"

    def test_load_balance_strategy(self):
        """测试负载均衡策略枚举"""
        assert LoadBalanceStrategy.ROUND_ROBIN.value == "round_robin"
        assert LoadBalanceStrategy.RANDOM.value == "random"
        assert LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN.value == "weighted_round_robin"
        assert LoadBalanceStrategy.LEAST_CONNECTIONS.value == "least_connections"
        assert LoadBalanceStrategy.CONSISTENT_HASH.value == "consistent_hash"

    def test_circuit_state(self):
        """测试熔断器状态枚举"""
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_sdk_error_codes(self):
        """测试 SDK 错误码"""
        assert SdkErrorCode.SUCCESS == 0
        assert SdkErrorCode.SERVICE_NOT_FOUND == 410
        assert SdkErrorCode.NO_HEALTHY_INSTANCE == 411
        assert SdkErrorCode.CALL_FAILED == 710
        assert SdkErrorCode.CALL_TIMEOUT == 711
        assert SdkErrorCode.CALL_RETRY_EXHAUSTED == 712
        assert SdkErrorCode.CIRCUIT_OPEN == 810
        assert SdkErrorCode.REGISTRY_UNAVAILABLE == 612
