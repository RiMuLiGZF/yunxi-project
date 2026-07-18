"""
i18n 工具函数
==============

提供数字格式化、日期格式化、相对时间、文本方向等本地化工具。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional, Union

from .core import get_i18n, get_current_language


# ------------------------------------------------------------------
# 数字格式化
# ------------------------------------------------------------------

def format_number(
    value: Union[int, float],
    language: Optional[str] = None,
    decimals: int = 0,
) -> str:
    """
    数字格式化（千分位分隔）

    Args:
        value: 数字值
        language: 目标语言，默认当前语言
        decimals: 小数位数

    Returns:
        格式化后的数字字符串

    示例：
        format_number(1234567.89, "en-US")  # "1,234,567.89"
        format_number(1234567.89, "zh-CN")  # "1,234,567.89"
    """
    lang = language or get_current_language()

    # 根据语言确定千分位和小数点分隔符
    if lang.startswith("de"):
        thousands_sep = "."
        decimal_sep = ","
    elif lang.startswith("fr"):
        thousands_sep = " "
        decimal_sep = ","
    else:
        # 中文、英文、日文等
        thousands_sep = ","
        decimal_sep = "."

    # 处理负数
    is_negative = value < 0
    value = abs(value)

    # 格式化小数部分
    if decimals > 0:
        value = round(value, decimals)
        integer_part = int(value)
        decimal_part = f"{value - integer_part:.{decimals}f}"[2:]
    else:
        integer_part = int(round(value))
        decimal_part = ""

    # 添加千分位分隔符
    integer_str = str(integer_part)
    if len(integer_str) > 3:
        groups = []
        while integer_str:
            groups.append(integer_str[-3:])
            integer_str = integer_str[:-3]
        integer_str = thousands_sep.join(reversed(groups))

    result = integer_str
    if decimal_part:
        result += decimal_sep + decimal_part

    if is_negative:
        result = "-" + result

    return result


def format_currency(
    value: Union[int, float],
    currency: str = "CNY",
    language: Optional[str] = None,
    decimals: int = 2,
) -> str:
    """
    货币格式化

    Args:
        value: 金额
        currency: 货币代码（CNY, USD, JPY 等）
        language: 目标语言
        decimals: 小数位数

    Returns:
        格式化后的货币字符串

    示例：
        format_currency(1234.56, "CNY", "zh-CN")  # "¥1,234.56"
        format_currency(1234.56, "USD", "en-US")  # "$1,234.56"
        format_currency(1234, "JPY", "ja-JP")     # "¥1,234"
    """
    lang = language or get_current_language()

    # 货币符号映射
    currency_symbols = {
        "CNY": "¥",
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "JPY": "¥",
        "KRW": "₩",
        "HKD": "HK$",
        "TWD": "NT$",
        "SGD": "S$",
        "AUD": "A$",
        "CAD": "C$",
        "CHF": "CHF ",
        "RUB": "₽",
        "INR": "₹",
        "BRL": "R$",
    }

    symbol = currency_symbols.get(currency, currency + " ")

    # 日元、韩元等通常不显示小数
    if currency in ("JPY", "KRW") and decimals == 2:
        decimals = 0

    formatted_number = format_number(value, lang, decimals)

    # 符号位置
    if lang.startswith("fr") or lang.startswith("de"):
        return f"{formatted_number} {symbol}"
    else:
        return f"{symbol}{formatted_number}"


# ------------------------------------------------------------------
# 日期时间格式化
# ------------------------------------------------------------------

def format_date(
    dt: Union[datetime, str],
    language: Optional[str] = None,
    format_style: str = "medium",
) -> str:
    """
    日期格式化

    Args:
        dt: 日期时间对象或字符串
        language: 目标语言
        format_style: 格式风格（short, medium, long, full）

    Returns:
        格式化后的日期字符串
    """
    lang = language or get_current_language()

    if isinstance(dt, str):
        dt = _parse_datetime(dt)

    # 语言相关的日期格式
    format_map = {
        "zh-CN": {
            "short": "%Y/%m/%d",
            "medium": "%Y年%m月%d日",
            "long": "%Y年%m月%d日 %A",
            "full": "%Y年%m月%d日 %A %B",
        },
        "en-US": {
            "short": "%m/%d/%Y",
            "medium": "%b %d, %Y",
            "long": "%B %d, %Y",
            "full": "%A, %B %d, %Y",
        },
        "ja-JP": {
            "short": "%Y/%m/%d",
            "medium": "%Y年%m月%d日",
            "long": "%Y年%m月%d日 %A",
            "full": "%Y年%m月%d日 %A %B",
        },
    }

    normalized_lang = get_i18n().normalize_language(lang)
    fmt = format_map.get(normalized_lang, format_map["en-US"]).get(
        format_style, format_map["en-US"]["medium"]
    )

    # 本地化星期和月份名称
    result = dt.strftime(fmt)
    result = _localize_date_names(result, normalized_lang)

    return result


def format_time(
    dt: Union[datetime, str],
    language: Optional[str] = None,
    format_style: str = "medium",
    with_seconds: bool = True,
) -> str:
    """
    时间格式化

    Args:
        dt: 日期时间对象或字符串
        language: 目标语言
        format_style: 格式风格（short, medium, long）
        with_seconds: 是否包含秒

    Returns:
        格式化后的时间字符串
    """
    lang = language or get_current_language()

    if isinstance(dt, str):
        dt = _parse_datetime(dt)

    normalized_lang = get_i18n().normalize_language(lang)

    # 12小时制还是24小时制
    if normalized_lang == "en-US":
        if with_seconds:
            return dt.strftime("%I:%M:%S %p")
        else:
            return dt.strftime("%I:%M %p")
    else:
        # 中文、日文等使用24小时制
        if with_seconds:
            return dt.strftime("%H:%M:%S")
        else:
            return dt.strftime("%H:%M")


def format_datetime(
    dt: Union[datetime, str],
    language: Optional[str] = None,
    date_style: str = "medium",
    time_style: str = "medium",
) -> str:
    """
    日期时间格式化

    Args:
        dt: 日期时间对象或字符串
        language: 目标语言
        date_style: 日期格式风格
        time_style: 时间格式风格

    Returns:
        格式化后的日期时间字符串
    """
    lang = language or get_current_language()
    date_str = format_date(dt, lang, date_style)
    time_str = format_time(dt, lang, time_style)

    normalized_lang = get_i18n().normalize_language(lang)

    if normalized_lang == "zh-CN" or normalized_lang == "ja-JP":
        return f"{date_str} {time_str}"
    else:
        return f"{date_str}, {time_str}"


def _parse_datetime(dt_str: str) -> datetime:
    """解析日期时间字符串"""
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue

    raise ValueError(f"无法解析日期时间字符串: {dt_str}")


def _localize_date_names(text: str, lang: str) -> str:
    """本地化日期名称（星期、月份）"""
    weekday_map = {
        "zh-CN": {
            "Monday": "星期一",
            "Tuesday": "星期二",
            "Wednesday": "星期三",
            "Thursday": "星期四",
            "Friday": "星期五",
            "Saturday": "星期六",
            "Sunday": "星期日",
        },
        "ja-JP": {
            "Monday": "月曜日",
            "Tuesday": "火曜日",
            "Wednesday": "水曜日",
            "Thursday": "木曜日",
            "Friday": "金曜日",
            "Saturday": "土曜日",
            "Sunday": "日曜日",
        },
    }

    month_map = {
        "zh-CN": {
            "January": "一月", "February": "二月", "March": "三月",
            "April": "四月", "May": "五月", "June": "六月",
            "July": "七月", "August": "八月", "September": "九月",
            "October": "十月", "November": "十一月", "December": "十二月",
        },
        "ja-JP": {
            "January": "1月", "February": "2月", "March": "3月",
            "April": "4月", "May": "5月", "June": "6月",
            "July": "7月", "August": "8月", "September": "9月",
            "October": "10月", "November": "11月", "December": "12月",
        },
    }

    if lang in weekday_map:
        for en, localized in weekday_map[lang].items():
            text = text.replace(en, localized)
        # 处理缩写
        short_weekdays = {
            "zh-CN": {"Mon": "周一", "Tue": "周二", "Wed": "周三",
                      "Thu": "周四", "Fri": "周五", "Sat": "周六", "Sun": "周日"},
            "ja-JP": {"Mon": "月", "Tue": "火", "Wed": "水",
                      "Thu": "木", "Fri": "金", "Sat": "土", "Sun": "日"},
        }
        if lang in short_weekdays:
            for en, localized in short_weekdays[lang].items():
                text = text.replace(en, localized)

    if lang in month_map:
        for en, localized in month_map[lang].items():
            text = text.replace(en, localized)
        # 处理缩写
        short_months = {
            "zh-CN": {
                "Jan": "1月", "Feb": "2月", "Mar": "3月", "Apr": "4月",
                "Jun": "6月", "Jul": "7月", "Aug": "8月", "Sep": "9月",
                "Oct": "10月", "Nov": "11月", "Dec": "12月",
            },
            "ja-JP": {
                "Jan": "1月", "Feb": "2月", "Mar": "3月", "Apr": "4月",
                "Jun": "6月", "Jul": "7月", "Aug": "8月", "Sep": "9月",
                "Oct": "10月", "Nov": "11月", "Dec": "12月",
            },
        }
        if lang in short_months:
            for en, localized in short_months[lang].items():
                text = text.replace(en, localized)

    return text


# ------------------------------------------------------------------
# 相对时间
# ------------------------------------------------------------------

def relative_time(
    dt: Union[datetime, str, timedelta, int],
    language: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """
    相对时间格式化

    Args:
        dt: 目标时间（datetime / 字符串 / timedelta / 秒数）
        language: 目标语言
        now: 基准时间，默认当前时间

    Returns:
        相对时间字符串

    示例：
        relative_time(datetime.now() - timedelta(minutes=5))  # "5 分钟前"
        relative_time(datetime.now() + timedelta(hours=2))    # "2 小时后"
    """
    lang = language or get_current_language()
    normalized_lang = get_i18n().normalize_language(lang)

    if now is None:
        now = datetime.now()

    # 计算时间差
    if isinstance(dt, str):
        dt = _parse_datetime(dt)
        delta = now - dt
    elif isinstance(dt, timedelta):
        delta = dt
    elif isinstance(dt, (int, float)):
        delta = timedelta(seconds=dt)
    else:
        delta = now - dt

    total_seconds = abs(delta.total_seconds())
    is_past = delta.total_seconds() >= 0

    # 本地化字符串
    locale_strings = {
        "zh-CN": {
            "just_now": "刚刚",
            "seconds_ago": "{n} 秒前",
            "seconds_later": "{n} 秒后",
            "minute_ago": "1 分钟前",
            "minutes_ago": "{n} 分钟前",
            "minute_later": "1 分钟后",
            "minutes_later": "{n} 分钟后",
            "hour_ago": "1 小时前",
            "hours_ago": "{n} 小时前",
            "hour_later": "1 小时后",
            "hours_later": "{n} 小时后",
            "day_ago": "1 天前",
            "days_ago": "{n} 天前",
            "day_later": "1 天后",
            "days_later": "{n} 天后",
            "week_ago": "1 周前",
            "weeks_ago": "{n} 周前",
            "week_later": "1 周后",
            "weeks_later": "{n} 周后",
            "month_ago": "1 个月前",
            "months_ago": "{n} 个月前",
            "month_later": "1 个月后",
            "months_later": "{n} 个月后",
            "year_ago": "1 年前",
            "years_ago": "{n} 年前",
            "year_later": "1 年后",
            "years_later": "{n} 年后",
        },
        "en-US": {
            "just_now": "just now",
            "seconds_ago": "{n} seconds ago",
            "seconds_later": "in {n} seconds",
            "minute_ago": "1 minute ago",
            "minutes_ago": "{n} minutes ago",
            "minute_later": "in 1 minute",
            "minutes_later": "in {n} minutes",
            "hour_ago": "1 hour ago",
            "hours_ago": "{n} hours ago",
            "hour_later": "in 1 hour",
            "hours_later": "in {n} hours",
            "day_ago": "1 day ago",
            "days_ago": "{n} days ago",
            "day_later": "in 1 day",
            "days_later": "in {n} days",
            "week_ago": "1 week ago",
            "weeks_ago": "{n} weeks ago",
            "week_later": "in 1 week",
            "weeks_later": "in {n} weeks",
            "month_ago": "1 month ago",
            "months_ago": "{n} months ago",
            "month_later": "in 1 month",
            "months_later": "in {n} months",
            "year_ago": "1 year ago",
            "years_ago": "{n} years ago",
            "year_later": "in 1 year",
            "years_later": "in {n} years",
        },
        "ja-JP": {
            "just_now": "たった今",
            "seconds_ago": "{n}秒前",
            "seconds_later": "{n}秒後",
            "minute_ago": "1分前",
            "minutes_ago": "{n}分前",
            "minute_later": "1分後",
            "minutes_later": "{n}分後",
            "hour_ago": "1時間前",
            "hours_ago": "{n}時間前",
            "hour_later": "1時間後",
            "hours_later": "{n}時間後",
            "day_ago": "1日前",
            "days_ago": "{n}日前",
            "day_later": "1日後",
            "days_later": "{n}日後",
            "week_ago": "1週間前",
            "weeks_ago": "{n}週間前",
            "week_later": "1週間後",
            "weeks_later": "{n}週間後",
            "month_ago": "1ヶ月前",
            "months_ago": "{n}ヶ月前",
            "month_later": "1ヶ月後",
            "months_later": "{n}ヶ月後",
            "year_ago": "1年前",
            "years_ago": "{n}年前",
            "year_later": "1年後",
            "years_later": "{n}年後",
        },
    }

    strings = locale_strings.get(normalized_lang, locale_strings["en-US"])

    # 计算合适的时间单位
    if total_seconds < 5:
        return strings["just_now"]

    if total_seconds < 60:
        n = int(total_seconds)
        key = "seconds_ago" if is_past else "seconds_later"
        return strings[key].format(n=n)

    minutes = total_seconds / 60
    if minutes < 60:
        n = int(minutes)
        if n == 1:
            key = "minute_ago" if is_past else "minute_later"
        else:
            key = "minutes_ago" if is_past else "minutes_later"
        return strings[key].format(n=n)

    hours = minutes / 60
    if hours < 24:
        n = int(hours)
        if n == 1:
            key = "hour_ago" if is_past else "hour_later"
        else:
            key = "hours_ago" if is_past else "hours_later"
        return strings[key].format(n=n)

    days = hours / 24
    if days < 7:
        n = int(days)
        if n == 1:
            key = "day_ago" if is_past else "day_later"
        else:
            key = "days_ago" if is_past else "days_later"
        return strings[key].format(n=n)

    weeks = days / 7
    if weeks < 4:
        n = int(weeks)
        if n == 1:
            key = "week_ago" if is_past else "week_later"
        else:
            key = "weeks_ago" if is_past else "weeks_later"
        return strings[key].format(n=n)

    months = days / 30
    if months < 12:
        n = int(months)
        if n == 1:
            key = "month_ago" if is_past else "month_later"
        else:
            key = "months_ago" if is_past else "months_later"
        return strings[key].format(n=n)

    years = days / 365
    n = int(years)
    if n == 1:
        key = "year_ago" if is_past else "year_later"
    else:
        key = "years_ago" if is_past else "years_later"
    return strings[key].format(n=n)


# ------------------------------------------------------------------
# 文本方向
# ------------------------------------------------------------------

def get_text_direction(language: Optional[str] = None) -> str:
    """
    获取文本方向（LTR 或 RTL）

    Args:
        language: 语言代码

    Returns:
        "ltr" 或 "rtl"
    """
    lang = language or get_current_language()

    # RTL 语言列表（基于 ISO 639-1 语言代码）
    rtl_languages = {
        "ar", "he", "fa", "ur", "yi", "dv", "ha", "ks", "ku", "ps", "sd", "ug"
    }

    # 直接使用语言基础代码判断
    lang_base = lang.lower().split("-")[0].split("_")[0]
    if lang_base in rtl_languages:
        return "rtl"

    return "ltr"


def is_rtl(language: Optional[str] = None) -> bool:
    """检查是否是从右到左的语言"""
    return get_text_direction(language) == "rtl"
