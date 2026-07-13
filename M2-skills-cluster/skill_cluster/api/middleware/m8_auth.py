"""M8 管理平台 Token 鉴权中间件.

为 M2 的 v2 API 提供 M8 管理平台的 Token 鉴权能力。

安全策略：
- 生产环境：必须配置 M2_ADMIN_TOKEN，无 Token 拒绝启动
- 开发/测试环境：未配置 Token 时警告放行，方便调试
- 白名单接口：健康检查不需要鉴权
- 所有鉴权失败记录审计日志
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Awaitable, Callable

import structlog

logger = structlog.get_logger()

# FastAPI / Starlette 可选导入
_fastapi_available = False
try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    _fastapi_available = True
except ImportError:
    BaseHTTPMiddleware = object  # type: ignore[assignment, misc]
    Request = object  # type: ignore[assignment, misc]
    JSONResponse = object  # type: ignore[assignment, misc]
    Response = object  # type: ignore[assignment, misc]


from skill_cluster.error_codes import ErrorCode


# 白名单接口（不需要鉴权）
WHITE_LIST_PATHS = {
    "/health",
    "/api/v2/health",
    "/api/v1/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}


def _gen_request_id() -> str:
    """生成请求ID."""
    return str(uuid.uuid4())


class M8TokenAuthMiddleware(BaseHTTPMiddleware if _fastapi_available else object):
    """M8 管理平台 Token 鉴权中间件.

    从 X-M8-Token 请求头读取 Token，与预期 Token 比对。
    鉴权失败返回 401，使用 M2 统一错误码格式。

    Usage:
        app.add_middleware(
            M8TokenAuthMiddleware,
            expected_token=os.getenv("M2_ADMIN_TOKEN", ""),
            env="production",
        )
    """

    def __init__(
        self,
        app: object,
        expected_token: str = "",
        env: str = "production",
    ) -> None:
        if not _fastapi_available:
            raise RuntimeError("FastAPI/Starlette not installed")

        super().__init__(app)  # type: ignore[misc]
        self.expected_token = expected_token
        self.env = env
        self._audit_log: list[dict] = []  # 内存审计日志（生产环境应持久化）

        # 启动时检查
        if env == "production" and not expected_token:
            raise RuntimeError(
                "生产环境必须配置 M2_ADMIN_TOKEN 环境变量！"
                "请设置 export M2_ADMIN_TOKEN=<your-secure-token>"
            )

        if env in ("development", "testing") and not expected_token:
            logger.warning(
                "auth_disabled_in_dev",
                message="M2_ADMIN_TOKEN 未配置，M8 接口鉴权已禁用！生产环境必须配置！",
                env=env,
            )

    @property
    def auth_enabled(self) -> bool:
        """鉴权是否启用."""
        return bool(self.expected_token)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """处理请求鉴权."""
        path = request.url.path

        # 1. 白名单接口直接放行
        if self._is_white_list(path):
            response = await call_next(request)
            return response

        # 2. 读取 Token
        token = request.headers.get("X-M8-Token", "")

        # 3. 鉴权未启用（开发模式）
        if not self.auth_enabled:
            request.state.is_m8_admin = False  # type: ignore[attr-defined]
            request.state.m8_token_valid = False  # type: ignore[attr-defined]
            response = await call_next(request)
            response.headers["X-Warning"] = "auth-disabled"
            return response

        # 4. 校验 Token
        if not token or token != self.expected_token:
            request_id = _gen_request_id()
            # 记录审计日志
            self._log_auth_failure(
                path=path,
                client_ip=request.client.host if request.client else "unknown",
                reason="invalid_token" if token else "missing_token",
                request_id=request_id,
            )
            return JSONResponse(
                status_code=401,
                content={
                    "code": ErrorCode.PERMISSION_TOKEN_INVALID,
                    "message": "未授权：无效的 M8 管理令牌",
                    "data": {"detail": "invalid_m8_token" if token else "missing_m8_token"},
                    "trace_id": request_id,
                    "success": False,
                },
            )

        # 5. 鉴权通过
        request.state.is_m8_admin = True  # type: ignore[attr-defined]
        request.state.m8_token_valid = True  # type: ignore[attr-defined]

        response = await call_next(request)
        return response

    def _is_white_list(self, path: str) -> bool:
        """检查是否在白名单中."""
        if path in WHITE_LIST_PATHS:
            return True
        # 支持前缀匹配（如 /docs/oauth2-redirect）
        for wp in WHITE_LIST_PATHS:
            if path.startswith(wp + "/"):
                return True
        return False

    def _log_auth_failure(self, path: str, client_ip: str, reason: str, request_id: str) -> None:
        """记录鉴权失败审计日志."""
        entry = {
            "timestamp": time.time(),
            "path": path,
            "client_ip": client_ip,
            "reason": reason,
            "request_id": request_id,
        }
        self._audit_log.append(entry)
        # 最多保留 1000 条
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-500:]

        logger.warning(
            "auth_failure",
            path=path,
            client_ip=client_ip,
            reason=reason,
            request_id=request_id,
        )

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """获取审计日志（最近N条）."""
        return self._audit_log[-limit:]


def get_admin_token_from_env() -> str:
    """从环境变量读取管理员 Token."""
    return os.environ.get("M2_ADMIN_TOKEN", "")


def check_production_requirements(env: str, token: str) -> list[str]:
    """检查生产环境要求，返回缺失的配置项列表."""
    missing = []
    if env == "production" and not token:
        missing.append("M2_ADMIN_TOKEN")
    return missing
