"""
M12 安全盾 - 模块级错误码定义（统一 6 位错误码体系）

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 12 (模块编号，M12)
  - YY = 错误类别
  - ZZ = 序号
"""

try:
    from shared.core.errors import (
        ModuleCode,
        ErrorCategory,
        build_error_code,
        ModuleErrorCode,
    )
    _UNIFIED_ERRORS_AVAILABLE = True
except ImportError:
    _UNIFIED_ERRORS_AVAILABLE = False
    ModuleCode = None  # type: ignore
    ErrorCategory = None  # type: ignore
    ModuleErrorCode = object  # type: ignore

    def build_error_code(module, category, seq):  # type: ignore
        return int(module) * 10000 + int(category) * 100 + seq


if _UNIFIED_ERRORS_AVAILABLE:

    class M12ErrorCode(ModuleErrorCode):
        """M12 安全盾错误码常量.

        模块编号: 12
        范围: 120100 - 120999
        """
        MODULE = ModuleCode.M12

        # ---------- 参数错误 (1201xx) ----------
        INVALID_RULE_ID = build_error_code(ModuleCode.M12, ErrorCategory.VALIDATION, 1)
        """无效的规则 ID"""
        INVALID_RULE_CONFIG = build_error_code(ModuleCode.M12, ErrorCategory.VALIDATION, 2)
        """无效的规则配置"""
        INVALID_IP_ADDRESS = build_error_code(ModuleCode.M12, ErrorCategory.VALIDATION, 3)
        """无效的 IP 地址"""
        INVALID_API_KEY = build_error_code(ModuleCode.M12, ErrorCategory.VALIDATION, 4)
        """无效的 API Key"""
        INVALID_WAF_PAYLOAD = build_error_code(ModuleCode.M12, ErrorCategory.VALIDATION, 5)
        """无效的 WAF 检测负载"""

        # ---------- 认证错误 (1202xx) ----------
        API_KEY_INVALID = build_error_code(ModuleCode.M12, ErrorCategory.AUTHENTICATION, 1)
        """API Key 无效"""
        API_KEY_EXPIRED = build_error_code(ModuleCode.M12, ErrorCategory.AUTHENTICATION, 2)
        """API Key 已过期"""
        API_KEY_REVOKED = build_error_code(ModuleCode.M12, ErrorCategory.AUTHENTICATION, 3)
        """API Key 已被吊销"""

        # ---------- 权限错误 (1203xx) ----------
        ADMIN_REQUIRED = build_error_code(ModuleCode.M12, ErrorCategory.AUTHORIZATION, 1)
        """需要管理员权限"""
        AUDITOR_REQUIRED = build_error_code(ModuleCode.M12, ErrorCategory.AUTHORIZATION, 2)
        """需要审计员权限"""
        IP_BLOCKED = build_error_code(ModuleCode.M12, ErrorCategory.AUTHORIZATION, 3)
        """IP 已被封禁"""

        # ---------- 资源不存在 (1204xx) ----------
        RULE_NOT_FOUND = build_error_code(ModuleCode.M12, ErrorCategory.NOT_FOUND, 1)
        """规则不存在"""
        IP_RULE_NOT_FOUND = build_error_code(ModuleCode.M12, ErrorCategory.NOT_FOUND, 2)
        """IP 规则不存在"""
        API_KEY_NOT_FOUND = build_error_code(ModuleCode.M12, ErrorCategory.NOT_FOUND, 3)
        """API Key 不存在"""
        AUDIT_LOG_NOT_FOUND = build_error_code(ModuleCode.M12, ErrorCategory.NOT_FOUND, 4)
        """审计日志不存在"""

        # ---------- 业务错误 (1205xx) ----------
        RATE_LIMIT_EXCEEDED = build_error_code(ModuleCode.M12, ErrorCategory.BUSINESS, 1)
        """超出速率限制"""
        WAF_BLOCKED = build_error_code(ModuleCode.M12, ErrorCategory.BUSINESS, 2)
        """被 WAF 拦截"""
        IP_BANNED = build_error_code(ModuleCode.M12, ErrorCategory.BUSINESS, 3)
        """IP 已被封禁"""
        RULE_ALREADY_EXISTS = build_error_code(ModuleCode.M12, ErrorCategory.BUSINESS, 4)
        """规则已存在"""
        API_KEY_ALREADY_EXISTS = build_error_code(ModuleCode.M12, ErrorCategory.BUSINESS, 5)
        """API Key 已存在"""
        SECURITY_INCIDENT_DETECTED = build_error_code(ModuleCode.M12, ErrorCategory.BUSINESS, 6)
        """检测到安全事件"""
        AUTO_RESPONSE_TRIGGERED = build_error_code(ModuleCode.M12, ErrorCategory.BUSINESS, 7)
        """自动响应已触发"""

        # ---------- 系统错误 (1206xx) ----------
        WAF_ENGINE_ERROR = build_error_code(ModuleCode.M12, ErrorCategory.SYSTEM, 1)
        """WAF 引擎错误"""
        RATE_LIMITER_ERROR = build_error_code(ModuleCode.M12, ErrorCategory.SYSTEM, 2)
        """限流器错误"""
        IP_FILTER_ERROR = build_error_code(ModuleCode.M12, ErrorCategory.SYSTEM, 3)
        """IP 过滤器错误"""
        AUDIT_LOG_ERROR = build_error_code(ModuleCode.M12, ErrorCategory.SYSTEM, 4)
        """审计日志错误"""
        SECRET_ERROR = build_error_code(ModuleCode.M12, ErrorCategory.SYSTEM, 5)
        """密钥管理错误"""

    # 便捷别名
    M12_ERR = M12ErrorCode

else:
    # 回退模式
    class M12ErrorCode:
        """M12 错误码常量（回退模式）"""
        INVALID_RULE_ID = 120101
        INVALID_RULE_CONFIG = 120102
        INVALID_IP_ADDRESS = 120103
        INVALID_API_KEY = 120104
        INVALID_WAF_PAYLOAD = 120105
        API_KEY_INVALID = 120201
        API_KEY_EXPIRED = 120202
        API_KEY_REVOKED = 120203
        ADMIN_REQUIRED = 120301
        AUDITOR_REQUIRED = 120302
        IP_BLOCKED = 120303
        RULE_NOT_FOUND = 120401
        IP_RULE_NOT_FOUND = 120402
        API_KEY_NOT_FOUND = 120403
        AUDIT_LOG_NOT_FOUND = 120404
        RATE_LIMIT_EXCEEDED = 120501
        WAF_BLOCKED = 120502
        IP_BANNED = 120503
        RULE_ALREADY_EXISTS = 120504
        API_KEY_ALREADY_EXISTS = 120505
        SECURITY_INCIDENT_DETECTED = 120506
        AUTO_RESPONSE_TRIGGERED = 120507
        WAF_ENGINE_ERROR = 120601
        RATE_LIMITER_ERROR = 120602
        IP_FILTER_ERROR = 120603
        AUDIT_LOG_ERROR = 120604
        SECRET_ERROR = 120605

    M12_ERR = M12ErrorCode


__all__ = [
    "M12ErrorCode",
    "M12_ERR",
    "_UNIFIED_ERRORS_AVAILABLE",
]
