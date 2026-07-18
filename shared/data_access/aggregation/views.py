"""
数据视图（Data Views）
====================

提供虚拟视图定义、视图缓存、视图权限控制和视图刷新能力。

数据视图是基于底层数据模型的虚拟表，
可以包含计算字段、过滤条件和关联数据。
"""

from __future__ import annotations

import time
import hashlib
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from ..base import PaginationResult, QueryFilter


# ============================================================
# 视图权限
# ============================================================

@dataclass
class ViewPermission:
    """视图权限配置"""
    roles: Set[str] = field(default_factory=set)
    read_only: bool = True
    max_rows: int = 10000
    expose_fields: Optional[Set[str]] = None  # None 表示所有字段

    def can_access(self, role: str) -> bool:
        """检查角色是否有权限访问"""
        if not self.roles:
            return True  # 无限制
        return role in self.roles

    def filter_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """根据权限过滤字段"""
        if self.expose_fields is None:
            return data
        return {k: v for k, v in data.items() if k in self.expose_fields}


# ============================================================
# 视图缓存
# ============================================================

@dataclass
class ViewCache:
    """
    视图缓存配置与存储。

    Attributes:
        enabled: 是否启用缓存
        ttl_seconds: 缓存有效期（秒）
        max_entries: 最大缓存条目数
    """
    enabled: bool = False
    ttl_seconds: int = 300
    max_entries: int = 100

    def __post_init__(self):
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if not self.enabled:
            return None
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            cached_at, value = entry
            if time.time() - cached_at > self.ttl_seconds:
                del self._cache[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        """设置缓存"""
        if not self.enabled:
            return
        with self._lock:
            # 淘汰旧数据
            if len(self._cache) >= self.max_entries:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][0])
                del self._cache[oldest_key]
            self._cache[key] = (time.time(), value)

    def invalidate(self, key: Optional[str] = None) -> int:
        """
        失效缓存。

        Args:
            key: 指定 key，None 表示全部失效

        Returns:
            失效的条目数
        """
        with self._lock:
            if key:
                if key in self._cache:
                    del self._cache[key]
                    return 1
                return 0
            else:
                count = len(self._cache)
                self._cache.clear()
                return count

    def size(self) -> int:
        """缓存大小"""
        with self._lock:
            return len(self._cache)


# ============================================================
# 数据视图定义
# ============================================================

@dataclass
class DataView:
    """
    数据视图定义。

    视图是基于底层数据模型的虚拟表，
    可以包含过滤、字段选择、计算字段等。

    Attributes:
        name: 视图名称
        description: 视图描述
        source_model: 源模型名称
        filters: 过滤条件
        fields: 包含的字段（None 表示全部）
        computed_fields: 计算字段定义 {字段名: 计算函数}
        permission: 权限配置
        cache: 缓存配置
        refresh_interval: 自动刷新间隔（秒），None 表示不自动刷新
    """
    name: str
    source_model: str
    description: str = ""
    filters: List[QueryFilter] = field(default_factory=list)
    fields: Optional[List[str]] = None
    computed_fields: Dict[str, Callable[[Dict[str, Any]], Any]] = field(default_factory=dict)
    permission: ViewPermission = field(default_factory=ViewPermission)
    cache: ViewCache = field(default_factory=ViewCache)
    refresh_interval: Optional[int] = None
    last_refreshed: Optional[float] = None

    def _cache_key(self, page: int, page_size: int, role: str = "") -> str:
        """生成缓存 key"""
        content = f"{self.name}:{page}:{page_size}:{role}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def _apply_fields(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """应用字段选择和计算字段"""
        result = {}

        # 选择字段
        if self.fields:
            for f in self.fields:
                result[f] = row.get(f)
        else:
            result = dict(row)

        # 计算字段
        for field_name, func in self.computed_fields.items():
            try:
                result[field_name] = func(row)
            except Exception:
                result[field_name] = None

        return result

    def needs_refresh(self) -> bool:
        """是否需要刷新"""
        if self.refresh_interval is None:
            return False
        if self.last_refreshed is None:
            return True
        return time.time() - self.last_refreshed > self.refresh_interval


# ============================================================
# 视图管理器
# ============================================================

class ViewManager:
    """
    视图管理器。

    管理所有数据视图的注册、查询、缓存和刷新。
    """

    def __init__(self, query_service: Any = None):
        """
        Args:
            query_service: 查询服务实例
        """
        self._views: Dict[str, DataView] = {}
        self._query_service = query_service
        self._lock = threading.RLock()

    def set_query_service(self, query_service: Any) -> None:
        """设置查询服务"""
        self._query_service = query_service

    # ---- 视图注册 ----

    def register_view(self, view: DataView) -> None:
        """注册视图"""
        with self._lock:
            self._views[view.name] = view

    def unregister_view(self, name: str) -> bool:
        """注销视图"""
        with self._lock:
            if name in self._views:
                del self._views[name]
                return True
            return False

    def get_view(self, name: str) -> Optional[DataView]:
        """获取视图定义"""
        return self._views.get(name)

    def list_views(self) -> List[Dict[str, Any]]:
        """列出所有视图（元信息）"""
        with self._lock:
            return [
                {
                    "name": view.name,
                    "description": view.description,
                    "source_model": view.source_model,
                    "fields_count": len(view.fields) if view.fields else 0,
                    "has_computed_fields": len(view.computed_fields) > 0,
                    "cached": view.cache.enabled,
                    "refresh_interval": view.refresh_interval,
                }
                for view in self._views.values()
            ]

    # ---- 视图查询 ----

    def query_view(
        self,
        name: str,
        page: int = 1,
        page_size: int = 20,
        role: str = "",
        extra_filters: Optional[List[QueryFilter]] = None,
    ) -> Dict[str, Any]:
        """
        查询视图数据。

        Args:
            name: 视图名称
            page: 页码
            page_size: 每页大小
            role: 访问角色（用于权限检查）
            extra_filters: 额外过滤条件

        Returns:
            查询结果

        Raises:
            PermissionError: 无权限访问
            ValueError: 视图不存在
        """
        view = self._views.get(name)
        if not view:
            raise ValueError(f"View not found: {name}")

        # 权限检查
        if not view.permission.can_access(role):
            raise PermissionError(f"Role '{role}' cannot access view '{name}'")

        # 行级限制
        actual_page_size = min(page_size, view.permission.max_rows)

        # 尝试缓存
        cache_key = view._cache_key(page, actual_page_size, role)
        cached = view.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore

        # 构建查询
        all_filters = list(view.filters)
        if extra_filters:
            all_filters.extend(extra_filters)

        if not self._query_service:
            raise RuntimeError("Query service not configured")

        # 执行查询
        result = self._query_service.query(
            model_name=view.source_model,
            filters=all_filters,
            page=page,
            page_size=actual_page_size,
        )

        # 应用字段和计算字段
        items = []
        for item in result.items:
            row = item.to_dict() if hasattr(item, "to_dict") else item
            processed = view._apply_fields(row)
            # 字段级权限过滤
            processed = view.permission.filter_fields(processed)
            items.append(processed)

        response = {
            "view": name,
            "items": items,
            "total": result.total,
            "page": result.page,
            "page_size": actual_page_size,
            "total_pages": result.total_pages,
            "cached": False,
        }

        # 缓存结果
        view.cache.set(cache_key, response)

        return response

    # ---- 缓存管理 ----

    def refresh_view(self, name: str) -> bool:
        """
        刷新视图（清空缓存）。

        Returns:
            是否成功
        """
        view = self._views.get(name)
        if not view:
            return False
        view.last_refreshed = time.time()
        invalidated = view.cache.invalidate()
        return invalidated >= 0

    def refresh_all(self) -> int:
        """刷新所有视图"""
        total = 0
        for view in self._views.values():
            view.last_refreshed = time.time()
            total += view.cache.invalidate()
        return total

    def invalidate_cache(self, view_name: Optional[str] = None) -> int:
        """
        失效视图缓存。

        Args:
            view_name: 视图名称，None 表示全部

        Returns:
            失效的缓存条目数
        """
        if view_name:
            view = self._views.get(view_name)
            if view:
                return view.cache.invalidate()
            return 0
        else:
            total = 0
            for view in self._views.values():
                total += view.cache.invalidate()
            return total

    # ---- 统计 ----

    def get_stats(self) -> Dict[str, Any]:
        """获取视图统计信息"""
        with self._lock:
            total_cache = 0
            cached_views = 0
            for view in self._views.values():
                size = view.cache.size()
                total_cache += size
                if size > 0:
                    cached_views += 1

            return {
                "total_views": len(self._views),
                "cached_views": cached_views,
                "total_cache_entries": total_cache,
                "views": [
                    {
                        "name": v.name,
                        "source_model": v.source_model,
                        "cache_enabled": v.cache.enabled,
                        "cache_size": v.cache.size(),
                        "last_refreshed": v.last_refreshed,
                    }
                    for v in self._views.values()
                ],
            }


# ============================================================
# 全局单例
# ============================================================

_view_manager: Optional[ViewManager] = None


def get_view_manager() -> ViewManager:
    """获取视图管理器单例"""
    global _view_manager
    if _view_manager is None:
        _view_manager = ViewManager()
    return _view_manager


def reset_view_manager() -> None:
    """重置视图管理器（测试用）"""
    global _view_manager
    _view_manager = None
