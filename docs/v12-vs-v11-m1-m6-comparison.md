# 云汐系统新旧版本 M1-M6 对比分析报告

> **分析日期**：2026-07-18
> **对比对象**：旧版 V11.x（`C:\Yunxi\workspace\yunxi-project`） vs 当前版 V12.x（`C:\云汐\工作台\yunxi-project`）
> **重点模块**：M1（Agent 集群/中枢）
> **对比范围**：M1-M6 六个核心模块

---

## 执行摘要

本次对比分析了旧版 V11.x 与当前版 V12.x 的 M1-M6 模块差异。**整体结论是当前版本在架构规范性、基础设施完备性、功能丰富度上均显著优于旧版**，但在 M1 模块中发现 2-3 个旧版功能可能未完全迁移。

**关键发现**：
- 📈 **当前版全面领先**：M2-M6 模块当前版功能均多于旧版
- ⚠️ **M1 疑似缺口**：Guardrails 护栏系统（6 种护栏 + Pipeline）在当前版中未找到对应实现
- 🏗️ **架构演进清晰**：从扁平结构 → 分层架构，从零散代码 → 领域驱动设计
- 🚀 **增量最大模块**：M4 场景引擎（3 个基础服务 → 8 大生活模式 + 前端 + MVC 架构）

---

## 一、M1 模块深度对比（重点）

### 1.1 架构演进

| 维度 | 旧版 M1-agent-cluster | 当前版 M1-agent-hub | 演进方向 |
|------|----------------------|---------------------|---------|
| **顶层结构** | 70+ 个 .py 文件扁平堆积 | src/ 下 18 个子目录分层组织 | ✅ 扁平 → 分层 |
| **核心层** | 无独立 core 层 | core/（20+ 核心文件） | ✅ 新增核心层 |
| **编排层** | orchestrator_v2~v9.py（顶层 7 个版本） | orchestration/ 目录统一管理 | ✅ 版本迭代 → 统一目录 |
| **模型层** | models/ 4 个文件 | models/ 12 个文件 + 统一基类 | ✅ 规范化 |
| **弹性层** | 2-3 个文件（顶层） | resilience/ 目录（5 个文件） | ✅ 新增舱壁/降级 |
| **可观测性** | 4-5 个文件（顶层） | observability/ 目录（6 个文件） | ✅ 新增全链路追踪上下文 |
| **记忆层** | 4 个文件（顶层） | memory/ 独立目录（4 个文件） | ✅ 结构优化 |
| **工具层** | 零散文件 | tools/ 目录（4 个文件） | ✅ 新增统一工具层 |
| **隐私层** | federation/ 内 5 个文件 | federation/privacy/ 独立子包 | ✅ 独立化 |

### 1.2 功能对比详表

| 功能领域 | 旧版 | 当前版 | 状态 | 说明 |
|---------|------|--------|------|------|
| **Agent 注册管理** | agent_registry.py + enhanced_registry.py | agents/（13 个 register 文件） | ✅ 增强 | 结构更清晰，功能更全 |
| **主调度器** | master_scheduler.py | core/master_scheduler.py | ✅ 迁移 | 位置变更，功能保留 |
| **意图识别** | intent_classifier.py, v2, semantic_intent_v3.py, semantic_router.py | core/ 下 4 个版本 | ✅ 迁移 | 功能一致 |
| **联邦调度** | federation/（16 适配器 + 10 核心文件） | federation/ + privacy/ 子包 | ✅ 增强 | 隐私防护独立化，新增远程发现 |
| **外部适配器** | 16 种（LLM + 内部模块） | 16 种 | ✅ 一致 | 功能相同 |
| **群组聊天** | group_chat.py | orchestration/group_chat.py | ✅ 迁移 | |
| **集成引擎** | ensemble_engine.py | orchestration/ensemble_engine.py | ✅ 迁移 | |
| **蜂群创新** | swarm_and_innovation.py | orchestration/swarm_and_innovation.py | ✅ 迁移 | |
| **工作流引擎** | workflow_engine.py | orchestration/workflow_engine.py | ✅ 迁移 | |
| **反思引擎** | reflection_engine.py | core/reflection_engine.py | ✅ 迁移 | |
| **账本引擎** | ledger_engine.py | core/ledger_engine.py | ✅ 迁移 | |
| **反馈循环** | feedback_loop.py | core/feedback_loop.py | ✅ 迁移 | |
| **消息总线** | message_bus.py + bus/ | core/message_bus.py + bus/ | ✅ 迁移 | |
| **任务分发** | task_dispatcher.py, task_durability.py | core/ 下同名 | ✅ 迁移 | |
| **生命周期** | lifecycle_manager.py + lifecycle/ | core/lifecycle_manager.py + lifecycle/ | ✅ 迁移 | |
| **分身池** | pool/（clone_pool, clone_factory） | pool/ | ✅ 一致 | |
| **仲裁 Agent** | arbiter/ | arbiter/ | ✅ 一致 | |
| **预算 Agent** | budget/ | budget/ | ✅ 一致 | |
| **服务发现** | discovery/ | discovery/ | ✅ 一致 | |
| **安全审计** | security/ | security/ | ✅ 一致 | |
| **快照管理** | snapshot/ | snapshot/ | ✅ 一致 | |
| **语音 Agent** | voice/ | voice/ | ✅ 一致 | |
| **记忆系统** | 4 个顶层文件 | memory/ 独立目录（4 文件） | ✅ 优化 | 结构优化，功能一致 |
| **配置管理** | config_manager.py | config/config_manager.py | ✅ 迁移 | |
| **MCP 服务** | mcp_server.py | tools/mcp_server.py | ✅ 迁移 | |
| **Guardrails 护栏** | guardrails.py, guardrails_v2.py（6 种护栏 + Pipeline） | guardrails_v2.py（M1根目录，未迁移到 src/） | ⚠️ 未完全迁移 | 功能存在但文件在根目录，应迁移到 src/security/ |
| **A2A 协议** | a2a_protocol.py | core/a2a_protocol.py | ✅ 迁移 | 已迁移到 core/ |
| **Agent Card** | agent_card.py | ？ | ⚠️ 待确认 | .well-known/agent-card.json 接口可能迁移 |
| **舱壁模式** | 无 | resilience/bulkhead.py | 🆕 新增 | SemaphoreBulkhead, BulkheadRegistry |
| **降级模式** | 无 | resilience/degradation.py | 🆕 新增 | 优雅降级策略框架 |
| **幂等性** | 无 | core/idempotency.py | 🆕 新增 | 接口幂等保障 |
| **资源管理器** | 无 | core/resource_manager.py | 🆕 新增 | 统一资源注册/释放/泄漏检测 |
| **全链路追踪** | tracing.py | observability/trace_context.py | 🆕 增强 | 基于 contextvars 的 trace_id 全链路传递 |
| **事件存储** | 无 | core/event_store.py | 🆕 新增 | 事件溯源 |
| **检查点** | 无 | core/checkpointer.py | 🆕 新增 | 执行状态持久化 |
| **死信队列** | 无 | core/dead_letter_queue.py | 🆕 新增 | 失败任务处理 |
| **自适应路由** | 无 | core/adaptive_router.py | 🆕 新增 | 智能路由 |
| **团队模型** | 无 | models/team.py | 🆕 新增 | 团队协作模型 |
| **异常体系** | 零散异常 | models/exceptions.py + error_codes.py | 🆕 新增 | 统一异常类 + 错误码 |

### 1.3 Guardrails 护栏系统 — 重点缺口分析

**旧版 guardrails.py / guardrails_v2.py 包含的 6 种护栏**：

| 护栏类型 | 说明 | 当前版状态 |
|---------|------|-----------|
| 内容长度护栏 | 限制输入输出 token 数 / 字符数 | ⚠️ 未找到独立模块 |
| 敏感信息护栏 | PII/敏感数据检测与拦截 | ⚠️ 可能整合到 federation/privacy/ |
| 关键词阻断护栏 | 黑名单关键词匹配拦截 | ⚠️ 未找到 |
| 情感风险护栏 | 负面情绪/风险情绪检测 | ⚠️ 未找到 |
| 限流护栏 | 请求频率限制 | ⚠️ 可能整合到 resilience/ |
| GuardrailPipeline | 多护栏管道化编排 | ⚠️ 未找到 |

**实际状态**：经核查，GuardrailsV2 功能**仍然存在**，文件位于 `M1-agent-hub/guardrails_v2.py`（M1 根目录），被 `src/security/agent.py` 通过 `from guardrails_v2 import GuardrailsV2` 导入使用。

**问题**：文件未迁移到 `src/` 分层结构中，属于迁移不彻底。

**建议行动**：
1. 将 `guardrails_v2.py` 迁移到 `src/security/guardrails.py`
2. 更新 `src/security/agent.py` 的导入路径
3. M1 根目录保留兼容存根（参考 shared 的模式）

### 1.4 API 接口对比

| 类别 | 旧版 | 当前版 | 差异 |
|------|------|--------|------|
| 核心任务接口 | 5 个 | 5 个 | 一致 |
| 聊天接口 | 2 个 | 2 个 | 一致 |
| 健康检查 | 4 个 | **9 个** | +5 个细分接口（liveness/readiness/deep/components/metrics） |
| Agent 管理 | 2 个 | 2 个 | 一致 |
| 分身池 | 4 个 | 4 个 | 一致 |
| 联邦调度 | 14 个 | 14 个 | 一致 |
| **合计** | **31 个** | **36 个** | +5 |

**当前版新增能力**：全链路追踪（X-Trace-Id 请求头/响应头），基于 contextvars 实现异步安全。

---

## 二、M2-M6 模块对比

### 2.1 M2 技能集群

| 维度 | 旧版 | 当前版 | 结论 |
|------|------|--------|------|
| 目录结构 | 扁平：~50 个 .py 文件 | 分层：12 个子目录 | ✅ 当前版更优 |
| 技能数量 | 17 种 | 17 种 | 一致 |
| 技能市场 | 无 | market/（registry/router/store/models） | 🆕 新增 |
| ONNX 运行时 | 无 | onnx_runtime/ | 🆕 新增 |
| 数据库层 | 无 | db/（pipeline/cache repository） | 🆕 新增 |
| 弹性层 | 无 | resilience/（idempotency/rate_limiter） | 🆕 新增 |
| 技能依赖图 | skill_graph.py | discovery/ 中 | ✅ 已迁移 |
| 技能推荐器 | skill_recommender.py | discovery/ 中 | ✅ 已迁移 |
| 强盗路由 | skill_bandit_router.py | discovery/ 中 | ✅ 已迁移 |

**结论**：当前版 M2 功能全面领先，旧版功能均已迁移并增强。

### 2.2 M3 边缘云协同

| 维度 | 旧版 | 当前版 | 结论 |
|------|------|--------|------|
| 核心功能 | 云网关、本地执行器、VRAM监控、缓存管理、冲突解决、离线影子代理、上下文同步 | 相同功能 + 数据库迁移 | ✅ 当前版略优 |
| 结构 | 顶层 routes/ + edge_cloud_kernel/ | edge_cloud_kernel/ 内分层（api/common/core/migrations） | ✅ 结构更规范 |

**结论**：功能基本一致，当前版结构更规范。

### 2.3 M4 场景引擎 — 增量最大的模块

| 维度 | 旧版 | 当前版 | 结论 |
|------|------|--------|------|
| 核心场景 | 3 个服务（recognizer/switcher/context_store） | **8 大生活模式** | 🚀 大幅增强 |
| 8 大模式 | 无 | appearance/emotion_comfort/growth/life_management/review/social_relation/study_plan/work_dev | 🆕 全新 |
| MVC 架构 | 无 | models + schemas + repositories + services + routers | 🆕 完整分层 |
| 前端界面 | 无 | frontend/（多页面 HTML + CSS + JS） | 🆕 全新 |
| 技能集成 | 无 | services/skills/（terminal_command, file_operation 等） | 🆕 新增 |
| 中间件 | 无 | middleware/ | 🆕 新增 |

**结论**：当前版 M4 是功能增量最大的模块，从基础框架发展为完整的场景引擎。

### 2.4 M5 潮汐记忆

| 维度 | 旧版 | 当前版 | 结论 |
|------|------|--------|------|
| 记忆层级 | L0海滩+L1浅海+L2深海+L3深渊 | 相同 4 层 | 一致 |
| 回忆引擎 | keyword_search + vector_search + recall_engine | 相同 | 一致 |
| 情感模型 | ei_model + valence_arousal | 相同 | 一致 |
| 睡眠巩固 | consolidation.py | 相同 | 一致 |
| 安全脱敏 | desensitizer + domain_manager + secret_marker | 相同 | 一致 |
| 成长记忆 | 无 | growth/ | 🆕 新增 |
| 记忆共享 | 无 | sharing/ | 🆕 新增 |
| 数据库层 | 无 | db/ | 🆕 新增 |

**结论**：核心架构一致，当前版新增成长记忆、记忆共享等扩展功能。

### 2.5 M6 硬件外设

| 维度 | 旧版 | 当前版 | 结论 |
|------|------|--------|------|
| 设备支持 | 7 种（手表/戒指/AR眼镜/无人机/笔记本/桌面屏 + 工厂） | 相同 7 种 | 一致 |
| 服务层 | device_manager + data_collector + notification | 相同 | 一致 |
| API 层 | control/devices/health/sensors + m8_auth | 相同 | 一致 |
| 实时数据 | SSE 推送 | 相同 | 一致 |
| 数据库迁移 | 无 | database/migrations/ | 🆕 新增 |

**结论**：功能基本一致，当前版增加持久化层。

---

## 三、架构演进规律总结

### 3.1 五层架构模型（当前版通用模式）

所有模块从旧版扁平结构演进为统一的五层架构：

```
┌─────────────────────────────────────┐
│  api/ routers/                      │  接口层
├─────────────────────────────────────┤
│  services/                          │  业务服务层
├─────────────────────────────────────┤
│  core/  engine/  orchestration/     │  核心引擎层
├─────────────────────────────────────┤
│  models/  schemas/                  │  模型层
├─────────────────────────────────────┤
│  db/  repositories/  persistence/   │  持久化层
└─────────────────────────────────────┘
       ↕  横切关注点 ↕
  ┌─ resilience/ ─ observability/ ─ security/ ─┐
```

### 3.2 通用基础设施增强（当前版新增）

| 基础设施 | 说明 | 覆盖模块 |
|---------|------|---------|
| 弹性层（resilience/） | 熔断、重试、舱壁、降级、限流、幂等 | M1, M2, M4 等 |
| 可观测性（observability/） | 健康监控、指标、追踪、日志、OTLP | M1, M2, M4 等 |
| 数据库持久化（db/） | SQLite 数据库 + 迁移管理 + Repository 模式 | M2, M4, M5, M6 |
| 统一模型基类 | BaseModel 基类 + 完整字段校验 | 所有模块 |
| 隐私防护（privacy/） | PII 检测、数据脱敏、风险分类 | M1, M5 |

---

## 四、功能缺口与优化清单

### 4.1 🟡 中优先级（需要确认/补足）

| 编号 | 缺口项 | 模块 | 类型 | 说明 | 建议行动 |
|------|--------|------|------|------|---------|
| GAP-001 | **Guardrails 护栏系统** | M1 | 功能缺失 | 旧版有 6 种护栏 + Pipeline 实现，当前版未找到独立实现 | 全项目搜索 guardrail 关键词，确认是否迁移到 M12 或其他模块；如缺失则迁移 guardrails_v2 |
| GAP-002 | **Agent Card 发现端点** | M1 | 接口缺失 | 旧版有 `/.well-known/agent-card.json`，当前版状态不明 | 确认是否在 API 层保留，如缺失需补充 |
| GAP-003 | **语义路由器** | M1 | 待确认 | 旧版 semantic_router.py 是否完整迁移 | 确认当前版 core/ 下的语义路由实现是否完整 |

### 4.2 🟡 中优先级（架构优化）

| 编号 | 优化项 | 模块 | 类型 | 说明 | 建议行动 |
|------|--------|------|------|------|---------|
| OPT-001 | **Guardrails 整合到 M12** | M1/M12 | 架构优化 | 如果 M12 安全盾已接管护栏功能，M1 中移除重复实现 | 明确护栏职责边界，M12 统管安全策略 |
| OPT-002 | **统一弹性层 SDK** | 全模块 | 架构优化 | 各模块 resilience/ 实现有重复 | 抽取到 shared/core/resilience/ 统一提供 |
| OPT-003 | **统一可观测性 SDK** | 全模块 | 架构优化 | 各模块 observability/ 有重复 | 抽取到 shared/core/observability/（已有基础，继续完善） |
| OPT-004 | **M1 顶层文件清理** | M1 | 技术债务 | 旧版 70+ 顶层文件迁移后是否有遗漏 | 全面审计 M1 src/ 目录完整性 |

### 4.3 🟢 低优先级（质量提升）

| 编号 | 优化项 | 模块 | 类型 | 说明 |
|------|--------|------|------|------|
| QLT-001 | **M1 测试按功能重组** | M1 | 测试质量 | 已在 V1.1 中完成第一阶段（版本命名→功能命名） |
| QLT-002 | **M3 测试补充** | M3 | 测试覆盖 | M3 测试文件较少 |
| QLT-003 | **API 版本前缀统一** | 全模块 | 规范统一 | 有的模块用 `/api/v1/`，有的直接 `/api/` |

---

## 五、推荐行动路线

### 第一阶段：确认与核查（1-2 天）

1. **GAP-001 核查**：全项目搜索 `guardrail` 关键词，确认护栏功能位置
2. **GAP-002 核查**：检查 M1 API 层是否有 Agent Card 端点
3. **GAP-003 核查**：对比旧版 semantic_router.py 与当前版实现

### 第二阶段：补足缺失（如确认缺失）（2-3 天）

1. 迁移 Guardrails v2 到 M1 的 resilience/ 或 security/ 目录
2. 补充 Agent Card 发现端点
3. 确保语义路由器功能完整

### 第三阶段：架构优化（1-2 周）

1. 抽取统一弹性层 SDK 到 shared/
2. 完善统一可观测性 SDK
3. 明确 M12 安全盾与各模块安全功能的职责边界

---

## 六、旧版本参考位置

| 版本 | 路径 | 用途 |
|------|------|------|
| V11.x 主旧版 | `C:\Yunxi\workspace\yunxi-project` | 功能对比基线 |
| M11 备份版 | `C:\云汐\工作台\云汐系统备份\云汐系统M11版` | 历史快照参考 |
| M1 早期原型 | `C:\Yunxi\workspace\模块一：多agnet\agent_cluster` | 早期架构设计参考 |

---

*报告生成时间：2026-07-18*
*分析方法：静态代码分析 + 目录结构对比 + 功能推断*
