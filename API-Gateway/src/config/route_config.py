"""
云汐 API 网关 - 路由配置管理器

功能特性：
1. 从 YAML 配置文件加载模块路由表（modules 字典格式）
2. 支持环境变量覆盖 target 地址（如 M0_TARGET、M1_TARGET）
3. 配置完整性验证（必填字段检查）
4. 默认值处理（timeout 默认 30s，enabled 默认 true 等）
5. 热重载支持（reload 方法，失败回滚）
6. 与 ModuleRoute 模型兼容，直接生成 ModuleRoute 列表
7. 文件变更检测（支持自动热加载）

这是路由配置的**唯一事实来源**。代码中不再硬编码模块路由，
所有模块路由均从 config/routes.yaml 配置文件读取。
"""

import os
import time
import logging
import threading
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass

import yaml

logger = logging.getLogger("yunxi-gateway.route-config")


# ============================================================
# 热重载结果数据类
# ============================================================

@dataclass
class RouteReloadResult:
    """路由热重载结果"""
    success: bool
    added: int = 0
    removed: int = 0
    updated: int = 0
    total_before: int = 0
    total_after: int = 0
    error: Optional[str] = None


# ============================================================
# 必填字段定义
# ============================================================

# 模块路由的必填字段
REQUIRED_FIELDS = ["name", "prefix", "target"]

# 可选字段及其默认值（与 ModuleRoute 的默认值保持一致）
DEFAULT_VALUES = {
    "enabled": True,
    "timeout": 30.0,
    "health_path": "/health",
    "health_timeout": 5.0,
    "auth_required": True,
    "public_paths": [],
    "rate_limit_per_minute": 60,
    "rate_limit_per_ip": 30,
    "rate_limit_tier": "public",
    "supports_websocket": False,
    "supports_sse": False,
    "cb_failure_threshold": 5,
    "cb_recovery_time": 30,
    "description": "",
}


# ============================================================
# 路由配置管理器
# ============================================================

class RouteConfigManager:
    """路由配置管理器

    负责从配置文件加载、验证、管理模块路由配置。

    设计原则：
    - 配置文件是唯一事实来源
    - 热重载失败时保留旧配置（原子切换）
    - 与 ModuleRoute 模型完全兼容
    - 支持环境变量覆盖 target 地址
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Args:
            config_path: 路由配置文件路径，默认自动查找 config/routes.yaml
        """
        self._lock = threading.RLock()
        self._routes: List[Any] = []          # ModuleRoute 列表
        self._route_index: Dict[str, Any] = {}  # key -> ModuleRoute
        self._config_path: Optional[str] = None
        self._last_modified: float = 0.0
        self._load_count: int = 0
        self._last_load_time: float = 0.0
        self._last_error: Optional[str] = None
        self._version: str = ""

        # 解析配置文件路径
        if config_path is None:
            config_path = self._find_default_config_path()
        self._config_path = config_path

    # --------------------------------------------------------
    # 配置路径查找
    # --------------------------------------------------------

    @staticmethod
    def _find_default_config_path() -> str:
        """查找默认的路由配置文件路径

        从当前文件位置向上查找 config/routes.yaml。
        """
        current = Path(__file__).resolve()
        for _ in range(5):
            candidate = current.parent / "config" / "routes.yaml"
            if candidate.exists():
                return str(candidate)
            current = current.parent

        # 回退到相对路径
        return "config/routes.yaml"

    # --------------------------------------------------------
    # 加载方法
    # --------------------------------------------------------

    def load(self) -> bool:
        """加载路由配置

        从配置文件读取并解析路由配置，验证完整性，
        应用环境变量覆盖，生成 ModuleRoute 列表。

        Returns:
            True 表示加载成功，False 表示失败
        """
        if not self._config_path:
            self._last_error = "No config file path specified"
            logger.error(self._last_error)
            return False

        config_file = Path(self._config_path)
        if not config_file.exists():
            self._last_error = f"Config file not found: {self._config_path}"
            logger.warning(self._last_error)
            return False

        try:
            content = config_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            if data is None:
                self._last_error = "Empty config file"
                logger.warning(self._last_error)
                return False

            # 验证顶层结构
            if not isinstance(data, dict):
                self._last_error = "Config file root must be a mapping"
                logger.error(self._last_error)
                return False

            if "modules" not in data:
                self._last_error = "Config file missing 'modules' section"
                logger.error(self._last_error)
                return False

            # 保存版本
            self._version = str(data.get("version", "1.0.0"))

            # 获取全局默认值
            global_defaults = data.get("defaults", {})
            if not isinstance(global_defaults, dict):
                global_defaults = {}

            # 解析模块路由
            modules = data["modules"]
            if not isinstance(modules, dict):
                self._last_error = "'modules' must be a mapping (key-value)"
                logger.error(self._last_error)
                return False

            # 延迟导入，避免循环依赖
            from ..config import ModuleRoute

            routes: List[Any] = []
            validation_errors: List[str] = []

            for module_key, module_config in modules.items():
                if not isinstance(module_config, dict):
                    validation_errors.append(
                        f"Module '{module_key}': config must be a mapping"
                    )
                    continue

                # 验证必填字段
                for field in REQUIRED_FIELDS:
                    if field not in module_config:
                        validation_errors.append(
                            f"Module '{module_key}': missing required field '{field}'"
                        )

                if validation_errors:
                    # 如果有必填字段缺失，跳过此模块的进一步处理
                    continue

                # 合并默认值：全局默认值 -> 模块配置
                merged = {}
                # 先应用全局默认值中相关字段
                for key, default_val in DEFAULT_VALUES.items():
                    if key in global_defaults:
                        merged[key] = global_defaults[key]
                    else:
                        merged[key] = default_val

                # 再用模块配置覆盖
                merged.update(module_config)

                # 应用环境变量覆盖 target
                env_target = os.getenv(f"{module_key.upper()}_TARGET")
                if env_target:
                    merged["target"] = env_target
                    logger.debug(
                        f"Module '{module_key}': target overridden by env var "
                        f"{module_key.upper()}_TARGET={env_target}"
                    )

                # 构造 ModuleRoute
                try:
                    route = ModuleRoute(
                        key=module_key,
                        name=merged["name"],
                        target_url=merged["target"],
                        prefix=merged["prefix"],
                        enabled=bool(merged.get("enabled", True)),
                        timeout=float(merged.get("timeout", 30.0)),
                        health_path=str(merged.get("health_path", "/health")),
                        health_timeout=float(merged.get("health_timeout", 5.0)),
                        auth_required=bool(merged.get("auth_required", True)),
                        public_paths=list(merged.get("public_paths", [])),
                        rate_limit_per_minute=int(merged.get("rate_limit_per_minute", 60)),
                        rate_limit_per_ip=int(merged.get("rate_limit_per_ip", 30)),
                        rate_limit_tier=str(merged.get("rate_limit_tier", "public")),
                        supports_websocket=bool(merged.get("supports_websocket", False)),
                        supports_sse=bool(merged.get("supports_sse", False)),
                        cb_failure_threshold=int(merged.get("cb_failure_threshold", 5)),
                        cb_recovery_time=int(merged.get("cb_recovery_time", 30)),
                        description=str(merged.get("description", "")),
                    )
                    routes.append(route)
                except Exception as e:
                    validation_errors.append(
                        f"Module '{module_key}': failed to build config - {e}"
                    )

            # 验证失败
            if validation_errors:
                self._last_error = "Validation failed: " + "; ".join(validation_errors)
                logger.error(self._last_error)
                return False

            # 检查 key 重复（理论上字典不会重复，但做个防御性检查）
            seen_keys = set()
            for route in routes:
                if route.key in seen_keys:
                    validation_errors.append(f"Duplicate module key: {route.key}")
                seen_keys.add(route.key)

            if validation_errors:
                self._last_error = "Validation failed: " + "; ".join(validation_errors)
                logger.error(self._last_error)
                return False

            # 原子替换
            with self._lock:
                self._routes = routes
                self._route_index = {r.key: r for r in routes}
                self._load_count += 1
                self._last_load_time = time.time()
                self._last_error = None

                if config_file.exists():
                    self._last_modified = config_file.stat().st_mtime

            logger.info(
                f"Route config loaded: {len(routes)} modules, "
                f"load_count={self._load_count}, version={self._version}"
            )
            return True

        except yaml.YAMLError as e:
            self._last_error = f"YAML parse error: {e}"
            logger.error(self._last_error, exc_info=True)
            return False
        except Exception as e:
            self._last_error = f"Failed to load config: {e}"
            logger.error(self._last_error, exc_info=True)
            return False

    def load_from_dict(self, data: Dict[str, Any]) -> bool:
        """从字典数据加载路由配置（用于测试）

        Args:
            data: 配置数据字典（需包含 modules 键）

        Returns:
            True 表示加载成功
        """
        if not isinstance(data, dict) or "modules" not in data:
            self._last_error = "Invalid data format: missing 'modules' section"
            return False

        # 延迟导入
        from ..config import ModuleRoute

        modules = data["modules"]
        if not isinstance(modules, dict):
            self._last_error = "'modules' must be a mapping"
            return False

        global_defaults = data.get("defaults", {})
        if not isinstance(global_defaults, dict):
            global_defaults = {}

        routes: List[Any] = []
        errors: List[str] = []

        for module_key, module_config in modules.items():
            if not isinstance(module_config, dict):
                errors.append(f"Module '{module_key}': config must be a mapping")
                continue

            for field in REQUIRED_FIELDS:
                if field not in module_config:
                    errors.append(f"Module '{module_key}': missing required field '{field}'")

            if errors:
                continue

            # 合并默认值
            merged = {}
            for key, default_val in DEFAULT_VALUES.items():
                if key in global_defaults:
                    merged[key] = global_defaults[key]
                else:
                    merged[key] = default_val
            merged.update(module_config)

            # 环境变量覆盖
            env_target = os.getenv(f"{module_key.upper()}_TARGET")
            if env_target:
                merged["target"] = env_target

            try:
                route = ModuleRoute(
                    key=module_key,
                    name=merged["name"],
                    target_url=merged["target"],
                    prefix=merged["prefix"],
                    enabled=bool(merged.get("enabled", True)),
                    timeout=float(merged.get("timeout", 30.0)),
                    health_path=str(merged.get("health_path", "/health")),
                    health_timeout=float(merged.get("health_timeout", 5.0)),
                    auth_required=bool(merged.get("auth_required", True)),
                    public_paths=list(merged.get("public_paths", [])),
                    rate_limit_per_minute=int(merged.get("rate_limit_per_minute", 60)),
                    rate_limit_per_ip=int(merged.get("rate_limit_per_ip", 30)),
                    rate_limit_tier=str(merged.get("rate_limit_tier", "public")),
                    supports_websocket=bool(merged.get("supports_websocket", False)),
                    supports_sse=bool(merged.get("supports_sse", False)),
                    cb_failure_threshold=int(merged.get("cb_failure_threshold", 5)),
                    cb_recovery_time=int(merged.get("cb_recovery_time", 30)),
                    description=str(merged.get("description", "")),
                )
                routes.append(route)
            except Exception as e:
                errors.append(f"Module '{module_key}': {e}")

        if errors:
            self._last_error = "Validation failed: " + "; ".join(errors)
            logger.error(self._last_error)
            return False

        with self._lock:
            self._routes = routes
            self._route_index = {r.key: r for r in routes}
            self._load_count += 1
            self._last_load_time = time.time()
            self._last_error = None
            self._version = str(data.get("version", "1.0.0"))

        logger.info(f"Route config loaded from dict: {len(routes)} modules")
        return True

    # --------------------------------------------------------
    # 热重载
    # --------------------------------------------------------

    def reload(self) -> RouteReloadResult:
        """重新加载路由配置（热重载）

        新配置加载成功后原子替换旧配置；
        加载失败时保留旧配置不变。

        Returns:
            RouteReloadResult 包含新增/删除/更新的路由数量
        """
        logger.info("Reloading route config...")

        # 保存旧配置
        with self._lock:
            old_routes = list(self._routes)
            old_index = dict(self._route_index)
            old_count = len(old_routes)

        # 尝试加载新配置
        success = self.load()

        if not success:
            # 加载失败，恢复旧配置
            with self._lock:
                self._routes = old_routes
                self._route_index = old_index
            error_msg = self._last_error or "Unknown error"
            logger.error(f"Route config reload failed, keeping old config: {error_msg}")
            return RouteReloadResult(
                success=False,
                total_before=old_count,
                total_after=old_count,
                error=error_msg,
            )

        # 计算变更
        with self._lock:
            new_routes = self._routes
            new_index = self._route_index

        old_keys = set(old_index.keys())
        new_keys = set(new_index.keys())

        added_keys = new_keys - old_keys
        removed_keys = old_keys - new_keys
        common_keys = old_keys & new_keys

        # 计算更新的路由（配置内容有变化的）
        updated_count = 0
        for key in common_keys:
            old_route = old_index[key]
            new_route = new_index[key]
            # 比较关键字段
            if (
                old_route.target_url != new_route.target_url
                or old_route.prefix != new_route.prefix
                or old_route.enabled != new_route.enabled
                or old_route.timeout != new_route.timeout
                or old_route.name != new_route.name
                or old_route.auth_required != new_route.auth_required
                or old_route.supports_websocket != new_route.supports_websocket
                or old_route.supports_sse != new_route.supports_sse
                or old_route.public_paths != new_route.public_paths
                or old_route.rate_limit_per_minute != new_route.rate_limit_per_minute
                or old_route.cb_failure_threshold != new_route.cb_failure_threshold
            ):
                updated_count += 1

        result = RouteReloadResult(
            success=True,
            added=len(added_keys),
            removed=len(removed_keys),
            updated=updated_count,
            total_before=old_count,
            total_after=len(new_routes),
        )

        logger.info(
            f"Route config reloaded: +{result.added} -{result.removed} "
            f"~{result.updated} (total: {old_count} -> {len(new_routes)})"
        )
        return result

    # --------------------------------------------------------
    # 文件变更检测
    # --------------------------------------------------------

    def check_for_changes(self) -> bool:
        """检查配置文件是否有变更

        Returns:
            True 表示文件有变更需要重新加载
        """
        if not self._config_path:
            return False

        config_file = Path(self._config_path)
        if not config_file.exists():
            return False

        try:
            mtime = config_file.stat().st_mtime
            return mtime > self._last_modified
        except Exception:
            return False

    # --------------------------------------------------------
    # 查询方法
    # --------------------------------------------------------

    def get_routes(self) -> List[Any]:
        """获取所有模块路由（ModuleRoute 列表）

        Returns:
            所有路由配置列表（包括禁用的）
        """
        with self._lock:
            return list(self._routes)

    def get_enabled_routes(self) -> List[Any]:
        """获取所有启用的模块路由

        Returns:
            启用的路由配置列表
        """
        with self._lock:
            return [r for r in self._routes if r.enabled]

    def get_route(self, key: str) -> Optional[Any]:
        """根据模块 key 获取路由配置

        Args:
            key: 模块标识，如 m1, m8

        Returns:
            ModuleRoute 或 None
        """
        with self._lock:
            return self._route_index.get(key)

    def find_route_by_path(self, path: str) -> Optional[Tuple[Any, str]]:
        """根据请求路径查找匹配的路由（最长前缀匹配）

        Args:
            path: 请求路径（如 /m1/api/v1/chat）

        Returns:
            (ModuleRoute, 剩余路径) 或 None
        """
        with self._lock:
            # 按前缀长度降序排序，实现最长前缀匹配
            sorted_routes = sorted(
                [r for r in self._routes if r.enabled],
                key=lambda r: len(r.prefix),
                reverse=True,
            )

        for route in sorted_routes:
            if path.startswith(route.prefix):
                remaining = path[len(route.prefix):]
                if not remaining.startswith("/"):
                    remaining = "/" + remaining
                return route, remaining

        return None

    # --------------------------------------------------------
    # 统计信息
    # --------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取配置管理器统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            total = len(self._routes)
            enabled = sum(1 for r in self._routes if r.enabled)
            return {
                "version": self._version,
                "total_routes": total,
                "enabled_routes": enabled,
                "disabled_routes": total - enabled,
                "load_count": self._load_count,
                "last_load_time": self._last_load_time,
                "config_path": self._config_path,
                "last_modified": self._last_modified,
                "last_error": self._last_error,
            }

    @property
    def config_path(self) -> Optional[str]:
        """配置文件路径"""
        return self._config_path

    @property
    def is_loaded(self) -> bool:
        """是否已加载配置"""
        with self._lock:
            return len(self._routes) > 0

    @property
    def version(self) -> str:
        """配置版本"""
        return self._version

    @property
    def load_count(self) -> int:
        """加载次数"""
        return self._load_count


# ============================================================
# 全局单例
# ============================================================

_route_config_manager: Optional[RouteConfigManager] = None
_manager_lock = threading.Lock()


def get_route_config_manager() -> RouteConfigManager:
    """获取全局路由配置管理器单例

    Returns:
        RouteConfigManager 实例
    """
    global _route_config_manager
    if _route_config_manager is None:
        with _manager_lock:
            if _route_config_manager is None:
                _route_config_manager = RouteConfigManager()
    return _route_config_manager


def _reset_route_config_manager_for_test():
    """重置单例（仅用于测试）"""
    global _route_config_manager
    with _manager_lock:
        _route_config_manager = None
