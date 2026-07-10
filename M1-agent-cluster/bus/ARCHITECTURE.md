# A2A通信总线子Agent（Bus-Agent）架构文档

## 一、职责定位

Bus-Agent 是云汐系统中所有Agent间通信的"中枢神经"，在底层 MessageBus 基础上提供面向Agent的消息路由、优先级发布、主题订阅及死信队列（DLQ）管理能力。它实现了 AgentTask 与 BusMessage 之间的双向格式转换，是Agent-to-Agent（A2A）通信的统一网关。

## 二、输入输出

### handle_task 支持的 intent

| intent | payload 关键字段 | 说明 |
|--------|-----------------|------|
| `bus.route` | `target`(str), `topic`(可选) | 路由消息到目标Agent |
| `bus.publish` | `topic`(str, 必填), `payload`(dict), `priority`(int, 可选) | 发布事件到指定主题 |
| `bus.subscribe` | `topic`(str, 必填), `subscriber_id`(str, 可选) | 订阅主题 |
| `bus.unsubscribe` | `subscription_id`(str, 必填) | 取消订阅 |
| `bus.queue_stats` | 无 | 查询队列统计 |
| `bus.dlq_stats` | 无 | 查询死信队列统计 |
| `bus.mcp_bridge` | `target_endpoint`(str), `mcp_method`(str), `a2a_task`(dict) | [v2.0-LINKAGE] A2A-MCP协议桥接，自动格式转换与错误码映射 |

### 公开API方法签名

```python
async def publish_event(topic: str, payload: dict[str, Any], priority: int = 5) -> str
async def subscribe_topic(topic: str, handler: Callable[[BusMessage], Awaitable[None]], subscriber_id: str = "anonymous") -> str
async def unsubscribe_topic_by_id(subscription_id: str) -> bool
def get_queue_stats() -> dict[str, Any]
def get_dlq_stats() -> dict[str, Any]
```

## 三、核心机制

**A2A消息格式转换** 是 Bus-Agent 的核心能力。`_task_to_bus_message` 将 AgentTask 转换为 BusMessage，保留原始 trace_id、priority、ttl 等元信息，并在 payload 中嵌入 `_a2a: True` 标记和 `intent`/`data` 字段；`_bus_message_to_task` 实现反向转换，将 BusMessage 还原为 AgentTask。这种双向转换确保了Agent间通信的透明性，类似 **Claude Code** 的工具调用消息封装模式。

**优先级路由** 通过 `route_message` 统一入口，先进行A2A格式转换，再通过底层 MessageBus 投递。MessageBus 支持优先级队列，优先级数值越小优先级越高。

**本地订阅缓存** 使用 `_local_subscriptions` 字典维护 subscription_id 到 (topic, subscriber_id) 的映射，确保 Agent 卸载时能批量取消所有订阅，避免资源泄漏。

**延迟初始化** MessageBus 实例在 `on_mount` 中通过 `MessageBus.get_instance()` 获取单例，而非构造时创建，适配了系统启动时的依赖注入顺序。

**涉密标记自动传递（x-security-classification）** [v2.0-LINKAGE] `_task_to_bus_message` 在转换时自动将 `task.security_classification` 写入 BusMessage。若目标Agent ID包含 `memory`、`m5` 等M5标识且原标记为 `INTERNAL`，自动升级为 `TOP_SECRET`（绝密），确保 M5（潮汐记忆）消息默认按最高涉密等级处理。反向转换 `_bus_message_to_task` 同步还原该字段。

## 四、协作关系

| 协作方 | 协作方式 | 说明 |
|--------|---------|------|
| 所有子Agent | 被调用方 | 所有子Agent通过Bus发布事件和路由消息，Bus-Agent是通信中枢 |
| MessageBus | 直接依赖 | 底层消息总线，提供发布/订阅/队列管理能力 |
| DeadLetterQueue | 直接依赖 | 死信队列，处理投递失败的消息 |

## 五、数据模型

| 类名 | 关键字段 | 说明 |
|------|---------|------|
| `BusMessage` | `msg_id`, `topic`, `sender`, `recipient`, `msg_type`, `payload`, `priority`, `ttl`, `trace_id` | 消息总线消息 |
| `AgentTask` | `task_id`, `trace_id`, `intent`, `payload`, `source`, `target`, `priority`, `ttl` | Agent任务对象 |
| `AgentResult` | `task_id`, `trace_id`, `agent_id`, `status`, `output`, `error`, `latency_ms` | Agent返回结果 |
| `BusHandler` | `Callable[[BusMessage], Awaitable[None]]` | 消息处理回调类型 |

## 六、测试覆盖

对应测试类 `TestBusAgent`，共 **2** 个测试用例：

- `test_agent_identity` — 验证 agent_id 正确性
- `test_health` — 验证健康检查返回正常状态

---

## 七、MCP 适配能力（A2A-MCP 协议桥接）

### 7.1 格式转换规则

Bus-Agent 提供 A2A 消息与 MCP（Model Context Protocol）JSON-RPC 2.0 消息之间的双向格式转换能力，使云汐系统能够通过统一总线对接外部 MCP 服务。

**A2A → MCP 转换规则：**

| A2A 字段 | MCP JSON-RPC 2.0 字段 | 转换说明 |
|---------|----------------------|---------|
| `task_id` | `id` | 直接映射，确保请求-响应对齐 |
| `intent` | `method` | A2A 的 intent 映射为 MCP 的 method 名称 |
| `payload` | `params` | A2A payload 整体嵌入 MCP params 对象 |
| `trace_id` | `meta.trace_id` | 放入 MCP 扩展元信息字段，保持链路追踪 |
| `sender` | `meta.sender` | 放入 MCP 扩展元信息字段 |
| `priority` | `meta.priority` | 放入 MCP 扩展元信息字段，供 MCP 服务端参考 |
| `ttl` | `meta.ttl` | 放入 MCP 扩展元信息字段，超时控制依据 |

**MCP → A2A 转换规则：**

| MCP JSON-RPC 2.0 字段 | A2A 字段 | 转换说明 |
|----------------------|---------|---------|
| `id` | `task_id` / `correlation_id` | 直接映射，correlation_id 用于异步关联 |
| `method` | `intent` | MCP method 映射为 A2A intent |
| `params` | `payload` | MCP params 整体提取为 A2A payload |
| `result` | `payload.result` | 成功响应结果放入 A2A payload |
| `error` | `payload.error` | 错误响应放入 A2A payload.error |
| `meta.*` | 对应 A2A 元字段 | MCP 扩展元信息反向映射 |

### 7.2 错误码映射表

| A2A 错误码 | MCP 错误码 | 含义 | 处理策略 |
|-----------|-----------|------|---------|
| `A2A_TIMEOUT` | `-32000` (Server error) | A2A 消息超时未响应 | Bus-Agent 触发重试，最多3次，指数退避 |
| `A2A_AGENT_NOT_FOUND` | `-32602` (Invalid params) | 目标 Agent 不存在 | 返回原始调用方，建议重新发现 |
| `A2A_INVALID_INTENT` | `-32601` (Method not found) | intent 无法映射到 MCP method | 返回调用方，提示检查 intent 名称 |
| `A2A_UNAUTHORIZED` | `-32001` (Server error) | 安全认证失败 | 路由至 Security-Agent，触发审计 |
| `A2A_PAYLOAD_TOO_LARGE` | `-32600` (Invalid Request) | payload 超过单消息上限 | 拒绝投递，建议拆分或压缩 |
| `A2A_CIRCUIT_OPEN` | `-32002` (Server error) | 熔断器开启，服务不可用 | 返回降级方案或排队等待 |
| `MCP_TRANSPORT_ERROR` | `-32003` (Server error) | MCP 底层传输异常 | Bus-Agent 记录日志，尝试备用传输通道 |

### 7.3 超时策略

Bus-Agent 对 MCP 适配链路实施分级超时控制：

| 场景 | 超时时间 | 说明 |
|------|---------|------|
| A2A → MCP 同步调用 | 30s | 单次请求从发送到接收 MCP 响应的总超时 |
| MCP → A2A 异步回调 | 60s | MCP 服务端异步回调的最大等待时间 |
| 连接建立 | 10s | 与 MCP 服务端建立传输连接的超时 |
| 重试间隔 | 指数退避（1s / 2s / 4s） | 失败重试时的退避策略，最多3次 |
| 全局熔断观察窗口 | 60s | 60秒内错误率超过50%触发 MCP 链路熔断 |

### 7.4 职责边界

MCP 适配仅由 Bus-Agent 负责实现，其他子Agent不直接感知 MCP 协议细节。Orchestrator-Agent 通过标准 A2A intent 发起调用，Bus-Agent 在路由时根据目标 endpoint 类型自动选择原生 A2A 传输或 MCP 桥接传输。
