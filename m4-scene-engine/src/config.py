"""
M4 场景引擎 - 统一配置管理

集中管理所有环境变量配置，替代分散在各文件中的 os.environ.get 调用。

使用方式：
    from src.config import get_settings
    settings = get_settings()
    print(settings.port, settings.default_scene)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from functools import lru_cache

import structlog
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 路径工具
# ---------------------------------------------------------------------------

def _find_project_root() -> Path:
    """向上查找项目根目录（含 config/yunxi.env 的目录）"""
    current = Path(__file__).resolve().parent.parent.parent
    for _ in range(10):
        if (current / "config" / "yunxi.env").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return current.parent


def _load_env_files() -> None:
    """加载环境变量文件（全局 + 模块级）"""
    project_root = _find_project_root()

    # 1. 全局配置（优先级低）
    global_env = project_root / "config" / "yunxi.env"
    if global_env.exists():
        _load_dotenv(str(global_env), override=False)

    # 2. 模块级 .env（优先级高）
    module_env = Path(__file__).resolve().parent.parent / ".env"
    if module_env.exists():
        _load_dotenv(str(module_env), override=True)


def _load_dotenv(filepath: str, override: bool = False) -> None:
    """手动加载 .env 文件（兼容无 python-dotenv 的环境）"""
    try:
        from dotenv import load_dotenv
        load_dotenv(filepath, override=override)
        return
    except ImportError:
        pass

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("\'")
                if key and (override or key not in os.environ):
                    os.environ[key] = value
    except Exception as e:
        logger.warning("config.load_dotenv_failed", filepath=filepath, error_type=type(e).__name__, error=str(e))


# 启动时加载环境变量
_load_env_files()


# ---------------------------------------------------------------------------
# 配置类
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """M4 场景引擎配置"""

    model_config = SettingsConfigDict(
        env_prefix="M4_",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 基础服务 ----
    port: int = Field(default=8004, ge=1, le=65535, description="服务端口")
    host: str = Field(default="0.0.0.0", min_length=1, description="监听地址")
    env: str = Field(default="development", min_length=1, description="运行环境")

    # ---- CORS ----
    cors_origins: str = Field(default="*", description="CORS 允许源（逗号分隔）")

    # ---- 场景引擎 ----
    default_scene: str = Field(default="emotional", min_length=1, description="默认场景")
    auto_switch: bool = Field(default=True, description="是否自动切换场景")
    switch_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="场景切换阈值")
    keyword_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="关键词匹配阈值")
    max_history: int = Field(default=100, ge=1, description="最大历史记录数")

    # ---- LLM ----
    enable_llm: bool = Field(default=False, description="是否启用 LLM")
    llm_base_url: str = Field(default="", description="LLM 基础 URL")
    llm_model: str = Field(default="", description="LLM 模型名称")

    # ---- 数据 ----
    data_path: str = Field(default="", description="数据目录路径")

    @field_validator("data_path")
    @classmethod
    def validate_data_path(cls, v: str) -> str:
        """验证数据目录路径，为空则自动推导默认路径.

        默认路径优先级：
        1. 项目根目录下的 data/（推荐）
        2. src/data/（向后兼容）
        """
        if v:
            return v
        # 自动推导默认数据目录
        project_root = Path(__file__).resolve().parent.parent
        default_data = project_root / "data"
        legacy_data = project_root / "src" / "data"
        # 如果默认 data 目录不存在但 legacy 存在，使用 legacy（向后兼容）
        if not default_data.exists() and legacy_data.exists():
            return str(legacy_data)
        return str(default_data)

    # ---- 安全 ----
    admin_token: str = Field(default="", description="管理员令牌")

    # ---- 新增配置字段 ----
    rate_limit_enabled: bool = Field(default=True, description="是否启用速率限制")
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000, description="每分钟速率限制")
    log_level: str = Field(default="info", description="日志级别")
    vscode_auto_launch: bool = Field(default=False, description="是否自动启动 VSCode")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """验证日志级别"""
        valid_levels = ["debug", "info", "warning", "error", "critical"]
        if v.lower() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}, got {v}")
        return v.lower()

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS 允许源列表"""
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        """是否开发环境"""
        return self.env.lower() in ("dev", "development")

    @property
    def is_production(self) -> bool:
        """是否生产环境"""
        return self.env.lower() in ("prod", "production")


# ---------------------------------------------------------------------------
# 单例获取
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


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
        from shared.version import SYSTEM_VERSION
        return SYSTEM_VERSION
    except Exception as e:
        logger.warning("config.load_system_version_failed", error_type=type(e).__name__, error=str(e))
        return "v1.2.0"


SYSTEM_VERSION = _load_system_version()


# ---------------------------------------------------------------------------
# 统一配置框架接入（第二阶段基础设施）
# ---------------------------------------------------------------------------
# 新增 M4ModuleConfig 继承 BaseConfig，获得：
# - 全局 .env 文件自动加载
# - 生产环境敏感字段校验
# - 配置热更新
# - 敏感字段自动脱敏
# 原有 Settings 类保持不变，确保向后兼容。
# ---------------------------------------------------------------------------

try:
    from shared.core.config import BaseConfig
    _USE_UNIFIED_CONFIG_M4 = True
except ImportError:
    _USE_UNIFIED_CONFIG_M4 = False
    BaseConfig = None  # type: ignore


if _USE_UNIFIED_CONFIG_M4:

    class M4ModuleConfig(BaseConfig):
        """
        M4 场景引擎配置（统一配置框架版）

        继承自 BaseConfig，自动获得：
        - .env 文件加载（config/yunxi.env）
        - 环境变量覆盖（优先级最高）
        - 生产环境敏感字段校验
        - 敏感字段脱敏输出
        - 配置热更新

        环境变量前缀：M4_
        """

        module_name: str = Field(default="m4-scene-engine", description="模块名称")
        port: int = Field(default=8004, ge=1, le=65535, description="服务监听端口")
        default_scene: str = Field(default="home", description="默认场景")
        auto_switch: bool = Field(default=True, description="是否自动切换场景")
        env: str = Field(default="development", description="运行环境")

        model_config = SettingsConfigDict(
            env_prefix="M4_",
            env_file="config/yunxi.env",
            env_file_encoding="utf-8",
            extra="allow",
            validate_assignment=True,
        )

    # 全局配置单例（新接口）
    _m4_unified_config: M4ModuleConfig | None = None

    def get_m4_unified_config() -> M4ModuleConfig:
        """获取 M4 模块统一配置实例（单例模式）"""
        global _m4_unified_config
        if _m4_unified_config is None:
            _m4_unified_config = M4ModuleConfig()
        return _m4_unified_config

else:
    M4ModuleConfig = None  # type: ignore
    get_m4_unified_config = None  # type: ignore
