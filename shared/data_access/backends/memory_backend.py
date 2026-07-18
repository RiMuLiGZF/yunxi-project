"""
内存存储后端（Memory Backend）
============================

纯内存实现，适合：
- 单元测试
- 临时数据缓存
- 开发调试

所有数据存储在内存字典中，进程退出后数据丢失。
"""

from __future__ import annotations

import copy
import time
import threading
from typing import Any, Dict, List, Optional, Type

from ..base import (
    BaseModel,
    BaseRepository,
    OrderBy,
    PaginationResult,
    QueryFilter,
    UnitOfWork,
    BackendFactory,
    T,
)


# ============================================================
# 内存仓库实现
# ============================================================

class MemoryRepository(BaseRepository[T]):
    """内存仓库实现"""

    def __init__(self, backend: "MemoryBackend", model_class: Type[BaseModel]):
        super().__init__(backend=backend)
        self._model_class = model_class
        self._data: Dict[Any, Dict[str, Any]] = backend.get_data_store(
            model_class.__table_name__
        )
        self._lock = backend.get_lock()
        self._auto_increment = backend.get_auto_increment(
            model_class.__table_name__
        )

    def _next_id(self) -> int:
        """生成下一个自增 ID"""
        pk_field = self._model_class.get_primary_key_field()
        if pk_field and self._model_class.__fields__.get(pk_field, {}).get("auto_increment"):
            self._auto_increment[pk_field] = self._auto_increment.get(pk_field, 0) + 1
            return self._auto_increment[pk_field]
        return 0

    def _do_create(self, data: Dict[str, Any]) -> T:
        with self._lock:
            pk_field = self._model_class.get_primary_key_field()

            # 处理自增主键
            if pk_field and pk_field not in data:
                field_def = self._model_class.__fields__.get(pk_field, {})
                if field_def.get("auto_increment"):
                    data = dict(data)
                    data[pk_field] = self._next_id()

            # 处理时间戳字段
            ts_fields = ["created_at", "updated_at"]
            for ts_field in ts_fields:
                if ts_field in self._model_class.__fields__ and ts_field not in data:
                    data = dict(data)
                    data[ts_field] = time.time()

            # 处理版本号
            if "version" in self._model_class.__fields__ and "version" not in data:
                data = dict(data)
                data["version"] = 1

            pk = data.get(pk_field) if pk_field else id(data)
            self._data[pk] = copy.deepcopy(data)
            return self._model_class.from_dict(data)  # type: ignore

    def _do_get_by_id(self, pk: Any) -> Optional[T]:
        with self._lock:
            data = self._data.get(pk)
            if data is None:
                return None
            return self._model_class.from_dict(copy.deepcopy(data))  # type: ignore

    def _do_update(self, pk: Any, data: Dict[str, Any]) -> Optional[T]:
        with self._lock:
            if pk not in self._data:
                return None

            existing = self._data[pk]
            # 更新字段
            for key, value in data.items():
                if key in self._model_class.__fields__:
                    existing[key] = value

            # 更新时间戳
            if "updated_at" in self._model_class.__fields__:
                existing["updated_at"] = time.time()

            # 版本号递增
            if "version" in self._model_class.__fields__:
                existing["version"] = (existing.get("version") or 0) + 1

            self._data[pk] = existing
            return self._model_class.from_dict(copy.deepcopy(existing))  # type: ignore

    def _do_delete(self, pk: Any) -> bool:
        with self._lock:
            if pk in self._data:
                del self._data[pk]
                return True
            return False

    def _filter_data(self, filters: List[QueryFilter]) -> List[Dict[str, Any]]:
        """过滤数据"""
        results = list(self._data.values())
        for f in filters:
            results = [item for item in results if f.matches(item)]
        return results

    def _sort_data(self, data: List[Dict[str, Any]], order_by: List[OrderBy]) -> List[Dict[str, Any]]:
        """排序数据"""
        if not order_by:
            return data

        result = list(data)
        for ob in reversed(order_by):  # 反向排序以保持优先级
            result.sort(
                key=lambda x: (x.get(ob.field) is None, x.get(ob.field)),
                reverse=not ob.ascending,
            )
        return result

    def _execute_query(
        self,
        filters: List[QueryFilter],
        order_by: List[OrderBy],
        limit: Optional[int],
        offset: Optional[int],
    ) -> List[T]:
        with self._lock:
            results = self._filter_data(filters)
            results = self._sort_data(results, order_by)

            if offset:
                results = results[offset:]
            if limit is not None:
                results = results[:limit]

            return [self._model_class.from_dict(copy.deepcopy(item)) for item in results]  # type: ignore

    def _execute_paginated_query(
        self,
        filters: List[QueryFilter],
        order_by: List[OrderBy],
        page: int,
        page_size: int,
    ) -> PaginationResult[T]:
        with self._lock:
            all_results = self._filter_data(filters)
            total = len(all_results)
            sorted_results = self._sort_data(all_results, order_by)

            start = (page - 1) * page_size
            end = start + page_size
            page_items = sorted_results[start:end]

            items = [self._model_class.from_dict(copy.deepcopy(item)) for item in page_items]  # type: ignore

            return PaginationResult(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
            )

    def _count_query(self, filters: List[QueryFilter]) -> int:
        with self._lock:
            return len(self._filter_data(filters))


# ============================================================
# 内存工作单元
# ============================================================

class MemoryUnitOfWork(UnitOfWork):
    """内存工作单元（基于版本的事务模拟）"""

    def __init__(self, backend: "MemoryBackend"):
        super().__init__(backend=backend)
        self._snapshots: Dict[str, Dict[Any, Dict[str, Any]]] = {}

    def begin(self) -> None:
        if self._active:
            return
        # 保存所有数据表的快照
        self._snapshots = {}
        for table_name, store in self._backend._stores.items():
            self._snapshots[table_name] = copy.deepcopy(store)
        self._active = True

    def commit(self) -> None:
        if not self._active:
            return
        self._snapshots.clear()
        self._active = False

    def rollback(self) -> None:
        if not self._active:
            return
        # 恢复快照
        for table_name, snapshot in self._snapshots.items():
            self._backend._stores[table_name] = copy.deepcopy(snapshot)
        self._snapshots.clear()
        self._active = False


# ============================================================
# 内存后端
# ============================================================

class MemoryBackend(BackendFactory):
    """
    内存存储后端。

    所有数据存储在内存中，适合测试和临时使用。
    """

    def __init__(self):
        self._stores: Dict[str, Dict[Any, Dict[str, Any]]] = {}
        self._auto_increments: Dict[str, Dict[str, int]] = {}
        self._lock = threading.RLock()

    def get_data_store(self, table_name: str) -> Dict[Any, Dict[str, Any]]:
        """获取指定表的数据存储"""
        if table_name not in self._stores:
            self._stores[table_name] = {}
        return self._stores[table_name]

    def get_lock(self) -> threading.RLock:
        """获取全局锁"""
        return self._lock

    def get_auto_increment(self, table_name: str) -> Dict[str, int]:
        """获取自增计数器"""
        if table_name not in self._auto_increments:
            self._auto_increments[table_name] = {}
        return self._auto_increments[table_name]

    def create_repository(self, model_class: Type[BaseModel]) -> MemoryRepository:
        """创建仓库实例"""
        return MemoryRepository(self, model_class)

    def create_unit_of_work(self) -> MemoryUnitOfWork:
        """创建工作单元"""
        return MemoryUnitOfWork(self)

    def get_backend_type(self) -> str:
        return "memory"

    def clear(self) -> None:
        """清空所有数据"""
        with self._lock:
            self._stores.clear()
            self._auto_increments.clear()
