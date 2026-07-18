"""
V11.1 整改专项测试

测试范围：
1. P0-002 API Key 加密存储（8 个测试）
2. P0-001 PII 风险分级修复（5 个测试）
3. P1-001 PII 检测正则增强（8 个测试）
4. P1-002 7 类 PII 脱敏补全（7 个测试）
5. P1-004 GPL 协议风险提示（4 个测试）
6. P2-003 审计摘要字段（3 个测试）
"""

from __future__ import annotations

import sys
import os

import pytest

# ============================================================================
# 1. P0-002 API Key 加密存储
# ============================================================================

class TestApiKeyEncryption:
    """API Key 加密存储整改测试（P0-002）"""

    def test_encrypted_key_not_in_memory(self):
        """加密存储后内存中无明文 Key"""
        from federation.registry import ExternalAgentRegistry

        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="测试Agent",
            provider="TestProvider",
            api_key="sk-real-secret-key-1234567890",
        )

        # 检查内部存储的 Key 不等于明文
        encrypted = registry._api_keys_encrypted.get(agent.agent_id, "")
        assert encrypted != "sk-real-secret-key-1234567890"
        assert len(encrypted) > 0
        # 加密后不包含原始明文片段
        assert "real-secret" not in encrypted

    def test_trusted_caller_gets_plaintext(self):
        """受信任调用者可读取明文 Key"""
        from federation.registry import ExternalAgentRegistry

        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="测试Agent",
            provider="TestProvider",
            api_key="sk-trusted-caller-key-12345",
        )

        # 受信任的内部组件可以读取明文
        plaintext = registry.get_api_key(
            agent.agent_id,
            caller_id="federation.adapter.openai",
        )
        assert plaintext == "sk-trusted-caller-key-12345"

    def test_untrusted_caller_gets_masked(self):
        """不受信任调用者返回脱敏值而非明文"""
        from federation.registry import ExternalAgentRegistry

        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="测试Agent",
            provider="TestProvider",
            api_key="sk-untrusted-secret-key-67890",
        )

        # 不受信任的调用者只能拿到脱敏值
        masked = registry.get_api_key(
            agent.agent_id,
            caller_id="some.external.service",
        )
        # 不应等于明文
        assert masked != "sk-untrusted-secret-key-67890"
        # 应包含脱敏标记（****）
        assert "****" in masked
        # 不应包含完整的 Key 内容
        assert "untrusted-secret" not in masked

    def test_master_key_rotation(self):
        """主密钥轮换后数据仍可正确解密"""
        from federation.registry import ExternalAgentRegistry

        registry = ExternalAgentRegistry()

        # 注册多个带 API Key 的 Agent
        agent1 = registry.register_agent(
            display_name="Agent1",
            provider="ProviderA",
            api_key="sk-key-one-aaaa1111",
        )
        agent2 = registry.register_agent(
            display_name="Agent2",
            provider="ProviderB",
            api_key="sk-key-two-bbbb2222",
        )

        # 轮换前验证可解密
        key1_before = registry.get_api_key(
            agent1.agent_id, caller_id="federation.registry"
        )
        assert key1_before == "sk-key-one-aaaa1111"

        # 执行主密钥轮换
        result = registry.rotate_all_keys()
        assert result["success"] is True
        assert result["rotated_keys_count"] == 2
        assert result["total_keys"] == 2

        # 轮换后仍能正确解密
        key1_after = registry.get_api_key(
            agent1.agent_id, caller_id="federation.registry"
        )
        key2_after = registry.get_api_key(
            agent2.agent_id, caller_id="federation.registry"
        )
        assert key1_after == "sk-key-one-aaaa1111"
        assert key2_after == "sk-key-two-bbbb2222"

    def test_set_api_key_log_no_plaintext(self):
        """set_api_key 日志中不包含明文 Key"""
        from federation.crypto_utils import mask_api_key
        from federation.registry import ExternalAgentRegistry

        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="测试Agent",
            provider="TestProvider",
        )

        plain_key = "sk-log-leak-test-9876543210"
        result = registry.set_api_key(agent.agent_id, plain_key)
        assert result is True

        # 验证 mask_api_key 工具函数不会泄漏明文
        masked = mask_api_key(plain_key)
        assert "log-leak-test" not in masked
        assert "****" in masked
        # 保留前后各 4 位
        assert masked.startswith("sk-l")
        assert masked.endswith("3210")

    def test_empty_api_key_handling(self):
        """空 Key 处理：加密和存储都不报错"""
        from federation.registry import ExternalAgentRegistry

        registry = ExternalAgentRegistry()
        agent = registry.register_agent(
            display_name="无KeyAgent",
            provider="NoKeyProvider",
            api_key="",
        )

        # 空 Key 不存储
        assert agent.agent_id not in registry._api_keys_encrypted

        # set_api_key 空字符串也能正常处理
        result = registry.set_api_key(agent.agent_id, "")
        assert result is True  # 设置成功（存储空加密值）

        # get_api_key 返回空字符串
        value = registry.get_api_key(agent.agent_id, caller_id="federation.registry")
        assert value == ""

    def test_unknown_agent_returns_empty(self):
        """未知 agent_id 查询 API Key 返回空"""
        from federation.registry import ExternalAgentRegistry

        registry = ExternalAgentRegistry()

        # 不存在的 Agent
        value = registry.get_api_key("nonexistent_agent_id")
        assert value == ""

        # 即使传入受信任 caller，也返回空
        value_trusted = registry.get_api_key(
            "nonexistent_agent_id",
            caller_id="federation.adapter.openai",
        )
        assert value_trusted == ""

    def test_stats_shows_encrypted_key_count(self):
        """stats 中显示加密 Key 数量"""
        from federation.registry import ExternalAgentRegistry

        registry = ExternalAgentRegistry()

        # 初始状态下的加密 Key 数（默认本地模型没有 Key）
        stats_before = registry.stats()
        initial_keys = stats_before.get("encrypted_keys", 0)

        # 注册 3 个带 API Key 的 Agent
        for i in range(3):
            registry.register_agent(
                display_name=f"Agent{i}",
                provider=f"Provider{i}",
                api_key=f"sk-test-key-{i}-{1000 + i}",
            )

        stats_after = registry.stats()
        assert stats_after["encrypted_keys"] == initial_keys + 3
        assert "crypto_available" in stats_after


# ============================================================================
# 2. P0-001 PII 风险分级修复
# ============================================================================

class TestPiiRiskLevelFixes:
    """PII 风险分级修复测试（P0-001）"""

    def test_low_risk_also_sanitized(self):
        """low 风险 PII 也会进入脱敏分支（was_modified=True）"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 单个 low 风险 PII（低涉密等级下，单个邮箱为 low）
        result = guard.sanitize_content(
            content="请联系 a@b.com 谢谢",
            security_level=SecurityClassification.PUBLIC,
        )

        # V11.1 修复：即使 low 风险也应该被脱敏
        assert result["was_modified"] is True
        assert "a@b.com" not in result["sanitized"]

    def test_medium_risk_sanitized(self):
        """medium 风险 PII 正确脱敏"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        result = guard.sanitize_content(
            content="我的邮箱是 test_user@example.com",
            security_level=SecurityClassification.INTERNAL,
        )

        assert result["risk_level"] in ("medium", "low")
        assert result["was_modified"] is True
        # 邮箱域名应保留，本地部分脱敏
        assert "test_user" not in result["sanitized"]
        assert "example.com" in result["sanitized"]

    def test_high_risk_strong_sanitization(self):
        """high 风险 PII 强脱敏（只保留极少特征）"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 使用 CONFIDENTIAL 涉密等级 + 手机号，提升到 high 风险
        result = guard.sanitize_content(
            content="我的手机号是13812345678",
            security_level=SecurityClassification.CONFIDENTIAL,
        )

        assert result["risk_level"] in ("high", "critical")
        assert result["was_modified"] is True
        # 强脱敏：手机号大部分被隐藏
        sanitized = result["sanitized"]
        assert "13812345678" not in sanitized
        # 强脱敏只保留极少数字
        digit_count = sum(c.isdigit() for c in sanitized)
        assert digit_count <= 5  # 最多保留前3后4或更少

    def test_critical_risk_full_replacement(self):
        """critical 风险 PII 完全替换或强脱敏"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 身份证号是 critical 级
        result = guard.sanitize_content(
            content="身份证号 110101199003077758",
            security_level=SecurityClassification.INTERNAL,
        )

        assert result["risk_level"] == "critical"
        assert result["was_modified"] is True
        # critical 风险下身份证被完全替换或几乎全部脱敏
        assert "110101199003077758" not in result["sanitized"]

    def test_none_risk_unchanged(self):
        """none 风险（无 PII）不修改原文"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        original = "这是一段完全正常的文本，不包含任何敏感信息。"
        result = guard.sanitize_content(
            content=original,
            security_level=SecurityClassification.PUBLIC,
        )

        assert result["risk_level"] == "none"
        assert result["was_modified"] is False
        assert result["sanitized"] == original


# ============================================================================
# 3. P1-001 PII 检测正则增强
# ============================================================================

class TestPiiDetectionEnhancement:
    """PII 检测正则增强测试（P1-001）"""

    def test_zero_width_char_bypass(self):
        """零宽字符绕过检测：插入零宽字符的 PII 仍能被检测到"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 在邮箱中插入零宽字符
        zw_email = "t\u200be\u200bs\u200bt@example.com"
        result = guard.scan_content(zw_email, SecurityClassification.PUBLIC)

        # 预处理应清除零宽字符后检测到邮箱
        pii_types = result["pii_types"]
        assert "email" in pii_types

    def test_fullwidth_char_bypass(self):
        """全角字符绕过检测：全角邮箱/手机号仍能被检测"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 全角数字邮箱
        fullwidth_email = "test@ｅｘａｍｐｌｅ．ｃｏｍ"
        result = guard.scan_content(fullwidth_email, SecurityClassification.PUBLIC)
        pii_types = result["pii_types"]
        assert "email" in pii_types

    def test_at_dot_notation_bypass(self):
        """"[at]/[dot] 替换绕过检测：仍能识别邮箱"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 使用 [at] / [dot] 形式
        obfuscated = "请联系 test [at] example [dot] com 获取信息"
        result = guard.scan_content(obfuscated, SecurityClassification.PUBLIC)

        # 预处理应还原后检测到邮箱
        pii_types = result["pii_types"]
        assert "email" in pii_types

    def test_phone_with_spaces_detected(self):
        """手机号空格分隔可被正确检测"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 空格分隔的手机号
        spaced_phone = "我的电话是 138 1234 5678"
        result = guard.scan_content(spaced_phone, SecurityClassification.PUBLIC)

        pii_types = result["pii_types"]
        assert "phone_cn" in pii_types

    def test_id_card_checksum_valid(self):
        """身份证校验码验证：正确校验码通过"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 110101199003077758 是校验码正确的身份证号
        valid_id = "身份证号：110101199003077758"
        result = guard.scan_content(valid_id, SecurityClassification.PUBLIC)

        pii_types = result["pii_types"]
        assert "id_card_cn" in pii_types
        assert result["pii_count"] >= 1

    def test_id_card_checksum_invalid(self):
        """身份证校验码验证：错误校验码被过滤（不误报）"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 将校验码最后一位改错（7改成9，应该不通过校验）
        invalid_id = "身份证号：110101199003077759"
        result = guard.scan_content(invalid_id, SecurityClassification.PUBLIC)

        # 校验码错误的不应被检测为身份证
        id_card_detections = [
            d for d in result["detections"] if d["pii_type"] == "id_card_cn"
        ]
        assert len(id_card_detections) == 0

    def test_bank_card_luhn_validation(self):
        """银行卡 Luhn 验证：正确卡号通过，错误卡号被过滤"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 4111111111111111 是标准 Luhn 有效测试卡号
        valid_card = "卡号：4111111111111111"
        result_valid = guard.scan_content(valid_card, SecurityClassification.PUBLIC)
        bank_detections_valid = [
            d for d in result_valid["detections"] if d["pii_type"] == "bank_card"
        ]
        assert len(bank_detections_valid) >= 1

        # 4111111111111112 Luhn 校验不通过
        invalid_card = "卡号：4111111111111112"
        result_invalid = guard.scan_content(invalid_card, SecurityClassification.PUBLIC)
        bank_detections_invalid = [
            d for d in result_invalid["detections"] if d["pii_type"] == "bank_card"
        ]
        assert len(bank_detections_invalid) == 0

    def test_phone_not_in_id_card_digits(self):
        """手机号不误匹配身份证中的数字段"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 身份证号中可能包含 11 位连续数字看似手机号
        # 如 110101199003077758 中 19900307775 看似手机号
        content = "身份证：110101199003077758"
        result = guard.scan_content(content, SecurityClassification.PUBLIC)

        phone_detections = [
            d for d in result["detections"] if d["pii_type"] == "phone_cn"
        ]
        # 身份证号中的数字段不应被误识别为手机号（边界断言保护）
        assert len(phone_detections) == 0

    def test_case_insensitive_detection(self):
        """大小写不敏感检测：API Key/Token 等混合大小写仍能识别"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 混合大小写的 API Key
        content = 'API_Key = "sk-abcdefghijklmnopqrstuvwxyz123456"'
        result = guard.scan_content(content, SecurityClassification.PUBLIC)

        pii_types = result["pii_types"]
        assert "api_key" in pii_types


# ============================================================================
# 4. P1-002 7 类 PII 脱敏补全
# ============================================================================

class TestPiiSanitizationComplete:
    """7 类 PII 脱敏补全测试（P1-002）"""

    def test_id_card_sanitization(self):
        """身份证脱敏：脱敏后不包含完整身份证号"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])
        original = "请提供身份证 110101199003077758 用于验证"
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)

        assert result["was_modified"] is True
        assert "110101199003077758" not in result["sanitized"]
        # 至少包含脱敏后的部分（保留前6或后4）
        assert "110101" in result["sanitized"] or "7758" in result["sanitized"] or "*" in result["sanitized"]

    def test_bank_card_sanitization(self):
        """银行卡脱敏：脱敏后不包含完整卡号"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])
        original = "银行卡号 4111111111111111 请妥善保管"
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)

        assert result["was_modified"] is True
        assert "4111111111111111" not in result["sanitized"]

    def test_api_key_sanitization(self):
        """API Key 脱敏：脱敏后不包含完整 Key"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])
        original = '配置文件内容：api_key = "sk-abcdefghijklmnopqrstuvwxyz123456"'
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)

        assert result["was_modified"] is True
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result["sanitized"]

    def test_password_sanitization(self):
        """密码脱敏：密码值被替换为占位符"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])
        original = "配置信息：password = my_secret_password_123，请妥善保管"
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)

        assert result["was_modified"] is True
        assert "my_secret_password_123" not in result["sanitized"]
        # 应包含密码脱敏标记
        assert "PASSWORD" in result["sanitized"] or "****" in result["sanitized"]

    def test_token_sanitization(self):
        """Token 脱敏：Bearer Token 被正确脱敏"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])
        original = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature12345"
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)

        assert result["was_modified"] is True
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result["sanitized"]

    def test_private_key_sanitization(self):
        """私钥脱敏：PEM 格式私钥被完全替换"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])
        original = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA0Z5+sampleprivatekeydata1234567890abcdefghij\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)

        assert result["was_modified"] is True
        assert "MIIEpAIBAAKCAQEA0Z5" not in result["sanitized"]
        # 私钥一律完全替换
        assert "REDACTED" in result["sanitized"] or "已脱敏" in result["sanitized"]

    def test_internal_url_sanitization(self):
        """内网 URL 脱敏：内网 IP/域名 URL 被脱敏"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])
        original = "请访问 http://192.168.1.100:8080/api/internal 获取数据"
        result = guard.sanitize_content(original, SecurityClassification.INTERNAL)

        assert result["was_modified"] is True
        assert "192.168.1.100" not in result["sanitized"]
        assert "url_internal" in result["pii_types"]


# ============================================================================
# 5. P1-004 GPL 协议风险提示
# ============================================================================

class TestGplLicenseRisk:
    """GPL 协议风险提示测试（P1-004）"""

    def test_gpl_license_without_confirmation_fails(self):
        """GPL 协议未确认风险时注册失败，抛出 ValueError"""
        from federation.registry import ExternalAgentRegistry

        registry = ExternalAgentRegistry()

        with pytest.raises(ValueError) as exc_info:
            registry.register_agent(
                display_name="GPL Agent",
                provider="GPLProvider",
                license="GPL-3.0",
                confirm_license_risk=False,
            )

        assert "GPL" in str(exc_info.value) or "传染性" in str(exc_info.value)

    def test_gpl_license_with_confirmation_succeeds(self):
        """GPL 协议确认风险后注册成功"""
        from federation.registry import ExternalAgentRegistry
        from shared_models import LicenseType

        registry = ExternalAgentRegistry()

        agent = registry.register_agent(
            display_name="GPL Agent",
            provider="GPLProvider",
            license="GPL-3.0",
            confirm_license_risk=True,
        )

        assert agent is not None
        assert agent.license == LicenseType.GPL_3

    def test_mit_apache_no_confirmation_needed(self):
        """MIT/Apache 等宽松协议无需确认即可注册"""
        from federation.registry import ExternalAgentRegistry
        from shared_models import LicenseType

        registry = ExternalAgentRegistry()

        # MIT 协议无需确认
        mit_agent = registry.register_agent(
            display_name="MIT Agent",
            provider="MITProvider",
            license="MIT",
            confirm_license_risk=False,
        )
        assert mit_agent.license == LicenseType.MIT

        # Apache 协议无需确认
        apache_agent = registry.register_agent(
            display_name="Apache Agent",
            provider="ApacheProvider",
            license="Apache-2.0",
            confirm_license_risk=False,
        )
        assert apache_agent.license == LicenseType.APACHE

    def test_license_field_saved_correctly(self):
        """license 字段在 profile 中正确保存"""
        from federation.registry import ExternalAgentRegistry
        from shared_models import LicenseType

        registry = ExternalAgentRegistry()

        # 测试不同协议类型
        test_cases = [
            ("MIT Agent", "MITProvider", "MIT", LicenseType.MIT),
            ("Apache Agent", "ApacheProvider", "Apache-2.0", LicenseType.APACHE),
            ("Proprietary Agent", "PropProvider", "Proprietary", LicenseType.PROPRIETARY),
            ("GPL Agent", "GPLProvider", "GPL-2.0", LicenseType.GPL_2),
        ]

        for name, provider, lic, expected in test_cases:
            agent = registry.register_agent(
                display_name=name,
                provider=provider,
                license=lic,
                confirm_license_risk=True,  # 全部确认，避免 GPL 类抛错
            )
            assert agent.license == expected

        # stats 中 license 统计存在
        stats = registry.stats()
        assert "by_license" in stats
        assert len(stats["by_license"]) >= 4


# ============================================================================
# 6. P2-003 审计摘要字段
# ============================================================================

class TestAuditSummaryFields:
    """审计摘要字段测试（P2-003）"""

    def test_scan_returns_content_hash_and_length(self):
        """scan 返回 content_hash 和 content_length 字段"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification
        import hashlib

        guard = PrivacyGuard(custom_keywords=[])
        content = "这是一段测试内容，用于验证哈希和长度。"
        result = guard.scan_content(content, SecurityClassification.PUBLIC)

        # 验证 content_hash 存在且正确
        assert "content_hash" in result
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert result["content_hash"] == expected_hash

        # 验证 content_length 存在且正确
        assert "content_length" in result
        assert result["content_length"] == len(content.encode("utf-8"))

    def test_sanitize_returns_sanitized_preview(self):
        """sanitize 返回 sanitized_preview 字段"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])
        content = "我的手机号是13812345678，邮箱是test@example.com"
        result = guard.sanitize_content(content, SecurityClassification.INTERNAL)

        # 验证 sanitized_preview 存在
        assert "sanitized_preview" in result
        assert isinstance(result["sanitized_preview"], str)
        assert len(result["sanitized_preview"]) > 0
        # 预览应基于脱敏后的内容
        assert result["sanitized_preview"] in result["sanitized"] + "..." or result["sanitized"].startswith(result["sanitized_preview"].rstrip("..."))

    def test_audit_log_contains_pii_types_detected(self):
        """audit_log 包含 pii_types_detected 字段"""
        from federation.privacy_guard import PrivacyGuard
        from shared_models import SecurityClassification

        guard = PrivacyGuard(custom_keywords=[])

        # 扫描包含多种 PII 的内容
        content = "手机号13812345678，邮箱test@example.com"
        guard.scan_content(content, SecurityClassification.PUBLIC)

        # 获取审计日志
        logs = guard.get_audit_log(limit=5)
        assert len(logs) >= 1

        # 验证最新的日志条目包含 pii_types_detected
        latest = logs[0]
        assert "pii_types_detected" in latest
        assert isinstance(latest["pii_types_detected"], list)
        # 应检测到手机号和邮箱
        assert "phone_cn" in latest["pii_types_detected"]
        assert "email" in latest["pii_types_detected"]


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
