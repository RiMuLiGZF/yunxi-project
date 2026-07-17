# 云汐系统统一错误码体系

> 版本：v1.0.0
> 生效日期：2026-07-17
> 状态：第二阶段统一治理 - 试点中

## 目录

1. [错误码规范](#1-错误码规范)
2. [模块编号](#2-模块编号)
3. [错误类别](#3-错误类别)
4. [通用错误码](#4-通用错误码)
5. [模块错误码范围](#5-模块错误码范围)
6. [各模块错误码详情](#6-各模块错误码详情)
7. [统一响应格式](#7-统一响应格式)
8. [向后兼容方案](#8-向后兼容方案)
9. [使用指南](#9-使用指南)

---

## 1. 错误码规范

### 1.1 格式

6 位数字错误码，格式为 `XX YY ZZ`：

```
XX YY ZZ
│  │  │
│  │  └── 具体错误序号（00-99）
│  └───── 错误类别（00-09）
└──────── 模块编号（00-12）
```

### 1.2 示例

| 错误码 | 模块 | 类别 | 说明 |
|--------|------|------|------|
| `000000` | 系统通用 | 成功 | 操作成功 |
| `000101` | 系统通用 | 参数错误 | 通用参数验证失败 |
| `000201` | 系统通用 | 认证错误 | 认证失败 |
| `080401` | M8 控制塔 | 资源不存在 | 模块不存在 |
| `080501` | M8 控制塔 | 业务错误 | 模块启动失败 |
| `090505` | M9 开发工坊 | 业务错误 | 代码执行超时 |
| `110701` | M11 MCP总线 | 第三方错误 | 上游服务超时 |

### 1.3 成功码

成功响应使用 `code = 0`，表示无错误。

---

## 2. 模块编号

| 编号 | 模块 | 名称 | 错误码范围 |
|------|------|------|------------|
| 00 | SYSTEM | 系统通用 | 000000 - 000999 |
| 01 | M1 | 智能体集群 | 010100 - 010999 |
| 02 | M2 | 技能集群 | 020100 - 020999 |
| 03 | M3 | 边端云协同 | 030100 - 030999 |
| 04 | M4 | 场景引擎 | 040100 - 040999 |
| 05 | M5 | 潮汐记忆 | 050100 - 050999 |
| 06 | M6 | 硬件外设 | 060100 - 060999 |
| 07 | M7 | 积木平台 | 070100 - 070999 |
| 08 | M8 | 控制塔 | 080100 - 080999 |
| 09 | M9 | 开发工坊 | 090100 - 090999 |
| 10 | M10 | 系统卫士 | 100100 - 100999 |
| 11 | M11 | MCP总线 | 110100 - 110999 |
| 12 | M12 | 安全盾 | 120100 - 120999 |

---

## 3. 错误类别

| 类别码 | 名称 | HTTP 状态码 | 说明 |
|--------|------|-------------|------|
| 00 | 成功 (SUCCESS) | 200 | 操作成功 |
| 01 | 参数错误 (VALIDATION) | 400 | 输入参数格式不正确、缺少必填字段、数据校验失败 |
| 02 | 认证错误 (AUTHENTICATION) | 401 | 用户未认证、Token 无效或已过期 |
| 03 | 权限错误 (AUTHORIZATION) | 403 | 用户已认证但无权访问请求的资源 |
| 04 | 资源不存在 (NOT_FOUND) | 404 | 请求的资源不存在 |
| 05 | 业务错误 (BUSINESS) | 409 | 业务规则校验失败、操作不允许 |
| 06 | 系统错误 (SYSTEM) | 500 | 服务器内部异常、依赖故障等不可预期的错误 |
| 07 | 第三方错误 (THIRD_PARTY) | 502 | 第三方或上游服务异常 |
| 08 | 限流错误 (RATE_LIMIT) | 429 | 请求频率超限或配额不足 |
| 09 | 数据错误 (DATA) | 409 | 数据冲突、完整性校验失败、数据库操作异常 |

---

## 4. 通用错误码

通用错误码使用 `00` 模块前缀，所有模块均可直接使用。

### 4.1 成功（0000xx）

| 错误码 | 常量名 | 说明 |
|--------|--------|------|
| 0 | `ErrorCode.SUCCESS` | 操作成功 |

### 4.2 参数错误（0001xx）

| 错误码 | 常量名 | 说明 |
|--------|--------|------|
| 000101 | `ErrorCode.VALIDATION_ERROR` | 通用参数验证失败 |
| 000102 | `ErrorCode.PARAM_MISSING` | 缺少必填参数 |
| 000103 | `ErrorCode.PARAM_INVALID` | 参数格式无效 |
| 000104 | `ErrorCode.PARAM_OUT_OF_RANGE` | 参数超出范围 |
| 000105 | `ErrorCode.PARAM_TYPE_ERROR` | 参数类型错误 |

### 4.3 认证错误（0002xx）

| 错误码 | 常量名 | 说明 |
|--------|--------|------|
| 000201 | `ErrorCode.AUTH_FAILED` | 认证失败 |
| 000202 | `ErrorCode.TOKEN_MISSING` | Token 缺失 |
| 000203 | `ErrorCode.TOKEN_INVALID` | Token 无效 |
| 000204 | `ErrorCode.TOKEN_EXPIRED` | Token 已过期 |
| 000205 | `ErrorCode.API_KEY_INVALID` | API Key 无效 |

### 4.4 权限错误（0003xx）

| 错误码 | 常量名 | 说明 |
|--------|--------|------|
| 000301 | `ErrorCode.PERMISSION_DENIED` | 无访问权限 |
| 000302 | `ErrorCode.ROLE_REQUIRED` | 需要特定角色权限 |
| 000303 | `ErrorCode.RESOURCE_FORBIDDEN` | 资源访问被禁止 |

### 4.5 资源不存在（0004xx）

| 错误码 | 常量名 | 说明 |
|--------|--------|------|
| 000401 | `ErrorCode.NOT_FOUND` | 资源不存在 |
| 000402 | `ErrorCode.ENDPOINT_NOT_FOUND` | 接口不存在 |
| 000403 | `ErrorCode.MODULE_NOT_FOUND` | 模块不存在 |

### 4.6 业务错误（0005xx）

| 错误码 | 常量名 | 说明 |
|--------|--------|------|
| 000501 | `ErrorCode.BUSINESS_ERROR` | 通用业务错误 |
| 000502 | `ErrorCode.OPERATION_NOT_ALLOWED` | 操作不允许 |
| 000503 | `ErrorCode.ALREADY_EXISTS` | 资源已存在 |

### 4.7 系统错误（0006xx）

| 错误码 | 常量名 | 说明 |
|--------|--------|------|
| 000601 | `ErrorCode.INTERNAL_ERROR` | 服务器内部错误 |
| 000602 | `ErrorCode.SERVICE_UNAVAILABLE` | 服务暂不可用 |
| 000603 | `ErrorCode.TIMEOUT` | 请求超时 |
| 000604 | `ErrorCode.CONFIG_ERROR` | 配置错误 |

### 4.8 第三方错误（0007xx）

| 错误码 | 常量名 | 说明 |
|--------|--------|------|
| 000701 | `ErrorCode.THIRD_PARTY_ERROR` | 第三方服务错误 |
| 000702 | `ErrorCode.UPSTREAM_TIMEOUT` | 上游服务超时 |
| 000703 | `ErrorCode.UPSTREAM_ERROR` | 上游服务错误 |
| 000704 | `ErrorCode.MODULE_CALL_FAILED` | 模块调用失败 |

### 4.9 限流错误（0008xx）

| 错误码 | 常量名 | 说明 |
|--------|--------|------|
| 000801 | `ErrorCode.RATE_LIMITED` | 请求频率超限 |
| 000802 | `ErrorCode.QUOTA_EXCEEDED` | 配额已用完 |

### 4.10 数据错误（0009xx）

| 错误码 | 常量名 | 说明 |
|--------|--------|------|
| 000901 | `ErrorCode.DATA_ERROR` | 数据错误 |
| 000902 | `ErrorCode.DATA_CONFLICT` | 数据冲突 |
| 000903 | `ErrorCode.DATA_INTEGRITY_ERROR` | 数据完整性错误 |
| 000904 | `ErrorCode.DATABASE_ERROR` | 数据库操作失败 |

---

## 5. 模块错误码范围

各模块应在各自的错误码文件中定义模块特有错误码。以下是各模块的错误码范围：

| 模块 | 起始码 | 结束码 | 数量 | 试点状态 |
|------|--------|--------|------|----------|
| M1 智能体集群 | 010100 | 010999 | 900 | 待接入 |
| M2 技能集群 | 020100 | 020999 | 900 | 待接入 |
| M3 边端云协同 | 030100 | 030999 | 900 | 待接入 |
| M4 场景引擎 | 040100 | 040999 | 900 | 待接入 |
| M5 潮汐记忆 | 050100 | 050999 | 900 | 待接入 |
| M6 硬件外设 | 060100 | 060999 | 900 | 待接入 |
| M7 积木平台 | 070100 | 070999 | 900 | 待接入 |
| M8 控制塔 | 080100 | 080999 | 900 | **试点中** |
| M9 开发工坊 | 090100 | 090999 | 900 | **试点中** |
| M10 系统卫士 | 100100 | 100999 | 900 | 待接入 |
| M11 MCP总线 | 110100 | 110999 | 900 | **试点中** |
| M12 安全盾 | 120100 | 120999 | 900 | 待接入 |

---

## 6. 各模块错误码详情

### 6.1 M8 控制塔（08 前缀）

文件：`M8-control-tower/backend/errors.py`

| 错误码 | 常量名 | 类别 | 说明 |
|--------|--------|------|------|
| 080101 | `INVALID_MODULE_KEY` | 参数错误 | 无效的模块标识 |
| 080102 | `INVALID_MODE_NAME` | 参数错误 | 无效的模式名称 |
| 080103 | `INVALID_INSPECTION_TYPE` | 参数错误 | 无效的巡检类型 |
| 080201 | `ADMIN_TOKEN_REQUIRED` | 认证错误 | 需要管理员 Token |
| 080202 | `M8_TOKEN_INVALID` | 认证错误 | M8 标准接口 Token 无效 |
| 080301 | `MODULE_OPERATION_FORBIDDEN` | 权限错误 | 模块操作权限不足 |
| 080302 | `EVOLUTION_FORBIDDEN` | 权限错误 | 自进化操作权限不足 |
| 080401 | `MODULE_NOT_FOUND` | 资源不存在 | 模块不存在 |
| 080402 | `MODE_NOT_FOUND` | 资源不存在 | 模式不存在 |
| 080403 | `INSPECTION_NOT_FOUND` | 资源不存在 | 巡检任务不存在 |
| 080501 | `MODULE_START_FAILED` | 业务错误 | 模块启动失败 |
| 080502 | `MODULE_STOP_FAILED` | 业务错误 | 模块停止失败 |
| 080503 | `MODULE_RESTART_FAILED` | 业务错误 | 模块重启失败 |
| 080504 | `MODULE_ALREADY_RUNNING` | 业务错误 | 模块已在运行 |
| 080505 | `MODULE_NOT_RUNNING` | 业务错误 | 模块未运行 |
| 080506 | `MODE_SWITCH_FAILED` | 业务错误 | 模式切换失败 |
| 080507 | `INSPECTION_RUN_FAILED` | 业务错误 | 巡检执行失败 |
| 080508 | `DEPLOYMENT_FAILED` | 业务错误 | 部署失败 |
| 080601 | `DATABASE_INIT_FAILED` | 系统错误 | 数据库初始化失败 |
| 080602 | `ORCHESTRATOR_ERROR` | 系统错误 | 编排器错误 |
| 080701 | `M4_PROXY_ERROR` | 第三方错误 | M4 代理错误 |
| 080702 | `M5_PROXY_ERROR` | 第三方错误 | M5 记忆代理错误 |
| 080703 | `M6_DEVICE_ERROR` | 第三方错误 | M6 设备通信错误 |
| 080801 | `MODULE_OPERATION_RATE_LIMITED` | 限流错误 | 模块操作频率超限 |
| 080901 | `SETTINGS_CONFLICT` | 数据错误 | 配置冲突 |
| 080902 | `USER_DATA_ERROR` | 数据错误 | 用户数据错误 |

### 6.2 M9 开发工坊（09 前缀）

文件：`M9-dev-workshop/backend/core/unified_errors.py`

| 错误码 | 常量名 | 类别 | 说明 |
|--------|--------|------|------|
| 090101 | `INVALID_PARAMS` | 参数错误 | 请求参数无效 |
| 090102 | `INVALID_PROJECT_NAME` | 参数错误 | 项目名称无效 |
| 090103 | `INVALID_FILE_PATH` | 参数错误 | 文件路径无效 |
| 090104 | `INVALID_CODE_LANGUAGE` | 参数错误 | 不支持的编程语言 |
| 090105 | `INVALID_TAG_FORMAT` | 参数错误 | 标签格式无效 |
| 090201 | `TOKEN_INVALID` | 认证错误 | Token 无效 |
| 090202 | `TOKEN_MISSING` | 认证错误 | Token 缺失 |
| 090203 | `ADMIN_TOKEN_REQUIRED` | 认证错误 | 需要管理员 Token |
| 090301 | `PERMISSION_DENIED` | 权限错误 | 无访问权限 |
| 090302 | `WORKSPACE_ACCESS_DENIED` | 权限错误 | 工作区访问被拒绝 |
| 090303 | `CODE_EXEC_FORBIDDEN` | 权限错误 | 代码执行被禁止 |
| 090401 | `PROJECT_NOT_FOUND` | 资源不存在 | 项目不存在 |
| 090402 | `FILE_NOT_FOUND` | 资源不存在 | 文件不存在 |
| 090403 | `VSCODE_NOT_FOUND` | 资源不存在 | VS Code 未安装 |
| 090404 | `MCP_TOOL_NOT_FOUND` | 资源不存在 | MCP 工具不存在 |
| 090405 | `BACKUP_NOT_FOUND` | 资源不存在 | 备份不存在 |
| 090501 | `PROJECT_ALREADY_EXISTS` | 业务错误 | 项目已存在 |
| 090502 | `PROJECT_PATH_EXISTS` | 业务错误 | 项目路径已存在 |
| 090503 | `VSCODE_START_FAILED` | 业务错误 | VS Code 启动失败 |
| 090504 | `VSCODE_STOP_FAILED` | 业务错误 | VS Code 停止失败 |
| 090505 | `CODE_EXEC_TIMEOUT` | 业务错误 | 代码执行超时 |
| 090506 | `CODE_EXEC_FAILED` | 业务错误 | 代码执行失败 |
| 090507 | `MCP_CALL_FAILED` | 业务错误 | MCP 工具调用失败 |
| 090508 | `MCP_TOOL_DISABLED` | 业务错误 | MCP 工具已禁用 |
| 090509 | `BACKUP_CREATE_FAILED` | 业务错误 | 备份创建失败 |
| 090510 | `BACKUP_RESTORE_FAILED` | 业务错误 | 备份恢复失败 |
| 090511 | `SCAN_FAILED` | 业务错误 | 扫描失败 |
| 090601 | `INTERNAL_ERROR` | 系统错误 | 内部服务错误 |
| 090602 | `DATABASE_ERROR` | 系统错误 | 数据库错误 |
| 090603 | `WORKSPACE_INIT_FAILED` | 系统错误 | 工作区初始化失败 |
| 090701 | `GIT_ERROR` | 第三方错误 | Git 操作错误 |
| 090702 | `VSCODE_EXTENSION_ERROR` | 第三方错误 | VS Code 扩展错误 |
| 090703 | `MCP_UPSTREAM_ERROR` | 第三方错误 | MCP 上游服务错误 |
| 090801 | `RATE_LIMITED` | 限流错误 | 请求频率超限 |
| 090802 | `CODE_EXEC_RATE_LIMITED` | 限流错误 | 代码执行频率超限 |
| 090901 | `PATH_UNSAFE` | 数据错误 | 路径安全校验失败 |
| 090902 | `SANDBOX_VIOLATION` | 数据错误 | 沙箱安全违规 |
| 090903 | `DATA_CORRUPTED` | 数据错误 | 数据损坏 |

### 6.3 M11 MCP 总线（11 前缀）

文件：`M11-mcp-bus/src/errors.py`

| 错误码 | 常量名 | 类别 | 说明 |
|--------|--------|------|------|
| 110101 | `INVALID_SERVER_ID` | 参数错误 | 无效的服务 ID |
| 110102 | `INVALID_TOOL_NAME` | 参数错误 | 无效的工具名称 |
| 110103 | `INVALID_API_KEY_NAME` | 参数错误 | 无效的 API Key 名称 |
| 110104 | `INVALID_TRANSPORT_TYPE` | 参数错误 | 无效的传输类型 |
| 110105 | `MCP_PARSE_ERROR` | 参数错误 | MCP 消息解析错误 |
| 110106 | `MCP_INVALID_REQUEST` | 参数错误 | MCP 请求无效 |
| 110107 | `MCP_INVALID_PARAMS` | 参数错误 | MCP 参数无效 |
| 110201 | `API_KEY_MISSING` | 认证错误 | 缺少 API Key |
| 110202 | `API_KEY_INVALID` | 认证错误 | API Key 无效 |
| 110203 | `API_KEY_EXPIRED` | 认证错误 | API Key 已过期 |
| 110204 | `MCP_AUTH_FAILED` | 认证错误 | MCP 认证失败 |
| 110301 | `ADMIN_REQUIRED` | 权限错误 | 需要管理员权限 |
| 110302 | `TOOL_ACCESS_DENIED` | 权限错误 | 工具访问被拒绝 |
| 110303 | `SERVER_ACCESS_DENIED` | 权限错误 | 服务访问被拒绝 |
| 110401 | `SERVER_NOT_FOUND` | 资源不存在 | MCP 服务不存在 |
| 110402 | `TOOL_NOT_FOUND` | 资源不存在 | MCP 工具不存在 |
| 110403 | `API_KEY_NOT_FOUND` | 资源不存在 | API Key 不存在 |
| 110404 | `SESSION_NOT_FOUND` | 资源不存在 | 会话不存在 |
| 110501 | `SERVER_ALREADY_EXISTS` | 业务错误 | 服务已存在 |
| 110502 | `SERVER_OFFLINE` | 业务错误 | 服务离线 |
| 110503 | `TOOL_DISABLED` | 业务错误 | 工具已禁用 |
| 110504 | `SESSION_EXPIRED` | 业务错误 | 会话已过期 |
| 110505 | `STDIO_START_FAILED` | 业务错误 | STDIO 进程启动失败 |
| 110506 | `STDIO_STOP_FAILED` | 业务错误 | STDIO 进程停止失败 |
| 110601 | `REGISTRY_ERROR` | 系统错误 | 注册中心错误 |
| 110602 | `ROUTER_ERROR` | 系统错误 | 路由错误 |
| 110603 | `CACHE_ERROR` | 系统错误 | 缓存错误 |
| 110701 | `UPSTREAM_TIMEOUT` | 第三方错误 | 上游服务超时 |
| 110702 | `UPSTREAM_ERROR` | 第三方错误 | 上游服务错误 |
| 110703 | `MCP_METHOD_NOT_FOUND` | 第三方错误 | MCP 方法不存在（上游返回） |
| 110704 | `MCP_INTERNAL_ERROR` | 第三方错误 | MCP 内部错误（上游返回） |
| 110705 | `ADAPTER_ERROR` | 第三方错误 | 适配器错误 |
| 110801 | `RATE_LIMITED` | 限流错误 | 请求频率超限 |
| 110802 | `TOOL_RATE_LIMITED` | 限流错误 | 工具调用频率超限 |
| 110803 | `QUOTA_EXCEEDED` | 限流错误 | 配额已用完 |
| 110901 | `DATABASE_ERROR` | 数据错误 | 数据库错误 |
| 110902 | `DATA_CONFLICT` | 数据错误 | 数据冲突 |

---

## 7. 统一响应格式

### 7.1 成功响应

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "key": "value"
    },
    "trace_id": "abc123def456"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | number | 是 | 状态码，0 表示成功 |
| `message` | string | 是 | 状态描述 |
| `data` | any | 是 | 响应数据 |
| `trace_id` | string | 否 | 请求追踪 ID |

### 7.2 错误响应

```json
{
    "code": 101,
    "message": "参数验证失败",
    "details": {
        "errors": [
            {"field": "username", "message": "用户名不能为空"}
        ],
        "error_count": 1
    },
    "trace_id": "abc123def456"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | number | 是 | 错误码（6 位） |
| `message` | string | 是 | 错误描述（面向用户的友好信息） |
| `details` | object | 是 | 错误详情（面向开发者的详细信息） |
| `trace_id` | string | 否 | 请求追踪 ID，用于问题排查 |

### 7.3 分页响应

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
    "trace_id": "abc123def456"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `data.items` | array | 是 | 数据列表 |
| `data.total` | number | 是 | 总记录数 |
| `data.page` | number | 是 | 当前页码（从 1 开始） |
| `data.page_size` | number | 是 | 每页数量 |
| `data.total_pages` | number | 是 | 总页数 |

---

## 8. 向后兼容方案

### 8.1 旧错误码映射

各模块的旧错误码将通过 `ERROR_CODE_LEGACY_MAP` 自动映射到新的 6 位错误码。

| 旧错误码 | 旧说明 | 新错误码 | 新说明 |
|----------|--------|----------|--------|
| 40001 | 参数验证失败 | 000101 | 参数验证失败 |
| 40002 | 配置错误 | 000604 | 配置错误 |
| 40101 | 认证失败 | 000201 | 认证失败 |
| 40301 | 无权限 | 000301 | 无访问权限 |
| 40401 | 资源不存在 | 000401 | 资源不存在 |
| 40402 | 模块不存在 | 000403 | 模块不存在 |
| 50000 | 内部错误 | 000601 | 服务器内部错误 |
| 50001 | 服务器内部错误 | 000601 | 服务器内部错误 |
| 50301 | 模块不可用 | 000602 | 服务暂不可用 |
| 50302 | 模块调用失败 | 000704 | 模块调用失败 |

### 8.2 M11 JSON-RPC 负数错误码

M11 原有的 JSON-RPC 风格负数错误码通过 `JSONRPC_ERROR_MAP` 映射：

| 旧错误码 | 旧说明 | 新错误码 | 新说明 |
|----------|--------|----------|--------|
| -32700 | Parse error | 110105 | MCP 消息解析错误 |
| -32600 | Invalid Request | 110106 | MCP 请求无效 |
| -32601 | Method not found | 110703 | MCP 方法不存在 |
| -32602 | Invalid params | 110107 | MCP 参数无效 |
| -32603 | Internal error | 110704 | MCP 内部错误 |

### 8.3 过渡期策略

1. **响应格式**：新接口必须使用统一格式，旧接口保持原有格式并逐步迁移
2. **错误码**：全局异常处理器自动将旧错误码规范化为新码
3. **异常类**：保留 `YunxiError` 基类，原有子类继续可用
4. **迁移顺序**：按 M8 → M9 → M11 → 其他模块的顺序逐步迁移

---

## 9. 使用指南

### 9.1 基本用法

```python
from shared.core.errors import (
    ErrorCode,
    NotFoundError,
    ValidationError,
    BusinessError,
    raise_not_found,
)
from shared.core.responses import ApiResponse, ok, fail

# 成功响应
return ok(data={"user": user}, message="获取成功")

# 错误响应 - 直接返回
return fail(code=ErrorCode.VALIDATION_ERROR, message="参数错误")

# 错误响应 - 抛出异常（推荐，由全局异常处理器统一处理）
raise NotFoundError(
    message="用户不存在",
    details={"user_id": user_id},
)

# 快捷函数
raise_not_found("用户", user_id)
```

### 9.2 模块特有错误码

```python
from .errors import M8ErrorCode
from shared.core.errors import BusinessError

# 使用模块特有错误码
raise BusinessError(
    message="模块启动失败",
    code=M8ErrorCode.MODULE_START_FAILED,
    details={"module_key": "m1"},
)
```

### 9.3 注册全局异常处理器

```python
from fastapi import FastAPI
from shared.core.responses import register_global_exception_handler

app = FastAPI()

# 注册全局异常处理器（一行代码搞定）
register_global_exception_handler(app)
```

### 9.4 定义模块错误码

```python
from shared.core.errors import (
    ModuleCode,
    ErrorCategory,
    build_error_code,
    ModuleErrorCode,
)

class MyModuleErrorCode(ModuleErrorCode):
    MODULE = ModuleCode.M8  # 替换为对应模块编号

    # 参数错误 (xx01xx)
    INVALID_SOMETHING = build_error_code(ModuleCode.M8, ErrorCategory.VALIDATION, 1)

    # 业务错误 (xx05xx)
    SOMETHING_FAILED = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 1)
```

### 9.5 错误信息编写规范

1. **友好明确**：错误信息应使用中文，清晰易懂
2. **可操作**：告诉用户应该怎么做（如 "请检查用户名是否正确"）
3. **不暴露敏感信息**：生产环境不返回堆栈、路径等内部细节
4. **统一风格**：使用陈述句，不带感叹号，不使用情绪化语言

### 9.6 新增错误码流程

1. 确认错误属于哪个模块、哪个类别
2. 在对应模块的错误码文件中，按序号递增添加
3. 更新本 ERROR_CODES.md 文档
4. 添加对应的单元测试

---

## 附录：相关文件

| 文件 | 说明 |
|------|------|
| `shared/core/errors.py` | 统一错误码体系核心实现 |
| `shared/core/responses.py` | 统一响应格式和全局异常处理器 |
| `shared/core/__init__.py` | 核心模块导出 |
| `M8-control-tower/backend/errors.py` | M8 模块错误码定义 |
| `M9-dev-workshop/backend/core/unified_errors.py` | M9 模块错误码定义 |
| `M11-mcp-bus/src/errors.py` | M11 模块错误码定义 |
