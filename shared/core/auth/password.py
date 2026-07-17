"""
统一认证体系 - 密码哈希与验证模块

提供安全的密码哈希和验证功能，基于 bcrypt 算法。
优先使用 bcrypt 库直接实现，兼容 passlib 旧版。

用法：
    from shared.core.auth.password import hash_password, verify_password

    hashed = hash_password("my_password")
    if verify_password("my_password", hashed):
        print("验证通过")
"""

import os
from typing import Optional

# ===========================================================================
# 后端检测：优先使用 bcrypt，其次 passlib，最后回退到 hashlib (仅开发用)
# ===========================================================================

_backend = None  # "bcrypt" | "passlib" | "fallback" | None
_bcrypt = None
_pwd_context = None


def _detect_backend():
    """检测可用的密码哈希后端"""
    global _backend, _bcrypt, _pwd_context

    # 1. 优先使用原生 bcrypt 库
    try:
        import bcrypt as _bcrypt_lib
        _bcrypt = _bcrypt_lib
        # 测试一下基本功能
        test_hash = _bcrypt.hashpw(b"test", _bcrypt.gensalt(rounds=4))
        if _bcrypt.checkpw(b"test", test_hash):
            _backend = "bcrypt"
            return
    except Exception:
        _bcrypt = None

    # 2. 回退到 passlib
    try:
        from passlib.context import CryptContext
        _ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        # 测试一下
        test_h = _ctx.hash("test")
        if _ctx.verify("test", test_h):
            _pwd_context = _ctx
            _backend = "passlib"
            return
    except Exception:
        _pwd_context = None

    # 3. 开发模式回退（仅在非生产环境使用）
    if os.environ.get("YUNXI_DEV_MODE") == "1":
        _backend = "fallback"
        return

    _backend = "unavailable"


# 初始化后端
_detect_backend()


def is_bcrypt_available() -> bool:
    """检查 bcrypt 是否可用

    Returns:
        True 表示 bcrypt (或 passlib+bcrypt) 已安装可用
    """
    return _backend in ("bcrypt", "passlib")


def hash_password(password: str) -> str:
    """哈希密码

    使用 bcrypt 算法对密码进行慢哈希，存储时仅保存哈希值，
    不保存明文密码。

    Args:
        password: 明文密码

    Returns:
        bcrypt 哈希后的密码字符串

    Raises:
        RuntimeError: 当 bcrypt 不可用时抛出
    """
    if not password:
        raise ValueError("密码不能为空")

    if _backend == "bcrypt":
        # bcrypt 限制 72 字节，超长自动截断前提示
        password_bytes = password.encode("utf-8")
        if len(password_bytes) > 72:
            password_bytes = password_bytes[:72]
        salt = _bcrypt.gensalt()
        return _bcrypt.hashpw(password_bytes, salt).decode("utf-8")

    elif _backend == "passlib":
        return _pwd_context.hash(password)

    elif _backend == "fallback":
        # 开发模式下的安全回退（使用 SHA256 + salt，仅用于开发）
        import hashlib
        import base64
        salt = os.urandom(16).hex()
        digest = hashlib.sha256((salt + password).encode()).hexdigest()
        return f"$fallback${salt}${digest}"

    else:
        raise RuntimeError(
            "bcrypt 不可用，请先安装 bcrypt 库: "
            "pip install bcrypt"
        )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码

    安全地比较明文密码和哈希密码，使用恒定时间比较
    防止时序攻击。

    Args:
        plain_password: 明文密码
        hashed_password: 哈希后的密码

    Returns:
        True 表示密码匹配，False 表示不匹配
    """
    if not plain_password or not hashed_password:
        return False

    try:
        if _backend == "bcrypt":
            password_bytes = plain_password.encode("utf-8")
            if len(password_bytes) > 72:
                password_bytes = password_bytes[:72]
            return _bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))

        elif _backend == "passlib":
            return _pwd_context.verify(plain_password, hashed_password)

        elif _backend == "fallback" and hashed_password.startswith("$fallback$"):
            import hashlib
            parts = hashed_password.split("$")
            if len(parts) != 4:
                return False
            salt = parts[2]
            expected = parts[3]
            actual = hashlib.sha256((salt + plain_password).encode()).hexdigest()
            # 恒定时间比较
            return _constant_time_compare(actual, expected)

        else:
            # 尝试解析哈希格式，兼容不同后端生成的哈希
            if hashed_password.startswith("$2"):
                # bcrypt 格式哈希，尝试用 bcrypt 验证
                if _bcrypt is not None:
                    password_bytes = plain_password.encode("utf-8")
                    if len(password_bytes) > 72:
                        password_bytes = password_bytes[:72]
                    return _bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))

            return False

    except Exception:
        return False


def needs_update(hashed_password: str) -> bool:
    """检查哈希密码是否需要升级

    当底层哈希方案更新时，可以用此函数检测旧的哈希值
    是否需要重新哈希。

    Args:
        hashed_password: 哈希后的密码

    Returns:
        True 表示需要升级哈希
    """
    if not hashed_password:
        return False

    try:
        if _backend == "passlib":
            return _pwd_context.needs_update(hashed_password)

        elif _backend == "bcrypt":
            # 检查 bcrypt 版本和 cost factor
            if not hashed_password.startswith("$2"):
                return True
            # 推荐 cost factor 至少 12
            parts = hashed_password.split("$")
            if len(parts) >= 3:
                try:
                    cost = int(parts[2])
                    return cost < 12
                except ValueError:
                    return True
            return False

        elif _backend == "fallback":
            return True  # fallback 哈希总是需要升级

        return False

    except Exception:
        return False


def _constant_time_compare(a: str, b: str) -> bool:
    """恒定时间字符串比较，防止时序攻击"""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0
