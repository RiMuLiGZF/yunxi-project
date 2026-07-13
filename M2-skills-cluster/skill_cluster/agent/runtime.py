from __future__ import annotations

"""Agent Runtime - Agent 运行时与状态管理.

为 Skill 集群系统引入真正的 Agent 实体概念，管理 Agent 的 Skill 绑定、
状态生命周期、记忆上下文、LLM 对话循环。
"""

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult


class AgentState(BaseModel):
    """Agent 状态快照."""

    agent_id: str = Field(..., description="Agent 唯一标识")
    name: str = Field(..., description="Agent 名称")
    description: str = Field(default="", description="Agent 描述")
    bound_skills: list[str] = Field(
        default_factory=list, description="绑定的 Skill ID 列表"
    )
    memory_context: dict[str, Any] = Field(
        default_factory=dict, description="记忆上下文"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="元数据"
    )
    status: str = Field(default="idle", description="状态: idle/busy/offline")
    created_at: float = Field(default_factory=time.time)
    last_active_at: float = Field(default_factory=time.time)


class AgentRegistry:
    """Agent 注册中心."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentState] = {}

    def register(self, state: AgentState) -> None:
        """注册 Agent."""
        self._agents[state.agent_id] = state

    def unregister(self, agent_id: str) -> None:
        """注销 Agent."""
        self._agents.pop(agent_id, None)

    def get(self, agent_id: str) -> AgentState | None:
        """获取 Agent 状态."""
        return self._agents.get(agent_id)

    def list_agents(self) -> list[str]:
        """列出所有 Agent ID."""
        return list(self._agents.keys())

    def bind_skill(self, agent_id: str, skill_id: str) -> bool:
        """为 Agent 绑定 Skill."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return False
        if skill_id not in agent.bound_skills:
            agent.bound_skills.append(skill_id)
            agent.last_active_at = time.time()
        return True

    def unbind_skill(self, agent_id: str, skill_id: str) -> bool:
        """为 Agent 解绑 Skill."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return False
        if skill_id in agent.bound_skills:
            agent.bound_skills.remove(skill_id)
            agent.last_active_at = time.time()
        return True

    def update_memory(self, agent_id: str, key: str, value: Any) -> bool:
        """更新 Agent 记忆."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return False
        agent.memory_context[key] = value
        agent.last_active_at = time.time()
        return True

    def update_status(self, agent_id: str, status: str) -> bool:
        """更新 Agent 状态."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return False
        agent.status = status
        agent.last_active_at = time.time()
        return True

    def get_bound_skills(self, agent_id: str) -> list[str]:
        """获取 Agent 绑定的 Skill 列表."""
        agent = self._agents.get(agent_id)
        return agent.bound_skills if agent else []


class AgentRuntime:
    """Agent 运行时.

    管理 Agent 的生命周期、Skill 调用代理、上下文注入。
    """

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self._registry = registry or AgentRegistry()

    def create_agent(
        self,
        name: str,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AgentState:
        """创建 Agent."""
        agent_id = f"agent_{uuid.uuid4().hex[:12]}"
        state = AgentState(
            agent_id=agent_id,
            name=name,
            description=description,
            metadata=metadata or {},
        )
        self._registry.register(state)
        return state

    def get_agent(self, agent_id: str) -> AgentState | None:
        """获取 Agent."""
        return self._registry.get(agent_id)

    def bind_skills(self, agent_id: str, skill_ids: list[str]) -> None:
        """批量绑定 Skill."""
        for sid in skill_ids:
            self._registry.bind_skill(agent_id, sid)

    def get_available_skills(self, agent_id: str) -> list[str]:
        """获取 Agent 可用的 Skill 列表."""
        return self._registry.get_bound_skills(agent_id)

    def inject_agent_context(
        self, request: SkillInvokeRequest, agent_id: str
    ) -> SkillInvokeRequest:
        """将 Agent 的上下文注入到 Skill 调用请求中.

        将 Agent 的 memory_context 合并到请求参数中，
        使 Skill 能够感知 Agent 的状态和记忆。
        """
        agent = self._registry.get(agent_id)
        if agent is None:
            return request

        # 创建新的请求，注入 Agent 上下文
        merged_params = dict(agent.memory_context)
        merged_params.update(request.params)
        # 保留原始 params 作为嵌套对象
        merged_params["__original_params"] = request.params
        merged_params["__agent_id"] = agent_id
        merged_params["__agent_name"] = agent.name

        return SkillInvokeRequest(
            skill_id=request.skill_id,
            action=request.action,
            params=merged_params,
            trace_id=request.trace_id,
            timeout=request.timeout,
        )

    async def run_skill(
        self,
        agent_id: str,
        skill_id: str,
        action: str,
        params: dict[str, Any],
        invoke_fn: Any,
    ) -> SkillInvokeResult:
        """Agent 代理执行 Skill 调用.

        自动注入 Agent 上下文、更新状态、记录活跃时间。
        """
        self._registry.update_status(agent_id, "busy")

        request = SkillInvokeRequest(
            skill_id=skill_id,
            action=action,
            params=params,
            trace_id=f"agent_{agent_id}_{uuid.uuid4().hex[:8]}",
        )
        request = self.inject_agent_context(request, agent_id)

        try:
            result = await invoke_fn(request, agent_id)
        finally:
            self._registry.update_status(agent_id, "idle")

        # 将 Skill 返回的数据写入 Agent 记忆
        if result.status == "success" and result.data is not None:
            self._registry.update_memory(
                agent_id,
                f"last_result:{skill_id}:{action}",
                result.data,
            )

        return result

    def get_all_agents(self) -> list[AgentState]:
        """获取所有 Agent 状态."""
        return [
            self._registry.get(aid)
            for aid in self._registry.list_agents()
            if self._registry.get(aid) is not None
        ]
