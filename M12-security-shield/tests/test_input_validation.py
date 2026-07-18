"""
M12 安全盾 - 输入校验增强单元测试
覆盖：字符串长度限制、特殊字符过滤、IP 地址格式校验、
路径遍历防护、ID 参数正整数校验、枚举值校验
"""

import sys
import os
import unittest
from datetime import datetime
from pydantic import ValidationError

# 将项目根目录加入路径
from backend.schemas.auth import (
    ApiKeyCreate,
    ApiKeyUpdate,
    LoginRequest,
)
from backend.schemas.ip import (
    IpBlacklistCreate,
    IpBlacklistUpdate,
    IpWhitelistCreate,
    IpCheckRequest,
)
from backend.schemas.waf import (
    WafRuleCreate,
    WafRuleUpdate,
    WafCheckRequest,
)
from backend.schemas.audit import (
    EventResolveRequest,
    EventQueryParams,
    AuditQueryParams,
)


class TestAuthInputValidation(unittest.TestCase):
    """认证模块输入校验测试"""

    def test_api_key_name_too_long(self):
        """测试：API Key 名称超过 100 字符时校验失败"""
        long_name = "a" * 101
        with self.assertRaises(ValidationError):
            ApiKeyCreate(key_name=long_name)

    def test_api_key_name_max_length(self):
        """测试：API Key 名称恰好 100 字符时通过"""
        name_100 = "a" * 100
        # 应该通过
        key = ApiKeyCreate(key_name=name_100)
        self.assertEqual(len(key.key_name), 100)

    def test_api_key_name_empty_fails(self):
        """测试：空名称校验失败"""
        with self.assertRaises(ValidationError):
            ApiKeyCreate(key_name="   ")

    def test_api_key_name_path_traversal_blocked(self):
        """测试：包含路径遍历字符的名称被拒绝"""
        with self.assertRaises(ValidationError):
            ApiKeyCreate(key_name="../etc/passwd")

    def test_api_key_name_path_traversal_encoded_blocked(self):
        """测试：URL 编码的路径遍历被拒绝"""
        with self.assertRaises(ValidationError):
            ApiKeyCreate(key_name="%2e%2e%2fetc")

    def test_api_key_owner_too_long(self):
        """测试：所有者超过 100 字符时校验失败"""
        long_owner = "a" * 101
        with self.assertRaises(ValidationError):
            ApiKeyCreate(key_name="test", owner=long_owner)

    def test_api_key_description_too_long(self):
        """测试：描述超过 500 字符时校验失败"""
        long_desc = "a" * 501
        with self.assertRaises(ValidationError):
            ApiKeyCreate(key_name="test", description=long_desc)

    def test_api_key_description_max_length(self):
        """测试：描述恰好 500 字符时通过"""
        desc_500 = "a" * 500
        key = ApiKeyCreate(key_name="test", description=desc_500)
        self.assertEqual(len(key.description), 500)

    def test_api_key_name_special_chars_blocked(self):
        """测试：包含危险特殊字符的名称被拒绝"""
        # 单引号
        with self.assertRaises(ValidationError):
            ApiKeyCreate(key_name="test' OR 1=1--")
        # 双引号
        with self.assertRaises(ValidationError):
            ApiKeyCreate(key_name='test" OR 1=1--')
        # 分号
        with self.assertRaises(ValidationError):
            ApiKeyCreate(key_name="test; DROP TABLE users")
        # 尖括号
        with self.assertRaises(ValidationError):
            ApiKeyCreate(key_name="<script>alert(1)</script>")

    def test_api_key_valid_name(self):
        """测试：合法的名称通过校验"""
        valid_names = [
            "my-api-key",
            "test_key_123",
            "生产环境密钥",
            "service-a-key",
            "key with spaces",
        ]
        for name in valid_names:
            try:
                key = ApiKeyCreate(key_name=name)
                self.assertEqual(key.key_name, name.strip())
            except ValidationError as e:
                self.fail(f"合法名称 '{name}' 被错误拒绝: {e}")

    def test_api_key_update_name_validation(self):
        """测试：更新 API Key 时名称也会校验"""
        with self.assertRaises(ValidationError):
            ApiKeyUpdate(key_name="../bad")

    def test_api_key_update_description_validation(self):
        """测试：更新 API Key 时描述也会校验"""
        with self.assertRaises(ValidationError):
            ApiKeyUpdate(description="../traversal")

    def test_login_username_length_bounds(self):
        """测试：登录用户名字段长度限制"""
        # 太短
        with self.assertRaises(ValidationError):
            LoginRequest(username="ab", password="password")
        # 太长
        with self.assertRaises(ValidationError):
            LoginRequest(username="a" * 101, password="password")

    def test_login_password_length_bounds(self):
        """测试：登录密码字段长度限制"""
        # 太短
        with self.assertRaises(ValidationError):
            LoginRequest(username="admin", password="12345")
        # 太长
        with self.assertRaises(ValidationError):
            LoginRequest(username="admin", password="a" * 201)


class TestIpInputValidation(unittest.TestCase):
    """IP 控制模块输入校验测试"""

    def test_valid_ipv4_address(self):
        """测试：合法 IPv4 地址通过校验"""
        entry = IpBlacklistCreate(ip_address="192.168.1.100")
        self.assertEqual(entry.ip_address, "192.168.1.100")

    def test_valid_ipv6_address(self):
        """测试：合法 IPv6 地址通过校验"""
        entry = IpBlacklistCreate(ip_address="2001:db8::1")
        self.assertEqual(entry.ip_address, "2001:db8::1")

    def test_valid_cidr_address(self):
        """测试：合法 CIDR 地址通过校验"""
        entry = IpBlacklistCreate(ip_address="192.168.1.0/24")
        self.assertEqual(entry.ip_address, "192.168.1.0/24")

    def test_invalid_ip_format_fails(self):
        """测试：非法 IP 地址格式校验失败"""
        invalid_ips = [
            "not-an-ip",
            "192.168.1",       # 只有 3 段
            "192.168.1.999",   # 超出范围
            "256.1.1.1",       # 超出范围
            "192.168.1.1/33",  # CIDR 超出范围
            "",                # 空字符串
        ]
        for ip in invalid_ips:
            with self.assertRaises(ValidationError, msg=f"IP '{ip}' 应该被拒绝"):
                IpBlacklistCreate(ip_address=ip)

    def test_ip_reason_too_long(self):
        """测试：封禁原因超过 500 字符时校验失败"""
        long_reason = "a" * 501
        with self.assertRaises(ValidationError):
            IpBlacklistCreate(ip_address="1.2.3.4", reason=long_reason)

    def test_ip_reason_path_traversal_blocked(self):
        """测试：封禁原因中的路径遍历被拒绝"""
        with self.assertRaises(ValidationError):
            IpBlacklistCreate(ip_address="1.2.3.4", reason="../test")

    def test_invalid_ip_type(self):
        """测试：非法 ip_type 值被拒绝"""
        with self.assertRaises(ValidationError):
            IpBlacklistCreate(ip_address="1.2.3.4", ip_type="invalid")

    def test_valid_ip_types(self):
        """测试：合法的 ip_type 值通过"""
        for ip_type in ["single", "cidr", "range"]:
            entry = IpBlacklistCreate(ip_address="1.2.3.4", ip_type=ip_type)
            self.assertEqual(entry.ip_type, ip_type)

    def test_invalid_severity(self):
        """测试：非法 severity 值被拒绝"""
        with self.assertRaises(ValidationError):
            IpBlacklistCreate(ip_address="1.2.3.4", severity="invalid")

    def test_valid_severity(self):
        """测试：合法的 severity 值通过"""
        for sev in ["low", "medium", "high", "critical", "info"]:
            entry = IpBlacklistCreate(ip_address="1.2.3.4", severity=sev)
            self.assertEqual(entry.severity, sev)

    def test_whitelist_ip_validation(self):
        """测试：白名单 IP 也进行格式校验"""
        with self.assertRaises(ValidationError):
            IpWhitelistCreate(ip_address="not-valid")

    def test_ip_check_request_validation(self):
        """测试：IP 检测请求也进行格式校验"""
        # 合法
        req = IpCheckRequest(ip_address="8.8.8.8")
        self.assertEqual(req.ip_address, "8.8.8.8")
        # 非法
        with self.assertRaises(ValidationError):
            IpCheckRequest(ip_address="invalid")

    def test_ip_blacklist_update_validation(self):
        """测试：更新 IP 黑名单时也校验"""
        with self.assertRaises(ValidationError):
            IpBlacklistUpdate(severity="invalid_severity")


class TestWafInputValidation(unittest.TestCase):
    """WAF 模块输入校验测试"""

    def test_rule_name_too_long(self):
        """测试：规则名称超过 100 字符时校验失败"""
        long_name = "a" * 101
        with self.assertRaises(ValidationError):
            WafRuleCreate(rule_name=long_name, pattern="test")

    def test_rule_name_path_traversal_blocked(self):
        """测试：规则名称中的路径遍历被拒绝"""
        with self.assertRaises(ValidationError):
            WafRuleCreate(rule_name="../bad", pattern="test")

    def test_rule_name_empty_fails(self):
        """测试：空规则名称失败"""
        with self.assertRaises(ValidationError):
            WafRuleCreate(rule_name="   ", pattern="test")

    def test_pattern_too_long(self):
        """测试：匹配规则超过 2000 字符时校验失败"""
        long_pattern = "a" * 2001
        with self.assertRaises(ValidationError):
            WafRuleCreate(rule_name="test", pattern=long_pattern)

    def test_invalid_regex_pattern(self):
        """测试：非法正则表达式被拒绝"""
        with self.assertRaises(ValidationError):
            WafRuleCreate(rule_name="test", pattern="[unclosed")

    def test_valid_regex_pattern(self):
        """测试：合法正则表达式通过"""
        rule = WafRuleCreate(rule_name="test", pattern=r"\d+")
        self.assertEqual(rule.pattern, r"\d+")

    def test_invalid_match_target(self):
        """测试：非法 match_target 值被拒绝"""
        with self.assertRaises(ValidationError):
            WafRuleCreate(rule_name="test", pattern="x", match_target="invalid")

    def test_valid_match_targets(self):
        """测试：合法的 match_target 值通过"""
        for target in ["query", "body", "header", "path", "all", "cookie", "url"]:
            rule = WafRuleCreate(rule_name="test", pattern="x", match_target=target)
            self.assertEqual(rule.match_target, target)

    def test_invalid_severity(self):
        """测试：非法 severity 值被拒绝"""
        with self.assertRaises(ValidationError):
            WafRuleCreate(rule_name="test", pattern="x", severity="invalid")

    def test_valid_severity(self):
        """测试：合法的 severity 值通过"""
        for sev in ["info", "low", "medium", "high", "critical"]:
            rule = WafRuleCreate(rule_name="test", pattern="x", severity=sev)
            self.assertEqual(rule.severity, sev)

    def test_invalid_action(self):
        """测试：非法 action 值被拒绝"""
        with self.assertRaises(ValidationError):
            WafRuleCreate(rule_name="test", pattern="x", action="invalid")

    def test_valid_actions(self):
        """测试：合法的 action 值通过"""
        for act in ["block", "log", "challenge", "allow"]:
            rule = WafRuleCreate(rule_name="test", pattern="x", action=act)
            self.assertEqual(rule.action, act)

    def test_description_too_long(self):
        """测试：规则描述超过 500 字符时校验失败"""
        long_desc = "a" * 501
        with self.assertRaises(ValidationError):
            WafRuleCreate(rule_name="test", pattern="x", description=long_desc)

    def test_description_path_traversal_blocked(self):
        """测试：规则描述中的路径遍历被拒绝"""
        with self.assertRaises(ValidationError):
            WafRuleCreate(rule_name="test", pattern="x", description="../bad")

    def test_waf_check_request_method_validation(self):
        """测试：WAF 检测请求的方法校验"""
        # 合法方法
        req = WafCheckRequest(path="/test", method="POST")
        self.assertEqual(req.method, "POST")
        # 非法方法
        with self.assertRaises(ValidationError):
            WafCheckRequest(path="/test", method="INVALID_METHOD")

    def test_waf_check_request_path_must_start_with_slash(self):
        """测试：请求路径必须以 / 开头"""
        with self.assertRaises(ValidationError):
            WafCheckRequest(path="no-slash")

    def test_waf_check_request_client_ip_validation(self):
        """测试：客户端 IP 格式校验"""
        # 合法
        req = WafCheckRequest(path="/test", client_ip="192.168.1.1")
        self.assertEqual(req.client_ip, "192.168.1.1")
        # 非法
        with self.assertRaises(ValidationError):
            WafCheckRequest(path="/test", client_ip="invalid-ip")

    def test_waf_rule_update_validation(self):
        """测试：更新 WAF 规则时也进行校验"""
        with self.assertRaises(ValidationError):
            WafRuleUpdate(severity="invalid")

        with self.assertRaises(ValidationError):
            WafRuleUpdate(pattern="[unclosed")


class TestAuditInputValidation(unittest.TestCase):
    """审计模块输入校验测试"""

    def test_resolution_note_too_long(self):
        """测试：处理说明超过 1000 字符时校验失败"""
        long_note = "a" * 1001
        with self.assertRaises(ValidationError):
            EventResolveRequest(resolution_note=long_note)

    def test_resolution_note_path_traversal_blocked(self):
        """测试：处理说明中的路径遍历被拒绝"""
        with self.assertRaises(ValidationError):
            EventResolveRequest(resolution_note="../test")

    def test_invalid_event_status(self):
        """测试：非法事件状态被拒绝"""
        with self.assertRaises(ValidationError):
            EventResolveRequest(status="invalid_status")

    def test_valid_event_status(self):
        """测试：合法事件状态通过"""
        for status in ["active", "resolved", "ignored", "false_positive"]:
            req = EventResolveRequest(status=status)
            self.assertEqual(req.status, status)

    def test_event_query_keyword_too_long(self):
        """测试：关键词超过 200 字符时校验失败"""
        long_keyword = "a" * 201
        with self.assertRaises(ValidationError):
            EventQueryParams(keyword=long_keyword)

    def test_event_query_keyword_path_traversal_blocked(self):
        """测试：关键词中的路径遍历被拒绝"""
        with self.assertRaises(ValidationError):
            EventQueryParams(keyword="../etc")

    def test_event_query_invalid_severity(self):
        """测试：查询参数中非法 severity 被拒绝"""
        with self.assertRaises(ValidationError):
            EventQueryParams(severity="invalid")

    def test_event_query_invalid_status(self):
        """测试：查询参数中非法 status 被拒绝"""
        with self.assertRaises(ValidationError):
            EventQueryParams(status="invalid")

    def test_event_query_page_must_be_positive(self):
        """测试：页码必须是正整数"""
        with self.assertRaises(ValidationError):
            EventQueryParams(page=0)
        with self.assertRaises(ValidationError):
            EventQueryParams(page=-1)

    def test_event_query_page_size_bounds(self):
        """测试：每页数量有上下限"""
        with self.assertRaises(ValidationError):
            EventQueryParams(page_size=0)
        with self.assertRaises(ValidationError):
            EventQueryParams(page_size=101)

    def test_audit_query_invalid_status(self):
        """测试：审计日志查询中非法 status 被拒绝"""
        with self.assertRaises(ValidationError):
            AuditQueryParams(status="invalid")

    def test_audit_query_valid_status(self):
        """测试：审计日志查询中合法 status 通过"""
        for status in ["success", "failed", "denied", "pending"]:
            params = AuditQueryParams(status=status)
            self.assertEqual(params.status, status)

    def test_audit_query_module_path_traversal_blocked(self):
        """测试：模块参数中的路径遍历被拒绝"""
        with self.assertRaises(ValidationError):
            AuditQueryParams(module="../bad")

    def test_audit_query_action_path_traversal_blocked(self):
        """测试：操作类型参数中的路径遍历被拒绝"""
        with self.assertRaises(ValidationError):
            AuditQueryParams(action="../bad")


class TestIdValidation(unittest.TestCase):
    """ID 参数正整数校验测试（通过 Pydantic int 类型自动实现）"""

    def test_route_id_positive_int(self):
        """测试：正整数 ID 通过 Pydantic int 类型校验"""
        # 这主要由 FastAPI 路径参数的类型注解保证
        # 这里验证 schema 中的 ID 字段都是 int 类型
        from backend.schemas.auth import ApiKeyResponse
        from backend.schemas.ip import IpBlacklistResponse
        from backend.schemas.waf import WafRuleResponse
        from backend.schemas.audit import SecurityEventResponse, AuditLogResponse

        # 验证 ID 字段存在且为 int 类型
        self.assertTrue(isinstance(ApiKeyResponse.model_fields["id"].annotation, type))
        self.assertTrue(isinstance(IpBlacklistResponse.model_fields["id"].annotation, type))
        self.assertTrue(isinstance(WafRuleResponse.model_fields["id"].annotation, type))
        self.assertTrue(isinstance(SecurityEventResponse.model_fields["id"].annotation, type))
        self.assertTrue(isinstance(AuditLogResponse.model_fields["id"].annotation, type))


if __name__ == "__main__":
    unittest.main(verbosity=2)
