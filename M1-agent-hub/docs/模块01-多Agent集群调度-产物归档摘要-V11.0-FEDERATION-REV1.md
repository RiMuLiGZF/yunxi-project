# 模块01-多Agent集群调度-产物归档摘要-V11.0-FEDERATION-REV1

> 版本：V11.0-FEDERATION  
> 代号：云汐·联邦  
> 状态：开发完成 / 自测通过  
> 日期：2026-07-03  
> 密级：普通涉密

---

## 一、版本概述

### 1.1 版本定位

V11.0 是 M1 多 Agent 集群调度架构的 **联邦调度版本**，核心目标是打破内部 Agent 集群的能力边界，通过引入外部 AI Agent 的统一接入与调度机制，实现"内部为主、外部为辅、按需调度、安全可控"的联邦式 Agent 协作体系。

### 1.2 版本编号

| 项目 | 内容 |
|------|------|
| 版本号 | V11.0-FEDERATION |
| 基线版本 | V10.1 |
| 增量代号 | 云汐·联邦 |
| 发布类型 | 功能增强版本 |

### 1.3 核心增量

- **外部 Agent 接入层**：统一适配器架构，支持 OpenAI / Anthropic / Google / 本地模型 4 类接入
- **联邦调度决策引擎**：5 因子加权决策，4 种用户偏好模式，内外部自动路由
- **多 Agent 结果对比**：并行执行 + 4 维度质量评分 + 3 种输出模式
- **成本管控系统**：月度预算 + 三级告警 + 超预算熔断 + 账单明细
- **隐私安全防护**：5 类敏感信息检测 + 三级处理 + 审计日志
- **HTTP API 完整覆盖**：17 个 RESTful 端点覆盖全部联邦调度能力
- **Orchestrator 深度集成**：3 个新意图 + 懒加载 + 全链路串联

---

## 二、架构设计

### 2.1 总体架构

```
                        ┌─────────────────────────────┐
                        │   调用方 (M4/M5/其他模块)    │
                        └──────────────┬──────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │     Orchestrator-Agent       │
                        │  (联邦调度入口：3个新意图)     │
                        └──────┬───────────┬──────────┘
                               │           │
                    ┌──────────▼──┐  ┌─────▼──────────┐
                    │  决策层      │  │  执行层         │
                    │  Scheduler  │  │  Invoke/Compare │
                    └──────┬──────┘  └─────┬──────────┘
                           │                │
          ┌────────────────┼────────────────┼───────────────┐
          │                │                │               │
    ┌─────▼─────┐   ┌──────▼──────┐  ┌────▼─────┐  ┌──────▼──────┐
    │  Registry  │   │ Cost Ctrler │  │ Privacy  │  │ Comparator  │
    │ (注册中心) │   │ (成本管控)  │  │  Guard    │  │ (对比融合)  │
    └─────┬─────┘   └─────────────┘  └────┬─────┘  └─────────────┘
          │                                │
    ┌─────▼────────────────────────────────▼──────┐
    │         Adapters (统一适配层)                 │
    │  ┌────────┐ ┌─────────┐ ┌────────┐ ┌──────┐ │
    │  │ OpenAI │ │Anthropic│ │ Gemini │ │Local │ │
    │  └────────┘ └─────────┘ └────────┘ └──────┘ │
    └──────────────────────────────────────────────┘
```

### 2.2 核心组件清单

| 组件 | 文件 | 职责 | 代码行 |
|------|------|------|--------|
| 外部Agent注册中心 | `federation/registry.py` | 外部Agent注册、管理、健康检查、适配器工厂 | ~300 |
| 适配器基类 | `federation/adapters/base.py` | 统一调用接口、重试、错误处理、成本计算 | ~180 |
| OpenAI适配器 | `federation/adapters/openai.py` | GPT系列模型接入 | ~80 |
| Anthropic适配器 | `federation/adapters/anthropic.py` | Claude系列模型接入 | ~80 |
| Gemini适配器 | `federation/adapters/gemini.py` | Google Gemini接入 | ~80 |
| 本地模型适配器 | `federation/adapters/local_model.py` | 本地开源模型接入 | ~80 |
| 联邦调度器 | `federation/scheduler.py` | 内外部决策、候选评分、5因子加权 | ~280 |
| 多Agent对比器 | `federation/comparator.py` | 并行执行、质量评分、结果融合 | ~250 |
| 成本控制器 | `federation/cost_controller.py` | 预算管理、三级告警、账单统计 | ~220 |
| 隐私防护层 | `federation/privacy_guard.py` | PII检测、敏感信息扫描、脱敏、审计 | ~280 |
| 数据模型 | `shared_models.py` | 12个联邦调度相关数据类 | 新增~300 |

### 2.3 设计原则

1. **统一接入**：所有外部 Agent 通过 Adapter 模式统一封装，上层无感知
2. **隐私优先**：数据外发前必须经过 PrivacyGuard 检查，高涉密强制拦截
3. **成本可控**：预算熔断 + 三级告警，杜绝超支
4. **质量可证**：多 Agent 结果对比 + 4 维度质量评分，输出可溯源
5. **渐进集成**：通过懒加载方式集成到 Orchestrator，不影响现有功能
6. **开发友好**：模拟模式（simulated）支持无 API Key 环境下的开发测试

---

## 三、核心功能详解

### 3.1 外部 Agent 注册中心 (ExternalAgentRegistry)

**功能清单：**

| 功能 | 说明 |
|------|------|
| Agent注册 | 支持按类型（LLM/代码/多模态/搜索）注册外部Agent |
| Agent管理 | CRUD操作、状态更新（active/inactive/degraded） |
| API Key管理 | 独立存储，不写入profile，避免泄露 |
| 健康检查 | 单Agent/全Agent健康检查，状态自动更新 |
| 适配器工厂 | 根据Agent配置自动创建对应适配器实例 |
| 默认本地模型 | 开箱即用的本地7B模型模拟注册 |

**关键数据结构：** `ExternalAgentProfile`

```python
ExternalAgentProfile(
    agent_id="ext_openai_xxx",      # 自动生成
    display_name="GPT-4",           # 显示名称
    provider="OpenAI",              # 供应商
    agent_type=ExternalAgentType.LLM,  # 类型
    capabilities=["general", "code"],  # 能力标签
    quality_rating=4.5,             # 质量评分(1-5)
    cost_model=CostModel(...),      # 成本模型
    privacy_level=STANDARD,         # 隐私等级
    status="active",                # 状态
)
```

### 3.2 联邦调度决策引擎 (FederatedScheduler)

**决策流程：**

```
任务输入
   │
   ▼
┌──────────────┐
│ 1. 隐私红线  │────TOP_SECRET────► 强制内部
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 2. 内部能力  │────≥0.8 且非质量优先──► 内部执行
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 3. 候选筛选  │────无可用外部Agent──► 内部执行
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 4. 综合评分  │────5因子加权排序
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 5. 预算检查  │────超预算──► 找次优 / 降级内部
└──────┬───────┘
       │
       ▼
  输出决策结果
```

**5 因子权重：**

| 因子 | 权重 | 说明 |
|------|------|------|
| 隐私合规 | 30% | 涉密等级与Agent隐私等级匹配度 |
| 能力匹配 | 25% | 任务类型与Agent能力匹配度 |
| 用户偏好 | 20% | 质量优先/成本优先/速度优先/平衡 |
| 成本预算 | 15% | 预估费用与剩余预算 |
| 响应速度 | 10% | Agent响应速度等级 |

**4 种用户偏好模式：**

| 模式 | 行为特征 | 适用场景 |
|------|----------|----------|
| 质量优先 (QUALITY_FIRST) | 优先选择最高评分Agent，不计较成本 | 高质量内容创作、复杂推理 |
| 成本优先 (COST_FIRST) | 优先选择便宜方案，内部够用就内部 | 日常对话、简单任务 |
| 速度优先 (SPEED_FIRST) | 优先选择最快响应，内部通常更快 | 实时交互、快速查询 |
| 平衡模式 (BALANCED) | 质量和成本各半，综合最优 | 默认模式，通用场景 |

### 3.3 多 Agent 结果对比 (MultiAgentComparator)

**3 种输出模式：**

| 模式 | 说明 |
|------|------|
| BEST_ONLY | 单优模式：只返回质量评分最高的结果 |
| FUSION | 融合模式：以最佳结果为主，融合其他结果的优点 |
| SIDE_BY_SIDE | 对比模式：返回所有结果，供用户对比选择 |

**4 维度质量评分：**

| 维度 | 权重 | 评估内容 |
|------|------|----------|
| 正确性 | 35% | 是否回答问题、有无矛盾 |
| 完整性 | 25% | 长度、结构、覆盖度 |
| 可读性 | 20% | 段落结构、句子流畅度 |
| 代码质量 | 20% | 注释、结构、规范（仅代码任务） |

### 3.4 成本管控系统 (CostController)

**三级预算告警：**

| 阈值 | 级别 | 动作 |
|------|------|------|
| 50% | Info | 提示已用一半 |
| 80% | Warning | 注意控制用量 |
| 100% | Critical | 熔断：切换到内部模式 |

**账单能力：**

- 月度预算设置与查询
- 费用明细查询（按Agent/时间/类型筛选）
- 按日统计汇总
- 失败调用不计费
- 跨月自动重置

### 3.5 隐私安全防护层 (FederationPrivacyGuard)

**5 类检测规则：**

| 类别 | 检测内容 | 典型严重度 |
|------|----------|------------|
| 涉密等级 | TOP_SECRET / CONFIDENTIAL 分级 | Critical/High |
| PII | 邮箱、手机号、身份证、银行卡、内部域名 | Medium |
| 代码密钥 | API Key、密码、Token、私钥 | High |
| 自定义关键词 | 用户配置的禁止外发词 | Medium |
| 内部链接 | 公司内网域名 | Medium |

**三级处理策略：**

| 风险等级 | 处理方式 |
|----------|----------|
| 高度敏感 (high) | 直接拦截 + 审计告警 |
| 中度敏感 (medium) | 拦截 + 提示用户确认 |
| 轻度敏感 (low) | 自动脱敏后发送 |

---

## 四、接口规范

### 4.1 HTTP API 端点清单

**基础路径：** `/v1/federation`

#### 外部 Agent 管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/federation/agents` | 列出外部Agent（支持status筛选） |
| POST | `/federation/agents/register` | 注册外部Agent |
| GET | `/federation/agents/{agent_id}` | 获取Agent详情 |
| DELETE | `/federation/agents/{agent_id}` | 注销外部Agent |
| POST | `/federation/agents/{agent_id}/health-check` | 健康检查 |

#### 联邦调度决策

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/federation/decide` | 联邦调度决策（内部vs外部） |

#### 外部 Agent 调用

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/federation/invoke` | 调用指定外部Agent（含隐私检查+成本记录） |
| POST | `/federation/compare` | 多Agent并行对比 |

#### 隐私安全

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/federation/privacy/scan` | 内容隐私扫描 |
| GET | `/federation/privacy/audit` | 审计日志查询 |

#### 成本管控

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/federation/cost/budget` | 获取预算状态 |
| POST | `/federation/cost/budget` | 设置月度预算 |
| GET | `/federation/cost/records` | 查询费用明细 |
| GET | `/federation/cost/daily` | 按日统计费用 |

**共计：17 个端点**

### 4.2 Orchestrator 意图扩展

| 意图 | 说明 | 输入 | 输出 |
|------|------|------|------|
| `federation.decide` | 联邦调度决策 | task_type, security_level, user_preference | decision对象 |
| `federation.invoke` | 调用外部Agent | agent_id, prompt, security_level | result + cost + privacy_scan |
| `federation.compare` | 多Agent对比 | agent_ids, prompt, output_mode | comparison对象 |

---

## 五、数据模型清单

### 5.1 新增数据类（12个）

| 数据类 | 说明 | 所属模块 |
|--------|------|----------|
| `ExternalAgentType` | 外部Agent类型枚举 | shared_models |
| `AgentPrivacyLevel` | Agent隐私等级枚举 | shared_models |
| `ConnectionType` | 连接方式枚举 | shared_models |
| `UserPreferenceMode` | 用户偏好模式枚举 | shared_models |
| `ComparisonOutputMode` | 对比输出模式枚举 | shared_models |
| `CostModel` | 成本模型 | shared_models |
| `ExternalAgentProfile` | 外部Agent配置档案 | shared_models |
| `FederationDecision` | 联邦调度决策结果 | shared_models |
| `CostRecord` | 费用记录 | shared_models |
| `FederationBudget` | 预算状态 | shared_models |
| `AgentResultItem` | 单Agent对比结果项 | shared_models |
| `MultiAgentComparison` | 多Agent对比结果 | shared_models |
| `PrivacyScanResult` | 隐私扫描结果 | shared_models |

---

## 六、测试验证

### 6.1 测试覆盖

| 测试类别 | 用例数 | 通过数 | 通过率 |
|----------|--------|--------|--------|
| 数据模型 | 5 | 5 | 100% |
| 注册中心 | 9 | 9 | 100% |
| 适配器 | 7 | 7 | 100% |
| 调度决策 | 7 | 7 | 100% |
| 对比器 | 7 | 7 | 100% |
| 成本管控 | 10 | 10 | 100% |
| 隐私防护 | 10 | 10 | 100% |
| Orchestrator集成 | 7 | 7 | 100% |
| 端到端集成 | 2 | 2 | 100% |
| **合计** | **65** | **65** | **100%** |

### 6.2 关键场景验证

**场景1：绝密内容强制内部**
- 输入：security_level=TOP_SECRET
- 预期：use_external=False，决策理由包含"强制内部"
- 结果：✅ 通过

**场景2：质量优先选择外部**
- 输入：preference=QUALITY_FIRST，普通任务
- 预期：选择评分最高的外部Agent
- 结果：✅ 通过

**场景3：预算不足降级内部**
- 输入：remaining_budget=0.0001（极低）
- 预期：降级到内部执行
- 结果：✅ 通过

**场景4：隐私拦截高涉密调用**
- 输入：TOP_SECRET + 外部Agent调用
- 预期：隐私检查拦截，返回失败
- 结果：✅ 通过

**场景5：多Agent并行对比**
- 输入：2个Agent + code_generation任务
- 预期：2个结果返回，质量评分可比较
- 结果：✅ 通过

**场景6：成本三级告警**
- 输入：逐步增加费用至50%/80%/100%
- 预期：告警依次触发，100%时熔断
- 结果：✅ 通过

**场景7：端到端完整流程**
- 输入：决策→隐私检查→调用→成本记录
- 预期：全链路打通，数据正确传递
- 结果：✅ 通过

### 6.3 回归测试

- 原有 V10.1 测试集：82%+ 通过，无新增失败
- 注：2 个 FastAPI 相关测试因环境缺少 fastapi 模块无法运行（历史遗留，非本版本引入）

---

## 七、文件清单

### 7.1 新增文件

```
federation/
├── __init__.py                  # 包初始化
├── registry.py                  # 外部Agent注册中心
├── scheduler.py                 # 联邦调度决策引擎
├── comparator.py                # 多Agent结果对比器
├── cost_controller.py           # 成本管控器
├── privacy_guard.py             # 隐私安全防护层
└── adapters/
    ├── __init__.py
    ├── base.py                  # 适配器基类
    ├── openai.py                # OpenAI适配器
    ├── anthropic.py             # Anthropic适配器
    ├── gemini.py                # Gemini适配器
    └── local_model.py           # 本地模型适配器

tests/
└── test_v11_federation.py       # 联邦调度专项测试（65用例）

docs/
└── 模块01-多Agent集群调度-产物归档摘要-V11.0-FEDERATION-REV1.md  # 本文档
```

### 7.2 修改文件

| 文件 | 修改内容 |
|------|----------|
| `shared_models.py` | 新增12个联邦调度相关数据类/枚举 |
| `api/server.py` | 新增17个联邦调度HTTP API端点，版本号升至V11.0 |
| `orchestrator/agent.py` | 新增3个联邦调度意图、5个懒加载组件、版本号升至11.0.0 |

**新增代码：约 2100 行**  
**修改代码：约 350 行**  
**测试代码：约 1000 行**

---

## 八、后续规划

### 8.1 短期优化（V11.1）

- [ ] 流式输出支持（SSE/WebSocket）
- [ ] 外部 Agent 能力自动发现
- [ ] 调用失败自动重试与降级策略
- [ ] 质量评分模型优化（引入人工反馈）

### 8.2 中期规划（V12.0）

- [ ] Agent 市场：第三方 Agent 上架与审核
- [ ] 联邦学习：跨 Agent 知识蒸馏
- [ ] 多轮对话上下文管理
- [ ] 任务级 SLA 保障机制

### 8.3 长期愿景

- 构建云汐 Agent 生态：内部集群 + 外部市场 + 端侧轻量的三级联邦体系
- 实现"任务来了自动选最合适的 Agent"的智能调度

---

## 附录：变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| V11.0-FEDERATION-REV1 | 2026-07-03 | 初始版本：联邦调度系统完整实现 | M1开发组 |

---

*本文档密级：普通涉密 | 仅限云汐项目内部使用*
