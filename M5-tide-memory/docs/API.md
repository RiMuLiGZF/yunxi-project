# M5 潮汐记忆系统 API 文档

> ⚠️ 所有接口返回的记忆内容均已脱敏，原文需单独授权获取

## 基础信息

- **Base URL**: `/api/v1/memory`
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

- `code`: 0表示成功，非0表示错误（详见错误码）
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

## 接口列表

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

> ⚠️ 返回元数据，原文需通过解密接口获取

### 4. 删除记忆

**DELETE** `/api/v1/memory/{memory_id}`

安全删除（覆写后删除）

### 5. 记忆统计

**GET** `/api/v1/memory/stats`

### 6. 触发巩固

**POST** `/api/v1/memory/consolidate`

请求体：
```json
{
  "mode": "normal"
}
```

mode 可选值：`quick` / `normal` / `full`

### 7. 层级信息

**GET** `/api/v1/memory/layers`

### 8. 健康检查

**GET** `/api/v1/health`

## M8 标准接口

M8 接口路径前缀：`/m8/memory/`

| 接口 | 方法 | 说明 |
|------|------|------|
| /m8/memory/recall | POST | M8标准检索 |
| /m8/memory/archive | POST | M8标准归档 |
| /m8/memory/stats | GET | M8标准统计 |
| /m8/health | GET | M8健康检查 |
