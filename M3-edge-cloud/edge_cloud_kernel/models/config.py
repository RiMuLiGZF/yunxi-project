"""M3 端云协同内核配置模型（Pydantic Schema 化）.

使用 Pydantic BaseModel 定义完整的配置 Schema，提供：
- 类型安全的配置结构
- 自动校验（类型、范围、枚举）
- 默认值统一管理
- 与 dict 双向转换（model_dump / model_validate）
- 与环境变量覆盖机制配合使用

配置层级：
    EdgeCloudConfig
    ├── BasicConfig        - 基础配置
    ├── SecurityConfig     - 安全配置（含 E2EE 子配置）
    ├── SyncConfig         - 同步配置
    ├── StorageConfig      - 存储配置
    ├── OfflineConfig      - 离线配置（含 Retry 子配置）
    ├── DatabaseConfig     - 数据库配置
    ├── LoggingConfig      - 日志配置
    └── DevicesConfig      - 设备注册表配置
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 子配置模型
# ---------------------------------------------------------------------------

class BasicConfig(BaseModel):
    """基础配置.

    Attributes:
        name: 服务名称标识.
        version: 当前版本号.
        port: 服务监听端口.
        log_level: 日志级别（debug/info/warning/error）.
        env: 运行环境（production/development/staging）.
    """

    name: str = Field(default="m3-sync", description="服务名称标识")
    version: str = Field(default="2.1.2", description="当前版本号")
    port: int = Field(default=8003, ge=1, le=65535, description="服务监听端口")
    log_level: str = Field(default="info", description="日志级别")
    env: str = Field(default="production", description="运行环境")

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        """校验日志级别合法性."""
        valid_levels = {"debug", "info", "warning", "error", "critical"}
        if v.lower() not in valid_levels:
            raise ValueError(
                f"Invalid log_level: {v}. Must be one of {valid_levels}"
            )
        return v.lower()


class E2EEConfig(BaseModel):
    """端到端加密配置.

    Attributes:
        enabled: 是否启用端到端加密.
        algorithm: 加密算法名称.
    """

    enabled: bool = Field(default=True, description="是否启用端到端加密")
    algorithm: str = Field(default="AES-256-GCM", description="加密算法名称")


class SecurityConfig(BaseModel):
    """安全配置.

    Attributes:
        encryption_key: 数据加密密钥（敏感字段）.
        admin_token: 管理员访问令牌（敏感字段）.
        cors_origins: 允许的 CORS 源列表.
        e2ee: 端到端加密子配置.
    """

    encryption_key: str = Field(default="", description="数据加密密钥")
    admin_token: str = Field(default="", description="管理员访问令牌")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="允许的 CORS 源列表",
    )
    e2ee: E2EEConfig = Field(
        default_factory=E2EEConfig,
        description="端到端加密子配置",
    )


class SyncConfig(BaseModel):
    """同步配置.

    Attributes:
        mode: 同步模式（auto/manual/scheduled）.
        interval: 同步间隔（秒），auto 模式下使用.
        conflict_strategy: 冲突解决策略.
        max_concurrent: 最大并发同步数.
        max_file_size: 单文件大小限制（MB）.
    """

    mode: str = Field(default="auto", description="同步模式")
    interval: int = Field(default=60, ge=1, description="同步间隔（秒）")
    conflict_strategy: str = Field(
        default="newest_wins",
        description="冲突解决策略",
    )
    max_concurrent: int = Field(
        default=10,
        ge=1,
        description="最大并发同步数",
    )
    max_file_size: int = Field(
        default=100,
        ge=1,
        description="单文件大小限制（MB）",
    )

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        """校验同步模式合法性."""
        valid_modes = {"auto", "manual", "scheduled"}
        if v not in valid_modes:
            raise ValueError(
                f"Invalid sync mode: {v}. Must be one of {valid_modes}"
            )
        return v

    @field_validator("conflict_strategy")
    @classmethod
    def _validate_conflict_strategy(cls, v: str) -> str:
        """校验冲突策略合法性."""
        valid_strategies = {
            "server_wins", "client_wins", "manual", "newest_wins",
        }
        if v not in valid_strategies:
            raise ValueError(
                f"Invalid conflict_strategy: {v}. "
                f"Must be one of {valid_strategies}"
            )
        return v


class StorageConfig(BaseModel):
    """存储配置.

    Attributes:
        local_path: 本地存储路径.
        cloud_type: 云端存储类型（local/s3/webdav）.
        cloud_path: 云端存储路径.
        cache_size: 缓存大小（MB）.
    """

    local_path: str = Field(default="./data/sync", description="本地存储路径")
    cloud_type: str = Field(default="local", description="云端存储类型")
    cloud_path: str = Field(default="./data/cloud", description="云端存储路径")
    cache_size: int = Field(default=512, ge=0, description="缓存大小（MB）")

    @field_validator("cloud_type")
    @classmethod
    def _validate_cloud_type(cls, v: str) -> str:
        """校验云端存储类型合法性."""
        valid_types = {"local", "s3", "webdav"}
        if v not in valid_types:
            raise ValueError(
                f"Invalid cloud_type: {v}. Must be one of {valid_types}"
            )
        return v


class OfflineRetryConfig(BaseModel):
    """离线重试策略配置.

    Attributes:
        max_attempts: 最大重试次数.
        backoff: 退避策略（exponential/linear/fixed）.
    """

    max_attempts: int = Field(default=5, ge=1, description="最大重试次数")
    backoff: str = Field(default="exponential", description="退避策略")

    @field_validator("backoff")
    @classmethod
    def _validate_backoff(cls, v: str) -> str:
        """校验退避策略合法性."""
        valid_strategies = {"exponential", "linear", "fixed"}
        if v not in valid_strategies:
            raise ValueError(
                f"Invalid backoff strategy: {v}. "
                f"Must be one of {valid_strategies}"
            )
        return v


class OfflineConfig(BaseModel):
    """离线配置.

    Attributes:
        queue_size: 离线队列大小.
        retry: 重试策略子配置.
    """

    queue_size: int = Field(default=1000, ge=0, description="离线队列大小")
    retry: OfflineRetryConfig = Field(
        default_factory=OfflineRetryConfig,
        description="重试策略子配置",
    )


class DatabaseConfig(BaseModel):
    """数据库配置.

    Attributes:
        type: 数据库类型（sqlite）.
        path: 数据库文件路径.
    """

    type: str = Field(default="sqlite", description="数据库类型")
    path: str = Field(default="./data/m3.db", description="数据库文件路径")

    @field_validator("type")
    @classmethod
    def _validate_db_type(cls, v: str) -> str:
        """校验数据库类型."""
        valid_types = {"sqlite"}
        if v not in valid_types:
            raise ValueError(
                f"Invalid database type: {v}. Must be one of {valid_types}"
            )
        return v


class LoggingConfig(BaseModel):
    """日志配置.

    Attributes:
        format: 日志格式（json/text）.
        level: 日志级别.
        file: 日志文件路径.
        max_size: 单日志文件最大大小.
        max_files: 日志文件最大数量.
        sensitive_fields: 敏感字段列表（日志中脱敏）.
    """

    format: str = Field(default="json", description="日志格式")
    level: str = Field(default="info", description="日志级别")
    file: str = Field(default="./logs/m3.log", description="日志文件路径")
    max_size: str = Field(default="100MB", description="单日志文件最大大小")
    max_files: int = Field(default=10, ge=1, description="日志文件最大数量")
    sensitive_fields: list[str] = Field(
        default_factory=lambda: ["encryption_key", "password"],
        description="敏感字段列表",
    )

    @field_validator("format")
    @classmethod
    def _validate_format(cls, v: str) -> str:
        """校验日志格式."""
        valid_formats = {"json", "text", "console"}
        if v not in valid_formats:
            raise ValueError(
                f"Invalid log format: {v}. Must be one of {valid_formats}"
            )
        return v

    @field_validator("level")
    @classmethod
    def _validate_level(cls, v: str) -> str:
        """校验日志级别."""
        valid_levels = {"debug", "info", "warning", "error", "critical"}
        if v.lower() not in valid_levels:
            raise ValueError(
                f"Invalid log level: {v}. Must be one of {valid_levels}"
            )
        return v.lower()


class DevicesConfig(BaseModel):
    """设备注册表配置.

    Attributes:
        registry_type: 注册表类型（memory/sqlite）.
        db_path: SQLite 持久化时的数据库路径.
    """

    registry_type: str = Field(
        default="memory",
        description="设备注册表类型",
    )
    db_path: str = Field(
        default="./data/devices.db",
        description="SQLite 持久化数据库路径",
    )

    @field_validator("registry_type")
    @classmethod
    def _validate_registry_type(cls, v: str) -> str:
        """校验注册表类型."""
        valid_types = {"memory", "sqlite"}
        if v not in valid_types:
            raise ValueError(
                f"Invalid registry_type: {v}. Must be one of {valid_types}"
            )
        return v


# ---------------------------------------------------------------------------
# 根配置模型
# ---------------------------------------------------------------------------

class EdgeCloudConfig(BaseModel):
    """端云协同内核完整配置模型.

    整合所有子配置模块，提供统一的配置入口。
    支持 model_dump() 导出为 dict，model_validate() 从 dict 加载。

    Attributes:
        basic: 基础配置.
        security: 安全配置.
        sync: 同步配置.
        storage: 存储配置.
        offline: 离线配置.
        database: 数据库配置.
        logging: 日志配置.
        devices: 设备注册表配置.
    """

    basic: BasicConfig = Field(
        default_factory=BasicConfig,
        description="基础配置",
    )
    security: SecurityConfig = Field(
        default_factory=SecurityConfig,
        description="安全配置",
    )
    sync: SyncConfig = Field(
        default_factory=SyncConfig,
        description="同步配置",
    )
    storage: StorageConfig = Field(
        default_factory=StorageConfig,
        description="存储配置",
    )
    offline: OfflineConfig = Field(
        default_factory=OfflineConfig,
        description="离线配置",
    )
    database: DatabaseConfig = Field(
        default_factory=DatabaseConfig,
        description="数据库配置",
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig,
        description="日志配置",
    )
    devices: DevicesConfig = Field(
        default_factory=DevicesConfig,
        description="设备注册表配置",
    )

    # -----------------------------------------------------------------------
    # 便捷方法
    # -----------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """导出为嵌套字典.

        Returns:
            完整配置的字典表示.
        """
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EdgeCloudConfig":
        """从字典加载配置（自动校验）.

        Args:
            data: 配置字典.

        Returns:
            EdgeCloudConfig 实例.

        Raises:
            pydantic.ValidationError: 配置数据不合法时抛出.
        """
        return cls.model_validate(data)

    def get_by_dot_key(self, key: str, default: Any = None) -> Any:
        """按点路径获取配置值.

        Args:
            key: 点路径键名，如 "sync.interval".
            default: 路径不存在时返回的默认值.

        Returns:
            配置值，路径不存在返回 default.
        """
        parts = key.split(".")
        current: Any = self
        for part in parts:
            if isinstance(current, BaseModel):
                if hasattr(current, part):
                    current = getattr(current, part)
                else:
                    return default
            elif isinstance(current, dict):
                if part in current:
                    current = current[part]
                else:
                    return default
            else:
                return default
        return current

    def set_by_dot_key(self, key: str, value: Any) -> None:
        """按点路径设置配置值（设置后自动重新校验）.

        Args:
            key: 点路径键名，如 "sync.interval".
            value: 要设置的值.

        Raises:
            KeyError: 路径不存在时抛出.
            pydantic.ValidationError: 值不合法时抛出.
        """
        parts = key.split(".")
        if len(parts) < 2:
            raise KeyError(
                f"Invalid dot key '{key}': must have at least section.key format"
            )

        section_name = parts[0]
        if not hasattr(self, section_name):
            raise KeyError(f"Unknown config section: {section_name}")

        section = getattr(self, section_name)
        if not isinstance(section, BaseModel):
            raise KeyError(f"Section '{section_name}' is not a config model")

        # 找到目标字段所在的子模型
        current_model: BaseModel = section
        remaining_parts = parts[1:]

        for i, part in enumerate(remaining_parts[:-1]):
            if not hasattr(current_model, part):
                raise KeyError(
                    f"Key '{'.'.join(parts[:i + 2])}' not found in config"
                )
            nested = getattr(current_model, part)
            if not isinstance(nested, BaseModel):
                raise KeyError(
                    f"Key '{'.'.join(parts[:i + 2])}' is not a nested config model"
                )
            current_model = nested

        field_name = remaining_parts[-1]
        if not hasattr(current_model, field_name):
            raise KeyError(f"Key '{key}' not found in config")

        # 使用 model_copy + 新值来触发校验
        updated = current_model.model_copy(update={field_name: value})
        # 将更新后的子模型设置回父模型
        if len(remaining_parts) == 1:
            # 直接在根配置的 section 上
            object.__setattr__(self, section_name, updated)
        else:
            # 需要回溯设置到上层
            # 重新构建路径来设置
            self._set_nested_model(section_name, remaining_parts[:-1], updated)

    def _set_nested_model(
        self,
        section_name: str,
        path_parts: list[str],
        new_model: BaseModel,
    ) -> None:
        """设置嵌套子模型（内部辅助方法）.

        Args:
            section_name: 顶层 section 名称.
            path_parts: 从 section 下到目标父模型的路径部分.
            new_model: 新的子模型实例.
        """
        # 获取顶层 section
        section = getattr(self, section_name)
        if not path_parts:
            object.__setattr__(self, section_name, new_model)
            return

        # 沿路径找到父模型
        current = section
        for part in path_parts[:-1]:
            current = getattr(current, part)

        # 设置到父模型
        target_field = path_parts[-1]
        updated_parent = current.model_copy(update={target_field: new_model})

        # 回溯更新到根
        self._set_nested_model(section_name, path_parts[:-1], updated_parent)

    def key_exists(self, key: str) -> bool:
        """检查点路径 key 是否存在.

        Args:
            key: 点路径键名.

        Returns:
            True 表示存在.
        """
        parts = key.split(".")
        current: Any = self
        for part in parts:
            if isinstance(current, BaseModel):
                if hasattr(current, part):
                    current = getattr(current, part)
                else:
                    return False
            elif isinstance(current, dict):
                if part in current:
                    current = current[part]
                else:
                    return False
            else:
                return False
        return True
