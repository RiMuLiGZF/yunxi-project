"""
认证中间件

FastAPI HTTP 认证中间件 + 内部 AuthMiddleware 认证核心
支持 JWT Token、M8 内部调用 Token、API Key 多种认证方式
通过环境变量 M5_AUTH_ENABLED 控制开关（默认关闭，开发环境友好）
"""

from __future__ import annotations

import os
import base64
import json
import time
import uuid
from typing import Dict, Optional, Tuple

import structlog
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from tide_memory.errors import ErrorCode, error_response

logger = structlog.get_logger(__name__)


# ========== 公开端点（跳过认证） ==========

_PUBLIC_PATHS = (
    # 健康检查
    "/health",
    "/api/v1/health",
    "/m8/health",
    # 公开文档
    "/docs",
    "/openapi.json",
    "/redoc",
    # favicon
    "/favicon.ico",
)


def _is_public_path(path: str) -> bool:
    """判断路径是否为公开端点（跳过认证）"""
    return path in _PUBLIC_PATHS


# ========== AuthMiddleware 核心认证类 ==========


class AuthMiddleware:
    """
    认证中间件核心类

    功能：
    - JWT Token 验证
    - M8 内部调用 Token 验证
    - API Key 验证
    - Agent 身份识别
    - 域权限预校验
    - 请求速率限制
    - 请求审计记录
    """

    def __init__(
        self,
        domain_manager=None,
        audit_logger=None,
        secret_key: str = "",
        m8_token: str = "",
        api_key: str = "",
    ):
        self._domain = domain_manager
        self._audit = audit_logger
        self._secret_key = secret_key or ""
        self._m8_token = m8_token or ""
        self._api_key = api_key or ""
        self._rate_limits: Dict[str, dict] = {}  # agent_id -> {count, window_start}
        self._default_rate_limit = 1000  # 每小时1000次请求

    def authenticate(self, request: Dict) -> Tuple[bool, Dict]:
        """
        认证请求

        Args:
            request: 请求对象字典

        Returns:
            (是否通过, 认证信息)
        """
        # 1. 提取并验证 Token（支持多种认证方式）
        auth_result = self._extract_and_verify(request)
        if not auth_result[0]:
            return auth_result

        passed, agent_info = auth_result

        # 2. 速率限制检查
        agent_id = agent_info.get("agent_id", "unknown")
        if not self._check_rate_limit(agent_id):
            return False, {"error": "rate_limited", "agent_id": agent_id}

        # 3. 审计记录
        if self._audit:
            try:
                self._audit.record(
                    memory_id="auth",
                    operation="login",
                    agent_id=agent_id,
                    domain=agent_info.get("domain", "private"),
                    success=True,
                    metadata={"request_id": request.get("request_id", "")},
                )
            except Exception:
                pass

        return True, agent_info

    def _extract_and_verify(self, request: Dict) -> Tuple[bool, Dict]:
        """
        从请求中提取凭证并验证

        优先级：
        1. M8 内部调用 Token (x-m8-token)
        2. JWT Bearer Token (Authorization: Bearer xxx)
        3. API Key (x-api-key 或 Authorization: ApiKey xxx)
        """
        headers = request.get("headers", {})

        # 1. M8 内部调用 Token
        m8_token = headers.get("x-m8-token", "")
        if m8_token and self._m8_token:
            if m8_token == self._m8_token:
                return True, {
                    "agent_id": "m8-internal",
                    "role": "internal",
                    "domain": "system",
                    "auth_type": "m8_token",
                }
            return False, {"error": "invalid_m8_token", "agent_id": "unknown"}

        # 2. JWT Bearer Token
        auth_header = headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token:
                agent_info = self._verify_jwt(token)
                if agent_info:
                    agent_info["auth_type"] = "jwt"
                    return True, agent_info
                return False, {"error": "invalid_token", "agent_id": "unknown"}

        # 3. API Key
        api_key = headers.get("x-api-key", "")
        if not api_key and auth_header.startswith("ApiKey "):
            api_key = auth_header[7:]

        if api_key and self._api_key:
            if api_key == self._api_key:
                return True, {
                    "agent_id": "api-key-user",
                    "role": "normal",
                    "domain": "private",
                    "auth_type": "api_key",
                }
            return False, {"error": "invalid_api_key", "agent_id": "unknown"}

        # 未提供任何凭证
        if not auth_header and not m8_token and not api_key:
            return False, {"error": "missing_credentials", "agent_id": "anonymous"}

        return False, {"error": "invalid_auth_format", "agent_id": "unknown"}

    def _verify_jwt(self, token: str) -> Optional[Dict]:
        """
        验证 JWT Token

        ⚠️ 当前为框架级实现：解码 payload 但不验证签名
        生产环境应使用 PyJWT 等库进行完整签名验证
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                # 非标准 JWT 格式，作为简单 token 处理
                return {
                    "agent_id": token[:16],
                    "role": "normal",
                    "domain": "private",
                }

            # 解码 payload
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))

            # 检查过期时间（如果有）
            exp = payload.get("exp")
            if exp and isinstance(exp, (int, float)):
                if time.time() > exp:
                    return None

            return {
                "agent_id": payload.get("sub", "unknown"),
                "role": payload.get("role", "normal"),
                "domain": payload.get("domain", "private"),
                "exp": exp,
            }
        except Exception:
            return None

    def _check_rate_limit(self, agent_id: str) -> bool:
        """检查速率限制"""
        now = int(time.time())
        window = 3600  # 1小时窗口

        if agent_id not in self._rate_limits:
            self._rate_limits[agent_id] = {"count": 0, "window_start": now}

        info = self._rate_limits[agent_id]

        # 重置窗口
        if now - info["window_start"] > window:
            info["count"] = 0
            info["window_start"] = now

        info["count"] += 1
        return info["count"] <= self._default_rate_limit

    def check_domain_permission(self, agent_id: str, domain: str, action: str) -> bool:
        """检查域权限"""
        if self._domain:
            return self._domain.check_permission(agent_id, domain, action)
        return True  # 无管理器时默认允许

    def get_auth_stats(self) -> Dict:
        """获取认证统计"""
        return {
            "total_agents_tracked": len(self._rate_limits),
            "rate_limit": self._default_rate_limit,
        }


# ========== FastAPI HTTP 认证中间件 ==========


class FastAPIAuthMiddleware(BaseHTTPMiddleware):
    """
    FastAPI 认证中间件

    作为 HTTP 中间件挂载到 FastAPI 应用，在请求到达路由之前进行认证。
    通过环境变量控制开关，默认关闭。

    环境变量：
    - M5_AUTH_ENABLED: 是否启用认证（"true"/"1" 启用，默认关闭）
    - M5_JWT_SECRET: JWT 签名密钥（可选，当前未做签名验证）
    - M5_M8_TOKEN: M8 内部调用 token（可选）
    - M5_API_KEY: API Key 认证密钥（可选）
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self._enabled = self._read_bool_env("M5_AUTH_ENABLED", default=False)
        self._secret_key = os.environ.get("M5_JWT_SECRET", "")
        self._m8_token = os.environ.get("M5_M8_TOKEN", "")
        self._api_key = os.environ.get("M5_API_KEY", "")
        self._auth_core = AuthMiddleware(
            secret_key=self._secret_key,
            m8_token=self._m8_token,
            api_key=self._api_key,
        )

        # 启动时日志
        enabled_methods = []
        if self._m8_token:
            enabled_methods.append("m8_token")
        if self._api_key:
            enabled_methods.append("api_key")
        enabled_methods.append("jwt")  # JWT 总是可用（框架级）

        logger.info(
            "auth_middleware_init",
            enabled=self._enabled,
            auth_methods=enabled_methods,
            public_paths=list(_PUBLIC_PATHS),
        )

    @staticmethod
    def _read_bool_env(name: str, default: bool = False) -> bool:
        """读取布尔型环境变量"""
        val = os.environ.get(name, "").strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off"):
            return False
        return default

    async def dispatch(self, request: Request, call_next):
        """
        中间件核心逻辑

        1. 认证关闭 → 直接放行
        2. 公开路径 → 直接放行
        3. 其他请求 → 验证凭证
        """
        # 认证未启用，直接放行
        if not self._enabled:
            return await call_next(request)

        path = request.url.path

        # 公开端点跳过认证
        if _is_public_path(path):
            logger.debug("auth_skip_public_path", path=path)
            return await call_next(request)

        # 生成 request_id
        request_id = getattr(request.state, "request_id", None)
        if not request_id:
            request_id = request.headers.get("x-request-id", f"m5-{uuid.uuid4().hex[:12]}")
            request.state.request_id = request_id

        # 构造认证请求字典
        auth_req = {
            "headers": dict(request.headers),
            "path": path,
            "method": request.method,
            "request_id": request_id,
        }

        # 执行认证
        passed, auth_info = self._auth_core.authenticate(auth_req)

        if not passed:
            error_type = auth_info.get("error", "unauthorized")
            agent_id = auth_info.get("agent_id", "unknown")

            logger.warning(
                "auth_failed",
                request_id=request_id,
                path=path,
                method=request.method,
                error=error_type,
                agent_id=agent_id,
            )

            # 映射错误消息
            message_map = {
                "missing_credentials": "未提供认证凭证",
                "invalid_token": "无效的认证 Token",
                "invalid_m8_token": "无效的 M8 内部调用 Token",
                "invalid_api_key": "无效的 API Key",
                "invalid_auth_format": "认证格式无效",
                "rate_limited": "请求过于频繁",
            }
            message = message_map.get(error_type, "未授权访问")

            # 速率限制返回 429
            if error_type == "rate_limited":
                resp = error_response(
                    code=ErrorCode.RATE_LIMITED,
                    message=message,
                    data={"error": error_type},
                    request_id=request_id,
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content=resp,
                )

            # 其他认证失败返回 401
            resp = error_response(
                code=ErrorCode.UNAUTHORIZED,
                message=message,
                data={"error": error_type},
                request_id=request_id,
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content=resp,
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 认证通过，将认证信息存入 request.state
        request.state.auth_info = auth_info
        request.state.agent_id = auth_info.get("agent_id", "unknown")

        logger.debug(
            "auth_passed",
            request_id=request_id,
            path=path,
            method=request.method,
            agent_id=auth_info.get("agent_id"),
            auth_type=auth_info.get("auth_type"),
        )

        response = await call_next(request)
        return response

    @property
    def enabled(self) -> bool:
        """认证是否启用"""
        return self._enabled

    def get_stats(self) -> Dict:
        """获取认证中间件统计"""
        return {
            "enabled": self._enabled,
            "has_m8_token": bool(self._m8_token),
            "has_api_key": bool(self._api_key),
            "has_jwt_secret": bool(self._secret_key),
            **self._auth_core.get_auth_stats(),
        }


__all__ = ["AuthMiddleware", "FastAPIAuthMiddleware"]
# vim: set et ts=4 sw=4:
