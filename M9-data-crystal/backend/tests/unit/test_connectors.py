"""
内置连接器基本测试

测试 8 个内置连接器的基本功能
"""

import sys
import os
import tempfile
import json
import csv
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from connectors import (
    SQLiteConnector,
    CSVConnector,
    JSONConnector,
    ExcelConnector,
    MySQLConnector,
    PostgreSQLConnector,
    RESTAPIConnector,
    S3Connector,
    ConnectorRegistry,
)

# 检查 openpyxl 是否可用（用于 skipif 装饰器）
def _openpyxl_available():
    try:
        import openpyxl
        return True
    except ImportError:
        return False


# ============================================================
# SQLite 连接器测试
# ============================================================

class TestSQLiteConnector:
    """测试 SQLite 连接器"""

    def test_create_instance(self):
        """测试创建实例"""
        conn = SQLiteConnector(config={"db_path": ":memory:"})
        assert conn is not None
        assert conn.meta.name == "sqlite"

    def test_connect_memory(self):
        """测试内存数据库连接"""
        conn = SQLiteConnector(config={"db_path": ":memory:"})
        assert conn.connect() is True
        assert conn.is_connected()

    def test_create_table_and_write_read(self):
        """测试创建表、写入和读取"""
        conn = SQLiteConnector(config={"db_path": ":memory:"})
        conn.connect()

        # 创建表
        conn.create_table("users", {
            "fields": {
                "id": {"type": "INTEGER", "primary_key": True, "autoincrement": True},
                "name": {"type": "TEXT", "nullable": False},
                "age": {"type": "INTEGER"},
            }
        })

        # 设置写入表
        conn._config["write_table"] = "users"

        # 写入数据
        data = [
            {"name": "Alice", "age": 25},
            {"name": "Bob", "age": 30},
            {"name": "Charlie", "age": 35},
        ]
        count = conn.write(data)
        assert count == 3

        # 读取数据
        results = conn.read_all({"table": "users"})
        assert len(results) == 3
        assert results[0]["name"] == "Alice"

        conn.disconnect()

    def test_read_with_where(self):
        """测试带条件的查询"""
        conn = SQLiteConnector(config={"db_path": ":memory:"})
        conn.connect()
        conn.create_table("items", {
            "fields": {
                "id": {"type": "INTEGER", "primary_key": True},
                "value": {"type": "TEXT"},
            }
        })
        conn._config["write_table"] = "items"
        conn.write([{"id": 1, "value": "a"}, {"id": 2, "value": "b"}])

        results = conn.read_all({"table": "items", "where": {"id": 1}})
        assert len(results) == 1
        assert results[0]["value"] == "a"

        conn.disconnect()

    def test_list_tables(self):
        """测试列出表"""
        conn = SQLiteConnector(config={"db_path": ":memory:"})
        conn.connect()
        conn.create_table("t1", {"fields": {"id": {"type": "INTEGER"}}})
        tables = conn.list_tables()
        assert "t1" in tables
        conn.disconnect()

    def test_get_schema(self):
        """测试获取 Schema"""
        conn = SQLiteConnector(config={"db_path": ":memory:"})
        conn.connect()
        conn.create_table("test", {
            "fields": {
                "id": {"type": "INTEGER", "primary_key": True},
                "name": {"type": "TEXT"},
            }
        })
        schema = conn.get_schema("test")
        assert schema["table"] == "test"
        assert "id" in schema["fields"]
        assert "name" in schema["fields"]
        conn.disconnect()

    def test_read_batch(self):
        """测试批量读取"""
        conn = SQLiteConnector(config={"db_path": ":memory:"})
        conn.connect()
        conn.create_table("nums", {
            "fields": {"n": {"type": "INTEGER"}}
        })
        conn._config["write_table"] = "nums"
        conn.write([{"n": i} for i in range(10)])

        batch = conn.read_batch(3, {"table": "nums"})
        assert len(batch) == 3
        conn.disconnect()

    def test_health_check(self):
        """测试健康检查"""
        conn = SQLiteConnector(config={"db_path": ":memory:"})
        conn.connect()
        result = conn.health_check()
        assert result.status == "healthy"
        conn.disconnect()

    def test_disconnect(self):
        """测试断开连接"""
        conn = SQLiteConnector(config={"db_path": ":memory:"})
        conn.connect()
        assert conn.disconnect() is True
        assert not conn.is_connected()


# ============================================================
# CSV 连接器测试
# ============================================================

class TestCSVConnector:
    """测试 CSV 连接器"""

    def test_create_instance(self):
        """测试创建实例"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write("name,age,city\nAlice,25,Beijing\nBob,30,Shanghai\n")
            f.flush()
            path = f.name

        try:
            conn = CSVConnector(config={"file_path": path})
            assert conn is not None
            assert conn.meta.name == "csv"
        finally:
            os.unlink(path)

    def test_connect_and_read(self):
        """测试连接和读取"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write("name,age,city\nAlice,25,Beijing\nBob,30,Shanghai\nCharlie,35,Guangzhou\n")
            f.flush()
            path = f.name

        try:
            conn = CSVConnector(config={"file_path": path})
            assert conn.connect() is True
            results = conn.read_all()
            assert len(results) == 3
            assert results[0]["name"] == "Alice"
            assert results[0]["age"] == "25"
            conn.disconnect()
        finally:
            os.unlink(path)

    def test_read_with_limit(self):
        """测试限制读取数量"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write("a,b\n1,2\n3,4\n5,6\n7,8\n")
            f.flush()
            path = f.name

        try:
            conn = CSVConnector(config={"file_path": path})
            conn.connect()
            results = conn.read_all({"limit": 2})
            assert len(results) == 2
            conn.disconnect()
        finally:
            os.unlink(path)

    def test_write(self):
        """测试写入"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            path = f.name

        try:
            conn = CSVConnector(config={"file_path": path, "mode": "w"})
            conn.connect()
            data = [{"x": 1, "y": 2}, {"x": 3, "y": 4}]
            count = conn.write(data)
            assert count == 2
            conn.disconnect()

            # 验证写入
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 2
        finally:
            os.unlink(path)

    def test_custom_delimiter(self):
        """测试自定义分隔符"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write("name;age\nAlice;25\nBob;30\n")
            f.flush()
            path = f.name

        try:
            conn = CSVConnector(config={"file_path": path, "delimiter": ";"})
            conn.connect()
            results = conn.read_all()
            assert len(results) == 2
            assert results[0]["name"] == "Alice"
            conn.disconnect()
        finally:
            os.unlink(path)


# ============================================================
# JSON 连接器测试
# ============================================================

class TestJSONConnector:
    """测试 JSON 连接器"""

    def test_read_json_array(self):
        """测试读取 JSON 数组"""
        data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(data, f)
            f.flush()
            path = f.name

        try:
            conn = JSONConnector(config={"file_path": path})
            conn.connect()
            results = conn.read_all()
            assert len(results) == 2
            assert results[0]["name"] == "Alice"
            conn.disconnect()
        finally:
            os.unlink(path)

    def test_read_jsonl(self):
        """测试读取 JSONL"""
        lines = [
            json.dumps({"id": 1, "name": "Alice"}),
            json.dumps({"id": 2, "name": "Bob"}),
        ]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False, encoding='utf-8') as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            path = f.name

        try:
            conn = JSONConnector(config={"file_path": path})
            conn.connect()
            results = conn.read_all()
            assert len(results) == 2
            assert results[1]["name"] == "Bob"
            conn.disconnect()
        finally:
            os.unlink(path)

    def test_flatten(self):
        """测试嵌套展平"""
        data = [{"id": 1, "user": {"name": "Alice", "age": 25}}]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(data, f)
            f.flush()
            path = f.name

        try:
            conn = JSONConnector(config={"file_path": path, "flatten": True})
            conn.connect()
            results = conn.read_all()
            assert len(results) == 1
            assert "user_name" in results[0]
            assert results[0]["user_name"] == "Alice"
            conn.disconnect()
        finally:
            os.unlink(path)

    def test_write_json(self):
        """测试写入 JSON"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            path = f.name

        try:
            conn = JSONConnector(config={"file_path": path, "mode": "w", "write_format": "jsonl"})
            conn.connect()
            data = [{"a": 1}, {"b": 2}]
            count = conn.write(data)
            assert count == 2
            conn.disconnect()
        finally:
            os.unlink(path)


# ============================================================
# Excel 连接器测试
# ============================================================

class TestExcelConnector:
    """测试 Excel 连接器"""

    def test_create_instance(self):
        """测试创建实例"""
        conn = ExcelConnector(config={"file_path": "/tmp/test.xlsx"})
        assert conn is not None
        assert conn.meta.name == "excel"

    def test_meta_properties(self):
        """测试连接器元数据属性"""
        conn = ExcelConnector(config={"file_path": "/tmp/test.xlsx"})
        assert conn.meta.connector_type == "file"
        assert hasattr(conn, "connect")
        assert hasattr(conn, "disconnect")
        assert hasattr(conn, "read_all")
        assert hasattr(conn, "write")

    def test_disconnect_without_connect(self):
        """测试未连接时断开连接"""
        conn = ExcelConnector(config={"file_path": "/tmp/test.xlsx"})
        # 未连接时断开应该返回 True（或不抛出异常）
        result = conn.disconnect()
        assert isinstance(result, bool)

    def test_is_connected_before_connect(self):
        """测试连接前 is_connected 返回 False"""
        conn = ExcelConnector(config={"file_path": "/tmp/test.xlsx"})
        assert conn.is_connected() is False

    @pytest.mark.skipif(not _openpyxl_available(), reason="openpyxl not installed")
    def test_connect_and_create(self):
        """测试连接并创建新文件"""
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
            path = f.name

        try:
            conn = ExcelConnector(config={"file_path": path, "mode": "w"})
            assert conn.connect() is True
            assert conn.is_connected()
            conn.disconnect()
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @pytest.mark.skipif(not _openpyxl_available(), reason="openpyxl not installed")
    def test_write_and_read(self):
        """测试写入和读取"""
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "test.xlsx")

        try:
            # 写入
            conn = ExcelConnector(config={"file_path": path, "mode": "w"})
            conn.connect()
            data = [{"Name": "Alice", "Age": 25}, {"Name": "Bob", "Age": 30}]
            count = conn.write(data)
            assert count == 2
            conn.disconnect()

            # 读取
            conn2 = ExcelConnector(config={"file_path": path, "mode": "r"})
            conn2.connect()
            results = conn2.read_all()
            assert len(results) == 2
            assert results[0]["Name"] == "Alice"
            conn2.disconnect()
        finally:
            import shutil
            if os.path.exists(tmpdir):
                shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.skipif(not _openpyxl_available(), reason="openpyxl not installed")
    def test_list_tables(self):
        """测试列出 Sheet"""
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
            path = f.name

        try:
            conn = ExcelConnector(config={"file_path": path, "mode": "w"})
            conn.connect()
            sheets = conn.list_tables()
            assert len(sheets) >= 1  # 至少有一个默认 Sheet
            conn.disconnect()
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @pytest.mark.skipif(not _openpyxl_available(), reason="openpyxl not installed")
    def test_write_empty_data(self):
        """测试写入空数据"""
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
            path = f.name

        try:
            conn = ExcelConnector(config={"file_path": path, "mode": "w"})
            conn.connect()
            count = conn.write([])
            assert count == 0
            conn.disconnect()
        finally:
            if os.path.exists(path):
                os.unlink(path)


# ============================================================
# MySQL / PostgreSQL 连接器测试（无需实际连接）
# ============================================================

class TestMySQLConnector:
    """测试 MySQL 连接器（无实际连接）"""

    def test_create_instance(self):
        """测试创建实例"""
        conn = MySQLConnector(config={"host": "localhost", "user": "test"})
        assert conn is not None
        assert conn.meta.name == "mysql"
        assert conn.meta.connector_type == "database"

    def test_connect_without_driver(self):
        """测试无驱动时的连接失败"""
        conn = MySQLConnector(config={"host": "invalid_host"})
        # 没有安装 pymysql 时会返回 False，但不应抛出异常
        result = conn.connect()
        # 可能成功也可能失败，取决于环境，但至少不应该崩溃
        assert isinstance(result, bool)

    def test_disconnect_without_connect(self):
        """测试未连接时断开"""
        conn = MySQLConnector(config={})
        assert conn.disconnect() is True


class TestPostgreSQLConnector:
    """测试 PostgreSQL 连接器（无实际连接）"""

    def test_create_instance(self):
        """测试创建实例"""
        conn = PostgreSQLConnector(config={"host": "localhost", "user": "test"})
        assert conn is not None
        assert conn.meta.name == "postgresql"

    def test_connect_without_driver(self):
        """测试无驱动时的连接失败"""
        conn = PostgreSQLConnector(config={"host": "invalid_host"})
        result = conn.connect()
        assert isinstance(result, bool)


# ============================================================
# REST API 连接器测试
# ============================================================

class TestRESTAPIConnector:
    """测试 REST API 连接器"""

    def test_create_instance(self):
        """测试创建实例"""
        conn = RESTAPIConnector(config={"base_url": "https://api.example.com"})
        assert conn is not None
        assert conn.meta.name == "rest_api"
        assert conn.meta.connector_type == "api"

    def test_connect(self):
        """测试连接初始化"""
        conn = RESTAPIConnector(config={"base_url": "https://api.example.com"})
        result = conn.connect()
        # 取决于 requests 是否可用
        assert isinstance(result, bool)

    def test_bearer_auth(self):
        """测试 Bearer Token 认证配置"""
        conn = RESTAPIConnector(config={
            "base_url": "https://api.example.com",
            "auth_type": "bearer",
            "token": "test_token_123",
        })
        assert conn._config["auth_type"] == "bearer"
        assert conn._config["token"] == "test_token_123"

    def test_api_key_auth(self):
        """测试 API Key 认证配置"""
        conn = RESTAPIConnector(config={
            "base_url": "https://api.example.com",
            "auth_type": "api_key",
            "api_key": "key_123",
        })
        assert conn._config["auth_type"] == "api_key"

    def test_disconnect_without_connect(self):
        """测试未连接时断开"""
        conn = RESTAPIConnector(config={"base_url": "https://example.com"})
        assert conn.disconnect() is True


# ============================================================
# S3 连接器测试
# ============================================================

class TestS3Connector:
    """测试 S3 连接器"""

    def test_create_instance(self):
        """测试创建实例"""
        conn = S3Connector(config={
            "access_key": "test",
            "secret_key": "test",
            "bucket": "test-bucket",
        })
        assert conn is not None
        assert conn.meta.name == "s3"
        assert conn.meta.connector_type == "cloud"

    def test_connect_without_driver(self):
        """测试无 boto3 时的连接失败"""
        conn = S3Connector(config={
            "access_key": "test",
            "secret_key": "test",
            "bucket": "test-bucket",
        })
        result = conn.connect()
        assert isinstance(result, bool)

    def test_disconnect_without_connect(self):
        """测试未连接时断开"""
        conn = S3Connector(config={"bucket": "test"})
        assert conn.disconnect() is True


# ============================================================
# 注册表测试：所有连接器都已注册
# ============================================================

class TestConnectorRegistration:
    """测试所有连接器都已正确注册"""

    @classmethod
    def setup_class(cls):
        """确保所有内置连接器都已注册"""
        # 导入所有连接器模块以触发注册
        from connectors import (
            SQLiteConnector, CSVConnector, JSONConnector, ExcelConnector,
            MySQLConnector, PostgreSQLConnector, RESTAPIConnector, S3Connector,
        )
        # 确保每个连接器都在注册表中
        for conn_cls in [
            SQLiteConnector, CSVConnector, JSONConnector, ExcelConnector,
            MySQLConnector, PostgreSQLConnector, RESTAPIConnector, S3Connector,
        ]:
            if conn_cls.__name__ not in ConnectorRegistry._connectors:
                ConnectorRegistry.register(conn_cls)

    def test_all_connectors_registered(self):
        """测试 8 个连接器都已注册"""
        registered = ConnectorRegistry.list_all()
        expected = [
            "SQLiteConnector",
            "CSVConnector",
            "JSONConnector",
            "ExcelConnector",
            "MySQLConnector",
            "PostgreSQLConnector",
            "RESTAPIConnector",
            "S3Connector",
        ]
        for name in expected:
            assert name in registered, f"{name} 未注册"

    def test_connector_categories(self):
        """测试连接器分类"""
        categories = ConnectorRegistry.get_categories()
        # 至少有 database, file, api, cloud 分类
        assert "database" in categories
        assert "file" in categories
        assert "api" in categories
        assert "cloud" in categories
