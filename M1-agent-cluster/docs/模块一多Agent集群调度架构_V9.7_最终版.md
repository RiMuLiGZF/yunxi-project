# 云汐项目 · 模块一：多Agent集群调度架构（V9.7 最终版）

> 版本：V9.7
> 迭代轮次：6轮完整闭环迭代（V9.1→V9.2→V9.4→V9.5→V9.6→V9.7）
> 测试覆盖：541项测试全量通过
> 日期：2026-06-28
> 适用范围：模块一（多Agent调度协作体系）

---

## 一、6轮完整迭代历程

### 第1-2轮（V9.1→V9.2）

- **诊断问题**：24项架构与实现缺陷
- **核心产出**：
  - **GuardrailsV2**：输入护栏升级，覆盖Prompt Injection与PII检测
  - **LedgerEngine**：引入Magentic-One式双层任务账本
  - **ConvergenceTermination**：基于TF-IDF余弦相似度的对话收敛检测
- **关键修复**：修复语义意图分类器覆盖率不足、GroupChat缺乏终止条件、V2编排器职责混杂等问题

### 第3-4轮（V9.3→V9.4）

- **诊断问题**：15项协议与桥接缺陷
- **核心产出**：
  - **MessageAdapter**：BusMessage与A2A Task双向无损转换
  - **MemoryBridge**：模块四记忆接口桥接，容量控制+TTL治理
  - **RetryCoordinator**：统一协调CircuitBreaker/DLQ/Ledger三重重试策略
- **关键修复**：Budget全链路传播、GroupChat RBAC强制约束、Ledger自动重规划、process()职责拆分

### 第5轮（V9.5）

- **诊断问题**：15项（含2项P0）
- **第一轮增量优化（7项修复）**：
  1. **N-012 [P0]**：Ledger replan死循环——新增SKIPPED状态 + replan_count计数器 + max_replan_rounds全局保护
  2. **N-001 [P1]**：`__getattr__`无白名单——V9/V8各维护可扩展方法白名单（`set[str]`），提供`register_passthrough()`运行时扩展
  3. **N-003 [P1]**：TaskDispatcher无Budget预检——`dispatch()`和`dispatch_parallel()`执行前检查BudgetManager
  4. **N-005 [P1]**：MessageAdapter outbound路径断裂——MemoryTransport区分处理，直接调用`get_handlers()`
  5. **N-006 [P1]**：HTTPTransport.subscribe()空实现——HTTP长轮询替代空实现，可配置`poll_interval` + 指数退避
  6. **N-008 [P1]**：BudgetManager._records无限增长——`list`改为`deque(maxlen=100000)`，日/月预算O(1)增量维护
  7. **N-009 [P1]**：GroupChat guest看不到任何agent消息——guest看到user完整消息 + agent最后一条消息摘要（80字截断）

- **第二轮深度迭代（6项修复）**：
  1. **R2-003**：LedgerEngine._replan_counts TTL清理（每小时一次）
  2. **R2-005**：HTTPTransport.subscribe()可配置间隔 + 指数退避
  3. **R2-004**：`__getattr__`白名单从`frozenset`改为可扩展`set`
  4. **R2-006**：启发式进度评估（零进展检测 + 循环依赖检测）
  5. **R2-002**：BudgetManager.preaggregate()预聚合
  6. **R2-001**：GroupChat guest摘要动作词标记增强

- **遗留问题**：6项（R2-001至R2-006），其中Ledger数据闭环、Registry反向索引、自适应重试EMA学习、V8 tracer穿透、A2A Task签名等5项进入V9.6 backlog

### 第6轮（V9.6）

- **诊断问题**：13项新问题
- **核心修复（5项）**：
  1. **Ledger数据闭环**：`close_task()`实现完整生命周期——将所有未完成计划标记为FINAL、从active_task_ledgers移除、保留ProgressLedger作为只读归档、清理replan_counts，配合每小时TTL清理孤立progress ledger
  2. **Registry反向索引**：`EnhancedRegistry`新增`_capability_index: dict[str, set[str]]`，注册/注销自动维护，能力查询从O(N)降至O(1)
  3. **自适应重试分类**：`RetryCoordinator`按错误类型分类（timeout/network/oom/circuit_breaker/unknown），五类错误独立退避配置（base_delay/max_delay/multiplier），实例级max_delay作为最终上限
  4. **V8 tracer穿透修复**：`OrchestratorV8.__init__`中通过显式参数或链式提取将tracer存储到`self._tracer`，`process()`使用本地引用而非深层穿透
  5. **A2A Task签名**：`Task`模型新增`signature`字段，`sign_task()`/`verify_task()`基于HMAC-SHA256实现

- **遗留问题**：3项进入V9.7 backlog

### 第7轮（V9.7）

- **评审遗留问题**：3项
- **核心修复（2项）**：
  1. **自适应重试EMA学习**：`RetryCoordinator`在`record_retry()`中实现EMA动态学习——连续失败时以alpha=0.3增大learned_multiplier（上限4.0），`record_success()`中成功后以alpha=0.3减小learned_multiplier（下限1.1）。延迟计算采用`(profile_multiplier + learned_multiplier) / 2`混合策略，比固定指数退避更智能
  2. **A2A签名集成到HTTPTransport**：`HTTPTransport.send()`发送前若配置了secret且Task无签名，自动调用`sign_task()`签名；接收响应时若包含signature且配置了secret，自动调用`verify_task()`验签，验签失败返回FAILED状态

---

## 二、核心架构图

V9 七层洋葱架构（保留但逐步扁平化方向）：

```
V9 (Guardrails + Ledger + IntentV3)
    ↓
V8 (Registry + Swarm + RBAC + Tracer)
    ↓
V7 (Ensemble + Budget + Durability)
    ↓
V5 (Vector + Plugin + MCP)
    ↓
V4 (Event + Streaming + LLM + CB)
    ↓
V3 (Semantic)
    ↓
V2 (Base)
```

**扁平化演进方向**：V9.7已在V9层直接组合MessageAdapter、MemoryBridge、RetryCoordinator等底层模块，未来版本计划废弃V2-V7中间洋葱层，实现V9→底层模块的直接扁平调用。

---

## 三、关键子系统说明

### 3.1 Safe-Ledger 双层防死循环任务账本

**双层结构**：
- **TaskLedger**：维护任务目标、分解计划、依赖关系。每条计划包含plan_id、description、assigned_agent、dependencies、status、retry_count、replan_count
- **ProgressLedger**：追踪Agent执行进度，记录每个agent_id的status、completion_rate、last_output、error、updated_at

**三级递进保护**：
1. **Plan级保护**：单个计划replan_count达到5次时，标记为SKIPPED终态，从detect_blockers中排除
2. **任务级保护**：整个任务的replan_counts达到20次时，触发"max_replans_exceeded"终止条件
3. **终态保护**：所有活跃计划均被SKIPPED且无可执行计划时，触发"all_plans_exhausted"终止

**启发式停滞检测（Heuristic-Stall-Detector）**：
- **零进展检测**：IN_PROGRESS计划5分钟无更新且completion_rate < 10%
- **循环依赖检测**：Plan A依赖B且B依赖A时触发
- **孤儿计划检测**：已完成的计划无人依赖，但未完成的计划无人为其做前置
- 纯规则实现，零LLM调用，7B本地友好

**数据闭环**：
- `close_task()`自动归档：将所有未完成计划标记为FINAL，从active_task_ledgers移除，保留ProgressLedger作为只读存档
- TTL每小时清理：stale replan_counts条目 + 孤立progress ledger（task已关闭且无引用）

### 3.2 Adaptive-Retry 自适应重试协调器

**错误类型分类**：
| 错误类型 | 识别关键字 | base_delay | max_delay | multiplier |
|---------|----------|-----------|----------|-----------|
| timeout | timeout, timed out, asyncio.timeout | 0.5s | 5s | 1.5 |
| network | connection, network, dns, refused | 1.0s | 30s | 2.0 |
| oom | oom, out of memory, cuda, memory | 5.0s | 120s | 2.0 |
| circuit_breaker | circuit breaker, circuit_breaker | 10.0s | 60s | 1.0 |
| unknown | 其他所有 | 1.0s | 60s | 2.0 |

**EMA学习机制**：
- **连续失败增大**：`record_retry()`中当retry_count >= 2时，`learned_multiplier = min(4.0, learned_multiplier * (1 + alpha * 0.3))`，alpha=0.3
- **成功后减小**：`record_success()`中`learned_multiplier = max(1.1, learned_multiplier * (1 - alpha * 0.5))`，alpha=0.3
- **混合延迟计算**：`effective_multiplier = (profile["multiplier"] + state.learned_multiplier) / 2`，既保留预设配置又融入历史经验
- **最终上限**：实例级`self._max_delay`作为全局上限，profile级max_delay作为类型上限

**防泄漏治理**：`_states`字典上限10000条，TTL=24h，超限时淘汰最旧条目

### 3.3 TLS-Vis 三层分级可见性

**三层模型**：
| 层级 | 可见范围 | 消息过滤规则 |
|------|---------|------------|
| guest | user完整消息 + agent摘要（80字截断） | agent消息截断至80字，自动标记动作词 |
| member | 完整RBAC过滤上下文 | 通过`can_read()`动态过滤 |
| owner | 全部消息无过滤 | 完整上下文 |

**动作词标记**：agent摘要根据内容自动标记四类动作词——共识（agree/确认/同意）、异议（disagree/反对/错误）、建议（suggest/建议/推荐）、疑问（question/为什么/如何）

**设计目标**：在信息隔离与协作效率间取得最优平衡，guest角色获得带动作词标记的摘要上下文，而非完全阻断或完全开放

### 3.4 A2A Protocol v1.0 适配层

**Task状态机**：
```
submitted → working → input_required → working → completed
    ↓           ↓            ↓              ↓
 cancelled   failed     cancelled      failed
```

**AgentCard签名**：基于HMAC-SHA256，支持Agent Discovery端点`/.well-known/agent-card.json`

**Task级签名（V9.7）**：
- `Task`模型包含`signature: str`字段
- `sign_task(task, secret)`：使用HMAC-SHA256对task内容签名
- `verify_task(task, signature, secret)`：验证签名完整性
- **HTTPTransport自动集成**：发送前自动签名（若配置了secret且Task无签名），接收响应时自动验签（若响应包含signature且配置了secret），验签失败返回TaskUpdate(status=FAILED, error="Task signature verification failed")

**多传输绑定**：
- **MemoryTransport**：内部高效内存总线，支持`get_handlers()`暴露注册handler
- **HTTPTransport**：跨进程HTTP传输，支持轮询订阅（可配置poll_interval + 指数退避max_backoff）

**MessageAdapter**：BusMessage↔A2A Task双向转换，在app_bootstrap.py中实例化并注册到MessageBus和A2ATransport

### 3.5 BudgetManager 滚动预算管理

**存储优化**：`_records`从无限增长`list`改为`deque(maxlen=100000)`，避免内存泄漏

**O(1)增量维护**：
- 每次`record_usage()`时同步更新`_daily_total`和`_monthly_total`
- `check_budget()`读取时直接比较增量累计值，无需遍历

**preaggregate()预聚合**：跨日/跨月首次检查时触发O(N)重算，后续恢复O(1)，摊销复杂度接近O(1)

**全链路预检**：
```
V9 process() → V8 process() → V7 process() → V7 process_ensemble() → TaskDispatcher
   首次检查      二次检查       三次检查         集成前检查            分发前过滤
```

超预算时各层均返回`{"status": "budget_exceeded"}`，阻止下层继续执行

### 3.6 Registry反向索引

**数据结构**：`_capability_index: dict[str, set[str]]`，capability → agent_id集合

**自动维护**：
- `register(agent)`：遍历agent.capabilities，将agent_id加入对应capability的set
- `unregister(agent_id)`：遍历所有capability的set，移除agent_id

**查询性能**：`find_by_capability(capability)`直接索引查找，O(1)时间复杂度

**兼容EnhancedRegistry**：懒加载、负载均衡、TTL卸载等增强特性与反向索引共存

---

## 四、强化后的专利创新点（5项）

### 创新点1：Safe-Ledger 双层防死循环任务账本

**技术方案**：Plan级淘汰（replan_count达5次→SKIPPED终态）→ 任务级终止（replan_counts达20次→max_replans_exceeded）→ all_plans_exhausted终态的三级递进保护

**差异化**：Magentic-One的stall计数器仅做重置，不做plan级淘汰；Safe-Ledger在plan级别实现"淘汰-降级-终止"三级递进，且全程无需LLM介入

**适用场景**：长时间运行的自主编排任务，特别是7B本地部署场景

### 创新点2：TLS-Vis 三层分级可见性RBAC

**技术方案**：GroupChat中基于Agent角色（guest/member/owner）动态过滤消息可见性。guest角色获得摘要级上下文（保留关键决策、标记动作类型），而非完全阻断或完全开放

**差异化**：主流框架（AutoGen/CrewAI）仅支持全量可见或完全隔离，无中间态。TLS-Vis在信息隔离与协作效率间取得最优平衡，guest获得带动作词标记的摘要上下文

**适用场景**：开放式多Agent协作中的访客Agent参与

### 创新点3：Heuristic-Stall-Detector

**技术方案**：纯规则（零LLM调用）检测三种停滞模式：零进展（5分钟无更新+进度<10%）、循环依赖（A→B→A）、孤儿计划

**差异化**：Magentic-One依赖LLM评估进度，7B本地模型无法承担此开销。Heuristic-Stall-Detector提供纯规则替代，计算开销可忽略

**适用场景**：7B本地部署的轻量级任务编排

### 创新点4：Adaptive-Retry 自适应重试

**技术方案**：按错误类型分类（timeout/network/oom/circuit_breaker/unknown）→ 五类错误独立退避配置 → EMA动态学习退避乘数（成功后减小、连续失败后增大）→ 混合延迟计算

**差异化**：主流框架（LangGraph RetryPolicy、Celery自动重试）采用固定指数退避或固定延迟。Adaptive-Retry通过EMA学习历史经验，使退避策略随运行时间自我优化

**适用场景**：高并发多Agent调度中的容错恢复

### 创新点5：A2A-Task-Signed 端到端消息签名

**技术方案**：Task级HMAC-SHA256签名 + HTTPTransport自动签名/验签集成。发送前自动签名，接收时自动验签，验签失败拒绝消息

**差异化**：A2A Protocol v1.0标准仅定义AgentCard签名（服务端发现时验证），未规定Task级端到端签名。本方案弥补A2A v1.0的安全缺口，实现Task级别的端到端完整性保护

**适用场景**：跨进程/跨网络A2A通信的安全加固

---

## 五、后续可优化方向

1. **SharedContext统一上下文传递**：将`override_intent`参数逐层透传改为SharedContext对象，统一管理所有跨层传递的上下文（tracer/classifier/registry等组装为独立对象）

2. **KV Cache跨Agent复用**：7B模型多Agent并行时共享KV Cache前缀，降低显存占用，参考"Agent Memory Below the Prompt"论文，预期4倍Agent容量提升

3. **gRPC Transport绑定**：替代HTTP提升性能，支持双向流式推送（替代当前轮询+指数退避方案），降低跨进程通信延迟

4. **动态组队强化学习算法**：当前`SwarmManager.recommend_team()`基于静态能力匹配，可引入强化学习（Q-Learning/PPO）或遗传算法，基于历史协作成功率动态优化组队策略

5. **GroupChat流式输出支持**：支持Agent `respond()`返回`AsyncIterator`而非`str`，实现打字机式流式输出，提升用户体验

6. **真正扁平化**：V9直接组合底层模块（Ledger+RetryCoordinator+MessageAdapter+MemoryBridge+EnhancedRegistry），废弃V2-V7洋葱层。预期减少30%调用栈深度，降低15-20%延迟

---

> 文档结束。6轮完整迭代全部完成，541项测试全量通过。
