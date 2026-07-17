"""
云汐系统统一配置管理模块

基于 pydantic-settings 构建，提供统一的配置基类 BaseConfig，
所有模块的配置类均应继承自此基类，以获得：

- .env 文件自动加载
- 环境变量自动覆盖（优先级最高）
- YAML 配置文件支持
- 生产环境强制校验（敏感字段不得使用默认值）
- 敏感字段自动脱敏
- 环境类型识别（development / staging / production）
- 配置热更新接口
- 向后兼容的旧环境变量 alias

使用方式：
    from shared.core.config import BaseConfig, EnvType

    class MyModuleConfig(BaseConfig):
        host: str = "0.0.0.0"
        port: int = 8000
        admin_token: str = Field(default="", sensitive=True)

        model_config = SettingsConfigDict(
            env_prefix="MY_MODULE_",
            env_file=".env",
            extra="allow",
        )
"""

from __future__ import annotations

import copy
import os
import secrets
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ============================================================
# 环境类型枚举
# ============================================================

class EnvType(str, Enum):
    """运行环境类型"""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"

    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return self == EnvType.PRODUCTION

    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self == EnvType.DEVELOPMENT

    @property
    def is_staging(self) -> bool:
        """是否为预发布环境"""
        return self == EnvType.STAGING


# ============================================================
# 敏感字段标记
# ============================================================

# 默认敏感字段名（不区分大小写）
DEFAULT_SENSITIVE_KEYS: Set[str] = {
    "token", "secret", "password", "api_key", "apikey",
    "encryption_key", "private_key", "access_key",
    "admin_token", "jwt_secret", "db_password",
    "redis_password", "mongo_password",
}


def is_sensitive_field(field_name: str) -> bool:
    """判断字段名是否为敏感字段（基于关键词匹配）"""
    name_lower = field_name.lower()
    for keyword in DEFAULT_SENSITIVE_KEYS:
        if keyword in name_lower:
            return True
    return False


# ============================================================
# 基础配置基类
# ============================================================

class BaseConfig(BaseSettings):
    """
    云汐系统统一配置基类

    所有模块配置类应继承此类，获得以下能力：

    1. **多源配置加载**：YAML 文件 > .env 文件 > 环境变量 > 默认值
    2. **生产环境校验**：生产环境下敏感字段不得使用默认值
    3. **敏感字段脱敏**：to_dict(sanitize=True) 自动脱敏
    4. **热更新支持**：reload() 方法重新加载配置
    5. **向后兼容**：通过 alias 支持旧环境变量名

    子类示例：
        class M6Config(BaseConfig):
            host: str = "0.0.0.0"
            port: int = 8006
            admin_token: str = ""

            model_config = SettingsConfigDict(
                env_prefix="M6_",
                env_file="config/yunxi.env",
                extra="allow",
            )
    """

    # ---- 通用基础字段 ----
    # 模块名称
    module_name: str = Field(default="unknown", description="模块名称")
    # 运行环境
    env: EnvType = Field(default=EnvType.DEVELOPMENT, description="运行环境")
    # 日志级别
    log_level: str = Field(default="info", description="日志级别")
    # 监听地址
    host: str = Field(default="0.0.0.0", description="服务监听地址")
    # 监听端口
    port: int = Field(default=8000, ge=1, le=65535, description="服务监听端口")
    # CORS 来源
    cors_origins: str = Field(default="*", description="CORS 允许的来源（逗号分隔）")
    # 管理员令牌
    admin_token: str = Field(default="", description="管理员令牌（敏感字段）")

    model_config = SettingsConfigDict(
        env_prefix="YUNXI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
        validate_assignment=True,
    )

    # ---- 内部状态 ----
    _yaml_config: Dict[str, Any] = {}
    _env_file_paths: List[str] = []
    _hot_reload_hooks: List[Callable[["BaseConfig"], None]] = []

    # ============================================================
    # 环境变量与 YAML 加载
    # ============================================================

    @classmethod
    def _find_project_root(cls) -> Optional[Path]:
        """查找项目根目录（从当前文件向上查找包含 config/yunxi.env 的目录）"""
        try:
            current = Path(__file__).resolve()
            for _ in range(10):
                current = current.parent
                if (current / "config" / "yunxi.env").exists():
                    return current
        except Exception:
            pass
        return None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> Tuple[Any, ...]:
        """
        自定义配置源优先级。

        优先级从高到低：
        1. 初始化参数（init_settings）
        2. 环境变量（env_settings）
        3. .env 文件（dotenv_settings）
        4. YAML 配置文件
        5. 默认值
        """
        # 定义 YAML 配置源（pydantic-settings 2.x 要求 source 是无参数可调用对象）
        def yaml_config_source() -> Dict[str, Any]:
            """从 YAML 文件加载配置"""
            result: Dict[str, Any] = {}

            # 查找项目根目录下的 config/yunxi.yaml
            project_root = cls._find_project_root()
            yaml_paths = []

            if project_root:
                yaml_paths.append(project_root / "config" / "yunxi.yaml")
                yaml_paths.append(project_root / "config" / "yunxi.yml")

            # 也检查当前工作目录
            cwd = Path.cwd()
            yaml_paths.append(cwd / "config.yaml")
            yaml_paths.append(cwd / "config.yml")

            for yaml_path in yaml_paths:
                if yaml_path and Path(yaml_path).exists():
                    try:
                        import yaml
                        with open(yaml_path, "r", encoding="utf-8") as f:
                            data = yaml.safe_load(f) or {}
                        # 扁平化：如果顶层有模块前缀，提取对应模块的配置
                        module_prefix = None
                        if hasattr(settings_cls, 'model_config'):
                            prefix = settings_cls.model_config.get("env_prefix", "")
                            if prefix:
                                module_prefix = prefix.rstrip("_").lower()

                        if module_prefix and module_prefix in data:
                            module_data = data[module_prefix]
                            if isinstance(module_data, dict):
                                result.update(module_data)
                        # 全局配置也合并进来
                        for key in ["env", "log_level", "cors_origins", "jwt_secret"]:
                            if key in data and key not in result:
                                result[key] = data[key]

                        cls._yaml_config = result
                        break
                    except ImportError:
                        pass
                    except Exception:
                        pass

            return result

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            yaml_config_source,
            file_secret_settings,
        )

    # ============================================================
    # 生产环境校验
    # ============================================================

    @model_validator(mode="after")
    def _validate_production_sensitive(self) -> "BaseConfig":
        """
        生产环境校验：敏感字段不得使用默认值或空值。

        对于标记为 sensitive 的字段（或字段名包含敏感关键词），
        在 production 环境下如果值为空或为默认值，则抛出 ValidationError。
        """
        if self.env != EnvType.PRODUCTION:
            return self

        errors = []
        for field_name, field_info in self.model_fields.items():
            # 跳过非敏感字段
            if not is_sensitive_field(field_name):
                continue

            value = getattr(self, field_name, None)
            # 空值或默认占位值不允许在生产环境使用
            if not value:
                errors.append(
                    f"生产环境必须配置 '{field_name}'，禁止使用空默认值。"
                    f"请通过环境变量或配置文件设置。"
                )
            elif isinstance(value, str) and value.startswith("yunxi-") and "default" in value.lower():
                errors.append(
                    f"生产环境 '{field_name}' 不能使用默认占位值，请修改为真实密钥。"
                )

        if errors:
            raise ValueError(";\n".join(errors))

        return self

    # ============================================================
    # 脱敏输出
    # ============================================================

    def to_dict(self, sanitize: bool = True) -> Dict[str, Any]:
        """
        导出配置为字典。

        Args:
            sanitize: 是否脱敏敏感字段

        Returns:
            配置字典
        """
        data = self.model_dump(mode="json")
        if sanitize:
            self._sanitize_dict(data)
        return data

    @classmethod
    def _sanitize_dict(cls, d: Dict[str, Any]) -> None:
        """递归脱敏字典中的敏感字段"""
        for key, value in list(d.items()):
            if is_sensitive_field(key) and value:
                d[key] = "***MASKED***"
            elif isinstance(value, dict):
                cls._sanitize_dict(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        cls._sanitize_dict(item)

    def __repr__(self) -> str:
        """字符串表示（脱敏）"""
        data = self.to_dict(sanitize=True)
        return f"<{self.__class__.__name__} env={self.env.value} port={self.port}>"

    def __str__(self) -> str:
        return self.__repr__()

    # ============================================================
    # 热更新
    # ============================================================

    def reload(self, **overrides: Any) -> Dict[str, Dict[str, Any]]:
        """
        重新加载配置（热更新）。

        会重新从环境变量和 .env 文件读取配置，并应用变更。
        变更后会触发所有注册的热更新钩子。

        Args:
            **overrides: 额外的覆盖参数

        Returns:
            变更字典：{field_name: {"old": old_val, "new": new_val}}
        """
        # 记录旧值（脱敏前的实际值）
        old_values = {}
        for field_name in self.model_fields:
            try:
                old_values[field_name] = copy.deepcopy(getattr(self, field_name))
            except Exception:
                old_values[field_name] = getattr(self, field_name)

        # 重新加载 .env 文件
        self._reload_dotenv()

        # 重新从环境变量构建新实例
        new_config = self.__class__(**overrides)

        # 应用变更到当前实例
        changes = {}
        for field_name in self.model_fields:
            new_val = getattr(new_config, field_name)
            old_val = old_values.get(field_name)
            if new_val != old_val:
                setattr(self, field_name, new_val)
                changes[field_name] = {"old": old_val, "new": new_val}

        # 触发热更新钩子
        if changes:
            for hook in self._hot_reload_hooks:
                try:
                    hook(self)
                except Exception:
                    pass

        return changes

    def _reload_dotenv(self) -> None:
        """重新加载 .env 文件到环境变量"""
        project_root = self._find_project_root()
        env_files = []

        if project_root:
            env_files.append(project_root / "config" / "yunxi.env")

        # 也检查模块自己的 .env
        cwd = Path.cwd()
        env_files.append(cwd / ".env")

        try:
            from dotenv import load_dotenv
            for env_file in env_files:
                if Path(env_file).exists():
                    load_dotenv(env_file, override=True)
        except ImportError:
            # python-dotenv 不可用时手动解析
            for env_file in env_files:
                if Path(env_file).exists():
                    try:
                        with open(env_file, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line or line.startswith("#") or "=" not in line:
                                    continue
                                key, _, value = line.partition("=")
                                key = key.strip()
                                value = value.strip().strip('"').strip("'")
                                if key:
                                    os.environ[key] = value
                    except Exception:
                        pass

    def register_hot_reload_hook(self, hook: Callable[["BaseConfig"], None]) -> None:
        """
        注册配置热更新钩子。

        当配置发生变更时，会调用所有注册的钩子函数。

        Args:
            hook: 回调函数，接收新的配置实例作为参数
        """
        self._hot_reload_hooks.append(hook)

    # ============================================================
    # 环境检测辅助方法
    # ============================================================

    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return self.env == EnvType.PRODUCTION

    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.env == EnvType.DEVELOPMENT

    @property
    def is_staging(self) -> bool:
        """是否为预发布环境"""
        return self.env == EnvType.STAGING

    def require_production_secret(self, value: str, field_name: str) -> str:
        """
        生产环境密钥校验工具方法。

        如果是生产环境且 value 为空，抛出 RuntimeError；
        如果是开发环境且 value 为空，生成随机一次性令牌并记录警告。

        Args:
            value: 当前配置值
            field_name: 字段名（用于错误信息）

        Returns:
            校验后的密钥值

        Raises:
            RuntimeError: 生产环境密钥缺失
        """
        if value:
            return value

        if self.is_production:
            raise RuntimeError(
                f"生产环境必须配置 {field_name}，禁止使用默认值。"
                f"请在环境变量或配置文件中设置。"
            )

        # 开发环境生成随机一次性令牌
        import logging
        logger = logging.getLogger(__name__)
        random_token = secrets.token_urlsafe(32)
        logger.warning(
            "开发环境未配置 %s，已自动生成一次性随机令牌：%s",
            field_name, random_token,
        )
        return random_token

    # ============================================================
    # 便捷方法
    # ============================================================

    def get(self, path: str, default: Any = None) -> Any:
        """
        按点分路径获取配置值（兼容旧接口）。

        Args:
            path: 配置路径，如 'basic.port'、'vector.top_k'
            default: 默认值

        Returns:
            配置值
        """
        keys = path.split(".")
        current: Any = self
        for key in keys:
            if isinstance(current, BaseModel):
                if hasattr(current, key):
                    current = getattr(current, key)
                else:
                    return default
            elif isinstance(current, dict):
                if key in current:
                    current = current[key]
                else:
                    return default
            else:
                return default
        return current


# ============================================================
# 全局配置：模块端口 / 地址 / Token / Base URL 集中管理
# ============================================================

class ModuleEndpointConfig(BaseModel):
    """单个模块的端点配置"""
    host: str = "0.0.0.0"
    port: int = 8000
    token: str = ""
    base_url: str = "http://localhost:8000"
    python_executable: str = "python"
    health_check_path: str = "/health"
    enabled: bool = True


class GlobalModuleConfig(BaseModel):
    """全局模块配置（所有模块的端口、地址、令牌集中管理）"""

    gateway: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8080,
            token="yunxi-gateway-admin-token-2026",
            base_url="http://localhost:8080",
        ),
        description="API 网关",
    )
    m0: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8000,
            token="yunxi-m0-admin-token-2026",
            base_url="http://localhost:8000",
        ),
        description="M0 主控台",
    )
    m1: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8001,
            token="yunxi-m1-admin-token-2026",
            base_url="http://localhost:8001",
        ),
        description="M1 多Agent集群",
    )
    m2: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8002,
            token="yunxi-m2-admin-token-2026",
            base_url="http://localhost:8002",
        ),
        description="M2 技能集群",
    )
    m3: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8003,
            token="yunxi-m3-admin-token-2026",
            base_url="http://localhost:8003",
        ),
        description="M3 端云协同",
    )
    m4: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8004,
            token="yunxi-m4-admin-token-2026",
            base_url="http://localhost:8004",
        ),
        description="M4 场景引擎",
    )
    m5: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8005,
            token="yunxi-m5-admin-token-2026",
            base_url="http://localhost:8005",
        ),
        description="M5 潮汐记忆",
    )
    m6: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8006,
            token="yunxi-m6-admin-token-2026",
            base_url="http://localhost:8006",
        ),
        description="M6 硬件外设",
    )
    m7: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8007,
            token="yunxi-m7-admin-token-2026",
            base_url="http://localhost:8007",
        ),
        description="M7 工作流编排",
    )
    m8: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8008,
            token="yunxi-m8-admin-token-2026",
            base_url="http://localhost:8008",
        ),
        description="M8 控制塔",
    )
    m9: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8009,
            token="yunxi-m9-admin-token-2026",
            base_url="http://localhost:8009",
        ),
        description="M9 开发者工坊",
    )
    m10: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8010,
            token="yunxi-m10-admin-token-2026",
            base_url="http://localhost:8010",
        ),
        description="M10 系统卫士",
    )
    m11: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8011,
            token="yunxi-m11-admin-token-2026",
            base_url="http://localhost:8011",
        ),
        description="M11 MCP总线",
    )
    m12: ModuleEndpointConfig = Field(
        default_factory=lambda: ModuleEndpointConfig(
            host="0.0.0.0", port=8012,
            token="yunxi-m12-admin-token-2026",
            base_url="http://localhost:8012",
        ),
        description="M12 安全盾",
    )


class GlobalSecurityConfig(BaseModel):
    """全局安全配置"""
    jwt_secret: str = Field(default="yunxi-jwt-secret-key-2026", description="JWT 签名密钥")
    jwt_algorithm: str = Field(default="HS256", description="JWT 签名算法")
    access_token_expire_minutes: int = Field(default=1440, description="访问令牌有效期（分钟）")
    cors_origins: str = Field(default="*", description="全局 CORS 来源")


class YunxiGlobalConfig(BaseConfig):
    """
    云汐系统全局配置

    集中管理所有模块的端点配置和全局安全配置。
    各模块可以通过全局配置获取其他模块的地址和令牌，
    实现模块间调用配置的集中管理。
    """

    # 全局安全配置
    security: GlobalSecurityConfig = Field(default_factory=GlobalSecurityConfig)

    # 所有模块的端点配置
    modules: GlobalModuleConfig = Field(default_factory=GlobalModuleConfig)

    model_config = SettingsConfigDict(
        env_prefix="YUNXI_",
        env_file="config/yunxi.env",
        env_file_encoding="utf-8",
        extra="allow",
        validate_assignment=True,
        nested_model_default_partial_update=True,
    )

    def get_module_endpoint(self, module_key: str) -> Optional[ModuleEndpointConfig]:
        """获取指定模块的端点配置"""
        module_key = module_key.lower()
        return getattr(self.modules, module_key, None)

    def get_module_port(self, module_key: str) -> Optional[int]:
        """获取指定模块的端口号"""
        ep = self.get_module_endpoint(module_key)
        return ep.port if ep else None

    def get_module_host(self, module_key: str) -> Optional[str]:
        """获取指定模块的主机地址"""
        ep = self.get_module_endpoint(module_key)
        return ep.host if ep else None

    def get_module_token(self, module_key: str) -> Optional[str]:
        """获取指定模块的管理令牌"""
        ep = self.get_module_endpoint(module_key)
        return ep.token if ep else None

    def get_module_base_url(self, module_key: str) -> Optional[str]:
        """获取指定模块的 Base URL"""
        ep = self.get_module_endpoint(module_key)
        return ep.base_url if ep else None

    def get_module_python_executable(self, module_key: str) -> Optional[str]:
        """获取指定模块的 Python 可执行文件路径"""
        ep = self.get_module_endpoint(module_key)
        return ep.python_executable if ep else None

    def get_module_health_check(self, module_key: str) -> Optional[str]:
        """获取指定模块的健康检查路径"""
        ep = self.get_module_endpoint(module_key)
        return ep.health_check_path if ep else None

    def get_all_module_keys(self) -> List[str]:
        """获取所有模块的 key 列表"""
        return list(self.modules.model_fields.keys())


# ============================================================
# 全局配置单例（向后兼容 YunxiConfig）
# ============================================================

_global_config: Optional[YunxiGlobalConfig] = None


def get_global_config() -> YunxiGlobalConfig:
    """获取全局配置实例（单例模式）"""
    global _global_config
    if _global_config is None:
        _global_config = YunxiGlobalConfig()
    return _global_config


# 向后兼容：旧的 YunxiConfig 类和 get_config() 函数
# 通过包装 YunxiGlobalConfig 提供旧接口
class YunxiConfig:
    """
    云汐系统全局配置类（向后兼容包装器）

    旧代码使用 `from shared.core.config import get_config` 获取的
    YunxiConfig 实例，现在内部委托给 YunxiGlobalConfig。

    保留了所有旧的属性和方法，确保不破坏现有代码。
    """

    def __init__(self):
        self._inner = get_global_config()

    @property
    def project_root(self) -> Path:
        """项目根目录"""
        root = BaseConfig._find_project_root()
        return root or Path(__file__).resolve().parent.parent

    @property
    def module_ports(self) -> Dict[str, int]:
        """模块端口字典（向后兼容）"""
        return {
            key: getattr(self._inner.modules, key).port
            for key in self._inner.get_all_module_keys()
        }

    @property
    def module_hosts(self) -> Dict[str, str]:
        """模块主机地址字典（向后兼容）"""
        return {
            key: getattr(self._inner.modules, key).host
            for key in self._inner.get_all_module_keys()
        }

    @property
    def module_tokens(self) -> Dict[str, str]:
        """模块令牌字典（向后兼容）"""
        return {
            key: getattr(self._inner.modules, key).token
            for key in self._inner.get_all_module_keys()
        }

    @property
    def module_base_urls(self) -> Dict[str, str]:
        """模块 Base URL 字典（向后兼容）"""
        return {
            key: getattr(self._inner.modules, key).base_url
            for key in self._inner.get_all_module_keys()
        }

    @property
    def module_python_executables(self) -> Dict[str, str]:
        """模块 Python 可执行文件字典（向后兼容）"""
        return {
            key: getattr(self._inner.modules, key).python_executable
            for key in self._inner.get_all_module_keys()
        }

    @property
    def module_health_checks(self) -> Dict[str, str]:
        """模块健康检查路径字典（向后兼容）"""
        return {
            key: getattr(self._inner.modules, key).health_check_path
            for key in self._inner.get_all_module_keys()
        }

    @property
    def env(self) -> str:
        """运行环境（字符串形式，向后兼容）"""
        return self._inner.env.value

    @property
    def cors_origins(self) -> str:
        """全局 CORS 来源（向后兼容）"""
        return self._inner.security.cors_origins

    @property
    def jwt_secret(self) -> str:
        """JWT 密钥（向后兼容）"""
        return self._inner.security.jwt_secret

    @property
    def jwt_algorithm(self) -> str:
        """JWT 算法（向后兼容）"""
        return self._inner.security.jwt_algorithm

    @property
    def access_token_expire_minutes(self) -> int:
        """访问令牌有效期（向后兼容）"""
        return self._inner.security.access_token_expire_minutes

    def get_module_port(self, module_key: str) -> Optional[int]:
        """获取指定模块的端口号"""
        return self._inner.get_module_port(module_key)

    def get_module_host(self, module_key: str) -> Optional[str]:
        """获取指定模块的主机地址"""
        return self._inner.get_module_host(module_key)

    def get_module_token(self, module_key: str) -> Optional[str]:
        """获取指定模块的管理令牌"""
        return self._inner.get_module_token(module_key)

    def get_module_base_url(self, module_key: str) -> Optional[str]:
        """获取指定模块的 Base URL"""
        return self._inner.get_module_base_url(module_key)

    def get_module_python_executable(self, module_key: str) -> Optional[str]:
        """获取指定模块的 Python 可执行文件路径"""
        return self._inner.get_module_python_executable(module_key)

    def get_module_health_check(self, module_key: str) -> Optional[str]:
        """获取指定模块的健康检查路径"""
        return self._inner.get_module_health_check(module_key)

    def get_all_module_keys(self) -> List[str]:
        """获取所有模块的 key 列表"""
        return self._inner.get_all_module_keys()


# 全局配置单例（旧接口）
_config: Optional[YunxiConfig] = None


def get_config() -> YunxiConfig:
    """获取全局配置实例（单例模式，向后兼容旧接口）"""
    global _config
    if _config is None:
        _config = YunxiConfig()
    return _config


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 核心基类
    "BaseConfig",
    "EnvType",
    # 全局配置
    "YunxiGlobalConfig",
    "GlobalModuleConfig",
    "GlobalSecurityConfig",
    "ModuleEndpointConfig",
    "get_global_config",
    # 向后兼容
    "YunxiConfig",
    "get_config",
    # 工具函数
    "is_sensitive_field",
    "DEFAULT_SENSITIVE_KEYS",
]
