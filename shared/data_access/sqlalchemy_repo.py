"""
SQLAlchemy Repository 实现
=========================

基于 SQLAlchemy 2.0 的标准 Repository 实现，
供各模块直接继承使用，替代自建的数据访问层。

核心特性：
- 标准 CRUD（create/get_by_id/update/delete/list_all）
- 分页查询（paginate）
- 条件查询（filter_by/filter）
- 批量操作（bulk_create/bulk_update/bulk_delete）
- 软删除支持（可选，通过 mixin）
- 与 UnitOfWork 集成

使用方式：
    from shared.data_access.sqlalchemy_repo import SQLAlchemyRepository

    class UserRepository(SQLAlchemyRepository):
        model_class = UserModel  # SQLAlchemy Model

    repo = UserRepository(session)
    user = repo.create({"username": "alice"})
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar, Union

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from .base import BaseRepository, PaginationResult, QueryFilter, OrderBy, T


# ============================================================
# SQLAlchemy Repository 基类
# ============================================================

class SQLAlchemyRepository(BaseRepository[T]):
    """
    基于 SQLAlchemy 的标准 Repository 实现。

    子类只需设置 model_class 即可获得完整的 CRUD 能力。

    示例::

        class UserRepository(SQLAlchemyRepository):
            model_class = User

        repo = UserRepository(session)
        user = repo.create({"username": "alice", "email": "alice@test.com"})
        user = repo.get_by_id(1)
        users = repo.paginate(page=1, page_size=20)
    """

    #: SQLAlchemy 模型类（子类必须设置）
    model_class: Type[Any] = None  # type: ignore

    def __init__(self, session: Session):
        """
        初始化 Repository。

        Args:
            session: SQLAlchemy Session 对象
        """
        super().__init__(backend=session)
        self._session = session
        if self.model_class is None:
            raise ValueError(
                f"{type(self).__name__} must define model_class"
            )
        self._model_class = self.model_class  # type: ignore

    # ============================================================
    #  基础 CRUD
    # ============================================================

    def _do_create(self, data: Dict[str, Any]) -> T:
        instance = self._model_class(**data)
        self._session.add(instance)
        self._session.flush()
        self._session.refresh(instance)
        return instance  # type: ignore

    def _do_get_by_id(self, pk: Any) -> Optional[T]:
        pk_field = self._get_pk_field()
        result = self._session.query(self._model_class).filter(
            getattr(self._model_class, pk_field) == pk
        ).first()
        return result  # type: ignore

    def _do_update(self, pk: Any, data: Dict[str, Any]) -> Optional[T]:
        pk_field = self._get_pk_field()
        instance = self._session.query(self._model_class).filter(
            getattr(self._model_class, pk_field) == pk
        ).first()
        if not instance:
            return None

        for key, value in data.items():
            if hasattr(instance, key) and key != pk_field:
                setattr(instance, key, value)

        self._session.flush()
        self._session.refresh(instance)
        return instance  # type: ignore

    def _do_delete(self, pk: Any) -> bool:
        pk_field = self._get_pk_field()
        result = self._session.query(self._model_class).filter(
            getattr(self._model_class, pk_field) == pk
        ).delete()
        self._session.flush()
        return result > 0

    # ============================================================
    #  查询
    # ============================================================

    def _execute_query(
        self,
        filters: List[QueryFilter],
        order_by: List[OrderBy],
        limit: Optional[int],
        offset: Optional[int],
    ) -> List[T]:
        query = self._session.query(self._model_class)
        query = self._apply_filters(query, filters)
        query = self._apply_order_by(query, order_by)

        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)

        return query.all()  # type: ignore

    def _execute_paginated_query(
        self,
        filters: List[QueryFilter],
        order_by: List[OrderBy],
        page: int,
        page_size: int,
    ) -> PaginationResult[T]:
        total = self._count_query(filters)
        items = self._execute_query(
            filters=filters,
            order_by=order_by,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return PaginationResult(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def _count_query(self, filters: List[QueryFilter]) -> int:
        pk_field = self._get_pk_field()
        query = self._session.query(
            func.count(getattr(self._model_class, pk_field))
        )
        query = self._apply_filters(query, filters)
        result = query.scalar()
        return int(result or 0)

    # ============================================================
    #  便捷方法（提供更 SQLAlchemy 风格的 API）
    # ============================================================

    def filter_by(self, **kwargs: Any) -> List[T]:
        """
        按字段值过滤（精确匹配）。

        Args:
            **kwargs: 字段名=值

        Returns:
            匹配的记录列表
        """
        return self.query().filter(**kwargs).all()

    def get_by_field(self, field_name: str, value: Any) -> Optional[T]:
        """
        按字段值获取单条记录。

        Args:
            field_name: 字段名
            value: 字段值

        Returns:
            匹配的记录，不存在返回 None
        """
        return self.query().add_filter(field_name, "eq", value).first()

    def paginate(
        self,
        page: int = 1,
        page_size: int = 20,
        order_by: Optional[str] = None,
        ascending: bool = True,
        **filters: Any,
    ) -> PaginationResult[T]:
        """
        分页查询（便捷方法）。

        Args:
            page: 页码（从 1 开始）
            page_size: 每页大小
            order_by: 排序字段
            ascending: 是否升序
            **filters: 过滤条件

        Returns:
            分页结果
        """
        query = self.query().filter(**filters)
        if order_by:
            query = query.order_by(order_by, ascending=ascending)
        return query.paginate(page=page, page_size=page_size)

    # ============================================================
    #  批量操作（优化为 SQLAlchemy 批量操作）
    # ============================================================

    def bulk_create(self, items: List[Union[Dict[str, Any], T]]) -> List[T]:
        """
        批量创建记录。

        Args:
            items: 数据字典或模型实例列表

        Returns:
            创建后的模型实例列表
        """
        instances = []
        for item in items:
            if isinstance(item, dict):
                instances.append(self._model_class(**item))
            else:
                instances.append(item)

        self._session.bulk_save_objects(instances)
        self._session.flush()
        return instances  # type: ignore

    def bulk_update(self, items: List[Tuple[Any, Dict[str, Any]]]) -> int:
        """
        批量更新记录。

        Args:
            items: [(pk, data_dict), ...] 列表

        Returns:
            更新的记录数
        """
        pk_field = self._get_pk_field()
        count = 0
        for pk, data in items:
            result = self._session.query(self._model_class).filter(
                getattr(self._model_class, pk_field) == pk
            ).update(data)
            count += result
        self._session.flush()
        return count

    def bulk_delete(self, pks: List[Any]) -> int:
        """
        批量删除记录。

        Args:
            pks: 主键值列表

        Returns:
            删除的记录数
        """
        if not pks:
            return 0
        pk_field = self._get_pk_field()
        result = self._session.query(self._model_class).filter(
            getattr(self._model_class, pk_field).in_(pks)
        ).delete(synchronize_session=False)
        self._session.flush()
        return result

    # ============================================================
    #  内部工具方法
    # ============================================================

    def _get_pk_field(self) -> str:
        """获取主键字段名"""
        if hasattr(self._model_class, '__table__'):
            pk_columns = list(self._model_class.__table__.primary_key.columns)
            if pk_columns:
                return pk_columns[0].name
        return "id"

    def _apply_filters(self, query: Any, filters: List[QueryFilter]) -> Any:
        """应用过滤条件到查询"""
        if not filters:
            return query

        conditions = []
        for f in filters:
            column = getattr(self._model_class, f.field, None)
            if column is None:
                continue

            if f.operator == "eq":
                conditions.append(column == f.value)
            elif f.operator == "ne":
                conditions.append(column != f.value)
            elif f.operator == "gt":
                conditions.append(column > f.value)
            elif f.operator == "gte":
                conditions.append(column >= f.value)
            elif f.operator == "lt":
                conditions.append(column < f.value)
            elif f.operator == "lte":
                conditions.append(column <= f.value)
            elif f.operator == "in":
                conditions.append(column.in_(f.value or []))
            elif f.operator == "not_in":
                conditions.append(column.notin_(f.value or []))
            elif f.operator == "like":
                conditions.append(column.like(f.value))
            elif f.operator == "contains":
                conditions.append(column.like(f"%{f.value}%"))
            elif f.operator == "between":
                if isinstance(f.value, (list, tuple)) and len(f.value) == 2:
                    conditions.append(column.between(f.value[0], f.value[1]))
            elif f.operator == "is_null":
                conditions.append(column.is_(None))
            elif f.operator == "is_not_null":
                conditions.append(column.isnot(None))
            else:
                conditions.append(column == f.value)

        if conditions:
            query = query.filter(and_(*conditions))

        return query

    def _apply_order_by(self, query: Any, order_by: List[OrderBy]) -> Any:
        """应用排序到查询"""
        if not order_by:
            return query

        for ob in order_by:
            column = getattr(self._model_class, ob.field, None)
            if column is not None:
                if ob.ascending:
                    query = query.order_by(column.asc())
                else:
                    query = query.order_by(column.desc())

        return query


# ============================================================
# SQLAlchemy Unit of Work
# ============================================================

class SQLAlchemyUnitOfWork:
    """
    基于 SQLAlchemy 的工作单元实现。

    管理事务边界，协调多个 Repository 的操作。

    使用方式::

        uow = SQLAlchemyUnitOfWork(session_factory)
        with uow as session:
            user_repo = UserRepository(session)
            profile_repo = ProfileRepository(session)
            user = user_repo.create(...)
            profile_repo.create(...)
        # 自动提交，异常自动回滚
    """

    def __init__(self, session_factory: Any):
        """
        初始化工作单元。

        Args:
            session_factory: SQLAlchemy sessionmaker 或可调用的 session 工厂
        """
        self._session_factory = session_factory
        self._session: Optional[Session] = None
        self._active = False
        self._repositories: Dict[str, SQLAlchemyRepository] = {}

    def __enter__(self) -> Session:
        self.begin()
        assert self._session is not None
        return self._session

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self.rollback()
            return False
        self.commit()
        return True

    def begin(self) -> None:
        """开始事务"""
        if self._active:
            return
        self._session = self._session_factory()
        self._active = True

    def commit(self) -> None:
        """提交事务"""
        if not self._active or not self._session:
            return
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        finally:
            self._session.close()
            self._session = None
            self._active = False
            self._repositories.clear()

    def rollback(self) -> None:
        """回滚事务"""
        if not self._active or not self._session:
            return
        self._session.rollback()
        self._session.close()
        self._session = None
        self._active = False
        self._repositories.clear()

    @property
    def is_active(self) -> bool:
        """事务是否活跃"""
        return self._active

    @property
    def session(self) -> Optional[Session]:
        """获取当前 session"""
        return self._session

    def get_repository(self, repo_class: Type[SQLAlchemyRepository]) -> SQLAlchemyRepository:
        """
        获取仓库实例（同一个 UoW 内复用）。

        Args:
            repo_class: Repository 类

        Returns:
            Repository 实例
        """
        if not self._session:
            raise RuntimeError("UnitOfWork is not active. Call begin() first.")

        key = repo_class.__name__
        if key not in self._repositories:
            self._repositories[key] = repo_class(self._session)
        return self._repositories[key]


# ============================================================
# 导出
# ============================================================

__all__ = [
    "SQLAlchemyRepository",
    "SQLAlchemyUnitOfWork",
]
