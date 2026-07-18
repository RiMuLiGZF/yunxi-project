"""
云汐 M9 数据水晶 - 配置管理模块

P3 优化：数据采集管道 + 连接器生态
统一配置框架，支持环境变量覆盖
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict


# ============================================================
# 尝试从统一配置基类导入，失败则降级到本地实现
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
    _USE_UNIFIED_CONFIG = True
except ImportError:
    _USE_UNIFIED_CONFIG = False


def _get_base_dir() -> Path:
    """获取项目基础目录"""
    if "__file__" in globals():
        return Path(__file__).resolve().parent.parent
    return Path.cwd()


# ============================================================
# M9 Data Crystal 模块配置类
# ============================================================

if _USE_UNIFIED_CONFIG:

    class DataCrystalConfig(BaseConfig):
        """
        M9 数据水晶模块配置

        环境变量前缀：M9_DC_
        """

        # ---- 模块基础信息 ----
        module_name: str = Field(default="m9-data-crystal", description="模块名称")
        port: int = Field(default=8019, ge=1, le=65535, description="服务监听端口")

        # ---- 基础路径配置 ----
        base_dir: str = Field(default_factory=lambda: str(_get_base_dir()), description="项目根目录")
        data_dir: str = Field(default="", description="数据目录")
        db_path: str = Field(default="", description="数据库路径")

        # ---- 连接器配置 ----
        connector_pool_size: int = Field(default=10, ge=1, description="连接器连接池大小")
        connector_idle_timeout: int = Field(default=300, ge=10, description="连接器空闲超时（秒）")
        connector_health_check_interval: int = Field(default=60, ge=10, description="健康检查间隔（秒）")

        # ---- 管道配置 ----
        pipeline_max_concurrent: int = Field(default=5, ge=1, description="最大并发管道数")
        pipeline_default_batch_size: int = Field(default=1000, ge=1, description="默认批处理大小")
        pipeline_retry_max_attempts: int = Field(default=3, ge=0, description="管道失败最大重试次数")
        pipeline_retry_delay: float = Field(default=5.0, ge=0, description="管道重试延迟（秒）")

        # ---- 服务配置 ----
        debug: bool = Field(default=True, description="调试模式")
        host: str = Field(default="0.0.0.0", description="监听地址")
        cors_origins: List[str] = Field(
            default_factory=lambda: [
                "http://localhost:3000",
                "http://localhost:5173",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:5173",
            ],
            description="CORS 允许来源",
        )
        admin_token: str = Field(default="", description="管理员 Token")

        model_config = SettingsConfigDict(
            env_prefix="M9_DC_",
            env_file=".env",
            env_file_encoding="utf-8",
            extra="allow",
            validate_assignment=True,
        )

        @field_validator("data_dir", mode="before")
        @classmethod
        def _default_data_dir(cls, v: str) -> str:
            if not v:
                return str(_get_base_dir() / "data")
            return v

        @field_validator("db_path", mode="before")
        @classmethod
        def _default_db_path(cls, v: str) -> str:
            if not v:
                return str(_get_base_dir() / "data" / "yunxi_m9_dc.db")
            return v

        def get_db_url(self) -> str:
            """获取 SQLAlchemy 数据库连接 URL"""
            return f"sqlite:///{Path(self.db_path).as_posix()}"

        def ensure_data_dir(self) -> None:
            """确保数据目录存在"""
            Path(self.data_dir).mkdir(parents=True, exist_ok=True)

    _dc_config: Optional[DataCrystalConfig] = None

    def get_config() -> DataCrystalConfig:
        """获取配置单例"""
        global _dc_config
        if _dc_config is None:
            _dc_config = DataCrystalConfig()
            _dc_config.ensure_data_dir()
        return _dc_config

else:
    # 降级模式：简单 dataclass 配置
    from dataclasses import dataclass, field

    @dataclass
    class DataCrystalConfig:
        module_name: str = "m9-data-crystal"
        port: int = 8019
        base_dir: Path = field(default_factory=_get_base_dir)
        data_dir: Path = field(default_factory=lambda: _get_base_dir() / "data")
        db_path: Path = field(default_factory=lambda: _get_base_dir() / "data" / "yunxi_m9_dc.db")
        connector_pool_size: int = 10
        connector_idle_timeout: int = 300
        connector_health_check_interval: int = 60
        pipeline_max_concurrent: int = 5
        pipeline_default_batch_size: int = 1000
        pipeline_retry_max_attempts: int = 3
        pipeline_retry_delay: float = 5.0
        debug: bool = True
        host: str = "0.0.0.0"
        cors_origins: List[str] = field(default_factory=lambda: [
            "http://localhost:3000", "http://localhost:5173",
            "http://127.0.0.1:3000", "http://127.0.0.1:5173",
        ])
        admin_token: str = ""

        def __post_init__(self):
            if isinstance(self.base_dir, str):
                self.base_dir = Path(self.base_dir)
            if isinstance(self.data_dir, str):
                self.data_dir = Path(self.data_dir)
            if isinstance(self.db_path, str):
                self.db_path = Path(self.db_path)
            self.ensure_data_dir()

        def get_db_url(self) -> str:
            return f"sqlite:///{self.db_path.as_posix()}"

        def ensure_data_dir(self) -> None:
            Path(self.data_dir).mkdir(parents=True, exist_ok=True)

        def reload_config(self) -> dict:
            return {}

    _dc_config: Optional[DataCrystalConfig] = None

    def get_config() -> DataCrystalConfig:
        global _dc_config
        if _dc_config is None:
            _dc_config = DataCrystalConfig()
        return _dc_config


# 兼容别名
def get_settings() -> DataCrystalConfig:
    """向后兼容：获取配置"""
    return get_config()
