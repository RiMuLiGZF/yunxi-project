"""
M8 管理工作台 - 配置管理（P2-18: 配置去重）

全局通用配置从 shared.config 读取，避免与 YunxiConfig 重复定义。
M8 特有配置（数据库、JWT 详细参数等）保留在此处。
"""

import sys
import os
import re
import secrets
import string
from pathlib import Path

# 将项目根目录加入 path，以便导入 shared 模块
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional

# 从 shared 读取全局配置作为默认值基准
try:
    from shared.core.config import get_config
    _global_config = get_config()
except Exception:
    # shared 不可用时使用回退默认值，保持 M8 独立可运行
    _global_config = None

# 尝试导入统一的密钥安全校验工具（SC-001）
try:
    from shared.core.config import validate_secret_key, is_default_or_weak_key
    _HAS_SECURITY_TOOLS = True
except ImportError:
    _HAS_SECURITY_TOOLS = False

def _global_get(attr: str, default=None):
    """从全局配置读取属性，不可用时返回默认值"""
    if _global_config is None:
        return default
    return getattr(_global_config, attr, default)

# backend 目录的绝对路径
backend_dir = Path(__file__).parent
# data 目录的绝对路径
data_dir = backend_dir / "data"
# 确保 data 目录存在
data_dir.mkdir(parents=True, exist_ok=True)
# 数据库文件的绝对路径
db_path = data_dir / "m8.db"


# ===========================================================================
# 密码安全工具（SC-004 P1级安全加固）
# ===========================================================================

# 默认弱密码列表（用于检测是否使用了不安全的默认密码）
WEAK_DEFAULT_PASSWORDS = {
    "admin123456",
    "password",
    "123456",
    "12345678",
    "123456789",
    "admin",
    "changeme",
    "default",
    "qwerty",
    "abc123",
    "password123",
    "admin@123",
    "yunxi123",
    "yunxi2026",
}

# 密码强度要求
PASSWORD_MIN_LENGTH = 12


def validate_password_strength(password: str) -> tuple[bool, str]:
    """验证密码强度

    密码强度要求：
    - 至少 12 位
    - 包含大写字母
    - 包含小写字母
    - 包含数字
    - 包含特殊字符

    Args:
        password: 待验证的密码（明文）

    Returns:
        tuple[bool, str]: (是否通过, 错误信息)
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, f"密码长度不足，至少需要 {PASSWORD_MIN_LENGTH} 位"

    if not re.search(r'[A-Z]', password):
        return False, "密码必须包含大写字母"

    if not re.search(r'[a-z]', password):
        return False, "密码必须包含小写字母"

    if not re.search(r'[0-9]', password):
        return False, "密码必须包含数字"

    if not re.search(r'[!@#$%^&*()\-_=+{}\[\]\\|;:\'",.<>/?`~]', password):
        return False, "密码必须包含特殊字符（如 !@#$%^&* 等）"

    return True, ""


def generate_strong_password(length: int = 16) -> str:
    """生成符合强度要求的随机强密码

    生成的密码保证包含：
    - 至少一个大写字母
    - 至少一个小写字母
    - 至少一个数字
    - 至少一个特殊字符

    Args:
        length: 密码长度，默认 16 位

    Returns:
        str: 生成的随机强密码
    """
    if length < PASSWORD_MIN_LENGTH:
        length = PASSWORD_MIN_LENGTH

    # 确保至少包含各类字符
    uppercase = secrets.choice(string.ascii_uppercase)
    lowercase = secrets.choice(string.ascii_lowercase)
    digit = secrets.choice(string.digits)
    special = secrets.choice("!@#$%^&*()-_=+")

    # 剩余字符从所有可打印字符中随机选择
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    remaining = ''.join(secrets.choice(alphabet) for _ in range(length - 4))

    # 组合并打乱顺序
    all_chars = list(uppercase + lowercase + digit + special + remaining)
    secrets.SystemRandom().shuffle(all_chars)

    return ''.join(all_chars)


def is_weak_default_password(password: str) -> bool:
    """检查密码是否为弱默认密码

    Args:
        password: 待检查的密码（明文）

    Returns:
        bool: 是否为弱默认密码
    """
    if not password:
        return True
    return password.lower() in {p.lower() for p in WEAK_DEFAULT_PASSWORDS}


class Settings(BaseSettings):
    """M8 后端配置

    全局通用配置从 shared.config 同步，避免重复定义。
    M8 特有配置保留在此类中。
    """

    model_config = SettingsConfigDict(
        env_file=str(project_root / "config" / "yunxi.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== 服务配置（与全局配置同步） =====
    app_name: str = "云汐管理工作台 M8"
    version: str = _global_get("version", "1.2.0")
    host: str = _global_get("module_hosts", {}).get("m8", "0.0.0.0")
    port: int = _global_get("module_ports", {}).get("m8", 8008)
    env: str = _global_get("env", "development")

    # ===== 安全配置（与全局配置同步，M8 扩展） =====
    admin_username: str = _global_get("m8_admin_username", "admin")
    admin_password: str = _global_get("m8_admin_password", "")
    jwt_secret: str = _global_get("m8_jwt_secret", "")
    jwt_algorithm: str = "HS256"
    # SEC-011: 开发环境 24 小时（方便调试），生产环境 2 小时
    access_token_expire_minutes: int = 1440 if env == "development" else 120
    refresh_token_expire_days: int = 7  # SEC-011: Refresh Token 7 天过期
    m8_admin_token: str = _global_get("module_tokens", {}).get("m8", "")

    # ===== CORS（与全局配置同步，开发环境默认 localhost 常见端口） =====
    cors_origins: str = _global_get("cors_origins", "http://localhost:3000,http://localhost:5173,http://localhost:8080,http://localhost:8000,http://127.0.0.1:3000,http://127.0.0.1:5173,http://127.0.0.1:8080,http://127.0.0.1:8000")

    # ===== 数据库（M8 特有） =====
    database_url: str = f"sqlite:///{db_path}"

    # ===== 日志（与全局配置同步） =====
    log_level: str = _global_get("log_level", "info")

    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return self.env.lower() in ("production", "prod", "release")

    def validate_security(self) -> list[str]:
        """验证安全配置，返回警告/错误信息列表

        检查项：
        1. 管理员密码强度（SC-004）
        2. 默认弱密码检测（SC-004）
        3. JWT 密钥安全性（SC-001）
        4. Admin Token 安全性（SC-001）
        5. 占位符密钥检测（CHANGEME_ 前缀）（SC-001）

        Returns:
            list[str]: 警告信息列表（空列表表示无问题）
        """
        warnings = []

        # 1. 检查管理员密码
        pwd = self.admin_password
        if not pwd:
            if self.is_production:
                warnings.append(
                    "[SC-004 P1] [ERROR] 生产环境必须配置 M8_ADMIN_PASSWORD！"
                )
            else:
                warnings.append(
                    "[SC-004 P1] [WARN] 开发环境未配置 M8_ADMIN_PASSWORD，将使用自动生成的随机密码"
                )
        elif is_weak_default_password(pwd):
            if self.is_production:
                warnings.append(
                    "[SC-004 P1] [ERROR] 生产环境禁止使用默认弱密码 admin123456！\n"
                    "       请修改 M8_ADMIN_PASSWORD 为符合强度要求的强密码：\n"
                    f"       - 至少 {PASSWORD_MIN_LENGTH} 位\n"
                    "       - 包含大写字母、小写字母、数字和特殊字符\n"
                    "       建议使用: python -c \"import secrets; print(secrets.token_urlsafe(16))\" 生成"
                )
            else:
                warnings.append(
                    "[SC-004 P1] [WARN] 当前使用默认弱密码 admin123456，仅适用于开发环境\n"
                    "       生产环境请务必修改为强密码"
                )
        else:
            # 密码已配置，检查强度
            strong, msg = validate_password_strength(pwd)
            if not strong:
                if self.is_production:
                    warnings.append(
                        f"[SC-004 P1] [ERROR] 生产环境管理员密码强度不足：{msg}"
                    )
                else:
                    warnings.append(
                        f"[SC-004 P1] [WARN] 管理员密码强度不足：{msg}"
                    )

        # 2. 检查 JWT 密钥（SC-001 安全加固）
        if _HAS_SECURITY_TOOLS:
            # 使用统一的密钥校验工具
            jwt_valid, jwt_msg = validate_secret_key(self.jwt_secret, "M8_JWT_SECRET")
            if not jwt_valid:
                if self.is_production:
                    warnings.append(
                        f"[SC-001 P0] [ERROR] 生产环境 JWT 密钥不安全：{jwt_msg}"
                    )
                else:
                    warnings.append(
                        f"[SC-001 P0] [WARN] JWT 密钥安全警告：{jwt_msg}"
                    )
        else:
            # 回退：简单检查
            if not self.jwt_secret or self.jwt_secret.startswith("yunxi-") or self.jwt_secret.startswith("CHANGEME_"):
                if self.is_production:
                    warnings.append(
                        "[SC-001 P0] [ERROR] 生产环境必须配置安全的 M8_JWT_SECRET！"
                    )
                else:
                    warnings.append(
                        "[SC-001 P0] [WARN] 当前使用默认 JWT 密钥，仅适用于开发环境"
                    )

        # 3. 检查 Admin Token（SC-001 安全加固）
        if _HAS_SECURITY_TOOLS:
            token_valid, token_msg = validate_secret_key(self.m8_admin_token, "M8_ADMIN_TOKEN")
            if not token_valid:
                if self.is_production:
                    warnings.append(
                        f"[SC-001 P0] [ERROR] 生产环境 Admin Token 不安全：{token_msg}"
                    )
                else:
                    warnings.append(
                        f"[SC-001 P0] [WARN] Admin Token 安全警告：{token_msg}"
                    )
        else:
            if not self.m8_admin_token or self.m8_admin_token.startswith("yunxi-") or self.m8_admin_token.startswith("CHANGEME_"):
                if self.is_production:
                    warnings.append(
                        "[SC-001 P0] [ERROR] 生产环境必须配置安全的 M8_ADMIN_TOKEN！"
                    )
                else:
                    warnings.append(
                        "[SC-001 P0] [WARN] 当前使用默认 Admin Token，仅适用于开发环境"
                    )

        return warnings


settings = Settings()


# 系统版本号（统一从 shared.version 导入）
def _load_system_version() -> str:
    """从 shared.version 导入系统版本号，导入失败则回退到默认值"""
    try:
        # 查找项目根目录并加入 sys.path
        from pathlib import Path
        current = Path(__file__).resolve().parent
        for _ in range(10):
            if (current / "shared" / "version.py").exists():
                import sys
                if str(current) not in sys.path:
                    sys.path.insert(0, str(current))
                break
            current = current.parent
        from shared.core.version import SYSTEM_VERSION
        return SYSTEM_VERSION
    except Exception:
        return "v1.0.0"


SYSTEM_VERSION = _load_system_version()
