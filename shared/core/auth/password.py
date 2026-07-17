"""
统一认证体系 - 密码哈希与验证模块

提供安全的密码哈希和验证功能，基于 bcrypt 算法。
优先使用 bcrypt 库直接实现，兼容 passlib 旧版。

SEC-007 安全修复：
- 移除了 YUNXI_DEV_MODE 自动降级到 SHA256 的不安全模式
- bcrypt 不可用时默认直接抛出异常
- 仅在明确设置 YUNXI_INSECURE_PASSWORD=1 时才启用 SHA256 fallback
  （且启动时打印醒目红色警告）

用法：
    from shared.core.auth.password import hash_password, verify_password

    hashed = hash_password("my_password")
    if verify_password("my_password", hashed):
        print("验证通过")
"""

import os
import sys
from typing import Optional

# ===========================================================================
# 后端检测：优先使用 bcrypt，其次 passlib，最后仅在显式授权时回退到 hashlib
# ===========================================================================

_backend = None  # "bcrypt" | "passlib" | "fallback" | "unavailable" | None
_bcrypt = None
_pwd_context = None
_fallback_warning_shown = False


def _detect_backend():
    """检测可用的密码哈希后端

    SEC-007 安全修复：
    - 默认情况下，bcrypt 不可用时直接标记为 unavailable，调用时抛出异常
    - 仅在明确设置 YUNXI_INSECURE_PASSWORD=1 时才启用 fallback 模式
    - fallback 模式会打印醒目红色警告
    """
    global _backend, _bcrypt, _pwd_context, _fallback_warning_shown

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

    # 3. SEC-007: 仅在显式设置 YUNXI_INSECURE_PASSWORD=1 时启用 fallback
    #    这是一个明确的"我知道我在做什么"的开关
    if os.environ.get("YUNXI_INSECURE_PASSWORD") == "1":
        _backend = "fallback"
        _print_insecure_warning()
        return

    # 4. 默认：bcrypt 不可用，标记为 unavailable
    _backend = "unavailable"


def _print_insecure_warning():
    """打印醒目红色警告（fallback 模式下只打印一次）"""
    global _fallback_warning_shown
    if _fallback_warning_shown:
        return
    _fallback_warning_shown = True

    warning_msg = """
================================================================================
[SEC-007] 严重安全警告：密码哈希使用了不安全的 fallback 模式
================================================================================
  当前使用 SHA256 + salt 进行密码哈希，这是不安全的！
  SHA256 是快速哈希，无法抵御暴力破解和彩虹表攻击。

  触发原因：YUNXI_INSECURE_PASSWORD=1 环境变量被设置

  强烈建议立即安装 bcrypt 库：
      pip install bcrypt
  或：
      pip install passlib[bcrypt]

  此模式仅用于无法安装 bcrypt 的极端测试场景，
  绝对禁止在生产环境使用！
================================================================================"""

    # 尝试使用 ANSI 红色输出，如果不支持则普通输出
    try:
        RED = "\033[91m"
        BOLD = "\033[1m"
        RESET = "\033[0m"
        print(RED + BOLD + warning_msg + RESET, file=sys.stderr)
    except Exception:
        print(warning_msg, file=sys.stderr)


# 初始化后端
_detect_backend()


def is_bcrypt_available() -> bool:
    """检查 bcrypt 是否可用

    Returns:
        True 表示 bcrypt (或 passlib+bcrypt) 已安装可用
    """
    return _backend in ("bcrypt", "passlib")


def is_insecure_fallback_mode() -> bool:
    """检查是否处于不安全的 fallback 模式（SEC-007）

    Returns:
        True 表示当前使用 SHA256 fallback，不安全
        False 表示使用 bcrypt 或 bcrypt 不可用（会抛异常）
    """
    return _backend == "fallback"


def hash_password(password: str) -> str:
    """哈希密码

    使用 bcrypt 算法对密码进行慢哈希，存储时仅保存哈希值，
    不保存明文密码。

    SEC-007 安全修复：
    - bcrypt 不可用时默认抛出 RuntimeError
    - 仅在 YUNXI_INSECURE_PASSWORD=1 时才回退到 SHA256（不安全）

    Args:
        password: 明文密码

    Returns:
        bcrypt 哈希后的密码字符串

    Raises:
        RuntimeError: 当 bcrypt 不可用且未启用不安全 fallback 时抛出
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
        # SEC-007: 不安全的 fallback 模式，仅在 YUNXI_INSECURE_PASSWORD=1 时启用
        import hashlib
        salt = os.urandom(16).hex()
        digest = hashlib.sha256((salt + password).encode()).hexdigest()
        return f"$fallback${salt}${digest}"

    else:
        raise RuntimeError(
            "[SEC-007] bcrypt 不可用，密码哈希功能无法正常工作。\n"
            "请先安装 bcrypt 库:\n"
            "    pip install bcrypt\n"
            "或:\n"
            "    pip install passlib[bcrypt]\n\n"
            "如果您确实需要在没有 bcrypt 的情况下运行（极不推荐），\n"
            "可以设置环境变量 YUNXI_INSECURE_PASSWORD=1 来启用不安全的 fallback 模式。\n"
            "注意：fallback 模式使用 SHA256，无法抵御暴力破解，绝对禁止用于生产环境！"
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
