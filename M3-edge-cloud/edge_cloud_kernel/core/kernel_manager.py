"""内核组件管理器.

封装所有 M3 核心组件的初始化逻辑，支持 mock 模式降级。
每个组件独立 try/except，确保服务能够正常启动。

8 大组件：
    1. ConfigManager       - 配置管理器
    2. DeviceRegistry      - 设备注册表
    3. ConflictResolver    - 冲突解决器
    4. OfflineShadowProxy  - 离线影子代理
    5. HealthChecker       - 健康探测器
    6. ContextSyncController - 上下文同步控制器
    7. HealthMetricsService  - 健康指标服务
    8. M8APIService        - M8 API 服务
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger(__name__)


class KernelManager:
    """M3 内核组件管理器.

    负责所有核心组件的初始化、mock 降级和生命周期管理。
    每个组件独立初始化，失败时自动降级为 mock 模式。

    Attributes:
        _services: 组件实例字典.
        _mock_mode: 各组件的 mock 模式标记.
        _start_time: 内核启动时间戳.
        _base_dir: 基础目录路径.
        _project_root: 项目根目录路径.
        _config_path: 配置文件路径.
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        project_root: Path | None = None,
        config_path: Path | None = None,
    ) -> None:
        """初始化内核管理器.

        Args:
            base_dir: 基础目录（server.py 所在目录）.
            project_root: 项目根目录（包含 config/yunxi.env）.
            config_path: 配置文件路径.
        """
        self._services: dict[str, Any] = {}
        self._mock_mode: dict[str, bool] = {}
        self._start_time: float = time.time()
        self._base_dir = base_dir or Path(__file__).resolve().parent.parent.parent
        self._project_root = project_root
        self._config_path = config_path or (
            self._base_dir / "edge_cloud_kernel" / "config" / "config.yaml"
        )

    # -----------------------------------------------------------------------
    # 环境与配置初始化
    # -----------------------------------------------------------------------

    def _find_project_root(self) -> Path | None:
        """从当前目录向上查找包含 config/yunxi.env 的项目根目录.

        Returns:
            项目根目录路径，未找到则返回 None.
        """
        current = self._base_dir
        for _ in range(10):
            if (current / "config" / "yunxi.env").exists():
                return current
            current = current.parent
        return None

    def _load_yunxi_env(self) -> None:
        """从项目根目录的 config/yunxi.env 加载环境变量."""
        if self._project_root is None:
            self._project_root = self._find_project_root()

        if self._project_root is None:
            logger.warning("yunxi_env.not_found", hint="项目根目录未找到，将使用默认配置")
            return

        env_path = self._project_root / "config" / "yunxi.env"
        if not env_path.exists():
            logger.warning("yunxi_env.file_not_found", path=str(env_path))
            return

        try:
            from dotenv import load_dotenv

            load_dotenv(env_path, override=False)
            logger.info("yunxi_env.loaded", path=str(env_path))
        except ImportError:
            # python-dotenv 不可用时手动解析
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
                logger.info("yunxi_env.loaded_manual", path=str(env_path))
            except Exception as e:
                logger.warning("yunxi_env.load_failed", error=str(e))

    def _ensure_config_file(self) -> None:
        """从 config.example.yaml 复制创建 config.yaml（如果不存在）."""
        config_path = Path(self._config_path)
        config_dir = config_path.parent
        config_example_path = config_dir / "config.example.yaml"

        if config_path.exists():
            logger.info("config.file_exists", path=str(config_path))
            return

        if not config_example_path.exists():
            logger.warning("config.example_not_found", path=str(config_example_path))
            return

        # 确保 config 目录存在
        config_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(config_example_path, config_path)
        logger.info("config.created_from_example", path=str(config_path))

    # -----------------------------------------------------------------------
    # 组件初始化
    # -----------------------------------------------------------------------

    def init_all(self) -> None:
        """初始化所有核心组件.

        按依赖顺序依次初始化，每个组件独立 try/except，
        失败时标记为 mock 模式，确保服务能够正常启动。

        初始化流程：
            1. 加载 yunxi.env 环境变量
            2. 确保 config.yaml 配置文件存在
            3. 初始化 8 大核心组件
        """
        # 1. 加载 yunxi.env
        self._load_yunxi_env()

        # 2. 确保配置文件存在
        self._ensure_config_file()

        # 3. 初始化组件
        self._init_config_manager()
        self._init_device_registry()
        self._init_conflict_resolver()
        self._init_offline_proxy()
        self._init_health_checker()
        self._init_sync_controller()
        self._init_health_metrics()
        self._init_m8_api()

        self._services["_start_time"] = self._start_time

        # 统计
        total = len([k for k in self._mock_mode if not k.startswith("_")])
        ok_count = sum(
            1 for k, v in self._mock_mode.items()
            if not k.startswith("_") and not v
        )
        logger.info(
            "components.init_summary",
            total=total,
            ok=ok_count,
            mock=total - ok_count,
        )

    def _init_config_manager(self) -> None:
        """初始化配置管理器."""
        try:
            from edge_cloud_kernel.m8_api.config_endpoints import ConfigManager

            config_manager = ConfigManager(config_path=str(self._config_path))
            # 用环境变量覆盖关键配置
            self._apply_env_overrides(config_manager)
            self._services["config_manager"] = config_manager
            self._mock_mode["config_manager"] = False
            logger.info("component.init_ok", name="ConfigManager")
        except Exception as e:
            logger.error("component.init_failed", name="ConfigManager", error=str(e))
            self._mock_mode["config_manager"] = True

    def _init_device_registry(self) -> None:
        """初始化设备注册表."""
        try:
            from edge_cloud_kernel.m8_api.device_registry import create_device_registry

            _reg_type = "sqlite"
            _db_path = self._default_db_path("devices.db")
            try:
                config_manager = self._services.get("config_manager")
                if config_manager is not None:
                    _reg_type = config_manager.get("devices.registry_type", "sqlite")
                    _db_path = config_manager.get("devices.db_path", _db_path)
            except Exception:
                pass

            Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
            device_registry = create_device_registry(
                registry_type=_reg_type, db_path=_db_path
            )
            self._services["device_registry"] = device_registry
            self._mock_mode["device_registry"] = False
            logger.info(
                "component.init_ok", name=f"DeviceRegistry({_reg_type})"
            )
        except Exception as e:
            logger.error("component.init_failed", name="DeviceRegistry", error=str(e))
            self._mock_mode["device_registry"] = True

    def _init_conflict_resolver(self) -> None:
        """初始化冲突解决器."""
        try:
            from edge_cloud_kernel.local_data.conflict_resolver import ConflictResolver

            conflict_resolver = ConflictResolver()
            self._services["conflict_resolver"] = conflict_resolver
            self._mock_mode["conflict_resolver"] = False
            logger.info("component.init_ok", name="ConflictResolver")
        except Exception as e:
            logger.error("component.init_failed", name="ConflictResolver", error=str(e))
            self._mock_mode["conflict_resolver"] = True

    def _init_offline_proxy(self) -> None:
        """初始化离线影子代理（可选，依赖较多，失败则跳过）."""
        try:
            from edge_cloud_kernel.sync.offline_shadow_proxy import OfflineShadowProxy

            data_dir = self._base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            offline_proxy = OfflineShadowProxy(
                db_path=str(data_dir / "offline_queue.db"),
            )
            self._services["offline_proxy"] = offline_proxy
            self._mock_mode["offline_proxy"] = False
            logger.info("component.init_ok", name="OfflineShadowProxy")
        except Exception as e:
            logger.warning("component.init_skipped", name="OfflineShadowProxy", error=str(e))
            self._mock_mode["offline_proxy"] = True

    def _init_health_checker(self) -> None:
        """初始化健康探测器（可选）."""
        try:
            from edge_cloud_kernel.gateway.health_checker import HealthChecker

            health_checker = HealthChecker()
            self._services["health_checker"] = health_checker
            self._mock_mode["health_checker"] = False
            logger.info("component.init_ok", name="HealthChecker")
        except Exception as e:
            logger.warning("component.init_skipped", name="HealthChecker", error=str(e))
            self._mock_mode["health_checker"] = True

    def _init_sync_controller(self) -> None:
        """初始化上下文同步控制器（可选）."""
        try:
            from edge_cloud_kernel.sync.context_sync_controller import (
                ContextSyncController,
            )

            sync_controller = ContextSyncController()
            self._services["sync_controller"] = sync_controller
            self._mock_mode["sync_controller"] = False
            logger.info("component.init_ok", name="ContextSyncController")
        except Exception as e:
            logger.warning("component.init_skipped", name="ContextSyncController", error=str(e))
            self._mock_mode["sync_controller"] = True

    def _init_health_metrics(self) -> None:
        """初始化健康指标服务."""
        try:
            from edge_cloud_kernel.m8_api.health_endpoints import HealthMetricsService

            data_dir = self._base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            health_metrics = HealthMetricsService(
                db_path="",
                storage_path=str(data_dir),
                offline_proxy=self._services.get("offline_proxy"),
                conflict_resolver=self._services.get("conflict_resolver"),
                health_checker=self._services.get("health_checker"),
            )
            self._services["health_metrics"] = health_metrics
            self._mock_mode["health_metrics"] = False
            logger.info("component.init_ok", name="HealthMetricsService")
        except Exception as e:
            logger.error("component.init_failed", name="HealthMetricsService", error=str(e))
            self._mock_mode["health_metrics"] = True

    def _init_m8_api(self) -> None:
        """初始化 M8 API 服务."""
        try:
            from edge_cloud_kernel.m8_api.m8_api_service import M8APIService

            m8_api = M8APIService(
                sync_controller=self._services.get("sync_controller"),
                conflict_resolver=self._services.get("conflict_resolver"),
                offline_proxy=self._services.get("offline_proxy"),
                health_checker=self._services.get("health_checker"),
                device_registry=self._services.get("device_registry"),
            )
            self._services["m8_api"] = m8_api
            self._mock_mode["m8_api"] = False
            logger.info("component.init_ok", name="M8APIService")
        except Exception as e:
            logger.error("component.init_failed", name="M8APIService", error=str(e))
            self._mock_mode["m8_api"] = True

    # -----------------------------------------------------------------------
    # 环境变量覆盖
    # -----------------------------------------------------------------------

    def _apply_env_overrides(self, config_manager: Any) -> None:
        """用环境变量覆盖配置管理器中的关键配置项.

        Args:
            config_manager: 配置管理器实例.
        """
        updates: dict[str, Any] = {}

        # 端口
        port = os.environ.get("M3_PORT")
        if port:
            try:
                updates["basic.port"] = int(port)
            except Exception:
                pass

        # 环境
        env = os.environ.get("YUNXI_ENV") or os.environ.get("M3_ENV")
        if env:
            updates["basic.env"] = env

        # 日志级别
        log_level = os.environ.get("YUNXI_LOG_LEVEL")
        if log_level:
            updates["basic.log_level"] = log_level
            updates["logging.level"] = log_level

        # Admin Token
        admin_token = os.environ.get("M3_ADMIN_TOKEN")
        if admin_token:
            updates["security.admin_token"] = admin_token

        # 加密密钥
        encryption_key = os.environ.get("M3_ENCRYPTION_KEY")
        if encryption_key:
            updates["security.encryption_key"] = encryption_key

        # CORS
        cors_origins = os.environ.get("CORS_ORIGINS")
        if cors_origins:
            updates["security.cors_origins"] = cors_origins.split(",")

        # 数据库路径
        db_path = os.environ.get("M3_DATABASE_PATH")
        if db_path:
            updates["database.path"] = db_path

        # 批量应用更新
        if updates:
            try:
                config_manager.update_config(updates=updates, request_id="env_override")
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # 公共访问方法
    # -----------------------------------------------------------------------

    def get_component(self, name: str) -> Any | None:
        """获取指定组件实例.

        Args:
            name: 组件名称.

        Returns:
            组件实例，不存在则返回 None.
        """
        return self._services.get(name)

    def is_mock(self, name: str) -> bool:
        """判断指定组件是否处于 mock 模式.

        Args:
            name: 组件名称.

        Returns:
            是否为 mock 模式（组件不存在也视为 mock）.
        """
        return self._mock_mode.get(name, True)

    @property
    def services(self) -> dict[str, Any]:
        """所有服务实例字典（只读访问）."""
        return self._services

    @property
    def mock_mode(self) -> dict[str, bool]:
        """所有组件的 mock 模式标记字典（只读访问）."""
        return self._mock_mode

    @property
    def start_time(self) -> float:
        """内核启动时间戳."""
        return self._start_time

    @property
    def base_dir(self) -> Path:
        """基础目录路径."""
        return self._base_dir

    @property
    def project_root(self) -> Path | None:
        """项目根目录路径."""
        return self._project_root

    @property
    def config_path(self) -> Path:
        """配置文件路径."""
        return self._config_path

    @property
    def uptime_seconds(self) -> int:
        """运行时长（秒）."""
        return int(time.time() - self._start_time)

    def get_mock_components(self) -> list[str]:
        """获取处于 mock 模式的组件名称列表.

        Returns:
            Mock 组件名称列表.
        """
        return [k for k, v in self._mock_mode.items() if v]

    def get_real_components(self) -> list[str]:
        """获取正常初始化的组件名称列表.

        Returns:
            正常组件名称列表.
        """
        return [k for k, v in self._mock_mode.items() if not v]

    # -----------------------------------------------------------------------
    # 内部辅助
    # -----------------------------------------------------------------------

    def _default_db_path(self, db_name: str) -> str:
        """获取默认数据库文件路径.

        Args:
            db_name: 数据库文件名.

        Returns:
            数据库文件完整路径.
        """
        if self._project_root:
            return str(self._project_root / "M3-edge-cloud" / "data" / db_name)
        return str(self._base_dir / "data" / db_name)
