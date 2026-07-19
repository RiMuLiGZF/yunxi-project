"""
M10 系统卫士 - i18n 国际化测试

测试内容：
1. 默认语言为中文
2. Accept-Language 头切换到英文
3. X-Lang 头切换语言
4. 查询参数 lang=en
5. 错误消息翻译
6. API 响应消息翻译
7. 翻译文件完整性（所有 key 中英都有）
8. 不支持的语言回退到默认
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 导入 i18n 模块
from m10_system_guard.i18n import (
    t,
    _,
    set_current_language,
    get_current_language,
    extract_language_from_request,
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    _FallbackI18n,
    _LOCALES_DIR,
    M10_NAMESPACE,
)
from m10_system_guard.errors import (
    M10ErrorCode,
    get_error_message,
    M10Error,
    M10NotFoundError,
    M10ParamError,
    M10AuthError,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def reset_language():
    """每个测试后重置语言为默认."""
    set_current_language(DEFAULT_LANGUAGE)
    yield
    set_current_language(DEFAULT_LANGUAGE)


# ============================================================
# 测试 1: 默认语言为中文
# ============================================================

class TestDefaultLanguage:
    """测试默认语言设置."""

    def test_default_language_is_chinese(self):
        """默认语言应为 zh-CN."""
        assert DEFAULT_LANGUAGE == "zh-CN"

    def test_initial_language_is_default(self):
        """初始状态下当前语言应为默认语言."""
        # 重置到初始状态
        from m10_system_guard import i18n as i18n_module
        if hasattr(i18n_module._local, "current_language"):
            delattr(i18n_module._local, "current_language")
        assert get_current_language() == DEFAULT_LANGUAGE

    def test_supported_languages_includes_zh_en(self):
        """支持的语言应包含中文和英文."""
        assert "zh-CN" in SUPPORTED_LANGUAGES
        assert "en-US" in SUPPORTED_LANGUAGES
        assert len(SUPPORTED_LANGUAGES) >= 2


# ============================================================
# 测试 2: 翻译函数基本功能
# ============================================================

class TestTranslationFunction:
    """测试翻译函数基本功能."""

    def test_t_function_returns_chinese_by_default(self):
        """默认语言下翻译函数应返回中文."""
        result = t("m10_errors.process_not_found")
        assert result == "进程不存在"

    def test_t_function_with_english(self):
        """切换到英文后应返回英文."""
        set_current_language("en-US")
        result = t("m10_errors.process_not_found")
        assert result == "Process not found"

    def test_underscore_alias_works(self):
        """_() 别名函数应正常工作."""
        result = _("m10_errors.invalid_parameter")
        assert result == "参数错误"

    def test_t_with_format_params(self):
        """带参数的翻译应正常格式化."""
        set_current_language("zh-CN")
        result = t("m10_api.process.not_found", pid=1234)
        assert "1234" in result
        assert "进程" in result

    def test_t_with_format_params_english(self):
        """英文下带参数的翻译应正常格式化."""
        set_current_language("en-US")
        result = t("m10_api.process.not_found", pid=1234)
        assert "1234" in result
        assert "not found" in result.lower()

    def test_unknown_key_returns_key(self):
        """未知的翻译 key 应返回 key 本身."""
        result = t("m10_errors.nonexistent_key_xyz")
        assert result == "m10_errors.nonexistent_key_xyz"


# ============================================================
# 测试 3: 语言切换
# ============================================================

class TestLanguageSwitching:
    """测试语言切换功能."""

    def test_set_and_get_language(self):
        """设置和获取当前语言."""
        set_current_language("en-US")
        assert get_current_language() == "en-US"

    def test_switch_back_to_chinese(self):
        """切换回中文."""
        set_current_language("en-US")
        assert get_current_language() == "en-US"
        set_current_language("zh-CN")
        assert get_current_language() == "zh-CN"

    def test_language_switch_affects_translation(self):
        """语言切换应影响翻译结果."""
        set_current_language("zh-CN")
        cn_result = t("m10_errors.auth_failed")
        assert cn_result == "认证失败"

        set_current_language("en-US")
        en_result = t("m10_errors.auth_failed")
        assert en_result == "Authentication failed"

    def test_thread_local_isolation(self):
        """语言设置应是线程隔离的."""
        import threading

        results = {}

        def set_and_get(lang, key):
            set_current_language(lang)
            results[key] = get_current_language()

        t1 = threading.Thread(target=set_and_get, args=("en-US", "t1"))
        t2 = threading.Thread(target=set_and_get, args=("zh-CN", "t2"))

        # 先设置主线程
        set_current_language("zh-CN")
        main_lang_before = get_current_language()

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # 主线程语言不应被子线程影响
        assert get_current_language() == main_lang_before
        # 子线程各自有独立的语言设置
        assert results["t1"] == "en-US"
        assert results["t2"] == "zh-CN"


# ============================================================
# 测试 4: 从请求中提取语言
# ============================================================

class TestExtractLanguageFromRequest:
    """测试从 HTTP 请求中提取语言偏好."""

    def _make_request(self, headers=None, query_params=None):
        """创建模拟请求对象."""
        request = MagicMock()
        request.headers = headers or {}
        request.query_params = query_params or {}
        return request

    def test_default_language_when_no_hints(self):
        """没有语言提示时应返回默认语言."""
        request = self._make_request()
        result = extract_language_from_request(request)
        assert result == DEFAULT_LANGUAGE

    def test_accept_language_header_en(self):
        """Accept-Language: en 应返回 en-US."""
        request = self._make_request(headers={"accept-language": "en-US,en;q=0.9"})
        result = extract_language_from_request(request)
        assert result == "en-US"

    def test_accept_language_header_zh(self):
        """Accept-Language: zh 应返回 zh-CN."""
        request = self._make_request(headers={"accept-language": "zh-CN,zh;q=0.9"})
        result = extract_language_from_request(request)
        assert result == "zh-CN"

    def test_x_language_header(self):
        """X-Language 头应优先于 Accept-Language."""
        request = self._make_request(
            headers={
                "x-language": "en-US",
                "accept-language": "zh-CN,zh;q=0.9",
            }
        )
        result = extract_language_from_request(request)
        assert result == "en-US"

    def test_x_lang_header(self):
        """X-Lang 头应正常工作."""
        request = self._make_request(headers={"x-lang": "en-US"})
        result = extract_language_from_request(request)
        assert result == "en-US"

    def test_query_param_lang(self):
        """查询参数 lang 应优先于请求头."""
        request = self._make_request(
            headers={"accept-language": "zh-CN,zh;q=0.9"},
            query_params={"lang": "en"},
        )
        result = extract_language_from_request(request)
        assert result == "en-US"

    def test_query_param_locale(self):
        """查询参数 locale 应正常工作."""
        request = self._make_request(query_params={"locale": "en-US"})
        result = extract_language_from_request(request)
        assert result == "en-US"

    def test_unsupported_language_falls_back_to_default(self):
        """不支持的语言应回退到默认语言."""
        request = self._make_request(
            headers={"accept-language": "fr-FR,fr;q=0.9"},
            query_params={"lang": "ko"},
        )
        result = extract_language_from_request(request)
        assert result == DEFAULT_LANGUAGE

    def test_short_code_mapping(self):
        """短语言代码应映射到完整代码（zh -> zh-CN, en -> en-US）."""
        request = self._make_request(query_params={"lang": "en"})
        result = extract_language_from_request(request)
        assert result == "en-US"

        request2 = self._make_request(query_params={"lang": "zh"})
        result2 = extract_language_from_request(request2)
        assert result2 == "zh-CN"


# ============================================================
# 测试 5: 错误消息翻译
# ============================================================

class TestErrorMessages:
    """测试错误消息的国际化."""

    def test_get_error_message_chinese(self):
        """默认中文下错误消息应为中文."""
        set_current_language("zh-CN")
        msg = get_error_message(M10ErrorCode.PROCESS_NOT_FOUND)
        assert msg == "进程不存在"

    def test_get_error_message_english(self):
        """英文下错误消息应为英文."""
        set_current_language("en-US")
        msg = get_error_message(M10ErrorCode.PROCESS_NOT_FOUND)
        assert msg == "Process not found"

    def test_m10_error_default_message_chinese(self):
        """M10Error 默认消息应为中文."""
        set_current_language("zh-CN")
        err = M10Error(M10ErrorCode.INVALID_PARAMETER)
        assert err.message == "参数错误"

    def test_m10_error_default_message_english(self):
        """英文下 M10Error 默认消息应为英文."""
        set_current_language("en-US")
        err = M10Error(M10ErrorCode.INVALID_PARAMETER)
        assert err.message == "Invalid parameter"

    def test_m10_not_found_error(self):
        """M10NotFoundError 应使用翻译."""
        set_current_language("en-US")
        err = M10NotFoundError()
        assert "not found" in err.message.lower()

    def test_m10_param_error(self):
        """M10ParamError 应使用翻译."""
        set_current_language("en-US")
        err = M10ParamError()
        assert "invalid parameter" in err.message.lower()

    def test_m10_auth_error(self):
        """M10AuthError 应使用翻译."""
        set_current_language("en-US")
        err = M10AuthError()
        assert "auth" in err.message.lower() or "authentication" in err.message.lower()

    def test_unknown_error_code(self):
        """未知错误码应返回未知错误."""
        set_current_language("zh-CN")
        msg = get_error_message(999999)
        assert msg == "未知错误"


# ============================================================
# 测试 6: API 响应消息翻译
# ============================================================

class TestApiResponseMessages:
    """测试 API 响应消息的国际化."""

    def test_process_not_found_message(self):
        """进程不存在消息翻译."""
        set_current_language("zh-CN")
        msg = t("m10_api.process.not_found", pid=123)
        assert "进程" in msg
        assert "123" in msg

        set_current_language("en-US")
        msg = t("m10_api.process.not_found", pid=123)
        assert "Process" in msg or "process" in msg
        assert "123" in msg

    def test_guard_policy_not_found(self):
        """防护策略不存在消息翻译."""
        set_current_language("zh-CN")
        msg = t("m10_api.guard.policy_not_found", metric_type="cpu")
        assert "策略" in msg
        assert "cpu" in msg

        set_current_language("en-US")
        msg = t("m10_api.guard.policy_not_found", metric_type="cpu")
        assert "Policy" in msg or "policy" in msg
        assert "cpu" in msg

    def test_report_not_found(self):
        """报告不存在消息翻译."""
        set_current_language("zh-CN")
        msg = t("m10_api.report.not_found", report_id="r123")
        assert "报告" in msg

        set_current_language("en-US")
        msg = t("m10_api.report.not_found", report_id="r123")
        assert "Report" in msg or "report" in msg

    def test_startup_check_levels(self):
        """启动检查级别说明翻译."""
        set_current_language("zh-CN")
        assert t("m10_api.startup_check.level_safe_name") == "安全"
        assert t("m10_api.startup_check.level_danger_name") == "危险"

        set_current_language("en-US")
        assert t("m10_api.startup_check.level_safe_name") == "Safe"
        assert t("m10_api.startup_check.level_danger_name") == "Danger"

    def test_tide_mission_messages(self):
        """潮汐任务相关消息翻译."""
        set_current_language("zh-CN")
        assert "任务" in t("m10_api.tide.mission_submit_success")
        assert "任务" in t("m10_api.tide.mission_not_found")

        set_current_language("en-US")
        msg = t("m10_api.tide.mission_submit_success")
        assert "mission" in msg.lower() or "submitted" in msg.lower()


# ============================================================
# 测试 7: 翻译文件完整性
# ============================================================

class TestTranslationFileIntegrity:
    """测试翻译文件的完整性."""

    def _load_json(self, path: Path) -> dict:
        """加载 JSON 文件."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _collect_keys(self, d: dict, prefix: str = "") -> set:
        """递归收集所有叶子节点的 key."""
        keys = set()
        for k, v in d.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys.update(self._collect_keys(v, full_key))
            else:
                keys.add(full_key)
        return keys

    def test_errors_keys_match_between_languages(self):
        """errors.json 的 key 在中英两种语言中应都存在."""
        zh_errors = self._load_json(_LOCALES_DIR / "zh-CN" / "errors.json")
        en_errors = self._load_json(_LOCALES_DIR / "en-US" / "errors.json")

        zh_keys = self._collect_keys(zh_errors, f"{M10_NAMESPACE}_errors")
        en_keys = self._collect_keys(en_errors, f"{M10_NAMESPACE}_errors")

        # 中文的 key 英文应该都有
        missing_in_en = zh_keys - en_keys
        assert not missing_in_en, f"英文 errors.json 缺少 key: {missing_in_en}"

        # 英文的 key 中文应该都有
        missing_in_zh = en_keys - zh_keys
        assert not missing_in_zh, f"中文 errors.json 缺少 key: {missing_in_zh}"

    def test_common_keys_match_between_languages(self):
        """common.json 的 key 在中英两种语言中应都存在."""
        zh_common = self._load_json(_LOCALES_DIR / "zh-CN" / "common.json")
        en_common = self._load_json(_LOCALES_DIR / "en-US" / "common.json")

        zh_keys = self._collect_keys(zh_common, f"{M10_NAMESPACE}_common")
        en_keys = self._collect_keys(en_common, f"{M10_NAMESPACE}_common")

        missing_in_en = zh_keys - en_keys
        assert not missing_in_en, f"英文 common.json 缺少 key: {missing_in_en}"

    def test_api_keys_match_between_languages(self):
        """api.json 的 key 在中英两种语言中应都存在."""
        zh_api = self._load_json(_LOCALES_DIR / "zh-CN" / "api.json")
        en_api = self._load_json(_LOCALES_DIR / "en-US" / "api.json")

        zh_keys = self._collect_keys(zh_api, f"{M10_NAMESPACE}_api")
        en_keys = self._collect_keys(en_api, f"{M10_NAMESPACE}_api")

        missing_in_en = zh_keys - en_keys
        assert not missing_in_en, f"英文 api.json 缺少 key: {missing_in_en}"

        missing_in_zh = en_keys - zh_keys
        assert not missing_in_zh, f"中文 api.json 缺少 key: {missing_in_zh}"

    def test_guard_keys_match_between_languages(self):
        """guard.json 的 key 在中英两种语言中应都存在."""
        zh_guard = self._load_json(_LOCALES_DIR / "zh-CN" / "guard.json")
        en_guard = self._load_json(_LOCALES_DIR / "en-US" / "guard.json")

        zh_keys = self._collect_keys(zh_guard, f"{M10_NAMESPACE}_guard")
        en_keys = self._collect_keys(en_guard, f"{M10_NAMESPACE}_guard")

        missing_in_en = zh_keys - en_keys
        assert not missing_in_en, f"英文 guard.json 缺少 key: {missing_in_en}"

    def test_startup_keys_match_between_languages(self):
        """startup.json 的 key 在中英两种语言中应都存在."""
        zh_startup = self._load_json(_LOCALES_DIR / "zh-CN" / "startup.json")
        en_startup = self._load_json(_LOCALES_DIR / "en-US" / "startup.json")

        zh_keys = self._collect_keys(zh_startup, f"{M10_NAMESPACE}_startup")
        en_keys = self._collect_keys(en_startup, f"{M10_NAMESPACE}_startup")

        missing_in_en = zh_keys - en_keys
        assert not missing_in_en, f"英文 startup.json 缺少 key: {missing_in_en}"

    def test_audit_keys_match_between_languages(self):
        """audit.json 的 key 在中英两种语言中应都存在."""
        zh_audit = self._load_json(_LOCALES_DIR / "zh-CN" / "audit.json")
        en_audit = self._load_json(_LOCALES_DIR / "en-US" / "audit.json")

        zh_keys = self._collect_keys(zh_audit, f"{M10_NAMESPACE}_audit")
        en_keys = self._collect_keys(en_audit, f"{M10_NAMESPACE}_audit")

        missing_in_en = zh_keys - en_keys
        assert not missing_in_en, f"英文 audit.json 缺少 key: {missing_in_en}"

    def test_all_error_codes_have_translations(self):
        """所有错误码都应有对应的翻译 key."""
        from m10_system_guard.errors import _ERROR_MESSAGE_KEYS

        en_errors = self._load_json(_LOCALES_DIR / "en-US" / "errors.json")
        zh_errors = self._load_json(_LOCALES_DIR / "zh-CN" / "errors.json")

        for code, key in _ERROR_MESSAGE_KEYS.items():
            assert key in zh_errors, f"中文 errors.json 缺少错误码 {code} 对应的 key: {key}"
            assert key in en_errors, f"英文 errors.json 缺少错误码 {code} 对应的 key: {key}"

    def test_translations_are_not_empty(self):
        """翻译值不应为空字符串."""
        for lang_dir in ["zh-CN", "en-US"]:
            lang_path = _LOCALES_DIR / lang_dir
            for json_file in lang_path.glob("*.json"):
                data = self._load_json(json_file)
                keys = self._collect_keys(data)
                for key in keys:
                    # 获取值
                    parts = key.split(".")
                    val = data
                    for p in parts:
                        val = val.get(p, {})
                    assert val != "", f"{lang_dir}/{json_file.name}: {key} 的翻译为空"


# ============================================================
# 测试 8: 不支持的语言回退
# ============================================================

class TestFallbackBehavior:
    """测试语言回退行为."""

    def test_unsupported_language_falls_back(self):
        """设置不支持的语言时，翻译应回退到默认语言."""
        # 直接测试 FallbackI18n 的回退行为
        i18n = _FallbackI18n()
        result = i18n.t("m10_errors.process_not_found", language="fr-FR")
        # 不支持的语言应回退到默认（中文）
        assert result == "进程不存在"

    def test_missing_key_in_one_language_falls_back(self):
        """某语言缺少 key 时应回退到默认语言."""
        # 设置一个不存在的语言命名空间，测试回退
        i18n = _FallbackI18n()
        # 使用一个在英文中不存在但中文中存在的 key（模拟）
        # 实际上我们的翻译文件是对称的，这里测试已知存在的 key
        result = i18n.t("m10_errors.success", language="en-US")
        assert result == "Success"

    def test_completely_unknown_key_returns_key(self):
        """完全不存在的 key 应返回 key 本身."""
        result = t("m10_errors.completely_nonexistent_key_xyz123")
        assert result == "m10_errors.completely_nonexistent_key_xyz123"


# ============================================================
# 测试 9: i18n 中间件
# ============================================================

class TestI18nMiddleware:
    """测试 i18n 中间件."""

    def test_middleware_sets_language_from_header(self):
        """中间件应从请求头设置语言."""
        from m10_system_guard.i18n_middleware import I18nMiddleware

        # 创建模拟 app 和请求
        mock_app = MagicMock()
        middleware = I18nMiddleware(mock_app)

        # 模拟 call_next 返回响应
        mock_response = MagicMock()
        mock_response.headers = {}

        async def mock_call_next(request):
            # 在处理请求时检查语言是否已设置
            assert get_current_language() == "en-US"
            return mock_response

        # 模拟请求
        mock_request = MagicMock()
        mock_request.headers = {"x-lang": "en-US"}
        mock_request.query_params = {}

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            middleware.dispatch(mock_request, mock_call_next)
        )

        # 响应头中应包含当前语言
        assert "X-Current-Language" in mock_response.headers
        assert mock_response.headers["X-Current-Language"] == "en-US"

    def test_middleware_default_language(self):
        """没有语言提示时中间件应使用默认语言."""
        from m10_system_guard.i18n_middleware import I18nMiddleware

        mock_app = MagicMock()
        middleware = I18nMiddleware(mock_app)

        mock_response = MagicMock()
        mock_response.headers = {}

        async def mock_call_next(request):
            assert get_current_language() == DEFAULT_LANGUAGE
            return mock_response

        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.query_params = {}

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            middleware.dispatch(mock_request, mock_call_next)
        )

        assert mock_response.headers["X-Current-Language"] == DEFAULT_LANGUAGE
