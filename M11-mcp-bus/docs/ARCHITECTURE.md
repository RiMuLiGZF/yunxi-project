# M11 MCP Bus 架构文档

## 一、架构总览

M11 MCP 总线服务采用清晰的四层架构设计，自底向上分别为：

```
┌─────────────────────────────────────────────────────────────┐
│                    API 层 (FastAPI Routers)                  │
│  routers/  -  HTTP 端点、REST API、MCP 协议端点              │
├─────────────────────────────────────────────────────────────┤
│                    服务层 (Services)                         │
│  services/  -  注册中心、路由转发、缓存、监控、审计、限流     │
├─────────────────────────────────────────────────────────────┤
│                    安全层 (Security)                         │
│  security/  -  认证、权限、审计日志                          │
├─────────────────────────────────────────────────────────────┤
│                    传输层 (Transport)                        │
│  transport/ -  HTTP、SSE、stdio 传输抽象                     │
├─────────────────────────────────────────────────────────────┤
│                    协议层 (Protocol)                         │
│  protocol/  -  JSON-RPC 2.0 协议解析                        │
└─────────────────────────────────────────────────────────────┘
```

### 设计原则

1. **分层清晰**：各层职责明确，层间通过定义良好的接口交互
2. **单向依赖**：上层依赖下层，下层不依赖上层
3. **可替换性**：各层实现可独立替换，不影响其他层
4. **向后兼容**：新架构逐步引入，旧代码可继续运行

---

## 二、各层职责说明

### 2.1 Protocol 协议层 (`src/protocol/`)

**职责**：负责 JSON-RPC 2.0 协议的编解码，是整个系统的最底层。

**核心模块**：

| 模块 | 说明 |
|------|------|
| `jsonrpc.py` | JSON-RPC 2.0 协议解析器，包含请求/响应/错误模型、解析函数、构建函数 |
| `types.py` | 协议相关的类型定义、常量、标准错误码 |

**功能特性**：
- 完整的 JSON-RPC 2.0 规范实现
- 支持批量请求（Batch Request）
- 支持通知（Notification，无 id 的请求）
- 标准错误码：-32700 Parse Error, -32600 Invalid Request, -32601 Method Not Found, -32602 Invalid Params, -32603 Internal Error
- Pydantic 模型验证
- 纯逻辑层，不依赖任何传输或 Web 框架

**使用示例**：
```python
from src.protocol import parse_request, build_response, build_error

# 解析请求
request = parse_request(raw_json)

# 构建成功响应
response = build_response(request_id=1, result={"tools": []})

# 构建错误响应
error_resp = build_error(request_id=1, code=-32601, message="Method not found")
```

### 2.2 Transport 传输层 (`src/transport/`)

**职责**：负责具体的网络/进程通信，将 Protocol 层的消息对象传递到远端并接收响应。

**核心模块**：

| 模块 | 说明 |
|------|------|
| `base.py` | 传输层抽象基类 `BaseTransport`，定义统一接口和事件回调 |
| `http_transport.py` | HTTP 传输实现（请求-响应模式） |
| `sse_transport.py` | SSE 传输实现（长连接，支持服务器推送） |
| `stdio_transport.py` | stdio 传输实现（子进程管道通信） |
| `factory.py` | 传输工厂 `TransportFactory`，根据配置创建传输实例 |

**统一接口**：
- `connect()` / `disconnect()`：连接管理
- `send(message)`：发送消息
- `receive(timeout)`：接收消息
- `request(message, timeout)`：请求-响应模式
- `is_connected()`：连接状态检查

**事件回调**：
- `on_message`：收到消息时触发
- `on_connect`：连接建立时触发
- `on_disconnect`：连接断开时触发
- `on_error`：发生错误时触发

**使用示例**：
```python
from src.transport import create_transport

# 使用工厂创建传输实例
transport = create_transport("http", {
    "endpoint": "http://localhost:8000/mcp",
    "api_key": "my-key",
})

# 连接并发送请求
await transport.connect()
response = await transport.request({
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 1,
})
await transport.disconnect()
```

### 2.3 Security 安全层 (`src/security/`)

**职责**：提供认证、授权、审计三大安全功能，不依赖任何 Web 框架。

**核心模块**：

| 模块 | 说明 |
|------|------|
| `auth.py` | API Key 认证核心逻辑，密钥验证、速率限制 |
| `permission.py` | 权限检查服务，支持通配符匹配、RBAC 简化版 |
| `audit.py` | 审计日志服务，事件记录与查询 |

**与 middleware 的关系**：
- `middleware/auth.py` 是薄适配层，负责 FastAPI 依赖注入
- `security/auth.py` 是核心逻辑层，可在任意场景中复用
- 认证流程：middleware 提取请求头 → 调用 security 核心逻辑 → 返回结果

**权限格式**：
```
资源:操作          如 "servers:read", "tools:call"
资源:子资源:操作   如 "admin:apikeys:write"
*                 超级权限
资源:*            资源通配符，如 "admin:*"
```

**使用示例**：
```python
from src.security import get_auth_service, get_permission_checker

# 认证
auth_service = get_auth_service()
result = auth_service.authenticate_full(path="/api/v1/tools", key_value="api-key-xxx")

# 权限检查
checker = get_permission_checker()
if checker.has_permission(api_key, "tools:call"):
    # 允许操作
    pass
```

### 2.4 Services 服务层 (`src/services/`)

**职责**：业务逻辑层，提供核心业务功能。

**核心服务**：

| 服务 | 说明 |
|------|------|
| `registry.py` | 服务注册中心，管理 MCP 服务的注册、发现、心跳 |
| `router.py` | 请求路由转发器，根据工具名路由到对应服务 |
| `cache.py` | 缓存服务，工具列表和结果缓存 |
| `monitor.py` | 监控服务，调用记录、统计指标 |
| `audit.py` | 审计日志（业务层封装，核心逻辑在 security/audit.py） |
| `rate_limiter.py` | 速率限制服务 |
| `sse_manager.py` | SSE 连接管理器（服务端） |
| `stdio_manager.py` | stdio 服务管理器（服务端） |
| `health_checker.py` | 健康检查服务 |
| `redis_client.py` | Redis 客户端封装 |
| `mcp_block_executor.py` | MCP 阻塞执行器 |
| `scheduler.py` | 定时任务调度器 |
| `m7_sync.py` | M7 同步服务 |
| `alert.py` | 告警服务 |

> 注意：`services/audit.py` 为业务层封装，核心审计逻辑已下沉到 `security/audit.py`。

### 2.5 API 层 (`src/routers/`)

**职责**：HTTP 端点层，负责接收外部请求并返回响应。

| 路由模块 | 说明 |
|----------|------|
| `mcp.py` | MCP 协议端点（JSON-RPC + SSE） |
| `admin.py` | 管理 API（服务管理、API Key 管理） |
| `health.py` | 健康检查端点 |
| `monitor.py` | 监控指标端点 |
| `console.py` | 控制台端点 |

---

## 三、扩展指南

### 3.1 添加新的传输类型

1. 在 `src/transport/` 下创建新文件，如 `websocket_transport.py`
2. 继承 `BaseTransport` 抽象基类
3. 实现所有抽象方法：`connect()`, `disconnect()`, `send()`, `receive()`
4. 在 `factory.py` 中注册新传输类型

```python
from src.transport import BaseTransport, TransportFactory

class WebSocketTransport(BaseTransport):
    def __init__(self, ws_url: str):
        super().__init__(transport_type="websocket", endpoint=ws_url)
        # 初始化...

    async def connect(self):
        # 实现连接逻辑
        self._set_state(TransportState.CONNECTED)
        await self._emit_connect()

    # ... 实现其他方法

# 注册到工厂
factory = TransportFactory()
factory.register_transport("websocket", WebSocketTransport)
```

### 3.2 添加新的适配器

适配器位于 `src/adapters/`，用于对接外部系统。

1. 继承 `BaseAdapter` 基类
2. 实现 `list_tools()`, `call_tool()` 等方法
3. 在适配器注册中心中注册

### 3.3 添加新的工具提供方

1. 实现 MCP 协议的服务端（HTTP/SSE/stdio 任意方式）
2. 通过 M11 管理 API 注册服务
3. 服务自动出现在工具聚合列表中

### 3.4 添加新的安全检查

在 `src/security/` 中扩展：
- 新增认证方式：在 `auth.py` 中添加新的认证方法
- 新增权限类型：在 `permission.py` 中添加新的权限常量和检查方法
- 新增审计事件：在 `audit.py` 中添加新的事件类型和便捷方法

---

## 四、协议规范

### 4.1 JSON-RPC 2.0

M11 使用 JSON-RPC 2.0 作为 MCP 协议的底层协议。

**请求格式**：
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "tool_name",
    "arguments": { "arg1": "value1" }
  },
  "id": 1
}
```

**成功响应格式**：
```json
{
  "jsonrpc": "2.0",
  "result": {
    "content": [
      { "type": "text", "text": "result text" }
    ]
  },
  "id": 1
}
```

**错误响应格式**：
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32601,
    "message": "Method not found"
  },
  "id": 1
}
```

### 4.2 标准错误码

| 错误码 | 含义 |
|--------|------|
| -32700 | Parse Error - JSON 解析错误 |
| -32600 | Invalid Request - 请求格式无效 |
| -32601 | Method Not Found - 方法不存在 |
| -32602 | Invalid Params - 参数无效 |
| -32603 | Internal Error - 服务器内部错误 |
| -32000 ~ -32099 | Server Error - 服务器自定义错误 |

### 4.3 MCP 标准方法

| 方法 | 说明 |
|------|------|
| `initialize` | 初始化握手 |
| `notifications/initialized` | 初始化完成通知 |
| `tools/list` | 获取工具列表 |
| `tools/call` | 调用工具 |
| `resources/list` | 获取资源列表 |
| `resources/read` | 读取资源内容 |
| `prompts/list` | 获取提示词列表 |
| `prompts/get` | 获取提示词详情 |

---

## 五、安全模型

### 5.1 认证方式

M11 支持 API Key 认证，提供两种传递方式：
1. `X-API-Key` 请求头
2. `Authorization: Bearer <key>` 请求头

API Key 使用 SHA-256 哈希存储，不保存明文。

### 5.2 权限模型

采用基于资源的权限控制（RBAC 简化版）：
- 权限格式：`资源:操作` 或 `资源:子资源:操作`
- 支持通配符匹配（如 `admin:*` 匹配所有 admin 权限）
- 超级权限 `*` 拥有所有权限
- 每个 API Key 可配置多个权限

**内置权限**：
- `servers:read` / `servers:write` - 服务器读写
- `tools:read` / `tools:call` - 工具查询和调用
- `mcp:read` / `mcp:call` - MCP 协议访问
- `admin:apikeys` - API Key 管理
- `audit:read` - 审计日志查看
- `*` - 超级权限

### 5.3 速率限制

- 基于 API Key 的速率限制
- 默认窗口：60 秒
- 限制阈值可配置（创建 API Key 时指定）
- 超出限制返回 429 Too Many Requests

### 5.4 审计日志

所有关键操作均记录审计日志：
- 服务注册/删除
- 工具调用（成功/失败）
- API Key 创建/删除
- 认证成功/失败
- 权限拒绝
- 限流触发
- 配置变更

审计日志持久化到数据库，不可修改、不可删除。

### 5.5 生产环境安全要求

- 必须启用 API Key 鉴权
- 禁止使用默认开发密钥
- 必须配置管理员 Token
- API Key 最小长度 16 字符
- 建议使用 HTTPS 传输

---

## 六、数据流图

### 6.1 工具调用数据流

```
客户端请求
    │
    ▼
┌──────────┐
│  Routers │  接收 HTTP 请求
└────┬─────┘
     │
     ▼
┌──────────┐
│ Security │  认证 + 权限检查 + 审计
└────┬─────┘
     │
     ▼
┌──────────┐
│ Services │  路由转发 + 缓存 + 监控
│ (Router) │
└────┬─────┘
     │
     ▼
┌──────────┐
│Transport │  选择传输方式（HTTP/SSE/stdio）
└────┬─────┘
     │
     ▼
┌──────────┐
│ Protocol │  JSON-RPC 编解码
└────┬─────┘
     │
     ▼
  目标 MCP 服务
```

### 6.2 服务注册数据流

```
MCP 服务
   │
   ▼ POST /api/v1/servers
┌──────────┐
│  Routers │
└────┬─────┘
     │
     ▼
┌──────────┐
│ Security │  认证 + 权限检查
└────┬─────┘
     │
     ▼
┌──────────┐
│ Registry │  保存服务信息到数据库
└────┬─────┘
     │
     ▼
┌──────────┐
│  Audit   │  记录审计日志
└──────────┘
```

---

## 七、版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.5.0 | 2026-07 | 架构重整：恢复 protocol/transport/security 三层架构，文档对齐 |
| v0.2.0 | 2026-06 | 功能增强：SSE 传输、stdio 管理、熔断器、缓存 |
| v0.1.0 | 2026-05 | 初始版本：基础 MCP 总线功能 |
