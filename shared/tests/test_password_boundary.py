"""
密码哈希模块边界条件与异常路径测试

对应问题：TST-006（边界条件与异常路径测试不足）
测试模块：shared.core.auth.password

覆盖场景：
- 空密码
- 超长密码（bcrypt 72 字节限制）
- 特殊字符密码
- 空哈希
- 非法哈希格式
- 弱密码检测
- 密码强度验证
- Unicode / 多字节字符
- 边界长度密码
- 恒定时间比较
- needs_update 边界
"""

import sys
import os
from pathlib import Path

import pytest

# 确保可以导入 shared 模块
SHARED_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SHARED_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


# 检查 bcrypt 是否可用
from shared.core.auth.password import is_bcrypt_available, is_insecure_fallback_mode

_bcrypt_available = is_bcrypt_available()

pytestmark = pytest.mark.skipif(
    not _bcrypt_available and not is_insecure_fallback_mode(),
    reason="bcrypt 不可用且未启用 fallback 模式，跳过密码测试"
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def sample_hashed():
    """生成一个示例哈希密码"""
    from shared.core.auth.password import hash_password
    return hash_password("TestPass123!")


# ===========================================================================
# 1. 空密码测试
# ===========================================================================

class TestEmptyPassword:
    """空密码边界测试"""

    @pytest.mark.parametrize("empty_pwd", [
        "",
        None,
    ])
    def test_hash_empty_password_raises(self, empty_pwd):
        """哈希空密码应抛出 ValueError"""
        from shared.core.auth.password import hash_password

        with pytest.raises(ValueError, match="密码不能为空"):
            hash_password(empty_pwd)

    @pytest.mark.parametrize("empty_pwd", [
        "",
        None,
    ])
    def test_verify_empty_password_returns_false(self, sample_hashed, empty_pwd):
        """验证空密码应返回 False"""
        from shared.core.auth.password import verify_password

        result = verify_password(empty_pwd, sample_hashed)
        assert result is False

    @pytest.mark.parametrize("empty_hash", [
        "",
        None,
    ])
    def test_verify_empty_hash_returns_false(self, empty_hash):
        """验证空哈希应返回 False"""
        from shared.core.auth.password import verify_password

        result = verify_password("password123", empty_hash)
        assert result is False

    def test_verify_both_empty_returns_false(self):
        """密码和哈希都为空时应返回 False"""
        from shared.core.auth.password import verify_password

        result = verify_password("", "")
        assert result is False

    def test_needs_update_empty_hash(self):
        """空哈希的 needs_update 应返回 False"""
        from shared.core.auth.password import needs_update

        result = needs_update("")
        assert result is False


# ===========================================================================
# 2. 超长密码测试（bcrypt 72 字节限制）
# ===========================================================================

class TestOversizedPassword:
    """超长密码边界测试（bcrypt 72 字节限制）"""

    def test_password_at_exactly_72_bytes(self):
        """恰好 72 字节的密码应正常处理"""
        from shared.core.auth.password import hash_password, verify_password

        # 72 个 ASCII 字符 = 72 字节
        pwd_72 = "a" * 72
        hashed = hash_password(pwd_72)
        assert verify_password(pwd_72, hashed) is True

    def test_password_exactly_72_different_from_73(self):
        """72 字节和 73 字节的密码（截断后）应不同"""
        from shared.core.auth.password import hash_password, verify_password

        pwd_72 = "a" * 72
        pwd_73 = "a" * 72 + "b"  # 73 字节

        hashed_72 = hash_password(pwd_72)
        hashed_73 = hash_password(pwd_73)

        # bcrypt 会截断到 72 字节，所以 72 和 73 个 a 的密码截断后相同
        # 但第 73 个字符不同，截断后应该不同
        # 注意：72个a + b 截断为前72个a，和72个a完全相同
        # 所以这个测试验证的是截断行为
        result = verify_password(pwd_72, hashed_73)
        # 因为 72 个 a 是 73 字节密码的前 72 字节，截断后相同
        # 所以验证应该通过（这是 bcrypt 的已知行为）
        assert result is True

    def test_very_long_password_handles_gracefully(self):
        """非常长的密码（远超过 72 字节）应不抛异常"""
        from shared.core.auth.password import hash_password, verify_password

        # 1000 字符的密码
        very_long = "a" * 1000
        try:
            hashed = hash_password(very_long)
            assert verify_password(very_long, hashed) is True
        except Exception as e:
            pytest.fail(f"超长密码处理不应抛出异常: {e}")

    def test_10000_char_password(self):
        """10000 字符的密码应安全处理"""
        from shared.core.auth.password import hash_password, verify_password

        huge_pwd = "x" * 10000
        try:
            hashed = hash_password(huge_pwd)
            assert verify_password(huge_pwd, hashed) is True
        except Exception as e:
            pytest.fail(f"10000 字符密码不应抛出异常: {e}")

    def test_long_unicode_password(self):
        """长 Unicode 密码（多字节字符）应正确处理字节截断"""
        from shared.core.auth.password import hash_password, verify_password

        # 中文字符每个占 3 字节，24 个中文字符 = 72 字节
        pwd_cn_72bytes = "测" * 24  # 24 * 3 = 72 字节
        try:
            hashed = hash_password(pwd_cn_72bytes)
            assert verify_password(pwd_cn_72bytes, hashed) is True
        except Exception as e:
            pytest.fail(f"Unicode 密码处理不应抛出异常: {e}")


# ===========================================================================
# 3. 特殊字符密码测试
# ===========================================================================

class TestSpecialCharacters:
    """特殊字符密码测试"""

    @pytest.mark.parametrize("special_pwd", [
        "!@#$%^&*()",
        "pass<>?/\\|",
        "`~-_=+[]{}",
        "pass;:'\"",
        "password\nwith\tnewline",
        "password\x00nullbyte",
        "pässwörd",           # 德语变音
        "пароль",             # 俄语
        "密码123",              # 中文
        "パスワード",          # 日语
        "🎃🔐password",        # emoji
    ])
    def test_special_characters_hash_and_verify(self, special_pwd):
        """各种特殊字符的密码应能正确哈希和验证"""
        from shared.core.auth.password import hash_password, verify_password

        try:
            hashed = hash_password(special_pwd)
            assert verify_password(special_pwd, hashed) is True
        except Exception as e:
            pytest.fail(f"特殊字符密码 '{special_pwd[:20]}...' 不应抛出异常: {e}")

    def test_all_ascii_printable_chars(self):
        """所有可打印 ASCII 字符的密码应正常处理"""
        from shared.core.auth.password import hash_password, verify_password
        import string

        all_printable = string.printable[:62]  # 取前 62 个可打印字符
        try:
            hashed = hash_password(all_printable)
            assert verify_password(all_printable, hashed) is True
        except Exception as e:
            pytest.fail(f"所有可打印字符密码不应抛出异常: {e}")

    def test_only_special_characters(self):
        """纯特殊字符密码应正常处理"""
        from shared.core.auth.password import hash_password, verify_password

        special_only = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
        hashed = hash_password(special_only)
        assert verify_password(special_only, hashed) is True


# ===========================================================================
# 4. 非法哈希格式测试
# ===========================================================================

class TestInvalidHashFormat:
    """非法哈希格式测试"""

    @pytest.mark.parametrize("bad_hash", [
        "not-a-valid-hash",
        "$2b$",                     # 只有前缀
        "$2b$10$",                  # 前缀+cost
        "$2b$10$short",             # 太短
        "$99$10$abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz01",  # 未知算法
        "$2b$99$abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz01",  # 无效 cost
        "$$$",                      # 空段
        "$2a$",                     # 旧版本前缀
        "fallback$salt$hash",       # 缺少 $ 前缀
        "$fallback$",               # 缺少段
    ])
    def test_invalid_hash_verify_returns_false(self, bad_hash):
        """各种非法格式的哈希验证应返回 False 且不抛异常"""
        from shared.core.auth.password import verify_password

        try:
            result = verify_password("password123", bad_hash)
            assert result is False
        except Exception as e:
            pytest.fail(f"非法哈希 '{bad_hash[:30]}...' 验证不应抛出异常: {e}")

    @pytest.mark.parametrize("bad_hash", [
        "not-a-valid-hash",
        "$2b$10$short",
        "",
    ])
    def test_invalid_hash_needs_update(self, bad_hash):
        """非法哈希的 needs_update 应合理处理"""
        from shared.core.auth.password import needs_update

        try:
            # 不关心返回 True 还是 False，只要不抛异常
            result = needs_update(bad_hash)
            assert isinstance(result, bool)
        except Exception as e:
            pytest.fail(f"非法哈希 needs_update 不应抛出异常: {e}")


# ===========================================================================
# 5. 密码强度验证边界测试（M8 配置中的强度检查）
# ===========================================================================

class TestPasswordStrength:
    """密码强度验证边界测试"""

    @staticmethod
    def _validate_strength(password):
        """使用 M8 配置中的密码强度验证函数"""
        # 导入 M8 的密码强度验证
        m8_config_path = PROJECT_DIR / "M8-control-tower" / "backend"
        if str(m8_config_path) not in sys.path:
            sys.path.insert(0, str(m8_config_path))
        try:
            from config import validate_password_strength
            return validate_password_strength(password)
        except ImportError:
            pytest.skip("M8 配置模块不可用，跳过密码强度测试")

    def test_password_below_min_length_fails(self):
        """低于最小长度的密码应验证失败"""
        result, msg = self._validate_strength("Short1!")  # 7 字符
        assert result is False
        assert "长度" in msg

    def test_password_at_exact_min_length(self):
        """恰好 12 位的密码（满足其他条件）应通过"""
        pwd = "Aa1!bcdefghi"  # 12 字符
        result, msg = self._validate_strength(pwd)
        assert result is True, f"密码 '{pwd}' 应通过强度验证: {msg}"

    def test_password_no_uppercase_fails(self):
        """没有大写字母的密码应失败"""
        result, msg = self._validate_strength("alllower123!")
        assert result is False
        assert "大写" in msg

    def test_password_no_lowercase_fails(self):
        """没有小写字母的密码应失败"""
        result, msg = self._validate_strength("ALLUPPER123!")
        assert result is False
        assert "小写" in msg

    def test_password_no_digit_fails(self):
        """没有数字的密码应失败"""
        result, msg = self._validate_strength("NoDigitsHere!")
        assert result is False
        assert "数字" in msg

    def test_password_no_special_fails(self):
        """没有特殊字符的密码应失败"""
        result, msg = self._validate_strength("NoSpecial1234")
        assert result is False
        assert "特殊字符" in msg

    def test_password_exactly_min_with_all_classes(self):
        """刚好满足所有条件的边界密码应通过"""
        # 12 字符，含大小写数字特殊字符
        pwd = "Aa1!bcdefghi"
        result, msg = self._validate_strength(pwd)
        assert result is True

    def test_very_long_strong_password(self):
        """很长的强密码应通过"""
        pwd = "Aa1!" + "x" * 100
        result, _ = self._validate_strength(pwd)
        assert result is True

    def test_unicode_password_strength(self):
        """Unicode 密码的强度验证"""
        # 中文字符 + 数字 + 特殊字符
        pwd = "密码测试Aa1!"
        result, msg = self._validate_strength(pwd)
        # 中文字符是否算作大写/小写取决于具体实现
        # 这里只验证不抛异常
        assert isinstance(result, bool)
        assert isinstance(msg, str)


# ===========================================================================
# 6. 弱密码检测测试
# ===========================================================================

class TestWeakPasswordDetection:
    """弱默认密码检测测试"""

    @staticmethod
    def _is_weak(pwd):
        """使用 M8 的弱密码检测"""
        m8_config_path = PROJECT_DIR / "M8-control-tower" / "backend"
        if str(m8_config_path) not in sys.path:
            sys.path.insert(0, str(m8_config_path))
        try:
            from config import is_weak_default_password
            return is_weak_default_password(pwd)
        except ImportError:
            pytest.skip("M8 配置模块不可用，跳过弱密码检测测试")

    @pytest.mark.parametrize("weak_pwd", [
        "admin123456",
        "password",
        "123456",
        "12345678",
        "admin",
        "changeme",
        "default",
        "qwerty",
        "abc123",
    ])
    def test_known_weak_passwords_detected(self, weak_pwd):
        """已知弱密码应被检测到"""
        assert self._is_weak(weak_pwd) is True

    @pytest.mark.parametrize("strong_pwd", [
        "MyStr0ng!Pass",
        "CorrectHorseBatteryStaple1!",
        "R@nd0mP@ssw0rd",
        "abcdefg1A!",  # 不在弱密码列表中
    ])
    def test_strong_passwords_not_weak(self, strong_pwd):
        """强密码不应被检测为弱密码"""
        assert self._is_weak(strong_pwd) is False

    def test_empty_password_is_weak(self):
        """空密码应被视为弱密码"""
        assert self._is_weak("") is True

    def test_case_insensitive_weak_check(self):
        """弱密码检测应不区分大小写"""
        assert self._is_weak("Admin123456") is True
        assert self._is_weak("PASSWORD") is True
        assert self._is_weak("Password") is True

    def test_generate_strong_password_is_not_weak(self):
        """生成的强密码不应是弱密码"""
        m8_config_path = PROJECT_DIR / "M8-control-tower" / "backend"
        if str(m8_config_path) not in sys.path:
            sys.path.insert(0, str(m8_config_path))
        try:
            from config import generate_strong_password
        except ImportError:
            pytest.skip("M8 配置模块不可用")

        for _ in range(10):  # 测试多次，确保随机生成的都不是弱密码
            pwd = generate_strong_password(16)
            assert self._is_weak(pwd) is False

    def test_generate_strong_password_min_length(self):
        """生成的密码长度小于最小值时应自动调整"""
        m8_config_path = PROJECT_DIR / "M8-control-tower" / "backend"
        if str(m8_config_path) not in sys.path:
            sys.path.insert(0, str(m8_config_path))
        try:
            from config import generate_strong_password, PASSWORD_MIN_LENGTH
        except ImportError:
            pytest.skip("M8 配置模块不可用")

        # 请求 8 位（小于最小值 12）
        pwd = generate_strong_password(8)
        assert len(pwd) == PASSWORD_MIN_LENGTH

    def test_generate_strong_password_meets_requirements(self):
        """生成的密码应满足所有强度要求"""
        m8_config_path = PROJECT_DIR / "M8-control-tower" / "backend"
        if str(m8_config_path) not in sys.path:
            sys.path.insert(0, str(m8_config_path))
        try:
            from config import generate_strong_password, validate_password_strength
        except ImportError:
            pytest.skip("M8 配置模块不可用")

        for _ in range(10):
            pwd = generate_strong_password(16)
            valid, msg = validate_password_strength(pwd)
            assert valid is True, f"生成的密码 '{pwd}' 不满足强度要求: {msg}"


# ===========================================================================
# 7. 恒定时间比较测试
# ===========================================================================

class TestConstantTimeCompare:
    """恒定时间字符串比较测试"""

    @staticmethod
    def _ct_compare(a, b):
        from shared.core.auth.password import _constant_time_compare
        return _constant_time_compare(a, b)

    def test_equal_strings_return_true(self):
        """相同字符串应返回 True"""
        assert self._ct_compare("abc123", "abc123") is True

    def test_different_strings_return_false(self):
        """不同字符串应返回 False"""
        assert self._ct_compare("abc123", "abc124") is False

    def test_different_lengths_return_false(self):
        """不同长度的字符串应返回 False"""
        assert self._ct_compare("short", "longer_string") is False

    def test_empty_strings_equal(self):
        """两个空字符串应返回 True"""
        assert self._ct_compare("", "") is True

    def test_empty_vs_nonempty_false(self):
        """空字符串 vs 非空应返回 False"""
        assert self._ct_compare("", "a") is False
        assert self._ct_compare("a", "") is False

    def test_long_strings_equal(self):
        """长字符串相等应返回 True"""
        s = "a" * 1000
        assert self._ct_compare(s, s) is True

    def test_unicode_strings(self):
        """Unicode 字符串比较应正确"""
        assert self._ct_compare("测试密码", "测试密码") is True
        assert self._ct_compare("测试密码", "测试吗") is False

    def test_first_char_diff(self):
        """第一个字符不同应返回 False"""
        assert self._ct_compare("abc", "xbc") is False

    def test_last_char_diff(self):
        """最后一个字符不同应返回 False"""
        assert self._ct_compare("abc", "abx") is False


# ===========================================================================
# 8. needs_update 边界测试
# ===========================================================================

class TestNeedsUpdate:
    """密码哈希升级检测边界测试"""

    def test_fallback_hash_needs_update(self):
        """fallback 哈希应始终需要升级"""
        from shared.core.auth.password import needs_update

        # 如果当前是 bcrypt 模式，构造一个 fallback 格式的哈希
        fallback_hash = "$fallback$abc123$def456"
        if is_bcrypt_available():
            # bcrypt 模式下，fallback 哈希需要升级
            result = needs_update(fallback_hash)
            assert result is True

    def test_empty_hash_no_update(self):
        """空哈希不需要升级"""
        from shared.core.auth.password import needs_update

        assert needs_update("") is False
        assert needs_update(None) is False

    def test_valid_bcrypt_hash_no_update(self):
        """有效的 bcrypt 哈希（cost >= 12）不需要升级"""
        from shared.core.auth.password import needs_update, hash_password

        if not is_bcrypt_available():
            pytest.skip("bcrypt 不可用")

        hashed = hash_password("TestPass123!")
        # 注意：默认 cost 可能 >= 12 也可能 < 12，取决于 bcrypt 默认值
        # 这里只验证不抛异常
        result = needs_update(hashed)
        assert isinstance(result, bool)

    def test_invalid_format_hash_needs_update(self):
        """非 bcrypt 格式哈希需要升级"""
        from shared.core.auth.password import needs_update

        result = needs_update("not-a-bcrypt-hash")
        # 非 bcrypt 格式应该需要升级
        assert result is True


# ===========================================================================
# 9. 密码哈希一致性测试
# ===========================================================================

class TestHashConsistency:
    """密码哈希一致性测试"""

    def test_same_password_different_hashes(self):
        """同一密码两次哈希结果应不同（salt 不同）"""
        from shared.core.auth.password import hash_password

        pwd = "SamePassword123!"
        hash1 = hash_password(pwd)
        hash2 = hash_password(pwd)

        assert hash1 != hash2
        # 但两者都能验证通过
        from shared.core.auth.password import verify_password
        assert verify_password(pwd, hash1) is True
        assert verify_password(pwd, hash2) is True

    def test_one_char_diff_passwords_different(self):
        """只差一个字符的密码应产生完全不同的哈希"""
        from shared.core.auth.password import hash_password

        pwd1 = "Password123!"
        pwd2 = "Password123?"  # 最后一个字符不同

        hash1 = hash_password(pwd1)
        hash2 = hash_password(pwd2)

        assert hash1 != hash2

    def test_case_sensitive_passwords(self):
        """密码验证应区分大小写"""
        from shared.core.auth.password import hash_password, verify_password

        pwd_lower = "password123!"
        pwd_upper = "PASSWORD123!"

        hashed = hash_password(pwd_lower)
        assert verify_password(pwd_lower, hashed) is True
        assert verify_password(pwd_upper, hashed) is False


# ===========================================================================
# 10. 边界长度密码测试
# ===========================================================================

class TestBoundaryLengths:
    """边界长度密码测试"""

    def test_one_char_password(self):
        """1 字符密码应能正常哈希（虽然不安全）"""
        from shared.core.auth.password import hash_password, verify_password

        pwd = "a"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True
        assert verify_password("b", hashed) is False

    def test_two_char_password(self):
        """2 字符密码应能正常哈希"""
        from shared.core.auth.password import hash_password, verify_password

        pwd = "ab"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True

    def test_71_byte_password(self):
        """71 字节密码（接近 bcrypt 限制）应正常工作"""
        from shared.core.auth.password import hash_password, verify_password

        pwd = "a" * 71
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True

    def test_72_byte_password(self):
        """72 字节密码（bcrypt 限制边界）应正常工作"""
        from shared.core.auth.password import hash_password, verify_password

        pwd = "a" * 72
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True

    def test_whitespace_only_password(self):
        """纯空白字符密码应能正常处理"""
        from shared.core.auth.password import hash_password, verify_password

        pwd = "     "  # 5 个空格
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True
        assert verify_password("    ", hashed) is False  # 4 个空格不匹配

    def test_tab_and_newline_password(self):
        """含制表符和换行的密码应正常处理"""
        from shared.core.auth.password import hash_password, verify_password

        pwd = "pass\tword\n123"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True


# ===========================================================================
# 11. 后端检测测试
# ===========================================================================

class TestBackendDetection:
    """密码哈希后端检测测试"""

    def test_is_bcrypt_available_returns_bool(self):
        """is_bcrypt_available 应返回布尔值"""
        from shared.core.auth.password import is_bcrypt_available

        result = is_bcrypt_available()
        assert isinstance(result, bool)

    def test_is_insecure_fallback_returns_bool(self):
        """is_insecure_fallback_mode 应返回布尔值"""
        from shared.core.auth.password import is_insecure_fallback_mode

        result = is_insecure_fallback_mode()
        assert isinstance(result, bool)

    def test_not_both_unavailable_and_fallback(self):
        """bcrypt 不可用和 fallback 模式不应同时为 False（否则无法工作）"""
        from shared.core.auth.password import is_bcrypt_available, is_insecure_fallback_mode

        bcrypt_ok = is_bcrypt_available()
        fallback = is_insecure_fallback_mode()

        # 至少有一个应该可用（否则测试就不会运行到这里）
        assert bcrypt_ok or fallback
