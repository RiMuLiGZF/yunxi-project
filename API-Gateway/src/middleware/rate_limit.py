"""
云汐 API 网关 - 速率限制中间件

支持分级限速：根据路径自动匹配限速级别，
敏感接口（登录、注册等）使用更严格的限速策略。
"""
import time
import re
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from ..services.rate_limiter import get_rate_limiter, RATE_LIMIT_TIERS


# 路径到限速级别的映射规则
# 按顺序匹配，第一个匹配的生效
PATH_TIER_RULES = [
    # 敏感接口 - 登录、注册、验证码
    (r"^.*/auth/login$", "sensitive"),
    (r"^.*/auth/register$", "sensitive"),
    (r"^.*/auth/password.*", "sensitive"),
    (r"^.*/auth/reset.*", "sensitive"),
    (r"^.*/auth/forgot.*", "sensitive"),
    (r"^.*/verify.*", "sensitive"),
    (r"^.*/captcha.*", "sensitive"),
    (r"^.*/otp.*", "sensitive"),
    (r"^.*/sms.*", "sensitive"),
    
    # 严格接口 - API Key 管理、管理员操作
    (r"^.*/admin.*", "admin"),
    (r"^.*/api-keys.*", "strict"),
    (r"^.*/settings/security.*", "strict"),
    
    # MCP 接口
    (r"^.*/mcp.*", "mcp"),
    (r"^.*/tools.*", "mcp"),
    
    # 默认公开接口
    (r"^.*$", "public"),
]


def _match_tier(path: str) -> str:
    """根据路径匹配限速级别.
    
    Args:
        path: 请求路径
    
    Returns:
        限速级别名称
    """
    for pattern, tier in PATH_TIER_RULES:
        if re.match(pattern, path, re.IGNORECASE):
            return tier
    return "public"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件（增强版）
    
    功能：
    - 分级限速（根据路径自动匹配）
    - 渐进式封禁（连续超限自动封禁）
    - 完整的限流响应头
    - 多种限速级别：public/sensitive/strict/admin/mcp
    """
    
    async def dispatch(self, request: Request, call_next):
        # 获取客户端IP
        client_ip = self._get_client_ip(request)
        path = request.url.path
        
        # 匹配限速级别
        tier = _match_tier(path)
        
        # 检查速率限制
        rate_limiter = get_rate_limiter()
        allowed, reason, limit_headers = await rate_limiter.check_rate_limit(
            ip=client_ip,
            tier=tier,
        )
        
        if not allowed:
            error_messages = {
                "ip_banned": "IP 已被临时封禁，请稍后再试",
                "tier_rate_limit_exceeded": "请求过于频繁，请稍后再试",
                "ip_rate_limit_exceeded": "IP 限流，请稍后再试",
                "global_rate_limit_exceeded": "系统繁忙，请稍后再试",
            }
            message = error_messages.get(reason, "Rate limit exceeded")
            trace_id = str(uuid.uuid4())

            # 尝试使用统一错误码体系的错误码
            try:
                from shared.core.errors import ErrorCode
                error_code = ErrorCode.RATE_LIMITED
            except (ImportError, AttributeError):
                error_code = 801  # 000801 = 系统通用-限流错误-请求频率超限

            # 构建响应头
            headers = {
                "Retry-After": limit_headers.get("Retry-After", "60"),
                "X-Trace-Id": trace_id,
            }
            for k, v in limit_headers.items():
                if k.startswith("X-RateLimit"):
                    headers[k] = v

            return JSONResponse(
                status_code=429,
                content={
                    "code": error_code,
                    "message": message,
                    "details": {
                        "reason": reason,
                        "tier": tier,
                        "retry_after": int(limit_headers.get("Retry-After", "60")),
                    },
                    "trace_id": trace_id,
                },
                headers=headers,
            )
        
        # 继续处理
        response = await call_next(request)
        
        # 添加限流响应头
        for k, v in limit_headers.items():
            if k.startswith("X-RateLimit") or k == "Retry-After":
                response.headers[k] = v
        
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
