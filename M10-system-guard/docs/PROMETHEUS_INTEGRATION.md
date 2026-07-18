# M10 Prometheus 集成文档

## 概述

M10 系统卫士提供完整的 Prometheus 指标导出功能，支持 5 大类共 30+ 指标，
覆盖系统资源、GPU、潮汐引擎、防护引擎和进程监控。同时支持与 M8 监控体系
双向打通：M8 可通过标准接口拉取 M10 指标，M10 也可主动上报指标到 M8。

## 目录

1. [指标列表](#指标列表)
2. [配置方法](#配置方法)
3. [HTTP 端点](#http-端点)
4. [Grafana 仪表盘建议](#grafana-仪表盘建议)
5. [与 M8 监控体系集成](#与-m8-监控体系集成)
6. [告警规则建议](#告警规则建议)
7. [架构说明](#架构说明)
8. [向后兼容性](#向后兼容性)

---

## 指标列表

### 系统指标 (system)

| 指标名称 | 类型 | 标签 | 说明 |
|---------|------|------|------|
| `system_cpu_percent` | Gauge | hostname | CPU 使用率 (%) |
| `system_memory_percent` | Gauge | hostname | 内存使用率 (%) |
| `system_memory_used_bytes` | Gauge | hostname | 已用内存字节数 |
| `system_memory_total_bytes` | Gauge | hostname | 总内存字节数 |
| `system_disk_percent` | Gauge | hostname | 磁盘使用率 (%) |
| `system_disk_used_bytes` | Gauge | hostname | 已用磁盘字节数 |
| `system_network_io_sent_bytes` | Gauge | hostname | 网络发送字节数 |
| `system_network_io_recv_bytes` | Gauge | hostname | 网络接收字节数 |
| `system_process_count` | Gauge | hostname | 系统进程总数 |

### GPU 指标 (gpu)

| 指标名称 | 类型 | 标签 | 说明 |
|---------|------|------|------|
| `gpu_count` | Gauge | hostname | GPU 设备数量 |
| `gpu_utilization_percent` | Gauge | hostname, gpu_id, gpu_name | GPU 利用率 (%) |
| `gpu_memory_percent` | Gauge | hostname, gpu_id, gpu_name | GPU 显存使用率 (%) |
| `gpu_memory_used_mb` | Gauge | hostname, gpu_id, gpu_name | GPU 显存使用量 (MB) |
| `gpu_memory_total_mb` | Gauge | hostname, gpu_id, gpu_name | GPU 显存总量 (MB) |
| `gpu_temperature_celsius` | Gauge | hostname, gpu_id, gpu_name | GPU 温度 (°C) |
| `gpu_power_watts` | Gauge | hostname, gpu_id, gpu_name | GPU 功耗 (W) |

### 潮汐引擎指标 (tide)

| 指标名称 | 类型 | 标签 | 说明 |
|---------|------|------|------|
| `tide_active_tasks` | Gauge | hostname, module_name | 潮汐引擎活跃任务数 |
| `tide_completed_total` | Counter | hostname, module_name | 已完成任务总数 |
| `tide_failed_total` | Counter | hostname, module_name | 失败任务总数 |
| `tide_gpu_allocated_mb` | Gauge | hostname, gpu_id | 已分配显存 (MB) |
| `tide_scheduler_runs_total` | Counter | hostname, module_name | 调度器运行次数 |
| `tide_current_phase` | Gauge | hostname, module_name | 当前潮汐阶段 (0=涨潮,1=平潮,2=退潮,3=枯潮) |

### 防护引擎指标 (guard)

| 指标名称 | 类型 | 标签 | 说明 |
|---------|------|------|------|
| `guard_alerts_total` | Counter | hostname, level | 告警总数（按级别） |
| `guard_active_alerts` | Gauge | hostname, level | 当前活跃告警数（按级别） |
| `guard_blocked_total` | Counter | hostname, metric_type | 拦截次数 |
| `guard_circuit_breaker_state` | Gauge | hostname | 熔断器状态 (0=关闭,1=半开,2=打开) |
| `guard_current_level` | Gauge | hostname, metric_type | 当前防护级别 (0=info,1=warning,2=critical,3=emergency) |
| `guard_throttling_active` | Gauge | hostname | 限流是否激活 (0=否,1=是) |

### 进程指标 (process)

| 指标名称 | 类型 | 标签 | 说明 |
|---------|------|------|------|
| `process_count` | Gauge | hostname | 受监控进程总数 |
| `process_yunxi_count` | Gauge | hostname | 云汐相关进程数 |
| `process_cpu_percent` | Gauge | hostname, process_name | 进程 CPU 使用率 (%) |
| `process_memory_mb` | Gauge | hostname, process_name | 进程内存使用 (MB) |

### Exporter 自身指标 (exporter)

| 指标名称 | 类型 | 标签 | 说明 |
|---------|------|------|------|
| `exporter_up` | Gauge | hostname, module | Exporter 是否运行 |
| `exporter_collect_duration_seconds` | Gauge | hostname, module | 采集耗时 (秒) |
| `exporter_collect_total` | Counter | hostname, module | 采集总次数 |

---

## 配置方法

### 环境变量配置

所有配置通过环境变量控制，优先级：环境变量 > .env 文件 > 默认值。

```bash
# === Prometheus 指标导出 ===
# 是否启用 Prometheus 指标导出（默认: true）
M10_PROMETHEUS_ENABLED=true

# 指标采集间隔，单位秒（默认: 15）
M10_PROMETHEUS_COLLECT_INTERVAL=15

# === M8 监控主动上报 ===
# 是否启用 M8 主动上报（默认: false）
M10_M8_REPORT_ENABLED=false

# M8 上报间隔，单位秒（默认: 60）
M10_M8_REPORT_INTERVAL=60

# M8 监控中心基础 URL
M10_M8_BASE_URL=http://localhost:8008

# M8 上报鉴权 Token（可选，M8 侧需配置对应 token）
M10_M8_REPORT_TOKEN=your-secret-token
```

### Prometheus Server 配置

在 Prometheus 的 `prometheus.yml` 中添加抓取配置：

```yaml
scrape_configs:
  - job_name: 'm10-system-guard'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:8010']
    metrics_path: '/api/v1/metrics'
    # 如果启用了鉴权
    # headers:
    #   X-API-Key: 'your-api-key'
```

---

## HTTP 端点

### 标准端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/metrics` | GET | Prometheus 格式指标（标准端点） |
| `/api/v1/metrics/json` | GET | JSON 格式指标（便于调试） |
| `/api/v1/metrics/health` | GET | Exporter 健康状态 |
| `/api/v1/metrics/list` | GET | 所有已注册指标元信息 |
| `/api/v1/m8-report/status` | GET | M8 上报状态 |

### M8 标准对接端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查 |
| `/m8/metrics` | GET | M8 标准性能指标 |
| `/m8/config` | GET | M8 标准配置查询 |

### 响应示例

**Prometheus 格式** (`/api/v1/metrics`):

```
# HELP system_cpu_percent CPU 使用率 (%)
# TYPE system_cpu_percent gauge
system_cpu_percent{hostname="DESKTOP-ABC123"} 45.2
# HELP gpu_utilization_percent GPU 利用率 (%)
# TYPE gpu_utilization_percent gauge
gpu_utilization_percent{gpu_id="0",gpu_name="NVIDIA RTX 4090",hostname="DESKTOP-ABC123"} 67.8
```

**健康检查** (`/api/v1/metrics/health`):

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "status": "healthy",
    "enabled": true,
    "prometheus_available": true,
    "running": true,
    "hostname": "DESKTOP-ABC123",
    "last_collect_time": 1752825600.0,
    "collect_interval": 15,
    "metric_count": 32,
    "uptime_seconds": 120.5
  }
}
```

---

## Grafana 仪表盘建议

### 仪表盘结构

建议创建一个"M10 系统卫士"仪表盘，包含以下面板：

#### 1. 总览面板 (Overview)

- **状态卡片**：CPU、内存、磁盘、GPU 使用率
- **告警状态**：各级别活跃告警数
- **系统运行时间**：uptime

PromQL 示例：
```promql
# CPU 使用率
system_cpu_percent{job="m10-system-guard"}

# 内存使用率
system_memory_percent{job="m10-system-guard"}

# 活跃告警总数
sum(guard_active_alerts{job="m10-system-guard"})
```

#### 2. GPU 监控面板

- **GPU 利用率趋势图**（按 GPU ID 分组）
- **显存使用趋势图**
- **GPU 温度监控**
- **GPU 功耗监控**

PromQL 示例：
```promql
# 所有 GPU 利用率
gpu_utilization_percent{job="m10-system-guard"}

# 单 GPU 显存使用
gpu_memory_used_mb{job="m10-system-guard", gpu_id="0"}

# GPU 温度
gpu_temperature_celsius{job="m10-system-guard"}
```

#### 3. 潮汐引擎面板

- **当前潮汐阶段**（使用 stat 面板，值映射为阶段名）
- **活跃任务数趋势**
- **任务完成速率**
- **显存分配情况**

PromQL 示例：
```promql
# 活跃任务数
tide_active_tasks{job="m10-system-guard"}

# 任务完成速率（每分钟）
rate(tide_completed_total{job="m10-system-guard"}[5m]) * 60

# 显存分配
tide_gpu_allocated_mb{job="m10-system-guard"}
```

#### 4. 防护引擎面板

- **当前防护级别**
- **告警趋势**（按级别）
- **限流状态**
- **熔断器状态**

PromQL 示例：
```promql
# 各级别活跃告警
guard_active_alerts{job="m10-system-guard"}

# 告警速率
rate(guard_alerts_total{job="m10-system-guard"}[10m])

# 限流状态
guard_throttling_active{job="m10-system-guard"}
```

#### 5. 进程监控面板

- **进程总数趋势**
- **云汐进程数**
- **Top 进程 CPU/内存排行**

PromQL 示例：
```promql
# 进程总数
process_count{job="m10-system-guard"}

# 云汐进程数
process_yunxi_count{job="m10-system-guard"}
```

### 推荐变量

- `hostname`：主机名筛选
- `gpu_id`：GPU 设备筛选
- `interval`：数据粒度选择

---

## 与 M8 监控体系集成

### 集成架构

M10 与 M8 监控体系支持双向集成：

```
┌─────────────────┐         HTTP 拉取          ┌─────────────────┐
│   M8 监控中心    │ ◄──────────────────────── │  M10 系统卫士   │
│  (monitor.py)   │    /api/v1/status/metrics │  (system_monitor)│
└─────────────────┘                            └─────────────────┘
          │                                              ▲
          │ HTTP 上报 (可选)                             │
          └──────────────────────────────────────────────┘
                    M10 主动上报到 M8
```

### 方式一：M8 主动拉取（推荐）

M8 监控中心已内置从 M10 拉取增强指标的逻辑，位于
`M8-control-tower/backend/routers/monitor.py` 的 `/metrics/realtime` 接口。

M8 通过 HTTP GET 请求 `http://m10-host:8010/api/v1/status/metrics`
获取 M10 的增强硬件指标（GPU、温度等），并合并到自身的监控数据中。

**优势：**
- 由 M8 控制采集频率
- M10 无需额外配置
- 故障隔离：M10 不可用时 M8 正常运行

### 方式二：M10 主动上报（可选）

M10 可配置主动将指标推送到 M8 监控中心，适用于需要实时告警的场景。

**配置步骤：**

1. 在 M10 的 `.env` 文件中启用上报：

```bash
M10_M8_REPORT_ENABLED=true
M10_M8_REPORT_INTERVAL=60
M10_M8_BASE_URL=http://m8-host:8008
M10_M8_REPORT_TOKEN=your-shared-token
```

2. M8 侧需提供指标接收接口（建议路径：`/api/v1/monitor/metrics/receive`）

**上报数据格式：**

```json
{
  "module": "m10",
  "module_name": "系统卫士",
  "hostname": "DESKTOP-ABC123",
  "timestamp": 1752825600.0,
  "metrics": {
    "cpu": {
      "usage_percent": 45.2,
      "core_count": 16,
      "load_avg_1min": 3.5
    },
    "memory": {
      "usage_percent": 62.5,
      "used_mb": 10240.0,
      "total_mb": 16384.0
    },
    "gpu": {
      "count": 1,
      "usage_percent": 67.8,
      "memory_percent": 45.3,
      "temperature_celsius": 72.5,
      "power_watt": 280.0
    },
    "guard": {
      "overall_level": "info",
      "total_alerts": 5,
      "throttling_active": false
    }
  }
}
```

### M8 侧接口 TODO

M8 监控中心目前通过拉取方式获取 M10 数据。如需支持 M10 主动上报，
建议在 M8 侧添加以下接口（M10 侧已按此格式准备）：

- **POST `/api/v1/monitor/metrics/receive`** - 接收模块上报的指标数据
- 请求体：见上方上报数据格式
- 鉴权：`X-M8-Token` 请求头
- 返回：标准 `ApiResponse` 格式

---

## 告警规则建议

以下是建议的 Prometheus AlertManager 告警规则：

```yaml
groups:
  - name: m10-system-alerts
    rules:
      # CPU 告警
      - alert: M10_CPU_High
        expr: system_cpu_percent{job="m10-system-guard"} > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "M10 CPU 使用率过高"
          description: "CPU 使用率已达 {{ $value }}%，超过 85% 阈值"

      - alert: M10_CPU_Critical
        expr: system_cpu_percent{job="m10-system-guard"} > 95
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "M10 CPU 使用率严重过高"
          description: "CPU 使用率已达 {{ $value }}%，超过 95% 严重阈值"

      # 内存告警
      - alert: M10_Memory_High
        expr: system_memory_percent{job="m10-system-guard"} > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "M10 内存使用率过高"
          description: "内存使用率已达 {{ $value }}%"

      - alert: M10_Memory_Critical
        expr: system_memory_percent{job="m10-system-guard"} > 95
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "M10 内存使用率严重过高"
          description: "内存使用率已达 {{ $value }}%，可能导致系统不稳定"

      # 磁盘告警
      - alert: M10_Disk_High
        expr: system_disk_percent{job="m10-system-guard"} > 85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "M10 磁盘空间不足"
          description: "磁盘使用率已达 {{ $value }}%"

      # GPU 告警
      - alert: M10_GPU_Temperature_High
        expr: gpu_temperature_celsius{job="m10-system-guard"} > 85
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "M10 GPU 温度过高"
          description: "GPU {{ $labels.gpu_id }} 温度已达 {{ $value }}°C"

      - alert: M10_GPU_Temperature_Critical
        expr: gpu_temperature_celsius{job="m10-system-guard"} > 95
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "M10 GPU 温度严重过高"
          description: "GPU {{ $labels.gpu_id }} 温度已达 {{ $value }}°C，可能损坏硬件"

      - alert: M10_GPU_Memory_High
        expr: gpu_memory_percent{job="m10-system-guard"} > 90
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "M10 GPU 显存使用过高"
          description: "GPU {{ $labels.gpu_id }} 显存使用率已达 {{ $value }}%"

      # 防护引擎告警
      - alert: M10_Guard_CircuitBreaker_Open
        expr: guard_circuit_breaker_state{job="m10-system-guard"} == 2
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "M10 防护引擎熔断器已打开"
          description: "系统处于紧急防护状态，重型任务已暂停"

      - alert: M10_Guard_Active_Alerts
        expr: sum(guard_active_alerts{job="m10-system-guard", level=~"critical|emergency"}) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "M10 存在严重级别活跃告警"
          description: "当前有 {{ $value }} 条严重/紧急告警未处理"

      # Exporter 自身告警
      - alert: M10_Exporter_Down
        expr: exporter_up{job="m10-system-guard"} == 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "M10 Prometheus Exporter 未运行"
          description: "M10 指标导出器已停止运行"
```

---

## 架构说明

### 核心组件

```
┌─────────────────────────────────────────────────────────┐
│                    PrometheusExporter                    │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌───────────────────────────┐  │
│  │ MetricRegistry  │    │  采集调度器               │  │
│  │  (指标注册中心)  │    │  (定时采集 + 缓存)        │  │
│  └────────┬────────┘    └─────────────┬─────────────┘  │
│           │                          │                │
│           ▼                          ▼                │
│  ┌──────────────────────────────────────────────────┐  │
│  │             指标采集层 (Collectors)               │  │
│  ├──────────┬──────────┬───────┬─────────┬──────────┤  │
│  │  System  │   GPU    │ Tide  │  Guard  │ Process  │  │
│  │ Collector│ Collector│ Col.  │ Col.    │ Col.     │  │
│  └──────────┴──────────┴───────┴─────────┴──────────┘  │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │             M8MetricsReporter (可选)              │  │
│  │          (主动上报 + 失败重试)                     │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 设计特点

1. **注册中心模式**：所有指标通过 `MetricRegistry` 统一管理，支持动态注册
2. **可选依赖降级**：`prometheus_client` 不可用时自动降级为文本模拟模式
3. **定时采集缓存**：后台线程定时采集，HTTP 请求直接返回缓存结果
4. **线程安全**：所有状态变更通过锁保护，支持并发访问
5. **向后兼容**：保留旧版 API 函数，现有调用不受影响

### 数据流

1. 后台采集线程按配置间隔触发采集
2. 各 Collector 从对应模块（SystemMonitor、GuardEngine 等）获取数据
3. 数据更新到 MetricRegistry 的指标对象中
4. Prometheus Server 访问 `/api/v1/metrics` 拉取指标
5. （可选）M8MetricsReporter 将核心指标推送到 M8 监控中心

---

## 向后兼容性

### API 兼容性

保留了以下旧版函数，现有代码无需修改：

| 旧函数 | 新实现方式 | 说明 |
|--------|-----------|------|
| `generate_prometheus_metrics()` | `PrometheusExporter.generate_metrics_text()` | 完全兼容 |
| `generate_metrics_json()` | `PrometheusExporter.generate_metrics_json()` | 返回结构有扩展（新增字段） |
| `is_prometheus_available()` | 模块级变量 | 完全兼容 |

### 指标命名变更

旧版指标使用 `yunxi_` 前缀，新版使用分类前缀（`system_`, `gpu_` 等）。
如果需要兼容旧版指标名，可在 Prometheus 中使用 `metric_relabel_configs` 重命名，
或在 M10 侧注册兼容别名指标。

### 配置兼容性

- Prometheus 功能**默认启用**，不影响核心功能
- 所有新增配置项都有合理默认值
- 旧的 `yunxi_*` 指标相关代码已移除，但不影响系统运行

### 升级路径

1. 升级后 Prometheus 端点默认可用，无需额外配置
2. 如需使用旧版指标名，更新 Prometheus 配置或 Grafana 仪表盘
3. M8 主动上报功能默认关闭，按需启用
