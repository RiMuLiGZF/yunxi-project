"""
云汐 M12 安全盾 - 敏感数据脱敏工具
提供各类敏感数据的脱敏处理功能，支持：

1. API Key 脱敏：前4位 + **** + 后4位
2. 密码脱敏：全部显示为 ******
3. JWT Token 脱敏：前10位 + ****
4. IP 地址脱敏：最后一段替换为 ***
5. 通用字段脱敏：可自定义脱敏规则
6. 批量脱敏：支持字典数据中指定字段的自动脱敏

所有脱敏函数均为纯函数，输入输出类型一致，不修改原始数据。
"""

import re
import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ===========================================================================
# 单字段脱敏函数
# ===========================================================================

def mask_api_key(value: str) -> str:
    """API Key 脱敏：只显示前 4 位 + **** + 后 4 位

    Args:
        value: 原始 API Key 字符串

    Returns:
        脱敏后的字符串，如 "m12-****abcd"
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    if len(value) <= 8:
        # 太短的 Key 全部隐藏
        return "*" * len(value)

    return f"{value[:4]}****{value[-4:]}"


def mask_password(value: str) -> str:
    """密码脱敏：全部显示为 ******

    Args:
        value: 原始密码字符串

    Returns:
        固定 6 个星号
    """
    if value is None:
        return ""
    return "******"


def mask_jwt_token(value: str) -> str:
    """JWT Token 脱敏：只显示前 10 位 + ****

    Args:
        value: 原始 JWT Token 字符串

    Returns:
        脱敏后的字符串，如 "eyJhbGciOi****"
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    if len(value) <= 10:
        return "*" * len(value)

    return f"{value[:10]}****"


def mask_ip_address(value: str) -> str:
    """IP 地址脱敏：最后一段替换为 ***

    支持 IPv4（如 192.168.1.100 -> 192.168.1.***）
    支持 IPv6（简单处理，最后一段替换为 ***）
    支持 CIDR 格式（如 192.168.1.0/24 -> 192.168.1.***/24）

    Args:
        value: 原始 IP 地址字符串

    Returns:
        脱敏后的 IP 地址
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    # 处理 CIDR 格式
    cidr_suffix = ""
    if "/" in value:
        parts = value.split("/", 1)
        value = parts[0]
        cidr_suffix = "/" + parts[1]

    # IPv4 格式
    if "." in value:
        parts = value.split(".")
        if len(parts) == 4:
            parts[-1] = "***"
            return ".".join(parts) + cidr_suffix

    # IPv6 格式（简单处理：最后一段替换）
    if ":" in value:
        parts = value.split(":")
        if len(parts) >= 2:
            parts[-1] = "***"
            return ":".join(parts) + cidr_suffix

    # 无法识别的格式，直接返回原值
    return value + cidr_suffix


def mask_email(value: str) -> str:
    """邮箱地址脱敏：用户名部分部分隐藏

    如：user@example.com -> u***r@example.com

    Args:
        value: 原始邮箱地址

    Returns:
        脱敏后的邮箱地址
    """
    if not value or not isinstance(value, str) or "@" not in value:
        return str(value) if value is not None else ""

    username, domain = value.split("@", 1)
    if len(username) <= 2:
        masked_user = "*" * len(username)
    else:
        masked_user = username[0] + "***" + username[-1]

    return f"{masked_user}@{domain}"


def mask_phone(value: str) -> str:
    """手机号脱敏：中间 4 位替换为 ****

    如：13812345678 -> 138****5678

    Args:
        value: 原始手机号

    Returns:
        脱敏后的手机号
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    # 提取数字部分
    digits = re.sub(r"\D", "", value)
    if len(digits) < 7:
        return "*" * len(value) if value else ""

    # 保留前3后4，中间替换
    if len(digits) >= 11:
        masked = digits[:3] + "****" + digits[-4:]
    else:
        masked = digits[:3] + "****" + digits[-1]

    return masked


# ===========================================================================
# 脱敏规则映射
# ===========================================================================

# 预设脱敏类型到函数的映射
_MASK_FUNCTIONS = {
    "api_key": mask_api_key,
    "password": mask_password,
    "jwt_token": mask_jwt_token,
    "token": mask_jwt_token,
    "ip": mask_ip_address,
    "ip_address": mask_ip_address,
    "email": mask_email,
    "phone": mask_phone,
}


# ===========================================================================
# 批量脱敏函数
# ===========================================================================

def mask_sensitive_data(
    data: Any,
    fields: Optional[Dict[str, str]] = None,
) -> Any:
    """对数据中的敏感字段进行脱敏处理

    支持对字典数据中指定字段进行脱敏，可以指定每个字段的脱敏类型。
    不修改原始数据，返回脱敏后的副本。

    Args:
        data: 待脱敏的数据，支持 dict、list 或单个值
        fields: 字段名 -> 脱敏类型 的映射字典
            支持的脱敏类型：api_key, password, jwt_token/token,
            ip/ip_address, email, phone
            例如：{"api_key_value": "api_key", "user_ip": "ip"}

    Returns:
        脱敏后的数据，类型与输入一致

    Examples:
        >>> data = {"token": "eyJhbGciOiJIUzI1NiIs...", "password": "secret123"}
        >>> mask_sensitive_data(data, {"token": "jwt_token", "password": "password"})
        {'token': 'eyJhbGciOi****', 'password': '******'}
    """
    if fields is None or not fields:
        return data

    if data is None:
        return None

    # 字典类型：递归处理指定字段
    if isinstance(data, dict):
        result = data.copy()
        for field_name, mask_type in fields.items():
            if field_name in result:
                mask_func = _MASK_FUNCTIONS.get(mask_type)
                if mask_func:
                    result[field_name] = mask_func(result[field_name])
                # 未知类型不处理
        # 递归处理嵌套字典
        for key in result:
            if isinstance(result[key], dict) and key not in fields:
                result[key] = mask_sensitive_data(result[key], fields)
            elif isinstance(result[key], list) and key not in fields:
                result[key] = mask_sensitive_data(result[key], fields)
        return result

    # 列表类型：递归处理每个元素
    if isinstance(data, list):
        return [mask_sensitive_data(item, fields) for item in data]

    # 其他类型直接返回
    return data


def mask_dict_with_rules(
    data: Dict[str, Any],
    rules: Dict[str, str],
) -> Dict[str, Any]:
    """按规则字典对字典数据进行脱敏（mask_sensitive_data 的别名）

    Args:
        data: 待脱敏的字典数据
        rules: 字段名 -> 脱敏类型 的规则字典

    Returns:
        脱敏后的字典
    """
    return mask_sensitive_data(data, rules)


# ===========================================================================
# 审计日志专用脱敏
# ===========================================================================

# 审计日志中默认需要脱敏的字段及其类型
AUDIT_SENSITIVE_FIELDS = {
    # 认证相关
    "password": "password",
    "old_password": "password",
    "new_password": "password",
    "access_token": "jwt_token",
    "refresh_token": "jwt_token",
    "token": "jwt_token",
    "jwt_token": "jwt_token",
    # API Key 相关
    "api_key": "api_key",
    "api_key_value": "api_key",
    "key_value": "api_key",
    "secret": "api_key",
    "secret_key": "api_key",
    # IP 相关
    "source_ip": "ip",
    "client_ip": "ip",
    "remote_ip": "ip",
    "ip_address": "ip",
    # 用户信息
    "email": "email",
    "phone": "phone",
    "mobile": "phone",
}


def mask_audit_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """对审计日志数据进行默认脱敏

    使用 AUDIT_SENSITIVE_FIELDS 中定义的规则对审计日志进行脱敏。
    不修改原始数据，返回脱敏后的副本。

    Args:
        data: 审计日志字典数据

    Returns:
        脱敏后的审计日志数据
    """
    return mask_sensitive_data(data, AUDIT_SENSITIVE_FIELDS)


# ===========================================================================
# 直接运行测试
# ===========================================================================

if __name__ == "__main__":
    # 测试各脱敏函数
    logger.info("=== 脱敏工具测试 ===")

    # API Key 脱敏
    logger.info("API Key 脱敏:")
    logger.info("  'm12-abcdefghijklmnop1234' -> %s", mask_api_key("m12-abcdefghijklmnop1234"))
    logger.info("  'short' -> %s", mask_api_key("short"))

    # 密码脱敏
    logger.info("密码脱敏:")
    logger.info("  'mysecret123' -> %s", mask_password("mysecret123"))

    # JWT Token 脱敏
    logger.info("JWT Token 脱敏:")
    test_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    logger.info("  '%s...' -> %s", test_token[:30], mask_jwt_token(test_token))

    # IP 地址脱敏
    logger.info("IP 地址脱敏:")
    logger.info("  '192.168.1.100' -> %s", mask_ip_address("192.168.1.100"))
    logger.info("  '10.0.0.1' -> %s", mask_ip_address("10.0.0.1"))
    logger.info("  '192.168.1.0/24' -> %s", mask_ip_address("192.168.1.0/24"))
    logger.info("  '2001:db8::1' -> %s", mask_ip_address("2001:db8::1"))

    # 邮箱脱敏
    logger.info("邮箱脱敏:")
    logger.info("  'user@example.com' -> %s", mask_email("user@example.com"))

    # 手机号脱敏
    logger.info("手机号脱敏:")
    logger.info("  '13812345678' -> %s", mask_phone("13812345678"))

    # 批量脱敏
    logger.info("批量脱敏 (mask_sensitive_data):")
    test_data = {
        "username": "admin",
        "password": "secret123",
        "api_key": "m12-abcdefghijklmnopqrst",
        "source_ip": "192.168.1.100",
        "access_token": test_token,
        "details": {
            "password": "nested_pass",
            "ip_address": "10.0.0.50",
        },
    }
    masked = mask_sensitive_data(test_data, AUDIT_SENSITIVE_FIELDS)
    logger.info("  原始 password: %s", test_data["password"])
    logger.info("  脱敏 password: %s", masked["password"])
    logger.info("  原始 api_key: %s", test_data["api_key"])
    logger.info("  脱敏 api_key: %s", masked["api_key"])
    logger.info("  原始 source_ip: %s", test_data["source_ip"])
    logger.info("  脱敏 source_ip: %s", masked["source_ip"])
    logger.info("  嵌套 password: %s", masked["details"]["password"])
    logger.info("  嵌套 ip_address: %s", masked["details"]["ip_address"])
