"""
M6 硬件外设 - 配置管理

统一配置框架迁移版：
- 新接口：M6ModuleConfig（继承 BaseConfig，基于 pydantic-settings）
- 旧接口：M6Config 普通类（保留，向后兼容）

从环境变量和 yunxi.env 加载配置

配置项清单：
+---------------------------+---------------------------------+-----------------------------+----------+
| 配置项                    | 环境变量名                     | 默认值                      | 说明     |
+===========================+=================================+=============================+==========+
| module_name               | M6_NAME                        | m6-hardware                 | 模块名称 |
+---------------------------+---------------------------------+-----------------------------+----------+
| host                      | M6_HOST                       | 0.0.0.0                     | 监听地址 |
+---------------------------+---------------------------------+-----------------------------+----------+
| port                      | M6_PORT                       | 8006                        | 监听端口 |
+---------------------------+---------------------------------+-----------------------------+----------+
| env                       | M6_ENV                        | development                 | 运行环境 |
+---------------------------+---------------------------------+-----------------------------+----------+
| admin_token               | M6_ADMIN_TOKEN                | 生产: 无(必填)/开发: 随机 | 管理令牌 |
+---------------------------+---------------------------------+-----------------------------+----------+
| simulation_mode           | M6_SIMULATION_MODE            | true                        | 模拟模式 |
+---------------------------+---------------------------------+-----------------------------+----------+
| database_path             | M6_DATABASE_PATH              | data/m6_sensors.db          | 数据库路径 |
+---------------------------+---------------------------------+-----------------------------+----------+
| collection_interval       | M6_COLLECTION_INTERVAL        | 5                           | 采集间隔(秒) |
+---------------------------+---------------------------------+-----------------------------+----------+
| data_retention_days       | M6_DATA_RETENTION_DAYS        | 30                          | 数据保留天数 |
+---------------------------+---------------------------------+-----------------------------+----------+
| sse_token_ttl             | M6_SSE_TOKEN_TTL              | 300                         | SSE令牌有效期(秒) |
+---------------------------+---------------------------------+-----------------------------+----------+
| sse_max_connections       | M6_SSE_MAX_CONNECTIONS        | 100                         | SSE最大连接数 |
+---------------------------+---------------------------------+-----------------------------+----------+
| sse_interval              | M6_SSE_INTERVAL               | 5                           | SSE推送间隔(秒) |
+---------------------------+---------------------------------+-----------------------------+----------+
| sse_heartbeat_interval    | M6_SSE_HEARTBEAT_INTERVAL     | 30                          | SSE心跳间隔(秒) |
+---------------------------+---------------------------------+-----------------------------+----------+
| battery_low_threshold     | M6_BATTERY_LOW_THRESHOLD      | 20                          | 低电量告警阈值(%) |
+---------------------------+---------------------------------+-----------------------------+----------+
| battery_drain_base        | M6_BATTERY_DRAIN_BASE         | 0.1                         | 基础电量消耗速率 |
+---------------------------+---------------------------------+-----------------------------+----------+
| default_devices_path      | M6_DEFAULT_DEVICES_PATH       | ""                          | 默认设备配置文件路径 |
+---------------------------+---------------------------------+-----------------------------+----------+
| cors_origins              | CORS_ORIGINS                  | *                           | CORS允许来源 |
+---------------------------+---------------------------------+-----------------------------+----------+
| log_level                 | YUNXI_LOG_LEVEL               | info                        | 日志级别 |
+---------------------------+---------------------------------+-----------------------------+----------+
"""

from __future__ import annotations

import os
import secrets
import sys
import logging
from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator


# ============================================================
# 尝试从统一配置基类导入
# ============================================================

try:
    _current = Path(__file__).resolve()
    for _ in range(10):
        _current = _current.parent
        if (_current / "shared" / "core" / "config.py").exists():
            if str(_current) not in sys.path:
                sys.path.insert(0, str(_current))
            break
    from shared.core.config import BaseConfig, EnvType
    from pydantic_settings import SettingsConfigDict
    _USE_UNIFIED_CONFIG = True
except ImportError:
    _USE_UNIFIED_CONFIG = False


logger = logging.getLogger(__name__)


# ============================================================
# 路径工具
# ============================================================

def _find_project_root() -> Optional[Path]:
    """从当前目录向上查找包含 config/yunxi.env 的项目根目录"""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "config" / "yunxi.env").exists():
            return current
        current = current.parent
    return None


def _default_db_path() -> str:
    """默认数据库路径"""
    return str(Path(__file__).parent.parent / "data" / "m6_sensors.db")


# ============================================================
# M6 模块统一配置类（新接口）
# ============================================================

if _USE_UNIFIED_CONFIG:

    class M6ModuleConfig(BaseConfig):
        """
        M6 硬件外设模块配置（统一配置框架版）

        继承自 BaseConfig，自动获得：
        - .env 文件加载
        - 环境变量覆盖
        - 生产环境敏感字段校验
        - 敏感字段脱敏
        - 配置热更新

        环境变量前缀：M6_
        """

        module_name: str = Field(default="m6-hardware", description="模块名称")
        port: int = Field(default=8006, ge=1, le=65535, description="监听端口")

        # 运行模式
        simulation_mode: bool = Field(default=True, description="模拟模式")

        # 数据库
        database_path: str = Field(default_factory=_default_db_path, description="数据库路径")

        # 数据采集
        collection_interval: float = Field(default=5.0, ge=0.1, description="采集间隔(秒)")
        data_retention_days: int = Field(default=30, ge=1, description="数据保留天数")

        # SSE 配置
        sse_token_ttl: int = Field(default=300, ge=1, description="SSE令牌有效期(秒)")
        sse_max_connections: int = Field(default=100, ge=1, description="SSE最大连接数")
        sse_interval: float = Field(default=5.0, ge=0.1, description="SSE推送间隔(秒)")
        sse_heartbeat_interval: float = Field(default=30.0, ge=1, description="SSE心跳间隔(秒)")

        # 电量配置
        battery_low_threshold: float = Field(default=20.0, ge=0, le=100, description="低电量告警阈值(%)")
        battery_drain_base: float = Field(default=0.1, ge=0, description="基础电量消耗速率")

        # 设备配置
        default_devices_path: str = Field(default="", description="默认设备配置文件路径")

        model_config = SettingsConfigDict(
            env_prefix="M6_",
            env_file="config/yunxi.env",
            env_file_encoding="utf-8",
            extra="allow",
            validate_assignment=True,
        )

        @model_validator(mode="after")
        def _validate_admin_token(self) -> "M6ModuleConfig":
            """
            管理员 Token 校验。

            - 生产环境：未配置则抛出 RuntimeError，阻止启动
            - 开发环境：未配置则生成随机一次性 Token，并打印 warning 日志

            注意：admin_token 继承自 BaseConfig，这里做额外的业务校验。
            """
            if self.admin_token:
                return self

            if self.is_production:
                raise ValueError(
                    "生产环境必须配置 M6_ADMIN_TOKEN，禁止使用默认值。"
                    "请在环境变量或 config/yunxi.env 中设置 M6_ADMIN_TOKEN。"
                )

            # 开发环境生成随机一次性令牌
            self.admin_token = secrets.token_urlsafe(32)
            logger.warning(
                "开发环境未配置 M6_ADMIN_TOKEN，已自动生成一次性随机 Token：%s",
                self.admin_token,
            )
            return self

        def ensure_data_dir(self) -> None:
            """确保数据目录存在"""
            db_dir = Path(self.database_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)


    # 全局配置单例（新接口）
    _m6_config: Optional[M6ModuleConfig] = None

    def get_m6_config() -> M6ModuleConfig:
        """获取 M6 模块配置实例（单例模式，统一配置框架）"""
        global _m6_config
        if _m6_config is None:
            _m6_config = M6ModuleConfig()
            _m6_config.ensure_data_dir()
        return _m6_config

else:
    M6ModuleConfig = None  # type: ignore
    get_m6_config = None  # type: ignore


# ============================================================
# 旧接口：M6Config（向后兼容）
# ============================================================

class M6Config:
    """
    M6 硬件外设配置类（向后兼容层）

    .. deprecated:: 2.0.0
        请使用 M6ModuleConfig 替代。

    P0-4 改造：移除 __new__ 单例模式，改为由 FastAPI lifespan 统一创建管理。
    模块级 get_config() 作为向后兼容层保留（标记 deprecated）。
    """

    def __init__(self):
        if _USE_UNIFIED_CONFIG and M6ModuleConfig is not None:
            self._inner = M6ModuleConfig()
            self._inner.ensure_data_dir()
        else:
            self._inner = None
            self._load_config()

    def _load_config(self):
        """加载配置文件和环境变量（旧逻辑，降级模式）"""
        # 从项目根目录查找 config/yunxi.env
        project_root = _find_project_root()
        if project_root:
            env_file = project_root / "config" / "yunxi.env"
            if env_file.exists():
                try:
                    from dotenv import load_dotenv
                    load_dotenv(env_file, override=False)
                except ImportError:
                    self._manual_load_env(env_file)

        # 运行环境
        self.env = os.getenv("M6_ENV", "development").lower()

        # 基础配置
        self.module_name = os.getenv("M6_NAME", "m6-hardware")
        self.port = int(os.getenv("M6_PORT", "8006"))
        self.host = os.getenv("M6_HOST", "0.0.0.0")
        self.simulation_mode = os.getenv("M6_SIMULATION_MODE", "true").lower() == "true"

        # 管理员 Token
        self._admin_token_env = os.getenv("M6_ADMIN_TOKEN")
        self._admin_token_generated = None

        # 数据库配置
        default_db_path = str(Path(__file__).parent.parent / "data" / "m6_sensors.db")
        self.database_path = os.getenv("M6_DATABASE_PATH", default_db_path)

        # 数据采集配置
        self.collection_interval = float(os.getenv("M6_COLLECTION_INTERVAL", "5"))
        self.data_retention_days = int(os.getenv("M6_DATA_RETENTION_DAYS", "30"))

        # SSE 配置
        self.sse_token_ttl = int(os.getenv("M6_SSE_TOKEN_TTL", "300"))
        self.sse_max_connections = int(os.getenv("M6_SSE_MAX_CONNECTIONS", "100"))
        self.sse_interval = float(os.getenv("M6_SSE_INTERVAL", "5"))
        self.sse_heartbeat_interval = float(os.getenv("M6_SSE_HEARTBEAT_INTERVAL", "30"))

        # 电量配置
        self.battery_low_threshold = float(os.getenv("M6_BATTERY_LOW_THRESHOLD", "20"))
        self.battery_drain_base = float(os.getenv("M6_BATTERY_DRAIN_BASE", "0.1"))

        # 设备配置
        self.default_devices_path = os.getenv("M6_DEFAULT_DEVICES_PATH", "")

        # CORS 配置
        self.cors_origins = os.getenv("CORS_ORIGINS", "*")

        # 日志配置
        self.log_level = os.getenv("YUNXI_LOG_LEVEL", "info")

    @property
    def admin_token(self) -> str:
        """
        管理员 Token，动态获取。

        - 生产环境（env=production）：未配置则抛出 RuntimeError，阻止启动
        - 开发环境（env=development）：未配置则生成随机一次性 Token，并打印 warning 日志
        """
        if self._inner is not None:
            return self._inner.admin_token

        # 降级模式
        if self._admin_token_env:
            return self._admin_token_env

        if self.env == "production":
            raise RuntimeError(
                "生产环境必须配置 M6_ADMIN_TOKEN，禁止使用默认值。"
                "请在环境变量或 config/yunxi.env 中设置 M6_ADMIN_TOKEN。"
            )

        if self._admin_token_generated is None:
            self._admin_token_generated = secrets.token_urlsafe(32)
            logger.warning(
                "开发环境未配置 M6_ADMIN_TOKEN，已自动生成一次性随机 Token：%s",
                self._admin_token_generated,
            )
        return self._admin_token_generated

    @admin_token.setter
    def admin_token(self, value: str):
        if self._inner is not None:
            self._inner.admin_token = value
        else:
            self._admin_token_env = value

    @property
    def env(self) -> str:
        if self._inner is not None:
            return self._inner.env.value
        return self._env

    @env.setter
    def env(self, value: str):
        if self._inner is not None:
            from shared.core.config import EnvType
            self._inner.env = EnvType(value)
        else:
            self._env = value

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(f"'M6Config' object has no attribute '{name}'")
        if self._inner is not None:
            try:
                return getattr(self._inner, name)
            except AttributeError:
                raise AttributeError(f"'M6Config' object has no attribute '{name}'")
        raise AttributeError(f"'M6Config' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        elif hasattr(self, "_inner") and self._inner is not None and hasattr(self._inner, name):
            setattr(self._inner, name, value)
        else:
            super().__setattr__(name, value)

    def _manual_load_env(self, env_file: Path):
        """手动加载 .env 文件（当 python-dotenv 不可用时）"""
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
        except Exception:
            pass


# ============================================================
# 全局配置单例（旧接口，向后兼容）
# ============================================================

_instance: M6Config | None = None


def get_config() -> M6Config:
    """获取 M6 配置单例

    .. deprecated:: P0-4
        推荐使用 FastAPI 依赖注入 ``Depends(get_config)`` 方式，
        由 lifespan 统一管理实例生命周期。本函数作为向后兼容层保留。
    """
    global _instance
    if _instance is None:
        _instance = M6Config()
    return _instance


# ============================================================
# 系统版本号（统一从 shared.version 导入）
# ============================================================

def _load_system_version() -> str:
    """从 shared.version 导入系统版本号，导入失败则回退到默认值"""
    try:
        current = Path(__file__).resolve().parent
        for _ in range(10):
            if (current / "shared" / "version.py").exists():
                if str(current) not in sys.path:
                    sys.path.insert(0, str(current))
                break
            current = current.parent
        from shared.version import SYSTEM_VERSION
        return SYSTEM_VERSION
    except Exception:
        return "v1.0.0"


SYSTEM_VERSION = _load_system_version()
