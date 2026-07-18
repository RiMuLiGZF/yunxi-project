"""
管道执行测试 + 连接器管理器测试

测试管道同步/异步/取消执行，以及连接器管理器功能
"""

import sys
import time
import tempfile
import os
from pathlib import Path
import pytest

backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from pipelines import (
    DataPipeline,
    PipelineStatus,
    FilterStage,
    TransformStage,
    CleanStage,
    PipelineManager,
    get_pipeline_manager,
)
from connectors.manager import ConnectorManager
from connectors.base import BaseConnector, ConnectorMeta, ConnectionStatus
from typing import Iterator, List, Dict, Any, Optional


# ============================================================
# 测试用连接器
# ============================================================

class TestSourceConnector(BaseConnector):
    """测试用源连接器"""
    meta = ConnectorMeta(name="test_source", connector_type="database")

    def __init__(self, config=None):
        super().__init__(config)
        self._data = [
            {"id": i, "name": f"User_{i}", "age": 20 + i % 10, "city": "Beijing" if i % 2 == 0 else "Shanghai"}
            for i in range(20)
        ]

    def connect(self, config=None):
        if config:
            self._config.update(config)
        self._status = ConnectionStatus.CONNECTED
        return True

    def disconnect(self):
        self._status = ConnectionStatus.DISCONNECTED
        return True

    def read(self, query=None):
        self._ensure_connected()
        query = query or {}
        limit = query.get("limit")
        offset = query.get("offset", 0)
        for i, record in enumerate(self._data):
            if i < offset:
                continue
            if limit and i >= offset + limit:
                break
            yield record

    def write(self, data):
        self._ensure_connected()
        self._data.extend(data)
        return len(data)


class TestTargetConnector(BaseConnector):
    """测试用目标连接器"""
    meta = ConnectorMeta(name="test_target", connector_type="database")

    def __init__(self, config=None):
        super().__init__(config)
        self._written_data = []

    def connect(self, config=None):
        if config:
            self._config.update(config)
        self._status = ConnectionStatus.CONNECTED
        return True

    def disconnect(self):
        self._status = ConnectionStatus.DISCONNECTED
        return True

    def read(self, query=None):
        yield from []

    def write(self, data):
        self._ensure_connected()
        self._written_data.extend(data)
        return len(data)


# ============================================================
# 管道执行测试
# ============================================================

class TestDataPipeline:
    """测试数据管道执行"""

    def test_pipeline_with_source_only(self):
        pipeline = DataPipeline(name="test_pipe")
        source = TestSourceConnector()
        source.connect()
        result = pipeline.run(source=source)
        assert result.status == PipelineStatus.SUCCESS
        assert result.total_records_read == 20
        assert result.total_records_processed == 20

    def test_pipeline_with_source_and_target(self):
        pipeline = DataPipeline(name="test_pipe")
        source = TestSourceConnector()
        target = TestTargetConnector()
        source.connect()
        target.connect()
        result = pipeline.run(source=source, target=target)
        assert result.status == PipelineStatus.SUCCESS
        assert result.total_records_read == 20
        assert result.total_records_written == 20
        assert len(target._written_data) == 20

    def test_pipeline_with_filter_stage(self):
        pipeline = DataPipeline(name="filter_pipe")
        pipeline.add_stage(FilterStage(config={
            "type": "condition",
            "conditions": [{"field": "city", "operator": "eq", "value": "Beijing"}],
        }))
        source = TestSourceConnector()
        source.connect()
        result = pipeline.run(source=source)
        assert result.status == PipelineStatus.SUCCESS
        assert result.total_records_read == 20
        assert result.total_records_processed == 10

    def test_pipeline_with_multiple_stages(self):
        pipeline = DataPipeline(name="multi_stage_pipe")
        pipeline.add_stage(FilterStage(config={
            "type": "condition",
            "conditions": [{"field": "city", "operator": "eq", "value": "Beijing"}],
        }))
        pipeline.add_stage(TransformStage(config={
            "rename": {"name": "full_name"},
        }))
        pipeline.add_stage(CleanStage(config={
            "case_mode": "lower",
        }))
        source = TestSourceConnector()
        source.connect()
        result = pipeline.run(source=source)
        assert result.status == PipelineStatus.SUCCESS
        assert len(result.stage_results) == 3
        assert result.stage_results[0].stage_name == "filter"
        assert result.stage_results[0].records_in == 20
        assert result.stage_results[0].records_out == 10
        assert result.total_records_processed == 10

    def test_pipeline_cancel(self):
        pipeline = DataPipeline(name="cancel_pipe")
        pipeline.cancel()
        assert pipeline.is_cancelled() is True

    def test_pipeline_stream(self):
        pipeline = DataPipeline(name="stream_pipe")
        pipeline.add_stage(FilterStage(config={
            "type": "condition",
            "conditions": [{"field": "city", "operator": "eq", "value": "Beijing"}],
        }))
        source = TestSourceConnector()
        source.connect()
        results = list(pipeline.run_stream(source=source))
        assert len(results) == 10

    def test_pipeline_with_list_source(self):
        pipeline = DataPipeline(name="list_pipe")
        data = [{"x": i} for i in range(10)]
        result = pipeline.run(source=data)
        assert result.status == PipelineStatus.SUCCESS
        assert result.total_records_read == 10

    def test_pipeline_validate(self):
        pipeline = DataPipeline(name="valid_pipe")
        pipeline.add_stage(FilterStage(config={"type": "null"}))
        assert pipeline.validate() is True

    def test_pipeline_add_remove_stage(self):
        pipeline = DataPipeline(name="stage_manip")
        s1 = FilterStage(config={"type": "null"})
        s2 = TransformStage(config={})
        pipeline.add_stage(s1)
        assert len(pipeline.stages) == 1
        pipeline.insert_stage(0, s2)
        assert len(pipeline.stages) == 2
        assert pipeline.stages[0] is s2
        removed = pipeline.remove_stage(0)
        assert removed is s2
        assert len(pipeline.stages) == 1

    def test_pipeline_result_to_dict(self):
        pipeline = DataPipeline(name="dict_pipe")
        result = pipeline.run(source=[{"a": 1}])
        d = result.to_dict()
        assert d["pipeline_name"] == "dict_pipe"
        assert d["status"] == PipelineStatus.SUCCESS
        assert "stage_results" in d

    def test_pipeline_no_source(self):
        pipeline = DataPipeline(name="no_source")
        result = pipeline.run(source=None)
        assert result.status == PipelineStatus.FAILED
        assert "数据源" in result.error_message


# ============================================================
# 管道管理器测试
# ============================================================

class TestPipelineManager:
    """测试管道管理器"""

    def setup_method(self):
        self.mgr = PipelineManager(max_concurrent=10)

    def test_create_pipeline(self):
        pipe_id = self.mgr.create_pipeline(
            name="test_pipe",
            stages=[
                {"type": "FilterStage", "config": {"type": "null"}},
            ],
            description="测试管道",
        )
        assert pipe_id is not None
        assert pipe_id.startswith("pipe_")

    def test_get_pipeline(self):
        pipe_id = self.mgr.create_pipeline(
            name="test",
            stages=[{"type": "FilterStage", "config": {"type": "null"}}],
        )
        pipeline = self.mgr.get_pipeline(pipe_id)
        assert pipeline.name == "test"

    def test_get_nonexistent_pipeline(self):
        with pytest.raises(KeyError):
            self.mgr.get_pipeline("nonexistent")

    def test_update_pipeline(self):
        pipe_id = self.mgr.create_pipeline(
            name="original",
            stages=[{"type": "FilterStage", "config": {"type": "null"}}],
        )
        self.mgr.update_pipeline(pipe_id, name="updated")
        pipeline = self.mgr.get_pipeline(pipe_id)
        assert pipeline.name == "updated"

    def test_delete_pipeline(self):
        pipe_id = self.mgr.create_pipeline(
            name="to_delete",
            stages=[{"type": "FilterStage", "config": {"type": "null"}}],
        )
        assert self.mgr.delete_pipeline(pipe_id) is True
        assert self.mgr.delete_pipeline(pipe_id) is False

    def test_list_pipelines(self):
        self.mgr.create_pipeline(name="p1", stages=[{"type": "FilterStage", "config": {}}])
        self.mgr.create_pipeline(name="p2", stages=[{"type": "TransformStage", "config": {}}])
        pipelines = self.mgr.list_pipelines()
        assert len(pipelines) == 2

    def test_run_pipeline_sync(self):
        pipe_id = self.mgr.create_pipeline(
            name="run_test",
            stages=[
                {"type": "FilterStage", "config": {
                    "type": "condition",
                    "conditions": [{"field": "id", "operator": "lt", "value": 5}],
                }},
            ],
        )
        source_data = [{"id": i} for i in range(10)]
        run_record = self.mgr.run_pipeline(
            pipe_id,
            trigger_type="manual",
            source_data=source_data,
        )
        assert run_record.status == PipelineStatus.SUCCESS
        assert run_record.records_read == 10
        assert run_record.records_processed == 5

    def test_run_pipeline_async(self):
        pipe_id = self.mgr.create_pipeline(
            name="async_test",
            stages=[{"type": "FilterStage", "config": {"type": "null"}}],
        )
        source_data = [{"x": i} for i in range(10)]
        run_id = self.mgr.run_pipeline_async(pipe_id, source_data=source_data)
        assert run_id is not None
        assert run_id.startswith("run_")
        # 等待执行完成
        time.sleep(1.0)
        run = self.mgr.get_run(run_id)
        assert run.status in (
            PipelineStatus.SUCCESS,
            PipelineStatus.RUNNING,
            PipelineStatus.PENDING,
        )

    def test_cancel_run(self):
        pipe_id = self.mgr.create_pipeline(
            name="cancel_test",
            stages=[{"type": "FilterStage", "config": {"type": "null"}}],
        )
        run_id = self.mgr.run_pipeline_async(pipe_id, source_data=[{"x": 1}])
        result = self.mgr.cancel_run(run_id)
        assert result is True

    def test_list_runs(self):
        pipe_id = self.mgr.create_pipeline(
            name="runs_test",
            stages=[{"type": "FilterStage", "config": {"type": "null"}}],
        )
        source_data = [{"x": 1}]
        self.mgr.run_pipeline(pipe_id, source_data=source_data)
        self.mgr.run_pipeline(pipe_id, source_data=source_data)
        runs = self.mgr.list_runs(pipeline_id=pipe_id)
        assert len(runs) == 2

    def test_get_run(self):
        pipe_id = self.mgr.create_pipeline(
            name="get_run_test",
            stages=[{"type": "FilterStage", "config": {"type": "null"}}],
        )
        run_record = self.mgr.run_pipeline(pipe_id, source_data=[{"x": 1}])
        fetched = self.mgr.get_run(run_record.run_id)
        assert fetched.run_id == run_record.run_id

    def test_get_stats(self):
        self.mgr.create_pipeline(name="p1", stages=[{"type": "FilterStage", "config": {}}])
        stats = self.mgr.get_stats()
        assert stats["total_pipelines"] == 1
        assert stats["max_concurrent"] == 10

    def test_create_pipeline_invalid_stage(self):
        with pytest.raises(ValueError):
            self.mgr.create_pipeline(
                name="invalid",
                stages=[{"type": "NonExistentStage", "config": {}}],
            )


# ============================================================
# 连接器管理器测试
# ============================================================

class TestConnectorManager:
    """测试连接器管理器"""

    def setup_method(self):
        self.mgr = ConnectorManager(max_pool_size=5, idle_timeout=60)

    def test_list_connector_types(self):
        types = self.mgr.list_connector_types()
        assert len(types) > 0
        names = [t["name"] for t in types]
        assert "SQLiteConnector" in names

    def test_create_connector(self):
        conn_id = self.mgr.create_connector(
            connector_type="SQLiteConnector",
            config={"db_path": ":memory:"},
        )
        assert conn_id is not None
        assert conn_id.startswith("conn_")

    def test_get_connector(self):
        conn_id = self.mgr.create_connector(
            connector_type="SQLiteConnector",
            config={"db_path": ":memory:"},
        )
        connector = self.mgr.get_connector(conn_id)
        assert connector is not None

    def test_get_nonexistent_connector(self):
        with pytest.raises(KeyError):
            self.mgr.get_connector("nonexistent")

    def test_update_connector(self):
        conn_id = self.mgr.create_connector(
            connector_type="SQLiteConnector",
            config={"db_path": ":memory:"},
        )
        result = self.mgr.update_connector(conn_id, {"db_path": ":memory:"})
        assert result is True

    def test_delete_connector(self):
        conn_id = self.mgr.create_connector(
            connector_type="SQLiteConnector",
            config={"db_path": ":memory:"},
        )
        assert self.mgr.delete_connector(conn_id) is True
        assert self.mgr.delete_connector(conn_id) is False

    def test_list_connectors(self):
        self.mgr.create_connector("SQLiteConnector", {"db_path": ":memory:"})
        self.mgr.create_connector("CSVConnector", {"file_path": "/tmp/test.csv"})
        connectors = self.mgr.list_connectors()
        assert len(connectors) == 2

    def test_connect_connector(self):
        conn_id = self.mgr.create_connector(
            "SQLiteConnector",
            {"db_path": ":memory:"},
        )
        result = self.mgr.connect_connector(conn_id)
        assert result is True

    def test_test_connection(self):
        result = self.mgr.test_connection(
            "SQLiteConnector",
            {"db_path": ":memory:"},
        )
        assert result["success"] is True
        assert "response_time_ms" in result

    def test_health_check(self):
        conn_id = self.mgr.create_connector(
            "SQLiteConnector",
            {"db_path": ":memory:"},
        )
        self.mgr.connect_connector(conn_id)
        health = self.mgr.check_health(conn_id)
        assert health.status == "healthy"

    def test_get_health_status(self):
        conn_id = self.mgr.create_connector(
            "SQLiteConnector",
            {"db_path": ":memory:"},
        )
        self.mgr.connect_connector(conn_id)
        status = self.mgr.get_health_status(conn_id)
        assert "status" in status

    def test_list_tables(self):
        conn_id = self.mgr.create_connector(
            "SQLiteConnector",
            {"db_path": ":memory:"},
        )
        self.mgr.connect_connector(conn_id)
        connector = self.mgr.get_connector(conn_id)
        connector.create_table("test_table", {"fields": {"id": {"type": "INTEGER"}}})
        tables = self.mgr.list_tables(conn_id)
        assert "test_table" in tables

    def test_get_schema(self):
        conn_id = self.mgr.create_connector(
            "SQLiteConnector",
            {"db_path": ":memory:"},
        )
        self.mgr.connect_connector(conn_id)
        connector = self.mgr.get_connector(conn_id)
        schema_def = {"fields": {"id": {"type": "INTEGER", "primary_key": True}}}
        connector.create_table("t1", schema_def)
        schema = self.mgr.get_schema(conn_id, "t1")
        assert schema["table"] == "t1"
        assert "id" in schema["fields"]

    def test_get_stats(self):
        self.mgr.create_connector("SQLiteConnector", {"db_path": ":memory:"})
        stats = self.mgr.get_stats()
        assert stats["total_connectors"] == 1

    def test_connection_pool(self):
        conn = self.mgr.acquire_from_pool(
            "SQLiteConnector",
            {"db_path": ":memory:"},
        )
        assert conn is not None
        assert conn.is_connected()
        self.mgr.release_to_pool(conn)

    def test_shutdown(self):
        self.mgr.create_connector("SQLiteConnector", {"db_path": ":memory:"})
        self.mgr.shutdown()
        stats = self.mgr.get_stats()
        assert stats["total_connectors"] == 0

    def test_get_connector_categories(self):
        categories = self.mgr.get_connector_categories()
        assert isinstance(categories, dict)
        assert "database" in categories
