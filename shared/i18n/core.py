"""
i18n 国际化核心模块
====================

核心类 I18nManager 提供：
- 语言切换（zh-CN / en-US / ja-JP 等）
- 翻译加载（JSON / YAML 文件）
- 翻译查找（支持嵌套键，如 "common.ok"）
- 回退机制（找不到用默认语言）
- 变量替换（如 "Hello, {name}!"）
- 复数形式支持
- 语言检测（从请求头 / 用户偏好 / 浏览器）
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from contextvars import ContextVar

# 当前语言上下文变量（用于请求级别语言切换）
_current_language_var: ContextVar[str] = ContextVar("i18n_current_language", default="zh-CN")

# 支持的语言列表
SUPPORTED_LANGUAGES = {
    "zh-CN": {"name": "简体中文", "native_name": "简体中文", "direction": "ltr", "flag": "🇨🇳"},
    "en-US": {"name": "English (US)", "native_name": "English", "direction": "ltr", "flag": "🇺🇸"},
    "ja-JP": {"name": "日本語", "native_name": "日本語", "direction": "ltr", "flag": "🇯🇵"},
}

# 默认语言
DEFAULT_LANGUAGE = "zh-CN"


class I18nManager:
    """
    国际化管理器

    负责加载翻译资源、查找翻译、处理变量替换和复数形式。

    使用方式：
        manager = I18nManager(locales_dir="/path/to/locales")
        manager.set_language("en-US")
        text = manager.t("common.ok")
        greeting = manager.t("greeting.hello", name="云汐")
    """

    def __init__(
        self,
        locales_dir: Optional[Union[str, Path]] = None,
        default_language: str = DEFAULT_LANGUAGE,
        fallback_language: str = "en-US",
        auto_reload: bool = False,
    ):
        """
        初始化 i18n 管理器

        Args:
            locales_dir: 翻译资源目录，默认为本模块下的 locales/
            default_language: 默认语言
            fallback_language: 回退语言（当默认语言也找不到时使用）
            auto_reload: 是否自动重新加载（文件变更时）
        """
        if locales_dir is None:
            locales_dir = Path(__file__).parent / "locales"
        self._locales_dir = Path(locales_dir)
        self._default_language = default_language
        self._fallback_language = fallback_language
        self._auto_reload = auto_reload

        # 翻译缓存: {lang: {namespace: {key: value}}}
        self._translations: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # 文件修改时间缓存（用于自动重载）
        self._file_mtimes: Dict[str, float] = {}

        # 缺失的翻译键（用于统计和调试）
        self._missing_keys: Dict[str, set] = {}

        # 加载所有语言的翻译
        self._load_all_languages()

    # ------------------------------------------------------------------
    # 加载相关
    # ------------------------------------------------------------------

    def _load_all_languages(self) -> None:
        """加载所有支持语言的翻译文件"""
        if not self._locales_dir.exists():
            return

        for lang in SUPPORTED_LANGUAGES:
            lang_dir = self._locales_dir / lang
            if lang_dir.exists():
                self._load_language(lang, lang_dir)

    def _load_language(self, lang: str, lang_dir: Path) -> None:
        """加载指定语言的所有命名空间翻译文件"""
        self._translations.setdefault(lang, {})

        # 加载 JSON 文件
        for json_file in lang_dir.glob("*.json"):
            namespace = json_file.stem
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._translations[lang][namespace] = data
                self._file_mtimes[str(json_file)] = os.path.getmtime(json_file)
            except (json.JSONDecodeError, IOError) as e:
                # 加载失败时静默处理，使用空字典
                self._translations[lang].setdefault(namespace, {})

        # 加载 YAML 文件（如果 PyYAML 可用）
        try:
            import yaml  # type: ignore

            for yaml_file in list(lang_dir.glob("*.yaml")) + list(lang_dir.glob("*.yml")):
                namespace = yaml_file.stem
                try:
                    with open(yaml_file, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        if namespace in self._translations[lang]:
                            self._translations[lang][namespace].update(data)
                        else:
                            self._translations[lang][namespace] = data
                    self._file_mtimes[str(yaml_file)] = os.path.getmtime(yaml_file)
                except Exception:
                    pass
        except ImportError:
            pass

    def reload(self) -> None:
        """重新加载所有翻译文件"""
        self._translations.clear()
        self._file_mtimes.clear()
        self._missing_keys.clear()
        self._load_all_languages()

    # ------------------------------------------------------------------
    # 语言管理
    # ------------------------------------------------------------------

    @property
    def default_language(self) -> str:
        """默认语言"""
        return self._default_language

    @property
    def supported_languages(self) -> Dict[str, Dict[str, str]]:
        """支持的语言列表及元信息"""
        return SUPPORTED_LANGUAGES.copy()

    def is_supported(self, lang: str) -> bool:
        """检查语言是否受支持"""
        return lang in SUPPORTED_LANGUAGES

    def normalize_language(self, lang: str) -> str:
        """
        规范化语言代码

        将 en、zh-cn、ZH_CN 等格式规范化为 zh-CN / en-US 格式。
        """
        if not lang:
            return self._default_language

        lang = lang.strip().lower().replace("_", "-")

        # 精确匹配
        for supported in SUPPORTED_LANGUAGES:
            if supported.lower() == lang:
                return supported

        # 前缀匹配（如 "en" -> "en-US", "zh" -> "zh-CN"）
        prefix_map = {
            "zh": "zh-CN",
            "en": "en-US",
            "ja": "ja-JP",
        }
        base = lang.split("-")[0]
        if base in prefix_map:
            return prefix_map[base]

        return self._default_language

    def detect_language(
        self,
        accept_language: Optional[str] = None,
        cookie_lang: Optional[str] = None,
        user_preference: Optional[str] = None,
        query_param: Optional[str] = None,
    ) -> str:
        """
        检测用户语言偏好

        优先级：
        1. 查询参数 (?lang=xxx)
        2. 用户偏好（数据库中存储的设置）
        3. Cookie
        4. Accept-Language 请求头
        5. 默认语言
        """
        # 1. 查询参数
        if query_param and self.is_supported(self.normalize_language(query_param)):
            return self.normalize_language(query_param)

        # 2. 用户偏好
        if user_preference and self.is_supported(self.normalize_language(user_preference)):
            return self.normalize_language(user_preference)

        # 3. Cookie
        if cookie_lang and self.is_supported(self.normalize_language(cookie_lang)):
            return self.normalize_language(cookie_lang)

        # 4. Accept-Language 头
        if accept_language:
            parsed = self._parse_accept_language(accept_language)
            for lang_code, _ in parsed:
                normalized = self.normalize_language(lang_code)
                if self.is_supported(normalized):
                    return normalized

        # 5. 默认语言
        return self._default_language

    def _parse_accept_language(self, header: str) -> List[tuple[str, float]]:
        """
        解析 Accept-Language 请求头

        返回按质量值降序排列的 (language, quality) 列表。
        """
        result = []
        if not header:
            return result

        for part in header.split(","):
            part = part.strip()
            if not part:
                continue

            quality = 1.0
            if ";q=" in part:
                lang, q_str = part.split(";q=", 1)
                try:
                    quality = float(q_str.strip())
                except ValueError:
                    quality = 0.0
                lang = lang.strip()
            else:
                lang = part

            if lang:
                result.append((lang, quality))

        # 按质量降序排列
        result.sort(key=lambda x: x[1], reverse=True)
        return result

    # ------------------------------------------------------------------
    # 翻译查找
    # ------------------------------------------------------------------

    def t(
        self,
        key: str,
        language: Optional[str] = None,
        count: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """
        翻译查找

        Args:
            key: 翻译键，支持点号嵌套，如 "common.ok" 或 "errors.not_found.title"
            language: 目标语言，默认为当前上下文语言
            count: 数量（用于复数形式）
            **kwargs: 变量替换参数

        Returns:
            翻译后的文本。如果找不到翻译，返回 key 本身。
        """
        if language is None:
            language = _current_language_var.get()

        # 规范化语言
        language = self.normalize_language(language)

        # 解析命名空间和键
        namespace, rest_key = self._parse_key(key)

        # 查找翻译
        value = self._lookup(language, namespace, rest_key)

        # 回退到默认语言
        if value is None and language != self._default_language:
            value = self._lookup(self._default_language, namespace, rest_key)

        # 回退到英文
        if value is None and self._default_language != self._fallback_language:
            value = self._lookup(self._fallback_language, namespace, rest_key)

        # 还是找不到，记录缺失键，返回 key 本身
        if value is None:
            self._record_missing_key(language, key)
            return key

        # 处理复数形式
        if count is not None and isinstance(value, dict):
            plural_value = self._get_plural_form(value, count, language)
            if plural_value is not None:
                value = plural_value

        # 确保是字符串
        if not isinstance(value, str):
            value = str(value)

        # 变量替换
        if kwargs:
            try:
                value = value.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                # 变量替换失败，返回原始文本
                pass

        return value

    def _parse_key(self, key: str) -> tuple[str, str]:
        """
        解析翻译键，分离命名空间和剩余键路径

        "common.ok" -> ("common", "ok")
        "errors.not_found.title" -> ("errors", "not_found.title")
        "simple_key" -> ("common", "simple_key")
        """
        parts = key.split(".", 1)
        if len(parts) == 2 and parts[0] in self._get_namespaces():
            return parts[0], parts[1]
        # 默认命名空间为 common
        return "common", key

    def _get_namespaces(self) -> set:
        """获取所有命名空间"""
        namespaces = set()
        for lang_data in self._translations.values():
            namespaces.update(lang_data.keys())
        return namespaces

    def _lookup(self, language: str, namespace: str, key: str) -> Optional[Any]:
        """
        在指定语言和命名空间中查找翻译

        支持点号嵌套键。
        """
        lang_data = self._translations.get(language, {})
        ns_data = lang_data.get(namespace, {})

        if not ns_data:
            return None

        # 直接查找（键本身可能包含点号的情况作为整体）
        if key in ns_data:
            return ns_data[key]

        # 点号嵌套查找
        parts = key.split(".")
        current = ns_data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

        return current

    def _get_plural_form(
        self, plural_dict: Dict[str, str], count: int, language: str
    ) -> Optional[str]:
        """
        获取复数形式

        支持的复数键：
        - zero: 零个
        - one: 一个（单数）
        - two: 两个
        - few: 几个
        - many: 很多
        - other: 其他（复数默认）

        不同语言的复数规则不同：
        - 中文：只有 other 一种形式
        - 英文：one（1）和 other（其他）
        - 日文：只有 other 一种形式
        """
        if not isinstance(plural_dict, dict):
            return None

        # 根据语言选择复数规则
        if language.startswith("zh") or language.startswith("ja"):
            # 中文/日文：只有 other
            return plural_dict.get("other", plural_dict.get("one", str(plural_dict)))

        # 英文等
        if count == 0 and "zero" in plural_dict:
            return plural_dict["zero"]
        if count == 1 and "one" in plural_dict:
            return plural_dict["one"]
        if count == 2 and "two" in plural_dict:
            return plural_dict["two"]

        return plural_dict.get("other", plural_dict.get("many", str(plural_dict)))

    def _record_missing_key(self, language: str, key: str) -> None:
        """记录缺失的翻译键"""
        if language not in self._missing_keys:
            self._missing_keys[language] = set()
        self._missing_keys[language].add(key)

    def get_missing_keys(self, language: Optional[str] = None) -> Dict[str, List[str]]:
        """获取缺失的翻译键"""
        if language:
            return {language: sorted(list(self._missing_keys.get(language, set())))}
        return {
            lang: sorted(list(keys))
            for lang, keys in self._missing_keys.items()
        }

    # ------------------------------------------------------------------
    # 统计信息
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取国际化统计信息"""
        stats: Dict[str, Any] = {
            "default_language": self._default_language,
            "fallback_language": self._fallback_language,
            "supported_languages": list(SUPPORTED_LANGUAGES.keys()),
            "languages": {},
        }

        for lang in SUPPORTED_LANGUAGES:
            lang_data = self._translations.get(lang, {})
            total_keys = 0
            namespaces = {}
            for ns, ns_data in lang_data.items():
                count = self._count_keys(ns_data)
                namespaces[ns] = count
                total_keys += count

            missing_count = len(self._missing_keys.get(lang, set()))
            stats["languages"][lang] = {
                "info": SUPPORTED_LANGUAGES[lang],
                "namespaces": namespaces,
                "total_keys": total_keys,
                "missing_keys": missing_count,
            }

        return stats

    def _count_keys(self, data: Dict[str, Any]) -> int:
        """递归统计字典中的叶子键数量"""
        count = 0
        for value in data.values():
            if isinstance(value, dict):
                # 检查是否是复数形式字典
                if any(k in value for k in ["zero", "one", "two", "few", "many", "other"]):
                    count += 1
                else:
                    count += self._count_keys(value)
            else:
                count += 1
        return count

    def get_translations(self, language: str, namespace: Optional[str] = None) -> Dict[str, Any]:
        """获取指定语言的所有翻译"""
        language = self.normalize_language(language)
        lang_data = self._translations.get(language, {})

        if namespace:
            return lang_data.get(namespace, {})

        return lang_data

    def get_namespaces(self, language: Optional[str] = None) -> List[str]:
        """获取命名空间列表"""
        if language:
            language = self.normalize_language(language)
            return sorted(self._translations.get(language, {}).keys())
        return sorted(self._get_namespaces())


# ------------------------------------------------------------------
# 全局单例
# ------------------------------------------------------------------

_global_manager: Optional[I18nManager] = None


def get_i18n() -> I18nManager:
    """获取全局 i18n 管理器单例"""
    global _global_manager
    if _global_manager is None:
        _global_manager = I18nManager()
    return _global_manager


def t(key: str, **kwargs: Any) -> str:
    """
    快捷翻译函数

    使用全局 i18n 管理器进行翻译。

    Args:
        key: 翻译键
        **kwargs: 变量替换参数

    Returns:
        翻译后的文本
    """
    return get_i18n().t(key, **kwargs)


def _(key: str, **kwargs: Any) -> str:
    """
    翻译函数别名（gettext 风格）

    与 t() 相同，方便习惯 gettext 的开发者使用。
    """
    return t(key, **kwargs)


def set_current_language(lang: str) -> None:
    """设置当前上下文的语言"""
    normalized = get_i18n().normalize_language(lang)
    _current_language_var.set(normalized)


def get_current_language() -> str:
    """获取当前上下文的语言"""
    return _current_language_var.get()
