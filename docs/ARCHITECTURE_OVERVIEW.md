# 云汐系统架构总览

> 版本：V12.0 · 更新时间：2026-07-16
> 文档类型：架构总览 · 适用范围：全系统

---

## 一、系统定位

云汐系统是一套以大语言模型为核心、模块化微服务架构的个人智能助理系统。采用「潮汐记忆 + 多Agent协作 + 场景化服务」三层架构，覆盖工作、学习、生活、休闲等全场景智能交互。

---

## 二、模块总览

### 2.1 模块矩阵（13个核心模块）

| 编号 | 模块名称 | 目录 | 端口 | 定位层级 | 核心职责 |
|------|---------|------|------|---------|---------|
| **M0** | 主理人管控台 | `M0-principal-console` | 8000 | 管控层 | 最高权限节点，全局仪表盘、模块管理、审计、紧急操作 |
| **M1** | 多Agent集群调度 | `M1-agent-hub` | 8001 | 核心服务层 | Agent联邦调度、8个子Agent管理、16+外部Adapter |
| **M2** | 技能集群 | `M2-skills-cluster` | 8002 | 能力扩展层 | 技能注册/发现/路由/执行，18种内置技能，MCP/A2A接入 |
| **M3** | 端云协同内核 | `M3-edge-cloud` | 8003 | 基础设施层 | 端云混合调度，隐私保护 + 算力增强 |
| **M4** | 业务场景引擎 | `M4-scene-engine` | 8004 | 业务调度层 | 场景智能切换（工作/学习/生活/休闲） |
| **M5** | 潮汐分层记忆 | `M5-tide-memory` | 8005 | 核心数据层 | 四层潮汐记忆模型（沙滩/浅水/深水/深海） |
| **M6** | 穿戴硬件外设 | `M6-hardware-peripheral` | 8006 | 设备接入层 | 6种设备管理（手表/戒指/AR/桌面屏/无人机/笔记本） |
| **M7** | 积木编排平台 | `M7-workflow-builder` | 8007 | 生产力层 | 可视化工作流编排，DAG执行，条件分支 |
| **M8** | 管理控制塔 | `M8-control-tower` | 8008 | 管控核心层 | 用户认证、模块纳管、算力调度、自进化引擎 |
| **M9** | 开发者工坊 | `M9-dev-workshop` | 8009 | 生产力层 | VSCode管理、工作区管理、MCP桥接、代码沙箱 |
| **M10** | 系统卫士 | `M10-system-guard` | 8010 | 基础设施层 | 资源监控、进程管理、阈值防护、GPU智能调度 |
| **M11** | MCP总线服务 | `M11-mcp-bus` | 8011 | 基础设施层 | MCP服务注册/发现/路由/调用，工具聚合 |
| **M12** | 安全盾 | `M12-security-shield` | 8012 | 安全防护层 | WAF防护、密钥管理、速率限制、威胁检测 |

### 2.2 模块依赖关系

```
M0 主理人管控台 (管控入口)
  ↓ 纳管
M8 管理控制塔 (统一管控)
  ├─ 调用 → M1 Agent集群  ←→ M2 技能集群
  ├─ 调用 → M4 场景引擎
  ├─ 调用 → M5 潮汐记忆
  ├─ 调用 → M7 工作流编排
  ├─ 调用 → M9 开发者工坊
  ├─ 调用 → M6 硬件外设
  └─ 依赖 → M11 MCP总线 / M12 安全盾 / M10 系统卫士 / M3 端云协同
```

---

## 三、架构分层

### 3.1 七层架构模型

| 层级 | 包含模块 | 核心能力 |
|------|---------|---------|
| **管控层** | M0、M8 | 全局管理、用户认证、系统监控、配置中心 |
| **业务调度层** | M4 | 场景识别、模式切换、上下文路由 |
| **智能核心层** | M1、M2、M5 | Agent调度、技能执行、记忆存储 |
| **生产力层** | M7、M9 | 工作流编排、开发工具链 |
| **基础设施层** | M3、M10、M11 | 端云协同、系统监控、MCP总线 |
| **安全防护层** | M12 | WAF、鉴权、速率限制、威胁检测 |
| **设备接入层** | M6 | 多设备管理、数据采集、远程控制 |

---

## 四、M8 控制塔路由总览

M8 是系统的统一管理中枢，包含 **47个路由模块**，分为以下类别：

### 4.1 基础管理类（8个）
| 路由 | 功能 |
|------|------|
| `auth.py` | 用户认证、JWT Token管理 |
| `users.py` | 用户管理 |
| `system.py` | 系统设置、API密钥、模块Token |
| `audit.py` | 审计日志 |
| `modules.py` | 模块纳管（健康/指标/代理） |
| `monitor.py` | 监控中心、告警管理 |
| `deploy.py` | 部署中心、进程管理 |
| `security.py` | 安全功能、紧急制动 |

### 4.2 算力调度类（8个）
| 路由 | 功能 |
|------|------|
| `compute_sources.py` | 算力源管理 |
| `compute_groups.py` | 算力分组 |
| `compute_models.py` | 模型配置 |
| `compute_routing.py` | 路由策略、故障转移、熔断 |
| `compute_monitor.py` | 算力监控统计 |
| `compute_config.py` | 算力调度配置 |
| `compute_skills.py` | 技能调度 |
| `compute_gpu.py` | GPU算力源、任务管理 |

### 4.3 自进化引擎类（3个）
| 路由 | 功能 |
|------|------|
| `evolution_planner.py` | 进化规划、健康扫描 |
| `evolution_deployer.py` | 部署治理、版本管理、一键回滚 |
| `evolution_auditor.py` | 安全审计、风险评级 |

### 4.4 业务功能类（14个）
| 路由 | 功能 |
|------|------|
| `chat.py` | 主聊天接口 |
| `brain.py` | 知识库管理 |
| `agents.py` | Agent与密钥管理 |
| `memory.py` | M5记忆代理 |
| `growth.py` | 成长中心（成就/天赋/赛季等7子系统） |
| `workflow.py` | M7工作流管理 |
| `review.py` | 复盘总结、情绪追踪 |
| `study_plan.py` | 学业规划 |
| `life_management.py` | 生活管理 |
| `emotion_comfort.py` | 情绪陪伴 |
| `social_relation.py` | 人际关系 |
| `appearance.py` | 形象工坊 |
| `work_dev.py` | 工作开发模式 |

### 4.5 其他类（14个）
场景与模式（3个）、语音与提醒（3个）、硬件与设备（3个）、工具与其他（5个）

---

## 五、Shared 共享库总览

### 5.1 基础核心模块
- `config.py` — 全局配置中心
- `logger.py` — 统一结构化日志
- `llm_client.py` — LLM客户端（多后端）
- `module_client.py` — 模块间HTTP调用
- `process_manager.py` — 进程管理器
- `errors.py` — 统一异常体系
- `responses.py` — 标准化API响应
- `utils.py` — 通用工具函数
- `auth.py` — 轻量级鉴权工具

### 5.2 分布式 & 中间件
- `distributed/` — 节点注册、集群总线、分布式API
- `middleware/tracing.py` — 链路追踪中间件

### 5.3 业务能力模块
- Agent体系：`agent_engine.py`、`multi_agent.py`、`agent_team.py`
- 工具系统：`tool_system.py`、`builtin_tools.py`
- 推理与路由：`reasoning_engine.py`、`model_router.py`
- 记忆与知识：`long_term_memory.py`、`rag_knowledge.py`
- 用户与上下文：`user_profile.py`、`context_aware.py`
- 多模态：`multimodal.py`

### 5.4 进化与学习模块
- `autonomous_learning.py` — 自主学习
- `personality_engine.py` — 人格引擎
- `skill_evolution.py` — 技能进化

### 5.5 语音相关模块
- `voice_engine.py`、`cosyvoice_client.py`、`cosyvoice_server.py`
- `voice_preset_manager.py`、`prosody_controller.py`
- `reminder_voice.py`

---

## 六、启动方式

### 6.1 一键启动
```powershell
# 普通启动
.\start-all.ps1

# 等待健康检查通过
.\start-all.ps1 -WaitForHealth
```

### 6.2 启动顺序（4个批次）
1. **基础设施**：M5 → M11 → M12
2. **核心服务**：M1 → M4 → M8
3. **业务模块**：M2 → M3 → M6 → M7 → M9 → M10
4. **管控台**：M0

### 6.3 停止
```powershell
.\stop-all.ps1
```

---

## 七、技术栈

| 类别 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| 语言 | Python 3.10+ |
| 数据库 | SQLite（各模块独立） |
| 前端 | Vue 3 + Element Plus |
| 大模型 | DeepSeek / OpenAI / Ollama（可切换） |
| 部署 | Docker / 本地进程 |
| 协议 | HTTP/REST + SSE + WebSocket |
| 工具协议 | MCP / A2A |

---

## 八、版本历史

| 版本 | 代号 | 核心特性 |
|------|------|---------|
| V9.x | 集群调度 | 多Agent集群调度架构 |
| V10.0 | 八子Agent | 8个子Agent + DAG编排 + API层升级 |
| V11.0 | 联邦调度 | 联邦调度系统 + 16个外部Agent Adapter |
| V11.1 | M8对接 | M8标准接口 + 整合优化 |
| V12.0 | 安全盾 + 自进化 | M12安全盾 + 自进化引擎 + 工程化升级 |
