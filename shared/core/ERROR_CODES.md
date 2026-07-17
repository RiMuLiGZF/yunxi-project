# 云汐系统统一错误码体系

> 版本：v2.0.0
> 生效日期：2026-07-17
> 状态：CQ-015 错误体系统一 - 全面推进中

## 目录

1. [错误码规范](#1-错误码规范)
2. [模块编号](#2-模块编号)
3. [错误类别](#3-错误类别)
4. [通用错误码](#4-通用错误码)
5. [模块接入状态](#5-模块接入状态)
6. [各模块错误码详情](#6-各模块错误码详情)
7. [统一响应格式](#7-统一响应格式)
8. [向后兼容方案](#8-向后兼容方案)
9. [使用指南](#9-使用指南)
10. [客户端处理建议](#10-客户端处理建议)

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
| `060401` | M6 硬件外设 | 资源不存在 | 设备不存在 |
| `070504` | M7 工作流 | 业务错误 | 检测到循环依赖 |
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

## 5. 模块接入状态

各模块统一错误体系接入进度：

| 模块 | 模块码 | 错误码定义文件 | 全局异常处理器 | 接入状态 |
|------|--------|---------------|---------------|----------|
| API-Gateway | 00 | `API-Gateway/src/unified_errors.py` | 已注册 | **已接入** |
| M1 智能体集群 | 01 | - | - | 待接入 |
| M2 技能集群 | 02 | - | - | 待接入 |
| M3 边端云协同 | 03 | - | - | 待接入 |
| M4 场景引擎 | 04 | - | - | 待接入 |
| M5 潮汐记忆 | 05 | - | - | 待接入 |
| M6 硬件外设 | 06 | `M6-hardware-peripheral/m6_hardware/unified_errors.py` | 已集成 | **已接入** |
| M7 积木平台 | 07 | `M7-workflow-builder/src/unified_errors.py` | 已集成 | **已接入** |
| M8 控制塔 | 08 | `M8-control-tower/backend/errors.py` | 已注册 | **已接入** |
| M9 开发工坊 | 09 | `M9-dev-workshop/backend/core/unified_errors.py` | 已注册 | **已接入** |
| M10 系统卫士 | 10 | - | - | 待接入 |
| M11 MCP总线 | 11 | `M11-mcp-bus/src/errors.py` | 已注册 | **已接入** |
| M12 安全盾 | 12 | - | - | 待接入 |

**当前接入进度：7/13 模块已接入统一错误体系**

---

## 6. 各模块错误码详情

### 6.1 API-Gateway（00 前缀，系统级）

文件：`API-Gateway/src/unified_errors.py`

| 错误码 | 常量名 | 类别 | 说明 |
|--------|--------|------|------|
| 000110 | `INVALID_ROUTE_KEY` | 参数错误 | 无效的路由键 |
| 000111 | `INVALID_UPSTREAM_URL` | 参数错误 | 无效的上游地址 |
| 000510 | `ROUTE_DISABLED` | 业务错误 | 路由已禁用 |
| 000511 | `UPSTREAM_UNAVAILABLE` | 业务错误 | 上游服务不可用 |
| 000512 | `CIRCUIT_BREAKER_OPEN` | 业务错误 | 熔断器已打开 |
| 000513 | `PROXY_TIMEOUT` | 业务错误 | 代理超时 |

### 6.2 M6 硬件外设（06 前缀）

文件：`M6-hardware-peripheral/m6_hardware/unified_errors.py`

| 错误码 | 常量名 | 类别 | 说明 |
|--------|--------|------|------|
| 060101 | `INVALID_DEVICE_ID` | 参数错误 | 无效的设备 ID |
| 060102 | `INVALID_DEVICE_TYPE` | 参数错误 | 无效的设备类型 |
| 060103 | `INVALID_COMMAND` | 参数错误 | 无效的控制命令 |
| 060104 | `INVALID_SENSOR_DATA` | 参数错误 | 无效的传感器数据 |
| 060105 | `INVALID_DRIVER_CONFIG` | 参数错误 | 无效的驱动配置 |
| 060401 | `DEVICE_NOT_FOUND` | 资源不存在 | 设备不存在 |
| 060402 | `DRIVER_NOT_FOUND` | 资源不存在 | 驱动不存在 |
| 060403 | `SENSOR_NOT_FOUND` | 资源不存在 | 传感器不存在 |
| 060404 | `PERIPHERAL_NOT_FOUND` | 资源不存在 | 外设不存在 |
| 060501 | `DEVICE_OFFLINE` | 业务错误 | 设备离线 |
| 060502 | `DEVICE_BUSY` | 业务错误 | 设备繁忙 |
| 060503 | `COMMUNICATION_FAILED` | 业务错误 | 通信失败 |
| 060504 | `COMMAND_TIMEOUT` | 业务错误 | 命令超时 |
| 060505 | `DEVICE_INIT_FAILED` | 业务错误 | 设备初始化失败 |
| 060506 | `DRIVER_LOAD_FAILED` | 业务错误 | 驱动加载失败 |
| 060507 | `HARDWARE_ERROR` | 业务错误 | 硬件错误 |
| 060508 | `SENSOR_READ_FAILED` | 业务错误 | 传感器读取失败 |
| 060601 | `SERIAL_PORT_ERROR` | 系统错误 | 串口错误 |
| 060602 | `USB_ERROR` | 系统错误 | USB 错误 |
| 060603 | `GPIO_ERROR` | 系统错误 | GPIO 错误 |
| 060604 | `I2C_ERROR` | 系统错误 | I2C 错误 |
| 060605 | `SPI_ERROR` | 系统错误 | SPI 错误 |

### 6.3 M7 工作流构建器（07 前缀）

文件：`M7-workflow-builder/src/unified_errors.py`

| 错误码 | 常量名 | 类别 | 说明 |
|--------|--------|------|------|
| 070101 | `INVALID_WORKFLOW_ID` | 参数错误 | 无效的工作流 ID |
| 070102 | `INVALID_WORKFLOW_NAME` | 参数错误 | 无效的工作流名称 |
| 070103 | `INVALID_NODE_CONFIG` | 参数错误 | 无效的节点配置 |
| 070104 | `INVALID_EDGE_CONFIG` | 参数错误 | 无效的连线配置 |
| 070105 | `INVALID_VARIABLE` | 参数错误 | 无效的变量定义 |
| 070106 | `INVALID_TEMPLATE` | 参数错误 | 无效的模板 |
| 070401 | `WORKFLOW_NOT_FOUND` | 资源不存在 | 工作流不存在 |
| 070402 | `NODE_NOT_FOUND` | 资源不存在 | 节点不存在 |
| 070403 | `TEMPLATE_NOT_FOUND` | 资源不存在 | 模板不存在 |
| 070404 | `EXECUTION_NOT_FOUND` | 资源不存在 | 执行记录不存在 |
| 070501 | `WORKFLOW_ALREADY_EXISTS` | 业务错误 | 工作流已存在 |
| 070502 | `WORKFLOW_RUNNING` | 业务错误 | 工作流正在运行 |
| 070503 | `WORKFLOW_NOT_RUNNING` | 业务错误 | 工作流未运行 |
| 070504 | `CYCLE_DETECTED` | 业务错误 | 检测到循环依赖 |
| 070505 | `NODE_EXECUTION_FAILED` | 业务错误 | 节点执行失败 |
| 070506 | `WORKFLOW_VALIDATION_FAILED` | 业务错误 | 工作流校验失败 |
| 070507 | `VARIABLE_RESOLUTION_FAILED` | 业务错误 | 变量解析失败 |
| 070508 | `TEMPLATE_IMPORT_FAILED` | 业务错误 | 模板导入失败 |
| 070509 | `TEMPLATE_EXPORT_FAILED` | 业务错误 | 模板导出失败 |
| 070510 | `WORKFLOW_SUSPENDED` | 业务错误 | 工作流已暂停 |
| 070601 | `EXECUTION_ENGINE_ERROR` | 系统错误 | 执行引擎错误 |
| 070602 | `STORAGE_ERROR` | 系统错误 | 存储错误 |
| 070603 | `SCHEDULER_ERROR` | 系统错误 | 调度器错误 |

### 6.4 M8 控制塔（08 前缀）

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

### 6.5 M9 开发工坊（09 前缀）

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

### 6.6 M11 MCP 总线（11 前缀）

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

### 7.1 错误响应（标准格式）

所有模块的 API 错误响应必须使用以下统一格式：

```json
{
  "error": {
    "code": "MODULE_ERROR_CODE",
    "message": "人类可读的错误消息",
    "details": {},
    "request_id": "uuid",
    "timestamp": "iso8601"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `error.code` | number | 是 | 错误码（6 位数字） |
| `error.message` | string | 是 | 错误描述（面向用户的友好信息，中文） |
| `error.details` | object | 是 | 错误详情（面向开发者的详细信息） |
| `error.request_id` | string | 是 | 请求追踪 ID，用于问题排查 |
| `error.timestamp` | string | 是 | 错误发生时间（ISO 8601 格式） |

### 7.2 成功响应（标准格式）

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "key": "value"
  },
  "request_id": "abc123def456"
}
```

### 7.3 旧格式兼容（过渡期）

部分模块仍在使用旧的扁平格式，过渡期内全局异常处理器会自动转换：

**旧格式（将逐步淘汰）：**
```json
{
  "code": 101,
  "message": "参数验证失败",
  "details": {}
}
```

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

### 8.2 M6 旧错误码映射

M6 模块原有的 3 位错误码（1xx/2xx/3xx/4xx）通过 `M6_LEGACY_ERROR_MAP` 映射：

| 旧错误码 | 旧说明 | 新错误码 | 新说明 |
|----------|--------|----------|--------|
| 100 | 设备不存在 | 060401 | 设备不存在 |
| 101 | 设备离线 | 060501 | 设备离线 |
| 102 | 设备已配对 | 060502 | 设备繁忙 |
| 104 | 操作不支持 | 060103 | 无效的控制命令 |
| 200 | 传感器不存在 | 060403 | 传感器不存在 |
| 201 | 传感器数据无效 | 060104 | 无效的传感器数据 |
| 300 | SSE Token 无效 | 000201 | 认证失败 |
| 301 | SSE Token 过期 | 000204 | Token 已过期 |
| 302 | SSE 连接超限 | 000801 | 请求频率超限 |

### 8.3 M11 JSON-RPC 负数错误码

M11 原有的 JSON-RPC 风格负数错误码通过 `JSONRPC_ERROR_MAP` 映射：

| 旧错误码 | 旧说明 | 新错误码 | 新说明 |
|----------|--------|----------|--------|
| -32700 | Parse error | 110105 | MCP 消息解析错误 |
| -32600 | Invalid Request | 110106 | MCP 请求无效 |
| -32601 | Method not found | 110703 | MCP 方法不存在 |
| -32602 | Invalid params | 110107 | MCP 参数无效 |
| -32603 | Internal error | 110704 | MCP 内部错误 |

### 8.4 过渡期策略

1. **响应格式**：新接口必须使用统一格式，旧接口保持原有格式并逐步迁移
2. **错误码**：全局异常处理器自动将旧错误码规范化为新码
3. **异常类**：`M6Exception`、`M11Exception` 等模块异常类已继承 `YunxiError`
4. **迁移顺序**：按 M8 → M9 → M11 → M6 → M7 → Gateway → 其他模块的顺序逐步迁移

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

## 10. 客户端处理建议

### 10.1 按 HTTP 状态码处理

| HTTP 状态码 | 建议处理方式 |
|-------------|-------------|
| 200 | 正常处理响应数据 |
| 400 | 提示用户修正输入参数，高亮错误字段 |
| 401 | 清除本地登录状态，跳转到登录页 |
| 403 | 提示 "无访问权限"，引导联系管理员 |
| 404 | 提示 "资源不存在"，返回列表页或首页 |
| 409 | 展示业务错误原因，引导用户操作 |
| 429 | 提示 "请求过于频繁"，显示倒计时，自动重试 |
| 500 | 提示 "服务器内部错误"，提供重试按钮 |
| 502 | 提示 "服务暂时不可用"，稍后重试 |

### 10.2 按错误类别处理

1. **参数错误（01xx）**：表单校验失败，高亮对应字段
2. **认证错误（02xx）**：统一走登录流程
3. **权限错误（03xx）**：显示权限不足页面
4. **资源不存在（04xx）**：显示 404 页面
5. **业务错误（05xx）**：根据具体错误码展示不同提示
6. **系统错误（06xx）**：统一错误提示 + 上报问题
7. **第三方错误（07xx）**：提示上游服务异常，稍后重试
8. **限流错误（08xx）**：显示限流提示 + 退避重试
9. **数据错误（09xx）**：提示数据异常，联系管理员

### 10.3 request_id 的使用

所有错误响应都包含 `request_id`，客户端应：
- 在错误提示中展示 request_id（可选）
- 在用户反馈时附带 request_id
- 在前端日志中记录 request_id 便于排查

---

## 附录：相关文件

| 文件 | 说明 |
|------|------|
| `shared/core/errors.py` | 统一错误码体系核心实现 |
| `shared/core/responses.py` | 统一响应格式和全局异常处理器 |
| `shared/core/__init__.py` | 核心模块导出 |
| `API-Gateway/src/unified_errors.py` | API 网关错误码定义 |
| `M6-hardware-peripheral/m6_hardware/unified_errors.py` | M6 模块错误码定义 |
| `M6-hardware-peripheral/m6_hardware/models/errors.py` | M6 旧错误码兼容层 |
| `M7-workflow-builder/src/unified_errors.py` | M7 模块错误码定义 |
| `M8-control-tower/backend/errors.py` | M8 模块错误码定义 |
| `M9-dev-workshop/backend/core/unified_errors.py` | M9 模块错误码定义 |
| `M11-mcp-bus/src/errors.py` | M11 模块错误码定义 |
