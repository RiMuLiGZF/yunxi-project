"""
M12 安全盾 - 敏感数据脱敏单元测试
覆盖：API Key 脱敏、密码脱敏、JWT Token 脱敏、IP 地址脱敏、
邮箱脱敏、手机号脱敏、批量脱敏、审计数据脱敏
"""

import sys
import os
import unittest

# 将项目根目录加入路径
from backend.services.masking import (
    mask_api_key,
    mask_password,
    mask_jwt_token,
    mask_ip_address,
    mask_email,
    mask_phone,
    mask_sensitive_data,
    mask_audit_data,
    mask_dict_with_rules,
    AUDIT_SENSITIVE_FIELDS,
)


class TestMaskApiKey(unittest.TestCase):
    """API Key 脱敏测试"""

    def test_mask_api_key_normal(self):
        """测试：正常长度的 API Key 脱敏（前4位 + **** + 后4位）"""
        key = "m12-abcdefghijklmnopqrstuvwxyz"
        masked = mask_api_key(key)
        self.assertEqual(masked[:4], key[:4])
        self.assertEqual(masked[-4:], key[-4:])
        self.assertIn("****", masked)
        # 验证中间部分被隐藏
        self.assertNotIn("efgh", masked)

    def test_mask_api_key_short_key(self):
        """测试：短 Key（<=8字符）全部隐藏"""
        short_key = "abc12345"  # 8 个字符
        masked = mask_api_key(short_key)
        self.assertEqual(len(masked), len(short_key))
        self.assertEqual(masked, "*" * len(short_key))

    def test_mask_api_key_very_short(self):
        """测试：非常短的 Key 全部隐藏"""
        masked = mask_api_key("abc")
        self.assertEqual(masked, "***")

    def test_mask_api_key_empty(self):
        """测试：空字符串返回空"""
        self.assertEqual(mask_api_key(""), "")

    def test_mask_api_key_none(self):
        """测试：None 返回空字符串"""
        self.assertEqual(mask_api_key(None), "")

    def test_mask_api_key_m12_prefix(self):
        """测试：标准 m12- 前缀的 Key 脱敏"""
        key = "m12-abcdefghijklmnop1234"
        masked = mask_api_key(key)
        self.assertTrue(masked.startswith("m12-"))
        self.assertTrue(masked.endswith("1234"))
        self.assertIn("****", masked)


class TestMaskPassword(unittest.TestCase):
    """密码脱敏测试"""

    def test_mask_password_returns_six_stars(self):
        """测试：密码脱敏返回固定 6 个星号"""
        self.assertEqual(mask_password("my_password"), "******")

    def test_mask_password_long_password(self):
        """测试：长密码也只显示 6 个星号"""
        long_pass = "a" * 100
        masked = mask_password(long_pass)
        self.assertEqual(masked, "******")
        self.assertEqual(len(masked), 6)

    def test_mask_password_empty(self):
        """测试：空密码返回空？不，返回 6 个星号"""
        self.assertEqual(mask_password(""), "******")

    def test_mask_password_none(self):
        """测试：None 返回空字符串"""
        self.assertEqual(mask_password(None), "")

    def test_mask_password_special_chars(self):
        """测试：含特殊字符的密码也只显示 6 个星号"""
        self.assertEqual(mask_password("P@ssw0rd!23"), "******")


class TestMaskJwtToken(unittest.TestCase):
    """JWT Token 脱敏测试"""

    def test_mask_jwt_token_normal(self):
        """测试：正常 JWT Token 脱敏（前10位 + ****）"""
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        masked = mask_jwt_token(token)
        self.assertEqual(masked[:10], token[:10])
        self.assertTrue(masked.endswith("****"))
        self.assertIn("****", masked)

    def test_mask_jwt_token_short(self):
        """测试：短 Token（<=10字符）全部隐藏"""
        short = "abcdefghij"  # 10 个字符
        masked = mask_jwt_token(short)
        self.assertEqual(masked, "**********")

    def test_mask_jwt_token_empty(self):
        """测试：空 Token 返回空"""
        self.assertEqual(mask_jwt_token(""), "")

    def test_mask_jwt_token_none(self):
        """测试：None 返回空字符串"""
        self.assertEqual(mask_jwt_token(None), "")

    def test_mask_jwt_token_preserves_prefix(self):
        """测试：脱敏后保留前 10 位用于识别"""
        token = "eyJhbGciOiJ" + "x" * 100
        masked = mask_jwt_token(token)
        self.assertTrue(masked.startswith("eyJhbGciOi"))
        self.assertTrue(masked.endswith("****"))


class TestMaskIpAddress(unittest.TestCase):
    """IP 地址脱敏测试"""

    def test_mask_ipv4_normal(self):
        """测试：IPv4 地址脱敏（最后一段替换为 ***）"""
        masked = mask_ip_address("192.168.1.100")
        self.assertEqual(masked, "192.168.1.***")

    def test_mask_ipv4_another(self):
        """测试：另一个 IPv4 地址"""
        masked = mask_ip_address("10.0.0.1")
        self.assertEqual(masked, "10.0.0.***")

    def test_mask_ipv4_cidr(self):
        """测试：CIDR 格式的 IPv4 地址脱敏"""
        masked = mask_ip_address("192.168.1.0/24")
        self.assertEqual(masked, "192.168.1.***/24")

    def test_mask_ipv6_basic(self):
        """测试：IPv6 地址脱敏（最后一段替换为 ***）"""
        masked = mask_ip_address("2001:db8::1")
        # IPv6 简单处理：最后一段替换
        self.assertTrue(masked.endswith("***"))
        self.assertIn(":", masked)

    def test_mask_ip_empty(self):
        """测试：空 IP 返回空"""
        self.assertEqual(mask_ip_address(""), "")

    def test_mask_ip_none(self):
        """测试：None 返回空字符串"""
        self.assertEqual(mask_ip_address(None), "")

    def test_mask_ip_invalid_format(self):
        """测试：非 IP 格式字符串原样返回"""
        masked = mask_ip_address("not-an-ip")
        self.assertEqual(masked, "not-an-ip")

    def test_mask_ip_127_0_0_1(self):
        """测试：本地回环地址脱敏"""
        masked = mask_ip_address("127.0.0.1")
        self.assertEqual(masked, "127.0.0.***")


class TestMaskEmail(unittest.TestCase):
    """邮箱脱敏测试"""

    def test_mask_email_normal(self):
        """测试：正常邮箱脱敏（用户名首尾保留，中间 ***）"""
        masked = mask_email("user@example.com")
        self.assertTrue(masked.endswith("@example.com"))
        self.assertTrue(masked.startswith("u"))
        self.assertIn("***", masked)
        self.assertIn("r@", masked)

    def test_mask_email_short_username(self):
        """测试：短用户名（<=2字符）全部隐藏"""
        masked = mask_email("ab@example.com")
        self.assertTrue(masked.endswith("@example.com"))
        self.assertEqual(masked.split("@")[0], "**")

    def test_mask_email_single_char(self):
        """测试：单字符用户名"""
        masked = mask_email("a@b.com")
        self.assertEqual(masked.split("@")[0], "*")

    def test_mask_email_empty(self):
        """测试：空字符串返回空"""
        self.assertEqual(mask_email(""), "")

    def test_mask_email_no_at(self):
        """测试：不含 @ 的字符串原样返回"""
        self.assertEqual(mask_email("not-an-email"), "not-an-email")


class TestMaskPhone(unittest.TestCase):
    """手机号脱敏测试"""

    def test_mask_phone_11_digits(self):
        """测试：11 位手机号脱敏（前3 + **** + 后4）"""
        masked = mask_phone("13812345678")
        self.assertEqual(masked, "138****5678")

    def test_mask_phone_with_hyphens(self):
        """测试：带分隔符的手机号"""
        masked = mask_phone("138-1234-5678")
        # 会提取数字部分进行脱敏
        self.assertIn("****", masked)

    def test_mask_phone_short(self):
        """测试：太短的号码全部隐藏"""
        masked = mask_phone("123456")
        self.assertEqual(masked, "******")

    def test_mask_phone_empty(self):
        """测试：空字符串返回空"""
        self.assertEqual(mask_phone(""), "")

    def test_mask_phone_none(self):
        """测试：None 返回空"""
        self.assertEqual(mask_phone(None), "")


class TestMaskSensitiveData(unittest.TestCase):
    """批量脱敏函数测试"""

    def test_mask_sensitive_data_basic(self):
        """测试：基础字典数据脱敏"""
        data = {
            "username": "admin",
            "password": "secret123",
            "api_key": "m12-abcdefghijklmnop",
        }
        fields = {
            "password": "password",
            "api_key": "api_key",
        }
        result = mask_sensitive_data(data, fields)
        # 非敏感字段保持不变
        self.assertEqual(result["username"], "admin")
        # 密码被脱敏
        self.assertEqual(result["password"], "******")
        # API Key 被脱敏
        self.assertIn("****", result["api_key"])
        self.assertTrue(result["api_key"].startswith("m12-"))

    def test_mask_sensitive_data_original_unchanged(self):
        """测试：不修改原始数据（纯函数）"""
        data = {"password": "secret"}
        original = data.copy()
        mask_sensitive_data(data, {"password": "password"})
        # 原始数据不变
        self.assertEqual(data["password"], "secret")
        self.assertEqual(data, original)

    def test_mask_sensitive_data_empty_fields(self):
        """测试：空 fields 参数返回原始数据"""
        data = {"password": "secret"}
        result = mask_sensitive_data(data, {})
        self.assertEqual(result["password"], "secret")

    def test_mask_sensitive_data_none_fields(self):
        """测试：None fields 返回原始数据"""
        data = {"key": "value"}
        result = mask_sensitive_data(data, None)
        self.assertEqual(result, data)

    def test_mask_sensitive_data_nested_dict(self):
        """测试：嵌套字典中的敏感字段也被脱敏"""
        data = {
            "user": {
                "name": "alice",
                "password": "secret",
                "email": "alice@example.com",
            },
            "password": "top_secret",
        }
        fields = {
            "password": "password",
            "email": "email",
        }
        result = mask_sensitive_data(data, fields)
        # 顶层密码
        self.assertEqual(result["password"], "******")
        # 嵌套字典中的密码
        self.assertEqual(result["user"]["password"], "******")
        # 嵌套字典中的邮箱
        self.assertIn("***", result["user"]["email"])

    def test_mask_sensitive_data_list(self):
        """测试：列表数据中的每个元素都被脱敏"""
        data = [
            {"username": "user1", "password": "pass1"},
            {"username": "user2", "password": "pass2"},
        ]
        fields = {"password": "password"}
        result = mask_sensitive_data(data, fields)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["password"], "******")
        self.assertEqual(result[1]["password"], "******")

    def test_mask_sensitive_data_unknown_mask_type(self):
        """测试：未知脱敏类型不处理"""
        data = {"secret": "value"}
        fields = {"secret": "unknown_type"}
        result = mask_sensitive_data(data, fields)
        # 未知类型不处理
        self.assertEqual(result["secret"], "value")

    def test_mask_sensitive_data_ip(self):
        """测试：IP 地址类型脱敏"""
        data = {"client_ip": "192.168.1.100"}
        fields = {"client_ip": "ip"}
        result = mask_sensitive_data(data, fields)
        self.assertEqual(result["client_ip"], "192.168.1.***")


class TestMaskAuditData(unittest.TestCase):
    """审计数据脱敏测试"""

    def test_mask_audit_data_password(self):
        """测试：审计数据中的密码字段被脱敏"""
        data = {"action": "login", "password": "secret123"}
        result = mask_audit_data(data)
        self.assertEqual(result["password"], "******")

    def test_mask_audit_data_api_key(self):
        """测试：审计数据中的 API Key 被脱敏"""
        data = {"action": "create_key", "api_key": "m12-abcdefghijklmnop"}
        result = mask_audit_data(data)
        self.assertIn("****", result["api_key"])

    def test_mask_audit_data_source_ip(self):
        """测试：审计数据中的 source_ip 被脱敏"""
        data = {"action": "login", "source_ip": "192.168.1.100"}
        result = mask_audit_data(data)
        self.assertEqual(result["source_ip"], "192.168.1.***")

    def test_mask_audit_data_access_token(self):
        """测试：审计数据中的 access_token 被脱敏"""
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        data = {"action": "login", "access_token": token}
        result = mask_audit_data(data)
        self.assertTrue(result["access_token"].startswith("eyJhbGciOi"))
        self.assertTrue(result["access_token"].endswith("****"))

    def test_mask_audit_data_non_sensitive_unchanged(self):
        """测试：非敏感字段保持不变"""
        data = {
            "action": "create_rule",
            "module": "waf",
            "user_id": "user_001",
            "status": "success",
        }
        result = mask_audit_data(data)
        self.assertEqual(result["action"], "create_rule")
        self.assertEqual(result["module"], "waf")
        self.assertEqual(result["user_id"], "user_001")
        self.assertEqual(result["status"], "success")

    def test_mask_audit_data_full_audit_log(self):
        """测试：完整审计日志数据脱敏"""
        log = {
            "id": 1,
            "user_id": "user_001",
            "username": "admin",
            "action": "login",
            "source_ip": "10.0.0.50",
            "password": "admin123",
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "status": "success",
            "extra_data": {
                "api_key": "m12-testkey1234567890",
                "password": "nested_pass",
            },
        }
        result = mask_audit_data(log)
        # 非敏感字段
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["username"], "admin")
        self.assertEqual(result["action"], "login")
        self.assertEqual(result["status"], "success")
        # 敏感字段
        self.assertEqual(result["password"], "******")
        self.assertEqual(result["source_ip"], "10.0.0.***")
        self.assertTrue(result["access_token"].endswith("****"))
        # 嵌套敏感字段
        self.assertEqual(result["extra_data"]["password"], "******")
        self.assertIn("****", result["extra_data"]["api_key"])

    def test_mask_audit_data_original_unchanged(self):
        """测试：审计数据脱敏不修改原始数据"""
        data = {"password": "secret", "source_ip": "1.2.3.4"}
        original = data.copy()
        mask_audit_data(data)
        self.assertEqual(data, original)


class TestMaskDictWithRules(unittest.TestCase):
    """mask_dict_with_rules 别名函数测试"""

    def test_mask_dict_with_rules_basic(self):
        """测试：mask_dict_with_rules 功能与 mask_sensitive_data 一致"""
        data = {"password": "secret"}
        rules = {"password": "password"}
        result = mask_dict_with_rules(data, rules)
        self.assertEqual(result["password"], "******")


class TestAuditSensitiveFields(unittest.TestCase):
    """AUDIT_SENSITIVE_FIELDS 配置测试"""

    def test_audit_sensitive_fields_contains_password(self):
        """测试：包含密码相关字段"""
        self.assertIn("password", AUDIT_SENSITIVE_FIELDS)
        self.assertEqual(AUDIT_SENSITIVE_FIELDS["password"], "password")

    def test_audit_sensitive_fields_contains_token(self):
        """测试：包含 Token 相关字段"""
        self.assertIn("access_token", AUDIT_SENSITIVE_FIELDS)
        self.assertIn("refresh_token", AUDIT_SENSITIVE_FIELDS)
        self.assertEqual(AUDIT_SENSITIVE_FIELDS["access_token"], "jwt_token")

    def test_audit_sensitive_fields_contains_api_key(self):
        """测试：包含 API Key 相关字段"""
        self.assertIn("api_key", AUDIT_SENSITIVE_FIELDS)
        self.assertEqual(AUDIT_SENSITIVE_FIELDS["api_key"], "api_key")

    def test_audit_sensitive_fields_contains_ip(self):
        """测试：包含 IP 相关字段"""
        self.assertIn("source_ip", AUDIT_SENSITIVE_FIELDS)
        self.assertEqual(AUDIT_SENSITIVE_FIELDS["source_ip"], "ip")


if __name__ == "__main__":
    unittest.main(verbosity=2)
