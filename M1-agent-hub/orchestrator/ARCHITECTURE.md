# 任务编排子Agent（Orchestrator-Agent）架构文档

## 一、职责定位

Orchestrator-Agent 是云汐系统任务执行的核心入口，负责将用户的高层请求分解为结构化的有向无环任务图（TaskDAG），并管理DAG的全生命周期。它在系统中充当"总调度"角色，协调 Lifecycle-Agent 创建执行团队、Snapshot-Agent 记录快照、Bus-Agent 发布事件，确保任务从构建到执行的全链路贯通。

## 二、输入输出

### handle_task 支持的 intent

| intent | payload 关键字段 | 说明 |
|--------|-----------------|------|
| `orchestrate.build` | `goal`(str, 必填), `context`(dict, 可选), `available_agents`(list[dict], 可选) | 构建新DAG |
| `orchestrate.query` | `dag_id`(str) | 查询DAG详情 |
| `orchestrate.progress` | `dag_id`(str) | 获取DAG进度摘要 |
| `orchestrate.ready_tasks` | `dag_id`(str) | 获取当前可执行节点 |
| `orchestrate.update_node` | `dag_id`(str), `node_id`(str), `status`(str), `result_summary`(可选), `error`(可选) | 更新节点状态 |
| `orchestrate.scene_switch` | `old_scene`(str), `new_scene`(str), `context_handover`(dict), `involved_agents`(list), `new_scene_agents`(list) | [v2.0-LINKAGE] M4场景切换：释放旧场景资源、初始化新场景Agent组合 |

### 公开API方法签名

```python
def get_dag(dag_id: str) -> TaskDAG | None
def get_ready_tasks(dag_id: str) -> list[dict]
def update_node_status(dag_id: str, node_id: str, status: str, result_summary: str = "", error: str = "") -> bool
def get_dag_progress(dag_id: str) -> dict[str, Any]
```

## 三、核心机制

**DAG构建流程（DAGBuilder）** 采用五步流水线：复杂度评估 -> 节点规划 -> 边规划 -> Agent分配 -> DAG组装。复杂度评估基于三级关键词词典（simple/medium/complex）+ 上下文丰富度综合判定，支持通过 `context.complexity` 显式指定。此设计借鉴了 **LangGraph** 的图编排思想，将任务抽象为可组合的DAG节点。

**节点规划** 按复杂度等级生成不同规模的节点集合：simple为1-2节点顺序执行，medium为3-5节点含fan_out扇出，complex为6+节点含fan_out和条件分支（conditional_gate）。条件分支节点使用 `control` 类型边，配合 `sufficiency_check` 条件表达式，实现了类似 **CrewAI** 的条件路由能力。

**Agent分配** 采用两阶段匹配策略：优先使用节点 metadata 中的 `preferred_agent`，其次基于节点描述关键词与Agent capabilities的模糊匹配（完全匹配+3分，包含匹配+1分）。这吸收了 **AutoGen** 中能力声明与动态匹配的设计理念。

**状态流转规则** 为严格的单向流转：pending -> running -> completed/failed/skipped，确保DAG节点状态的确定性。

**M4 场景切换处理（scene_switch）** [v2.0-LINKAGE] 接收 M4 场景引擎的场景切换请求后，执行三步流程：
1. **释放旧场景资源**：遍历旧场景涉及的Agent列表，从 `_dag_registry` 中移除所有关联的活跃DAG，释放执行团队。
2. **初始化新场景组合**：根据 `new_scene_agents` 配置列表，初始化新场景所需的Agent身份与能力声明。
3. **上下文交接**：将 `context_handover` 数据传递给新场景的首个Agent，确保用户会话状态不中断。

## 四、协作关系

| 协作方 | 协作方式 | 说明 |
|--------|---------|------|
| Lifecycle-Agent（agent.lifecycle） | Bus消息 | DAG构建完成后请求创建执行团队，传递 involved_agents 列表 |
| Snapshot-Agent（agent.snapshot） | Bus消息 | DAG创建后请求记录初始状态快照 |
| Bus-Agent（agent.bus） | Bus消息 | 发布 `dag.created`、`node.status_changed` 等DAG生命周期事件到 `orchestrate.*` 主题 |

## 五、数据模型

| 类名 | 关键字段 | 说明 |
|------|---------|------|
| `TaskDAG` | `dag_id`, `root_task_id`, `goal`, `nodes`(list[dict]), `edges`(list[dict]) | 有向无环任务图 |
| `DAGNode` | `node_id`, `description`, `priority`, `status`, `dependencies`(list[str]), `assigned_agent`, `metadata` | DAG节点 |
| `DAGEdge` | `source_node`, `target_node`, `edge_type`(data/fan_out/control), `condition` | DAG边 |
| `AgentResult` | `task_id`, `trace_id`, `agent_id`, `status`, `output`, `error`, `latency_ms` | 统一返回结构 |

## 六、测试覆盖

对应测试类 `TestOrchestratorAgent`，共 **4** 个测试用例：

- `test_agent_identity` — 验证 agent_id 和 capabilities 正确性
- `test_build_dag_simple` — 验证简单任务DAG构建成功
- `test_build_dag_medium` — 验证中等复杂度任务DAG构建成功，节点数 >= 3
- `test_query_dag` — 验证先创建再查询DAG的完整流程
- `test_update_node_status` — 验证节点状态更新（pending -> completed）的正确性

另有 `TestConcurrencySafety.test_concurrent_dag_build` 覆盖并发DAG构建场景（10个并发构建请求全部成功）。

---

## 七、调度策略映射表（6 种调度策略 × 8 子Agent）

> **命名空间说明**：本章所述为 M1 调度层的 **6 种任务调度策略（STRAT-A~F）**，与 M4 业务场景层的 6 种底层执行模式（DOCUMENT/CODING/REVIEW/DESIGN/MENTAL/PLANNING）属于不同层级。M4 场景模式决定「做什么类型的事」，M1 调度策略决定「用什么方式组队执行」。两者通过 Orchestrator-Agent 的 DAG 构建器协作。

Orchestrator-Agent 作为调度总入口，根据任务特征选择不同调度策略，每种策略明确主Agent、协作子Agent、输入输出格式及路由优先级。

### 7.1 映射矩阵总表

| 调度策略 | 主Agent | 协作子Agent（≥2个） | 触发条件 | 输入格式 | 输出格式 | 路由优先级 |
|---------|--------|-------------------|---------|---------|---------|-----------|
| **STRAT-A：简单任务直调** | Orchestrator-Agent | Discovery-Agent, Bus-Agent, Budget-Agent | 单意图、无依赖、低复杂度（simple） | `{"goal": str, "task_type": str, "priority": int}` | `{"task_id": str, "result": Any, "latency_ms": int}` | P0（最高） |
| **STRAT-B：复杂任务DAG编排** | Orchestrator-Agent | Lifecycle-Agent, Snapshot-Agent, Bus-Agent, Budget-Agent | 多步骤、有依赖、中/高复杂度（medium/complex） | `{"goal": str, "context": dict, "available_agents": list}` | `{"dag_id": str, "nodes": list, "edges": list, "execution_plan": str}` | P0 |
| **STRAT-C：端云协同计算** | Discovery-Agent | Orchestrator-Agent, Bus-Agent, Snapshot-Agent | 任务涉及端云资源选择或网络状态变化 | `{"battery_pct": float, "network_available": bool, "task_complexity": float}` | `{"decision": "LOCAL_FIRST/\|AUTO/\|CLOUD_FIRST", "target_node": str, "sync_needed": bool}` | P1 |
| **STRAT-D：涉密内容处理** | Security-Agent | Orchestrator-Agent, Bus-Agent, Arbiter-Agent | 输入内容命中涉密关键词或显式标记分级 | `{"content": str, "agent_id": str, "required_clearance": str}` | `{"classification": str, "sanitized_text": str, "access_decision": "allow/\|deny", "audit_id": str}` | P0 |
| **STRAT-E：多Agent冲突仲裁** | Arbiter-Agent | Bus-Agent, Lifecycle-Agent, Snapshot-Agent | 检测到死锁、资源争用或循环依赖 | `{"conflict_type": str, "involved_agents": list[str], "resource_id": str}` | `{"arbitration_level": "AUTO_RESOLVE/\|NEGOTIATE/\|HUMAN_ESCALATE", "resolution": dict, "terminated_agents": list}` | P1 |
| **STRAT-F：断点续跑恢复** | Snapshot-Agent | Orchestrator-Agent, Lifecycle-Agent, Bus-Agent | 系统重启、Agent异常退出或手动触发恢复 | `{"snapshot_id": str, "resume_options": {"replay": bool, "replan": bool}}` | `{"restored_dag_id": str, "recovery_status": "success/\|partial/\|failed", "skipped_nodes": list}` | P1 |

### 7.2 各策略详细说明

**STRAT-A：简单任务直调**
- Orchestrator-Agent 接收用户请求后，直接委托 Discovery-Agent 查找最优Agent（能力匹配 + 最低负载）。
- Budget-Agent 在调用前执行单次请求级预算检查，不足时直接拒绝。
- Bus-Agent 将任务路由至目标Agent，等待同步返回结果。
- 无DAG构建开销，适用于单轮问答、简单工具调用等场景。

**STRAT-B：复杂任务DAG编排**
- Orchestrator-Agent 的 DAGBuilder 将目标分解为 TaskDAG，完成拓扑排序和Agent分配。
- Lifecycle-Agent 根据 `involved_agents` 列表创建执行团队，激活所需Agent实例。
- Snapshot-Agent 在DAG创建成功后记录初始状态快照，为后续断点续跑提供基线。
- Budget-Agent 在DAG构建阶段执行日/月级预算检查，在节点执行阶段执行请求级检查。

**STRAT-C：端云协同计算**
- Discovery-Agent 的 SchedulingPolicy 综合电量、网络、任务复杂度做出 LOCAL_FIRST / AUTO / CLOUD_FIRST 决策。
- Orchestrator-Agent 接收决策结果，决定后续DAG节点分配至本地Agent或云端影子Agent。
- Bus-Agent 负责本地与云端代理之间的消息路由；云端断连时将消息缓存，恢复后增量同步。
- Snapshot-Agent 在端云状态切换时同步快照，确保两端状态一致性。

**STRAT-D：涉密内容处理**
- Security-Agent 的 SecurityClassifier 对输入进行四级分级， blocked 内容直接拦截。
- Orchestrator-Agent 在收到 `access_decision=deny` 时终止后续DAG构建，返回安全拦截提示。
- Bus-Agent 对标记为 CONFIDENTIAL/TOP_SECRET 的消息执行安全路由：TOP_SECRET payload 须经 Security-Agent 字段级脱敏后方可进入传输层。
- Arbiter-Agent 处理涉密传输中的安全异常（如未授权降级、标记篡改），触发三级仲裁。

**STRAT-E：多Agent冲突仲裁**
- Arbiter-Agent 的 WaitForGraph 检测死锁环，ArbitrationEngine 按 AUTO_RESOLVE → NEGOTIATE → HUMAN_ESCALATE 三级策略裁决。
- Bus-Agent 广播仲裁结果到所有涉事Agent，确保全局状态一致性。
- Lifecycle-Agent 执行仲裁决议中的Agent终止或降级操作。
- Snapshot-Agent 记录仲裁前的全量状态，支持仲裁回滚。

**STRAT-F：断点续跑恢复**
- Snapshot-Agent 从快照链中恢复最近的可用检查点，验证 SHA256 完整性。
- Orchestrator-Agent 根据恢复后的状态决定重放（replay）或重规划（replan）：若原DAG结构完整则重放，若节点Agent已失效则重规划。
- Lifecycle-Agent 重新创建失效的Agent实例，恢复引用计数和状态机。
- Bus-Agent 恢复事件流，补发断点期间的未投递消息。
