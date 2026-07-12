# [模块名称] API 文档

## 基本信息

| 项目 | 内容 |
|------|------|
| 模块 | Mx - [模块名称] |
| 版本 | vX.Y.Z |
| 更新日期 | YYYY-MM-DD |
| 文档作者 | [作者] |

## 概述

简要描述 API 的用途、鉴权方式、基础 URL 等。

**基础 URL**: `http://localhost:{port}/api/v1`

**鉴权方式**: API Key / Bearer Token / 无需鉴权

## 通用约定

### 请求格式
- Content-Type: application/json
- 字符编码: UTF-8

### 响应格式

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

### 错误码

| 错误码 | 说明 |
|--------|------|
| 0 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未授权 |
| 403 | 禁止访问 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

## API 列表

### 1. [接口名称]

**描述**: 接口功能描述

**请求**:
- 方法: GET/POST/PUT/DELETE
- 路径: `/resource/{id}`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | string | 是 | 资源 ID |
| name | string | 否 | 资源名称 |

**请求示例**:

```json
{
  "name": "example",
  "value": 123
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "xxx",
    "name": "example",
    "created_at": "2026-07-08T10:00:00Z"
  }
}
```

**响应字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 资源 ID |
| name | string | 资源名称 |
| created_at | string | 创建时间 |

---

### 2. [接口名称]

...

## 附录

### 数据模型

#### ModelName

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 主键 |
| name | string | 名称 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

### 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| vX.Y | YYYY-MM-DD | 新增/修改/删除 xxx |
