"""
M1 Agent 集群 - 配置校验模型

M1 调度中心各模块的配置校验 Pydantic 模型。
迁移自 config_manager.py 中的配置模型定义。

配置模型使用 extra="allow" 以保证向后兼容，
仅对已知字段进行类型与范围校验。
"""

from __future__ import annotations

from pydantic import Field, field_validator

from models.base import M1BaseModel


class ServerConfig(M1BaseModel):
    """服务端配置子模型。"""

    model_config = {"extra": "allow"}

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "info"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"debug", "info", "warning", "error"}
        if v.lower() not in allowed:
            raise ValueError(f"log_level 必须是 {allowed} 之一，当前值: {v}")
        return v.lower()


class DatabaseConfig(M1BaseModel):
    """数据库配置子模型。"""

    model_config = {"extra": "allow"}

    db_path: str = "./data/m1.db"
    wal_mode: bool = True
    busy_timeout: int = 5000


class MessageBusConfig(M1BaseModel):
    """消息总线配置子模型。"""

    model_config = {"extra": "allow"}

    max_queue_size: int = 10000
    topic_pattern: str = "m1.*"


class FederationConfig(M1BaseModel):
    """联邦调度配置子模型。"""

    model_config = {"extra": "allow"}

    enabled: bool = True
    default_privacy_level: str = "L1"


class AgentsConfig(M1BaseModel):
    """Agent 管理配置子模型。"""

    model_config = {"extra": "allow"}

    max_concurrent: int = 100
    default_timeout_s: int = 300


class MemoryConfig(M1BaseModel):
    """记忆系统配置子模型。"""

    model_config = {"extra": "allow"}

    enabled: bool = True
    max_entries: int = 10000


class SecurityConfig(M1BaseModel):
    """安全配置子模型。"""

    model_config = {"extra": "allow"}

    admin_key: str | None = None
    rate_limit_per_minute: int = 60


class M1Config(M1BaseModel):
    """M1 调度中心配置校验 Schema。

    使用 Pydantic v2 风格的模型配置，允许额外字段（extra="allow"），
    仅对已知字段进行类型与范围校验，未知字段原样保留以保证向后兼容。
    """

    model_config = {"extra": "allow"}

    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    message_bus: MessageBusConfig = Field(default_factory=MessageBusConfig)
    federation: FederationConfig = Field(default_factory=FederationConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
