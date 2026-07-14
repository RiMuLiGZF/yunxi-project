"""
中间件测试（限流 / 熔断 / 幂等性 / 认证）

运行: python -m pytest tests/test_middleware.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from tide_memory.middleware.rate_limit import TokenBucket, RateLimitMiddleware, _is_exempt_path
from tide_memory.middleware.circuit_breaker import CircuitBreakerMiddleware, _is_server_error
from tide_memory.middleware.idempotency import IdempotencyMiddleware
from tide_memory.middleware.auth import AuthMiddleware, FastAPIAuthMiddleware, _is_public_path
from tide_memory.common.retry import CircuitState, CircuitBreaker


# ============================================================
# TokenBucket 令牌桶测试
# ============================================================

class TestTokenBucket:
    """TokenBucket 限流器测试"""

    def test_init_invalid_rate(self):
        """rate <= 0 抛出 ValueError"""
        with pytest.raises(ValueError, match="rate"):
            TokenBucket(rate=0, capacity=10)

    def test_init_invalid_capacity(self):
        """capacity <= 0 抛出 ValueError"""
        with pytest.raises(ValueError, match="capacity"):
            TokenBucket(rate=1.0, capacity=-1)

    def test_initial_tokens_equal_capacity(self):
        """初始令牌数等于桶容量"""
        bucket = TokenBucket(rate=1.0, capacity=5.0)
        assert bucket.tokens == pytest.approx(5.0)

    def test_try_consume_success(self):
        """令牌充足时消耗成功"""
        bucket = TokenBucket(rate=1.0, capacity=5.0)
        assert bucket.try_consume(1.0) is True
        assert bucket.try_consume(1.0) is True
        assert bucket.try_consume(1.0) is True

    def test_try_consume_insufficient(self):
        """令牌不足时消耗失败"""
        bucket = TokenBucket(rate=1.0, capacity=2.0)
        bucket.try_consume(2.0)
        assert bucket.try_consume(1.0) is False

    def test_reset(self):
        """重置后令牌恢复到满"""
        bucket = TokenBucket(rate=1.0, capacity=10.0)
        bucket.try_consume(10.0)
        bucket.reset()
        assert bucket.tokens == pytest.approx(10.0)

    def test_repr(self):
        """repr 输出格式正确"""
        bucket = TokenBucket(rate=2.5, capacity=100.0)
        assert "rate=2.5" in repr(bucket)
        assert "capacity=100.0" in repr(bucket)


# ============================================================
# RateLimitMiddleware 测试
# ============================================================

class TestRateLimitMiddleware:
    """限流中间件测试"""

    def test_exempt_paths_skip(self):
        """豁免路径直接放行"""
        assert _is_exempt_path("/health") is True
        assert _is_exempt_path("/docs") is True
        assert _is_exempt_path("/m8/metrics") is True

    def test_non_exempt_paths_not_skipped(self):
        """非豁免路径不跳过"""
        assert _is_exempt_path("/api/v1/recall") is False
        assert _is_exempt_path("/api/v1/archive") is False

    @pytest.mark.asyncio
    async def test_disabled_middleware_passes_through(self):
        """限流关闭时直接放行"""
        with patch.dict(os.environ, {"M5_RATE_LIMIT_ENABLED": "false"}):
            mw = RateLimitMiddleware(app=MagicMock())
            mock_request = MagicMock()
            mock_request.url.path = "/api/v1/recall"
            mock_call_next = AsyncMock(return_value=MagicMock())
            response = await mw.dispatch(mock_request, mock_call_next)
            mock_call_next.assert_called_once()

    def test_get_stats_structure(self):
        """get_stats 返回正确结构"""
        mw = RateLimitMiddleware(app=MagicMock())
        stats = mw.get_stats()
        assert "enabled" in stats
        assert "per_minute" in stats
        assert "tracked_ips" in stats
        assert "max_buckets" in stats


# ============================================================
# CircuitBreakerMiddleware 测试
# ============================================================

class TestCircuitBreakerMiddleware:
    """熔断中间件测试"""

    def test_is_server_error_5xx(self):
        """5xx 状态码判定为服务端错误"""
        assert _is_server_error(500) is True
        assert _is_server_error(503) is True
        assert _is_server_error(599) is True

    def test_is_server_error_non_5xx(self):
        """非 5xx 不判定为服务端错误"""
        assert _is_server_error(200) is False
        assert _is_server_error(400) is False
        assert _is_server_error(429) is False

    def test_exempt_paths_skip(self):
        """豁免路径跳过熔断"""
        assert _is_exempt_path("/health") is True
        assert _is_exempt_path("/m8/health") is True

    def test_circuit_breaker_three_states(self):
        """CircuitBreaker 三态转换：CLOSED -> OPEN -> HALF_OPEN -> CLOSED"""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=3,
            recovery_timeout=9999,
            half_open_max_calls=1,
            window_size=60.0,
        )

        # 初始为 CLOSED
        assert cb.state == CircuitState.CLOSED

        # 记录失败直到熔断
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # 手动模拟时间流逝让 _opened_at 超过 recovery_timeout
        cb._opened_at = 0.0  # 让 now - opened_at 远超 9999
        assert cb.state == CircuitState.HALF_OPEN

        # 半开状态下成功 -> 闭合
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        """半开状态失败重新熔断"""
        cb = CircuitBreaker(
            name="test2",
            failure_threshold=2,
            recovery_timeout=9999,
            half_open_max_calls=1,
            window_size=60.0,
        )

        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # 手动模拟时间流逝进入 HALF_OPEN
        cb._opened_at = 0.0
        assert cb.state == CircuitState.HALF_OPEN

        # 半开状态下失败 -> 重新 OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_middleware_reset(self):
        """reset 重置熔断器"""
        with patch.dict(os.environ, {}, clear=True):
            mw = CircuitBreakerMiddleware(app=MagicMock())
            mw._circuit_breaker.record_failure()
            mw._circuit_breaker.record_failure()
            mw.reset()
            assert mw.circuit_state == CircuitState.CLOSED


# ============================================================
# IdempotencyMiddleware 测试
# ============================================================

class TestIdempotencyMiddleware:
    """幂等性中间件测试"""

    def test_extract_key_from_x_idempotency_key(self, tmp_path):
        """从 X-Idempotency-Key 头提取幂等键"""
        mw = IdempotencyMiddleware(
            app=MagicMock(),
            ttl=60,
            max_keys=100,
        )
        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda h: {
            "X-Idempotency-Key": "key-001",
        }.get(h)
        key = mw._extract_idempotency_key(mock_request)
        assert key == "key-001"

    def test_extract_key_from_x_request_id(self, tmp_path):
        """无 X-Idempotency-Key 时使用 X-Request-ID"""
        mw = IdempotencyMiddleware(
            app=MagicMock(),
            ttl=60,
            max_keys=100,
        )
        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda h: {
            "X-Request-ID": "req-001",
        }.get(h)
        key = mw._extract_idempotency_key(mock_request)
        assert key == "req-001"

    def test_extract_key_none_when_absent(self, tmp_path):
        """无幂等键头时返回 None"""
        mw = IdempotencyMiddleware(
            app=MagicMock(),
            ttl=60,
            max_keys=100,
        )
        mock_request = MagicMock()
        mock_request.headers.get.return_value = None
        key = mw._extract_idempotency_key(mock_request)
        assert key is None

    def test_get_methods_not_cached(self, tmp_path):
        """GET 请求不缓存"""
        mw = IdempotencyMiddleware(
            app=MagicMock(),
            ttl=60,
            max_keys=100,
        )
        assert "GET" not in mw.IDEMPOTENT_METHODS
        assert "POST" in mw.IDEMPOTENT_METHODS


# ============================================================
# FastAPIAuthMiddleware 测试
# ============================================================

class TestFastAPIAuthMiddleware:
    """认证中间件测试"""

    def test_public_paths_skip_auth(self):
        """公开路径跳过认证"""
        assert _is_public_path("/health") is True
        assert _is_public_path("/docs") is True
        assert _is_public_path("/redoc") is True
        assert _is_public_path("/api/v1/health") is True

    def test_non_public_paths_require_auth(self):
        """非公开路径需要认证"""
        assert _is_public_path("/api/v1/recall") is False
        assert _is_public_path("/api/v1/archive") is False

    def test_auth_middleware_core_missing_credentials(self):
        """AuthMiddleware 无凭证时返回 missing_credentials"""
        auth = AuthMiddleware()
        passed, info = auth.authenticate({"headers": {}})
        assert passed is False
        assert info["error"] == "missing_credentials"

    def test_auth_middleware_core_invalid_api_key(self):
        """AuthMiddleware API Key 错误时返回 invalid_api_key"""
        auth = AuthMiddleware(api_key="secret-key")
        passed, info = auth.authenticate({
            "headers": {"x-api-key": "wrong-key"},
        })
        assert passed is False
        assert info["error"] == "invalid_api_key"

    def test_auth_middleware_core_valid_api_key(self):
        """AuthMiddleware API Key 正确时认证通过"""
        auth = AuthMiddleware(api_key="secret-key")
        passed, info = auth.authenticate({
            "headers": {"x-api-key": "secret-key"},
        })
        assert passed is True
        assert info["auth_type"] == "api_key"
        assert info["agent_id"] == "api-key-user"

    def test_auth_middleware_core_valid_m8_token(self):
        """AuthMiddleware M8 Token 正确时认证通过"""
        auth = AuthMiddleware(m8_token="m8-secret")
        passed, info = auth.authenticate({
            "headers": {"x-m8-token": "m8-secret"},
        })
        assert passed is True
        assert info["auth_type"] == "m8_token"
        assert info["role"] == "internal"

    def test_auth_middleware_core_jwt_without_dot(self):
        """AuthMiddleware 简单 token（非标准 JWT）作为简单 token 处理"""
        auth = AuthMiddleware()
        passed, info = auth.authenticate({
            "headers": {"authorization": "Bearer simpletoken12345678"},
        })
        assert passed is True
        assert info["auth_type"] == "jwt"
        assert info["agent_id"] == "simpletoken12345"