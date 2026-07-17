"""
安全测试套件

测试常见安全场景：
- XSS 攻击防护
- SQL 注入防护
- 路径遍历防护
- 命令注入防护
- 文件上传安全
- 敏感数据脱敏
- 安全响应头
- 速率限制
- 密码安全
- URL 安全
"""

import pytest
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.core.security import (
    escape_html,
    sanitize_html,
    xss_filter,
    safe_join_path,
    safe_filename,
    is_path_safe,
    normalize_path,
    validate_path_component,
    validate_file_upload,
    detect_file_type_by_magic,
    generate_safe_filename,
    mask_sensitive_data,
    mask_string,
    check_password_strength,
    constant_time_equals,
    secure_random_string,
    prevent_js_protocol,
    validate_url_safety,
    validate_input,
    strip_tags,
    ALLOWED_IMAGE_TYPES,
    DANGEROUS_EXTENSIONS,
)


class TestXSSProtection:
    """XSS 攻击防护测试"""

    def test_basic_xss_escaping(self):
        """测试基础 XSS 转义"""
        payload = "<script>alert('xss')</script>"
        result = escape_html(payload)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_xss_event_handlers(self):
        """测试事件处理器 XSS"""
        payload = '<img src=x onerror="alert(1)">'
        result = sanitize_html(payload)
        assert "onerror" not in result.lower()

    def test_xss_javascript_protocol(self):
        """测试 javascript: 协议 XSS"""
        payload = '<a href="javascript:alert(1)">click</a>'
        result = sanitize_html(payload)
        assert "javascript:" not in result.lower()

    def test_xss_strict_mode(self):
        """测试严格模式 XSS 过滤"""
        payload = "<b>Hello</b><script>alert(1)</script>"
        result = xss_filter(payload, mode="strict")
        assert "<b>" not in result
        assert "<script>" not in result

    def test_xss_basic_mode(self):
        """测试基础模式 XSS 过滤"""
        payload = "<script>alert(1)</script><b>Hello</b>"
        result = xss_filter(payload, mode="basic")
        assert "<script>" not in result
        assert "<b>" not in result  # basic 模式移除所有标签

    def test_xss_rich_mode(self):
        """测试富文本模式 XSS 过滤"""
        payload = "<b>Hello</b><script>alert(1)</script>"
        result = xss_filter(payload, mode="rich")
        assert "<script>" not in result
        # 安全标签应该保留
        assert "Hello" in result

    def test_xss_svg_onload(self):
        """测试 SVG onload XSS 被 WAF 检测"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/test",
            query="html=<svg onload='alert(1)'>",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert not result["passed"]
        assert "xss" in result["rule_type"].lower()

    def test_xss_expression(self):
        """测试 CSS expression XSS 被 WAF 检测"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/test",
            query="style=expression(alert(1))",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert not result["passed"]

    def test_xss_data_uri(self):
        """测试 data URI XSS 被 WAF 检测"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/test",
            query="url=data:text/html,<script>alert(1)</script>",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert not result["passed"]

    def test_xss_hex_encoding(self):
        """测试十六进制编码 XSS 被 WAF 检测"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/test",
            query="q=%3Cscript%3Ealert(1)%3C/script%3E",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert not result["passed"]


class TestSQLInjection:
    """SQL 注入防护测试"""

    def test_waf_sql_union_select(self):
        """测试 WAF 检测 UNION SELECT 注入"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/test",
            query="id=1' UNION SELECT * FROM users--",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert not result["passed"]
        assert "sql" in result["rule_type"].lower()

    def test_waf_sql_or_1_1(self):
        """测试 WAF 检测 OR 1=1 注入"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/test",
            query="id=' OR '1'='1",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert not result["passed"]

    def test_waf_sql_drop_table(self):
        """测试 WAF 检测 DROP TABLE 注入"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="POST",
            path="/api/test",
            query="",
            body="query=1; DROP TABLE users--",
            headers={},
            client_ip="127.0.0.1",
        )
        assert not result["passed"]

    def test_waf_sql_normal_input(self):
        """测试正常输入不被 WAF 误判"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/test",
            query="q=hello world&email=user@example.com",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert result["passed"]

    def test_validate_input_sql_pattern(self):
        """测试输入验证函数能正常工作"""
        # validate_input 验证单个值
        is_valid, error = validate_input(
            "hello_world",
            field_type="text",
            min_length=1,
            max_length=100,
        )
        # 正常输入应该通过验证
        assert is_valid
        assert error == ""

        # 测试长度超限
        is_valid, error = validate_input(
            "a" * 200,
            max_length=100,
        )
        assert not is_valid
        assert "长度超限" in error


class TestPathTraversal:
    """路径遍历防护测试"""

    def test_path_traversal_relative(self):
        """测试相对路径遍历检测"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # 尝试路径遍历应该被拒绝
            assert not is_path_safe("../../../etc/passwd", tmpdir)

    def test_waf_path_traversal(self):
        """测试 WAF 检测路径遍历"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/files",
            query="file=../../../etc/passwd",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert not result["passed"]

    def test_safe_join_path_normal(self):
        """测试正常路径拼接"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = safe_join_path(tmpdir, "subdir", "file.txt")
            assert result.startswith(os.path.realpath(tmpdir))

    def test_safe_join_path_traversal(self):
        """测试路径遍历被阻止"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="Path traversal"):
                safe_join_path(tmpdir, "../../etc/passwd")

    def test_is_path_safe(self):
        """测试路径安全检查"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            assert is_path_safe("file.txt", tmpdir)
            assert is_path_safe("subdir/file.txt", tmpdir)
            assert not is_path_safe("../../etc/passwd", tmpdir)

    def test_normalize_path(self):
        """测试路径规范化"""
        assert normalize_path("../../etc/passwd") == "etc/passwd"
        assert normalize_path("/etc/passwd") == "etc/passwd"
        assert normalize_path("a/./b/../c") == "a/c"

    def test_validate_path_component(self):
        """测试路径组件验证"""
        assert validate_path_component("file.txt")[0]
        assert validate_path_component("subdir")[0]
        assert not validate_path_component("../")[0]
        assert not validate_path_component("..")[0]
        assert not validate_path_component("a/b")[0]
        assert not validate_path_component("")[0]

    def test_safe_filename(self):
        """测试安全文件名"""
        assert safe_filename("../../../etc/passwd") == "passwd"
        # 空字节被替换为下划线
        assert "_" in safe_filename("file\x00name.txt")
        assert "\x00" not in safe_filename("file\x00name.txt")
        # 测试空文件名
        assert safe_filename("") == "unnamed"
        # 测试隐藏文件（去掉开头的点）
        assert not safe_filename(".hidden").startswith(".")


class TestCommandInjection:
    """命令注入防护测试"""

    def test_waf_command_semicolon(self):
        """测试 WAF 检测分号命令注入"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/test",
            query="cmd=test; cat /etc/passwd",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert not result["passed"]
        assert "command" in result["rule_type"].lower()

    def test_waf_command_pipe(self):
        """测试 WAF 检测管道命令注入"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/test",
            query="cmd=test | whoami",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert not result["passed"]

    def test_waf_command_backtick(self):
        """测试 WAF 检测反引号命令注入"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/test",
            query="cmd=`rm -rf /`",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert not result["passed"]

    def test_waf_command_normal_input(self):
        """测试正常输入不被 WAF 误判"""
        from shared.core.waf_middleware import WafEngineCore

        engine = WafEngineCore()
        result = engine.check_request(
            method="GET",
            path="/api/test",
            query="q=hello world&name=file-name.txt",
            body="",
            headers={},
            client_ip="127.0.0.1",
        )
        assert result["passed"]


class TestFileUploadSecurity:
    """文件上传安全测试"""

    def test_dangerous_extensions(self):
        """测试危险扩展名被拦截"""
        for ext in [".exe", ".php", ".js", ".sh", ".bat"]:
            is_safe, reason = validate_file_upload(
                filename=f"test{ext}",
                content_type="application/octet-stream",
            )
            assert not is_safe, f"{ext} 应该被拦截"

    def test_path_traversal_filename(self):
        """测试文件名路径遍历被拦截"""
        is_safe, reason = validate_file_upload(
            filename="../../../etc/passwd.jpg",
            content_type="image/jpeg",
        )
        assert not is_safe
        assert "路径" in reason or "path" in reason.lower()

    def test_null_byte_filename(self):
        """测试文件名为空字节被拦截"""
        is_safe, reason = validate_file_upload(
            filename="test\x00.jpg",
            content_type="image/jpeg",
        )
        assert not is_safe

    def test_mime_mismatch(self):
        """测试 MIME 类型不匹配"""
        # 声明是图片但扩展名是 pdf
        is_safe, reason = validate_file_upload(
            filename="test.pdf",
            content_type="image/jpeg",
            allowed_types=ALLOWED_IMAGE_TYPES,
        )
        assert not is_safe

    def test_valid_image_upload(self):
        """测试合法图片上传通过"""
        is_safe, reason = validate_file_upload(
            filename="test.jpg",
            content_type="image/jpeg",
            allowed_types=ALLOWED_IMAGE_TYPES,
        )
        assert is_safe, f"合法上传应该通过: {reason}"

    def test_file_size_limit(self):
        """测试文件大小限制"""
        # 创建一个超过 1KB 限制的内容
        large_content = b"x" * (2 * 1024)
        is_safe, reason = validate_file_upload(
            filename="test.jpg",
            content_type="image/jpeg",
            file_content=large_content,
            max_size_bytes=1024,
        )
        assert not is_safe
        assert "大小" in reason or "size" in reason.lower()

    def test_magic_number_detection_jpeg(self):
        """测试 JPEG 魔数检测"""
        jpeg_header = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        assert detect_file_type_by_magic(jpeg_header) == "image/jpeg"

    def test_magic_number_detection_png(self):
        """测试 PNG 魔数检测"""
        png_header = b"\x89PNG\r\n\x1a\n"
        assert detect_file_type_by_magic(png_header) == "image/png"

    def test_magic_number_detection_pdf(self):
        """测试 PDF 魔数检测"""
        pdf_header = b"%PDF-1.4\n"
        assert detect_file_type_by_magic(pdf_header) == "application/pdf"

    def test_generate_safe_filename(self):
        """测试生成安全文件名"""
        safe_name = generate_safe_filename("test.jpg", prefix="img_")
        assert safe_name.startswith("img_")
        # 扩展名会被 safe_filename 处理（移除前导点），所以是 jpg 不是 .jpg
        assert safe_name.endswith("jpg") or safe_name.endswith(".jpg")
        # 原始文件名主体应该被替换
        assert "test" not in safe_name
        # 应该包含随机部分
        assert len(safe_name) > len("img_") + 3

    def test_empty_filename(self):
        """测试空文件名被拒绝"""
        is_safe, reason = validate_file_upload(
            filename="",
            content_type="image/jpeg",
        )
        assert not is_safe


class TestSensitiveDataMasking:
    """敏感数据脱敏测试"""

    def test_mask_password(self):
        """测试密码脱敏"""
        text = "password: mySecretPass123"
        result = mask_sensitive_data(text)
        assert "mySecretPass123" not in result

    def test_mask_jwt_token(self):
        """测试 JWT Token 脱敏"""
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        text = f"Authorization: Bearer {token}"
        result = mask_sensitive_data(text)
        assert token[:20] not in result

    def test_mask_phone(self):
        """测试手机号脱敏"""
        text = "手机号：13812345678"
        result = mask_sensitive_data(text)
        assert "13812345678" not in result

    def test_mask_email(self):
        """测试邮箱脱敏"""
        text = "邮箱：user@example.com"
        result = mask_sensitive_data(text)
        assert "user@example.com" not in result or "user" not in result

    def test_mask_id_card(self):
        """测试身份证号脱敏"""
        text = "身份证：110101199001011234"
        result = mask_sensitive_data(text)
        assert "110101199001011234" not in result

    def test_mask_api_key(self):
        """测试 API Key 脱敏"""
        text = "api_key: sk-1234567890abcdef"
        result = mask_sensitive_data(text)
        assert "sk-1234567890abcdef" not in result

    def test_mask_string_function(self):
        """测试通用字符串脱敏函数"""
        result = mask_string("13812345678", keep_start=3, keep_end=4)
        assert result.startswith("138")
        assert result.endswith("5678")
        assert len(result) == 11


class TestPasswordSecurity:
    """密码安全测试"""

    def test_weak_password_short(self):
        """测试短密码被拒绝"""
        is_strong, msg, checks = check_password_strength("Abc123!")
        assert not is_strong
        assert not checks["min_length"]

    def test_weak_password_no_uppercase(self):
        """测试无大写字母的密码被拒绝"""
        is_strong, msg, checks = check_password_strength("abcdefgh123!")
        assert not is_strong
        assert not checks["has_uppercase"]

    def test_weak_password_no_lowercase(self):
        """测试无小写字母的密码被拒绝"""
        is_strong, msg, checks = check_password_strength("ABCDEFGH123!")
        assert not is_strong
        assert not checks["has_lowercase"]

    def test_weak_password_no_digit(self):
        """测试无数字的密码被拒绝"""
        is_strong, msg, checks = check_password_strength("Abcdefghij!")
        assert not is_strong
        assert not checks["has_digit"]

    def test_weak_password_common(self):
        """测试常见弱密码被拒绝"""
        # 使用常见弱密码列表中的密码
        is_strong, msg, checks = check_password_strength("password")
        assert not is_strong
        assert not checks["not_common"]

    def test_strong_password(self):
        """测试强密码通过"""
        is_strong, msg, checks = check_password_strength("MyStr0ngP@ssw0rd!")
        assert is_strong

    def test_constant_time_equals(self):
        """测试恒定时间比较"""
        assert constant_time_equals("abc", "abc")
        assert not constant_time_equals("abc", "abd")
        assert not constant_time_equals("abc", "ab")


class TestURLSecurity:
    """URL 安全测试"""

    def test_javascript_protocol(self):
        """测试 javascript: 协议被拦截"""
        result = prevent_js_protocol("javascript:alert(1)")
        assert result == "#"

    def test_javascript_protocol_encoded(self):
        """测试编码的 javascript: 协议被拦截"""
        result = prevent_js_protocol("java%0ascript:alert(1)")
        assert result == "#"

    def test_vbscript_protocol(self):
        """测试 vbscript: 协议被拦截"""
        result = prevent_js_protocol("vbscript:msgbox(1)")
        assert result == "#"

    def test_data_uri_base64(self):
        """测试 data: URI base64 被拦截"""
        result = prevent_js_protocol("data:text/html;base64,PHNjcmlwdD4=")
        assert result == "#"

    def test_normal_url(self):
        """测试正常 URL 通过"""
        url = "https://example.com/path"
        assert prevent_js_protocol(url) == url

    def test_validate_url_safety_http(self):
        """测试 HTTP URL 安全验证"""
        is_safe, reason = validate_url_safety("http://example.com")
        assert is_safe

    def test_validate_url_safety_https(self):
        """测试 HTTPS URL 安全验证"""
        is_safe, reason = validate_url_safety("https://example.com")
        assert is_safe

    def test_validate_url_safety_relative(self):
        """测试相对路径 URL 安全验证"""
        is_safe, reason = validate_url_safety("/path/to/page")
        assert is_safe

    def test_validate_url_safety_javascript(self):
        """测试 javascript: URL 被拒绝"""
        is_safe, reason = validate_url_safety("javascript:alert(1)")
        assert not is_safe

    def test_validate_url_safety_path_traversal(self):
        """测试路径遍历 URL 被拒绝"""
        is_safe, reason = validate_url_safety("../../../etc/passwd")
        assert not is_safe

    def test_validate_url_safety_null_byte(self):
        """测试含空字节的 URL 被拒绝"""
        is_safe, reason = validate_url_safety("http://example.com\x00")
        assert not is_safe


class TestRandomSecurity:
    """随机数安全测试"""

    def test_secure_random_string_length(self):
        """测试安全随机字符串长度"""
        result = secure_random_string(32)
        assert len(result) == 32

    def test_secure_random_string_url_safe(self):
        """测试 URL 安全的随机字符串"""
        result = secure_random_string(32, url_safe=True)
        # URL 安全字符不包含 + 和 /
        assert "+" not in result
        assert "/" not in result

    def test_secure_random_string_uniqueness(self):
        """测试随机字符串唯一性"""
        results = {secure_random_string(32) for _ in range(100)}
        assert len(results) == 100  # 100 个都不相同


class TestSecurityHeaders:
    """安全响应头测试（使用 FastAPI TestClient）"""

    def test_security_headers_config_default(self):
        """测试安全头配置默认值"""
        from shared.core.middleware.security_headers import SecurityHeadersConfig

        config = SecurityHeadersConfig()
        assert config.enabled
        assert config.content_type_options
        assert config.frame_options
        assert config.xss_protection
        assert config.referrer_policy

    def test_security_headers_get_headers(self):
        """测试获取安全头字典"""
        from shared.core.middleware.security_headers import SecurityHeadersConfig

        config = SecurityHeadersConfig(env="development")
        headers = config.get_headers("/api/test")

        assert "X-Content-Type-Options" in headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "X-Frame-Options" in headers
        assert "X-XSS-Protection" in headers
        assert "Referrer-Policy" in headers

    def test_security_headers_hsts_production(self):
        """测试生产环境 HSTS 启用"""
        from shared.core.middleware.security_headers import SecurityHeadersConfig

        config = SecurityHeadersConfig(env="production")
        headers = config.get_headers("/api/test")

        assert "Strict-Transport-Security" in headers
        assert "max-age=31536000" in headers["Strict-Transport-Security"]

    def test_security_headers_hsts_disabled_development(self):
        """测试开发环境 HSTS 不启用"""
        from shared.core.middleware.security_headers import SecurityHeadersConfig

        config = SecurityHeadersConfig(env="development")
        headers = config.get_headers("/api/test")

        # 开发环境默认不启用 HSTS
        assert "Strict-Transport-Security" not in headers

    def test_security_headers_cache_control(self):
        """测试 Cache-Control 安全头"""
        from shared.core.middleware.security_headers import SecurityHeadersConfig

        config = SecurityHeadersConfig(env="development")
        headers = config.get_headers("/api/sensitive")

        assert "Cache-Control" in headers
        assert "no-store" in headers["Cache-Control"]

    def test_security_headers_permissions_policy(self):
        """测试 Permissions-Policy 安全头"""
        from shared.core.middleware.security_headers import SecurityHeadersConfig

        config = SecurityHeadersConfig()
        headers = config.get_headers("/api/test")

        assert "Permissions-Policy" in headers

    def test_security_headers_disabled(self):
        """测试安全头禁用"""
        from shared.core.middleware.security_headers import SecurityHeadersConfig

        config = SecurityHeadersConfig(enabled=False)
        headers = config.get_headers("/api/test")

        assert headers == {}

    def test_csp_builder(self):
        """测试 CSP 构建器"""
        from shared.core.middleware.security_headers import CSPBuilder

        csp = (
            CSPBuilder()
            .default_src("'self'")
            .script_src("'self'", "https://cdn.example.com")
            .img_src("'self'", "data:")
            .style_src("'self'", "'unsafe-inline'")
            .build()
        )

        assert "default-src 'self'" in csp
        assert "script-src 'self' https://cdn.example.com" in csp
        assert "img-src 'self' data:" in csp
        assert "style-src 'self' 'unsafe-inline'" in csp


class TestRateLimit:
    """速率限制测试"""

    def test_sliding_window_counter(self):
        """测试滑动窗口计数器"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "rate_limiter",
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "..", "API-Gateway", "src", "services", "rate_limiter.py"
            )
        )
        # 直接使用 sys.path 方式导入
        api_gateway_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "API-Gateway", "src"
        )
        sys.path.insert(0, api_gateway_path)
        from services.rate_limiter import SlidingWindowCounter

        counter = SlidingWindowCounter(window_seconds=60, max_requests=5)

        # 前 5 次应该允许
        for i in range(5):
            allowed, remaining = counter.add_and_check()
            assert allowed

        # 第 6 次应该被拒绝
        allowed, remaining = counter.add_and_check()
        assert not allowed

    def test_rate_limit_tiers_exist(self):
        """测试限速级别定义存在"""
        api_gateway_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "API-Gateway", "src"
        )
        if api_gateway_path not in sys.path:
            sys.path.insert(0, api_gateway_path)
        from services.rate_limiter import RATE_LIMIT_TIERS

        assert "public" in RATE_LIMIT_TIERS
        assert "sensitive" in RATE_LIMIT_TIERS
        assert "strict" in RATE_LIMIT_TIERS
        assert "admin" in RATE_LIMIT_TIERS
        assert "mcp" in RATE_LIMIT_TIERS

    def test_sensitive_tier_stricter_than_public(self):
        """测试敏感接口限速比公开接口更严格"""
        api_gateway_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "API-Gateway", "src"
        )
        if api_gateway_path not in sys.path:
            sys.path.insert(0, api_gateway_path)
        from services.rate_limiter import RATE_LIMIT_TIERS

        public_limit = RATE_LIMIT_TIERS["public"].requests_per_minute
        sensitive_limit = RATE_LIMIT_TIERS["sensitive"].requests_per_minute

        assert sensitive_limit < public_limit

    def test_login_failure_tracking(self):
        """测试登录失败追踪功能"""
        api_gateway_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "API-Gateway", "src"
        )
        if api_gateway_path not in sys.path:
            sys.path.insert(0, api_gateway_path)
        from services.rate_limiter import RateLimiter

        limiter = RateLimiter()
        username = "testuser"
        ip = "192.168.1.100"

        # 初始状态应该允许登录
        allowed, info = limiter.check_login_allowed(username, ip)
        assert allowed
        assert info["failures"] == 0

        # 记录 4 次失败，应该还能尝试
        for i in range(4):
            result = limiter.record_login_failure(username, ip)

        allowed, info = limiter.check_login_allowed(username, ip)
        assert allowed  # 还没到阈值
        assert info["failures"] == 4

    def test_login_lock_after_max_failures(self):
        """测试达到最大失败次数后锁定"""
        api_gateway_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "API-Gateway", "src"
        )
        if api_gateway_path not in sys.path:
            sys.path.insert(0, api_gateway_path)
        from services.rate_limiter import RateLimiter

        limiter = RateLimiter()
        username = "locktestuser"
        ip = "192.168.1.101"

        # 记录 5 次失败（达到阈值）
        for i in range(5):
            result = limiter.record_login_failure(username, ip)

        # 第 5 次后应该被锁定
        assert result["locked"]
        assert result["lock_count"] == 1

        # 检查登录应该被拒绝
        allowed, info = limiter.check_login_allowed(username, ip)
        assert not allowed
        assert info["reason"] == "account_locked"

    def test_login_success_clears_failures(self):
        """测试登录成功清除失败计数"""
        api_gateway_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "API-Gateway", "src"
        )
        if api_gateway_path not in sys.path:
            sys.path.insert(0, api_gateway_path)
        from services.rate_limiter import RateLimiter

        limiter = RateLimiter()
        username = "successtest"
        ip = "192.168.1.102"

        # 记录几次失败
        for i in range(3):
            limiter.record_login_failure(username, ip)

        # 登录成功
        limiter.record_login_success(username, ip)

        # 失败计数应该被清除
        allowed, info = limiter.check_login_allowed(username, ip)
        assert allowed
        assert info["failures"] == 0

    def test_api_key_rate_limit(self):
        """测试 API Key 限速"""
        api_gateway_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "API-Gateway", "src"
        )
        if api_gateway_path not in sys.path:
            sys.path.insert(0, api_gateway_path)
        from services.rate_limiter import RateLimiter

        limiter = RateLimiter()
        api_key = "test-api-key-123"

        # 设置限制为 3 次/分钟
        limiter.set_api_key_limit(api_key, requests_per_minute=3)

        # 前 3 次应该允许
        for i in range(3):
            allowed, info = limiter.check_api_key_rate_limit(api_key)
            assert allowed

        # 第 4 次应该被拒绝
        allowed, info = limiter.check_api_key_rate_limit(api_key)
        assert not allowed
        assert info["reason"] == "api_key_rate_limit_exceeded"


# ---------------------------------------------------------------------------
# 运行测试
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
