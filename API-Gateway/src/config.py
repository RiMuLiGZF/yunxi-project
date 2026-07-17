"""
云汐 API 网关配置

统一配置框架迁移版：
- 新接口：GatewayModuleConfig（继承 BaseConfig，基于 pydantic-settings）
- 旧接口：GatewaySettings + ModuleRoute + settings 单例（保留，向后兼容）
"""

from __future__ import annotations

import os
import sys
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
# 模块路由配置（保持不变）
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
# API Gateway 模块统一配置类（新接口）
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
        """

        module_name: str = Field(default="api-gateway", description="模块名称")
        port: int = Field(default=8080, ge=1, le=65535, description="服务监听端口")
        log_level: str = Field(default="info", description="日志级别")

        # CORS
        cors_origins: str = Field(
            default="*",
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
            """从环境变量构建默认路由表（12个模块完整配置）

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
# 旧接口：GatewaySettings（向后兼容）
# ============================================================

class GatewaySettings(BaseModel):
    """网关配置（向后兼容层）

    .. deprecated:: 2.0.0
        请使用 GatewayModuleConfig 替代。
    """
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "info"
    env: str = "development"  # 运行环境：development / production

    # CORS
    cors_origins: str = "*"  # 允许的来源（逗号分隔，生产环境禁止使用 *）

    # 认证
    api_key_header: str = "X-API-Key"
    jwt_header: str = "Authorization"

    # 限流
    rate_limit_per_minute: int = 600
    rate_limit_per_ip: int = 100

    # 熔断
    circuit_breaker_threshold: int = 5  # 连续失败次数阈值
    circuit_breaker_recovery_time: int = 30  # 恢复时间（秒）

    # 模块路由表
    routes: List[ModuleRoute] = Field(default_factory=list)

    @classmethod
    def from_env(cls) -> "GatewaySettings":
        """从环境变量加载配置（向后兼容旧接口）

        .. deprecated:: 2.0.0
            请使用 GatewayModuleConfig 替代。
        """
        routes = [
            # M1 多Agent调度中心
            ModuleRoute(
                key="m1",
                name="M1 多Agent调度中心",
                description="多智能体集群调度与管理",
                target_url=os.getenv("M1_BASE_URL", "http://localhost:8001"),
                prefix="/m1",
                timeout=60.0,
                health_path="/health",
                auth_required=True,
                public_paths=["/health", "/api/v1/public"],
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
                description="技能市场与技能执行引擎",
                target_url=os.getenv("M2_BASE_URL", "http://localhost:8002"),
                prefix="/m2",
                timeout=30.0,
                health_path="/health",
                auth_required=True,
                public_paths=["/health", "/api/v1/skills/public", "/api/v1/categories"],
                rate_limit_per_minute=100,
                rate_limit_per_ip=50,
                rate_limit_tier="public",
                cb_failure_threshold=5,
                cb_recovery_time=30,
            ),
            # M3 端云协同内核
            ModuleRoute(
                key="m3",
                name="M3 端云协同内核",
                description="端云协同计算框架",
                target_url=os.getenv("M3_BASE_URL", "http://localhost:8003"),
                prefix="/m3",
                timeout=120.0,
                health_path="/health",
                auth_required=True,
                public_paths=["/health", "/api/v1/status"],
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
                description="场景模板引擎",
                target_url=os.getenv("M4_BASE_URL", "http://localhost:8004"),
                prefix="/m4",
                timeout=60.0,
                health_path="/health",
                auth_required=True,
                public_paths=["/health", "/api/v1/scenes/public", "/api/v1/templates"],
                rate_limit_per_minute=60,
                rate_limit_per_ip=30,
                rate_limit_tier="public",
                supports_sse=True,
                cb_failure_threshold=5,
                cb_recovery_time=30,
            ),
            # M5 潮汐记忆系统
            ModuleRoute(
                key="m5",
                name="M5 潮汐记忆系统",
                description="长期记忆系统",
                target_url=os.getenv("M5_BASE_URL", "http://localhost:8005"),
                prefix="/m5",
                timeout=30.0,
                health_path="/health",
                auth_required=True,
                public_paths=["/health"],
                rate_limit_per_minute=120,
                rate_limit_per_ip=60,
                rate_limit_tier="public",
                cb_failure_threshold=5,
                cb_recovery_time=30,
            ),
            # M6 硬件外设模拟
            ModuleRoute(
                key="m6",
                name="M6 硬件外设模拟",
                description="硬件外设模拟与管理",
                target_url=os.getenv("M6_BASE_URL", "http://localhost:8006"),
                prefix="/m6",
                timeout=30.0,
                health_path="/health",
                auth_required=True,
                public_paths=["/health", "/api/v1/devices/public"],
                rate_limit_per_minute=60,
                rate_limit_per_ip=30,
                rate_limit_tier="public",
                supports_websocket=True,
                supports_sse=True,
                cb_failure_threshold=5,
                cb_recovery_time=30,
            ),
            # M7 积木平台
            ModuleRoute(
                key="m7",
                name="M7 积木平台",
                description="可视化工作流编排平台",
                target_url=os.getenv("M7_BASE_URL", "http://localhost:8007"),
                prefix="/m7",
                timeout=60.0,
                health_path="/health",
                auth_required=True,
                public_paths=["/health", "/api/v1/workflows/public"],
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
                description="系统管理控制台",
                target_url=os.getenv("M8_BASE_URL", "http://localhost:8008"),
                prefix="/m8",
                timeout=30.0,
                health_path="/health",
                auth_required=True,
                public_paths=[
                    "/health", "/metrics", "/api/v1/auth/login",
                    "/api/v1/status", "/api/v1/public",
                ],
                rate_limit_per_minute=120,
                rate_limit_per_ip=60,
                rate_limit_tier="admin",
                cb_failure_threshold=10,
                cb_recovery_time=15,
            ),
            # M9 开发者工坊
            ModuleRoute(
                key="m9",
                name="M9 开发者工坊",
                description="开发者工具集",
                target_url=os.getenv("M9_BASE_URL", "http://localhost:8009"),
                prefix="/m9",
                timeout=120.0,
                health_path="/health",
                auth_required=True,
                public_paths=["/health", "/api/v1/public"],
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
                description="系统监控与运维管理",
                target_url=os.getenv("M10_BASE_URL", "http://localhost:8010"),
                prefix="/m10",
                timeout=30.0,
                health_path="/health",
                auth_required=True,
                public_paths=["/health", "/api/v1/status"],
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
                description="MCP协议总线",
                target_url=os.getenv("M11_BASE_URL", "http://localhost:8011"),
                prefix="/m11",
                timeout=60.0,
                health_path="/health",
                auth_required=True,
                public_paths=["/health", "/api/v1/tools/public", "/sse"],
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
                description="安全防护中心",
                target_url=os.getenv("M12_BASE_URL", "http://localhost:8012"),
                prefix="/m12",
                timeout=30.0,
                health_path="/health",
                auth_required=True,
                public_paths=[
                    "/health", "/api/v1/auth/login", "/api/v1/auth/register",
                    "/api/v1/auth/password/forgot", "/api/v1/auth/password/reset",
                    "/api/v1/status", "/api/v1/public-key",
                ],
                rate_limit_per_minute=60,
                rate_limit_per_ip=30,
                rate_limit_tier="public",
                cb_failure_threshold=10,
                cb_recovery_time=15,
            ),
        ]

        return cls(
            host=os.getenv("GATEWAY_HOST", "0.0.0.0"),
            port=int(os.getenv("GATEWAY_PORT", "8080")),
            log_level=os.getenv("GATEWAY_LOG_LEVEL", "info"),
            env=os.getenv("YUNXI_ENV", os.getenv("ENV", "development")),
            cors_origins=os.getenv("GATEWAY_CORS_ORIGINS", os.getenv("CORS_ORIGINS", "*")),
            api_key_header=os.getenv("GATEWAY_API_KEY_HEADER", "X-API-Key"),
            jwt_header=os.getenv("GATEWAY_JWT_HEADER", "Authorization"),
            rate_limit_per_minute=int(os.getenv("GATEWAY_RATE_LIMIT_TOTAL", "600")),
            rate_limit_per_ip=int(os.getenv("GATEWAY_RATE_LIMIT_PER_IP", "100")),
            circuit_breaker_threshold=int(os.getenv("GATEWAY_CB_THRESHOLD", "5")),
            circuit_breaker_recovery_time=int(os.getenv("GATEWAY_CB_RECOVERY", "30")),
            routes=routes,
        )


# 向后兼容：旧的 settings 单例
settings = GatewaySettings.from_env()
