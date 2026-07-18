"""
数据访问抽象层（Data Access Abstraction）
======================================

提供统一的数据访问抽象，与具体存储后端解耦。

核心组件：
- BaseModel: 数据模型基类
- BaseRepository: 仓库基类（统一 CRUD 接口）
- UnitOfWork: 工作单元模式（事务管理）
- QueryBuilder: 查询构造器抽象
- QueryFilter: 查询过滤器
- PaginationResult: 分页结果
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    Iterator,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)
from contextlib import contextmanager


# ============================================================
# 类型变量
# ============================================================

T = TypeVar("T", bound="BaseModel")


# ============================================================
# 数据模型基类
# ============================================================

class BaseModel:
    """
    数据模型基类。

    所有统一数据层的数据模型都应继承此类。
    提供统一的主键、时间戳、版本号字段。

    子类通过类属性定义字段 schema：
        class UserModel(BaseModel):
            __table_name__ = "users"
            __fields__ = {
                "id": {"type": int, "primary_key": True, "auto_increment": True},
                "username": {"type": str, "required": True, "unique": True},
                "email": {"type": str, "required": False},
            }
    """

    #: 表/集合名称（子类必须设置）
    __table_name__: str = ""

    #: 字段定义 schema
    __fields__: Dict[str, Dict[str, Any]] = {}

    def __init__(self, **kwargs: Any):
        self._data: Dict[str, Any] = {}
        # 设置默认值
        for field_name, field_def in self.__fields__.items():
            default = field_def.get("default", None)
            if callable(default):
                self._data[field_name] = default()
            else:
                self._data[field_name] = default
        # 覆盖传入值
        for key, value in kwargs.items():
            if key in self.__fields__:
                self._data[key] = value

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if "_data" in self.__dict__ and name in self._data:
            return self._data[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_") or name in ("__fields__", "__table_name__"):
            super().__setattr__(name, value)
        elif hasattr(self, "__fields__") and name in self.__fields__:
            self._data[name] = value
        else:
            super().__setattr__(name, value)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return dict(self._data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseModel":
        """从字典创建实例"""
        return cls(**data)

    def get_primary_key(self) -> Optional[Any]:
        """获取主键值"""
        for field_name, field_def in self.__fields__.items():
            if field_def.get("primary_key"):
                return self._data.get(field_name)
        return None

    def set_primary_key(self, value: Any) -> None:
        """设置主键值"""
        for field_name, field_def in self.__fields__.items():
            if field_def.get("primary_key"):
                self._data[field_name] = value
                return

    @classmethod
    def get_primary_key_field(cls) -> Optional[str]:
        """获取主键字段名"""
        for field_name, field_def in cls.__fields__.items():
            if field_def.get("primary_key"):
                return field_name
        return None

    @classmethod
    def get_table_name(cls) -> str:
        """获取表/集合名称"""
        return cls.__table_name__

    def __repr__(self) -> str:
        pk = self.get_primary_key()
        return f"<{type(self).__name__} pk={pk}>"


# ============================================================
# 查询过滤器
# ============================================================

@dataclass
class QueryFilter:
    """
    查询过滤器。

    支持的操作符：
    - eq: 等于 (=)
    - ne: 不等于 (!=)
    - gt: 大于 (>)
    - gte: 大于等于 (>=)
    - lt: 小于 (<)
    - lte: 小于等于 (<=)
    - in: 在列表中 (IN)
    - not_in: 不在列表中 (NOT IN)
    - like: 模糊匹配 (LIKE)
    - contains: 包含 (字符串包含)
    - between: 在范围内 (BETWEEN)
    - is_null: 为空 (IS NULL)
    - is_not_null: 不为空 (IS NOT NULL)
    """

    field: str
    operator: str = "eq"
    value: Any = None

    def matches(self, data: Dict[str, Any]) -> bool:
        """检查数据是否匹配过滤条件（内存后端用）"""
        field_value = data.get(self.field)
        op = self.operator

        if op == "eq":
            return field_value == self.value
        elif op == "ne":
            return field_value != self.value
        elif op == "gt":
            if field_value is None or self.value is None:
                return False
            return field_value > self.value
        elif op == "gte":
            if field_value is None or self.value is None:
                return False
            return field_value >= self.value
        elif op == "lt":
            if field_value is None or self.value is None:
                return False
            return field_value < self.value
        elif op == "lte":
            if field_value is None or self.value is None:
                return False
            return field_value <= self.value
        elif op == "in":
            return field_value in (self.value or [])
        elif op == "not_in":
            return field_value not in (self.value or [])
        elif op == "like":
            if field_value is None or self.value is None:
                return False
            pattern = str(self.value).replace("%", ".*").replace("_", ".")
            import re
            return bool(re.match(f"^{pattern}$", str(field_value)))
        elif op == "contains":
            if field_value is None or self.value is None:
                return False
            return str(self.value) in str(field_value)
        elif op == "between":
            if field_value is None or not isinstance(self.value, (list, tuple)) or len(self.value) != 2:
                return False
            return self.value[0] <= field_value <= self.value[1]
        elif op == "is_null":
            return field_value is None
        elif op == "is_not_null":
            return field_value is not None
        return False


# ============================================================
# 排序定义
# ============================================================

@dataclass
class OrderBy:
    """排序定义"""
    field: str
    ascending: bool = True


# ============================================================
# 分页结果
# ============================================================

@dataclass
class PaginationResult(Generic[T]):
    """
    分页查询结果。

    Attributes:
        items: 当前页数据
        total: 总记录数
        page: 当前页码（从1开始）
        page_size: 每页大小
        total_pages: 总页数
    """

    items: List[T]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        """总页数"""
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    def to_dict(self, item_transform: Optional[Callable[[T], Dict[str, Any]]] = None) -> Dict[str, Any]:
        """转换为字典"""
        if item_transform:
            items = [item_transform(item) for item in self.items]
        else:
            items = [item.to_dict() if hasattr(item, "to_dict") else item for item in self.items]
        return {
            "items": items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
        }


# ============================================================
# 查询构造器
# ============================================================

class QueryBuilder(Generic[T]):
    """
    查询构造器。

    提供流式 API 构建查询：
        query = QueryBuilder(UserRepository)
            .filter(username="test")
            .filter(age__gt=18)
            .order_by("created_at", ascending=False)
            .paginate(page=1, page_size=20)

    注意：这是一个查询描述对象，实际执行由后端完成。
    """

    def __init__(self, repository: "BaseRepository"):
        self._repository = repository
        self._filters: List[QueryFilter] = []
        self._order_by: List[OrderBy] = []
        self._limit: Optional[int] = None
        self._offset: Optional[int] = None

    def filter(self, **kwargs: Any) -> "QueryBuilder[T]":
        """
        添加过滤条件。

        支持双下划线操作符：
            filter(username="test")       -> eq
            filter(age__gt=18)            -> gt
            filter(name__contains="abc")  -> contains
        """
        for key, value in kwargs.items():
            if "__" in key:
                field, op = key.rsplit("__", 1)
            else:
                field, op = key, "eq"
            self._filters.append(QueryFilter(field=field, operator=op, value=value))
        return self

    def add_filter(self, field: str, operator: str, value: Any = None) -> "QueryBuilder[T]":
        """显式添加过滤条件"""
        self._filters.append(QueryFilter(field=field, operator=operator, value=value))
        return self

    def order_by(self, field: str, ascending: bool = True) -> "QueryBuilder[T]":
        """添加排序"""
        self._order_by.append(OrderBy(field=field, ascending=ascending))
        return self

    def limit(self, n: int) -> "QueryBuilder[T]":
        """设置限制条数"""
        self._limit = n
        return self

    def offset(self, n: int) -> "QueryBuilder[T]":
        """设置偏移量"""
        self._offset = n
        return self

    def paginate(self, page: int = 1, page_size: int = 20) -> PaginationResult[T]:
        """执行分页查询"""
        self._limit = page_size
        self._offset = (page - 1) * page_size
        return self._repository._execute_paginated_query(
            filters=self._filters,
            order_by=self._order_by,
            page=page,
            page_size=page_size,
        )

    def all(self) -> List[T]:
        """执行查询，返回所有结果"""
        return self._repository._execute_query(
            filters=self._filters,
            order_by=self._order_by,
            limit=self._limit,
            offset=self._offset,
        )

    def first(self) -> Optional[T]:
        """执行查询，返回第一条结果"""
        self._limit = 1
        results = self.all()
        return results[0] if results else None

    def count(self) -> int:
        """统计符合条件的记录数"""
        return self._repository._count_query(filters=self._filters)

    def exists(self) -> bool:
        """检查是否存在符合条件的记录"""
        return self.count() > 0


# ============================================================
# 仓库基类
# ============================================================

class BaseRepository(ABC, Generic[T]):
    """
    仓库基类（Repository Pattern）。

    定义统一的 CRUD 接口，所有具体仓库实现都应继承此类。
    后端无关，具体实现由各存储后端提供。

    子类需要实现：
    - _model_class: 模型类
    - _do_create: 创建记录
    - _do_get_by_id: 按主键获取
    - _do_update: 更新记录
    - _do_delete: 删除记录
    - _execute_query: 执行查询
    - _execute_paginated_query: 执行分页查询
    - _count_query: 统计数量
    """

    #: 模型类（子类必须设置）
    _model_class: Type[BaseModel] = BaseModel

    def __init__(self, backend: Any = None):
        """
        初始化仓库。

        Args:
            backend: 存储后端实例
        """
        self._backend = backend

    @property
    def model_class(self) -> Type[T]:
        """获取模型类"""
        return self._model_class  # type: ignore

    @property
    def table_name(self) -> str:
        """获取表/集合名称"""
        return self._model_class.__table_name__

    # ---- 基础 CRUD ----

    def create(self, data: Union[Dict[str, Any], T]) -> T:
        """
        创建一条记录。

        Args:
            data: 数据字典或模型实例

        Returns:
            创建后的模型实例（含主键等生成字段）
        """
        if isinstance(data, BaseModel):
            data = data.to_dict()
        return self._do_create(data)

    def get_by_id(self, pk: Any) -> Optional[T]:
        """
        按主键获取记录。

        Args:
            pk: 主键值

        Returns:
            模型实例，不存在返回 None
        """
        return self._do_get_by_id(pk)

    def update(self, pk: Any, data: Dict[str, Any]) -> Optional[T]:
        """
        更新记录。

        Args:
            pk: 主键值
            data: 要更新的字段

        Returns:
            更新后的模型实例，不存在返回 None
        """
        return self._do_update(pk, data)

    def delete(self, pk: Any) -> bool:
        """
        删除记录。

        Args:
            pk: 主键值

        Returns:
            是否删除成功
        """
        return self._do_delete(pk)

    def list_all(self) -> List[T]:
        """列出所有记录"""
        return self._execute_query(filters=[], order_by=[], limit=None, offset=None)

    # ---- 查询构造器 ----

    def query(self) -> QueryBuilder[T]:
        """创建查询构造器"""
        return QueryBuilder[T](self)

    def find_one(self, **filters: Any) -> Optional[T]:
        """按条件查找单条记录"""
        return self.query().filter(**filters).first()

    def find_many(self, **filters: Any) -> List[T]:
        """按条件查找多条记录"""
        return self.query().filter(**filters).all()

    def count(self, **filters: Any) -> int:
        """统计记录数"""
        return self.query().filter(**filters).count()

    def exists(self, **filters: Any) -> bool:
        """检查记录是否存在"""
        return self.count(**filters) > 0

    # ---- 批量操作 ----

    def bulk_create(self, items: List[Union[Dict[str, Any], T]]) -> List[T]:
        """
        批量创建记录。

        默认实现是循环调用 create，后端可以优化为批量插入。
        """
        return [self.create(item) for item in items]

    def bulk_update(self, items: List[Tuple[Any, Dict[str, Any]]]) -> int:
        """
        批量更新记录。

        Args:
            items: [(pk, data), ...] 列表

        Returns:
            更新的记录数
        """
        count = 0
        for pk, data in items:
            if self.update(pk, data) is not None:
                count += 1
        return count

    def bulk_delete(self, pks: List[Any]) -> int:
        """
        批量删除记录。

        Returns:
            删除的记录数
        """
        count = 0
        for pk in pks:
            if self.delete(pk):
                count += 1
        return count

    # ---- 抽象方法（后端必须实现） ----

    @abstractmethod
    def _do_create(self, data: Dict[str, Any]) -> T:
        ...

    @abstractmethod
    def _do_get_by_id(self, pk: Any) -> Optional[T]:
        ...

    @abstractmethod
    def _do_update(self, pk: Any, data: Dict[str, Any]) -> Optional[T]:
        ...

    @abstractmethod
    def _do_delete(self, pk: Any) -> bool:
        ...

    @abstractmethod
    def _execute_query(
        self,
        filters: List[QueryFilter],
        order_by: List[OrderBy],
        limit: Optional[int],
        offset: Optional[int],
    ) -> List[T]:
        ...

    @abstractmethod
    def _execute_paginated_query(
        self,
        filters: List[QueryFilter],
        order_by: List[OrderBy],
        page: int,
        page_size: int,
    ) -> PaginationResult[T]:
        ...

    @abstractmethod
    def _count_query(self, filters: List[QueryFilter]) -> int:
        ...


# ============================================================
# 工作单元（Unit of Work）
# ============================================================

class UnitOfWork(ABC):
    """
    工作单元模式。

    管理事务边界，确保一组操作要么全部成功，要么全部回滚。

    使用方式：
        uow = UnitOfWork(backend)
        with uow:
            user_repo = uow.get_repository(UserRepository)
            user_repo.create(...)
            profile_repo = uow.get_repository(ProfileRepository)
            profile_repo.create(...)
        # 自动提交，异常自动回滚
    """

    def __init__(self, backend: Any = None):
        self._backend = backend
        self._repositories: Dict[str, BaseRepository] = {}
        self._active = False

    def __enter__(self) -> "UnitOfWork":
        self.begin()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self.rollback()
            return False
        self.commit()
        return True

    @abstractmethod
    def begin(self) -> None:
        """开始事务"""
        ...

    @abstractmethod
    def commit(self) -> None:
        """提交事务"""
        ...

    @abstractmethod
    def rollback(self) -> None:
        """回滚事务"""
        ...

    @property
    def is_active(self) -> bool:
        """事务是否活跃"""
        return self._active

    def get_repository(self, repo_class: Type[BaseRepository]) -> BaseRepository:
        """
        获取仓库实例（同一个 UoW 内复用）。

        Args:
            repo_class: 仓库类

        Returns:
            仓库实例
        """
        key = repo_class.__name__
        if key not in self._repositories:
            self._repositories[key] = repo_class(backend=self._backend)
        return self._repositories[key]


# ============================================================
# 后端工厂抽象
# ============================================================

class BackendFactory(ABC):
    """
    后端工厂抽象。

    负责创建特定后端的仓库和工作单元。
    """

    @abstractmethod
    def create_repository(self, model_class: Type[BaseModel]) -> BaseRepository:
        """创建指定模型的仓库"""
        ...

    @abstractmethod
    def create_unit_of_work(self) -> UnitOfWork:
        """创建工作单元"""
        ...

    @abstractmethod
    def get_backend_type(self) -> str:
        """获取后端类型名称"""
        ...
