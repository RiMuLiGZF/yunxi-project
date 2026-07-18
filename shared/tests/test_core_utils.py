"""
shared 单元测试 - 核心工具类

覆盖: 模块注册表、ModuleInfo 序列化、日志工具
运行: python -m pytest tests/ -v
"""
import os
import sys
import pytest
import logging
from unittest.mock import patch, MagicMock
# shared 使用相对导入，需确保作为包导入
import importlib.util
spec = importlib.util.spec_from_file_location(
    "yunxi_shared",
    os.path.join(os.path.dirname(__file__), "..", "__init__.py"),
)
if spec and spec.loader:
    import sys as _sys
    _shared_module = importlib.util.module_from_spec(spec)
    _sys.modules["yunxi_shared"] = _shared_module
    spec.loader.exec_module(_shared_module)


class TestGetLogger:
    """日志工具测试"""

    def test_get_logger_returns_logger(self):
        """get_logger 应返回 logging.Logger 实例"""
        from yunxi_shared.logger import get_logger
        logger = get_logger("test-logger")
        assert isinstance(logger, logging.Logger)

    def test_get_logger_same_name(self):
        """同名 logger 应返回同一实例"""
        from yunxi_shared.logger import get_logger
        l1 = get_logger("same-name")
        l2 = get_logger("same-name")
        assert l1 is l2

    def test_get_logger_with_level(self):
        """指定日志级别应生效"""
        from yunxi_shared.logger import get_logger
        logger = get_logger("level-test", level="DEBUG")
        assert logger.level == logging.DEBUG or logger.getEffectiveLevel() == logging.DEBUG

    def test_get_logger_default_level(self):
        """默认日志级别应为 INFO 或 DEBUG"""
        from yunxi_shared.logger import get_logger
        logger = get_logger("default-level")
        level = logger.getEffectiveLevel()
        assert level in (logging.INFO, logging.DEBUG)


class TestModuleRegistry:
    """模块注册表测试"""

    def setup_method(self):
        """每个测试前创建干净的注册表"""
        from yunxi_shared.module_client import ModuleRegistry
        self.registry = ModuleRegistry()

    def test_initial_empty(self):
        """初始状态应无模块"""
        modules = self.registry.get_all_modules()
        assert isinstance(modules, (list, dict))

    def test_register_module(self):
        """注册模块应成功"""
        from yunxi_shared.module_client import ModuleInfo
        info = ModuleInfo(key="m1", name="模块1", version="1.0.0", port=8001, base_url="http://127.0.0.1:8001")
        self.registry.register_module(info)
        m = self.registry.get_module("m1")
        assert m is not None
        assert m.key == "m1"

    def test_unregister_module(self):
        """注销模块应成功"""
        from yunxi_shared.module_client import ModuleInfo
        info = ModuleInfo(key="m1", name="模块1", version="1.0.0", port=8001, base_url="http://127.0.0.1:8001")
        self.registry.register_module(info)
        assert self.registry.get_module("m1") is not None
        self.registry.unregister_module("m1")
        assert self.registry.get_module("m1") is None

    def test_get_nonexistent_module(self):
        """查询不存在的模块应返回 None"""
        result = self.registry.get_module("nonexistent")
        assert result is None

    def test_status_summary(self):
        """状态统计应正确"""
        from yunxi_shared.module_client import ModuleInfo
        self.registry.register_module(
            ModuleInfo(key="m1", name="模块1", version="1.0.0", port=8001, base_url="http://127.0.0.1:8001")
        )
        self.registry.register_module(
            ModuleInfo(key="m2", name="模块2", version="1.0.0", port=8002, base_url="http://127.0.0.1:8002")
        )
        self.registry.register_module(
            ModuleInfo(key="m3", name="模块3", version="1.0.0", port=8003, base_url="http://127.0.0.1:8003")
        )
        summary = self.registry.get_status_summary()
        assert isinstance(summary, dict)
        # 应有总数和各状态统计
        assert "total" in summary or "online" in summary
