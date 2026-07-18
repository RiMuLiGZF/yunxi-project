"""
i18n FastAPI 依赖注入
======================

提供 FastAPI 依赖注入函数，方便在路由中使用 i18n。

使用方式：
    from fastapi import Depends, FastAPI
    from shared.i18n.dependencies import get_i18n, gettext, _

    app = FastAPI()

    @app.get("/hello")
    def hello(i18n = Depends(get_i18n)):
        return {"message": i18n.t("common.greeting", name="云汐")}

    @app.get("/hello2")
    def hello2(_: gettext = Depends()):
        return {"message": _("common.ok")}
"""

from __future__ import annotations

from typing import Optional

from fastapi import Request, Depends

from .core import I18nManager, get_i18n as _get_global_i18n
from .middleware import get_language_from_request


def get_i18n(request: Request) -> I18nManager:
    """
    FastAPI 依赖：获取 i18n 管理器

    返回全局 i18n 管理器实例，当前语言已由中间件设置。

    使用方式：
        @app.get("/example")
        def example(i18n: I18nManager = Depends(get_i18n)):
            return i18n.t("common.ok")
    """
    return _get_global_i18n()


def get_current_language(request: Request) -> str:
    """
    FastAPI 依赖：获取当前语言代码

    使用方式：
        @app.get("/example")
        def example(lang: str = Depends(get_current_language)):
            return {"language": lang}
    """
    return get_language_from_request(request)


class gettext:
    """
    gettext 风格的翻译函数类（可作为 FastAPI 依赖）

    使用方式：
        @app.get("/example")
        def example(_: gettext = Depends()):
            return {"message": _("common.ok")}

    也可以直接调用：
        _ = gettext()
        print(_("common.cancel"))
    """

    def __init__(self, language: Optional[str] = None, request: Optional[Request] = None):
        """
        初始化翻译函数

        Args:
            language: 目标语言，不传则使用当前上下文语言
            request: FastAPI 请求对象（由依赖注入自动传入）
        """
        self._i18n = _get_global_i18n()
        if language:
            self._language = language
        elif request is not None:
            self._language = get_language_from_request(request)
        else:
            self._language = None

    def __call__(self, key: str, **kwargs) -> str:
        """
        翻译函数调用

        Args:
            key: 翻译键
            **kwargs: 变量替换参数

        Returns:
            翻译后的文本
        """
        return self._i18n.t(key, language=self._language, **kwargs)

    def t(self, key: str, **kwargs) -> str:
        """翻译方法（与 __call__ 相同）"""
        return self(key, **kwargs)

    def set_language(self, lang: str) -> None:
        """设置语言"""
        self._language = lang

    @property
    def language(self) -> str:
        """当前语言"""
        return self._language or self._i18n.default_language


# 便捷别名
_ = gettext


def create_gettext(language: Optional[str] = None) -> gettext:
    """
    创建一个指定语言的翻译函数

    Args:
        language: 目标语言

    Returns:
        gettext 实例
    """
    return gettext(language=language)
