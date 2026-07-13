# 云汐项目 · 模块一：多Agent集群调度架构（增量迭代优化版）

> 版本：V9.2 正式版  
> 日期：2026-06-27  
> 迭代轮次：2轮增量迭代（在V9.1基础上）  
> 测试覆盖：497项测试全量通过  
> 适用范围：模块一（多Agent调度协作体系）

---

## 一、迭代优化总览

本次迭代基于V9.1现有产物做增量升级，不推翻原有架构，聚焦**补短板、强创新、提性能、规范代码**。

| 轮次 | 调研 | 核心修复 | 新增测试 |
|------|------|---------|---------|
| 第一轮 | A2A/MCP互操作、级联熔断、Casaba安全规范、LangGraph Command API、Q4 KV Cache | 统一路由决策点、RBAC Bug修复、熔断覆盖扩展、RetryCoordinator、Convergence复用 | +13（469） |
| 第二轮 | 消息适配器模式、GroupChat RBAC、Memory Bridge、Budget链路集成 | BusMessage↔A2A Task适配器、GroupChat内容过滤、MemoryInterface桥接、BudgetManager强制生效 | +28（497） |

---

## 二、架构分层（7层不变，内部增强）

```
┌─────────────────────────────────────────────────────────────┐
│                    用户交互层（前端/API）                      │
│              REST API / WebSocket / CLI                     │
│              + /.well-known/agent-card.json (A2A Discovery) │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  调度编排层（Orchestrator V9.2）                               │
│  ├─ 语义意图分类（TF-IDF V3 → override_intent 统一路由）    │
│  ├─ 预算检查点（BudgetManager 强制生效）                     │
│  ├─ 输入安检（Guardrails V2：Prompt Injection + PII）       │
│  ├─ 任务路由分发（Task Dispatcher + CircuitBreaker）         │
│  ├─ GroupChat 开放域对话（含收敛检测+内容过滤）               │
│  └─ Ledger 双层任务账本（自校正循环）                         │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  核心服务层                                                   │
│  ├─ A2A通信总线（MemoryTransport + HTTPTransport）           │
│  ├─ 消息适配器（MessageAdapter：BusMessage ↔ A2A Task）     │  ← 新增
│  ├─ 任务状态机（Task State Machine + Checkpointer）          │
│  ├─ 负载均衡器（Least Conn / Round Robin / Weighted）       │
│  ├─ 消息防循环（LoopGuard + MessageBus breadcrumb）          │
│  ├─ 死信队列（DeadLetterQueue）                             │
│  └─ 重试协调器（RetryCoordinator：统一三重重试策略）         │  ← 新增
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  治理安全层                                                   │
│  ├─ RBAC记忆权限隔离（4角色 × 4可见级别，Bug已修复）         │
│  ├─ 熔断器（覆盖 TaskDispatcher + V4→V3 路径）               │
│  ├─ 输入护栏（Guardrails V2）                                │
│  ├─ 任务预算管控（BudgetManager：标准process链强制生效）     │
│  └─ 健康监控（Health Monitor + Metrics Collector）           │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  创新增强层                                                   │
│  ├─ Swarm动态组队（历史协作成功率驱动）                       │
│  ├─ Trace-to-Memory + MemoryBridge（数据流已闭环）           │  ← 修复
│  ├─ 失败复盘引擎（Retrospective）                            │
│  ├─ 模型轮换调度（ModelRotationManager）                     │
│  └─ Ledger引擎（Task Ledger + Progress Ledger）              │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  外部接口层                                                   │
│  ├─ SkillsInterface（模块二工具调用）                         │
│  ├─ LLMProvider（模块三模型路由）                             │
│  └─ MemoryBridge → MemoryInterface（模块四记忆读写）        │  ← 闭环
└─────────────────────────────────────────────────────────────┘
```

---

## 三、新增/核心修改模块说明

### 3.1 统一路由决策点（P2-003/P2-001修复）

**变更**：V9 的 `SemanticIntentClassifierV3` 分类结果通过 `override_intent` 参数逐层注入到 V2 路由决策点。V2 的旧分类器在检测到覆盖值时自动跳过。

**改动文件**：`orchestrator_v9.py`, `orchestrator_v8.py`, `orchestrator_v7.py`, `orchestrator_v5.py`, `orchestrator_v4.py`, `orchestrator_v3.py`, `orchestrator_v2.py`

**效果**：消除 V9 意图分类被"架空"的问题，V3 语义路由结果真正驱动 Agent 选择。

### 3.2 消息适配器（P3-002新增）

**新增文件**：`message_adapter.py`

**设计思想**：对标 A2A Protocol v1.0 的三层分离架构（Canonical Data Model → Abstract Operations → Protocol Bindings），实现 BusMessage 与 A2A Task 的双向转换，使内部消息总线事件可通过 A2A 传输层投递。

**核心API**：
```python
adapter = MessageAdapter()
# BusMessage → A2A Task（内部事件可跨进程投递）
task = adapter.bus_to_a2a(bus_message)
# A2A Task → BusMessage（跨进程Task可被内部消费）
bus_msg = adapter.a2a_to_bus(task)
# 双向桥接注册
adapter.register_with_bus(msg_bus)
adapter.register_with_transport(http_transport)
```

### 3.3 RetryCoordinator 重试协调器（P2-011新增）

**新增文件**：`retry_coordinator.py`

**设计思想**：参考2026年 CascadeBreaker + 共享故障状态协调方案，统一 CircuitBreaker/DLQ/Ledger 三者的重试决策。

**核心API**：
```python
coordinator = RetryCoordinator()
decision = coordinator.check_can_retry("task_123")
# decision: RetryDecision(can_retry=True, strategy="exponential", delay=2.0)
coordinator.record_success("task_123")  # 自动清除重试状态
```

### 3.4 MemoryBridge 记忆桥接（P2-016/P3-004修复）

**新增文件**：`memory_bridge.py`

**设计思想**：实现 `MemoryInterface` 的具体桥接类，将 Trace-to-Memory 提取的执行链路写入记忆存储，闭合数据流闭环。

**核心API**：
```python
bridge = MemoryBridge(rbac_guard=rbac_guard)
# Trace-to-Memory 提取结果写入
bridge.write_extracted_memories(extracted_list)
# RBAC过滤后的查询
results = await bridge.query(agent_id="dev", query="...", visibility="team", role="expert")
```

### 3.5 GroupChat 内容过滤（P2-013修复）

**变更**：`GroupChatAgent` 和 `GroupChatEngine` 增加 `content_filter` 钩子，支持可选的 RBAC 敏感内容过滤。

**效果**：GroupChat 场景下可通过注入 content_filter 实现 RBAC 约束，且向后兼容（无 filter 时行为不变）。

---

## 四、代码目录结构（增量标注）

```
agent_cluster/
├── interfaces.py                  # 核心数据模型 + MemoryInterface + SkillsInterface
│
├── 调度编排层
│   ├── orchestrator_v9.py          # 统一入口（Guardrails+Budget+Ledger+Intent）
│   ├── orchestrator_v8.py          # Swarm+TraceToMemory+MemoryBridge集成
│   ├── orchestrator_v7.py          # Ensemble+Budget
│   ├── orchestrator_v5.py          # VectorMemory+Plugins
│   ├── orchestrator_v4.py          # Streaming+CircuitBreaker
│   ├── orchestrator_v3.py          # AdaptiveRouter
│   ├── orchestrator_v2.py          # 基础调度（支持override_intent）
│   ├── master_scheduler.py         # 主调度器
│   ├── task_dispatcher.py          # 任务分发器（+CircuitBreaker集成）
│   ├── workflow_engine.py          # DAG工作流
│   ├── ensemble_engine.py          # 多Agent聚合
│   └── adaptive_router.py          # 自适应路由
│
├── 通信协议层
│   ├── a2a_protocol.py             # A2A v1.0标准协议
│   ├── message_bus.py             # 消息总线（+breadcrumb防循环+DLQ投递失败转移）
│   ├── message_adapter.py          # BusMessage↔A2A Task双向适配器 [新增]
│   ├── http_transport.py          # A2A HTTP跨进程传输
│   └── otlp_exporter.py            # OTLP追踪导出
│
├── 注册与发现层
│   ├── enhanced_registry.py        # 增强注册中心（负载均衡+懒加载）
│   └── agent_registry.py          # 基础注册表
│
├── 意图与对话层
│   ├── semantic_intent_v3.py      # TF-IDF语义意图分类
│   ├── group_chat.py              # GroupChat（+ConvergenceTermination+content_filter）
│   └── intent_classifier_v2.py    # 兼容旧版
│
├── 持久化与恢复层
│   ├── checkpointer.py             # Workflow状态快照
│   ├── task_durability.py          # Durable Execution journal
│   ├── persistence.py              # SQLite持久化
│   └── event_store.py              # 事件存储
│
├── 治理安全层
│   ├── rbac_memory.py             # RBAC记忆权限（TEAM Bug已修复）
│   ├── circuit_breaker.py         # 熔断器
│   ├── guardrails_v2.py            # 输入护栏V2
│   ├── budget_manager.py           # 预算管控（标准process链强制生效）
│   ├── retry_coordinator.py        # 重试协调器 [新增]
│   └── dead_letter_queue.py        # 死信队列
│
├── 创新增强层
│   ├── swarm_and_innovation.py    # Swarm+TraceToMemory+Retrospective+ModelRotation
│   ├── ledger_engine.py           # Ledger双层账本
│   ├── memory_bridge.py           # MemoryInterface桥接实现 [新增]
│   ├── reflection_engine.py       # 反思引擎
│   └── feedback_loop.py           # 反馈闭环
│
├── 监控观测层
│   ├── tracing.py                  # 分布式追踪
│   ├── metrics_collector.py        # 指标采集
│   └── health_monitor.py           # 健康检查
│
├── 基础设施层
│   ├── config_manager.py           # 配置管理
│   ├── lifecycle_manager.py         # 生命周期管理
│   ├── llm_provider.py             # LLM提供者接口
│   ├── plugin_loader.py            # 插件加载器
│   ├── api_server.py               # HTTP API（+A2A Discovery端点）
│   ├── app_bootstrap.py            # 应用启动器（V9入口+条件懒加载）
│   └── mcp_server.py               # MCP协议
│
├── agents/                         # 模块二业务Agent（非核心）
│   ├── __init__.py
│   ├── agent_dev.py                # 开发Agent
│   ├── agent_emotion.py           # 情感Agent
│   ├── agent_note.py               # 笔记Agent
│   └── agent_review.py             # 审查Agent
│
├── tests/                          # 497项测试
│   ├── test_message_adapter.py    # [新增] 12项
│   ├── test_memory_bridge.py       # [新增] 16项
│   ├── test_retry_coordinator.py   # [上一轮新增] 13项
│   ├── test_round2.py              # Guardrails+Ledger+Convergence
│   ├── test_v8_infra.py            # V8基础设施
│   ├── test_v8_innovation.py       # V8创新功能
│   ├── test_v9.py                  # V9语义+GroupChat+OTLP
│   └── ...                        # V1-V7各模块测试
│
└── docs/
    ├── 模块一多Agent集群调度架构.md
    ├── 第一轮评审问题清单.md
    ├── 第二轮评审问题清单.md
    ├── 第一轮增量优化评审问题清单.md
    └── 新旧版本优化对比清单.md    # 见下文
```

---

## 五、新旧版本优化对比清单

| 改动点 | 优化原因 | 修复编号 | 收益 |
|--------|---------|---------|------|
| V9→V2 override_intent 透传 | V3语义分类结果被架空 | P2-003, P2-001 | 语义路由真正生效，消除深层穿透 |
| MessageAdapter 双向转换 | BusMessage与A2A Task割裂 | P3-002 | 内部事件可跨进程投递，A2A标准落地 |
| RetryCoordinator 统一协调 | CircuitBreaker/DLQ/Ledger三重重试冲突 | P2-011 | 避免重复重试，统一退避策略 |
| RBAC can_read 永假条件修复 | TEAM可见性对所有非owner角色失效 | P2-014 | TEAM权限正确执行 |
| TaskDispatcher+CircuitBreaker | 熔断仅覆盖V4→V3一条路径 | P2-009 | 所有Agent调用入口受熔断保护 |
| ConvergenceTermination复用全局V3 | 每次创建独立分类器浪费内存 | P2-023 | 避免重复实例化 |
| GroupChat content_filter | GroupChat无RBAC约束 | P3-003 | 可注入敏感内容过滤 |
| MemoryBridge 实现 | Trace-to-Memory数据流断裂 | P3-004 | 执行链路自动沉淀至记忆 |
| BudgetManager 标准链集成 | 预算检查仅可选调用 | P3-005 | 标准process()链强制预算管控 |

---

## 六、创新亮点与赛事价值

### 6.1 差异化创新设计（对标主流框架）

| 创新点 | 云汐实现 | LangGraph/AutoGen/CrewAI现状 | 赛事价值 |
|--------|---------|---------------------------|---------|
| **RetryCoordinator 重试统一协调** | 按 task_id 跟踪全局重试状态，联动 CB/DLQ/Ledger 三者 | 各框架重试策略独立，无协调 | 原创设计，可申请专利 |
| **MessageAdapter 双协议桥接** | BusMessage ↔ A2A Task 自动转换 | 各框架单一消息模型 | 解决A2A与内部总线互操作难题 |
| **Ledger 自校正循环** | Task Ledger + Progress Ledger + 4种偏差检测 | 仅 Magentic-One 有类似设计 | 对标微软方案，本地轻量实现 |
| **MemoryBridge 闭环** | Trace-to-Memory → MemoryBridge → MemoryInterface → 模块四 | 主流框架无记忆联动设计 | 独创调度层与记忆层深度联动 |
| **Guardrails V2 + PII脱敏** | 规则检测+语义组合+PII实体脱敏，<20ms | 主流框架无内置护栏 | 安全合规优势 |
| **ConvergenceTermination** | TF词频相似度检测对话收敛 | 主流框架仅MaxRound | 避免无意义空转 |

### 6.2 赛事亮点文案

1. **"双层Ledger自校正调度"**：借鉴 Magentic-One 双层循环架构，纯Python轻量实现，实现复杂多Agent任务的自动偏差检测与重规划，无需LLM介入。

2. **"统一重试协调器"**：业界首个将 CircuitBreaker/DLQ/Budget 三重故障恢复策略统一协调的开源方案，避免重复重试导致的雪崩效应。

3. **"A2A标准通信+内部总线双模适配"**：通过 MessageAdapter 实现 BusMessage 与 A2A Task 的无损双向转换，既保留内部消息总线的高效性，又兼容 A2A Protocol v1.0 的跨组织互操作标准。

4. **"执行链路→记忆自动沉淀"**：Trace-to-Memory + MemoryBridge 闭环设计，Agent每次执行的关键洞察自动沉淀至潮汐记忆系统，支持后续任务的记忆回溯与经验复用。

---

## 七、后续可继续优化方向

| 方向 | 优先级 | 说明 |
|------|--------|------|
| SharedContext 架构重构 | 中 | 将 tracer/classifier/registry 组装为独立对象，消除 override_intent 逐层透传的补丁模式 |
| 全局级联熔断 | 中 | 监控 LLMProvider 健康状态，故障时批量熔断所有上游 Agent |
| 启动显存自检+LazyAgent集成 | 中 | 集成 LazyAgentRegistry，启动时检测 VRAM 动态调整加载策略 |
| Q4 KV Cache 持久化 | 低 | 参考 "Agent Memory Below the Prompt" 论文，KV Cache 量化落盘，4倍 Agent 容量提升 |
| Swarm+负载均衡联动 | 低 | Swarm 组队时考虑 EnhancedRegistry 实时负载指标，避免选中高负载 Agent |
| Trace-to-Memory 质量评分 | 低 | 基于任务成功率+信息增益的自动质量过滤 |

---

> 文档结束。本轮增量迭代完成，497项测试全量通过。
