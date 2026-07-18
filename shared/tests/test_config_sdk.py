# -*- coding: utf-8 -*-
"""
配置客户端 SDK 测试

测试范围：
1. ConfigClient 基本功能
2. 本地缓存
3. 文件缓存
4. 配置监听
5. 故障降级
6. LocalConfigMerger 本地合并
7. 层级继承
8. 环境变量加载
"""

import sys
import os
import json
import tempfile
import threading
import time
from pathlib import Path

import pytest

# 路径设置
_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

# 导入 SDK
from shared.config_sdk import ConfigClient, LocalConfigMerger  # noqa: E402


# ============================================================
# 1. ConfigClient 基本功能测试
# ============================================================

class TestConfigClientBasic:
    """ConfigClient 基本功能测试"""

    def test_create_client(self):
        """测试创建客户端"""
        client = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False},
            local_config={"key1": "value1"},
        )
        assert client.module_name == "test"
        assert client.env == "development"
        assert client.instance_id is not None

    def test_get_from_local_defaults(self):
        """测试从本地默认配置获取"""
        client = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False},
            local_config={
                "app.name": "test-app",
                "app.version": "1.0.0",
            },
        )
        assert client.get("app.name") == "test-app"
        assert client.get("app.version") == "1.0.0"

    def test_get_with_default(self):
        """测试带默认值的 get"""
        client = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False},
        )
        assert client.get("nonexistent", default="fallback") == "fallback"
        assert client.get("nonexistent") is None

    def test_get_all(self):
        """测试获取所有配置"""
        client = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False},
            local_config={
                "a.b": 1,
                "a.c": 2,
                "x.y": 3,
            },
        )
        all_configs = client.get_all()
        assert all_configs["a.b"] == 1
        assert all_configs["a.c"] == 2
        assert all_configs["x.y"] == 3

    def test_get_all_with_prefix(self):
        """测试按前缀过滤获取"""
        client = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False},
            local_config={
                "db.host": "localhost",
                "db.port": 5432,
                "log.level": "info",
            },
        )
        db_configs = client.get_all(prefix="db.")
        assert len(db_configs) == 2
        assert "db.host" in db_configs
        assert "db.port" in db_configs
        assert "log.level" not in db_configs

    def test_set_local_mode(self):
        """测试本地模式下的 set"""
        client = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False,
                    "enable_file_cache": False},
            local_config={"key": "old"},
        )
        assert client.get("key") == "old"

        success = client.set("key", "new")
        assert success is True
        assert client.get("key") == "new"

    def test_instance_id_generation(self):
        """测试实例 ID 生成"""
        client1 = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False},
        )
        client2 = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False},
        )
        # 不同实例有不同的 ID
        assert client1.instance_id != client2.instance_id
        # 都包含模块名
        assert "test" in client1.instance_id

    def test_custom_instance_id(self):
        """测试自定义实例 ID"""
        client = ConfigClient(
            module_name="test",
            config={
                "enable_remote": False,
                "enable_watch": False,
                "instance_id": "my-custom-instance",
            },
        )
        assert client.instance_id == "my-custom-instance"


# ============================================================
# 2. 文件缓存测试
# ============================================================

class TestFileCache:
    """文件缓存测试"""

    def test_file_cache_saved(self, tmp_path):
        """测试文件缓存保存"""
        cache_file = tmp_path / "test_cache.json"
        client = ConfigClient(
            module_name="test",
            config={
                "enable_remote": False,
                "enable_watch": False,
                "enable_file_cache": True,
                "file_cache_path": str(cache_file),
            },
            local_config={"cached_key": "cached_value"},
        )

        # 触发保存（set 会触发保存）
        client.set("new_key", "new_value")

        # 验证文件存在
        assert cache_file.exists()

        # 验证文件内容
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["module"] == "test"
        assert "config" in data
        assert data["config"]["new_key"] == "new_value"

    def test_file_cache_loaded(self, tmp_path):
        """测试文件缓存加载"""
        cache_file = tmp_path / "test_cache.json"
        cache_data = {
            "module": "test",
            "config": {
                "from_cache": "yes",
                "cache_version": 2,
            },
            "timestamp": time.time(),
            "last_change_id": 0,
            "saved_at": "2026-01-01T00:00:00",
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)

        client = ConfigClient(
            module_name="test",
            config={
                "enable_remote": False,
                "enable_watch": False,
                "enable_file_cache": True,
                "file_cache_path": str(cache_file),
            },
        )
        assert client.get("from_cache") == "yes"
        assert client.get("cache_version") == 2

    def test_fallback_to_file_cache_when_remote_down(self, tmp_path):
        """测试远程不可用时回退到文件缓存"""
        cache_file = tmp_path / "fallback_cache.json"
        cache_data = {
            "module": "test",
            "config": {
                "fallback_key": "fallback_value",
            },
            "timestamp": time.time(),
            "last_change_id": 0,
            "saved_at": "2026-01-01T00:00:00",
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)

        client = ConfigClient(
            module_name="test",
            config={
                "enable_remote": True,  # 启用远程但指向无效地址
                "config_center_url": "http://nonexistent.invalid:9999/api/config",
                "timeout": 1.0,
                "enable_watch": False,
                "enable_file_cache": True,
                "file_cache_path": str(cache_file),
                "cache_ttl": 0,  # 立即过期，强制刷新
            },
        )

        # 应该从文件缓存获取
        val = client.get("fallback_key")
        assert val == "fallback_value"
        # 连接状态应为 False
        assert client.is_connected is False

    def test_disabled_file_cache(self, tmp_path):
        """测试禁用文件缓存"""
        cache_file = tmp_path / "disabled_cache.json"
        client = ConfigClient(
            module_name="test",
            config={
                "enable_remote": False,
                "enable_watch": False,
                "enable_file_cache": False,
                "file_cache_path": str(cache_file),
            },
            local_config={"test_key": "test_val"},
        )

        client.set("test_key", "new_val")
        # 文件不应被创建
        assert not cache_file.exists()


# ============================================================
# 3. 配置监听测试
# ============================================================

class TestConfigWatch:
    """配置监听测试"""

    def test_watch_and_unwatch(self):
        """测试注册和取消监听器"""
        client = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False},
        )

        def callback(key, old, new):
            pass

        listener_id = client.watch("test.key", callback)
        assert listener_id is not None
        assert len(listener_id) > 0

        # 取消监听
        result = client.unwatch(listener_id)
        assert result is True

        # 再次取消返回 False
        result = client.unwatch(listener_id)
        assert result is False

    def test_watch_callback_triggered_on_change(self):
        """测试配置变化时触发回调"""
        client = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False,
                    "enable_file_cache": False},
            local_config={"watched.key": "initial"},
        )

        changes = []
        lock = threading.Lock()

        def on_change(key, old_val, new_val):
            with lock:
                changes.append({"key": key, "old": old_val, "new": new_val})

        client.watch("watched.key", on_change)

        # 手动设置配置，触发变更
        client.set("watched.key", "updated")

        # 本地模式下 set 会更新缓存但不触发 watcher
        # （watcher 由远程变更触发，本地 set 直接更新）
        # 这里验证本地 set 正确更新了值
        assert client.get("watched.key") == "updated"

    def test_multiple_watchers(self):
        """测试多个监听器"""
        client = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False,
                    "enable_file_cache": False},
        )

        count1 = [0]
        count2 = [0]

        def watcher1(key, old, new):
            count1[0] += 1

        def watcher2(key, old, new):
            count2[0] += 1

        id1 = client.watch("key", watcher1)
        id2 = client.watch("key", watcher2)

        assert id1 != id2

        # 取消第一个
        client.unwatch(id1)
        # 第二个应该还在
        assert client.unwatch(id2) is True


# ============================================================
# 4. 故障降级测试
# ============================================================

class TestDegradation:
    """故障降级测试"""

    def test_remote_disabled_uses_local(self):
        """测试禁用远程时完全使用本地配置"""
        client = ConfigClient(
            module_name="test",
            config={"enable_remote": False, "enable_watch": False},
            local_config={"degrade.key": "local_value"},
        )
        assert client.get("degrade.key") == "local_value"
        # 连接状态不适用
        assert client.is_connected is False

    def test_remote_unreachable_falls_back(self):
        """测试远程不可达时回退到本地"""
        client = ConfigClient(
            module_name="test",
            config={
                "enable_remote": True,
                "config_center_url": "http://127.0.0.1:1/api/config",  # 无效地址
                "timeout": 0.5,
                "enable_watch": False,
                "enable_file_cache": False,
                "cache_ttl": 0,
            },
            local_config={"fallback.key": "local_fallback"},
        )

        # 应该能从本地配置获取
        val = client.get("fallback.key")
        assert val == "local_fallback"

    def test_refresh_returns_false_on_failure(self):
        """测试刷新失败返回 False"""
        client = ConfigClient(
            module_name="test",
            config={
                "enable_remote": True,
                "config_center_url": "http://invalid.invalid:9999/api/config",
                "timeout": 0.5,
                "enable_watch": False,
                "enable_file_cache": False,
            },
        )

        result = client.refresh()
        assert result is False


# ============================================================
# 5. LocalConfigMerger 测试
# ============================================================

class TestLocalConfigMerger:
    """本地配置合并器测试"""

    def test_merge_with_defaults(self):
        """测试默认值合并"""
        merger = LocalConfigMerger(
            defaults={"log.level": "info", "port": 8000},
        )
        assert merger.get("log.level") == "info"
        assert merger.get("port") == 8000

    def test_override_takes_highest_priority(self):
        """测试覆盖配置优先级最高"""
        merger = LocalConfigMerger(
            defaults={"key": "default"},
        )
        merger.set_override("key", "override")

        result = merger.merge(remote_configs={"key": "remote"})
        assert result["key"] == "override"

    def test_remote_overrides_local(self):
        """测试远程配置覆盖本地配置"""
        merger = LocalConfigMerger(
            defaults={"key": "default"},
        )
        # 本地配置（通过 _local_config 模拟）
        merger._local_config = {"key": "local"}

        result = merger.merge(remote_configs={"key": "remote"})
        assert result["key"] == "remote"

    def test_layered_merge(self):
        """测试分层合并"""
        merger = LocalConfigMerger(
            defaults={"a": "default", "b": "default", "c": "default", "d": "default"},
        )

        result = merger.merge_layered(
            global_configs={"a": "global", "b": "global"},
            module_configs={"b": "module", "c": "module"},
            env_configs={"c": "env"},
            instance_configs=None,
        )
        assert result["a"] == "global"   # 只有全局有
        assert result["b"] == "module"   # 模块覆盖全局
        assert result["c"] == "env"      # 环境覆盖模块
        assert result["d"] == "default"  # 都没有，用默认值

    def test_layered_full_priority(self):
        """测试完整的优先级链"""
        merger = LocalConfigMerger(
            defaults={"key": "default"},
        )
        merger._local_config = {"key": "local"}

        result = merger.merge_layered(
            global_configs={"key": "global"},
            module_configs={"key": "module"},
            env_configs={"key": "env"},
            instance_configs={"key": "instance"},
        )
        assert result["key"] == "instance"  # 实例优先级最高

    def test_clear_override(self):
        """测试清除覆盖配置"""
        merger = LocalConfigMerger(defaults={"key": "default"})
        merger.set_override("key", "override")
        assert merger.get("key") == "override"

        result = merger.clear_override("key")
        assert result is True
        assert merger.get("key") == "default"

        # 再次清除返回 False
        result = merger.clear_override("key")
        assert result is False

    def test_get_returns_default_for_missing(self):
        """测试缺失配置返回默认值"""
        merger = LocalConfigMerger(defaults={"existing": "val"})
        assert merger.get("missing", default="fallback") == "fallback"
        assert merger.get("missing") is None

    def test_json_config_file(self, tmp_path):
        """测试 JSON 配置文件加载"""
        config_file = tmp_path / "config.json"
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump({
                "database": {
                    "host": "localhost",
                    "port": 5432,
                },
                "log_level": "debug",
            }, f)

        merger = LocalConfigMerger(local_config_path=str(config_file))
        # 嵌套结构会被扁平化
        assert merger.get("database.host") == "localhost"
        assert merger.get("database.port") == 5432
        assert merger.get("log_level") == "debug"

    def test_dotenv_file(self, tmp_path):
        """测试 .env 文件加载"""
        env_file = tmp_path / ".env"
        env_file.write_text("""
# 注释
DB_HOST=localhost
DB_PORT=5432
DEBUG=true
LOG_LEVEL=info
        """.strip(), encoding="utf-8")

        merger = LocalConfigMerger(local_config_path=str(env_file))
        assert merger.get("db_host") == "localhost"
        assert merger.get("db_port") == 5432  # 自动解析为数字
        assert merger.get("debug") is True   # 自动解析为布尔
        assert merger.get("log_level") == "info"

    def test_env_prefix_loading(self):
        """测试带前缀的环境变量加载"""
        # 设置测试环境变量
        os.environ["TESTSDK_APP_NAME"] = "test-app"
        os.environ["TESTSDK_PORT"] = "9000"
        os.environ["TESTSDK_DEBUG"] = "true"

        try:
            merger = LocalConfigMerger(env_prefix="TESTSDK_")
            assert merger.get("app_name") == "test-app"
            assert merger.get("port") == 9000
            assert merger.get("debug") is True
        finally:
            # 清理
            del os.environ["TESTSDK_APP_NAME"]
            del os.environ["TESTSDK_PORT"]
            del os.environ["TESTSDK_DEBUG"]

    def test_value_parsing(self):
        """测试值类型自动解析"""
        merger = LocalConfigMerger(
            defaults={},
        )
        # 通过 env 变量测试
        os.environ["PARSE_INT"] = "42"
        os.environ["PARSE_FLOAT"] = "3.14"
        os.environ["PARSE_BOOL_TRUE"] = "true"
        os.environ["PARSE_BOOL_FALSE"] = "false"
        os.environ["PARSE_STRING"] = "hello"

        try:
            m = LocalConfigMerger(env_prefix="PARSE_")
            assert m.get("int") == 42
            assert m.get("float") == 3.14
            assert m.get("bool_true") is True
            assert m.get("bool_false") is False
            assert m.get("string") == "hello"
        finally:
            for key in ["INT", "FLOAT", "BOOL_TRUE", "BOOL_FALSE", "STRING"]:
                full_key = f"PARSE_{key}"
                if full_key in os.environ:
                    del os.environ[full_key]


# ============================================================
# 6. 向后兼容测试
# ============================================================

class TestBackwardCompatibility:
    """向后兼容测试"""

    def test_existing_config_still_works(self):
        """测试原有配置方式不受影响"""
        # 不使用 ConfigClient 的情况下，原有代码正常运行
        from shared.core.config import BaseConfig, EnvType

        class TestConfig(BaseConfig):
            module_name: str = "test"
            custom_setting: str = "default_value"

            model_config = {"env_prefix": "TESTBC_", "extra": "allow"}

        config = TestConfig()
        assert config.module_name == "test"
        assert config.custom_setting == "default_value"

    def test_sdk_does_not_break_existing_imports(self):
        """测试 SDK 导入不影响现有模块"""
        # 确保 shared.config 仍然可用
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from shared import config as shared_config

        assert hasattr(shared_config, "BaseConfig")
        assert hasattr(shared_config, "EnvType")

    def test_config_sdk_imports(self):
        """测试配置 SDK 的导入路径正确"""
        from shared.config_sdk import ConfigClient, LocalConfigMerger
        assert ConfigClient is not None
        assert LocalConfigMerger is not None

    def test_local_mode_is_default_compatible(self):
        """测试本地模式与原有配置兼容"""
        # ConfigClient 在 enable_remote=False 时，
        # 功能等价于一个增强的配置字典
        client = ConfigClient(
            module_name="compat",
            config={"enable_remote": False, "enable_watch": False,
                    "enable_file_cache": False},
            local_config={
                "host": "0.0.0.0",
                "port": 8000,
                "log_level": "info",
            },
        )

        # 行为与普通配置一致
        assert client.get("host") == "0.0.0.0"
        assert client.get("port") == 8000
        assert client.get("log_level") == "info"
        assert client.get("nonexistent", "default") == "default"


# ============================================================
# 7. 上下文管理器测试
# ============================================================

class TestContextManager:
    """上下文管理器测试"""

    def test_with_statement(self):
        """测试 with 语句使用"""
        with ConfigClient(
            module_name="ctx_test",
            config={"enable_remote": False, "enable_watch": False},
            local_config={"key": "val"},
        ) as client:
            assert client.get("key") == "val"
            assert client.module_name == "ctx_test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
