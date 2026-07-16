"""
云汐 API 网关 - 认证中间件
"""
import hashlib
import hmac
import time
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..config import settings


class AuthMiddleware(BaseHTTPMiddleware):
    """API网关认证中间件"""
    
    # 无需认证的白名单路径
    WHITE_LIST_PATHS = [
        "/health",
        "/m8/health",
        "/m8/metrics",
        "/favicon.ico",
        "/docs",
        "/openapi.json",
        "/redoc",
    ]
    
    # 各模块的白名单路径（转发时直接放行）
    MODULE_WHITE_LIST = {
        "m8": ["/health", "/m8/health", "/m8/metrics"],
    }
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # 检查是否是白名单路径
        if self._is_white_list(path):
            return await call_next(request)
        
        # 尝试 API Key 认证
        api_key = request.headers.get(settings.api_key_header)
        if api_key and self._validate_api_key(api_key):
            request.state.auth_method = "api_key"
            request.state.authenticated = True
            return await call_next(request)
        
        # 尝试 JWT Bearer Token 认证
        auth_header = request.headers.get(settings.jwt_header)
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if self._validate_jwt(token):
                request.state.auth_method = "jwt"
                request.state.authenticated = True
                return await call_next(request)
        
        # 未认证
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "code": 401,
                "message": "Unauthorized - API Key or Bearer Token required",
                "data": None,
            },
        )
    
    def _is_white_list(self, path: str) -> bool:
        """检查路径是否在白名单中"""
        for wp in self.WHITE_LIST_PATHS:
            if path == wp or path.startswith(wp + "/"):
                return True
        
        # 检查模块白名单
        for module_key, white_paths in self.MODULE_WHITE_LIST.items():
            prefix = f"/{module_key}"
            if path.startswith(prefix):
                remaining = path[len(prefix):]
                for wp in white_paths:
                    if remaining == wp or remaining.startswith(wp + "/"):
                        return True
        
        return False
    
    def _validate_api_key(self, api_key: str) -> bool:
        """验证 API Key"""
        import os
        
        # 从环境变量获取有效的 API Keys
        valid_keys = []
        for i in range(1, 10):
            key = os.getenv(f"GATEWAY_API_KEY_{i}")
            if key:
                valid_keys.append(key)
        
        # 默认测试 key（仅开发环境）
        if os.getenv("ENV", "development") == "development":
            valid_keys.append("yunxi-gateway-dev-key")
        
        return api_key in valid_keys
    
    def _validate_jwt(self, token: str) -> bool:
        """
        验证 JWT Token（简化版）
        
        完整实现需要对接 M8 的认证服务，这里做基础格式验证。
        生产环境应调用 M8 /api/v1/auth/verify 接口验证。
        """
        try:
            # JWT 格式验证：三段式 base64
            parts = token.split(".")
            if len(parts) != 3:
                return False
            
            # 基础校验通过（生产环境应调用M8验证）
            return True
        except Exception:
            return False
