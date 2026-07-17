"""
云汐共享安全模块 - 输入验证与输出编码

提供统一的安全输入验证和输出编码工具，防止：
- XSS（跨站脚本攻击）
- SQL注入（参数化查询在 data_layer 中实现）
- 命令注入
- 路径遍历
- 输入验证与长度限制

使用方式：
    from shared.security import sanitize_html, validate_input, safe_filename
"""

import re
import html
import os
from typing import Optional, Dict, Any, List, Tuple, Union


# ===========================================================================
# XSS 防护 - 输出编码
# ===========================================================================

def escape_html(text: str) -> str:
    """HTML 转义（防止 XSS）.
    
    转义以下字符：& < > " ' /
    
    Args:
        text: 原始文本
    
    Returns:
        转义后的安全文本
    """
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def sanitize_html(text: str, allowed_tags: Optional[List[str]] = None) -> str:
    """净化 HTML 内容，移除危险标签和属性.
    
    简单版白名单净化：只允许指定的安全标签，移除所有 script/style/iframe 等危险标签，
    移除所有 on* 事件属性和 javascript: 协议。
    
    注意：如果有更高安全要求，建议使用 bleach 库。
    
    Args:
        text: 原始 HTML 文本
        allowed_tags: 允许的标签列表，默认为常见安全标签
    
    Returns:
        净化后的 HTML
    """
    if not text:
        return ""
    
    if allowed_tags is None:
        allowed_tags = {
            "b", "i", "u", "s", "em", "strong", "p", "br", "span",
            "ul", "ol", "li",
            "h1", "h2", "h3", "h4", "h5", "h6",
            "a", "img",
            "table", "thead", "tbody", "tr", "th", "td",
            "code", "pre", "blockquote", "hr",
        }
    else:
        allowed_tags = set(t.lower() for t in allowed_tags)
    
    # 1. 移除 script, style, iframe, frame, object, embed, video, audio 等危险标签及其内容
    dangerous_tags = [
        "script", "style", "iframe", "frame", "frameset",
        "object", "embed", "video", "audio", "canvas",
        "svg", "math", "meta", "link", "base", "form",
        "input", "button", "select", "textarea",
    ]
    result = text
    for tag in dangerous_tags:
        # 移除标签及其内容（非贪婪匹配）
        pattern = re.compile(
            rf'<{tag}[^>]*>.*?</{tag}>',
            re.IGNORECASE | re.DOTALL
        )
        result = pattern.sub('', result)
        # 移除自闭合标签
        pattern_single = re.compile(
            rf'<{tag}[^>]*/?>',
            re.IGNORECASE
        )
        result = pattern_single.sub('', result)
    
    # 2. 移除所有 on* 事件属性
    result = re.sub(
        r'\son[a-z]+\s*=\s*["\'][^"\']*["\']',
        '', result, flags=re.IGNORECASE
    )
    result = re.sub(
        r'\son[a-z]+\s*=\s*[^"\'\s>]+',
        '', result, flags=re.IGNORECASE
    )
    
    # 3. 移除 javascript: 协议
    result = re.sub(
        r'(href|src|action|data)\s*=\s*["\']\s*javascript:',
        r'\1="#"',
        result, flags=re.IGNORECASE
    )
    result = re.sub(
        r'(href|src|action|data)\s*=\s*javascript:',
        r'\1="#',
        result, flags=re.IGNORECASE
    )
    
    # 4. 移除不在白名单内的标签（保留内容）
    # 先提取所有标签
    def _replace_tag(match):
        tag_full = match.group(0)
        tag_name_match = re.match(r'<(/?)([a-zA-Z0-9]+)', tag_full)
        if tag_name_match:
            tag_name = tag_name_match.group(2).lower()
            if tag_name in allowed_tags:
                return tag_full  # 允许的标签保留
        # 不在白名单，移除标签但保留内容（用空字符串替换）
        return ''
    
    result = re.sub(r'<[^>]+>', _replace_tag, result)
    
    return result


# ===========================================================================
# 输入验证
# ===========================================================================

# 常见输入类型的正则模式
INPUT_PATTERNS = {
    "username": re.compile(r'^[a-zA-Z0-9_\-]{3,32}$'),
    "email": re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
    "url": re.compile(r'^https?://[^\s/$.?#].[^\s]*$', re.IGNORECASE),
    "ipv4": re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'),
    "uuid": re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE),
    "slug": re.compile(r'^[a-z0-9\-]{1,100}$'),
    "api_key": re.compile(r'^[a-zA-Z0-9_\-]{16,128}$'),
    "phone_cn": re.compile(r'^1[3-9]\d{9}$'),
    "hex_color": re.compile(r'^#?[0-9a-fA-F]{3,6}$'),
    "alphanumeric": re.compile(r'^[a-zA-Z0-9]+$'),
    "identifier": re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$'),
}


def validate_input(
    value: str,
    field_type: str = "text",
    min_length: int = 0,
    max_length: int = 1000,
    pattern: Optional[re.Pattern] = None,
    allowed_chars: Optional[str] = None,
    forbidden_patterns: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """验证输入是否合法.
    
    Args:
        value: 输入值
        field_type: 字段类型（对应 INPUT_PATTERNS 中的键）
        min_length: 最小长度
        max_length: 最大长度
        pattern: 自定义正则模式（覆盖 field_type）
        allowed_chars: 允许的字符（如 string.ascii_letters + string.digits）
        forbidden_patterns: 禁止的正则模式列表
    
    Returns:
        (是否通过, 错误消息)
    """
    if value is None:
        return False, "值不能为空"
    
    value_str = str(value)
    
    # 1. 长度检查
    length = len(value_str)
    if length < min_length:
        return False, f"长度不足：最少 {min_length} 字符（当前 {length}）"
    if length > max_length:
        return False, f"长度超限：最多 {max_length} 字符（当前 {length}）"
    
    # 2. 类型模式检查
    if pattern is not None:
        if not pattern.match(value_str):
            return False, f"格式不正确：不符合 {field_type} 格式"
    elif field_type in INPUT_PATTERNS:
        if not INPUT_PATTERNS[field_type].match(value_str):
            return False, f"格式不正确：不符合 {field_type} 格式"
    
    # 3. 允许字符检查
    if allowed_chars:
        for ch in value_str:
            if ch not in allowed_chars:
                return False, f"包含不允许的字符：{repr(ch)}"
    
    # 4. 禁止模式检查
    if forbidden_patterns:
        for fp in forbidden_patterns:
            if re.search(fp, value_str, re.IGNORECASE):
                return False, f"包含禁止的内容模式"
    
    return True, ""


def validate_dict(
    data: Dict[str, Any],
    rules: Dict[str, Dict[str, Any]],
) -> Tuple[bool, Dict[str, str]]:
    """批量验证字典输入.
    
    Args:
        data: 输入数据字典
        rules: 验证规则字典，key 为字段名，value 为验证参数字典
    
    Returns:
        (是否全部通过, {字段名: 错误消息})
    """
    errors = {}
    
    for field, rule in rules.items():
        value = data.get(field, "")
        required = rule.get("required", False)
        
        if required and (value is None or value == ""):
            errors[field] = "必填字段"
            continue
        
        if value is not None and value != "":
            passed, msg = validate_input(
                value,
                field_type=rule.get("type", "text"),
                min_length=rule.get("min_length", 0),
                max_length=rule.get("max_length", 1000),
                pattern=rule.get("pattern"),
                allowed_chars=rule.get("allowed_chars"),
                forbidden_patterns=rule.get("forbidden_patterns"),
            )
            if not passed:
                errors[field] = msg
    
    return len(errors) == 0, errors


# ===========================================================================
# 路径遍历防护
# ===========================================================================

def safe_filename(filename: str, max_length: int = 255) -> str:
    """生成安全的文件名（防止路径遍历）.
    
    移除路径分隔符、父目录引用、控制字符等。
    
    Args:
        filename: 原始文件名
        max_length: 最大长度
    
    Returns:
        安全的文件名
    """
    if not filename:
        return "unnamed"
    
    # 移除路径分隔符
    name = os.path.basename(filename)
    
    # 移除危险字符：控制字符、路径分隔符、空字符
    name = re.sub(r'[\x00-\x1f\x7f\\/]', '_', name)
    
    # 移除特殊的危险文件名组件
    name = name.replace('..', '_')
    
    # 移除开头的点（隐藏文件）
    name = name.lstrip('.')
    
    # 空文件名处理
    if not name:
        name = "unnamed"
    
    # 长度限制
    if len(name) > max_length:
        # 保留扩展名
        _, ext = os.path.splitext(name)
        base = name[:max_length - len(ext)]
        name = base + ext
    
    return name


def safe_join_path(base_dir: str, *paths: str) -> str:
    """安全拼接路径（防止路径遍历）.
    
    确保最终路径在 base_dir 目录内。
    
    Args:
        base_dir: 基础目录
        *paths: 要拼接的路径组件
    
    Returns:
        安全的绝对路径
    
    Raises:
        ValueError: 路径越出基础目录
    """
    base = os.path.realpath(base_dir)
    full_path = os.path.realpath(os.path.join(base, *paths))
    
    # 确保在基础目录内
    if not full_path.startswith(base + os.sep) and full_path != base:
        raise ValueError(f"Path traversal detected: {full_path} not in {base}")
    
    return full_path


# ===========================================================================
# 命令注入防护
# ===========================================================================

def safe_shell_arg(arg: str) -> str:
    """安全的 shell 参数转义（防止命令注入）.
    
    注意：优先使用 subprocess 列表形式传参，而非字符串拼接。
    此函数仅用于必要时的转义。
    
    Args:
        arg: 原始参数
    
    Returns:
        转义后的安全参数
    """
    # 只允许安全字符
    if re.match(r'^[a-zA-Z0-9_\-./=]+$', arg):
        return arg
    
    # 包含特殊字符时，使用单引号包裹并转义单引号
    escaped = arg.replace("'", "'\\''")
    return f"'{escaped}'"


# ===========================================================================
# 快速工具函数
# ===========================================================================

def truncate(text: str, max_len: int, suffix: str = "...") -> str:
    """安全截断文本.
    
    Args:
        text: 原始文本
        max_len: 最大长度
        suffix: 截断后缀
    
    Returns:
        截断后的文本
    """
    if text is None:
        return ""
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[:max_len - len(suffix)] + suffix


def strip_tags(text: str) -> str:
    """移除所有 HTML/XML 标签.
    
    Args:
        text: 原始文本
    
    Returns:
        纯文本
    """
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text)


def normalize_whitespace(text: str) -> str:
    """规范化空白字符.
    
    将连续的空白字符替换为单个空格，去除首尾空白。
    
    Args:
        text: 原始文本
    
    Returns:
        规范化后的文本
    """
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


# ===========================================================================
# 日志脱敏
# ===========================================================================

# 敏感数据模式（用于自动检测和脱敏）
_SENSITIVE_PATTERNS = [
    # JWT Token
    (r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}', '***JWT***'),
    # Bearer Token
    (r'(?i)(bearer\s+)[A-Za-z0-9._-]{16,}', r'\1***'),
    # API Key
    (r'(?i)(api[_-]?key\s*[=:]\s*)[A-Za-z0-9_\-]{16,}', r'\1***'),
    # Password
    (r'(?i)(password\s*[=:]\s*)\S+', r'\1***'),
    (r'(?i)(passwd\s*[=:]\s*)\S+', r'\1***'),
    (r'(?i)(pwd\s*[=:]\s*)\S+', r'\1***'),
    # Secret
    (r'(?i)(secret\s*[=:]\s*)[A-Za-z0-9_\-]{8,}', r'\1***'),
    (r'(?i)(token\s*[=:]\s*)[A-Za-z0-9_\-]{8,}', r'\1***'),
    # 手机号（中国）
    (r'(?<!\d)1[3-9]\d{9}(?!\d)', '1*********'),
    # 邮箱（保留首字母和域名）
    (r'([a-zA-Z])[a-zA-Z0-9._%+-]*@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', r'\1***@\2'),
    # 身份证号（18位）
    (r'(?<!\d)\d{6}\d{8}\d{4}(?!\d)', '**********'),
    # 银行卡号（16-19位）
    (r'(?<!\d)(\d{4})\d{8,11}(\d{4})(?!\d)', r'\1********\2'),
    # IP 地址（可选脱敏）
    # IPv4 保留前两段
    (r'(\d{1,3}\.\d{1,3}\.)\d{1,3}\.\d{1,3}', r'\1***.***'),
]


def mask_sensitive_data(text: str) -> str:
    """自动检测并脱敏日志中的敏感数据.
    
    支持自动检测和脱敏：
    - JWT Token
    - Bearer Token / API Key
    - Password / Secret
    - 手机号、邮箱、身份证号、银行卡号
    - IP 地址
    
    Args:
        text: 原始日志文本
    
    Returns:
        脱敏后的文本
    """
    if not text:
        return text
    
    result = str(text)
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = re.sub(pattern, replacement, result)
    
    return result


def mask_dict_sensitive(
    data: Dict[str, Any],
    sensitive_keys: Optional[List[str]] = None,
    mask_value: str = "***",
) -> Dict[str, Any]:
    """脱敏字典中的敏感字段.
    
    Args:
        data: 原始字典
        sensitive_keys: 敏感字段名列表（不区分大小写），默认包含常见敏感字段
        mask_value: 脱敏后的值
    
    Returns:
        脱敏后的字典
    """
    if not data:
        return data
    
    if sensitive_keys is None:
        sensitive_keys = [
            "password", "passwd", "pwd", "secret", "token",
            "api_key", "apikey", "access_key", "access_token",
            "refresh_token", "private_key", "public_key",
            "authorization", "auth", "cookie", "session",
            "credit_card", "card_number", "cvv", "cvc",
            "ssn", "id_card", "id_number",
            "phone", "mobile", "email",
            "address", "location",
        ]
    
    sensitive_lower = {k.lower() for k in sensitive_keys}
    
    result = {}
    for key, value in data.items():
        if key.lower() in sensitive_lower:
            result[key] = mask_value
        elif isinstance(value, dict):
            result[key] = mask_dict_sensitive(value, sensitive_keys, mask_value)
        elif isinstance(value, str) and key.lower() not in {"name", "title", "content", "message", "description"}:
            # 字符串值也进行模式脱敏
            result[key] = mask_sensitive_data(value)
        else:
            result[key] = value
    
    return result


def mask_email(email: str, keep_chars: int = 1) -> str:
    """脱敏邮箱地址.
    
    Args:
        email: 邮箱地址
        keep_chars: 保留的首字母数量
    
    Returns:
        脱敏后的邮箱
    """
    if not email or "@" not in email:
        return email
    
    username, domain = email.split("@", 1)
    if len(username) <= keep_chars:
        return f"{username[0]}***@{domain}"
    
    return f"{username[:keep_chars]}***@{domain}"


def mask_phone(phone: str) -> str:
    """脱敏手机号.
    
    Args:
        phone: 手机号
    
    Returns:
        脱敏后的手机号（保留前3后4位）
    """
    if not phone:
        return phone
    
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 11:
        return f"{digits[:3]}****{digits[-4:]}"
    
    # 其他长度：保留前后各2位
    if len(digits) > 4:
        return f"{digits[:2]}***{digits[-2:]}"
    
    return "***"


def mask_string(s: str, keep_start: int = 2, keep_end: int = 2, mask_char: str = "*") -> str:
    """通用字符串脱敏.
    
    Args:
        s: 原始字符串
        keep_start: 保留开头字符数
        keep_end: 保留结尾字符数
        mask_char: 脱敏字符
    
    Returns:
        脱敏后的字符串
    """
    if not s:
        return s
    
    length = len(s)
    if length <= keep_start + keep_end:
        return mask_char * length
    
    return s[:keep_start] + mask_char * (length - keep_start - keep_end) + s[-keep_end:]

