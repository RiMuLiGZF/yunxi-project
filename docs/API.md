# 云汐系统 API 文档

> **版本**：v1.0（第四阶段 · 生产就绪）
> **更新时间**：2026-07-17
> **文档类型**：API 参考手册 · 适用范围：全系统

---

## 目录

- [1. API 设计规范](#1-api-设计规范)
- [2. 认证方式](#2-认证方式)
- [3. 统一响应格式](#3-统一响应格式)
- [4. 错误码规范](#4-错误码规范)
- [5. 网关路由规则](#5-网关路由规则)
- [6. 限流规则](#6-限流规则)
- [7. M8 控制塔 API](#7-m8-控制塔-api)
- [8. 各模块核心 API](#8-各模块核心-api)
- [9. M8 标准接口规范](#9-m8-标准接口规范)
- [10. 示例请求/响应](#10-示例请求响应)
- [11. WebSocket / SSE 接口](#11-websocket--sse-接口)
- [12. 版本策略](#12-版本策略)

---

## 1. API 设计规范

### 1.1 基础规范

| 项目 | 规范 |
|------|------|
| **协议** | HTTP/HTTPS + RESTful |
| **数据格式** | JSON（UTF-8 编码） |
| **认证方式** | JWT Token (Bearer) / API Key / Module Token |
| **API 版本** | URL 路径版本化（`/api/v1/`） |
| **请求方法** | GET（查询）/ POST（创建/操作）/ PUT（更新）/ DELETE（删除） |

### 1.2 URL 命名规范

- 使用小写字母和连字符（kebab-case）
- 资源名称使用复数形式
- 层级关系通过路径体现

```
# 正确
GET  /api/v1/users
POST /api/v1/workflows
GET  /api/v1/modules/{module_id}/health

# 错误
GET  /api/v1/getUser
POST /api/v1/createWorkflow
```

### 1.3 请求规范

- GET 请求参数通过 Query String 传递
- POST/PUT 请求体使用 JSON 格式
- 分页参数：`page`（页码，从 1 开始）、`page_size`（每页数量）
- 排序参数：`sort_by`（排序字段）、`sort_order`（asc/desc）

### 1.4 响应头规范

| 响应头 | 说明 |
|--------|------|
| `Content-Type` | `application/json; charset=utf-8` |
| `X-Request-ID` | 请求追踪 ID |
| `X-RateLimit-Limit` | 限流配额 |
| `X-RateLimit-Remaining` | 剩余配额 |
| `X-RateLimit-Reset` | 配额重置时间 |

---

## 2. 认证方式

云汐系统采用三层认证体系，不同场景使用不同认证方式。

### 2.1 JWT Token（用户认证）

**适用场景**：用户登录、前端页面、用户相关操作

```http
Authorization: Bearer <jwt_token>
```

**Token 说明**：
- 访问令牌有效期：2 小时
- 刷新令牌有效期：7 天
- 算法：HS256
- 支持主动注销（Redis 黑名单）

**登录获取 Token**：
```bash
curl -X POST http://localhost:8008/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_password"}'
```

### 2.2 API Key（服务间调用）

**适用场景**：服务间调用、脚本、第三方集成

```http
X-API-Key: <api_key>
```

**API Key 说明**：
- 生成时显示完整密钥，之后仅存储 SHA256 哈希
- 支持设置过期时间和权限范围
- 支持按 API Key 独立限流

### 2.3 Module Token（M8 纳管）

**适用场景**：模块向 M8 注册、健康检查上报、模块间纳管调用

```http
X-Module-Token: <module_token>
```

**Module Token 说明**：
- 每个模块有独立的 Module Token
- 仅用于 M8 标准接口的认证
- 可配置独立的权限范围

### 2.4 公开路径

以下路径无需认证即可访问：

| 路径 | 说明 |
|------|------|
| `/health` | 健康检查 |
| `/m8/health` | M8 标准健康检查 |
| `/docs` | Swagger API 文档 |
| `/openapi.json` | OpenAPI 规范 |
| `/api/v1/auth/login` | 登录接口 |

---

## 3. 统一响应格式

所有 API 响应采用统一的 JSON 格式。

### 3.1 成功响应

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "name": "example"
  },
  "trace_id": "a1b2c3d4e5f6"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | number | 是 | 状态码，0 表示成功 |
| `message` | string | 是 | 状态描述 |
| `data` | any | 是 | 响应数据 |
| `trace_id` | string | 否 | 请求追踪 ID，用于问题排查 |

### 3.2 错误响应

```json
{
  "code": 80101,
  "message": "模块不存在",
  "details": {
    "module_key": "m99"
  },
  "trace_id": "a1b2c3d4e5f6"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | number | 是 | 错误码（6 位） |
| `message` | string | 是 | 错误描述（面向用户的友好信息） |
| `details` | object | 否 | 错误详情（面向开发者的详细信息） |
| `trace_id` | string | 否 | 请求追踪 ID |

### 3.3 分页响应

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {"id": 1, "name": "item1"},
      {"id": 2, "name": "item2"}
    ],
    "total": 100,
    "page": 1,
    "page_size": 20,
    "total_pages": 5
  },
  "trace_id": "..."
}
```

---

## 4. 错误码规范

### 4.1 错误码格式

6 位数字错误码，格式为 `XX YY ZZ`：

```
XX YY ZZ
│  │  │
│  │  └── 具体错误序号（00-99）
│  └───── 错误类别（01-09）
└──────── 模块编号（00-12）
```

### 4.2 模块编号

| 编号 | 模块 | 错误码范围 |
|------|------|-----------|
| 00 | 系统通用 | 000000 - 000999 |
| 01 | M1 Agent集群 | 010100 - 010999 |
| 02 | M2 技能集群 | 020100 - 020999 |
| 03 | M3 端云协同 | 030100 - 030999 |
| 04 | M4 场景引擎 | 040100 - 040999 |
| 05 | M5 潮汐记忆 | 050100 - 050999 |
| 06 | M6 硬件外设 | 060100 - 060999 |
| 07 | M7 积木平台 | 070100 - 070999 |
| 08 | M8 控制塔 | 080100 - 080999 |
| 09 | M9 开发工坊 | 090100 - 090999 |
| 10 | M10 系统卫士 | 100100 - 100999 |
| 11 | M11 MCP总线 | 110100 - 110999 |
| 12 | M12 安全盾 | 120100 - 120999 |

### 4.3 错误类别

| 类别码 | 名称 | HTTP 状态码 | 说明 |
|--------|------|-------------|------|
| 00 | 成功 | 200 | 操作成功 |
| 01 | 参数错误 | 400 | 输入参数格式不正确、缺少必填字段 |
| 02 | 认证错误 | 401 | 用户未认证、Token 无效或已过期 |
| 03 | 权限错误 | 403 | 用户已认证但无权访问 |
| 04 | 资源不存在 | 404 | 请求的资源不存在 |
| 05 | 业务错误 | 409 | 业务规则校验失败 |
| 06 | 系统错误 | 500 | 服务器内部异常 |
| 07 | 第三方错误 | 502 | 第三方或上游服务异常 |
| 08 | 限流错误 | 429 | 请求频率超限 |
| 09 | 数据错误 | 409 | 数据冲突、完整性校验失败 |

### 4.4 通用错误码

| 错误码 | 常量名 | HTTP 码 | 说明 |
|--------|--------|---------|------|
| 0 | `SUCCESS` | 200 | 操作成功 |
| 000101 | `VALIDATION_ERROR` | 400 | 通用参数验证失败 |
| 000102 | `PARAM_MISSING` | 400 | 缺少必填参数 |
| 000201 | `AUTH_FAILED` | 401 | 认证失败 |
| 000203 | `TOKEN_INVALID` | 401 | Token 无效 |
| 000204 | `TOKEN_EXPIRED` | 401 | Token 已过期 |
| 000301 | `PERMISSION_DENIED` | 403 | 无访问权限 |
| 000401 | `NOT_FOUND` | 404 | 资源不存在 |
| 000501 | `BUSINESS_ERROR` | 409 | 通用业务错误 |
| 000601 | `INTERNAL_ERROR` | 500 | 服务器内部错误 |
| 000602 | `SERVICE_UNAVAILABLE` | 503 | 服务暂不可用 |
| 000801 | `RATE_LIMITED` | 429 | 请求频率超限 |

> **完整错误码列表**：参见 [shared/core/ERROR_CODES.md](../shared/core/ERROR_CODES.md)

---

## 5. 网关路由规则

API 网关（端口 8080）是外部请求的统一入口，基于路径前缀路由到各模块。

### 5.1 路由表

| 前缀 | 目标模块 | 目标地址 | 说明 |
|------|---------|---------|------|
| `/m0` | M0 主理人管控台 | `http://localhost:8000` | 最高权限管控台 |
| `/m1` | M1 Agent集群 | `http://localhost:8001` | 多Agent调度 |
| `/m2` | M2 技能集群 | `http://localhost:8002` | 技能服务 |
| `/m3` | M3 端云协同 | `http://localhost:8003` | 端云同步 |
| `/m4` | M4 场景引擎 | `http://localhost:8004` | 场景编排 |
| `/m5` | M5 潮汐记忆 | `http://localhost:8005` | 记忆系统 |
| `/m6` | M6 硬件外设 | `http://localhost:8006` | 硬件接口 |
| `/m7` | M7 积木平台 | `http://localhost:8007` | 工作流构建 |
| `/m8` | M8 控制塔 | `http://localhost:8008` | 管理后台 |
| `/m9` | M9 开发工坊 | `http://localhost:8009` | 代码生成 |
| `/m10` | M10 系统卫士 | `http://localhost:8010` | 系统监控 |
| `/m11` | M11 MCP总线 | `http://localhost:8011` | MCP 服务 |
| `/m12` | M12 安全盾 | `http://localhost:8012` | 安全防护 |

### 5.2 网关处理流程

```
客户端请求
    ↓
[CORS 中间件]
    ↓
[WAF 检测] ──拦截──▶ 403 Forbidden
    ↓
[速率限制] ──超限──▶ 429 Too Many Requests
    ↓
[认证中间件] ──失败──▶ 401 Unauthorized
    ↓
[路由匹配] ──未找到──▶ 404 Not Found
    ↓
[熔断器] ──熔断──▶ 503 Service Unavailable
    ↓
[代理转发] → 目标模块服务
    ↓
响应返回
```

### 5.3 调用示例

通过网关调用 M8 控制塔 API：

```bash
curl http://localhost:8080/m8/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "xxx"}'
```

通过网关调用 M11 MCP 工具列表：

```bash
curl http://localhost:8080/m11/api/v1/tools \
  -H "X-API-Key: your-api-key"
```

---

## 6. 限流规则

### 6.1 限流层级

| 层级 | 算法 | 默认限制 | 说明 |
|------|------|---------|------|
| 全局限流 | 令牌桶 | 600 请求/分钟 | 所有请求的总限制 |
| IP 级限流 | 令牌桶 | 100 请求/分钟 | 单 IP 地址限制 |
| API Key 限流 | 令牌桶 | 可配置 | 按 API Key 独立限流 |
| 用户级限流 | 令牌桶 | 预留 | 按用户 ID 限流 |
| 接口级限流 | 令牌桶 | 分级限制 | 不同接口不同级别 |

### 6.2 接口限流分级

| 级别 | 每分钟请求 | 每小时请求 | 适用场景 |
|------|-----------|-----------|----------|
| public | 100 | 2000 | 公开接口（默认） |
| sensitive | 10 | 100 | 登录、注册、验证码 |
| strict | 5 | 20 | 密码重置、API Key 管理 |
| admin | 30 | 500 | 管理后台接口 |
| mcp | 60 | 1000 | MCP 工具调用 |

### 6.3 渐进式封禁

连续超限时，封禁时间逐步延长：

| 超限次数 | 封禁时长 |
|---------|---------|
| 1-3 次 | 仅警告，不封禁 |
| 4-6 次 | 封禁 5 分钟 |
| 7-10 次 | 封禁 30 分钟 |
| 11+ 次 | 封禁 24 小时 |

### 6.4 典型接口限流

| 接口 | 限流级别 | 限制 | 说明 |
|------|---------|------|------|
| 登录接口 | sensitive | 10 次/分钟 | 防止暴力破解 |
| 聊天接口 | - | 60 次/分钟 | 防止滥用 |
| 算力调度 | - | 30 次/分钟 | 保护算力资源 |
| 文件上传 | - | 20 次/分钟 | 防止资源耗尽 |
| 通用接口 | public | 100 次/分钟 | 默认限流 |

---

## 7. M8 控制塔 API

M8 控制塔是系统的核心管理中枢，Base URL: `http://localhost:8008/api/v1`

### 7.1 认证接口

| 方法 | 路径 | 说明 | 限流级别 |
|------|------|------|---------|
| POST | `/auth/login` | 用户登录 | sensitive |
| POST | `/auth/logout` | 用户登出 | public |
| POST | `/auth/refresh` | 刷新 Token | public |
| POST | `/auth/change-password` | 修改密码 | strict |
| GET | `/auth/me` | 获取当前用户信息 | - |

### 7.2 聊天接口

| 方法 | 路径 | 说明 | 限流 |
|------|------|------|------|
| POST | `/chat/send` | 发送消息（SSE流式） | 60次/分钟 |
| GET | `/chat/history` | 获取聊天历史 | - |
| GET | `/chat/sessions` | 获取会话列表 | - |
| DELETE | `/chat/history/{id}` | 删除单条消息 | - |
| POST | `/chat/clear` | 清空当前会话 | - |

### 7.3 模块纳管接口

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/modules` | 获取所有模块列表 | admin |
| GET | `/modules/{module_id}` | 获取模块详情 | admin |
| GET | `/modules/{module_id}/health` | 模块健康检查 | admin |
| GET | `/modules/{module_id}/metrics` | 模块运行指标 | admin |
| POST | `/modules/{module_id}/restart` | 重启模块 | admin |
| POST | `/modules/proxy/{module_id}/{path:path}` | 模块代理调用 | admin |

### 7.4 算力调度接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/compute/sources` | 算力源列表 |
| POST | `/compute/sources` | 新增算力源 |
| PUT | `/compute/sources/{id}` | 编辑算力源 |
| DELETE | `/compute/sources/{id}` | 删除算力源 |
| GET | `/compute/groups` | 算力分组列表 |
| GET | `/compute/models` | 模型配置列表 |
| GET | `/compute/routing` | 路由策略列表 |
| GET | `/compute/monitor/stats` | 算力监控统计 |

### 7.5 记忆接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/memory/search` | 搜索记忆 |
| GET | `/memory/layers` | 记忆分层统计 |
| POST | `/memory/add` | 添加记忆 |
| DELETE | `/memory/{id}` | 删除记忆 |

### 7.6 知识库接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/brain/documents` | 文档列表 |
| POST | `/brain/upload` | 上传文档 |
| DELETE | `/brain/documents/{id}` | 删除文档 |
| GET | `/brain/search` | 知识库检索 |
| GET | `/brain/stats` | 知识库统计 |

### 7.7 成长中心接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/growth/overview` | 成长总览 |
| GET | `/growth/achievements` | 成就列表 |
| GET | `/growth/talent-tree` | 天赋树 |
| GET | `/growth/season` | 赛季旅程 |
| GET | `/growth/echoes` | 记忆回响 |

### 7.8 系统监控接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/monitor/realtime` | 实时系统指标 |
| GET | `/monitor/alerts` | 告警列表 |
| POST | `/monitor/alerts/{id}/ack` | 确认告警 |
| GET | `/monitor/module/{id}/detail` | 模块健康详情 |

### 7.9 自进化引擎接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/evolution/scan` | 健康扫描 |
| GET | `/evolution/plans` | 进化计划列表 |
| POST | `/evolution/plans` | 创建进化计划 |
| POST | `/evolution/deploy/{id}` | 部署进化方案 |
| POST | `/evolution/rollback/{id}` | 一键回滚 |
| GET | `/evolution/audit/{id}` | 安全审计报告 |

### 7.10 工作开发接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/work_dev/code/execute` | 执行代码 |
| GET | `/work_dev/projects` | 项目列表 |
| POST | `/work_dev/projects` | 创建项目 |
| GET | `/work_dev/vscode/status` | VSCode 状态 |
| POST | `/work_dev/vscode/start` | 启动 VSCode |

### 7.11 语音接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/voice/tts` | 文字转语音 |
| POST | `/voice/asr` | 语音转文字 |
| GET | `/voice/presets` | 音色预设列表 |
| POST | `/voice/presets` | 创建音色预设 |

---

## 8. 各模块核心 API

### 8.1 M1 Agent 集群调度（8001）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/agents` | Agent 列表 |
| POST | `/api/v1/agents/dispatch` | 任务分发 |
| GET | `/api/v1/agents/{id}/status` | Agent 状态 |
| GET | `/api/v1/agents/stream` | Agent 执行流（SSE） |
| GET | `/api/v1/federation/adapters` | 联邦适配器列表 |
| GET | `/api/v1/federation/stats` | 联邦调度统计 |
| GET | `/m8/health` | M8 健康检查 |
| GET | `/m8/metrics` | M8 指标 |

### 8.2 M2 技能集群（8002）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/skills` | 技能列表 |
| GET | `/api/v1/skills/{id}` | 技能详情 |
| POST | `/api/v1/skills/{id}/execute` | 执行技能 |
| GET | `/api/v1/skills/categories` | 技能分类 |
| GET | `/api/v1/market` | 技能市场列表 |
| POST | `/api/v1/market/install/{id}` | 安装技能 |
| GET | `/m8/health` | M8 健康检查 |

### 8.3 M3 端云协同内核（8003）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/route` | 路由任务到端/云 |
| GET | `/api/v1/nodes` | 节点列表 |
| GET | `/api/v1/stats` | 调度统计 |
| GET | `/api/v1/network/status` | 网络状态 |
| POST | `/api/v1/sync/trigger` | 触发同步 |
| GET | `/m8/health` | M8 健康检查 |

### 8.4 M4 场景引擎（8004）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/scenes` | 场景列表 |
| POST | `/api/v1/scenes/switch` | 切换场景 |
| GET | `/api/v1/scenes/current` | 当前场景 |
| GET | `/api/v1/scenes/{id}/config` | 场景配置 |
| PUT | `/api/v1/scenes/{id}/config` | 更新场景配置 |
| GET | `/m8/health` | M8 健康检查 |

### 8.5 M5 潮汐记忆（8005）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/memory/store` | 存储记忆 |
| GET | `/api/v1/memory/search` | 搜索记忆 |
| GET | `/api/v1/memory/layers` | 分层统计 |
| POST | `/api/v1/memory/consolidate` | 记忆巩固 |
| DELETE | `/api/v1/memory/{id}` | 删除记忆 |
| GET | `/api/v1/memory/{id}` | 记忆详情 |
| GET | `/m8/health` | M8 健康检查 |

### 8.6 M6 硬件外设（8006）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/devices` | 设备列表 |
| GET | `/api/v1/devices/{id}` | 设备详情 |
| GET | `/api/v1/devices/{id}/data` | 设备数据 |
| POST | `/api/v1/devices/{id}/control` | 设备控制 |
| GET | `/api/v1/devices/stream` | SSE 数据推送 |
| GET | `/m8/health` | M8 健康检查 |

### 8.7 M7 积木编排平台（8007）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/workflows` | 工作流列表 |
| POST | `/api/v1/workflows` | 创建工作流 |
| GET | `/api/v1/workflows/{id}` | 工作流详情 |
| PUT | `/api/v1/workflows/{id}` | 更新工作流 |
| DELETE | `/api/v1/workflows/{id}` | 删除工作流 |
| POST | `/api/v1/workflows/{id}/execute` | 执行工作流 |
| GET | `/api/v1/workflows/{id}/runs` | 执行历史 |
| GET | `/api/v1/templates` | 模板市场列表 |
| GET | `/m8/health` | M8 健康检查 |

### 8.8 M9 开发者工坊（8009）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/vscode/status` | VSCode 状态 |
| POST | `/api/v1/vscode/start` | 启动 VSCode |
| POST | `/api/v1/code/execute` | 执行代码 |
| GET | `/api/v1/workspace/projects` | 项目列表 |
| POST | `/api/v1/workspace/projects` | 创建项目 |
| GET | `/api/v1/mcp/tools` | MCP 工具列表 |
| POST | `/api/v1/mcp/call` | 调用 MCP 工具 |
| GET | `/api/v1/dashboard/overview` | 仪表盘概览 |
| GET | `/m8/health` | M8 深度健康检查 |
| GET | `/m8/metrics` | M8 指标 |
| POST | `/m8/config/reload` | 配置热重载 |

### 8.9 M10 系统卫士（8010）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/system/resources` | 系统资源 |
| GET | `/api/v1/processes` | 进程列表 |
| POST | `/api/v1/processes/{pid}/kill` | 终止进程 |
| GET | `/api/v1/alerts/thresholds` | 阈值配置 |
| PUT | `/api/v1/alerts/thresholds` | 更新阈值 |
| GET | `/api/v1/gpu/stats` | GPU 状态 |
| GET | `/m8/health` | M8 健康检查 |

### 8.10 M11 MCP 总线（8011）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/services` | MCP 服务列表 |
| POST | `/api/v1/services/register` | 注册服务 |
| DELETE | `/api/v1/services/{id}` | 注销服务 |
| GET | `/api/v1/tools` | 全部工具列表 |
| POST | `/api/v1/tools/call` | 调用工具 |
| GET | `/api/v1/keys` | API Key 列表 |
| POST | `/api/v1/keys` | 创建 API Key |
| GET | `/m8/health` | M8 健康检查 |

### 8.11 M12 安全盾（8012）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/waf/rules` | WAF 规则列表 |
| POST | `/api/v1/waf/rules` | 添加 WAF 规则 |
| GET | `/api/v1/waf/stats` | WAF 统计 |
| GET | `/api/v1/keys` | API 密钥列表 |
| POST | `/api/v1/keys` | 创建 API 密钥 |
| GET | `/api/v1/ip/whitelist` | IP 白名单 |
| GET | `/api/v1/ip/blacklist` | IP 黑名单 |
| POST | `/api/v1/ip/whitelist` | 添加白名单 |
| POST | `/api/v1/ip/blacklist` | 添加黑名单 |
| GET | `/api/v1/audit/logs` | 安全审计日志 |
| GET | `/m8/health` | M8 健康检查 |

---

## 9. M8 标准接口规范

所有模块必须实现以下 M8 标准接口，用于 M8 控制塔纳管。

### 9.1 健康检查接口

```
GET /m8/health
```

**响应示例**：
```json
{
  "code": 0,
  "message": "healthy",
  "data": {
    "status": "healthy",
    "version": "v1.3.0",
    "uptime": 86400,
    "components": {
      "database": "healthy",
      "vscode": "healthy",
      "mcp": "degraded"
    }
  },
  "trace_id": "..."
}
```

**状态定义**：
- `healthy`：全部组件正常
- `degraded`：部分组件异常，核心功能可用
- `unhealthy`：核心功能异常，服务不可用

### 9.2 运行指标接口

```
GET /m8/metrics
```

**响应示例**：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "qps": 120,
    "avg_latency_ms": 45,
    "p99_latency_ms": 200,
    "error_rate": 0.01,
    "requests_total": 123456,
    "active_connections": 25
  }
}
```

### 9.3 配置查询接口

```
GET /m8/config
```

返回当前配置（脱敏处理，不返回敏感信息）。

### 9.4 配置热重载接口（可选）

```
POST /m8/config/reload
```

支持热重载的模块实现此接口，用于动态更新配置。

---

## 10. 示例请求/响应

### 10.1 用户登录

**请求**：
```bash
curl -X POST http://localhost:8008/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "MyStr0ngP@ssw0rd"
  }'
```

**响应**：
```json
{
  "code": 0,
  "message": "登录成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 7200,
    "user": {
      "id": 1,
      "username": "admin",
      "role": "admin"
    }
  },
  "trace_id": "a1b2c3d4"
}
```

### 10.2 发送聊天消息

**请求**：
```bash
curl -X POST http://localhost:8008/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{
    "message": "你好，介绍一下云汐系统",
    "session_id": "sess_abc123",
    "stream": true
  }'
```

**流式响应（SSE）**：
```
data: {"type": "thinking", "content": "正在思考..."}

data: {"type": "token", "content": "云"}

data: {"type": "token", "content": "汐"}

data: {"type": "token", "content": "是"}

data: {"type": "done", "content": "云汐是一套AI原生个人操作系统..."}
```

### 10.3 获取模块列表

**请求**：
```bash
curl http://localhost:8008/api/v1/modules \
  -H "Authorization: Bearer <access_token>"
```

**响应**：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "key": "m1",
        "name": "多Agent集群调度",
        "port": 8001,
        "status": "running",
        "health": "healthy",
        "version": "v11.1.0"
      },
      {
        "key": "m8",
        "name": "管理控制塔",
        "port": 8008,
        "status": "running",
        "health": "healthy",
        "version": "v12.0.0"
      }
    ],
    "total": 13,
    "running": 12,
    "stopped": 1
  },
  "trace_id": "..."
}
```

### 10.4 调用 MCP 工具

**请求**：
```bash
curl -X POST http://localhost:8011/api/v1/tools/call \
  -H "Content-Type: application/json" \
  -H "X-API-Key: yunxi-mcp-dev-key" \
  -d '{
    "tool_name": "filesystem_read_file",
    "arguments": {
      "path": "/data/example.txt"
    }
  }'
```

**响应**：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "content": "文件内容...",
    "metadata": {
      "size": 1024,
      "modified": "2026-07-17T10:00:00Z"
    }
  },
  "trace_id": "..."
}
```

### 10.5 错误响应示例

**请求（参数错误）**：
```bash
curl -X POST http://localhost:8008/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": ""}'
```

**响应**：
```json
{
  "code": 101,
  "message": "参数验证失败",
  "details": {
    "errors": [
      {"field": "username", "message": "用户名不能为空"},
      {"field": "password", "message": "密码不能为空"}
    ],
    "error_count": 2
  },
  "trace_id": "a1b2c3d4"
}
```

---

## 11. WebSocket / SSE 接口

### 11.1 SSE 接口列表

| 模块 | 路径 | 说明 |
|------|------|------|
| M8 | `/api/v1/chat/stream` | 聊天消息流 |
| M1 | `/api/v1/agents/stream` | Agent 执行流 |
| M6 | `/api/v1/devices/stream` | 设备数据推送 |
| M7 | `/api/v1/workflows/{id}/stream` | 工作流执行流 |
| M10 | `/api/v1/monitor/stream` | 监控数据实时推送 |

### 11.2 SSE 使用示例

```javascript
// 前端 SSE 连接示例
const eventSource = new EventSource(
  'http://localhost:8008/api/v1/chat/stream?session_id=abc123',
  { withCredentials: true }
);

eventSource.addEventListener('message', (event) => {
  const data = JSON.parse(event.data);
  console.log('收到消息:', data);
});

eventSource.addEventListener('error', (error) => {
  console.error('连接错误:', error);
});
```

---

## 12. 版本策略

### 12.1 版本号规则

- API 版本通过 URL 路径标识（如 `/api/v1/`）
- 主版本号变更时，旧版本保留至少 3 个月过渡期
- 向后兼容的小版本迭代不增加版本号

### 12.2 兼容性原则

| 变更类型 | 是否增加版本号 | 说明 |
|---------|--------------|------|
| 新增接口 | 否 | 不影响现有接口 |
| 新增可选参数 | 否 | 不影响现有调用 |
| 新增响应字段 | 否 | 不影响现有解析 |
| 修改参数名 | 是 | 破坏性变更 |
| 删除接口 | 是 | 破坏性变更 |
| 修改响应结构 | 是 | 破坏性变更 |

### 12.3 弃用策略

1. 标记弃用：在文档和响应头中标注 `Deprecation`
2. 过渡期：至少保留 3 个月
3. 正式移除：新版本中移除旧接口

---

## 附录

### 相关文档

- [架构文档](ARCHITECTURE.md) — 系统架构与模块说明
- [运维手册](OPS.md) — 运维操作与故障排查
- [开发者指南](DEVELOPMENT.md) — 开发规范与最佳实践
- [错误码规范](../shared/core/ERROR_CODES.md) — 完整错误码列表
- [安全文档](SECURITY.md) — 安全架构与防护措施

---

**文档维护**：API 变更时必须同步更新本文档
**最后更新**：2026-07-17
**版本**：v1.0
