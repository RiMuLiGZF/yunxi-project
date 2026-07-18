"""
云汐 API 网关 - 路由配置加载器

功能：
1. 从 YAML/JSON 文件加载路由配置
2. 从数据库加载路由配置（预留接口）
3. 配置校验
4. 路由匹配（最长前缀匹配）
5. 热加载支持
"""
import os
import time
import logging
import threading
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, validator

logger = logging.getLogger("yunxi-gateway.route-loader")

# 尝试导入 yaml
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ============================================================
# 配置数据模型
# ============================================================

class RateLimitConfig(BaseModel):
    """限流配置"""
    per_minute: int = 60
    per_ip: int = 30
    tier: str = "public"


class CircuitBreakerConfig(BaseModel):
    """熔断器配置"""
    failure_threshold: int = 5
    recovery_time: int = 30


class RouteConfig(BaseModel):
    """路由配置（完整配置项）

    Attributes:
        id: 路由唯一标识
        name: 路由名称
        description: 描述信息
        path: 路径前缀
        target: 目标服务名
        url: 目标 URL
        weight: 权重（用于灰度发布）
        methods: 允许的 HTTP 方法
        timeout: 超时时间（秒）
        retry: 重试次数
        strip_prefix: 是否剥离前缀
        enabled: 是否启用
        auth_required: 是否需要认证
        health_path: 健康检查路径
        health_timeout: 健康检查超时
        public_paths: 公开路径白名单
        rate_limit: 限流配置
        supports_websocket: 是否支持 WebSocket
        supports_sse: 是否支持 SSE
        circuit_breaker: 熔断器配置
        plugins: 插件列表
    """
    id: str
    name: str = ""
    description: str = ""
    path: str
    target: str = ""
    url: str
    weight: int = 100
    methods: List[str] = Field(default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "PATCH"])
    timeout: float = 30.0
    retry: int = 2
    strip_prefix: bool = True
    enabled: bool = True
    auth_required: bool = True
    health_path: str = "/health"
    health_timeout: float = 5.0
    public_paths: List[str] = Field(default_factory=list)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    supports_websocket: bool = False
    supports_sse: bool = False
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    plugins: List[str] = Field(default_factory=list)

    @validator('path')
    def path_must_start_with_slash(cls, v: str) -> str:
        if not v.startswith('/'):
            raise ValueError(f"path must start with '/', got: {v}")
        return v

    @validator('weight')
    def weight_must_be_positive(cls, v: int) -> int:
        if v < 0 or v > 100:
            raise ValueError(f"weight must be between 0 and 100, got: {v}")
        return v

    @validator('timeout')
    def timeout_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"timeout must be positive, got: {v}")
        return v

    class Config:
        extra = "allow"


class RouteConfigFile(BaseModel):
    """路由配置文件结构"""
    version: str = "1.0.0"
    defaults: Dict[str, Any] = Field(default_factory=dict)
    routes: List[RouteConfig] = Field(default_factory=list)


# ============================================================
# 路由配置加载器
# ============================================================

class RouteConfigLoader:
    """路由配置加载器

    负责从各种数据源加载和管理路由配置，支持热加载。

    功能：
    - 从 YAML/JSON 文件加载配置
    - 从数据库加载配置（预留）
    - 配置校验
    - 路由匹配（最长前缀匹配）
    - 热加载支持
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Args:
            config_path: 配置文件路径，默认为 config/routes.yaml
        """
        self._lock = threading.RLock()
        self._routes: List[RouteConfig] = []
        self._route_index: Dict[str, RouteConfig] = {}
        self._config_path: Optional[str] = None
        self._last_modified: float = 0.0
        self._load_count: int = 0
        self._last_load_time: float = 0.0
        self._last_error: Optional[str] = None

        # 默认配置路径
        if config_path is None:
            # 向上查找项目根目录下的 config/routes.yaml
            current = Path(__file__).resolve()
            for _ in range(5):
                candidate = current.parent / "config" / "routes.yaml"
                if candidate.exists():
                    config_path = str(candidate)
                    break
                current = current.parent
            if config_path is None:
                # 使用相对路径作为后备
                config_path = "config/routes.yaml"

        self._config_path = config_path

    # --------------------------------------------------------
    # 加载方法
    # --------------------------------------------------------

    def load_from_file(self, path: Optional[str] = None) -> bool:
        """从文件加载路由配置

        Args:
            path: 配置文件路径，为 None 时使用初始化时的路径

        Returns:
            True 表示加载成功，False 表示失败
        """
        if path is not None:
            self._config_path = path

        if self._config_path is None:
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
            return self._load_from_content(content, config_file.suffix)
        except Exception as e:
            self._last_error = f"Failed to load config file: {e}"
            logger.error(self._last_error, exc_info=True)
            return False

    def load_from_db(self) -> bool:
        """从数据库加载路由配置（预留接口）

        Returns:
            True 表示加载成功，False 表示失败
        """
        # 预留接口，后续版本实现
        logger.info("load_from_db() is not implemented yet")
        return False

    def load_from_dict(self, data: Dict[str, Any]) -> bool:
        """从字典数据加载路由配置

        Args:
            data: 配置数据字典

        Returns:
            True 表示加载成功，False 表示失败
        """
        try:
            config_file = RouteConfigFile(**data)
            return self._apply_routes(config_file.routes)
        except Exception as e:
            self._last_error = f"Failed to load from dict: {e}"
            logger.error(self._last_error, exc_info=True)
            return False

    def _load_from_content(self, content: str, file_type: str) -> bool:
        """从内容字符串加载配置

        Args:
            content: 配置内容
            file_type: 文件类型（.yaml, .yml, .json）

        Returns:
            True 表示加载成功，False 表示失败
        """
        try:
            if file_type.lower() in ('.yaml', '.yml'):
                if not HAS_YAML:
                    self._last_error = "PyYAML not installed, cannot load YAML config"
                    logger.error(self._last_error)
                    return False
                data = yaml.safe_load(content)
            elif file_type.lower() == '.json':
                import json
                data = json.loads(content)
            else:
                # 默认尝试 YAML
                if HAS_YAML:
                    data = yaml.safe_load(content)
                else:
                    import json
                    data = json.loads(content)

            if data is None:
                self._last_error = "Empty config file"
                logger.warning(self._last_error)
                return False

            return self.load_from_dict(data)

        except Exception as e:
            self._last_error = f"Failed to parse config content: {e}"
            logger.error(self._last_error, exc_info=True)
            return False

    def _apply_routes(self, routes: List[RouteConfig]) -> bool:
        """应用路由配置（原子替换）

        Args:
            routes: 新的路由列表

        Returns:
            True 表示成功
        """
        # 校验
        validation_errors = self._validate_routes(routes)
        if validation_errors:
            self._last_error = f"Validation failed: {'; '.join(validation_errors)}"
            logger.error(self._last_error)
            return False

        with self._lock:
            self._routes = routes
            self._route_index = {r.id: r for r in routes}
            self._load_count += 1
            self._last_load_time = time.time()
            self._last_error = None

            if self._config_path and Path(self._config_path).exists():
                self._last_modified = Path(self._config_path).stat().st_mtime

        logger.info(
            f"Route config loaded: {len(routes)} routes, "
            f"load_count={self._load_count}"
        )
        return True

    # --------------------------------------------------------
    # 校验方法
    # --------------------------------------------------------

    def validate(self) -> List[str]:
        """校验当前路由配置

        Returns:
            错误列表，空列表表示校验通过
        """
        with self._lock:
            return self._validate_routes(self._routes)

    def _validate_routes(self, routes: List[RouteConfig]) -> List[str]:
        """校验路由配置列表

        Args:
            routes: 路由列表

        Returns:
            错误列表
        """
        errors = []

        if not routes:
            errors.append("No routes defined")
            return errors

        # 检查 ID 重复
        seen_ids = set()
        for route in routes:
            if route.id in seen_ids:
                errors.append(f"Duplicate route id: {route.id}")
            seen_ids.add(route.id)

        # 检查路径重复（可能导致匹配歧义）
        seen_paths = {}
        for route in routes:
            if route.path in seen_paths:
                errors.append(
                    f"Duplicate path '{route.path}' in routes "
                    f"'{seen_paths[route.path]}' and '{route.id}'"
                )
            seen_paths[route.path] = route.id

        # 检查 URL 格式
        for route in routes:
            if not route.url:
                errors.append(f"Route '{route.id}' has empty url")
            elif not route.url.startswith(('http://', 'https://', 'internal://')):
                errors.append(
                    f"Route '{route.id}' has invalid url scheme: {route.url}"
                )

        return errors

    # --------------------------------------------------------
    # 查询方法
    # --------------------------------------------------------

    def get_routes(self) -> List[RouteConfig]:
        """获取所有有效路由

        Returns:
            路由配置列表（仅启用的）
        """
        with self._lock:
            return [r for r in self._routes if r.enabled]

    def get_all_routes(self) -> List[RouteConfig]:
        """获取所有路由（包括禁用的）

        Returns:
            所有路由配置列表
        """
        with self._lock:
            return list(self._routes)

    def get_route(self, route_id: str) -> Optional[RouteConfig]:
        """根据 ID 获取路由

        Args:
            route_id: 路由 ID

        Returns:
            路由配置，不存在返回 None
        """
        with self._lock:
            return self._route_index.get(route_id)

    def match_route(self, path: str, method: str = "GET") -> Optional[RouteConfig]:
        """根据路径匹配路由（最长前缀匹配）

        Args:
            path: 请求路径
            method: HTTP 方法

        Returns:
            匹配的路由配置，无匹配返回 None
        """
        with self._lock:
            # 按路径长度降序排序，实现最长前缀匹配
            sorted_routes = sorted(
                [r for r in self._routes if r.enabled],
                key=lambda r: len(r.path),
                reverse=True
            )

            for route in sorted_routes:
                if path.startswith(route.path):
                    # 检查方法限制
                    if route.methods and method.upper() not in [m.upper() for m in route.methods]:
                        continue
                    # 确保前缀匹配是完整的路径段
                    remaining = path[len(route.path):]
                    if not remaining or remaining.startswith('/'):
                        return route

            return None

    # --------------------------------------------------------
    # 运行时修改方法
    # --------------------------------------------------------

    def add_route(self, route: RouteConfig) -> bool:
        """运行时添加路由（仅内存生效）

        Args:
            route: 路由配置

        Returns:
            True 表示成功
        """
        with self._lock:
            if route.id in self._route_index:
                self._last_error = f"Route '{route.id}' already exists"
                logger.warning(self._last_error)
                return False

            self._routes.append(route)
            self._route_index[route.id] = route
            logger.info(f"Route added: {route.id}")
            return True

    def update_route(self, route_id: str, updates: Dict[str, Any]) -> bool:
        """运行时更新路由（仅内存生效）

        Args:
            route_id: 路由 ID
            updates: 更新字段字典

        Returns:
            True 表示成功
        """
        with self._lock:
            if route_id not in self._route_index:
                self._last_error = f"Route '{route_id}' not found"
                logger.warning(self._last_error)
                return False

            existing = self._route_index[route_id]
            try:
                # 创建更新后的路由
                existing_dict = existing.dict()
                existing_dict.update(updates)
                updated = RouteConfig(**existing_dict)

                # 替换
                idx = self._routes.index(existing)
                self._routes[idx] = updated
                self._route_index[route_id] = updated

                logger.info(f"Route updated: {route_id}")
                return True
            except Exception as e:
                self._last_error = f"Failed to update route '{route_id}': {e}"
                logger.error(self._last_error)
                return False

    def delete_route(self, route_id: str) -> bool:
        """运行时删除路由（仅内存生效）

        Args:
            route_id: 路由 ID

        Returns:
            True 表示成功
        """
        with self._lock:
            if route_id not in self._route_index:
                self._last_error = f"Route '{route_id}' not found"
                logger.warning(self._last_error)
                return False

            route = self._route_index.pop(route_id)
            self._routes.remove(route)
            logger.info(f"Route deleted: {route_id}")
            return True

    # --------------------------------------------------------
    # 热加载
    # --------------------------------------------------------

    def reload(self) -> bool:
        """重新加载配置

        从当前配置文件重新加载。
        热加载时：新配置加载失败时保留旧配置。

        Returns:
            True 表示重新加载成功
        """
        logger.info("Reloading route config...")

        # 保存旧配置
        with self._lock:
            old_routes = list(self._routes)
            old_index = dict(self._route_index)

        # 尝试加载新配置
        success = self.load_from_file()

        if not success:
            # 加载失败，恢复旧配置
            with self._lock:
                self._routes = old_routes
                self._route_index = old_index
            logger.error(
                f"Route config reload failed, keeping old config. "
                f"Error: {self._last_error}"
            )
            return False

        logger.info("Route config reloaded successfully")
        return True

    def check_for_changes(self) -> bool:
        """检查配置文件是否有变更

        Returns:
            True 表示文件有变更
        """
        if self._config_path is None:
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
    # 统计信息
    # --------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取加载器统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            total = len(self._routes)
            enabled = sum(1 for r in self._routes if r.enabled)
            return {
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
        return len(self._routes) > 0


# ============================================================
# 全局单例
# ============================================================

_route_loader: Optional[RouteConfigLoader] = None
_loader_lock = threading.Lock()


def get_route_config_loader() -> RouteConfigLoader:
    """获取全局路由配置加载器单例"""
    global _route_loader
    if _route_loader is None:
        with _loader_lock:
            if _route_loader is None:
                _route_loader = RouteConfigLoader()
    return _route_loader
