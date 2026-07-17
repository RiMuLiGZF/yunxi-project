# 云汐 (Yunxi) — AI 原生个人操作系统

> **一个运行在本地设备上的 AI 原生个人操作系统，13 个微服务模块化架构，让 AI 真正为你所用。**
>
> 📦 **版本**：v0.9.1（第四阶段 · 生产就绪）
> 📅 **更新日期**：2026-07-17

---

## 目录

- [项目简介](#项目简介)
- [系统架构总览](#系统架构总览)
- [核心特性](#核心特性)
- [快速开始](#快速开始)
- [模块列表](#模块列表)
- [技术栈](#技术栈)
- [文档索引](#文档索引)
- [版本信息](#版本信息)
- [变更日志](#变更日志)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 项目简介

**云汐 (Yunxi)** 是一套面向重度 AI 使用者、个人开发者和知识工作者的 **AI 原生个人操作系统**。它采用 **13 个微服务模块化架构**，全部运行在用户本地设备上，解决三大核心痛点：

- **AI 工具碎片化** — 翻译、搜索、数据分析、代码生成散落在不同工具中，切换成本高
- **云端依赖与隐私风险** — 个人数据被迫上传到第三方服务器，缺乏自主控制权
- **AI 能力扩展困难** — 难以将通用 AI 能力适配到个人专属的工作流与知识体系中

云汐通过统一的身份认证、模块化的技能集群、可视化的工作流编排，以及本地优先的数据存储，构建了一个 **可扩展、可定制、数据自主** 的 AI 操作系统。

---

## 系统架构总览

云汐系统采用 **七层架构模型**，13 个核心模块 + API 网关各司其职，通过 M8 管理控制塔统一纳管。

```
┌───────────────────────────────────────────────────────────┐
│                    管控层 (Control)                        │
│   M0 主理人管控台  │  M8 管理控制塔                         │
├───────────────────────────────────────────────────────────┤
│                    业务调度层 (Orchestration)               │
│   M4 业务场景引擎  │  M7 积木编排平台                       │
├───────────────────────────────────────────────────────────┤
│                    智能核心层 (Intelligence)                │
│   M1 多Agent集群  │  M2 技能集群  │  M5 潮汐记忆            │
├───────────────────────────────────────────────────────────┤
│                    生产力层 (Productivity)                  │
│   M9 开发者工坊                                             │
├───────────────────────────────────────────────────────────┤
│                    基础设施层 (Infrastructure)              │
│   M3 端云协同内核 │  M10 系统卫士 │  M11 MCP 总线            │
├───────────────────────────────────────────────────────────┤
│                    安全防护层 (Security)                    │
│   M12 安全盾                                                │
├───────────────────────────────────────────────────────────┤
│                    设备接入层 (Devices)                     │
│   M6 穿戴硬件外设                                           │
└───────────────────────────────────────────────────────────┘
                          ↓
              ┌─────────────────────┐
              │   API Gateway 网关   │
              │   (统一接入 · 8080)  │
              └─────────────────────┘
```

> **详细架构说明**：参见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## 核心特性

### 🏗️ 13 模块微服务架构

13 个独立模块，每个模块职责单一、可独立部署和扩展。模块间通过标准化的 M8 接口和 MCP 总线通信，松耦合高内聚。

### 🤖 联邦多 Agent 调度

M1 调度中心支持 8 个子 Agent + 16+ 外部 Adapter 的联邦调度，智能路由任务到最合适的 Agent，支持成本控制、隐私保护和故障转移。

### 🔌 统一 MCP 工具总线

M11 MCP 总线将各模块能力封装为 **87 个标准 MCP 工具**，实现跨模块能力调用：

```
M1.agent_list → M2.translate → M7.workflow_run → M12.security_audit
```

### 🧠 潮汐分层记忆

M5 潮汐记忆采用四层记忆模型（沙滩/浅水/深水/深海），模拟人类记忆巩固机制，支持情绪推断、睡眠巩固和跨设备同步。

### 🎨 可视化工作流编排

M7 积木编排平台提供可视化 DAG 工作流设计，支持条件分支、循环、并行执行，内置模板市场，工作流可一键分享和复用。

### 🔒 本地优先 · 隐私可控

- 所有个人数据存储在本地 SQLite / FAISS 向量库
- JWT + AES-256-GCM 加密存储
- 端云协同支持离线降级，无网络也能用
- M12 安全盾提供 WAF、速率限制、IP 控制等防护

### 🌐 端云协同

M3 端云协同内核实现本地与云端的混合调度，隐私敏感任务在本地执行，复杂计算卸载到云端，网络断开时自动降级为纯本地模式。

---

## 快速开始

### 环境要求

- **Python** 3.10+
- **操作系统**：Windows / Linux / macOS
- **可选**：Docker & Docker Compose
- **可选**：Ollama（本地 LLM 推理）

### 5 步启动

```powershell
# 第 1 步：克隆仓库
git clone https://github.com/RiMuLiGZF/yunxi-project.git
cd yunxi-project

# 第 2 步：复制配置模板
Copy-Item config\yunxi.env.example config\yunxi.env
# 编辑 config\yunxi.env，配置必要的 API Key 和密钥

# 第 3 步：安装核心模块依赖（以 M8 为例）
cd M8-control-tower\backend
pip install -r requirements.txt
cd ..\..

# 第 4 步：一键启动全部模块
.\scripts\start-all.ps1

# 第 5 步：验证系统运行
.\scripts\health-check.ps1
```

启动成功后访问：

- **主理人管控台**：http://localhost:8000
- **管理控制塔**：http://localhost:8008
- **API 网关**：http://localhost:8080

> **详细部署指南**：参见 [docs/OPS.md](docs/OPS.md)

---

## 模块列表

| 编号 | 模块名称 | 目录 | 端口 | 定位层级 | 核心职责 |
|------|---------|------|------|---------|---------|
| **M0** | 主理人管控台 | `M0-principal-console` | 8000 | 管控层 | 最高权限节点，全局仪表盘、模块管理、审计、紧急操作 |
| **M1** | 多Agent集群调度 | `M1-agent-hub` | 8001 | 智能核心层 | Agent联邦调度、8个子Agent管理、16+外部Adapter |
| **M2** | 技能集群 | `M2-skills-cluster` | 8002 | 智能核心层 | 技能注册/发现/路由/执行，18种内置技能，MCP/A2A接入 |
| **M3** | 端云协同内核 | `M3-edge-cloud` | 8003 | 基础设施层 | 端云混合调度，隐私保护 + 算力增强 |
| **M4** | 业务场景引擎 | `M4-scene-engine` | 8004 | 业务调度层 | 场景智能切换（工作/学习/生活/休闲） |
| **M5** | 潮汐分层记忆 | `M5-tide-memory` | 8005 | 智能核心层 | 四层潮汐记忆模型（沙滩/浅水/深水/深海） |
| **M6** | 穿戴硬件外设 | `M6-hardware-peripheral` | 8006 | 设备接入层 | 6种设备管理（手表/戒指/AR/桌面屏/无人机/笔记本） |
| **M7** | 积木编排平台 | `M7-workflow-builder` | 8007 | 业务调度层 | 可视化工作流编排，DAG执行，条件分支 |
| **M8** | 管理控制塔 | `M8-control-tower` | 8008 | 管控层 | 用户认证、模块纳管、算力调度、自进化引擎 |
| **M9** | 开发者工坊 | `M9-dev-workshop` | 8009 | 生产力层 | VSCode管理、工作区管理、MCP桥接、代码沙箱 |
| **M10** | 系统卫士 | `M10-system-guard` | 8010 | 基础设施层 | 资源监控、进程管理、阈值防护、GPU智能调度 |
| **M11** | MCP总线服务 | `M11-mcp-bus` | 8011 | 基础设施层 | MCP服务注册/发现/路由/调用，工具聚合 |
| **M12** | 安全盾 | `M12-security-shield` | 8012 | 安全防护层 | WAF防护、密钥管理、速率限制、威胁检测 |
| **GW** | API 网关 | `API-Gateway` | 8080 | 接入层 | 统一接入、路由转发、认证鉴权、熔断降级 |

> 🔒 **M5 为核心私有模块**，仅保留在本地设备，不包含于公开仓库。

---

## 技术栈

| 层级 | 技术选型 |
|------|---------|
| **后端框架** | Python 3.10+ · FastAPI · SQLAlchemy · Pydantic |
| **前端** | Vue 3 + Vite · SPA 单页应用 · Pinia · Vue Router |
| **AI 推理** | Ollama 本地 LLM · DeepSeek · OpenAI 兼容协议 |
| **向量检索** | FAISS · ChromaDB |
| **数据存储** | SQLite（本地优先）· JSON 配置 · 内存缓存 |
| **协议标准** | MCP · A2A · OneBot v11 · OpenAI API · RESTful |
| **安全** | JWT (HS256) · AES-256-GCM · bcrypt · WAF · 速率限制 |
| **缓存与消息** | Redis（可选）· 内存令牌桶 |
| **部署** | Docker Compose · PowerShell 脚本 · 裸机进程 |
| **测试** | pytest · pytest-cov · httpx · unittest.mock |
| **监控** | Prometheus + Grafana（Docker profile）· 内置健康检查 |

---

## 文档索引

### 核心文档

| 文档 | 说明 | 路径 |
|------|------|------|
| **架构文档** | 系统架构总览、模块详细说明、技术决策 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| **API 文档** | API 设计规范、各模块端点、认证方式 | [docs/API.md](docs/API.md) |
| **运维手册** | 日常运维、监控告警、备份恢复、故障排查 | [docs/OPS.md](docs/OPS.md) |
| **开发者指南** | 环境搭建、代码规范、测试规范、调试技巧 | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| **变更日志** | 版本历史、功能变更、Bug 修复记录 | [CHANGELOG.md](CHANGELOG.md) |
| **贡献指南** | 参与贡献的规范和流程 | [CONTRIBUTING.md](CONTRIBUTING.md) |

### 专项文档

| 文档 | 说明 | 路径 |
|------|------|------|
| **部署手册** | 生产环境部署与运维 | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| **安全文档** | 安全架构、防护措施、漏洞响应 | [docs/SECURITY.md](docs/SECURITY.md) |
| **灾难恢复** | 备份策略、恢复流程、RPO/RTO | [docs/DISASTER_RECOVERY.md](docs/DISASTER_RECOVERY.md) |
| **发展路线图** | 系统演进规划与里程碑 | [docs/云汐系统发展路线图v2.0.md](docs/云汐系统发展路线图v2.0.md) |

### 模块文档

| 模块 | 文档路径 |
|------|---------|
| M1 多Agent集群 | [M1-agent-hub/README.md](M1-agent-hub/README.md) |
| M2 技能集群 | [M2-skills-cluster/README.md](M2-skills-cluster/README.md) |
| M3 端云协同 | [M3-edge-cloud/README.md](M3-edge-cloud/README.md) |
| M4 场景引擎 | [M4-scene-engine/README.md](M4-scene-engine/README.md) |
| M5 潮汐记忆 | [M5-tide-memory/README.md](M5-tide-memory/README.md) |
| M6 硬件外设 | [M6-hardware-peripheral/README.md](M6-hardware-peripheral/README.md) |
| M7 积木编排 | [M7-workflow-builder/README.md](M7-workflow-builder/README.md) |
| M8 控制塔 | [M8-control-tower/README.md](M8-control-tower/README.md) |
| M9 开发工坊 | [M9-dev-workshop/README.md](M9-dev-workshop/README.md) |
| M10 系统卫士 | [M10-system-guard/README.md](M10-system-guard/README.md) |
| M11 MCP总线 | [M11-mcp-bus/README.md](M11-mcp-bus/README.md) |
| M12 安全盾 | [M12-security-shield/README.md](M12-security-shield/README.md) |
| API 网关 | [API-Gateway/README.md](API-Gateway/README.md) |

### 目录说明

| 目录 | 说明 | 文档 |
|------|------|------|
| `shared/` | 公共组件库（三层架构） | [shared/README.md](shared/README.md) |
| `docs/` | 项目文档目录 | [docs/README.md](docs/README.md) |
| `scripts/` | 运维与工具脚本 | [scripts/README.md](scripts/README.md) |
| `tests/` | 测试用例目录 | [tests/README.md](tests/README.md) |

### 参考规范

| 文档 | 说明 | 路径 |
|------|------|------|
| **错误码规范** | 统一错误码体系 | [shared/core/ERROR_CODES.md](shared/core/ERROR_CODES.md) |
| **配置指南** | 全局配置说明 | [shared/core/CONFIG_GUIDE.md](shared/core/CONFIG_GUIDE.md) |
| **健康检查指南** | M8 标准健康检查接口 | [shared/core/HEALTH_GUIDE.md](shared/core/HEALTH_GUIDE.md) |
| **数据迁移指南** | 数据库迁移 | [shared/data/MIGRATION_GUIDE.md](shared/data/MIGRATION_GUIDE.md) |
| **备份指南** | 数据备份与恢复 | [shared/data/BACKUP_GUIDE.md](shared/data/BACKUP_GUIDE.md) |
| **性能指南** | 性能调优 | [shared/data/PERFORMANCE_GUIDE.md](shared/data/PERFORMANCE_GUIDE.md) |

---

## 版本信息

### 版本演进

| 版本 | 时间 | 代号 | 核心交付 |
|------|------|------|----------|
| v0.6.0 | 2026-07-13 | 集群起步 | 12 模块集群完整跑通 |
| v0.7.0 | 2026-07-14 | 前端场景 | Vue3 前端 + M4 多模态场景引擎 |
| v0.8.0 | 2026-07-15 | 分布式 | 节点注册发现 + 跨节点消息总线 + 联邦调度 |
| v0.9.0 | 2026-07-15 | 内容生态 | 技能市场 + 模板市场 + 记忆共享 + MCP 扩展 |
| v0.9.1 | 2026-07-16 | 安全加固 | JWT 密钥去硬编码 + 安全审计 + 文档体系 |

### 项目数据

- **13 个微服务模块**（12 个开源 + 1 个私有）
- **87 个 MCP 工具**
- **100+ RESTful API 端点**
- **12 个 Vue 3 前端页面**
- **2,109 项测试用例**

---

## 变更日志

详细的版本变更记录请参阅 [CHANGELOG.md](CHANGELOG.md)。

变更日志遵循 **Keep a Changelog** 规范，版本号遵循 **语义化版本** 规范，按版本倒序排列。

---

## 贡献指南

欢迎参与云汐项目的贡献！详细的贡献规范和流程请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)。

内容包括：
- 如何报告 Bug 和提交功能建议
- 开发环境搭建步骤
- Python 代码规范和命名约定
- Conventional Commits 提交规范
- 分支策略和 Pull Request 流程
- 模块开发规范和 M8 标准对接要求
- Issue 模板

---

## 许可证

本项目采用 **云汐开源许可证**，核心原则：

- ✅ 个人使用、学习、修改完全免费
- ✅ 非商业用途的二次分发需注明出处
- ❌ 禁止用于商业产品或服务
- ❌ M5 潮汐记忆模块为私有模块，不对外开源

详细条款请参阅项目根目录下的许可证文件。

---

<p align="center">
  <sub>Built with 💙 using <a href="https://www.trae.cn/">TRAE</a></sub>
</p>
