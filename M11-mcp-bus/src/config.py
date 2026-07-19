"""M11 MCP Bus - 配置模块.

统一配置框架迁移版（AR-002）：
- 新接口：M11ModuleConfig（继承 BaseConfig，基于 pydantic-settings）
- 旧接口：Settings 类（保留，内部委托给 M11ModuleConfig，向后兼容）

从环境变量和 .env 文件加载配置，提供单例访问。
"""

from __future__ import annotations

import os
import secrets
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import structlog
from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

logger = structlog.get_logger(__name__)


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
    _USE_UNIFIED_CONFIG_M11 = True
except ImportError:
    _USE_UNIFIED_CONFIG_M11 = False
    BaseConfig = None  # type: ignore
    EnvType = None  # type: ignore


# ============================================================
# 路径工具
# ============================================================

def _default_db_path() -> str:
    """默认数据库路径"""
    return "~/.yunxi/m11_bus.db"


# ============================================================
# M11 模块统一配置类（新接口）
# ============================================================

if _USE_UNIFIED_CONFIG_M11:

    class M11ModuleConfig(BaseConfig):
        """
        M11 MCP 总线配置（统一配置框架版）

        继承自 BaseConfig，自动获得：
        - .env 文件加载（config/yunxi.env）
        - 环境变量覆盖（优先级最高）
        - 生产环境敏感字段校验
        - 敏感字段脱敏输出
        - 配置热更新

        环境变量前缀：M11_
        """

        module_name: str = Field(default="m11-mcp-bus", description="模块名称")
        port: int = Field(default=8011, ge=1, le=65535, description="服务监听端口")
        host: str = Field(default="0.0.0.0", description="监听地址")

        # ---------- 安全配置 ----------
        api_key_auth_enabled: bool = Field(
            default=True, description="是否启用 API Key 鉴权，默认启用"
        )
        mcp_require_auth: bool = Field(
            default=True, description="MCP 端点是否需要鉴权，默认启用"
        )
        mcp_default_api_key: str = Field(
            default="",
            description="MCP 默认 API Key（仅开发环境自动生成，生产环境必须显式配置）",
        )

        # ---------- 数据库配置 ----------
        db_path: str = Field(
            default_factory=_default_db_path, description="SQLite 数据库路径"
        )

        # ---------- 业务配置 ----------
        heartbeat_timeout: int = Field(
            default=30, ge=1, description="心跳超时时间（秒）"
        )
        tool_refresh_interval: int = Field(
            default=300, ge=1, description="工具刷新间隔（秒）"
        )
        sse_heartbeat_interval: int = Field(
            default=30, ge=1, description="SSE 心跳间隔（秒）"
        )
        sse_max_clients: int = Field(
            default=100, ge=1, description="SSE 最大连接数"
        )

        # ---------- 熔断与重试配置 ----------
        retry_max_attempts: int = Field(
            default=2, ge=0, description="工具调用最大重试次数"
        )
        retry_base_delay_ms: int = Field(
            default=100, ge=0, description="重试基础延迟（毫秒），指数退避"
        )
        circuit_breaker_fail_threshold: int = Field(
            default=5, ge=1, description="熔断器连续失败阈值"
        )
        circuit_breaker_open_duration: int = Field(
            default=30, ge=1, description="熔断器打开持续时间（秒）"
        )
        circuit_breaker_half_open_limit: int = Field(
            default=1, ge=1, description="半开状态放行请求数"
        )

        # ---------- Redis 配置 ----------
        redis_url: str = Field(
            default="", description="Redis 连接 URL（为空表示不启用 Redis）"
        )
        redis_prefix: str = Field(default="m11:", description="Redis Key 前缀")
        redis_timeout: int = Field(
            default=5, ge=1, description="Redis 操作超时时间（秒）"
        )

        # ---------- 沙箱安全配置 ----------
        sandbox_level: int = Field(
            default=1, ge=0, le=3,
            description="沙箱安全级别：0=无限制, 1=基础隔离(默认), 2=严格隔离, 3=最大安全(Docker)"
        )
        sandbox_timeout: int = Field(
            default=30, ge=1, le=3600,
            description="沙箱执行超时时间（秒）"
        )
        sandbox_max_output_size: int = Field(
            default=1048576, ge=1024,
            description="沙箱最大输出大小（字节，默认 1MB）"
        )
        sandbox_max_string_length: int = Field(
            default=10000, ge=1,
            description="沙箱参数字符串最大长度"
        )
        sandbox_max_list_length: int = Field(
            default=1000, ge=1,
            description="沙箱参数列表最大长度"
        )
        sandbox_max_dict_keys: int = Field(
            default=1000, ge=1,
            description="沙箱参数字典最大键数"
        )
        sandbox_max_nesting_depth: int = Field(
            default=10, ge=1, le=100,
            description="沙箱参数最大嵌套深度"
        )
        rate_limit_per_tool: int = Field(
            default=100, ge=0,
            description="每工具每分钟调用限制（0 表示不限制）"
        )
        rate_limit_per_key: int = Field(
            default=1000, ge=0,
            description="每 API Key 每分钟调用限制（0 表示不限制）"
        )
        max_concurrent_executions: int = Field(
            default=10, ge=0,
            description="最大并发执行数（0 表示不限制）"
        )
        security_headers_enabled: bool = Field(
            default=True, description="是否启用安全响应头（CSP, X-Frame-Options 等）"
        )
        sandbox_working_directory: str = Field(
            default="",
            description="沙箱工作目录（仅 Level 2+ 生效，空表示不限制）"
        )

        # ---------- stdio 传输配置 ----------
        stdio_enabled: bool = Field(
            default=True, description="是否启用 stdio 传输支持"
        )
        stdio_max_services: int = Field(
            default=10, ge=1, description="最大同时运行的 stdio 服务数"
        )
        stdio_start_timeout: int = Field(
            default=10, ge=1, description="stdio 服务启动超时时间（秒）"
        )
        stdio_stop_timeout: int = Field(
            default=5, ge=1, description="stdio 服务停止超时时间（秒）"
        )

        model_config = SettingsConfigDict(
            env_prefix="M11_",
            env_file=".env",
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="allow",
            validate_assignment=True,
        )

        # ============================================================
        # 校验：生产环境安全配置
        # ============================================================

        @model_validator(mode="after")
        def _validate_mcp_security(self) -> "M11ModuleConfig":
            """
            MCP 安全配置校验（SEC-001 安全加固）。

            生产环境：
            - MCP 鉴权必须启用
            - 禁止使用空/默认 API Key
            开发环境：
            - 未配置时自动生成随机 API Key 并打印警告
            """
            if self.is_production:
                # 生产环境：MCP 鉴权必须启用
                if not self.mcp_require_auth:
                    raise ValueError(
                        "生产环境下 MCP 鉴权必须启用（M11_MCP_REQUIRE_AUTH=true），"
                        "禁止在生产环境中关闭 MCP 端点认证"
                    )
                # 生产环境：禁止使用空 API Key
                if not self.mcp_default_api_key:
                    raise ValueError(
                        "生产环境下必须显式配置 MCP API Key（M11_MCP_DEFAULT_API_KEY），"
                        "禁止使用空值或默认开发密钥"
                    )
            elif self.is_development:
                # 开发环境：未配置时自动生成随机 API Key
                if self.mcp_require_auth and not self.mcp_default_api_key:
                    random_key = "m11-dev-" + secrets.token_hex(16)
                    self.mcp_default_api_key = random_key
                    logger.warning(
                        "m11.security.mcp_auto_generated_key",
                        message="MCP 端点未配置 API Key，开发环境已自动生成临时密钥。"
                                "请通过 M11_MCP_DEFAULT_API_KEY 环境变量配置自定义密钥，"
                                "或在数据库中创建正式 API Key。",
                        generated_key_preview=random_key[:16] + "..." + random_key[-8:],
                    )

            # admin_token 警告（BaseConfig 已处理生产环境校验，这里仅开发环境警告）
            if not self.admin_token and not self.is_production:
                logger.warning(
                    "m11.security.admin_token_not_set",
                    message="M11_ADMIN_TOKEN 未设置，M8 对接鉴权将处于不安全状态，"
                            "请在环境变量中配置 M11_ADMIN_TOKEN",
                )

            return self

        # ============================================================
        # 便捷属性
        # ============================================================

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
        def use_redis(self) -> bool:
            """是否启用 Redis（根据 redis_url 是否为空判断）."""
            return bool(self.redis_url)

        @property
        def cors_origin_list(self) -> list[str]:
            """获取 CORS 来源列表."""
            if not self.cors_origins or self.cors_origins == "*":
                return ["*"]
            return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

        def ensure_data_dir(self) -> None:
            """确保数据目录存在"""
            db_dir = self.db_file_path.parent
            db_dir.mkdir(parents=True, exist_ok=True)


    # ============================================================
    # 全局配置单例（新接口）
    # ============================================================

    _m11_unified_config: Optional[M11ModuleConfig] = None

    def get_m11_unified_config() -> M11ModuleConfig:
        """获取 M11 模块统一配置实例（单例模式）"""
        global _m11_unified_config
        if _m11_unified_config is None:
            _m11_unified_config = M11ModuleConfig()
            _m11_unified_config.ensure_data_dir()
        return _m11_unified_config

else:
    M11ModuleConfig = None  # type: ignore
    get_m11_unified_config = None  # type: ignore


# ============================================================
# 向后兼容：旧的 Settings 类
# ============================================================
# 内部委托给 M11ModuleConfig，对外保持完全相同的接口
# ============================================================

class Settings:
    """M11 服务配置（向后兼容层）.

    .. deprecated:: 2.0.0
        请使用 M11ModuleConfig 替代。
        旧的 Settings 类内部已委托给 M11ModuleConfig，
        接口保持不变，可继续使用。

    所有配置项均从环境变量读取，前缀为 M11_。
    """

    def __init__(self, **kwargs):
        if _USE_UNIFIED_CONFIG_M11 and M11ModuleConfig is not None:
            self._inner = M11ModuleConfig(**kwargs)
            self._inner.ensure_data_dir()
        else:
            self._inner = None
            self._fallback_init(**kwargs)

    def _fallback_init(self, **kwargs):
        """降级模式下的初始化（旧 BaseSettings 逻辑）"""
        # 基础配置
        self.host = kwargs.get("host", "0.0.0.0")
        self.port = int(kwargs.get("port", 8011))
        self.env = kwargs.get("env", "development")
        self.log_level = kwargs.get("log_level", "info")

        # 安全配置
        self.admin_token = kwargs.get("admin_token", "")
        self.api_key_auth_enabled = kwargs.get("api_key_auth_enabled", True)
        self.mcp_require_auth = kwargs.get("mcp_require_auth", True)
        self.mcp_default_api_key = kwargs.get(
            "mcp_default_api_key", ""
        )

        # 数据库
        self.db_path = kwargs.get("db_path", "~/.yunxi/m11_bus.db")

        # 业务配置
        self.heartbeat_timeout = int(kwargs.get("heartbeat_timeout", 30))
        self.tool_refresh_interval = int(kwargs.get("tool_refresh_interval", 300))
        self.sse_heartbeat_interval = int(kwargs.get("sse_heartbeat_interval", 30))
        self.sse_max_clients = int(kwargs.get("sse_max_clients", 100))

        # 熔断与重试
        self.retry_max_attempts = int(kwargs.get("retry_max_attempts", 2))
        self.retry_base_delay_ms = int(kwargs.get("retry_base_delay_ms", 100))
        self.circuit_breaker_fail_threshold = int(kwargs.get("circuit_breaker_fail_threshold", 5))
        self.circuit_breaker_open_duration = int(kwargs.get("circuit_breaker_open_duration", 30))
        self.circuit_breaker_half_open_limit = int(kwargs.get("circuit_breaker_half_open_limit", 1))

        # Redis
        self.redis_url = kwargs.get("redis_url", "")
        self.redis_prefix = kwargs.get("redis_prefix", "m11:")
        self.redis_timeout = int(kwargs.get("redis_timeout", 5))

        # 沙箱安全配置
        self.sandbox_level = int(kwargs.get("sandbox_level", 1))
        self.sandbox_timeout = int(kwargs.get("sandbox_timeout", 30))
        self.sandbox_max_output_size = int(kwargs.get("sandbox_max_output_size", 1048576))
        self.sandbox_max_string_length = int(kwargs.get("sandbox_max_string_length", 10000))
        self.sandbox_max_list_length = int(kwargs.get("sandbox_max_list_length", 1000))
        self.sandbox_max_dict_keys = int(kwargs.get("sandbox_max_dict_keys", 1000))
        self.sandbox_max_nesting_depth = int(kwargs.get("sandbox_max_nesting_depth", 10))
        self.rate_limit_per_tool = int(kwargs.get("rate_limit_per_tool", 100))
        self.rate_limit_per_key = int(kwargs.get("rate_limit_per_key", 1000))
        self.max_concurrent_executions = int(kwargs.get("max_concurrent_executions", 10))
        self.security_headers_enabled = kwargs.get("security_headers_enabled", True)
        self.sandbox_working_directory = kwargs.get("sandbox_working_directory", "")

        # stdio
        self.stdio_enabled = kwargs.get("stdio_enabled", True)
        self.stdio_max_services = int(kwargs.get("stdio_max_services", 10))
        self.stdio_start_timeout = int(kwargs.get("stdio_start_timeout", 10))
        self.stdio_stop_timeout = int(kwargs.get("stdio_stop_timeout", 5))

        # CORS
        self.cors_origins = kwargs.get(
            "cors_origins",
            "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
        )

    # ---- 属性访问委托 ----

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(f"'Settings' object has no attribute '{name}'")
        if self._inner is not None:
            try:
                return getattr(self._inner, name)
            except AttributeError:
                raise AttributeError(f"'Settings' object has no attribute '{name}'")
        raise AttributeError(f"'Settings' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        elif hasattr(self, "_inner") and self._inner is not None and hasattr(self._inner, name):
            setattr(self._inner, name, value)
        else:
            super().__setattr__(name, value)

    # ---- 便捷属性（统一框架下直接委托，降级模式手动实现） ----

    @property
    def db_file_path(self) -> Path:
        """获取解析后的数据库文件路径."""
        if self._inner is not None:
            return self._inner.db_file_path
        expanded = os.path.expanduser(self.db_path)
        return Path(expanded).resolve()

    @property
    def db_url(self) -> str:
        """获取 SQLAlchemy 数据库 URL."""
        if self._inner is not None:
            return self._inner.db_url
        return f"sqlite:///{self.db_file_path}"

    @property
    def is_development(self) -> bool:
        """是否为开发环境."""
        if self._inner is not None:
            return self._inner.is_development
        return self.env == "development"

    @property
    def is_production(self) -> bool:
        """是否为生产环境."""
        if self._inner is not None:
            return self._inner.is_production
        return self.env == "production"

    @property
    def use_redis(self) -> bool:
        """是否启用 Redis（根据 redis_url 是否为空判断）."""
        if self._inner is not None:
            return self._inner.use_redis
        return bool(self.redis_url)

    @property
    def cors_origin_list(self) -> list[str]:
        """获取 CORS 来源列表."""
        if self._inner is not None:
            return self._inner.cors_origin_list
        if not self.cors_origins or self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


# ============================================================
# 全局配置单例（旧接口，向后兼容）
# ============================================================

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取配置单例.

    使用 lru_cache 确保整个应用只创建一个 Settings 实例。
    启动时校验安全密钥配置，若 admin_token 为空则记录警告。
    同时校验 MCP 认证配置：生产环境必须显式配置 API Key。

    Returns:
        Settings 配置实例

    Raises:
        RuntimeError: 生产环境下 MCP 认证关闭或使用默认 key 时抛出
    """
    settings = Settings()
    # 生产环境校验（如果使用统一配置框架，已在 model_validator 中处理）
    if settings._inner is None and settings.is_production:
        if not settings.mcp_require_auth:
            raise RuntimeError(
                "生产环境下 MCP 鉴权必须启用（M11_MCP_REQUIRE_AUTH=true），"
                "禁止在生产环境中关闭 MCP 端点认证"
            )
        if not settings.mcp_default_api_key:
            raise RuntimeError(
                "生产环境下必须显式配置 MCP API Key（M11_MCP_DEFAULT_API_KEY），"
                "禁止使用空值或默认开发密钥"
            )
    return settings


def reload_settings() -> Settings:
    """重新加载配置（清除缓存）.

    Returns:
        新的 Settings 配置实例
    """
    get_settings.cache_clear()
    # 如果使用统一配置，也触发热更新
    if _USE_UNIFIED_CONFIG_M11 and _m11_unified_config is not None:
        _m11_unified_config.reload()
    return get_settings()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 新接口
    "M11ModuleConfig",
    "get_m11_unified_config",
    # 旧接口（向后兼容）
    "Settings",
    "get_settings",
    "reload_settings",
    # 状态标记
    "_USE_UNIFIED_CONFIG_M11",
]
