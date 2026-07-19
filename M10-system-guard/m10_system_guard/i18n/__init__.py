"""
M10 系统卫士 - i18n 国际化模块

基于 shared.i18n 构建，提供 M10 模块专属的翻译资源。
翻译文件位于 locales/ 目录下，支持 zh-CN 和 en-US。

使用方式：
    from m10_system_guard.i18n import t, _
    print(t("m10.errors.process_not_found"))

也可以直接使用 shared.i18n 的全局单例：
    from shared.i18n import t
    print(t("m10.errors.process_not_found"))
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

# 确保 shared 模块可导入
_current = Path(__file__).resolve()
for _ in range(10):
    _current = _current.parent
    if (_current / "shared" / "i18n" / "__init__.py").exists():
        if str(_current) not in sys.path:
            sys.path.insert(0, str(_current))
        break

# 从 shared.i18n 导入核心组件
try:
    from shared.i18n import I18nManager, get_i18n as _get_global_i18n
    from shared.i18n.core import (
        _current_language_var,
        set_current_language,
        get_current_language,
        DEFAULT_LANGUAGE,
        SUPPORTED_LANGUAGES,
    )
    _SHARED_I18N_AVAILABLE = True
except ImportError:
    _SHARED_I18N_AVAILABLE = False
    I18nManager = None  # type: ignore
    _current_language_var = None  # type: ignore
    DEFAULT_LANGUAGE = "zh-CN"
    SUPPORTED_LANGUAGES = {
        "zh-CN": {"name": "简体中文", "native_name": "简体中文", "direction": "ltr"},
        "en-US": {"name": "English (US)", "native_name": "English", "direction": "ltr"},
    }


# M10 翻译资源目录
_LOCALES_DIR = Path(__file__).parent / "locales"

# M10 命名空间前缀
M10_NAMESPACE = "m10"

# M10 i18n 管理器单例
_m10_i18n_manager: Optional["I18nManager"] = None


def get_m10_i18n():
    """
    获取 M10 模块的 i18n 管理器。

    优先使用 shared.i18n 的全局管理器（M10 的翻译文件会被加载到其中），
    如果 shared.i18n 不可用，则创建独立的 M10 i18n 管理器。
    """
    global _m10_i18n_manager

    if _m10_i18n_manager is not None:
        return _m10_i18n_manager

    if _SHARED_I18N_AVAILABLE:
        # 使用 shared.i18n 全局管理器，加载 M10 翻译文件
        manager = _get_global_i18n()
        # 加载 M10 翻译文件到全局管理器
        _load_m10_translations(manager)
        _m10_i18n_manager = manager
    else:
        # shared.i18n 不可用，使用独立的 I18nManager（如果可用）
        if I18nManager is not None:
            _m10_i18n_manager = I18nManager(
                locales_dir=_LOCALES_DIR,
                default_language=DEFAULT_LANGUAGE,
                fallback_language="en-US",
            )
        else:
            # 兜底：返回一个简单的翻译函数
            _m10_i18n_manager = _FallbackI18n()

    return _m10_i18n_manager


def _load_m10_translations(manager) -> None:
    """
    将 M10 的翻译文件加载到全局 i18n 管理器中。

    M10 的翻译使用 "m10" 命名空间前缀，如 "m10.errors.process_not_found"。
    """
    import json
    import os

    if not _LOCALES_DIR.exists():
        return

    for lang_dir in _LOCALES_DIR.iterdir():
        if not lang_dir.is_dir():
            continue

        lang = lang_dir.name
        if lang not in SUPPORTED_LANGUAGES:
            continue

        # 确保语言在管理器中存在
        if lang not in manager._translations:
            manager._translations[lang] = {}

        for json_file in lang_dir.glob("*.json"):
            # 使用 "m10" 作为命名空间前缀
            namespace = f"{M10_NAMESPACE}_{json_file.stem}"
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if namespace in manager._translations[lang]:
                    manager._translations[lang][namespace].update(data)
                else:
                    manager._translations[lang][namespace] = data

                manager._file_mtimes[str(json_file)] = os.path.getmtime(json_file)
            except (json.JSONDecodeError, IOError):
                pass


def t(key: str, **kwargs: Any) -> str:
    """
    M10 翻译函数。

    自动添加 m10 命名空间前缀，然后调用全局 i18n 管理器翻译。

    Args:
        key: 翻译键（自动添加 m10_ 前缀到命名空间）
        **kwargs: 变量替换参数

    Returns:
        翻译后的文本
    """
    manager = get_m10_i18n()
    return manager.t(key, **kwargs)


def _(key: str, **kwargs: Any) -> str:
    """翻译函数别名（gettext 风格）。"""
    return t(key, **kwargs)


class _FallbackI18n:
    """
    兜底 i18n 实现（当 shared.i18n 完全不可用时使用）。

    仅支持基本的翻译查找，不支持高级功能。
    """

    def __init__(self):
        self._translations = {}
        self._default_language = DEFAULT_LANGUAGE
        self._load_all()

    def _load_all(self):
        import json
        if not _LOCALES_DIR.exists():
            return
        for lang_dir in _LOCALES_DIR.iterdir():
            if not lang_dir.is_dir():
                continue
            lang = lang_dir.name
            self._translations.setdefault(lang, {})
            for json_file in lang_dir.glob("*.json"):
                namespace = f"{M10_NAMESPACE}_{json_file.stem}"
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        self._translations[lang][namespace] = json.load(f)
                except Exception:
                    pass

    def t(self, key: str, language: Optional[str] = None, **kwargs) -> str:
        if language is None:
            language = self._default_language

        # 解析命名空间和键
        parts = key.split(".", 1)
        if len(parts) == 2:
            namespace, rest_key = parts
        else:
            namespace = f"{M10_NAMESPACE}_common"
            rest_key = key

        # 查找翻译
        value = self._lookup(language, namespace, rest_key)
        if value is None and language != self._default_language:
            value = self._lookup(self._default_language, namespace, rest_key)
        if value is None:
            return key

        if kwargs and isinstance(value, str):
            try:
                value = value.format(**kwargs)
            except Exception:
                pass

        return value

    def _lookup(self, language, namespace, key):
        lang_data = self._translations.get(language, {})
        ns_data = lang_data.get(namespace, {})
        if not ns_data:
            return None
        if key in ns_data:
            return ns_data[key]
        parts = key.split(".")
        current = ns_data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    @property
    def default_language(self) -> str:
        return self._default_language


__all__ = [
    "t",
    "_",
    "get_m10_i18n",
    "M10_NAMESPACE",
    "DEFAULT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
]
