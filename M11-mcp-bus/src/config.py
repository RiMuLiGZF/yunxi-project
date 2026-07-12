"""M11 MCP Bus - 配置模块.

从环境变量读取配置，提供单例访问。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """M11 服务配置.

    所有配置项均从环境变量读取，前缀为 M11_。
    """

    model_config = SettingsConfigDict(
        env_prefix="M11_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 基础配置 ----------
    host: str = Field(default="0.0.0.0", description="监听地址")
    port: int = Field(default=8011, description="监听端口")
    env: str = Field(default="development", description="运行环境")
    log_level: str = Field(default="info", description="日志级别")

    # ---------- 安全配置 ----------
    admin_token: str = Field(default="", description="管理 Token（M8 对接）")

    # ---------- 数据库配置 ----------
    db_path: str = Field(default="~/.yunxi/m11_bus.db", description="SQLite 数据库路径")

    # ---------- 业务配置 ----------
    heartbeat_timeout: int = Field(default=30, description="心跳超时时间（秒）")
    tool_refresh_interval: int = Field(default=300, description="工具刷新间隔（秒）")
    sse_heartbeat_interval: int = Field(default=30, description="SSE 心跳间隔（秒）")
    sse_max_clients: int = Field(default=100, description="SSE 最大连接数")

    # ---------- 熔断与重试配置 ----------
    retry_max_attempts: int = Field(default=2, description="工具调用最大重试次数")
    retry_base_delay_ms: int = Field(default=100, description="重试基础延迟（毫秒），指数退避")
    circuit_breaker_fail_threshold: int = Field(default=5, description="熔断器连续失败阈值")
    circuit_breaker_open_duration: int = Field(default=30, description="熔断器打开持续时间（秒）")
    circuit_breaker_half_open_limit: int = Field(default=1, description="半开状态放行请求数")

    # ---------- Redis 配置 ----------
    redis_url: str = Field(default="", description="Redis 连接 URL（为空表示不启用 Redis")
    redis_prefix: str = Field(default="m11:", description="Redis Key 前缀")
    redis_timeout: int = Field(default=5, description="Redis 操作超时时间（秒）")

    # ---------- stdio 传输配置 ----------
    stdio_enabled: bool = Field(default=True, description="是否启用 stdio 传输支持")
    stdio_max_services: int = Field(default=10, description="最大同时运行的 stdio 服务数")
    stdio_start_timeout: int = Field(default=10, description="stdio 服务启动超时时间（秒）")
    stdio_stop_timeout: int = Field(default=5, description="stdio 服务停止超时时间（秒）")

    # ---------- CORS 配置 ----------
    cors_origins: str = Field(default="*", description="CORS 允许的来源，逗号分隔")

    @property
    def db_file_path(self) -> Path:
        """获取解析后的数据库文件路径."""
        expanded = os.path.expanduser(self.db_path)
        return Path(expanded).resolve()

    @property
    def db_url(self) -> str:
        """获取 SQLAlchemy 数据库 URL."""
        return f"sqlite:///{self.db_file_path}"

    @property
    def is_development(self) -> bool:
        """是否为开发环境."""
        return self.env == "development"

    @property
    def is_production(self) -> bool:
        """是否为生产环境."""
        return self.env == "production"

    @property
    def use_redis(self) -> bool:
        """是否启用 Redis（根据 redis_url 是否为空判断）.

        Returns:
            True 表示配置了 Redis 并应尝试使用
        """
        return bool(self.redis_url)

    @property
    def cors_origin_list(self) -> list[str]:
        """获取 CORS 来源列表."""
        if not self.cors_origins or self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取配置单例.

    使用 lru_cache 确保整个应用只创建一个 Settings 实例。

    Returns:
        Settings 配置实例
    """
    return Settings()


def reload_settings() -> Settings:
    """重新加载配置（清除缓存）.

    Returns:
        新的 Settings 配置实例
    """
    get_settings.cache_clear()
    return get_settings()
