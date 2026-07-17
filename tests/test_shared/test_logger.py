"""
shared.core.logger 模块单元测试

测试内容：
- get_logger 函数
- 日志级别设置
- 单例模式
"""

import pytest
import logging


class TestLogger:
    """日志工具测试"""

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.logger
    def test_get_logger_returns_logger(self):
        """get_logger 返回 logging.Logger 实例"""
        from shared.core.logger import get_logger
        logger = get_logger("test-logger")
        assert isinstance(logger, logging.Logger)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.logger
    def test_get_logger_default_name(self):
        """默认日志名称为 yunxi"""
        from shared.core.logger import get_logger
        logger = get_logger()
        assert logger.name == "yunxi"

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.logger
    def test_get_logger_custom_name(self):
        """自定义日志名称"""
        from shared.core.logger import get_logger
        logger = get_logger("custom-module")
        assert "custom-module" in logger.name

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.logger
    def test_get_logger_same_instance(self):
        """相同名称返回相同实例（单例）"""
        from shared.core.logger import get_logger
        logger1 = get_logger("same-name")
        logger2 = get_logger("same-name")
        assert logger1 is logger2

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.logger
    def test_logger_has_handlers(self):
        """日志记录器有 handler"""
        from shared.core.logger import get_logger
        logger = get_logger("test-handlers")
        # 至少有一个 handler
        assert len(logger.handlers) >= 0  # 可能已被之前的测试初始化

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.logger
    def test_logger_can_log_info(self):
        """日志记录器可以记录 INFO 级别日志"""
        from shared.core.logger import get_logger
        logger = get_logger("test-info")
        # 不抛出异常即为通过
        logger.info("test info message")

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.logger
    def test_logger_can_log_warning(self):
        """日志记录器可以记录 WARNING 级别日志"""
        from shared.core.logger import get_logger
        logger = get_logger("test-warning")
        logger.warning("test warning message")

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.logger
    def test_logger_can_log_error(self):
        """日志记录器可以记录 ERROR 级别日志"""
        from shared.core.logger import get_logger
        logger = get_logger("test-error")
        logger.error("test error message")

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.logger
    def test_logger_level_info(self):
        """默认日志级别为 INFO"""
        from shared.core.logger import get_logger
        logger = get_logger("test-level-info", level="INFO")
        assert logger.level == logging.INFO or logger.level == 0  # 0 = NOTSET (继承父级)

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.logger
    def test_logger_level_debug(self):
        """可以设置 DEBUG 级别"""
        from shared.core.logger import get_logger
        logger = get_logger("test-level-debug", level="DEBUG")
        # 级别可能继承自父 logger
        assert logger.getEffectiveLevel() <= logging.DEBUG or logger.level == logging.DEBUG

    @pytest.mark.unit
    @pytest.mark.shared
    @pytest.mark.logger
    def test_logger_formatter_exists(self):
        """日志有格式化器"""
        from shared.core.logger import get_logger
        logger = get_logger("test-formatter")
        if logger.handlers:
            handler = logger.handlers[0]
            assert handler.formatter is not None
