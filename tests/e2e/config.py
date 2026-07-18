"""
E2E 测试配置管理

提供 E2E 测试所需的所有配置项，包括：
- 测试环境配置（开发/测试/预发）
- 各模块服务地址
- 认证配置
- 测试数据配置
- 超时与重试配置
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
@dataclass
class E2ETestConfig:
    """
    E2E 测试配置

    所有配置项均可通过环境变量覆盖，命名规则：E2E_<配置名大写>
    例如：E2E_BASE_URL=http://localhost:8080
    """

    # ============================================================
    # 基础配置
    # ============================================================

    # 测试环境：testing / staging / production
    env: str = field(default_factory=lambda: os.getenv("E2E_ENV", "testing"))

    # 是否使用 mock 后端（不依赖真实服务）
    use_mock: bool = field(default_factory=lambda: os.getenv("E2E_USE_MOCK", "1") == "1")

    # 测试运行模式：sync（同步）/ async（异步）
    run_mode: str = field(default_factory=lambda: os.getenv("E2E_RUN_MODE", "sync"))

    # ============================================================
    # 服务地址配置
    # ============================================================

    # API 网关地址
    gateway_url: str = field(
        default_factory=lambda: os.getenv("E2E_GATEWAY_URL", "http://127.0.0.1:8080")
    )

    # M0 主理人管控台地址
    m0_url: str = field(
        default_factory=lambda: os.getenv("E2E_M0_URL", "http://127.0.0.1:18080")
    )

    # M1 Agent Hub 地址
    m1_url: str = field(
        default_factory=lambda: os.getenv("E2E_M1_URL", "http://127.0.0.1:8001")
    )

    # M2 技能集群地址
    m2_url: str = field(
        default_factory=lambda: os.getenv("E2E_M2_URL", "http://127.0.0.1:8002")
    )

    # M4 场景引擎地址
    m4_url: str = field(
        default_factory=lambda: os.getenv("E2E_M4_URL", "http://127.0.0.1:8004")
    )

    # M5 潮汐记忆地址
    m5_url: str = field(
        default_factory=lambda: os.getenv("E2E_M5_URL", "http://127.0.0.1:8005")
    )

    # M7 工作流地址
    m7_url: str = field(
        default_factory=lambda: os.getenv("E2E_M7_URL", "http://127.0.0.1:8007")
    )

    # M8 控制塔地址
    m8_url: str = field(
        default_factory=lambda: os.getenv("E2E_M8_URL", "http://127.0.0.1:8008")
    )

    # M9 开发工坊地址
    m9_url: str = field(
        default_factory=lambda: os.getenv("E2E_M9_URL", "http://127.0.0.1:8009")
    )

    # M11 MCP 总线地址
    m11_url: str = field(
        default_factory=lambda: os.getenv("E2E_M11_URL", "http://127.0.0.1:8011")
    )

    # ============================================================
    # 认证配置
    # ============================================================

    # 管理员账号
    admin_username: str = field(
        default_factory=lambda: os.getenv("E2E_ADMIN_USERNAME", "admin")
    )
    admin_password: str = field(
        default_factory=lambda: os.getenv("E2E_ADMIN_PASSWORD", "admin123456")
    )

    # 测试用户账号（自动创建）
    test_user_prefix: str = field(
        default_factory=lambda: os.getenv("E2E_TEST_USER_PREFIX", "e2e_test_user_")
    )

    # JWT 配置
    jwt_secret: str = field(
        default_factory=lambda: os.getenv(
            "E2E_JWT_SECRET",
            "e2e-test-jwt-secret-key-for-testing-purposes-only-1234567890"
        )
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # ============================================================
    # 超时与重试配置
    # ============================================================

    # 请求超时（秒）
    request_timeout: float = field(
        default_factory=lambda: float(os.getenv("E2E_REQUEST_TIMEOUT", "30"))
    )

    # 最大重试次数
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("E2E_MAX_RETRIES", "3"))
    )

    # 重试间隔（秒）
    retry_interval: float = field(
        default_factory=lambda: float(os.getenv("E2E_RETRY_INTERVAL", "1"))
    )

    # ============================================================
    # 测试数据配置
    # ============================================================

    # 测试数据清理策略：auto / manual / none
    cleanup_strategy: str = field(
        default_factory=lambda: os.getenv("E2E_CLEANUP_STRATEGY", "auto")
    )

    # 是否保留失败测试的数据（用于调试）
    preserve_failed_data: bool = field(
        default_factory=lambda: os.getenv("E2E_PRESERVE_FAILED_DATA", "0") == "1"
    )

    # 测试数据目录
    test_data_dir: str = field(
        default_factory=lambda: os.getenv(
            "E2E_TEST_DATA_DIR",
            str(PROJECT_ROOT / "tests" / "e2e" / "test_data")
        )
    )

    # ============================================================
    # 报告配置
    # ============================================================

    # 是否生成测试报告
    generate_report: bool = field(
        default_factory=lambda: os.getenv("E2E_GENERATE_REPORT", "1") == "1"
    )

    # 报告输出目录
    report_dir: str = field(
        default_factory=lambda: os.getenv(
            "E2E_REPORT_DIR",
            str(PROJECT_ROOT / "tests" / "reports" / "e2e")
        )
    )

    # 报告格式：html / json / all
    report_format: str = field(
        default_factory=lambda: os.getenv("E2E_REPORT_FORMAT", "html")
    )

    # ============================================================
    # 模块配置
    # ============================================================

    # 需要测试的模块列表
    target_modules: List[str] = field(default_factory=lambda: [
        "m0", "m1", "m2", "m4", "m5", "m7", "m8", "m9", "m11", "gateway"
    ])

    # 模块路由前缀映射
    module_prefixes: Dict[str, str] = field(default_factory=lambda: {
        "m0": "/m0",
        "m1": "/m1",
        "m2": "/m2",
        "m3": "/m3",
        "m4": "/m4",
        "m5": "/m5",
        "m6": "/m6",
        "m7": "/m7",
        "m8": "/m8",
        "m9": "/m9",
        "m10": "/m10",
        "m11": "/m11",
        "m12": "/m12",
    })

    # ============================================================
    # 性能阈值配置
    # ============================================================

    # API 响应时间阈值（毫秒）
    api_response_time_threshold_ms: int = 3000

    # 页面加载时间阈值（毫秒）
    page_load_time_threshold_ms: int = 5000

    # ============================================================
    # 便捷方法
    # ============================================================

    def get_module_url(self, module: str) -> Optional[str]:
        """获取指定模块的 URL"""
        url_attr = f"{module.lower()}_url"
        return getattr(self, url_attr, None)

    def get_module_prefix(self, module: str) -> Optional[str]:
        """获取指定模块的路由前缀"""
        return self.module_prefixes.get(module.lower())

    def is_module_enabled(self, module: str) -> bool:
        """检查模块是否在测试目标列表中"""
        return module.lower() in self.target_modules

    @property
    def is_testing_env(self) -> bool:
        """是否为测试环境"""
        return self.env == "testing"

    @property
    def is_staging_env(self) -> bool:
        """是否为预发环境"""
        return self.env == "staging"

    @property
    def is_production_env(self) -> bool:
        """是否为生产环境"""
        return self.env == "production"


# 全局配置单例
_e2e_config: Optional[E2ETestConfig] = None


def get_e2e_config() -> E2ETestConfig:
    """获取 E2E 测试配置单例"""
    global _e2e_config
    if _e2e_config is None:
        _e2e_config = E2ETestConfig()
    return _e2e_config


def reset_e2e_config() -> None:
    """重置配置单例（测试用）"""
    global _e2e_config
    _e2e_config = None
