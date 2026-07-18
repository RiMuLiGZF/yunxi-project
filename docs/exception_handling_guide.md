# 云汐系统异常处理规范

> 版本: v1.0
> 适用范围: M1~M12 所有模块
> 维护者: 云汐架构组

---

## 1. 为什么需要异常处理规范

良好的异常处理是系统可观测性、可维护性和可靠性的基石。不规范的异常处理（如空捕获、裸 `except Exception`、catch-and-rethrow 无日志）会导致：

- 问题难以定位（堆栈丢失、上下文不足）
- 静默失败（业务异常被吞没，用户无感知）
- 错误码混乱（前端无法根据错误类型做差异化处理）
- 系统脆弱（一个模块故障导致连锁反应）

本规范旨在统一云汐系统的异常处理方式，提升代码质量和可观测性。

---

## 2. 异常分类

### 2.1 预期内异常（A 类）

**定义：** 业务逻辑中可以预见的、有明确处理方式的异常。

**特征：**
- 异常类型明确（如 `FileNotFoundError`、`ValueError`、`KeyError`）
- 有明确的业务含义和处理策略
- 不应触发告警（属于正常业务分支）

**常见类型：**

| 异常类型 | 场景 | 处理方式 |
|---------|------|---------|
| `json.JSONDecodeError` | JSON 解析失败 | 返回 400 参数错误 |
| `FileNotFoundError` | 文件不存在 | 返回 404 或友好提示 |
| `KeyError` | 字典键不存在 | 参数校验或返回默认值 |
| `ValueError` | 值不合法 | 返回 400 参数错误 |
| `TypeError` | 类型错误 | 返回 400 参数错误 |
| `TimeoutError` / `asyncio.TimeoutError` | 操作超时 | 重试或返回 504 |
| `ConnectionError` / `OSError` | 网络连接失败 | 降级或返回 503 |
| `PermissionError` | 权限不足 | 返回 403 |
| `ValidationError` (自定义) | 数据校验失败 | 返回 400 |
| `NotFoundError` (自定义) | 资源不存在 | 返回 404 |
| `ConfigError` (自定义) | 配置错误 | 启动失败或降级 |

**处理原则：**
- 使用最具体的异常类型捕获
- 捕获后执行对应的业务处理逻辑
- 记录适当级别的日志（通常是 `debug` 或 `info`）

### 2.2 预期外异常（C 类 - 需要关注）

**定义：** 不应该发生的异常，通常意味着代码 bug 或系统故障。

**特征：**
- 异常类型不明确（如 `AttributeError`、`IndexError`、`TypeError` 在非预期位置）
- 需要开发人员介入排查
- 应该触发告警

**处理原则：**
- 不要静默吞掉！至少记录 `error` 级日志 + 完整堆栈
- 向上抛出或返回 500 错误
- 确保有 trace_id 便于链路追踪

### 2.3 容错兜底异常（B 类）

**定义：** 在外层使用的大粒度异常捕获，用于防止单个故障导致整个请求/进程崩溃。

**特征：**
- 包裹较大的代码块（如整个请求处理函数）
- 目的是优雅降级而非精确处理
- 通常保留 `except Exception`，但必须配合完善的日志

**处理原则：**
- 必须有 `logger.exception()` 记录完整堆栈
- 必须有明确注释说明兜底的范围和目的
- 返回友好的错误响应（不暴露内部细节）
- 考虑增加错误计数指标（metrics）
- 兜底层数不应超过 2-3 层

---

## 3. 捕获原则

### 3.1 能具体就不宽泛

**反模式：**
```python
try:
    result = json.loads(data)
except Exception:
    return None
```

**正确做法：**
```python
try:
    result = json.loads(data)
except json.JSONDecodeError:
    logger.debug("JSON 解析失败: %s", data[:100])
    return None
```

### 3.2 能早就不晚

尽早捕获并处理预期内异常，不要让异常传播到外层才处理。

**反模式：**
```python
def get_user(user_id):
    user = db.query(User).get(user_id)
    if not user:
        raise Exception("用户不存在")  # 应该用自定义异常
```

**正确做法：**
```python
def get_user(user_id):
    user = db.query(User).get(user_id)
    if not user:
        raise NotFoundError(message=f"用户 {user_id} 不存在")
```

### 3.3 不要空捕获

**反模式：**
```python
try:
    do_something()
except Exception:
    pass  # 静默失败，出了问题完全不知道
```

**正确做法：**
```python
try:
    do_something()
except (SpecificError1, SpecificError2) as e:
    logger.debug("操作失败（可接受）: %s", e)
except Exception:
    logger.exception("未预期的异常")  # 至少有日志
    raise  # 或者返回友好错误
```

### 3.4 catch-and-rethrow 必须有日志

如果捕获异常只是为了记录日志然后重新抛出，使用 `logger.exception()`。

**正确做法：**
```python
try:
    await call_external_service()
except Exception:
    logger.exception("调用外部服务失败")
    raise
```

---

## 4. 日志规范

### 4.1 日志级别选择

| 级别 | 使用场景 | 示例 |
|------|---------|------|
| `debug` | 预期内异常的详细信息，不影响功能 | JSON 解析失败（有降级）、缓存未命中 |
| `info` | 重要业务事件的异常分支 | 用户登录失败（密码错误）、模块优雅降级 |
| `warning` | 可能影响功能但不致命的异常 | 第三方服务超时后重试成功、配置项缺失使用默认值 |
| `error` | 影响功能的异常，需要关注 | 数据库连接失败、核心依赖不可用 |
| `exception` | 未预期的异常，附完整堆栈 | 兜底 `except Exception` 中使用 |

### 4.2 日志内容要求

异常日志应包含：
1. **发生了什么** - 简洁描述异常场景
2. **关键上下文** - 用户 ID、模块名、请求路径等
3. **异常信息** - 使用 `logger.exception()` 自动包含堆栈

**示例：**
```python
try:
    result = await module_client.get("m1", "/api/v1/tasks")
except Exception:
    logger.exception("获取 M1 任务列表失败 | user_id=%s | module=m1", user_id)
    raise
```

### 4.3 避免日志泄露敏感信息

- 不要记录密码、Token、API Key 等敏感数据
- 使用脱敏后的用户标识
- 异常消息中可能包含敏感信息，注意审查

---

## 5. 错误返回规范

### 5.1 统一响应格式

所有 API 错误响应遵循以下格式：

```json
{
  "code": 80401,
  "message": "模块不存在",
  "details": {
    "module_key": "m99",
    "trace_id": "abc123..."
  }
}
```

| 字段 | 说明 |
|------|------|
| `code` | 6 位错误码（见错误码规范） |
| `message` | 面向用户的友好错误消息 |
| `details` | 面向开发者的详细信息（可选） |
| `details.trace_id` | 请求追踪 ID，用于日志排查 |

### 5.2 错误码规范

6 位错误码格式：`XX YY ZZ`

- **XX**（前 2 位）：模块编号
  - `00` = 系统通用
  - `01`~`12` = M1~M12
- **YY**（中间 2 位）：错误类别
  - `01` = 参数错误 (400)
  - `02` = 认证错误 (401)
  - `03` = 权限错误 (403)
  - `04` = 资源不存在 (404)
  - `05` = 业务错误 (409)
  - `06` = 系统错误 (500)
  - `07` = 第三方错误 (502)
  - `08` = 限流错误 (429)
  - `09` = 数据错误 (409)
- **ZZ**（后 2 位）：具体错误序号

### 5.3 HTTP 状态码映射

| 错误类别 | HTTP 状态码 | 说明 |
|---------|------------|------|
| 参数错误 | 400 | 请求参数不合法 |
| 认证错误 | 401 | 未认证或 Token 无效 |
| 权限错误 | 403 | 已认证但无权限 |
| 资源不存在 | 404 | 请求的资源不存在 |
| 业务错误 | 409 | 业务规则冲突 |
| 系统错误 | 500 | 服务器内部错误 |
| 第三方错误 | 502 | 上游服务异常 |
| 服务不可用 | 503 | 服务暂时不可用 |
| 超时 | 504 | 请求超时 |
| 限流 | 429 | 请求频率超限 |

---

## 6. 标准异常类型

所有模块应优先使用 `shared.core.errors` 中的标准异常类型。

### 6.1 基类

| 异常类 | 说明 | 默认错误码 | 默认 HTTP 状态码 |
|--------|------|-----------|----------------|
| `YunxiError` | 所有自定义异常的基类 | `000601` (内部错误) | 500 |

### 6.2 常用异常

| 异常类 | 说明 | 默认错误码 | 默认 HTTP 状态码 |
|--------|------|-----------|----------------|
| `ValidationError` | 参数验证失败 | `000101` | 400 |
| `AuthenticationError` | 认证失败 | `000201` | 401 |
| `AuthorizationError` | 权限不足 | `000301` | 403 |
| `NotFoundError` | 资源不存在 | `000401` | 404 |
| `BusinessError` | 业务逻辑错误 | `000501` | 409 |
| `SystemError` | 系统内部错误 | `000601` | 500 |
| `ConfigError` | 配置错误 | `000604` | 500 |
| `ServiceUnavailableError` | 服务不可用 | `000602` | 503 |
| `TimeoutError` / `YunxiTimeoutError` | 操作超时 | `000603` | 504 |
| `RateLimitError` | 限流 | `000801` | 429 |
| `ThirdPartyError` | 第三方服务错误 | `000701` | 502 |
| `DependencyError` | 依赖服务错误 | `000605` | 502 |
| `DataError` | 数据错误 | `000901` | 409 |
| `ModuleNotFoundError` | 模块不存在 | `000403` | 404 |
| `ModuleCallError` | 模块调用失败 | `000704` | 502 |

### 6.3 使用示例

```python
from shared.core.errors import NotFoundError, ValidationError

def get_module(module_key: str):
    module = registry.get(module_key)
    if not module:
        raise NotFoundError(
            message=f"模块 {module_key} 不存在",
            details={"module_key": module_key}
        )
    return module

def validate_config(config: dict):
    if "name" not in config:
        raise ValidationError(
            message="缺少必填字段 name",
            details={"field": "name"}
        )
```

---

## 7. 常见异常类型对照表

### 7.1 Python 内置异常 → 标准异常映射

| 内置异常 | 对应标准异常 | 典型场景 |
|---------|-------------|---------|
| `ValueError` | `ValidationError` | 参数值不合法 |
| `TypeError` | `ValidationError` | 参数类型错误 |
| `KeyError` | `ValidationError` / `NotFoundError` | 键不存在 |
| `IndexError` | `ValidationError` | 索引越界 |
| `json.JSONDecodeError` | `ValidationError` | JSON 解析失败 |
| `FileNotFoundError` | `NotFoundError` | 文件不存在 |
| `PermissionError` | `AuthorizationError` | 文件权限不足 |
| `OSError` | `DependencyError` / `SystemError` | 系统调用失败 |
| `ConnectionError` | `DependencyError` | 网络连接失败 |
| `TimeoutError` / `asyncio.TimeoutError` | `TimeoutError` | 操作超时 |
| `ImportError` / `ModuleNotFoundError` | `ConfigError` / `SystemError` | 模块导入失败 |
| `AttributeError` | `SystemError` | 属性不存在（通常是 bug） |

### 7.2 HTTP 状态码 → 标准异常映射

| HTTP 状态码 | 对应标准异常 | 说明 |
|------------|-------------|------|
| 400 | `ValidationError` | 坏请求 |
| 401 | `AuthenticationError` | 未认证 |
| 403 | `AuthorizationError` | 禁止访问 |
| 404 | `NotFoundError` | 资源不存在 |
| 409 | `BusinessError` / `DataError` | 冲突 |
| 429 | `RateLimitError` | 请求过多 |
| 500 | `SystemError` | 服务器内部错误 |
| 502 | `ThirdPartyError` / `DependencyError` | 网关错误 |
| 503 | `ServiceUnavailableError` | 服务不可用 |
| 504 | `TimeoutError` | 网关超时 |

---

## 8. 反模式（Anti-Patterns）

### 8.1 空 except

```python
# ❌ 反模式
try:
    do_something()
except:
    pass

# ❌ 反模式
try:
    do_something()
except Exception:
    pass
```

**危害：** 完全吞没异常，出了问题无从排查。

**正确做法：** 至少加 `logger.debug()`，如果是兜底用 `logger.exception()`。

### 8.2 裸 except Exception 无注释无日志

```python
# ❌ 反模式
try:
    result = process(data)
except Exception as e:
    return {"error": str(e)}
```

**危害：** 不知道为什么用宽泛捕获，没有堆栈日志。

**正确做法：**
```python
try:
    result = process(data)
except (ValueError, TypeError) as e:
    # 预期内：数据格式错误
    logger.debug("数据处理失败: %s", e)
    return {"error": "数据格式错误"}
except Exception:
    # 兜底：防止未预期异常导致接口崩溃
    logger.exception("数据处理未预期错误")
    return {"error": "处理失败，请稍后重试"}
```

### 8.3 catch-and-rethrow 无日志

```python
# ❌ 反模式
try:
    call_service()
except Exception:
    raise  # 等于没捕获，还多了一层栈
```

**危害：** 没有任何价值，反而增加调用栈深度。

**正确做法：** 要么不捕获直接抛，要么捕获加日志再抛。

```python
try:
    call_service()
except Exception:
    logger.exception("服务调用失败")
    raise
```

### 8.4 异常消息中包含敏感信息

```python
# ❌ 反模式
raise ValueError(f"密码错误: {password}")
```

**危害：** 敏感信息可能泄露到日志或前端。

**正确做法：** 不记录敏感数据，使用脱敏标识。

### 8.5 异常控制流

```python
# ❌ 反模式 - 用异常做正常流程控制
try:
    user = users[key]
except KeyError:
    user = create_user(key)
```

**危害：** 异常开销大，代码意图不清晰。

**正确做法：** 使用条件判断。

```python
if key in users:
    user = users[key]
else:
    user = create_user(key)
```

---

## 9. 模块级异常定义

各模块可以在 `errors.py` 中定义模块特有的异常类型和错误码，应继承自 `YunxiError` 并使用模块前缀错误码。

**示例（M8 控制塔）：**
```python
from shared.core.errors import YunxiError, ModuleCode, build_error_code, ErrorCategory

class M8ErrorCode:
    MODULE_NOT_FOUND = build_error_code(ModuleCode.M8, ErrorCategory.NOT_FOUND, 1)
    MODULE_START_FAILED = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 1)

class ModuleStartError(YunxiError):
    def __init__(self, message=None, details=None):
        super().__init__(
            message=message or "模块启动失败",
            code=M8ErrorCode.MODULE_START_FAILED,
            details=details
        )
```

---

## 10. 改造路线图

### 阶段 1：M8 试点（当前阶段）
- 统计 `except Exception` 分布
- 重点文件改造（modules.py、health_service.py 等）
- 建立标准异常类型和规范文档
- 目标：减少 30% 的 `except Exception`

### 阶段 2：推广到核心模块
- M1 智能体集群
- M2 技能集群
- M5 潮汐记忆
- 目标：各模块减少 30%

### 阶段 3：全系统覆盖
- 所有模块完成改造
- CI 检查：禁止新增裸 `except Exception`（lint 规则）
- 目标：全系统 `except Exception` 占比 < 10%

---

## 附录 A：相关文件

- 标准异常定义：`shared/core/errors.py`
- M8 错误码：`M8-control-tower/backend/errors.py`
- 可观测性文档：`docs/OPS.md`
- 质量路线图：`docs/QUALITY_ROADMAP.md`

---

*本文档为活文档，随实践持续更新。如有疑问或建议，请联系架构组。*
