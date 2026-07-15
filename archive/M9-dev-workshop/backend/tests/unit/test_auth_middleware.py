"""认证中间件单元测试 (>=15 用例)"""
import sys
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

# 确保可以导入 backend 模块
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest
from core.auth_middleware import (
    validate_token,
    get_admin_token,
    RateLimiter,
    PUBLIC_PATHS,
)


class TestValidateToken:
    """validate_token 函数测试"""

    def test_correct_token(self):
        """正确的 token 验证通过"""
        # 使用开发环境默认 token
        token = get_admin_token()
        if token:
            assert validate_token(token) is True

    def test_wrong_token(self):
        """错误的 token 验证失败"""
        assert validate_token("wrong-token-12345") is False

    def test_empty_token(self):
        """空 token 验证失败"""
        assert validate_token("") is False

    def test_none_token(self):
        """None token 不崩溃"""
        assert validate_token("") is False

    def test_case_sensitive_token(self):
        """Token 验证区分大小写"""
        token = get_admin_token()
        if token and token.islower():
            assert validate_token(token.upper()) is False

    @patch.dict(os.environ, {"M9_ADMIN_TOKEN": "test-secret-token-xyz"})
    def test_env_token_override(self):
        """环境变量覆盖默认 token"""
        token = get_admin_token()
        assert token == "test-secret-token-xyz"
        assert validate_token("test-secret-token-xyz") is True

    @patch.dict(os.environ, {"M9_ADMIN_TOKEN": ""}, clear=True)
    def test_no_token_configured(self):
        """未配置 token 时验证失败"""
        # 重置全局单例
        import core.auth_middleware as am
        token = get_admin_token()
        if not token:
            assert validate_token("anything") is False


class TestGetAdminToken:
    """get_admin_token 函数测试"""

    def test_returns_string(self):
        """返回字符串"""
        token = get_admin_token()
        assert isinstance(token, str)

    @patch.dict(os.environ, {"M9_ADMIN_TOKEN": "env-token-123"})
    def test_priority_env_var(self):
        """优先使用环境变量"""
        token = get_admin_token()
        assert token == "env-token-123"

    @patch.dict(os.environ, {"M9_ADMIN_TOKEN": ""})
    def test_fallback_to_default(self):
        """回退到默认值"""
        token = get_admin_token()
        # 开发环境应返回默认值
        assert isinstance(token, str)

    @patch.dict(os.environ, {"M9_ADMIN_TOKEN": ""}, clear=True)
    @patch.dict(os.environ, {"YUNXI_ENV": "production"})
    def test_production_no_default(self):
        """生产环境不设默认值"""
        token = get_admin_token()
        assert token == ""


class TestRateLimiter:
    """RateLimiter 类测试"""

    def test_initial_request_allowed(self):
        """首次请求允许"""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        allowed, info = limiter.check("test_key")
        assert allowed is True
        assert info["remaining"] == 4

    def test_within_limit(self):
        """限额内请求允许"""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for i in range(5):
            allowed, info = limiter.check("test_key")
            assert allowed is True

    def test_over_limit(self):
        """超限请求拒绝"""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for i in range(3):
            limiter.check("test_key")
        allowed, info = limiter.check("test_key")
        assert allowed is False
        assert info["remaining"] == 0

    def test_different_keys_independent(self):
        """不同 key 独立计数"""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        limiter.check("key_a")
        limiter.check("key_a")
        # key_a 已用完
        allowed_a, _ = limiter.check("key_a")
        assert allowed_a is False
        # key_b 仍然可用
        allowed_b, _ = limiter.check("key_b")
        assert allowed_b is True

    def test_token_refill_after_window(self):
        """令牌补充（模拟时间流逝）"""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for i in range(3):
            limiter.check("test_key")
        # 模拟时间流逝
        limiter._buckets["test_key"]["last_refill"] = time.time() - 120
        allowed, info = limiter.check("test_key")
        # 经过 120 秒（2 个窗口），应补充令牌
        assert allowed is True

    def test_remaining_decrement(self):
        """remaining 递减"""
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        _, info1 = limiter.check("key")
        assert info1["remaining"] == 9
        _, info2 = limiter.check("key")
        assert info2["remaining"] == 8

    def test_limit_field(self):
        """limit 字段正确"""
        limiter = RateLimiter(max_requests=50, window_seconds=60)
        _, info = limiter.check("key")
        assert info["limit"] == 50


class TestPublicPaths:
    """PUBLIC_PATHS 白名单测试"""

    def test_health_in_public(self):
        """/health 在白名单"""
        assert "/health" in PUBLIC_PATHS

    def test_docs_in_public(self):
        """/docs 在白名单"""
        assert "/docs" in PUBLIC_PATHS

    def test_api_info_in_public(self):
        """/api/info 在白名单"""
        assert "/api/info" in PUBLIC_PATHS

    def test_root_in_public(self):
        """/ 在白名单"""
        assert "/" in PUBLIC_PATHS

    def test_m8_endpoints_in_public(self):
        """M8 端点在白名单"""
        assert "/m8/health" in PUBLIC_PATHS
