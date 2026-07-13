# 模块01-多Agent集群调度-产物归档摘要-V10.1-REV1

> 文档编号：M1-ARCH-V10.1-REV1
> 版本：V10.1-REV1
> 日期：2026-07-03
> 状态：V10.1 定向改进完成（4项改进：命名空间/场景命名对齐/偏好持久化/流式润色）
> 评审依据：STD-M4-MODE-20250630 v2.6.1（M4 六大底层执行模式体系标准）

---

## 1. 模块基础信息

| 属性 | 内容 |
|------|------|
| 模块名称 | 模块1 — 多Agent集群调度架构 |
| 模块定位 | 系统中央调度底座，只负责全局管控，不承接业务落地 |
| 当前版本 | V10.0 |
| 上一版本 | V9.9 |
| 完成度 | 100%（14项核心功能全部落地） |
| 代码规模 | 约60个Python源文件，70+测试文件 |
| 开发语言 | Python 3.11+ |
| 核心依赖 | pydantic, asyncio, aiohttp, cryptography, structlog, fastapi |
| 架构模式 | 8专属子Agent + A2A协议通信 + 分身池管理 |
| 测试框架 | pytest, pytest-asyncio, pytest-cov |
| 覆盖率目标 | 总体≥80%（分批全量验证81%，V10新增模块覆盖86%+） |

### 1.1 版本变更记录（V9.9 → V10.0）

| # | 变更类别 | 变更内容 | 影响范围 |
|---|---------|---------|---------|
| 1 | 架构重构 | 七层委托链（V2→V9）重构为8专属子Agent + A2A协议通信 | 全部调度逻辑 |
| 2 | 新增组件 | Orchestrator-Agent：TaskDAG构建、拓扑排序、Agent能力匹配 | orchestrator/ |
| 3 | 新增组件 | Lifecycle-Agent：八态状态机、引用计数、优雅终止 | lifecycle/ |
| 4 | 新增组件 | Discovery-Agent：四维负载评分、端云调度决策树 | discovery/ |
| 5 | 新增组件 | Bus-Agent：A2A消息路由、优先级队列、DLQ管理、MCP适配 | bus/ |
| 6 | 新增组件 | Snapshot-Agent：增量快照链、SHA256校验、断点续跑 | snapshot/ |
| 7 | 新增组件 | Budget-Agent：滚动窗口预算、熔断、成本预警、M1-M2预算分工 | budget/ |
| 8 | 新增组件 | Security-Agent：四级涉密分级、权限域隔离、审计留痕、高涉密传输保护 | security/ |
| 9 | 新增组件 | Arbiter-Agent：Wait-For图、三级仲裁、人工介入 | arbiter/ |
| 10 | 新增组件 | ClonePool：四种临时分身、最小信息下发、自动销毁 | pool/ |
| 11 | 新增数据模型 | TaskDAG、DAGNode、DAGEdge、AgentLifeState、SecurityClassification等 | shared_models.py |
| 12 | 接口补全 | 补全4个缺失标准HTTP接口（DELETE/status/query_status/bus_publish） | api/server.py |
| 13 | 接口封装 | FastAPI HTTP封装层，M1为submit_task唯一入口 | api/server.py |
| 14 | 硬件联动 | 硬件健康探测、断连缓存、降级策略、批量补发 | task_dispatcher.py |
| 15 | 职责剥离 | VectorMemory/PluginLoader/MCPServer标记DEPRECATED，明确迁移边界 | 相应文件 |
| 16 | 职责剥离 | LLMProvider推理剥离标记，保留InferenceRouter路由决策 | llm_provider.py |
| 17 | 测试新增 | 62个V10.0全量子Agent测试（含4个并发安全测试） | tests/test_v10_subagents.py |
| 18 | 文档新增 | 8份子Agent架构文档 + 1份总体回流文档 + 场景映射表 | 各子目录ARCHITECTURE.md |
| 19 | API新增 | 分身池HTTP API（POST/GET /v1/pool/*） | api/server.py |
| 20 | 缺陷修正 | C5/C1/C3/C4/C2/I1 六项缺陷全部关闭 | 详见附录A |
| 21 | [v2.0-LINKAGE] A2A涉密标记 | AgentTask / BusMessage 增加 `security_classification` 字段；Bus-Agent 自动传递并升级M5消息为绝密 | interfaces.py / bus/agent.py |
| 22 | [v2.0-LINKAGE] API入参补全 | `submit_task` 增加 `budget` 入参；响应增加 `trace_id` / `agents_deployed` / `budget_consumed` | api/server.py |
| 23 | [v2.0-LINKAGE] 场景切换 | Orchestrator-Agent 增加 `orchestrate.scene_switch` 意图，支持M4场景切换：释放旧场景资源、初始化新场景Agent组合、上下文交接 | orchestrator/agent.py |
| 24 | **[v1.0-VOICE] 云汐人格润色Agent** | 新增 YunxiVoice-Agent（第9个子Agent）：五维人格参数、六场景语气偏移、质量自检流水线、红线违规检测、MENTAL场景涉密保护 | voice/agent.py + voice/ARCHITECTURE.md |
| 25 | **[v1.0-VOICE] 润色调度接入** | Orchestrator-Agent 增加 `orchestrate.voice_polish` 意图，懒加载 YunxiVoice-Agent，支持失败降级（润色失败返回原始内容） | orchestrator/agent.py |
| 26 | **[V10.1-改进2] 命名空间区分** | M1内部6种「模式」重命名为「调度策略」（STRAT-A~F），5.3节增加边界澄清说明，Orchestrator ARCHITECTURE.md同步更新，与M4业务模式命名空间彻底隔离 | docs/ + orchestrator/ARCHITECTURE.md |
| 27 | **[V10.1-改进1] 场景命名对齐** | YunxiVoice重构为两层命名体系（6底层模式+6上层场景=12组配置），新增M4ExecutionMode/UserScene/SchedulingStrategy枚举和命名映射表，voice.polish支持模式名/场景名双输入 | shared_models.py + voice/agent.py |
| 28 | **[V10.1-改进4] 偏好持久化** | 新增voice.update_preference接口，PersonalityPreference数据模型，M5潮汐记忆L2层存储方案，CONFIDENTIAL级隐私规则，增量更新+本地缓存 | shared_models.py + voice/agent.py |
| 29 | **[V10.1-改进3] 流式润色方案** | /chat/stream新增voice_polish参数（默认true），定义流畅模式（按句子缓冲）/极速模式（跳过润色）/500ms自动降级规则，Token单独计量 | api/server.py + docs/ |

---

## 2. Agent编制清单

### 2.1 主Agent

| Agent名称 | Agent ID | 职责 |
|-----------|----------|------|
| OrchestratorV9 | orchestrator_v9 | 统一编排入口（V9基线保留，向后兼容） |

### 2.2 9个专属子Agent（V10.0 + v1.0-VOICE）

| # | 子Agent名称 | Agent ID | 职责定位 | 目录 |
|---|-------------|----------|---------|------|
| 1 | Orchestrator-Agent | agent.orchestrator | DAG构建、任务解析、拓扑排序、Agent能力匹配、**调度策略**映射、人格润色调度 | `orchestrator/` |
| 2 | Lifecycle-Agent | agent.lifecycle | Agent全生命周期管理（CREATED→ARCHIVED八态状态机）、引用计数、优雅终止 | `lifecycle/` |
| 3 | Discovery-Agent | agent.discovery | 注册发现、反向索引O(1)、VRAM/CPU/电量/网络综合评分、端云调度决策 | `discovery/` |
| 4 | Bus-Agent | agent.bus | A2A消息路由、优先级队列、死信队列管理、消息格式转换、MCP协议桥接 | `bus/` |
| 5 | Snapshot-Agent | agent.snapshot | 增量快照、快照链、SHA256完整性校验、断点续跑 | `snapshot/` |
| 6 | Budget-Agent | agent.budget | 滚动窗口预算（15min/1h/24h）、熔断、成本预警、M1-M2预算分工 | `budget/` |
| 7 | Security-Agent | agent.security | Prompt注入检测、PII脱敏、涉密四级分级、权限域隔离、审计留痕、高涉密传输保护 | `security/` |
| 8 | Arbiter-Agent | agent.arbiter | Wait-For图死锁检测、DFS环检测、三级冲突仲裁、人工介入 | `arbiter/` |
| 9 | **YunxiVoice-Agent** | **agent.yunxi_voice** | **云汐人格润色输出：六场景语气偏移、质量自检、红线检测、MENTAL涉密保护** | **`voice/`** |

### 2.3 分身池（V10.0新增）

| 组件 | 目录 | 职责 |
|------|------|------|
| ClonePool | `pool/` | 勘探/规划/撰写/审查四种临时分身，按需生成、最小信息下发、自动销毁 |

---

## 3. 已落地功能清单

| # | 核心功能 | 实现状态 | 负责子Agent | 测试覆盖 |
|---|---------|---------|------------|---------|
| 1 | 全局任务编排：接收上层请求，生成DAG形式的多Agent协作任务图 | 已落地 | Orchestrator-Agent | DAG构建/拓扑排序/关键路径/并行检测 |
| 2 | 全Agent生命周期管理：创建/激活/挂起/恢复/终止/回收，含引用计数和优雅终止 | 已落地 | Lifecycle-Agent | 八态状态机/引用计数/优雅终止 |
| 3 | Agent注册发现：反向索引O(1)注册表，动态加入/退出，健康检查 | 已落地 | Discovery-Agent | 注册/注销/发现/健康检查 |
| 4 | 动态组队：按任务类型和Agent能力画像自动组建执行团队 | 已落地 | Orchestrator-Agent + Discovery-Agent | DAG节点Agent分配/能力匹配 |
| 5 | 负载均衡：综合VRAM/CPU/电量/网络评分，LOCAL_FIRST/AUTO/CLOUD_FIRST决策树 | 已落地 | Discovery-Agent | 四维评分/决策树/端云切换 |
| 6 | A2A通信协议适配：消息格式/序列化/签名/端到端加密/优先级总线/死信队列 | 已落地 | Bus-Agent | 消息路由/优先级/DLQ/MCP桥接 |
| 7 | 前置输入风控安检：Prompt注入检测、PII识别、恶意指令过滤 | 已落地 | Security-Agent | 注入检测/PII脱敏/恶意过滤 |
| 8 | 算力/Token预算管控：滚动窗口（15min/1h/24h）+ 超预算熔断 + 成本预警 | 已落地 | Budget-Agent | 预算检查/熔断/预警/配额申请 |
| 9 | 死循环/无限交互防护：调用深度计数、递归检测、循环依赖分析、超时中断 | 已落地 | Arbiter-Agent + LedgerEngine | 死锁检测/环检测/仲裁 |
| 10 | 任务账本快照：全生命周期状态变更记录，支持任意时刻回溯 | 已落地 | Snapshot-Agent + LedgerEngine | 快照创建/链式存储/完整性校验 |
| 11 | 断点续跑与重规划：从快照恢复或自动重规划执行路径 | 已落地 | Snapshot-Agent + Orchestrator-Agent | 恢复/重规划 |
| 12 | 涉密信息隔离审计：四级分级（公开/内部/机密/绝密）+ 操作日志留痕 | 已落地 | Security-Agent | 分级/权限预检/审计日志 |
| 13 | 临时分身池管理：勘探/规划/撰写/审查四种分身，按需生成、最小信息下发、自动销毁 | 已落地 | ClonePool | 分身创建/释放/配额/清理 |
| 14 | 端云协同调度：云端影子代理映射、算力自动分流、离线任务缓存、重连增量同步 | 已落地 | Discovery-Agent + TaskDispatcher | 端云决策/离线缓存/重连补发 |
| 15 | **云汐人格润色输出**：六场景语气偏移、五维人格参数、质量自检、红线检测、MENTAL涉密保护 | **已落地（v1.0-VOICE）** | **YunxiVoice-Agent + Orchestrator-Agent** | **人格润色/场景偏移/质量校验/红线检测** |

---

## 4. 对外对接接口总表

### 4.1 RESTful HTTP API（模块1对外暴露）

| 方法 | 路径 | 功能 | 入参 | 出参 | 状态 |
|------|------|------|------|------|------|
| POST | /api/v1/tasks/submit | 提交任务（M1唯一入口） | user_input, task_id, trace_id, model, **budget**(dict), input_tokens, output_tokens, priority, metadata | status, task_id, result, **trace_id**, **agents_deployed**, **budget_consumed** | 已实现 |
| POST | /api/v1/agents/register | 注册Agent | agent_info | success | 已有 |
| DELETE | /api/v1/agents/{id} | 注销Agent | - | status, action | 已实现 |
| GET | /api/v1/agents/{id}/status | 查询Agent状态 | - | agent_id, registered, version, capabilities, health | 已实现 |
| GET | /api/v1/tasks/{id}/status | 查询任务状态 | - | task_id, goal, status, completion_rate, plans, agents, active | 已实现 |
| POST | /api/v1/bus/publish | 消息总线发布 | topic, payload, sender, recipient, msg_type, priority, ttl, trace_id | status, msg_id, topic | 已实现 |
| POST | /api/v1/chat | 同步对话 | user_input, trace_id | 对话结果 | 已有 |
| POST | /api/v1/chat/stream | SSE流式对话 | user_input, trace_id, **voice_polish**(bool, 默认true) | SSE流 | 已有（V10.1新增voice_polish参数） |
| GET | /health | 存活检查 | - | {status} | 已有 |
| GET | /ready | 就绪检查 | - | {status} | 已有 |
| GET | /metrics | Prometheus指标 | - | text/plain | 已有 |
| GET | /diagnose | 全量诊断 | - | JSON | 已有 |
| GET | /agents | 列出所有Agent | - | {agents} | 已有 |
| GET | /.well-known/agent-card.json | A2A Discovery | - | {agent_cards} | 已有 |

### 4.2 分身池HTTP API（V10.0-P2-1新增）

| 方法 | 路径 | 功能 | 入参 | 出参 | 状态 |
|------|------|------|------|------|------|
| POST | /v1/pool/request | 申请临时分身 | parent_agent_id, clone_type, task_id, context | clone_id, clone_type, ttl, created_at | 已实现 |
| POST | /v1/pool/release | 释放临时分身 | clone_id | status, clone_id | 已实现 |
| GET | /v1/pool/status | 查询分身池状态 | - | status, stats | 已实现 |
| GET | /v1/pool/clones/{clone_id} | 查询指定分身状态 | - | clone_id, parent_agent_id, clone_type, task_id, ttl | 已实现 |

### 4.3 跨模块ABC接口（定义在M1，由其他模块实现）

| 接口 | 职责归属 | 方法签名 |
|------|---------|---------|
| MemoryInterface | 模块5（潮汐记忆） | query(), write(), permission_check() |
| SkillsInterface | 模块2（Skill集群） | invoke_tool(), list_available_tools(), check_tool_permission() |
| InferenceInterface | 模块3（端云协同） | chat(), chat_stream(), embed() |

### 4.4 A2A Protocol v1.0

| 组件 | 文件 | 状态 |
|------|------|------|
| A2AProtocol | a2a_protocol.py | 完整实现（Task状态机、JSON-RPC 2.0、HMAC-SHA256签名） |
| MemoryTransport | a2a_protocol.py | 完整实现 |
| HTTPTransport | http_transport.py | 完整实现 |

**A2A 协议字段说明（概念级）**：
- `task_id` / `trace_id`：任务标识与链路追踪标识
- `intent` / `payload`：意图标识与载荷数据
- `sender` / `recipient`：消息收发方Agent ID
- `priority` / `ttl`：优先级与生存时间
- `signature`：HMAC-SHA256 签名摘要（仅保留签名字段，不暴露密钥参数）
- **`x-security-classification`**：[v2.0-LINKAGE] 涉密四级标记头字段，所有A2A消息必须携带；M5目标消息默认自动升级为 `TOP_SECRET`
- **脱敏说明**：A2A 协议字段表中不包含任何原始敏感字段标识（如向量摘要标识等），统一以概念级描述替代。

### 4.5 涉密四级标记传递规则（C5-P0 新增）

A2A 消息头中统一携带 `x-security-classification` 字段，四级标记定义如下：

| 标记值 | 等级名称 | 传递规则 | 处理要求 |
|--------|---------|---------|---------|
| `PUBLIC` | 公开 | 可在所有模块间自由传递 | 常规路由，无需额外脱敏 |
| `INTERNAL` | 内部 | 仅限云汐系统内部模块间传递；未设置时默认按此处理 | 禁止流向外部系统或第三方服务 |
| `CONFIDENTIAL` | 机密 | 须经 Security-Agent 预检通过后方可传递 | 接收方须具备不低于该等级的 clearance |
| `TOP_SECRET` | 绝密 | 须经 Security-Agent 双重审批 + 字段级脱敏 | payload 中敏感字段替换为脱敏占位符后方可进入传输层 |

**传递规则要点**：
1. 消息发起方须在构造 A2A Task 时设置 `x-security-classification` 头字段。
2. Bus-Agent 在路由前读取该标记，`CONFIDENTIAL`/`TOP_SECRET` 须先路由至 Security-Agent 预检。
3. `TOP_SECRET` payload 须经 Security-Agent 字段级脱敏（如向量摘要标识等替换为 `[已脱敏-绝密]`）。
4. M1-M5 涉密传输须启用端到端加密（概念级描述，具体密钥管理遵循《密钥管理规范》）。

### 4.6 M1-M3 端云边界协议（C3-P1 新增）

| 职责维度 | M1（多Agent集群调度） | M3（端云协同） |
|---------|---------------------|---------------|
| 调度决策 | **负责 WHERE**：决定任务在本地还是云端执行（LOCAL_FIRST/AUTO/CLOUD_FIRST） | 不干涉调度决策 |
| 数据传输 | 不直接读写数据队列 | **负责 HOW**：执行实际的数据传输、SQLite队列操作、端云节点管理 |
| 接口调用 | 通过 InferenceInterface 调用 M3 的 chat/chat_stream/embed | 暴露 InferenceInterface 实现 |
| 禁止事项 | **禁止**直接读写 M3 的 SQLite 队列；**禁止**擅自切换端云节点 | **禁止**绕过 M1 调度直接接收上层任务 |

**边界协议要点**：
- M1 Discovery-Agent 做出调度决策后，通过 Bus-Agent 将决策指令（WHERE）下发给 M3。
- M3 负责实际的数据传输通道建立、数据序列化、重连补发（HOW）。
- M1 仅通过标准接口与 M3 交互，不感知 M3 内部存储结构（如 SQLite 队列）。
- M3 的端云节点切换须由 M1 调度指令触发，M3 不得擅自切换。

### 4.7 M1-M2 预算申请/上报接口（C2-P2 新增）

| 接口名称 | 方向 | Intent | 入参 | 出参 | 说明 |
|---------|------|--------|------|------|------|
| 配额申请 | M2 → M1 | `budget.request_quota` | `task_id`, `estimated_tokens`, `model`, `skill_name` | `status`(approve/deny/defer), `granted_quota`, `expires_at` | M2 调用前须向 M1 申请配额 |
| 消耗上报 | M2 → M1 | `budget.report_usage` | `task_id`, `actual_tokens`, `model`, `latency_ms` | `acknowledged`, `remaining_quota` | M2 执行完成后上报实际消耗 |
| 预算告警 | M2 → M1 | `budget.report_alert` | `alert_level`(warning/critical), `skill_name`, `threshold_pct` | `acknowledged`, `action`(throttle/circuit/none) | M2 触及预警阈值时上报，由 M1 统一裁决 |

**分工原则**：M1 负责全局配额分配与熔断裁决；M2 负责单技能消耗估算与上报。M2 不得独立执行熔断决策。

### 4.8 云汐人格润色输出接口（v1.0-VOICE 新增）

| 接口名称 | 方向 | Intent | 入参 | 出参 | 说明 |
|---------|------|--------|------|------|------|
| 标准人格润色 | M1/M4 → YunxiVoice | `voice.polish` | `raw_content`, `scene_type`, `user_context`(可选), `output_format`, `length_hint` | `polished_content`, `tone_applied`, `personality_params`, `facts_preserved`, `privacy_check` | 将结构化原始内容润色为云汐人格自然语言 |
| 自定义语气润色 | M1 → YunxiVoice | `voice.polish_with_tone` | `raw_content`, `personality_params`, `scene_type`(可选) | `polished_content`, `tone_applied`, `personality_params` | 使用自定义五维人格参数润色 |
| 质量校验 | M1 → YunxiVoice | `voice.quality_check` | `raw_content`, `polished_content`, `scene_type` | `passed`, `fact_integrity`, `tone_consistency`, `red_line_clean` | 校验润色结果的事实完整性和语气一致性 |
| 红线检测 | M1 → YunxiVoice | `voice.red_line_check` | `content` | `has_violation`, `violations`, `violation_count` | 扫描禁忌词（机器化表述、内部架构泄露等） |
| 人格参数查询 | M1/M4 → YunxiVoice | `voice.get_personality` | `scene_type`, `user_context`(可选) | `scene_name`, `personality_params`, `tone_keywords` | 获取指定场景的人格参数配置 |
| Orchestrator润色调度 | M4 → M1 | `orchestrate.voice_polish` | `raw_content`, `scene_type`, `user_context`(可选) | `polished_content`, `tone_applied`, `personality_params`, `degraded` | Orchestrator统一入口，含失败降级 |
| **偏好持久化更新** | **M4 → M1 → M5** | **`voice.update_preference`** | **`user_id`**, **`preferences`**, **`source`**(可选) | **`success`**, **`preferences`**, **`security_level`**, **`storage`** | **[V10.1新增] 更新用户人格偏好，委托M5持久化（CONFIDENTIAL级）** |

**调用链路**：
`M4 SceneResult → M1 Orchestrator-Agent（orchestrate.voice_polish）→ YunxiVoice-Agent（voice.polish）→ 润色结果 → UI渲染`

**MENTAL 场景特殊链路**：
`MentalAgent原始输出 → Security-Agent涉密预检 → YunxiVoice-Agent润色（仅基于结构化指标）→ UI渲染`

---

## 5. 跨模块联动

### 5.1 M1-M2 Skill集群联动

- **联动路径**：Orchestrator-Agent → Bus-Agent → M2 SkillExecutor
- **职责边界**：M1 负责任务分解与Agent组队，M2 负责具体 Skill 执行。M2 调用前须通过 `budget.request_quota` 向 M1 申请配额。
- **接口**：M1 通过 SkillsInterface（定义在 M1，M2 实现）调用 `invoke_tool()` / `list_available_tools()`。
- **异常处理**：M2 执行异常通过 Bus-Agent 回传，Arbiter-Agent 判定是否重试或降级。

### 5.2 M1-M3 端云协同联动

- **联动路径**：Discovery-Agent（决策）→ Bus-Agent → M3 InferenceInterface
- **职责边界**：M1 负责 WHERE（本地/云端决策），M3 负责 HOW（实际数据传输与推理执行）。M1 禁止直接读写 M3 的 SQLite 队列。
- **接口**：InferenceInterface（`chat()` / `chat_stream()` / `embed()`）。
- **异常处理**：端侧断连时，M3 离线缓存任务；网络恢复后 M1 通过 Discovery-Agent 触发 `drain_offline_tasks()` 重试。

### 5.3 M1-M4 场景引擎联动

> **边界澄清**：本节所述为 M1 调度层的 **6 种任务调度策略（STRAT-A~F）**，与 M4 业务场景层的 6 种底层执行模式（DOCUMENT/CODING/REVIEW/DESIGN/MENTAL/PLANNING）属于不同层级。M4 场景模式决定「做什么类型的事」，M1 调度策略决定「用什么方式组队执行」。两者通过 Orchestrator-Agent 的 DAG 构建器协作。

- **联动路径**：M4 SceneRouter（业务场景）→ Orchestrator-Agent（调度策略选择）→ 子Agent调度执行
- **6种调度策略映射矩阵**（C4-P1，STRAT-A~F）：

| 调度策略 | 主Agent | 协作子Agent | 触发条件 | 路由优先级 |
|---------|--------|------------|---------|-----------|
| STRAT-A：简单任务直调 | Orchestrator-Agent | Discovery-Agent, Bus-Agent, Budget-Agent | 单意图、无依赖、低复杂度 | P0 |
| STRAT-B：复杂任务DAG编排 | Orchestrator-Agent | Lifecycle-Agent, Snapshot-Agent, Bus-Agent, Budget-Agent | 多步骤、有依赖、中/高复杂度 | P0 |
| STRAT-C：端云协同计算 | Discovery-Agent | Orchestrator-Agent, Bus-Agent, Snapshot-Agent | 端云资源选择或网络状态变化 | P1 |
| STRAT-D：涉密内容处理 | Security-Agent | Orchestrator-Agent, Bus-Agent, Arbiter-Agent | 命中涉密关键词或显式标记分级 | P0 |
| STRAT-E：多Agent冲突仲裁 | Arbiter-Agent | Bus-Agent, Lifecycle-Agent, Snapshot-Agent | 死锁、资源争用或循环依赖 | P1 |
| STRAT-F：断点续跑恢复 | Snapshot-Agent | Orchestrator-Agent, Lifecycle-Agent, Bus-Agent | 系统重启、Agent异常退出 | P1 |

- **输入输出格式**：详见 `orchestrator/ARCHITECTURE.md` 第七章。

### 5.4 M1-M5 潮汐记忆联动

- **联动路径**：Bus-Agent → Security-Agent（涉密预检）→ M5 MemoryInterface
- **职责边界**：M1 与 M5 之间的所有数据传输须启用端到端加密（概念级）。M5 不直接参与 M1 的调度决策。
- **接口**：MemoryInterface（`query()` / `write()` / `permission_check()`）。
- **安全要求**：[v2.0-LINKAGE] M5 A2A 消息默认标记为 `TOP_SECRET`（绝密）。Bus-Agent 在路由时自动将目标为 M5 的消息涉密等级升级为 `TOP_SECRET`。`TOP_SECRET` 级 payload 须经 Security-Agent 字段级脱敏后方可传输至 M5。所有 A2A 消息必须携带 `x-security-classification` 头字段。

### 5.5 M1-M6 设备健康联动

- **联动路径**：M6 设备状态事件 → TaskDispatcher（订阅）→ Discovery-Agent（调度降级）
- **职责边界**：M6 负责采集端侧设备健康状态（电量、温度、连接状态），M1 根据状态调整调度策略。
- **异常处理**：离线/低电量/断连时，M1 将任务缓存到离线队列，待设备恢复后批量补发。

### 5.6 [v2.0-LINKAGE] 联调阶段约束

- **就绪检查**：M1 必须通过 `/health` 和 `/ready` 端点确认自身就绪后方可参与联调。
- **涉密标记强制**：所有 A2A 消息必须携带 `x-security-classification` 头字段，未设置时默认按 `INTERNAL` 处理。
- **分身池配额**：联调阶段分身池全局上限设置为 50，单父Agent上限设置为 5，防止资源耗尽。
- **异常上报链路**：
  - Agent 调用异常 → Arbiter-Agent 判定重试/降级/人工介入
  - 预算超限 → Budget-Agent 熔断 + 通过 `budget.report_alert` 上报
  - 涉密违规 → Security-Agent 拒绝 + 审计日志记录
  - 死锁/循环依赖 → Wait-For 图 DFS 检测 + 三级仲裁

### 5.7 [v1.0-VOICE] M1-YunxiVoice 人格润色联动

- **联动路径**：M4 SceneResult → M1 Orchestrator-Agent（`orchestrate.voice_polish`）→ YunxiVoice-Agent（`voice.polish`）→ UI 渲染
- **职责边界**：
  - M1 Orchestrator-Agent：负责调度入口、懒加载 Voice Agent、失败降级（润色失败时返回原始内容，不阻断主流程）
  - YunxiVoice-Agent：负责人格润色执行、两层语气体系、质量自检、红线检测、MENTAL 场景涉密保护
  - M4 场景引擎：决定调用时机（SceneResult 输出前最后一道工序），传入 scene_type 和 user_context
- **两层命名映射体系**（底层模式 ↔ 上层场景）：

| 层级 | 命名空间 | 6 个标识 | 说明 |
|------|---------|---------|------|
| L1 底层模式 | M4 全局标准 | `DOCUMENT / CODING / REVIEW / DESIGN / MENTAL / PLANNING` | 决定「做什么类型的事」，定义基础语气基调 |
| L2 上层场景 | 用户可见场景 | `work_dev / study_plan / review_summary / relationship / emotion_companion / life_management` | 业务语义层，在基础语气上叠加细腻微调 |

- **语气计算链路**：基础五维人格 → 底层模式偏移 → 上层场景微调 → 用户偏好微调 → 钳位 0-10
- **接口兼容性**：`voice.polish` 同时支持传入底层模式名（大写）或上层场景名（小写），内部自动查表解析
- **命名映射表位置**：`shared_models.py` 中 `M4ExecutionMode` / `UserScene` / `MODE_TO_SCENE_PRIMARY` / `SCENE_TO_MODE`
- **MENTAL 场景特殊链路**：MentalAgent 原始情绪分析 → Security-Agent 涉密预检（确保无原始对话泄漏）→ YunxiVoice-Agent 润色（仅基于结构化指标）→ UI 渲染
- **质量校验**：润色结果输出前执行三重校验——事实完整性（数字/数据点保留）、语气一致性（场景参数范围）、红线违规检测（禁忌词扫描）
- **降级策略**：YunxiVoice-Agent 异常时自动降级为原始内容输出，标记 `degraded=true`

#### 5.7.1 流式润色方案（SSE 接入）

- **两种模式**：
  - **流畅模式（默认，`voice_polish=true`）**：按句子缓冲，每收到一个完整句子就送入 YunxiVoice 润色，然后流式输出润色结果。权衡：首字延迟增加 ~200ms，但输出更自然
  - **极速模式（`voice_polish=false`）**：跳过 YunxiVoice，直接流式输出原始内容。权衡：无润色延迟，但语气偏机械
- **降级规则**：YunxiVoice 响应 > 500ms 时自动降级为极速模式，不阻断流式输出，标记 `degraded=true`
- **接口位置**：`POST /api/v1/chat/stream` 入参增加 `voice_polish`（布尔值，默认 true）
- **Token 计量**：润色消耗的 token 单独计量，计入 Budget-Agent 的 `voice_polish` 类目，不影响原始推理 token 配额

#### 5.7.2 人格偏好持久化链路

- **存储位置**：M5 潮汐记忆系统（L2 海湾层，用户配置类记忆，key = `user_personality_preference`）
- **读取时机**：新会话开始时，Orchestrator-Agent 通过 MemoryInterface 读取用户偏好，写入 YunxiVoice 本地缓存
- **写入时机**：用户在设置中修改偏好时，通过 M4 → M1 → M5 链路写入（`voice.update_preference` 接口）
- **缓存策略**：M1 会话级缓存（YunxiVoice 的 `_user_preferences` 字典），避免每次润色都查 M5
- **隐私规则**：人格偏好数据标记为 `CONFIDENTIAL` 级，跨设备同步时须经 Security-Agent 脱敏检查
- **降级路径**：M5 不可用时使用系统默认人格参数（DEFAULT_PERSONALITY），不影响润色功能
- **接口定义**：`voice.update_preference` — 入参 `user_id`/`preferences`/`source`，出参 `success`/`preferences`/`security_level`/`storage`

---

## 6. 测试报告

### 6.1 测试框架与运行方式

- **框架**：pytest + pytest-asyncio + pytest-cov
- **运行命令**：`pytest tests/ -v --cov=agent_cluster --cov-report=term-missing`
- **环境要求**：Python 3.11+，已安装 pytest、pytest-asyncio、pytest-cov

### 6.2 测试覆盖率概览

| 测试批次 | 测试文件 | 用例数 | 通过率 | 覆盖率 |
|---------|---------|--------|--------|--------|
| V9基线回归 | tests/test_v9_regression.py | 20+ | 100% | 基线 |
| V10全量子Agent | tests/test_v10_subagents.py | 62 | 100% | 86%+ |
| API接口测试 | tests/test_api_v10.py | 10 | 100% | 覆盖14个HTTP端点 |
| 硬件感知测试 | tests/test_hardware_awareness.py | 5 | 100% | 断连缓存/降级策略 |
| 并发安全测试 | tests/test_v10_subagents.py（并发子类） | 4 | 100% | 并发DAG构建/死锁检测 |
| **分批全量合计** | **全部** | **~101** | **100%** | **81%** |

### 6.3 关键测试用例说明

| 测试类 | 用例数 | 验证重点 |
|--------|--------|---------|
| `TestOrchestratorAgent` | 4 | DAG构建（simple/medium）、节点状态更新、Agent身份 |
| `TestLifecycleAgent` | 4 | 八态状态机流转、引用计数、优雅终止、Agent身份 |
| `TestDiscoveryAgent` | 4 | 负载评分、端云调度策略、注册发现 |
| `TestBusAgent` | 2 | 消息路由、健康检查 |
| `TestSnapshotAgent` | 3 | 快照创建、链式存储、完整性校验 |
| `TestBudgetAgent` | 5 | 预算检查、使用量记录、模型选择、预算报告 |
| `TestSecurityAgent` | 6 | 涉密分级、权限预检、审计日志、输入安检 |
| `TestArbiterAgent` | 4 | 死锁检测、环检测、仲裁裁决、人工介入 |
| `TestConcurrencySafety` | 4 | 并发DAG构建、并发快照、并发死锁检测、并发预算检查 |
| `TestAPIV10` | 10 | HTTP端点功能、错误处理、参数校验 |
| `TestHardwareAwareness` | 5 | 硬件状态更新、断连缓存、降级策略、批量补发 |

---

## 7. 目录结构

```
agent_cluster/
├── __init__.py
├── interfaces.py              # 核心接口：IAgentPlugin / MemoryInterface / SkillsInterface / InferenceInterface
├── shared_models.py           # V10.0 共享数据模型：TaskDAG / DAGNode / DAGEdge / AgentLifeState / SecurityClassification 等
├── a2a_protocol.py            # A2A Protocol v1.0：Task状态机、AgentCard、签名验证、传输抽象
├── http_transport.py          # HTTP传输层实现
├── message_bus.py             # 底层消息总线（优先级队列、发布订阅）
├── agent_registry.py          # Agent注册表（反向索引O(1)）
├── task_dispatcher.py         # 任务调度分发器（含硬件健康探测、断连缓存、降级策略）
├── ledger_engine.py           # 任务账本引擎
├── budget_manager.py          # 预算管理中心（滚动窗口、熔断）
├── guardrails_v2.py           # 输入风控安检（Prompt注入、PII脱敏）
├── circuit_breaker.py         # 熔断器
├── dead_letter_queue.py       # 死信队列
├── llm_provider.py            # LLMProvider（DEPRECATED，推理已剥离至M3）
│
├── api/
│   ├── __init__.py
│   └── server.py              # FastAPI HTTP封装层（14标准端点 + 4分身池端点）
│
├── orchestrator/
│   ├── __init__.py
│   ├── agent.py               # Orchestrator-Agent 实现
│   └── dag_builder.py         # DAGBuilder：复杂度评估、节点规划、边规划、Agent分配
│
├── lifecycle/
│   ├── __init__.py
│   ├── agent.py               # Lifecycle-Agent 实现
│   └── instance_pool.py       # AgentInstancePool：八态状态机、引用计数
│
├── discovery/
│   ├── __init__.py
│   ├── agent.py               # Discovery-Agent 实现
│   ├── load_evaluator.py      # LoadEvaluator：四维负载评分
│   └── scheduling_policy.py   # SchedulingPolicy：端云调度决策树
│
├── bus/
│   ├── __init__.py
│   └── agent.py               # Bus-Agent 实现（A2A↔BusMessage 转换、MCP适配）
│
├── snapshot/
│   ├── __init__.py
│   ├── agent.py               # Snapshot-Agent 实现
│   └── snapshot_store.py      # SnapshotStore：增量快照链、SHA256校验
│
├── budget/
│   ├── __init__.py
│   └── agent.py               # Budget-Agent 实现（多级预算、成本预警）
│
├── security/
│   ├── __init__.py
│   └── agent.py               # Security-Agent 实现（四级分级、审计留痕）
│
├── arbiter/
│   ├── __init__.py
│   ├── agent.py               # Arbiter-Agent 实现
│   └── wait_for_graph.py      # WaitForGraph：DFS环检测、三级仲裁
│
├── pool/
│   ├── __init__.py
│   ├── clone_factory.py       # CloneFactory：分身创建工厂
│   ├── clone_pool.py          # ClonePool：分身生命周期、配额、清理
│   └── agent_adapter.py       # CloneAgentAdapter：分身Agent适配器
│
├── tests/
│   ├── test_v10_subagents.py  # 62个V10全量子Agent测试 + 4个并发安全测试
│   ├── test_api_v10.py        # 10个HTTP API接口测试
│   └── test_hardware_awareness.py # 5个硬件感知与降级测试
│
└── docs/
    └── 模块01-多Agent集群调度-产物归档摘要-V10.0-FINAL.md  # 本文档
```

---

## 8. 本地涉密留存声明

依据云汐项目保密分级管理办法，以下涉密内容仅限本地留存，不上传主控或云端：

1. **A2A/MCP通信密钥管理方案**：HMAC-SHA256签名使用的密钥生成、分发、轮换策略文件，仅存本地安全存储区。

2. **负载均衡评分权重参数**：LoadEvaluator中VRAM/CPU/电量/网络四维综合评分的具体权重系数和聚合算法实现细节，属技术秘密。

3. **涉密分级策略规则**：SecurityClassifier中绝密级关键词规则库和正则模式库，涉及企业敏感信息分类标准。

4. **调度决策树内部阈值**：SchedulingPolicy中LOCAL_FIRST/AUTO/CLOUD_FIRST策略的电池阈值、网络延迟阈值等内部参数。

5. **固件签名验证密钥**：无人机/手表等端侧设备的固件签名公钥和验证逻辑，由模块6提供，M1仅调用接口不存储密钥。

6. **接口实现源码**：api/server.py等HTTP API封装层的具体实现代码，上传主控仅需接口定义文档（入参/出参/路径/方法）。

7. **端到端加密算法参数**：M1-M5涉密传输保护中使用的具体加密算法参数和密钥协商细节，遵循《密钥管理规范》本地留存。

---

## 附录A：缺陷修正清单（本次关闭）

| 缺陷编号 | 优先级 | 修正内容 | 验收状态 |
|---------|--------|---------|---------|
| C5 | P0 | Security-Agent 补充"高涉密传输保护"专节；A2A协议字段表无vector_fingerprint明文；涉密四级标记规则写入全局接口对照表 | **已验收** |
| C1 | P1 | Bus-Agent 补充MCP适配专节（A2A↔MCP格式转换规则、错误码映射表、超时策略） | **已验收** |
| C3 | P1 | 全局接口对照表补充M1-M3端云边界协议（M1负责WHERE/M3负责HOW；禁止SQLite直接操作）；Discovery-Agent无SQLite队列描述 | **已验收** |
| C4 | P1 | 补充6种场景模式×8子Agent映射矩阵，写入Orchestrator-Agent文档和全局接口对照表 | **已验收** |
| C2 | P2 | Budget-Agent明确M1-M2 Token预算分工；全局接口对照表包含预算申请/上报接口 | **已验收** |
| I1 | P2 | 归档摘要重组为8章标准格式（模块基础信息/Agent编制/功能清单/对外接口/跨模块联动/测试报告/目录结构/涉密声明） | **已验收** |

---

## 附录B：专利创新点

| 创新点 | 描述 | 差异化价值 |
|--------|------|-----------|
| **三层混合仲裁架构** | Wait-For图 + DFS环检测 + 三级仲裁（自动→协商→人工） | 解决多Agent系统死锁的行业痛点，三级仲裁具备方法论创新 |
| **临时委派分身机制** | 勘探/规划/撰写/审查四种分身，按需生成、最小信息下发、自动销毁 | 解决Agent临时任务委派的安全与效率平衡问题，最小信息原则形成差异化 |
| **端云影子代理映射** | 本地Agent与云端影子Agent双向映射，断连时任务自动缓存，重连后增量同步 | 解决端云协同中的离线连续性问题 |
| **DAG拓扑驱动调度** | 任务DAG显式建模，支持拓扑排序、并行检测、关键路径分析 | 解决多Agent协作中的任务依赖管理问题，标准格式输出供工作台渲染 |
| **四级涉密分级隔离** | 公开/内部/机密/绝密四级 + 权限域隔离 + 审计日志留痕 | 满足企业级安全合规要求 |

---

> 归档完毕。本次修正覆盖 C5(P0) / C1(P1) / C3(P1) / C4(P1) / C2(P2) / I1(P2) 共6项缺陷，全部关闭。