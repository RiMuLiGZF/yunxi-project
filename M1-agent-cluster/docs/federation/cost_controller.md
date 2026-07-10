# CostController 成本控制器

## 一、组件职责

CostController 是联邦调度系统的"财务管家"，负责外部 Agent 调用的全链路成本管控。核心功能包括：月度预算设置与剩余预算查询、每次调用的实时扣费与记录、三级预算告警（50%/80%/100%）、超预算自动熔断、以及账单明细查询与日级统计。它确保联邦调度在预算可控范围内运行，当预算耗尽时自动切换到内部模式，防止意外超支，同时提供完整的消费审计追溯能力。

## 二、核心数据结构

| 结构 | 关键字段 | 说明 |
|------|---------|------|
| `FederationBudget` | `monthly_budget`, `spent_this_month`, `alert_threshold_50/80/100`, `currency`, `last_reset_month` | 月度预算状态（Pydantic Model） |
| `CostRecord` | `record_id`, `task_id`, `agent_id`, `input_tokens`, `output_tokens`, `cost`, `currency`, `task_type`, `success` | 单条消费记录 |
| `_records: list[CostRecord]` | 按时间追加 | 消费记录列表，支持多维度筛选查询 |
| `_budget: FederationBudget` | 月度预算实例 | 当前预算状态，跨月自动重置 |

## 三、关键方法

- **`record_cost(task_id, agent_id, cost, ...)`** — 记录一次调用费用，成功调用才计入已花费金额，同时触发阈值检查，自动更新告警状态。
- **`set_monthly_budget(amount)`** — 设置月度预算金额，立即重新计算告警状态，返回当前预算全景。
- **`remaining_budget()`** / **`budget_exceeded()`** — 查询剩余预算和是否超支，供调度决策时调用。
- **`_check_thresholds()`** — 三级阈值告警：50% 提示信息、80% 警告、100% 严重并触发熔断，每级仅首次触发时记录日志。
- **`get_records(agent_id, start_time, end_time, task_type, limit)`** — 多维度账单查询，支持按 Agent、时间范围、任务类型筛选，按时间倒序返回。
- **`get_daily_summary(days)`** — 按日聚合统计，返回最近 N 天的每日总费用、调用次数、涉及 Agent 列表。
- **`_ensure_month_reset()`** — 月度自动重置：跨月时清零已花费金额和告警标志，记录重置日志。

## 四、依赖关系

| 依赖方 | 依赖类型 | 说明 |
|--------|---------|------|
| `shared_models` | 强依赖 | `CostRecord`, `FederationBudget` 数据模型 |
| `FederatedScheduler` | 双向协作 | Scheduler 传入 `remaining_budget` 做预算感知决策；执行层调用 CostController 扣费 |
| `structlog` | 工具依赖 | 结构化日志记录消费、告警、重置事件 |
| `time` / `uuid` | 标准库 | 时间戳、记录 ID 生成 |

调用方向：执行层（调用外部 Agent 后）-> `CostController.record_cost()`；调度器 -> `CostController.remaining_budget()`；管理端 -> `get_records()` / `get_daily_summary()`。

## 五、V11.1 改进点

1. **三级预算告警机制**：建立 50%（info）、80%（warning）、100%（critical）三级渐进式告警，每级仅首次触发时记录，避免告警风暴，100% 时自动切换内部模式。
2. **月度自动重置**：基于 `last_reset_month` 字段实现跨月自动清零，无需手动重置，同时重置所有告警标志。
3. **多维度账单查询**：支持按 Agent ID、时间范围、任务类型组合筛选，默认按时间倒序返回，满足审计和对账需求。
4. **日级消费统计**：`get_daily_summary()` 按天聚合总费用、调用次数、涉及 Agent，便于观察消费趋势和异常波动。
5. **成功才计费**：只有调用成功（`success=True`）的记录才计入 `spent_this_month`，失败调用不扣预算，计费逻辑更合理。
