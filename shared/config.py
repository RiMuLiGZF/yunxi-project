"""
云汐系统全局配置模块
统一管理所有模块的配置信息，支持环境变量覆盖
"""

import os
from pathlib import Path
from typing import Optional


class YunxiConfig:
    """云汐系统全局配置类"""

    def __init__(self):
        # 项目根目录
        self.project_root: Path = Path(__file__).resolve().parent.parent

        # ===== 模块端口配置 =====
        self.module_ports: dict = {
            "m0": int(os.getenv("M0_PORT", "8000")),
            "m1": int(os.getenv("M1_PORT", "8001")),
            "m2": int(os.getenv("M2_PORT", "8002")),
            "m3": int(os.getenv("M3_PORT", "8003")),
            "m4": int(os.getenv("M4_PORT", "8004")),
            "m5": int(os.getenv("M5_PORT", "8005")),
            "m6": int(os.getenv("M6_PORT", "8006")),
            "m7": int(os.getenv("M7_PORT", "8007")),
            "m8": int(os.getenv("M8_PORT", "8008")),
            "m10": int(os.getenv("M10_PORT", "8010")),
            "m11": int(os.getenv("M11_PORT", "8011")),
            "m12": int(os.getenv("M12_PORT", "8012")),
        }

        # ===== 模块主机配置 =====
        self.module_hosts: dict = {
            "m0": os.getenv("M0_HOST", "0.0.0.0"),
            "m1": os.getenv("M1_HOST", "0.0.0.0"),
            "m2": os.getenv("M2_HOST", "0.0.0.0"),
            "m3": os.getenv("M3_HOST", "0.0.0.0"),
            "m4": os.getenv("M4_HOST", "0.0.0.0"),
            "m5": os.getenv("M5_HOST", "0.0.0.0"),
            "m6": os.getenv("M6_HOST", "0.0.0.0"),
            "m7": os.getenv("M7_HOST", "0.0.0.0"),
            "m8": os.getenv("M8_HOST", "0.0.0.0"),
            "m10": os.getenv("M10_HOST", "0.0.0.0"),
            "m11": os.getenv("M11_HOST", "0.0.0.0"),
            "m12": os.getenv("M12_HOST", "0.0.0.0"),
        }

        # ===== 模块管理令牌配置 =====
        self.module_tokens: dict = {
            "m0": os.getenv("M0_ADMIN_TOKEN", "yunxi-m0-admin-token-2026"),
            "m1": os.getenv("M1_ADMIN_TOKEN", "yunxi-m1-admin-token-2026"),
            "m2": os.getenv("M2_ADMIN_TOKEN", "yunxi-m2-admin-token-2026"),
            "m3": os.getenv("M3_ADMIN_TOKEN", "yunxi-m3-admin-token-2026"),
            "m4": os.getenv("M4_ADMIN_TOKEN", "yunxi-m4-admin-token-2026"),
            "m5": os.getenv("M5_ADMIN_TOKEN", "yunxi-m5-admin-token-2026"),
            "m6": os.getenv("M6_ADMIN_TOKEN", "yunxi-m6-admin-token-2026"),
            "m7": os.getenv("M7_ADMIN_TOKEN", "yunxi-m7-admin-token-2026"),
            "m8": os.getenv("M8_ADMIN_TOKEN", "yunxi-m8-admin-token-2026"),
            "m10": os.getenv("M10_ADMIN_TOKEN", "yunxi-m10-admin-token-2026"),
            "m11": os.getenv("M11_ADMIN_TOKEN", "yunxi-m11-admin-token-2026"),
            "m12": os.getenv("M12_ADMIN_TOKEN", "yunxi-m12-admin-token-2026"),
        }

        # ===== 模块 Base URL 配置 =====
        self.module_base_urls: dict = {
            "m0": os.getenv("M0_BASE_URL", "http://localhost:8000"),
            "m1": os.getenv("M1_BASE_URL", "http://localhost:8001"),
            "m2": os.getenv("M2_BASE_URL", "http://localhost:8002"),
            "m3": os.getenv("M3_BASE_URL", "http://localhost:8003"),
            "m4": os.getenv("M4_BASE_URL", "http://localhost:8004"),
            "m5": os.getenv("M5_BASE_URL", "http://localhost:8005"),
            "m6": os.getenv("M6_BASE_URL", "http://localhost:8006"),
            "m7": os.getenv("M7_BASE_URL", "http://localhost:8007"),
            "m8": os.getenv("M8_BASE_URL", "http://localhost:8008"),
            "m10": os.getenv("M10_BASE_URL", "http://localhost:8010"),
            "m11": os.getenv("M11_BASE_URL", "http://localhost:8011"),
            "m12": os.getenv("M12_BASE_URL", "http://localhost:8012"),
        }

        # ===== 模块 Python 可执行文件配置（进程管理用） =====
        self.module_python_executables: dict = {
            "m0": os.getenv("M0_PYTHON", "python"),
            "m1": os.getenv("M1_PYTHON", "python"),
            "m2": os.getenv("M2_PYTHON", "python"),
            "m3": os.getenv("M3_PYTHON", "python"),
            "m4": os.getenv("M4_PYTHON", "python"),
            "m5": os.getenv("M5_PYTHON", "python"),
            "m6": os.getenv("M6_PYTHON", "python"),
            "m7": os.getenv("M7_PYTHON", "python"),
            "m8": os.getenv("M8_PYTHON", "python"),
            "m10": os.getenv("M10_PYTHON", "python"),
            "m11": os.getenv("M11_PYTHON", "python"),
            "m12": os.getenv("M12_PYTHON", "python"),
        }

        # ===== 模块健康检查路径配置 =====
        self.module_health_checks: dict = {
            "m0": "/health",
            "m1": "/health",
            "m2": "/health",
            "m3": "/health",
            "m4": "/health",
            "m5": "/health",
            "m6": "/health",
            "m7": "/health",
            "m8": "/health",
            "m10": "/health",
            "m11": "/health",
            "m12": "/health",
        }

        # ===== 全局安全配置 =====
        self.jwt_secret: str = os.getenv("JWT_SECRET", "yunxi-jwt-secret-key-2026")
        self.jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.access_token_expire_minutes: int = int(
            os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
        )

    def get_module_port(self, module_key: str) -> Optional[int]:
        """获取指定模块的端口号"""
        return self.module_ports.get(module_key)

    def get_module_host(self, module_key: str) -> Optional[str]:
        """获取指定模块的主机地址"""
        return self.module_hosts.get(module_key)

    def get_module_token(self, module_key: str) -> Optional[str]:
        """获取指定模块的管理令牌"""
        return self.module_tokens.get(module_key)

    def get_module_base_url(self, module_key: str) -> Optional[str]:
        """获取指定模块的 Base URL"""
        return self.module_base_urls.get(module_key)

    def get_module_python_executable(self, module_key: str) -> Optional[str]:
        """获取指定模块的 Python 可执行文件路径（进程管理用）"""
        return self.module_python_executables.get(module_key)

    def get_module_health_check(self, module_key: str) -> Optional[str]:
        """获取指定模块的健康检查路径"""
        return self.module_health_checks.get(module_key)

    def get_all_module_keys(self) -> list:
        """获取所有模块的 key 列表"""
        return list(self.module_ports.keys())


# 全局配置单例
_config: Optional[YunxiConfig] = None


def get_config() -> YunxiConfig:
    """获取全局配置实例（单例模式）"""
    global _config
    if _config is None:
        _config = YunxiConfig()
    return _config
