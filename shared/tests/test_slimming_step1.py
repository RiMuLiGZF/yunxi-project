"""
shared 库瘦身第一步 - 测试套件

测试内容:
1. 核心模块导入正常
2. 废弃模块的 deprecation warning
3. 合并后模块的功能一致性
4. 向后兼容性验证
"""

import warnings
import pytest


# ============================================================================
# 测试一：核心模块导入正常
# ============================================================================

class TestCoreImports:
    """测试核心模块可以正常导入"""

    def test_import_shared_root(self):
        """测试 shared 根模块可以导入"""
        import shared
        assert hasattr(shared, "__version__")

    def test_import_core_errors(self):
        """测试 shared.core.errors 核心错误模块"""
        from shared.core.errors import (
            YunxiError, ConfigError, ValidationError,
            AuthenticationError, AuthorizationError,
            error_to_dict,
        )
        assert YunxiError is not None
        assert issubclass(ConfigError, YunxiError)

    def test_import_core_config(self):
        """测试 shared.core.config 配置模块"""
        from shared.core.config import YunxiConfig, get_config
        assert YunxiConfig is not None
        assert callable(get_config)

    def test_import_core_responses(self):
        """测试 shared.core.responses 响应模块"""
        from shared.core.responses import ApiResponse, ok, fail, SUCCESS
        assert ApiResponse is not None
        assert callable(ok)
        assert callable(fail)
        assert SUCCESS == 0

    def test_import_core_version(self):
        """测试 shared.core.version 版本模块"""
        from shared.core.version import SYSTEM_VERSION, BUILD_DATE, VERSION_CODE
        assert SYSTEM_VERSION is not None
        assert isinstance(VERSION_CODE, int)

    def test_import_core_utils(self):
        """测试 shared.core.utils 工具模块"""
        from shared.core.utils import (
            generate_id, now_timestamp, now_iso,
            safe_get, truncate_text, format_file_size,
        )
        assert callable(generate_id)
        assert callable(now_timestamp)
        assert isinstance(generate_id(), str)

    def test_import_data_cache(self):
        """测试 shared.data.cache 缓存模块"""
        from shared.data.cache import SimpleCache, CacheStats, get_cache
        assert SimpleCache is not None
        assert callable(get_cache)

    def test_import_business_module_client(self):
        """测试 shared.business.module_client 模块客户端"""
        from shared.business.module_client import (
            ModuleClient, ModuleInfo, ModuleStatus,
            get_registry,
        )
        assert ModuleClient is not None
        assert callable(get_registry)


# ============================================================================
# 测试二：废弃模块的 DeprecationWarning
# ============================================================================

class TestDeprecatedModules:
    """测试已归档模块会发出 DeprecationWarning"""

    @pytest.mark.filterwarnings("always::DeprecationWarning")
    def test_deprecated_errors_module(self):
        """测试 shared.errors 顶层存根发出弃用警告"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # 强制重新导入以触发警告
            import importlib
            import shared.errors
            importlib.reload(shared.errors)
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1
            # 验证功能一致性
            from shared.core.errors import YunxiError as YunxiErrorCore
            assert shared.errors.YunxiError is YunxiErrorCore

    @pytest.mark.filterwarnings("always::DeprecationWarning")
    def test_deprecated_config_module(self):
        """测试 shared.config 顶层存根发出弃用警告"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import shared.config
            importlib.reload(shared.config)
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1
            # 验证功能一致性
            from shared.core.config import get_config as get_config_core
            assert shared.config.get_config is get_config_core

    @pytest.mark.filterwarnings("always::DeprecationWarning")
    def test_deprecated_auth_module(self):
        """测试 shared.auth 顶层存根发出弃用警告"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import shared.auth
            importlib.reload(shared.auth)
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1
            # 验证功能一致性
            from shared.core.auth import hash_api_key as hash_core
            assert shared.auth.hash_api_key is hash_core

    @pytest.mark.filterwarnings("always::DeprecationWarning")
    def test_deprecated_security_module(self):
        """测试 shared.security 顶层存根发出弃用警告"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import shared.security
            importlib.reload(shared.security)
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1
            # 验证功能一致性
            from shared.core.security import escape_html as escape_core
            assert shared.security.escape_html is escape_core

    @pytest.mark.filterwarnings("always::DeprecationWarning")
    def test_deprecated_cors_utils_module(self):
        """测试 shared.cors_utils 顶层存根发出弃用警告"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import shared.cors_utils
            importlib.reload(shared.cors_utils)
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1

    @pytest.mark.filterwarnings("always::DeprecationWarning")
    def test_deprecated_responses_module(self):
        """测试 shared.responses 顶层存根发出弃用警告"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import shared.responses
            importlib.reload(shared.responses)
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1
            # 验证功能一致性
            from shared.core.responses import ApiResponse as ApiRespCore
            assert shared.responses.ApiResponse is ApiRespCore

    @pytest.mark.filterwarnings("always::DeprecationWarning")
    def test_deprecated_data_governance_package(self):
        """测试 shared.data_governance 存根包发出弃用警告"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import shared.data_governance
            importlib.reload(shared.data_governance)
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1

    @pytest.mark.filterwarnings("always::DeprecationWarning")
    def test_deprecated_distributed_package(self):
        """测试 shared.distributed 存根包发出弃用警告"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import shared.distributed
            importlib.reload(shared.distributed)
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1

    @pytest.mark.filterwarnings("always::DeprecationWarning")
    def test_deprecated_middleware_package(self):
        """测试 shared.middleware 存根包发出弃用警告"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import shared.middleware
            importlib.reload(shared.middleware)
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1


# ============================================================================
# 测试三：合并后模块的功能一致性
# ============================================================================

class TestFunctionalConsistency:
    """测试归档后模块的功能一致性（旧路径 vs 新路径）"""

    def test_errors_functional_consistency(self):
        """测试错误类功能一致：shared.errors == shared.core.errors"""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from shared.errors import YunxiError, ValidationError, error_to_dict
            from shared.core.errors import (
                YunxiError as YunxiErrorCore,
                ValidationError as ValidationErrorCore,
                error_to_dict as error_to_dict_core,
            )

        # 类引用一致
        assert YunxiError is YunxiErrorCore
        assert ValidationError is ValidationErrorCore
        assert error_to_dict is error_to_dict_core

        # 功能一致
        try:
            raise ValidationError("test error", code=1001)
        except YunxiError as e:
            result = error_to_dict(e)
            assert "code" in result
            assert "test error" in result["message"]

    def test_config_functional_consistency(self):
        """测试配置功能一致：shared.config == shared.core.config"""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from shared.config import get_config
            from shared.core.config import get_config as get_config_core

        assert get_config is get_config_core
        cfg = get_config()
        assert cfg is not None

    def test_responses_functional_consistency(self):
        """测试响应功能一致：shared.responses == shared.core.responses"""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from shared.responses import ApiResponse, ok, fail, SUCCESS
            from shared.core.responses import (
                ApiResponse as ApiRespCore,
                ok as ok_core,
                fail as fail_core,
                SUCCESS as SUCCESS_CORE,
            )

        assert ApiResponse is ApiRespCore
        assert ok is ok_core
        assert fail is fail_core
        assert SUCCESS == SUCCESS_CORE

        # 测试功能（ok 返回 dict）
        resp = ok({"key": "value"})
        assert isinstance(resp, dict)
        assert resp["code"] == SUCCESS
        assert resp["data"] == {"key": "value"}

    def test_auth_functional_consistency(self):
        """测试认证功能一致：shared.auth == shared.core.auth"""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from shared.auth import hash_api_key, verify_api_key
            from shared.core.auth import (
                hash_api_key as hash_core,
                verify_api_key as verify_core,
            )

        assert hash_api_key is hash_core
        assert verify_api_key is verify_core

        # 测试功能（hash_api_key 返回哈希值）
        test_key = "test-api-key-123"
        hashed = hash_api_key(test_key)
        assert hashed != test_key
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_security_functional_consistency(self):
        """测试安全工具功能一致：shared.security == shared.core.security"""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from shared.security import escape_html, mask_email, validate_input
            from shared.core.security import (
                escape_html as escape_core,
                mask_email as mask_core,
                validate_input as validate_core,
            )

        assert escape_html is escape_core
        assert mask_email is mask_core
        assert validate_input is validate_core

        # 测试功能
        assert escape_html("<script>") == "&lt;script&gt;"
        assert "@" in mask_email("user@example.com")

    def test_waf_middleware_consistency(self):
        """测试 WAF 中间件功能一致"""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from shared.waf_middleware import WafMiddleware, WAF_ENABLED
            from shared.core.waf_middleware import (
                WafMiddleware as WafMiddlewareCore,
                WAF_ENABLED as WAF_ENABLED_CORE,
            )

        assert WafMiddleware is WafMiddlewareCore
        assert WAF_ENABLED == WAF_ENABLED_CORE


# ============================================================================
# 测试四：__init__.py 导出精简
# ============================================================================

class TestInitSlimming:
    """测试 shared/__init__.py 精简后的行为"""

    def test_all_size_reduced(self):
        """测试 __all__ 已精简到合理范围"""
        import shared
        # 从原来的 110+ 减少到 39 个核心符号
        assert len(shared.__all__) <= 50
        assert len(shared.__all__) >= 30

    def test_recommended_in_all(self):
        """测试核心推荐符号在 __all__ 中"""
        import shared
        recommended = [
            "YunxiError", "ConfigError", "ValidationError",
            "get_config", "YunxiConfig",
            "get_logger", "UnifiedLogger",
            "ApiResponse", "SUCCESS",
            "SYSTEM_VERSION", "BUILD_DATE", "VERSION_CODE",
            "ModuleClient", "ModuleInfo",
            "generate_id", "now_timestamp",
            "__version__",
        ]
        for name in recommended:
            assert name in shared.__all__, f"{name} should be in __all__"

    def test_legacy_not_in_all(self):
        """测试不推荐的符号不在 __all__ 中（但仍可访问）"""
        import shared
        legacy = [
            # 认证相关（不推荐从顶层导入）
            "hash_api_key", "verify_api_key", "generate_api_key",
            # 安全相关
            "escape_html", "mask_email", "INPUT_PATTERNS",
            # WAF
            "WafMiddleware", "WAF_ENABLED",
            # 数据层
            "SimpleCache", "DatabaseManager", "BackupManager",
            # 链路追踪
            "TracingMiddleware", "MetricsCollector",
            # 进程管理
            "ProcessManager",
        ]
        for name in legacy:
            # 不在 __all__ 中
            assert name not in shared.__all__, f"{name} should not be in __all__"
            # 但仍可访问（向后兼容）
            assert hasattr(shared, name), f"{name} should still be accessible"

    def test_backward_compatible_imports(self):
        """测试所有原有的导入路径仍可工作"""
        import shared
        # 确保所有之前导出的符号仍然可以通过属性访问
        symbols_to_check = [
            # core 层
            "YunxiConfig", "get_config", "get_logger",
            "YunxiError", "ConfigError", "error_to_dict",
            "ApiResponse", "SUCCESS",
            "DEFAULT_PUBLIC_PATHS", "hash_api_key",
            "escape_html", "validate_input",
            "resolve_cors_origins", "DEFAULT_DEV_ORIGINS",
            "generate_id", "now_timestamp",
            "SYSTEM_VERSION", "BUILD_DATE", "VERSION_CODE",
            "WafMiddleware", "WAF_ENABLED",
            "TracingMiddleware", "get_trace_id",
            "UnifiedLogger", "MetricsCollector",
            # data 层
            "SimpleCache", "CacheStats",
            "DatabaseManager", "get_db_manager",
            "BackupManager", "get_backup_manager",
            "MigrationEngine", "get_migration_engine",
            # business 层
            "ModuleClient", "ModuleInfo",
            "ProcessManager",
            "A2AClient",
        ]
        missing = []
        for name in symbols_to_check:
            if not hasattr(shared, name):
                missing.append(name)
        assert len(missing) == 0, f"Missing symbols: {missing}"


# ============================================================================
# 测试五：_deprecated 目录
# ============================================================================

class TestDeprecatedDirectory:
    """测试 _deprecated 归档目录的结构和内容"""

    def test_deprecated_package_exists(self):
        """测试 _deprecated 包存在"""
        import shared._deprecated
        assert hasattr(shared._deprecated, "__version__")

    def test_deprecated_modules_exist(self):
        """测试归档的模块文件存在于 _deprecated 中"""
        from pathlib import Path
        deprecated_dir = Path(__file__).resolve().parent.parent / "_deprecated"
        assert deprecated_dir.exists()
        assert deprecated_dir.is_dir()

        # 检查归档的文件
        archived_files = [
            "errors.py",
            "config.py",
            "auth.py",
            "security.py",
            "responses.py",
            "utils.py",
            "cors_utils.py",
            "waf_middleware.py",
            "version.py",  # 不，version 还有引用，不归档
        ]
        # 只检查确实归档了的
        should_exist = ["errors.py", "config.py", "auth.py", "security.py", "responses.py"]
        for f in should_exist:
            assert (deprecated_dir / f).exists(), f"{f} should be in _deprecated"

    def test_deprecated_packages_exist(self):
        """测试归档的包存在于 _deprecated 中"""
        from pathlib import Path
        deprecated_dir = Path(__file__).resolve().parent.parent / "_deprecated"

        archived_packages = ["data_governance", "distributed", "middleware"]
        for pkg in archived_packages:
            pkg_dir = deprecated_dir / pkg
            assert pkg_dir.exists(), f"{pkg}/ should be in _deprecated"
            assert (pkg_dir / "__init__.py").exists()

    def test_deprecated_import_via_deprecated(self):
        """测试可以通过 _deprecated 路径导入"""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from shared._deprecated.errors import YunxiError
            from shared.core.errors import YunxiError as YunxiErrorCore
        assert YunxiError is YunxiErrorCore


# ============================================================================
# 测试六：内部引用已更新
# ============================================================================

class TestInternalImportsUpdated:
    """测试 shared 内部代码不再使用已弃用的顶层路径"""

    def test_module_client_uses_core_config(self):
        """测试 business.module_client 使用正确的导入路径"""
        from pathlib import Path
        module_path = Path(__file__).resolve().parent.parent / "business" / "module_client.py"
        content = module_path.read_text(encoding="utf-8")

        # 应该使用新路径
        assert "from shared.core.config import" in content
        assert "from shared.data.cache import" in content

        # 不应该使用旧路径
        # (注意：可能在注释中出现，所以检查 import 语句)
        import re
        old_imports = re.findall(r'from shared\.(config|cache)\s+import', content)
        # 应该只有新路径
        assert "from shared.config import" not in content
        assert "from shared.cache import" not in content

    def test_voice_engine_uses_business_cosyvoice(self):
        """测试 business.voice_engine 使用正确的导入路径"""
        from pathlib import Path
        module_path = Path(__file__).resolve().parent.parent / "business" / "voice_engine.py"
        content = module_path.read_text(encoding="utf-8")

        # 应该使用新路径
        assert "from shared.business.cosyvoice_client import" in content

        # 不应该使用旧路径
        assert "from shared.cosyvoice_client import" not in content
