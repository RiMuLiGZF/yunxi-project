"""
M6 硬件外设 - 配置管理
从环境变量和 yunxi.env 加载配置

配置项清单：
+---------------------------+---------------------------------+-----------------------------+----------+
| 配置项                    | 环境变量名                     | 默认值                      | 说明     |
+===========================+=================================+=============================+==========+
| module_name               | M6_NAME                        | m6-hardware                 | 模块名称 |
+---------------------------+---------------------------------+-----------------------------+----------+
| host                      | M6_HOST                       | 0.0.0.0                     | 监听地址 |
+---------------------------+---------------------------------+-----------------------------+----------+
| port                      | M6_PORT                       | 8006                        | 监听端口 |
+---------------------------+---------------------------------+-----------------------------+----------+
| env                       | M6_ENV                        | development                 | 运行环境 |
+---------------------------+---------------------------------+-----------------------------+----------+
| admin_token               | M6_ADMIN_TOKEN                | 生产: 无(必填)/开发: 随机 | 管理令牌 |
+---------------------------+---------------------------------+-----------------------------+----------+
| simulation_mode           | M6_SIMULATION_MODE            | true                        | 模拟模式 |
+---------------------------+---------------------------------+-----------------------------+----------+
| database_path             | M6_DATABASE_PATH              | data/m6_sensors.db          | 数据库路径 |
+---------------------------+---------------------------------+-----------------------------+----------+
| collection_interval       | M6_COLLECTION_INTERVAL        | 5                           | 采集间隔(秒) |
+---------------------------+---------------------------------+-----------------------------+----------+
| data_retention_days       | M6_DATA_RETENTION_DAYS        | 30                          | 数据保留天数 |
+---------------------------+---------------------------------+-----------------------------+----------+
| sse_token_ttl             | M6_SSE_TOKEN_TTL              | 300                         | SSE令牌有效期(秒) |
+---------------------------+---------------------------------+-----------------------------+----------+
| sse_max_connections       | M6_SSE_MAX_CONNECTIONS        | 100                         | SSE最大连接数 |
+---------------------------+---------------------------------+-----------------------------+----------+
| cors_origins              | CORS_ORIGINS                  | *                           | CORS允许来源 |
+---------------------------+---------------------------------+-----------------------------+----------+
| log_level                 | YUNXI_LOG_LEVEL               | info                        | 日志级别 |
+---------------------------+---------------------------------+-----------------------------+----------+
"""

import os
import secrets
import logging
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


class M6Config:
    """M6 硬件外设配置类

    P0-4 改造：移除 __new__ 单例模式，改为由 FastAPI lifespan 统一创建管理。
    模块级 get_config() 作为向后兼容层保留（标记 deprecated）。
    """

    def __init__(self):
        self._load_config()

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

        # 运行环境
        self.env = os.getenv("M6_ENV", "development").lower()

        # 基础配置
        self.module_name = os.getenv("M6_NAME", "m6-hardware")
        self.port = int(os.getenv("M6_PORT", "8006"))
        self.host = os.getenv("M6_HOST", "0.0.0.0")
        self.simulation_mode = os.getenv("M6_SIMULATION_MODE", "true").lower() == "true"

        # 管理员 Token（通过 property 动态获取，见 admin_token）
        self._admin_token_env = os.getenv("M6_ADMIN_TOKEN")
        self._admin_token_generated = None

        # 数据库配置
        default_db_path = str(Path(__file__).parent.parent / "data" / "m6_sensors.db")
        self.database_path = os.getenv("M6_DATABASE_PATH", default_db_path)

        # 数据采集配置
        self.collection_interval = float(os.getenv("M6_COLLECTION_INTERVAL", "5"))  # 秒
        self.data_retention_days = int(os.getenv("M6_DATA_RETENTION_DAYS", "30"))

        # SSE 配置
        self.sse_token_ttl = int(os.getenv("M6_SSE_TOKEN_TTL", "300"))  # SSE令牌有效期(秒)
        self.sse_max_connections = int(os.getenv("M6_SSE_MAX_CONNECTIONS", "100"))  # 最大连接数

        # CORS 配置
        self.cors_origins = os.getenv("CORS_ORIGINS", "*")

        # 日志配置
        self.log_level = os.getenv("YUNXI_LOG_LEVEL", "info")

    @property
    def admin_token(self) -> str:
        """
        管理员 Token，动态获取。

        - 生产环境（env=production）：未配置则抛出 RuntimeError，阻止启动
        - 开发环境（env=development）：未配置则生成随机一次性 Token，并打印 warning 日志
        """
        # 优先使用环境变量中配置的 Token
        if self._admin_token_env:
            return self._admin_token_env

        if self.env == "production":
            raise RuntimeError(
                "生产环境必须配置 M6_ADMIN_TOKEN，禁止使用默认值。"
                "请在环境变量或 config/yunxi.env 中设置 M6_ADMIN_TOKEN。"
            )

        # 开发环境：生成随机一次性 Token
        if self._admin_token_generated is None:
            self._admin_token_generated = secrets.token_urlsafe(32)
            logger.warning(
                "开发环境未配置 M6_ADMIN_TOKEN，已自动生成一次性随机 Token：%s",
                self._admin_token_generated,
            )
        return self._admin_token_generated

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


_instance: M6Config | None = None


def get_config() -> M6Config:
    """获取 M6 配置单例

    .. deprecated:: P0-4
        推荐使用 FastAPI 依赖注入 ``Depends(get_config)`` 方式，
        由 lifespan 统一管理实例生命周期。本函数作为向后兼容层保留。
    """
    global _instance
    if _instance is None:
        _instance = M6Config()
    return _instance


# 系统版本号（统一从 shared.version 导入）
def _load_system_version() -> str:
    """从 shared.version 导入系统版本号，导入失败则回退到默认值"""
    try:
        # 查找项目根目录并加入 sys.path
        current = Path(__file__).resolve().parent
        for _ in range(10):
            if (current / "shared" / "version.py").exists():
                import sys
                if str(current) not in sys.path:
                    sys.path.insert(0, str(current))
                break
            current = current.parent
        from shared.version import SYSTEM_VERSION
        return SYSTEM_VERSION
    except Exception:
        return "v1.0.0"


SYSTEM_VERSION = _load_system_version()
