"""
连接器基类接口测试

测试 BaseConnector 接口和 ConnectorRegistry 注册表
"""

import sys
from pathlib import Path
import pytest

backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from connectors.base import (
    BaseConnector,
    ConnectorMeta,
    ConnectorRegistry,
    ConnectorType,
    ConnectionStatus,
    HealthStatus,
    HealthCheckResult,
    ConnectorStats,
)
from typing import Iterator, List, Dict, Any, Optional


# ============================================================
# 测试用连接器
# ============================================================

class TestConnector(BaseConnector):
    """测试用连接器"""

    meta = ConnectorMeta(
        name="test",
        connector_type=ConnectorType.DATABASE,
        description="测试连接器",
        version="1.0.0",
        supported_operations=["read", "write"],
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._data = [
            {"id": 1, "name": "Alice", "age": 25},
            {"id": 2, "name": "Bob", "age": 30},
            {"id": 3, "name": "Charlie", "age": 35},
        ]

    def connect(self, config: Optional[Dict[str, Any]] = None) -> bool:
        if config:
            self._config.update(config)
        self._status = ConnectionStatus.CONNECTED
        return True

    def disconnect(self) -> bool:
        self._status = ConnectionStatus.DISCONNECTED
        return True

    def read(self, query: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        self._ensure_connected()
        query = query or {}
        limit = query.get("limit")
        offset = query.get("offset", 0)

        count = 0
        for i, record in enumerate(self._data):
            if i < offset:
                continue
            if limit and i >= offset + limit:
                break
            count += 1
            yield record
        self._stats.total_reads += 1
        self._stats.total_bytes_read += count

    def write(self, data: List[Dict[str, Any]]) -> int:
        self._ensure_connected()
        self._data.extend(data)
        return len(data)

    def list_tables(self) -> List[str]:
        return ["test_table"]

    def get_schema(self, table: str) -> Dict[str, Any]:
        return {
            "table": table,
            "fields": {
                "id": {"type": "integer", "primary_key": True},
                "name": {"type": "string"},
                "age": {"type": "integer"},
            }
        }


# ============================================================
# 测试：连接器元数据
# ============================================================

class TestConnectorMeta:
    """测试连接器元数据"""

    def test_meta_defaults(self):
        """测试默认元数据"""
        meta = ConnectorMeta()
        assert meta.name == ""
        assert meta.connector_type == ""
        assert meta.description == ""
        assert meta.version == "1.0.0"
        assert meta.supported_operations == []

    def test_meta_custom(self):
        """测试自定义元数据"""
        meta = ConnectorMeta(
            name="test",
            connector_type="database",
            description="测试",
            version="2.0.0",
            supported_operations=["read", "write"],
        )
        assert meta.name == "test"
        assert meta.connector_type == "database"
        assert meta.description == "测试"
        assert meta.version == "2.0.0"
        assert meta.supported_operations == ["read", "write"]


# ============================================================
# 测试：健康检查结果
# ============================================================

class TestHealthCheckResult:
    """测试健康检查结果"""

    def test_defaults(self):
        """测试默认值"""
        result = HealthCheckResult()
        assert result.status == HealthStatus.UNKNOWN
        assert result.response_time_ms == 0.0
        assert result.details == {}
        assert result.error is None

    def test_to_dict(self):
        """测试转字典"""
        result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            response_time_ms=123.456,
            details={"db": "ok"},
            error=None,
        )
        d = result.to_dict()
        assert d["status"] == HealthStatus.HEALTHY
        assert d["response_time_ms"] == 123.46
        assert d["details"] == {"db": "ok"}
        assert d["error"] is None


# ============================================================
# 测试：连接器统计
# ============================================================

class TestConnectorStats:
    """测试连接器统计"""

    def test_defaults(self):
        """测试默认统计"""
        stats = ConnectorStats()
        assert stats.total_reads == 0
        assert stats.total_writes == 0
        assert stats.total_bytes_read == 0
        assert stats.total_errors == 0

    def test_to_dict(self):
        """测试转字典"""
        stats = ConnectorStats(total_reads=10, total_writes=5)
        d = stats.to_dict()
        assert d["total_reads"] == 10
        assert d["total_writes"] == 5


# ============================================================
# 测试：基类接口
# ============================================================

class TestBaseConnector:
    """测试连接器基类接口"""

    def test_init(self):
        """测试初始化"""
        conn = TestConnector()
        assert conn.status == ConnectionStatus.DISCONNECTED
        assert not conn.is_connected()

    def test_connect_disconnect(self):
        """测试连接和断开"""
        conn = TestConnector()
        assert conn.connect() is True
        assert conn.is_connected() is True
        assert conn.status == ConnectionStatus.CONNECTED

        assert conn.disconnect() is True
        assert conn.is_connected() is False
        assert conn.status == ConnectionStatus.DISCONNECTED

    def test_config_sanitization(self):
        """测试配置脱敏"""
        conn = TestConnector(config={
            "host": "localhost",
            "password": "secret123",
            "token": "abc123",
            "api_key": "key123",
        })
        sanitized = conn.config
        assert sanitized["host"] == "localhost"
        assert sanitized["password"] == "***"
        assert sanitized["token"] == "***"
        assert sanitized["api_key"] == "***"

    def test_read(self):
        """测试流式读取"""
        conn = TestConnector()
        conn.connect()
        results = list(conn.read())
        assert len(results) == 3
        assert results[0]["id"] == 1

    def test_read_batch(self):
        """测试批量读取"""
        conn = TestConnector()
        conn.connect()
        results = conn.read_batch(batch_size=2)
        assert len(results) == 2

    def test_read_all(self):
        """测试读取全部"""
        conn = TestConnector()
        conn.connect()
        results = conn.read_all()
        assert len(results) == 3

    def test_write(self):
        """测试写入"""
        conn = TestConnector()
        conn.connect()
        count = conn.write([{"id": 4, "name": "David", "age": 40}])
        assert count == 1
        results = conn.read_all()
        assert len(results) == 4

    def test_list_tables(self):
        """测试列出表"""
        conn = TestConnector()
        conn.connect()
        tables = conn.list_tables()
        assert "test_table" in tables

    def test_get_schema(self):
        """测试获取 Schema"""
        conn = TestConnector()
        conn.connect()
        schema = conn.get_schema("test_table")
        assert schema["table"] == "test_table"
        assert "id" in schema["fields"]

    def test_health_check(self):
        """测试健康检查"""
        conn = TestConnector()
        conn.connect()
        result = conn.health_check()
        assert isinstance(result, HealthCheckResult)
        assert result.status == HealthStatus.HEALTHY
        assert result.response_time_ms >= 0

    def test_get_stats(self):
        """测试获取统计"""
        conn = TestConnector()
        conn.connect()
        conn.read_all()
        stats = conn.get_stats()
        assert stats["total_reads"] > 0

    def test_reset_stats(self):
        """测试重置统计"""
        conn = TestConnector()
        conn.connect()
        conn.read_all()
        conn.reset_stats()
        stats = conn.get_stats()
        assert stats["total_reads"] == 0

    def test_context_manager(self):
        """测试上下文管理器"""
        with TestConnector() as conn:
            assert conn.is_connected()
            results = conn.read_all()
            assert len(results) == 3

    def test_ensure_connected_raises(self):
        """测试未连接时读取抛出异常"""
        conn = TestConnector()
        with pytest.raises(ConnectionError):
            list(conn.read())

    def test_write_stream(self):
        """测试流式写入"""
        conn = TestConnector()
        conn.connect()

        def data_gen():
            yield {"id": 10, "name": "Test", "age": 99}

        count = conn.write_stream(data_gen())
        assert count == 1


# ============================================================
# 测试：连接器注册表
# ============================================================

class TestConnectorRegistry:
    """测试连接器注册表"""

    def setup_method(self):
        """每个测试前清空注册表"""
        ConnectorRegistry.clear()

    def test_register(self):
        """测试注册连接器"""
        ConnectorRegistry.register(TestConnector, "database")
        assert "TestConnector" in ConnectorRegistry.list_all()

    def test_register_decorator(self):
        """测试装饰器注册"""

        @ConnectorRegistry.register
        class DecoratedConnector(TestConnector):
            meta = ConnectorMeta(name="decorated")

        assert "DecoratedConnector" in ConnectorRegistry.list_all()

    def test_get(self):
        """测试获取连接器类"""
        ConnectorRegistry.register(TestConnector)
        cls = ConnectorRegistry.get("TestConnector")
        assert cls is TestConnector

    def test_get_nonexistent(self):
        """测试获取不存在的连接器"""
        assert ConnectorRegistry.get("NonExistent") is None

    def test_create(self):
        """测试创建连接器实例"""
        ConnectorRegistry.register(TestConnector)
        conn = ConnectorRegistry.create("TestConnector")
        assert isinstance(conn, TestConnector)

    def test_create_nonexistent(self):
        """测试创建不存在的连接器"""
        with pytest.raises(ValueError):
            ConnectorRegistry.create("NonExistent")

    def test_unregister(self):
        """测试注销连接器"""
        ConnectorRegistry.register(TestConnector)
        assert ConnectorRegistry.unregister("TestConnector") is True
        assert ConnectorRegistry.get("TestConnector") is None

    def test_unregister_nonexistent(self):
        """测试注销不存在的连接器"""
        assert ConnectorRegistry.unregister("NonExistent") is False

    def test_list_all(self):
        """测试列出所有连接器"""
        ConnectorRegistry.register(TestConnector, "database")
        all_types = ConnectorRegistry.list_all()
        assert "TestConnector" in all_types

    def test_list_by_category(self):
        """测试按分类列出"""
        ConnectorRegistry.register(TestConnector, "database")
        db_types = ConnectorRegistry.list_by_category("database")
        assert "TestConnector" in db_types

    def test_get_categories(self):
        """测试获取分类"""
        ConnectorRegistry.register(TestConnector, "database")
        categories = ConnectorRegistry.get_categories()
        assert "database" in categories
        assert "TestConnector" in categories["database"]

    def test_get_meta(self):
        """测试获取元数据"""
        ConnectorRegistry.register(TestConnector)
        meta = ConnectorRegistry.get_meta("TestConnector")
        assert meta is not None
        assert meta.name == "test"

    def test_register_invalid_class(self):
        """测试注册非 BaseConnector 子类"""
        with pytest.raises(TypeError):
            ConnectorRegistry.register(str)  # type: ignore

    def test_clear(self):
        """测试清空注册表"""
        # 保存当前状态
        saved_connectors = dict(ConnectorRegistry._connectors)
        saved_categories = {k: list(v) for k, v in ConnectorRegistry._categories.items()}
        try:
            ConnectorRegistry.register(TestConnector)
            ConnectorRegistry.clear()
            assert len(ConnectorRegistry.list_all()) == 0
        finally:
            # 恢复状态
            ConnectorRegistry._connectors = saved_connectors
            ConnectorRegistry._categories = saved_categories
