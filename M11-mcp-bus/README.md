# M11 MCP 总线服务 (MCP Bus)

**模块代号**：M11
**模块名称**：MCP 总线服务
**版本**：v1.2.0
**端口**：8011
**技术栈**：FastAPI + SQLAlchemy + SQLite + httpx

---

## 一、模块概述

M11 MCP 总线服务是云汐系统的 MCP（Model Context Protocol）服务总线，负责统一管理所有 MCP 服务的注册、发现、路由和调用。它作为 MCP 生态的核心枢纽，向上游消费方提供统一的工具聚合接口，向下游 MCP 服务提供标准化的注册与心跳机制。

### 核心能力

| 能力 | 说明 |
|------|------|
| **服务注册** | MCP 服务向总线注册自身信息与工具清单 |
| **工具聚合** | 聚合所有已注册服务的工具，提供统一查询入口 |
| **请求路由** | 根据工具名自动路由到对应 MCP 服务执行 |
| **多传输支持** | 支持 HTTP、SSE、stdio 三种传输方式 |
| **统一鉴权** | API Key 管理，支持细粒度权限控制与限流 |
| **监控审计** | 全链路调用日志、成功率统计、耗时分析 |
| **健康检查** | 心跳机制自动检测服务在线状态 |
| **熔断重试** | 熔断器 + 指数退避重试，保障服务稳定性 |
| **结果缓存** | 工具结果缓存，提升重复调用性能 |
| **M8 标准对接** | 完整实现 /m8/health、/m8/metrics、/m8/config |
| **多适配器** | 内置 M1~M10、Voice 等多种适配器 |

---

## 二、目录结构

```
M11-mcp-bus/
├── server.py              # 服务启动入口
├── requirements.txt       # 依赖列表
├── .env.example           # 配置示例
├── README.md              # 本文件
├── pytest.ini             # 测试配置
├── Dockerfile             # Docker 构建文件
├── data/                  # 数据目录
├── docs/                  # 文档目录
│   └── ARCHITECTURE.md    # 架构文档
├── frontend/              # 前端静态文件
├── logs/                  # 日志目录
├── tools/                 # 工具脚本
│   ├── start_all_adapters.py
│   ├── start_m2_adapter.py
│   └── ...
├── tests/                 # 测试用例
│   ├── test_protocol.py   # Protocol 层测试
│   ├── test_transport.py  # Transport 层测试
│   ├── test_auth.py
│   ├── test_cache.py
│   └── ...
└── src/                   # 核心代码
    ├── __init__.py
    ├── __main__.py
    ├── config.py          # 配置模块
    ├── db.py              # 数据库基础设施
    ├── models_db.py       # SQLAlchemy 数据模型
    ├── models.py          # Pydantic 数据模型
    ├── errors.py          # 错误码定义
    ├── main.py            # FastAPI 主入口
    │
    ├── protocol/          # [新增] 协议层 - JSON-RPC 2.0
    │   ├── __init__.py
    │   ├── jsonrpc.py     # JSON-RPC 解析器
    │   └── types.py       # 类型定义与常量
    │
    ├── transport/         # [新增] 传输层 - 多传输抽象
    │   ├── __init__.py
    │   ├── base.py        # 传输基类 BaseTransport
    │   ├── http_transport.py   # HTTP 传输实现
    │   ├── sse_transport.py    # SSE 传输实现
    │   ├── stdio_transport.py  # stdio 传输实现
    │   └── factory.py     # 传输工厂
    │
    ├── security/          # [新增] 安全层 - 认证/权限/审计
    │   ├── __init__.py
    │   ├── auth.py        # API Key 认证
    │   ├── permission.py  # 权限检查
    │   └── audit.py       # 审计日志
    │
    ├── middleware/        # 中间件（薄适配层）
    │   ├── __init__.py
    │   └── auth.py        # 鉴权中间件（委托给 security/）
    │
    ├── routers/           # 路由层 - HTTP 端点
    │   ├── __init__.py
    │   ├── mcp.py         # MCP 协议端点
    │   ├── admin.py       # 管理 API
    │   ├── health.py      # 健康检查
    │   ├── monitor.py     # 监控指标
    │   └── console.py     # 控制台
    │
    ├── services/          # 服务层 - 业务逻辑
    │   ├── __init__.py
    │   ├── registry.py    # 服务注册中心
    │   ├── router.py      # 请求路由转发
    │   ├── cache.py       # 缓存服务
    │   ├── monitor.py     # 监控服务
    │   ├── audit.py       # 审计服务（业务封装）
    │   ├── rate_limiter.py # 限流服务
    │   ├── sse_manager.py # SSE 连接管理（服务端）
    │   ├── stdio_manager.py # stdio 服务管理（服务端）
    │   ├── health_checker.py # 健康检查
    │   ├── redis_client.py # Redis 客户端
    │   ├── mcp_block_executor.py # MCP 阻塞执行器
    │   ├── scheduler.py   # 定时任务
    │   ├── m7_sync.py     # M7 同步
    │   └── alert.py       # 告警服务
    │
    ├── adapters/          # 适配器层 - 外部系统对接
    │   ├── __init__.py
    │   ├── base.py
    │   ├── m1_adapter.py
    │   ├── m2_adapter.py
    │   ├── m3_adapter.py
    │   └── ...
    │
    └── sdk/               # SDK - 客户端 SDK
        ├── __init__.py
        └── mcp_bus_client.py
```

---

## 三、架构说明

M11 采用清晰的四层架构设计，自底向上分别为：

```
┌─────────────────────────────────────────┐
│         API 层 (Routers)                │  HTTP 端点
├─────────────────────────────────────────┤
│         服务层 (Services)               │  业务逻辑
├─────────────────────────────────────────┤
│         安全层 (Security)               │  认证/权限/审计
├─────────────────────────────────────────┤
│         传输层 (Transport)              │  HTTP/SSE/stdio
├─────────────────────────────────────────┤
│         协议层 (Protocol)               │  JSON-RPC 2.0
└─────────────────────────────────────────┘
```

**各层职责**：

| 层级 | 目录 | 职责 |
|------|------|------|
| Protocol 协议层 | `src/protocol/` | JSON-RPC 2.0 协议编解码，纯逻辑层 |
| Transport 传输层 | `src/transport/` | 统一传输抽象，支持 HTTP/SSE/stdio |
| Security 安全层 | `src/security/` | 认证、权限、审计，不依赖 Web 框架 |
| Services 服务层 | `src/services/` | 业务逻辑：注册中心、路由、缓存、监控 |
| API 层 | `src/routers/` | HTTP 端点，接收外部请求 |

> 详细架构说明请参考 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## 四、配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M11_HOST` | `0.0.0.0` | 监听地址 |
| `M11_PORT` | `8011` | 监听端口 |
| `M11_ENV` | `development` | 运行环境 |
| `M11_LOG_LEVEL` | `info` | 日志级别 |
| `M11_ADMIN_TOKEN` | `""` | 管理 Token |
| `M11_DB_PATH` | `~/.yunxi/m11_bus.db` | SQLite 数据库路径 |
| `M11_HEARTBEAT_TIMEOUT` | `30` | 心跳超时时间（秒） |
| `M11_TOOL_REFRESH_INTERVAL` | `300` | 工具刷新间隔（秒） |
| `M11_API_KEY_AUTH_ENABLED` | `true` | 是否启用 API Key 鉴权 |
| `M11_MCP_REQUIRE_AUTH` | `true` | MCP 端点是否需要鉴权 |
| `M11_MCP_DEFAULT_API_KEY` | `m11_mcp_dev_key_default_change_me` | 默认 API Key（仅开发） |
| `M11_SSE_MAX_CLIENTS` | `100` | SSE 最大连接数 |
| `M11_STDIO_ENABLED` | `true` | 是否启用 stdio 传输 |
| `M11_STDIO_MAX_SERVICES` | `10` | 最大 stdio 服务数 |
| `M11_REDIS_URL` | `""` | Redis 连接 URL（空为不启用） |
| `M11_RETRY_MAX_ATTEMPTS` | `2` | 最大重试次数 |
| `M11_CIRCUIT_BREAKER_FAIL_THRESHOLD` | `5` | 熔断器失败阈值 |

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

## 五、API 接口

### 5.1 M8 标准接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查 |
| `/m8/metrics` | GET | M8 标准性能指标 |
| `/m8/config` | GET | M8 标准配置查询 |

### 5.2 服务注册与管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/servers` | GET | 获取已注册 MCP 服务列表 |
| `/api/v1/servers/{id}` | GET | 获取服务详情 |
| `/api/v1/servers` | POST | 注册新的 MCP 服务 |
| `/api/v1/servers/{id}` | PUT | 更新服务信息 |
| `/api/v1/servers/{id}` | DELETE | 注销 MCP 服务 |
| `/api/v1/servers/{id}/heartbeat` | POST | 服务心跳上报 |
| `/api/v1/servers/{id}/tools/refresh` | POST | 刷新服务工具列表 |

### 5.3 工具查询与调用

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/tools` | GET | 获取所有可用工具列表 |
| `/api/v1/tools/{tool_name}` | GET | 获取工具详情 |
| `/api/v1/tools/{tool_name}/call` | POST | 调用指定工具 |
| `/api/v1/tools/categories` | GET | 工具分类列表 |

### 5.4 调用记录与审计

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/calls` | GET | 获取调用历史记录 |
| `/api/v1/calls/{id}` | GET | 获取单次调用详情 |

### 5.5 管理 API

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/admin/api-keys` | GET | 获取 API Key 列表 |
| `/api/v1/admin/api-keys` | POST | 创建新的 API Key |
| `/api/v1/admin/api-keys/{id}` | DELETE | 撤销 API Key |
| `/api/v1/admin/metrics` | GET | 总线运营指标 |
| `/api/v1/admin/audit-logs` | GET | 审计日志查询 |

### 5.6 MCP 协议端点

| 接口 | 方法 | 说明 |
|------|------|------|
| `/mcp` | POST | MCP JSON-RPC 2.0 统一入口 |
| `/mcp/sse` | GET | MCP SSE 连接端点 |
| `/mcp/sse/{session_id}` | POST | MCP SSE 消息发送端点 |
| `/mcp/tools/list` | POST | MCP tools/list 方法（REST 风格） |
| `/mcp/tools/call` | POST | MCP tools/call 方法（REST 风格） |

---

## 六、数据模型

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
| key_hash | String | 密钥哈希（SHA-256） |
| name | String | 密钥名称 |
| permissions | JSON | 权限列表 |
| rate_limit | Integer | 限流阈值（次/分钟） |
| created_at | DateTime | 创建时间 |
| expires_at | DateTime | 过期时间 |
| last_used_at | DateTime | 最后使用时间 |

### 审计日志 (AuditLog)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| event_type | String | 事件类型 |
| actor | String | 操作主体 |
| action | String | 操作动作 |
| resource | String | 操作资源 |
| metadata | JSON | 附加元数据 |
| description | Text | 事件描述 |
| ip_address | String | IP 地址 |
| created_at | DateTime | 创建时间 |

---

## 七、架构设计

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
│                      │   传输抽象层       │                     │
│                      │  (HTTP/SSE/stdio)  │                     │
│                      └─────────┬─────────┘                     │
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

## 八、与其他模块关系

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

---

## 九、开发指南

### 运行测试

```bash
# 运行所有测试
pytest tests/

# 运行 Protocol 层测试
pytest tests/test_protocol.py -v

# 运行 Transport 层测试
pytest tests/test_transport.py -v

# 生成覆盖率报告
pytest tests/ --cov=src --cov-report=html
```

### 代码规范

- 遵循 PEP 8 代码风格
- 使用类型注解（Type Hints）
- 文档字符串使用 Google 风格
- 新增功能需附带单元测试

### 扩展开发

- **添加新传输类型**：继承 `BaseTransport`，注册到 `TransportFactory`
- **添加新适配器**：继承 `BaseAdapter`，实现工具列表和调用方法
- **添加新安全检查**：在 `src/security/` 中扩展认证或权限逻辑

详细扩展指南请参考 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 十、版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.5.0 | 2026-07 | 架构重整：恢复 protocol/transport/security 三层架构，文档对齐 |
| v0.4.0 | 2026-06 | 新增 stdio 传输管理、SSE 连接管理、熔断器、结果缓存 |
| v0.3.0 | 2026-06 | 新增 API Key 鉴权、权限控制、速率限制、审计日志 |
| v0.2.0 | 2026-05 | 新增多适配器支持、服务注册中心、工具聚合 |
| v0.1.0 | 2026-05 | 初始版本：基础 MCP 总线功能 |
