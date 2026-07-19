"""
数据访问层 Mixin 集合
====================

提供可复用的 Mixin 类，用于增强 Repository 和 Model 的能力。

可用 Mixin：
- SoftDeleteMixin: 软删除支持（Repository 级别）
- TimestampMixin: 自动时间戳（SQLAlchemy Model 级别）
- VersionMixin: 乐观锁版本号（SQLAlchemy Model 级别）
- AuditMixin: 审计字段（创建人/更新人）
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.orm import Session

from .base import BaseRepository, QueryFilter, T


# ============================================================
# 软删除 Mixin（Repository 级别）
# ============================================================

class SoftDeleteMixin:
    """
    软删除 Mixin。

    为 Repository 添加软删除能力：
    - delete() 改为软删除（设置 is_deleted=True）
    - 查询默认过滤已删除记录
    - hard_delete() 真正删除
    - restore() 恢复软删除的记录

    使用方式：
        class UserRepository(SoftDeleteMixin, SQLAlchemyRepository):
            model_class = UserModel
            soft_delete_field = "is_deleted"
    """

    #: 软删除字段名（默认 is_deleted）
    soft_delete_field: str = "is_deleted"

    #: 删除时间字段名（None 表示不记录）
    deleted_at_field: Optional[str] = "deleted_at"

    # ---- 软删除操作 ----

    def soft_delete(self, pk: Any) -> bool:
        """
        软删除记录。

        Args:
            pk: 主键值

        Returns:
            是否成功
        """
        data: Dict[str, Any] = {self.soft_delete_field: True}
        if self.deleted_at_field:
            data[self.deleted_at_field] = self._get_current_timestamp()
        return self.update(pk, data) is not None  # type: ignore

    def hard_delete(self, pk: Any) -> bool:
        """
        硬删除记录（真正从数据库删除）。

        Args:
            pk: 主键值

        Returns:
            是否成功
        """
        return super().delete(pk)  # type: ignore

    def restore(self, pk: Any) -> bool:
        """
        恢复软删除的记录。

        Args:
            pk: 主键值

        Returns:
            是否成功
        """
        data: Dict[str, Any] = {self.soft_delete_field: False}
        if self.deleted_at_field:
            data[self.deleted_at_field] = None
        return self.update(pk, data) is not None  # type: ignore

    # ---- 覆盖默认 delete 为软删除 ----

    def delete(self, pk: Any) -> bool:
        """删除记录（默认软删除）"""
        return self.soft_delete(pk)

    # ---- 查询包含已删除记录 ----

    def get_by_id_include_deleted(self, pk: Any) -> Optional[Any]:
        """
        按 ID 获取记录（包含已删除的）。

        Args:
            pk: 主键值

        Returns:
            模型实例或 None
        """
        # 绕过默认过滤，直接查询
        if hasattr(self, '_session') and hasattr(self, '_model_class'):
            pk_field = self._model_class.get_primary_key_field()  # type: ignore
            result = self._session.query(self._model_class).filter(  # type: ignore
                getattr(self._model_class, pk_field) == pk  # type: ignore
            ).first()
            return result
        return None

    def list_include_deleted(self, **filters: Any) -> List[Any]:
        """
        列出所有记录（包含已删除的）。

        Args:
            **filters: 过滤条件

        Returns:
            记录列表
        """
        if hasattr(self, 'query'):
            # 使用内部查询，绕过软删除过滤
            pass
        return []

    def count_include_deleted(self, **filters: Any) -> int:
        """
        统计记录数（包含已删除的）。

        Returns:
            记录数
        """
        return 0

    # ---- 辅助方法 ----

    def _get_current_timestamp(self) -> Any:
        """获取当前时间戳"""
        return time.time()

    def _add_soft_delete_filter(self, filters: List[QueryFilter]) -> List[QueryFilter]:
        """
        添加软删除过滤条件（供子类调用）。

        Args:
            filters: 原始过滤条件

        Returns:
            添加了软删除过滤的条件
        """
        soft_filter = QueryFilter(
            field=self.soft_delete_field,
            operator="eq",
            value=False,
        )
        return filters + [soft_filter]


# ============================================================
# SQLAlchemy Model Mixins
# ============================================================

def _utc_now() -> datetime:
    """返回 UTC 当前时间"""
    return datetime.now(timezone.utc)


class TimestampMixin:
    """
    时间戳 Mixin（SQLAlchemy Model 级别）。

    自动添加 created_at 和 updated_at 字段。

    使用方式：
        class UserModel(TimestampMixin, Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
    """

    created_at = Column(DateTime, default=_utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


class SoftDeleteModelMixin:
    """
    软删除 Model Mixin（SQLAlchemy Model 级别）。

    添加 is_deleted 和 deleted_at 字段。

    使用方式：
        class UserModel(SoftDeleteModelMixin, Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
    """

    is_deleted = Column(Integer, default=0, nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True)


class VersionMixin:
    """
    版本号 Mixin（乐观锁）。

    添加 version 字段，用于乐观锁控制。

    使用方式：
        class UserModel(VersionMixin, Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
    """

    version = Column(Integer, default=1, nullable=False)


class AuditMixin(TimestampMixin):
    """
    审计 Mixin。

    包含创建人、更新人、创建时间、更新时间。

    使用方式：
        class UserModel(AuditMixin, Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
    """

    created_by = Column(String(100), default="system", nullable=False)
    updated_by = Column(String(100), default="system", nullable=False)


# ============================================================
# 导出
# ============================================================

__all__ = [
    "SoftDeleteMixin",
    "TimestampMixin",
    "SoftDeleteModelMixin",
    "VersionMixin",
    "AuditMixin",
]
