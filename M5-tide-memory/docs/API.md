# M5 潮汐记忆系统 API 文档

> 所有接口返回的记忆内容均已脱敏，原文需单独授权获取

## 基础信息

- **Base URL**: `/api/v1`
- **认证方式**: Bearer Token (JWT)
- **数据格式**: JSON
- **字符编码**: UTF-8

## 统一响应格式

```json
{
  "code": 0,
  "message": "success",
  "data": { ... },
  "request_id": "m5-xxxxxxxxxxxx",
  "timestamp": "2024-01-01T00:00:00.000000"
}
```

- `code`: 0 表示成功，非 0 表示错误（详见错误码）
- `data`: 响应数据
- `request_id`: 请求唯一标识，用于排查问题

## 错误码

| 错误码 | 说明 |
|--------|------|
| 0 | 成功 |
| 50001 | 参数错误 |
| 50002 | 未授权 |
| 50003 | 禁止访问 |
| 50004 | 资源不存在 |
| 50101 | 记忆不存在 |
| 50201 | 权限不足 |
| 50203 | 密级过高 |
| 50301 | 存储空间不足 |

---

## 一、核心 API 端点

### 1. 记忆检索

**POST** `/api/v1/memory/recall`

请求体：
```json
{
  "query": "检索关键词",
  "top_k": 10,
  "layers": ["l1_shallow", "l2_deep"],
  "domain": "private",
  "agent_id": "agent_001",
  "emotion_context": {
    "valence": 0.5,
    "arousal": 0.3,
    "dominant_emotion": "calm"
  }
}
```

响应：
```json
{
  "code": 0,
  "data": {
    "results": [
      {
        "memory_id": "mem_xxxxxxxxxxxxxxxx",
        "content_preview": "[SANITIZED]",
        "layer": "l1_shallow",
        "domain": "private",
        "similarity": 0.85,
        "created_at": "2024-01-01T00:00:00",
        "emotion_tags": ["calm"],
        "quality_score": 75.0
      }
    ],
    "total": 1
  }
}
```

### 2. 记忆归档

**POST** `/api/v1/memory/archive`

请求体：
```json
{
  "content": "记忆内容（已加密传输）",
  "source": "conversation",
  "domain": "private",
  "agent_id": "agent_001",
  "tags": ["工作", "会议"],
  "metadata": {
    "session_id": "sess_001"
  }
}
```

响应：
```json
{
  "code": 0,
  "data": {
    "archive_id": "mem_xxxxxxxxxxxxxxxx",
    "layer": "l1_shallow",
    "content_hash": "sha256:xxxxxxxxxx",
    "created_at": "2024-01-01T00:00:00"
  }
}
```

### 3. 获取单条记忆

**GET** `/api/v1/memory/{memory_id}`

> 返回元数据，原文需通过解密接口获取

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| domain | string | private | 域权限 |
| agent_id | string | unknown | 代理 ID |

响应：
```json
{
  "code": 0,
  "data": {
    "memory_id": "mem_xxxxxxxxxxxxxxxx",
    "content_preview": "[SANITIZED]",
    "layer": "l1_shallow",
    "domain": "private",
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00",
    "tags": [],
    "classification": "INTERNAL"
  }
}
```

### 4. 删除记忆

**DELETE** `/api/v1/memory/{memory_id}`

安全删除（覆写后删除）。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| domain | string | private | 域权限 |
| agent_id | string | unknown | 代理 ID |

### 5. 记忆统计

**GET** `/api/v1/memory/stats`

响应：
```json
{
  "code": 0,
  "data": {
    "total": 1024,
    "layers": {
      "l0_beach": 100,
      "l1_shallow": 500,
      "l2_deep": 300,
      "l3_abyss": 124
    }
  }
}
```

### 6. 触发巩固

**POST** `/api/v1/memory/consolidate`

请求体：
```json
{
  "mode": "normal"
}
```

`mode` 可选值：`quick` / `normal` / `full`

响应：
```json
{
  "code": 0,
  "data": {
    "mode": "normal",
    "promoted": 5,
    "consolidated": 20,
    "duration_ms": 350
  }
}
```

### 7. 层级信息

**GET** `/api/v1/memory/layers`

响应：
```json
{
  "code": 0,
  "data": {
    "layers": [
      {"name": "l0_beach", "description": "沙滩层 - 瞬时记忆", "retention": "~1小时"},
      {"name": "l1_shallow", "description": "浅水层 - 短期记忆", "retention": "~1天"},
      {"name": "l2_deep", "description": "深水层 - 中期记忆", "retention": "~30天"},
      {"name": "l3_abyss", "description": "深海层 - 长期记忆", "retention": "永久"}
    ]
  }
}
```

### 8. 高级搜索

**POST** `/api/v1/memory/search`

与 `/api/v1/memory/recall` 共享同一处理逻辑，支持相同的请求参数。

### 9. 批量归档

**POST** `/api/v1/memory/batch_archive`

请求体：
```json
{
  "items": [
    {"content": "记忆内容1", "source": "conversation", "tags": ["标签1"]},
    {"content": "记忆内容2", "source": "conversation", "tags": ["标签2"]}
  ],
  "domain": "private",
  "agent_id": "agent_001"
}
```

响应：
```json
{
  "code": 0,
  "data": {
    "success_count": 2,
    "failed": []
  }
}
```

### 10. 批量删除

**DELETE** `/api/v1/memory/batch_delete`

请求体：
```json
{
  "memory_ids": ["mem_xxxx", "mem_yyyy"],
  "domain": "private",
  "agent_id": "agent_001"
}
```

响应：
```json
{
  "code": 0,
  "data": {
    "deleted_count": 2
  }
}
```

### 11. 分页查询

**GET** `/api/v1/memory/list`

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| page_size | int | 20 | 每页条数 |
| cursor | string | null | 游标（上一页返回的 next_cursor） |
| domain | string | private | 域权限 |
| agent_id | string | unknown | 代理 ID |
| sort_by | string | created_at | 排序字段 |
| order | string | desc | 排序方向（asc / desc） |

响应：
```json
{
  "code": 0,
  "data": {
    "items": [...],
    "next_cursor": "cursor_token_here",
    "has_more": true,
    "total": 1024
  }
}
```

### 12. 潮汐相位查询

**GET** `/api/v1/memory/phase`

响应：
```json
{
  "code": 0,
  "data": {
    "current_phase": "flood",
    "phase_progress": 0.35,
    "next_phase": "rising",
    "time_to_next_phase_min": 25
  }
}
```

### 13. 手动切换潮汐相位

**POST** `/api/v1/memory/phase/switch`

请求体：
```json
{
  "phase": "rising"
}
```

`phase` 可选值：`flood` / `rising` / `slack` / `ebb`

响应：
```json
{
  "code": 0,
  "data": {
    "switched": true,
    "current_phase": "rising"
  }
}
```

### 14. 健康检查

**GET** `/api/v1/health`

响应：
```json
{
  "code": 0,
  "data": {
    "status": "healthy",
    "version": "0.5.0",
    "module": "m5-memory",
    "timestamp": "2024-01-01T00:00:00"
  }
}
```

---

## 二、M8 标准接口端点

M8 接口遵循云汐系统统一标准协议，路径前缀为 `/m8`。
所有 M8 接口返回统一的 M8 响应格式（含 `code`、`message`、`data`、`request_id`、`timestamp`）。
错误码唯一来源为 `tide_memory.errors.ErrorCode` 枚举。

### M8-1. 健康检查

**GET** `/m8/health`

返回模块健康状态、版本号及已启用功能列表。

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "module": "m5-memory",
    "version": "0.5.0",
    "status": "healthy",
    "features": [
      "four_layer_tidal_memory",
      "emotion_inference",
      "domain_isolation",
      "classification_marking",
      "sleep_consolidation",
      "audit_logging",
      "m8_compatible"
    ]
  }
}
```

### M8-2. 性能指标

**GET** `/m8/metrics`

返回模块运行时的性能指标，包括 CPU 使用率、内存占用、存储用量、记忆条目数等。

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "cpu_usage": 2.3,
    "memory_mb": 128,
    "memory_entries": 1024,
    "vector_dim": 1536,
    "cache_hit_rate": 0.856,
    "storage_used_mb": 45
  }
}
```

### M8-3. 配置查询

**GET** `/m8/config`

返回模块配置信息，包括模块名称、版本、层级定义、向量检索状态。

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "module": "m5",
    "module_name": "潮汐记忆系统",
    "version": "0.5.0",
    "levels": ["sensory", "short_term", "long_term"],
    "vector_enabled": true
  }
}
```

### M8-4. 记忆检索

**POST** `/m8/memory/recall`

请求体：
```json
{
  "query": "检索文本",
  "top_k": 10,
  "filters": {
    "domain": "private",
    "layers": ["l1", "l2"]
  },
  "context": {
    "emotion": {
      "valence": 0.5,
      "arousal": 0.3
    },
    "agent_id": "agent_001"
  }
}
```

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "results": [
      {
        "memory_id": "mem_xxxxxxxxxxxxxxxx",
        "content_preview": "[SANITIZED]",
        "layer": "l1_shallow",
        "similarity": 0.85
      }
    ],
    "total": 1,
    "query": "检索文本"
  }
}
```

### M8-5. 记忆归档

**POST** `/m8/memory/archive`

请求体：
```json
{
  "content": "记忆内容（已加密）",
  "source": "conversation",
  "metadata": {
    "tags": ["标签"],
    "emotion": {"valence": 0.5, "arousal": 0.3},
    "domain": "private"
  },
  "context": {
    "agent_id": "agent_001"
  }
}
```

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "memory_id": "mem_xxxxxxxxxxxxxxxx",
    "layer": "l1_shallow",
    "content_hash": "sha256:xxxxxxxxxx",
    "created_at": "2024-01-01T00:00:00"
  }
}
```

### M8-6. 统计信息

**GET** `/m8/memory/stats`

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| domain | string | private | 指定域权限筛选 |

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "total": 1024,
    "layers": {
      "l0_beach": 100,
      "l1_shallow": 500,
      "l2_deep": 300,
      "l3_abyss": 124
    }
  }
}
```

### M8-7. 接口规范查询

**GET** `/m8/spec`

返回 M8 接口规范定义，包括所有端点列表和错误码映射。

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "module": "m5-memory",
    "version": "0.5.0",
    "m8_version": "1.0",
    "endpoints": [
      {"name": "health", "method": "GET", "path": "/m8/health"},
      {"name": "metrics", "method": "GET", "path": "/m8/metrics"},
      {"name": "config", "method": "GET", "path": "/m8/config"},
      {"name": "recall", "method": "POST", "path": "/m8/memory/recall"},
      {"name": "archive", "method": "POST", "path": "/m8/memory/archive"},
      {"name": "stats", "method": "GET", "path": "/m8/memory/stats"}
    ],
    "error_codes": {
      "SUCCESS": 0,
      "INVALID_PARAMS": 50001,
      "UNAUTHORIZED": 50002,
      "FORBIDDEN": 50003,
      "NOT_FOUND": 50004,
      "MEMORY_NOT_FOUND": 50101,
      "PERMISSION_DENIED": 50201,
      "CLASSIFICATION_TOO_HIGH": 50203,
      "STORAGE_FULL": 50301
    }
  }
}
```

---

## 三、端点总览

### 核心 API（`/api/v1`）

| 序号 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 1 | POST | `/api/v1/memory/recall` | 记忆检索 |
| 2 | POST | `/api/v1/memory/archive` | 记忆归档 |
| 3 | GET | `/api/v1/memory/{memory_id}` | 获取单条记忆 |
| 4 | DELETE | `/api/v1/memory/{memory_id}` | 删除记忆 |
| 5 | GET | `/api/v1/memory/stats` | 记忆统计 |
| 6 | POST | `/api/v1/memory/consolidate` | 触发巩固 |
| 7 | GET | `/api/v1/memory/layers` | 层级信息 |
| 8 | POST | `/api/v1/memory/search` | 高级搜索 |
| 9 | POST | `/api/v1/memory/batch_archive` | 批量归档 |
| 10 | DELETE | `/api/v1/memory/batch_delete` | 批量删除 |
| 11 | GET | `/api/v1/memory/list` | 分页查询 |
| 12 | GET | `/api/v1/memory/phase` | 潮汐相位查询 |
| 13 | POST | `/api/v1/memory/phase/switch` | 手动切换相位 |
| 14 | GET | `/api/v1/health` | 健康检查 |

### M8 标准接口（`/m8`）

| 序号 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 1 | GET | `/m8/health` | M8 健康检查 |
| 2 | GET | `/m8/metrics` | M8 性能指标 |
| 3 | GET | `/m8/config` | M8 配置查询 |
| 4 | POST | `/m8/memory/recall` | M8 记忆检索 |
| 5 | POST | `/m8/memory/archive` | M8 记忆归档 |
| 6 | GET | `/m8/memory/stats` | M8 统计信息 |
| 7 | GET | `/m8/spec` | M8 接口规范查询 |
