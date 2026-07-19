# 统一响应格式标准 (Unified Response Standard)

> 云汐项目权威统一响应格式工具包，所有模块的 API 响应均应遵循此标准。

## 目录

- [标准定义](#标准定义)
- [快速开始](#快速开始)
- [API 参考](#api-参考)
- [FastAPI 集成](#fastapi-集成)
- [错误码体系](#错误码体系)
- [迁移指南](#迁移指南)
- [向后兼容策略](#向后兼容策略)

---

## 标准定义

### 响应字段

所有 API 响应统一使用以下 5 个字段：

| 字段       | 类型    | 必填 | 说明                                     |
| ---------- | ------- | ---- | ---------------------------------------- |
| `code`     | int     | 是   | 状态码，`0` 表示成功，非 0 表示失败      |
| `message`  | str     | 是   | 状态消息描述                             |
| `data`     | Any     | 否   | 响应数据，成功时返回业务数据，失败时可为空 |
| `trace_id` | str     | 否   | 链路追踪 ID，用于问题排查                |
| `timestamp`| float   | 是   | Unix 时间戳，**秒级**（精度到毫秒的小数） |

### 成功响应示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "user_id": "1001",
    "username": "yunxi"
  },
  "trace_id": "abc123def456",
  "timestamp": 1710000000.123
}
```

### 失败响应示例

```json
{
  "code": 404001,
  "message": "资源不存在",
  "data": {
    "resource": "user",
    "id": "9999"
  },
  "trace_id": "abc123def456",
  "timestamp": 1710000000.123
}
```

### 设计原则

1. **字段名统一**：使用 `trace_id`（不使用 `request_id`）
2. **时间戳单位统一**：秒级浮点数（不使用毫秒级整数）
3. **零破坏性**：所有旧实现保留为兼容别名，不删除
4. **Pydantic 优先**：基于 Pydantic v2 实现，同时兼容 v1

---

## 快速开始

### 安装/导入

```python
from shared.unified_response import (
    ApiResponse,
    success,
    error,
    ok,
    fail,
    generate_trace_id,
    from_legacy_response,
)
```

### 基本用法

```python
# 成功响应（推荐：类方法）
resp = ApiResponse.success(data={"key": "value"})
print(resp.to_dict())

# 成功响应（便捷函数）
resp = ok(data={"key": "value"}, message="操作成功")

# 错误响应（推荐：类方法）
resp = ApiResponse.error(code=400, message="参数错误")

# 错误响应（便捷函数）
resp = fail(code=500, message="服务器内部错误")

# 带 trace_id
resp = ApiResponse.success(data={}, trace_id="trace-001")

# 链式调用
resp = ApiResponse.success().with_trace_id("trace-001")
```

### 序列化与反序列化

```python
# 转为字典
d = resp.to_dict()

# 从字典重建
resp2 = ApiResponse.from_dict(d)
assert resp2.code == resp.code

# Pydantic 原生支持
json_str = resp.model_dump_json()
resp3 = ApiResponse.model_validate_json(json_str)
```

---

## API 参考

### ApiResponse 类

**基类**: `pydantic.BaseModel`

**字段**:

| 字段       | 类型         | 默认值       | 说明                           |
| ---------- | ------------ | ------------ | ------------------------------ |
| `code`     | int          | `0`          | 状态码，0 成功                 |
| `message`  | str          | `"ok"`       | 状态消息                       |
| `data`     | Optional[Any]| `None`       | 响应数据                       |
| `trace_id` | Optional[str]| `None`       | 链路追踪 ID                    |
| `timestamp`| float        | `time.time()`| Unix 时间戳（秒级）            |

**类方法**:

- `success(data=None, message="ok", trace_id=None)` - 创建成功响应
- `error(code=500, message=None, data=None, trace_id=None)` - 创建错误响应
  - 若 `message` 为 None，自动根据 `code` 查找标准消息
- `from_dict(data_dict)` - 从字典反序列化
- `from_legacy_response(legacy_dict)` - 从旧格式响应转换

**实例方法**:

- `to_dict()` - 转为标准字典
- `is_success` - 属性，判断是否成功（code == 0）
- `http_status_code` - 属性，获取对应的 HTTP 状态码
- `with_trace_id(trace_id)` - 链式设置 trace_id
- `with_data(data)` - 链式设置 data

### 便捷函数

| 函数                    | 说明                                   |
| ----------------------- | -------------------------------------- |
| `ok(data, message)`     | 创建成功响应（返回 ApiResponse 对象）  |
| `fail(code, message)`   | 创建失败响应（返回 ApiResponse 对象）  |
| `success(data, message)`| 创建成功响应（返回字典）               |
| `error(code, message)`  | 创建失败响应（返回字典）               |
| `generate_trace_id()`   | 生成 UUID4 格式的 trace_id             |
| `from_legacy_response()`| 旧格式响应转换为标准格式               |

---

## FastAPI 集成

### 中间件（推荐）

```python
from fastapi import FastAPI
from shared.unified_response import UnifiedResponseMiddleware

app = FastAPI()

app.add_middleware(
    UnifiedResponseMiddleware,
    wrap_success=False,    # 是否自动包装成功响应
    catch_exceptions=True, # 是否自动捕获异常并包装
    add_trace_header=True, # 是否在响应头添加 X-Trace-Id
    exclude_paths=["/health", "/healthz", "/ping"],
)
```

**中间件特性**:

- 自动为每个请求生成或透传 `X-Trace-Id`
- 自动捕获未处理异常并包装为标准错误响应
- 可选的成功响应自动包装
- 支持路径排除（健康检查等）

### 装饰器方式

```python
from shared.unified_response import unified_response

@app.get("/items/{item_id}")
@unified_response
def get_item(item_id: int):
    return {"item_id": item_id, "name": "test"}
```

### 异常处理器

```python
from shared.unified_response import register_unified_response_exception

# 注册到 FastAPI 应用
register_unified_response_exception(app)

# 自定义业务异常
class BusinessError(Exception):
    def __init__(self, code: int, message: str, data=None):
        self.code = code
        self.message = message
        self.data = data
```

### 路由层直接使用

```python
@app.get("/users/{user_id}", response_model=ApiResponse)
async def get_user(user_id: str):
    user = await db.get_user(user_id)
    if not user:
        return ApiResponse.error(code=404, message="用户不存在")
    return ApiResponse.success(data=user)
```

---

## 错误码体系

### HTTP 标准状态码

| 常量名               | 码值  | 说明                 |
| -------------------- | ----- | -------------------- |
| `SUCCESS`            | 0     | 成功                 |
| `HTTP_OK`            | 200   | OK                   |
| `HTTP_BAD_REQUEST`   | 400   | 请求参数错误         |
| `HTTP_UNAUTHORIZED`  | 401   | 未认证               |
| `HTTP_FORBIDDEN`     | 403   | 无权限               |
| `HTTP_NOT_FOUND`     | 404   | 资源不存在           |
| `HTTP_TOO_MANY_REQUESTS` | 429 | 请求过于频繁         |
| `HTTP_INTERNAL_ERROR`| 500   | 服务器内部错误       |
| `HTTP_SERVICE_UNAVAILABLE` | 503 | 服务不可用       |

### 业务错误码区间（6 位编码）

6 位错误码格式：`XX YY ZZZ`

- **XX**：模块编号（01-99）
- **YY**：错误类别（00=通用, 01=参数, 02=认证, 03=权限, 04=业务, 05=资源）
- **ZZZ**：顺序号（001-999）

| 区间       | 模块             |
| ---------- | ---------------- |
| 00 00 000  | 通用/系统        |
| 08 00 000  | M8 控制塔        |
| 10 00 000  | M10 系统卫士     |
| 12 00 000  | M12 安全护盾     |
| 04 00 000  | M4 场景引擎      |
| 01 00 000  | API-Gateway      |

### 常用工具函数

```python
from shared.unified_response import (
    get_standard_message,
    get_http_status,
    HTTP_OK,
    HTTP_NOT_FOUND,
)

# 根据错误码获取标准消息
msg = get_standard_message(404)  # "Not Found"

# 根据错误码获取 HTTP 状态码
status = get_http_status(100403)  # 403
```

---

## 迁移指南

### 从旧模块迁移

#### 1. M8 控制塔 (schemas.common)

```python
# 旧导入（仍可用，但已标记弃用）
from schemas.common import ApiResponse, ApiResponseCompat

# 新导入（推荐）
from shared.unified_response import ApiResponse
```

**字段变化**:
- `request_id` → `trace_id`
- `timestamp` (int, 毫秒) → `timestamp` (float, 秒)

**兼容方式**:
- `LegacyApiResponse` 保留旧字段格式（request_id + 毫秒级时间戳）
- `ApiResponseCompat` 同时包含新旧字段

#### 2. M10 系统卫士 (api.response)

```python
# 旧导入（仍可用）
from m10_system_guard.api.response import success, error, make_response

# 新导入（推荐）
from shared.unified_response import ok, fail, ApiResponse
```

**字段变化**:
- 已自动添加 `trace_id` 和 `timestamp` 字段
- 返回格式从 3 字段升级为 5 字段标准

#### 3. M12 安全护盾 (schemas.common)

```python
# 旧导入（仍可用）
from schemas.common import ApiResponse, make_response, make_error_response

# 新导入（推荐）
from shared.unified_response import ApiResponse, ok, fail
```

**兼容方式**:
- `LegacyApiResponse` 保留 3 字段旧格式
- `make_response` / `make_error_response` 已升级为 5 字段标准格式

#### 4. M4 场景引擎 (schemas.common)

```python
# 旧导入（仍可用）
from src.schemas.common import ApiResponse, LegacyApiResponse

# 新导入（推荐）
from shared.unified_response import ApiResponse
```

#### 5. API-Gateway

```python
# Gateway 已接入 UnifiedResponseMiddleware
# 路由层可直接使用标准响应
from shared.unified_response import ApiResponse, ok, fail
```

### 从 shared/module_sdk 迁移

```python
# 旧导入（仍可用，有 DeprecationWarning）
from shared.module_sdk.models import ApiResponse

# 新导入（推荐）
from shared.unified_response import ApiResponse
```

> **注意**: `shared.module_sdk.models.ApiResponse` 已重定向到统一标准版本，
> 所有接口保持兼容。导入时会触发 `DeprecationWarning` 提示迁移。

### 旧格式转换工具

如果需要处理来自旧系统的响应，可以使用 `from_legacy_response`：

```python
from shared.unified_response import from_legacy_response

# 旧格式（request_id + 毫秒级时间戳）
legacy = {
    "code": 0,
    "message": "ok",
    "data": {"key": "value"},
    "request_id": "abc123",
    "timestamp": 1710000000000,  # 毫秒
}

# 转换为标准格式
standard = from_legacy_response(legacy)
print(standard.trace_id)     # "abc123"
print(standard.timestamp)    # 1710000000.0（秒级）
```

---

## 向后兼容策略

### 原则

1. **只新增，不删除**：旧类、旧函数一律保留
2. **别名重定向**：新代码通过别名引用标准实现
3. **渐进式迁移**：不强制一次性全部迁移
4. **弃用提示**：通过 `DeprecationWarning` 引导迁移

### 兼容层一览

| 模块                 | 旧类/函数              | 兼容方式          | 状态       |
| -------------------- | ---------------------- | ----------------- | ---------- |
| shared/module_sdk    | `ApiResponse`          | 重定向 + 警告     | 已迁移     |
| M8 控制塔            | `ApiResponse`          | 别名重定向        | 已接入     |
| M8 控制塔            | `LegacyApiResponse`    | 保留旧实现        | 向后兼容   |
| M8 控制塔            | `ApiResponseCompat`    | 保留旧实现        | 向后兼容   |
| M10 系统卫士         | `success()` / `error()`| 升级为 5 字段     | 已接入     |
| M10 系统卫士         | `make_response()`      | 保留可用          | 向后兼容   |
| M12 安全护盾         | `ApiResponse`          | 别名重定向        | 已接入     |
| M12 安全护盾         | `LegacyApiResponse`    | 保留旧实现        | 向后兼容   |
| M12 安全护盾         | `make_response()`      | 升级为 5 字段     | 已接入     |
| M4 场景引擎          | `ApiResponse`          | 别名重定向        | 已接入     |
| M4 场景引擎          | `LegacyApiResponse`    | 保留旧实现        | 向后兼容   |
| API-Gateway          | —                      | 中间件 + 工具函数 | 已接入     |

---

## 测试

运行单元测试：

```bash
cd shared
python -m pytest tests/unified_response/ -v
```

测试覆盖：
- 核心响应类（8 个用例）
- 便捷函数（3 个用例）
- 错误码常量（3 个用例）
- 旧格式兼容（4 个用例）
- FastAPI 集成（4 个用例）
- Pydantic 兼容（3 个用例）
- 模块集成验证（19 个用例，5 个模块 + SDK）

**总计：48 个测试用例，全部通过**

---

## 后续建议

### 待接入模块

以下模块尚未接入统一响应标准，建议按优先级逐步迁移：

| 优先级 | 模块               | 说明                         |
| ------ | ------------------ | ---------------------------- |
| 高     | M2 数据中台        | 核心数据服务，响应格式需统一 |
| 高     | M6 AI 大脑         | AI 服务接口较多              |
| 中     | M14 用户中心       | 用户相关接口                 |
| 中     | 通知服务           | 第三方通知接口               |
| 低     | 其他边缘模块       | 按需迁移                     |

### 最佳实践

1. **新模块直接使用**：新建模块直接从 `shared.unified_response` 导入
2. **旧模块逐步替换**：现有模块在迭代中逐步替换导入路径
3. **统一中间件**：FastAPI 服务统一接入 `UnifiedResponseMiddleware`
4. **错误码规划**：各模块按 6 位编码规范定义业务错误码
5. **链路追踪**：所有跨模块调用透传 `X-Trace-Id` 请求头
