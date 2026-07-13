"""
记忆事务管理模块

为潮汐分层记忆系统提供跨层事务保证，确保记忆在层间迁移时的原子性：
- 所有操作要么全部成功（commit），要么全部回滚（rollback）
- 支持 add / remove / update 三类操作
- 支持上下文管理器 with 语法
- 记录完整的操作审计日志

设计参考 M4 db_transaction.py 的风格，但针对记忆层的异构存储
（内存 / SQLite / 加密文件）做了适配，采用补偿式事务（补偿回滚）
而非数据库原生事务。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import structlog

from ..core.models import MemoryItem


logger = structlog.get_logger(__name__)


class TransactionOperation(str, Enum):
    """事务操作类型"""
    ADD = "add"
    REMOVE = "remove"
    UPDATE = "update"


class TransactionState(str, Enum):
    """事务状态"""
    PENDING = "pending"      # 初始化完成，可登记操作
    ACTIVE = "active"        # 正在执行操作
    COMMITTED = "committed"  # 已提交
    ROLLED_BACK = "rolled_back"  # 已回滚
    FAILED = "failed"        # 提交失败（可回滚）


@dataclass
class TransactionLogEntry:
    """事务操作日志条目"""
    op_id: str
    operation: TransactionOperation
    layer_name: str
    memory_id: str
    timestamp: datetime
    before_state: Optional[Dict[str, Any]] = None   # 操作前状态（用于回滚）
    after_state: Optional[Dict[str, Any]] = None    # 操作后状态
    success: bool = False
    error: Optional[str] = None


@dataclass
class PendingOperation:
    """待执行的事务操作"""
    operation: TransactionOperation
    layer: Any           # 记忆层对象（BeachLayer / ShallowLayer 等）
    layer_name: str      # 层名称（用于日志）
    memory: Optional[MemoryItem] = None   # ADD 操作使用
    memory_id: Optional[str] = None       # REMOVE / UPDATE 操作使用
    update_data: Optional[Dict[str, Any]] = None  # UPDATE 操作使用
    # 回滚所需的快照
    rollback_snapshot: Optional[Dict[str, Any]] = None


class MemoryTransaction:
    """
    记忆事务管理器

    采用补偿式事务（Saga 模式简化版）：
    1. 登记所有操作（add / remove / update）
    2. commit 时按顺序执行，每步记录回滚快照
    3. 任一步失败，按逆序执行补偿操作回滚

    使用方式::

        with MemoryTransaction() as tx:
            tx.add(l1_layer, memory_item)
            tx.remove(l0_layer, memory_id)
            # 退出 with 块时自动 commit
            # 发生异常时自动 rollback

    或者手动控制::

        tx = MemoryTransaction()
        tx.add(l1_layer, item)
        tx.remove(l0_layer, item.memory_id)
        try:
            tx.commit()
        except Exception:
            tx.rollback()
    """

    def __init__(self, name: str = ""):
        self._tx_id: str = f"tx_{uuid.uuid4().hex[:16]}"
        self._name: str = name or self._tx_id
        self._state: TransactionState = TransactionState.PENDING
        self._pending_ops: List[PendingOperation] = []
        self._executed_ops: List[PendingOperation] = []
        self._audit_log: List[TransactionLogEntry] = []

    # ============================================================
    # 操作登记
    # ============================================================

    def add(self, layer, memory: MemoryItem) -> None:
        """
        登记 add 操作：将记忆添加到指定层

        Args:
            layer: 目标记忆层对象
            memory: 待添加的记忆项

        Raises:
            RuntimeError: 事务已提交或已回滚
        """
        self._ensure_pending()
        self._pending_ops.append(PendingOperation(
            operation=TransactionOperation.ADD,
            layer=layer,
            layer_name=self._get_layer_name(layer),
            memory=memory.model_copy(deep=True),
            memory_id=memory.memory_id,
        ))
        logger.debug(
            "transaction.register_add",
            tx_id=self._tx_id,
            layer=self._get_layer_name(layer),
            memory_id=memory.memory_id,
        )

    def remove(self, layer, memory_id: str) -> None:
        """
        登记 remove 操作：从指定层删除记忆

        Args:
            layer: 目标记忆层对象
            memory_id: 待删除的记忆 ID

        Raises:
            RuntimeError: 事务已提交或已回滚
        """
        self._ensure_pending()
        self._pending_ops.append(PendingOperation(
            operation=TransactionOperation.REMOVE,
            layer=layer,
            layer_name=self._get_layer_name(layer),
            memory_id=memory_id,
        ))
        logger.debug(
            "transaction.register_remove",
            tx_id=self._tx_id,
            layer=self._get_layer_name(layer),
            memory_id=memory_id,
        )

    def update(self, layer, memory_id: str, data: Dict[str, Any]) -> None:
        """
        登记 update 操作：更新指定层的记忆字段

        Args:
            layer: 目标记忆层对象
            memory_id: 待更新的记忆 ID
            data: 待更新的字段字典

        Raises:
            RuntimeError: 事务已提交或已回滚
        """
        self._ensure_pending()
        self._pending_ops.append(PendingOperation(
            operation=TransactionOperation.UPDATE,
            layer=layer,
            layer_name=self._get_layer_name(layer),
            memory_id=memory_id,
            update_data=dict(data),
        ))
        logger.debug(
            "transaction.register_update",
            tx_id=self._tx_id,
            layer=self._get_layer_name(layer),
            memory_id=memory_id,
            fields=list(data.keys()),
        )

    # ============================================================
    # 核心事务方法
    # ============================================================

    def commit(self) -> bool:
        """
        提交事务：按顺序执行所有登记的操作

        任一步失败则自动回滚所有已执行的操作，并抛出异常。

        Returns:
            True 表示全部成功

        Raises:
            RuntimeError: 事务状态不允许提交
            Exception: 操作执行失败时抛出（已自动回滚）
        """
        self._ensure_pending()
        self._state = TransactionState.ACTIVE

        logger.info(
            "transaction.commit_start",
            tx_id=self._tx_id,
            tx_name=self._name,
            op_count=len(self._pending_ops),
        )

        for op in self._pending_ops:
            op_id = f"op_{uuid.uuid4().hex[:12]}"
            try:
                # 执行前快照（用于回滚）
                self._snapshot_before(op)

                # 执行操作
                self._execute_op(op)

                # 记录成功
                self._log_entry(TransactionLogEntry(
                    op_id=op_id,
                    operation=op.operation,
                    layer_name=op.layer_name,
                    memory_id=op.memory_id or "",
                    timestamp=datetime.now(),
                    before_state=op.rollback_snapshot,
                    success=True,
                ))

                self._executed_ops.append(op)

            except Exception as e:
                # 记录失败
                self._log_entry(TransactionLogEntry(
                    op_id=op_id,
                    operation=op.operation,
                    layer_name=op.layer_name,
                    memory_id=op.memory_id or "",
                    timestamp=datetime.now(),
                    before_state=op.rollback_snapshot,
                    success=False,
                    error=str(e),
                ))

                logger.error(
                    "transaction.commit_failed",
                    tx_id=self._tx_id,
                    failed_op=op.operation.value,
                    layer=op.layer_name,
                    memory_id=op.memory_id,
                    error=str(e),
                )

                self._state = TransactionState.FAILED
                # 自动回滚
                self._do_rollback()
                raise

        self._state = TransactionState.COMMITTED
        logger.info(
            "transaction.commit_success",
            tx_id=self._tx_id,
            tx_name=self._name,
            op_count=len(self._executed_ops),
        )
        return True

    def rollback(self) -> bool:
        """
        手动回滚事务：逆序撤销所有已执行的操作

        Returns:
            True 表示回滚成功

        Raises:
            RuntimeError: 事务状态不允许回滚
        """
        if self._state == TransactionState.ROLLED_BACK:
            return True
        if self._state not in (
            TransactionState.ACTIVE,
            TransactionState.FAILED,
            TransactionState.PENDING,
        ):
            raise RuntimeError(
                f"事务当前状态 {self._state.value} 不允许回滚"
            )

        return self._do_rollback()

    def _do_rollback(self) -> bool:
        """
        执行实际回滚逻辑：按逆序补偿已执行的操作
        """
        if not self._executed_ops:
            self._state = TransactionState.ROLLED_BACK
            return True

        logger.warning(
            "transaction.rollback_start",
            tx_id=self._tx_id,
            tx_name=self._name,
            rollback_count=len(self._executed_ops),
        )

        rollback_errors = []
        # 逆序回滚
        for op in reversed(self._executed_ops):
            try:
                self._compensate_op(op)
                logger.debug(
                    "transaction.rollback_op",
                    tx_id=self._tx_id,
                    operation=op.operation.value,
                    layer=op.layer_name,
                    memory_id=op.memory_id,
                )
            except Exception as e:
                rollback_errors.append({
                    "operation": op.operation.value,
                    "layer": op.layer_name,
                    "memory_id": op.memory_id,
                    "error": str(e),
                })
                logger.error(
                    "transaction.rollback_op_failed",
                    tx_id=self._tx_id,
                    operation=op.operation.value,
                    layer=op.layer_name,
                    memory_id=op.memory_id,
                    error=str(e),
                )

        self._state = TransactionState.ROLLED_BACK

        if rollback_errors:
            logger.critical(
                "transaction.rollback_partial",
                tx_id=self._tx_id,
                error_count=len(rollback_errors),
                errors=rollback_errors,
            )
            # 部分回滚失败，抛出让上层感知数据不一致风险
            raise RuntimeError(
                f"事务部分回滚失败，{len(rollback_errors)} 个操作补偿失败: "
                f"{rollback_errors}"
            )

        logger.info(
            "transaction.rollback_success",
            tx_id=self._tx_id,
            tx_name=self._name,
            rollback_count=len(self._executed_ops),
        )
        return True

    # ============================================================
    # 操作执行与补偿
    # ============================================================

    def _execute_op(self, op: PendingOperation) -> None:
        """执行单个操作"""
        if op.operation == TransactionOperation.ADD:
            assert op.memory is not None
            success = op.layer.add(op.memory)
            if not success:
                raise RuntimeError(
                    f"添加记忆失败: {op.layer_name}/{op.memory.memory_id}"
                )

        elif op.operation == TransactionOperation.REMOVE:
            assert op.memory_id is not None
            success = op.layer.remove(op.memory_id)
            if not success:
                raise RuntimeError(
                    f"删除记忆失败: {op.layer_name}/{op.memory_id}"
                )

        elif op.operation == TransactionOperation.UPDATE:
            assert op.memory_id is not None
            assert op.update_data is not None
            self._execute_update(op)

    def _execute_update(self, op: PendingOperation) -> None:
        """
        执行 update 操作：读取现有记忆，更新字段后写回

        由于各层没有原生的 update 接口，采用 get -> 修改 -> add（覆盖）模式。
        """
        assert op.memory_id is not None
        assert op.update_data is not None

        existing = op.layer.get(op.memory_id)
        if existing is None:
            raise RuntimeError(
                f"更新失败：记忆不存在 {op.layer_name}/{op.memory_id}"
            )

        # 更新字段
        for key, value in op.update_data.items():
            if hasattr(existing, key):
                setattr(existing, key, value)
            else:
                # 对于 metadata 等嵌套字段，也支持直接写入 metadata 的子键
                existing.metadata[key] = value

        existing.updated_at = datetime.now()

        success = op.layer.add(existing)
        if not success:
            raise RuntimeError(
                f"更新记忆失败: {op.layer_name}/{op.memory_id}"
            )

    def _snapshot_before(self, op: PendingOperation) -> None:
        """
        执行操作前拍摄快照，用于回滚补偿
        """
        if op.operation == TransactionOperation.ADD:
            # ADD 的补偿是 REMOVE，快照只需记录 memory_id
            assert op.memory is not None
            op.rollback_snapshot = {
                "memory_id": op.memory.memory_id,
            }

        elif op.operation == TransactionOperation.REMOVE:
            # REMOVE 的补偿是 ADD，需要快照完整的记忆对象
            assert op.memory_id is not None
            existing = op.layer.get(op.memory_id)
            if existing is None:
                raise RuntimeError(
                    f"删除失败：记忆不存在 {op.layer_name}/{op.memory_id}"
                )
            op.rollback_snapshot = {
                "memory_item": existing.model_copy(deep=True),
            }

        elif op.operation == TransactionOperation.UPDATE:
            # UPDATE 的补偿是恢复旧值，需要快照完整的记忆对象
            assert op.memory_id is not None
            existing = op.layer.get(op.memory_id)
            if existing is None:
                raise RuntimeError(
                    f"更新失败：记忆不存在 {op.layer_name}/{op.memory_id}"
                )
            op.rollback_snapshot = {
                "memory_item": existing.model_copy(deep=True),
            }

    def _compensate_op(self, op: PendingOperation) -> None:
        """
        补偿（回滚）单个操作

        补偿失败时抛出异常，由外层 _do_rollback 捕获并记录。
        """
        assert op.rollback_snapshot is not None

        if op.operation == TransactionOperation.ADD:
            # ADD 的补偿：删除刚添加的记忆
            memory_id = op.rollback_snapshot["memory_id"]
            success = op.layer.remove(memory_id)
            if not success:
                raise RuntimeError(
                    f"回滚失败：无法删除刚添加的记忆 "
                    f"{op.layer_name}/{memory_id}"
                )

        elif op.operation == TransactionOperation.REMOVE:
            # REMOVE 的补偿：重新添加被删除的记忆
            memory_item = op.rollback_snapshot["memory_item"]
            success = op.layer.add(memory_item)
            if not success:
                raise RuntimeError(
                    f"回滚失败：无法恢复被删除的记忆 "
                    f"{op.layer_name}/{memory_item.memory_id}"
                )

        elif op.operation == TransactionOperation.UPDATE:
            # UPDATE 的补偿：恢复更新前的状态
            memory_item = op.rollback_snapshot["memory_item"]
            success = op.layer.add(memory_item)
            if not success:
                raise RuntimeError(
                    f"回滚失败：无法恢复更新前的记忆 "
                    f"{op.layer_name}/{memory_item.memory_id}"
                )

    # ============================================================
    # 辅助方法
    # ============================================================

    def _ensure_pending(self) -> None:
        """确保事务处于可登记操作的状态"""
        if self._state != TransactionState.PENDING:
            raise RuntimeError(
                f"事务当前状态 {self._state.value}，无法登记新操作"
            )

    def _get_layer_name(self, layer) -> str:
        """获取层名称用于日志"""
        if hasattr(layer, "_layer_enum"):
            return layer._layer_enum.value
        if hasattr(layer, "__class__"):
            return layer.__class__.__name__
        return str(layer)

    def _log_entry(self, entry: TransactionLogEntry) -> None:
        """记录审计日志"""
        self._audit_log.append(entry)

    @property
    def tx_id(self) -> str:
        """事务 ID"""
        return self._tx_id

    @property
    def state(self) -> TransactionState:
        """当前事务状态"""
        return self._state

    @property
    def audit_log(self) -> List[TransactionLogEntry]:
        """审计日志（只读视图）"""
        return list(self._audit_log)

    @property
    def pending_count(self) -> int:
        """待执行操作数"""
        return len(self._pending_ops)

    # ============================================================
    # 上下文管理器
    # ============================================================

    def __enter__(self) -> "MemoryTransaction":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """
        上下文管理器退出

        - 无异常：自动 commit
        - 有异常：自动 rollback，异常继续向上抛出
        """
        if exc_type is None:
            # 正常退出，提交事务
            try:
                self.commit()
            except Exception:
                # commit 内部已回滚，异常继续抛出
                raise
            return False
        else:
            # 发生异常，回滚事务
            logger.warning(
                "transaction.exit_with_exception",
                tx_id=self._tx_id,
                exception_type=exc_type.__name__,
                exception=str(exc_val),
            )
            try:
                if self._state in (TransactionState.ACTIVE, TransactionState.PENDING):
                    self._do_rollback()
            except Exception as rb_err:
                logger.error(
                    "transaction.rollback_on_exit_failed",
                    tx_id=self._tx_id,
                    error=str(rb_err),
                )
            # 返回 False 让异常继续传播
            return False

    def __repr__(self) -> str:
        return (
            f"<MemoryTransaction id={self._tx_id} "
            f"name={self._name} state={self._state.value} "
            f"pending={len(self._pending_ops)} "
            f"executed={len(self._executed_ops)}>"
        )


# ============================================================
# 便捷函数
# ============================================================

def migrate_memory(
    source_layer,
    target_layer,
    memory_id: str,
    *,
    modify_before_add=None,
) -> bool:
    """
    便捷函数：在事务中完成单层记忆迁移

    从 source_layer 取出指定记忆，可选修改后添加到 target_layer，
    再从 source_layer 删除。全部操作在一个事务中保证原子性。

    Args:
        source_layer: 源记忆层
        target_layer: 目标记忆层
        memory_id: 待迁移的记忆 ID
        modify_before_add: 可选的修改函数，接收 MemoryItem 并原地修改

    Returns:
        True 表示迁移成功

    Raises:
        Exception: 迁移失败时抛出（已自动回滚）
    """
    item = source_layer.get(memory_id)
    if item is None:
        raise ValueError(f"源层中不存在记忆: {memory_id}")

    # 深拷贝，避免修改源层中的对象
    item_copy = item.model_copy(deep=True)

    if modify_before_add is not None:
        modify_before_add(item_copy)

    with MemoryTransaction(name=f"migrate_{memory_id}") as tx:
        tx.add(target_layer, item_copy)
        tx.remove(source_layer, memory_id)

    return True


__all__ = [
    "MemoryTransaction",
    "TransactionOperation",
    "TransactionState",
    "TransactionLogEntry",
    "migrate_memory",
]
# vim: set et ts=4 sw=4:
