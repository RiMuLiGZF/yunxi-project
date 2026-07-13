"""
Agent 生命周期管理器 — AgentLifecycleManager
==============================================

统一管理所有联邦 Agent 的生命周期：
  - 🟢 热状态（WARM）：模型已加载，可立即响应
  - 🟡 温状态（WARMING）：正在加载中
  - 🔵 冷状态（COLD）：模型未加载，需要唤醒
  - ⏸️ 休眠状态（DORMANT）：长时间未使用，已深度休眠

核心机制：
  1. 按需唤醒：调度前自动唤醒目标 Agent
  2. 空闲休眠：超过 TTL 未使用自动进入休眠
  3. 并发限制：同时活跃的 Agent 不超过上限
  4. 优先级调度：重要 Agent 优先保活

与 OllamaModelManager 配合实现模型级别的显存管理。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

import structlog

from federation.ollama_manager import OllamaModelManager

logger = structlog.get_logger(__name__)


class AgentLifecycleState(str, Enum):
    """Agent 生命周期状态"""
    COLD = "cold"           # 冷启动：从未加载或已深度休眠
    WARMING = "warming"     # 预热中：正在加载模型
    WARM = "warm"           # 热状态：模型已加载，立即可用
    COOLING = "cooling"     # 冷却中：即将进入休眠
    DORMANT = "dormant"     # 休眠：模型已卸载，可快速唤醒


@dataclass
class AgentLifecycleInfo:
    """Agent 生命周期信息"""
    agent_id: str
    display_name: str
    state: AgentLifecycleState = AgentLifecycleState.COLD
    model_name: str = ""
    priority: int = 5           # 优先级 0-10，越高越优先保活
    last_used: float = 0.0      # 最后使用时间
    warm_count: int = 0         # 累计唤醒次数
    total_warm_time: float = 0.0  # 累计热状态时长（秒）
    warm_started_at: float = 0.0  # 本次热状态开始时间
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        now = time.time()
        current_warm_duration = now - self.warm_started_at if self.state == AgentLifecycleState.WARM else 0
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "state": self.state.value,
            "model_name": self.model_name,
            "priority": self.priority,
            "last_used_seconds_ago": round(now - self.last_used, 1) if self.last_used > 0 else None,
            "warm_count": self.warm_count,
            "total_warm_seconds": round(self.total_warm_time + current_warm_duration, 1),
            "metadata": self.metadata,
        }


class AgentLifecycleManager:
    """Agent 生命周期管理器

    负责：
      - 追踪所有 Agent 的生命周期状态
      - 按需唤醒 Agent（调用前确保模型就绪）
      - 空闲超时自动休眠（释放显存）
      - 并发控制（同时热状态的 Agent 不超过上限）
      - 优先级管理（高优先级 Agent 优先保活）

    与 OllamaModelManager 协作：
      - 唤醒时调用 ollama_manager.ensure_model()
      - 休眠时由 ollama_manager 的 idle TTL 自动处理
    """

    def __init__(
        self,
        ollama_manager: OllamaModelManager | None = None,
        max_warm_agents: int = 3,           # 同时热状态的最大 Agent 数
        idle_ttl: float = 300.0,            # 空闲超时进入休眠（秒），默认5分钟
        dormant_ttl: float = 1800.0,        # 超长空闲进入深度休眠（秒），默认30分钟
        check_interval: float = 60.0,       # 空闲检测间隔（秒）
    ) -> None:
        self._ollama = ollama_manager
        self._max_warm = max_warm_agents
        self._idle_ttl = idle_ttl
        self._dormant_ttl = dormant_ttl
        self._check_interval = check_interval

        # Agent 状态表
        self._agents: dict[str, AgentLifecycleInfo] = {}

        # 唤醒锁（防止并发唤醒同一个 Agent）
        self._warmup_locks: dict[str, asyncio.Lock] = {}

        # 唤醒回调（可选，用于自定义唤醒逻辑）
        self._warmup_hooks: dict[str, Callable[[str], Awaitable[bool]]] = {}
        self._cooldown_hooks: dict[str, Callable[[str], Awaitable[None]]] = {}

        # 后台任务
        self._cleanup_task: asyncio.Task | None = None
        self._running = False

        self._logger = logger.bind(component="agent_lifecycle_manager")

    # ── 生命周期 ──────────────────────────────────────────

    async def start(self) -> None:
        """启动生命周期管理器"""
        if self._running:
            return

        self._running = True

        # 启动空闲检测
        self._cleanup_task = asyncio.create_task(self._idle_check_loop())

        self._logger.info(
            "lifecycle_manager_started",
            max_warm_agents=self._max_warm,
            idle_ttl=self._idle_ttl,
            dormant_ttl=self._dormant_ttl,
        )

    async def stop(self) -> None:
        """停止管理器"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        self._logger.info("lifecycle_manager_stopped")

    # ── Agent 注册 ──────────────────────────────────────────

    def register_agent(
        self,
        agent_id: str,
        display_name: str,
        model_name: str = "",
        priority: int = 5,
        warmup_hook: Callable[[str], Awaitable[bool]] | None = None,
        cooldown_hook: Callable[[str], Awaitable[None]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册一个受管理的 Agent"""
        info = AgentLifecycleInfo(
            agent_id=agent_id,
            display_name=display_name,
            model_name=model_name,
            priority=priority,
            metadata=metadata or {},
        )
        self._agents[agent_id] = info

        if warmup_hook:
            self._warmup_hooks[agent_id] = warmup_hook
        if cooldown_hook:
            self._cooldown_hooks[agent_id] = cooldown_hook

        self._logger.debug(
            "agent_registered_for_lifecycle",
            agent_id=agent_id,
            model=model_name,
            priority=priority,
        )

    def unregister_agent(self, agent_id: str) -> None:
        """取消注册"""
        self._agents.pop(agent_id, None)
        self._warmup_locks.pop(agent_id, None)
        self._warmup_hooks.pop(agent_id, None)
        self._cooldown_hooks.pop(agent_id, None)

    # ── 核心 API ──────────────────────────────────────────

    async def ensure_warm(self, agent_id: str) -> bool:
        """确保 Agent 处于热状态（按需唤醒）

        调度器在调用 Agent 之前调用此方法。

        Returns:
            True 表示 Agent 已就绪，False 表示唤醒失败
        """
        info = self._agents.get(agent_id)
        if not info:
            # 未注册的 Agent，默认放行
            return True

        # 已经是热状态，直接返回
        if info.state == AgentLifecycleState.WARM:
            info.last_used = time.time()
            return True

        # 正在预热中，等待完成
        if info.state == AgentLifecycleState.WARMING:
            lock = self._warmup_locks.setdefault(agent_id, asyncio.Lock())
            async with lock:
                # 重新检查状态
                if info.state == AgentLifecycleState.WARM:
                    info.last_used = time.time()
                    return True
                # 被其他协程唤醒失败
                return False

        # 需要唤醒，获取锁
        lock = self._warmup_locks.setdefault(agent_id, asyncio.Lock())
        async with lock:
            # 双重检查
            if info.state == AgentLifecycleState.WARM:
                info.last_used = time.time()
                return True

            return await self._do_warmup(agent_id, info)

    async def mark_used(self, agent_id: str) -> None:
        """标记 Agent 被使用了（更新最后使用时间）"""
        info = self._agents.get(agent_id)
        if info:
            info.last_used = time.time()

    async def release(self, agent_id: str) -> None:
        """主动释放 Agent（标记为可冷却）"""
        info = self._agents.get(agent_id)
        if info and info.state == AgentLifecycleState.WARM:
            info.last_used = time.time()  # 从现在开始计时空闲
            # 不立即冷却，等 idle_ttl 后由后台任务处理

    def get_state(self, agent_id: str) -> AgentLifecycleState | None:
        """获取 Agent 状态"""
        info = self._agents.get(agent_id)
        return info.state if info else None

    def list_agents(self) -> list[dict[str, Any]]:
        """列出所有受管理的 Agent 状态"""
        return [info.to_dict() for info in self._agents.values()]

    def stats(self) -> dict[str, Any]:
        """统计信息"""
        states: dict[str, int] = {}
        for info in self._agents.values():
            states[info.state.value] = states.get(info.state.value, 0) + 1

        return {
            "total_agents": len(self._agents),
            "states": states,
            "max_warm_agents": self._max_warm,
            "idle_ttl": self._idle_ttl,
            "dormant_ttl": self._dormant_ttl,
            "running": self._running,
        }

    # ── 内部方法 ──────────────────────────────────────────

    async def _do_warmup(self, agent_id: str, info: AgentLifecycleInfo) -> bool:
        """执行实际的唤醒操作"""
        info.state = AgentLifecycleState.WARMING
        self._logger.info("agent_warming_up", agent_id=agent_id, model=info.model_name)

        success = True

        # 1. 如果有 Ollama 管理器，先确保模型加载
        if self._ollama and info.model_name:
            model_ok = await self._ollama.ensure_model(info.model_name)
            if not model_ok:
                self._logger.warning(
                    "agent_warmup_model_failed",
                    agent_id=agent_id,
                    model=info.model_name,
                )
                success = False

        # 2. 如果有自定义唤醒钩子，调用它
        if success and agent_id in self._warmup_hooks:
            try:
                hook_ok = await self._warmup_hooks[agent_id](agent_id)
                if not hook_ok:
                    success = False
            except Exception as exc:
                self._logger.error(
                    "agent_warmup_hook_failed",
                    agent_id=agent_id,
                    error=str(exc),
                )
                success = False

        if success:
            info.state = AgentLifecycleState.WARM
            info.warm_count += 1
            info.warm_started_at = time.time()
            info.last_used = time.time()
            self._logger.info(
                "agent_warm_success",
                agent_id=agent_id,
                model=info.model_name,
                warm_count=info.warm_count,
            )
        else:
            info.state = AgentLifecycleState.COLD
            self._logger.warning("agent_warm_failed", agent_id=agent_id)

        return success

    async def _idle_check_loop(self) -> None:
        """后台空闲检测循环"""
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)
                await self._check_idle_agents()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._logger.error("idle_check_error", error=str(exc))

    async def _check_idle_agents(self) -> None:
        """检查并处理空闲 Agent"""
        now = time.time()

        # 收集热状态的 Agent，按优先级+最后使用时间排序
        warm_agents = [
            info for info in self._agents.values()
            if info.state == AgentLifecycleState.WARM
        ]

        # 1. 超过 idle_ttl 的 → 进入冷却（标记为可被 Ollama 卸载）
        for info in warm_agents:
            idle_time = now - info.last_used
            if idle_time > self._idle_ttl:
                await self._cool_down(info)

        # 2. 超过 dormant_ttl 的 → 深度休眠（冷状态）
        dormant_agents = [
            info for info in self._agents.values()
            if info.state in (AgentLifecycleState.COOLING, AgentLifecycleState.DORMANT)
        ]
        for info in dormant_agents:
            idle_time = now - info.last_used
            if idle_time > self._dormant_ttl:
                info.state = AgentLifecycleState.DORMANT

        # 3. 如果热 Agent 超过上限，按优先级+空闲时间淘汰
        current_warm = [
            info for info in self._agents.values()
            if info.state == AgentLifecycleState.WARM
        ]
        if len(current_warm) > self._max_warm:
            # 按优先级升序、最后使用时间升序排序（最该被淘汰的在前）
            current_warm.sort(key=lambda i: (i.priority, i.last_used))
            to_evict = current_warm[:len(current_warm) - self._max_warm]
            for info in to_evict:
                await self._cool_down(info)

    async def _cool_down(self, info: AgentLifecycleInfo) -> None:
        """冷却一个 Agent"""
        if info.state != AgentLifecycleState.WARM:
            return

        info.state = AgentLifecycleState.COOLING

        # 累计热状态时长
        info.total_warm_time += time.time() - info.warm_started_at

        # 调用冷却钩子
        if info.agent_id in self._cooldown_hooks:
            try:
                await self._cooldown_hooks[info.agent_id](info.agent_id)
            except Exception as exc:
                self._logger.error(
                    "cooldown_hook_failed",
                    agent_id=info.agent_id,
                    error=str(exc),
                )

        # Ollama 模型由 OllamaManager 的 idle TTL 管理
        # 这里只更新状态，模型卸载由 ollama_manager 自动处理

        self._logger.info(
            "agent_cooling_down",
            agent_id=info.agent_id,
            idle_seconds=round(time.time() - info.last_used, 1),
        )
