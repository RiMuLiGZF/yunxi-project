"""
云汐 M12 安全盾 - 配置管理模块
使用 pydantic-settings 管理系统全局配置，包括服务配置、安全策略、
数据库路径、JWT 密钥、速率限制等参数。
"""

import os
import secrets
import sys
import warnings
from pathlib import Path
from typing import List, Optional

import structlog
from pydantic_settings import BaseSettings

logger = structlog.get_logger(__name__)

# 默认 JWT 密钥（用于检测用户是否使用了默认值）
DEFAULT_JWT_SECRET = "yunxi-m12-security-shield-secret-key-2026"


def generate_secret_key(length: int = 64) -> str:
    """生成安全的随机密钥

    使用 secrets 模块生成加密安全的随机字符串，可作为 JWT 密钥、
    API 密钥或其他需要高熵值的密钥使用。

    Args:
        length: 密钥长度（字节数），默认 64 字节

    Returns:
        URL-safe Base64 编码的随机密钥字符串
    """
    return secrets.token_urlsafe(length)


def _get_base_dir() -> Path:
    """获取项目基础目录（兼容直接运行和作为模块导入）

    Returns:
        项目根目录 Path 对象
    """
    if "__file__" in globals():
        # 从当前文件向上回溯两级到项目根
        return Path(__file__).resolve().parent.parent
    return Path.cwd()


class Settings(BaseSettings):
    """
    M12 安全盾系统配置类

    所有配置项均可通过环境变量覆盖，环境变量前缀为 M12_
    例如：M12_PORT=9000 将覆盖 port 默认值
    """

    # ===== 基础配置 =====
    # 模块名称
    module_name: str = "m12-security-shield"
    # 模块中文名
    module_name_cn: str = "安全盾"
    # 版本号
    version: str = "1.0.0"
    # 服务主机
    host: str = "0.0.0.0"
    # 服务端口
    port: int = 8012
    # 调试模式（生产环境必须关闭）
    debug: bool = False
    # 日志级别
    log_level: str = "info"
    # 运行环境
    env: str = "development"

    # ===== 路径配置 =====
    # 项目根目录
    base_dir: Path = Path(_get_base_dir())
    # 数据目录
    data_dir: Path = Path(_get_base_dir()) / "data"
    # 数据库文件路径
    db_path: Path = Path(_get_base_dir()) / "data" / "m12.db"

    # ===== CORS 配置 =====
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # ===== WAF 配置 =====
    # WAF 防护总开关
    waf_enabled: bool = True
    # SQL 注入检测开关
    waf_sql_injection: bool = True
    # XSS 检测开关
    waf_xss: bool = True
    # CSRF 检测开关
    waf_csrf: bool = True
    # 命令注入检测开关
    waf_command_injection: bool = True
    # 路径遍历检测开关
    waf_path_traversal: bool = True
    # WAF 日志开关
    waf_logging: bool = True

    # ===== 速率限制配置 =====
    # 速率限制总开关
    rate_limit_enabled: bool = True
    # 默认每分钟请求数
    default_rate_per_minute: int = 60
    # 令牌桶容量（突发请求数）
    rate_limit_burst: int = 30
    # 速率限制时间窗口（秒）
    rate_limit_window_seconds: int = 60

    # ===== JWT 配置 =====
    # JWT 签名密钥（必须设置，默认空字符串强制要求环境变量）
    jwt_secret: str = ""
    # JWT 算法
    jwt_algorithm: str = "HS256"
    # Token 过期时间（分钟）
    jwt_expire_minutes: int = 1440
    # 刷新 Token 过期时间（天）
    jwt_refresh_expire_days: int = 7
    # 是否强制要求安全密钥（安全默认值：True）
    # 开启后，如果使用默认密钥或空密钥，启动时将抛出错误并退出
    require_secure_secret: bool = True

    # ===== API 密钥配置 =====
    # 默认 API Key 长度
    api_key_length: int = 32
    # API Key 前缀
    api_key_prefix: str = "m12-"

    # ===== 审计配置 =====
    # 审计日志保留天数
    audit_retention_days: int = 90
    # 是否记录所有请求
    audit_log_all_requests: bool = False

    # ===== IP 封禁配置 =====
    # 失败多少次自动封禁
    auto_ban_failures: int = 10
    # 自动封禁时长（分钟）
    auto_ban_minutes: int = 60

    # ===== 管理员账户配置 =====
    # 管理员用户名（用于登录认证）
    admin_username: str = ""
    # 管理员密码哈希（bcrypt 格式，可通过 hash_password() 生成）
    admin_password_hash: str = ""

    class Config:
        """pydantic-settings 配置"""
        env_prefix = "M12_"
        env_file = ".env"
        case_sensitive = False

    @property
    def database_url(self) -> str:
        """获取 SQLAlchemy 数据库连接 URL

        Returns:
            SQLite 连接字符串
        """
        return f"sqlite:///{self.db_path.as_posix()}"

    def ensure_dirs(self) -> None:
        """确保必要的目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_default_secret(self) -> bool:
        """检查是否使用了默认的 JWT 密钥

        Returns:
            True 表示使用的是默认密钥或空密钥，存在安全风险
        """
        return (
            not self.jwt_secret
            or self.jwt_secret == DEFAULT_JWT_SECRET
            or len(self.jwt_secret) < 16
        )

    def validate_secret_security(self) -> None:
        """验证 JWT 密钥安全性

        根据环境和 require_secure_secret 配置执行密钥安全检查：
        - 如果 require_secure_secret=True 且使用默认密钥，记录严重错误后抛出 ValueError
        - 如果在生产环境使用默认密钥，发出警告
        - 如果在开发环境使用默认密钥，仅提示

        Raises:
            ValueError: 当 require_secure_secret=True 且密钥不安全时
        """
        if not self.is_default_secret:
            return

        secret_warning = (
            "【安全警告】当前 JWT 密钥不安全，存在严重安全风险！"
            "请通过环境变量 M12_JWT_SECRET 设置自定义密钥，"
            "或在 Python 中调用 generate_secret_key() 生成安全密钥："
            "    from backend.config import generate_secret_key; print(generate_secret_key())"
        )

        if self.require_secure_secret:
            logger.critical(
                "m12.security.jwt_secret_unsafe",
                message=secret_warning,
                env=self.env,
                jwt_secret_length=len(self.jwt_secret) if self.jwt_secret else 0,
            )
            raise ValueError(
                f"[M12] 启动失败：JWT 密钥不安全！\n{secret_warning}\n"
                "如需强制跳过检查（仅限开发测试），请设置 "
                "M12_REQUIRE_SECURE_SECRET=false"
            )

        if self.env == "production":
            logger.warning(
                "m12.security.jwt_secret_unsafe_production",
                message=secret_warning,
                env=self.env,
            )
            warnings.warn(
                f"[M12] {secret_warning}",
                UserWarning,
                stacklevel=2,
            )
        else:
            logger.warning(
                "m12.security.jwt_secret_unsafe_development",
                message=secret_warning,
                env=self.env,
            )


# 全局配置单例
_settings: Optional[Settings] = None
_settings_lock = threading.Lock()


def get_settings() -> Settings:
    """获取全局配置实例（单例模式）

    首次调用时会验证 JWT 密钥安全性，根据配置决定
    是抛出错误、发出警告还是仅打印提示。

    Returns:
        Settings 配置对象
    """
    global _settings
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                _settings = Settings()
                _settings.ensure_dirs()
                # 验证密钥安全性
                _settings.validate_secret_security()
    return _settings


# 兼容直接运行测试
if __name__ == "__main__":
    settings = get_settings()
    print(f"模块名称: {settings.module_name_cn} ({settings.module_name})")
    print(f"版本: {settings.version}")
    print(f"项目根目录: {settings.base_dir}")
    print(f"数据目录: {settings.data_dir}")
    print(f"数据库路径: {settings.db_path}")
    print(f"服务端口: {settings.port}")
    print(f"WAF 防护: {'开启' if settings.waf_enabled else '关闭'}")
    print(f"速率限制: {'开启' if settings.rate_limit_enabled else '关闭'}")
    print(f"默认限流: {settings.default_rate_per_minute} 次/分钟")
