"""
M7 工作流构建器 - 统一配置框架接入（AR-002 收尾）

M7ModuleConfig 继承 BaseConfig，作为配置的唯一真源。
Settings 类作为向后兼容层，内部委托给 M7ModuleConfig。

配置项清单：
+---------------------------+---------------------------------+-----------------------------+----------+
| 配置项                    | 环境变量名                     | 默认值                      | 说明     |
+===========================+=================================+=============================+==========+
| module_name               | M7_MODULE_NAME                 | m7-workflow-builder         | 模块名称 |
+---------------------------+---------------------------------+-----------------------------+----------+
| host                      | M7_HOST                        | 0.0.0.0                     | 监听地址 |
+---------------------------+---------------------------------+-----------------------------+----------+
| port                      | M7_PORT                        | 8007                        | 监听端口 |
+---------------------------+---------------------------------+-----------------------------+----------+
| env                       | M7_ENV                         | development                 | 运行环境 |
+---------------------------+---------------------------------+-----------------------------+----------+
| log_level                 | M7_LOG_LEVEL                   | info                        | 日志级别 |
+---------------------------+---------------------------------+-----------------------------+----------+
| admin_token               | M7_ADMIN_TOKEN                 | 生产:必填/开发:随机        | 管理令牌 |
+---------------------------+---------------------------------+-----------------------------+----------+
| cors_origins              | M7_CORS_ORIGINS                | *                           | CORS来源 |
+---------------------------+---------------------------------+-----------------------------+----------+
| data_path                 | M7_DATA_PATH                   | ~/.yunxi/m7_workflows.json | 数据路径 |
+---------------------------+---------------------------------+-----------------------------+----------+
| temp_dir                  | M7_TEMP_DIR                    | ~/.yunxi/m7_temp           | 临时目录 |
+---------------------------+---------------------------------+-----------------------------+----------+
| max_running_workflows     | M7_MAX_RUNNING_WORKFLOWS       | 10                          | 最大并发工作流 |
+---------------------------+---------------------------------+-----------------------------+----------+
| workflow_timeout          | M7_WORKFLOW_TIMEOUT            | 300                         | 工作流超时(秒) |
+---------------------------+---------------------------------+-----------------------------+----------+
| block_timeout             | M7_BLOCK_TIMEOUT               | 60                          | 节点超时(秒) |
+---------------------------+---------------------------------+-----------------------------+----------+
| max_parallel_nodes        | M7_MAX_PARALLEL_NODES          | 5                           | 最大并行节点数 |
+---------------------------+---------------------------------+-----------------------------+----------+
| m2_base_url               | M7_M2_BASE_URL                 | http://localhost:8002      | M2技能集群地址 |
+---------------------------+---------------------------------+-----------------------------+----------+
| m2_admin_token            | M2_ADMIN_TOKEN                 | ""                          | M2管理令牌 |
+---------------------------+---------------------------------+-----------------------------+----------+
"""

from __future__ import annotations

import os
import secrets
import sys
import warnings
from pathlib import Path
from typing import Optional

try:
    _current_m7_cfg = Path(__file__).resolve()
    for _ in range(10):
        _current_m7_cfg = _current_m7_cfg.parent
        if (_current_m7_cfg / "shared" / "core" / "config.py").exists():
            if str(_current_m7_cfg) not in sys.path:
                sys.path.insert(0, str(_current_m7_cfg))
            break
    from shared.core.config import BaseConfig, EnvType
    from pydantic import Field, model_validator
    from pydantic_settings import SettingsConfigDict
    _USE_UNIFIED_CONFIG_M7 = True
except ImportError:
    _USE_UNIFIED_CONFIG_M7 = False
    BaseConfig = None  # type: ignore
    EnvType = None  # type: ignore
    Field = None  # type: ignore
    SettingsConfigDict = None  # type: ignore


# ============================================================
# 工具函数
# ============================================================

def _default_data_path() -> str:
    """默认数据文件路径"""
    return os.path.join(os.path.expanduser("~"), ".yunxi", "m7_workflows.json")


def _default_temp_dir() -> str:
    """默认临时目录路径"""
    return os.path.join(os.path.expanduser("~"), ".yunxi", "m7_temp")


# ============================================================
# M7 模块统一配置类（新接口 - 唯一真源）
# ============================================================

if _USE_UNIFIED_CONFIG_M7:

    class M7ModuleConfig(BaseConfig):
        """
        M7 工作流构建器配置（统一配置框架版）

        继承自 BaseConfig，自动获得：
        - .env 文件加载（config/yunxi.env）
        - 环境变量覆盖（优先级最高）
        - 生产环境敏感字段校验
        - 敏感字段脱敏输出
        - 配置热更新

        环境变量前缀：M7_
        这是 M7 配置的唯一真源。
        """

        # ---- 基础配置 ----
        module_name: str = Field(default="m7-workflow-builder", description="模块名称")
        port: int = Field(default=8007, ge=1, le=65535, description="服务监听端口")
        host: str = Field(default="0.0.0.0", description="监听地址")
        log_level: str = Field(default="info", description="日志级别")

        # ---- CORS ----
        cors_origins: str = Field(
            default="*",
            description="CORS 允许来源（逗号分隔，生产环境禁止使用 *）",
        )

        # ---- 数据存储 ----
        data_path: str = Field(
            default_factory=_default_data_path,
            description="工作流数据文件路径",
        )
        temp_dir: str = Field(
            default_factory=_default_temp_dir,
            description="临时文件目录",
        )

        # ---- 执行引擎 ----
        max_running_workflows: int = Field(
            default=10, ge=1, description="最大并发运行工作流数",
        )
        workflow_timeout: int = Field(
            default=300, ge=1, description="单个工作流执行超时时间（秒）",
        )
        block_timeout: int = Field(
            default=60, ge=1, description="单个节点执行超时时间（秒）",
        )
        max_parallel_nodes: int = Field(
            default=5, ge=1, description="单个工作流最大并行节点数",
        )

        # ---- M2 技能集群对接 ----
        m2_base_url: str = Field(
            default="http://localhost:8002",
            description="M2 技能集群 API 地址",
        )
        m2_admin_token: str = Field(
            default="",
            description="M2 技能集群管理令牌",
        )

        model_config = SettingsConfigDict(
            env_prefix="M7_",
            env_file="config/yunxi.env",
            env_file_encoding="utf-8",
            extra="allow",
            validate_assignment=True,
        )

        @model_validator(mode="after")
        def _validate_admin_token(self) -> "M7ModuleConfig":
            """管理员 Token 校验（生产环境必填）"""
            if self.admin_token:
                return self

            if self.is_production:
                raise ValueError(
                    "生产环境必须配置 M7_ADMIN_TOKEN，禁止使用默认值。"
                    "请在环境变量或 config/yunxi.env 中设置 M7_ADMIN_TOKEN。"
                )

            # 开发环境生成随机一次性令牌
            import logging
            logger = logging.getLogger(__name__)
            self.admin_token = secrets.token_urlsafe(32)
            logger.warning(
                "开发环境未配置 M7_ADMIN_TOKEN，已自动生成一次性随机 Token: %s",
                self.admin_token,
            )
            return self

        @property
        def data_file_path(self) -> Path:
            """获取解析后的数据文件路径"""
            expanded = os.path.expanduser(self.data_path)
            return Path(expanded).resolve()

        @property
        def temp_dir_path(self) -> Path:
            """获取解析后的临时目录路径"""
            expanded = os.path.expanduser(self.temp_dir)
            return Path(expanded).resolve()

        def ensure_dirs(self) -> None:
            """确保数据目录和临时目录存在"""
            self.data_file_path.parent.mkdir(parents=True, exist_ok=True)
            self.temp_dir_path.mkdir(parents=True, exist_ok=True)

    # 全局配置单例（新接口）
    _m7_unified_config: Optional[M7ModuleConfig] = None

    def get_m7_config() -> M7ModuleConfig:
        """获取 M7 模块配置实例（单例模式，统一配置框架）"""
        global _m7_unified_config
        if _m7_unified_config is None:
            _m7_unified_config = M7ModuleConfig()
            _m7_unified_config.ensure_dirs()
        return _m7_unified_config

else:
    M7ModuleConfig = None  # type: ignore
    get_m7_config = None  # type: ignore


# ============================================================
# 旧接口：Settings（向后兼容层 - DEPRECATED）
# ============================================================

_DEPRECATION_MSG_M7 = (
    "M7 Settings 和 settings 单例已废弃（deprecated），"
    "请使用 M7ModuleConfig 和 get_m7_config() 替代。"
    "详见 AR-002 统一配置迁移方案。"
)


class Settings:
    """M7 配置类（向后兼容层）

    .. deprecated:: 2.0.0
        请使用 M7ModuleConfig 替代。
        通过 get_m7_config() 获取新配置实例。

    兼容层设计：
    - 内部持有 M7ModuleConfig 实例（当统一配置可用时）
    - 所有属性访问委托给内部的新配置实例
    - 实例化时触发 DeprecationWarning
    """

    def __init__(self, _suppress_warning: bool = False):
        if not _suppress_warning:
            warnings.warn(_DEPRECATION_MSG_M7, DeprecationWarning, stacklevel=2)

        # 优先使用统一配置框架
        self._unified: Optional[M7ModuleConfig] = None
        if _USE_UNIFIED_CONFIG_M7:
            self._unified = get_m7_config()

        # 回退字段：当统一配置不可用时使用的默认值
        self._fallback_port: int = 8007
        self._fallback_host: str = "0.0.0.0"
        self._fallback_env: str = "development"
        self._fallback_log_level: str = "info"
        self._fallback_cors_origins: str = "*"
        self._fallback_admin_token: str = ""
        self._fallback_data_path: str = _default_data_path()
        self._fallback_temp_dir: str = _default_temp_dir()
        self._fallback_max_running_workflows: int = 10
        self._fallback_workflow_timeout: int = 300
        self._fallback_block_timeout: int = 60
        self._fallback_max_parallel_nodes: int = 5
        self._fallback_m2_base_url: str = "http://localhost:8002"
        self._fallback_m2_admin_token: str = ""

    # ---- 属性代理：优先从统一配置读取，回退到默认值 ----

    @property
    def host(self) -> str:
        if self._unified is not None:
            return self._unified.host
        return self._fallback_host

    @host.setter
    def host(self, value: str) -> None:
        if self._unified is not None:
            self._unified.host = value
        else:
            self._fallback_host = value

    @property
    def port(self) -> int:
        if self._unified is not None:
            return self._unified.port
        return self._fallback_port

    @port.setter
    def port(self, value: int) -> None:
        if self._unified is not None:
            self._unified.port = value
        else:
            self._fallback_port = value

    @property
    def env(self) -> str:
        if self._unified is not None:
            return self._unified.env.value
        return self._fallback_env

    @env.setter
    def env(self, value: str) -> None:
        if self._unified is not None:
            from shared.core.config import EnvType
            self._unified.env = EnvType(value)
        else:
            self._fallback_env = value

    @property
    def log_level(self) -> str:
        if self._unified is not None:
            return self._unified.log_level
        return self._fallback_log_level

    @log_level.setter
    def log_level(self, value: str) -> None:
        if self._unified is not None:
            self._unified.log_level = value
        else:
            self._fallback_log_level = value

    @property
    def cors_origins(self) -> str:
        if self._unified is not None:
            return self._unified.cors_origins
        return self._fallback_cors_origins

    @cors_origins.setter
    def cors_origins(self, value: str) -> None:
        if self._unified is not None:
            self._unified.cors_origins = value
        else:
            self._fallback_cors_origins = value

    @property
    def admin_token(self) -> str:
        if self._unified is not None:
            return self._unified.admin_token
        return self._fallback_admin_token

    @admin_token.setter
    def admin_token(self, value: str) -> None:
        if self._unified is not None:
            self._unified.admin_token = value
        else:
            self._fallback_admin_token = value

    @property
    def data_path(self) -> str:
        if self._unified is not None:
            return self._unified.data_path
        return self._fallback_data_path

    @data_path.setter
    def data_path(self, value: str) -> None:
        if self._unified is not None:
            self._unified.data_path = value
        else:
            self._fallback_data_path = value

    @property
    def temp_dir(self) -> str:
        if self._unified is not None:
            return self._unified.temp_dir
        return self._fallback_temp_dir

    @temp_dir.setter
    def temp_dir(self, value: str) -> None:
        if self._unified is not None:
            self._unified.temp_dir = value
        else:
            self._fallback_temp_dir = value

    @property
    def max_running_workflows(self) -> int:
        if self._unified is not None:
            return self._unified.max_running_workflows
        return self._fallback_max_running_workflows

    @max_running_workflows.setter
    def max_running_workflows(self, value: int) -> None:
        if self._unified is not None:
            self._unified.max_running_workflows = value
        else:
            self._fallback_max_running_workflows = value

    @property
    def workflow_timeout(self) -> int:
        if self._unified is not None:
            return self._unified.workflow_timeout
        return self._fallback_workflow_timeout

    @workflow_timeout.setter
    def workflow_timeout(self, value: int) -> None:
        if self._unified is not None:
            self._unified.workflow_timeout = value
        else:
            self._fallback_workflow_timeout = value

    @property
    def block_timeout(self) -> int:
        if self._unified is not None:
            return self._unified.block_timeout
        return self._fallback_block_timeout

    @block_timeout.setter
    def block_timeout(self, value: int) -> None:
        if self._unified is not None:
            self._unified.block_timeout = value
        else:
            self._fallback_block_timeout = value

    @property
    def max_parallel_nodes(self) -> int:
        if self._unified is not None:
            return self._unified.max_parallel_nodes
        return self._fallback_max_parallel_nodes

    @max_parallel_nodes.setter
    def max_parallel_nodes(self, value: int) -> None:
        if self._unified is not None:
            self._unified.max_parallel_nodes = value
        else:
            self._fallback_max_parallel_nodes = value

    @property
    def m2_base_url(self) -> str:
        if self._unified is not None:
            return self._unified.m2_base_url
        return self._fallback_m2_base_url

    @m2_base_url.setter
    def m2_base_url(self, value: str) -> None:
        if self._unified is not None:
            self._unified.m2_base_url = value
        else:
            self._fallback_m2_base_url = value

    @property
    def m2_admin_token(self) -> str:
        if self._unified is not None:
            return self._unified.m2_admin_token
        return self._fallback_m2_admin_token

    @m2_admin_token.setter
    def m2_admin_token(self, value: str) -> None:
        if self._unified is not None:
            self._unified.m2_admin_token = value
        else:
            self._fallback_m2_admin_token = value

    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        if self._unified is not None:
            return self._unified.is_development
        return self._fallback_env == "development"

    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        if self._unified is not None:
            return self._unified.is_production
        return self._fallback_env == "production"

    def reload_config(self) -> dict:
        """重新加载配置，返回变更项"""
        if self._unified is not None:
            return self._unified.reload()
        return {}

    def __repr__(self) -> str:
        return (
            f"<Settings (deprecated) host={self.host} port={self.port} "
            f"env={self.env}>"
        )


# ============================================================
# 向后兼容：settings 单例
# ============================================================

def _create_settings_singleton_m7() -> Settings:
    """创建 settings 单例（不触发顶层 deprecation warning）"""
    return Settings(_suppress_warning=True)


# 向后兼容：旧的 settings 单例
settings = _create_settings_singleton_m7()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 新接口（推荐使用）
    "M7ModuleConfig",
    "get_m7_config",
    # 旧接口（deprecated，向后兼容）
    "Settings",
    "settings",
    "_USE_UNIFIED_CONFIG_M7",
]
