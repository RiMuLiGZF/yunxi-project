"""
M8 管理工作台 - 配置管理（P2-18: 配置去重）

全局通用配置从 shared.config 读取，避免与 YunxiConfig 重复定义。
M8 特有配置（数据库、JWT 详细参数等）保留在此处。
"""

import sys
import os
from pathlib import Path

# 将项目根目录加入 path，以便导入 shared 模块
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from pydantic_settings import BaseSettings
from typing import List, Optional

# 从 shared 读取全局配置作为默认值基准
try:
    from shared.config import get_config
    _global_config = get_config()
except Exception:
    # shared 不可用时使用回退默认值，保持 M8 独立可运行
    _global_config = None

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


class Settings(BaseSettings):
    """M8 后端配置

    全局通用配置从 shared.config 同步，避免重复定义。
    M8 特有配置保留在此类中。
    """

    # ===== 服务配置（与全局配置同步） =====
    app_name: str = "云汐管理工作台 M8"
    version: str = _global_get("version", "1.0.0")
    host: str = _global_get("module_hosts", {}).get("m8", "0.0.0.0")
    port: int = _global_get("module_ports", {}).get("m8", 8000)
    env: str = _global_get("env", "development")

    # ===== 安全配置（与全局配置同步，M8 扩展） =====
    admin_username: str = _global_get("m8_admin_username", "admin")
    admin_password: str = _global_get("m8_admin_password", "")
    jwt_secret: str = _global_get("m8_jwt_secret", "")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24小时
    m8_admin_token: str = _global_get("module_tokens", {}).get("m8", "")

    # ===== CORS（与全局配置同步） =====
    cors_origins: str = _global_get("cors_origins", "*")

    # ===== 数据库（M8 特有） =====
    database_url: str = f"sqlite:///{db_path}"

    # ===== 日志（与全局配置同步） =====
    log_level: str = _global_get("log_level", "info")

    class Config:
        env_file = str(project_root / "config" / "yunxi.env")
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


settings = Settings()


# 系统版本号（统一从 shared.version 导入）
# from shared.version import SYSTEM_VERSION
SYSTEM_VERSION = "0.4.0"  # 与 shared/version.py 保持同步
