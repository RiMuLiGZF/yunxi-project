# 死锁仲裁子Agent（Arbiter-Agent）架构文档

## 一、职责定位

Arbiter-Agent 是云汐系统的"纠纷调解员"，负责检测和解决Agent间的资源竞争与死锁问题。它维护一张Agent等待关系图（WaitForGraph），通过DFS环检测发现死锁，并采用三级仲裁策略（自动解决 -> 协商解决 -> 人工介入）逐步升级处理无法自动化解的冲突。

## 二、输入输出

### handle_task 支持的 intent

| intent | payload 关键字段 | 说明 |
|--------|-----------------|------|
| `arbiter.check_deadlock` | 无 | 检测当前等待图中的死锁环 |
| `arbiter.arbitrate` | `conflict_type`(str, 必填), `involved_agents`(list[str], 必填), `task_ids`(list[str]), `context`(dict) | 发起仲裁 |
| `arbiter.update_wait_for` | `waiter`(str, 必填), `holder`(str, 必填) | 添加等待关系 |
| `arbiter.resolve_wait_for` | `waiter`(str, 必填), `holder`(str, 必填) | 解除等待关系 |
| `arbiter.status` | 无 | 获取仲裁系统状态 |
| `arbiter.history` | `limit`(int, 默认100) | 获取仲裁历史 |

### 公开API方法签名

```python
async def check_deadlock() -> list[list[str]]
def arbitrate(conflict_type: str, involved_agents: list[str], task_ids: list[str], context: dict[str, Any]) -> ArbitrationResult
async def update_wait_for(waiter: str, holder: str) -> None
async def resolve_wait_for(waiter: str, holder: str) -> None
async def get_status() -> dict[str, Any]
```

## 三、核心机制

**等待图与环检测（WaitForGraph）** 使用有向图维护Agent间的资源等待关系，每条边表示 waiter 等待 holder。环检测采用经典的DFS + 三色标记算法（WHITE未访问、GRAY在路径上、BLACK已完成），在GRAY节点发现回边即判定为环。图使用 asyncio.Lock 保证并发安全，同时维护正向边（waiter -> holder）和反向边（holder -> waiter）双向索引。此设计借鉴了操作系统中的 **资源分配图（RAG）死锁检测** 算法。

**三级仲裁引擎（ArbitrationEngine）** 按优先级逐级尝试解决冲突：

1. **自动解决（AUTO_RESOLVE）**：针对不同冲突类型采用不同策略。`timeout` 冲突取消超时Agent的等待；`resource_deadlock` 取消优先级最低的Agent（受害者选择），资源分配给高优先级Agent；`priority_conflict` 按优先级排序后高优先级先执行，低优先级延迟重试；`dependency_cycle` 取消环中最后加入的Agent以打断环。此设计参考了 **AutoGen** 中多Agent冲突解决的优先级策略。

2. **协商解决（NEGOTIATE）**：检查是否有替代资源进行重路由；对于优先级冲突采用老化策略（aging），等待时间越长优先级越高（每30秒+1，上限10）。

3. **人工介入（HUMAN_ESCALATE）**：生成详细报告包含所有涉及Agent的状态、等待时间、任务ID和资源信息，附带处理建议。所有仲裁结果记录到历史中，支持查询与统计。

## 四、协作关系

| 协作方 | 协作方式 | 说明 |
|--------|---------|------|
| Lifecycle-Agent（agent.lifecycle） | Bus消息 | Lifecycle 管理实例状态变更时可能触发等待关系更新 |
| Orchestrator-Agent | Bus消息 | Orchestrator 管理DAG节点依赖时可能涉及资源等待 |
| Bus-Agent（agent.bus） | Bus消息 | 仲裁结果可通过Bus广播到涉及Agent |

## 五、数据模型

| 类名 | 关键字段 | 说明 |
|------|---------|------|
| `WaitForGraph` | `_edges`(dict[str, set[str]]), `_reverse_edges`(dict[str, set[str]]), `_lock`(asyncio.Lock) | 等待关系图 |
| `ArbitrationRequest` | `request_id`, `conflict_type`, `involved_agents`(list[str]), `task_ids`(list[str]), `context`(dict) | 仲裁请求 |
| `ArbitrationResult` | `request_id`, `level`(ArbitrationLevel), `decision`(str), `assigned_agent`, `reason`, `actions`(list[dict]) | 仲裁结果 |
| `ArbitrationLevel` | 枚举值：AUTO_RESOLVE/NEGOTIATE/HUMAN_ESCALATE | 仲裁级别枚举 |

## 六、测试覆盖

对应测试类 `TestArbiterAgent`，共 **6** 个测试用例：

- `test_agent_identity` — 验证 agent_id 正确性
- `test_no_deadlock` — 验证空图中无死锁
- `test_deadlock_detection` — 验证 a->b->c->a 环被检测到
- `test_arbitrate_resource_deadlock` — 验证资源死锁仲裁返回非空决策
- `test_arbitration_engine_timeout` — 验证超时冲突在level1自动解决（decision="abort"）
- `test_update_wait_for` — 验证添加等待关系后边数正确
- `test_resolve_wait_for` — 验证解除等待关系后边数为0

另有 `TestConcurrencySafety.test_concurrent_deadlock_detection` 覆盖并发死锁检测场景（多个不相关等待 + 环检测）。
