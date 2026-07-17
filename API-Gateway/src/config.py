"""
云汐 API 网关配置
"""
import os
from typing import List, Dict, Optional
from pydantic import BaseModel, Field


class ModuleRoute(BaseModel):
    """模块路由配置"""
    key: str
    name: str
    target_url: str
    prefix: str  # 路由前缀，如 /m1, /m8
    enabled: bool = True
    timeout: float = 30.0  # 超时时间（秒）


class GatewaySettings(BaseModel):
    """网关配置"""
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
        """从环境变量加载配置"""
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


settings = GatewaySettings.from_env()
