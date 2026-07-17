"""
分身池 — ClonePool

管理所有临时分身的完整生命周期，包括：
- 分身获取与释放
- 全局与按父Agent维度的配额控制
- 过期分身的定时清理
- 分身检索与统计
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

import structlog

from shared_models import CloneIdentity, CloneType

from src.pool.clone_factory import CloneFactory

logger = structlog.get_logger(__name__)


class ClonePool:
    """临时分身池

    职责：
    - 管理所有临时分身的创建、存储与释放
    - 全局最大分身数量与按父Agent维度的配额控制
    - 定时清理过期分身，防止资源泄漏
    - 提供多维度检索与统计能力
    """

    def __init__(
        self,
        max_pool_size: int = 100,
        max_clones_per_parent: int = 10,
        cleanup_interval: float = 60.0,
    ) -> None:
        """初始化分身池

        Args:
            max_pool_size:       全局最大分身数量
            max_clones_per_parent: 每个父Agent允许创建的最大分身数
            cleanup_interval:    过期清理定时器间隔（秒）
        """
        self._clones: dict[str, CloneIdentity] = {}
        self._max_pool_size: int = max_pool_size
        self._max_clones_per_parent: int = max_clones_per_parent
        self._factory = CloneFactory()
        self._cleanup_task: asyncio.Task[None] | None = None
        self._cleanup_interval: float = cleanup_interval
        self._logger = logger.bind(component="clone_pool")

    # ══════════════════════════════════════════════════════════
    # 生命周期管理
    # ══════════════════════════════════════════════════════════

    async def acquire(
        self,
        parent_agent_id: str,
        clone_type: CloneType,
        task_id: str,
        context: dict[str, Any] | None = None,
    ) -> CloneIdentity:
        """获取一个临时分身

        通过 CloneFactory 创建分身并注册到池中。
        当达到全局上限或父Agent配额上限时拒绝创建。

        Args:
            parent_agent_id: 父Agent ID
            clone_type:     分身类型
            task_id:        关联的任务ID
            context:        下发上下文（将被裁剪为最小信息）

        Returns:
            新创建的 CloneIdentity

        Raises:
            RuntimeError: 达到分身数量上限
        """
        # 先清理一次过期分身，腾出空间
        self.cleanup_expired()

        # 检查配额限制
        if not self._check_limits(parent_agent_id):
            self._logger.warning(
                "clone_acquire_rejected",
                parent_agent_id=parent_agent_id,
                clone_type=clone_type.value,
                reason="limit_exceeded",
                current_pool_size=len(self._clones),
                max_pool_size=self._max_pool_size,
            )
            raise RuntimeError(
                f"分身池已满（全局上限={self._max_pool_size}，"
                f"父Agent上限={self._max_clones_per_parent}），无法创建新分身"
            )

        # 通过工厂创建分身
        clone = self._factory.create_clone(
            parent_agent_id=parent_agent_id,
            clone_type=clone_type,
            task_id=task_id,
            context=context,
        )

        # 注册到池中
        self._clones[clone.clone_id] = clone

        self._logger.info(
            "clone_acquired",
            clone_id=clone.clone_id,
            clone_type=clone_type.value,
            parent_agent_id=parent_agent_id,
            task_id=task_id,
            pool_size=len(self._clones),
        )

        return clone

    def release(self, clone_id: str) -> bool:
        """释放一个临时分身

        从池中移除指定分身。

        Args:
            clone_id: 分身ID

        Returns:
            True 表示成功释放，False 表示分身不存在
        """
        clone = self._clones.pop(clone_id, None)
        if clone is None:
            self._logger.warning(
                "clone_release_not_found",
                clone_id=clone_id,
            )
            return False

        self._logger.info(
            "clone_released",
            clone_id=clone_id,
            clone_type=clone.clone_type.value,
            parent_agent_id=clone.parent_agent_id,
            task_id=clone.task_id,
            remaining_pool_size=len(self._clones),
        )
        return True

    # ══════════════════════════════════════════════════════════
    # 检索
    # ══════════════════════════════════════════════════════════

    def get_clone(self, clone_id: str) -> CloneIdentity | None:
        """根据ID获取分身

        Args:
            clone_id: 分身ID

        Returns:
            对应的 CloneIdentity，不存在则返回 None
        """
        return self._clones.get(clone_id)

    def list_by_parent(self, parent_agent_id: str) -> list[CloneIdentity]:
        """列出指定父Agent的所有分身

        Args:
            parent_agent_id: 父Agent ID

        Returns:
            该父Agent创建的所有活跃分身列表
        """
        return [
            clone
            for clone in self._clones.values()
            if clone.parent_agent_id == parent_agent_id
        ]

    def list_by_type(self, clone_type: CloneType) -> list[CloneIdentity]:
        """列出指定类型的所有分身

        Args:
            clone_type: 分身类型

        Returns:
            所有匹配类型的活跃分身列表
        """
        return [
            clone
            for clone in self._clones.values()
            if clone.clone_type == clone_type
        ]

    # ══════════════════════════════════════════════════════════
    # 过期清理
    # ══════════════════════════════════════════════════════════

    def cleanup_expired(self) -> int:
        """清理所有过期分身

        根据 created_at + ttl 判断是否过期，移除所有过期分身。

        Returns:
            本次清理移除的分身数量
        """
        now = time.time()
        expired_ids: list[str] = []

        for clone_id, clone in self._clones.items():
            if now > clone.created_at + clone.ttl:
                expired_ids.append(clone_id)

        for clone_id in expired_ids:
            expired_clone = self._clones.pop(clone_id)
            self._logger.info(
                "clone_expired_and_removed",
                clone_id=clone_id,
                clone_type=expired_clone.clone_type.value,
                parent_agent_id=expired_clone.parent_agent_id,
                task_id=expired_clone.task_id,
                age_seconds=round(now - expired_clone.created_at, 2),
            )

        if expired_ids:
            self._logger.info(
                "cleanup_completed",
                expired_count=len(expired_ids),
                remaining_pool_size=len(self._clones),
            )

        return len(expired_ids)

    def _schedule_cleanup(self) -> None:
        """启动定时清理任务

        创建一个异步定时器，周期性调用 cleanup_expired()。
        仅应在 asyncio 事件循环中调用。
        """
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._logger.debug("cleanup_task_already_running")
            return

        async def _cleanup_loop() -> None:
            """过期清理循环"""
            while True:
                try:
                    await asyncio.sleep(self._cleanup_interval)
                    count = self.cleanup_expired()
                    if count > 0:
                        self._logger.info(
                            "scheduled_cleanup_swept",
                            expired_count=count,
                            remaining=len(self._clones),
                        )
                except asyncio.CancelledError:
                    self._logger.info("cleanup_task_cancelled")
                    break
                except Exception as exc:
                    self._logger.error(
                        "cleanup_task_error",
                        error=str(exc),
                    )

        self._cleanup_task = asyncio.create_task(_cleanup_loop())
        self._logger.info(
            "cleanup_scheduler_started",
            interval_seconds=self._cleanup_interval,
        )

    async def stop_cleanup(self) -> None:
        """停止定时清理任务"""
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._logger.info("cleanup_scheduler_stopped")

    # ══════════════════════════════════════════════════════════
    # 配额检查
    # ══════════════════════════════════════════════════════════

    def _check_limits(self, parent_agent_id: str) -> bool:
        """检查是否达到配额上限

        同时检查全局上限和父Agent维度上限。

        Args:
            parent_agent_id: 父Agent ID

        Returns:
            True 表示未达上限，可以继续创建
        """
        # 全局上限检查
        if len(self._clones) >= self._max_pool_size:
            return False

        # 父Agent维度上限检查
        parent_clone_count = sum(
            1 for c in self._clones.values() if c.parent_agent_id == parent_agent_id
        )
        if parent_clone_count >= self._max_clones_per_parent:
            return False

        return True

    # ══════════════════════════════════════════════════════════
    # 统计
    # ══════════════════════════════════════════════════════════

    def stats(self) -> dict[str, Any]:
        """生成分身池统计信息

        Returns:
            包含总量、按类型统计、按父Agent统计、配额使用率的字典
        """
        now = time.time()

        # 按分身类型统计
        by_type: dict[str, int] = defaultdict(int)
        for clone in self._clones.values():
            by_type[clone.clone_type.value] += 1

        # 按父Agent统计
        by_parent: dict[str, int] = defaultdict(int)
        for clone in self._clones.values():
            by_parent[clone.parent_agent_id] += 1

        # 计算即将过期数量（未来30秒内）
        near_expiry_count = sum(
            1
            for clone in self._clones.values()
            if now > clone.created_at + clone.ttl - 30
        )

        # 计算平均TTL使用率
        ttl_usage_ratios: list[float] = []
        for clone in self._clones.values():
            elapsed = now - clone.created_at
            ratio = elapsed / clone.ttl if clone.ttl > 0 else 0.0
            ttl_usage_ratios.append(ratio)
        avg_ttl_usage = (
            sum(ttl_usage_ratios) / len(ttl_usage_ratios)
            if ttl_usage_ratios
            else 0.0
        )

        return {
            "total_clones": len(self._clones),
            "max_pool_size": self._max_pool_size,
            "pool_utilization": round(
                len(self._clones) / self._max_pool_size, 4
            ) if self._max_pool_size > 0 else 0.0,
            "max_clones_per_parent": self._max_clones_per_parent,
            "by_type": dict(by_type),
            "by_parent": dict(by_parent),
            "parent_agent_count": len(by_parent),
            "near_expiry_count": near_expiry_count,
            "avg_ttl_usage": round(avg_ttl_usage, 4),
        }
