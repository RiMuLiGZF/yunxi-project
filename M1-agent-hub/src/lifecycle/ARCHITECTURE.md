# Agent生命周期池子Agent（Lifecycle-Agent）架构文档

## 一、职责定位

Lifecycle-Agent 是云汐系统中所有Agent实例的"户籍管理器"，负责管理Agent从创建到归档的完整生命周期状态转移。它通过消息总线向集群广播状态变更事件，确保各节点对实例状态达成一致认知，并为多任务共享同一实例提供引用计数机制。

## 二、输入输出

### handle_task 支持的 intent

| intent | payload 关键字段 | 说明 |
|--------|-----------------|------|
| `lifecycle.create` | `agent_id`(str, 必填), `role`(str, 默认"executor"), `capabilities`(list[str]), `config`(dict) | 创建实例 |
| `lifecycle.activate` | `agent_id`(str, 必填) | 激活实例 |
| `lifecycle.suspend` | `agent_id`(str, 必填) | 挂起实例 |
| `lifecycle.resume` | `agent_id`(str, 必填) | 恢复实例 |
| `lifecycle.drain` | `agent_id`(str, 必填) | 优雅终止 |
| `lifecycle.terminate` | `agent_id`(str, 必填) | 强制终止 |
| `lifecycle.archive` | `agent_id`(str, 必填) | 归档实例 |
| `lifecycle.add_ref` | `agent_id`(str, 必填) | 增加引用计数 |
| `lifecycle.release_ref` | `agent_id`(str, 必填) | 释放引用计数 |
| `lifecycle.get` | `agent_id`(str, 必填) | 查询实例详情 |
| `lifecycle.list` | `state`(str, 必填) | 按状态列出实例 |
| `lifecycle.stats` | 无 | 池统计信息 |

### 公开API方法签名

```python
# 通过 handle_task 路由调用，无独立公开方法
# 内部委托给 AgentInstancePool:
#   pool.create(agent_id, role, capabilities, config) -> AgentInstance
#   pool.activate(agent_id) -> bool
#   pool.suspend(agent_id) -> bool
#   pool.resume(agent_id) -> bool
#   pool.drain(agent_id) -> bool
#   pool.terminate(agent_id) -> bool
#   pool.archive(agent_id) -> bool
#   pool.add_ref(agent_id) -> int
#   pool.release_ref(agent_id) -> int
#   pool.get_instance(agent_id) -> AgentInstance | None
#   pool.list_by_state(state) -> list[AgentInstance]
#   pool.stats() -> dict
```

## 三、核心机制

**状态机** 采用严格的有限状态转移表驱动设计，合法转移路径为：`CREATED -> ACTIVATING -> ACTIVE -> SUSPENDED -> DRAINING -> TERMINATED -> ARCHIVED`，同时支持 `ACTIVE -> DRAINING` 直达。`ARCHIVED` 和 `FAILED` 为终态，不可再转移。所有转移均通过 `_can_transition(current, target)` 静态方法校验合法性。此设计参考了 **Kubernetes Pod 生命周期状态机** 的思想。

**引用计数** 是多任务共享实例的核心保障机制。`add_ref`/`release_ref` 操作维护每个实例的引用计数，`drain` 操作在引用归零时自动转为 `TERMINATED`；`release_ref` 在 DRAINING 状态且引用归零时也会自动终止，确保优雅终止的语义正确性。`terminate`（强制终止）会直接清除引用计数。

**事件广播** 每次状态变更和引用计数变更都会通过 Bus 发布到 `lifecycle.state_change` 和 `lifecycle.ref_change` 主题，采用 `system.config_change` 消息类型，确保集群内其他Agent能实时感知实例状态变化。

## 四、协作关系

| 协作方 | 协作方式 | 说明 |
|--------|---------|------|
| Bus-Agent（agent.bus） | Bus消息发布 | 发布状态变更事件到 `lifecycle.state_change` 和引用变更到 `lifecycle.ref_change` |
| Orchestrator-Agent（agent.orchestrator） | 被调用方 | Orchestrator 请求创建执行团队时，通过Bus向 Lifecycle 发送组队请求 |

## 五、数据模型

| 类名 | 关键字段 | 说明 |
|------|---------|------|
| `AgentInstance` | `agent_id`, `role`(AgentRole), `capabilities`(list[str]), `state`(AgentLifeState), `created_at`, `activated_at`, `terminated_at`, `ref_count`(int), `config`(dict), `health`(dict), `last_heartbeat` | 单个Agent实例数据快照 |
| `AgentInstancePool` | `_instances`(dict[str, AgentInstance]), `_ref_counts`(dict[str, int]) | 实例池，集中管理所有实例 |
| `AgentLifeState` | 枚举值：CREATED/ACTIVATING/ACTIVE/SUSPENDED/DRAINING/TERMINATED/ARCHIVED/FAILED | 生命周期状态枚举 |
| `AgentRole` | 枚举值：EXECUTOR 等 | Agent角色枚举 |
| `BusMessage` | `topic`, `sender`, `msg_type`, `payload`, `trace_id` | 消息总线消息 |

## 六、测试覆盖

对应测试类 `TestLifecycleAgent`，共 **4** 个测试用例：

- `test_agent_identity` — 验证 agent_id 正确性
- `test_create_and_activate` — 验证创建+激活完整流程
- `test_suspend_resume` — 验证挂起+恢复流程
- `test_full_lifecycle` — 验证完整生命周期：create -> activate -> suspend -> drain -> terminate -> archive
- `test_instance_pool_ref_count` — 验证引用计数的增减操作正确性

另有 `TestConcurrencySafety.test_concurrent_lifecycle_ops` 覆盖并发创建+激活场景（10个Agent并发创建后并发激活）。
