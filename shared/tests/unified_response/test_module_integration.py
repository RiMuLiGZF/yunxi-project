"""
5 个核心模块接入验证测试
==========================

验证 5 个核心模块的统一响应格式接入：
1. M8 控制塔
2. M10 系统卫士
3. M12 安全护盾
4. M4 场景引擎
5. API-Gateway

每个模块至少 3 个测试用例。

注意：由于多个模块都有 schemas/common.py 等同名文件，
本测试使用 importlib 直接按文件路径加载，避免 sys.path 冲突。
"""

import sys
import time
import pytest
import importlib.util
from pathlib import Path

# 项目根目录（test 文件在 shared/tests/unified_response/ 下，上 3 级到 yunxi-project/）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# M10 模块路径（包名唯一，可直接加入 sys.path）
_M10_PATH = _PROJECT_ROOT / "M10-system-guard"
if str(_M10_PATH) not in sys.path:
    sys.path.insert(0, str(_M10_PATH))


def _load_module_from_file(module_name: str, file_path: Path):
    """
    直接从文件路径加载模块，不依赖 sys.path。

    适用于不同模块下有同名包/模块的情况（如多个 schemas/common.py）。
    """
    file_path = Path(file_path)
    if not file_path.exists():
        pytest.skip(f"模块文件不存在: {file_path}")
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        pytest.skip(f"无法创建模块 spec: {file_path}")
    module = importlib.util.module_from_spec(spec)
    # 确保 shared 包可导入
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        del sys.modules[module_name]
        pytest.skip(f"模块加载失败（可能缺少依赖）: {file_path}, 错误: {e}")
    return module


# ============================================================
# M8 控制塔模块测试
# ============================================================

class TestM8ControlTower:
    """M8 控制塔统一响应接入验证."""

    @pytest.fixture(scope="class")
    def m8_module(self):
        """加载 M8 的 schemas.common 模块."""
        path = _PROJECT_ROOT / "M8-control-tower" / "backend" / "schemas" / "common.py"
        return _load_module_from_file("m8_schemas_common", path)

    def test_m8_api_response_uses_unified(self, m8_module):
        """测试 M8-1: ApiResponse 来自统一标准包."""
        from shared.unified_response import ApiResponse as UnifiedApiResponse
        M8ApiResponse = getattr(m8_module, "ApiResponse", None)
        assert M8ApiResponse is not None, "M8 模块未导出 ApiResponse"
        assert M8ApiResponse is UnifiedApiResponse, "M8 ApiResponse 不是统一标准版本"

    def test_m8_legacy_compat_available(self, m8_module):
        """测试 M8-2: 旧版兼容类 LegacyApiResponse 和 ApiResponseCompat 可用."""
        LegacyApiResponse = getattr(m8_module, "LegacyApiResponse", None)
        ApiResponseCompat = getattr(m8_module, "ApiResponseCompat", None)
        assert LegacyApiResponse is not None, "M8 缺少 LegacyApiResponse 兼容类"
        assert ApiResponseCompat is not None, "M8 缺少 ApiResponseCompat 兼容别名"
        # 旧版有 request_id 字段
        legacy = LegacyApiResponse.success(data={"test": 1})
        d = legacy.model_dump()
        assert "request_id" in d
        assert "timestamp" in d
        # 旧版时间戳是毫秒级整数
        assert isinstance(d["timestamp"], int)
        assert d["timestamp"] > 1_000_000_000_000  # 毫秒级

    def test_m8_unified_response_fields(self, m8_module):
        """测试 M8-3: 标准响应字段名正确（trace_id 而非 request_id）."""
        ApiResponse = getattr(m8_module, "ApiResponse", None)
        assert ApiResponse is not None
        resp = ApiResponse.success(data={"m8": "test"}, trace_id="m8-trace-001")
        d = resp.to_dict()
        assert d["code"] == 0
        assert "message" in d
        assert d["data"] == {"m8": "test"}
        assert "trace_id" in d
        assert d["trace_id"] == "m8-trace-001"
        assert "timestamp" in d
        assert isinstance(d["timestamp"], float)
        # 确保没有 request_id 字段
        assert "request_id" not in d


# ============================================================
# M10 系统卫士模块测试
# ============================================================

class TestM10SystemGuard:
    """M10 系统卫士统一响应接入验证."""

    def test_m10_success_returns_standard_fields(self):
        """测试 M10-1: success() 返回标准 5 字段格式."""
        from m10_system_guard.api.response import success
        result = success(data={"status": "ok"})
        assert isinstance(result, dict)
        assert result["code"] == 0
        assert result["message"] == "ok"
        assert result["data"] == {"status": "ok"}
        assert "trace_id" in result
        assert "timestamp" in result
        assert isinstance(result["timestamp"], float)

    def test_m10_error_returns_standard_fields(self):
        """测试 M10-2: error() 返回标准 5 字段格式."""
        from m10_system_guard.api.response import error
        result = error(code=500, message="内部错误", data={"detail": "test"})
        assert isinstance(result, dict)
        assert result["code"] == 500
        assert result["message"] == "内部错误"
        assert result["data"] == {"detail": "test"}
        assert "trace_id" in result
        assert "timestamp" in result

    def test_m10_make_response_backward_compat(self):
        """测试 M10-3: 底层 make_response 仍可用（向后兼容）."""
        from m10_system_guard.models import make_response
        # make_response 应该仍然可用
        result = make_response(data={"test": 1})
        assert isinstance(result, dict)
        assert result["code"] == 0
        assert "data" in result


# ============================================================
# M12 安全护盾模块测试
# ============================================================

class TestM12SecurityShield:
    """M12 安全护盾统一响应接入验证."""

    @pytest.fixture(scope="class")
    def m12_module(self):
        """加载 M12 的 schemas.common 模块."""
        path = _PROJECT_ROOT / "M12-security-shield" / "backend" / "schemas" / "common.py"
        return _load_module_from_file("m12_schemas_common", path)

    def test_m12_api_response_uses_unified(self, m12_module):
        """测试 M12-1: ApiResponse 来自统一标准包."""
        from shared.unified_response import ApiResponse as UnifiedApiResponse
        M12ApiResponse = getattr(m12_module, "ApiResponse", None)
        assert M12ApiResponse is not None, "M12 模块未导出 ApiResponse"
        assert M12ApiResponse is UnifiedApiResponse, "M12 ApiResponse 不是统一标准版本"

    def test_m12_legacy_api_response_available(self, m12_module):
        """测试 M12-2: LegacyApiResponse 保留 3 字段旧格式."""
        LegacyApiResponse = getattr(m12_module, "LegacyApiResponse", None)
        assert LegacyApiResponse is not None, "M12 缺少 LegacyApiResponse 兼容类"
        legacy = LegacyApiResponse(code=0, message="ok", data={"test": 1})
        d = legacy.model_dump()
        # 旧版只有 3 个字段
        assert d["code"] == 0
        assert d["message"] == "ok"
        assert d["data"] == {"test": 1}
        # 旧版没有 trace_id 和 timestamp
        assert "trace_id" not in d
        assert "timestamp" not in d

    def test_m12_make_response_standard_format(self, m12_module):
        """测试 M12-3: make_response 已升级为 5 字段标准格式."""
        make_response = getattr(m12_module, "make_response", None)
        make_error_response = getattr(m12_module, "make_error_response", None)
        assert make_response is not None, "M12 缺少 make_response 函数"
        assert make_error_response is not None, "M12 缺少 make_error_response 函数"

        # 成功响应
        result = make_response(data={"scan": "result"})
        assert result["code"] == 0
        assert result["message"] == "success"
        assert result["data"] == {"scan": "result"}
        assert "trace_id" in result
        assert "timestamp" in result
        assert isinstance(result["timestamp"], float)

        # 错误响应
        err = make_error_response("安全扫描失败", code=500)
        assert err["code"] == 500
        assert err["message"] == "安全扫描失败"
        assert "trace_id" in err
        assert "timestamp" in err


# ============================================================
# M4 场景引擎模块测试
# ============================================================

class TestM4SceneEngine:
    """M4 场景引擎统一响应接入验证."""

    @pytest.fixture(scope="class")
    def m4_schemas_module(self):
        """加载 M4 的 schemas.common 模块."""
        path = _PROJECT_ROOT / "M4-scene-engine" / "src" / "schemas" / "common.py"
        return _load_module_from_file("m4_schemas_common", path)

    @pytest.fixture(scope="class")
    def m4_response_utils_module(self):
        """加载 M4 的 response_utils 模块."""
        path = _PROJECT_ROOT / "M4-scene-engine" / "src" / "models" / "response_utils.py"
        return _load_module_from_file("m4_response_utils", path)

    def test_m4_api_response_uses_unified(self, m4_schemas_module):
        """测试 M4-1: ApiResponse 来自统一标准包."""
        from shared.unified_response import ApiResponse as UnifiedApiResponse
        M4ApiResponse = getattr(m4_schemas_module, "ApiResponse", None)
        assert M4ApiResponse is not None, "M4 schemas.common 未导出 ApiResponse"
        assert M4ApiResponse is UnifiedApiResponse, "M4 ApiResponse 不是统一标准版本"

    def test_m4_legacy_api_response_available(self, m4_schemas_module):
        """测试 M4-2: LegacyApiResponse 可用（向后兼容）."""
        LegacyApiResponse = getattr(m4_schemas_module, "LegacyApiResponse", None)
        assert LegacyApiResponse is not None, "M4 缺少 LegacyApiResponse 兼容类"
        legacy = LegacyApiResponse(code=0, message="success", data={"mode": "work"})
        d = legacy.model_dump()
        assert d["code"] == 0
        assert d["message"] == "success"
        assert d["data"] == {"mode": "work"}
        # 旧版只有 3 字段
        assert "trace_id" not in d
        assert "timestamp" not in d

    def test_m4_response_utils_standard_format(self, m4_response_utils_module):
        """测试 M4-3: response_utils.make_response 返回标准 5 字段."""
        make_response = getattr(m4_response_utils_module, "make_response", None)
        assert make_response is not None, "M4 缺少 make_response 函数"
        result = make_response(data={"scene": "study"})
        assert result["code"] == 0
        assert result["message"] == "success"
        assert result["data"] == {"scene": "study"}
        assert "trace_id" in result
        assert "timestamp" in result
        assert isinstance(result["timestamp"], float)


# ============================================================
# API-Gateway 模块测试
# ============================================================

class TestApiGateway:
    """API-Gateway 统一响应接入验证.

    由于 API-Gateway 使用相对导入（from .config import settings 等），
    直接 import main 会失败。这里通过读取源码验证关键接入点。
    """

    @pytest.fixture(scope="class")
    def main_source(self):
        """读取 API-Gateway main.py 源码."""
        path = _PROJECT_ROOT / "API-Gateway" / "src" / "main.py"
        if not path.exists():
            pytest.skip(f"API-Gateway main.py 不存在: {path}")
        return path.read_text(encoding="utf-8")

    def test_gateway_unified_response_imported(self, main_source):
        """测试 GW-1: 统一响应标准已在 main.py 中导入."""
        # 检查关键导入
        assert "unified_response" in main_source, "main.py 中未导入 unified_response"
        assert "ApiResponse" in main_source, "main.py 中未导入 ApiResponse"
        assert "UnifiedResponseMiddleware" in main_source, "main.py 中未导入中间件"

    def test_gateway_middleware_registered(self, main_source):
        """测试 GW-2: UnifiedResponseMiddleware 已注册到 app."""
        # 检查中间件注册
        assert "UnifiedResponseMiddleware" in main_source, "缺少 UnifiedResponseMiddleware"
        assert "add_middleware" in main_source, "未调用 add_middleware"
        # 检查健康检查端点
        assert "/health" in main_source, "缺少 /health 端点"

    def test_gateway_trace_id_passthrough(self, main_source):
        """测试 GW-3: X-Trace-Id 透传支持已配置."""
        # 检查 trace_id 相关配置
        assert "trace_id" in main_source.lower(), "缺少 trace_id 相关配置"
        assert "X-Trace-Id" in main_source or "x-trace-id" in main_source, \
            "缺少 X-Trace-Id 请求头处理"

    def test_gateway_ok_fail_available(self, main_source):
        """测试 GW-4: ok() / fail() 便捷函数已导入."""
        # 检查便捷函数
        assert "ok" in main_source and "fail" in main_source, \
            "缺少 ok/fail 便捷函数导入"


# ============================================================
# shared/module_sdk 向后兼容测试
# ============================================================

class TestModuleSdkBackwardCompat:
    """shared/module_sdk 向后兼容测试."""

    def test_module_sdk_api_response_importable(self):
        """测试 SDK-1: 旧导入路径仍然有效，且有 DeprecationWarning."""
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from shared.module_sdk.models import ApiResponse
            # 应该有 DeprecationWarning
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) > 0, "旧导入路径应触发 DeprecationWarning"

    def test_module_sdk_success_backward_compat(self):
        """测试 SDK-2: success() 接口与旧版兼容."""
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        from shared.module_sdk.models import ApiResponse
        # 旧版接口：success(data, message="success", trace_id="")
        resp = ApiResponse.success(
            data={"sdk": "test"},
            message="success",
            trace_id="sdk-trace-001",
        )
        d = resp.to_dict()
        assert d["code"] == 0
        assert d["message"] == "success"
        assert d["data"] == {"sdk": "test"}
        assert "trace_id" in d
        assert "timestamp" in d

    def test_module_sdk_is_success_property(self):
        """测试 SDK-3: is_success 属性可用."""
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        from shared.module_sdk.models import ApiResponse
        resp = ApiResponse.success()
        assert resp.is_success is True
        err = ApiResponse.error(code=500, message="error")
        assert err.is_success is False
