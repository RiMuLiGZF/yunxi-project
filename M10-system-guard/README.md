# M10 系统卫士 (System Guard)

| 属性 | 值 |
|------|-----|
| **模块代号** | M10 |
| **模块名称** | 系统卫士 |
| **版本** | v1.1.0 |
| **端口** | 8010 |
| **技术栈** | FastAPI + psutil + NVML + SQLAlchemy + APScheduler |

---

## 一、模块定位

M10 系统卫士是**云汐系统基础设施守护模块**，提供以下核心能力：

- 系统资源监控（CPU / 内存 / 磁盘 / 网络 / GPU / 温度 / 电池）
- 进程管理与异常检测
- 阈值防护与自动降级
- 启动安全检查
- 审计日志与操作追踪
- 硬件保护报告生成
- 沙箱任务调度
- 潮汐引擎 GPU 智能调度

它像一个 7x24 小时值守的运维工程师，确保云汐系统全栈稳定高效运行。

---

## 二、目录结构

```
M10-system-guard/
├── server.py                  # FastAPI 服务启动入口
├── requirements.txt           # 运行时依赖
├── requirements-dev.txt       # 开发/测试依赖
├── .env.example               # 环境变量配置示例
├── README.md                  # 本文件
│
├── m10_system_guard/          # 核心代码包
│   ├── __init__.py
│   ├── config.py              # 配置管理（10 个子配置类）
│   ├── models.py              # 数据模型（指标 / 进程 / 防护 / 聚合）
│   ├── database.py            # SQLAlchemy 数据库连接与会话管理
│   ├── db_models.py           # ORM 模型（7 张表）
│   ├── errors.py              # 统一错误码与异常定义（M10xxx）
│   ├── system_monitor.py      # 系统资源监控（7 类指标 + 4 级聚合）
│   ├── process_manager.py     # 进程管理（全量快照 + 进程树）
│   ├── guard_engine.py        # 防护引擎（4 种策略 + 四级拦截）
│   ├── startup_check.py       # 启动安全检查
│   ├── audit_logger.py        # 审计日志（内存 + 数据库双写）
│   ├── report_generator.py    # 报告生成器（日报 / 周报）
│   ├── sandbox_scheduler.py   # 沙箱任务调度器（四级队列）
│   ├── auth_middleware.py     # API 认证中间件
│   │
│   ├── api/                   # API 路由层
│   │   ├── __init__.py        # 路由汇总注册
│   │   ├── status.py          # 系统状态接口
│   │   ├── process.py         # 进程管理接口
│   │   ├── guard.py           # 防护策略接口
│   │   ├── audit.py           # 审计日志接口
│   │   ├── report.py          # 报告生成接口
│   │   ├── startup_check.py   # 启动检查接口
│   │   └── tide.py            # 潮汐引擎接口
│   │
│   ├── repositories/          # 数据持久化层
│   │   ├── __init__.py
│   │   ├── metric_repository.py    # 系统指标持久化
│   │   ├── audit_repository.py     # 审计日志持久化
│   │   ├── alert_repository.py     # 告警记录持久化
│   │   └── policy_repository.py    # 防护策略持久化
│   │
│   └── tide_engine/           # 潮汐引擎子包
│       ├── __init__.py
│       ├── tide_engine.py     # 潮汐引擎主入口（单例）
│       ├── tide_scheduler.py  # 潮汐调度器
│       ├── tide_predictor.py  # 潮汐预测器
│       ├── tide_state.py      # 潮汐状态机
│       ├── gpu_orchestrator.py # GPU 编排器
│       └── models.py          # 潮汐模型定义
│
├── data/                      # 运行时数据
│   └── yunxi_m10.db           # SQLite 数据库文件
│
├── docs/                      # 文档
│   ├── CUDA_12.9_TENSORRT_UPGRADE_GUIDE.md
│   └── TIDE_ENGINE_GPU_SETUP_GUIDE.md
│
├── _legacy_backend/           # 旧版后端（归档）
│
└── tests/                     # 单元测试（7 个文件）
    ├── __init__.py
    ├── test_system_monitor.py
    ├── test_guard_engine.py
    ├── test_process_manager.py
    ├── test_sandbox_scheduler.py
    ├── test_startup_check.py
    ├── test_gpu_monitor.py
    └── test_tide_engine.py
```

---

## 三、快速开始

### 3.1 安装依赖

```bash
# 克隆项目
cd M10-system-guard

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate   # Linux/macOS
venv\Scripts\activate      # Windows

# 安装运行时依赖
pip install -r requirements.txt

# 安装开发依赖（测试）
pip install -r requirements-dev.txt
```

### 3.2 配置环境变量

```bash
# 复制配置模板
cp .env.example .env

# 编辑配置（按需修改）
vim .env
```

### 3.3 启动服务

```bash
# 标准启动
python server.py

# 验证服务
curl http://localhost:8010/health
```

### 3.4 访问文档

启动后访问以下地址：

- **Swagger UI**: http://localhost:8010/docs
- **OpenAPI JSON**: http://localhost:8010/openapi.json

---

## 四、核心能力（8 大能力）

| 序号 | 能力 | 说明 | 核心模块 |
|------|------|------|----------|
| 1 | **系统资源监控** | 7 类指标实时采集（CPU / 内存 / 磁盘 / 网络 / GPU / 温度 / 电池），支持四级聚合（原始 / 分钟 / 小时 / 天） | `system_monitor.py` |
| 2 | **进程管理** | 云汐各模块进程状态监控、全量快照、进程树分析、自动拉起异常进程 | `process_manager.py` |
| 3 | **阈值防护** | CPU / 内存 / 温度 / 磁盘四维防护，四级分级拦截策略（提示 / 警告 / 严重 / 紧急），自动降级 | `guard_engine.py` |
| 4 | **启动安全检查** | 系统启动时的健康预检，检测内存余量、CPU 负载、温度状态、重复进程，确保依赖就绪 | `startup_check.py` |
| 5 | **审计日志** | 全系统操作审计追踪，支持内存 + 数据库双写持久化，按时间 / 操作 / 模块查询 | `audit_logger.py` |
| 6 | **硬件保护报告** | 自动生成日报 / 周报，涵盖资源使用趋势、告警统计、GPU 状态、进程异常等 | `report_generator.py` |
| 7 | **沙箱任务调度** | 四级任务队列（轻量 / 普通 / 重型 / 超重型），基于当前系统负载智能调度任务执行 | `sandbox_scheduler.py` |
| 8 | **潮汐引擎 GPU 调度** | 基于 GPU 资源潮汐式变化的智能调度，四阶段自适应（涨潮 / 平潮 / 退潮 / 枯潮） | `tide_engine/` |

---

## 五、API 概览

### 5.1 服务信息

| 接口 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 服务基本信息与端点列表 |
| `/health` | GET | 标准健康检查 |

### 5.2 M8 标准对接接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查（需 X-M8-Token） |
| `/m8/metrics` | GET | M8 标准性能指标（需 X-M8-Token） |
| `/m8/config` | GET | M8 标准配置查询（需 X-M8-Token） |

### 5.3 业务接口（/api/v1/*）

| 接口组 | 前缀 | 说明 |
|--------|------|------|
| 系统状态 | `/api/v1/status` | 当前系统指标、历史数据、资源摘要 |
| 进程管理 | `/api/v1/process` | 进程列表、模块状态、启停操作 |
| 防护引擎 | `/api/v1/guard` | 防护等级、策略查询、告警历史 |
| 启动检查 | `/api/v1/startup-check` | 执行检查、检查报告 |
| 审计日志 | `/api/v1/audit` | 日志查询、详情查看、日志导出 |
| 报告生成 | `/api/v1/report` | 日报 / 周报生成、历史报告查询 |
| 潮汐引擎 | `/api/v1/tide` | 潮汐状态、GPU 调度、任务编排 |

> 完整接口文档请访问 http://localhost:8010/docs

---

## 六、环境变量配置

### 6.1 基础配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M10_HOST` | `0.0.0.0` | 服务监听地址 |
| `M10_PORT` | `8010` | 服务监听端口 |
| `M10_ENV` | `development` | 运行环境（development / production / test） |
| `M10_LOG_LEVEL` | `info` | 日志级别 |

### 6.2 采样与沙盒

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M10_SAMPLE_INTERVAL` | `5` | 采样间隔（秒） |
| `M10_SANDBOX_ENABLED` | `false` | 沙盒模式（true 使用模拟数据） |

### 6.3 认证

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M10_ADMIN_TOKEN` | `""` | 管理员 Token（M8 对接认证） |
| `M10_BASE_URL` | `http://localhost:8010` | 服务基础 URL |

### 6.4 阈值配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M10_CPU_WARNING` | `70` | CPU 警告阈值（%） |
| `M10_CPU_CRITICAL` | `90` | CPU 紧急阈值（%） |
| `M10_MEM_WARNING` | `75` | 内存警告阈值（%） |
| `M10_MEM_CRITICAL` | `90` | 内存紧急阈值（%） |
| `M10_DISK_WARNING` | `80` | 磁盘警告阈值（%） |
| `M10_DISK_CRITICAL` | `95` | 磁盘紧急阈值（%） |

### 6.5 审计配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M10_AUDIT_RETENTION` | `30` | 审计日志保留天数 |
| `M10_AUDIT_PATH` | `./data/audit` | 审计日志存储路径 |

### 6.6 GPU 监控配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M10_GPU_MONITOR_ENABLED` | `true` | 是否启用 GPU 监控（需要 NVIDIA 显卡） |
| `M10_GPU_POLLING_INTERVAL_MS` | `500` | GPU 轮询间隔（毫秒） |
| `M10_GPU_MONITOR_PROCESSES` | `true` | 是否监控 GPU 进程 |
| `M10_GPU_MEMORY_WARNING_PERCENT` | `80` | GPU 显存告警阈值（%） |
| `M10_GPU_TEMP_WARNING_CELSIUS` | `85` | GPU 温度告警阈值（摄氏度） |

### 6.7 潮汐引擎配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M10_TIDE_ENABLED` | `true` | 是否启用潮汐引擎 |
| `M10_TIDE_POLL_INTERVAL` | `2` | 潮汐调度轮询间隔（秒） |
| `M10_TIDE_PRIMARY_METRIC` | `gpu_memory` | 潮汐主指标（gpu_memory / gpu_util / combined） |
| `M10_TIDE_FLOOD_THRESHOLD` | `30` | 涨潮阈值（%），低于此值进入涨潮 |
| `M10_TIDE_EBB_THRESHOLD` | `70` | 退潮阈值（%），高于此值进入退潮 |
| `M10_TIDE_LOW_THRESHOLD` | `90` | 枯潮阈值（%），高于此值进入枯潮 |
| `M10_TIDE_HYSTERESIS` | `5` | 滞回区间（%），防止频繁切换阶段 |
| `M10_TIDE_MIN_PHASE_DURATION` | `120` | 阶段最小持续时间（秒） |
| `M10_TIDE_PREDICTION_ENABLED` | `true` | 是否启用潮汐预测 |
| `M10_TIDE_PREDICTION_WINDOW` | `30` | 预测窗口（分钟） |

### 6.8 数据库

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M10_DB_PATH` | `./data/yunxi_m10.db` | SQLite 数据库文件路径 |

---

## 七、防护等级说明

防护引擎采用四级分级拦截策略，基于 CPU、内存、温度、磁盘四维指标综合判定：

| 等级 | 状态 | 触发条件 | 自动动作 |
|------|------|----------|----------|
| **NORMAL** | 绿色 | 所有指标均在安全范围内 | 正常运行，标准采样 |
| **WATCH** | 黄色 | 任一指标超过关注阈值 | 记录日志，增加采样频率，发出提示 |
| **WARNING** | 橙色 | 多指标同时超过警告阈值，或单指标持续超限 | 发送告警，限制重型任务入队，准备降级 |
| **CRITICAL** | 红色 | 关键指标超过紧急阈值 | 自动降级，暂停非核心服务，限制并发 |

### 阈值参考（默认值）

| 指标 | WATCH | WARNING | CRITICAL |
|------|-------|---------|----------|
| CPU 使用率 | > 60% | > 75% | > 95% |
| 内存使用率 | > 65% | > 80% | > 95% |
| 温度 | > 60 C | > 70 C | > 90 C |
| 磁盘使用率 | > 70% | > 85% | > 98% |

---

## 八、潮汐引擎说明

潮汐引擎是 M10 的 GPU 智能调度子系统，基于 GPU 资源的潮汐式变化特征，实现自适应任务调度。

### 8.1 设计理念

GPU 资源使用率呈现类似海洋潮汐的周期性波动：白天训练任务集中时资源紧张（退潮/枯潮），夜间空闲时资源充裕（涨潮）。潮汐引擎通过实时监测 GPU 状态，自动调整任务并发度。

### 8.2 四个阶段

| 阶段 | 含义 | GPU 负载 | 并发系数 | 调度策略 |
|------|------|----------|----------|----------|
| **涨潮 (FLOOD)** | 资源充裕 | < 30% | 2.0x | 满负荷调度，最大化利用 GPU |
| **平潮 (SLACK)** | 资源适中 | 30% - 70% | 1.0x | 标准调度，维持当前并发 |
| **退潮 (EBB)** | 资源紧张 | 70% - 90% | 0.5x | 降并发调度，排队等待 |
| **枯潮 (LOW)** | 资源枯竭 | > 90% | 0.2x | 最低限度调度，仅允许高优先级任务 |

### 8.3 核心组件

| 组件 | 说明 |
|------|------|
| `TideEngine` | 引擎主入口，整合所有组件的单例 |
| `TideScheduler` | 潮汐调度器，周期性检测资源并切换阶段 |
| `TidePredictor` | 潮汐预测器，基于历史数据预测未来资源趋势 |
| `TideState` | 潮汐状态机，管理阶段转换与滞回逻辑 |
| `GPUOrchestrator` | GPU 编排器，执行具体的任务分配与调度 |

### 8.4 与 M10 其他模块的联动

```
SystemMonitor ──(实时数据)──> TideEngine
                                 │
GuardEngine  <──(联动)────── TideEngine
                                 │
SandboxScheduler <──(调度)──── TideEngine
```

- 从 **SystemMonitor** 获取实时 GPU / 系统资源数据
- 与 **GuardEngine** 的防护策略联动，在紧急状态强制降级
- 为 **SandboxScheduler** 提供 GPU 任务调度能力

---

## 九、数据库设计

使用 SQLAlchemy ORM，默认 SQLite 存储，支持 7 张核心表：

| 表名 | 说明 |
|------|------|
| `audit_logs` | 审计日志 |
| `guard_alerts` | 防护告警记录 |
| `metric_history` | 系统指标历史（原始 / 分钟聚合） |
| `guard_policies` | 防护策略配置 |
| `startup_checks` | 启动检查记录 |
| `reports` | 报告记录 |
| `tide_missions` | 潮汐任务记录 |

数据库路径可通过 `M10_DB_PATH` 环境变量配置，默认位于 `./data/yunxi_m10.db`。

---

## 十、测试

```bash
# 运行全部测试
pytest tests/ -v

# 运行单个模块测试
pytest tests/test_system_monitor.py -v
pytest tests/test_guard_engine.py -v
pytest tests/test_tide_engine.py -v
```

---

## 十一、与其他模块关系

```
                    ┌─────────────┐
                    │   M8 管理台  │
                    └──────┬──────┘
                           │ 纳管 / 监控
                    ┌──────▼──────┐
                    │ M10 系统卫士 │
                    └──────┬──────┘
         ┌─────────────────┼─────────────────┐
    ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
    │ M1-M9  │       │  操作系统  │       │  SQLite  │
    │ 各模块  │       │(资源/进程)│       │  审计日志 │
    └─────────┘       └─────────┘       └─────────┘
```

- **上游**：M8 管理台通过 M8 标准接口（`/m8/*`）调用 M10 获取系统状态
- **下游**：M10 监控 M1-M9 所有模块的进程和资源使用情况
- **存储**：审计日志、指标历史、告警记录等持久化到 SQLite 数据库

---

## 十二、注意事项

1. **沙盒模式**：默认关闭（`M10_SANDBOX_ENABLED=false`），采集真实系统数据。开启后使用模拟数据生成器，不调用真实系统 API，适合开发和测试环境。

2. **GPU 监控依赖**：真实 GPU 监控需要安装 `nvidia-ml-py` 库和 NVIDIA 驱动。未安装时自动回退到模拟数据。

3. **数据库初始化**：首次启动时自动创建 SQLite 数据库文件和表结构，无需手动迁移。

4. **认证中间件**：所有 `/api/v1/*` 接口默认受认证中间件保护，M8 接口使用 `X-M8-Token` 请求头认证。

5. **指标持久化**：系统监控指标支持数据库持久化，需通过 `enable_db_persistence()` 方法显式启用。

6. **潮汐引擎**：默认启用，会持续监测 GPU 资源状态。在无 GPU 设备的环境中自动降级为监控模式。

7. **数据聚合**：系统指标支持四级聚合——原始数据（秒级）、分钟聚合、小时聚合、天聚合，各级保留时长可在配置中调整。

8. **CORS 配置**：默认允许所有来源（`*`），生产环境建议通过 `CORS_ORIGINS` 环境变量限制。

---

## 十三、版本历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.1.0 | 2026-07 | 新增潮汐引擎 GPU 智能调度；新增数据库持久化层（SQLAlchemy）；新增统一错误码体系；新增 repositories 数据访问层；新增 db_models ORM 模型；新增 errors.py 异常定义 |
| v1.0.0 | 2026-06 | 初始版本：系统监控、进程管理、防护引擎、启动检查、审计日志、报告生成、沙箱调度 |
