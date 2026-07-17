# M2 技能集群 (Skill Cluster)

**模块代号**：M2
**模块名称**：技能集群
**版本**：v2.0
**端口**：8002
**技术栈**：FastAPI + 技能注册中心 + 18个内置技能

---

## 一、模块概述

M2 技能集群是云汐系统的能力扩展层，提供可插拔的技能注册、发现、路由和执行框架。内置 18 种实用技能，并支持通过 MCP 协议、A2A 协议接入外部技能。

### 核心能力

| 能力 | 说明 |
|------|------|
| **18 个内置技能** | 日历、待办、目标、全文搜索、文档处理、数据分析等 |
| **技能注册中心** | 技能注册、发现、分类管理、开关控制 |
| **智能路由** | 语义匹配 + 贝叶斯 + 老虎机算法，最优技能推荐 |
| **执行管线** | 技能流水线执行、缓存、重试、熔断降级 |
| **MCP 桥接** | 支持 MCP 协议接入外部工具 |
| **A2A 总线** | 支持 A2A 协议的 Agent 间协作 |
| **沙箱隔离** | 代码执行类技能在沙箱中运行 |
| **M8 标准对接** | 完整实现 /m8/health、/m8/metrics、/m8/config |

---

## 二、内置技能列表

### 2.1 已实现技能（18个）

所有技能均有完整实现，位于 `skill_cluster/skills/` 目录。

| 技能 | 分类 | 说明 | 代码行数 |
|------|------|------|--------|
| **calendar** | 效率 | 日历管理、日程提醒 | 173 |
| **todo** | 效率 | 待办事项、任务管理 | 543 |
| **goal** | 效率 | 目标追踪、OKR 管理 | 595 |
| **habit** | 效率 | 习惯养成、打卡统计 | 467 |
| **flashcard** | 学习 | 闪卡记忆、间隔重复 | 592 |
| **journal** | 学习 | 日记写作、情绪记录 | 417 |
| **mood** | 健康 | 心情追踪、情绪分析 | 525 |
| **fulltext_search** | 工具 | 全文搜索、关键词检索 | 146 |
| **doc_proc** | 工具 | 文档处理、格式转换 | 146 |
| **data_analysis** | 工具 | 数据分析、图表生成 | 146 |
| **code_search** | 开发 | 代码搜索、符号查找 | 179 |
| **code_skills** | 开发 | 代码生成、重构建议 | 847 |
| **translate** | 工具 | 多语言翻译 | 155 |
| **web_fetch** | 工具 | 网页抓取、内容提取 | 139 |
| **finance** | 生活 | 财务记录、账单统计 | 695 |
| **contact** | 社交 | 联系人管理 | 505 |
| **notify** | 系统 | 通知推送、消息提醒 | 138 |
| **tide_memory** | 系统 | 潮汐记忆接入 | 629 |

### 2.2 待规划技能（0个）

当前所有规划内技能均已实现，暂无存根状态的技能。

> 注：`skill_cluster/stubs/` 目录存放的是**向后兼容存根**（从根目录迁移的旧模块名，
> 非待实现功能。所有存根模块导入时会发出 `DeprecationWarning`，请使用新路径即可。

---

## 三、目录结构

```
M2-skills-cluster/
├── skill_cluster/              # 主包
│   ├── __init__.py           # 包入口（含 stubs 延迟加载）
│   ├── config.py             # 配置模型
│   ├── error_codes.py        # 错误码定义
│   ├── exceptions.py         # 异常定义
│   ├── interfaces.py         # 核心接口
│   ├── mcp_transport.py      # MCP传输层
│   ├── version.py            # 版本号
│   ├── skills/               # 18个内置技能实现
│   ├── core/                 # 核心引擎
│   ├── api/                  # API层
│   ├── agent/                # Agent运行时
│   ├── models/               # 数据模型
│   ├── db/                   # 数据层
│   ├── discovery/            # 技能发现
│   ├── resilience/           # 弹性容错
│   ├── security/             # 安全沙箱
│   ├── infrastructure/       # 基础设施
│   ├── extensions/           # 扩展（MCP/语音）
│   ├── market/               # 技能市场
│   ├── onnx_runtime/         # ONNX运行时
│   ├── tests/                # 单元测试
│   └── stubs/                # 向后兼容存根（47个，已迁移模块）
├── tests/                     # 集成测试
├── start_server.py             # 启动入口
├── resource.py                 # 资源管理
└── README.md
```

---

## 四、配置说明

### 配置文件

- `config.example.yaml` — 配置示例（15大类配置）
- `skill_cluster/config.py` — Pydantic 配置模型

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M2_HOST` | `0.0.0.0` | 监听地址 |
| `M2_PORT` | `8002` | 监听端口 |
| `M2_ENV` | `development` | 运行环境 |
| `M2_ADMIN_TOKEN` | `""` | M8 对接管理 Token |

### 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python start_server.py

# 健康检查
curl http://localhost:8002/health

# API 文档
http://localhost:8002/docs
```

---

## 五、API 接口

### 4.1 M8 标准接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查 |
| `/m8/metrics` | GET | M8 标准性能指标 |
| `/m8/config` | GET | M8 标准配置查询 |

### 4.2 技能管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/v2/skills` | GET | 技能列表（支持分类过滤、分页） |
| `GET /api/v2/skills/{skill_id}` | GET | 技能详情 |
| `POST /api/v2/skills/{skill_id}/toggle` | POST | 技能开关 |
| `GET /api/v2/categories` | GET | 技能分类列表 |

### 4.3 技能调用

| 接口 | 方法 | 说明 |
|------|------|------|
| `POST /api/v2/skills/invoke` | POST | 调用单个技能 |
| `POST /api/v2/skills/batch-invoke` | POST | 批量调用技能 |
| `POST /api/v2/recommend/test` | POST | 推荐测试 |

### 4.4 统计

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/v2/stats/accuracy` | GET | 准确率统计 |
| `GET /api/v2/stats/invocations` | GET | 调用统计 |
| `GET /api/v2/stats/system` | GET | 系统统计 |

### 4.5 MCP 桥接

| 接口 | 方法 | 说明 |
|------|------|------|
| `POST /mcp/v1/tools/list` | POST | MCP 工具列表 |
| `POST /mcp/v1/tools/call` | POST | MCP 工具调用 |

---

## 五、测试

```bash
# 运行所有测试
pytest skill_cluster/tests/ -v

# 运行 M8 集成测试
pytest skill_cluster/tests/test_m8_integration.py -v

# 运行技能管线测试
pytest skill_cluster/tests/test_pipeline.py -v
```

---

## 七、与其他模块关系

```
┌─────────────┐  技能调用    ┌─────────────┐
│  M1 调度中心 │ ───────────▶ │  M2 技能集群 │
└─────────────┘              └──────┬──────┘
                                    │
                              M8 纳管
                                    │
                              ┌─────▼─────┐
                              │ M8 管理台 │
                              └───────────┘
```

- **上游**：M1 调度中心、M7 积木平台通过 API 调用 M2 技能
- **下游**：M2 调用 M5 潮汐记忆存储技能数据
- **管理**：M8 管理台通过 M8 标准接口纳管 M2
