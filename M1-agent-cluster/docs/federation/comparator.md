# MultiAgentComparator 多 Agent 结果对比器

## 一、组件职责

MultiAgentComparator 是联邦调度系统的"评审团"，负责对多个 Agent 的并行执行结果进行质量评分、横向对比和融合输出。它通过 `asyncio.gather` 并发调用多个适配器，收集各 Agent 的原始输出后，从正确性、完整性、可读性、代码质量四个维度进行自动化质量评分，支持三种输出模式：仅输出最优结果（BEST_ONLY）、多结果融合（FUSION）、完整对比（COMPARE），帮助用户在质量与成本之间取得最佳平衡。

## 二、核心数据结构

| 结构 | 关键字段 | 说明 |
|------|---------|------|
| `AgentResultItem` | `agent_id`, `agent_name`, `output`, `quality_score`, `cost`, `latency_ms`, `success`, `error` | 单个 Agent 的执行结果条目 |
| `MultiAgentComparison` | `results`, `best_result_index`, `fusion_output`, `output_mode`, `comparison_summary`, `total_cost` | 多 Agent 对比结果集合 |
| `QUALITY_WEIGHTS: dict` | `correctness: 0.35`, `completeness: 0.25`, `readability: 0.20`, `code_quality: 0.20` | 四维质量评分权重 |
| `ComparisonOutputMode` | 枚举：`BEST_ONLY` / `FUSION` / `COMPARE` | 输出模式枚举 |

## 三、关键方法

- **`execute_parallel(adapters, prompt, output_mode, ...)`** — 并行执行主入口：并发调用所有适配器 -> 处理异常 -> 计算质量分 -> 选出最优 -> 根据输出模式生成结果。
- **`_score_quality(output, task_type, prompt)`** — 四维度质量评分（0-100）：正确性（35%）评估长度、结构、代码块；完整性（25%）评估输入输出比、段落数；可读性（20%）评估句子长度、段落结构、列表编号；代码质量（20%，仅代码任务）评估代码块、注释、函数定义。
- **`_fuse_results(results, task_type)`** — 结果融合：以质量最高的结果为主体，补充次优结果的观点，附融合说明标注参考来源。
- **`_build_summary()`** — 生成对比摘要，包含调用数、成功数、最佳 Agent、总费用等关键指标。

## 四、依赖关系

| 依赖方 | 依赖类型 | 说明 |
|--------|---------|------|
| `federation.adapters.*` | 强依赖 | 各平台适配器，提供 `invoke()` 和 `calculate_cost()` 方法 |
| `shared_models` | 强依赖 | `MultiAgentComparison`, `AgentResultItem`, `ComparisonOutputMode` 数据模型 |
| `asyncio` | 标准库 | 并发执行多个 Agent 调用 |
| `structlog` | 工具依赖 | 结构化日志记录并行执行过程 |

调用方向：联邦调度执行层 -> `MultiAgentComparator.execute_parallel()` -> 各 Adapter.invoke()。对比结果返回给上层进行展示或进一步处理。

## 五、V11.1 改进点

1. **四维质量评分体系**：建立正确性（35%）、完整性（25%）、可读性（20%）、代码质量（20%）四维度量化评估模型，替代主观判断，为 Agent 选择提供数据支撑。
2. **代码任务专项评分**：非代码任务将代码质量权重分配给正确性，代码任务则额外检测代码块、注释、函数定义等特征，评分更贴合任务类型。
3. **三种输出模式**：`BEST_ONLY` 直接返回最优解（默认，节省 token）；`FUSION` 融合多 Agent 观点生成综合答案；`COMPARE` 完整展示所有结果供用户对比，满足不同场景需求。
4. **异常容错处理**：使用 `return_exceptions=True` 收集异常，单个 Agent 失败不影响整体执行，失败结果以 `success=False` 标记并计入对比。
5. **成本透明化**：每个结果条目包含实际调用费用，对比摘要展示总费用，帮助用户直观评估质量-成本性价比。
