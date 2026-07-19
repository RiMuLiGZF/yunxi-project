# M8 已弃用路由清单与迁移指南

> 版本: v0.6 (P2 体验优化 - M8 已迁移路由清理)
> 更新日期: 2026-07-19
> 维护者: M8 控制塔团队

## 概述

本文档记录 M8 控制塔中已标记为 **deprecated（弃用）** 的路由端点和兼容代码，
提供迁移指南和兼容时间表，帮助调用方平滑迁移到标准路径。

**设计原则**

- **保守策略**: 宁留勿删，不确定的一律保留
- **完全向后兼容**: 所有现有功能必须继续工作
- **弃用不等于删除**: 标记弃用，给调用方迁移时间
- **做好文档记录**: 方便后续彻底清理

---

## 一、已弃用路由列表

### 1.1 /api/system/health

| 项目 | 说明 |
|------|------|
| **路径** | `GET /api/system/health` |
| **弃用版本** | v0.6 |
| **替代路径** | `GET /m8/health`（模块间标准接口）或 `GET /health`（公开健康检查） |
| **计划删除版本** | v0.7 |
| **清理理由** | 与公开 `/health` 功能重复，且受 JWT 鉴权保护不适合作为健康检查端点 |
| **影响范围** | M8 内部前端代码、第三方监控系统（如有配置此路径） |
| **弃用标记** | `DeprecationWarning` + 日志 WARNING + 响应中 `_deprecated: true` |

**响应变化**：响应 data 中新增 `_deprecated: true` 和 `_replacement: "/m8/health"` 字段，功能完全不变。

### 1.2 /api/system/notices

| 项目 | 说明 |
|------|------|
| **路径** | `GET /api/system/notices` |
| **弃用版本** | v0.6 |
| **替代路径** | `GET /api/system/announcements` |
| **计划删除版本** | v0.7 |
| **清理理由** | 旧路径命名遗留，与 `announcements` 系列端点不一致 |
| **影响范围** | 旧版前端代码 |
| **弃用标记** | `DeprecationWarning` + 日志 WARNING |

### 1.3 /api/system/modules/* 系列（共 8 个端点）

模块管理功能已统一迁移到 `/api/modules/*` 路径（见 `routers/modules.py`），
以下旧路径保留用于向后兼容。

| 旧路径 | 方法 | 替代路径 | 计划删除版本 |
|--------|------|----------|-------------|
| `/api/system/modules` | GET | `GET /api/modules/` | v0.8 |
| `/api/system/modules/{key}` | GET | `GET /api/modules/{key}` | v0.8 |
| `/api/system/modules/{key}/start` | POST | `POST /api/modules/registry/{key}/enable` 或进程管理接口 | v0.8 |
| `/api/system/modules/{key}/stop` | POST | `POST /api/modules/registry/{key}/disable` 或进程管理接口 | v0.8 |
| `/api/system/modules/{key}/restart` | POST | 对应 modules.py 中的重启接口 | v0.8 |
| `/api/system/modules/batch-start` | POST | `/api/modules/registry/*` 批量操作 | v0.8 |
| `/api/system/modules/batch-stop` | POST | `/api/modules/registry/*` 批量操作 | v0.8 |
| `/api/system/modules/status/realtime` | GET | `GET /api/monitor/modules` 或 `GET /api/ops/modules` | v0.8 |

| 项目 | 说明 |
|------|------|
| **弃用版本** | v0.6 |
| **清理理由** | 模块管理主入口已统一为 `/api/modules/*`（P1-3 完成），旧路径功能重复 |
| **影响范围** | 旧版前端、外部脚本直接调用 system 路径 |
| **弃用标记** | `DeprecationWarning` + 日志 WARNING |

### 1.4 monitor.py 向后兼容薄封装函数（内部函数）

| 函数名 | 替代方法 | 计划删除版本 |
|--------|----------|-------------|
| `_get_system_metrics()` | `monitor_service.get_system_metrics()` | v0.8 |
| `_collect_history_point()` | `monitor_service.collect_history_point()` | v0.8 |
| `_start_history_collector()` | `monitor_service.start_collector()` | v0.8 |
| `_get_history_data(period)` | `monitor_service.get_history_data(period)` | v0.8 |

| 项目 | 说明 |
|------|------|
| **弃用版本** | v0.6 |
| **清理理由** | 历史数据采集已由 MonitorService 类统一管理（线程安全），旧函数为薄封装 |
| **影响范围** | M8 内部代码（其他模块引用这些函数的地方） |
| **弃用标记** | `DeprecationWarning` |

---

## 二、保留不清理的项及原因

### 2.1 /health 公开健康检查端点

- **文件**: `services/health_service.py` (`register_public_health_endpoint`)
- **路径**: `GET /health`
- **保留原因**: 外部监控系统（Prometheus、负载均衡器、K8s liveness/readiness probe）依赖此路径
- **状态**: 保留，不计划删除
- **说明**: 模块间调用请使用 `/m8/health` 标准路径

### 2.2 OpsStatusAggregator /health 降级逻辑

- **文件**: `services/ops_status_aggregator.py` (`_refresh_module` 方法)
- **保留原因**: 老模块可能仍未迁移到 `/m8/health`，降级逻辑保证系统可用
- **状态**: 保留，计划 v1.0 评估是否移除
- **说明**: 降级时已记录 WARNING 日志，可用于追踪未迁移模块

### 2.3 ModuleClient.health_check /health 降级逻辑

- **文件**: `shared/business/module_client.py` (`health_check` 方法)
- **保留原因**: 同上，与 OpsStatusAggregator 保持一致的降级策略
- **状态**: 保留，计划 v1.0 评估是否移除

### 2.4 ModuleInfo.health_endpoint 默认值 "/health"

- **文件**: `shared/business/module_client.py` (`ModuleInfo.__init__`)
- **保留原因**: 配置兼容性，修改默认值可能影响已有配置
- **状态**: 保留

### 2.5 ProxyFallbackService 健康检查路径

- **文件**: `services/proxy_fallback_service.py`
- **保留原因**: M4/M5/M6 代理服务的健康检查使用 `/health`，属于模块自身的健康检查端点
- **状态**: 保留，待各模块完成 M8 标准接口迁移后再更新

### 2.6 业务模式路由的 M4 代理降级

- **文件**: `routers/` 下的 `chat.py`, `brain.py`, `review.py` 等
- **保留原因**: 业务功能的代理降级，与路由清理无关
- **状态**: 保留

---

## 三、迁移指南

### 3.1 模块健康检查迁移

**迁移前**（旧方式）:

```python
# 直接调用 /health
async with httpx.AsyncClient() as client:
    resp = await client.get(f"http://localhost:{port}/health")
```

**迁移后**（标准方式）:

```python
# 优先使用 /m8/health，支持降级
from shared.business.module_client import get_module_registry

registry = get_module_registry()
client = registry.get_client("m1")
is_healthy = await client.health_check()  # 自动处理 /m8/health → /health 降级
```

或直接使用标准路径:

```python
async with httpx.AsyncClient() as client:
    resp = await client.get(f"http://localhost:{port}/m8/health",
                            headers={"X-M8-Token": token})
```

### 3.2 模块管理接口迁移

**迁移前**:

```javascript
// 获取模块列表
GET /api/system/modules

// 启动模块
POST /api/system/modules/m1/start
```

**迁移后**:

```javascript
// 获取模块列表（带实时状态）
GET /api/modules/

// 模块详情
GET /api/modules/m1

// 健康检查
GET /api/modules/m1/health

// 注册表管理
GET /api/modules/registry/list
POST /api/modules/registry/m1/enable
POST /api/modules/registry/m1/disable
```

### 3.3 系统公告迁移

**迁移前**:
```
GET /api/system/notices
```

**迁移后**:
```
GET /api/system/announcements
```

### 3.4 监控指标函数迁移

**迁移前**（旧函数）:

```python
from routers.monitor import _get_system_metrics, _get_history_data

metrics = _get_system_metrics()
history = _get_history_data("1h")
```

**迁移后**（标准方式）:

```python
from services.monitor_service import get_monitor_service

monitor_service = get_monitor_service()
metrics = monitor_service.get_system_metrics()
history = monitor_service.get_history_data("1h")
```

---

## 四、兼容时间表

### 4.1 版本路线图

| 版本 | 状态 | 说明 |
|------|------|------|
| v0.5 | 已完成 | P1-3: 运维调用路径统一，所有模块迁移到 /m8/health |
| v0.6（当前） | 进行中 | P2: 标记弃用旧路由，添加警告日志，功能完全保留 |
| v0.7 | 计划 | 移除 /api/system/health、/api/system/notices 等低风险端点 |
| v0.8 | 计划 | 移除 /api/system/modules/* 系列端点、monitor.py 旧函数 |
| v1.0 | 计划 | 评估是否移除 /health 降级逻辑（取决于所有模块迁移进度） |

### 4.2 弃用告警级别

| 阶段 | 日志级别 | Python Warning | 响应头 | 说明 |
|------|----------|---------------|--------|------|
| v0.6 弃用标记 | WARNING | `DeprecationWarning` | 无 | 首次标记，提醒迁移 |
| v0.7 宽限期 | WARNING | `DeprecationWarning` | `X-Deprecated: true` | 继续提醒，添加响应头 |
| v0.8 移除候选 | ERROR | `DeprecationWarning` | `X-Deprecated: true, X-Removal-Version: v0.8` | 强提醒，准备移除 |
| v1.0 正式移除 | - | - | 410 Gone | 彻底移除，返回 410 |

---

## 五、如何检测未迁移调用

### 5.1 日志监控

所有已弃用端点被调用时，会输出 WARNING 级别的日志:

```
[DEPRECATED] /api/system/health 已弃用，请使用 /m8/health（标准接口）或 /health（公开接口）
```

可通过以下方式监控:

```bash
# 统计弃用接口调用次数
grep -c "DEPRECATED" logs/m8.log
```

### 5.2 Python warnings 捕获

```python
import warnings

# 捕获所有弃用警告
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    # 调用被弃用的函数...
    for warning in w:
        if issubclass(warning.category, DeprecationWarning):
            print(f"弃用警告: {warning.message}")
```

### 5.3 响应字段检测

部分弃用端点在响应 data 中添加了 `_deprecated: true` 字段，可用于程序化检测:

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "status": "healthy",
    "_deprecated": true,
    "_replacement": "/m8/health"
  }
}
```

---

## 六、相关文档

- [M8 架构文档](./M8_ARCHITECTURE.md)
- [迁移状态](./migration_status.md)
- P1-3 运维调用路径统一方案（见 M8 职责拆分第一阶段清理报告）

---

## 七、变更记录

| 日期 | 版本 | 变更内容 | 变更人 |
|------|------|----------|--------|
| 2026-07-19 | v0.6 | 首次创建，标记 v0.6 弃用端点列表 | M8 控制塔团队 |
