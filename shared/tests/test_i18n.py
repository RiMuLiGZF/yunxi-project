"""
i18n 国际化框架测试
====================

测试覆盖：
- i18n 核心（加载/查找/回退/变量替换/复数）
- 中间件（语言检测/上下文）
- 日期时间本地化
- 版本号一致性
- 翻译完整性
- 向后兼容
"""

import sys
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

import pytest

# 将项目根目录加入 path
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ======================================================================
# 1. i18n 核心测试
# ======================================================================

class TestI18nCore:
    """i18n 核心功能测试"""

    def test_manager_creation(self):
        """测试 I18nManager 创建"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()
        assert manager is not None
        assert manager.default_language == "zh-CN"

    def test_supported_languages(self):
        """测试支持的语言列表"""
        from shared.i18n.core import I18nManager, SUPPORTED_LANGUAGES
        manager = I18nManager()

        # 至少支持三种语言
        assert "zh-CN" in SUPPORTED_LANGUAGES
        assert "en-US" in SUPPORTED_LANGUAGES
        assert "ja-JP" in SUPPORTED_LANGUAGES

        # 语言信息完整
        for lang, info in SUPPORTED_LANGUAGES.items():
            assert "name" in info
            assert "native_name" in info
            assert "direction" in info

    def test_is_supported(self):
        """测试语言支持检查"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        assert manager.is_supported("zh-CN") is True
        assert manager.is_supported("en-US") is True
        assert manager.is_supported("ja-JP") is True
        assert manager.is_supported("fr-FR") is False
        assert manager.is_supported("") is False

    def test_normalize_language(self):
        """测试语言代码规范化"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 精确匹配
        assert manager.normalize_language("zh-CN") == "zh-CN"
        assert manager.normalize_language("en-US") == "en-US"
        assert manager.normalize_language("ja-JP") == "ja-JP"

        # 大小写不敏感
        assert manager.normalize_language("zh-cn") == "zh-CN"
        assert manager.normalize_language("EN-US") == "en-US"

        # 下划线格式
        assert manager.normalize_language("zh_CN") == "zh-CN"
        assert manager.normalize_language("en_US") == "en-US"

        # 仅语言前缀
        assert manager.normalize_language("zh") == "zh-CN"
        assert manager.normalize_language("en") == "en-US"
        assert manager.normalize_language("ja") == "ja-JP"

        # 不支持的语言回退到默认
        assert manager.normalize_language("fr") == "zh-CN"
        assert manager.normalize_language("") == "zh-CN"

    def test_basic_translation(self):
        """测试基本翻译查找"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 中文
        assert manager.t("common.ok", language="zh-CN") == "确定"
        assert manager.t("common.cancel", language="zh-CN") == "取消"
        assert manager.t("common.save", language="zh-CN") == "保存"

        # 英文
        assert manager.t("common.ok", language="en-US") == "OK"
        assert manager.t("common.cancel", language="en-US") == "Cancel"
        assert manager.t("common.save", language="en-US") == "Save"

        # 日文
        assert manager.t("common.ok", language="ja-JP") == "確定"
        assert manager.t("common.cancel", language="ja-JP") == "キャンセル"

    def test_nested_keys(self):
        """测试嵌套键查找"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 错误信息嵌套
        assert manager.t("errors.not_found.title", language="zh-CN") == "未找到"
        assert manager.t("errors.not_found.message", language="zh-CN") == "请求的资源不存在"
        assert manager.t("errors.internal.title", language="en-US") == "Internal Error"

        # 模块名称嵌套
        assert manager.t("modules.m8.name", language="zh-CN") == "控制塔"
        assert manager.t("modules.m8.full_name", language="zh-CN") == "M8 控制塔"

    def test_variable_replacement(self):
        """测试变量替换"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 问候语
        result = manager.t("common.greeting", language="zh-CN", name="云汐")
        assert result == "你好，云汐！"

        result = manager.t("common.greeting", language="en-US", name="Yunxi")
        assert result == "Hello, Yunxi!"

        result = manager.t("common.greeting", language="ja-JP", name="雲汐")
        assert result == "こんにちは、雲汐さん！"

        # 错误信息中的变量
        result = manager.t("errors.not_found.resource", language="zh-CN", resource="用户")
        assert result == "用户 不存在"

    def test_fallback_mechanism(self):
        """测试回退机制"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 日文只有 common.json，找 modules 应该回退到中文（默认语言）
        result = manager.t("modules.m8.name", language="ja-JP")
        # 应该回退到默认语言（中文）
        assert result == "控制塔"

    def test_missing_key_returns_key(self):
        """测试找不到翻译时返回 key 本身"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        result = manager.t("nonexistent.key.here", language="zh-CN")
        assert result == "nonexistent.key.here"

    def test_missing_keys_tracking(self):
        """测试缺失翻译键跟踪"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 触发缺失键
        manager.t("missing_key_1", language="zh-CN")
        manager.t("missing_key_2", language="en-US")

        missing = manager.get_missing_keys()
        assert "zh-CN" in missing
        assert "en-US" in missing
        assert "missing_key_1" in missing["zh-CN"]
        assert "missing_key_2" in missing["en-US"]

    def test_reload(self):
        """测试重新加载翻译"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 先记录一些缺失键
        manager.t("some_missing_key", language="zh-CN")
        assert len(manager.get_missing_keys().get("zh-CN", [])) > 0

        # 重新加载
        manager.reload()

        # 缺失键应该被清空
        missing = manager.get_missing_keys()
        assert len(missing.get("zh-CN", [])) == 0

        # 翻译仍然可用
        assert manager.t("common.ok", language="zh-CN") == "确定"

    def test_get_namespaces(self):
        """测试获取命名空间列表"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        namespaces = manager.get_namespaces("zh-CN")
        assert "common" in namespaces
        assert "errors" in namespaces
        assert "modules" in namespaces
        assert "validation" in namespaces

    def test_get_translations(self):
        """测试获取全部翻译"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 获取指定命名空间
        common = manager.get_translations("zh-CN", "common")
        assert isinstance(common, dict)
        assert "ok" in common
        assert "cancel" in common

        # 获取所有命名空间
        all_trans = manager.get_translations("en-US")
        assert isinstance(all_trans, dict)
        assert "common" in all_trans
        assert "errors" in all_trans

    def test_stats(self):
        """测试统计信息"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        stats = manager.get_stats()
        assert stats["default_language"] == "zh-CN"
        assert "zh-CN" in stats["languages"]
        assert "en-US" in stats["languages"]
        assert stats["languages"]["zh-CN"]["total_keys"] > 50


# ======================================================================
# 2. 语言检测测试
# ======================================================================

class TestLanguageDetection:
    """语言检测测试"""

    def test_parse_accept_language(self):
        """测试解析 Accept-Language 头"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 标准格式
        result = manager._parse_accept_language("zh-CN,zh;q=0.9,en;q=0.8")
        assert len(result) == 3
        assert result[0][0] == "zh-CN"
        assert result[0][1] == 1.0
        assert result[1][0] == "zh"
        assert result[2][0] == "en"

        # 只有一个语言
        result = manager._parse_accept_language("en-US")
        assert len(result) == 1
        assert result[0][0] == "en-US"

        # 空字符串
        result = manager._parse_accept_language("")
        assert len(result) == 0

    def test_detect_language_priority(self):
        """测试语言检测优先级"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 查询参数优先级最高
        lang = manager.detect_language(
            accept_language="zh-CN",
            cookie_lang="en-US",
            query_param="ja-JP",
        )
        assert lang == "ja-JP"

        # Cookie 优先于 Accept-Language
        lang = manager.detect_language(
            accept_language="zh-CN",
            cookie_lang="en-US",
        )
        assert lang == "en-US"

        # Accept-Language 作为后备
        lang = manager.detect_language(
            accept_language="en-US,en;q=0.9",
        )
        assert lang == "en-US"

        # 全部没有时用默认语言
        lang = manager.detect_language()
        assert lang == "zh-CN"

    def test_detect_with_user_preference(self):
        """测试用户偏好优先级"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 用户偏好优先于 Cookie
        lang = manager.detect_language(
            cookie_lang="en-US",
            user_preference="ja-JP",
        )
        assert lang == "ja-JP"

        # 查询参数优先于用户偏好
        lang = manager.detect_language(
            user_preference="en-US",
            query_param="zh-CN",
        )
        assert lang == "zh-CN"


# ======================================================================
# 3. 工具函数测试
# ======================================================================

class TestI18nUtils:
    """i18n 工具函数测试"""

    def test_format_number(self):
        """测试数字格式化"""
        from shared.i18n.utils import format_number

        # 整数千分位
        assert format_number(1234567, "en-US") == "1,234,567"
        assert format_number(1234567, "zh-CN") == "1,234,567"

        # 带小数
        result = format_number(1234.56, "en-US", decimals=2)
        assert result == "1,234.56"

        # 负数
        result = format_number(-1000, "en-US")
        assert result == "-1,000"

        # 小数
        result = format_number(0.5, "en-US", decimals=1)
        assert result == "0.5"

    def test_format_currency(self):
        """测试货币格式化"""
        from shared.i18n.utils import format_currency

        # 人民币
        result = format_currency(1234.56, "CNY", "zh-CN")
        assert "¥" in result
        assert "1,234.56" in result

        # 美元
        result = format_currency(1234.56, "USD", "en-US")
        assert "$" in result

        # 日元（无小数）
        result = format_currency(1234, "JPY", "ja-JP")
        assert "¥" in result
        assert "." not in result  # 日元没有小数

    def test_format_date(self):
        """测试日期格式化"""
        from shared.i18n.utils import format_date
        from datetime import datetime

        dt = datetime(2026, 7, 19)

        # 中文
        result = format_date(dt, "zh-CN", "medium")
        assert "2026年" in result
        assert "7月" in result
        assert "19日" in result

        # 英文
        result = format_date(dt, "en-US", "short")
        assert "7/19/2026" in result or "07/19/2026" in result

    def test_format_time(self):
        """测试时间格式化"""
        from shared.i18n.utils import format_time
        from datetime import datetime

        dt = datetime(2026, 7, 19, 14, 30, 45)

        # 中文使用24小时制
        result = format_time(dt, "zh-CN", with_seconds=True)
        assert "14:30:45" in result

        # 英文使用12小时制
        result = format_time(dt, "en-US", with_seconds=False)
        assert "02:30" in result or "2:30" in result
        assert "PM" in result

    def test_relative_time(self):
        """测试相对时间格式化"""
        from shared.i18n.utils import relative_time
        from datetime import datetime, timedelta

        now = datetime.now()

        # 刚刚
        result = relative_time(now, "zh-CN", now)
        assert result == "刚刚"

        # 几分钟前
        result = relative_time(now - timedelta(minutes=5), "zh-CN", now)
        assert "5" in result
        assert "分钟前" in result

        # 英文
        result = relative_time(now - timedelta(minutes=5), "en-US", now)
        assert "5" in result
        assert "minutes ago" in result

        # 小时前
        result = relative_time(now - timedelta(hours=2), "zh-CN", now)
        assert "2" in result
        assert "小时前" in result

        # 天前
        result = relative_time(now - timedelta(days=3), "zh-CN", now)
        assert "3" in result
        assert "天前" in result

        # 未来时间
        result = relative_time(now + timedelta(hours=1), "en-US", now)
        assert "in 1 hour" in result or "in 1 hours" in result

        # 日文
        result = relative_time(now - timedelta(minutes=10), "ja-JP", now)
        assert "10" in result
        assert "分前" in result

    def test_text_direction(self):
        """测试文本方向检测"""
        from shared.i18n.utils import get_text_direction, is_rtl

        # LTR 语言
        assert get_text_direction("zh-CN") == "ltr"
        assert get_text_direction("en-US") == "ltr"
        assert get_text_direction("ja-JP") == "ltr"
        assert is_rtl("zh-CN") is False

        # RTL 语言
        assert get_text_direction("ar") == "rtl"
        assert get_text_direction("he") == "rtl"
        assert is_rtl("ar") is True


# ======================================================================
# 4. 日期时间本地化测试
# ======================================================================

class TestDateTimeLocalizer:
    """日期时间本地化测试"""

    def test_creation(self):
        """测试 DateTimeLocalizer 创建"""
        from shared.i18n.datetime_localizer import DateTimeLocalizer

        localizer = DateTimeLocalizer(timezone="Asia/Shanghai", language="zh-CN")
        assert localizer is not None
        assert localizer.timezone_name == "Asia/Shanghai"

    def test_now_and_today(self):
        """测试 now/today 方法"""
        from shared.i18n.datetime_localizer import DateTimeLocalizer

        localizer = DateTimeLocalizer(timezone="Asia/Shanghai", language="zh-CN")

        now = localizer.now()
        assert isinstance(now, datetime)
        assert now.tzinfo is not None

        today = localizer.today()
        assert today.hour == 0
        assert today.minute == 0
        assert today.second == 0

    def test_format_date_localized(self):
        """测试本地化日期格式化"""
        from shared.i18n.datetime_localizer import DateTimeLocalizer
        from datetime import datetime

        localizer_cn = DateTimeLocalizer(language="zh-CN")
        localizer_en = DateTimeLocalizer(language="en-US")
        localizer_jp = DateTimeLocalizer(language="ja-JP")

        dt = datetime(2026, 7, 19, 14, 30)

        # 中文
        result = localizer_cn.format_date(dt, "medium")
        assert "2026年" in result

        # 英文
        result = localizer_en.format_date(dt, "short")
        assert "/" in result

        # 日文
        result = localizer_jp.format_date(dt, "medium")
        assert "2026年" in result

    def test_relative_time_short(self):
        """测试简短相对时间"""
        from shared.i18n.datetime_localizer import DateTimeLocalizer
        from datetime import timedelta

        localizer = DateTimeLocalizer(language="zh-CN")
        now = localizer.now()

        # 秒
        result = localizer.relative_time_short(now - timedelta(seconds=30))
        assert result.endswith("s")

        # 分钟
        result = localizer.relative_time_short(now - timedelta(minutes=5))
        assert "m" in result

        # 小时
        result = localizer.relative_time_short(now - timedelta(hours=3))
        assert "h" in result

        # 天
        result = localizer.relative_time_short(now - timedelta(days=2))
        assert "d" in result

    def test_weekday_names(self):
        """测试星期名称"""
        from shared.i18n.datetime_localizer import DateTimeLocalizer

        localizer_cn = DateTimeLocalizer(language="zh-CN")
        localizer_en = DateTimeLocalizer(language="en-US")
        localizer_jp = DateTimeLocalizer(language="ja-JP")

        # 中文
        weekdays = localizer_cn.get_weekday_names()
        assert len(weekdays) == 7
        assert "星期一" in weekdays

        # 英文
        weekdays = localizer_en.get_weekday_names()
        assert "Monday" in weekdays

        # 日文
        weekdays = localizer_jp.get_weekday_names()
        assert "月曜日" in weekdays

        # 缩写
        short_weekdays = localizer_cn.get_weekday_names(short=True)
        assert "周一" in short_weekdays

    def test_month_names(self):
        """测试月份名称"""
        from shared.i18n.datetime_localizer import DateTimeLocalizer

        localizer_en = DateTimeLocalizer(language="en-US")
        months = localizer_en.get_month_names()
        assert len(months) == 12
        assert "January" in months
        assert "December" in months

        short_months = localizer_en.get_month_names(short=True)
        assert "Jan" in short_months

    def test_date_boundaries(self):
        """测试日期边界计算"""
        from shared.i18n.datetime_localizer import DateTimeLocalizer

        localizer = DateTimeLocalizer(language="zh-CN")

        # 一天的开始和结束
        sod = localizer.start_of_day()
        eod = localizer.end_of_day()
        assert sod.hour == 0
        assert sod.minute == 0
        assert eod.hour == 23
        assert eod.minute == 59

        # 一个月的开始和结束
        som = localizer.start_of_month()
        eom = localizer.end_of_month()
        assert som.day == 1
        assert eom.day >= 28

    def test_is_today_yesterday_tomorrow(self):
        """测试今天/昨天/明天判断"""
        from shared.i18n.datetime_localizer import DateTimeLocalizer
        from datetime import timedelta

        localizer = DateTimeLocalizer(language="zh-CN")
        now = localizer.now()

        assert localizer.is_today(now) is True
        assert localizer.is_tomorrow(now + timedelta(days=1)) is True
        assert localizer.is_yesterday(now - timedelta(days=1)) is True
        assert localizer.is_today(now + timedelta(days=2)) is False

    def test_parse_date(self):
        """测试日期解析"""
        from shared.i18n.datetime_localizer import DateTimeLocalizer

        localizer_cn = DateTimeLocalizer(language="zh-CN")

        # 中文格式
        result = localizer_cn.parse_date("2026年7月19日")
        assert result is not None
        assert result.year == 2026
        assert result.month == 7
        assert result.day == 19

        # 标准格式
        result = localizer_cn.parse_date("2026-07-19")
        assert result is not None

        # 无效格式
        result = localizer_cn.parse_date("invalid-date")
        assert result is None

    def test_common_timezones(self):
        """测试常用时区列表"""
        from shared.i18n.datetime_localizer import DateTimeLocalizer

        timezones = DateTimeLocalizer.get_common_timezones()
        assert "Asia/Shanghai" in timezones
        assert "America/New_York" in timezones
        assert "UTC" in timezones
        assert "Europe/London" in timezones

        name = DateTimeLocalizer.get_timezone_name("Asia/Shanghai")
        assert "北京" in name


# ======================================================================
# 5. 版本号一致性测试
# ======================================================================

class TestVersionConsistency:
    """版本号一致性测试"""

    def test_shared_core_version(self):
        """测试 shared.core 版本"""
        from shared.core.version import SYSTEM_VERSION, VERSION_CODE
        assert SYSTEM_VERSION == "v1.2.0"
        assert VERSION_CODE == 120

    def test_shared_version(self):
        """测试 shared 版本"""
        import shared
        assert shared.__version__ == "1.2.0"

    def test_version_file(self):
        """测试根目录 VERSION 文件"""
        version_file = _project_root / "VERSION"
        assert version_file.exists()

        content = version_file.read_text(encoding="utf-8")
        assert "VERSION=1.2.0" in content
        assert "v1.2.0" in content.lower()

    def test_m0_version(self):
        """测试 M0 版本"""
        sys.path.insert(0, str(_project_root / "M0-principal-console"))
        try:
            from src import __version__ as m0_version
            assert m0_version == "1.2.0"
        finally:
            sys.path.pop(0)

    def test_m2_version(self):
        """测试 M2 版本"""
        sys.path.insert(0, str(_project_root / "M2-skills-cluster"))
        try:
            from skill_cluster import __version__ as m2_version
            assert m2_version == "1.2.0"
        finally:
            sys.path.pop(0)

    def test_m6_version(self):
        """测试 M6 版本"""
        sys.path.insert(0, str(_project_root / "M6-hardware-peripheral"))
        try:
            from m6_hardware import __version__ as m6_version
            assert m6_version == "1.2.0"
        finally:
            sys.path.pop(0)

    def test_m10_version(self):
        """测试 M10 版本"""
        sys.path.insert(0, str(_project_root / "M10-system-guard"))
        try:
            from m10_system_guard import __version__ as m10_version
            assert m10_version == "1.2.0"
        finally:
            sys.path.pop(0)

    def test_m12_version(self):
        """测试 M12 版本"""
        sys.path.insert(0, str(_project_root / "M12-security-shield"))
        try:
            import importlib
            m12_module = importlib.import_module("__init__")
            # 跳过，直接检查文件
        except Exception:
            pass

        # 直接读文件验证
        m12_init = _project_root / "M12-security-shield" / "__init__.py"
        content = m12_init.read_text(encoding="utf-8")
        assert '__version__ = "1.2.0"' in content


# ======================================================================
# 6. 翻译完整性测试
# ======================================================================

class TestTranslationCompleteness:
    """翻译完整性测试"""

    def test_zh_cn_has_all_namespaces(self):
        """测试中文包含所有命名空间"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        namespaces = manager.get_namespaces("zh-CN")
        assert "common" in namespaces
        assert "errors" in namespaces
        assert "modules" in namespaces
        assert "validation" in namespaces

    def test_en_us_has_all_namespaces(self):
        """测试英文包含所有命名空间"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        namespaces = manager.get_namespaces("en-US")
        assert "common" in namespaces
        assert "errors" in namespaces
        assert "modules" in namespaces
        assert "validation" in namespaces

    def test_common_minimum_keys(self):
        """测试 common 命名空间至少 50 个键"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        stats = manager.get_stats()
        zh_common = stats["languages"]["zh-CN"]["namespaces"].get("common", 0)
        en_common = stats["languages"]["en-US"]["namespaces"].get("common", 0)

        assert zh_common >= 50
        assert en_common >= 50

    def test_errors_translation_count(self):
        """测试 errors 命名空间翻译数量"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        stats = manager.get_stats()
        zh_errors = stats["languages"]["zh-CN"]["namespaces"].get("errors", 0)
        en_errors = stats["languages"]["en-US"]["namespaces"].get("errors", 0)

        # 至少有 20 个错误类别
        assert zh_errors >= 20
        assert en_errors >= 20

    def test_modules_translation_complete(self):
        """测试模块名称翻译完整"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 所有主要模块都应该有翻译
        modules = ["m0", "m1", "m2", "m3", "m4", "m5", "m6",
                    "m7", "m8", "m9", "m10", "m11", "m12"]

        for m in modules:
            zh_name = manager.t(f"modules.{m}.name", language="zh-CN")
            en_name = manager.t(f"modules.{m}.name", language="en-US")
            # 应该有翻译（不是 key 本身）
            assert zh_name != f"modules.{m}.name"
            assert en_name != f"modules.{m}.name"


# ======================================================================
# 7. 向后兼容测试
# ======================================================================

class TestBackwardCompatibility:
    """向后兼容性测试"""

    def test_default_language_is_chinese(self):
        """测试默认语言是中文"""
        from shared.i18n.core import I18nManager, DEFAULT_LANGUAGE
        assert DEFAULT_LANGUAGE == "zh-CN"

        manager = I18nManager()
        assert manager.default_language == "zh-CN"

    def test_translation_chinese_by_default(self):
        """测试不指定语言时默认返回中文"""
        from shared.i18n.core import I18nManager
        manager = I18nManager()

        # 不指定语言，应该返回中文
        result = manager.t("common.ok")
        assert result == "确定"

    def test_existing_code_unchanged(self):
        """测试现有代码不受影响"""
        # shared 模块的其他功能应该仍然可用
        from shared.core.errors import ErrorCode
        assert ErrorCode is not None

        from shared.core.config import get_config
        config = get_config()
        assert config is not None

    def test_version_backward_compat(self):
        """测试版本导入路径向后兼容"""
        # 旧路径仍然可用（有 deprecation warning）
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from shared.version import SYSTEM_VERSION
            assert SYSTEM_VERSION == "v1.2.0"


# ======================================================================
# 8. 全局函数测试
# ======================================================================

class TestGlobalFunctions:
    """全局便捷函数测试"""

    def test_get_i18n_singleton(self):
        """测试 get_i18n 返回单例"""
        from shared.i18n.core import get_i18n

        m1 = get_i18n()
        m2 = get_i18n()
        assert m1 is m2

    def test_t_function(self):
        """测试 t() 快捷函数"""
        from shared.i18n.core import t, set_current_language

        set_current_language("zh-CN")
        assert t("common.ok") == "确定"

        set_current_language("en-US")
        assert t("common.ok") == "OK"

        # 重置为中文
        set_current_language("zh-CN")

    def test_underscore_function(self):
        """测试 _() 别名函数"""
        from shared.i18n.core import _, set_current_language

        set_current_language("zh-CN")
        assert _("common.cancel") == "取消"

    def test_module_init_exports(self):
        """测试模块 __init__ 导出"""
        import shared.i18n as i18n

        assert hasattr(i18n, "I18nManager")
        assert hasattr(i18n, "get_i18n")
        assert hasattr(i18n, "t")
        assert hasattr(i18n, "_")
        assert hasattr(i18n, "I18nMiddleware")
        assert hasattr(i18n, "format_number")
        assert hasattr(i18n, "format_currency")
        assert hasattr(i18n, "format_date")
        assert hasattr(i18n, "relative_time")
        assert hasattr(i18n, "DateTimeLocalizer")
        assert i18n.__version__ == "1.2.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
