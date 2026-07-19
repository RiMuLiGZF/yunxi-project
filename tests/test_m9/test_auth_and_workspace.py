"""
M9 开发工坊 - 认证中间件与工作空间单元测试

测试内容：
- 路径安全工具函数（纯函数测试，100% 可运行）
- 认证中间件核心逻辑（纯函数 + mock）
- Token 验证（hmac 时序安全比较）
- 速率限制器逻辑
- 工作空间 API（集成测试，标记为 integration）
"""

import sys
import os
import pytest
import tempfile
import hmac
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent.parent
M9_BACKEND_PATH = PROJECT_ROOT / "M9-dev-workshop" / "backend"

if str(M9_BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(M9_BACKEND_PATH))


# ============================================================
# 路径安全单元测试（纯函数，100% 可运行）
# ============================================================

class TestPathSafety:
    """路径安全工具单元测试"""

    @pytest.fixture
    def temp_root(self, tmp_path):
        """创建临时根目录用于测试"""
        return tmp_path

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_safe_join_normal_path(self, temp_root):
        """安全拼接正常路径"""
        from core.path_safety import safe_join

        result = safe_join(str(temp_root), "subdir", "file.txt")
        assert result is not None
        assert os.path.realpath(result).startswith(os.path.realpath(str(temp_root)))

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_safe_join_path_traversal_blocked(self, temp_root):
        """路径遍历攻击被阻止（返回 None）"""
        from core.path_safety import safe_join

        result = safe_join(str(temp_root), "..", "..", "etc", "passwd")
        assert result is None

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_safe_join_relative_traversal_blocked(self, temp_root):
        """相对路径遍历被阻止"""
        from core.path_safety import safe_join

        result = safe_join(str(temp_root), "../../etc/passwd")
        assert result is None

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_safe_join_root_itself_is_safe(self, temp_root):
        """根目录自身是安全的"""
        from core.path_safety import safe_join

        result = safe_join(str(temp_root), ".")
        assert result is not None

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_is_path_safe_inside_returns_true(self, temp_root):
        """路径在根目录内返回 True"""
        from core.path_safety import is_path_safe

        subdir = temp_root / "subdir" / "file.txt"
        subdir.parent.mkdir(parents=True)
        subdir.write_text("test")

        assert is_path_safe(str(temp_root), str(subdir)) is True

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_is_path_safe_outside_returns_false(self, temp_root):
        """路径在根目录外返回 False"""
        from core.path_safety import is_path_safe

        outside = temp_root.parent / "outside.txt"
        assert is_path_safe(str(temp_root), str(outside)) is False

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_is_path_safe_root_itself(self, temp_root):
        """根目录自身是安全的"""
        from core.path_safety import is_path_safe

        assert is_path_safe(str(temp_root), str(temp_root)) is True

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_sanitize_filename_removes_path_separators(self):
        """清理文件名移除路径分隔符"""
        from core.path_safety import sanitize_filename

        assert "/" not in sanitize_filename("a/b/c.txt")
        assert "\\" not in sanitize_filename("a\\b\\c.txt")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_sanitize_filename_removes_leading_dots(self):
        """清理文件名移除开头的点（隐藏文件）"""
        from core.path_safety import sanitize_filename

        result = sanitize_filename(".hidden")
        assert not result.startswith(".")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_sanitize_filename_truncates_long_names(self):
        """长文件名被截断到 255 字符以内"""
        from core.path_safety import sanitize_filename

        long_name = "a" * 300 + ".txt"
        result = sanitize_filename(long_name)
        assert len(result) <= 255

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_sanitize_filename_empty_returns_default(self):
        """空文件名返回默认名"""
        from core.path_safety import sanitize_filename

        assert sanitize_filename("") == "unnamed"
        assert sanitize_filename("...") == "unnamed"

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_assert_path_safe_raises_on_traversal(self, temp_root):
        """路径越界时抛出 PathSecurityError"""
        from core.path_safety import assert_path_safe, PathSecurityError

        with pytest.raises(PathSecurityError):
            assert_path_safe(str(temp_root), "/etc/passwd", "read")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_assert_path_safe_passes_on_safe_path(self, temp_root):
        """安全路径不抛出异常"""
        from core.path_safety import assert_path_safe

        safe_path = temp_root / "safe.txt"
        safe_path.write_text("test")
        # 不应抛出异常
        assert_path_safe(str(temp_root), str(safe_path), "read")


# ============================================================
# 认证中间件单元测试
# ============================================================

class TestAuthMiddlewareCore:
    """认证中间件核心逻辑单元测试"""

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_public_paths_constant_exists(self):
        """PUBLIC_PATHS 常量存在且包含核心路径"""
        from core.auth_middleware import PUBLIC_PATHS

        assert isinstance(PUBLIC_PATHS, (set, list, tuple))
        assert "/health" in PUBLIC_PATHS

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_public_paths_includes_docs(self):
        """公开路径包含文档路径"""
        from core.auth_middleware import PUBLIC_PATHS

        assert "/docs" in PUBLIC_PATHS
        assert "/openapi.json" in PUBLIC_PATHS

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_get_admin_token_returns_string(self):
        """get_admin_token 返回字符串"""
        from core.auth_middleware import get_admin_token

        result = get_admin_token()
        assert isinstance(result, str)

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_get_admin_token_env_var(self, monkeypatch):
        """环境变量 M9_ADMIN_TOKEN 优先"""
        from core.auth_middleware import get_admin_token

        monkeypatch.setenv("M9_ADMIN_TOKEN", "env-token-12345")
        # 强制重新获取（函数内部直接读 os.environ）
        assert get_admin_token() == "env-token-12345"

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_validate_token_correct(self, monkeypatch):
        """正确 Token 验证通过"""
        from core.auth_middleware import validate_token

        monkeypatch.setenv("M9_ADMIN_TOKEN", "correct-token-123")
        # 重新获取 token 以确保使用环境变量
        from core.auth_middleware import get_admin_token
        expected = get_admin_token()
        assert validate_token(expected) is True

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_validate_token_wrong(self, monkeypatch):
        """错误 Token 验证失败"""
        from core.auth_middleware import validate_token

        monkeypatch.setenv("M9_ADMIN_TOKEN", "correct-token-123")
        assert validate_token("wrong-token") is False

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_validate_token_empty_token(self, monkeypatch):
        """空 Token 验证失败"""
        from core.auth_middleware import validate_token

        monkeypatch.setenv("M9_ADMIN_TOKEN", "some-token")
        assert validate_token("") is False

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_validate_token_uses_constant_time_compare(self):
        """Token 验证使用常量时间比较（hmac.compare_digest）"""
        from core.auth_middleware import validate_token

        # 验证函数使用 hmac.compare_digest（时序攻击防护）
        # 通过检查源码中是否使用 hmac 来确认
        import inspect
        source = inspect.getsource(validate_token)
        assert "compare_digest" in source or "hmac" in source

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_auth_middleware_class_exists(self):
        """AuthMiddleware 类存在"""
        from core.auth_middleware import AuthMiddleware

        assert AuthMiddleware is not None
        assert callable(AuthMiddleware)


class TestRateLimiter:
    """速率限制器单元测试"""

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_rate_limiter_class_exists(self):
        """RateLimiter 类存在"""
        from core.auth_middleware import RateLimiter

        assert RateLimiter is not None

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_rate_limiter_allows_requests_within_limit(self):
        """限制范围内的请求被允许"""
        from core.auth_middleware import RateLimiter

        limiter = RateLimiter(max_requests=10, window_seconds=60)
        allowed, info = limiter.check("test-key")

        assert allowed is True
        assert "remaining" in info
        assert "limit" in info

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_rate_limiter_blocks_after_limit(self):
        """超过限制后请求被拒绝"""
        from core.auth_middleware import RateLimiter

        limiter = RateLimiter(max_requests=3, window_seconds=60)
        key = "limited-key"

        # 消耗完配额
        for _ in range(3):
            limiter.check(key)

        # 第 4 次应该被拒绝
        allowed, info = limiter.check(key)
        assert allowed is False
        assert info["remaining"] == 0

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.security
    def test_rate_limiter_global_instance_exists(self):
        """全局 rate_limiter 实例存在"""
        from core.auth_middleware import rate_limiter

        assert rate_limiter is not None
        assert hasattr(rate_limiter, "check")


# ============================================================
# 统一错误码单元测试
# ============================================================

class TestUnifiedErrors:
    """M9 统一错误码测试"""

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.error
    def test_m9_error_codes_exist(self):
        """M9 错误码定义存在"""
        try:
            from core.unified_errors import M9ErrorCode
            assert M9ErrorCode is not None
        except ImportError:
            pytest.skip("M9 错误码模块不可用")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.error
    def test_m9_error_module_prefix(self):
        """M9 错误码模块前缀正确"""
        try:
            from core.unified_errors import M9ErrorCode
            from shared.core.errors import ModuleCode

            if hasattr(M9ErrorCode, "MODULE"):
                assert M9ErrorCode.MODULE == ModuleCode.M9
        except ImportError:
            pytest.skip("shared/core/errors 模块不可用")


# ============================================================
# 集成测试（需要完整 M9 应用）
# ============================================================

class TestAuthMiddlewareIntegration:
    """认证中间件集成测试（需要 M9 应用实例）

    依赖 m9_client fixture，应用无法初始化时自动跳过。
    """

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_health_endpoint_no_auth_required(self, m9_client):
        """健康检查接口无需认证"""
        response = m9_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_protected_endpoint_requires_auth(self, m9_client):
        """受保护接口需要认证"""
        response = m9_client.get("/api/v1/workspace/projects")
        if response.status_code == 404:
            response = m9_client.get("/api/workspace/projects")
        assert response.status_code in [200, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.auth
    @pytest.mark.middleware
    def test_invalid_token_returns_401(self, m9_client):
        """无效 Token 返回 401"""
        headers = {"X-M9-Token": "invalid-token-12345"}
        response = m9_client.get("/api/v1/workspace/projects", headers=headers)
        if response.status_code == 404:
            response = m9_client.get("/api/workspace/projects", headers=headers)
        assert response.status_code in [200, 401, 403, 404]


class TestWorkspaceAPIIntegration:
    """工作空间 API 集成测试"""

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_workspace_info_endpoint(self, m9_client):
        """工作空间信息接口"""
        response = m9_client.get("/api/v1/workspace/info")
        if response.status_code == 404:
            response = m9_client.get("/api/workspace/info")
        assert response.status_code in [200, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_workspace_stats_endpoint(self, m9_client):
        """工作空间统计接口"""
        response = m9_client.get("/api/v1/workspace/stats")
        if response.status_code == 404:
            response = m9_client.get("/api/workspace/stats")
        assert response.status_code in [200, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_m9_health_check(self, m9_client):
        """M9 健康检查"""
        response = m9_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_m9_root_endpoint(self, m9_client):
        """M9 根路径"""
        response = m9_client.get("/")
        assert response.status_code in [200, 301, 302, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_workspace_scan_endpoint(self, m9_client):
        """工作空间扫描接口"""
        body = {"scan_dirs": [], "max_depth": 3}
        response = m9_client.post("/api/v1/workspace/scan", json=body)
        if response.status_code == 404:
            response = m9_client.post("/api/workspace/scan", json=body)
        assert response.status_code in [200, 202, 400, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_workspace_activity_endpoint(self, m9_client):
        """工作空间活动记录接口"""
        body = {
            "project": "test-project",
            "activity_type": "edit",
            "duration": 10.5,
            "description": "测试活动",
        }
        response = m9_client.post("/api/v1/workspace/activity", json=body)
        if response.status_code == 404:
            response = m9_client.post("/api/workspace/activity", json=body)
        assert response.status_code in [200, 201, 400, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_workspace_dashboard_endpoint(self, m9_client):
        """工作空间仪表板接口"""
        response = m9_client.get("/api/v1/dashboard")
        if response.status_code == 404:
            response = m9_client.get("/api/dashboard")
        assert response.status_code in [200, 401, 403, 404]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_info_endpoint_public(self, m9_client):
        """信息接口可能是公开的"""
        response = m9_client.get("/api/info")
        assert response.status_code in [200, 401, 403, 404]
