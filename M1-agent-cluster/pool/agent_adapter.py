"""
分身Agent适配器 — CloneAgentAdapter

将临时分身适配为 IAgentPlugin 接口，使分身可以像普通 Agent 一样
参与任务分发与调度系统。适配器实现最小权限隔离：
- 只能访问其被授权的资源和API
- 所有操作记录审计日志
- 卸载时自动通知 ClonePool 释放资源
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from interfaces import AgentResult, AgentTask, IAgentPlugin
from shared_models import CloneIdentity

logger = structlog.get_logger(__name__)

# 原始Agent的 handle_task 方法签名
HandleTaskFunc = Callable[[AgentTask], Awaitable[AgentResult]]


class CloneAgentAdapter(IAgentPlugin):
    """分身Agent适配器

    将 CloneIdentity 适配为 IAgentPlugin 接口的桥接层，
    使临时分身可以无缝参与集群的任务调度。

    特性：
    - 继承 IAgentPlugin，可注册到 Agent 注册中心
    - handle_task 时记录审计日志（分身ID + 父AgentID）
    - 实现最小权限：分身只能访问其被授权的资源和API
    - on_unmount 时通知 ClonePool 释放分身

    Args:
        identity:    分身身份信息
        parent_handle_task: 父Agent的原始 handle_task 方法引用
        pool:        分身池引用（用于自动释放），可为 None（不自动释放）
    """

    def __init__(
        self,
        identity: CloneIdentity,
        parent_handle_task: HandleTaskFunc,
        pool: Any | None = None,
    ) -> None:
        self.agent_id: str = identity.clone_id
        self.version: str = "1.0.0"
        self.capabilities: list[str] = list(identity.capabilities)

        self._identity = identity
        self._parent_handle_task = parent_handle_task
        self._pool = pool  # 避免循环导入，使用 Any 类型
        self._logger = logger.bind(
            component="clone_agent_adapter",
            clone_id=identity.clone_id,
            clone_type=identity.clone_type.value,
            parent_agent_id=identity.parent_agent_id,
        )
        self._task_count: int = 0
        self._created_at: float = time.time()

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理任务（带审计日志）

        在委托给父Agent的 handle_task 之前：
        1. 检查任务是否在分身权限范围内（最小权限检查）
        2. 将分身身份注入任务元数据
        3. 记录审计日志

        Args:
            task: 待处理的任务

        Returns:
            任务执行结果
        """
        start_time = time.time()

        # 最小权限检查：分身只能处理与其能力匹配的任务
        self._check_permission(task)

        # 注入分身身份到任务元数据
        self._inject_clone_metadata(task)

        self._logger.info(
            "clone_handle_task_start",
            clone_id=self._identity.clone_id,
            parent_agent_id=self._identity.parent_agent_id,
            task_id=task.task_id,
            intent=task.intent,
        )

        try:
            # 委托给父Agent的原始 handle_task 方法
            result = await self._parent_handle_task(task)

            # 确保结果中包含分身标识
            result.agent_id = self.agent_id

            elapsed_ms = (time.time() - start_time) * 1000
            self._task_count += 1

            self._logger.info(
                "clone_handle_task_complete",
                clone_id=self._identity.clone_id,
                parent_agent_id=self._identity.parent_agent_id,
                task_id=task.task_id,
                status=result.status,
                latency_ms=round(elapsed_ms, 2),
                total_tasks_handled=self._task_count,
            )

            return result

        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000

            self._logger.error(
                "clone_handle_task_error",
                clone_id=self._identity.clone_id,
                parent_agent_id=self._identity.parent_agent_id,
                task_id=task.task_id,
                error=str(exc),
                latency_ms=round(elapsed_ms, 2),
            )

            # 返回失败结果
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status="failure",
                error=f"分身执行失败: {exc}",
                latency_ms=elapsed_ms,
            )

    def _check_permission(self, task: AgentTask) -> None:
        """最小权限检查

        分身只能处理其被授权的资源。检查方式：
        - 如果任务指定了 required_capability，检查分身是否具备
        - 检查任务 payload 中的 resource 字段是否在授权范围内
        - 分身只能操作与其 clone_type 和 minimized_context 相关的资源

        Args:
            task: 待检查的任务

        Raises:
            PermissionError: 分身无权处理该任务
        """
        required = task.metadata.get("required_capability", "")
        if required and required not in self.capabilities:
            self._logger.warning(
                "clone_permission_denied",
                clone_id=self._identity.clone_id,
                task_id=task.task_id,
                required_capability=required,
                clone_capabilities=self.capabilities,
            )
            raise PermissionError(
                f"分身 {self._identity.clone_id}（{self._identity.clone_type.value}）"
                f"不具备所需能力 '{required}'，拒绝执行任务 {task.task_id}"
            )

        # 检查资源范围限制：分身只能访问 minimized_context 中声明的资源
        authorized_resources = self._identity.minimized_context.get("authorized_resources", [])
        if authorized_resources:
            target_resource = task.metadata.get("target_resource", "")
            if target_resource and target_resource not in authorized_resources:
                self._logger.warning(
                    "clone_resource_access_denied",
                    clone_id=self._identity.clone_id,
                    task_id=task.task_id,
                    target_resource=target_resource,
                    authorized_resources=authorized_resources,
                )
                raise PermissionError(
                    f"分身 {self._identity.clone_id} 无权访问资源 '{target_resource}'"
                )

    def _inject_clone_metadata(self, task: AgentTask) -> None:
        """将分身身份信息注入任务元数据

        使下游处理链可以识别任务是由分身执行的，
        便于审计追踪和权限校验。

        Args:
            task: 待注入的任务
        """
        task.metadata["clone_id"] = self._identity.clone_id
        task.metadata["clone_type"] = self._identity.clone_type.value
        task.metadata["parent_agent_id"] = self._identity.parent_agent_id
        task.metadata["is_clone_task"] = True

    async def on_mount(self, registry: Any | None = None) -> None:
        """分身被注册到注册中心时调用

        Args:
            registry: 注册中心引用（可选）
        """
        self._logger.info(
            "clone_adapter_mounted",
            clone_id=self._identity.clone_id,
            parent_agent_id=self._identity.parent_agent_id,
        )

    async def on_unmount(self) -> None:
        """分身从注册中心注销时调用

        自动通知 ClonePool 释放该分身，防止资源泄漏。
        """
        self._logger.info(
            "clone_adapter_unmounting",
            clone_id=self._identity.clone_id,
            parent_agent_id=self._identity.parent_agent_id,
            total_tasks_handled=self._task_count,
            lifetime_seconds=round(time.time() - self._created_at, 2),
        )

        # 通知分身池释放该分身
        if self._pool is not None:
            try:
                released = self._pool.release(self._identity.clone_id)
                if released:
                    self._logger.info(
                        "clone_auto_released_on_unmount",
                        clone_id=self._identity.clone_id,
                    )
                else:
                    self._logger.warning(
                        "clone_release_failed_on_unmount",
                        clone_id=self._identity.clone_id,
                    )
            except Exception as exc:
                self._logger.error(
                    "clone_release_error_on_unmount",
                    clone_id=self._identity.clone_id,
                    error=str(exc),
                )

    async def health(self) -> dict[str, Any]:
        """返回分身适配器的健康状态

        Returns:
            包含分身基本信息和运行统计的字典
        """
        now = time.time()
        elapsed = now - self._created_at
        ttl_remaining = max(0, self._identity.created_at + self._identity.ttl - now)

        return {
            "agent_id": self.agent_id,
            "status": "healthy",
            "version": self.version,
            "clone_type": self._identity.clone_type.value,
            "parent_agent_id": self._identity.parent_agent_id,
            "task_id": self._identity.task_id,
            "tasks_handled": self._task_count,
            "lifetime_seconds": round(elapsed, 2),
            "ttl_remaining_seconds": round(ttl_remaining, 2),
            "capabilities": self.capabilities,
        }
