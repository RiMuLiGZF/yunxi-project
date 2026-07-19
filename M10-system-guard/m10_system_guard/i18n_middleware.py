"""
M10 系统卫士 - i18n 中间件

从 HTTP 请求中提取语言偏好，设置到线程上下文中，
使翻译函数 t() 能自动使用当前请求的语言。
"""

from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .i18n import (
    extract_language_from_request,
    set_current_language,
    get_current_language,
)


class I18nMiddleware(BaseHTTPMiddleware):
    """
    i18n 国际化中间件。

    从请求中提取语言偏好并设置到上下文：
    - 查询参数：lang / locale
    - 请求头：X-Language / X-Lang / Accept-Language

    在响应头中返回当前使用的语言：X-Current-Language
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # 从请求中提取语言
        lang = extract_language_from_request(request)

        # 设置当前线程语言
        set_current_language(lang)

        # 处理请求
        response = await call_next(request)

        # 在响应头中添加当前语言信息
        response.headers["X-Current-Language"] = get_current_language()

        return response


def register_i18n_middleware(app) -> None:
    """
    为 FastAPI 应用注册 i18n 中间件。

    Args:
        app: FastAPI 应用实例
    """
    app.add_middleware(I18nMiddleware)
