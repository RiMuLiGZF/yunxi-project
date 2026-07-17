"""
云汐系统 - 可复用测试 Fixtures

提供可在多个测试模块中复用的 fixtures。
这些 fixtures 通过 conftest.py 自动加载，也可直接导入使用。

使用方式（在 conftest.py 或测试文件中）:
    from tests.utils.fixtures import *
    # 或在 conftest.py 中通过 pytest_plugins 导入
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, Generator, List
from datetime import datetime, timedelta

import pytest


# ============================================================
# 临时目录 Fixtures
# ============================================================

@pytest.fixture
def temp_file(tmp_path) -> Path:
    """
    创建一个临时文件，可用于测试文件读写。

    Returns:
        临时文件路径（文件已创建但为空）
    """
    f = tmp_path / "test_file.txt"
    f.write_text("")
    return f


@pytest.fixture
def temp_json_file(tmp_path) -> Path:
    """
    创建一个临时 JSON 文件，包含测试数据。

    Returns:
        临时 JSON 文件路径
    """
    import json
    f = tmp_path / "test_data.json"
    f.write_text(json.dumps({
        "name": "test",
        "version": "1.0",
        "items": [1, 2, 3],
        "nested": {"key": "value"},
    }, ensure_ascii=False, indent=2))
    return f


@pytest.fixture
def temp_config_dir(tmp_path) -> Path:
    """
    创建一个临时配置目录结构。

    目录结构:
        tmp/
        ├── config.yaml
        ├── .env
        └── conf.d/
            └── extra.yaml
    """
    conf_d = tmp_path / "conf.d"
    conf_d.mkdir()

    (tmp_path / "config.yaml").write_text("""
app:
  name: test-app
  version: 1.0.0
server:
  host: 127.0.0.1
  port: 8080
""".strip())

    (tmp_path / ".env").write_text("""
APP_ENV=testing
DEBUG=true
LOG_LEVEL=INFO
""".strip())

    (conf_d / "extra.yaml").write_text("""
extra:
  enabled: true
  value: test
""".strip())

    return tmp_path


# ============================================================
# 数据 Fixtures
# ============================================================

@pytest.fixture
def sample_user_data() -> Dict[str, Any]:
    """示例用户数据。"""
    return {
        "id": 1,
        "username": "testuser",
        "email": "test@example.com",
        "role": "user",
        "is_active": True,
        "created_at": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def sample_module_status_list() -> List[Dict[str, Any]]:
    """示例模块状态列表。"""
    modules = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"]
    return [
        {
            "key": m,
            "name": f"模块{m}",
            "status": "running",
            "cpu_usage": 30 + i * 5,
            "memory_usage": 40 + i * 3,
            "version": f"v1.{i}.0",
        }
        for i, m in enumerate(modules)
    ]


@pytest.fixture
def sample_api_response() -> Dict[str, Any]:
    """示例 API 成功响应。"""
    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
        },
        "request_id": "req-1234567890",
        "timestamp": datetime.now().isoformat(),
    }


# ============================================================
# 环境 Fixtures
# ============================================================

@pytest.fixture
def clean_env(monkeypatch) -> None:
    """
    清理与测试相关的环境变量。

    使用 monkeypatch 确保测试结束后恢复原始环境。
    """
    env_vars_to_clean = [
        "ENV",
        "YUNXI_TEST_MODE",
        "DEBUG",
        "LOG_LEVEL",
    ]
    for var in env_vars_to_clean:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ENV", "testing")
    monkeypatch.setenv("YUNXI_TEST_MODE", "1")


# ============================================================
# 性能测试 Fixtures
# ============================================================

@pytest.fixture
def perf_timer():
    """
    性能计时器 fixture。

    使用示例:
        def test_performance(perf_timer):
            with perf_timer("operation_name"):
                do_something()
            assert perf_timer.elapsed("operation_name") < 1.0
    """

    class PerformanceTimer:
        def __init__(self):
            self._timings: Dict[str, float] = {}

        def measure(self, name: str):
            """返回一个上下文管理器，用于测量代码块执行时间。"""
            import time

            class TimerContext:
                def __init__(self, timer, name):
                    self._timer = timer
                    self._name = name
                    self._start = None
                    self.elapsed = None

                def __enter__(self):
                    self._start = time.perf_counter()
                    return self

                def __exit__(self, *args):
                    self.elapsed = time.perf_counter() - self._start
                    self._timer._timings[self._name] = self.elapsed
                    return False

            return TimerContext(self, name)

        def elapsed(self, name: str) -> float:
            """获取指定测量项的耗时。"""
            return self._timings.get(name, 0.0)

        @property
        def all_timings(self) -> Dict[str, float]:
            """获取所有测量结果。"""
            return dict(self._timings)

        def assert_under(self, name: str, max_seconds: float):
            """断言指定操作耗时不超过阈值。"""
            actual = self.elapsed(name)
            assert actual <= max_seconds, \
                f"'{name}' 耗时 {actual:.4f}s 超过阈值 {max_seconds}s"

    return PerformanceTimer()


# ============================================================
# Mock Fixtures（从 mock_helpers 导入并包装为 fixture）
# ============================================================

@pytest.fixture
def mock_http_response_factory():
    """HTTP 响应 Mock 工厂 fixture。"""
    from tests.utils.mock_helpers import mock_http_response
    return mock_http_response


@pytest.fixture
def mock_httpx_client_factory():
    """httpx 客户端 Mock 工厂 fixture。"""
    from tests.utils.mock_helpers import mock_httpx_client
    return mock_httpx_client


@pytest.fixture
def mock_db_session_factory():
    """数据库会话 Mock 工厂 fixture。"""
    from tests.utils.mock_helpers import mock_db_session
    return mock_db_session


@pytest.fixture
def assert_helper():
    """
    断言辅助工具 fixture。

    提供常用断言方法的便捷访问。
    """
    from tests.utils.assertions import (
        assert_api_success,
        assert_api_error,
        assert_api_pagination,
        assert_has_keys,
        assert_dict_contains,
        assert_list_length,
        assert_is_valid_uuid,
        assert_is_valid_datetime,
        assert_is_valid_email,
        assert_execution_time,
    )

    class AssertHelper:
        """断言辅助类，聚合常用断言方法。"""
        api_success = staticmethod(assert_api_success)
        api_error = staticmethod(assert_api_error)
        api_pagination = staticmethod(assert_api_pagination)
        has_keys = staticmethod(assert_has_keys)
        dict_contains = staticmethod(assert_dict_contains)
        list_length = staticmethod(assert_list_length)
        is_valid_uuid = staticmethod(assert_is_valid_uuid)
        is_valid_datetime = staticmethod(assert_is_valid_datetime)
        is_valid_email = staticmethod(assert_is_valid_email)
        execution_time = staticmethod(assert_execution_time)

    return AssertHelper()
