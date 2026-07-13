"""
测试：ConfigManager 配置管理中心
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/workspace/agent_cluster")

import pytest

from config_manager import ConfigManager


@pytest.fixture
def config():
    return ConfigManager()


def test_get_default(config):
    assert config.get("memory.wm_ttl_seconds") == 30.0
    assert config.get("nonexistent.key", "default") == "default"


def test_get_typed(config):
    assert config.get_int("message_bus.max_queue_size") == 10000
    assert config.get_float("memory.wm_ttl_seconds") == 30.0
    assert config.get_bool("plugin_loader.auto_reload") is True
    assert config.get_str("llm.model") == "gpt-4o-mini"
    assert config.get_dict("memory")["stm_max_rounds"] == 20


def test_set_runtime(config):
    config.set("custom.key", "value")
    assert config.get("custom.key") == "value"

    config.set("memory.wm_ttl_seconds", 60.0)
    assert config.get("memory.wm_ttl_seconds") == 60.0


def test_to_dict(config):
    d = config.to_dict()
    assert "message_bus" in d
    assert "memory" in d


def test_export_json(config, tmp_path):
    path = tmp_path / "config.json"
    config.export_to_file(str(path), "json")
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["llm"]["model"] == "gpt-4o-mini"


def test_load_from_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"custom": {"key": "from_file"}}))
    config = ConfigManager(str(path))
    assert config.get("custom.key") == "from_file"


def test_env_substitution(tmp_path):
    os.environ["TEST_YUNXI_KEY"] = "env_value"
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"key": "${TEST_YUNXI_KEY}"}))
    config = ConfigManager(str(path))
    assert config.get("key") == "env_value"
    del os.environ["TEST_YUNXI_KEY"]


def test_env_substitution_with_default(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"key": "${NONEXISTENT_VAR:default_value}"}))
    config = ConfigManager(str(path))
    assert config.get("key") == "default_value"


def test_reload(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"version": 1}))
    config = ConfigManager(str(path))
    assert config.get("version") == 1

    import time
    time.sleep(0.1)
    path.write_text(json.dumps({"version": 2}))
    # 强制修改 mtime 并跳过检查间隔
    config._last_check = 0
    reloaded = config.check_reload()
    assert reloaded is True
    assert config.get("version") == 2
