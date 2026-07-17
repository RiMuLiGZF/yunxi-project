"""
统一认证体系 - FastAPI 认证中间件

提供统一的认证中间件，支持多种认证方式：
- JWT Bearer Token
- API Key（Header 方式：X-API-Key）
- API Key（Query 参数方式：?api_key=xxx）
- 自定义 Header Token（兼容 M9/M10 等旧模块）

特性：
- 公开路径白名单配置（支持通配符）
- 速率限制集成接口
- 审计日志接口
- 自动降级模式（认证服务不可用时的策略）
- 多种认证方式可配置组合

用法：
    from shared.core.auth.middleware import UnifiedAuthMiddleware
    from shared.core.auth.jwt import JWTHandler, JWTConfig

    jwt_handler = JWTHandler(JWTConfig(secret="your-secret"))
    app.add_middleware(
        UnifiedAuthMiddleware,
        jwt_handler=jwt_handler,
        api_key_validator=api_key_validator,
        public_paths=["/health", "/docs", "/openapi.json"],
    )
"""

import time
import logging
from fnmatch import fnmatch
from typing import Optional, List, Callable, Dict, Any, Set

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("unified_auth")


# ===========================================================================
# 默认公开路径
# ===========================================================================

DEFAULT_PUBLIC_PATHS: List[str] = [
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
]


# ===========================================================================
# 辅助函数
# ===========================================================================

def is_public_path(path: str, public_paths: List[str]) -> bool:
    """判断路径是否在公开路径列表中

    支持通配符 * 匹配，例如 /m8/* 可以匹配 /m8/health。

    Args:
        path: 待检查的请求路径
        public_paths: 公开路径列表，支持通配符

    Returns:
        True 表示该路径为公开路径，无需鉴权
    """
    if not path or not public_paths:
        return False

    for pattern in public_paths:
        if fnmatch(path, pattern):
            return True
        # 兼容不带通配符的前缀匹配（如 /docs 匹配 /docs/xxx）
        # 排除根路径 "/"，避免匹配所有路径
        stripped = pattern.rstrip("/")
        if stripped and not pattern.endswith("*") and path.startswith(stripped + "/"):
            return True

    return False


def extract_bearer_token(request: Request) -> Optional[str]:
    """从请求中提取 Bearer Token

    Args:
        request: FastAPI/Starlette 请求对象

    Returns:
        Token 字符串，未找到返回 None
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


def extract_api_key(request: Request, header_names: Optional[List[str]] = None) -> Optional[str]:
    """从请求中提取 API Key

    优先级：
    1. 自定义 Header（如 X-API-Key, X-M9-Token 等）
    2. Query 参数（api_key）

    Args:
        request: 请求对象
        header_names: 自定义 Header 名称列表，默认 ["X-API-Key"]

    Returns:
        API Key 字符串，未找到返回 None
    """
    if header_names is None:
        header_names = ["X-API-Key"]

    # 从 Header 提取
    for header_name in header_names:
        key = request.headers.get(header_name.lower())
        if key:
            return key

    # 从 Query 参数提取
    query_key = request.query_params.get("api_key")
    if query_key:
        return query_key

    return None


# ===========================================================================
# 速率限制接口
# ===========================================================================

class RateLimitBackend:
    """速率限制后端接口

    各模块可实现自己的速率限制器（内存、Redis 等）。
    """

    def check(self, key: str) -> tuple:
        """检查是否超过限流

        Args:
            key: 限流键（如 IP 地址、用户 ID、API Key ID 等）

        Returns:
            (是否允许, 剩余次数, 窗口秒数)
        """
        raise NotImplementedError


class SimpleMemoryRateLimiter(RateLimitBackend):
    """简单内存版速率限制器（令牌桶算法）

    线程安全，适用于单进程场景。
    """

    def __init__(self, default_limit: int = 60, window_seconds: int = 60):
        import threading
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._buckets: Dict[str, tuple] = {}  # key -> (count, window_start)

    def _get_window_id(self, now: float) -> int:
        return int(now // self.window_seconds)

    def check(self, key: str, limit: Optional[int] = None) -> tuple:
        if limit is None:
            limit = self.default_limit

        now = time.time()
        window_id = self._get_window_id(now)

        with self._lock:
            count, start_time = self._buckets.get(key, (0, 0.0))
            current_window_id = self._get_window_id(start_time)

            if current_window_id != window_id:
                count = 0
                start_time = now

            if count >= limit:
                self._buckets[key] = (count, start_time)
                return False, 0, self.window_seconds

            count += 1
            self._buckets[key] = (count, start_time)
            remaining = limit - count
            return True, remaining, self.window_seconds

    def remaining(self, key: str, limit: Optional[int] = None) -> int:
        """查询当前剩余次数（不消耗令牌）"""
        if limit is None:
            limit = self.default_limit
        now = time.time()
        window_id = self._get_window_id(now)
        with self._lock:
            count, start_time = self._buckets.get(key, (0, 0.0))
            if self._get_window_id(start_time) != window_id:
                return limit
            return max(0, limit - count)

    def reset(self, key: str) -> None:
        """重置指定 key 的限流计数"""
        with self._lock:
            self._buckets.pop(key, None)

    def clear(self) -> None:
        """清空所有限流计数"""
        with self._lock:
            self._buckets.clear()


# ===========================================================================
# 审计日志接口
# ===========================================================================

class AuditLogger:
    """审计日志接口

    各模块可实现自己的审计日志记录方式。
    """

    def log_auth(
        self,
        request: Request,
        auth_result: str,
        auth_type: Optional[str] = None,
        user_info: Optional[Dict[str, Any]] = None,
        error_detail: Optional[str] = None,
    ) -> None:
        """记录认证审计日志

        Args:
            request: 请求对象
            auth_result: 认证结果（"success" / "failed" / "denied"）
            auth_type: 认证方式（"jwt" / "api_key" / "none"）
            user_info: 用户信息（认证成功时）
            error_detail: 错误详情（认证失败时）
        """
        pass  # 默认空实现


# ===========================================================================
# 统一认证中间件
# ===========================================================================

class UnifiedAuthMiddleware(BaseHTTPMiddleware):
    """统一认证中间件

    支持多种认证方式，可灵活配置。
    将认证结果存入 request.state.user，供后续路由处理函数使用。

    Args:
        jwt_handler: JWT 处理器（可选，不提供则不支持 JWT 认证）
        api_key_validator: API Key 验证器（可选，不提供则不支持 API Key 认证）
        api_key_header_names: API Key Header 名称列表，默认 ["X-API-Key"]
        public_paths: 公开路径列表（支持通配符）
        rate_limiter: 速率限制器（可选）
        rate_limit_by: 限流键来源："ip" / "api_key" / "user"
        audit_logger: 审计日志记录器（可选）
        enabled: 是否启用认证（开发环境可设为 False）
        fallback_mode: 降级模式：
            - "strict": 认证服务不可用时拒绝所有请求（默认）
            - "permissive": 认证服务不可用时放行（仅用于紧急情况）
            - "public_only": 仅放行公开路径
        require_auth: 是否强制要求认证（公开路径除外）
        token_blacklist_checker: Token 黑名单检查函数（可选）
            签名: (jti: str) -> bool
    """

    def __init__(
        self,
        app,
        jwt_handler=None,
        api_key_validator=None,
        api_key_header_names: Optional[List[str]] = None,
        public_paths: Optional[List[str]] = None,
        rate_limiter: Optional[RateLimitBackend] = None,
        rate_limit_by: str = "ip",
        audit_logger: Optional[AuditLogger] = None,
        enabled: bool = True,
        fallback_mode: str = "strict",
        require_auth: bool = True,
        token_blacklist_checker: Optional[Callable[[str], bool]] = None,
    ):
        super().__init__(app)
        self.jwt_handler = jwt_handler
        self.api_key_validator = api_key_validator
        self.api_key_header_names = api_key_header_names or ["X-API-Key"]
        self.public_paths = public_paths or DEFAULT_PUBLIC_PATHS
        self.rate_limiter = rate_limiter
        self.rate_limit_by = rate_limit_by
        self.audit_logger = audit_logger
        self.enabled = enabled
        self.fallback_mode = fallback_mode
        self.require_auth = require_auth
        self.token_blacklist_checker = token_blacklist_checker

    async def dispatch(self, request: Request, call_next) -> Response:
        # 认证完全关闭（开发模式）
        if not self.enabled:
            request.state.user = {
                "auth_type": "disabled",
                "user_id": "dev",
                "username": "developer",
                "roles": ["super_admin"],
                "scopes": ["*"],
            }
            return await call_next(request)

        path = request.url.path

        # 公开路径直接放行
        if is_public_path(path, self.public_paths):
            request.state.user = {
                "auth_type": "public",
                "user_id": "",
                "username": "anonymous",
                "roles": [],
                "scopes": [],
            }
            if self.rate_limiter:
                rate_result = await self._apply_rate_limit(request, "ip")
                if rate_result is not None:
                    return rate_result
            return await call_next(request)

        # 尝试各种认证方式
        user_info = None
        auth_type = None
        auth_error = None

        try:
            # 方式 1: API Key 认证
            if self.api_key_validator is not None:
                api_key = extract_api_key(request, self.api_key_header_names)
                if api_key:
                    key_info = self.api_key_validator.validate(api_key)
                    if key_info:
                        user_info = {
                            "auth_type": "api_key",
                            "user_id": f"api_{key_info.key_name}",
                            "username": key_info.key_name,
                            "roles": key_info.roles or [],
                            "scopes": key_info.scopes or [],
                            "api_key_name": key_info.key_name,
                            "rate_limit": key_info.rate_limit,
                        }
                        auth_type = "api_key"

            # 方式 2: JWT Bearer Token 认证
            if user_info is None and self.jwt_handler is not None:
                token = extract_bearer_token(request)
                if token:
                    payload = self.jwt_handler.decode_token(token, token_type="access")
                    if payload:
                        # 黑名单检查
                        jti = payload.get("jti")
                        if jti and self.token_blacklist_checker:
                            try:
                                if self.token_blacklist_checker(jti):
                                    auth_error = "Token 已失效"
                                    payload = None
                            except Exception:
                                pass  # 黑名单检查失败不影响主流程

                        if payload:
                            user_info = {
                                "auth_type": "jwt",
                                "user_id": payload.get("sub", ""),
                                "username": payload.get("username", ""),
                                "roles": payload.get("roles", []),
                                "scopes": payload.get("scopes", []),
                                "jti": jti,
                            }
                            auth_type = "jwt"
        except Exception as e:
            # 认证服务异常，根据降级模式处理
            logger.error(f"认证服务异常: {e}", exc_info=True)
            if self.fallback_mode == "permissive":
                request.state.user = {
                    "auth_type": "fallback_permissive",
                    "user_id": "",
                    "username": "fallback",
                    "roles": [],
                    "scopes": [],
                }
                return await call_next(request)
            elif self.fallback_mode == "public_only":
                # 仅公开路径已在前面放行，这里直接拒绝
                return self._auth_failed_response("认证服务暂不可用", 503)
            # strict 模式：继续往下走，返回 401

        # 认证成功
        if user_info is not None:
            request.state.user = user_info

            # 速率限制
            if self.rate_limiter:
                rate_result = await self._apply_rate_limit(
                    request, self.rate_limit_by, user_info
                )
                if rate_result is not None:
                    return rate_result

            # 审计日志（成功）
            if self.audit_logger:
                try:
                    self.audit_logger.log_auth(
                        request, "success", auth_type, user_info
                    )
                except Exception:
                    pass

            return await call_next(request)

        # 认证失败
        if self.require_auth:
            # 审计日志（失败）
            if self.audit_logger:
                try:
                    self.audit_logger.log_auth(
                        request, "failed", None, None,
                        auth_error or "未提供有效认证凭证"
                    )
                except Exception:
                    pass

            return self._auth_failed_response(
                auth_error or "未认证或认证已过期"
            )

        # 不强制认证（可选认证模式）
        request.state.user = {
            "auth_type": "none",
            "user_id": "",
            "username": "anonymous",
            "roles": [],
            "scopes": [],
        }
        return await call_next(request)

    async def _apply_rate_limit(
        self,
        request: Request,
        rate_by: str,
        user_info: Optional[Dict[str, Any]] = None,
    ) -> Optional[Response]:
        """应用速率限制

        Returns:
            被限流时返回 429 响应，否则返回 None
        """
        if self.rate_limiter is None:
            return None

        # 确定限流键
        if rate_by == "api_key" and user_info and user_info.get("auth_type") == "api_key":
            rate_key = f"api:{user_info.get('api_key_name', 'unknown')}"
            custom_limit = user_info.get("rate_limit", 0)
        elif rate_by == "user" and user_info and user_info.get("user_id"):
            rate_key = f"user:{user_info['user_id']}"
            custom_limit = 0
        else:
            client_ip = request.client.host if request.client else "unknown"
            rate_key = f"ip:{client_ip}"
            custom_limit = 0

        limit = custom_limit if custom_limit > 0 else None
        allowed, remaining, window = self.rate_limiter.check(rate_key, limit)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "message": f"请求过于频繁，请 {window} 秒后重试",
                    "data": {"retry_after": window},
                },
                headers={
                    "X-RateLimit-Limit": str(
                        custom_limit if custom_limit > 0
                        else getattr(self.rate_limiter, 'default_limit', 'unknown')
                    ),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(window),
                },
            )

        return None

    def _auth_failed_response(self, detail: str, status_code: int = 401) -> JSONResponse:
        """生成认证失败响应

        Args:
            detail: 错误详情
            status_code: HTTP 状态码

        Returns:
            JSON 响应
        """
        return JSONResponse(
            status_code=status_code,
            content={
                "code": status_code,
                "message": detail,
                "data": None,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
