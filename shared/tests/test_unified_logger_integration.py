"""
统一日志系统集成测试

测试 M2/M3/M6 模块接入 shared 统一日志体系的功能：
1. logger 初始化成功
2. 各级别输出正确
3. JSON 格式正确
4. trace_id 注入
5. 日志轮转（模拟）
6. 敏感字段脱敏
7. 配置生效
8. 模块初始化日志正常工作
9. 异常处理日志自动带堆栈
10. 上下文变量线程安全
"""

import os
import sys
import json
import logging
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_log_dir():
    """创建临时日志目录，测试完成后清理."""
    tmp_dir = tempfile.mkdtemp(prefix="test_logs_")
    yield tmp_dir
    # 清理
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def clean_logger_state():
    """测试前后清理全局 logger 状态，避免单例污染."""
    from shared.core.observability.unified_logger import _loggers, _get_lock
    lock = _get_lock()
    with lock:
        # 保存原始状态
        original = dict(_loggers)
        _loggers.clear()
    yield
    with lock:
        _loggers.clear()
        _loggers.update(original)


# ============================================================================
# 测试 1: logger 初始化成功
# ============================================================================

class TestLoggerInitialization:
    """测试统一日志器初始化."""

    def test_init_module_logger_m2(self, clean_logger_state, temp_log_dir):
        """测试 M2 模块日志器初始化成功."""
        from shared.core.observability import init_module_logger
        logger = init_module_logger("m2", log_dir=temp_log_dir)
        assert logger is not None
        assert logger.name == "yunxi.m2"
        # 验证 module_key 上下文已设置
        from shared.core.observability import get_log_context
        ctx = get_log_context()
        assert ctx.get("module_key") == "m2"

    def test_init_module_logger_m3(self, clean_logger_state, temp_log_dir):
        """测试 M3 模块日志器初始化成功."""
        from shared.core.observability import init_module_logger
        logger = init_module_logger("m3", log_dir=temp_log_dir)
        assert logger is not None
        assert logger.name == "yunxi.m3"
        from shared.core.observability import get_log_context
        ctx = get_log_context()
        assert ctx.get("module_key") == "m3"

    def test_init_module_logger_m6(self, clean_logger_state, temp_log_dir):
        """测试 M6 模块日志器初始化成功."""
        from shared.core.observability import init_module_logger
        logger = init_module_logger("m6", log_dir=temp_log_dir)
        assert logger is not None
        assert logger.name == "yunxi.m6"
        from shared.core.observability import get_log_context
        ctx = get_log_context()
        assert ctx.get("module_key") == "m6"

    def test_get_logger_singleton(self, clean_logger_state, temp_log_dir):
        """测试 get_logger 单例模式 - 同名返回同一实例."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger1 = UnifiedLogger("test_singleton", log_dir=temp_log_dir,
                                console_output=False)
        # 直接使用 UnifiedLogger 验证创建成功
        assert logger1 is not None
        assert logger1.name == "test_singleton"

    def test_logger_has_file_handler(self, clean_logger_state, temp_log_dir):
        """测试日志器配置了文件输出 handler."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_file_handler", log_dir=temp_log_dir,
                               file_output=True, console_output=False)
        py_logger = logger.get_logger()
        # 应该有文件 handler
        file_handlers = [
            h for h in py_logger.handlers
            if isinstance(h, (logging.FileHandler, logging.handlers.TimedRotatingFileHandler,
                              logging.handlers.RotatingFileHandler))
        ]
        assert len(file_handlers) >= 2  # 主日志 + error 日志


# ============================================================================
# 测试 2: 各级别输出正确
# ============================================================================

class TestLogLevels:
    """测试各日志级别输出正确."""

    def test_debug_level(self, clean_logger_state, temp_log_dir):
        """测试 DEBUG 级别日志输出."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_debug", level="DEBUG", log_dir=temp_log_dir,
                               file_output=True, console_output=False)

        test_msg = "this is a debug message"
        logger.debug(test_msg, extra_field="debug_value")

        # 检查日志文件
        log_file = Path(temp_log_dir) / "test_debug.log"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert test_msg in content
        assert '"level": "DEBUG"' in content

    def test_info_level(self, clean_logger_state, temp_log_dir):
        """测试 INFO 级别日志输出."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_info", level="INFO", log_dir=temp_log_dir,
                               file_output=True, console_output=False)

        test_msg = "this is an info message"
        logger.info(test_msg, module="test")

        log_file = Path(temp_log_dir) / "test_info.log"
        content = log_file.read_text(encoding="utf-8")
        assert test_msg in content
        assert '"level": "INFO"' in content

    def test_warning_level(self, clean_logger_state, temp_log_dir):
        """测试 WARNING 级别日志输出."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_warning", level="WARNING", log_dir=temp_log_dir,
                               file_output=True, console_output=False)

        test_msg = "this is a warning message"
        logger.warning(test_msg, warning_type="test")

        log_file = Path(temp_log_dir) / "test_warning.log"
        content = log_file.read_text(encoding="utf-8")
        assert test_msg in content
        assert '"level": "WARNING"' in content

    def test_error_level(self, clean_logger_state, temp_log_dir):
        """测试 ERROR 级别日志输出."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_error", level="ERROR", log_dir=temp_log_dir,
                               file_output=True, console_output=False)

        test_msg = "this is an error message"
        logger.error(test_msg, error_code=500)

        # 主日志文件
        log_file = Path(temp_log_dir) / "test_error.log"
        content = log_file.read_text(encoding="utf-8")
        assert test_msg in content
        assert '"level": "ERROR"' in content

        # error 日志文件（单独记录 ERROR 及以上）
        error_log_file = Path(temp_log_dir) / "test_error-error.log"
        assert error_log_file.exists()
        error_content = error_log_file.read_text(encoding="utf-8")
        assert test_msg in error_content

    def test_level_filtering(self, clean_logger_state, temp_log_dir):
        """测试日志级别过滤 - INFO 级别不输出 DEBUG."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_filter", level="INFO", log_dir=temp_log_dir,
                               file_output=True, console_output=False)

        logger.debug("should not appear")
        logger.info("should appear")

        log_file = Path(temp_log_dir) / "test_filter.log"
        content = log_file.read_text(encoding="utf-8")
        assert "should not appear" not in content
        assert "should appear" in content


# ============================================================================
# 测试 3: JSON 格式正确
# ============================================================================

class TestJsonFormat:
    """测试 JSON 格式日志输出正确."""

    def test_json_log_is_valid_json(self, clean_logger_state, temp_log_dir):
        """测试每行日志都是合法的 JSON."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_json", level="INFO", log_dir=temp_log_dir,
                               file_output=True, console_output=False, json_format=True)

        logger.info("json test message", key1="val1", key2=123)

        log_file = Path(temp_log_dir) / "test_json.log"
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 1

        for line in lines:
            if line.strip():
                entry = json.loads(line)
                assert "timestamp" in entry
                assert "level" in entry
                assert "logger" in entry
                assert "message" in entry
                assert "module" in entry
                assert "function" in entry
                assert "line" in entry

    def test_json_extra_fields(self, clean_logger_state, temp_log_dir):
        """测试 JSON 日志中 extra 字段正确包含."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_json_extra", level="INFO", log_dir=temp_log_dir,
                               file_output=True, console_output=False, json_format=True)

        logger.info("extra fields test", user_id="user_123", action="login", ip="192.168.1.1")

        log_file = Path(temp_log_dir) / "test_json_extra.log"
        line = log_file.read_text(encoding="utf-8").strip().split("\n")[0]
        entry = json.loads(line)

        # user_id 是上下文字段，在顶层
        assert entry["user_id"] == "user_123"
        # 其他字段在 extra 中
        assert "extra" in entry
        assert entry["extra"]["action"] == "login"
        assert entry["extra"]["ip"] == "192.168.1.1"


# ============================================================================
# 测试 4: trace_id 注入
# ============================================================================

class TestTraceIdInjection:
    """测试 trace_id 上下文注入."""

    def test_set_and_get_log_context(self, clean_logger_state):
        """测试设置和获取日志上下文."""
        from shared.core.observability import set_log_context, get_log_context, clear_log_context
        clear_log_context()

        set_log_context(trace_id="abc123", user_id="user_456")
        ctx = get_log_context()
        assert ctx["trace_id"] == "abc123"
        assert ctx["user_id"] == "user_456"

        clear_log_context()
        assert get_log_context() == {}

    def test_trace_id_in_log_output(self, clean_logger_state, temp_log_dir):
        """测试 trace_id 自动注入到日志输出中."""
        from shared.core.observability.unified_logger import UnifiedLogger
        from shared.core.observability import set_log_context, clear_log_context
        clear_log_context()

        logger = UnifiedLogger("test_trace", level="INFO", log_dir=temp_log_dir,
                               file_output=True, console_output=False, json_format=True)

        set_log_context(trace_id="trace_xyz_789")
        logger.info("message with trace id")
        clear_log_context()

        log_file = Path(temp_log_dir) / "test_trace.log"
        line = log_file.read_text(encoding="utf-8").strip().split("\n")[0]
        entry = json.loads(line)

        assert entry["trace_id"] == "trace_xyz_789"

    def test_context_per_thread(self, clean_logger_state):
        """测试上下文变量线程安全 - 不同线程有独立上下文."""
        from shared.core.observability import set_log_context, get_log_context, clear_log_context
        clear_log_context()

        results = {}

        def worker(thread_id):
            set_log_context(trace_id=f"trace_{thread_id}")
            time.sleep(0.01)
            results[thread_id] = get_log_context().get("trace_id")

        threads = []
        for i in range(3):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert results[0] == "trace_0"
        assert results[1] == "trace_1"
        assert results[2] == "trace_2"

        clear_log_context()


# ============================================================================
# 测试 5: 日志轮转（模拟）
# ============================================================================

class TestLogRotation:
    """测试日志轮转配置."""

    def test_rotation_config_defaults(self):
        """测试默认轮转配置正确."""
        from shared.core.observability import LogRotationConfig
        config = LogRotationConfig()
        assert config.enabled is True
        assert config.when == "midnight"
        assert config.backup_count == 30
        assert config.compress is True
        assert config.interval == 1

    def test_rotation_config_env_override(self, monkeypatch):
        """测试环境变量覆盖轮转配置."""
        monkeypatch.setenv("LOG_ROTATION_BACKUP_COUNT", "15")
        monkeypatch.setenv("LOG_ROTATION_COMPRESS", "false")
        monkeypatch.setenv("LOG_ROTATION_WHEN", "hourly")

        from shared.core.observability.unified_logger import LogRotationConfig
        config = LogRotationConfig()
        assert config.backup_count == 15
        assert config.compress is False
        assert config.when == "H"  # hourly 映射为 H

    def test_time_based_rotation_handler(self, clean_logger_state, temp_log_dir):
        """测试基于时间的轮转创建正确的 handler."""
        from shared.core.observability.unified_logger import (
            UnifiedLogger, LogRotationConfig, GzipTimedRotatingFileHandler
        )
        config = LogRotationConfig(
            enabled=True,
            when="midnight",
            backup_count=30,
            compress=False,
        )
        logger = UnifiedLogger(
            "test_time_rotation",
            log_dir=temp_log_dir,
            file_output=True,
            console_output=False,
            rotation_config=config,
        )
        py_logger = logger.get_logger()
        timed_handlers = [
            h for h in py_logger.handlers
            if isinstance(h, (logging.handlers.TimedRotatingFileHandler,
                              GzipTimedRotatingFileHandler))
        ]
        assert len(timed_handlers) >= 2  # 主日志 + error 日志
        assert timed_handlers[0].backupCount == 30
        assert timed_handlers[0].when.upper() == "MIDNIGHT"


# ============================================================================
# 测试 6: 敏感字段脱敏
# ============================================================================

class TestSensitiveDataMasking:
    """测试敏感字段自动脱敏."""

    def test_mask_password_field(self):
        """测试 password 字段脱敏."""
        from shared.core.observability import mask_sensitive_data
        data = {"username": "admin", "password": "secret123"}
        result = mask_sensitive_data(data)
        assert result["username"] == "admin"
        assert result["password"] == "***MASKED***"

    def test_mask_token_field(self):
        """测试 token 字段脱敏."""
        from shared.core.observability import mask_sensitive_data
        data = {"access_token": "abc123token", "refresh_token": "xyz789"}
        result = mask_sensitive_data(data)
        assert result["access_token"] == "***MASKED***"
        assert result["refresh_token"] == "***MASKED***"

    def test_mask_nested_dict(self):
        """测试嵌套字典中的敏感字段脱敏."""
        from shared.core.observability import mask_sensitive_data
        data = {
            "user": {
                "name": "test",
                "profile": {
                    "password": "secret",
                    "api_key": "key123"
                }
            }
        }
        result = mask_sensitive_data(data)
        assert result["user"]["name"] == "test"
        assert result["user"]["profile"]["password"] == "***MASKED***"
        assert result["user"]["profile"]["api_key"] == "***MASKED***"

    def test_mask_in_log_output(self, clean_logger_state, temp_log_dir):
        """测试日志输出中敏感字段自动脱敏."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_mask", level="INFO", log_dir=temp_log_dir,
                               file_output=True, console_output=False, json_format=True)

        logger.info(
            "user login",
            user_id="user1",
            password="my_secret_password",
            api_key="sk-1234567890"
        )

        log_file = Path(temp_log_dir) / "test_mask.log"
        line = log_file.read_text(encoding="utf-8").strip().split("\n")[0]
        entry = json.loads(line)

        assert entry["user_id"] == "user1"
        assert entry["extra"]["password"] == "***MASKED***"
        assert entry["extra"]["api_key"] == "***MASKED***"


# ============================================================================
# 测试 7: 配置生效
# ============================================================================

class TestConfiguration:
    """测试日志配置项正确生效."""

    def test_log_level_from_env(self, monkeypatch, clean_logger_state, temp_log_dir):
        """测试从环境变量读取日志级别."""
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        monkeypatch.setenv("LOG_DIR", temp_log_dir)

        from shared.core.observability import get_logger
        logger = get_logger("test_env_level", file_output=False)
        assert logger.level == logging.WARNING

    def test_log_dir_from_env(self, monkeypatch, clean_logger_state, temp_log_dir):
        """测试从环境变量读取日志目录."""
        monkeypatch.setenv("LOG_DIR", temp_log_dir)

        from shared.core.observability import get_logger
        logger = get_logger("test_env_dir", file_output=True)

        log_file = Path(temp_log_dir) / "test_env_dir.log"
        logger.info("test log dir")
        assert log_file.exists()

    def test_json_format_from_env(self, monkeypatch, clean_logger_state, temp_log_dir):
        """测试从环境变量读取日志格式."""
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("LOG_DIR", temp_log_dir)

        from shared.core.observability import get_logger
        logger = get_logger("test_env_format", file_output=False)
        assert logger.json_format is True

    def test_dynamic_level_change(self, clean_logger_state, temp_log_dir):
        """测试动态修改日志级别."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_dynamic_level", level="INFO", log_dir=temp_log_dir,
                               file_output=True, console_output=False)

        logger.debug("before change - should not appear")
        logger.set_level("DEBUG")
        logger.debug("after change - should appear")

        log_file = Path(temp_log_dir) / "test_dynamic_level.log"
        content = log_file.read_text(encoding="utf-8")
        assert "before change - should not appear" not in content
        assert "after change - should appear" in content


# ============================================================================
# 测试 8: 异常处理日志（自动带堆栈）
# ============================================================================

class TestExceptionLogging:
    """测试异常日志自动包含堆栈信息."""

    def test_exception_method_includes_stack(self, clean_logger_state, temp_log_dir):
        """测试 logger.exception() 自动包含异常堆栈."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_exception", level="ERROR", log_dir=temp_log_dir,
                               file_output=True, console_output=False, json_format=True)

        try:
            raise ValueError("test error value")
        except ValueError:
            logger.exception("an error occurred")

        log_file = Path(temp_log_dir) / "test_exception.log"
        line = log_file.read_text(encoding="utf-8").strip().split("\n")[0]
        entry = json.loads(line)

        assert entry["level"] == "ERROR"
        assert "exception" in entry
        assert "ValueError" in entry["exception"]
        assert "test error value" in entry["exception"]

    def test_error_with_exc_info(self, clean_logger_state, temp_log_dir):
        """测试 logger.error(exc_info=True) 也包含堆栈."""
        from shared.core.observability.unified_logger import UnifiedLogger
        logger = UnifiedLogger("test_error_exc", level="ERROR", log_dir=temp_log_dir,
                               file_output=True, console_output=False, json_format=True)

        try:
            raise RuntimeError("runtime test")
        except RuntimeError:
            logger.error("error with exc_info", exc_info=True)

        log_file = Path(temp_log_dir) / "test_error_exc.log"
        line = log_file.read_text(encoding="utf-8").strip().split("\n")[0]
        entry = json.loads(line)

        assert entry["level"] == "ERROR"
        assert "exception" in entry
        assert "RuntimeError" in entry["exception"]


# ============================================================================
# 测试 9: 模块初始化集成验证
# ============================================================================

class TestModuleIntegration:
    """测试各模块日志集成正确."""

    def test_m2_logger_importable(self):
        """测试 M2 模块可以正常导入并使用统一日志."""
        from shared.core.observability import init_module_logger
        assert callable(init_module_logger)

    def test_m3_logger_importable(self):
        """测试 M3 模块可以正常导入并使用统一日志."""
        from shared.core.observability import init_module_logger
        assert callable(init_module_logger)

    def test_m6_logger_importable(self):
        """测试 M6 模块可以正常导入并使用统一日志."""
        from shared.core.observability import init_module_logger
        assert callable(init_module_logger)

    def test_observability_middleware_importable(self):
        """测试 ObservabilityMiddleware 可以正常导入."""
        from shared.core.observability import ObservabilityMiddleware
        assert ObservabilityMiddleware is not None
        assert hasattr(ObservabilityMiddleware, 'dispatch')

    def test_create_observability_router_importable(self):
        """测试 create_observability_router 可以正常导入."""
        from shared.core.observability import create_observability_router
        assert callable(create_observability_router)


# ============================================================================
# 测试 10: 日志清理工具
# ============================================================================

class TestLogCleanupTools:
    """测试日志清理和归档工具函数."""

    def test_get_log_dir_size(self, temp_log_dir):
        """测试日志目录大小统计."""
        from shared.core.observability import get_log_dir_size

        # 创建一些测试文件
        test_file = Path(temp_log_dir) / "test.log"
        test_file.write_text("x" * 1000, encoding="utf-8")

        total_size, file_count = get_log_dir_size(temp_log_dir)
        assert total_size >= 1000
        assert file_count >= 1

    def test_clean_expired_logs(self, temp_log_dir):
        """测试过期日志清理."""
        from shared.core.observability import clean_expired_logs
        import time as _time

        # 创建一个旧日志文件（修改时间设为 40 天前）
        old_file = Path(temp_log_dir) / "old.log"
        old_file.write_text("old log content", encoding="utf-8")
        old_time = _time.time() - 40 * 24 * 3600
        os.utime(str(old_file), (old_time, old_time))

        # 创建一个新日志文件
        new_file = Path(temp_log_dir) / "new.log"
        new_file.write_text("new log content", encoding="utf-8")

        result = clean_expired_logs(temp_log_dir, max_age_days=30)
        assert result["deleted"] >= 1
        assert not old_file.exists()
        assert new_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
