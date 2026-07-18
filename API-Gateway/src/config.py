"""
云汐 API 网关配置

统一配置框架版（CQ-007 + AR-002, P2级）：
- 主接口：GatewayModuleConfig（继承 BaseConfig，基于 pydantic-settings）
  唯一真源，所有配置字段和路由表均在此定义
- 兼容层：GatewaySettings + settings 单例（deprecated，内部委托给 GatewayModuleConfig）
  保留向后兼容，对外属性访问方式不变，触发 deprecation warning

路由表只有一份定义：在 GatewayModuleConfig._build_default_routes() 中。
旧兼容层从新配置同步数据，杜绝双配置不一致问题。
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path
from typing import List, Dict, Optional

from pydantic import BaseModel, Field


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


# ============================================================
# 模块路由配置（保持不变，两套配置共用同一个 ModuleRoute）
# ============================================================

class ModuleRoute(BaseModel):
    """模块路由配置（增强版）

    包含完整的模块路由信息：
    - 基础信息：模块ID、名称、后端地址、路由前缀
    - 健康检查：健康检查路径、超时时间
    - 认证配置：是否需要认证、公开路径白名单
    - 限流配置：单模块限流阈值
    - 协议支持：是否支持 WebSocket、SSE
    - 熔断配置：单独的熔断阈值
    """
    # 基础信息
    key: str                    # 模块唯一标识，如 m1, m8
    name: str                   # 模块名称
    target_url: str             # 后端服务地址
    prefix: str                 # 路由前缀，如 /m1, /m8
    enabled: bool = True        # 是否启用
    timeout: float = 30.0       # 请求超时时间（秒）

    # 健康检查
    health_path: str = "/health"    # 健康检查路径
    health_timeout: float = 5.0     # 健康检查超时（秒）

    # 认证配置
    auth_required: bool = True      # 是否需要认证
    public_paths: List[str] = Field(
        default_factory=list,
        description="公开路径白名单（无需认证），支持前缀匹配"
    )

    # 限流配置
    rate_limit_per_minute: int = 60     # 模块级每分钟限流
    rate_limit_per_ip: int = 30         # 模块级单IP每分钟限流
    rate_limit_tier: str = "public"     # 默认限速级别

    # 协议支持
    supports_websocket: bool = False    # 是否支持 WebSocket
    supports_sse: bool = False          # 是否支持 SSE

    # 熔断配置
    cb_failure_threshold: int = 5       # 熔断失败次数阈值
    cb_recovery_time: int = 30          # 熔断恢复时间（秒）

    # 描述信息
    description: str = ""               # 模块描述


# ============================================================
# 路由表构建函数（唯一真源，新配置和兼容层都调用此函数）
# ============================================================

def build_default_routes() -> List[ModuleRoute]:
    """构建默认路由表（12个模块完整配置）

    这是路由表的**唯一真源**。
    GatewayModuleConfig 和 GatewaySettings 兼容层都从此函数获取路由定义，
    确保两套配置的路由表完全一致，避免双配置并行导致的不一致问题。

    每个模块包含：
    - 基础路由信息
    - 健康检查路径
    - 认证要求与公开路径
    - 限流配置
    - 协议支持（WebSocket/SSE）
    - 熔断阈值
    """
    routes = [
        # M1 多Agent调度中心
        ModuleRoute(
            key="m1",
            name="M1 多Agent调度中心",
            description="多智能体集群调度与管理，负责Agent的创建、调度、负载均衡",
            target_url=os.getenv("M1_BASE_URL", "http://localhost:8001"),
            prefix="/m1",
            timeout=60.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
                "/api/v1/public",
            ],
            rate_limit_per_minute=120,
            rate_limit_per_ip=60,
            rate_limit_tier="public",
            supports_websocket=True,
            supports_sse=True,
            cb_failure_threshold=5,
            cb_recovery_time=30,
        ),
        # M2 技能集群
        ModuleRoute(
            key="m2",
            name="M2 技能集群",
            description="技能市场与技能执行引擎，提供各类AI能力调用",
            target_url=os.getenv("M2_BASE_URL", "http://localhost:8002"),
            prefix="/m2",
            timeout=30.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
                "/api/v1/skills/public",
                "/api/v1/categories",
            ],
            rate_limit_per_minute=100,
            rate_limit_per_ip=50,
            rate_limit_tier="public",
            supports_websocket=False,
            supports_sse=False,
            cb_failure_threshold=5,
            cb_recovery_time=30,
        ),
        # M3 端云协同内核
        ModuleRoute(
            key="m3",
            name="M3 端云协同内核",
            description="端云协同计算框架，支持本地推理与云端协同",
            target_url=os.getenv("M3_BASE_URL", "http://localhost:8003"),
            prefix="/m3",
            timeout=120.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
                "/api/v1/status",
            ],
            rate_limit_per_minute=80,
            rate_limit_per_ip=40,
            rate_limit_tier="public",
            supports_websocket=True,
            supports_sse=True,
            cb_failure_threshold=3,
            cb_recovery_time=60,
        ),
        # M4 场景引擎
        ModuleRoute(
            key="m4",
            name="M4 场景引擎",
            description="场景模板引擎，支持场景配置、代码生成与执行",
            target_url=os.getenv("M4_BASE_URL", "http://localhost:8004"),
            prefix="/m4",
            timeout=60.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
                "/api/v1/scenes/public",
                "/api/v1/templates",
            ],
            rate_limit_per_minute=60,
            rate_limit_per_ip=30,
            rate_limit_tier="public",
            supports_websocket=False,
            supports_sse=True,
            cb_failure_threshold=5,
            cb_recovery_time=30,
        ),
        # M5 潮汐记忆系统
        ModuleRoute(
            key="m5",
            name="M5 潮汐记忆系统",
            description="长期记忆系统，支持向量检索、记忆存储与遗忘机制",
            target_url=os.getenv("M5_BASE_URL", "http://localhost:8005"),
            prefix="/m5",
            timeout=30.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
            ],
            rate_limit_per_minute=120,
            rate_limit_per_ip=60,
            rate_limit_tier="public",
            supports_websocket=False,
            supports_sse=False,
            cb_failure_threshold=5,
            cb_recovery_time=30,
        ),
        # M6 硬件外设模拟
        ModuleRoute(
            key="m6",
            name="M6 硬件外设模拟",
            description="硬件外设模拟与管理，支持IoT设备接入",
            target_url=os.getenv("M6_BASE_URL", "http://localhost:8006"),
            prefix="/m6",
            timeout=30.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
                "/api/v1/devices/public",
            ],
            rate_limit_per_minute=60,
            rate_limit_per_ip=30,
            rate_limit_tier="public",
            supports_websocket=True,
            supports_sse=True,
            cb_failure_threshold=5,
            cb_recovery_time=30,
        ),
        # M7 积木平台（工作流编排）
        ModuleRoute(
            key="m7",
            name="M7 积木平台",
            description="可视化工作流编排平台，支持拖拽式流程构建",
            target_url=os.getenv("M7_BASE_URL", "http://localhost:8007"),
            prefix="/m7",
            timeout=60.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
                "/api/v1/workflows/public",
            ],
            rate_limit_per_minute=60,
            rate_limit_per_ip=30,
            rate_limit_tier="public",
            supports_websocket=True,
            supports_sse=True,
            cb_failure_threshold=5,
            cb_recovery_time=30,
        ),
        # M8 管理控制塔
        ModuleRoute(
            key="m8",
            name="M8 管理控制塔",
            description="系统管理控制台，负责全局监控、配置管理与运维操作",
            target_url=os.getenv("M8_BASE_URL", "http://localhost:8008"),
            prefix="/m8",
            timeout=30.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
                "/metrics",
                "/api/v1/auth/login",
                "/api/v1/status",
                "/api/v1/public",
            ],
            rate_limit_per_minute=120,
            rate_limit_per_ip=60,
            rate_limit_tier="admin",
            supports_websocket=False,
            supports_sse=False,
            cb_failure_threshold=10,
            cb_recovery_time=15,
        ),
        # M9 开发者工坊
        ModuleRoute(
            key="m9",
            name="M9 开发者工坊",
            description="开发者工具集，代码生成、调试、测试一站式服务",
            target_url=os.getenv("M9_BASE_URL", "http://localhost:8009"),
            prefix="/m9",
            timeout=120.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
                "/api/v1/public",
            ],
            rate_limit_per_minute=60,
            rate_limit_per_ip=30,
            rate_limit_tier="public",
            supports_websocket=True,
            supports_sse=True,
            cb_failure_threshold=5,
            cb_recovery_time=30,
        ),
        # M10 系统卫士
        ModuleRoute(
            key="m10",
            name="M10 系统卫士",
            description="系统监控与运维管理，性能监控、告警、日志分析",
            target_url=os.getenv("M10_BASE_URL", "http://localhost:8010"),
            prefix="/m10",
            timeout=30.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
                "/api/v1/status",
            ],
            rate_limit_per_minute=120,
            rate_limit_per_ip=60,
            rate_limit_tier="admin",
            supports_websocket=True,
            supports_sse=True,
            cb_failure_threshold=5,
            cb_recovery_time=30,
        ),
        # M11 MCP总线
        ModuleRoute(
            key="m11",
            name="M11 MCP总线",
            description="MCP协议总线，统一管理各类工具与数据源接入",
            target_url=os.getenv("M11_BASE_URL", "http://localhost:8011"),
            prefix="/m11",
            timeout=60.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
                "/api/v1/tools/public",
                "/sse",
            ],
            rate_limit_per_minute=120,
            rate_limit_per_ip=60,
            rate_limit_tier="mcp",
            supports_websocket=True,
            supports_sse=True,
            cb_failure_threshold=5,
            cb_recovery_time=30,
        ),
        # M12 安全盾
        ModuleRoute(
            key="m12",
            name="M12 安全盾",
            description="安全防护中心，认证鉴权、WAF、审计日志",
            target_url=os.getenv("M12_BASE_URL", "http://localhost:8012"),
            prefix="/m12",
            timeout=30.0,
            health_path="/health",
            auth_required=True,
            public_paths=[
                "/health",
                "/api/v1/auth/login",
                "/api/v1/auth/register",
                "/api/v1/auth/password/forgot",
                "/api/v1/auth/password/reset",
                "/api/v1/status",
                "/api/v1/public-key",
            ],
            rate_limit_per_minute=60,
            rate_limit_per_ip=30,
            rate_limit_tier="public",
            supports_websocket=False,
            supports_sse=False,
            cb_failure_threshold=10,
            cb_recovery_time=15,
        ),
    ]
    return routes


# ============================================================
# API Gateway 模块统一配置类（新接口 - 唯一真源）
# ============================================================

if _USE_UNIFIED_CONFIG:

    class GatewayModuleConfig(BaseConfig):
        """
        API 网关模块配置（统一配置框架版）

        继承自 BaseConfig，自动获得：
        - .env 文件加载
        - 环境变量覆盖
        - 生产环境敏感字段校验
        - 敏感字段脱敏
        - 配置热更新

        环境变量前缀：GATEWAY_

        这是网关配置的**唯一真源**。旧的 GatewaySettings 兼容层
        内部委托给此类，确保数据一致性。
        """

        module_name: str = Field(default="api-gateway", description="模块名称")
        port: int = Field(default=8080, ge=1, le=65535, description="服务监听端口")
        log_level: str = Field(default="info", description="日志级别")

        # CORS（开发环境默认 localhost 常见端口，生产环境必须显式配置）
        cors_origins: str = Field(
            default="http://localhost:3000,http://localhost:5173,http://localhost:8080,http://localhost:8000,http://127.0.0.1:3000,http://127.0.0.1:5173,http://127.0.0.1:8080,http://127.0.0.1:8000",
            description="允许的来源（逗号分隔，生产环境禁止使用 *）",
        )

        # 认证
        api_key_header: str = Field(default="X-API-Key", description="API Key 头字段名")
        jwt_header: str = Field(default="Authorization", description="JWT 头字段名")

        # 限流
        rate_limit_per_minute: int = Field(
            default=600, ge=1, description="全局每分钟限流次数"
        )
        rate_limit_per_ip: int = Field(
            default=100, ge=1, description="每 IP 每分钟限流次数"
        )

        # 熔断
        circuit_breaker_threshold: int = Field(
            default=5, ge=1, description="连续失败次数阈值"
        )
        circuit_breaker_recovery_time: int = Field(
            default=30, ge=1, description="熔断恢复时间（秒）"
        )

        # 模块路由表
        routes: List[ModuleRoute] = Field(
            default_factory=list,
            description="模块路由表",
        )

        model_config = SettingsConfigDict(
            env_prefix="GATEWAY_",
            env_file=".env",
            env_file_encoding="utf-8",
            extra="allow",
            validate_assignment=True,
        )

        def model_post_init(self, __context: Dict) -> None:
            """初始化后自动构建路由表"""
            if not self.routes:
                self.routes = self._build_default_routes()

        def _build_default_routes(self) -> List[ModuleRoute]:
            """构建默认路由表（委托给全局唯一真源函数）

            路由表的唯一真源是 build_default_routes() 函数，
            确保新配置和旧兼容层使用完全相同的路由定义。
            """
            return build_default_routes()

        def get_route(self, key: str) -> Optional[ModuleRoute]:
            """根据 key 获取路由配置"""
            for route in self.routes:
                if route.key == key:
                    return route
            return None

        def get_enabled_routes(self) -> List[ModuleRoute]:
            """获取所有启用的路由"""
            return [r for r in self.routes if r.enabled]


    # 全局配置单例（新接口）
    _gateway_config: Optional[GatewayModuleConfig] = None

    def get_gateway_config() -> GatewayModuleConfig:
        """获取网关配置实例（单例模式，统一配置框架）"""
        global _gateway_config
        if _gateway_config is None:
            _gateway_config = GatewayModuleConfig()
        return _gateway_config

else:
    GatewayModuleConfig = None  # type: ignore
    get_gateway_config = None  # type: ignore


# ============================================================
# 旧接口：GatewaySettings（向后兼容层 - DEPRECATED）
# ============================================================

_DEPRECATION_MSG = (
    "GatewaySettings 和 settings 单例已废弃（deprecated），"
    "请使用 GatewayModuleConfig 和 get_gateway_config() 替代。"
    "详见 CQ-007 + AR-002 统一配置方案。"
)


class GatewaySettings:
    """网关配置（向后兼容层）

    .. deprecated:: 2.0.0
        请使用 GatewayModuleConfig 替代。
        通过 get_gateway_config() 获取新配置实例。

    兼容层设计：
    - 内部持有 GatewayModuleConfig 实例（当统一配置可用时）
    - 所有属性访问委托给内部的新配置实例
    - 路由表从新配置同步，确保数据一致性
    - 实例化时触发 DeprecationWarning
    """

    def __init__(self, _suppress_warning: bool = False):
        if not _suppress_warning:
            warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)

        # 优先使用统一配置框架
        self._unified: Optional[GatewayModuleConfig] = None
        if _USE_UNIFIED_CONFIG:
            self._unified = get_gateway_config()

        # 回退字段：当统一配置不可用时使用的默认值
        self._fallback_host: str = "0.0.0.0"
        self._fallback_port: int = 8080
        self._fallback_log_level: str = "info"
        self._fallback_env: str = "development"
        self._fallback_cors_origins: str = "*"
        self._fallback_api_key_header: str = "X-API-Key"
        self._fallback_jwt_header: str = "Authorization"
        self._fallback_rate_limit_per_minute: int = 600
        self._fallback_rate_limit_per_ip: int = 100
        self._fallback_circuit_breaker_threshold: int = 5
        self._fallback_circuit_breaker_recovery_time: int = 30
        self._fallback_routes: List[ModuleRoute] = []

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
    def env(self) -> str:
        """运行环境（字符串形式，向后兼容）

        新配置中 env 是 EnvType 枚举，兼容层返回字符串值。
        """
        if self._unified is not None:
            return self._unified.env.value
        return self._fallback_env

    @env.setter
    def env(self, value: str) -> None:
        if self._unified is not None:
            # 从字符串转换为 EnvType 枚举
            from shared.core.config import EnvType
            self._unified.env = EnvType(value)
        else:
            self._fallback_env = value

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
    def api_key_header(self) -> str:
        if self._unified is not None:
            return self._unified.api_key_header
        return self._fallback_api_key_header

    @api_key_header.setter
    def api_key_header(self, value: str) -> None:
        if self._unified is not None:
            self._unified.api_key_header = value
        else:
            self._fallback_api_key_header = value

    @property
    def jwt_header(self) -> str:
        if self._unified is not None:
            return self._unified.jwt_header
        return self._fallback_jwt_header

    @jwt_header.setter
    def jwt_header(self, value: str) -> None:
        if self._unified is not None:
            self._unified.jwt_header = value
        else:
            self._fallback_jwt_header = value

    @property
    def rate_limit_per_minute(self) -> int:
        if self._unified is not None:
            return self._unified.rate_limit_per_minute
        return self._fallback_rate_limit_per_minute

    @rate_limit_per_minute.setter
    def rate_limit_per_minute(self, value: int) -> None:
        if self._unified is not None:
            self._unified.rate_limit_per_minute = value
        else:
            self._fallback_rate_limit_per_minute = value

    @property
    def rate_limit_per_ip(self) -> int:
        if self._unified is not None:
            return self._unified.rate_limit_per_ip
        return self._fallback_rate_limit_per_ip

    @rate_limit_per_ip.setter
    def rate_limit_per_ip(self, value: int) -> None:
        if self._unified is not None:
            self._unified.rate_limit_per_ip = value
        else:
            self._fallback_rate_limit_per_ip = value

    @property
    def circuit_breaker_threshold(self) -> int:
        if self._unified is not None:
            return self._unified.circuit_breaker_threshold
        return self._fallback_circuit_breaker_threshold

    @circuit_breaker_threshold.setter
    def circuit_breaker_threshold(self, value: int) -> None:
        if self._unified is not None:
            self._unified.circuit_breaker_threshold = value
        else:
            self._fallback_circuit_breaker_threshold = value

    @property
    def circuit_breaker_recovery_time(self) -> int:
        if self._unified is not None:
            return self._unified.circuit_breaker_recovery_time
        return self._fallback_circuit_breaker_recovery_time

    @circuit_breaker_recovery_time.setter
    def circuit_breaker_recovery_time(self, value: int) -> None:
        if self._unified is not None:
            self._unified.circuit_breaker_recovery_time = value
        else:
            self._fallback_circuit_breaker_recovery_time = value

    @property
    def routes(self) -> List[ModuleRoute]:
        """模块路由表

        从新配置同步，确保路由表只有一份真源。
        """
        if self._unified is not None:
            return self._unified.routes
        if not self._fallback_routes:
            self._fallback_routes = build_default_routes()
        return self._fallback_routes

    @routes.setter
    def routes(self, value: List[ModuleRoute]) -> None:
        if self._unified is not None:
            self._unified.routes = value
        else:
            self._fallback_routes = value

    # ---- 旧的 from_env 类方法 ----

    @classmethod
    def from_env(cls) -> "GatewaySettings":
        """从环境变量加载配置（向后兼容旧接口）

        .. deprecated:: 2.0.0
            请使用 GatewayModuleConfig 替代。

        兼容层实现：直接创建 GatewaySettings 实例，
        内部的统一配置会自动从环境变量加载。
        """
        warnings.warn(
            "GatewaySettings.from_env() 已废弃，请使用 get_gateway_config() 替代。",
            DeprecationWarning,
            stacklevel=2,
        )
        return cls(_suppress_warning=True)

    # ---- 便捷方法 ----

    def __repr__(self) -> str:
        return (
            f"<GatewaySettings (deprecated) host={self.host} port={self.port} "
            f"env={self.env} routes={len(self.routes)}>"
        )


# ============================================================
# 向后兼容：旧的 settings 单例
# ============================================================

def _create_settings_singleton() -> GatewaySettings:
    """创建 settings 单例（不触发顶层 deprecation warning）

    单例在模块导入时创建，为避免每次导入都触发警告，
    这里使用 _suppress_warning=True。代码中访问 settings 属性时
    不会触发警告，只有显式实例化 GatewaySettings 才会。
    """
    return GatewaySettings(_suppress_warning=True)


# 向后兼容：旧的 settings 单例
# 注：模块级单例不触发警告，避免每次导入都报警
settings = _create_settings_singleton()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 新接口（推荐使用）
    "GatewayModuleConfig",
    "get_gateway_config",
    # 路由配置（共用）
    "ModuleRoute",
    "build_default_routes",
    # 旧接口（deprecated，向后兼容）
    "GatewaySettings",
    "settings",
]
