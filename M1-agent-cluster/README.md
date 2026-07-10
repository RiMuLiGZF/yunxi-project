# M1 多Agent集群调度 (Agent Cluster)

**模块代号**：M1
**模块名称**：多Agent集群调度
**版本**：v11.1
**端口**：8001
**技术栈**：FastAPI + 联邦调度 + 8 个子 Agent

---

## 一、模块概述

M1 多Agent集群调度是云汐系统的核心调度中枢，采用联邦调度架构，管理 8 个功能各异的子 Agent，通过智能路由、负载均衡、熔断降级等机制，确保用户请求被最优分配到最合适的 Agent 处理。

### 核心能力

| 能力 | 说明 |
|------|------|
| **8 个子 Agent** | Arbiter、Budget、Bus、Discovery、Lifecycle、Security、Snapshot、Voice |
| **联邦调度** | 16+ 外部 Agent Adapter，支持 DeepSeek/OpenAI/Gemini 等 |
| **成本管控** | 预算管理、成本统计、Token 用量追踪 |
| **隐私防护** | 数据脱敏、分级权限、隐私扫描 |
| **分身池** | Agent 克隆、实例池管理、自适应扩缩容 |
| **健康监控** | 实时健康检查、熔断器、重试机制 |
| **M8 标准对接** | 完整实现 /m8/health、/m8/metrics、/m8/config |

---

## 二、子 Agent 一览

| Agent | 代号 | 职责 |
|-------|------|------|
| **Arbiter** | 仲裁者 | 任务分发、结果仲裁、质量评估 |
| **Budget** | 预算官 | 成本管控、预算分配、用量统计 |
| **Bus** | 消息总线 | 消息传递、事件订阅、广播通知 |
| **Discovery** | 发现者 | Agent 注册、能力发现、路由决策 |
| **Lifecycle** | 生命周期 | 实例管理、状态追踪、优雅启停 |
| **Security** | 安全官 | 权限校验、数据脱敏、安全审计 |
| **Snapshot** | 快照师 | 状态快照、版本回滚、记忆备份 |
| **Voice** | 语音师 | 语音交互、TTS/ASR、情感语音 |

---

## 三、配置说明

### 配置文件

- `config.yaml` — 主配置文件
- `config.example.yaml` — 配置示例（7大类配置）

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M1_HOST` | `0.0.0.0` | 监听地址 |
| `M1_PORT` | `8001` | 监听端口 |
| `M1_ENV` | `development` | 运行环境 |
| `M1_ADMIN_TOKEN` | `""` | M8 对接管理 Token |

### 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python server.py

# 健康检查
curl http://localhost:8001/health

# API 文档
http://localhost:8001/docs
```

---

## 四、API 接口

### 4.1 M8 标准接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查 |
| `/m8/metrics` | GET | M8 标准性能指标 |
| `/m8/config` | GET | M8 标准配置查询 |

### 4.2 任务调度

| 接口 | 方法 | 说明 |
|------|------|------|
| `POST /api/v1/tasks/submit` | POST | 提交任务 |
| `GET /api/v1/tasks/{task_id}/status` | GET | 任务状态查询 |
| `POST /api/v1/chat` | POST | 同步对话 |
| `POST /api/v1/chat/stream` | POST | 流式对话 |

### 4.3 Agent 管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/v1/agents` | GET | Agent 列表 |
| `GET /api/v1/agents/{agent_id}/status` | GET | Agent 状态 |
| `DELETE /api/v1/agents/{agent_id}` | DELETE | Agent 注销 |

### 4.4 联邦调度

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /v1/federation/agents` | GET | 联邦Agent列表 |
| `POST /v1/federation/dispatch` | POST | 调度决策 |
| `POST /v1/federation/call` | POST | 调用联邦Agent |
| `POST /v1/federation/compare` | POST | 多模型对比 |
| `POST /v1/federation/privacy-scan` | POST | 隐私扫描 |
| `GET /v1/federation/cost` | GET | 成本统计 |

### 4.5 分身池

| 接口 | 方法 | 说明 |
|------|------|------|
| `POST /v1/pool/clone` | POST | 创建分身 |
| `GET /v1/pool/list` | GET | 分身列表 |
| `DELETE /v1/pool/{id}` | DELETE | 回收分身 |

---

## 五、测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行联邦调度测试
pytest tests/test_v11_federation.py -v

# 运行 M8 集成测试
pytest tests/test_v11_1_m8_integration.py -v
```

---

## 六、架构说明

```
                    ┌─────────────────────┐
                    │    API Gateway      │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Federation Scheduler│
                    │  （联邦调度器）       │
                    └──────────┬──────────┘
          ┌────────────────────┼────────────────────┐
┌─────────▼────────┐ ┌────────▼────────┐ ┌─────────▼────────┐
│  Internal Agents │ │  External Agents │ │  Clone Pool       │
│  （8个子Agent）   │ │  （16+ Adapter） │ │  （分身池）       │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

---

## 七、与其他模块关系

- **上游**：M8 管理台通过 M8 标准接口纳管 M1
- **下游**：调用 M2 技能集群扩展能力
- **数据**：通过 M5 潮汐记忆系统存储对话历史
