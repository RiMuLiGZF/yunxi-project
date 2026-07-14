"""
M8 中间件模块
"""
from .waf_middleware import WafMiddleware, register_waf_middleware

__all__ = ["WafMiddleware", "register_waf_middleware"]
