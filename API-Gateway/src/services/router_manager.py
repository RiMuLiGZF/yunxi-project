"""
云汐 API 网关 - 路由管理器

功能：
1. 从 RouteConfigLoader 读取配置
2. 支持热更新（调用 reload_config 方法）
3. 路由匹配（最长前缀匹配）
4. 权重路由（一致性哈希 / 随机权重）
5. 路由命中统计
6. 文件监听热加载（轮询方式，每 5 秒检查）
"""
import asyncio
import time
import logging
import threading
import random
import hashlib
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

from .route_config_loader import (
    RouteConfigLoader,
    RouteConfig,
    get_route_config_loader,
)

logger = logging.getLogger("yunxi-gateway.router-manager")


# ============================================================
# 路由命中统计
# ============================================================

class RouteStats:
    """路由统计信息"""

    def __init__(self):
        self._stats: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def record_hit(self, route_id: str, latency_ms: float, success: bool):
        """记录一次路由命中

        Args:
            route_id: 路由 ID
            latency_ms: 延迟（毫秒）
            success: 是否成功
        """
        with self._lock:
            if route_id not in self._stats:
                self._stats[route_id] = {
                    "total_hits": 0,
                    "success_hits": 0,
                    "failed_hits": 0,
                    "total_latency_ms": 0.0,
                    "last_hit_time": 0.0,
                }

            stats = self._stats[route_id]
            stats["total_hits"] += 1
            stats["total_latency_ms"] += latency_ms
            stats["last_hit_time"] = time.time()

            if success:
                stats["success_hits"] += 1
            else:
                stats["failed_hits"] += 1

    def get_route_stats(self, route_id: str) -> Optional[Dict[str, Any]]:
        """获取单条路由的统计信息"""
        with self._lock:
            if route_id not in self._stats:
                return None
            stats = self._stats[route_id].copy()
            if stats["total_hits"] > 0:
                stats["avg_latency_ms"] = round(
                    stats["total_latency_ms"] / stats["total_hits"], 2
                )
                stats["success_rate"] = round(
                    stats["success_hits"] / stats["total_hits"] * 100, 2
                )
            else:
                stats["avg_latency_ms"] = 0.0
                stats["success_rate"] = 0.0
            return stats

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有路由的统计信息"""
        with self._lock:
            result = {}
            for route_id, stats in self._stats.items():
                s = stats.copy()
                if s["total_hits"] > 0:
                    s["avg_latency_ms"] = round(
                        s["total_latency_ms"] / s["total_hits"], 2
                    )
                    s["success_rate"] = round(
                        s["success_hits"] / s["total_hits"] * 100, 2
                    )
                else:
                    s["avg_latency_ms"] = 0.0
                    s["success_rate"] = 0.0
                result[route_id] = s
            return result

    def reset(self):
        """重置所有统计"""
        with self._lock:
            self._stats.clear()


# ============================================================
# 路由管理器
# ============================================================

class RouterManager:
    """路由管理器

    负责路由的匹配、权重选择、热加载和统计。

    特性：
    - 从 RouteConfigLoader 读取配置
    - 最长前缀匹配
    - 权重路由（一致性哈希 / 随机权重）
    - 热更新支持
    - 路由命中统计
    - 文件变更自动检测（轮询）
    """

    def __init__(
        self,
        config_loader: Optional[RouteConfigLoader] = None,
        auto_reload: bool = True,
        reload_interval: int = 5,
    ):
        """
        Args:
            config_loader: 配置加载器，为 None 时使用全局单例
            auto_reload: 是否自动检测文件变更并重新加载
            reload_interval: 自动检测间隔（秒），默认 5 秒
        """
        self._loader = config_loader or get_route_config_loader()
        self._stats = RouteStats()
        self._auto_reload = auto_reload
        self._reload_interval = reload_interval
        self._reload_task: Optional[asyncio.Task] = None
        self._stop_event = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._reload_callbacks: List[callable] = []

    # --------------------------------------------------------
    # 初始化和生命周期
    # --------------------------------------------------------

    def initialize(self) -> bool:
        """初始化路由管理器

        尝试从配置文件加载路由配置。
        如果配置文件不存在或加载失败，回退到硬编码的默认路由。

        Returns:
            True 表示初始化成功
        """
        # 尝试从文件加载
        success = self._loader.load_from_file()

        if not success:
            logger.warning(
                "Failed to load routes from config file, "
                "will use hardcoded routes as fallback"
            )
            # 回退到硬编码路由（向后兼容）
            self._load_hardcoded_routes()

        # 启动自动检测（如果启用）
        if self._auto_reload:
            self._start_auto_reload()

        logger.info(
            f"RouterManager initialized: {len(self._loader.get_routes())} routes "
            f"(auto_reload={self._auto_reload}, interval={self._reload_interval}s)"
        )
        return True

    def _load_hardcoded_routes(self):
        """加载硬编码的默认路由（向后兼容 fallback）"""
        try:
            from ..config import build_default_routes, ModuleRoute

            default_routes = build_default_routes()
            route_configs = []

            for route in default_routes:
                route_configs.append(
                    RouteConfig(
                        id=route.key,
                        name=route.name,
                        description=route.description,
                        path=route.prefix,
                        target=route.key,
                        url=route.target_url,
                        weight=100,
                        timeout=route.timeout,
                        retry=2,
                        strip_prefix=True,
                        enabled=route.enabled,
                        auth_required=route.auth_required,
                        health_path=route.health_path,
                        health_timeout=route.health_timeout,
                        public_paths=list(route.public_paths),
                        rate_limit={
                            "per_minute": route.rate_limit_per_minute,
                            "per_ip": route.rate_limit_per_ip,
                            "tier": route.rate_limit_tier,
                        },
                        supports_websocket=route.supports_websocket,
                        supports_sse=route.supports_sse,
                        circuit_breaker={
                            "failure_threshold": route.cb_failure_threshold,
                            "recovery_time": route.cb_recovery_time,
                        },
                    )
                )

            # 直接设置路由（绕过校验中的重复检查）
            self._loader._routes = route_configs
            self._loader._route_index = {r.id: r for r in route_configs}
            self._loader._load_count += 1
            self._loader._last_load_time = time.time()

            logger.info(f"Loaded {len(route_configs)} hardcoded routes as fallback")
        except Exception as e:
            logger.error(f"Failed to load hardcoded routes: {e}", exc_info=True)

    async def start(self):
        """异步启动（用于 ASGI 应用）"""
        self.initialize()
        if self._auto_reload:
            self._start_async_auto_reload()

    async def stop(self):
        """停止路由管理器"""
        self._stop_event.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=2)
        if self._reload_task:
            self._reload_task.cancel()
        logger.info("RouterManager stopped")

    # --------------------------------------------------------
    # 自动热加载
    # --------------------------------------------------------

    def _start_auto_reload(self):
        """启动自动热加载（线程轮询方式）"""
        if self._poll_thread and self._poll_thread.is_alive():
            return

        self._stop_event.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="route-config-watcher",
            daemon=True,
        )
        self._poll_thread.start()
        logger.info(f"Auto-reload started (interval={self._reload_interval}s)")

    def _start_async_auto_reload(self):
        """启动异步自动热加载"""
        loop = asyncio.get_event_loop()
        self._reload_task = loop.create_task(self._async_poll_loop())

    def _poll_loop(self):
        """轮询循环（线程模式）"""
        logger.debug("Config file watcher started")
        while not self._stop_event.is_set():
            try:
                if self._loader.check_for_changes():
                    logger.info("Config file change detected, reloading...")
                    self.reload_config()
            except Exception as e:
                logger.error(f"Error in config watcher: {e}", exc_info=True)

            # 分段 sleep，便于快速停止
            for _ in range(self._reload_interval * 2):
                if self._stop_event.is_set():
                    break
                time.sleep(0.5)

        logger.debug("Config file watcher stopped")

    async def _async_poll_loop(self):
        """异步轮询循环"""
        logger.debug("Async config file watcher started")
        while True:
            try:
                await asyncio.sleep(self._reload_interval)
                if self._loader.check_for_changes():
                    logger.info("Config file change detected (async), reloading...")
                    self.reload_config()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in async config watcher: {e}", exc_info=True)

        logger.debug("Async config file watcher stopped")

    # --------------------------------------------------------
    # 热更新
    # --------------------------------------------------------

    def reload_config(self) -> bool:
        """重新加载路由配置

        热加载时：
        - 新配置加载成功后，新请求使用新配置
        - 进行中的请求不受影响（因为使用的是路由引用）
        - 加载失败时保留旧配置

        Returns:
            True 表示重新加载成功
        """
        old_count = len(self._loader.get_all_routes())
        success = self._loader.reload()

        if success:
            new_count = len(self._loader.get_all_routes())
            logger.info(
                f"Routes reloaded: {old_count} -> {new_count} "
                f"(load_count={self._loader.get_stats()['load_count']})"
            )
            # 通知回调
            self._notify_reload_callbacks(success)
        else:
            logger.error(
                f"Route reload failed, keeping {old_count} old routes. "
                f"Error: {self._loader.get_stats()['last_error']}"
            )
            self._notify_reload_callbacks(False)

        return success

    def register_reload_callback(self, callback: callable):
        """注册配置重新加载回调

        Args:
            callback: 回调函数，接收一个 bool 参数表示是否成功
        """
        with self._lock:
            self._reload_callbacks.append(callback)

    def _notify_reload_callbacks(self, success: bool):
        """通知所有回调"""
        with self._lock:
            callbacks = list(self._reload_callbacks)

        for cb in callbacks:
            try:
                cb(success)
            except Exception as e:
                logger.error(f"Error in reload callback: {e}", exc_info=True)

    # --------------------------------------------------------
    # 路由匹配
    # --------------------------------------------------------

    def match_route(self, path: str, method: str = "GET") -> Optional[RouteConfig]:
        """匹配路由（最长前缀匹配）

        Args:
            path: 请求路径
            method: HTTP 方法

        Returns:
            匹配的路由配置，无匹配返回 None
        """
        route = self._loader.match_route(path, method)
        if route:
            logger.debug(f"Route matched: {path} -> {route.id}")
        return route

    def match_route_with_remaining(
        self, path: str, method: str = "GET"
    ) -> Optional[Tuple[RouteConfig, str]]:
        """匹配路由并返回剩余路径

        Args:
            path: 请求路径
            method: HTTP 方法

        Returns:
            (路由配置, 剩余路径) 或 None
        """
        route = self.match_route(path, method)
        if not route:
            return None

        # 计算剩余路径
        if route.strip_prefix:
            remaining = path[len(route.path):]
            if not remaining.startswith("/"):
                remaining = "/" + remaining
        else:
            remaining = path

        return route, remaining

    # --------------------------------------------------------
    # 权重路由
    # --------------------------------------------------------

    def select_weighted_target(
        self,
        route_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """权重路由选择（预留接口，支持灰度发布）

        当前版本：单目标路由，直接返回配置的 URL。
        后续版本可扩展为多目标权重路由。

        Args:
            route_id: 路由 ID
            user_id: 用户 ID（用于一致性哈希）

        Returns:
            目标 URL，无可用目标返回 None
        """
        route = self._loader.get_route(route_id)
        if not route or not route.enabled:
            return None

        # 单目标直接返回
        return route.url

    def _consistent_hash_select(self, targets: List[Any], user_id: str) -> Any:
        """一致性哈希选择

        Args:
            targets: 目标列表
            user_id: 用户 ID

        Returns:
            选中的目标
        """
        if not targets:
            return None

        virtual_nodes = 100
        ring: Dict[int, Any] = {}

        for i, target in enumerate(targets):
            for j in range(virtual_nodes):
                key = f"target-{i}-{j}"
                hash_val = int(hashlib.md5(key.encode()).hexdigest(), 16)
                ring[hash_val] = target

        if not ring:
            return None

        user_hash = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        sorted_keys = sorted(ring.keys())

        for key in sorted_keys:
            if key >= user_hash:
                return ring[key]

        return ring[sorted_keys[0]]

    # --------------------------------------------------------
    # 统计
    # --------------------------------------------------------

    def record_hit(self, route_id: str, latency_ms: float, success: bool):
        """记录路由命中"""
        self._stats.record_hit(route_id, latency_ms, success)

    def get_route_stats(self, route_id: str) -> Optional[Dict[str, Any]]:
        """获取单条路由的统计信息"""
        return self._stats.get_route_stats(route_id)

    def get_all_stats(self) -> Dict[str, Any]:
        """获取所有统计信息"""
        return {
            "routes": self._stats.get_all_stats(),
            "loader": self._loader.get_stats(),
            "auto_reload": self._auto_reload,
            "reload_interval": self._reload_interval,
        }

    def reset_stats(self):
        """重置统计"""
        self._stats.reset()

    # --------------------------------------------------------
    # 运行时路由管理
    # --------------------------------------------------------

    def add_route(self, route: RouteConfig) -> bool:
        """运行时添加路由（仅内存生效）"""
        return self._loader.add_route(route)

    def update_route(self, route_id: str, updates: Dict[str, Any]) -> bool:
        """运行时更新路由（仅内存生效）"""
        return self._loader.update_route(route_id, updates)

    def delete_route(self, route_id: str) -> bool:
        """运行时删除路由（仅内存生效）"""
        return self._loader.delete_route(route_id)

    def get_all_routes(self) -> List[RouteConfig]:
        """获取所有路由"""
        return self._loader.get_all_routes()

    def get_enabled_routes(self) -> List[RouteConfig]:
        """获取所有启用的路由"""
        return self._loader.get_routes()

    def get_route(self, route_id: str) -> Optional[RouteConfig]:
        """根据 ID 获取路由"""
        return self._loader.get_route(route_id)

    # --------------------------------------------------------
    # 属性
    # --------------------------------------------------------

    @property
    def config_loader(self) -> RouteConfigLoader:
        """配置加载器"""
        return self._loader

    @property
    def stats(self) -> RouteStats:
        """统计信息"""
        return self._stats

    @property
    def auto_reload(self) -> bool:
        """是否启用自动热加载"""
        return self._auto_reload


# ============================================================
# 全局单例
# ============================================================

_router_manager: Optional[RouterManager] = None
_manager_lock = threading.Lock()


def get_router_manager() -> RouterManager:
    """获取全局路由管理器单例"""
    global _router_manager
    if _router_manager is None:
        with _manager_lock:
            if _router_manager is None:
                _router_manager = RouterManager()
    return _router_manager
