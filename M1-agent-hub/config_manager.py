"""
M1 调度中心 - 配置管理中心

灵感来源：Consul / etcd / Spring Cloud Config

支持 YAML/JSON 配置文件，环境变量插值，
热重载（文件变化自动刷新），嵌套字典点号访问，
必填配置校验，敏感字段自动脱敏。

所有硬编码参数均可通过配置中心外部化管理。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import structlog

try:
    from pydantic import BaseModel, Field, field_validator, ConfigDict
    from pydantic import ValidationError as PydanticValidationError

    _PYDANTIC_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _PYDANTIC_AVAILABLE: bool = False
    # 降级：定义占位类，避免运行时 ImportError
    class BaseModel:  # type: ignore[no-redef]
        pass

    def Field(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        return None

    class PydanticValidationError(Exception):  # type: ignore[no-redef]
        pass

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ── Pydantic 配置模型 ────────────────────────────────────────────────────────
# [V12.0] 配置模型已迁移至 models/config.py 统一管理。
# 优先从 models 包导入，失败时回退到本地定义以保持向后兼容。

try:
    from models.config import (
        M1Config,
        ServerConfig,
        DatabaseConfig,
        MessageBusConfig,
        FederationConfig,
        AgentsConfig,
        MemoryConfig,
        SecurityConfig,
    )
    _config_models_imported = True
except ImportError:
    _config_models_imported = False

    # deprecated: use models.config.ServerConfig instead
    class ServerConfig(BaseModel):  # type: ignore[no-redef]
        """服务端配置子模型。"""

        model_config = ConfigDict(extra="allow")

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

    # deprecated: use models.config.DatabaseConfig instead
    class DatabaseConfig(BaseModel):  # type: ignore[no-redef]
        """数据库配置子模型。"""

        model_config = ConfigDict(extra="allow")

        db_path: str = "./data/m1.db"
        wal_mode: bool = True
        busy_timeout: int = 5000

    # deprecated: use models.config.MessageBusConfig instead
    class MessageBusConfig(BaseModel):  # type: ignore[no-redef]
        """消息总线配置子模型。"""

        model_config = ConfigDict(extra="allow")

        max_queue_size: int = 10000
        topic_pattern: str = "m1.*"

    # deprecated: use models.config.FederationConfig instead
    class FederationConfig(BaseModel):  # type: ignore[no-redef]
        """联邦调度配置子模型。"""

        model_config = ConfigDict(extra="allow")

        enabled: bool = True
        default_privacy_level: str = "L1"

    # deprecated: use models.config.AgentsConfig instead
    class AgentsConfig(BaseModel):  # type: ignore[no-redef]
        """Agent 管理配置子模型。"""

        model_config = ConfigDict(extra="allow")

        max_concurrent: int = 100
        default_timeout_s: int = 300

    # deprecated: use models.config.MemoryConfig instead
    class MemoryConfig(BaseModel):  # type: ignore[no-redef]
        """记忆系统配置子模型。"""

        model_config = ConfigDict(extra="allow")

        enabled: bool = True
        max_entries: int = 10000

    # deprecated: use models.config.SecurityConfig instead
    class SecurityConfig(BaseModel):  # type: ignore[no-redef]
        """安全配置子模型。"""

        model_config = ConfigDict(extra="allow")

        admin_key: str | None = None
        rate_limit_per_minute: int = 60

    # deprecated: use models.config.M1Config instead
    class M1Config(BaseModel):  # type: ignore[no-redef]
        """M1 调度中心配置校验 Schema。

        使用 Pydantic v2 风格的模型配置，允许额外字段（extra="allow"），
        仅对已知字段进行类型与范围校验，未知字段原样保留以保证向后兼容。
        """

        model_config = ConfigDict(extra="allow")

        server: ServerConfig = Field(default_factory=ServerConfig)
        database: DatabaseConfig = Field(default_factory=DatabaseConfig)
        message_bus: MessageBusConfig = Field(default_factory=MessageBusConfig)
        federation: FederationConfig = Field(default_factory=FederationConfig)
        agents: AgentsConfig = Field(default_factory=AgentsConfig)
        memory: MemoryConfig = Field(default_factory=MemoryConfig)
        security: SecurityConfig = Field(default_factory=SecurityConfig)


class ConfigValidationError(Exception):
    """配置校验异常

    当必填配置缺失或格式不合法时抛出。
    """


class ConfigManager:
    """配置管理中心

    加载外部配置文件，支持环境变量替换，
    提供类型安全的取值接口，支持必填校验和敏感字段脱敏。

    Attributes:
        _config: 内部存储的配置字典
        _config_path: 配置文件路径
        _last_modified: 配置文件上次修改时间
        _last_check: 上次检查文件变化的时间
        _check_interval: 热重载检查间隔（秒）
        _required_fields: 必填配置字段列表
        _sensitive_fields: 敏感字段名列表（用于脱敏）
        _logger: 结构化日志实例
    """

    # 必填配置字段（点号路径）
    # 启动时若这些字段缺失或为空，将抛出 ConfigValidationError
    _REQUIRED_FIELDS: list[str] = [
        "basic.name",
        "basic.version",
        "basic.port",
        "security.encryption_key",
        "security.jwt_secret",
    ]

    # 当前配置版本号，用于版本迁移
    _CURRENT_CONFIG_VERSION: int = 1

    def __init__(
        self,
        config_path: str | None = None,
        *,
        validate_on_load: bool = False,
        check_interval: float = 5.0,
    ) -> None:
        """初始化配置管理器

        配置加载优先级（从高到低）：
        1. 环境变量（M1_*、LLM_*、FEDERATION_*）
        2. 项目根目录 config/yunxi.env（全局配置）
        3. 指定的配置文件（YAML/JSON）
        4. 默认配置

        加载完成后执行：
        - 配置版本迁移（_migrate_config）
        - Pydantic Schema 校验（validate_schema）

        Args:
            config_path: 配置文件路径，为 None 时使用默认配置
            validate_on_load: 加载后是否立即执行必填校验
            check_interval: 热重载检查间隔（秒）
        """
        self._config: dict[str, Any] = {}
        self._config_path: str | None = config_path
        self._last_modified: float = 0.0
        self._last_check: float = 0.0
        self._check_interval: float = check_interval
        self._sensitive_fields: list[str] = [
            "password",
            "token",
            "api_key",
            "secret",
            "encryption_key",
            "admin_token",
            "admin_key",
            "internal_secret",
            "master_key",
            "jwt_secret",
        ]
        self._logger: structlog.stdlib.BoundLogger = logger.bind(service="config_manager")

        # 热加载回退相关状态
        # 上一版有效配置的深拷贝，热加载失败时用于回退
        self._last_valid_config: dict[str, Any] = {}
        # 上次热加载的成功状态
        self._reload_status: bool = True
        # 上次热加载失败的原因（成功时为空字符串）
        self._reload_error: str = ""

        # 配置变更回调注册表：key -> list[callback]
        self._change_callbacks: dict[str, list[Callable[[Any, Any], None]]] = {}

        # 1. 先加载默认配置作为基础
        self._load_defaults()

        # 2. 从全局配置文件 yunxi.env 加载（项目根目录 config/yunxi.env）
        self._load_yunxi_env()

        # 3. 从指定配置文件加载（如果存在）
        if config_path and Path(config_path).exists():
            self._load()

        # 4. 从环境变量加载（最高优先级，覆盖所有其他来源）
        self._load_from_env()

        # 5. 配置版本迁移
        self._config = self._migrate_config(self._config)

        # 6. Pydantic Schema 校验
        if _PYDANTIC_AVAILABLE:
            self.validate_schema()

        # 7. 保存首份有效配置快照
        self._last_valid_config = json.loads(json.dumps(self._config))

        if validate_on_load:
            self.validate_required()

    # ── yunxi.env 全局配置加载 ──────────────────────────────────────────────────

    @staticmethod
    def _find_project_root() -> Path | None:
        """查找 yunxi-project 项目根目录

        从当前文件位置向上查找，找到包含 config/yunxi.env 的目录。
        """
        current = Path(__file__).resolve()
        for _ in range(10):
            current = current.parent
            if (current / "config" / "yunxi.env").exists():
                return current
        return None

    def _load_yunxi_env(self) -> None:
        """从项目根目录的 config/yunxi.env 加载全局配置

        使用 python-dotenv 或手动解析 .env 文件。
        不覆盖已有的环境变量。
        """
        project_root = self._find_project_root()
        if not project_root:
            return
        env_path = project_root / "config" / "yunxi.env"
        if not env_path.exists():
            return

        try:
            from dotenv import load_dotenv
            load_dotenv(env_path, override=False)
            self._logger.info("yunxi_env_loaded", path=str(env_path))
        except ImportError:
            # python-dotenv 不可用时手动解析
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
                self._logger.info("yunxi_env_loaded_manual", path=str(env_path))
            except Exception as exc:
                self._logger.warning("yunxi_env_load_failed", error=str(exc))

    def _load_from_env(self) -> None:
        """从环境变量加载配置（最高优先级）

        将 yunxi.env 中定义的 M1_*、LLM_*、FEDERATION_* 等变量
        映射到内部配置的点号路径。
        """
        env_mappings: dict[str, tuple[str, Callable[[str], Any] | None]] = {
            # 基础配置
            "M1_NAME": ("basic.name", str),
            "M1_PORT": ("basic.port", int),
            "M1_HOST": ("basic.host", str),
            "YUNXI_ENV": ("basic.env", str),
            "YUNXI_LOG_LEVEL": ("basic.log_level", str),
            # 安全配置
            "M1_ENCRYPTION_KEY": ("security.encryption_key", str),
            "M1_ADMIN_TOKEN": ("security.admin_token", str),
            "M1_JWT_SECRET": ("security.jwt_secret", str),
            "FEDERATION_MASTER_KEY": ("security.master_key", str),
            "FEDERATION_ADMIN_KEY": ("security.admin_key", str),
            "FEDERATION_INTERNAL_SECRET": ("security.internal_secret", str),
            # LLM 配置
            "LLM_API_KEY": ("llm.api_key", str),
            "LLM_BASE_URL": ("llm.base_url", str),
            "LLM_MODEL": ("llm.model", str),
            "LLM_TIMEOUT": ("llm.timeout", int),
            # 数据库配置
            "M1_DATABASE_URL": ("database.url", str),
            # CORS
            "CORS_ORIGINS": ("security.cors_origins", lambda v: [x.strip() for x in v.split(",") if x.strip()]),
        }

        for env_key, (config_path, converter) in env_mappings.items():
            value = os.environ.get(env_key)
            if value is not None and value != "":
                try:
                    if converter and callable(converter) and converter is not str:
                        converted = converter(value)
                    else:
                        converted = value
                    self.set(config_path, converted)
                except (ValueError, TypeError):
                    pass

        # 特殊处理：LLM_PROVIDER 映射到内部 provider_type
        # deepseek / openai / ollama 等兼容 OpenAI API 的都映射为 "openai"
        # mock 保持为 "mock"
        llm_provider = os.environ.get("LLM_PROVIDER", "").lower()
        if llm_provider:
            if llm_provider in ("mock", "test"):
                self.set("llm.provider_type", "mock")
            else:
                # deepseek, openai, ollama 等都走 OpenAI 兼容协议
                self.set("llm.provider_type", "openai")

        loaded_count = len([
            k for k in env_mappings
            if os.environ.get(k) and os.environ.get(k) != ""
        ])
        self._logger.info("env_config_loaded", vars=loaded_count)

    # ── 默认配置 ──────────────────────────────────────────────────────────────

    def _load_defaults(self) -> None:
        """加载默认配置

        默认配置与 config.example.yaml 结构保持一致，
        同时保留历史模块的默认值以保证向后兼容。
        """
        self._config = {
            # 元信息（版本迁移用）
            "meta": {
                "config_version": 1,
            },
            # 基础配置
            "basic": {
                "name": "m1-scheduler",
                "version": "11.1.0",
                "port": 8001,
                "log_level": "info",
                "env": "development",
            },
            # 安全配置
            "security": {
                "encryption_key": "",
                "admin_token": "",
                "admin_key": "",
                "internal_secret": "",
                "master_key": "",
                "cors_origins": [
                    "http://localhost:3000",
                    "http://localhost:8080",
                ],
                "jwt_secret": "",
            },
            # 数据库配置
            "database": {
                "type": "sqlite",
                "path": "./data/m1.db",
            },
            # 调度器配置
            "scheduler": {
                "max_concurrent_tasks": 100,
                "queue_size": 1000,
                "default_timeout": 300,
                "retry": {
                    "max_attempts": 3,
                    "backoff": "exponential",
                    "initial_delay": 1,
                },
            },
            # 联邦配置
            "federation": {
                "enabled": True,
                "nodes": [],
                "sync_interval": 60,
                "desensitization": {
                    "default_level": "L1",
                    "rules": [],
                },
            },
            # 模块配置
            "modules": {
                "m2": {
                    "enabled": True,
                    "endpoint": "http://localhost:8002",
                },
                "m3": {
                    "enabled": True,
                    "endpoint": "http://localhost:8003",
                },
            },
            # 日志配置
            "logging": {
                "format": "json",
                "level": "info",
                "file": "./logs/m1.log",
                "max_size": "100MB",
                "max_files": 10,
                "sensitive_fields": [
                    "password",
                    "token",
                    "api_key",
                    "secret",
                ],
            },
            # ── 以下为历史模块默认配置，保留向后兼容 ──
            # 消息总线
            "message_bus": {
                "max_queue_size": 10000,
                "consume_interval": 0.01,
            },
            # 任务分发
            "dispatcher": {
                "max_retries": 1,
                "timeout_factor": 0.8,
            },
            # 意图分类
            "intent_classifier": {
                "direct_threshold": 0.7,
                "confirm_threshold": 0.4,
            },
            # Guardrails
            "guardrails": {
                "max_content_length": 5000,
                "max_output_length": 5000,
                "rate_limit_per_minute": 60,
            },
            # 工作流
            "workflow": {
                "max_concurrent": 10,
            },
            # 记忆系统
            "memory": {
                "wm_ttl_seconds": 30.0,
                "stm_max_rounds": 20,
                "stm_max_sessions": 1000,
                "ltm_capacity": 1000,
                "ltm_forget_threshold": 0.3,
            },
            # 反思引擎
            "reflection": {
                "max_reflections": 1000,
            },
            # 自适应路由
            "adaptive_router": {
                "epsilon": 0.15,
                "min_samples": 5,
                "decay_factor": 0.95,
            },
            # 反馈
            "feedback": {
                "max_feedbacks": 5000,
            },
            # 熔断器
            "circuit_breaker": {
                "failure_threshold": 5,
                "recovery_timeout": 30.0,
                "half_open_max_calls": 3,
                "success_threshold": 2,
            },
            # 事件存储
            "event_store": {
                "max_events": 50000,
            },
            # LLM
            "llm": {
                "provider_type": "mock",
                "model": "gpt-4o-mini",
                "api_key": "",
                "base_url": "",
                "temperature": 0.7,
                "max_tokens": 2048,
            },
            # 流式输出
            "streaming": {
                "chunk_size": 4,
                "chunk_delay_ms": 5.0,
            },
            # 持久化
            "persistence": {
                "db_path": "yunxi_core.db",
            },
            # 插件加载
            "plugin_loader": {
                "plugin_dir": "./plugins",
                "watch_interval": 10.0,
                "auto_reload": True,
            },
            # 向量记忆
            "vector_memory": {
                "dimension": 128,
                "top_k": 5,
                "similarity_threshold": 0.7,
            },
            # MCP Server
            "mcp_server": {
                "enabled": True,
                "transport": "stdio",
                "name": "yunxi-core-mcp",
                "version": "5.0.0",
            },
        }
        self._logger.info("config_loaded_defaults")

    # ── 文件加载 ──────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """从文件加载配置

        支持 YAML 和 JSON 格式，加载前先进行环境变量替换。

        Raises:
            ImportError: 加载 YAML 但未安装 pyyaml
            Exception: 配置文件解析失败
        """
        if not self._config_path:
            return

        path = Path(self._config_path)
        if not path.exists():
            self._logger.warning("config_file_not_found", path=str(path))
            return

        try:
            content: str = path.read_text(encoding="utf-8")
            # 环境变量替换 ${VAR} 或 ${VAR:default}
            content = self._substitute_env_vars(content)

            loaded_config: dict[str, Any] = {}
            if path.suffix in (".yaml", ".yml"):
                try:
                    import yaml

                    loaded_config = yaml.safe_load(content) or {}
                except ImportError:
                    self._logger.error("yaml_not_installed")
                    raise
            elif path.suffix == ".json":
                loaded_config = json.loads(content)
            else:
                self._logger.warning("unsupported_config_format", suffix=path.suffix)
                return

            # 合并到默认配置（用户配置覆盖默认值）
            self._merge_config(self._config, loaded_config)

            # 从 logging.sensitive_fields 同步脱敏字段列表
            custom_sensitive = self.get_list("logging.sensitive_fields", [])
            for field in custom_sensitive:
                if field not in self._sensitive_fields:
                    self._sensitive_fields.append(field)

            self._last_modified = path.stat().st_mtime
            self._logger.info(
                "config_loaded",
                path=str(path),
                keys=list(loaded_config.keys()),
            )
        except Exception as exc:
            self._logger.error("config_load_failed", error=str(exc))
            raise

    def _merge_config(
        self,
        base: dict[str, Any],
        override: dict[str, Any],
    ) -> None:
        """递归合并配置字典

        以 override 的值覆盖 base 中的对应项，
        嵌套字典采用深度合并而非整体替换。

        Args:
            base: 基础配置字典（将被修改）
            override: 覆盖配置字典
        """
        for key, value in override.items():
            if (
                key in base
                and isinstance(base[key], dict)
                and isinstance(value, dict)
            ):
                self._merge_config(base[key], value)
            else:
                base[key] = value

    # ── 环境变量替换 ──────────────────────────────────────────────────────────

    def _substitute_env_vars(self, content: str) -> str:
        """替换 ${VAR} 和 ${VAR:default} 为环境变量值

        Args:
            content: 原始配置文本内容

        Returns:
            替换后的文本内容
        """

        def replacer(match: re.Match[str]) -> str:
            var_expr: str = match.group(1)
            if ":" in var_expr:
                var_name, default = var_expr.split(":", 1)
            else:
                var_name, default = var_expr, ""
            return os.getenv(var_name, default)

        return re.sub(r"\$\{([^}]+)\}", replacer, content)

    # ── 热重载 ────────────────────────────────────────────────────────────────

    def check_reload(self) -> bool:
        """检查文件是否变化并自动重载

        采用节流策略，检查间隔由 _check_interval 控制。

        热加载流程：
        1. 保存当前有效配置快照到 _last_valid_config
        2. 重新加载配置文件
        3. 执行 Pydantic Schema 校验
        4. 校验失败时自动回退到上一版有效配置，并记录 warning 日志
        5. 更新 reload_status 属性

        Returns:
            是否发生了重载（校验失败回退时也返回 True，因为触发了加载流程）
        """
        if not self._config_path:
            return False

        now: float = time.time()
        if now - self._last_check < self._check_interval:
            return False
        self._last_check = now

        path = Path(self._config_path)
        if not path.exists():
            return False

        mtime: float = path.stat().st_mtime
        if mtime > self._last_modified:
            self._logger.info("config_reload_triggered", path=str(path))

            # 保存当前有效配置快照，用于回退
            old_config_snapshot: dict[str, Any] = json.loads(json.dumps(self._config))

            try:
                # 重载前先重置为默认值，避免旧值残留
                self._load_defaults()
                self._load()
                self._load_from_env()

                # 配置版本迁移
                self._config = self._migrate_config(self._config)

                # Pydantic Schema 校验
                if _PYDANTIC_AVAILABLE:
                    self.validate_schema()

                # 校验通过，更新有效配置快照
                self._last_valid_config = json.loads(json.dumps(self._config))
                self._reload_status = True
                self._reload_error = ""

                # 触发变更回调
                self._fire_change_callbacks(old_config_snapshot)

                self._logger.info("config_reload_succeeded", path=str(path))
                return True

            except Exception as exc:
                # 校验失败：自动回退到上一版有效配置
                self._config = json.loads(json.dumps(self._last_valid_config))
                self._reload_status = False
                self._reload_error = str(exc)

                # 恢复文件修改时间，避免反复触发
                self._last_modified = mtime

                self._logger.warning(
                    "config_reload_failed_fallback",
                    path=str(path),
                    error=str(exc),
                    fallback_to="last_valid_config",
                )
                return True

        return False

    # ── 必填校验 ──────────────────────────────────────────────────────────────

    def validate_required(
        self,
        extra_fields: list[str] | None = None,
    ) -> None:
        """校验必填配置是否齐全

        检查所有必填字段是否存在且非空。
        若有缺失则抛出 ConfigValidationError。

        Args:
            extra_fields: 额外的必填字段列表（点号路径）

        Raises:
            ConfigValidationError: 当必填字段缺失或为空时
        """
        required: list[str] = list(self._REQUIRED_FIELDS)
        if extra_fields:
            required.extend(extra_fields)

        missing: list[str] = []
        for key in required:
            value = self.get(key)
            if value is None or (isinstance(value, str) and value.strip() == ""):
                missing.append(key)

        if missing:
            error_msg = (
                f"必填配置缺失: {', '.join(missing)}。"
                f"请在配置文件中设置这些字段，或通过环境变量注入。"
            )
            self._logger.error("config_validation_failed", missing=missing)
            raise ConfigValidationError(error_msg)

        self._logger.info("config_validation_passed", fields=len(required))

    # ── Pydantic Schema 校验 ──────────────────────────────────────────────────

    def validate_schema(self) -> None:
        """使用 Pydantic M1Config 模型对配置进行 Schema 校验。

        仅对 M1Config 模型中定义的字段分组进行类型与范围校验，
        额外字段（extra="allow"）不做校验，保证向后兼容。

        校验失败时抛出 ConfigurationError（从 exceptions.py 惰性导入），
        错误信息明确指出哪个字段、什么原因。

        Raises:
            ConfigurationError: 当 Pydantic 校验失败时抛出，
                detail 中包含每个错误字段的位置与原因。
        """
        if not _PYDANTIC_AVAILABLE:
            self._logger.debug("pydantic_not_available_skip_schema_validation")
            return

        try:
            # 使用 model_validate 进行校验（Pydantic v2 风格）
            M1Config.model_validate(self._config)
            self._logger.info("config_schema_validation_passed")
        except PydanticValidationError as exc:
            # 格式化错误信息：列出每个字段的位置与原因
            error_details: list[str] = []
            for err in exc.errors():
                loc = ".".join(str(x) for x in err.get("loc", []))
                msg = err.get("msg", "未知错误")
                error_details.append(f"字段 '{loc}': {msg}")

            error_msg = (
                f"配置 Schema 校验失败，共 {len(error_details)} 处错误：\n"
                + "\n".join(f"  - {d}" for d in error_details)
            )

            self._logger.error(
                "config_schema_validation_failed",
                error_count=len(error_details),
                errors=error_details,
            )

            # 惰性导入 ConfigurationError，避免循环导入
            try:
                from exceptions import ConfigurationError

                raise ConfigurationError(
                    detail=error_msg,
                    data={"validation_errors": error_details},
                ) from exc
            except ImportError:
                # 如果 exceptions 模块不可用，回退到内置异常
                raise ConfigValidationError(error_msg) from exc

    # ── 配置版本迁移 ──────────────────────────────────────────────────────────

    def _migrate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """将旧版本配置自动迁移到当前版本。

        读取 meta.config_version 字段，从旧版本逐步升级到 _CURRENT_CONFIG_VERSION。
        当前版本为 1，此方法为未来版本预留扩展点。

        迁移原则：
        - 不破坏现有配置结构，仅做字段重命名、默认值补充、格式转换
        - 每次版本升级独立一个 _migrate_v{N}_to_v{N+1} 方法
        - 迁移完成后更新 meta.config_version 为当前版本

        Args:
            config: 原始配置字典

        Returns:
            迁移后的配置字典
        """
        # 确保 meta 配置块存在
        if "meta" not in config or not isinstance(config["meta"], dict):
            config["meta"] = {}

        # 读取源版本号，默认 0（无版本标记的旧配置）
        source_version: int = int(config.get("meta", {}).get("config_version", 0))
        target_version: int = self._CURRENT_CONFIG_VERSION

        if source_version >= target_version:
            return config

        self._logger.info(
            "config_migration_started",
            from_version=source_version,
            to_version=target_version,
        )

        # 逐步迁移：v0 -> v1 -> v2 -> ...
        current_version = source_version
        migrations = {
            0: self._migrate_v0_to_v1,
            # 未来版本扩展点：
            # 1: self._migrate_v1_to_v2,
            # 2: self._migrate_v2_to_v3,
        }

        while current_version < target_version:
            migrate_fn = migrations.get(current_version)
            if migrate_fn is None:
                self._logger.warning(
                    "config_migration_no_handler",
                    from_version=current_version,
                )
                break
            config = migrate_fn(config)
            current_version += 1
            config["meta"]["config_version"] = current_version

        # 最终确认版本号
        config["meta"]["config_version"] = current_version

        self._logger.info(
            "config_migration_completed",
            from_version=source_version,
            to_version=current_version,
        )

        return config

    def _migrate_v0_to_v1(self, config: dict[str, Any]) -> dict[str, Any]:
        """从 v0（无版本标记）迁移到 v1。

        v1 变更：
        - 新增 meta.config_version = 1
        - 补充 server 配置块的默认值（从 basic 块迁移 host/port/log_level）
        - 补充 database.db_path 默认值（从 database.path 或 persistence.db_path 推断）
        - 补充 agents.max_concurrent / default_timeout_s
        - 补充 memory.enabled / max_entries

        仅在目标字段不存在时才迁移，避免覆盖用户已有的显式配置。

        Args:
            config: v0 配置字典

        Returns:
            v1 配置字典
        """
        # server 块：从 basic 推断
        if "server" not in config or not isinstance(config["server"], dict):
            config["server"] = {}

        basic = config.get("basic", {})
        if "host" not in config["server"] and isinstance(basic, dict) and "host" in basic:
            config["server"]["host"] = basic["host"]
        if "port" not in config["server"] and isinstance(basic, dict) and "port" in basic:
            config["server"]["port"] = basic["port"]
        if "log_level" not in config["server"] and isinstance(basic, dict) and "log_level" in basic:
            config["server"]["log_level"] = basic["log_level"]

        # database 块：db_path 从 database.path 或 persistence.db_path 推断
        if "database" not in config or not isinstance(config["database"], dict):
            config["database"] = {}

        db_section = config.get("database", {})
        if "db_path" not in config["database"]:
            if isinstance(db_section, dict) and "path" in db_section:
                config["database"]["db_path"] = db_section["path"]
            elif "persistence" in config and isinstance(config["persistence"], dict):
                config["database"]["db_path"] = config["persistence"].get("db_path", "./data/m1.db")

        # agents 块：从 scheduler / workflow 推断
        if "agents" not in config or not isinstance(config["agents"], dict):
            config["agents"] = {}

        scheduler = config.get("scheduler", {})
        workflow = config.get("workflow", {})
        if "max_concurrent" not in config["agents"]:
            if isinstance(scheduler, dict) and "max_concurrent_tasks" in scheduler:
                config["agents"]["max_concurrent"] = scheduler["max_concurrent_tasks"]
            elif isinstance(workflow, dict) and "max_concurrent" in workflow:
                config["agents"]["max_concurrent"] = workflow["max_concurrent"]
        if "default_timeout_s" not in config["agents"]:
            if isinstance(scheduler, dict) and "default_timeout" in scheduler:
                config["agents"]["default_timeout_s"] = scheduler["default_timeout"]

        # memory 块：从 memory 块迁移 enabled/max_entries
        if "memory" in config and isinstance(config["memory"], dict):
            mem = config["memory"]
            if "enabled" not in mem:
                mem["enabled"] = True
            if "max_entries" not in mem:
                # 从 ltm_capacity 或 stm_max_sessions 推断一个合理值
                if "ltm_capacity" in mem:
                    mem["max_entries"] = mem["ltm_capacity"]
                elif "stm_max_sessions" in mem:
                    mem["max_entries"] = mem["stm_max_sessions"]

        # security 块：rate_limit_per_minute 从 guardrails 推断
        if "security" not in config or not isinstance(config["security"], dict):
            config["security"] = {}

        guardrails = config.get("guardrails", {})
        if "rate_limit_per_minute" not in config["security"]:
            if isinstance(guardrails, dict) and "rate_limit_per_minute" in guardrails:
                config["security"]["rate_limit_per_minute"] = guardrails["rate_limit_per_minute"]

        self._logger.debug("config_migration_v0_to_v1_done")
        return config

    # ── 热加载状态属性 ────────────────────────────────────────────────────────

    @property
    def reload_status(self) -> bool:
        """上次热加载是否成功。

        Returns:
            True 表示上次热加载校验通过；
            False 表示上次热加载校验失败，已自动回退到上一版有效配置。
        """
        return self._reload_status

    @property
    def reload_error(self) -> str:
        """上次热加载失败的错误信息。

        Returns:
            失败原因字符串；成功时为空字符串。
        """
        return self._reload_error

    # ── 取值接口 ──────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """通过点号路径获取配置值

        Args:
            key: 点号分隔的路径，如 "scheduler.max_concurrent_tasks"
            default: 键不存在时返回的默认值

        Returns:
            配置值，若路径不存在则返回 default
        """
        parts: list[str] = key.split(".")
        value: Any = self._config
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value

    def get_int(self, key: str, default: int = 0) -> int:
        """获取整型配置

        Args:
            key: 点号路径
            default: 默认值

        Returns:
            整型配置值
        """
        value = self.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """获取浮点型配置

        Args:
            key: 点号路径
            default: 默认值

        Returns:
            浮点型配置值
        """
        value = self.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔型配置

        支持字符串形式的 true/1/yes/on 解析为 True。

        Args:
            key: 点号路径
            default: 默认值

        Returns:
            布尔型配置值
        """
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def get_str(self, key: str, default: str = "") -> str:
        """获取字符串配置

        Args:
            key: 点号路径
            default: 默认值

        Returns:
            字符串配置值
        """
        value = self.get(key, default)
        if value is None:
            return default
        return str(value)

    def get_dict(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        """获取字典配置

        Args:
            key: 点号路径
            default: 默认值

        Returns:
            字典配置值
        """
        value = self.get(key, default or {})
        if isinstance(value, dict):
            return value
        return default or {}

    def get_list(self, key: str, default: list[Any] | None = None) -> list[Any]:
        """获取列表配置

        Args:
            key: 点号路径
            default: 默认值

        Returns:
            列表配置值
        """
        value = self.get(key, default or [])
        if isinstance(value, list):
            return value
        return default or []

    def set(self, key: str, value: Any) -> None:
        """运行时设置配置值（内存中，不持久化到文件）

        Args:
            key: 点号路径，中间层级不存在时自动创建
            value: 要设置的值
        """
        parts: list[str] = key.split(".")
        config: dict[str, Any] = self._config
        for part in parts[:-1]:
            if part not in config or not isinstance(config[part], dict):
                config[part] = {}
            config = config[part]
        config[parts[-1]] = value

    # ── 敏感字段脱敏 ──────────────────────────────────────────────────────────

    def _is_sensitive_field(self, key: str) -> bool:
        """判断字段名是否属于敏感字段

        采用不区分大小写的包含匹配，即字段名中包含敏感关键词即视为敏感。

        Args:
            key: 字段名

        Returns:
            是否为敏感字段
        """
        key_lower: str = key.lower()
        return any(
            sensitive.lower() in key_lower
            for sensitive in self._sensitive_fields
        )

    def mask_sensitive(
        self,
        data: Any,
        mask_char: str = "*",
        keep_chars: int = 2,
    ) -> Any:
        """递归脱敏数据中的敏感字段

        对字典中的敏感字段值进行掩码处理，
        保留前后各 keep_chars 个字符，中间用 mask_char 填充。

        Args:
            data: 待脱敏的数据（字典、列表或基本类型）
            mask_char: 掩码字符
            keep_chars: 首尾保留的明文字符数

        Returns:
            脱敏后的数据
        """
        if isinstance(data, dict):
            result: dict[str, Any] = {}
            for key, value in data.items():
                if self._is_sensitive_field(key) and isinstance(value, str):
                    result[key] = self._mask_value(value, mask_char, keep_chars)
                else:
                    result[key] = self.mask_sensitive(value, mask_char, keep_chars)
            return result
        elif isinstance(data, list):
            return [self.mask_sensitive(item, mask_char, keep_chars) for item in data]
        else:
            return data

    @staticmethod
    def _mask_value(value: str, mask_char: str, keep_chars: int) -> str:
        """对单个字符串值进行掩码处理

        Args:
            value: 原始字符串
            mask_char: 掩码字符
            keep_chars: 首尾保留的明文字符数

        Returns:
            脱敏后的字符串
        """
        if not value:
            return value
        length: int = len(value)
        if length <= keep_chars * 2:
            return mask_char * length
        return (
            value[:keep_chars]
            + mask_char * (length - keep_chars * 2)
            + value[-keep_chars:]
        )

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def to_dict(self, *, mask_sensitive: bool = False) -> dict[str, Any]:
        """导出完整配置字典

        Args:
            mask_sensitive: 是否对敏感字段脱敏

        Returns:
            配置字典的副本
        """
        config_copy: dict[str, Any] = json.loads(json.dumps(self._config))
        if mask_sensitive:
            config_copy = self.mask_sensitive(config_copy)
        return config_copy

    def export_to_file(
        self,
        path: str,
        format: str = "json",
        *,
        mask_sensitive: bool = False,
    ) -> None:
        """导出配置到文件

        Args:
            path: 输出文件路径
            format: 导出格式：json / yaml / yml
            mask_sensitive: 是否对敏感字段脱敏

        Raises:
            ImportError: YAML 导出需要 pyyaml
            ValueError: 不支持的格式
        """
        output_path = Path(path)
        config = self.to_dict(mask_sensitive=mask_sensitive)

        if format == "json":
            output_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif format in ("yaml", "yml"):
            try:
                import yaml

                output_path.write_text(
                    yaml.dump(
                        config,
                        allow_unicode=True,
                        default_flow_style=False,
                    ),
                    encoding="utf-8",
                )
            except ImportError:
                raise ImportError("PyYAML is required for YAML export")
        else:
            raise ValueError(f"Unsupported format: {format}")

        self._logger.info("config_exported", path=path, format=format)

    def add_sensitive_field(self, field_name: str) -> None:
        """添加自定义敏感字段

        Args:
            field_name: 敏感字段名（不区分大小写的包含匹配）
        """
        if field_name not in self._sensitive_fields:
            self._sensitive_fields.append(field_name)

    def on_change(
        self,
        key: str,
        callback: Callable[[Any, Any], None],
    ) -> None:
        """注册配置变更回调（可选功能）

        当 check_reload 检测到指定键的值发生变化时，
        调用回调函数 (old_value, new_value) -> None。

        注意：当前实现为轻量级回调注册，
        如需完整的订阅/发布机制建议结合消息总线使用。

        Args:
            key: 监听的配置键（点号路径）
            callback: 变更回调函数
        """
        if key not in self._change_callbacks:
            self._change_callbacks[key] = []
        self._change_callbacks[key].append(callback)

    def _fire_change_callbacks(self, old_config: dict[str, Any]) -> None:
        """触发所有配置变更回调

        Args:
            old_config: 变更前的配置字典
        """
        for key, callbacks in self._change_callbacks.items():
            old_val = self._get_from_dict(old_config, key)
            new_val = self.get(key)
            if old_val != new_val:
                for callback in callbacks:
                    try:
                        callback(old_val, new_val)
                    except Exception as exc:
                        self._logger.error(
                            "config_change_callback_failed",
                            key=key,
                            error=str(exc),
                        )

    @staticmethod
    def _get_from_dict(data: dict[str, Any], key: str) -> Any:
        """从字典中按点号路径取值

        Args:
            data: 字典数据
            key: 点号路径

        Returns:
            对应的值，不存在返回 None
        """
        parts = key.split(".")
        value: Any = data
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        return value
