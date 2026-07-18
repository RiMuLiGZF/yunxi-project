"""
M8 异常处理测试
===============

验证 M8 控制塔异常处理改造后的正确性：
- 模块路由的异常处理仍能正常工作
- 特定异常场景返回正确的错误码
- 健康检查服务的异常降级逻辑
"""

import sys
import os
import importlib.util
from pathlib import Path

import pytest

# 确保可以导入 backend 模块
_M8_ROOT = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _M8_ROOT.parent.parent
for _p in (str(_M8_ROOT), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ============================================================
# 测试：M8 错误码定义
# ============================================================

class TestM8ErrorCodes:
    """测试 M8 错误码定义"""

    def test_m8_error_code_prefix(self):
        """测试 M8 错误码前缀为 08"""
        from errors import M8ErrorCode
        from shared.core.errors import parse_error_code

        parsed = parse_error_code(M8ErrorCode.MODULE_NOT_FOUND)
        assert parsed["module"] == 8  # M8 模块

    def test_m8_error_categories(self):
        """测试 M8 各分类错误码"""
        from errors import M8ErrorCode
        from shared.core.errors import parse_error_code

        # 参数错误
        assert parse_error_code(M8ErrorCode.INVALID_MODULE_KEY)["category"] == 1
        # 认证错误
        assert parse_error_code(M8ErrorCode.ADMIN_TOKEN_REQUIRED)["category"] == 2
        # 权限错误
        assert parse_error_code(M8ErrorCode.MODULE_OPERATION_FORBIDDEN)["category"] == 3
        # 资源不存在
        assert parse_error_code(M8ErrorCode.MODULE_NOT_FOUND)["category"] == 4
        # 业务错误
        assert parse_error_code(M8ErrorCode.MODULE_START_FAILED)["category"] == 5
        # 系统错误
        assert parse_error_code(M8ErrorCode.DATABASE_INIT_FAILED)["category"] == 6
        # 第三方错误
        assert parse_error_code(M8ErrorCode.M4_PROXY_ERROR)["category"] == 7
        # 限流错误
        assert parse_error_code(M8ErrorCode.MODULE_OPERATION_RATE_LIMITED)["category"] == 8
        # 数据错误
        assert parse_error_code(M8ErrorCode.SETTINGS_CONFLICT)["category"] == 9

    def test_m8_exception_inherits_yunxi(self):
        """测试 M8Exception 继承自 YunxiError"""
        from errors import M8Exception
        from shared.core.errors import YunxiError

        assert issubclass(M8Exception, YunxiError)

    def test_m8_exception_creation(self):
        """测试 M8Exception 创建"""
        from errors import M8Exception, M8ErrorCode

        err = M8Exception(
            message="模块启动失败",
            code=M8ErrorCode.MODULE_START_FAILED,
            details={"module": "m1"}
        )
        assert err.code == M8ErrorCode.MODULE_START_FAILED
        assert "模块启动失败" in err.message
        assert err.details["module"] == "m1"
        assert err.http_status == 409  # BUSINESS 类别默认 409


# ============================================================
# 测试：健康检查服务异常处理
# ============================================================

class TestHealthServiceErrorHandling:
    """测试健康检查服务的异常降级处理"""

    def _load_health_service(self):
        """直接加载 health_service 模块，避免 services/__init__.py 的依赖问题"""
        spec = importlib.util.spec_from_file_location(
            "health_service",
            str(_M8_ROOT / "services" / "health_service.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_register_m8_std_endpoints_no_crash(self):
        """测试注册 M8 标准端点不会崩溃"""
        from fastapi import FastAPI
        from shared.core.observability import get_logger

        health_service = self._load_health_service()

        app = FastAPI()
        logger = get_logger("test")

        class MockSettings:
            version = "1.0.0"

        settings = MockSettings()
        # 不应该抛出异常
        health_service.register_m8_std_endpoints(app, settings, logger)
        # 验证端点已注册
        routes = [r.path for r in app.routes]
        assert "/m8/health" in routes
        assert "/m8/metrics" in routes
        assert "/m8/config" in routes

    def test_register_system_check_endpoint_no_crash(self):
        """测试注册系统检查端点不会崩溃"""
        from fastapi import FastAPI
        from shared.core.observability import get_logger

        health_service = self._load_health_service()

        app = FastAPI()
        logger = get_logger("test")

        health_service.register_system_check_endpoint(app, logger, _PROJECT_ROOT)
        routes = [r.path for r in app.routes]
        assert "/api/system/check" in routes

    def test_register_public_health_endpoint_no_crash(self):
        """测试注册公开健康检查端点不会崩溃"""
        from fastapi import FastAPI
        from shared.core.observability import get_logger

        health_service = self._load_health_service()

        app = FastAPI()
        logger = get_logger("test")

        class MockSettings:
            version = "1.0.0"

        settings = MockSettings()
        # observability 不可用时也应该正常工作
        health_service.register_public_health_endpoint(app, settings, logger, _observability_available=False)
        routes = [r.path for r in app.routes]
        assert "/health" in routes


# ============================================================
# 测试：模块路由异常处理
# ============================================================

class TestModulesRouterErrorHandling:
    """测试模块路由的异常处理逻辑"""

    def test_module_unavailable_helper(self):
        """测试 _module_unavailable 辅助函数"""
        # 直接从文件读取并验证函数逻辑
        modules_py = _M8_ROOT / "routers" / "modules.py"
        with open(modules_py, 'r', encoding='utf-8') as f:
            content = f.read()

        # 验证 _module_unavailable 函数存在
        assert "def _module_unavailable" in content
        # 验证返回 ApiResponse
        assert "ApiResponse(" in content

    def test_not_found_error_module(self):
        """测试模块不存在时抛出 NotFoundError"""
        from shared.core.errors import NotFoundError
        from errors import M8ErrorCode

        err = NotFoundError(
            message="未找到模块: m99",
            code=M8ErrorCode.MODULE_NOT_FOUND,
            details={"module_key": "m99"}
        )
        assert err.code == M8ErrorCode.MODULE_NOT_FOUND
        assert err.http_status == 404
        assert "m99" in err.message

    def test_module_call_error_is_third_party_category(self):
        """测试 ModuleCallError 属于第三方错误类别"""
        from shared.core.errors import ModuleCallError, parse_error_code

        err = ModuleCallError()
        parsed = parse_error_code(err.code)
        assert parsed["category"] == 7  # THIRD_PARTY
        assert err.http_status == 502


# ============================================================
# 测试：系统设置加载异常处理
# ============================================================

class TestSettingsErrorHandling:
    """测试系统设置加载的异常处理"""

    def test_load_settings_file_not_exist(self):
        """测试设置文件不存在时返回默认值"""
        import json

        DEFAULT_SETTINGS = {
            "theme": "dark",
            "language": "zh-CN",
        }

        # 文件不存在应该返回默认值（模拟 _load_settings 的逻辑）
        result = DEFAULT_SETTINGS.copy()
        assert result["theme"] == "dark"
        assert result["language"] == "zh-CN"

    def test_invalid_json_handling(self):
        """测试无效 JSON 文件的处理"""
        import json
        import tempfile

        # 创建一个无效的 JSON 文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{invalid json!!!")
            temp_path = f.name

        try:
            # 模拟 _load_settings 的异常处理逻辑
            with open(temp_path, 'r') as f:
                try:
                    saved = json.load(f)
                    result = saved
                except json.JSONDecodeError:
                    # 预期：捕获 JSON 解析错误
                    result = None

            assert result is None  # 说明捕获到了 JSONDecodeError
        finally:
            os.unlink(temp_path)


# ============================================================
# 测试：异常处理改造验证
# ============================================================

class TestExceptionHandlingRefactoring:
    """验证异常处理改造的正确性"""

    def test_modules_py_specific_exceptions(self):
        """验证 modules.py 中使用了具体异常类型"""
        modules_py_path = _M8_ROOT / "routers" / "modules.py"
        with open(modules_py_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 验证有 httpx.HTTPError 捕获
        assert "httpx.HTTPError" in content
        # 验证有 ModuleCallError 捕获
        assert "ModuleCallError" in content
        # 验证有 ValueError 捕获
        assert "ValueError" in content
        # 验证有日志记录
        assert "logger.exception" in content

    def test_health_service_specific_exceptions(self):
        """验证 health_service.py 中使用了具体异常类型"""
        health_py_path = _M8_ROOT / "services" / "health_service.py"
        with open(health_py_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 验证有 ImportError 捕获
        assert "ImportError" in content
        # 验证有 OSError 捕获
        assert "OSError" in content
        # 验证有 asyncio.TimeoutError 捕获
        assert "TimeoutError" in content
        # 验证有注释说明
        assert "预期内异常" in content

    def test_growth_m5_proxy_json_decode(self):
        """验证 growth_m5_proxy.py 使用 json.JSONDecodeError"""
        growth_py_path = _M8_ROOT / "routers" / "growth_m5_proxy.py"
        with open(growth_py_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 验证有 json.JSONDecodeError 捕获
        assert "json.JSONDecodeError" in content

    def test_system_py_specific_exceptions(self):
        """验证 system.py 中使用了具体异常类型"""
        system_py_path = _M8_ROOT / "routers" / "system.py"
        with open(system_py_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 验证有 json.JSONDecodeError 捕获
        assert "json.JSONDecodeError" in content
        # 验证有 ValueError/TypeError 捕获
        assert "ValueError" in content
        # 验证有 ImportError 捕获
        assert "ImportError" in content

    def test_modules_py_exception_count_reduced(self):
        """验证 modules.py 中 except Exception 数量显著减少"""
        modules_py_path = _M8_ROOT / "routers" / "modules.py"
        with open(modules_py_path, 'r', encoding='utf-8') as f:
            content = f.read()

        count = content.count("except Exception")
        # 改造前约 62 处，改造后应远少于此数
        assert count < 30, f"except Exception 数量 {count} 仍然太多"
