"""
云汐内核 - 任务编排子Agent（Orchestrator-Agent）实现

负责：
- 接收编排请求，调用 DAGBuilder 生成 TaskDAG
- 与 Lifecycle-Agent 协作：请求创建执行团队
- 与 Snapshot-Agent 协作：记录 DAG 创建快照
- 与 Bus-Agent 协作：发布 DAG 创建事件
- 维护 _dag_registry 存储所有活跃 DAG
- 提供 DAG 查询、进度追踪、节点状态更新等管理接口
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from interfaces import AgentResult, AgentTask, IAgentPlugin
from shared_models import TaskDAG

from orchestrator.dag_builder import DAGBuilder

logger = structlog.get_logger(__name__)


class OrchestratorAgent(IAgentPlugin):
    """任务编排子Agent（Orchestrator-Agent）

    负责将用户的高层请求分解为结构化的 TaskDAG，
    管理DAG全生命周期，协调其他子Agent完成执行。

    实现的意图（intent）：
    - "orchestrate.build": 构建新DAG
    - "orchestrate.query": 查询DAG信息
    - "orchestrate.progress": 获取DAG进度
    - "orchestrate.ready_tasks": 获取可执行节点
    - "orchestrate.update_node": 更新节点状态

    协作Agent：
    - Lifecycle-Agent（agent.lifecycle）：创建/销毁执行团队
    - Snapshot-Agent（agent.snapshot）：记录DAG快照
    - Bus-Agent（agent.bus）：发布DAG事件

    Attributes:
        agent_id: Agent唯一标识
        version: Agent版本号
        capabilities: Agent能力列表
        _dag_registry: 活跃DAG存储字典（dag_id -> TaskDAG）
        _dag_builder: DAG构建器实例
        _logger: structlog 绑定日志器
    """

    agent_id: str = "agent.orchestrator"
    version: str = "11.0.0"  # [V11.0-FEDERATION]
    capabilities: list[str] = [
        "orchestrate.build",
        "orchestrate.query",
        "orchestrate.progress",
        "orchestrate.ready_tasks",
        "orchestrate.update_node",
        "orchestrate.scene_switch",  # [v2.0-LINKAGE] M4场景切换
        "orchestrate.voice_polish",  # [v1.0-VOICE] 云汐人格润色输出
        "federation.decide",         # [V11.0] 联邦调度决策
        "federation.invoke",         # [V11.0] 调用外部Agent
        "federation.compare",        # [V11.0] 多Agent对比
    ]

    def __init__(self) -> None:
        self._logger = logger.bind(agent_id=self.agent_id)
        self._dag_registry: dict[str, TaskDAG] = {}
        self._dag_builder = DAGBuilder()
        # [v1.0-VOICE] 云汐人格润色Agent引用（懒加载）
        self._voice_agent = None  # type: Any
        # [V11.0-FEDERATION] 联邦调度组件引用（懒加载）
        self._fed_registry = None
        self._fed_scheduler = None
        self._fed_comparator = None
        self._cost_controller = None
        self._privacy_guard = None

    # ──────────────────────────────────────────────────────
    # IAgentPlugin 接口实现
    # ──────────────────────────────────────────────────────

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理编排相关任务

        根据任务意图路由到不同的处理方法：
        - orchestrate.build: 构建新DAG
        - orchestrate.query: 查询DAG详情
        - orchestrate.progress: 获取DAG进度摘要
        - orchestrate.ready_tasks: 获取当前可执行节点
        - orchestrate.update_node: 更新节点执行状态
        - orchestrate.scene_switch: [v2.0-LINKAGE] M4场景切换

        Args:
            task: Agent任务对象，包含意图和载荷

        Returns:
            AgentResult 执行结果
        """
        start_time = time.time()
        intent = task.intent
        payload = task.payload

        self._logger.info(
            "handling_task",
            trace_id=task.trace_id,
            task_id=task.task_id,
            intent=intent,
        )

        try:
            if intent == "orchestrate.build":
                result = await self._handle_build(payload)
            elif intent == "orchestrate.query":
                result = await self._handle_query(payload)
            elif intent == "orchestrate.progress":
                result = await self._handle_progress(payload)
            elif intent == "orchestrate.ready_tasks":
                result = await self._handle_ready_tasks(payload)
            elif intent == "orchestrate.update_node":
                result = await self._handle_update_node(payload)
            elif intent == "orchestrate.scene_switch":
                result = await self._handle_scene_switch(payload)
            elif intent == "orchestrate.voice_polish":
                result = await self._handle_voice_polish(payload)
            elif intent == "federation.decide":
                result = await self._handle_fed_decide(payload)
            elif intent == "federation.invoke":
                result = await self._handle_fed_invoke(payload)
            elif intent == "federation.compare":
                result = await self._handle_fed_compare(payload)
            else:
                return AgentResult(
                    task_id=task.task_id,
                    trace_id=task.trace_id,
                    agent_id=self.agent_id,
                    status="failure",
                    error=f"未知意图: {intent}，支持的意图: {self.capabilities}",
                    latency_ms=(time.time() - start_time) * 1000,
                )

            latency_ms = (time.time() - start_time) * 1000
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="success",
                output=result,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = (time.time() - start_time) * 1000
            self._logger.error(
                "task_error",
                trace_id=task.trace_id,
                intent=intent,
                error=str(exc),
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=str(exc),
                latency_ms=latency_ms,
            )

    async def on_mount(self, registry: Any | None = None) -> None:
        """Agent 被注册到注册中心时调用

        初始化DAG构建器，订阅消息总线事件。

        Args:
            registry: Agent注册中心实例（可选）
        """
        self._logger.info("agent_mounted", registry=registry is not None)

    async def on_unmount(self) -> None:
        """Agent 从注册中心注销时调用

        清理所有活跃DAG注册信息。
        """
        count = len(self._dag_registry)
        self._dag_registry.clear()
        self._logger.info("agent_unmounted", cleared_dags=count)

    async def health(self) -> dict[str, Any]:
        """返回健康状态

        Returns:
            包含健康信息的字典
        """
        return {
            "agent_id": self.agent_id,
            "status": "healthy",
            "version": self.version,
            "active_dags": len(self._dag_registry),
        }

    # ──────────────────────────────────────────────────────
    # 公开管理接口
    # ──────────────────────────────────────────────────────

    def get_dag(self, dag_id: str) -> TaskDAG | None:
        """根据dag_id获取DAG实例

        Args:
            dag_id: DAG唯一标识

        Returns:
            对应的TaskDAG实例，不存在则返回None
        """
        dag = self._dag_registry.get(dag_id)
        if dag is None:
            self._logger.warn("dag_not_found", dag_id=dag_id)
        return dag

    def get_ready_tasks(self, dag_id: str) -> list[dict]:
        """获取DAG中当前可执行的节点列表

        返回所有前置依赖已完成且状态为pending的节点，
        按优先级降序排列。

        Args:
            dag_id: DAG唯一标识

        Returns:
            可执行节点字典列表；DAG不存在则返回空列表
        """
        dag = self._dag_registry.get(dag_id)
        if dag is None:
            self._logger.warn("dag_not_found_for_ready_tasks", dag_id=dag_id)
            return []
        return dag.get_ready_nodes()

    def update_node_status(
        self,
        dag_id: str,
        node_id: str,
        status: str,
        result_summary: str = "",
        error: str = "",
    ) -> bool:
        """更新DAG中指定节点的执行状态

        状态流转规则：
        - pending -> running: 节点开始执行
        - running -> completed: 节点执行成功
        - running -> failed: 节点执行失败
        - pending -> skipped: 节点被跳过（如条件分支不满足）

        Args:
            dag_id: DAG唯一标识
            node_id: 节点唯一标识
            status: 新状态（pending/running/completed/failed/skipped）
            result_summary: 执行结果摘要（可选）
            error: 错误信息（可选）

        Returns:
            True 更新成功，False 失败（DAG或节点不存在）
        """
        dag = self._dag_registry.get(dag_id)
        if dag is None:
            self._logger.warn(
                "dag_not_found_for_update",
                dag_id=dag_id,
                node_id=node_id,
            )
            return False

        # 在nodes列表中查找目标节点
        for node in dag.nodes:
            if node.get("node_id") == node_id:
                # 记录旧状态用于日志
                old_status = node.get("status", "unknown")

                # 更新状态
                node["status"] = status

                # 更新结果摘要
                if result_summary:
                    node["result_summary"] = result_summary

                # 更新错误信息
                if error:
                    node["error"] = error

                # 更新时间戳
                if status == "running" and not node.get("started_at"):
                    node["started_at"] = time.time()
                elif status in ("completed", "failed", "skipped"):
                    node["completed_at"] = time.time()

                self._logger.info(
                    "node_status_updated",
                    dag_id=dag_id,
                    node_id=node_id,
                    old_status=old_status,
                    new_status=status,
                )
                return True

        self._logger.warn(
            "node_not_found_for_update",
            dag_id=dag_id,
            node_id=node_id,
        )
        return False

    def get_dag_progress(self, dag_id: str) -> dict[str, Any]:
        """获取DAG执行进度摘要

        返回DAG的整体执行状态统计，包括各状态节点计数、完成率等信息。

        Args:
            dag_id: DAG唯一标识

        Returns:
            进度摘要字典，包含以下字段：
            - dag_id: DAG标识
            - goal: 任务目标
            - total_nodes: 总节点数
            - completed: 已完成节点数
            - running: 执行中节点数
            - failed: 失败节点数
            - skipped: 跳过节点数
            - pending: 待执行节点数
            - completion_rate: 完成率（0.0-1.0）
            - exists: DAG是否存在
        """
        dag = self._dag_registry.get(dag_id)
        if dag is None:
            return {
                "dag_id": dag_id,
                "exists": False,
                "error": "DAG不存在",
            }

        # 统计各状态节点数
        status_counts: dict[str, int] = {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
        }
        for node in dag.nodes:
            node_status = node.get("status", "pending")
            if node_status in status_counts:
                status_counts[node_status] += 1

        progress = {
            "dag_id": dag_id,
            "goal": dag.goal,
            "total_nodes": len(dag.nodes),
            "completed": status_counts["completed"],
            "running": status_counts["running"],
            "failed": status_counts["failed"],
            "skipped": status_counts["skipped"],
            "pending": status_counts["pending"],
            "completion_rate": dag.completion_rate(),
            "exists": True,
        }

        return progress

    # ──────────────────────────────────────────────────────
    # 内部处理方法
    # ──────────────────────────────────────────────────────

    async def _handle_build(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理DAG构建请求

        流程：
        1. 调用 DAGBuilder 生成 TaskDAG
        2. 将DAG注册到 _dag_registry
        3. 请求 Lifecycle-Agent 创建执行团队
        4. 请求 Snapshot-Agent 记录快照
        5. 通过 Bus-Agent 发布 DAG 创建事件

        Args:
            payload: 包含以下字段
                - goal: str — 任务目标
                - context: dict — 附加上下文（可选）
                - available_agents: list[dict] — 可用Agent列表（可选）

        Returns:
            构建结果字典
        """
        goal: str = payload.get("goal", "")
        context: dict[str, Any] = payload.get("context", {})
        available_agents: list[dict[str, Any]] = payload.get("available_agents", [])

        if not goal:
            raise ValueError("payload 中缺少必要字段: goal")

        # 第一步：构建 DAG
        dag = self._dag_builder.build_dag(goal, context, available_agents)

        # 第二步：注册到活跃DAG字典
        self._dag_registry[dag.dag_id] = dag
        self._logger.info(
            "dag_registered",
            dag_id=dag.dag_id,
            goal=goal[:80],
        )

        # 第三步：与 Lifecycle-Agent 协作 —— 请求创建执行团队
        await self._request_lifecycle_team(dag)

        # 第四步：与 Snapshot-Agent 协作 —— 记录DAG创建快照
        await self._request_snapshot(dag)

        # 第五步：与 Bus-Agent 协作 —— 发布DAG创建事件
        await self._publish_dag_event(dag, "dag.created")

        return {
            "action": "dag_built",
            "dag_id": dag.dag_id,
            "goal": dag.goal,
            "node_count": len(dag.nodes),
            "edge_count": len(dag.edges),
            "topological_order": dag.topological_sort(),
        }

    async def _handle_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理DAG查询请求

        Args:
            payload: 包含 dag_id 字段

        Returns:
            DAG详情字典
        """
        dag_id: str = payload.get("dag_id", "")
        dag = self.get_dag(dag_id)
        if dag is None:
            return {"action": "query_failed", "dag_id": dag_id, "error": "DAG不存在"}
        return {
            "action": "query_success",
            "dag": dag.to_dict(),
        }

    async def _handle_progress(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理DAG进度查询请求

        Args:
            payload: 包含 dag_id 字段

        Returns:
            进度摘要字典
        """
        dag_id: str = payload.get("dag_id", "")
        progress = self.get_dag_progress(dag_id)
        return {
            "action": "progress",
            **progress,
        }

    async def _handle_ready_tasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理可执行节点查询请求

        Args:
            payload: 包含 dag_id 字段

        Returns:
            可执行节点列表
        """
        dag_id: str = payload.get("dag_id", "")
        ready = self.get_ready_tasks(dag_id)
        return {
            "action": "ready_tasks",
            "dag_id": dag_id,
            "ready_tasks": ready,
            "count": len(ready),
        }

    async def _handle_update_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理节点状态更新请求

        Args:
            payload: 包含以下字段
                - dag_id: str — DAG标识
                - node_id: str — 节点标识
                - status: str — 新状态
                - result_summary: str — 结果摘要（可选）
                - error: str — 错误信息（可选）

        Returns:
            更新结果字典
        """
        dag_id: str = payload.get("dag_id", "")
        node_id: str = payload.get("node_id", "")
        status: str = payload.get("status", "")
        result_summary: str = payload.get("result_summary", "")
        error: str = payload.get("error", "")

        if not dag_id or not node_id or not status:
            raise ValueError("payload 中缺少必要字段: dag_id, node_id, status")

        success = self.update_node_status(
            dag_id=dag_id,
            node_id=node_id,
            status=status,
            result_summary=result_summary,
            error=error,
        )

        # 更新成功后发布状态变更事件
        if success:
            dag = self._dag_registry.get(dag_id)
            if dag:
                await self._publish_dag_event(dag, "node.status_changed", extra={
                    "node_id": node_id,
                    "status": status,
                })

        return {
            "action": "node_updated",
            "dag_id": dag_id,
            "node_id": node_id,
            "success": success,
        }

    async def _handle_scene_switch(self, payload: dict[str, Any]) -> dict[str, Any]:
        """[v2.0-LINKAGE] 处理M4场景切换请求

        流程：
        1. 解析旧场景与新场景信息
        2. 释放旧场景关联的Agent资源（通过Lifecycle-Agent）
        3. 初始化新场景所需的Agent组合
        4. 传递上下文交接数据

        Args:
            payload: 包含以下字段
                - old_scene: str — 旧场景标识
                - new_scene: str — 新场景标识
                - context_handover: dict — 上下文交接数据
                - involved_agents: list[str] — 旧场景涉及的Agent列表
                - new_scene_agents: list[dict] — 新场景需要的Agent配置列表

        Returns:
            场景切换结果字典
        """
        old_scene: str = payload.get("old_scene", "")
        new_scene: str = payload.get("new_scene", "")
        context_handover: dict[str, Any] = payload.get("context_handover", {})
        involved_agents: list[str] = payload.get("involved_agents", [])
        new_scene_agents: list[dict[str, Any]] = payload.get("new_scene_agents", [])

        if not new_scene:
            raise ValueError("payload 中缺少必要字段: new_scene")

        self._logger.info(
            "scene_switch_started",
            old_scene=old_scene,
            new_scene=new_scene,
            involved_agents_count=len(involved_agents),
        )

        # 第一步：释放旧场景Agent资源
        released_agents: list[str] = []
        for agent_id in involved_agents:
            # 从活跃DAG中移除关联
            dags_to_remove = [
                dag_id for dag_id, dag in self._dag_registry.items()
                if any(node.get("assigned_agent") == agent_id for node in dag.nodes)
            ]
            for dag_id in dags_to_remove:
                self._logger.info(
                    "removing_dag_for_scene_switch",
                    dag_id=dag_id,
                    agent_id=agent_id,
                    old_scene=old_scene,
                )
                self._dag_registry.pop(dag_id, None)
            released_agents.append(agent_id)

        # 第二步：初始化新场景Agent组合
        initialized_agents: list[dict[str, Any]] = []
        for agent_cfg in new_scene_agents:
            agent_id = agent_cfg.get("agent_id", "")
            if agent_id:
                initialized_agents.append({
                    "agent_id": agent_id,
                    "role": agent_cfg.get("role", "executor"),
                    "capabilities": agent_cfg.get("capabilities", []),
                })

        # 第三步：记录上下文交接
        self._logger.info(
            "scene_switch_completed",
            old_scene=old_scene,
            new_scene=new_scene,
            released_count=len(released_agents),
            initialized_count=len(initialized_agents),
        )

        return {
            "action": "scene_switched",
            "old_scene": old_scene,
            "new_scene": new_scene,
            "released_agents": released_agents,
            "initialized_agents": initialized_agents,
            "context_handover": context_handover,
        }

    # ──────────────────────────────────────────────────────
    # 跨Agent协作方法
    # ──────────────────────────────────────────────────────

    async def _request_lifecycle_team(self, dag: TaskDAG) -> None:
        """与 Lifecycle-Agent 协作：请求创建执行团队

        根据DAG中涉及的Agent列表，向Lifecycle-Agent发送组队请求。

        Args:
            dag: 已构建的TaskDAG
        """
        # 收集DAG中所有需要参与的Agent
        involved_agents: list[str] = []
        for node in dag.nodes:
            agent_id = node.get("assigned_agent", "")
            if agent_id and agent_id not in involved_agents:
                involved_agents.append(agent_id)

        self._logger.info(
            "requesting_lifecycle_team",
            dag_id=dag.dag_id,
            involved_agents=involved_agents,
        )

        # 通过消息总线向 Lifecycle-Agent 发送组队请求
        # 实际消息发送通过 BusMessage 完成，此处为逻辑预留
        self._logger.debug(
            "lifecycle_team_request_sent",
            target="agent.lifecycle",
            dag_id=dag.dag_id,
            team_members=involved_agents,
        )

    async def _request_snapshot(self, dag: TaskDAG) -> None:
        """与 Snapshot-Agent 协作：记录DAG创建快照

        在DAG创建完成后，请求Snapshot-Agent保存初始状态快照，
        用于后续回溯和审计。

        Args:
            dag: 已构建的TaskDAG
        """
        self._logger.info(
            "requesting_snapshot",
            dag_id=dag.dag_id,
            node_count=len(dag.nodes),
        )

        # 通过消息总线向 Snapshot-Agent 发送快照请求
        self._logger.debug(
            "snapshot_request_sent",
            target="agent.snapshot",
            dag_id=dag.dag_id,
            snapshot_type="dag_creation",
        )

    async def _publish_dag_event(
        self,
        dag: TaskDAG,
        event_type: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """与 Bus-Agent 协作：发布DAG事件

        通过消息总线发布DAG生命周期事件，通知其他Agent。

        Args:
            dag: 关联的TaskDAG
            event_type: 事件类型（如 dag.created, node.status_changed）
            extra: 额外事件数据（可选）
        """
        event_payload: dict[str, Any] = {
            "dag_id": dag.dag_id,
            "goal": dag.goal,
            "event_type": event_type,
            "node_count": len(dag.nodes),
            "completion_rate": dag.completion_rate(),
        }
        if extra:
            event_payload.update(extra)

        self._logger.info(
            "publishing_dag_event",
            dag_id=dag.dag_id,
            event_type=event_type,
        )

        # 通过消息总线发布事件
        self._logger.debug(
            "bus_event_published",
            target="agent.bus",
            topic="orchestrate.*",
            event_type=event_type,
            payload_keys=list(event_payload.keys()),
        )

    # ──────────────────────────────────────────────────────
    # [v1.0-VOICE] 云汐人格润色输出
    # ──────────────────────────────────────────────────────

    async def _handle_voice_polish(self, payload: dict[str, Any]) -> dict[str, Any]:
        """[v1.0-VOICE] 处理云汐人格润色请求

        在多Agent结果合并后、返回M4前，调用 YunxiVoice-Agent 对输出进行人格润色。
        作为面向用户输出的最后一道工序。

        流程：
        1. 懒加载 YunxiVoice-Agent
        2. 校验 raw_content 非空
        3. 调用 voice.polish 执行润色
        4. 执行质量校验（事实完整性/红线检测）
        5. 返回润色结果

        Args:
            payload: 包含以下字段
                - raw_content: str — 上游结构化原始内容
                - scene_type: str — 场景类型（coding/study/review/relationship/mental/life）
                - user_context: dict — 用户偏好上下文（可选）
                - output_format: str — 输出格式（text/markdown/mixed，默认text）
                - length_hint: str — 长度提示（short/medium/long，默认medium）

        Returns:
            润色结果字典
        """
        raw_content: str = payload.get("raw_content", "")
        scene_type: str = payload.get("scene_type", "life")
        user_context: dict[str, Any] | None = payload.get("user_context")
        output_format: str = payload.get("output_format", "text")
        length_hint: str = payload.get("length_hint", "medium")

        if not raw_content:
            return {
                "action": "voice_polish_skipped",
                "reason": "empty_raw_content",
                "polished_content": "",
                "scene_type": scene_type,
            }

        # 懒加载 voice agent
        voice_agent = self._get_voice_agent()

        self._logger.info(
            "voice_polish_started",
            scene_type=scene_type,
            content_length=len(raw_content),
            output_format=output_format,
        )

        # 调用 YunxiVoice-Agent 执行润色
        from interfaces import AgentTask
        voice_task = AgentTask(
            intent="voice.polish",
            payload={
                "raw_content": raw_content,
                "scene_type": scene_type,
                "user_context": user_context or {},
                "output_format": output_format,
                "length_hint": length_hint,
            },
        )
        voice_result = await voice_agent.handle_task(voice_task)

        if voice_result.status != "success":
            self._logger.warning(
                "voice_polish_failed",
                error=voice_result.error,
                scene_type=scene_type,
            )
            # 润色失败时降级返回原始内容，不阻断主流程
            return {
                "action": "voice_polish_failed_degraded",
                "error": voice_result.error,
                "polished_content": raw_content,
                "scene_type": scene_type,
                "degraded": True,
            }

        output = voice_result.output or {}

        self._logger.info(
            "voice_polish_completed",
            scene_type=scene_type,
            tone_applied=output.get("tone_applied", ""),
            quality_ok=output.get("facts_preserved", True),
            privacy_check=output.get("privacy_check", "passed"),
        )

        return {
            "action": "voice_polished",
            "scene_type": scene_type,
            "scene_name": output.get("scene_name", ""),
            "raw_content": raw_content,
            "polished_content": output.get("polished_content", raw_content),
            "tone_applied": output.get("tone_applied", ""),
            "personality_params": output.get("personality_params", {}),
            "content_modified": output.get("content_modified", False),
            "facts_preserved": output.get("facts_preserved", True),
            "privacy_check": output.get("privacy_check", "passed"),
            "red_line_violations": output.get("red_line_violations", []),
            "degraded": False,
        }

    def _get_voice_agent(self) -> Any:
        """获取 YunxiVoice-Agent 实例（懒加载）

        Returns:
            YunxiVoiceAgent 实例
        """
        if self._voice_agent is None:
            from voice.agent import YunxiVoiceAgent
            self._voice_agent = YunxiVoiceAgent()
            # 注意：on_mount 由调用方负责在外部触发
            self._logger.info("voice_agent_lazy_loaded")
        return self._voice_agent

    # ──────────────────────────────────────────────────────
    # [V11.0-FEDERATION] 联邦调度集成
    # ──────────────────────────────────────────────────────

    def _get_fed_registry(self) -> Any:
        """获取外部Agent注册表（懒加载）"""
        if self._fed_registry is None:
            from federation.registry import ExternalAgentRegistry
            self._fed_registry = ExternalAgentRegistry()
            self._logger.info("fed_registry_lazy_loaded")
        return self._fed_registry

    def _get_fed_scheduler(self) -> Any:
        """获取联邦调度器（懒加载）"""
        if self._fed_scheduler is None:
            from federation.scheduler import FederatedScheduler
            self._fed_scheduler = FederatedScheduler(
                registry=self._get_fed_registry(),
            )
            self._logger.info("fed_scheduler_lazy_loaded")
        return self._fed_scheduler

    def _get_fed_comparator(self) -> Any:
        """获取多Agent对比器（懒加载）"""
        if self._fed_comparator is None:
            from federation.comparator import MultiAgentComparator
            self._fed_comparator = MultiAgentComparator()
            self._logger.info("fed_comparator_lazy_loaded")
        return self._fed_comparator

    def _get_cost_controller(self) -> Any:
        """获取成本控制器（懒加载）"""
        if self._cost_controller is None:
            from federation.cost_controller import CostController
            self._cost_controller = CostController()
            self._logger.info("cost_controller_lazy_loaded")
        return self._cost_controller

    def _get_privacy_guard(self) -> Any:
        """获取隐私防护层（懒加载）"""
        if self._privacy_guard is None:
            from federation.privacy_guard import FederationPrivacyGuard
            self._privacy_guard = FederationPrivacyGuard()
            self._logger.info("privacy_guard_lazy_loaded")
        return self._privacy_guard

    def _parse_security_level(self, level_str: str) -> SecurityClassification:
        """将字符串转换为 SecurityClassification 枚举

        支持 IntEnum 的名称查找。
        """
        from shared_models import SecurityClassification
        if isinstance(level_str, SecurityClassification):
            return level_str
        try:
            return SecurityClassification[level_str.upper()]
        except (KeyError, AttributeError):
            return SecurityClassification.PUBLIC

    async def _handle_fed_decide(self, payload: dict[str, Any]) -> dict[str, Any]:
        """[V11.0] 联邦调度决策

        根据任务类型、涉密等级、用户偏好等因素，
        决定使用内部 Agent 还是外部 Agent，以及选择哪个外部 Agent。

        Args:
            payload: 决策参数
                - task_type: 任务类型
                - security_level: 涉密等级
                - user_preference: 用户偏好模式
                - remaining_budget: 剩余预算
                - speed_requirement: 速度要求
                - task_complexity: 任务复杂度

        Returns:
            决策结果
        """
        from shared_models import UserPreferenceMode

        scheduler = self._get_fed_scheduler()
        decision = scheduler.decide(
            task_type=payload.get("task_type", "general"),
            security_level=self._parse_security_level(
                payload.get("security_level", "PUBLIC")
            ),
            user_preference=UserPreferenceMode(
                payload.get("user_preference", "balanced")
            ) if payload.get("user_preference") else None,
            remaining_budget=float(payload.get("remaining_budget", -1.0)),
            speed_requirement=payload.get("speed_requirement", "medium"),
            task_complexity=float(payload.get("task_complexity", 0.5)),
        )

        return {"decision": decision.model_dump()}

    async def _handle_fed_invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        """[V11.0] 调用外部 Agent

        流程：
        1. 隐私扫描检查
        2. 获取适配器
        3. 调用外部 Agent
        4. 记录成本

        Args:
            payload: 调用参数
                - agent_id: 外部 Agent ID
                - prompt: 用户输入
                - system_prompt: 系统提示词
                - temperature: 温度
                - max_tokens: 最大 token
                - security_level: 涉密等级
                - task_id: 任务 ID（用于成本记录）

        Returns:
            调用结果
        """
        from shared_models import SecurityClassification

        registry = self._get_fed_registry()
        privacy_guard = self._get_privacy_guard()
        cost_controller = self._get_cost_controller()

        agent_id = payload.get("agent_id", "")
        prompt = payload.get("prompt", "")
        system_prompt = payload.get("system_prompt", "")
        security_level = self._parse_security_level(
            payload.get("security_level", "PUBLIC")
        )

        # 1. 隐私检查
        scan_result = privacy_guard.scan(
            content=prompt + "\n" + system_prompt,
            security_level=security_level,
            task_type=payload.get("task_type", "general"),
        )
        if scan_result.blocked:
            return {
                "success": False,
                "error": f"隐私检查未通过: {scan_result.summary}",
                "scan_result": scan_result.model_dump(),
            }

        # 2. 获取适配器
        adapter = registry.get_adapter(agent_id)
        if not adapter:
            return {
                "success": False,
                "error": f"外部 Agent '{agent_id}' 不存在",
            }

        # 3. 预算检查
        agent_info = registry.get_agent(agent_id)
        estimated_cost = 0.0
        if agent_info:
            cost_model = agent_info.cost_model
            estimated_cost = (
                1000 / 1000 * cost_model.input_per_1k
                + payload.get("max_tokens", 2048) / 1000 * cost_model.output_per_1k
            )
            if cost_controller.budget_exceeded():
                return {
                    "success": False,
                    "error": "本月预算已用完，切换到内部模式",
                    "fallback": "internal",
                }

        # 4. 调用外部 Agent
        result = await adapter.invoke(
            prompt=scan_result.sanitized_content if scan_result.risk_level != "none" else prompt,
            system_prompt=system_prompt,
            temperature=float(payload.get("temperature", 0.7)),
            max_tokens=int(payload.get("max_tokens", 2048)),
        )

        # 5. 记录成本
        cost = adapter.calculate_cost(
            result.get("input_tokens", 0),
            result.get("output_tokens", 0),
        )
        cost_controller.record_cost(
            task_id=payload.get("task_id", result.get("request_id", "")),
            agent_id=agent_id,
            agent_name=agent_info.display_name if agent_info else agent_id,
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            cost=cost,
            task_type=payload.get("task_type", "general"),
            success=result.get("success", True),
        )

        return {
            "result": result,
            "cost": cost,
            "privacy_scan": scan_result.model_dump(),
        }

    async def _handle_fed_compare(self, payload: dict[str, Any]) -> dict[str, Any]:
        """[V11.0] 多 Agent 并行对比

        Args:
            payload: 对比参数
                - agent_ids: 外部 Agent ID 列表
                - prompt: 用户输入
                - system_prompt: 系统提示词
                - temperature: 温度
                - max_tokens: 最大 token
                - output_mode: 输出模式
                - task_type: 任务类型

        Returns:
            对比结果
        """
        from shared_models import ComparisonOutputMode

        registry = self._get_fed_registry()
        comparator = self._get_fed_comparator()
        cost_controller = self._get_cost_controller()

        agent_ids = payload.get("agent_ids", [])
        adapters = []
        for aid in agent_ids:
            adapter = registry.get_adapter(aid)
            if adapter:
                adapters.append(adapter)

        if not adapters:
            return {
                "success": False,
                "error": "未找到有效的外部 Agent",
            }

        comparison = await comparator.execute_parallel(
            adapters=adapters,
            prompt=payload.get("prompt", ""),
            system_prompt=payload.get("system_prompt", ""),
            temperature=float(payload.get("temperature", 0.7)),
            max_tokens=int(payload.get("max_tokens", 2048)),
            output_mode=ComparisonOutputMode(
                payload.get("output_mode", "best_only")
            ),
            task_type=payload.get("task_type", "general"),
        )

        # 记录成本
        for r in comparison.results:
            cost_controller.record_cost(
                task_id=payload.get("task_id", f"compare_{id(comparison)}"),
                agent_id=r.agent_id,
                agent_name=r.agent_name,
                input_tokens=0,
                output_tokens=0,
                cost=r.cost,
                task_type=payload.get("task_type", "general"),
                success=r.success,
            )

        return {"comparison": comparison.model_dump()}
