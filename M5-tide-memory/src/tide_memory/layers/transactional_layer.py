"""
事务化记忆层包装器

为各记忆层（L0/L1/L2/L3）提供事务感知的包装能力，
使得跨层迁移等多步操作可以在事务保障下执行。

提供两种使用模式：

1. **TransactionalLayer 包装器类**
   将任意记忆层包装为事务感知版本，其 add/remove 操作
   可以绑定到一个外部事务上。

2. **transactional 装饰器**
   装饰函数，自动创建事务并注入到函数参数中。

设计参考 M4 db_transaction.py 的风格，
适配记忆层的异构存储特性。
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Dict, List, Optional

import structlog

from ..core.models import MemoryItem
from ..common.transaction import MemoryTransaction, TransactionState


logger = structlog.get_logger(__name__)


class TransactionalLayer:
    """
    事务化记忆层包装器

    将一个普通的记忆层对象包装为事务感知版本。
    当设置了活跃事务（active_transaction）时，
    add / remove / update 操作会登记到事务中，
    而不是立即执行。

    当没有设置活跃事务时，行为与原层完全一致（向后兼容）。

    使用方式::

        l1 = ShallowLayer(config)
        tx_layer = TransactionalLayer(l1)

        # 非事务模式（向后兼容）
        tx_layer.add(item)  # 立即执行

        # 事务模式
        with MemoryTransaction() as tx:
            tx_layer.bind_transaction(tx)
            tx_layer.add(item)      # 登记到事务
            tx_layer.remove(mid)    # 登记到事务
            # 退出 with 块时一起提交
    """

    def __init__(self, layer) -> None:
        """
        Args:
            layer: 被包装的记忆层对象（BeachLayer / ShallowLayer 等）
        """
        self._layer = layer
        self._transaction: Optional[MemoryTransaction] = None

    # ============================================================
    # 事务绑定
    # ============================================================

    def bind_transaction(self, tx: MemoryTransaction) -> None:
        """
        绑定一个活跃事务，后续 add/remove 将登记到事务中

        Args:
            tx: MemoryTransaction 实例
        """
        self._transaction = tx

    def unbind_transaction(self) -> None:
        """解绑事务，恢复立即执行模式"""
        self._transaction = None

    @property
    def has_transaction(self) -> bool:
        """是否绑定了活跃事务"""
        return (
            self._transaction is not None
            and self._transaction.state == TransactionState.PENDING
        )

    # ============================================================
    # 核心 CRUD（事务感知）
    # ============================================================

    def add(self, item: MemoryItem) -> bool:
        """
        添加记忆

        - 绑定了事务时：登记到事务，返回 True（实际执行在 commit 时）
        - 未绑定时：立即执行，返回原层的结果
        """
        if self.has_transaction:
            assert self._transaction is not None
            self._transaction.add(self._layer, item)
            return True
        return self._layer.add(item)

    def remove(self, memory_id: str) -> bool:
        """
        删除记忆

        - 绑定了事务时：登记到事务，返回 True
        - 未绑定时：立即执行
        """
        if self.has_transaction:
            assert self._transaction is not None
            self._transaction.remove(self._layer, memory_id)
            return True
        return self._layer.remove(memory_id)

    def update(self, memory_id: str, data: Dict[str, Any]) -> bool:
        """
        更新记忆字段

        - 绑定了事务时：登记到事务
        - 未绑定时：立即执行（get -> 修改 -> add）
        """
        if self.has_transaction:
            assert self._transaction is not None
            self._transaction.update(self._layer, memory_id, data)
            return True
        # 非事务模式：立即执行更新
        existing = self._layer.get(memory_id)
        if existing is None:
            return False
        for key, value in data.items():
            if hasattr(existing, key):
                setattr(existing, key, value)
            else:
                existing.metadata[key] = value
        from datetime import datetime
        existing.updated_at = datetime.now()
        return self._layer.add(existing)

    # ============================================================
    # 透传方法（非事务性，直接代理到原层）
    # ============================================================

    def get(self, memory_id: str) -> Optional[MemoryItem]:
        """获取记忆（直接透传）"""
        return self._layer.get(memory_id)

    def count(self) -> int:
        """获取数量（直接透传）"""
        return self._layer.count()

    def items(self) -> List[MemoryItem]:
        """获取所有记忆（直接透传）"""
        return self._layer.items()

    def search(self, *args, **kwargs) -> Any:
        """搜索（直接透传）"""
        return self._layer.search(*args, **kwargs)

    def batch_add(self, items: List[MemoryItem]) -> Dict:
        """批量添加（直接透传，非事务）"""
        return self._layer.batch_add(items)

    def batch_remove(self, memory_ids: List[str]) -> int:
        """批量删除（直接透传，非事务）"""
        return self._layer.batch_remove(memory_ids)

    def list_items(self, *args, **kwargs) -> Dict[str, Any]:
        """分页查询（直接透传）"""
        return self._layer.list_items(*args, **kwargs)

    def close(self) -> None:
        """关闭连接（直接透传）"""
        if hasattr(self._layer, "close"):
            self._layer.close()

    # ============================================================
    # 属性透传
    # ============================================================

    def __getattr__(self, name: str) -> Any:
        """
        动态透传未定义的属性到原层

        保证 TransactionalLayer 可以无缝替换原层对象，
        访问原层的所有属性和方法。
        """
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._layer, name)

    @property
    def layer(self) -> Any:
        """获取被包装的原层对象"""
        return self._layer

    def __repr__(self) -> str:
        return f"<TransactionalLayer wrapping={self._layer.__class__.__name__} tx_bound={self._transaction is not None}>"


# ============================================================
# 装饰器模式
# ============================================================

def transactional(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    事务装饰器

    为函数自动创建 MemoryTransaction 并注入到 kwargs 的 tx 参数中。
    函数正常返回则自动提交，抛出异常则自动回滚。

    使用方式::

        @transactional
        def promote_l0_to_l1(l0, l1, *, tx=None):
            for item in l0.items():
                if should_promote(item):
                    tx.add(l1, item)
                    tx.remove(l0, item.memory_id)

    Args:
        func: 要装饰的函数，必须接受 tx 关键字参数

    Returns:
        包装后的函数
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        tx_name = kwargs.pop("_tx_name", func.__name__)
        with MemoryTransaction(name=tx_name) as tx:
            kwargs["tx"] = tx
            result = func(*args, **kwargs)
        return result

    return wrapper


def transactional_method(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    方法级事务装饰器

    用于类的实例方法，自动创建事务并注入到 tx 参数中。
    整个方法作为一个事务：正常返回则 commit，抛出异常则 rollback。

    使用方式::

        class ConsolidationEngine:
            @transactional_method
            def promote_l0_to_l1(self, *, tx=None):
                ...

    Args:
        func: 要装饰的实例方法

    Returns:
        包装后的方法
    """
    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        tx_name = f"{self.__class__.__name__}.{func.__name__}"
        with MemoryTransaction(name=tx_name) as tx:
            kwargs["tx"] = tx
            result = func(self, *args, **kwargs)
        return result

    return wrapper


# ============================================================
# 便捷工具：多层事务迁移
# ============================================================

def migrate_with_transaction(
    source_layer,
    target_layer,
    memory_id: str,
    *,
    modify_fn: Optional[Callable[[MemoryItem], None]] = None,
) -> bool:
    """
    在事务中完成单条记忆的跨层迁移

    确保「先加后删」的原子性：目标层添加失败时，源层不删除。

    Args:
        source_layer: 源记忆层
        target_layer: 目标记忆层
        memory_id: 待迁移的记忆 ID
        modify_fn: 可选的修改函数，在添加到目标层前修改记忆

    Returns:
        True 表示迁移成功

    Raises:
        ValueError: 源层中不存在指定记忆
        RuntimeError: 迁移失败（已自动回滚）
    """
    from ..common.transaction import migrate_memory
    return migrate_memory(
        source_layer,
        target_layer,
        memory_id,
        modify_before_add=modify_fn,
    )


def batch_migrate_with_transaction(
    source_layer,
    target_layer,
    memory_ids: List[str],
    *,
    modify_fn: Optional[Callable[[MemoryItem], None]] = None,
    per_item_tx: bool = False,
) -> Dict[str, Any]:
    """
    批量迁移记忆，支持单条事务或整体事务两种模式

    Args:
        source_layer: 源记忆层
        target_layer: 目标记忆层
        memory_ids: 待迁移的记忆 ID 列表
        modify_fn: 可选的修改函数
        per_item_tx: True 表示每条记忆一个独立事务（一条失败不影响其他），
                     False 表示所有迁移在一个事务中（全部成功或全部回滚）

    Returns:
        {success_count, failed_count, failed_ids: [...]}
    """
    success_count = 0
    failed_ids: List[str] = []

    if per_item_tx:
        # 每条独立事务
        for mid in memory_ids:
            try:
                migrate_with_transaction(
                    source_layer, target_layer, mid, modify_fn=modify_fn
                )
                success_count += 1
            except Exception as e:
                logger.warning(
                    "batch_migrate.item_failed",
                    memory_id=mid,
                    error=str(e),
                )
                failed_ids.append(mid)
    else:
        # 整体一个事务
        try:
            with MemoryTransaction(name=f"batch_migrate_{len(memory_ids)}") as tx:
                for mid in memory_ids:
                    item = source_layer.get(mid)
                    if item is None:
                        raise ValueError(f"源层中不存在记忆: {mid}")
                    item_copy = item.model_copy(deep=True)
                    if modify_fn is not None:
                        modify_fn(item_copy)
                    tx.add(target_layer, item_copy)
                    tx.remove(source_layer, mid)
            success_count = len(memory_ids)
        except Exception as e:
            logger.error(
                "batch_migrate.all_failed",
                total=len(memory_ids),
                error=str(e),
            )
            failed_ids = list(memory_ids)

    return {
        "success_count": success_count,
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids,
    }


__all__ = [
    "TransactionalLayer",
    "transactional",
    "transactional_method",
    "migrate_with_transaction",
    "batch_migrate_with_transaction",
]
# vim: set et ts=4 sw=4:
