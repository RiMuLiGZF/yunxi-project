"""
云汐 API 网关 - 速率限制中间件
"""
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from ..services.rate_limiter import get_rate_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件"""
    
    async def dispatch(self, request: Request, call_next):
        # 获取客户端IP
        client_ip = self._get_client_ip(request)
        
        # 检查速率限制
        rate_limiter = get_rate_limiter()
        allowed = await rate_limiter.check_rate_limit(client_ip)
        
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "message": "Too Many Requests - Rate limit exceeded",
                    "data": None,
                },
                headers={
                    "X-RateLimit-Limit": str(rate_limiter.per_ip_limit),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": "60",
                },
            )
        
        # 继续处理
        response = await call_next(request)
        
        # 添加限速响应头
        stats = rate_limiter.get_stats()
        response.headers["X-RateLimit-Limit"] = str(stats["per_ip_limit"])
        response.headers["X-RateLimit-Remaining"] = str(
            int(rate_limiter._ip_tokens.get(client_ip, stats["per_ip_limit"]))
        )
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实IP"""
        # 优先从 X-Forwarded-For 获取
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        
        # 其次从 X-Real-IP 获取
        xri = request.headers.get("X-Real-IP")
        if xri:
            return xri
        
        # 最后使用连接IP
        return request.client.host if request.client else "unknown"
