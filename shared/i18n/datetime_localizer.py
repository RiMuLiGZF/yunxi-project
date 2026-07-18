"""
日期时间本地化模块
====================

提供时区支持、相对时间计算、日历本地化、日期解析等功能。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, Dict, List, Tuple

try:
    from zoneinfo import ZoneInfo
    _HAS_ZONEINFO = True
except ImportError:
    try:
        from backports.zoneinfo import ZoneInfo  # type: ignore
        _HAS_ZONEINFO = True
    except ImportError:
        _HAS_ZONEINFO = False

from .core import get_i18n, get_current_language
from .utils import _parse_datetime, _localize_date_names


# 常用时区
COMMON_TIMEZONES = {
    "Asia/Shanghai": {"name": "北京时间", "offset": "+08:00", "country": "CN"},
    "Asia/Tokyo": {"name": "东京时间", "offset": "+09:00", "country": "JP"},
    "Asia/Seoul": {"name": "首尔时间", "offset": "+09:00", "country": "KR"},
    "Asia/Singapore": {"name": "新加坡时间", "offset": "+08:00", "country": "SG"},
    "Asia/Hong_Kong": {"name": "香港时间", "offset": "+08:00", "country": "HK"},
    "Asia/Taipei": {"name": "台北时间", "offset": "+08:00", "country": "TW"},
    "America/New_York": {"name": "纽约时间", "offset": "-05:00/-04:00", "country": "US"},
    "America/Los_Angeles": {"name": "洛杉矶时间", "offset": "-08:00/-07:00", "country": "US"},
    "America/Chicago": {"name": "芝加哥时间", "offset": "-06:00/-05:00", "country": "US"},
    "Europe/London": {"name": "伦敦时间", "offset": "+00:00/+01:00", "country": "GB"},
    "Europe/Paris": {"name": "巴黎时间", "offset": "+01:00/+02:00", "country": "FR"},
    "Europe/Berlin": {"name": "柏林时间", "offset": "+01:00/+02:00", "country": "DE"},
    "UTC": {"name": "UTC", "offset": "+00:00", "country": "—"},
}


class DateTimeLocalizer:
    """
    日期时间本地化器

    提供时区转换、日历本地化、日期解析等功能。

    使用方式：
        localizer = DateTimeLocalizer(timezone="Asia/Shanghai", language="zh-CN")
        now = localizer.now()
        print(localizer.format_date(now))
        print(localizer.relative_time(now - timedelta(days=1)))
    """

    def __init__(
        self,
        timezone: str = "Asia/Shanghai",
        language: Optional[str] = None,
    ):
        """
        初始化日期时间本地化器

        Args:
            timezone: 时区（IANA 时区名）
            language: 语言代码
        """
        self._timezone_name = timezone
        self._language = language or get_current_language()
        self._i18n = get_i18n()

        # 时区对象
        if _HAS_ZONEINFO:
            try:
                self._tz = ZoneInfo(timezone)
            except Exception:
                self._tz = timezone(timedelta(hours=8))  # 回退到北京时间
        else:
            # 简化处理：使用固定偏移
            offset_map = {
                "Asia/Shanghai": 8,
                "Asia/Tokyo": 9,
                "Asia/Seoul": 9,
                "Asia/Singapore": 8,
                "Asia/Hong_Kong": 8,
                "Asia/Taipei": 8,
                "UTC": 0,
                "Europe/London": 0,
                "Europe/Paris": 1,
                "Europe/Berlin": 1,
                "America/New_York": -5,
                "America/Los_Angeles": -8,
                "America/Chicago": -6,
            }
            offset_hours = offset_map.get(timezone, 8)
            self._tz = timezone(timedelta(hours=offset_hours))

    # ------------------------------------------------------------------
    # 时间获取
    # ------------------------------------------------------------------

    def now(self) -> datetime:
        """获取当前时间（带时区）"""
        return datetime.now(self._tz)

    def utcnow(self) -> datetime:
        """获取当前 UTC 时间"""
        return datetime.now(timezone.utc)

    def today(self) -> datetime:
        """获取今天的开始时间（00:00:00）"""
        n = self.now()
        return datetime(n.year, n.month, n.day, tzinfo=self._tz)

    def tomorrow(self) -> datetime:
        """获取明天的开始时间"""
        return self.today() + timedelta(days=1)

    def yesterday(self) -> datetime:
        """获取昨天的开始时间"""
        return self.today() - timedelta(days=1)

    # ------------------------------------------------------------------
    # 时区转换
    # ------------------------------------------------------------------

    def convert(
        self,
        dt: Union[datetime, str],
        target_tz: Optional[str] = None,
    ) -> datetime:
        """
        转换时区

        Args:
            dt: 日期时间对象或字符串
            target_tz: 目标时区，默认使用本地时区

        Returns:
            转换后的 datetime 对象
        """
        if isinstance(dt, str):
            dt = _parse_datetime(dt)

        if target_tz is None:
            target_tz_obj = self._tz
        elif _HAS_ZONEINFO:
            target_tz_obj = ZoneInfo(target_tz)
        else:
            target_tz_obj = self._tz  # 简化处理

        # 如果原始时间没有时区信息，假设是 UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(target_tz_obj)

    def to_utc(self, dt: Union[datetime, str]) -> datetime:
        """转换为 UTC 时间"""
        return self.convert(dt, "UTC")

    def to_local(self, dt: Union[datetime, str]) -> datetime:
        """转换为本地时间"""
        return self.convert(dt)

    @property
    def timezone_name(self) -> str:
        """时区名称"""
        return self._timezone_name

    @property
    def timezone(self):
        """时区对象"""
        return self._tz

    # ------------------------------------------------------------------
    # 格式化
    # ------------------------------------------------------------------

    def format_date(
        self,
        dt: Union[datetime, str],
        style: str = "medium",
    ) -> str:
        """
        格式化日期

        Args:
            dt: 日期时间
            style: 格式风格（short, medium, long, full）

        Returns:
            格式化后的日期字符串
        """
        if isinstance(dt, str):
            dt = _parse_datetime(dt)

        lang = self._i18n.normalize_language(self._language)

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

        fmt = format_map.get(lang, format_map["en-US"]).get(style, format_map["en-US"]["medium"])
        result = dt.strftime(fmt)
        return _localize_date_names(result, lang)

    def format_time(
        self,
        dt: Union[datetime, str],
        style: str = "medium",
    ) -> str:
        """格式化时间"""
        if isinstance(dt, str):
            dt = _parse_datetime(dt)

        lang = self._i18n.normalize_language(self._language)

        if lang == "en-US":
            if style == "short":
                return dt.strftime("%I:%M %p")
            else:
                return dt.strftime("%I:%M:%S %p")
        else:
            if style == "short":
                return dt.strftime("%H:%M")
            else:
                return dt.strftime("%H:%M:%S")

    def format_datetime(
        self,
        dt: Union[datetime, str],
        date_style: str = "medium",
        time_style: str = "medium",
    ) -> str:
        """格式化日期时间"""
        date_str = self.format_date(dt, date_style)
        time_str = self.format_time(dt, time_style)

        lang = self._i18n.normalize_language(self._language)
        if lang in ("zh-CN", "ja-JP"):
            return f"{date_str} {time_str}"
        else:
            return f"{date_str}, {time_str}"

    # ------------------------------------------------------------------
    # 相对时间
    # ------------------------------------------------------------------

    def relative_time(
        self,
        dt: Union[datetime, str],
        now: Optional[datetime] = None,
    ) -> str:
        """
        相对时间

        Args:
            dt: 目标时间
            now: 基准时间，默认当前时间

        Returns:
            相对时间字符串
        """
        from .utils import relative_time as _relative_time
        return _relative_time(dt, self._language, now or self.now())

    def relative_time_short(
        self,
        dt: Union[datetime, str],
        now: Optional[datetime] = None,
    ) -> str:
        """
        简短相对时间（如 "5m", "2h", "3d"）

        Args:
            dt: 目标时间
            now: 基准时间

        Returns:
            简短相对时间字符串
        """
        if isinstance(dt, str):
            dt = _parse_datetime(dt)

        if now is None:
            now = self.now()
        elif isinstance(now, str):
            now = _parse_datetime(now)

        delta = now - dt
        total_seconds = abs(delta.total_seconds())
        is_past = delta.total_seconds() >= 0
        suffix = "" if is_past else ""

        if total_seconds < 60:
            return f"{int(total_seconds)}s{suffix}"
        if total_seconds < 3600:
            return f"{int(total_seconds / 60)}m{suffix}"
        if total_seconds < 86400:
            return f"{int(total_seconds / 3600)}h{suffix}"
        if total_seconds < 2592000:  # 30天
            return f"{int(total_seconds / 86400)}d{suffix}"
        if total_seconds < 31536000:  # 365天
            return f"{int(total_seconds / 2592000)}mo{suffix}"
        return f"{int(total_seconds / 31536000)}y{suffix}"

    # ------------------------------------------------------------------
    # 日历本地化
    # ------------------------------------------------------------------

    def get_weekday_names(self, short: bool = False) -> List[str]:
        """
        获取星期名称列表

        Args:
            short: 是否使用缩写

        Returns:
            星期名称列表（从周一开始或周日开始，取决于语言）
        """
        lang = self._i18n.normalize_language(self._language)

        if lang == "zh-CN":
            if short:
                return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            return ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        elif lang == "ja-JP":
            if short:
                return ["月", "火", "水", "木", "金", "土", "日"]
            return ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
        else:  # en-US
            if short:
                return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def get_month_names(self, short: bool = False) -> List[str]:
        """
        获取月份名称列表

        Args:
            short: 是否使用缩写

        Returns:
            月份名称列表
        """
        lang = self._i18n.normalize_language(self._language)

        if lang == "zh-CN":
            if short:
                return [f"{i}月" for i in range(1, 13)]
            return [f"{i}月" for i in range(1, 13)]
        elif lang == "ja-JP":
            if short:
                return [f"{i}月" for i in range(1, 13)]
            return [f"{i}月" for i in range(1, 13)]
        else:  # en-US
            if short:
                return ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            return ["January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December"]

    def first_day_of_week(self) -> int:
        """
        获取一周的第一天

        Returns:
            0=周一, 6=周日
        """
        lang = self._i18n.normalize_language(self._language)
        # 大多数国家周一是一周的开始，美国等是周日
        if lang in ("en-US",):
            return 6  # 周日
        return 0  # 周一

    # ------------------------------------------------------------------
    # 日期解析
    # ------------------------------------------------------------------

    def parse_date(
        self,
        date_str: str,
        formats: Optional[List[str]] = None,
    ) -> Optional[datetime]:
        """
        解析日期字符串

        支持多种格式，包括本地化的日期格式。

        Args:
            date_str: 日期字符串
            formats: 自定义格式列表

        Returns:
            解析后的 datetime 对象，解析失败返回 None
        """
        lang = self._i18n.normalize_language(self._language)

        default_formats = {
            "zh-CN": [
                "%Y年%m月%d日",
                "%Y-%m-%d",
                "%Y/%m/%d",
                "%Y.%m.%d",
                "%m月%d日",
            ],
            "en-US": [
                "%m/%d/%Y",
                "%Y-%m-%d",
                "%B %d, %Y",
                "%b %d, %Y",
                "%d/%m/%Y",
            ],
            "ja-JP": [
                "%Y年%m月%d日",
                "%Y-%m-%d",
                "%Y/%m/%d",
                "%Y.%m.%d",
            ],
        }

        if formats is None:
            formats = default_formats.get(lang, default_formats["en-US"])

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        return None

    # ------------------------------------------------------------------
    # 时间计算
    # ------------------------------------------------------------------

    def start_of_day(self, dt: Optional[datetime] = None) -> datetime:
        """获取一天的开始"""
        if dt is None:
            dt = self.now()
        return datetime(dt.year, dt.month, dt.day, tzinfo=dt.tzinfo or self._tz)

    def end_of_day(self, dt: Optional[datetime] = None) -> datetime:
        """获取一天的结束"""
        if dt is None:
            dt = self.now()
        return datetime(dt.year, dt.month, dt.day, 23, 59, 59, 999999,
                        tzinfo=dt.tzinfo or self._tz)

    def start_of_week(self, dt: Optional[datetime] = None) -> datetime:
        """获取一周的开始"""
        if dt is None:
            dt = self.now()
        first_day = self.first_day_of_week()
        # Python weekday(): 周一=0, 周日=6
        days_diff = (dt.weekday() - first_day) % 7
        start = self.start_of_day(dt - timedelta(days=days_diff))
        return start

    def end_of_week(self, dt: Optional[datetime] = None) -> datetime:
        """获取一周的结束"""
        start = self.start_of_week(dt)
        return self.end_of_day(start + timedelta(days=6))

    def start_of_month(self, dt: Optional[datetime] = None) -> datetime:
        """获取一月的开始"""
        if dt is None:
            dt = self.now()
        return datetime(dt.year, dt.month, 1, tzinfo=dt.tzinfo or self._tz)

    def end_of_month(self, dt: Optional[datetime] = None) -> datetime:
        """获取一月的结束"""
        if dt is None:
            dt = self.now()
        # 下个月第一天减一天
        if dt.month == 12:
            next_month = datetime(dt.year + 1, 1, 1, tzinfo=dt.tzinfo or self._tz)
        else:
            next_month = datetime(dt.year, dt.month + 1, 1, tzinfo=dt.tzinfo or self._tz)
        return self.end_of_day(next_month - timedelta(days=1))

    def is_today(self, dt: datetime) -> bool:
        """判断是否是今天"""
        today = self.today()
        return dt.date() == today.date()

    def is_tomorrow(self, dt: datetime) -> bool:
        """判断是否是明天"""
        tomorrow = self.tomorrow()
        return dt.date() == tomorrow.date()

    def is_yesterday(self, dt: datetime) -> bool:
        """判断是否是昨天"""
        yesterday = self.yesterday()
        return dt.date() == yesterday.date()

    def is_this_week(self, dt: datetime) -> bool:
        """判断是否在本周"""
        start = self.start_of_week()
        end = self.end_of_week()
        return start <= dt <= end

    def is_this_month(self, dt: datetime) -> bool:
        """判断是否在本月"""
        start = self.start_of_month()
        end = self.end_of_month()
        return start <= dt <= end

    # ------------------------------------------------------------------
    # 常用时区列表
    # ------------------------------------------------------------------

    @staticmethod
    def get_common_timezones() -> Dict[str, Dict[str, str]]:
        """获取常用时区列表"""
        return COMMON_TIMEZONES.copy()

    @staticmethod
    def get_timezone_name(tz: str) -> str:
        """获取时区的友好名称"""
        return COMMON_TIMEZONES.get(tz, {}).get("name", tz)
