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
    """模块路由配置"""
    key: str
    name: str
    target_url: str
    prefix: str  # 路由前缀，如 /m1, /m8
    enabled: bool = True
    timeout: float = 30.0  # 超时时间（秒）


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
            """从环境变量构建默认路由表"""
            routes = [
                ModuleRoute(
                    key="m8",
                    name="M8 管理控制塔",
                    target_url=os.getenv("M8_BASE_URL", "http://localhost:8008"),
                    prefix="/m8",
                ),
                ModuleRoute(
                    key="m1",
                    name="M1 多Agent集群",
                    target_url=os.getenv("M1_BASE_URL", "http://localhost:8001"),
                    prefix="/m1",
                ),
                ModuleRoute(
                    key="m2",
                    name="M2 技能集群",
                    target_url=os.getenv("M2_BASE_URL", "http://localhost:8002"),
                    prefix="/m2",
                ),
                ModuleRoute(
                    key="m3",
                    name="M3 端云协同",
                    target_url=os.getenv("M3_BASE_URL", "http://localhost:8003"),
                    prefix="/m3",
                ),
                ModuleRoute(
                    key="m4",
                    name="M4 场景引擎",
                    target_url=os.getenv("M4_BASE_URL", "http://localhost:8004"),
                    prefix="/m4",
                ),
                ModuleRoute(
                    key="m5",
                    name="M5 潮汐记忆",
                    target_url=os.getenv("M5_BASE_URL", "http://localhost:8005"),
                    prefix="/m5",
                ),
                ModuleRoute(
                    key="m6",
                    name="M6 硬件外设",
                    target_url=os.getenv("M6_BASE_URL", "http://localhost:8006"),
                    prefix="/m6",
                ),
                ModuleRoute(
                    key="m7",
                    name="M7 工作流编排",
                    target_url=os.getenv("M7_BASE_URL", "http://localhost:8007"),
                    prefix="/m7",
                ),
                ModuleRoute(
                    key="m9",
                    name="M9 开发者工坊",
                    target_url=os.getenv("M9_BASE_URL", "http://localhost:8009"),
                    prefix="/m9",
                ),
                ModuleRoute(
                    key="m10",
                    name="M10 系统卫士",
                    target_url=os.getenv("M10_BASE_URL", "http://localhost:8010"),
                    prefix="/m10",
                ),
                ModuleRoute(
                    key="m11",
                    name="M11 MCP总线",
                    target_url=os.getenv("M11_BASE_URL", "http://localhost:8011"),
                    prefix="/m11",
                ),
                ModuleRoute(
                    key="m12",
                    name="M12 安全盾",
                    target_url=os.getenv("M12_BASE_URL", "http://localhost:8012"),
                    prefix="/m12",
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
        """从环境变量加载配置（向后兼容旧接口）"""
        routes = [
            ModuleRoute(
                key="m8",
                name="M8 管理控制塔",
                target_url=os.getenv("M8_BASE_URL", "http://localhost:8008"),
                prefix="/m8",
            ),
            ModuleRoute(
                key="m1",
                name="M1 多Agent集群",
                target_url=os.getenv("M1_BASE_URL", "http://localhost:8001"),
                prefix="/m1",
            ),
            ModuleRoute(
                key="m2",
                name="M2 技能集群",
                target_url=os.getenv("M2_BASE_URL", "http://localhost:8002"),
                prefix="/m2",
            ),
            ModuleRoute(
                key="m3",
                name="M3 端云协同",
                target_url=os.getenv("M3_BASE_URL", "http://localhost:8003"),
                prefix="/m3",
            ),
            ModuleRoute(
                key="m4",
                name="M4 场景引擎",
                target_url=os.getenv("M4_BASE_URL", "http://localhost:8004"),
                prefix="/m4",
            ),
            ModuleRoute(
                key="m5",
                name="M5 潮汐记忆",
                target_url=os.getenv("M5_BASE_URL", "http://localhost:8005"),
                prefix="/m5",
            ),
            ModuleRoute(
                key="m6",
                name="M6 硬件外设",
                target_url=os.getenv("M6_BASE_URL", "http://localhost:8006"),
                prefix="/m6",
            ),
            ModuleRoute(
                key="m7",
                name="M7 工作流编排",
                target_url=os.getenv("M7_BASE_URL", "http://localhost:8007"),
                prefix="/m7",
            ),
            ModuleRoute(
                key="m9",
                name="M9 开发者工坊",
                target_url=os.getenv("M9_BASE_URL", "http://localhost:8009"),
                prefix="/m9",
            ),
            ModuleRoute(
                key="m10",
                name="M10 系统卫士",
                target_url=os.getenv("M10_BASE_URL", "http://localhost:8010"),
                prefix="/m10",
            ),
            ModuleRoute(
                key="m11",
                name="M11 MCP总线",
                target_url=os.getenv("M11_BASE_URL", "http://localhost:8011"),
                prefix="/m11",
            ),
            ModuleRoute(
                key="m12",
                name="M12 安全盾",
                target_url=os.getenv("M12_BASE_URL", "http://localhost:8012"),
                prefix="/m12",
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
