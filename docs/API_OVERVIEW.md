# 云汐系统 API 总览

> 版本：V12.0 · 更新时间：2026-07-16
> 文档类型：API总览 · 适用范围：全系统

---

## 一、API 设计规范

### 1.1 基础规范
- **协议**：HTTP/HTTPS + RESTful
- **数据格式**：JSON
- **字符编码**：UTF-8
- **认证方式**：JWT Token (Bearer) / API Key

### 1.2 统一响应格式
```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "timestamp": 1700000000
}
```

| 字段 | 说明 |
|------|------|
| `code` | 状态码，0=成功，非0=错误 |
| `message` | 状态描述 |
| `data` | 响应数据 |
| `timestamp` | 时间戳 |

### 1.3 错误码规范
| 码段 | 含义 |
|------|------|
| 0 | 成功 |
| 1000-1999 | 通用错误 |
| 2000-2999 | 认证/授权错误 |
| 3000-3999 | 参数/验证错误 |
| 4000-4999 | 业务逻辑错误 |
| 5000-5999 | 系统/服务错误 |

---

## 二、M8 控制塔 API 总览

**Base URL**: `http://localhost:8008/api/v1`

### 2.1 认证接口
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 用户登录 |
| POST | `/auth/logout` | 用户登出 |
| POST | `/auth/change-password` | 修改密码 |
| GET | `/auth/me` | 获取当前用户信息 |

### 2.2 聊天接口
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat/send` | 发送消息（SSE流式） |
| GET | `/chat/history` | 获取聊天历史 |
| DELETE | `/chat/history/{id}` | 删除单条消息 |
| POST | `/chat/clear` | 清空当前会话 |

### 2.3 模块纳管接口
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/modules` | 获取所有模块列表 |
| GET | `/modules/{module_id}` | 获取模块详情 |
| GET | `/modules/{module_id}/health` | 模块健康检查 |
| GET | `/modules/{module_id}/metrics` | 模块指标 |
| POST | `/modules/{module_id}/restart` | 重启模块 |
| POST | `/modules/proxy/{module_id}/{path:path}` | 模块代理调用 |

### 2.4 算力调度接口
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

### 2.5 记忆接口
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/memory/search` | 搜索记忆 |
| GET | `/memory/layers` | 记忆分层统计 |
| POST | `/memory/add` | 添加记忆 |
| DELETE | `/memory/{id}` | 删除记忆 |

### 2.6 知识库接口
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/brain/documents` | 文档列表 |
| POST | `/brain/upload` | 上传文档 |
| DELETE | `/brain/documents/{id}` | 删除文档 |
| GET | `/brain/search` | 知识库检索 |
| GET | `/brain/stats` | 知识库统计 |

### 2.7 成长中心接口
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/growth/overview` | 成长总览 |
| GET | `/growth/achievements` | 成就列表 |
| GET | `/growth/talent-tree` | 天赋树 |
| GET | `/growth/season` | 赛季旅程 |
| GET | `/growth/echoes` | 记忆回响 |

### 2.8 系统监控接口
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/monitor/realtime` | 实时系统指标 |
| GET | `/monitor/alerts` | 告警列表 |
| POST | `/monitor/alerts/{id}/ack` | 确认告警 |
| GET | `/monitor/module/{id}/detail` | 模块健康详情 |

### 2.9 自进化引擎接口
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/evolution/scan` | 健康扫描 |
| GET | `/evolution/plans` | 进化计划列表 |
| POST | `/evolution/plans` | 创建进化计划 |
| POST | `/evolution/deploy/{id}` | 部署进化方案 |
| POST | `/evolution/rollback/{id}` | 一键回滚 |
| GET | `/evolution/audit/{id}` | 安全审计报告 |

### 2.10 工作开发接口
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/work_dev/code/execute` | 执行代码 |
| GET | `/work_dev/projects` | 项目列表 |
| POST | `/work_dev/projects` | 创建项目 |
| GET | `/work_dev/vscode/status` | VSCode状态 |
| POST | `/work_dev/vscode/start` | 启动VSCode |

### 2.11 语音接口
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/voice/tts` | 文字转语音 |
| POST | `/voice/asr` | 语音转文字 |
| GET | `/voice/presets` | 音色预设列表 |
| POST | `/voice/presets` | 创建音色预设 |

---

## 三、各模块 API 端点

### 3.1 M1 Agent 集群 (8001)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/agents` | Agent列表 |
| POST | `/api/v1/agents/dispatch` | 任务分发 |
| GET | `/api/v1/agents/{id}/status` | Agent状态 |
| GET | `/api/v1/federation/adapters` | 联邦适配器列表 |
| GET | `/m8/health` | M8健康检查 |
| GET | `/m8/metrics` | M8指标 |

### 3.2 M2 技能集群 (8002)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/skills` | 技能列表 |
| POST | `/api/v1/skills/{id}/execute` | 执行技能 |
| GET | `/api/v1/skills/categories` | 技能分类 |
| GET | `/m8/health` | M8健康检查 |

### 3.3 M3 端云协同 (8003)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/route` | 路由任务到端/云 |
| GET | `/api/v1/nodes` | 节点列表 |
| GET | `/api/v1/stats` | 调度统计 |
| GET | `/m8/health` | M8健康检查 |

### 3.4 M4 场景引擎 (8004)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/scenes` | 场景列表 |
| POST | `/api/v1/scenes/switch` | 切换场景 |
| GET | `/api/v1/scenes/current` | 当前场景 |
| GET | `/m8/health` | M8健康检查 |

### 3.5 M5 潮汐记忆 (8005)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/memory/store` | 存储记忆 |
| GET | `/api/v1/memory/search` | 搜索记忆 |
| GET | `/api/v1/memory/layers` | 分层统计 |
| POST | `/api/v1/memory/consolidate` | 记忆巩固 |
| GET | `/m8/health` | M8健康检查 |

### 3.6 M6 硬件外设 (8006)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/devices` | 设备列表 |
| GET | `/api/v1/devices/{id}` | 设备详情 |
| GET | `/api/v1/devices/{id}/data` | 设备数据 |
| POST | `/api/v1/devices/{id}/control` | 设备控制 |
| GET | `/api/v1/devices/stream` | SSE数据推送 |
| GET | `/m8/health` | M8健康检查 |

### 3.7 M7 工作流 (8007)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/workflows` | 工作流列表 |
| POST | `/api/v1/workflows` | 创建工作流 |
| POST | `/api/v1/workflows/{id}/execute` | 执行工作流 |
| GET | `/api/v1/workflows/{id}/runs` | 执行历史 |
| GET | `/m8/health` | M8健康检查 |

### 3.8 M9 开发者工坊 (8009)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/vscode/status` | VSCode状态 |
| POST | `/api/v1/vscode/start` | 启动VSCode |
| POST | `/api/v1/code/execute` | 执行代码 |
| GET | `/api/v1/workspace/projects` | 项目列表 |
| GET | `/api/v1/mcp/tools` | MCP工具列表 |
| POST | `/api/v1/mcp/call` | 调用MCP工具 |
| GET | `/api/v1/dashboard/overview` | 仪表盘概览 |
| GET | `/m8/health` | M8深度健康检查 |
| GET | `/m8/metrics` | M8指标 |
| POST | `/m8/config/reload` | 配置热重载 |

### 3.9 M10 系统卫士 (8010)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/system/resources` | 系统资源 |
| GET | `/api/v1/processes` | 进程列表 |
| POST | `/api/v1/processes/{pid}/kill` | 终止进程 |
| GET | `/api/v1/alerts/thresholds` | 阈值配置 |
| GET | `/m8/health` | M8健康检查 |

### 3.10 M11 MCP 总线 (8011)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/services` | MCP服务列表 |
| POST | `/api/v1/services/register` | 注册服务 |
| GET | `/api/v1/tools` | 全部工具列表 |
| POST | `/api/v1/tools/call` | 调用工具 |
| GET | `/m8/health` | M8健康检查 |

### 3.11 M12 安全盾 (8012)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/waf/rules` | WAF规则列表 |
| POST | `/api/v1/waf/rules` | 添加WAF规则 |
| GET | `/api/v1/keys` | API密钥列表 |
| POST | `/api/v1/keys` | 创建API密钥 |
| GET | `/api/v1/ip/whitelist` | IP白名单 |
| GET | `/api/v1/ip/blacklist` | IP黑名单 |
| GET | `/api/v1/audit/logs` | 安全审计日志 |
| GET | `/m8/health` | M8健康检查 |

---

## 四、M8 标准接口规范

所有模块必须实现以下 M8 标准接口，用于 M8 控制塔纳管：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/m8/health` | 健康检查（深度探针，含各子系统状态） |
| GET | `/m8/metrics` | 运行指标（QPS、延迟、错误率等） |
| GET | `/m8/config` | 当前配置（脱敏） |
| POST | `/m8/config/reload` | 配置热重载（可选） |

### 健康检查响应示例
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
  }
}
```

---

## 五、认证方式

### 5.1 JWT Token（用户认证）
```http
Authorization: Bearer <jwt_token>
```

### 5.2 API Key（模块间调用）
```http
X-API-Key: <api_key>
```

### 5.3 模块 Token（M8纳管）
```http
X-Module-Token: <module_token>
```

---

## 六、限流策略

| 接口类型 | 限流 | 说明 |
|---------|------|------|
| 认证接口 | 10次/分钟 | 防止暴力破解 |
| 聊天接口 | 60次/分钟 | 防止滥用 |
| 算力调度 | 30次/分钟 | 保护算力资源 |
| 通用接口 | 100次/分钟 | 默认限流 |

---

## 七、WebSocket / SSE 接口

| 模块 | 路径 | 协议 | 说明 |
|------|------|------|------|
| M8 | `/api/v1/chat/stream` | SSE | 聊天消息流 |
| M6 | `/api/v1/devices/stream` | SSE | 设备数据推送 |
| M1 | `/api/v1/agents/stream` | SSE | Agent执行流 |

---

## 八、版本策略

- API 版本通过 URL 路径标识（如 `/api/v1/`）
- 主版本号变更时，旧版本保留至少 3 个月过渡期
- 向后兼容的小版本迭代不增加版本号
