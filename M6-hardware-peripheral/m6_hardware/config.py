"""
M6 硬件外设 - 配置管理
从环境变量和 yunxi.env 加载配置
"""

import os
from pathlib import Path
from typing import Optional


class M6Config:
    """M6 硬件外设配置类"""

    _instance = None
    _loaded = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._loaded:
            return
        self._load_config()
        self._loaded = True

    def _load_config(self):
        """加载配置文件和环境变量"""
        # 从项目根目录查找 config/yunxi.env
        project_root = self._find_project_root()
        if project_root:
            env_file = project_root / "config" / "yunxi.env"
            if env_file.exists():
                try:
                    from dotenv import load_dotenv
                    load_dotenv(env_file, override=False)
                except ImportError:
                    self._manual_load_env(env_file)

        # 基础配置
        self.module_name = os.getenv("M6_NAME", "m6-hardware")
        self.port = int(os.getenv("M6_PORT", "8006"))
        self.host = os.getenv("M6_HOST", "0.0.0.0")
        self.admin_token = os.getenv("M6_ADMIN_TOKEN", "yunxi-m6-admin-token-2026")
        self.simulation_mode = os.getenv("M6_SIMULATION_MODE", "true").lower() == "true"

        # 数据库配置
        default_db_path = str(Path(__file__).parent.parent / "data" / "m6_sensors.db")
        self.database_path = os.getenv("M6_DATABASE_PATH", default_db_path)

        # 数据采集配置
        self.collection_interval = float(os.getenv("M6_COLLECTION_INTERVAL", "5"))  # 秒
        self.history_retention_days = int(os.getenv("M6_HISTORY_RETENTION_DAYS", "30"))

        # CORS 配置
        self.cors_origins = os.getenv("CORS_ORIGINS", "*")

        # 日志配置
        self.log_level = os.getenv("YUNXI_LOG_LEVEL", "info")

    def _find_project_root(self) -> Optional[Path]:
        """从当前目录向上查找包含 config/yunxi.env 的项目根目录"""
        current = Path(__file__).resolve().parent
        for _ in range(10):
            if (current / "config" / "yunxi.env").exists():
                return current
            current = current.parent
        return None

    def _manual_load_env(self, env_file: Path):
        """手动加载 .env 文件（当 python-dotenv 不可用时）"""
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
        except Exception:
            pass


def get_config() -> M6Config:
    """获取 M6 配置单例"""
    return M6Config()


# 系统版本号（统一从 shared.version 导入）
# from shared.version import SYSTEM_VERSION
SYSTEM_VERSION = "0.4.0"  # 与 shared/version.py 保持同步
