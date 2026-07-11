"""潮汐记忆桥接.

通过 SkillRouter 间接调用 TideMemorySkill 的记忆操作。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Awaitable
from enum import Enum
from typing import Any, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)


class DegradationLevel(str, Enum):
    """降级级别枚举.

    Attributes:
        FULL: 完整功能.
        READ_ONLY: 仅读取，不写入.
        DISABLED: 完全禁用.
    """

    FULL = "full"
    READ_ONLY = "read_only"
    DISABLED = "disabled"


@runtime_checkable
class SkillRouterProtocol(Protocol):
    """SkillRouter 协议定义.

    定义 SkillRouter 必须实现的 call 方法接口，
    用于间接调用 TideMemorySkill 的各操作。

    Note:
        使用 Protocol 而非 Any 类型，确保类型安全。
    """

    async def call(
        self,
        skill_name: str,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        """调用指定 Skill 的方法.

        Args:
            skill_name: 技能名称.
            method: 方法名.
            params: 调用参数字典.

        Returns:
            调用结果.

        Raises:
            Exception: 调用失败.
        """
        ...


class TideMemoryBridge:
    """潮汐记忆桥接.

    通过 SkillRouter 间接调用 TideMemorySkill 的 recall/archive/compress 接口，
    实现推理上下文的记忆增强。内置降级策略，当记忆服务不可用时自动降级。

    Attributes:
        _skill_router: SkillRouter 引用（间接调用 TideMemorySkill）.
        _degradation_level: 当前降级级别.
        _recall_timeout_s: recall 操作超时（秒）.
        _archive_timeout_s: archive 操作超时（秒）.
        _offline_cache: 离线缓存字典（archive 降级时使用）.
    """

    def __init__(
        self,
        skill_router: SkillRouterProtocol | None = None,
        recall_timeout_s: float = 3.0,
        archive_timeout_s: float = 5.0,
    ) -> None:
        """初始化 TideMemoryBridge.

        Args:
            skill_router: SkillRouter 实例（可选），符合 SkillRouterProtocol 协议.
            recall_timeout_s: recall 超时（秒）.
            archive_timeout_s: archive 超时（秒）.
        """
        self._skill_router: SkillRouterProtocol | None = skill_router
        self._degradation_level = DegradationLevel.FULL
        self._recall_timeout_s = recall_timeout_s
        self._archive_timeout_s = archive_timeout_s
        self._offline_cache: dict[str, list[dict[str, Any]]] = {}
        logger.info(
            "tide_memory_bridge.init",
            recall_timeout=recall_timeout_s,
            archive_timeout=archive_timeout_s,
        )

    def set_skill_router(self, skill_router: SkillRouterProtocol) -> None:
        """设置 SkillRouter.

        Args:
            skill_router: SkillRouter 实例（符合 SkillRouterProtocol 协议）.
        """
        self._skill_router = skill_router
        self._degradation_level = DegradationLevel.FULL
        logger.info("tide_memory_bridge.skill_router_set")

    async def recall(
        self,
        query: str,
        top_k: int = 5,
        session_id: str = "",
    ) -> list[dict[str, Any]]:
        """从记忆中召回相关内容.

        通过 SkillRouter 调用 TideMemorySkill.recall()。
        使用 asyncio.wait_for 实现超时控制，超时后降级返回空结果。

        Args:
            query: 查询文本.
            top_k: 返回的最大条目数.
            session_id: 会话 ID（用于限定范围）.

        Returns:
            相关记忆条目列表，按相关性排序.

        Raises:
            RuntimeError: 记忆服务完全禁用.
        """
        if self._degradation_level == DegradationLevel.DISABLED:
            logger.debug("tide_memory_bridge.recall_disabled")
            return []

        if self._skill_router is None:
            self._upgrade_degradation()
            logger.debug("tide_memory_bridge.no_router")
            return []

        try:
            result = await asyncio.wait_for(
                self._skill_router.call(
                    skill_name="tide_memory",
                    method="recall",
                    params={"query": query, "top_k": top_k, "session_id": session_id},
                ),
                timeout=self._recall_timeout_s,
            )
            memories: list[dict[str, Any]] = result if isinstance(result, list) else []
            logger.debug(
                "tide_memory_bridge.recall_success",
                count=len(memories),
            )
            return memories

        except asyncio.TimeoutError:
            logger.warning(
                "tide_memory_bridge.recall_timeout",
                timeout_s=self._recall_timeout_s,
                query=query[:50],
            )
            self._upgrade_degradation()
            return []
        except Exception as e:
            logger.error(
                "tide_memory_bridge.recall_error",
                error=str(e),
            )
            self._upgrade_degradation()
            return []

    async def archive(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> bool:
        """将内容归档到长期记忆.

        通过 SkillRouter 调用 TideMemorySkill.archive()。
        当服务不可用时降级到本地离线缓存。

        Args:
            content: 待归档内容.
            metadata: 附带元数据.
            session_id: 会话 ID.

        Returns:
            是否归档成功.
        """
        if self._degradation_level != DegradationLevel.FULL:
            logger.debug(
                "tide_memory_bridge.archive_skipped",
                level=self._degradation_level.value,
            )
            # 降级到离线缓存
            return self._cache_offline(content, metadata, session_id)

        if self._skill_router is None:
            return self._cache_offline(content, metadata, session_id)

        try:
            await asyncio.wait_for(
                self._skill_router.call(
                    skill_name="tide_memory",
                    method="archive",
                    params={
                        "content": content,
                        "metadata": metadata,
                        "session_id": session_id,
                    },
                ),
                timeout=self._archive_timeout_s,
            )
            logger.debug(
                "tide_memory_bridge.archive_success",
                session_id=session_id,
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "tide_memory_bridge.archive_timeout",
                timeout_s=self._archive_timeout_s,
            )
            return self._cache_offline(content, metadata, session_id)
        except Exception as e:
            logger.error(
                "tide_memory_bridge.archive_error",
                error=str(e),
            )
            return self._cache_offline(content, metadata, session_id)

    def _cache_offline(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> bool:
        """将内容缓存到本地离线存储（降级路径）.

        当记忆服务不可用时，将数据暂存到内存缓存中，
        待服务恢复后可重新同步。

        Args:
            content: 待缓存内容.
            metadata: 附带元数据.
            session_id: 会话 ID.

        Returns:
            是否缓存成功（始终返回 True）.
        """
        cache_key = session_id or "_default"
        entry: dict[str, Any] = {
            "content": content,
            "metadata": metadata,
            "cached_at": time.time(),
        }
        if cache_key not in self._offline_cache:
            self._offline_cache[cache_key] = []
        self._offline_cache[cache_key].append(entry)
        logger.debug(
            "tide_memory_bridge.offline_cached",
            cache_key=cache_key,
            cache_size=len(self._offline_cache[cache_key]),
        )
        return True

    async def compress(
        self,
        session_id: str = "",
        strategy: str = "summary",
    ) -> bool:
        """压缩历史记忆.

        通过 SkillRouter 调用 TideMemorySkill.compress()，
        将冗余记忆压缩为精简摘要。
        使用 asyncio.create_task 异步调度，不阻塞调用方。

        Args:
            session_id: 会话 ID.
            strategy: 压缩策略（summary/merge/drop）.

        Returns:
            是否成功发起压缩任务.
        """
        if self._degradation_level != DegradationLevel.FULL:
            return False

        if self._skill_router is None:
            return False

        try:
            # 异步调度压缩任务，不阻塞调用方
            asyncio.create_task(
                self._do_compress(session_id, strategy),
                name=f"tide_compress_{session_id or 'default'}",
            )
            logger.info(
                "tide_memory_bridge.compress_scheduled",
                session_id=session_id,
                strategy=strategy,
            )
            return True
        except Exception as e:
            logger.error(
                "tide_memory_bridge.compress_error",
                error=str(e),
            )
            return False

    async def _do_compress(self, session_id: str, strategy: str) -> None:
        """执行实际的压缩操作（异步后台任务）.

        Args:
            session_id: 会话 ID.
            strategy: 压缩策略.
        """
        try:
            await self._skill_router.call(  # type: ignore[union-attr]
                skill_name="tide_memory",
                method="compress",
                params={"session_id": session_id, "strategy": strategy},
            )
            logger.info(
                "tide_memory_bridge.compress_completed",
                session_id=session_id,
                strategy=strategy,
            )
        except Exception as e:
            logger.error(
                "tide_memory_bridge.compress_task_error",
                session_id=session_id,
                error=str(e),
            )

    def _upgrade_degradation(self) -> None:
        """升级降级级别（功能逐步减少）.

        降级链：FULL -> READ_ONLY -> DISABLED.
        """
        levels = list(DegradationLevel)
        current_idx = levels.index(self._degradation_level)
        if current_idx < len(levels) - 1:
            new_level = levels[current_idx + 1]
            self._degradation_level = new_level
            logger.warning(
                "tide_memory_bridge.degradation_upgraded",
                new_level=new_level.value,
            )

    def reset_degradation(self) -> None:
        """重置降级级别到 FULL.

        在记忆服务恢复后调用。
        """
        self._degradation_level = DegradationLevel.FULL
        logger.info("tide_memory_bridge.degradation_reset")

    @property
    def degradation_level(self) -> DegradationLevel:
        """获取当前降级级别.

        Returns:
            当前降级级别.
        """
        return self._degradation_level

    @property
    def offline_cache_size(self) -> int:
        """获取离线缓存条目总数.

        Returns:
            离线缓存中的总条目数.
        """
        return sum(len(entries) for entries in self._offline_cache.values())
