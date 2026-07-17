"""
云汐系统模块注册表 (CQ-001, P1级)
====================================

实现模块配置外部化和动态注册发现机制。

核心能力：
- ModuleInfo: 单个模块的配置信息（Pydantic 模型）
- ModuleRegistry: 模块注册表，支持从 YAML/JSON 加载、动态注册/注销、查询
- 心跳检测与健康状态跟踪
- 启动优先级排序

使用方式：
    from shared.core.module_registry import ModuleRegistry, get_module_registry

    registry = get_module_registry()
    m8 = registry.get_module("m8")
    all_modules = registry.list_modules()
    startup_order = registry.get_startup_order()

配置优先级：
    环境变量 > config/modules.yaml > 代码内置默认值
"""

from __future__ import annotations

import copy
import os
import time
import threading
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================
# 枚举与常量
# ============================================================

class ModuleCategory(str, Enum):
    """模块分类"""
    MANAGEMENT = "management"   # 管控类
    CORE = "core"               # 核心能力类
    TOOL = "tool"               # 工具类
    INFRA = "infra"             # 基础设施类


class ModuleStatus(str, Enum):
    """模块运行状态"""
    UNKNOWN = "unknown"
    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    UNHEALTHY = "unhealthy"


class HealthStatus(str, Enum):
    """健康检查状态"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# 默认配置文件路径（相对于项目根目录）
DEFAULT_CONFIG_PATH = "config/modules.yaml"
DEFAULT_CONFIG_PATH_JSON = "config/modules.json"

# 环境变量名
ENV_CONFIG_PATH = "YUNXI_MODULES_CONFIG"


# ============================================================
# ModuleInfo - 模块配置信息
# ============================================================

class ModuleInfo(BaseModel):
    """
    单个模块的配置信息。

    包含启动配置、网络配置、元信息、运行时状态等。
    """

    # ---- 基本标识 ----
    id: str = Field(..., description="模块唯一标识（如 m0, m1, gateway）")
    name: str = Field(..., description="模块显示名称")
    description: str = Field("", description="模块描述")
    version: str = Field("v1.0.0", description="模块版本")
    category: ModuleCategory = Field(ModuleCategory.CORE, description="模块分类")

    # ---- 启动配置 ----
    directory: str = Field("", description="模块工作目录（相对于项目根）")
    start_command: str = Field("python server.py", description="启动命令")
    entrypoint: str = Field("server.py", description="入口文件")
    python_executable: str = Field("", description="Python 可执行文件路径（空则用全局默认）")

    # ---- 网络配置 ----
    port: int = Field(0, ge=1, le=65535, description="服务监听端口")
    host: str = Field("127.0.0.1", description="服务监听地址")
    health_check_path: str = Field("/health", description="健康检查路径")

    # ---- 控制配置 ----
    enabled: bool = Field(True, description="是否启用")
    priority: int = Field(100, description="启动优先级，数字越小越先启动")

    # ---- 运行时状态（非配置项，运行时更新） ----
    status: ModuleStatus = Field(ModuleStatus.UNKNOWN, description="运行状态")
    health: HealthStatus = Field(HealthStatus.UNKNOWN, description="健康状态")
    last_heartbeat: Optional[float] = Field(None, description="最后心跳时间戳")
    pid: Optional[int] = Field(None, description="进程 PID")
    base_url: Optional[str] = Field(None, description="模块 Base URL（运行时计算）")

    model_config = {
        "extra": "allow",
        "validate_assignment": True,
    }

    @field_validator("id")
    @classmethod
    def id_must_be_lowercase(cls, v: str) -> str:
        return v.lower().strip()

    def model_post_init(self, __context: Any) -> None:
        """初始化后自动计算 base_url（如果未设置）"""
        if not self.base_url:
            host = self.host if self.host not in ("0.0.0.0", "") else "127.0.0.1"
            self.base_url = f"http://{host}:{self.port}"

    @property
    def is_enabled(self) -> bool:
        """是否启用"""
        return self.enabled

    @property
    def is_running(self) -> bool:
        """是否在运行"""
        return self.status == ModuleStatus.RUNNING

    @property
    def is_healthy(self) -> bool:
        """是否健康"""
        return self.health == HealthStatus.HEALTHY

    def get_base_url(self) -> str:
        """获取模块的 base_url"""
        if self.base_url:
            return self.base_url
        host = self.host if self.host not in ("0.0.0.0", "") else "127.0.0.1"
        return f"http://{host}:{self.port}"

    def to_dict(self, include_runtime: bool = True) -> Dict[str, Any]:
        """
        转换为字典。

        Args:
            include_runtime: 是否包含运行时状态字段

        Returns:
            字典形式的模块信息
        """
        data = self.model_dump(mode="json")
        if not include_runtime:
            for key in ["status", "health", "last_heartbeat", "pid", "base_url"]:
                data.pop(key, None)
        return data

    def get_work_dir(self, project_root: Path) -> Path:
        """获取模块工作目录的绝对路径"""
        if not self.directory:
            return project_root
        work_dir = Path(self.directory)
        if not work_dir.is_absolute():
            work_dir = project_root / work_dir
        return work_dir


# ============================================================
# GlobalConfig - 全局配置
# ============================================================

class RegistryGlobalConfig(BaseModel):
    """注册表全局配置"""

    health_timeout: int = Field(5, description="默认健康检查超时（秒）")
    startup_timeout: int = Field(30, description="默认启动超时（秒）")
    heartbeat_interval: int = Field(0, description="心跳检测间隔（秒），0 表示不启用")
    heartbeat_timeout: int = Field(30, description="心跳超时阈值（秒）")
    project_root: str = Field(".", description="项目根目录")
    python_executable: str = Field("python", description="默认 Python 可执行文件")

    model_config = {"extra": "allow"}


# ============================================================
# ModuleRegistry - 模块注册表
# ============================================================

class ModuleRegistry:
    """
    云汐系统模块注册表。

    负责加载模块配置、管理模块注册信息、提供查询接口。
    支持从 YAML/JSON 配置文件加载，也支持运行时动态注册。

    使用示例：
        registry = ModuleRegistry.load_from_env()
        module = registry.get_module("m8")
        all_modules = registry.list_modules(category="core")
        order = registry.get_startup_order()
    """

    # 单例
    _instance: Optional["ModuleRegistry"] = None
    _instance_lock = threading.Lock()

    def __init__(self, config_path: Optional[str] = None, project_root: Optional[Path] = None):
        """
        初始化模块注册表。

        Args:
            config_path: 配置文件路径，None 时使用默认路径
            project_root: 项目根目录，None 时自动推断
        """
        self._lock = threading.RLock()
        self._modules: Dict[str, ModuleInfo] = {}
        self._config_path: Optional[Path] = None
        self._global_config = RegistryGlobalConfig()
        self._project_root = self._resolve_project_root(project_root)
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        self._initialized = False

        # 尝试从配置文件加载
        if config_path:
            self._config_path = Path(config_path)
            if not self._config_path.is_absolute():
                self._config_path = self._project_root / self._config_path
            self._load_from_file(self._config_path)
        else:
            # 尝试默认路径
            self._try_load_default_config()

        # 如果没有加载到任何模块，使用内置默认配置
        if not self._modules:
            self._load_default_modules()

        self._initialized = True

    # ------------------------------------------------------------------
    #  类方法：加载入口
    # ------------------------------------------------------------------

    @classmethod
    def load_from_yaml(cls, path: str, project_root: Optional[Path] = None) -> "ModuleRegistry":
        """从 YAML 文件加载配置"""
        return cls(config_path=path, project_root=project_root)

    @classmethod
    def load_from_env(cls) -> "ModuleRegistry":
        """
        从默认路径加载配置。

        查找顺序：
        1. 环境变量 YUNXI_MODULES_CONFIG 指定的路径
        2. config/modules.yaml
        3. config/modules.json
        4. 内置默认配置
        """
        config_path = os.getenv(ENV_CONFIG_PATH, "")
        if config_path:
            return cls(config_path=config_path)
        return cls()

    @classmethod
    def get_instance(cls) -> "ModuleRegistry":
        """获取全局单例（线程安全，与 get_module_registry() 返回同一实例）"""
        return get_module_registry()

    # ------------------------------------------------------------------
    #  内部工具：路径解析与配置加载
    # ------------------------------------------------------------------

    def _resolve_project_root(self, explicit_root: Optional[Path]) -> Path:
        """解析项目根目录"""
        if explicit_root:
            return Path(explicit_root).resolve()

        # 从当前文件向上查找：shared/core/module_registry.py -> 项目根
        current = Path(__file__).resolve()
        for _ in range(5):
            current = current.parent
            # 检查常见的项目根标识
            if (current / "config").exists() or (current / "shared").exists():
                return current
        return current

    def _try_load_default_config(self) -> None:
        """尝试从默认路径加载配置文件"""
        candidates = [
            self._project_root / DEFAULT_CONFIG_PATH,
            self._project_root / DEFAULT_CONFIG_PATH_JSON,
        ]
        for path in candidates:
            if path.exists():
                self._config_path = path
                self._load_from_file(path)
                if self._modules:
                    return

    def _load_from_file(self, path: Path) -> None:
        """从文件加载配置（YAML 或 JSON）"""
        try:
            suffix = path.suffix.lower()
            if suffix in (".yaml", ".yml"):
                self._load_from_yaml_file(path)
            elif suffix == ".json":
                self._load_from_json_file(path)
            else:
                # 尝试 YAML
                self._load_from_yaml_file(path)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("加载模块配置文件失败 %s: %s，将使用内置默认配置", path, e)

    def _load_from_yaml_file(self, path: Path) -> None:
        """从 YAML 文件加载"""
        try:
            import yaml
        except ImportError:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("PyYAML 未安装，无法加载 YAML 配置文件")
            return

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self._parse_config_data(data)

    def _load_from_json_file(self, path: Path) -> None:
        """从 JSON 文件加载"""
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._parse_config_data(data)

    def _parse_config_data(self, data: Dict[str, Any]) -> None:
        """解析配置数据并填充注册表"""
        # 全局配置
        if "global" in data and isinstance(data["global"], dict):
            try:
                self._global_config = RegistryGlobalConfig(**data["global"])
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning("解析全局配置失败: %s", e)

        # 模块配置
        modules_data = data.get("modules", {})
        if not isinstance(modules_data, dict):
            return

        with self._lock:
            self._modules.clear()
            for key, mod_data in modules_data.items():
                if not isinstance(mod_data, dict):
                    continue
                try:
                    # 如果配置中没有 id 字段，使用 YAML key
                    if "id" not in mod_data:
                        mod_data = {**mod_data, "id": key}
                    # 如果没有 python_executable，使用全局默认
                    if not mod_data.get("python_executable"):
                        mod_data["python_executable"] = self._global_config.python_executable
                    module = ModuleInfo(**mod_data)
                    # 计算 base_url
                    if not module.base_url:
                        host = module.host if module.host not in ("0.0.0.0", "") else "127.0.0.1"
                        module.base_url = f"http://{host}:{module.port}"
                    self._modules[module.id] = module
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning("解析模块配置 %s 失败: %s", key, e)

    def _load_default_modules(self) -> None:
        """加载内置默认模块配置（向后兼容 fallback）"""
        defaults = _get_default_module_configs()
        with self._lock:
            self._modules.clear()
            for mod_data in defaults:
                try:
                    module = ModuleInfo(**mod_data)
                    if not module.base_url:
                        host = module.host if module.host not in ("0.0.0.0", "") else "127.0.0.1"
                        module.base_url = f"http://{host}:{module.port}"
                    self._modules[module.id] = module
                except Exception:
                    pass

    # ------------------------------------------------------------------
    #  查询接口
    # ------------------------------------------------------------------

    def get_module(self, module_id: str) -> Optional[ModuleInfo]:
        """
        获取指定模块的配置信息。

        Args:
            module_id: 模块标识（如 "m8", "m0", "gateway"）

        Returns:
            ModuleInfo 或 None
        """
        module_id = module_id.lower().strip()
        with self._lock:
            return self._modules.get(module_id)

    def get_by_port(self, port: int) -> Optional[ModuleInfo]:
        """
        根据端口号查找模块。

        Args:
            port: 端口号

        Returns:
            ModuleInfo 或 None
        """
        with self._lock:
            for module in self._modules.values():
                if module.port == port:
                    return module
        return None

    def list_modules(
        self,
        category: Optional[str] = None,
        enabled_only: bool = True,
    ) -> List[ModuleInfo]:
        """
        列出模块。

        Args:
            category: 按分类筛选（management/core/tool/infra），None 表示全部
            enabled_only: 是否只返回启用的模块

        Returns:
            模块列表（按优先级排序）
        """
        with self._lock:
            modules = list(self._modules.values())

        if enabled_only:
            modules = [m for m in modules if m.enabled]

        if category:
            cat = ModuleCategory(category) if isinstance(category, str) else category
            modules = [m for m in modules if m.category == cat]

        # 按优先级排序（数字小的在前）
        modules.sort(key=lambda m: m.priority)
        return modules

    def get_startup_order(self, enabled_only: bool = True) -> List[ModuleInfo]:
        """
        获取启动顺序（按优先级排序）。

        Args:
            enabled_only: 是否只包含启用的模块

        Returns:
            按启动优先级排序的模块列表
        """
        return self.list_modules(category=None, enabled_only=enabled_only)

    def get_module_count(self, enabled_only: bool = True) -> int:
        """获取模块数量"""
        with self._lock:
            if enabled_only:
                return sum(1 for m in self._modules.values() if m.enabled)
            return len(self._modules)

    def has_module(self, module_id: str) -> bool:
        """检查模块是否存在"""
        return self.get_module(module_id) is not None

    @property
    def global_config(self) -> RegistryGlobalConfig:
        """获取全局配置"""
        return self._global_config

    @property
    def project_root(self) -> Path:
        """获取项目根目录"""
        return self._project_root

    @property
    def config_path(self) -> Optional[Path]:
        """获取配置文件路径"""
        return self._config_path

    # ------------------------------------------------------------------
    #  动态注册/注销
    # ------------------------------------------------------------------

    def register_module(self, module_info: ModuleInfo) -> ModuleInfo:
        """
        动态注册新模块。

        Args:
            module_info: 模块信息

        Returns:
            注册后的模块信息
        """
        if not module_info.base_url:
            host = module_info.host if module_info.host not in ("0.0.0.0", "") else "127.0.0.1"
            module_info.base_url = f"http://{host}:{module_info.port}"

        with self._lock:
            self._modules[module_info.id] = module_info

        import logging
        logger = logging.getLogger(__name__)
        logger.info("模块已注册: %s (%s)", module_info.id, module_info.name)
        return module_info

    def unregister_module(self, module_id: str) -> bool:
        """
        注销模块。

        Args:
            module_id: 模块标识

        Returns:
            True 表示成功注销，False 表示模块不存在
        """
        module_id = module_id.lower().strip()
        with self._lock:
            if module_id in self._modules:
                del self._modules[module_id]
                import logging
                logger = logging.getLogger(__name__)
                logger.info("模块已注销: %s", module_id)
                return True
        return False

    def update_module(self, module_id: str, **kwargs: Any) -> Optional[ModuleInfo]:
        """
        更新模块配置。

        Args:
            module_id: 模块标识
            **kwargs: 要更新的字段

        Returns:
            更新后的模块信息，或 None 如果模块不存在
        """
        module = self.get_module(module_id)
        if module is None:
            return None

        with self._lock:
            for key, value in kwargs.items():
                if hasattr(module, key):
                    setattr(module, key, value)
            # 如果端口或 host 变了，更新 base_url
            if "port" in kwargs or "host" in kwargs:
                host = module.host if module.host not in ("0.0.0.0", "") else "127.0.0.1"
                module.base_url = f"http://{host}:{module.port}"

        return module

    def enable_module(self, module_id: str) -> bool:
        """启用模块"""
        module = self.update_module(module_id, enabled=True)
        return module is not None

    def disable_module(self, module_id: str) -> bool:
        """禁用模块"""
        module = self.update_module(module_id, enabled=False)
        return module is not None

    # ------------------------------------------------------------------
    #  心跳与健康状态
    # ------------------------------------------------------------------

    def heartbeat(self, module_id: str, status: Optional[str] = None) -> bool:
        """
        模块心跳上报。

        Args:
            module_id: 模块标识
            status: 可选的状态更新

        Returns:
            True 表示成功，False 表示模块未注册
        """
        module = self.get_module(module_id)
        if module is None:
            return False

        with self._lock:
            module.last_heartbeat = time.time()
            module.health = HealthStatus.HEALTHY
            if status:
                try:
                    module.status = ModuleStatus(status)
                except ValueError:
                    pass

        return True

    def check_heartbeat_timeout(self) -> List[str]:
        """
        检查心跳超时的模块。

        Returns:
            心跳超时的模块 ID 列表
        """
        if self._global_config.heartbeat_interval <= 0:
            return []

        timeout = self._global_config.heartbeat_timeout
        now = time.time()
        timed_out: List[str] = []

        with self._lock:
            for module_id, module in self._modules.items():
                if not module.enabled:
                    continue
                if module.status != ModuleStatus.RUNNING:
                    continue
                if module.last_heartbeat is None:
                    continue
                if now - module.last_heartbeat > timeout:
                    module.health = HealthStatus.UNHEALTHY
                    timed_out.append(module_id)

        return timed_out

    def start_heartbeat_monitor(self) -> bool:
        """
        启动心跳监控线程。

        Returns:
            True 表示成功启动
        """
        if self._global_config.heartbeat_interval <= 0:
            return False

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return True

        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_monitor_loop,
            name="ModuleHeartbeatMonitor",
            daemon=True,
        )
        self._heartbeat_thread.start()
        return True

    def stop_heartbeat_monitor(self) -> None:
        """停止心跳监控线程"""
        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
            self._heartbeat_thread = None

    def _heartbeat_monitor_loop(self) -> None:
        """心跳监控循环（后台线程）"""
        interval = self._global_config.heartbeat_interval
        import logging
        logger = logging.getLogger(__name__)

        while not self._heartbeat_stop.is_set():
            try:
                timed_out = self.check_heartbeat_timeout()
                if timed_out:
                    logger.warning("心跳超时模块: %s", timed_out)
            except Exception as e:
                logger.error("心跳监控异常: %s", e)

            self._heartbeat_stop.wait(interval)

    # ------------------------------------------------------------------
    #  保存配置
    # ------------------------------------------------------------------

    def save(self, path: Optional[str] = None) -> bool:
        """
        保存当前配置回文件。

        Args:
            path: 保存路径，None 时使用原配置文件路径

        Returns:
            True 表示成功保存
        """
        save_path = Path(path) if path else self._config_path
        if save_path is None:
            # 默认保存到 config/modules.yaml
            save_path = self._project_root / DEFAULT_CONFIG_PATH

        if not save_path.is_absolute():
            save_path = self._project_root / save_path

        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)

            # 构建配置数据
            with self._lock:
                modules_data: Dict[str, Any] = {}
                for mid, mod in sorted(self._modules.items(), key=lambda x: x[1].priority):
                    mod_dict = mod.to_dict(include_runtime=False)
                    # 移除 id 字段（用 YAML key 表示）
                    mod_dict.pop("id", None)
                    # 移除默认值字段，让配置更简洁
                    if mod_dict.get("host") == "127.0.0.1":
                        mod_dict.pop("host", None)
                    if mod_dict.get("python_executable") == self._global_config.python_executable:
                        mod_dict.pop("python_executable", None)
                    modules_data[mid] = mod_dict

                config_data = {
                    "modules": modules_data,
                    "global": self._global_config.model_dump(mode="json"),
                }

            suffix = save_path.suffix.lower()
            if suffix in (".yaml", ".yml"):
                import yaml
                with open(save_path, "w", encoding="utf-8") as f:
                    yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            elif suffix == ".json":
                import json
                with open(save_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)
            else:
                # 默认 YAML
                import yaml
                with open(save_path, "w", encoding="utf-8") as f:
                    yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            self._config_path = save_path
            import logging
            logger = logging.getLogger(__name__)
            logger.info("模块配置已保存到: %s", save_path)
            return True

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("保存模块配置失败: %s", e)
            return False

    # ------------------------------------------------------------------
    #  状态汇总
    # ------------------------------------------------------------------

    def get_status_summary(self) -> Dict[str, Any]:
        """获取模块状态汇总"""
        with self._lock:
            modules = list(self._modules.values())

        total = len(modules)
        enabled = sum(1 for m in modules if m.enabled)
        running = sum(1 for m in modules if m.status == ModuleStatus.RUNNING)
        stopped = sum(1 for m in modules if m.status == ModuleStatus.STOPPED)
        error = sum(1 for m in modules if m.status == ModuleStatus.ERROR)
        healthy = sum(1 for m in modules if m.health == HealthStatus.HEALTHY)
        unhealthy = sum(1 for m in modules if m.health == HealthStatus.UNHEALTHY)

        return {
            "total": total,
            "enabled": enabled,
            "disabled": total - enabled,
            "running": running,
            "stopped": stopped,
            "error": error,
            "unknown_status": total - running - stopped - error,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "unknown_health": total - healthy - unhealthy,
        }

    def reload(self) -> int:
        """
        重新从配置文件加载（会覆盖运行时修改但未保存的配置）。

        Returns:
            加载的模块数量
        """
        old_modules = self._modules.copy()
        self._modules.clear()

        if self._config_path and self._config_path.exists():
            self._load_from_file(self._config_path)

        if not self._modules:
            # 加载失败，恢复旧的
            self._modules = old_modules

        return len(self._modules)


# ============================================================
# 内置默认模块配置（向后兼容 fallback）
# ============================================================

def _get_default_module_configs() -> List[Dict[str, Any]]:
    """
    获取内置默认模块配置。

    与 process_manager.py 和 startup_orchestrator.py 中的硬编码保持一致，
    作为配置文件不存在时的 fallback。
    """
    return [
        # Tier 0 - 管控基础设施
        {
            "id": "m8",
            "name": "控制塔",
            "port": 8008,
            "directory": "M8-control-tower",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 1,
            "category": "management",
            "health_check_path": "/health",
            "description": "算力调度、API网关、统一管控台",
            "version": "v1.0.0",
        },
        {
            "id": "m10",
            "name": "系统卫士",
            "port": 8010,
            "directory": "M10-system-guard",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 2,
            "category": "management",
            "health_check_path": "/health",
            "description": "系统资源监控、进程管理、阈值防护、审计日志",
            "version": "v1.0.0",
        },
        {
            "id": "m12",
            "name": "安全盾",
            "port": 8012,
            "directory": "M12-security-shield",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 3,
            "category": "management",
            "health_check_path": "/health",
            "description": "安全防护、攻击检测、漏洞扫描",
            "version": "v1.0.0",
        },
        # Tier 1 - 核心能力
        {
            "id": "m1",
            "name": "代理集群",
            "port": 8001,
            "directory": "M1-agent-hub",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 10,
            "category": "core",
            "health_check_path": "/health",
            "description": "多智能体协作、联邦调度、任务编排",
            "version": "v1.0.0",
        },
        {
            "id": "m5",
            "name": "潮汐记忆",
            "port": 8005,
            "directory": "M5-tide-memory",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 11,
            "category": "core",
            "health_check_path": "/health",
            "description": "长期记忆、向量检索、知识图谱",
            "version": "v1.0.0",
        },
        {
            "id": "m2",
            "name": "技能集群",
            "port": 8002,
            "directory": "M2-skills-cluster",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 12,
            "category": "core",
            "health_check_path": "/health",
            "description": "技能库管理、技能发现、技能执行引擎",
            "version": "v1.0.0",
        },
        # Tier 2 - 按需能力
        {
            "id": "m4",
            "name": "场景引擎",
            "port": 8004,
            "directory": "m4-scene-engine",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 20,
            "category": "core",
            "health_check_path": "/health",
            "description": "场景模板、场景编排、交互引擎",
            "version": "v1.0.0",
        },
        {
            "id": "m7",
            "name": "工作流构建器",
            "port": 8007,
            "directory": "M7-workflow-builder",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 21,
            "category": "tool",
            "health_check_path": "/health",
            "description": "可视化流程编排、自动化任务、触发器",
            "version": "v1.0.0",
        },
        {
            "id": "m3",
            "name": "边缘云端",
            "port": 8003,
            "directory": "M3-edge-cloud",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 22,
            "category": "infra",
            "health_check_path": "/health",
            "description": "边缘计算、云边协同、混合算力调度",
            "version": "v1.0.0",
        },
        # Tier 3 - 即用即启
        {
            "id": "m6",
            "name": "硬件外设",
            "port": 8006,
            "directory": "M6-hardware-peripheral",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 30,
            "category": "infra",
            "health_check_path": "/health",
            "description": "硬件驱动、外设管理、设备联动",
            "version": "v1.0.0",
        },
        {
            "id": "m0",
            "name": "主理人管控台",
            "port": 8000,
            "directory": "M0-principal-console",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 31,
            "category": "management",
            "health_check_path": "/health",
            "description": "云汐系统主理人专属管控平台，最高权限",
            "version": "v1.0.0",
        },
        {
            "id": "m11",
            "name": "MCP总线",
            "port": 8011,
            "directory": "M11-mcp-bus",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 32,
            "category": "infra",
            "health_check_path": "/health",
            "description": "MCP 服务总线、工具协议适配",
            "version": "v1.0.0",
        },
        # API Gateway
        {
            "id": "gateway",
            "name": "API网关",
            "port": 8080,
            "directory": "API-Gateway",
            "start_command": "python server.py",
            "entrypoint": "server.py",
            "enabled": True,
            "priority": 0,
            "category": "infra",
            "health_check_path": "/health",
            "description": "统一接入层、路由转发、限流熔断",
            "version": "v1.0.0",
        },
    ]


# ============================================================
# 全局单例获取函数
# ============================================================

_registry_instance: Optional[ModuleRegistry] = None
_registry_lock = threading.Lock()


def get_module_registry() -> ModuleRegistry:
    """
    获取全局模块注册表单例。

    Returns:
        ModuleRegistry 实例
    """
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = ModuleRegistry.load_from_env()
                # 同时设置类级别的 _instance，保持一致
                ModuleRegistry._instance = _registry_instance
    return _registry_instance


def reset_module_registry() -> None:
    """重置注册表单例（主要用于测试）"""
    global _registry_instance
    with _registry_lock:
        if _registry_instance:
            _registry_instance.stop_heartbeat_monitor()
        _registry_instance = None
    # 同时重置类级别的 _instance，保持一致
    ModuleRegistry._instance = None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 核心类
    "ModuleInfo",
    "ModuleRegistry",
    "RegistryGlobalConfig",
    # 枚举
    "ModuleCategory",
    "ModuleStatus",
    "HealthStatus",
    # 全局函数
    "get_module_registry",
    "reset_module_registry",
    # 常量
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_CONFIG_PATH_JSON",
    "ENV_CONFIG_PATH",
]
