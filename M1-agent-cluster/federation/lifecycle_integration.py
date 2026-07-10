"""
联邦生命周期集成 — FederationLifecycleIntegration
====================================================

将 Agent 生命周期管理器与联邦调度系统集成：
  - 注册 Agent 时自动注册到生命周期管理器
  - 调度前自动 ensure_warm
  - 调用后自动 mark_used
  - 提供统一的启动/停止入口
"""

from __future__ import annotations

from typing import Any

import structlog

from federation.ollama_manager import OllamaModelManager
from federation.lifecycle_manager import (
    AgentLifecycleManager,
    AgentLifecycleState,
)
from federation.registry import ExternalAgentRegistry
from shared_models import ExternalAgentProfile

logger = structlog.get_logger(__name__)


class FederationLifecycleIntegration:
    """联邦生命周期集成层

    职责：
      1. 串联 OllamaModelManager + AgentLifecycleManager
      2. 与 ExternalAgentRegistry 联动，注册时自动纳入生命周期管理
      3. 提供给调度器使用的简便 API

    使用方式：
        lifecycle = FederationLifecycleIntegration()
        await lifecycle.start()

        # 注册一个受管理的 Agent
        lifecycle.register_agent(profile)

        # 调度前唤醒
        await lifecycle.ensure_agent_warm(agent_id)

        # 调用完成后标记使用
        await lifecycle.mark_agent_used(agent_id)
    """

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        max_concurrent_models: int = 2,
        max_warm_agents: int = 3,
        model_idle_ttl: float = 180.0,
        agent_idle_ttl: float = 300.0,
        agent_dormant_ttl: float = 1800.0,
    ) -> None:
        # Ollama 模型管理器
        self.ollama = OllamaModelManager(
            base_url=ollama_base_url,
            max_concurrent_models=max_concurrent_models,
            idle_ttl=model_idle_ttl,
        )

        # Agent 生命周期管理器
        self.agent_lifecycle = AgentLifecycleManager(
            ollama_manager=self.ollama,
            max_warm_agents=max_warm_agents,
            idle_ttl=agent_idle_ttl,
            dormant_ttl=agent_dormant_ttl,
        )

        self._logger = logger.bind(component="federation_lifecycle")
        self._started = False

    # ── 启动/停止 ────────────────────────────────────────

    async def start(self) -> None:
        """启动所有生命周期组件"""
        if self._started:
            return

        await self.ollama.start()
        await self.agent_lifecycle.start()
        self._started = True
        self._logger.info("federation_lifecycle_started")

    async def stop(self) -> None:
        """停止所有生命周期组件"""
        if not self._started:
            return

        await self.agent_lifecycle.stop()
        await self.ollama.stop()
        self._started = False
        self._logger.info("federation_lifecycle_stopped")

    # ── Agent 注册 ────────────────────────────────────────

    def register_agent_from_profile(
        self,
        profile: ExternalAgentProfile,
        model_name: str = "",
        priority: int = 5,
    ) -> None:
        """从 Agent Profile 注册到生命周期管理

        Args:
            profile: 外部 Agent 配置
            model_name: 使用的 Ollama 模型名（从 config 中自动探测，也可手动指定）
            priority: 优先级 0-10
        """
        # 从 config 中探测模型名
        if not model_name:
            config = profile.config or {}
            model_name = (
                config.get("model_name")
                or config.get("model")
                or config.get("ollama_model")
                or ""
            )

        # 判断是否为本地 Ollama 模型驱动的 Agent
        is_local_ollama = bool(model_name) and profile.privacy_level.value == "local_only"

        self.agent_lifecycle.register_agent(
            agent_id=profile.agent_id,
            display_name=profile.display_name,
            model_name=model_name if is_local_ollama else "",
            priority=priority,
            metadata={
                "provider": profile.provider,
                "capabilities": list(profile.capabilities),
                "is_local_ollama": is_local_ollama,
            },
        )

        self._logger.debug(
            "agent_registered_for_lifecycle",
            agent_id=profile.agent_id,
            model=model_name,
            priority=priority,
        )

    def register_all_from_registry(
        self,
        registry: ExternalAgentRegistry,
        priority_overrides: dict[str, int] | None = None,
    ) -> int:
        """从注册表批量注册所有 Agent

        Args:
            registry: 外部 Agent 注册表
            priority_overrides: 优先级覆盖 {agent_id_prefix: priority}

        Returns:
            注册的 Agent 数量
        """
        agents = registry.list_agents()
        count = 0

        for profile in agents:
            # 确定优先级
            priority = 5
            if priority_overrides:
                for prefix, prio in priority_overrides.items():
                    if profile.agent_id.startswith(prefix):
                        priority = prio
                        break

            self.register_agent_from_profile(profile, priority=priority)
            count += 1

        self._logger.info(
            "bulk_registered_from_registry",
            count=count,
        )
        return count

    # ── 调度器 API ────────────────────────────────────────

    async def ensure_agent_warm(self, agent_id: str) -> bool:
        """确保 Agent 处于热状态（调度前调用）

        Returns:
            True = 就绪，False = 唤醒失败（调度器应考虑降级）
        """
        return await self.agent_lifecycle.ensure_warm(agent_id)

    async def mark_agent_used(self, agent_id: str) -> None:
        """标记 Agent 被使用（调用成功后调用）"""
        await self.agent_lifecycle.mark_used(agent_id)

    async def release_agent(self, agent_id: str) -> None:
        """主动释放 Agent（任务完成后可选调用）"""
        await self.agent_lifecycle.release(agent_id)

    # ── 状态查询 ──────────────────────────────────────────

    def get_agent_state(self, agent_id: str) -> AgentLifecycleState | None:
        """获取 Agent 状态"""
        return self.agent_lifecycle.get_state(agent_id)

    def list_agent_states(self) -> list[dict[str, Any]]:
        """列出所有 Agent 的生命周期状态"""
        return self.agent_lifecycle.list_agents()

    async def get_vram_status(self) -> dict[str, Any]:
        """获取 VRAM 使用状态"""
        return await self.ollama.get_vram_usage()

    def stats(self) -> dict[str, Any]:
        """综合统计"""
        return {
            "ollama": self.ollama.stats(),
            "agent_lifecycle": self.agent_lifecycle.stats(),
        }
