# 状态快照与断点续跑子Agent（Snapshot-Agent）架构文档

## 一、职责定位

Snapshot-Agent 是云汐系统的"时光机"，负责捕获Agent集群在任务执行过程中的完整状态快照，支持从任意快照点断点续跑。它以链式结构管理同一任务的多次快照，通过SHA256校验和保证数据完整性，并提供过期清理机制防止存储膨胀。

## 二、输入输出

### handle_task 支持的 intent

| intent | payload 关键字段 | 说明 |
|--------|-----------------|------|
| `snapshot.create` | `task_id`(str, 必填), `dag_id`(str), `node_states`(list[dict]), `agent_states`(list[dict]), `budget_snapshot`(dict) | 创建快照 |
| `snapshot.restore` | `snapshot_id`(str, 必填) | 恢复到指定快照点 |
| `snapshot.chain` | `task_id`(str, 必填) | 获取任务快照链 |
| `snapshot.verify` | `snapshot_id`(str, 必填) | 校验快照完整性 |
| `snapshot.cleanup` | `task_id`(str, 必填), `max_age_seconds`(float, 默认3600) | 清理旧快照 |
| `snapshot.stats` | 无 | 存储统计 |

### 公开API方法签名

```python
def create(task_id: str, dag_id: str, context: dict[str, Any]) -> SnapshotEntry
def restore(snapshot_id: str) -> dict[str, Any] | None
def get_chain(task_id: str) -> list[dict[str, Any]]
def verify(snapshot_id: str) -> bool
def cleanup(task_id: str, max_age: float) -> int
```

## 三、核心机制

**链式快照存储** 每次创建快照时自动关联前序快照的 snapshot_id（parent_id），形成按时间排列的链式结构。同一任务的所有快照通过 `_chains` 字典（task_id -> [snapshot_id...]）索引，支持完整链遍历和差异比较。此设计参考了 **LangGraph** 的 checkpoint 机制，但增加了 parent_id 链式关联以支持更精细的版本追溯。

**SHA256完整性校验** 每次创建快照时，对 task_id、dag_id、node_states、agent_states、budget_snapshot 五个字段进行 JSON 序列化（sort_keys=True, ensure_ascii=False），计算SHA256摘要。恢复前强制校验完整性，校验失败则拒绝恢复。

**差异比较（SnapshotChain.diff）** 支持比较任意两个快照之间的差异，以ID为key匹配节点状态和Agent状态，输出 added/removed/modified 变更列表，以及预算变化明细。

**过期清理** 按最大存活时间清理旧快照，但始终保留最新快照不被删除。清理后自动更新快照链索引。

## 四、协作关系

| 协作方 | 协作方式 | 说明 |
|--------|---------|------|
| Orchestrator-Agent（agent.orchestrator） | Bus消息 | Orchestrator DAG创建后请求Snapshot记录初始快照 |
| Budget-Agent（agent.budget） | 共享数据 | 快照中包含 budget_snapshot，用于断点续跑时恢复预算状态 |
| Lifecycle-Agent（agent.lifecycle） | 共享数据 | 快照中包含 agent_states，用于断点续跑时恢复实例状态 |

## 五、数据模型

| 类名 | 关键字段 | 说明 |
|------|---------|------|
| `SnapshotEntry` | `snapshot_id`(UUID), `task_id`, `dag_id`, `node_states`(list[dict]), `agent_states`(list[dict]), `budget_snapshot`(dict), `timestamp`, `checksum`(SHA256), `parent_id` | 单次快照条目 |
| `SnapshotStore` | `_snapshots`(dict[str, SnapshotEntry]), `_chains`(dict[str, list[str]]) | 快照存储 |
| `SnapshotChain` | `_store`(SnapshotStore), `_task_id`(str) | 快照链便捷操作包装 |

## 六、测试覆盖

对应测试类 `TestSnapshotAgent`，共 **4** 个测试用例：

- `test_agent_identity` — 验证 agent_id 正确性
- `test_create_snapshot` — 验证快照创建后 checksum 非空
- `test_snapshot_chain` — 验证同一任务创建两次快照后链长度为2
- `test_store_integrity` — 验证SHA256完整性校验通过
- `test_store_prune` — 验证过期清理至少清理1条

另有 `TestConcurrencySafety.test_concurrent_snapshot` 覆盖并发快照创建场景（20次并发创建后链长度正确）。
