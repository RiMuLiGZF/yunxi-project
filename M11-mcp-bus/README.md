# M11 MCP 总线服务 (MCP Bus)

**模块代号**：M11
**模块名称**：MCP 总线服务
**版本**：v0.1.0
**端口**：8011
**技术栈**：FastAPI + SQLAlchemy + SQLite + FastMCP

---

## 一、模块概述

M11 MCP 总线服务是云汐系统的 MCP（Model Context Protocol）服务总线，负责统一管理所有 MCP 服务的注册、发现、路由和调用。它作为 MCP 生态的核心枢纽，向上游消费方提供统一的工具聚合接口，向下游 MCP 服务提供标准化的注册与心跳机制。

### 核心能力

| 能力 | 说明 |
|------|------|
| **服务注册** | MCP 服务向总线注册自身信息与工具清单 |
| **工具聚合** | 聚合所有已注册服务的工具，提供统一查询入口 |
| **请求路由** | 根据工具名自动路由到对应 MCP 服务执行 |
| **统一鉴权** | API Key 管理，支持细粒度权限控制与限流 |
| **监控审计** | 全链路调用日志、成功率统计、耗时分析 |
| **健康检查** | 心跳机制自动检测服务在线状态 |
| **M8 标准对接** | 完整实现 /m8/health、/m8/metrics、/m8/config |

---

## 二、目录结构

```
M11-mcp-bus/
├── server.py              # 服务启动入口
├── requirements.txt       # 依赖列表
├── .env.example           # 配置示例
├── README.md              # 本文件
├── data/                  # 数据目录
│   └── .gitkeep
└── src/                   # 核心代码
    ├── __init__.py
    ├── config.py          # 配置模块
    ├── db.py              # 数据库基础设施
    ├── models_db.py       # SQLAlchemy 数据模型
    ├── models.py          # Pydantic 数据模型
    ├── main.py            # FastAPI 主入口（待实现）
    ├── routers/           # 路由模块
    │   └── __init__.py
    └── services/          # 业务服务
        └── __init__.py
```

---

## 三、配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M11_HOST` | `0.0.0.0` | 监听地址 |
| `M11_PORT` | `8011` | 监听端口 |
| `M11_ENV` | `development` | 运行环境 |
| `M11_LOG_LEVEL` | `info` | 日志级别 |
| `M11_ADMIN_TOKEN` | `""` | M8 对接管理 Token |
| `M11_DB_PATH` | `~/.yunxi/m11_bus.db` | SQLite 数据库路径 |
| `M11_HEARTBEAT_TIMEOUT` | `30` | 心跳超时时间（秒） |
| `M11_TOOL_REFRESH_INTERVAL` | `300` | 工具刷新间隔（秒） |

### 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env

# 启动服务
python server.py

# 健康检查
curl http://localhost:8011/health

# API 文档
http://localhost:8011/docs
```

---

## 四、API 接口

### 4.1 M8 标准接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查 |
| `/m8/metrics` | GET | M8 标准性能指标 |
| `/m8/config` | GET | M8 标准配置查询 |

### 4.2 服务注册与管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/servers` | GET | 获取已注册 MCP 服务列表 |
| `/api/v1/servers/{id}` | GET | 获取服务详情 |
| `/api/v1/servers` | POST | 注册新的 MCP 服务 |
| `/api/v1/servers/{id}` | PUT | 更新服务信息 |
| `/api/v1/servers/{id}` | DELETE | 注销 MCP 服务 |
| `/api/v1/servers/{id}/heartbeat` | POST | 服务心跳上报 |
| `/api/v1/servers/{id}/tools/refresh` | POST | 刷新服务工具列表 |

### 4.3 工具查询与调用

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/tools` | GET | 获取所有可用工具列表 |
| `/api/v1/tools/{tool_name}` | GET | 获取工具详情 |
| `/api/v1/tools/call` | POST | 调用指定工具 |
| `/api/v1/tools/categories` | GET | 工具分类列表 |

### 4.4 调用记录与审计

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/calls` | GET | 获取调用历史记录 |
| `/api/v1/calls/{id}` | GET | 获取单次调用详情 |

### 4.5 管理 API

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/admin/api-keys` | GET | 获取 API Key 列表 |
| `/api/v1/admin/api-keys` | POST | 创建新的 API Key |
| `/api/v1/admin/api-keys/{id}` | DELETE | 撤销 API Key |
| `/api/v1/admin/metrics` | GET | 总线运营指标 |

### 4.6 MCP 协议端点

| 接口 | 方法 | 说明 |
|------|------|------|
| `/mcp` | POST | MCP 协议统一入口（SSE/Streamable HTTP） |
| `/mcp/tools/list` | POST | MCP tools/list 方法 |
| `/mcp/tools/call` | POST | MCP tools/call 方法 |

---

## 五、数据模型

### MCP 服务 (McpServer)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| name | String | 服务名称（唯一） |
| description | Text | 服务描述 |
| transport_type | String | 传输类型：http/sse/stdio |
| endpoint | String | 服务端点地址 |
| status | String | 状态：online/offline |
| api_key | String | 服务鉴权密钥 |
| health_check_url | String | 健康检查地址 |
| last_heartbeat | DateTime | 最后心跳时间 |
| created_at | DateTime | 创建时间 |

### MCP 工具 (McpTool)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| server_id | Integer | 所属服务 ID |
| name | String | 工具名称 |
| description | Text | 工具描述 |
| category | String | 工具分类 |
| input_schema | JSON | 输入参数 Schema |
| cached_at | DateTime | 缓存时间 |

### 调用记录 (McpCall)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| tool_name | String | 被调用工具名 |
| server_id | Integer | 目标服务 ID |
| consumer | String | 调用方标识 |
| status | String | 状态：success/failed |
| duration_ms | Integer | 耗时（毫秒） |
| error_message | Text | 错误信息 |
| request_snippet | Text | 请求摘要 |
| response_snippet | Text | 响应摘要 |
| created_at | DateTime | 创建时间 |

### API 密钥 (ApiKey)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| key_hash | String | 密钥哈希 |
| name | String | 密钥名称 |
| permissions | JSON | 权限列表 |
| rate_limit | Integer | 限流阈值（次/分钟） |
| created_at | DateTime | 创建时间 |
| expires_at | DateTime | 过期时间 |
| last_used_at | DateTime | 最后使用时间 |

---

## 六、架构设计

### 架构图（文字版）

```
┌───────────────────────────────────────────────────────────────┐
│                        M11 MCP Bus                             │
│                      ┌───────────────────┐                     │
│                      │   FastAPI 网关    │                     │
│                      │  (鉴权 / 限流)    │                     │
│                      └─────────┬─────────┘                     │
│                                │                               │
│              ┌─────────────────┼─────────────────┐             │
│              │                 │                 │             │
│     ┌────────▼──────┐  ┌──────▼────────┐  ┌─────▼────────┐    │
│     │  服务注册中心  │  │  工具聚合层    │  │  请求路由层  │    │
│     │ (Registry)    │  │ (Tool Agg.)   │  │  (Router)    │    │
│     └────────┬──────┘  └──────┬────────┘  └─────┬────────┘    │
│              │                 │                 │             │
│              └─────────────────┼─────────────────┘             │
│                                │                               │
│                      ┌─────────▼─────────┐                     │
│                      │   SQLAlchemy      │                     │
│                      │   SQLite 存储     │                     │
│                      └───────────────────┘                     │
└───────────────────────────────┬───────────────────────────────┘
                                │
           ┌────────────────────┼────────────────────┐
           │                    │                    │
    ┌──────▼─────┐       ┌──────▼─────┐       ┌──────▼─────┐
    │ MCP 服务 A │       │ MCP 服务 B │       │ MCP 服务 C │
    │ (HTTP/SSE) │       │  (stdio)   │       │  (SSE)     │
    └────────────┘       └────────────┘       └────────────┘
```

### 核心流程

1. **服务注册**：MCP 服务启动后向总线注册，提交服务信息与工具清单
2. **心跳保活**：已注册服务定期上报心跳，总线维护在线状态
3. **工具发现**：消费方查询工具列表，总线聚合所有在线服务的工具
4. **请求路由**：消费方调用工具，总线根据工具名路由到对应服务
5. **结果返回**：执行结果沿原路返回，总线记录调用日志

---

## 七、与其他模块关系

```
┌─────────────┐               ┌─────────────┐
│  M1 调度中心  │ ◀─────────── │  M11 MCP    │
│  (消费方)    │    工具调用    │  总线服务    │
└─────────────┘               └──────┬──────┘
                                     │
                               M8 纳管
                                     │
                               ┌─────▼─────┐
                               │ M8 管理台 │
                               └───────────┘
                                     │
                                     ▼
              ┌──────────────────────────────────────┐
              │  下游 MCP 服务（M2/M5/M6/M9 等）    │
              └──────────────────────────────────────┘
```

- **上游消费方**：M1 调度中心、前端界面等通过 M11 统一调用 MCP 工具
- **下游服务方**：各个 MCP 兼容服务向 M11 注册自身能力
- **管理台**：M8 通过 M8 标准接口纳管 M11
