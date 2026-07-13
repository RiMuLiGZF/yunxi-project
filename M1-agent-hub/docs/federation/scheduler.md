# FederatedScheduler 联邦调度决策器

## 一、组件职责

FederatedScheduler 是联邦调度系统的"大脑"，负责决定每一个任务应该由内部 Agent 集群执行还是路由到外部 Agent 执行，以及具体选择哪个外部 Agent。决策过程遵循"隐私红线优先、能力匹配其次、成本效益最优"的原则，通过五因素加权评分模型对候选 Agent 进行综合排序，并结合预算约束输出可解释的决策结果。同时提供降级备选方案（fallback），确保首选不可用时的业务连续性。

## 二、核心数据结构

| 结构 | 关键字段 | 说明 |
|------|---------|------|
| `FederationDecision` | `use_external`, `selected_agent_id`, `decision_reason`, `estimated_cost`, `privacy_check`, `quality_score`, `fallback_agent_id` | 调度决策结果（Pydantic Model） |
| `FACTOR_WEIGHTS: dict` | `privacy: 0.30`, `capability: 0.25`, `preference: 0.20`, `cost: 0.15`, `speed: 0.10` | 五因素决策权重配置 |
| `_registry` | ExternalAgentRegistry 实例 | 外部 Agent 注册表引用 |
| `_internal_coverage: float` | 默认 0.7 | 内部 Agent 能力覆盖率基线 |

## 三、关键方法

- **`decide(task_type, security_level, user_preference, remaining_budget, ...)`** — 核心决策入口，执行六步决策流程：隐私红线检查 -> 内部能力评估 -> 获取候选 -> 五因素评分排序 -> 内外部对比 -> 预算校验，最终返回 `FederationDecision`。
- **`_score_candidate()`** — 五因素加权评分：隐私分（30%）按 Agent 隐私等级打分；能力分（25%）基于 quality_rating + 任务类型匹配；偏好分（20%）随用户模式（质量/成本/速度/平衡）动态调整；成本分（15%）结合剩余预算比例；速度分（10%）基于 response_speed。
- **`_check_privacy()`** — 隐私红线判定：TOP_SECRET 级直接阻断（blocked），CONFIDENTIAL 级预警（warning），其余通过（passed）。
- **`_estimate_cost()`** — 成本预估：按输入 1000 token + 输出 500~2000 token（随复杂度线性增长）粗略估算调用费用。
- **`_build_reason()`** — 生成可解释的决策理由文本，便于用户理解调度依据。

## 四、依赖关系

| 依赖方 | 依赖类型 | 说明 |
|--------|---------|------|
| `ExternalAgentRegistry` | 强依赖 | 查询可用外部 Agent 列表、获取 Agent 能力画像 |
| `shared_models` | 强依赖 | `FederationDecision`, `UserPreferenceMode`, `SecurityClassification` 等 |
| `CostController` | 间接依赖 | 决策时传入 `remaining_budget` 进行预算校验 |
| `structlog` | 工具依赖 | 结构化日志记录每次决策过程 |

调用方向：调度入口 / Orchestrator -> `FederatedScheduler.decide()` -> `ExternalAgentRegistry.list_agents()`。决策结果输出给执行层，用于选择实际调用的 Agent。

## 五、V11.1 改进点

1. **五因素加权决策模型**：从单一成本/能力判断升级为隐私（30%）、能力（25%）、偏好（20%）、成本（15%）、速度（10%）五维度综合评分，决策更全面。
2. **用户偏好模式适配**：支持 `QUALITY_FIRST` / `COST_FIRST` / `SPEED_FIRST` / `BALANCED` 四种偏好模式，动态调整各因素权重分配逻辑。
3. **预算感知调度**：决策流程中嵌入预算检查步骤，若 Top1 候选超预算则自动寻找下一个预算内候选，全部超预算则降级到内部执行，避免超支。
4. **可解释决策理由**：每次决策均生成人类可读的 `decision_reason`，说明选择依据（如"质量优先模式，该 Agent 评分 4.8/5 为最高"），提升透明度。
5. **降级备选机制**：决策结果包含 `fallback_agent_id` 字段，标注第二优候选，支持上层在首选失败时快速切换。
