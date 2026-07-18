"""
JSON 文件存储后端（JSON Backend）
================================

基于 JSON 文件的仓库实现，适合：
- 小规模数据
- 配置数据
- 需要人工可读的数据文件

每个表对应一个 JSON 文件，数据以列表形式存储。
"""

from __future__ import annotations

import json
import time
import os
import threading
import copy
from typing import Any, Dict, List, Optional, Type
from pathlib import Path

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
# JSON 仓库实现
# ============================================================

class JSONRepository(BaseRepository[T]):
    """JSON 文件仓库实现"""

    def __init__(self, backend: "JSONBackend", model_class: Type[BaseModel]):
        super().__init__(backend=backend)
        self._model_class = model_class
        self._table_name = model_class.__table_name__
        self._file_path = backend.get_file_path(self._table_name)
        self._lock = backend.get_lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        """确保数据文件存在"""
        if not self._file_path.exists():
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)

    def _load_all(self) -> List[Dict[str, Any]]:
        """加载所有数据"""
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_all(self, data: List[Dict[str, Any]]) -> None:
        """保存所有数据"""
        tmp_path = self._file_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self._file_path)

    def _find_index(self, pk: Any, data: List[Dict[str, Any]]) -> int:
        """查找记录索引"""
        pk_field = self._model_class.get_primary_key_field() or "id"
        for i, item in enumerate(data):
            if item.get(pk_field) == pk:
                return i
        return -1

    def _next_id(self, data: List[Dict[str, Any]]) -> int:
        """生成下一个自增 ID"""
        pk_field = self._model_class.get_primary_key_field() or "id"
        max_id = 0
        for item in data:
            val = item.get(pk_field)
            if isinstance(val, int) and val > max_id:
                max_id = val
        return max_id + 1

    def _do_create(self, data: Dict[str, Any]) -> T:
        with self._lock:
            all_data = self._load_all()
            new_data = dict(data)

            pk_field = self._model_class.get_primary_key_field() or "id"

            # 处理自增主键
            field_def = self._model_class.__fields__.get(pk_field, {})
            if field_def.get("auto_increment") and (pk_field not in new_data or new_data[pk_field] is None):
                new_data[pk_field] = self._next_id(all_data)

            # 时间戳
            for ts_field in ["created_at", "updated_at"]:
                if ts_field in self._model_class.__fields__ and ts_field not in new_data:
                    new_data[ts_field] = time.time()

            # 版本号
            if "version" in self._model_class.__fields__ and "version" not in new_data:
                new_data["version"] = 1

            all_data.append(new_data)
            self._save_all(all_data)

            return self._model_class.from_dict(copy.deepcopy(new_data))  # type: ignore

    def _do_get_by_id(self, pk: Any) -> Optional[T]:
        with self._lock:
            all_data = self._load_all()
            idx = self._find_index(pk, all_data)
            if idx >= 0:
                return self._model_class.from_dict(copy.deepcopy(all_data[idx]))  # type: ignore
        return None

    def _do_update(self, pk: Any, data: Dict[str, Any]) -> Optional[T]:
        with self._lock:
            all_data = self._load_all()
            idx = self._find_index(pk, all_data)
            if idx < 0:
                return None

            for key, value in data.items():
                if key in self._model_class.__fields__:
                    all_data[idx][key] = value

            # 更新时间戳
            if "updated_at" in self._model_class.__fields__:
                all_data[idx]["updated_at"] = time.time()

            # 版本号递增
            if "version" in self._model_class.__fields__:
                all_data[idx]["version"] = (all_data[idx].get("version") or 0) + 1

            self._save_all(all_data)
            return self._model_class.from_dict(copy.deepcopy(all_data[idx]))  # type: ignore

    def _do_delete(self, pk: Any) -> bool:
        with self._lock:
            all_data = self._load_all()
            idx = self._find_index(pk, all_data)
            if idx >= 0:
                del all_data[idx]
                self._save_all(all_data)
                return True
        return False

    def _filter_data(self, data: List[Dict[str, Any]], filters: List[QueryFilter]) -> List[Dict[str, Any]]:
        """过滤数据"""
        results = list(data)
        for f in filters:
            results = [item for item in results if f.matches(item)]
        return results

    def _sort_data(self, data: List[Dict[str, Any]], order_by: List[OrderBy]) -> List[Dict[str, Any]]:
        """排序数据"""
        if not order_by:
            return data

        result = list(data)
        for ob in reversed(order_by):
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
            all_data = self._load_all()
            results = self._filter_data(all_data, filters)
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
            all_data = self._load_all()
            filtered = self._filter_data(all_data, filters)
            total = len(filtered)
            sorted_data = self._sort_data(filtered, order_by)

            start = (page - 1) * page_size
            end = start + page_size
            page_items = sorted_data[start:end]

            items = [self._model_class.from_dict(copy.deepcopy(item)) for item in page_items]  # type: ignore

            return PaginationResult(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
            )

    def _count_query(self, filters: List[QueryFilter]) -> int:
        with self._lock:
            all_data = self._load_all()
            return len(self._filter_data(all_data, filters))


# ============================================================
# JSON 工作单元
# ============================================================

class JSONUnitOfWork(UnitOfWork):
    """JSON 工作单元（基于文件快照的事务模拟）"""

    def __init__(self, backend: "JSONBackend"):
        super().__init__(backend=backend)
        self._snapshots: Dict[str, List[Dict[str, Any]]] = {}

    def begin(self) -> None:
        if self._active:
            return
        self._snapshots = {}
        self._active = True

    def _ensure_snapshot(self, table_name: str) -> None:
        """确保表的快照已保存"""
        if table_name not in self._snapshots:
            file_path = self._backend.get_file_path(table_name)
            if file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self._snapshots[table_name] = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError):
                    self._snapshots[table_name] = []
            else:
                self._snapshots[table_name] = []

    def register_table(self, table_name: str) -> None:
        """注册需要事务保护的表"""
        if self._active:
            self._ensure_snapshot(table_name)

    def commit(self) -> None:
        if not self._active:
            return
        self._snapshots.clear()
        self._active = False

    def rollback(self) -> None:
        if not self._active:
            return
        for table_name, snapshot in self._snapshots.items():
            file_path = self._backend.get_file_path(table_name)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
        self._snapshots.clear()
        self._active = False


# ============================================================
# JSON 后端
# ============================================================

class JSONBackend(BackendFactory):
    """
    JSON 文件存储后端。

    每个表对应一个 JSON 文件，适合小规模数据存储。
    """

    def __init__(self, data_dir: str = "./data/json"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def get_file_path(self, table_name: str) -> Path:
        """获取表对应的数据文件路径"""
        return self._data_dir / f"{table_name}.json"

    def get_lock(self) -> threading.RLock:
        """获取全局锁"""
        return self._lock

    def create_repository(self, model_class: Type[BaseModel]) -> JSONRepository:
        """创建仓库实例"""
        return JSONRepository(self, model_class)

    def create_unit_of_work(self) -> JSONUnitOfWork:
        """创建工作单元"""
        return JSONUnitOfWork(self)

    def get_backend_type(self) -> str:
        return "json"

    def clear_table(self, table_name: str) -> None:
        """清空指定表"""
        file_path = self.get_file_path(table_name)
        if file_path.exists():
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)

    def clear_all(self) -> None:
        """清空所有表"""
        for file_path in self._data_dir.glob("*.json"):
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
