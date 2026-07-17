# 预算管控子Agent（Budget-Agent）架构文档

## 一、职责定位

Budget-Agent 是云汐系统的"成本守门员"，负责Token预算的多级管控（请求级/会话级/日级/月级），提供成本感知的模型选择、使用量记录与成本估算、超预算熔断以及成本预警能力。它在系统中防止LLM调用成本失控，并为任务调度提供经济最优的模型推荐。

## 二、输入输出

### handle_task 支持的 intent

| intent | payload 关键字段 | 说明 |
|--------|-----------------|------|
| `budget.check` | `level`(str, 默认"daily"), `model`(str), `projected_cost`(float) | 检查预算是否充足 |
| `budget.record` | `model`(str), `input_tokens`(int), `output_tokens`(int), `agent_id`(str), `latency_ms`(float) | 记录使用量 |
| `budget.select_model` | `task_complexity`(str, 默认"medium"), `preferred_model`(str) | 成本感知模型选择 |
| `budget.alerts` | 无 | 获取成本预警列表 |
| `budget.circuit` | 无（使用 task_id 幂等） | 超预算熔断检查 |
| `budget.report` | 无 | 获取预算报告 |

### 公开API方法签名

```python
def check_budget(level: BudgetLevel, model: str = "", projected_cost: float = 0.0) -> tuple[bool, float, float]
def record_usage(model: str, input_tokens: int, output_tokens: int, agent_id: str = "") -> dict[str, Any]
def select_model(task_complexity: str) -> str
def get_alerts() -> list[dict[str, Any]]
def enforce_circuit(task_id: str) -> bool
def get_budget_report() -> dict[str, Any]
```

## 三、核心机制

**多级预算管控** 支持四级预算粒度：REQUEST（单次请求）、SESSION（会话）、DAILY（日预算，默认$100）、MONTHLY（月预算，默认$1000）。每级预算独立检查，任一级超支即判定为不足。此设计借鉴了 **Claude Code** 的 token budget 分级控制思想。

**成本感知模型选择** 根据任务复杂度（low/medium/high）和当前预算余量，推荐最具成本效益的模型。在预算充裕时选择高质量模型，预算紧张时自动降级为经济模型。

**超预算熔断** 采用幂等机制，每个 task_id 仅触发一次熔断。检查 REQUEST/DAILY/MONTHLY 三级预算，任一耗尽即触发熔断。熔断后该任务的所有后续LLM调用将被拦截。

**三级成本预警** 按预算使用率生成不同级别的预警：70% 为 info 级别、90% 为 warning 级别、100% 为 critical 级别。日预算和月预算分别独立预警。

**M1-M2 Token 预算分工** 明确模块间预算职责边界：
- **M1（Budget-Agent）负责全局配额分配**：维护 REQUEST/SESSION/DAILY/MONTHLY 四级预算总池，根据任务优先级、Agent负载、历史消耗趋势进行全局配额调度。
- **M2（SkillExecutor）负责单技能消耗**：每个 Skill 调用前须向 M1 申请配额（概念级描述：通过 `budget.request_quota` intent 提交预估消耗，M1 返回授权额度与有效期）。M2 不得独立执行熔断决策；当单技能消耗触及预警阈值时，须通过 `budget.report_alert` intent 向 M1 上报预算告警，由 M1 统一判定是否触发全局熔断或调度降级。
- **配额申请流程（概念级）**：M2 在调用 LLM 或外部工具前，先通过 Bus-Agent 发送配额申请 → M1 Budget-Agent 检查全局预算池 → 返回授权结果（approve/deny/defer）→ M2 在授权额度内执行 → 执行完成后上报实际消耗。此流程确保预算管控中心化，避免各模块独立熔断导致全局状态不一致。

## 四、协作关系

| 协作方 | 协作方式 | 说明 |
|--------|---------|------|
| Snapshot-Agent（agent.snapshot） | 共享数据 | 快照中包含 budget_snapshot，用于断点续跑时恢复预算状态 |
| Orchestrator-Agent | 被调用方 | Orchestrator 在任务执行前检查预算，超预算时拒绝创建DAG |
| M2 SkillExecutor | 跨模块协作 | M2 调用前向 M1 申请配额，执行后上报实际消耗；M2 不独立熔断，统一由 M1 裁决 |

## 五、数据模型

| 类名 | 关键字段 | 说明 |
|------|---------|------|
| `BudgetLevel` | 枚举值：REQUEST/SESSION/DAILY/MONTHLY | 预算级别枚举 |
| `BudgetManager` | `daily_budget`, `monthly_budget`, `request_budget`, `enable_routing` | 底层预算管理中心 |
| 使用记录 | `timestamp`, `model`, `agent_id`, `input_tokens`, `output_tokens`, `estimated_cost`, `latency_ms` | LLM使用记录 |
| 熔断缓存 | `_circuit_triggered`(dict[str, bool]) | 已触发熔断的task_id集合 |

## 六、测试覆盖

对应测试类 `TestBudgetAgent`，共 **5** 个测试用例：

- `test_agent_identity` — 验证 agent_id 正确性
- `test_check_budget_available` — 验证预算充足时返回 True
- `test_record_usage` — 验证使用量记录后 model 和 token 数正确
- `test_select_model` — 验证模型选择返回非空结果
- `test_budget_report` — 验证预算报告包含 daily_budget 字段
