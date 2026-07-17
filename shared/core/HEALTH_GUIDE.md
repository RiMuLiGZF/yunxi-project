# 云汐健康检查与可观测性规范

> 第三阶段：可观测性体系完善与健康检查标准化

## 目录

1. [健康检查规范](#健康检查规范)
2. [指标命名规范](#指标命名规范)
3. [各模块接入指南](#各模块接入指南)
4. [Prometheus 集成指南](#prometheus-集成指南)
5. [API 参考](#api-参考)

---

## 健康检查规范

### 响应格式

所有模块的健康检查接口必须返回统一的 JSON 格式：

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "module": "m8-control-tower",
  "timestamp": "2024-01-01T00:00:00Z",
  "uptime_seconds": 3600,
  "checks": {
    "database": {
      "status": "healthy",
      "response_time_ms": 5
    },
    "redis": {
      "status": "healthy",
      "response_time_ms": 2
    },
    "memory": {
      "status": "healthy",
      "percent": 45.2,
      "used_mb": 2048,
      "total_mb": 4096
    },
    "disk": {
      "status": "healthy",
      "free_gb": 50,
      "percent": 60.5
    }
  }
}
```

### 字段说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `status` | string | 是 | 整体健康状态：`healthy` / `degraded` / `unhealthy` |
| `version` | string | 是 | 模块版本号 |
| `module` | string | 是 | 模块标识（如 `m8`, `m9`, `gateway`） |
| `timestamp` | string | 是 | ISO 8601 格式的时间戳（UTC） |
| `uptime_seconds` | number | 是 | 服务运行时间（秒） |
| `checks` | object | 否 | 各检查项的详细结果，键为检查项名称 |

### 健康状态定义

| 状态 | 含义 | HTTP 状态码 |
|------|------|------------|
| `healthy` | 所有检查项正常，系统完全可用 | 200 |
| `degraded` | 部分非核心检查失败，核心功能仍可用 | 200 |
| `unhealthy` | 核心检查失败，系统无法正常提供服务 | 503 |

### 状态汇总规则

健康检查的整体状态根据以下规则汇总：

1. **任一核心（critical）检查项为 `unhealthy`** → 整体 `unhealthy`
2. **任一非核心检查项为 `degraded` 或 `unhealthy`** → 整体 `degraded`
3. **所有检查项为 `healthy`** → 整体 `healthy`

### 检查模式

#### 轻量检查（默认）

- 路径：`/health`
- 只检查自身状态和轻量依赖
- 响应时间要求：< 100ms
- 典型检查项：内存、磁盘、自身进程状态

#### 深度检查

- 路径：`/health?deep=true`
- 检查所有依赖项
- 响应时间要求：< 5s
- 典型检查项：数据库、Redis、外部服务、下游模块

---

## 指标命名规范

### 命名规则

指标名称遵循以下格式：

```
{namespace}_{module}_{metric_name}_{unit}
```

- **namespace**: 命名空间，统一为 `yunxi`
- **module**: 模块名，如 `m8`, `m9`, `gateway`
- **metric_name**: 指标名称，使用 snake_case
- **unit**: 单位（可选），如 `seconds`, `bytes`, `total`

### 示例

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `yunxi_m8_requests_total` | Counter | M8 总请求数 |
| `yunxi_m8_request_duration_seconds` | Histogram | M8 请求延迟（秒） |
| `yunxi_m8_errors_total` | Counter | M8 错误总数 |
| `yunxi_m8_active_requests` | Gauge | M8 活跃请求数 |
| `yunxi_m8_memory_usage_bytes` | Gauge | M8 内存使用（字节） |
| `yunxi_m8_slow_requests_total` | Counter | M8 慢请求总数 |

### 标签规范

标签使用小写字母和下划线，常见标签：

| 标签名 | 说明 | 示例值 |
|--------|------|--------|
| `method` | HTTP 方法 | `GET`, `POST` |
| `path` | 请求路径 | `/api/users` |
| `status` | 状态码 | `200`, `404`, `500` |
| `status_class` | 状态码分类 | `2xx`, `4xx`, `5xx` |
| `module` | 模块名 | `m8`, `m9` |
| `le` | 直方图桶上限（Prometheus 内置） | `0.1`, `1.0`, `+Inf` |

### 标准指标集合

每个模块应至少提供以下标准指标：

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `{module}_requests_total` | Counter | 总请求数 |
| `{module}_requests_duration_seconds` | Histogram | 请求延迟分布 |
| `{module}_errors_total` | Counter | 错误请求数 |
| `{module}_active_requests` | Gauge | 当前活跃请求数 |
| `{module}_memory_usage_bytes` | Gauge | 内存使用量 |
| `{module}_slow_requests_total` | Counter | 慢请求数 |
| `{module}_request_latency_summary` | Summary | 请求延迟摘要（含分位数） |

---

## 各模块接入指南

### 快速接入（推荐）

使用 `create_observability_router` 一键创建标准化的健康检查和指标端点。

```python
from shared.core.observability import create_observability_router

# 最简方式：只有内存和磁盘检查
obs_router = create_observability_router(
    service_name="m9",
    version="1.0.0",
)
app.include_router(obs_router)

# 带数据库检查
obs_router = create_observability_router(
    service_name="m9",
    version="1.0.0",
    db_session_factory=SessionLocal,  # SQLAlchemy 会话工厂
)
app.include_router(obs_router)

# 带数据库和 Redis 检查
obs_router = create_observability_router(
    service_name="m9",
    version="1.0.0",
    db_session_factory=SessionLocal,
    redis_client=redis_client,  # Redis 客户端实例
)
app.include_router(obs_router)
```

### 自定义健康检查

如需添加模块特有的检查项，可手动创建 `HealthChecker`：

```python
from shared.core.observability import HealthChecker, create_observability_router
from shared.core.health import CheckResult

# 创建健康检查器
checker = HealthChecker(
    module_name="m9",
    version="1.0.0",
    module_display_name="开发工坊",
)

# 注册内置检查
checker.register_memory_check(threshold_percent=90.0, lightweight=True)
checker.register_disk_check(path=".", threshold_percent=90.0, lightweight=True)
checker.register_database_check(session_factory=SessionLocal, critical=True)
checker.register_redis_check(redis_client=redis, critical=False)

# 注册自定义检查（同步）
def check_my_service() -> CheckResult:
    start_t = time.time()
    try:
        result = my_service.ping()
        resp_ms = (time.time() - start_t) * 1000
        if result:
            return CheckResult.healthy(
                detail1="value1",
                response_time_ms=resp_ms,
            )
        return CheckResult.degraded(
            error="service not responding",
            response_time_ms=resp_ms,
        )
    except Exception as e:
        resp_ms = (time.time() - start_t) * 1000
        return CheckResult.unhealthy(
            error=str(e),
            response_time_ms=resp_ms,
        )

checker.register_check(
    "my_service",
    check_my_service,
    critical=True,       # 是否核心依赖
    lightweight=False,   # 是否轻量检查（默认即执行）
)

# 注册自定义检查（异步）
async def check_external_api() -> CheckResult:
    start_t = time.time()
    try:
        result = await external_api.ping()
        resp_ms = (time.time() - start_t) * 1000
        return CheckResult.healthy(response_time_ms=resp_ms)
    except Exception as e:
        resp_ms = (time.time() - start_t) * 1000
        return CheckResult.degraded(error=str(e), response_time_ms=resp_ms)

checker.register_async_check(
    "external_api",
    check_external_api,
    critical=False,
    lightweight=False,
)

# 创建路由
obs_router = create_observability_router(
    service_name="m9",
    version="1.0.0",
    health_checker=checker,
)
app.include_router(obs_router)
```

### 自定义指标

```python
from shared.core.observability import get_metrics

metrics = get_metrics()

# 计数器
metrics.inc_counter("my_custom_counter", labels={"type": "login"})

# 仪表盘
metrics.set_gauge("my_custom_gauge", 42.0, labels={"env": "prod"})

# 直方图
metrics.observe_histogram("my_latency", 0.123, labels={"endpoint": "/api/users"})

# 摘要（支持分位数）
metrics.observe_summary("my_summary", 0.456)

# 获取延迟百分位
percentiles = metrics.get_latency_percentiles("m8")
print(percentiles["tp50_ms"], percentiles["tp99_ms"])
```

### 中间件集成

使用 `ObservabilityMiddleware` 自动收集请求指标：

```python
from shared.core.observability import ObservabilityMiddleware

app.add_middleware(
    ObservabilityMiddleware,
    service_name="m8",
    slow_request_threshold=3.0,
    exclude_paths=["/health", "/metrics"],
)
```

中间件自动收集以下指标：
- 请求总数（按状态码分类）
- 请求延迟（直方图 + 摘要）
- 错误数
- 慢请求数

---

## Prometheus 集成指南

### 抓取配置

在 Prometheus 的 `prometheus.yml` 中添加云汐模块的抓取配置：

```yaml
scrape_configs:
  # API 网关
  - job_name: 'yunxi-gateway'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s

  # M8 控制塔
  - job_name: 'yunxi-m8'
    static_configs:
      - targets: ['localhost:8001']
    metrics_path: '/metrics'
    scrape_interval: 15s

  # M9 开发工坊
  - job_name: 'yunxi-m9'
    static_configs:
      - targets: ['localhost:8002']
    metrics_path: '/metrics'
    scrape_interval: 15s

  # M10 系统卫士
  - job_name: 'yunxi-m10'
    static_configs:
      - targets: ['localhost:8010']
    metrics_path: '/metrics'
    scrape_interval: 15s

  # M11 MCP 总线
  - job_name: 'yunxi-m11'
    static_configs:
      - targets: ['localhost:8011']
    metrics_path: '/metrics'
    scrape_interval: 15s

  # M12 安全盾
  - job_name: 'yunxi-m12'
    static_configs:
      - targets: ['localhost:8012']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### 常用 PromQL 查询

#### 请求速率

```promql
# 每秒请求数（5 分钟速率）
rate(yunxi_m8_requests_total[5m])

# 按状态码分类的请求速率
sum by (status_class) (rate(yunxi_m8_requests_total[5m]))
```

#### 错误率

```promql
# 错误率（5xx / 总请求）
sum(rate(yunxi_m8_requests_total{status_class="5xx"}[5m]))
/
sum(rate(yunxi_m8_requests_total[5m]))
```

#### 延迟

```promql
# p50 延迟（从直方图计算）
histogram_quantile(0.5, sum by (le) (rate(yunxi_m8_request_duration_seconds_bucket[5m])))

# p95 延迟
histogram_quantile(0.95, sum by (le) (rate(yunxi_m8_request_duration_seconds_bucket[5m])))

# p99 延迟
histogram_quantile(0.99, sum by (le) (rate(yunxi_m8_request_duration_seconds_bucket[5m])))
```

#### 内存使用

```promql
# 内存使用（字节）
yunxi_m8_memory_usage_bytes

# 内存使用（MB）
yunxi_m8_memory_usage_bytes / 1024 / 1024
```

#### 活跃请求数

```promql
# 当前活跃请求数
yunxi_m8_active_requests
```

### Grafana 面板示例

可基于以下指标创建监控面板：

1. **系统总览**：各模块 QPS、错误率、延迟
2. **请求分析**：按路径/方法/状态码的请求分布
3. **资源使用**：内存、CPU、磁盘
4. **错误监控**：错误率趋势、Top 错误接口
5. **延迟分析**：p50/p95/p99 延迟趋势

---

## API 参考

### 健康检查接口

#### GET /health

健康检查端点。

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `deep` | boolean | `false` | 是否执行深度检查 |

**响应示例（轻量）：**

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "module": "m8",
  "timestamp": "2024-01-01T00:00:00Z",
  "uptime_seconds": 3600,
  "checks": {
    "memory": {
      "status": "healthy",
      "response_time_ms": 1.2,
      "percent": 45.2,
      "used_mb": 2048,
      "total_mb": 4096
    },
    "disk": {
      "status": "healthy",
      "response_time_ms": 0.5,
      "free_gb": 50,
      "percent": 60.5
    }
  }
}
```

**响应示例（深度）：**

```json
{
  "status": "degraded",
  "version": "1.0.0",
  "module": "m8",
  "timestamp": "2024-01-01T00:00:00Z",
  "uptime_seconds": 3600,
  "checks": {
    "memory": {
      "status": "healthy",
      "response_time_ms": 1.2
    },
    "disk": {
      "status": "healthy",
      "response_time_ms": 0.5
    },
    "database": {
      "status": "healthy",
      "response_time_ms": 5.3
    },
    "redis": {
      "status": "degraded",
      "response_time_ms": 100.5,
      "error": "connection timeout"
    }
  }
}
```

### 指标接口

#### GET /metrics

Prometheus 文本格式的指标端点。

**响应格式：**

```
# HELP yunxi_m8_requests_total Total number of HTTP requests for m8
# TYPE yunxi_m8_requests_total counter
yunxi_m8_requests_total{status="2xx"} 1027
yunxi_m8_requests_total{status="4xx"} 42
yunxi_m8_requests_total{status="5xx"} 3

# HELP yunxi_m8_request_duration_seconds HTTP request duration in seconds for m8
# TYPE yunxi_m8_request_duration_seconds histogram
yunxi_m8_request_duration_seconds_bucket{le="0.005"} 0
yunxi_m8_request_duration_seconds_bucket{le="0.01"} 10
yunxi_m8_request_duration_seconds_bucket{le="0.1"} 500
yunxi_m8_request_duration_seconds_bucket{le="1.0"} 950
yunxi_m8_request_duration_seconds_bucket{le="+Inf"} 1072
yunxi_m8_request_duration_seconds_sum 45.23
yunxi_m8_request_duration_seconds_count 1072
```

---

## 已接入模块列表

| 模块 | 健康检查 | 指标端点 | 深度检查 | 接入方式 |
|------|----------|----------|----------|----------|
| API-Gateway | ✅ /health | ✅ /metrics | ✅ | create_observability_router |
| M8 控制塔 | ✅ /health | ✅ /metrics | ✅ | 自定义 HealthChecker |
| M9 开发工坊 | ✅ /health | ✅ /metrics | ✅ | 自定义 HealthChecker |
| M10 系统卫士 | ✅ /health | ✅ /metrics | ✅ | 自定义 HealthChecker |
| M11 MCP 总线 | ✅ /health | ✅ /metrics | ✅ | 自定义 HealthChecker |
| M12 安全盾 | ✅ /api/m12/status/health | - | ✅ | 自定义 HealthChecker |

---

## 性能注意事项

1. **指标收集性能**：各指标独立加锁，不会成为瓶颈
2. **健康检查缓存**：深度检查结果不缓存，每次请求实时计算
3. **轻量检查优化**：轻量检查只执行快速操作，确保响应 < 100ms
4. **指标精度**：Summary 使用滑动窗口（默认 10000 条），内存占用可控
5. **Prometheus 抓取**：建议抓取间隔 15s 以上，避免对服务造成压力

---

## 向后兼容

- 所有模块的旧 `/health` 端点保持不变，返回原有格式
- 新增的标准化健康检查遵循统一规范
- 旧有 M8 标准接口（`/m8/health`, `/m8/metrics`, `/m8/config`）保持不变
- 如 shared 库不可用，所有模块自动回退到本地实现
