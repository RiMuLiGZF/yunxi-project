"""
云汐 M12 安全盾 - 数据脱敏核心模块（增强版）

在原有脱敏功能基础上增强，提供：
1. 常见脱敏规则
   - 手机号：138****1234
   - 邮箱：a***@example.com
   - 身份证：110***********1234
   - 银行卡：6222 **** **** 1234
   - 姓名：张*
   - 地址：北京市海淀区***
   - IP 地址：192.168.***.***

2. 自定义脱敏
   - 正则匹配脱敏
   - 位置脱敏（前N后M）
   - 哈希脱敏（不可逆）
   - 加密脱敏（可逆，需要密钥）

3. 自动脱敏
   - API 响应自动脱敏
   - 日志自动脱敏
   - 按字段类型自动匹配规则
"""

import re
import hashlib
import base64
import logging
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


# ===========================================================================
# 基础脱敏函数
# ===========================================================================

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

    digits = re.sub(r"\D", "", value)
    if len(digits) < 7:
        return "*" * len(value) if value else ""

    if len(digits) >= 11:
        masked = digits[:3] + "****" + digits[-4:]
    else:
        masked = digits[:3] + "****" + digits[-1:]

    return masked


def mask_email(value: str) -> str:
    """邮箱脱敏：用户名部分部分隐藏

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


def mask_id_card(value: str) -> str:
    """身份证号脱敏：只显示前3位和后4位

    如：110101199001011234 -> 110***********1234

    Args:
        value: 原始身份证号

    Returns:
        脱敏后的身份证号
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    # 去除可能的分隔符
    id_str = re.sub(r"[\s\-]", "", value)
    if len(id_str) < 10:
        return "*" * len(value)

    if len(id_str) >= 18:
        # 18位身份证
        return id_str[:3] + "*" * 11 + id_str[-4:]
    elif len(id_str) == 15:
        # 15位身份证
        return id_str[:3] + "*" * 8 + id_str[-4:]
    else:
        return id_str[:3] + "*" * (len(id_str) - 7) + id_str[-4:]


def mask_bank_card(value: str) -> str:
    """银行卡号脱敏：只显示前4位和后4位，中间用 **** 分隔

    如：62220212345678901234 -> 6222 **** **** 1234

    Args:
        value: 原始银行卡号

    Returns:
        脱敏后的银行卡号
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    digits = re.sub(r"\D", "", value)
    if len(digits) < 8:
        return "*" * len(value)

    prefix = digits[:4]
    suffix = digits[-4:]
    middle_length = len(digits) - 8

    # 每4位用 **** 表示
    middle_groups = (middle_length + 3) // 4
    middle = " **** " * middle_groups
    middle = middle.strip()

    return f"{prefix} {middle} {suffix}"


def mask_name(value: str) -> str:
    """姓名脱敏：只显示姓氏，名字用 * 代替

    如：张三 -> 张*
    欧阳锋 -> 欧**
    Alice -> A****

    Args:
        value: 原始姓名

    Returns:
        脱敏后的姓名
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    if len(value) == 1:
        return "*"
    elif len(value) == 2:
        return value[0] + "*"
    else:
        return value[0] + "*" * (len(value) - 1)


def mask_address(value: str, keep_chars: int = 6) -> str:
    """地址脱敏：保留前 N 个字符，其余用 *** 代替

    如：北京市海淀区中关村大街1号 -> 北京市海淀区***

    Args:
        value: 原始地址
        keep_chars: 保留的字符数

    Returns:
        脱敏后的地址
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    if len(value) <= keep_chars:
        return "*" * len(value)

    return value[:keep_chars] + "***"


def mask_ip_address(value: str) -> str:
    """IP 地址脱敏：最后两段替换为 ***

    如：192.168.1.100 -> 192.168.***.***

    支持 IPv4、IPv6、CIDR 格式。

    Args:
        value: 原始 IP 地址

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
            parts[-2] = "***"
            parts[-1] = "***"
            return ".".join(parts) + cidr_suffix

    # IPv6 格式
    if ":" in value:
        parts = value.split(":")
        if len(parts) >= 2:
            parts[-2] = "***"
            parts[-1] = "***"
            return ":".join(parts) + cidr_suffix

    return value + cidr_suffix


# ===========================================================================
# 自定义脱敏函数
# ===========================================================================

def mask_by_position(
    value: str,
    prefix_length: int = 3,
    suffix_length: int = 2,
    mask_char: str = "*",
) -> str:
    """按位置脱敏：保留前 N 位和后 M 位，中间用掩码字符填充

    Args:
        value: 原始字符串
        prefix_length: 前缀保留长度
        suffix_length: 后缀保留长度
        mask_char: 掩码字符

    Returns:
        脱敏后的字符串
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    total_len = len(value)
    if total_len <= prefix_length + suffix_length:
        return mask_char * total_len

    mask_length = total_len - prefix_length - suffix_length
    return value[:prefix_length] + (mask_char * mask_length) + value[-suffix_length:]


def mask_by_regex(
    value: str,
    pattern: str,
    replacement: str = "***",
    flags: int = 0,
) -> str:
    """正则匹配脱敏：匹配正则表达式的部分替换为掩码

    Args:
        value: 原始字符串
        pattern: 正则表达式
        replacement: 替换字符串
        flags: 正则标志

    Returns:
        脱敏后的字符串
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    try:
        return re.sub(pattern, replacement, value, flags=flags)
    except re.error:
        return value


def mask_with_hash(
    value: str,
    algorithm: str = "sha256",
    salt: str = "",
    keep_prefix: int = 0,
) -> str:
    """哈希脱敏：不可逆的哈希脱敏

    Args:
        value: 原始字符串
        algorithm: 哈希算法（md5/sha1/sha256/sha512）
        salt: 盐值
        keep_prefix: 保留前缀长度（0 表示全部哈希）

    Returns:
        哈希脱敏后的字符串
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    algorithms = {
        "md5": hashlib.md5,
        "sha1": hashlib.sha1,
        "sha256": hashlib.sha256,
        "sha512": hashlib.sha512,
    }

    hasher = algorithms.get(algorithm.lower(), hashlib.sha256)()
    hasher.update((salt + value).encode("utf-8"))
    hashed = hasher.hexdigest()

    if keep_prefix > 0 and keep_prefix < len(value):
        return value[:keep_prefix] + hashed[:16]

    return hashed


def mask_with_encryption(
    value: str,
    key: str,
    algorithm: str = "fernet",
) -> str:
    """加密脱敏：可逆的加密脱敏

    注意：此函数为简化实现，实际生产环境应使用专门的加密库。

    Args:
        value: 原始字符串
        key: 加密密钥
        algorithm: 加密算法

    Returns:
        加密后的字符串（可解密还原）
    """
    if not value or not isinstance(value, str):
        return str(value) if value is not None else ""

    try:
        # 使用 base64 + 简单 XOR 加密作为示例（实际应使用 Fernet 等）
        key_bytes = hashlib.sha256(key.encode()).digest()
        value_bytes = value.encode("utf-8")

        encrypted = bytearray()
        for i, b in enumerate(value_bytes):
            encrypted.append(b ^ key_bytes[i % len(key_bytes)])

        return "ENC:" + base64.b64encode(bytes(encrypted)).decode("ascii")
    except Exception as e:
        logger.warning("加密脱敏失败: %s", e)
        return value


def decrypt_masked_value(
    encrypted_value: str,
    key: str,
) -> str:
    """解密脱敏值

    Args:
        encrypted_value: 加密的脱敏值
        key: 解密密钥

    Returns:
        原始值
    """
    if not encrypted_value or not encrypted_value.startswith("ENC:"):
        return encrypted_value

    try:
        key_bytes = hashlib.sha256(key.encode()).digest()
        encrypted_bytes = base64.b64decode(encrypted_value[4:])

        decrypted = bytearray()
        for i, b in enumerate(encrypted_bytes):
            decrypted.append(b ^ key_bytes[i % len(key_bytes)])

        return decrypted.decode("utf-8")
    except Exception as e:
        logger.warning("解密失败: %s", e)
        return encrypted_value


# ===========================================================================
# 脱敏规则映射
# ===========================================================================

# 所有脱敏类型到函数的映射
MASK_FUNCTIONS: Dict[str, Callable] = {
    "phone": mask_phone,
    "mobile": mask_phone,
    "email": mask_email,
    "id_card": mask_id_card,
    "idcard": mask_id_card,
    "identity_card": mask_id_card,
    "bank_card": mask_bank_card,
    "bankcard": mask_bank_card,
    "name": mask_name,
    "address": mask_address,
    "ip": mask_ip_address,
    "ip_address": mask_ip_address,
}

# 字段名到脱敏类型的自动映射（用于自动脱敏）
FIELD_NAME_TO_MASK_TYPE: Dict[str, str] = {
    # 手机号
    "phone": "phone",
    "mobile": "phone",
    "tel": "phone",
    "telephone": "phone",
    "phone_number": "phone",
    "mobile_phone": "phone",
    "手机号": "phone",
    "手机": "phone",
    # 邮箱
    "email": "email",
    "mail": "email",
    "e_mail": "email",
    "邮箱": "email",
    "电子邮箱": "email",
    # 身份证
    "id_card": "id_card",
    "idcard": "id_card",
    "id_no": "id_card",
    "identity_card": "id_card",
    "id_number": "id_card",
    "身份证": "id_card",
    "身份证号": "id_card",
    # 银行卡
    "bank_card": "bank_card",
    "bankcard": "bank_card",
    "card_no": "bank_card",
    "card_number": "bank_card",
    "account_no": "bank_card",
    "银行卡": "bank_card",
    "银行卡号": "bank_card",
    # 姓名
    "name": "name",
    "username": "name",
    "full_name": "name",
    "real_name": "name",
    "姓名": "name",
    "真实姓名": "name",
    # 地址
    "address": "address",
    "addr": "address",
    "location": "address",
    "home_address": "address",
    "地址": "address",
    "住址": "address",
    # IP
    "ip": "ip",
    "ip_address": "ip",
    "client_ip": "ip",
    "source_ip": "ip",
    "remote_ip": "ip",
}


# ===========================================================================
# 批量脱敏函数
# ===========================================================================

def mask_data(
    data: Any,
    rules: Optional[Dict[str, str]] = None,
    auto_detect: bool = False,
) -> Any:
    """对数据进行脱敏处理

    Args:
        data: 待脱敏的数据（支持 dict/list/str）
        rules: 字段名 -> 脱敏类型 的规则映射
        auto_detect: 是否自动检测字段名进行脱敏

    Returns:
        脱敏后的数据
    """
    if data is None:
        return None

    if rules is None and not auto_detect:
        return data

    # 字符串类型：直接按规则处理
    if isinstance(data, str):
        return data

    # 字典类型
    if isinstance(data, dict):
        result = data.copy()
        for key in result:
            mask_type = None
            if rules and key in rules:
                mask_type = rules[key]
            elif auto_detect:
                # 自动检测字段名
                key_lower = key.lower()
                if key_lower in FIELD_NAME_TO_MASK_TYPE:
                    mask_type = FIELD_NAME_TO_MASK_TYPE[key_lower]

            if mask_type and isinstance(result[key], (str, int, float)):
                mask_func = MASK_FUNCTIONS.get(mask_type)
                if mask_func:
                    result[key] = mask_func(str(result[key]))

            # 递归处理嵌套字典/列表
            elif isinstance(result[key], (dict, list)):
                result[key] = mask_data(result[key], rules=rules, auto_detect=auto_detect)

        return result

    # 列表类型
    if isinstance(data, list):
        return [mask_data(item, rules=rules, auto_detect=auto_detect) for item in data]

    return data


def auto_mask(data: Any) -> Any:
    """自动脱敏：根据字段名自动匹配脱敏规则

    Args:
        data: 待脱敏的数据

    Returns:
        脱敏后的数据
    """
    return mask_data(data, auto_detect=True)


def mask_log_data(data: Any) -> Any:
    """日志自动脱敏

    对日志数据中常见的敏感字段进行脱敏。

    Args:
        data: 日志数据

    Returns:
        脱敏后的日志数据
    """
    # 日志中常见的敏感字段
    log_sensitive_fields = {
        "password": "password",
        "passwd": "password",
        "pwd": "password",
        "old_password": "password",
        "new_password": "password",
        "token": "hash",
        "access_token": "hash",
        "refresh_token": "hash",
        "api_key": "hash",
        "secret": "hash",
        "secret_key": "hash",
        "private_key": "hash",
    }

    if isinstance(data, dict):
        result = data.copy()
        for key in result:
            key_lower = key.lower()
            if key_lower in log_sensitive_fields:
                mask_type = log_sensitive_fields[key_lower]
                if mask_type == "password":
                    result[key] = "******"
                elif mask_type == "hash":
                    if isinstance(result[key], str) and len(result[key]) > 10:
                        result[key] = result[key][:6] + "****" + result[key][-4:]
                    else:
                        result[key] = "***"
            elif isinstance(result[key], (dict, list)):
                result[key] = mask_log_data(result[key])
        return result

    if isinstance(data, list):
        return [mask_log_data(item) for item in data]

    return data


# ===========================================================================
# 脱敏规则列表
# ===========================================================================

def get_all_mask_rules() -> List[Dict[str, Any]]:
    """获取所有脱敏规则列表

    Returns:
        脱敏规则列表
    """
    return [
        {
            "id": "phone",
            "name": "手机号脱敏",
            "description": "中间4位替换为****，保留前3位和后4位",
            "example": "138****5678",
            "category": "个人信息",
            "reversible": False,
        },
        {
            "id": "email",
            "name": "邮箱脱敏",
            "description": "用户名只显示首尾字符，中间用***代替",
            "example": "a***r@example.com",
            "category": "个人信息",
            "reversible": False,
        },
        {
            "id": "id_card",
            "name": "身份证号脱敏",
            "description": "只显示前3位和后4位，中间用*代替",
            "example": "110***********1234",
            "category": "个人信息",
            "reversible": False,
        },
        {
            "id": "bank_card",
            "name": "银行卡号脱敏",
            "description": "只显示前4位和后4位，中间用 **** 分组显示",
            "example": "6222 **** **** 1234",
            "category": "财务信息",
            "reversible": False,
        },
        {
            "id": "name",
            "name": "姓名脱敏",
            "description": "只显示姓氏，名字用*代替",
            "example": "张*",
            "category": "个人信息",
            "reversible": False,
        },
        {
            "id": "address",
            "name": "地址脱敏",
            "description": "保留前6个字符，其余用***代替",
            "example": "北京市海淀区***",
            "category": "个人信息",
            "reversible": False,
        },
        {
            "id": "ip",
            "name": "IP地址脱敏",
            "description": "最后两段替换为***",
            "example": "192.168.***.***",
            "category": "网络标识",
            "reversible": False,
        },
        {
            "id": "position",
            "name": "位置脱敏",
            "description": "自定义前缀/后缀保留长度，中间用掩码字符填充",
            "example": "前3****后2",
            "category": "自定义",
            "reversible": False,
        },
        {
            "id": "regex",
            "name": "正则脱敏",
            "description": "使用正则表达式匹配并替换敏感内容",
            "example": "自定义",
            "category": "自定义",
            "reversible": False,
        },
        {
            "id": "hash",
            "name": "哈希脱敏",
            "description": "使用哈希算法进行不可逆脱敏，支持加盐",
            "example": "e10adc3949ba59abbe56e057f20f883e",
            "category": "加密脱敏",
            "reversible": False,
        },
        {
            "id": "encryption",
            "name": "加密脱敏",
            "description": "使用密钥进行可逆加密脱敏",
            "example": "ENC:xxxxxx...",
            "category": "加密脱敏",
            "reversible": True,
        },
    ]


# ===========================================================================
# 直接运行测试
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== 常见数据类型脱敏测试 ===")

    test_cases = [
        ("phone", "13812345678"),
        ("email", "user@example.com"),
        ("id_card", "110101199001011234"),
        ("bank_card", "62220212345678901234"),
        ("name", "张三"),
        ("name", "欧阳锋"),
        ("address", "北京市海淀区中关村大街1号"),
        ("ip", "192.168.1.100"),
    ]

    for mask_type, value in test_cases:
        func = MASK_FUNCTIONS.get(mask_type)
        if func:
            print(f"  {mask_type}: {value} -> {func(value)}")

    print("\n=== 自定义脱敏测试 ===")
    print(f"  位置脱敏(前3后2): {mask_by_position('1234567890', 3, 2)}")
    print(f"  哈希脱敏(sha256): {mask_with_hash('password123', 'sha256')[:20]}...")
    print(f"  加密脱敏: {mask_with_encryption('secret_data', 'mykey')}")

    print("\n=== 自动脱敏测试 ===")
    test_data = {
        "username": "张三",
        "phone": "13812345678",
        "email": "zhangsan@example.com",
        "id_card": "110101199001011234",
        "age": 25,
        "address": "北京市海淀区中关村大街1号",
    }
    masked = auto_mask(test_data)
    print(f"  原始: {test_data}")
    print(f"  脱敏: {masked}")
