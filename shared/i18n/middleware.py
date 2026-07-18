"""
i18n FastAPI 中间件
====================

提供请求级别的语言检测和上下文管理。

功能：
- Accept-Language 请求头解析
- 语言偏好 Cookie 读取
- 查询参数 lang 支持
- 语言上下文（contextvar）管理
- X-Content-Language 响应头设置
"""

from __future__ import annotations

from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .core import (
    I18nManager,
    get_i18n,
    set_current_language,
    get_current_language,
    _current_language_var,
)


class I18nMiddleware(BaseHTTPMiddleware):
    """
    i18n 国际化中间件

    从请求中检测用户语言偏好，并设置到上下文变量中。

    语言检测优先级：
    1. 查询参数 ?lang=xxx
    2. 用户偏好（从 request.state.user_preferences 读取，如果存在）
    3. Cookie: yunxi_lang
    4. Accept-Language 请求头
    5. 默认语言（zh-CN）

    使用方式：
        from fastapi import FastAPI
        from shared.i18n import I18nMiddleware

        app = FastAPI()
        app.add_middleware(I18nMiddleware)
    """

    def __init__(
        self,
        app,
        i18n_manager: Optional[I18nManager] = None,
        cookie_name: str = "yunxi_lang",
        query_param: str = "lang",
        header_name: str = "X-Content-Language",
    ):
        """
        初始化中间件

        Args:
            app: FastAPI 应用
            i18n_manager: i18n 管理器，默认使用全局单例
            cookie_name: 语言偏好 Cookie 名称
            query_param: 语言查询参数名
            header_name: 响应头中设置当前语言的字段名
        """
        super().__init__(app)
        self._i18n = i18n_manager or get_i18n()
        self._cookie_name = cookie_name
        self._query_param = query_param
        self._header_name = header_name

    async def dispatch(self, request: Request, call_next):
        """处理请求，检测语言并设置上下文"""
        # 检测语言
        lang = self._detect_language(request)

        # 设置到上下文
        token = _current_language_var.set(lang)

        # 将语言保存到 request.state，方便后续使用
        request.state.language = lang

        try:
            # 处理请求
            response: Response = await call_next(request)

            # 在响应头中添加当前语言信息
            if self._header_name:
                response.headers[self._header_name] = lang

            # Vary 头，确保缓存正确处理不同语言
            response.headers.setdefault("Vary", "")
            vary_values = [v.strip() for v in response.headers["Vary"].split(",") if v.strip()]
            if "Accept-Language" not in vary_values:
                vary_values.append("Accept-Language")
                response.headers["Vary"] = ", ".join(vary_values)

            return response
        finally:
            # 重置上下文
            _current_language_var.reset(token)

    def _detect_language(self, request: Request) -> str:
        """
        从请求中检测语言偏好

        优先级：查询参数 > 用户偏好 > Cookie > Accept-Language > 默认
        """
        # 1. 查询参数
        query_lang = request.query_params.get(self._query_param)
        if query_lang:
            normalized = self._i18n.normalize_language(query_lang)
            if self._i18n.is_supported(normalized):
                return normalized

        # 2. 用户偏好（从 request.state 读取，如果设置了）
        user_lang = None
        try:
            if hasattr(request.state, "user_preferences"):
                user_lang = request.state.user_preferences.get("language")
            elif hasattr(request.state, "user"):
                user_obj = request.state.user
                if hasattr(user_obj, "language"):
                    user_lang = user_obj.language
                elif isinstance(user_obj, dict):
                    user_lang = user_obj.get("language")
        except Exception:
            pass

        if user_lang:
            normalized = self._i18n.normalize_language(user_lang)
            if self._i18n.is_supported(normalized):
                return normalized

        # 3. Cookie
        cookie_lang = request.cookies.get(self._cookie_name)
        if cookie_lang:
            normalized = self._i18n.normalize_language(cookie_lang)
            if self._i18n.is_supported(normalized):
                return normalized

        # 4. Accept-Language 请求头
        accept_language = request.headers.get("Accept-Language")
        if accept_language:
            parsed = self._i18n._parse_accept_language(accept_language)
            for lang_code, _ in parsed:
                normalized = self._i18n.normalize_language(lang_code)
                if self._i18n.is_supported(normalized):
                    return normalized

        # 5. 默认语言
        return self._i18n.default_language


def get_language_from_request(request: Request) -> str:
    """
    从请求中获取当前语言

    优先从 request.state.language 获取（中间件设置的），
    否则从上下文变量获取。
    """
    if hasattr(request.state, "language"):
        return request.state.language
    return get_current_language()
