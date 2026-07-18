"""
云汐系统 i18n 国际化框架
========================

提供多语言支持，包括：
- 核心翻译管理（I18nManager）
- 语言检测与切换
- 翻译资源加载（JSON / YAML）
- 变量替换与复数形式
- FastAPI 中间件与依赖注入
- 日期时间本地化
- 数字与货币格式化

默认语言：zh-CN（简体中文）
支持语言：zh-CN, en-US, ja-JP

使用方式：
    from shared.i18n import get_i18n, _

    i18n = get_i18n()
    print(i18n.t("common.ok"))
    print(_("common.cancel"))
"""

from .core import I18nManager, get_i18n, t, _
from .middleware import I18nMiddleware
from .dependencies import get_current_language, gettext
from .utils import (
    format_number,
    format_currency,
    format_date,
    format_time,
    format_datetime,
    relative_time,
    get_text_direction,
)
from .datetime_localizer import DateTimeLocalizer

__version__ = "1.2.0"
__all__ = [
    "I18nManager",
    "get_i18n",
    "t",
    "_",
    "I18nMiddleware",
    "get_current_language",
    "gettext",
    "format_number",
    "format_currency",
    "format_date",
    "format_time",
    "format_datetime",
    "relative_time",
    "get_text_direction",
    "DateTimeLocalizer",
]
