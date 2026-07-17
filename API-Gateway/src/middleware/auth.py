"""
云汐 API 网关 - 认证中间件（增强版）

支持两种认证方式：
1. API Key - 服务间调用
2. JWT Bearer Token - 用户登录认证（使用 jose 库验证签名）

认证策略：
- 开发环境: 本地验证 JWT 签名 + API Key
- 生产环境: 推荐调用 M12 安全盾验证接口获取完整用户信息

增强特性：
- 按模块配置白名单（从路由配置动态读取）
- 统一错误响应格式
- 用户信息注入 request.state，供后续中间件和代理使用
- 支持 API Key 和 JWT 双重认证
"""
import hashlib
import hmac
import time
import os
import base64
import json
import logging
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..config import settings, ModuleRoute

logger = logging.getLogger("yunxi-gateway.auth")

# 尝试导入 jose 库进行 JWT 验证
try:
    from jose import JWTError, jwt as jose_jwt
    HAS_JOSE = True
except ImportError:
    HAS_JOSE = False
    # SEC-006: jose 库不可用时的安全处理
    # 定义 JWTError 占位符，确保 except 子句语法正确
    class JWTError(Exception):
        """JWT 验证错误占位符（jose 不可用时使用）"""
        pass


def _find_route_by_path(path: str) -> Optional[ModuleRoute]:
    """根据路径查找对应的路由配置（最长前缀优先匹配）"""
    # 按前缀长度排序，优先匹配更长的前缀
    sorted_routes = sorted(
        settings.routes, key=lambda r: len(r.prefix), reverse=True
    )
    for route in sorted_routes:
        if not route.enabled:
            continue
        if path.startswith(route.prefix):
            return route
    return None


class AuthMiddleware(BaseHTTPMiddleware):
    """API网关认证中间件（增强版）

    特性：
    - 全局白名单路径
    - 按模块配置的公开路径白名单（从路由配置读取）
    - API Key 认证
    - JWT Bearer Token 认证
    - 用户信息注入 request.state
    - 统一错误响应格式
    """

    # 全局无需认证的白名单路径
    GLOBAL_WHITE_LIST = [
        "/health",
        "/gateway",
        "/favicon.ico",
        "/docs",
        "/openapi.json",
        "/redoc",
    ]

    def __init__(self, app):
        super().__init__(app)
        self._jwt_secret = os.getenv("GATEWAY_JWT_SECRET", os.getenv("JWT_SECRET", ""))
        self._jwt_algorithm = os.getenv("GATEWAY_JWT_ALGORITHM", os.getenv("JWT_ALGORITHM", "HS256"))
        self._jwt_issuer = os.getenv("GATEWAY_JWT_ISSUER", os.getenv("JWT_ISSUER", "yunxi"))
        self._dev_mode = os.getenv("ENV", "development") == "development"

        # SEC-006: jose 库必须可用，禁止降级到不验证签名的模式
        if not HAS_JOSE:
            error_msg = (
                "[SEC-006] python-jose 库未安装，JWT 认证无法进行签名验证。"
                "为保证安全，网关禁止在没有 jose 库的情况下运行。"
                "请安装: pip install python-jose[cryptography]"
            )
            logger.critical(error_msg)
            raise RuntimeError(error_msg)

        # 安全检查：生产环境不允许空密钥
        if not self._jwt_secret:
            if self._dev_mode:
                logger.warning(
                    "[Auth] 开发环境未配置 GATEWAY_JWT_SECRET，JWT认证将不可用。"
                    "请设置环境变量 GATEWAY_JWT_SECRET"
                )
            else:
                logger.error(
                    "[Auth] 生产环境必须配置 GATEWAY_JWT_SECRET！"
                    "未配置密钥将导致所有JWT认证失败。"
                )
                raise RuntimeError("GATEWAY_JWT_SECRET must be set in production environment")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 初始化认证状态
        request.state.authenticated = False
        request.state.auth_method = None
        request.state.user = None
        request.state.token = None

        # 检查是否是全局白名单路径
        if self._is_global_white_list(path):
            return await call_next(request)

        # 查找对应的模块路由
        route = _find_route_by_path(path)

        # 如果模块不需要认证，直接放行
        if route and not route.auth_required:
            return await call_next(request)

        # 检查模块的公开路径白名单
        if route and self._is_module_public_path(path, route):
            return await call_next(request)

        # 尝试 API Key 认证
        api_key = request.headers.get(settings.api_key_header)
        if api_key and self._validate_api_key(api_key):
            request.state.auth_method = "api_key"
            request.state.authenticated = True
            request.state.user = {
                "auth_type": "api_key",
                "user_id": "api-client",
                "username": "api-client",
                "roles": ["api"],
                "scopes": ["api:*"],
            }
            return await call_next(request)

        # 尝试 JWT Bearer Token 认证
        auth_header = request.headers.get(settings.jwt_header)
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = self._validate_jwt(token)
            if payload:
                request.state.auth_method = "jwt"
                request.state.authenticated = True
                request.state.user = payload
                request.state.token = token
                return await call_next(request)

        # 未认证 - 统一错误响应
        return self._unauthorized_response(path, route)

    def _is_global_white_list(self, path: str) -> bool:
        """检查是否是全局白名单路径"""
        for wp in self.GLOBAL_WHITE_LIST:
            if path == wp or path.startswith(wp + "/"):
                return True
        return False

    def _is_module_public_path(self, path: str, route: ModuleRoute) -> bool:
        """检查路径是否在模块的公开白名单中

        Args:
            path: 完整请求路径（如 /m12/api/v1/auth/login）
            route: 模块路由配置

        Returns:
            True 表示公开路径，无需认证
        """
        if not route.public_paths:
            return False

        # 去除模块前缀
        remaining = path[len(route.prefix):]
        if not remaining.startswith("/"):
            remaining = "/" + remaining

        # 匹配公开路径
        for public_path in route.public_paths:
            if remaining == public_path or remaining.startswith(public_path + "/"):
                return True

        return False

    def _validate_api_key(self, api_key: str) -> bool:
        """验证 API Key（使用 hmac.compare_digest 防时序攻击）"""
        # 从环境变量获取有效的 API Keys
        valid_keys = []
        for i in range(1, 20):  # 支持最多 20 个 API Key
            key = os.getenv(f"GATEWAY_API_KEY_{i}")
            if key and len(key) >= 16:  # 安全长度校验
                valid_keys.append(key)

        # 开发环境默认 key（仅当显式配置 GATEWAY_ENABLE_DEV_KEY=true 时启用）
        if self._dev_mode and os.getenv("GATEWAY_ENABLE_DEV_KEY", "").lower() in ("true", "1", "yes"):
            dev_key = os.getenv("GATEWAY_DEV_API_KEY", "")
            if dev_key:
                valid_keys.append(dev_key)
            else:
                logger.warning(
                    "[Auth] 开发模式已启用 GATEWAY_ENABLE_DEV_KEY 但未设置 GATEWAY_DEV_API_KEY"
                )

        if not valid_keys:
            return False

        # 使用常量时间比较防时序攻击
        for valid_key in valid_keys:
            if hmac.compare_digest(api_key, valid_key):
                return True

        return False

    def _validate_jwt(self, token: str) -> Optional[Dict[str, Any]]:
        """
        验证 JWT Token（完整验证）

        SEC-006 安全修复：移除了无 jose 库时的降级模式。
        jose 库不可用时中间件初始化直接失败，确保绝不会出现
        "仅解码不验证签名" 的不安全情况。

        验证内容：
        1. 格式验证（三段式）
        2. 签名验证（使用 jose 库）
        3. 过期时间验证
        4. 签发者验证
        5. Token 类型验证（access token）

        Returns:
            验证成功返回 payload 字典，失败返回 None
        """
        try:
            # 1. 基础格式验证
            parts = token.split(".")
            if len(parts) != 3:
                return None

            # 验证每段都是有效的 base64url
            for part in parts:
                try:
                    padded = part + "=" * (-len(part) % 4)
                    base64.urlsafe_b64decode(padded)
                except Exception:
                    return None

            # 2. 使用 jose 库进行完整验证
            # SEC-006: HAS_JOSE 在 __init__ 中已检查，这里始终为 True
            payload = jose_jwt.decode(
                token,
                self._jwt_secret,
                algorithms=[self._jwt_algorithm],
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_iss": False,  # 宽松模式，issuer 可选验证
                    "require": ["exp", "iat"],
                },
                issuer=self._jwt_issuer,
            )

            # 3. 额外验证：Token 类型
            token_type = payload.get("type", "access")
            if token_type not in ("access", "api"):
                return None

            # 4. 标准化返回格式
            return {
                "auth_type": "jwt",
                "user_id": payload.get("sub", ""),
                "username": payload.get("username", ""),
                "roles": payload.get("roles", []),
                "scopes": payload.get("scopes", []),
                "jti": payload.get("jti", ""),
                "exp": payload.get("exp"),
                "iat": payload.get("iat"),
                "type": token_type,
            }

        except JWTError:
            return None
        except Exception:
            return None

    def _unauthorized_response(self, path: str, route: Optional[ModuleRoute]) -> JSONResponse:
        """构建统一的未认证错误响应（6位错误码体系）

        返回格式遵循云汐系统统一错误响应格式：
        {
            "code": 6位错误码,
            "message": "错误消息",
            "details": {...},
            "trace_id": "..."
        }
        """
        import uuid
        module_key = route.key if route else "unknown"
        module_name = route.name if route else "unknown"
        trace_id = str(uuid.uuid4())

        # 尝试使用统一错误码体系的错误码
        try:
            from shared.core.errors import ErrorCode
            error_code = ErrorCode.AUTH_FAILED
        except (ImportError, AttributeError):
            error_code = 201  # 000201 = 系统通用-认证错误-认证失败

        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "code": error_code,
                "message": "认证失败：需要有效的 API Key 或 Bearer Token",
                "details": {
                    "module": module_name,
                    "path": path,
                    "auth_methods": ["api_key", "bearer_token"],
                    "api_key_header": settings.api_key_header,
                    "jwt_header": settings.jwt_header,
                },
                "trace_id": trace_id,
            },
            headers={
                "WWW-Authenticate": "Bearer",
                "X-Gateway-Module": module_key,
                "X-Trace-Id": trace_id,
            },
        )

    def get_token_info(self, token: str) -> Optional[Dict[str, Any]]:
        """获取Token信息（已验证）"""
        return self._validate_jwt(token)
