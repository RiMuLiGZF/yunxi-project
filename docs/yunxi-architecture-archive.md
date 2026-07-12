# 云汐系统架构归档文档 v1.0

> 文档版本：v1.0
> 归档日期：2026-07-07
> 项目路径：`yunxi-project/`
> 文档状态：正式归档

---

## 第一部分：总架构总览

### 1.1 系统定位与设计理念

#### 云汐是什么

云汐（Yunxi）是一套基于多 Agent 协同的个人智能助理系统，采用八大模块微服务架构设计。系统以「潮汐」为核心隐喻，将 AI 能力具象化为随用户状态流动变化的智能伙伴，覆盖工作、学习、生活、情感等全场景。

云汐的核心定位：
- **个人化 AI 操作系统**：统一调度大模型、技能、记忆、硬件等能力
- **多 Agent 协同平台**：8 大子 Agent 分工协作，联邦调度决策
- **场景化智能引擎**：6 大场景模式自动切换，上下文无缝迁移
- **本地优先隐私架构**：数据本地存储加密，支持端云协同与离线运行

#### 八大模块架构设计理念

云汐采用「管控层 + 调度层 + 能力层 + 编排层」的四层架构设计，共 8 个模块（M1-M8）：

| 层级 | 模块 | 名称 | 核心定位 |
|------|------|------|----------|
| 管控层 | M8 | 管理工作台 | 统一入口、用户鉴权、模块管控、业务聚合 |
| 调度层 | M1 | 多Agent调度中心 | 任务调度、Agent管理、联邦决策 |
| 能力层 | M2 | 技能集群 | 工具技能、能力发现、智能路由 |
| 能力层 | M3 | 端云协同内核 | 端云同步、离线缓存、冲突消解 |
| 能力层 | M4 | 场景引擎 | 场景识别、切换管理、上下文维护 |
| 能力层 | M5 | 潮汐记忆系统 | 分层记忆、向量检索、情绪关联 |
| 能力层 | M6 | 硬件外设 | 穿戴设备、传感器、实时数据流 |
| 编排层 | M7 | 积木编排平台 | 可视化工作流、自定义自动化 |

设计理念遵循以下原则：

1. **微服务独立部署**：每个模块独立进程、独立端口，可单独启停升级
2. **统一通信协议**：HTTP REST + JSON，标准响应格式 `{code, message, data}`
3. **M8 统一管控**：所有模块通过 M8 鉴权、注册、监控，M8 是唯一用户入口
4. **故障隔离降级**：单模块故障不影响整体，各模块具备 Mock/降级模式
5. **本地优先隐私**：核心数据本地存储加密，云端能力可选配置

#### M8 管控层 vs M4 业务层的权责划分

| 维度 | M8 管控层 | M4 业务场景层 |
|------|-----------|---------------|
| 定位 | 系统级管控枢纽 | 业务场景调度引擎 |
| 职责 | 用户管理、权限、模块监控、部署、数据聚合 | 场景识别、切换、上下文管理、模式路由 |
| 数据 | 用户、任务、告警、成长等系统级数据 | 场景配置、上下文、切换历史 |
| 入口 | 所有前端页面的 API 入口 | M8 调用的下游服务 |
| 鉴权 | JWT Token（用户级） | X-M8-Token（模块间） |
| 数据库 | SQLite (m8.db) - 34 张业务表 | JSON 文件持久化 |
| 业务模式 | 代理转发 + 数据聚合，承载业务数据存储 | 6 大场景的识别与切换调度逻辑 |

---

### 1.2 全局架构图（文字版）

#### 层级结构

```
┌─────────────────────────────────────────────────────────┐
│                    前端表现层 (Frontend)                  │
│  /m8 (管理台)  /xian (汐舷)  /modes (模式页)  /m7 (积木)  │
│  /startup (启动页)  /common (公共组件)                    │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP REST + JWT
┌──────────────────────────▼──────────────────────────────┐
│              M8 管控层 (Control Tower) :8000             │
│  用户认证 | 模块管理 | 监控告警 | 部署中心 | 业务聚合      │
│  代理转发 M1-M7 所有模块 API                              │
└─────┬──────────┬──────────┬──────────┬──────────┬───────┘
      │          │          │          │          │
      ▼          ▼          ▼          ▼          ▼
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ M1 调度 │ │ M2 技能 │ │ M3 端云 │ │ M4 场景 │ │ M5 记忆 │
│ :8001   │ │ :8002   │ │ :8003   │ │ :8004   │ │ :8005   │
└────┬────┘ └─────────┘ └─────────┘ └────┬────┘ └────┬────┘
     │                                     │           │
     │                                     ▼           ▼
     │                              ┌─────────┐ ┌─────────┐
     │                              │ M6 硬件 │ │ M7 编排 │
     │                              │ :8006   │ │ :3001   │
     │                              └─────────┘ └─────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│                    大模型层 (LLM Layer)                   │
│  Ollama (本地) | DeepSeek/OpenAI (云端) | 向量嵌入模型    │
└─────────────────────────────────────────────────────────┘
```

#### 模块间调用链路

**主调用链路（用户请求）：**
```
用户 → 前端页面 → M8 API → [JWT鉴权] → 业务路由
  ├─ 聊天/Agent任务 → M1 (任务调度) → M2 (技能调用) → M5 (记忆读写)
  ├─ 场景切换 → M4 (场景引擎) → 上下文持久化
  ├─ 记忆检索 → M5 (潮汐记忆) → 向量/关键词检索
  ├─ 工作流 → M7 (积木平台) → 编排执行
  ├─ 设备数据 → M6 (硬件外设) → SSE实时推送
  └─ 系统管理 → M8 本地处理 + 模块健康检查
```

**横向调用链路（模块间）：**
```
M1 ←→ M2  (调度器调用技能执行)
M1 ←→ M5  (任务记忆存取)
M3 ←→ M5  (端云记忆同步)
M4 ←→ M5  (场景上下文记忆)
M4 ←→ M1  (场景切换触发Agent调整)
M7 ←→ M1  (工作流节点调用Agent)
M7 ←→ M2  (工作流节点调用技能)
M8 → 所有模块  (健康检查/指标采集/配置管理)
```

#### 数据流走向

1. **输入流**：用户输入 → M8 认证 → M1 调度 → 意图识别 → 路由到对应能力模块
2. **记忆流**：对话/操作 → M5 归档（L0滩涂→L1浅层→L2深层→L3深渊）→ 巩固/遗忘
3. **场景流**：行为数据 → M4 识别 → 场景切换 → 上下文迁移 → 触发 M1/M2 调整
4. **设备流**：传感器 → M6 采集 → SSE推送 → M8 展示/告警
5. **同步流**：本地数据 → M3 同步队列 → 云端 → 冲突检测 → 消解
6. **工作流**：M7 编排定义 → 触发执行 → 节点调用 M1/M2 → 结果回写

#### 进程通信方式（HTTP REST + JSON）

- **协议**：HTTP/1.1 RESTful API
- **数据格式**：application/json
- **统一响应格式**：
  ```json
  {
    "code": 0,
    "message": "ok",
    "data": { ... }
  }
  ```
- **模块间鉴权**：请求头 `X-M8-Token: <module-admin-token>`
- **用户鉴权**：请求头 `Authorization: Bearer <jwt-token>`
- **请求追踪**：`X-Trace-Id` / `X-Request-ID` 响应头

---

### 1.3 技术栈总览

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| **后端框架** | Python 3.10+ + FastAPI + Uvicorn | 所有模块统一使用 FastAPI 异步框架 |
| **前端** | 纯 HTML/CSS/JS + Tailwind CSS | 无构建工具，直接静态文件服务 |
| **数据库** | SQLite + SQLAlchemy | M8/M5 使用关系型数据库 |
| **向量存储** | 本地向量索引（M5内置） | 基于嵌入向量的语义检索 |
| **ORM** | SQLAlchemy + Alembic | 数据模型与迁移管理 |
| **大模型** | Ollama（本地）+ 可配置云端（DeepSeek/OpenAI） | 支持多 Provider 切换 |
| **鉴权** | JWT Token（用户级）+ X-M8-Token（模块间） | 双层鉴权机制 |
| **进程管理** | 独立 Python 进程 + 端口监听 | 各模块独立进程 |
| **日志** | structlog / logging | 结构化 JSON 日志 |
| **HTTP客户端** | httpx | 模块间异步 HTTP 调用 |
| **配置管理** | python-dotenv + YAML | 环境变量 + 配置文件 |
| **实时通信** | SSE (Server-Sent Events) | M6 硬件数据推送、流式对话 |
| **密码加密** | bcrypt | 用户密码哈希 |
| **数据加密** | AES-256-GCM | M5 潮汐记忆本地加密 |

---

### 1.4 数据存储划分

| 模块 | 存储方式 | 数据库/文件 | 核心数据 |
|------|----------|-------------|----------|
| **M8 管控层** | SQLite 关系型 | `M8-control-tower/data/m8.db` | 用户、任务、告警、成长、工作开发、复盘、学业、生活、情绪、社交、形象等 34 张表 |
| **M1 调度中心** | 内存为主 + 配置持久化 | `config.yaml` | Agent注册信息、任务状态（运行时）、配置参数 |
| **M2 技能集群** | 内存 + 插件式加载 | 代码内技能定义 | 技能注册表、技能缓存、调用统计 |
| **M3 端云协同** | SQLite + 本地文件 | `data/offline_queue.db` | 同步队列、冲突记录、本地数据缓存 |
| **M4 场景引擎** | JSON 文件持久化 | `data/` 目录 | 场景配置、上下文数据、切换历史 |
| **M5 潮汐记忆** | SQLite + 向量存储 | `data/` 目录 | 四层记忆数据、向量索引、加密存储、审计日志 |
| **M6 硬件外设** | 内存 + 模拟数据 | 运行时内存 | 设备状态、传感器数据（实时模拟） |
| **M7 积木平台** | JSON 文件持久化 | `~/.yunxi/` 或 `data/` | 工作流定义、模板、运行记录 |

#### M8 数据库表清单（34 张表）

| 分类 | 表名 | 说明 |
|------|------|------|
| 系统基础 | users | 用户表 |
| 系统基础 | modules | 模块记录表 |
| 系统基础 | tasks | 任务记录表 |
| 系统基础 | alerts | 告警记录表 |
| 成长中心 | growth_achievements | 成就表 |
| 成长中心 | growth_talents | 天赋树节点表 |
| 成长中心 | growth_talent_meta | 天赋树元数据 |
| 成长中心 | growth_seasons | 赛季表 |
| 成长中心 | growth_season_tasks | 赛季任务表 |
| 成长中心 | growth_memories | 记忆回响表 |
| 成长中心 | growth_chronicles | 成长纪事表 |
| 成长中心 | growth_calendar | 潮汐日历/打卡表 |
| 工作开发 | work_projects | 项目表 |
| 工作开发 | work_tasks | 任务表 |
| 工作开发 | work_commits | 提交记录表 |
| 复盘总结 | review_reviews | 复盘记录表 |
| 复盘总结 | review_diaries | 日记表 |
| 复盘总结 | review_decisions | 决策记录表 |
| 复盘总结 | review_emotions | 情绪记录表 |
| 复盘总结 | review_biases | 认知偏差表 |
| 学业规划 | study_goals | 学习目标表（树形） |
| 学业规划 | study_plans | 学习计划表 |
| 学业规划 | study_notes | 学习笔记表 |
| 学业规划 | study_knowledge_categories | 知识分类表 |
| 学业规划 | study_exams | 考试计划表 |
| 学业规划 | study_progress | 科目进度表 |
| 学业规划 | study_meta | 元数据表 |
| 生活管理 | life_schedules | 日程表 |
| 生活管理 | life_rules | 自动化规则表 |
| 生活管理 | life_todos | 待办事项表 |
| 生活管理 | life_habits | 习惯打卡表 |
| 生活管理 | life_scenes | 场景模式表 |
| 生活管理 | life_finance_categories | 财务分类表 |
| 生活管理 | life_meta | 元数据表 |

---

### 1.5 模块通信协议

#### 统一响应格式

所有模块 API 遵循统一的响应格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": { ... },
  "trace_id": "abc123def456",
  "timestamp": 1234567890.123
}
```

- `code`: 状态码，0 表示成功，非 0 表示错误
- `message`: 状态描述文本
- `data`: 响应数据（对象或数组）
- `trace_id`: 请求追踪 ID（部分模块支持）
- `timestamp`: 响应时间戳（部分模块支持）

#### 鉴权方式

**1. 用户级鉴权（M8 面向前端）**
- 方式：JWT Bearer Token
- 请求头：`Authorization: Bearer <jwt-token>`
- 算法：HS256
- 有效期：24 小时（默认）
- 登录端点：`POST /api/auth/login`

**2. 模块间鉴权（M8 → 其他模块 / 模块互调）**
- 方式：Admin Token 白名单
- 请求头：`X-M8-Token: <module-admin-token>`
- 各模块独立 Token，通过环境变量配置
- 健康检查端点通常免鉴权

#### 健康检查标准接口

所有模块必须实现 `/health` 端点，返回标准格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "status": "healthy",
    "version": "x.y.z",
    "module": "mx"
  }
}
```

状态值：`healthy` / `degraded` / `unhealthy`

#### 指标接口

- 标准路径：`/metrics` 或 `/api/vX/admin/metrics` 或 `/api/vX/metrics`
- 格式：JSON 格式性能指标（M1 另提供 Prometheus 格式）
- 包含指标：请求数、错误率、平均响应时间、资源使用率等

---

## 第二部分：分模块详解

### M8 - 管理工作台（Control Tower）

#### 基本信息

| 项目 | 内容 |
|------|------|
| 模块代号 | M8 |
| 中文名称 | 管理工作台 / 控制塔 |
| 英文名称 | Control Tower |
| 版本号 | 1.0.0 |
| 监听端口 | 8000 |
| 技术栈 | Python + FastAPI + SQLAlchemy + Alembic + JWT + 静态文件服务 |
| 启动方式 | `python -m uvicorn M8-control-tower.backend.main:app --host 0.0.0.0 --port 8000` |
| 入口文件 | `M8-control-tower/backend/main.py` |

#### 定位与职责

M8 是云汐系统的统一管控枢纽和用户唯一入口，承担「管控 + 聚合 + 代理」三重角色。

**核心能力清单：**

1. **用户认证与权限管理**：JWT Token 登录/登出、用户管理、bcrypt 密码哈希
2. **模块统一管控**：8 大模块注册与状态监控、健康检查汇总、模块代理转发
3. **部署中心**：模块启停控制、版本管理与升级
4. **监控中心**：系统级告警管理（四级）、告警确认与解决、全局系统状态检测
5. **业务模式聚合层**：成长中心、工作开发、复盘总结、学业规划、生活管理、情绪陪伴、人际关系、形象工坊
6. **汐舷（任务执行面板）**：任务提交与追踪、执行步骤可视化、调用日志
7. **前端静态文件服务**：挂载 6 大前端目录，根路径返回首页

#### 目录结构（树形）

```
M8-control-tower/
├── backend/                        # 后端服务
│   ├── main.py                     # FastAPI 应用入口
│   ├── config.py                   # 配置管理（pydantic-settings）
│   ├── auth.py                     # JWT 认证 + bcrypt 密码
│   ├── models.py                   # SQLAlchemy 数据模型（34 张表）
│   ├── run.py                      # 运行脚本
│   ├── requirements.txt            # 依赖清单
│   ├── alembic.ini                 # Alembic 配置
│   ├── alembic/                    # 数据库迁移
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 001_initial_baseline.py
│   ├── routers/                    # API 路由（20 个路由文件）
│   │   ├── auth.py                 # 认证
│   │   ├── users.py                # 用户管理
│   │   ├── modules.py              # 模块管理（代理转发核心）
│   │   ├── monitor.py              # 监控告警
│   │   ├── deploy.py               # 部署中心
│   │   ├── task.py                 # 任务管理
│   │   ├── system.py               # 系统管理
│   │   ├── agents.py               # Agent 管理（M1 代理）
│   │   ├── chat.py                 # 云汐聊天
│   │   ├── memory.py               # 潮汐记忆（M5 代理）
│   │   ├── workflow.py             # 积木平台（M7 代理）
│   │   ├── growth.py               # 成长中心
│   │   ├── work_dev.py             # 工作开发
│   │   ├── review.py               # 复盘总结
│   │   ├── study_plan.py           # 学业规划
│   │   ├── life_management.py      # 生活管理
│   │   ├── emotion_comfort.py      # 情绪陪伴
│   │   ├── social_relation.py      # 人际关系
│   │   ├── appearance.py           # 形象工坊
│   │   └── m6_devices.py           # M6 设备代理
│   ├── schemas/                    # Pydantic Schema
│   │   └── __init__.py
│   └── data/                       # 数据库文件
│       └── m8.db                   # SQLite 主数据库
└── data/                           # 根级数据目录
    ├── m8.db
    └── m8.db.bak
```

#### API 接口清单（表格）

M8 共约 **290+** 个 API 端点，分布在 20 个路由文件中。

| 方法 | 路径 | 功能 | 鉴权 | 说明 |
|------|------|------|------|------|
| GET | `/` | 服务信息/首页 | 否 | 返回前端页面或 API 信息 |
| GET | `/health` | 健康检查 | 否 | 标准格式 |
| GET | `/api/modules/status` | 所有模块状态 | 否 | 公开接口 |
| GET | `/api/system/check` | 全局系统检测 | 否 | Ollama/Git/蓝牙/模块 |
| POST | `/api/auth/login` | 用户登录 | 否 | 返回 JWT Token |
| POST | `/api/auth/logout` | 用户登出 | 是 | |
| GET | `/api/auth/me` | 当前用户信息 | 是 | |
| GET | `/api/modules/` | 模块列表 | 是 | |
| GET | `/api/modules/{key}` | 模块详情 | 是 | |
| GET | `/api/modules/{key}/health` | 模块健康检查 | 是 | 代理转发 |
| GET | `/api/modules/{key}/metrics` | 模块指标 | 是 | 代理转发 |
| GET | `/api/monitor/alerts` | 告警列表 | 是 | 分页、级别过滤 |
| POST | `/api/monitor/alerts/{id}/ack` | 确认告警 | 是 | |
| POST | `/api/monitor/alerts/{id}/resolve` | 解决告警 | 是 | |
| GET | `/api/deploy/status` | 部署状态 | 是 | |
| POST | `/api/deploy/upgrade` | 模块升级 | 是 | |
| GET | `/api/tasks` | 任务列表 | 是 | |
| POST | `/api/tasks` | 提交任务 | 是 | |
| GET | `/api/tasks/{id}` | 任务详情 | 是 | |
| GET | `/api/agents/` | Agent 列表 | 是 | 代理到 M1 |
| POST | `/api/chat` | 聊天对话 | 是 | 代理到 M1 |
| POST | `/api/chat/stream` | 流式对话 | 是 | SSE |
| GET | `/api/memory/recall` | 记忆检索 | 是 | 代理到 M5 |
| POST | `/api/memory/archive` | 记忆归档 | 是 | 代理到 M5 |
| GET | `/api/workflows` | 工作流列表 | 是 | 代理到 M7 |
| GET | `/api/growth/achievements` | 成就列表 | 是 | |
| GET | `/api/growth/talents` | 天赋树 | 是 | |
| GET | `/api/growth/season` | 赛季信息 | 是 | |
| GET | `/api/growth/calendar` | 潮汐日历 | 是 | |
| GET | `/api/work-dev/projects` | 项目列表 | 是 | |
| GET | `/api/work-dev/tasks` | 任务看板 | 是 | |
| GET | `/api/work-dev/commits` | 提交记录 | 是 | |
| GET | `/api/review/reviews` | 复盘列表 | 是 | |
| GET | `/api/review/diaries` | 日记列表 | 是 | |
| GET | `/api/review/decisions` | 决策记录 | 是 | |
| GET | `/api/study-plan/goals` | 学习目标 | 是 | 树形结构 |
| GET | `/api/study-plan/plans` | 学习计划 | 是 | |
| GET | `/api/study-plan/notes` | 学习笔记 | 是 | |
| GET | `/api/life-management/schedules` | 日程列表 | 是 | |
| GET | `/api/life-management/todos` | 待办事项 | 是 | |
| GET | `/api/life-management/habits` | 习惯打卡 | 是 | |
| GET | `/api/emotion-comfort/` | 情绪陪伴 | 是 | |
| GET | `/api/social-relation/` | 人际关系 | 是 | |
| GET | `/api/appearance/` | 形象工坊 | 是 | |
| GET | `/api/v1/m6/devices` | 设备列表 | 是 | M6 代理 |
| GET | `/api/v1/m6/sensors` | 传感器数据 | 是 | M6 代理 |

> 注：以上为主要端点列表，完整 290+ 端点包括各业务模块的 CRUD 操作。

#### 依赖项

**上游依赖（被谁调用）：**
- 前端所有页面（/m8、/xian、/modes、/m7、/startup）
- 系统启动器（启动云汐.py）

**下游依赖（调用谁）：**
- M1 多Agent调度中心（聊天、任务、Agent 管理）
- M2 技能集群（技能列表、调用）
- M3 端云协同内核（同步状态、设备管理）
- M4 场景引擎（场景切换、上下文）
- M5 潮汐记忆系统（记忆读写、检索）
- M6 硬件外设（设备数据、传感器）
- M7 积木平台（工作流管理）
- shared 公共模块（config、logger、module_client）
- Ollama / 云端大模型（通过 M1 间接调用）

#### 故障隔离规则

- **不可用时的降级策略**：M8 是系统唯一入口，M8 故障 = 系统不可用。数据库为本地 SQLite，重启即可恢复。
- **对系统整体的影响级别**：P0（致命）——M8 宕机后所有用户无法访问系统。
- **数据安全**：使用 Alembic 迁移，支持版本回滚；数据库文件可备份。
- **启动保障**：各模块独立启动，M8 不影响其他模块运行，但用户无法通过 M8 访问。

#### 开发完成度

- **完成度**：90%
- **已落地功能列表**：
  - 用户认证与 JWT 鉴权
  - 20 个业务路由模块（9 大模式 + 系统管理 + 模块代理）
  - 34 张数据库表，Alembic 迁移管理
  - 模块代理转发（M1/M2/M5/M6/M7 等）
  - 健康检查与监控告警
  - 前端静态文件服务（6 大前端目录）
  - 全局系统状态检测
  - 成长中心完整 7 大子系统
  - 工作开发、复盘总结、学业规划、生活管理 4 大模式完整 CRUD
  - 情绪陪伴、人际关系、形象工坊 3 大模式基础框架
- **未开发/待完善功能列表**：
  - 多用户支持（当前单用户设计）
  - 细粒度权限控制（角色权限矩阵）
  - 操作审计日志
  - 部署中心的实际模块启停能力（当前仅状态展示）
  - 情绪陪伴、人际关系、形象工坊的深度 AI 功能
  - 通知推送（邮件/短信/桌面通知）
  - 数据导出与备份管理界面
- **后续迭代规划**：
  - v1.1：多用户与权限体系完善
  - v1.2：部署中心自动化（一键启停、版本升级）
  - v1.3：三大模式（情绪/社交/形象）深度功能
  - v2.0：插件化架构，支持第三方模块接入

---

### M1 - 多Agent调度中心（Agent Cluster）

#### 基本信息

| 项目 | 内容 |
|------|------|
| 模块代号 | M1 |
| 中文名称 | 多Agent调度中心 |
| 英文名称 | Agent Cluster / Federation Scheduler |
| 版本号 | 11.1.0 |
| 监听端口 | 8001 |
| 技术栈 | Python + FastAPI + structlog + YAML 配置 |
| 启动方式 | `python server.py` |
| 入口文件 | `M1-agent-cluster/server.py` |

#### 定位与职责

M1 是云汐系统的智能调度核心，负责接收用户任务、进行意图识别、调度多个 Agent 协同完成任务。V11.0 引入联邦调度系统，支持本地 Agent 与外部云端 Agent 的统一调度与成本管控。

**核心能力清单：**

1. **联邦调度系统（V11.0 核心）**
   - 外部 Agent 注册表（OpenAI/Anthropic/Gemini/DeepSeek 等）
   - 智能调度决策（本地 vs 云端，成本/速度/质量权衡）
   - 多 Agent 并行对比（A/B 测试）
   - 成本管控（月度预算、费用明细、日统计）
   - 隐私防护（内容脱敏、安全分级、审计日志）

2. **八子 Agent 架构（V10.0）**
   - Orchestrator（编排 Agent）：任务分解与流程控制
   - Arbiter（仲裁 Agent）：结果评判与质量把关
   - Discovery（发现 Agent）：能力发现与路由
   - Lifecycle（生命周期 Agent）：实例管理与池化
   - Security（安全 Agent）：内容安全与审计
   - Snapshot（快照 Agent）：状态保存与恢复
   - Budget（预算 Agent）：Token 与成本控制
   - Bus（总线 Agent）：消息分发与事件

3. **分身池（Clone Pool）**：临时分身申请与释放、TTL 自动回收、池化资源管理
4. **意图识别与路由**：多版本意图分类器、自适应路由器、语义路由
5. **工作流引擎**：DAG 任务编排、多版本编排器（v2~v9）、流式输出
6. **消息总线**：发布/订阅模式、Agent 间通信、A2A 协议支持
7. **健康监控与指标**：Prometheus 指标、全量诊断、健康状态检测

#### 目录结构（树形）

```
M1-agent-cluster/
├── server.py                       # 启动入口
├── requirements.txt                # 依赖清单
├── config.yaml                     # 配置文件
├── app_bootstrap.py                # 应用启动引导
├── api/                            # HTTP API 层
│   ├── server.py                   # FastAPI 服务器（31个端点）
│   └── m8_interface.py             # M8 标准对接接口
├── federation/                     # 联邦调度系统（V11.0）
│   ├── registry.py                 # 外部 Agent 注册表
│   ├── scheduler.py                # 联邦调度决策器
│   ├── comparator.py               # 多 Agent 对比器
│   ├── cost_controller.py          # 成本控制器
│   ├── privacy_guard.py            # 隐私防护层
│   ├── crypto_utils.py             # 加密工具
│   ├── key_manager.py              # 密钥管理
│   └── adapters/                   # Agent 适配器（16个）
│       ├── base.py / openai.py / anthropic.py
│       ├── gemini.py / local_model.py
│       ├── hermes_agent.py / codex_agent.py
│       ├── explore_agent.py / tide_agent.py
│       ├── voice_agent.py / scene_manager_agent.py
│       ├── skill_manager_agent.py / security_manager_agent.py
│       └── ...
├── orchestrator/ arbiter/ discovery/  # 八子 Agent
├── lifecycle/ security/ snapshot/
├── budget/ bus/ voice/
├── pool/                           # 分身池
├── agents/                         # 专用 Agent（dev/emotion/note/review）
├── master_scheduler.py             # 主调度器
├── orchestrator_v9.py              # 编排器 v9（当前主版本）
├── intent_classifier_v2.py         # 意图分类器 v2
├── semantic_intent_v3.py           # 语义意图 v3
├── workflow_engine.py              # 工作流引擎
├── message_bus.py                  # 消息总线
├── memory_bridge.py                # 记忆桥接
├── llm_provider.py                 # LLM 提供器
├── health_monitor.py               # 健康监控
├── circuit_breaker.py              # 熔断器
├── shared_models.py                # 共享模型
├── tests/                          # 测试（70+ 测试文件）
├── docs/                           # 文档
└── config/                         # 配置
    └── yunxi_personality.yaml      # 云汐人格配置
```

#### API 接口清单（表格）

M1 共约 **31+** 个 API 端点。

| 方法 | 路径 | 功能 | 鉴权 | 说明 |
|------|------|------|------|------|
| GET | `/health` | 健康检查 | 否 | 标准格式 |
| GET | `/ready` | 就绪检查 | 否 | |
| GET | `/metrics` | Prometheus 指标 | 否 | text/plain 格式 |
| GET | `/diagnose` | 全量诊断 | 否 | |
| GET | `/agents` | Agent 列表 | 否 | |
| GET | `/.well-known/agent-card.json` | A2A 发现 | 否 | Agent Discovery |
| POST | `/api/v1/tasks/submit` | 提交任务 | 否 | M1 唯一任务入口 |
| DELETE | `/api/v1/agents/{id}` | 注销 Agent | 否 | |
| GET | `/api/v1/agents/{id}/status` | Agent 状态 | 否 | |
| GET | `/api/v1/tasks/{id}/status` | 任务状态 | 否 | |
| POST | `/api/v1/bus/publish` | 消息总线发布 | 否 | |
| POST | `/api/v1/chat` | 同步对话 | 否 | 兼容旧版 |
| POST | `/api/v1/chat/stream` | 流式对话 | 否 | SSE |
| POST | `/v1/pool/request` | 申请分身 | 否 | Clone Pool |
| POST | `/v1/pool/release` | 释放分身 | 否 | |
| GET | `/v1/pool/status` | 分身池状态 | 否 | |
| GET | `/v1/federation/agents` | 外部 Agent 列表 | read | 联邦调度 |
| POST | `/v1/federation/agents/register` | 注册外部 Agent | admin | |
| GET | `/v1/federation/agents/{id}` | Agent 详情 | read | |
| DELETE | `/v1/federation/agents/{id}` | 注销外部 Agent | admin | |
| POST | `/v1/federation/agents/{id}/health-check` | 健康检查 | read | |
| POST | `/v1/federation/decide` | 调度决策 | read | |
| POST | `/v1/federation/invoke` | 调用外部 Agent | write | |
| POST | `/v1/federation/compare` | 多 Agent 对比 | write | |
| POST | `/v1/federation/privacy/scan` | 隐私扫描 | read | |
| GET | `/v1/federation/privacy/audit` | 隐私审计 | admin | |
| GET | `/v1/federation/cost/budget` | 预算状态 | read | |
| POST | `/v1/federation/cost/budget` | 设置预算 | admin | |
| GET | `/v1/federation/cost/records` | 费用明细 | read | |
| GET | `/v1/federation/cost/daily` | 日费用统计 | read | |

#### 依赖项

**上游依赖（被谁调用）：**
- M8 管理工作台（聊天、任务、Agent 管理）
- M7 积木平台（工作流执行节点调用）
- M4 场景引擎（场景切换调整 Agent）

**下游依赖（调用谁）：**
- M2 技能集群（技能调用与执行）
- M5 潮汐记忆系统（记忆读写）
- Ollama（本地大模型）
- 云端大模型 API（DeepSeek/OpenAI/Anthropic 等，联邦调度）
- MCP 服务（工具调用）

#### 故障隔离规则

- **不可用时的降级策略**：M1 故障时，所有 AI 对话和任务调度功能失效。M8 的系统管理、数据查询等非 AI 功能仍可使用。
- **对系统整体的影响级别**：P1（严重）——核心 AI 能力丧失，但系统管理和数据浏览仍可用。
- **降级模式**：可降级为直接调用 M2 技能（跳过 Agent 编排），或使用简单的 LLM 直连模式。
- **恢复方式**：重启 M1 进程，配置和 Agent 注册信息可从配置文件重新加载。

#### 开发完成度

- **完成度**：95%
- **已落地功能列表**：
  - V11.0 联邦调度系统（注册表、调度器、对比器、成本管控、隐私防护）
  - 八子 Agent 架构完整实现
  - 16 个外部 Agent 适配器
  - 分身池（Clone Pool）
  - 多版本意图分类器（v1/v2/v3）
  - 9 个版本的编排器迭代
  - 工作流引擎 + DAG 编排
  - 消息总线 + A2A 协议
  - 流式输出引擎
  - 健康监控 + Prometheus 指标
  - 熔断器 + 重试协调器
  - 记忆桥接 + 向量记忆
  - 70+ 单元测试文件
  - V11.1 M8 标准接口集成
- **未开发/待完善功能列表**：
  - 联邦调度的自动故障转移
  - Agent 能力动态发现与热更新
  - 多租户隔离
  - 分布式部署（当前单进程）
  - 任务持久化与断点续做的完整度
- **后续迭代规划**：
  - V12.0：分布式 Agent 集群
  - V12.1：自动故障转移与自愈
  - V13.0：多租户与资源隔离

---

### M2 - 技能集群（Skills Cluster）

#### 基本信息

| 项目 | 内容 |
|------|------|
| 模块代号 | M2 |
| 中文名称 | 技能集群 |
| 英文名称 | Skills Cluster |
| 版本号 | 3.10.2 |
| 监听端口 | 8002 |
| 技术栈 | Python + FastAPI + structlog |
| 启动方式 | `python start_server.py` |
| 入口文件 | `M2-skills-cluster/start_server.py` |

#### 定位与职责

M2 是云汐系统的技能能力中心，提供可插拔的工具技能集合，支持智能发现、路由选择、缓存优化、沙箱执行等能力。采用插件化架构，技能以 ISkill 接口为标准，可动态加载与注册。

**核心能力清单：**

1. **技能注册表**：统一管理所有技能的注册、发现、查询
2. **智能技能路由**：基于语义的技能发现、BM25 检索、多轮路由优化
3. **技能执行引擎**：技能调用流水线、沙箱执行、权限控制
4. **技能缓存**：结果缓存、命中率统计、缓存失效策略
5. **技能发现引擎**：分类浏览、关键词搜索、推荐系统
6. **技能经验系统**：技能使用经验积累、技能图谱关联
7. **沙箱执行**：代码技能的隔离执行、资源限制
8. **MCP 桥接**：Model Context Protocol 工具接入
9. **健康检查**：技能健康状态监控、自动检测

**内置技能清单（10+）：**
- 日历（calendar）、翻译（translate）、网页抓取（web_fetch）
- 文档处理（doc_proc）、数据分析（data_analysis）
- 通知（notify）、潮汐记忆（tide_memory）、全文搜索（fulltext_search）
- 代码技能（code_skills）、代码搜索（code_search）
- 待办（todo）、习惯（habit）、目标（goal）、日记（journal）
- 心情（mood）、闪卡（flashcard）、联系人（contact）、财务（finance）

#### 目录结构（树形）

```
M2-skills-cluster/
├── start_server.py                 # 启动入口
├── requirements.txt                # 依赖清单
├── config.example.yaml             # 配置示例
├── resource.py                     # resource 模块 mock（Windows兼容）
└── skill_cluster/                  # 核心包
    ├── __init__.py
    ├── version.py                  # 版本号 3.10.2
    ├── api_v2.py                   # API v2 主入口（13个端点）
    ├── http_api.py                 # HTTP API 旧版
    ├── skill_registry.py           # 技能注册表
    ├── skill_router.py             # 技能路由器
    ├── skill_discovery.py          # 技能发现引擎
    ├── skill_selection.py          # 技能选择器
    ├── skill_bandit_router.py      # Bandit 算法路由
    ├── adaptive_router.py          # 自适应路由器
    ├── skill_graph.py              # 技能图谱
    ├── skill_pipeline.py           # 技能流水线
    ├── skill_cache.py              # 技能缓存
    ├── skill_experience.py         # 技能经验系统
    ├── skill_handbook.py           # 技能手册
    ├── skill_health.py             # 技能健康检查
    ├── skill_recommender.py        # 技能推荐器
    ├── health_checker.py           # 健康检查器
    ├── sandbox.py                  # 沙箱执行器
    ├── code_execution_bridge.py    # 代码执行桥接
    ├── config.py / config_center.py # 配置管理
    ├── m8_auth_middleware.py       # M8 鉴权中间件
    ├── permissions.py              # 权限系统
    ├── mcp_bridge.py / mcp_transport.py  # MCP 桥接
    ├── memory_skill_bridge.py      # 记忆技能桥接
    ├── edge_cloud_orchestrator.py  # 端云编排
    ├── a2a_bus.py / a2a_protocol.py # A2A 协议
    ├── event_bus.py                # 事件总线
    ├── metrics.py                  # 指标收集
    ├── middleware.py               # 中间件
    ├── streaming.py                # 流式输出
    ├── voice_polish.py             # 语音润色
    ├── upgrade_endpoints.py        # 升级接口
    ├── test_endpoints.py           # 测试接口
    ├── tools/                      # 工具懒加载
    ├── skills/                     # 内置技能（22个）
    │   ├── calendar.py / translate.py / web_fetch.py
    │   ├── doc_proc.py / data_analysis.py
    │   ├── notify.py / tide_memory.py / fulltext_search.py
    │   ├── code_skills.py / code_search.py
    │   ├── todo.py / habit.py / goal.py / journal.py
    │   ├── mood.py / flashcard.py / contact.py / finance.py
    │   └── _code_base.py
    └── tests/                      # 测试（40+）
```

#### API 接口清单（表格）

M2 共约 **25+** 个 API 端点（核心 v2 API 共 13 个）。

| 方法 | 路径 | 功能 | 鉴权 | 说明 |
|------|------|------|------|------|
| GET | `/health` | 根路径健康检查 | 否 | 标准格式 |
| GET | `/api/v2/health` | API v2 健康检查 | 否 | |
| GET | `/api/v2/skills` | 技能列表 | 否 | 分页、分类筛选 |
| GET | `/api/v2/skills/{id}` | 技能详情 | 否 | |
| GET | `/api/v2/skills/{id}/manifest` | 技能清单 | 否 | |
| POST | `/api/v2/skills/{id}/invoke` | 调用技能 | 是 | |
| GET | `/api/v2/categories` | 技能分类 | 否 | |
| GET | `/api/v2/search` | 技能搜索 | 否 | 关键词搜索 |
| POST | `/api/v2/discover` | 智能发现 | 是 | 基于意图的技能发现 |
| GET | `/api/v2/stats` | 技能统计 | 是 | |
| POST | `/api/v2/cache/clear` | 清除缓存 | 是 | |
| GET | `/api/v2/health/status` | 健康状态详情 | 是 | |
| POST | `/m8/config` | M8 配置接口 | 是 | M8 标准接口 |
| POST | `/m8/upgrade` | M8 升级接口 | 是 | M8 标准接口 |

#### 依赖项

**上游依赖（被谁调用）：**
- M1 多Agent调度中心（技能执行）
- M7 积木平台（工作流技能节点）
- M8 管理工作台（技能管理代理）

**下游依赖（调用谁）：**
- M5 潮汐记忆系统（记忆类技能）
- 外部 API（天气、翻译、网页抓取等）
- 本地代码执行环境（沙箱）
- MCP 服务（工具接入）

#### 故障隔离规则

- **不可用时的降级策略**：M2 故障时，所有工具技能调用失败。Agent 可降级为纯对话模式，不调用工具。
- **对系统整体的影响级别**：P2（中等）——AI 对话仍可用，但工具使用能力丧失。
- **降级模式**：纯对话模式，跳过技能调用步骤。
- **恢复方式**：重启 M2 进程，技能自动重新注册。

#### 开发完成度

- **完成度**：85%
- **已落地功能列表**：
  - 10+ 内置技能（核心类）
  - 技能注册表 + 智能发现引擎
  - 多种路由策略（语义/Bandit/自适应）
  - 技能缓存与经验系统
  - 沙箱执行环境
  - MCP 桥接
  - A2A 协议与事件总线
  - 40+ 测试文件
  - M8 标准接口集成
- **未开发/待完善功能列表**：
  - 更多内置技能（当前仅核心 10+ 个完整实现）
  - 技能市场与第三方技能安装
  - 技能版本管理与回滚
  - 可视化技能编排
  - 技能使用数据分析与优化建议
- **后续迭代规划**：
  - v3.11：技能市场框架
  - v3.12：更多内置技能扩充到 50+
  - v4.0：可视化技能编排器

---

### M3 - 端云协同内核（Edge-Cloud Kernel）

#### 基本信息

| 项目 | 内容 |
|------|------|
| 模块代号 | M3 |
| 中文名称 | 端云协同内核 |
| 英文名称 | Edge-Cloud Collaborative Kernel |
| 版本号 | 2.1.2 |
| 监听端口 | 8003 |
| 技术栈 | Python + FastAPI + structlog + YAML 配置 |
| 启动方式 | `python server.py` |
| 入口文件 | `M3-edge-cloud/server.py` |

#### 定位与职责

M3 是云汐系统的端云协同调度内核，负责端侧与云侧的数据同步、离线缓存、冲突消解、通信网关、资源监控与硬件桥接等能力。确保在网络不稳定或断网场景下系统仍可正常运行。

**核心能力清单：**

1. **端云同步引擎**
   - 双向数据同步（对话、记忆、配置等）
   - 增量同步与全量同步
   - 同步状态监控与进度展示

2. **离线影子代理（Offline Shadow Proxy）**
   - 离线请求队列持久化
   - 网络恢复后自动回放
   - 队列大小限制与淘汰策略

3. **冲突解决器**
   - 多版本冲突检测
   - 多种冲突策略（最新优先/手动合并/云端优先）
   - 冲突列表与手动解决

4. **通信网关**
   - 云端 API 统一网关
   - 熔断器（Circuit Breaker）
   - 限流（Rate Limiter）
   - 健康检查器

5. **资源监控**
   - VRAM 监控（GPU 显存）
   - 缓存管理器
   - 硬件资源感知

6. **设备注册表**
   - 端侧设备注册与管理
   - 设备状态监控
   - 设备能力发现

7. **上下文同步控制器**
   - 对话上下文同步
   - 记忆覆盖度适配
   - 潮汐记忆桥接

#### 目录结构（树形）

```
M3-edge-cloud/
├── server.py                       # 启动入口（12个端点）
├── requirements.txt                # 依赖清单
├── verify_p1_fixes.py              # 验证脚本
└── edge_cloud_kernel/              # 核心包
    ├── __init__.py
    ├── config/                     # 配置
    │   ├── config.yaml / config.example.yaml
    │   ├── hardware_bridge.yaml
    │   ├── vram_policy.yaml
    │   └── sync_api_openapi.yaml
    ├── execution/                  # 执行引擎
    │   ├── local_executor.py
    │   ├── cloud_executor.py
    │   └── route_engine.py
    ├── gateway/                    # 通信网关
    │   ├── cloud_gateway.py
    │   ├── circuit_breaker.py
    │   ├── health_checker.py
    │   └── rate_limiter.py
    ├── local_data/                 # 本地数据管理
    │   ├── local_data_manager.py
    │   ├── conflict_resolver.py
    │   └── sync_client.py
    ├── sync/                       # 同步引擎
    │   ├── sync_api.py
    │   ├── context_sync_controller.py
    │   ├── offline_shadow_proxy.py
    │   ├── call_log_writer.py
    │   ├── tide_memory_bridge.py
    │   └── memory_coverage_adapter.py
    ├── m8_api/                     # M8 标准接口
    │   ├── m8_api_service.py
    │   ├── m8_auth_middleware.py
    │   ├── health_endpoints.py
    │   ├── config_endpoints.py
    │   ├── device_registry.py
    │   ├── upgrade_endpoints.py
    │   ├── test_endpoints.py
    │   └── error_codes.py
    ├── models/                     # 数据模型
    │   ├── call_log.py
    │   ├── sync_models.py
    │   ├── vram_report.py
    │   └── exceptions.py
    ├── resource/                   # 资源管理
    │   ├── cache_manager.py
    │   └── vram_monitor.py
    └── tests/                      # 测试（20+）
```

#### API 接口清单（表格）

M3 共约 **12+** 个 API 端点。

| 方法 | 路径 | 功能 | 鉴权 | 说明 |
|------|------|------|------|------|
| GET | `/` | 服务信息 | 否 | |
| GET | `/health` | 健康检查 | 否 | 标准格式 |
| GET | `/api/v3/health` | M8 标准健康检查 | 否 | |
| GET | `/api/v3/metrics` | 性能指标 | 是 | |
| GET | `/api/v3/config` | 获取配置 | 是 | 敏感字段脱敏 |
| POST | `/api/v3/config/update` | 更新配置 | 是 | 热更新 |
| GET | `/api/v3/sync/status` | 同步状态 | 是 | |
| POST | `/api/v3/sync/trigger` | 触发同步 | 是 | |
| GET | `/api/v3/sync/conflicts` | 冲突列表 | 是 | 分页 |
| POST | `/api/v3/sync/conflicts/{id}/resolve` | 解决冲突 | 是 | |
| GET | `/api/v3/devices` | 设备列表 | 是 | 分页、状态过滤 |
| POST | `/api/v3/devices/{id}/remove` | 移除设备 | 是 | |

#### 依赖项

**上游依赖（被谁调用）：**
- M8 管理工作台（同步状态、设备管理代理）
- M5 潮汐记忆系统（记忆同步桥接）

**下游依赖（调用谁）：**
- M5 潮汐记忆系统（记忆数据同步）
- 云端服务 API（云侧同步）
- 本地设备（硬件桥接）

#### 故障隔离规则

- **不可用时的降级策略**：M3 故障时，端云同步功能失效，系统运行在纯本地模式。不影响本地 AI 对话和数据存储。
- **对系统整体的影响级别**：P3（轻微）——纯本地模式可正常使用，仅同步功能丧失。
- **降级模式**：纯本地运行模式，数据仅存储在本地。
- **恢复方式**：重启 M3 进程，自动检测待同步队列并恢复同步。

#### 开发完成度

- **完成度**：75%
- **已落地功能列表**：
  - 健康检查与指标系统
  - 配置管理（热更新 + 脱敏）
  - 冲突解决器框架
  - 离线影子代理
  - 设备注册表
  - 通信网关（熔断器 + 限流）
  - 上下文同步控制器
  - 潮汐记忆桥接
  - M8 标准接口集成
  - 20+ 测试文件
- **未开发/待完善功能列表**：
  - 完整的端云双向同步实现（当前偏框架层）
  - 真实云端对接（当前模拟/Local 模式）
  - 多设备协同与状态同步
  - 端侧 AI 推理卸载
  - 断点续传与大文件同步
- **后续迭代规划**：
  - v2.2：完整端云双向同步
  - v2.3：多设备协同
  - v3.0：端侧 AI 推理与卸载

---

### M4 - 场景引擎（Scene Engine）

#### 基本信息

| 项目 | 内容 |
|------|------|
| 模块代号 | M4 |
| 中文名称 | 场景引擎 |
| 英文名称 | Scene Engine |
| 版本号 | 1.0.0 |
| 监听端口 | 8004 |
| 技术栈 | Python + FastAPI |
| 启动方式 | `python server.py` |
| 入口文件 | `M4-scene-engine/server.py` |

#### 定位与职责

M4 是云汐系统的场景调度引擎，负责根据用户行为和上下文自动识别当前场景、管理场景切换、维护各场景的独立上下文，实现「暖切换」过渡效果，确保场景变化时用户体验流畅自然。

**核心能力清单：**

1. **六大场景定义**
   - 工作开发（work_dev）：编程、项目管理、技术学习
   - 学业规划（study_plan）：学习计划、知识整理、考试准备
   - 复盘总结（review_summary）：每日复盘、周月总结、目标回顾
   - 人际关系（interpersonal）：社交建议、情感分析、沟通技巧
   - 情感陪伴（emotional）：聊天陪伴、情绪疏导、心理支持
   - 生活管理（life_manage）：日程、待办、习惯、财务

2. **场景识别器**
   - 关键词匹配（中英文关键词库）
   - 置信度计算与阈值判断
   - 可选 LLM 增强识别

3. **场景切换管理器**
   - 当前场景状态维护
   - 切换历史记录（最多 100 条）
   - 切换动画与过渡效果支持
   - 默认场景配置

4. **上下文存储**
   - 各场景独立上下文
   - JSON 文件持久化
   - 自动保存与加载

5. **M8 标准接口**
   - 健康检查 + 指标
   - 配置管理 + 升级接口
   - M8 Token 鉴权

#### 目录结构（树形）

```
M4-scene-engine/
├── server.py                       # 启动入口
├── requirements.txt                # 依赖清单
├── data/                           # 数据目录
└── src/                            # 源码
    ├── main.py                     # FastAPI 主应用
    ├── models.py                   # 数据模型与场景定义
    ├── routers/                    # API 路由
    │   ├── scene.py                # 场景管理（5个端点）
    │   ├── context.py              # 上下文管理（4个端点）
    │   ├── config_route.py         # 配置路由（2个端点）
    │   └── admin.py                # 管理接口（4个端点）
    ├── services/                   # 业务服务
    │   ├── recognizer.py           # 场景识别器
    │   ├── switcher.py             # 场景切换管理器
    │   └── context_store.py        # 上下文存储
    └── m8_api/                     # M8 标准接口
        ├── health_endpoints.py     # 健康与指标
        └── m8_auth_middleware.py   # M8 鉴权中间件
```

#### API 接口清单（表格）

M4 共约 **15+** 个 API 端点。

| 方法 | 路径 | 功能 | 鉴权 | 说明 |
|------|------|------|------|------|
| GET | `/` | 服务信息 | 否 | |
| GET | `/health` | 健康检查 | 否 | 标准格式 |
| GET | `/api/v1/scenes` | 场景列表 | 否 | 所有场景定义 |
| GET | `/api/v1/scene/current` | 当前场景 | 否 | |
| POST | `/api/v1/scene/switch` | 切换场景 | 是 | |
| POST | `/api/v1/scene/recognize` | 识别场景 | 否 | 基于输入文本 |
| GET | `/api/v1/scene/history` | 切换历史 | 是 | |
| GET | `/api/v1/scene/{id}/config` | 场景配置 | 是 | |
| GET | `/api/v1/context/{scene_id}` | 获取上下文 | 是 | |
| PUT | `/api/v1/context/{scene_id}` | 更新上下文 | 是 | |
| GET | `/api/v1/context/status` | 上下文状态 | 是 | |
| GET | `/api/v1/admin/health` | 管理健康检查 | 是 | M8 标准 |
| GET | `/api/v1/admin/metrics` | 管理指标 | 是 | M8 标准 |
| GET | `/api/v1/admin/config` | 获取配置 | 是 | |
| POST | `/api/v1/admin/config` | 更新配置 | 是 | |

#### 依赖项

**上游依赖（被谁调用）：**
- M8 管理工作台（场景状态、切换代理）
- M1 调度中心（场景感知的调度调整）

**下游依赖（调用谁）：**
- M5 潮汐记忆系统（场景上下文记忆）
- 大模型 API（LLM 增强识别，可选）

#### 故障隔离规则

- **不可用时的降级策略**：M4 故障时，场景切换功能失效，系统固定在默认场景（情感陪伴）。AI 对话和其他功能不受影响。
- **对系统整体的影响级别**：P3（轻微）——场景自动切换不可用，手动切换可通过 M8 前端模拟。
- **降级模式**：单场景模式，使用默认场景配置。
- **恢复方式**：重启 M4 进程，从持久化文件恢复上下文。

#### 开发完成度

- **完成度**：70%
- **已落地功能列表**：
  - 六大场景定义与关键词库
  - 场景识别器（关键词匹配）
  - 场景切换管理与历史记录
  - 上下文存储与持久化
  - M8 标准接口集成
  - M8 Token 鉴权中间件
- **未开发/待完善功能列表**：
  - LLM 增强场景识别（当前仅关键词）
  - 场景暖切换过渡动画
  - 场景上下文的智能迁移与摘要
  - 自定义场景创建
  - 场景触发规则配置（时间/位置/事件）
  - 场景与 M1 Agent 的深度联动
- **后续迭代规划**：
  - v1.1：LLM 增强识别 + 暖切换过渡
  - v1.2：自定义场景 + 触发规则
  - v2.0：上下文智能迁移 + 多场景并行

---

### M5 - 潮汐记忆系统（Tide Memory）

#### 基本信息

| 项目 | 内容 |
|------|------|
| 模块代号 | M5 |
| 中文名称 | 潮汐记忆系统 |
| 英文名称 | Tide Memory System |
| 版本号 | 2.4.0-REV2 |
| 监听端口 | 8005 |
| 技术栈 | Python + FastAPI + SQLite + 向量索引 + AES-256 加密 |
| 启动方式 | `python server.py` |
| 入口文件 | `M5-tide-memory/server.py` |

#### 定位与职责

M5 是云汐系统的核心记忆存储与检索系统，采用「潮汐」隐喻的四层记忆架构，模拟人类记忆从短期到长期的巩固过程。支持向量语义检索、关键词检索、情绪关联记忆、三级域权限、四级密级标记等高级特性。

**核心能力清单：**

1. **四层潮汐记忆架构**
   - L0 滩涂（Beach）：超短期记忆，最近对话，自动流失
   - L1 浅层（Shallow）：短期记忆，近期重要内容
   - L2 深层（Deep）：长期记忆，经过巩固的重要知识
   - L3 深渊（Abyss）：永久记忆，核心价值观与关键事件

2. **记忆检索引擎**
   - 向量语义检索（嵌入向量相似度）
   - 关键词检索（BM25/TF-IDF）
   - 混合检索（语义 + 关键词加权）
   - 情绪上下文关联检索

3. **记忆巩固（Consolidation）**
   - 定期巩固：从浅层向深层迁移
   - 重要性评分与筛选
   - 遗忘曲线模拟

4. **安全与权限**
   - 三级域权限（private/shared/public）
   - 四级密级标记（公开/内部/机密/绝密）
   - AES-256-GCM 本地加密存储
   - 数据脱敏与审计日志

5. **情绪记忆**
   - 效价-唤醒度模型（Valence-Arousal）
   - 情绪记忆关联检索
   - EI 情绪智能模型

#### 目录结构（树形）

```
M5-tide-memory/
├── server.py                       # 启动入口（11个端点）
├── requirements.txt                # 依赖清单
├── version.txt                     # 版本号 2.4.0-REV2
├── CHANGELOG.md                    # 变更日志
├── .env.example                    # 环境变量示例
├── data/                           # 数据目录
├── config/                         # 配置
│   └── .env.example
├── scripts/                        # 脚本
│   ├── init_db.py                  # 数据库初始化
│   └── migrate.py                  # 迁移脚本
├── src/                            # 源码
│   ├── main.py                     # 应用创建
│   └── tide_memory/                # 核心包
│       ├── __init__.py
│       ├── api/                    # API 层
│       │   ├── routes.py           # 路由定义
│       │   └── m8_interface.py     # M8 接口
│       ├── core/                   # 核心模块
│       │   ├── config.py
│       │   ├── models.py
│       │   └── skill_interface.py
│       ├── layers/                 # 四层记忆
│       │   ├── l0_beach.py
│       │   ├── l1_shallow.py
│       │   ├── l2_deep.py
│       │   └── l3_abyss.py
│       ├── recall/                 # 检索引擎
│       │   ├── recall_engine.py
│       │   ├── vector_search.py
│       │   └── keyword_search.py
│       ├── sleep/                  # 睡眠巩固
│       │   └── consolidation.py
│       ├── emotion/                # 情绪模块
│       │   ├── valence_arousal.py
│       │   └── ei_model.py
│       ├── security/               # 安全模块
│       │   ├── domain_manager.py
│       │   ├── secret_marker.py
│       │   └── desensitizer.py
│       ├── middleware/             # 中间件
│       │   └── auth.py
│       ├── audit/                  # 审计
│       │   └── audit_logger.py
│       └── utils/                  # 工具
│           ├── crypto.py           # AES-256 加密
│           └── hash_utils.py
├── tests/                          # 测试
├── docs/                           # 文档
│   ├── API.md / README.md
│   ├── 三级域权限设计.md
│   └── 四级密级标记规范.md
└── 开发日志/                        # 开发日志
```

#### API 接口清单（表格）

M5 共约 **11** 个 API 端点。

| 方法 | 路径 | 功能 | 鉴权 | 说明 |
|------|------|------|------|------|
| GET | `/health` | 健康检查 | 否 | 标准格式 |
| GET | `/api/v1/health` | API 健康检查 | 否 | |
| GET | `/m8/health` | M8 标准健康 | 否 | |
| POST | `/api/v1/memory/recall` | 记忆检索 | 是 | 向量 + 关键词混合 |
| POST | `/api/v1/memory/archive` | 记忆归档 | 是 | 写入 L0/L1 |
| GET | `/api/v1/memory/{id}` | 获取单条记忆 | 是 | |
| DELETE | `/api/v1/memory/{id}` | 删除记忆 | 是 | |
| GET | `/api/v1/memory/stats` | 记忆统计 | 是 | 各层数量等 |
| GET | `/api/v1/memory/layers` | 层级信息 | 是 | |
| POST | `/api/v1/memory/consolidate` | 触发巩固 | 是 | 手动触发 |
| POST | `/api/v1/memory/search` | 高级搜索 | 是 | |

#### 依赖项

**上游依赖（被谁调用）：**
- M1 多Agent调度中心（任务记忆存取）
- M2 技能集群（潮汐记忆技能）
- M3 端云协同内核（记忆同步）
- M4 场景引擎（场景上下文记忆）
- M8 管理工作台（记忆管理代理）

**下游依赖（调用谁）：**
- 本地 SQLite 数据库
- 向量索引（本地存储）
- Ollama 或云端嵌入模型（向量生成）

#### 故障隔离规则

- **不可用时的降级策略**：M5 故障时，记忆读写功能失效。Agent 对话可继续，但无长期记忆能力，每次对话无上下文关联。
- **对系统整体的影响级别**：P2（中等）——AI 对话可用，但失去记忆能力，体验大幅下降。
- **降级模式**：无记忆模式，仅使用当前会话上下文。
- **恢复方式**：重启 M5 进程，数据持久化在 SQLite 中，不会丢失。

#### 开发完成度

- **完成度**：85%
- **已落地功能列表**：
  - 四层潮汐记忆架构
  - 向量语义检索 + 关键词检索
  - 记忆巩固机制
  - AES-256-GCM 加密存储
  - 三级域权限 + 四级密级标记
  - 情绪记忆（效价-唤醒度模型）
  - 审计日志
  - M8 标准接口集成
  - 完整 API 文档
- **未开发/待完善功能列表**：
  - 记忆可视化与浏览界面
  - 记忆编辑与管理功能
  - 自动巩固调度（睡眠模式）
  - 记忆摘要与知识图谱构建
  - 多用户记忆隔离
  - 向量数据库替换（当前本地实现）
- **后续迭代规划**：
  - v2.5：记忆可视化与管理界面
  - v2.6：自动巩固调度优化
  - v3.0：知识图谱 + 记忆推理

---

### M6 - 硬件外设（Hardware Peripheral）

#### 基本信息

| 项目 | 内容 |
|------|------|
| 模块代号 | M6 |
| 中文名称 | 硬件外设 |
| 英文名称 | Hardware Peripheral Simulation |
| 版本号 | 1.0.0 |
| 监听端口 | 8006 |
| 技术栈 | Python + FastAPI + SSE |
| 启动方式 | `python server.py` |
| 入口文件 | `M6-hardware-peripheral/server.py` |

#### 定位与职责

M6 是云汐系统的硬件外设接入与模拟服务，负责智能穿戴设备、IoT 设备、传感器数据的统一接入与管理。当前以模拟模式运行，提供 6 种硬件设备的模拟数据与 SSE 实时推送，为上层应用提供硬件数据能力。

**核心能力清单：**

1. **设备模拟（6 种设备）**
   - 智能手表（Smart Watch）：心率、步数、血氧、睡眠
   - 智能戒指（Smart Ring）：体温、心率变异性、压力
   - AR 眼镜（AR Glasses）：视野、交互状态、电量
   - 桌面屏（Desktop Screen）：显示状态、亮度、模式
   - 无人机（Drone）：位置、高度、电池、状态
   - 笔记本（Laptop）：CPU、内存、电池、运行状态

2. **设备管理**
   - 设备注册与注销
   - 设备状态监控（在线/离线/警告）
   - 设备详情查询

3. **传感器数据采集**
   - 定时数据采集（默认 5 秒间隔）
   - 模拟数据生成（真实感模拟）
   - 历史数据查询

4. **实时推送（SSE）**
   - Server-Sent Events 实时数据流
   - 设备状态变更推送
   - 传感器数据更新推送
   - 告警通知推送

5. **设备控制**
   - 设备远程控制指令
   - 模式切换
   - 参数调整

#### 目录结构（树形）

```
M6-hardware-peripheral/
├── server.py                       # 启动入口
├── requirements.txt                # 依赖清单
├── verify_m6.py                    # 验证脚本
└── m6_hardware/                    # 核心包
    ├── __init__.py
    ├── config.py                   # 配置管理
    ├── api/                        # API 路由（16个端点）
    │   ├── __init__.py
    │   ├── devices.py              # 设备管理（7个端点）
    │   ├── sensors.py              # 传感器数据（3个端点）
    │   ├── control.py              # 设备控制（4个端点）
    │   └── health.py               # 健康检查（2个端点）
    ├── devices/                    # 设备模拟器
    │   ├── base_device.py          # 基类
    │   ├── smart_watch.py          # 智能手表
    │   ├── smart_ring.py           # 智能戒指
    │   ├── ar_glasses.py           # AR 眼镜
    │   ├── desktop_screen.py       # 桌面屏
    │   ├── drone.py                # 无人机
    │   └── laptop.py               # 笔记本
    ├── models/                     # 数据模型
    │   ├── device.py               # 设备模型
    │   └── sensor_data.py          # 传感器数据模型
    ├── services/                   # 业务服务
    │   ├── device_manager.py       # 设备管理器
    │   ├── data_collector.py       # 数据采集服务
    │   └── notification.py         # 通知服务
    └── realtime/                   # 实时通信
        └── sse_manager.py          # SSE 管理器
```

#### API 接口清单（表格）

M6 共约 **16+** 个 API 端点。

| 方法 | 路径 | 功能 | 鉴权 | 说明 |
|------|------|------|------|------|
| GET | `/` | 服务信息 | 否 | |
| GET | `/health` | 健康检查 | 否 | 标准格式 |
| GET | `/api/v1/devices` | 设备列表 | 否 | |
| GET | `/api/v1/devices/{id}` | 设备详情 | 否 | |
| GET | `/api/v1/devices/{id}/status` | 设备状态 | 否 | |
| POST | `/api/v1/devices/{id}/restart` | 重启设备 | 是 | |
| POST | `/api/v1/devices/{id}/enable` | 启用设备 | 是 | |
| POST | `/api/v1/devices/{id}/disable` | 禁用设备 | 是 | |
| GET | `/api/v1/sensors` | 传感器数据列表 | 否 | |
| GET | `/api/v1/sensors/latest` | 最新传感器数据 | 否 | |
| GET | `/api/v1/sensors/history` | 历史数据 | 是 | 时间范围查询 |
| POST | `/api/v1/control/{device_id}` | 发送控制指令 | 是 | |
| GET | `/api/v1/control/{device_id}/status` | 控制状态 | 是 | |
| POST | `/api/v1/control/{device_id}/mode` | 切换模式 | 是 | |
| GET | `/api/v1/health/status` | 健康状态详情 | 是 | |
| GET | `/api/v1/sse/stream` | SSE 实时流 | 否 | Server-Sent Events |

#### 依赖项

**上游依赖（被谁调用）：**
- M8 管理工作台（设备数据展示代理）
- M4 场景引擎（基于传感器数据的场景触发）

**下游依赖（调用谁）：**
- 模拟数据生成（内存计算，无外部依赖）
- 真实硬件设备（未来接入，当前模拟）

#### 故障隔离规则

- **不可用时的降级策略**：M6 故障时，硬件数据获取功能失效。不影响 AI 对话和核心功能，仅失去硬件数据输入。
- **对系统整体的影响级别**：P3（轻微）——失去硬件数据能力，但系统核心功能正常。
- **降级模式**：无硬件数据模式，场景切换依赖用户输入判断。
- **恢复方式**：重启 M6 进程，设备模拟器自动重新初始化。

#### 开发完成度

- **完成度**：70%
- **已落地功能列表**：
  - 6 种硬件设备模拟器
  - 设备管理 CRUD
  - 传感器数据采集与模拟
  - SSE 实时数据推送
  - 设备控制接口
  - 健康检查系统
  - 通知服务框架
- **未开发/待完善功能列表**：
  - 真实硬件设备接入（蓝牙/WiFi）
  - 更多设备类型
  - 设备固件升级管理
  - 数据持久化（当前内存为主）
  - 告警规则引擎
  - 设备分组与场景联动
- **后续迭代规划**：
  - v1.1：真实蓝牙设备接入
  - v1.2：告警规则 + 数据持久化
  - v2.0：设备市场 + 第三方设备接入

---

### M7 - 积木编排平台（Workflow Builder）

#### 基本信息

| 项目 | 内容 |
|------|------|
| 模块代号 | M7 |
| 中文名称 | 积木编排平台 |
| 英文名称 | Workflow Builder / Blocks Platform |
| 版本号 | 1.0.0 |
| 监听端口 | 3001 |
| 技术栈 | Python + FastAPI |
| 启动方式 | `python server.py` |
| 入口文件 | `M7-workflow-builder/server.py` |

#### 定位与职责

M7 是云汐系统的可视化工作流编排平台，采用「积木」隐喻，用户可以通过拖拽积木节点的方式构建自动化工作流。支持条件分支、循环、子工作流等高级编排能力，工作流节点可调用 M1 Agent 和 M2 技能。

**核心能力清单：**

1. **工作流管理**
   - 工作流 CRUD（创建、读取、更新、删除）
   - 工作流分类与标签
   - 工作流复制与导入导出

2. **积木系统**
   - 内置积木（触发、逻辑、数据、AI、工具等类别）
   - 自定义积木定义
   - 积木参数配置

3. **模板库**
   - 预置工作流模板
   - 模板分类浏览
   - 模板一键使用

4. **工作流执行**
   - 工作流引擎（执行与调度）
   - 运行记录与日志
   - 执行状态追踪

5. **M8 标准接口**
   - 健康检查 + 指标
   - M8 Token 鉴权中间件
   - 配置与升级接口

#### 目录结构（树形）

```
M7-workflow-builder/
├── server.py                       # 启动入口
├── requirements.txt                # 依赖清单
├── data/                           # 数据目录
└── src/                            # 源码
    ├── __init__.py                 # 版本号 1.0.0
    ├── main.py                     # FastAPI 主应用
    ├── routers/                    # API 路由（15个端点）
    │   ├── workflows.py            # 工作流管理（7个端点）
    │   ├── blocks.py               # 积木管理（3个端点）
    │   ├── templates.py            # 模板管理（3个端点）
    │   └── runs.py                 # 运行记录（2个端点）
    ├── services/                   # 业务服务
    │   ├── storage.py              # 存储服务
    │   └── engine.py               # 工作流引擎
    ├── models.py                   # 数据模型
    └── m8_api/                     # M8 标准接口
        ├── health_endpoints.py     # 健康与指标
        └── m8_auth_middleware.py   # M8 鉴权中间件
```

#### API 接口清单（表格）

M7 共约 **15+** 个 API 端点。

| 方法 | 路径 | 功能 | 鉴权 | 说明 |
|------|------|------|------|------|
| GET | `/` | 服务信息 | 否 | |
| GET | `/health` | 健康检查 | 否 | 标准格式 |
| GET | `/api/v1/health` | API 健康检查 | 否 | |
| GET | `/api/v1/workflows` | 工作流列表 | 是 | 分页、筛选、搜索 |
| GET | `/api/v1/workflows/{id}` | 工作流详情 | 是 | |
| POST | `/api/v1/workflows` | 创建工作流 | 是 | |
| PUT | `/api/v1/workflows/{id}` | 更新工作流 | 是 | |
| DELETE | `/api/v1/workflows/{id}` | 删除工作流 | 是 | |
| POST | `/api/v1/workflows/{id}/run` | 运行工作流 | 是 | |
| POST | `/api/v1/workflows/{id}/copy` | 复制工作流 | 是 | |
| GET | `/api/v1/blocks` | 积木列表 | 是 | |
| GET | `/api/v1/blocks/{id}` | 积木详情 | 是 | |
| POST | `/api/v1/blocks` | 自定义积木 | 是 | |
| GET | `/api/v1/templates` | 模板列表 | 是 | |
| GET | `/api/v1/templates/{id}` | 模板详情 | 是 | |
| POST | `/api/v1/templates/{id}/use` | 使用模板 | 是 | |
| GET | `/api/v1/runs` | 运行记录 | 是 | |
| GET | `/api/v1/runs/{id}` | 运行详情 | 是 | |

#### 依赖项

**上游依赖（被谁调用）：**
- M8 管理工作台（工作流管理代理）
- 前端 /m7 积木平台页面

**下游依赖（调用谁）：**
- M1 多Agent调度中心（AI 积木节点调用）
- M2 技能集群（工具积木节点调用）
- M5 潮汐记忆系统（记忆操作节点）

#### 故障隔离规则

- **不可用时的降级策略**：M7 故障时，工作流编排与执行功能失效。不影响 AI 对话和其他核心功能。
- **对系统整体的影响级别**：P3（轻微）——自动化工作流功能不可用，系统核心对话与场景功能正常。
- **降级模式**：无工作流模式，用户手动操作。
- **恢复方式**：重启 M7 进程，工作流定义从 JSON 文件恢复。

#### 开发完成度

- **完成度**：60%
- **已落地功能列表**：
  - 工作流 CRUD 基础框架
  - 积木系统基础框架
  - 模板系统基础框架
  - 工作流执行引擎基础
  - 运行记录
  - M8 标准接口集成
  - M8 Token 鉴权
- **未开发/待完善功能列表**：
  - 完整的可视化编排器前端
  - 丰富的内置积木库（36+ 积木）
  - 条件分支、循环、子工作流
  - 工作流调试与单步执行
  - 变量系统与数据传递
  - 错误处理与重试机制
  - 触发器（定时/事件/Webhook）
  - 与 M1/M2/M5 的深度集成
- **后续迭代规划**：
  - v1.1：完整积木库 + 可视化编排
  - v1.2：高级编排（分支/循环/子流）
  - v2.0：触发器 + 自动化调度

---

## 第三部分：开发进度台账

### 3.1 模块完成度总览（表格）

| 模块 | 名称 | 端口 | 版本号 | 完成度 | 状态 | 备注 |
|------|------|------|--------|--------|------|------|
| M8 | 管理工作台（控制塔） | 8000 | 1.0.0 | 90% | 核心完成 | 290+ API，22 个路由，6 大模式 + 5 大中心 |
| M1 | 多Agent调度中心 | 8001 | 11.1.0 | 95% | 核心完成 | 31+ API，联邦调度 + 八子 Agent |
| M2 | 技能集群 | 8002 | 3.10.2 | 85% | 功能完善 | 25+ API，10+ 内置技能，插件化架构 |
| M3 | 端云协同内核 | 8003 | 2.1.2 | 75% | 框架完成 | 12+ API，偏框架层，真实云端对接待完善 |
| M4 | 场景引擎 | 8004 | 1.0.0 | 70% | 基础可用 | 15+ API，六大场景 + 关键词识别 |
| M5 | 潮汐记忆系统 | 8005 | 2.4.0-REV2 | 85% | 功能完善 | 11 API，四层记忆 + 向量检索 + 加密 |
| M6 | 硬件外设 | 8006 | 1.0.0 | 70% | 模拟可用 | 16+ API，6 种设备模拟器 |
| M7 | 积木编排平台 | 3001 | 1.0.0 | 60% | 框架完成 | 15+ API，基础 CRUD + 执行框架 |

**系统整体完成度：约 79%**

### 3.2 版本历史

以下为项目主要里程碑提交（按时间倒序）：

| 序号 | 提交哈希 | 说明 |
|------|----------|------|
| 1 | bfbdac2 | M4 场景引擎 + M7 积木平台独立服务 + Alembic 数据库迁移 |
| 2 | 13fbfff | 集中修复 P0/P1 问题 - 数据库 schema / API 双重前缀 / 认证字段名 |
| 3 | ba6f4e2 | M1-M6 模块整合完善 - M3 代理端点 + M6 代理补全 + M3 缺失端点修复 |
| 4 | 7310dee | M8 控制塔大幅升级，完成度从 70% 提升到 90% |
| 5 | 919eef7 | 情绪陪伴 + 人际关系 + 形象工坊模式完整功能实现 |
| 6 | 618ec2c | M6 新增硬件外设模拟服务模块 |
| 7 | 6dfed86 | 生活管理模式完整功能实现 |
| 8 | f500bf5 | M5 向量检索兼容别名 + TF-IDF 阈值调整 |
| 9 | 5afbbbc | 学业规划模式完整功能实现 |
| 10 | 070a27b | 复盘总结模式完整功能实现 |
| 11 | 812e15f | 工作开发模式完整功能实现 |
| 12 | fcbd22e | M1 多 Agent + M2 技能集群整合到云汐系统 |
| 13 | ca47bd4 | 修复首页 API 错误和导航跳转问题 |
| 14 | 94d70a8 | 积木平台 + 成长中心前端对接真实 API |
| 15 | 9ceea64 / b1597ef | 系统全面升级 - Agent 中心 / 监控 / 设置 / 模式页 AI 功能 |
| 16 | dd9a93b | Hermes Agent 部署 + 全页面交互 + M5 潮汐记忆核心模块 |
| 17 | 53ce53d / ff03cd9 / 2d7a2c1 | M5 潮汐记忆系统模块逐步新增 |
| 18 | 4194e9d | 云汐系统 V1.0 完整整合：新增模块与 UI 界面 |
| 19 | 7db6732 | 云汐系统 V1.0 整合：千问大模型 + UI 全界面 + 桌面图标 |
| 20 | 8de61b3 | 自动提交：M1/M2/M3/M5 四大模块整合入项目 |
| 21 | 918f07d | 新增模型管理层 - 集成 Ollama 本地大模型支持 |
| 22 | a1f584c | 自动提交：UI 界面整合与后端 API 对接完成 |
| 23 | 68bfff3 | 云汐系统整合项目初始提交 |

### 3.3 已知待办事项

按优先级排列的待完成功能清单：

**P0（最高优先级）：**

1. **M7 积木平台可视化编排器**：当前仅有后端 API 和基础框架，缺少可视化拖拽编排前端
2. **M4 场景引擎 LLM 增强识别**：当前仅关键词匹配，需接入 LLM 做语义级场景识别
3. **M1 任务持久化与断点续做**：增强任务可靠性，确保进程重启后任务可恢复
4. **M8 性能优化**：290+ API 的性能监控与优化，数据库索引优化

**P1（高优先级）：**

1. **M5 记忆可视化与管理界面**：用户可浏览、编辑、管理自己的记忆
2. **M3 完整端云双向同步**：从框架层走向真实可用的端云同步
3. **M2 更多内置技能**：从 10+ 扩充到 30+ 常用技能
4. **M6 真实硬件设备接入**：蓝牙 / WiFi 真实设备对接
5. **M1 联邦调度自动故障转移**：Agent 故障时自动切换备用 Agent
6. **M8 全量自动化测试**：22 个路由的端到端测试覆盖

**P2（中优先级）：**

1. **M4 场景暖切换过渡动画**：场景切换时的平滑过渡体验
2. **M4 自定义场景创建**：用户可自定义场景与触发规则
3. **M6 告警规则引擎**：基于传感器数据的智能告警
4. **M6 数据持久化**：传感器历史数据持久化存储
5. **M2 技能市场框架**：第三方技能的发现与安装
6. **M5 自动巩固调度（睡眠模式）**：后台自动记忆巩固
7. **M7 高级编排能力**：条件分支、循环、子工作流
8. **多用户与多租户支持**：当前单用户设计，需扩展多用户

**P3（低优先级 / 长期规划）：**

1. **M1 分布式 Agent 集群**：从单进程到分布式部署
2. **M3 端侧 AI 推理卸载**：端侧设备本地运行小模型
3. **M5 知识图谱 + 记忆推理**：从记忆存储到知识推理
4. **M2 可视化技能编排器**：拖拽式技能组合
5. **插件化架构（v2.0）**：支持第三方模块热插拔
6. **国际化支持（i18n）**：多语言界面
7. **移动端适配**：手机 / 平板端 UI 优化

---

## 附录 A：shared 公共模块

### A.1 模块说明

`shared/` 目录是云汐系统的公共基础库，为所有模块提供共享的配置管理、日志、模块间通信客户端等基础设施。

### A.2 目录结构

```
shared/
├── config.py           # 全局配置管理
├── module_client.py    # 模块间 HTTP 通信客户端
├── logger.py           # 统一日志配置
├── models.py           # 共享数据模型
├── utils.py            # 通用工具函数
└── exceptions.py       # 统一异常定义
```

### A.3 核心组件

| 组件 | 文件 | 功能说明 |
|------|------|----------|
| 配置管理 | config.py | 从环境变量和配置文件加载全局配置，支持 .env 文件 |
| 模块客户端 | module_client.py | 封装 HTTP 请求，自动注入 X-M8-Token，统一错误处理 |
| 日志 | logger.py | 统一的日志格式与级别配置 |
| 数据模型 | models.py | 跨模块共享的 Pydantic 模型定义 |
| 工具函数 | utils.py | 通用工具函数集合 |
| 异常类 | exceptions.py | 统一的业务异常定义 |

---

## 附录 B：前端页面架构

### B.1 前端技术栈

- **框架**：原生 HTML / CSS / JavaScript（无构建工具）
- **样式**：Tailwind CSS（CDN 引入）
- **图标**：Lucide Icons
- **图表**：Chart.js
- **部署方式**：由 M8 控制塔作为静态文件服务

### B.2 页面结构

前端页面位于 `M8-control-tower/frontend/` 目录下，共 **6 大模式页面 + 5 大中心页面 + 登录页 + 首页**。

| 页面类型 | 页面名称 | 路径 | 功能说明 |
|----------|----------|------|----------|
| 入口 | 登录页 | login.html | 用户登录注册 |
| 入口 | 首页（仪表盘） | index.html | 系统总览 + 快捷入口 |
| 模式 | 工作开发 | mode-work.html | 编程助手 + 项目管理 + 技术学习 |
| 模式 | 学业规划 | mode-study.html | 学习计划 + 知识整理 + 考试准备 |
| 模式 | 复盘总结 | mode-review.html | 每日复盘 + 周月总结 + 目标回顾 |
| 模式 | 人际关系 | mode-people.html | 社交建议 + 情感分析 + 沟通技巧 |
| 模式 | 情绪陪伴 | mode-emotion.html | 聊天陪伴 + 情绪疏导 + 心理支持 |
| 模式 | 生活管理 | mode-life.html | 日程 + 待办 + 习惯 + 财务 |
| 中心 | Agent 中心 | agent-center.html | Agent 管理 + 分身池 + 联邦调度 |
| 中心 | 积木平台 | blocks-platform.html | 工作流可视化编排 |
| 中心 | 成长中心 | growth-center.html | 成长记录 + 成就系统 |
| 中心 | 形象工坊 | avatar-workshop.html | AI 形象自定义 |
| 中心 | 监控中心 | monitor-center.html | 系统监控 + 模块健康状态 |
| 中心 | 设置中心 | settings.html | 系统设置 + 模型配置 |

### B.3 前端架构特点

1. **单页应用风格**：每个 HTML 页面独立，但通过导航栏统一跳转
2. **侧栏导航**：左侧固定导航栏，支持模式切换
3. **响应式设计**：Tailwind CSS 响应式布局
4. **流式输出**：AI 对话支持 SSE 流式渲染
5. **深色主题**：默认深色模式，符合「云汐」品牌调性
6. **无构建依赖**：纯静态文件，直接由 FastAPI 静态文件服务托管

---

*文档版本：v1.0*
*生成日期：2026-07-07*
*适用项目：云汐系统（Yunxi System）*

